import os

import flask
from flask import request, url_for
import flask_login as FL
#from flask_login import login_user, current_user, login_required, login_url

from . import log
from .model import User

ENV = {}
for env_key in ['GTAG']:
    ENV[env_key] = os.environ.get(env_key)


ERROR = 'error'
SUCCESS = 'success'


def render_template(*args, **kwargs):
    return flask.render_template(*args, environ=ENV, user=FL.current_user, **kwargs)


def wrap(body=None, status=SUCCESS, description=None):
    return dict(
        head=dict(status=status, description=description),
        body=body)


def user_controllers(router, socket, chat_service, login_manager):

    service = chat_service

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.get(user_id)

    @router.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'GET':
            return render_template('login.html', action=request.values.get('action', 'login'))

        # form sumission as POST
        log.info(f'Form:: {request.form}')
        user_id = request.form.get('user_id')
        secret = request.form.get('secret')
        action = request.form.get('action', 'login')
        assert action in ('login', 'signup')
        if action == 'login':
            user = User.get(user_id)
            if user and user.verify_secret(secret):
                FL.login_user(user, remember=True, force=True)
                flask.flash('Logged in successfully.')
                return flask.redirect(flask.url_for('app.index'))
            else:
                flask.flash('login failed')
                if not user:
                    flask.flash('Login Hint: User not found')
                else:
                    flask.flash('Login Hint: password is invalid')
        elif action == 'signup':
            user = User.get(user_id)
            if user:
                flask.flash(f'User {user.id} already exists. Try login instead')
            elif len(user_id) < 2 or len(user_id) > 16 or not user_id.isalnum():
                flask.flash('Invalid User ID. ID should be at least 2 chars and atmost 16 chars and only alpha numeric chars are permitted')
            elif len(secret) < 4:
                flask.flash('Password should be atleast 4 chars long')
            name = request.form.get('name')
            user = User.create_new(user_id, secret, name=name)
            flask.flash(f'Sign up success.Try login with your user ID: {user.id}')
            return render_template('login.html', form=dict(user=user, action='login'))
        else:
            flask.flash('Wrong action. only login and signup are supported')
            action = 'login'
        return render_template('login.html', form=dict(user_id=user_id, action=action))

    @router.route('/logout')
    @FL.login_required
    def logout():
        FL.logout_user()
        flask.flash('Logout Success')
        return flask.redirect(flask.url_for('app.login'))

    @router.route('/')
    def index():
        return render_template('user/chatui.html', data={})


    @router.route('/test-login')
    @FL.login_required
    def test_login():
        user = FL.current_user
        return f'Login Success: User: {user} {user.id}'

    @socket.on('my event')
    def handle_my_custom_event(json, methods=['GET', 'POST']):
        log.info('received my event: ' + str(json))
        socket.emit('my response', json)

    @socket.on('new_message')
    def handle_new_message(msg, methods=['GET', 'POST']):
        log.info('received new_message: ' + str(msg))
        msg["text"] = 'server reply to ' + msg['text']
        thread_id = msg.get('thread_id')
        user_id = msg.get('user_id')
        if not thread_id or not user_id :
            return wrap(status=ERROR, description='both thread_id and user_id are required')

        chatroom = service.make_or_get_chatroom(user_id, thread_id)
        reply = chatroom.get_reply(msg)
        return wrap(body=reply)

