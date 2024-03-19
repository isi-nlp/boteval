
import functools
from typing import List, Tuple
import random
from datetime import datetime
from threading import Thread
import json

import flask
from flask import request, url_for, redirect, Response
import flask_login as FL

from boteval.service import ChatService


from . import log, C, db
from .utils import jsonify, render_template, register_template_filters
from .model import ChatMessage, ChatThread, ChatTopic, User, SuperTopic
from .mturk import MTurkController


def wrap(body=None, status=C.SUCCESS, description=None):
    return dict(
        head=dict(status=status, description=description),
        body=body)



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

def register_app_hooks(app, service: ChatService):

    @app.before_request
    def update_last_active():
        user:User = FL.current_user
        if user and user.is_active:
            if not user.last_active or\
                (datetime.now() - user.last_active).total_seconds() > C.USER_ACTIVE_UPDATE_FREQ:
                user.last_active = datetime.now()
                db.session.merge(user)  # update
                db.session.commit()
    
    @app.before_first_request
    def before_first_request():
        log.info('Before first request')
        ping_url = flask.url_for('app.ping', _external=True, _scheme='https')
        Thread(target=service.check_ext_url, args=(ping_url,)).start()


def user_controllers(router, service: ChatService):

    @router.route('/ping', methods=['GET', 'POST'])
    def ping():
        return jsonify(dict(reply='pong', time=datetime.now().timestamp())), 200

    @router.route('/login', methods=['GET', 'POST'])
    def login():
        next_url = request.values.get('next')
        ext_id = request.values.get('ext_id')
        ext_src = request.values.get('ext_src')

        # for seamless login, we still have to show terms and conditions,
        tmpl_args = dict(
            action=request.values.get('action', 'login'),
            next=next_url,
            ext_id=ext_id,
            ext_src=ext_src,
            onboarding=service.onboarding)
        log.info(f"login/signup. next={next_url} | ext: src: {ext_src}  id: {ext_id}")
        if request.method == 'GET':
            return render_template('login.html', **tmpl_args)

        # form sumission as POST
        args = dict(request.form)
        user_id = args.pop('user_id')
        secret = args.pop('secret')
        log.info(f'Form:: {user_id} {args}')
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
                    flask.flash('Login Hint: no user found with the given user ID')
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
                name = args.pop('name', None)
                ext_id = args.pop('ext_id', None)
                ext_src = args.pop('ext_src', None)
                user = User.create_new(user_id, secret, name=name, ext_id=ext_id, ext_src=ext_src, data=args)
                tmpl_args['action'] = 'login'
                flask.flash(f'Sign up success. Try login with your user ID: {user.id}. Verify that it works and write down the password for future logins.')
                return render_template('login.html', **tmpl_args)
        else:
            flask.flash('Wrong action. only login and signup are supported')
            tmpl_args['action'] = 'login'
        return render_template('login.html', user_id=user_id, **tmpl_args)


    @router.route('/seamlesslogin', methods=['GET', 'POST'])
    def seamlesslogin():
        next_url = request.values.get('next')
        ext_id = request.values.get('ext_id')
        ext_src = request.values.get('ext_src')

        if not ext_id or not ext_src:
            log.warning(f'seamless login requires both {ext_id=} and {ext_src=}')
            # return to normal login
            return login()

        # for seamless login, we still have to show terms and conditions,
        tmpl_args = dict(
            next=next_url,
            ext_id=ext_id,
            ext_src=ext_src,
            onboarding=service.onboarding)
        log.info(f"login/signup. next={next_url} | ext: src: {ext_src}  id: {ext_id}")
        if request.method == 'GET': # for GET, show terms,
            return render_template('seamlesslogin.html', **tmpl_args)

        # form sumission as POST => create a/c
        args = dict(request.form)
        user_id = args.pop('user_id')
        secret = args.pop('secret')
        user = User.get(user_id)
        log.info(f'Form:: {user_id} {args}')
        if user:# user already exists
            log.warning(f'User {user_id} already exists')
        else:
            name = args.pop('name', None)
            user = User.create_new(user_id, secret, name=name, ext_id=ext_id, ext_src=ext_src, data=args)

        FL.login_user(user, remember=True, force=True)
        log.info('Logged in automatically')
        if next_url and is_safe_url(next_url):
            return flask.redirect(next_url)
        return flask.redirect(flask.url_for('app.index'))


    @router.route('/logout', methods=['GET'])
    @FL.login_required
    def logout():
        FL.logout_user()
        flask.flash('Logout Success')
        return flask.redirect(flask.url_for('app.login'))

    @router.route('/about', methods=['GET'])
    def about():
        return render_template('about.html')
    
    @router.route('/instructions', methods=['GET'])
    def instructions(focus_mode=False):
        return render_template('page.html', content=service.instructions, focus_mode=focus_mode)


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
            if ChatTopic.query.get(thread.topic_id) is None:
                continue
            data[thread.topic_id][1] = thread

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
        user = FL.current_user
        if user.is_admin:
            return 'Wait, Admin! Create or use normal user a/c to chat.', 400
        topic = service.get_topic(topic_id=topic_id)
        if not topic:
            return f'Topic {topic} not found', 400
        if user.ext_id:  # create thread via crowd-source interface, or we dont know how to pay back to them
            return f'Error: Wait! You should launch a new task via {user.ext_src} interface to receive payments.', 400

        limit_exceeded, msg = service.limit_check(topic=topic, user=user)
        if limit_exceeded:
            return msg, 400

        thread = service.get_thread_for_topic(user=FL.current_user, topic=topic, create_if_missing=True)
        if thread is None:
            err_msg = 'Another user is loading this chat topic. Please retry after 10 seconds!'
            log.error(err_msg)
            return err_msg, 400

        return flask.redirect(url_for('app.get_thread', thread_id=thread.id))

    @router.route('/thread/<thread_id>', methods=['GET'])
    @FL.login_required
    def get_thread(thread_id, request_worker_id=None, focus_mode=False):
        """
        Go to the thread with the given thread id and user id (current login user).
        """
        focus_mode = focus_mode or request.values.get('focus_mode')
        thread: ChatThread = service.get_thread(thread_id)
        if not thread:
            return f'Thread {thread_id}  NOT found', 404
        ratings = service.get_rating_questions()
        topic: ChatTopic = service.get_topic(thread.topic_id)
        max_turns = thread.max_turns_per_thread
        if topic is None:
            # If topic has been deleted, it's still fine.
            # The required data for rendering is also copied in the thread obj
            topic = thread
            remaining_turns = 0
        else:
            remaining_turns = max_turns - thread.count_turns(FL.current_user)

        dialog_man = service.get_dialog_man(thread)  # this will init the thread
        log.info(f'data:!!!: {thread.data}')

        req_worker_is_human_mod = False
        instructions_for_user = service.instructions
        if topic.human_moderator == 'yes' and request_worker_id is not None and request_worker_id != '':
            req_worker_is_human_mod = service.crowd_service.is_worker_qualified(user_worker_id=request_worker_id,
                                                                                qual_name='human_moderator_qualification')

        if req_worker_is_human_mod:
            instructions_for_user = service.human_mod_instructions
            # add one more turn for human mod: 
            remaining_turns = remaining_turns + 1
            log.info('Human moderator instructions should be used for user:', request_worker_id)

        if thread.max_human_users_per_thread == 1:
            return render_template('user/chatui.html', limits=service.limits,
                                   thread_json=json.dumps(thread.as_dict(), ensure_ascii=False),
                                   thread=thread,
                                   topic=topic,
                                   socket_name=thread.socket_name,
                                   rating_questions=ratings,
                                   focus_mode=focus_mode,
                                   remaining_turns=remaining_turns,
                                   instructions_html=service.instructions,
                                   simple_instructions_html=service.simple_instructions,
                                   show_text_extra=FL.current_user.is_admin,
                                   data=dict())
        elif thread.max_human_users_per_thread == 2:
            return render_template('user/chatui_two_users.html', limits=service.limits,
                                   thread_json=json.dumps(thread.as_dict(), ensure_ascii=False),
                                   thread=thread,
                                   topic=topic,
                                   socket_name=thread.socket_name,
                                   rating_questions=ratings,
                                   focus_mode=focus_mode,
                                   remaining_turns=remaining_turns,
                                   instructions_html=instructions_for_user,
                                   simple_instructions_html=service.simple_instructions,
                                   show_text_extra=FL.current_user.is_admin,
                                   bot_name=C.Auth.BOT_USER,
                                   data=dict())

    @router.route('/thread/<thread_id>/<user_id>/message', methods=['POST'])
    #@FL.login_required  <-- login didnt work in iframe in mturk
    def post_new_message(thread_id, user_id):
        thread = service.get_thread(thread_id)
        if not thread:
            return f'Thread {thread_id}  NOT found', 404
        #user = FL.current_user
        user = User.get(user_id)
        if not user  or user not in thread.users:
            log.warning('user is not part of thread')
            reply = dict(status=C.ERROR,
                         description=f'User {user.id} is not part of thread {thread.id}. Wrong thread!')
            return flask.jsonify(reply), 400
        text = request.form.get('text', None)
        speaker_id = request.form.get('speaker_id', None)
        if not text or not isinstance(text, str):
            reply = dict(status=C.ERROR,
                         description=f'requires "text" field of type string')
            return flask.jsonify(reply), 400
        
        text = text[:C.MAX_TEXT_LENGTH]
        msg = ChatMessage(text=text, user_id=user.id, thread_id=thread.id, data={"speaker_id": speaker_id})
        try:
            reply, episode_done = service.new_message(msg, thread)
            reply_dict = reply.as_dict() | dict(episode_done=episode_done)
            return flask.jsonify(reply_dict), 200
        except Exception as e:
            log.exception(e)
            return flask.jsonify(dict(status=C.ERROR, description='Something went wrong on server side')), 500


    # same as above but just post current thread without new text 
    @router.route('/thread/<thread_id>/<user_id>/current_thread', methods=['POST'])
    def post_current_thread(thread_id, user_id): 
        thread = service.get_thread(thread_id)
        if not thread: 
            return f'Thread {thread_id}  NOT found', 404
        
        user = User.get(user_id)
        if not user or user not in thread.users:
            log.warning('user is not part of thread')
            reply = dict(status=C.ERROR,
                         description=f'User {user.id} is not part of thread {thread.id}. Wrong thread!')
            return flask.jsonify(reply), 400
        
        try: 
            reply, episode_done = service.current_thread(thread)
            reply_dict = reply.as_dict() | dict(episode_done=episode_done)
            return flask.jsonify(reply_dict), 200
        except Exception as e:
            log.exception(e)
            return flask.jsonify(dict(status=C.ERROR, description='Something went wrong on server side')), 500
    

    @router.route('/thread/<thread_id>/<user_id>/latest_message', methods=['GET'])
    def get_latest_message(thread_id, user_id):
        """
        Func called by the AJAX script on the user side every 5 seconds.
        """
        thread = service.get_thread(thread_id)
        if not thread:
            return f'Thread {thread_id}  NOT found', 404
        user = User.get(user_id)
        if not user or user not in thread.users:
            log.warning('user is not part of thread')
            reply = dict(status=C.ERROR,
                         description=f'User {user.id} is not part of thread {thread.id}. Wrong thread!')
            return flask.jsonify(reply), 400
        # We only need to send the last message to the user.
        # We don't need to worry about there might be >1 messages in the last 5 seconds,
        # because one user is always blocked after sending one message.
        latest_message: ChatMessage = thread.messages[-1]
        reply_dict = latest_message.as_dict() | dict(updated='0')
        if latest_message.user_id != user_id:
            reply_dict['updated'] = '1'
        if len(thread.speakers) > 1:
            reply_dict = reply_dict | dict(updated_speakers=thread.speakers)
        # print(thread.users)
        return flask.jsonify(reply_dict), 200

    @router.route('/thread/<thread_id>/get_thread_object', methods=['GET'])
    def get_thread_object(thread_id) -> tuple[Response, int]:
        thread = service.get_thread(thread_id)
        return flask.jsonify(thread.as_dict()), 200

    @router.route('/thread/<thread_id>/<user_id>/rating', methods=['POST'])
    #@FL.login_required   <-- login didnt work in iframe in mturk
    def thread_rating(thread_id, user_id):
        thread = service.get_thread(thread_id)
        user = User.get(user_id)   # FL.current_user
        if not thread:
            return f'Thread {thread_id} NOT found', 404
        if not user:
            return f'User {user_id} NOT found', 404
        if user not in thread.users:
            return f'User {user_id} is NOT part of thread', 403
        log.info(f'updating ratings for {thread.id}')
        ratings = {key: val for key, val in request.form.items()}
        log.info(f'ratings: {ratings}')
        focus_mode = ratings.pop('focus_mode', None)
        service.update_thread_ratings(thread, ratings=ratings, user_id=user_id)
        if thread.ext_src in (C.MTURK, C.MTURK_SANDBOX):
            return render_template('user/mturk_submit.html', thread=thread,
                                   user=user, focus_mode=focus_mode)
        note_text = 'Great job! You have completed a thread!'
        if focus_mode:
            return note_text, 200
        else:
            flask.flash(note_text)
            return flask.redirect(url_for('app.index'))

    ########### M Turk Integration #########################
    @router.route('/mturk-landing/<topic_id>', methods=['GET'])
    def mturk_landing(topic_id):  # this is where mturk worker should land first

        assignment_id = request.values.get('assignmentId')
        is_previewing = assignment_id == 'ASSIGNMENT_ID_NOT_AVAILABLE'
        hit_id = request.values.get('hitId')
        worker_id = request.values.get('workerId')          # wont be available while previewing
        submit_url = request.values.get('turkSubmitTo', '') # wont be available while previewing
        if not hit_id:
            return f'HITId not found. {assignment_id=} {worker_id=} This URL is reserved for Mturk users only: {submit_url}', 400
        
        # because Jon suggested we make it seamless for mturk users
        seamless_login = service.config.is_seamless_crowd_login

        ext_src = C.MTURK_SANDBOX if 'sandbox' in submit_url else C.MTURK 
        if submit_url:
            submit_url = submit_url.rstrip('/') + '/mturk/externalSubmit'
        
        #Our mapping: Worker=User; Assignment = ChatThread; HIT=ChatTopic
        # Step 1: map Hit to Topic, so we can perview it
        topic = ChatTopic.query.filter_by(ext_id=hit_id).first()
        if not topic:
            return 'Invalid HIT or topic ID.', 400

        # We shouldn't check limit here, because we don't know the user yet.
        # If the user has already participated in this task, we should still allow them to review the history.
        # So, the following code is commented out.
        # limit_exceeded, msg = service.limit_check(topic=topic, user=None)
        # if limit_exceeded:
        #     return msg, 400

        if is_previewing: 
            return instructions(focus_mode=True) # sending index page for now. We can do better later

        # Step2. Find the mapping user
        user = User.query.filter_by(ext_src=ext_src, ext_id=worker_id).first()
        if not user: # sign up and come back (so set next)
            
            return flask.redirect(
                url_for('app.seamlesslogin', ext_id=worker_id, ext_src=ext_src, next=request.url))
            
        if not FL.current_user or FL.current_user.get_id() != user.id:
            FL.logout_user()
            FL.login_user(user, remember=True, force=True)
        
        limit_exceeded, msg = service.limit_check(topic=topic, user=user)
        if limit_exceeded: # we may need to block user i.e. change user qualification
            return msg, 400

        # user exist, logged in => means user already signed up and doing so, gave consent,     
        # Step 3: map assignment to chat thread -- 
        data = {
            ext_src : {
                'submit_url': submit_url,
                'is_sandbox': 'workersandbox' in submit_url,
                'assignment_id': assignment_id,
                'hit_id': hit_id,
                'worker_id': worker_id
            }
        }
        chat_thread = service.get_thread_for_topic(user=FL.current_user, topic=topic, create_if_missing=True,
            ext_id=assignment_id, ext_src=ext_src, data=data)
        
        if chat_thread is None: 
            err_msg = 'Another user is loading this chat topic. Please retry after 10 seconds!'
            log.error(err_msg)
            return err_msg, 400

        log.info(f'chat_thread: {chat_thread}')
        log.info(f'worker_id: {worker_id}')
        return get_thread(thread_id=chat_thread.id, request_worker_id=worker_id, focus_mode=True)



###################### ADMIN STUFF #####################
def admin_controllers(router, service: ChatService):
    from .model import User, ChatMessage, ChatThread, ChatTopic

    # attach routes specific to crowd backend e.g. mturk
    if service.crowd_name in (C.MTURK, C.MTURK_SANDBOX):
        MTurkController(service.crowd_service).register_routes(router, login_decorator=admin_login_required)

    admin_templ_args = dict(crowd_name = service.crowd_name)

    # all other routes
    @router.route('/')
    @admin_login_required
    def index():

        counts = dict(
            user=User.query.count(),
            thread=ChatThread.query.count(),
            topic=ChatTopic.query.count(),
            message=ChatMessage.query.count(),
            )
        return render_template('admin/index.html', counts=counts, **admin_templ_args)

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
        return render_template('admin/users.html', users=users, **admin_templ_args)

    @router.route('/thread/')
    @admin_login_required
    def get_threads():
        threads = ChatThread.query.order_by(ChatThread.time_updated.desc(), ChatThread.time_created.desc()).limit(C.MAX_PAGE_SIZE).all()
        return render_template('admin/threads.html', threads=threads, **admin_templ_args)

    @router.route('/topic/delete_all', methods=['POST'])
    @admin_login_required
    def delete_all_topics():
        # delete all topics
        for topic in ChatTopic.query.all():
            if topic.ext_id or topic.ext_src in [C.MTURK, C.MTURK_SANDBOX]:
                MTurkController(service.crowd_service).expire_HIT(topic.ext_id)
            service.delete_topic(topic)
        return redirect(url_for('admin.get_topics'))

    @router.route('/topic/', methods=['GET', 'POST'])
    @admin_login_required
    def get_topics():
        if request.method == 'GET':
            """
            Go to admin "topics" page.
            """
            all_super_topics = SuperTopic.query.order_by(SuperTopic.time_updated.desc(), SuperTopic.time_created.desc()).\
                limit(C.MAX_PAGE_SIZE).all()
            all_topics = ChatTopic.query.order_by(ChatTopic.time_updated.desc(), ChatTopic.time_created.desc()).\
                limit(C.MAX_PAGE_SIZE).all()
            topic_thread_counts = service.get_thread_counts(episode_done=True)
            super_topic_thread_counts = service.get_thread_counts_of_super_topic(episode_done=True)
            topic_thread_counts_dict = {topic: topic_thread_counts.get(topic.id, 0) for topic in all_topics}
            super_topics = \
                [(super_topic, super_topic_thread_counts.get(super_topic.id, 0)) for super_topic in all_super_topics]
            return render_template('admin/topics.html', tasks=all_topics, super_topics=super_topics,
                                   external_url_ok=service.is_external_url_ok, **admin_templ_args,
                                   topic_thread_counts_dict=topic_thread_counts_dict, service=service)
        else:
            """
            "POST" request to 1.create a new topic (task) under a super-topic 2. update the thread limit of all users
            3. create multiple tasks(topics) under a super-topic  4. launch multiple topics(tasks) 
            """
            print("request.form: ", request.form)
            args = dict(request.form)
            if C.LIMIT_MAX_THREADS_PER_USER in args.keys():
                service.limits[C.LIMIT_MAX_THREADS_PER_USER] = int(args[C.LIMIT_MAX_THREADS_PER_USER])
            elif "multi-topics-creation" in args.keys():
                selected_super_topic_ids = request.form.getlist('multi-topics-creation')
                for super_topic_id in selected_super_topic_ids:
                    service.create_topic_from_super_topic(super_topic_id=super_topic_id, endpoint=args['endpoint'],
                                                          persona_id=args['persona_id'],
                                                          max_threads_per_topic=int(args['max_threads_per_topic']),
                                                          max_turns_per_thread=int(args['max_turns_per_thread']),
                                                          max_human_users_per_thread=int(args['max_human_users_per_thread']),
                                                          human_moderator=args['human_moderator'],
                                                          reward=args['reward'])
            elif "multi-tasks-launch" in args.keys():
                selected_task_ids = request.form.getlist('multi-tasks-launch')
                for task_id in selected_task_ids:
                    launch_topic_on_crowd(topic_id=task_id, crowd_name=service.crowd_name)
            else:
                service.create_topic_from_super_topic(super_topic_id=args['super_topic_id'], endpoint=args['endpoint'],
                                                      persona_id=args['persona_id'],
                                                      max_threads_per_topic=int(args['max_threads_per_topic']),
                                                      max_turns_per_thread=int(args['max_turns_per_thread']),
                                                      max_human_users_per_thread=int(args['max_human_users_per_thread']),
                                                      human_moderator=args['human_moderator'],
                                                      reward=args['reward'])
            return redirect(url_for('admin.get_topics'))

    @router.route(f'/topic/<topic_id>/launch/<crowd_name>')
    @admin_login_required
    def launch_topic_on_crowd(topic_id, crowd_name):
        topic = ChatTopic.query.get(topic_id)
        if not topic:
            return f'Topic {topic_id} not found', 404
        if crowd_name and service.crowd_name != crowd_name:
            return f'Crowd backend {crowd_name} is not configured. Currently serving {service.crowd_name}', 400

        if topic.ext_id:
            return f'Topic {topic_id} already has been launched on {topic.ext_src}'
        ext_id = service.launch_topic_on_crowd(topic)
        if ext_id:
            flask.flash(f'Successfully launched {topic_id} on {crowd_name} as {ext_id}')
            return flask.redirect(flask.url_for('admin.get_topics'))
        else:
            return 'Error: we couldnt launch on crowd', 400

    @router.route(f'/config')
    @admin_login_required
    def get_config():
        config_yaml = service.config.as_yaml_str()
        return render_template('admin/config.html', config_yaml=config_yaml)

    @router.route(f'/topic/<topic_id>/delete_topic/')
    @admin_login_required
    def delete_topic(topic_id):
        topic = ChatTopic.query.get(topic_id)
        if topic.ext_id or topic.ext_src in [C.MTURK, C.MTURK_SANDBOX]:
            MTurkController(service.crowd_service).expire_HIT(topic.ext_id)
        # ret_a, ret_b = MTurkController(service.crowd_service).delete_hit(topic.ext_id)

        service.delete_topic(topic)
        return redirect(url_for('admin.get_topics'))

        # if not topic:
        #     return f'Topic {topic_id} not found', 404
        # if crowd_name and service.crowd_name != crowd_name:
        #     return f'Crowd backend {crowd_name} is not configured. Currently serving {service.crowd_name}', 400
        #
        # if topic.ext_id:
        #     return f'Topic {topic_id} already has been launched on {topic.ext_src}'
        # ext_id = service.launch_topic_on_crowd(topic)
        # if ext_id:
        #     flask.flash(f'Successfully launched {topic_id} on {crowd_name} as {ext_id}')
        #     return flask.redirect(flask.url_for('admin.get_topics'))
        # else:
        #     return 'Error: we couldnt launch on crowd', 400

    # @router.route(f'/topics/', methods=["POST"])
    # @admin_login_required
    # def create_topic():
    #     # new_topic = service.create_topic_from_super_topic(super_topic_id)
    #     args = dict(request.form)
    #
    #     return redirect(url_for('admin.get_topics'))
