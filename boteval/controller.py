import os
import functools
from typing import List
import random
from datetime import datetime

import flask
from flask import request, url_for
import flask_login as FL
import flask_socketio as FS

from boteval.service import ChatService
#from flask_login import login_user, current_user, login_required, login_url

from . import log, C, db
from .utils import jsonify
from .model import ChatMessage, ChatThread, ChatTopic, User

ENV = {}
for env_key in ['GTAG']:
    ENV[env_key] = os.environ.get(env_key)


def render_template(*args, **kwargs):
    return flask.render_template(*args, environ=ENV,
        cur_user=FL.current_user,
        C=C, **kwargs)


def wrap(body=None, status=C.SUCCESS, description=None):
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



class AdminLoginDecorator:

    """
    Similar to flask-login's `login_required` but checks for role=admin on user
    This is a stateful decorator (hence class instead of function)
    """
    def __init__(self, login_manager=None) -> None:
        self.login_manager = login_manager

    def __call__(self, func):

        @functools.wraps(func)
        def decorated_view(*args, **kwargs):
            if not FL.current_user.is_authenticated:
                return self.login_manager.unauthorized()
            elif FL.current_user.role != User.ROLE_ADMIN:
                flask.flash('This functionality is for admin only')
                return 'ERROR: Access denied. This resource can only be accessed by admin user.', 403
            else: # user is logged in and they have role=admin;
                return func(*args, **kwargs)

        return decorated_view

admin_login_required = None


def init_login_manager(login_manager):

    global admin_login_required
    admin_login_required =  AdminLoginDecorator(login_manager=login_manager)

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.get(user_id)

    @login_manager.unauthorized_handler
    def unauthorized_handler():
        flask.flash(f'Login required for accessing the requested resource.')
        return flask.redirect(url_for('app.login', next=request.full_path, action='login'))


def is_safe_url(url):
    # TODO: validate url
    return True

def register_app_hooks(app):

    @app.before_request
    def update_last_active():
        user:User = FL.current_user
        if user and user.is_active:
            if not user.last_active or\
                (datetime.now() - user.last_active).total_seconds() > C.USER_ACTIVE_UPDATE_FREQ:
                user.last_active = datetime.now()
                db.session.merge(user)  # update
                db.session.commit()


def user_controllers(router, socket, service: ChatService):

    @router.route('/login', methods=['GET', 'POST'])
    def login():
        next_url = request.values.get('next')
        tmpl_args = dict(
            action=request.values.get('action', 'login'),
            next=next_url,
            ext_id=request.values.get('ext_id'),
            ext_src=request.values.get('ext_src'),
            onboarding=service.onboarding)
        log.info(f"login/signup. next={next}")
        if request.method == 'GET':
            return render_template('login.html', **tmpl_args)

        # form sumission as POST
        log.info(f'Form:: {request.form}')
        args = dict(request.form)
        user_id = args.pop('user_id')
        secret = args.pop('secret')
        action = args.pop('action', 'login')
        assert action in ('login', 'signup')
        if action == 'login':
            user = User.get(user_id)
            if user and user.verify_secret(secret):
                FL.login_user(user, remember=True, force=True)
                flask.flash('Logged in successfully.')
                if next_url and is_safe_url(next_url):
                    return flask.redirect(next_url)
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
                flask.flash(f'User {user.id} already exists. Try login instead.')
            elif len(user_id) < 2 or len(user_id) > 16 or not user_id.isalnum():
                flask.flash('Invalid User ID. ID should be at least 2 chars and atmost 16 chars and only alpha numeric chars are permitted')
            elif len(secret) < 4:
                flask.flash('Password should be atleast 4 chars long')
            else:
                name = args.pop('name')
                user = User.create_new(user_id, secret, name=name, data=args)
                tmpl_args['action'] = 'login'
                flask.flash(f'Sign up success. Try login with your user ID: {user.id}. Verify that it works and write down the password for future logins.')
                return render_template('login.html', **tmpl_args)
        else:
            flask.flash('Wrong action. only login and signup are supported')
            tmpl_args['action'] = 'login'
        return render_template('login.html', user_id=user_id, **tmpl_args)


    @router.route('/logout', methods=['GET'])
    @FL.login_required
    def logout():
        FL.logout_user()
        flask.flash('Logout Success')
        return flask.redirect(flask.url_for('app.login'))

    @router.route('/about', methods=['GET'])
    def about():
        return render_template('about.html')

    @router.route('/', methods=['GET'])
    @FL.login_required
    def index():
        topics: List[ChatTopic] = service.get_topics()
        threads: List[ChatThread] = service.get_user_threads(user=FL.current_user)
        data = {topic.id: [topic, None, 0] for topic in topics}

        limits = dict(threads_launched=len(threads),
                      threads_completed=sum(th.episode_done for th in threads))
        limits.update(service.limits)
        max_threads_per_topic = limits['max_threads_per_topic']
        thread_counts = service.get_thread_counts(episode_done=True) # completed threads
        for thread in threads:
            data[thread.topic_id][1] = thread
            print(thread, thread.episode_done)

        for topic_id, n_threads in thread_counts.items():
            data[topic_id][2] = n_threads
        data = list(data.values())
        random.shuffle(data)  # randomize
        # Ranks:  threads t threads that need anotation in the top
        def sort_key(rec):
            _, my_thread, n_threads = rec
            if my_thread:
                if not my_thread.episode_done: # Rank 1 incomplete threads,
                    return -1
                else: # completed thread
                    return max_threads_per_topic  # done, push it to the end
            else:
                return n_threads

        data = list(sorted(data, key=sort_key))
        return render_template('user/index.html', data=data, limits=limits)


    @router.route('/launch-topic/<topic_id>', methods=['GET'])
    @FL.login_required
    def launch_topic(topic_id):
        if FL.current_user.role == User.ROLE_ADMIN:
            return 'Wait, Admin! Create or use normal user a/c to chat.', 400
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
            return f'Thread {thread_id} found', 404
        ratings = service.get_rating_questions()
        topic = service.get_topic(thread.topic_id)
        return render_template('user/chatui.html', limits=service.limits,
                               thread=thread,
                               topic=topic,
                               rating_questions=ratings,
                               data=dict())

    @router.route('/thread/<thread_id>/rating', methods=['POST'])
    @FL.login_required
    def thread_rating(thread_id):
        thread = service.get_thread(thread_id)
        if not thread:
            return f'Thread {thread_id} found', 404
        log.info(f'updating ratings for {thread.id}')
        ratings = {key: val for key, val in request.form.items()}
        service.update_thread_ratings(thread, ratings=ratings)
        flask.flash('Great job! You have completed a thread!')
        return flask.redirect(url_for('app.index'))


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
            return wrap(status=C.ERROR, description='both thread_id and user_id are required')
        if user.id != user_id:
            return wrap(status=C.ERROR, description='user_id mismatch with login user. Try logout and login')
        if not text:
            return wrap(status=C.ERROR, description='text is empty or null')

        thread = service.get_thread(thread_id=thread_id)
        if not thread:
            return wrap(status=C.ERROR, description=f'thread_id {thread_id} is invalid')
        if user not in thread.users:
            return wrap(status=C.ERROR, description=f'User {user.id} is not part of threadd {thread.id}. Wrong thread!')

        msg = ChatMessage(text=text, user_id=user.id, thread_id=thread.id)
        try:
            reply, episode_done = service.new_message(msg, thread)
            reply_dict = {
                'id': reply.id,
                'text': reply.text,
                'time': (reply.time or datetime.now()).isoformat(),
                'user_id': reply.user_id,
                'thread_id': reply.thread_id,
                'episode_done': episode_done
            }
            return wrap(body=reply_dict)
        except Exception as e:
            log.exception(e)
            return wrap(status=C.ERROR, description='Something went wrong on server side')

    #### M Turk Integration
    @router.route('/launch-topic-mturk/<topic_id>', methods=['GET'])
    def launch_topic_mturk( topic_id):

        assignmet_id = request.values.get('assignmentId')
        hit_id = request.values.get('hitId')
        worker_id = request.values.get('workerId')
        sumit_url = request.values.get('turkSubmitTo') 
        is_previewing = assignmet_id == 'ASSIGNMENT_ID_NOT_AVAILABLE'
        #Our mapping: Worker=User; Assignment = ChatThread; HIT=ChatTopic
        # Step 1: map Hit to Topic, so we can perview it
        topic = ChatTopic.query.find_by(ext_src=C.MTURK, ext_id=hit_id).first()
        if not topic:
            return 'Invalid HIT or task', 400

        if is_previewing: 
            return index() # sending index page for now. We can do better later

        # Step2. Find the mapping user
        user = User.query.filter_by(ext_src=C.MTURK, ext_id=worker_id).first()
        if not user:
            # sign up and come back (so set next)
            return flask.redirect(url_for('app.login', action='signup', ext_id=worker_id, ext_src=C.MTURK, next=request.url))
        elif not FL.current_user or FL.current_user.get_id() != user.id:
                flask.flash(f'You have an a/c with UserID={user.id} but not logged in. Please relogin as {user.id}.')
                return flask.redirect(url_for('app.login', action='login', next=request.url))

        # user exist, logged in => means user already signed up and doing so, gave consent,     
        # Step 3: map assignment to chat thread -- 
        data = {
            C.MTURK: {
            'sumit_url': submit_url,
            'is_sandbox': 'workersandbox' in submit_url,
            'assignment_id': assignmet_id,
            'hit_id': hit_id,
            'worker_id': worker_id
        }}
        chat_thread = service.get_thread_for_topic(user=FL.current_user, topic=topic, create_if_missing=True,
            ext_id=ext_id, ext_src=C.MTURK, data=data)

        assert chat_thread
        return get_thread(thread_id=chat_thread)


def admin_controllers(router, service: ChatService):
    from .model import User, ChatMessage, ChatThread, ChatTopic

    @router.route('/')
    @admin_login_required
    def index():
        counts = dict(
            user=User.query.count(),
            thread=ChatThread.query.count(),
            topic=ChatTopic.query.count(),
            message=ChatMessage.query.count(),
            )
        return render_template('admin/index.html', counts=counts)

    @router.route('/thread/<thread_id>/export')
    @admin_login_required
    def thread_export(thread_id):
        thread: ChatThread = ChatThread.query.get(thread_id)
        if not thread:
            return 'Thread not found', 404
        return jsonify(thread), 200

    @router.route('/user/')
    @admin_login_required
    def get_users():
        users = User.query.order_by(User.last_active.desc()).limit(C.MAX_PAGE_SIZE).all()
        return render_template('admin/users.html', users=users)

    @router.route('/thread/')
    @admin_login_required
    def get_threads():
        threads = ChatThread.query.order_by(ChatThread.time_updated.desc(), ChatThread.time_created.desc()).limit(C.MAX_PAGE_SIZE).all()
        return render_template('admin/threads.html', threads=threads)

    @router.route('/topic/')
    @admin_login_required
    def get_topics():
        topics = ChatTopic.query.order_by(ChatTopic.time_updated.desc(), ChatTopic.time_created.desc()).limit(C.MAX_PAGE_SIZE).all()
        return render_template('admin/topics.html', topics=topics)

    @router.route(f'/topic/<topic_id>/launch/<crowd_name>')
    @admin_login_required
    def launch_topic_on_crowd(topic_id, crowd_name):
        topic = ChatTopic.query.get(topic_id)
        if not topic:
            return f'Topic {topic_id} not found', 404
        if not service.crowd_service or service.crowd_service.name != crowd_name:
            return f'Crowd backend {crowd_name} is not configured', 400

        if topic.ext_id:
            return f'Topic {topic_id} already has been launched on {topic.ext_src}'
        ext_id = service.launch_topic_on_crowd(topic)
        if ext_id:
            flask.flash(f'Successfully launched {topic_id} on {crowd_name} as {ext_id}')
            return dict(staus='success', ext_id=ext_id), 200
        else:
            return 'Error: we couldnt launch on crowd', 400