

from pathlib import Path
import json
from typing import List, Mapping, Optional, Tuple, Union
import functools
from datetime import datetime
import copy
import time

import flask
import requests
from sqlalchemy import func


from  . import log, db, C, TaskConfig
from .model import ChatTopic, User, ChatMessage, ChatThread, UserThread
from .bots import BotAgent, load_bot_agent
from .transforms import load_transforms, Transforms
from .mturk import MTurkService


class ChatManager:

    def __init__(self, thread_id) -> None:
        self.thread_id = thread_id
        # Note: dont save/cache thread object here as it will go out of sync with ORM, only save ID

    def new_message(self, message):
        raise NotImplementedError()


class DialogBotChatManager(ChatManager):

    # 1-on-1 dialog between human and a bot

    def __init__(self, thread: ChatThread, bot_agent:BotAgent,
                 max_turns:int=C.DEF_MAX_TURNS_PER_THREAD,
                 human_transforms: Optional[Transforms]=None,
                 bot_transforms: Optional[Transforms]=None):
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
        
        self.bot_transforms = bot_transforms
        self.human_transforms = human_transforms


    def observe_message(self, thread: ChatThread, message: ChatMessage) -> ChatMessage:
        # Observe and reply
        # this message is from human
        assert thread.id == self.thread_id
        assert message.user_id == self.human_user_id        
        if self.human_transforms:
            message = self.human_transforms(message)

        db.session.add(message)
        thread.messages.append(message)

        reply = self.bot_reply(message.text)
        if self.bot_transforms:
            reply = self.bot_transforms(reply)

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
        msg = ChatMessage(user_id = self.bot_user_id, text=reply, thread_id = self.thread_id, data={})
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

    def __init__(self, config: TaskConfig, task_dir:Path):
        self.config = config
        self.task_dir = task_dir
        self.task_dir.mkdir(exist_ok=True, parents=True)
        self._bot_user = None
        self._context_user = None
        
        topics_file = self.config['chatbot'].get('topics_file', C.DEF_TOPICS_FILE)
        self.topics_file = self.resolve_path(topics_file)
        instructions_file = self.config['chatbot'].get('instructions_file', C.DEF_INSTRUCTIONS_FILE)
        self.instructions_file = self.resolve_path(instructions_file)
        self._instructions = None

        transforms_conf = self.config['chatbot'].get('transforms', {})

        self.human_transforms = None
        if transforms_conf.get('human'):
            self.human_transforms = load_transforms(transforms_conf['human'])
        self.bot_transforms = None
        if transforms_conf.get('bot'):
            self.bot_transforms = load_transforms(transforms_conf['bot'])
        
        self.exporter = FileExportService(self.resolve_path(config['chat_dir']))
        bot_name = config['chatbot']['bot_name']
        bot_args = config['chatbot'].get('bot_args') or {}
        self.bot_agent = load_bot_agent(bot_name, bot_args)
        self.limits = config.get('limits') or {}
        self.ratings = config['ratings']

        self.onboarding = config.get('onboarding') and copy.deepcopy(config['onboarding'])
        if self.onboarding and 'agreement_file' in self.onboarding:
            self.onboarding['agreement_text'] = self.resolve_path(self.onboarding['agreement_file']).read_text()


        self.crowd_service = None
        if C.MTURK in self.config:
            self.crowd_service = MTurkService.new(**self.config[C.MTURK])
        self._external_url_ok = None
        
    def resolve_path(self, *args):
        return Path(self.task_dir, *args)

    def check_ext_url(self, ping_url, wait_time=C.PING_WAIT_TIME):
        # this will be called by app hook before_first_request
        log.info(f"Pinging URL {ping_url} in {wait_time} secs")
        if wait_time and  wait_time > 0:
            time.sleep(wait_time)
        try:
            reply = requests.get(ping_url)
            self._external_url_ok = reply and reply.status_code == 200 and reply.json()['reply'] == 'pong'
            log.info(f'{reply=} {self._external_url_ok=}')
        except Exception as e:
            log.exception(e)
            self._external_url_ok = False
       
    @property
    def is_external_url_ok(self):
        return self._external_url_ok
    
    @property
    def instructions(self) -> str:
        if not self._instructions:
            if self.instructions_file.exists():
                self._instructions = self.instructions_file.read_text()
            else:
                self._instructions = 'No instructions have been found for this task'
        return self._instructions


    @property
    def bot_user(self):
        if not self._bot_user:
            self._bot_user = User.query.get(C.Auth.BOT_USER)
        return self._bot_user

    @property
    def crowd_name(self):
        return self.crowd_service and self.crowd_service.name

    @property
    def context_user(self):
        if not self._context_user:
            self._context_user = User.query.get(C.Auth.CONTEXT_USER)
        return self._context_user


    def init_db(self, init_topics=True):
        
        if not User.query.get(C.Auth.ADMIN_USER):
            User.create_new(
                id=C.Auth.ADMIN_USER, name='Chat Admin',
                secret=C.Auth.ADMIN_SECRET, role=User.ROLE_ADMIN)

        if not User.query.get(C.Auth.DEV_USER): # for development
            User.create_new(id=C.Auth.DEV_USER, name='Developer',
                            secret=C.Auth.DEV_SECRET,
                            role=User.ROLE_HUMAN)

        if not User.query.get(C.Auth.BOT_USER):
            # login not enabled. directly insert with empty string as secret
            db.session.add(User(id=C.Auth.BOT_USER, name=C.BOT_DISPLAY_NAME or 'Chat Bot',
                                secret='', role=User.ROLE_BOT))

        if not User.query.get(C.Auth.CONTEXT_USER):
            # for loading context messages
            db.session.add(User(id=C.Auth.CONTEXT_USER,
                                name='Context User', secret='',
                                role=User.ROLE_HIDDEN))

        if init_topics:
            assert self.topics_file
            topics_file = self.topics_file.resolve()
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

    def limit_check(self, topic: ChatTopic=None, user: User=None) -> Tuple[bool, str]:
        # total_threads = db.session.query(func.count(ChatThread.id)).scalar()
        if user and self.limits.get(C.LIMIT_MAX_THREADS_PER_USER, 0) > 0:
            user_thread_count = ChatThread.query.join(User, ChatThread.users).filter(User.id==user.id).count()
            if user_thread_count >= self.limits[C.LIMIT_MAX_THREADS_PER_USER]:
                return True, 'User has exceeded maximum permissible threads'
        if topic and self.limits.get(C.LIMIT_MAX_THREADS_PER_TOPIC, 0):
            topic_thread_count = ChatThread.query.filter(ChatThread.topic_id==topic.id).count()
            if topic_thread_count >= self.limits[C.LIMIT_MAX_THREADS_PER_TOPIC]:
                return True, 'This topic has exceeded maximum permissible threads'
        return False, ''

    def get_topics(self):
        return ChatTopic.query.all()

    def get_user_threads(self, user):
        return ChatThread.query.join(User, ChatThread.users).filter(User.id==user.id).all()

    def get_topic(self, topic_id):
        return ChatTopic.query.get(topic_id)

    def get_thread_for_topic(self, user, topic, create_if_missing=True,
                             ext_id=None, ext_src=None, data=None) -> Optional[ChatThread]:
        topic_threads = ChatThread.query.filter_by(topic_id=topic.id).all()
        # TODO: appply this second filter directly into sqlalchemy
        thread = None
        for tt in topic_threads:
            if any(user.id == tu.id for tu in tt.users):
                log.info('Topic thread alredy exists; reusing it')
                thread = tt
                break

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

        thread.flag_data_modified()
        db.session.merge(thread)
        db.session.flush()
        db.session.commit()
        self.exporter.export_thread(thread, rating_questions=self.ratings)

    @functools.lru_cache(maxsize=256)
    def cached_get(self, thread):
        max_turns = self.limits.get(C.LIMIT_MAX_TURNS_PER_THREAD,
                                    C.DEF_MAX_TURNS_PER_THREAD)
        return DialogBotChatManager(thread=thread, bot_agent=self.bot_agent,
                                    max_turns=max_turns,
                                    bot_transforms=self.bot_transforms,
                                    human_transforms=self.human_transforms)

    def new_message(self, msg: ChatMessage, thread: ChatThread) -> ChatMessage:
        dialog = self.cached_get(thread)
        reply, episode_done = dialog.observe_message(thread, msg)
        return reply, episode_done

    def get_rating_questions(self):
        return self.ratings

    def launch_topic_on_crowd(self, topic: ChatTopic):
        if not self.crowd_service:
            log.warning('Crowd service not configured')
            return None
        if not self.is_external_url_ok:
            msg = 'External URL is not configured correctly. Skipping.'
            log.warning(msg)
            flask.flash(msg)
            return None
        if self.crowd_name in (C.MTURK, C.MTURK_SANDBOX):                
            landing_url = flask.url_for('app.mturk_landing', topic_id=topic.id,
                                        _external=True, _scheme='https')
            log.info(f'mturk landing URL {landing_url}')
            ext_id, task_url, result = self.crowd_service.create_HIT(landing_url, 
                max_assignments=self.limits.get(C.LIMIT_MAX_THREADS_PER_TOPIC, C.DEF_MAX_THREADS_PER_TOPIC),
                reward=self.limits.get(C.LIMIT_REWARD, C.DEF_REWARD),
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
