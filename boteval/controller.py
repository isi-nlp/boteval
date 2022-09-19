import os
import functools
from typing import List

import flask
from flask import request, url_for
import flask_login as FL
import flask_socketio as FS

from boteval.service import ChatService
#from flask_login import login_user, current_user, login_required, login_url

from . import log
from .model import ChatMessage, ChatThread, ChatTopic, User

ENV = {}
for env_key in ['GTAG']:
    ENV[env_key] = os.environ.get(env_key)


ERROR = 'error'
SUCCESS = 'success'


def render_template(*args, **kwargs):
    return flask.render_template(*args, environ=ENV, cur_user=FL.current_user, **kwargs)


def wrap(body=None, status=SUCCESS, description=None):
    return dict(
        head=dict(status=status, description=description),
        body=body)


def login_required_socket(f):
    """
    This decorator has similar functionality as Flask-Login's login_required
    but meant to be decorated for socketIO methods
    """
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not FL.current_user.is_authenticated:
            FS.disconnect()
        else:
            return f(*args, **kwargs)
    return wrapped


def user_controllers(router, socket, service: ChatService, login_manager):

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.get(user_id)

    @login_manager.unauthorized_handler
    def unauthorized_handler():
        flask.flash('Login required')
        return flask.redirect(url_for('app.login'))


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

    @router.route('/logout', methods=['GET'])
    @FL.login_required
    def logout():
        FL.logout_user()
        flask.flash('Logout Success')
        return flask.redirect(flask.url_for('app.login'))

    @router.route('/', methods=['GET'])
    @FL.login_required
    def index():
        topics: List[ChatTopic] = service.get_topics()
        threads: List[ChatThread] = service.get_user_threads(user=FL.current_user)
        topics = {topic.id: [topic, None] for topic in topics}
        limits = dict(max_threads_per_user = service.limits.get('max_threads_per_user'),
                    max_threads_per_topic = service.limits.get('max_threads_per_topic'),
                    threds_launched=len(threads),
                    threads_completed=(sum(th.episode_done for th in threads))
        )

        for thread in threads:
            topics[thread.topic_id][1] = thread
        topics = topics.values()
        return render_template('user/index.html', data=dict(topics=topics), limits=limits)


    @router.route('/launch-topic/<topic_id>', methods=['GET'])
    @FL.login_required
    def launch_topic(topic_id):
        topic = service.get_topic(topic_id=topic_id)
        if not topic:
            return f'Topic {topic} not found', 400
        thread = service.get_thread_for_topic(user=FL.current_user, topic=topic, create_if_missing=True)
        return flask.redirect(url_for('app.get_thread', thread_id=thread.id))


    @router.route('/thread/<thread_id>', methods=['GET'])
    @FL.login_required
    def get_thread(thread_id):
        thread = service.get_thread(thread_id)
        if not thread:
            return f'Thread {thread_id} found', 400
        ratings = service.get_rating_questions()
        topic = service.get_topic(thread.topic_id)
        return render_template('user/chatui.html', limits=service.limits,
                               thread=thread,
                               topic=topic,
                               rating_questions=ratings,
                               data=dict())


    ####### Sockets and stuff
    @socket.on('connect')
    def connect_handler():
        if FL.current_user.is_authenticated:
            log.info(f'{FL.current_user.id} has joined')
        else:
            return False  # not allowed here


    @socket.on('new_message')
    @login_required_socket
    def handle_new_message(msg, methods=['GET', 'POST']):
        log.info('received new_message: ' + str(msg))

        text = msg.get('text', '').strip()
        thread_id = msg.get('thread_id')
        user_id = msg.get('user_id')
        user = FL.current_user
        if not thread_id or not user_id:
            return wrap(status=ERROR, description='both thread_id and user_id are required')
        if user.id != user_id:
            return wrap(status=ERROR, description='user_id mismatch with login user. Try logout and login')
        if not text:
            return wrap(status=ERROR, description='text is empty or null')

        thread = service.get_thread(thread_id=thread_id)
        if not thread:
            return wrap(status=ERROR, description=f'thread_id {thread_id} is invalid')
        if user not in thread.users:
            return wrap(status=ERROR, description=f'User {user.id} is not part of threadd {thread.id}. Wrong thread!')

        msg = ChatMessage(text=text, user_id=user.id, thread_id=thread.id)
        reply, episode_done = service.new_message(msg, thread)
        reply_dict = {
            'id': reply.id,
            'text': reply.text,
            'time': str(reply.time),
            'user_id': reply.user_id,
            'thread_id': reply.thread_id,
            'episode_done': episode_done
        }
        return wrap(body=reply_dict)

