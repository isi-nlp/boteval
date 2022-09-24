

from pathlib import Path
import json
from threading import Thread
from typing import List, Mapping, Optional, Union
import functools
from datetime import datetime
import copy

import flask
import requests
from sqlalchemy import func
from sqlalchemy.orm import attributes

from  . import log, db, C
from .model import ChatTopic, User, ChatMessage, ChatThread, UserThread
from .bots import BotAgent, load_bot_agent
from .utils import jsonify
from .mturk import MTurkService
from . import constants


class ChatManager:

    def __init__(self, thread_id) -> None:
        self.thread_id = thread_id
        # Note: dont save/cache thread object here as it will go out of sync with ORM, only save ID

    def new_message(self, message):
        raise NotImplementedError()


class DialogBotChatManager(ChatManager):

    # 1-on-1 dialog between human and a bot

    def __init__(self, thread: ChatThread, bot_agent:BotAgent,
                 max_turns:int=constants.DEF_MAX_TURNS_PER_THREAD):
        super().__init__(thread.id)
        # Note: dont save/cache thread object here as it will go out of sync with ORM, only save ID
        bots = [ user for user in thread.users if user.role == User.ROLE_BOT ]
        user_ids = [u.id for u in thread.users]
        assert len(bots) == 1, f'Expect 1 bot in thead {thread.id}; found {len(bots)}; Users: {user_ids}'
        self.bot_user_id = bots[0].id
        assert bot_agent
        self.bot_agent = bot_agent

        humans = [ user for user in thread.users if user.role == User.ROLE_HUMAN ]
        assert len(humans) == 1, f'Expect 1 human in thead {thread.id}; found {len(humans)}; Users: {user_ids}'
        self.human_user_id = humans[0].id

        self.max_turns = max_turns
        self.num_turns = thread.count_turns(humans[0])


    def observe_message(self, thread: ChatThread, message: ChatMessage) -> ChatMessage:
        # Observe and reply
        # this message is from human
        assert thread.id == self.thread_id
        assert message.user_id == self.human_user_id
        db.session.add(message)
        thread.messages.append(message)

        reply = self.bot_reply(message.text)

        db.session.add(reply)
        thread.messages.append(reply)
        db.session.commit()
        self.num_turns += 1
        episode_done = self.num_turns >= self.max_turns
        log.info(f'{self.thread_id} turns:{self.num_turns} max:{self.max_turns}')
        return reply, episode_done

    def bot_reply(self, context: str) -> ChatMessage:
        # only using last message as context
        reply = self.bot_agent.talk(context)
        msg = ChatMessage(user_id = self.bot_user_id, text=reply, thread_id = self.thread_id)
        return msg


class FileExportService:
    """Export chat data from database into file system"""

    def __init__(self, data_dir: Union[Path,str]) -> None:
        if not isinstance(data_dir, Path):
            data_dir = Path(data_dir)
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def export_thread(self, thread: ChatThread, **meta):
        dt_now = datetime.now()
        file_name = dt_now.strftime("%Y%m%d-%H%M%S") + f'-{thread.topic_id}_{thread.id}.json'
        path = self.data_dir / dt_now.strftime("%Y%m%d") / file_name
        log.info(f'Export thread {thread.id} to {path}')
        path.parent.mkdir(exist_ok=True, parents=True)
        with open(path, 'w', encoding='utf-8') as out:
            data = thread.as_dict()
            data['_exported_'] = str(dt_now)
            data['meta'] = meta
            json.dump(data, out, indent=2, ensure_ascii=False)


class ChatService:

    def __init__(self, config):
        self.config = config
        self._bot_user = None
        self._context_user = None
        self.topics_file = self.config['chatbot']['topics_file']

        self.exporter = FileExportService(config['chat_dir'])
        bot_name = config['chatbot']['bot_name']
        bot_args = config['chatbot'].get('bot_args') or {}
        self.bot_agent = load_bot_agent(bot_name, bot_args)
        self.limits = config.get('limits') or {}
        self.ratings = config['ratings']

        self.onboarding = config.get('onboarding') and copy.deepcopy(config['onboarding'])
        if  self.onboarding and 'agreement_file' in self.onboarding:
            self.onboarding['agreement_text'] = Path(self.onboarding['agreement_file']).read_text()

        self.crowd_service = None
        if C.MTURK in self.config:
            self.crowd_service = MTurkService.new(**self.config[C.MTURK])
        
        #self._external_url_ok = None

    """
    @property
    def is_external_url_ok(self):
        if self._external_url_ok is None:
            ping_url = flask.url_for('app.ping', _external=True, _scheme='https')
            log.info(f"Checking external URL {ping_url}")
            try:
                reply = requests.get(ping_url)
                self._external_url_ok = reply and reply.status_code == 200 and reply.json()['reply'] == 'pong'
            except Exception as e:
                log.exception(e)
                self._external_url_ok = False
        return self._external_url_ok
    """

    @property
    def bot_user(self):
        if not self._bot_user:
            self._bot_user = User.query.get(constants.Auth.BOT_USER)
        return self._bot_user

    @property
    def crowd_name(self):
        return self.crowd_service and self.crowd_service.name

    @property
    def context_user(self):
        if not self._context_user:
            self._context_user = User.query.get(constants.Auth.CONTEXT_USER)
        return self._context_user


    def init_db(self, init_topics=True):

        if not User.query.get(constants.Auth.ADMIN_USER):
            User.create_new(
                id=constants.Auth.ADMIN_USER, name='Chat Admin',
                secret=constants.Auth.ADMIN_SECRET, role=User.ROLE_ADMIN)

        if not User.query.get(constants.Auth.DEV_USER): # for development
            User.create_new(id=constants.Auth.DEV_USER, name='Developer',
                            secret=constants.Auth.DEV_SECRET,
                            role=User.ROLE_HUMAN)

        if not User.query.get(constants.Auth.BOT_USER):
            # login not enabled. directly insert with empty string as secret
            db.session.add(User(id=constants.Auth.BOT_USER, name='Chat Bot',
                                secret='', role=User.ROLE_BOT))

        if not User.query.get(constants.Auth.CONTEXT_USER):
            # for loading context messages
            db.session.add(User(id=constants.Auth.CONTEXT_USER,
                                name='Context User', secret='',
                                role=User.ROLE_HIDDEN))


        if init_topics:
            assert self.topics_file
            topics_file = Path(self.topics_file).resolve()
            topics_file.exists(), f'{topics_file} not found'

            with open(topics_file, encoding='utf-8') as out:
                topics = json.load(out)
            assert isinstance(topics, list)
            log.info(f'found {len(topics)} topics in {topics_file}')
            objs = []
            for topic in topics:
                obj = ChatTopic.query.get(topic['id'])
                if obj:
                    log.warning(f'Chat topic exisits {topic["id"]}, so skipping')
                    continue
                obj = ChatTopic(id=topic['id'], name=topic['name'], data=topic)
                objs.append(obj)
            if objs:
                log.info(f"Inserting {len(objs)} topics to db")
                db.session.add_all(objs)
        db.session.commit()

    def get_topics(self):
        return ChatTopic.query.all()

    def get_user_threads(self, user):
        return ChatThread.query.join(User, ChatThread.users).filter(User.id==user.id).all()

    def get_topic(self, topic_id):
        return ChatTopic.query.get(topic_id)

    def get_thread_for_topic(self, user, topic, create_if_missing=True, ext_id=None, ext_src=None, data=None) -> Optional[ChatThread]:
        topic_threads = ChatThread.query.filter_by(topic_id=topic.id).all()
        # TODO: appply this second filter directly into sqlalchemy
        thread = None
        for tt in topic_threads:
            if any(user.id == tu.id for tu in tt.users):
                log.info('Topic thread alredy exists; reusing it')
                thread = tt

        if not thread and create_if_missing:
            log.info(f'creating a thread: user: {user.id} topic: {topic.id}')
            data = data or {}
            thread = ChatThread(topic_id=topic.id, ext_id=ext_id, ext_src=ext_src, data=data)
            thread.users.append(user)
            thread.users.append(self.bot_user)
            thread.users.append(self.context_user)
            db.session.add(thread)
            db.session.flush()  # flush it to get thread_id
            for m in topic.data['conversation']:
                text = m['text']
                data =  dict(text_orig=m.get('text_orig'), speaker_id= m.get('speaker_id'), fake_start=True)
                msg = ChatMessage(text=text, user_id=self.context_user.id, thread_id=thread.id, data=data)
                db.session.add(msg)
                thread.messages.append(msg)
            db.session.merge(thread)
            db.session.flush()
            db.session.commit()
        return thread

    def get_thread(self, thread_id) -> Optional[ChatThread]:
        return ChatThread.query.get(thread_id)

    def get_threads(self, user: User) -> List[ChatThread]:
        log.info(f'Querying {user.id}')
        threads = UserThread.query.filter(user_id=user.id).all()
        #threads = ChatThread.query.filter_by(user_id=user.id).all()
        log.info(f'Found {len(threads)} threads found')
        return threads

    def get_thread_counts(self, episode_done=True) -> Mapping[str, int]:
        thread_counts = ChatThread.query.filter_by(episode_done=bool(episode_done))\
            .with_entities(ChatThread.topic_id, func.count(ChatThread.topic_id))\
            .group_by(ChatThread.topic_id).all()

        return {tid: count for tid, count in thread_counts }

    def update_thread_ratings(self, thread: ChatThread, ratings:dict):
        if thread.data is None:
            thread.data = {}

        thread.data.update(dict(ratings=ratings, rating_done=True))
        thread.episode_done = True
        if self.crowd_service and thread.ext_id:
            self.crowd_service.task_complete(thread, ratings)

        thread.flag_data_modified()
        db.session.merge(thread)
        db.session.flush()
        db.session.commit()
        self.exporter.export_thread(thread, rating_questions=self.ratings)


    @functools.lru_cache(maxsize=256)
    def cached_get(self, thread):
        max_turns = self.config.get('limits', {}).get('max_turns_per_thread',
                                                      constants.DEF_MAX_TURNS_PER_THREAD)
        return DialogBotChatManager(thread=thread, bot_agent=self.bot_agent,
                                    max_turns=max_turns)

    def new_message(self, msg: ChatMessage, thread: ChatThread) -> ChatMessage:
        dialog = self.cached_get(thread)
        reply, episode_done = dialog.observe_message(thread, msg)
        return reply, episode_done

    def get_rating_questions(self):
        return self.ratings

    def launch_topic_on_crowd(self, topic:ChatTopic):
        if not self.crowd_service:
            log.warning('Crowd service not configured')
            return None
        #if not self.is_external_url_ok:
        #    log.warning('External URL is not configured correctly. ')
        #    return None
        if self.crowd_name in (C.MTURK, C.MTURK_SANDBOX):                
            landing_url = flask.url_for('app.mturk_landing', topic_id=topic.id, _external=True, _scheme='https')
            log.info(f'mturk landing URL {landing_url}')
            ext_id, task_url, result = self.crowd_service.create_HIT(landing_url, 
                max_assignments=self.limits.get('max_threads_per_topic', C.MAX_THREADS_PER_TOPIC),
                reward=self.limits.get('reward', '0.0'),
                description=topic.name,
                title=f'{topic.id}')
            ext_src = self.crowd_service.name
            if ext_id:
                topic.ext_id = ext_id
                topic.ext_src = ext_src
                topic.data[ext_src] = dict(
                    is_sabdbox = self.crowd_service.is_sandbox,
                    time_created = datetime.now().isoformat(),
                    hit_id = ext_id,
                    ext_url = task_url
                    )
                topic.flag_data_modified()
                db.session.merge(topic)
                db.session.commit()
            return ext_id
        else:
            log.error(f'Crowd name {self.crowd_name} not supported yet')
            return
