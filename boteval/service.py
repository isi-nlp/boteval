import os
from pathlib import Path
import json
from typing import List, Mapping, Optional, Tuple, Union
import functools
from datetime import datetime
import copy
import time
import re

import flask
import requests
from sqlalchemy import func


from  . import log, db, C, TaskConfig
from .model import ChatTopic, User, ChatMessage, ChatThread, UserThread, SuperTopic
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
        log.info(f'Initializing a dialog manager for thread {thread.id}')
        # Note: dont save/cache thread object here as it will go out of sync with ORM, only save ID
        bots = [ user for user in thread.users if user.role == User.ROLE_BOT ]
        user_ids = [u.id for u in thread.users]
        assert len(bots) == 1, f'Expect 1 bot in thread {thread.id}; found {len(bots)}; Users: {user_ids}'
        self.bot_user_id = bots[0].id
        assert bot_agent
        self.bot_agent: BotAgent = bot_agent

        humans = [ user for user in thread.users if user.role == User.ROLE_HUMAN ]
        # assert len(humans) == 1, f'Expect 1 human in thread {thread.id}; found {len(humans)}; Users: {user_ids}'

        self.max_turns = max_turns * thread.max_human_users_per_thread
        self.num_turns = 0
        for human in humans:
            self.num_turns += thread.count_turns(human)

        self.bot_transforms = bot_transforms
        self.human_transforms = human_transforms
                
        topic = ChatTopic.query.get(thread.topic_id)
        self.init_chat_context(thread)
        self.n_human_users = thread.max_human_users_per_thread
        


    def init_chat_context(self, thread: ChatThread):
        if not thread.messages:
            log.info(f'{thread.id} has no messages, so nothing to init')
            return
        log.info(f'Init Thread ID {thread.id}\'s context with {len(thread.messages)} msgs')
        topic_appeared = False 
        messages = [msg.as_dict() for msg in thread.messages]
        self.bot_agent.init_chat_context(messages)

    def bot_init_reply(self, thread):
        # Last one was targeted speaker; bot reply here
        
        if not thread.need_moderator_bot:
            log.info("Do not need moderator bot in this chat")
            reply = ChatMessage(user_id = self.bot_user_id, text='', is_seed=False)
        else: 
            reply: ChatMessage = self.bot_reply(n_users=self.n_human_users)
            if reply.text.strip():  # if bot responded
                db.session.add(reply)
                thread.messages.append(reply)
                db.session.commit()
            # We should not increment num_turns here, as the bot reply shouldn't be counted.
            # self.num_turns += 1
            log.info(f'{self.thread_id} turns:{self.num_turns} max:{self.max_turns}')
            db.session.merge(thread)
            db.session.flush()
            db.session.commit()

        episode_done = False
        
        return reply, episode_done 

    def observe_and_reply_message(self, thread: ChatThread, message: ChatMessage) -> Tuple[ChatMessage, bool]:
        """
        Observe and reply; input message is from human;
        return (bot reply, episode_done)
        """
        assert thread.id == self.thread_id

        # add new message
        db.session.add(message)
        thread.messages.append(message)
        db.session.commit()

        if self.human_transforms:
            message = self.human_transforms(message)

        self.bot_agent.hear(message.as_dict())

        if not thread.need_moderator_bot:
            log.info("Do not need moderator bot in this chat")
            reply = ChatMessage(user_id = self.bot_user_id, text='', is_seed=False)
        else: 
            reply = self.bot_reply(n_users = self.n_human_users)
            if reply.text.strip(): # if bot responded 
                db.session.add(reply)
                thread.messages.append(reply)
                db.session.commit()

        self.num_turns += 1

        humans = [user for user in thread.users if user.role == User.ROLE_HUMAN]
        episode_done = self.num_turns >= self.max_turns
        return reply, episode_done
        
    def bot_reply(self, n_users:int=None) -> ChatMessage:
        reply: dict = self.bot_agent.talk(n_users=n_users)
        if not reply: #bot decided to not respond 
            reply_text = ""
        else: 
            reply_text = reply['text']            
                
        reply = ChatMessage(user_id = self.bot_user_id, text=reply_text, is_seed=False,
                            thread_id = self.thread_id, data={"speaker_id": reply['data']['speaker_id']})
        if self.bot_transforms:
            reply = self.bot_transforms(reply)
        return reply


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

    def __init__(self, config: TaskConfig, task_dir:Path,
                 persona_configs_relative_filepath='persona_configs.json'):
        self.config: TaskConfig = config
        self.task_dir = task_dir
        self.task_dir.mkdir(exist_ok=True, parents=True)
        self._bot_user_id = C.Auth.BOT_USER
        self._context_user_id = C.Auth.CONTEXT_USER
        
        topics_file = self.config['chatbot'].get('topics_file', C.DEF_TOPICS_FILE)
        self.topics_file = self.resolve_path(topics_file)
        instructions_file = self.config['onboarding'].get('instructions_file', C.DEF_INSTRUCTIONS_FILE)
        simple_instructions_file = self.config['onboarding'].get('simple_instructions_file', C.DEF_INSTRUCTIONS_FILE)
        human_mod_instructions_file = self.config['onboarding'].get('human_moderator_instructions_file', C.DEF_INSTRUCTIONS_FILE)

        log.info('human_mod_instructions_file is: ', human_mod_instructions_file)

        self.instructions_file = self.resolve_path(instructions_file)
        self.simple_instructions_file = self.resolve_path(simple_instructions_file)
        self.human_mod_instructions_file = self.resolve_path(human_mod_instructions_file)
        self._instructions = None
        self._simple_instructions = None
        self._human_mod_instructions = None

        transforms_conf = self.config['chatbot'].get('transforms', {})

        self.human_transforms = None
        if transforms_conf.get('human'):
            self.human_transforms = load_transforms(transforms_conf['human'])
        self.bot_transforms = None
        if transforms_conf.get('bot'):
            self.bot_transforms = load_transforms(transforms_conf['bot'])
        
        self.exporter = FileExportService(self.resolve_path(config.get('chat_dir'), 'data'))
        bot_name = config['chatbot']['bot_name']
        # bot_args are no longer used as we always load all possible bots and chose the one we need at launching.
        bot_args = config['chatbot'].get('bot_args') or {}

        # get engine names
        self.endpoints = config['chatbot']['bot_args']['engines']
        log.info('endpoints: ', self.endpoints)

        # Starting to load all ids from persona_configs.json
        persona_filepath = Path(task_dir) / persona_configs_relative_filepath

        with open(persona_filepath, mode='r') as f:
            persona_jsons = json.load(f)
            self.persona_id_list = [x['id'] for x in persona_jsons]

        # Initialize all possible bots
        self.bot_agent_dict = {}
        for cur_endpoint_name in self.endpoints:
            for cur_persona_id in self.persona_id_list:
                tmp_dict = {
                    # 'engine': cur_engine_name,
                    'default_endpoint': cur_endpoint_name,
                    'persona_id': cur_persona_id
                }
                self.bot_agent_dict[(cur_endpoint_name, cur_persona_id)] = load_bot_agent(bot_name, tmp_dict)

        # self.persona_id = bot_args.get('persona_id')
        # self.bot_agent = load_bot_agent(bot_name, bot_args)
        self.limits = config.get('limits') or {}
        self.ratings = config['ratings']

        self.onboarding = config.get('onboarding') and copy.deepcopy(config['onboarding'])
        if self.onboarding and 'agreement_file' in self.onboarding:
            self.onboarding['agreement_text'] = self.resolve_path(self.onboarding['agreement_file']).read_text(encoding='UTF-8')


        self.crowd_service = None
        if C.MTURK in self.config:
            self.crowd_service = MTurkService.new(**self.config[C.MTURK])
        self._external_url_ok = None
        
    def resolve_path(self, *args):
        return Path(self.task_dir, *args)

    def check_ext_url(self, ping_url, wait_time=C.PING_WAIT_TIME):
        # this will be called by app hook before_first_request
        if not self.config['flask_config'].get('SERVER_NAME'):
            log.warning('flask_config.SERVER_NAME is not set. crowd launching feature is disabled')
            self._external_url_ok = None
            return

        log.info(f"Pinging URL {ping_url} in {wait_time} secs")
        if wait_time and  wait_time > 0:
            time.sleep(wait_time)
        try:
            reply = requests.get(ping_url)
            self._external_url_ok = reply and reply.status_code == 200 and reply.json()['reply'] == 'pong'
            log.info(f'{reply=} {self._external_url_ok=}')
        except Exception as e:
            log.warning(str(e))
            log.warning('Looks like external URL is not configured as HTTPs. Crowd launching is disabled')
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
    def simple_instructions(self) -> str:
        if not self._simple_instructions:
            if self.simple_instructions_file.exists():
                self._simple_instructions = self.simple_instructions_file.read_text()
            else:
                self._simple_instructions = 'No simple instructions have been found for this task'
        return self._simple_instructions

    @property
    def human_mod_instructions(self) -> str:
        if not self._human_mod_instructions:
            if self.human_mod_instructions_file.exists():
                self._human_mod_instructions = self.human_mod_instructions_file.read_text()
            else:
                self._human_mod_instructions = 'No human moderator instructions have been found for this task'
        return self._human_mod_instructions


    @property
    def bot_user(self):
        # do not cache user object.  ORM will complain
        return User.query.get(self._bot_user_id)

    @property
    def crowd_name(self):
        return self.crowd_service and self.crowd_service.name

    @property
    def context_user(self):
        # do not cache user  object.  ORM will complain
        return User.query.get(self._context_user_id)

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
            bot_name = self.config.get('chatbot', {}).get('display_name') or C.BOT_DISPLAY_NAME
            # login not enabled. directly insert with empty string as secret
            db.session.add(User(id=C.Auth.BOT_USER, name=bot_name,
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
                obj = SuperTopic.query.get(topic['id'])
                if obj:
                    log.warning(f'Chat topic exists {topic["id"]}, so skipping')
                    continue
                obj = SuperTopic(id=topic['id'], name=topic['name'], data=topic, next_task_id=1)
                objs.append(obj)
            if objs:
                log.info(f"Inserting {len(objs)} topics to db")
                db.session.add_all(objs)
            # self.init_sub_topics()
        db.session.commit()

    # def init_sub_topics(self):
    #     """
    #     A helper function to create a topic for all super_topics when booting.
    #     Not used for now (because we want to launch tasks with different settings dynamically)
    #     @return: None
    #     """
    #     super_topics = SuperTopic.query.all()
    #     for super_topic in super_topics:
    #         if not super_topic.topics:
    #             cur_topic = ChatTopic.create_new(super_topic)
    #             db.session.add(cur_topic)
        # db.session.commit()

    def create_topic_from_super_topic(self, super_topic_id, endpoint, persona_id, max_threads_per_topic,
                                      max_turns_per_thread, max_human_users_per_thread, human_moderator, reward):
        """
        Create a topic from a super topic
        The terminology is confusing.  A super topic is a topic in the old version.
        A topic is a task. Each task under the same super topic shares the same conversation history.
        """
        super_topic = SuperTopic.query.get(super_topic_id)
        new_topic = ChatTopic.create_new(super_topic, endpoint=endpoint, persona_id=persona_id,
                                         max_threads_per_topic=max_threads_per_topic,
                                         max_turns_per_thread=max_turns_per_thread,
                                         max_human_users_per_thread=max_human_users_per_thread,
                                         human_moderator=human_moderator, reward=reward)
        db.session.add(new_topic)
        db.session.commit()

    def limit_check(self, topic: ChatTopic=None, user: User=None) -> Tuple[bool, str]:
        # total_threads = db.session.query(func.count(ChatThread.id)).scalar()
        # Check if the user reached the max_threads_per_user.
        if user and self.limits.get(C.LIMIT_MAX_THREADS_PER_USER, 0) > 0:
            user_thread_count = ChatThread.query.join(User, ChatThread.users).filter(User.id==user.id).count()
            if user_thread_count >= self.limits[C.LIMIT_MAX_THREADS_PER_USER]:
                return True, 'User has exceeded maximum permissible threads'
        # Firstly, we check if the current user is trying to re-enter a chatroom
        # In this case, even if we have reached the max_threads_per_topic limit, we should still let the user
        # re-enter the chatroom and check their history.
        if User is not None:
            topic_threads = ChatThread.query.filter_by(topic_id=topic.id).all()
            for tt in topic_threads:
                if any(user.id == tu.id for tu in tt.users):
                    return False, ''
        # If the user is not trying to re-enter a chatroom,
        # we check if the topic has reached the max_threads_per_topic limit
        if topic and topic.max_threads_per_topic:
            topic_thread_count = ChatThread.query.filter(ChatThread.topic_id==topic.id).count()
            # If the user is trying to enter a single-user chatroom,
            # we just need to check if the topic has reached the max_threads_per_topic
            if topic.max_human_users_per_thread == 1:
                if topic_thread_count >= topic.max_threads_per_topic:
                    return True, 'This topic has exceeded maximum permissible threads'
            else:
                # If the user is entering a multi-user chatroom,
                # then we can still possibly enter the room if max_threads_per_topic is reached
                # (Because there might be a thread with less than max_human_users_per_thread number of users)
                if topic_thread_count > topic.max_threads_per_topic:
                    return True, 'This topic has exceeded maximum permissible threads'
                elif topic_thread_count == topic.max_threads_per_topic:
                    # Check if there is a thread with less than max_human_users_per_thread
                    # If so, allow the user to enter the thread
                    threads_under_this_topic = ChatThread.query.filter(ChatThread.topic_id == topic.id).all()
                    for thr in threads_under_this_topic:
                        humans = [user for user in thr.users if user.role == User.ROLE_HUMAN]
                        human_moderators = [user for user in thr.users if user.role == User.ROLE_HUMAN_MODERATOR]
                        if len(humans) + len(human_moderators) < topic.max_human_users_per_thread:
                            return False, ''
                    return True, 'This topic has exceeded maximum permissible threads'
        return False, ''

    def get_topics(self):
        return ChatTopic.query.all()

    def get_user_threads(self, user):
        return ChatThread.query.join(User, ChatThread.users).filter(User.id==user.id).all()

    def get_topic(self, topic_id):
        return ChatTopic.query.get(topic_id)

    def get_thread_for_topic(self, user, topic: ChatTopic, create_if_missing=True,
                             ext_id=None, ext_src=None, data=None) -> Optional[ChatThread]:
        """
        Get the thread for the given topic and given user.
        Since one user can only participate one thread of the same topic (task), with the given topic(task) and user,
        there is only one thread that can be returned.

        If there's no thread for the given topic and user (i.e., user first time clicking this topic),
        create a new thread if create_if_missing is True.
        """

        # log.info('data is: ', data)
        log.info(f'topic.human_moderator is: {topic.human_moderator}')

        if topic.human_moderator == 'yes' and data is not None and data.get(ext_src) is not None:
            cur_user_is_qualified = self.crowd_service.is_worker_qualified(user_worker_id=user.id,
                                                                           qual_name='human_moderator_qualification')

            if cur_user_is_qualified:
                log.info(f"Assign human moderator role to worker_id: {user.id}")
                user.role = User.ROLE_HUMAN_MODERATOR
            else:
                log.info(f"Not Assign human moderator role to worker_id: {user.id}")

        topic_threads = ChatThread.query.filter_by(topic_id=topic.id).all()
        # TODO: appply this second filter directly into sqlalchemy
        thread = None
        for tt in topic_threads:
            if any(user.id == tu.id for tu in tt.users):
                log.info('Topic thread already exists; reusing it')
                thread = tt
                break

            # if tt.human_user_2 is None or tt.human_user_2 == '':
            human_moderators = [user for user in tt.users if user.role == User.ROLE_HUMAN_MODERATOR]
            humans = [user for user in tt.users if user.role == User.ROLE_HUMAN]

            # if tt.need_moderator_bot and user.role == User.ROLE_HUMAN_MODERATOR:
                # print("Current chat thread does not need a human moderator, topic id: ", topic.id, ' user.role:', user.role)
                # continue

            if topic.human_moderator == 'yes' and len(human_moderators) > 0 and user.role == User.ROLE_HUMAN_MODERATOR:
                log.info("More than one human moderator not allowed, topic id: ", topic.id)
                continue

            if len(humans) + len(human_moderators) < topic.max_human_users_per_thread:
                # Mark the thread as "is being created".
                # This is to prevent other users from joining the thread at the same time.
                if tt.thread_state == 1:
                    log.error("thread is being created")
                    return None

                log.info('human_user_2 join thread!')

                # store speakers id
                chat_topic = ChatTopic.query.get(tt.topic_id)
                loaded_users = [speaker_id for speaker_id in chat_topic.data['conversation']]
                speakers = [cur_user.get('speaker_id') for cur_user in loaded_users]

                if topic.human_moderator == 'yes' and user.role == User.ROLE_HUMAN_MODERATOR:
                    # tt.need_moderator_bot = False
                    tt.speakers[user.id] = 'Moderator'
                elif topic.human_moderator == 'yes' and len(human_moderators) == 1:
                    tt.speakers[user.id] = speakers[-1]
                else:
                    i = -2
                    while len(speakers) + i >= 0:
                        if speakers[i] != speakers[-1]:
                            # user.name = speakers[i]
                            tt.speakers[user.id] = speakers[i]
                            # tt.user_2nd = user.id
                            # tt.speaker_2nd = speakers[i]
                            break
                        else:
                            i -= 1

                tt.assignment_id_dict[user.id] = ext_id
                if tt.data.get(ext_src) is not None:
                    tt.submit_url_dict[user.id] = tt.data.get(ext_src).get('submit_url')

                # user.name = speakers[-2]
                log.info(f'2nd user is: {user.id}, 2nd speaker is: {tt.speakers[user.id]}')

                tt.users.append(user)
                # tt.users.append(self.bot_user)
                # tt.users.append(self.context_user)
                # tt.human_user_2 = user.id

                tt.flag_speakers_modified()
                tt.flag_assignment_id_dict_modified()
                tt.flag_submit_url_dict_modified()
                db.session.merge(tt)
                db.session.flush()
                db.session.commit()

                thread = tt
                break

        if not thread and create_if_missing:
            log.info(f'creating a thread: user: {user.id} topic: {topic.id}')
            data = data or {}
            # If there is no data from input, we directly use the data from the topic
            # If there is data, we shouldn't update it with the topic data, otherwise the 'ext_src' might be overridden
            if not data:
                data.update(topic.data)
            thread = ChatThread(topic_id=topic.id, ext_id=ext_id, ext_src=ext_src, data=data, engine=topic.endpoint,
                                persona_id=topic.persona_id, max_threads_per_topic=topic.max_threads_per_topic,
                                max_turns_per_thread=topic.max_turns_per_thread, human_moderator=topic.human_moderator,
                                reward=topic.reward, max_human_users_per_thread=topic.max_human_users_per_thread)

            chat_topic = ChatTopic.query.get(thread.topic_id)
            loaded_users = [speaker_id for speaker_id in chat_topic.data['conversation']]
            speakers = [cur_user.get('speaker_id') for cur_user in loaded_users]

            if thread.human_moderator == 'yes':
                thread.need_moderator_bot = False
                log.info(topic.id, 'does not need a moderator bot')
            else:
                thread.need_moderator_bot = True
                log.info(topic.id, 'needs a moderator bot')

            # user.name = speakers[-1]
            if thread.speakers is None:
                thread.speakers = {}

            if thread.assignment_id_dict is None:
                thread.assignment_id_dict = {}

            if thread.submit_url_dict is None:
                thread.submit_url_dict = {}

            if topic.human_moderator == 'yes' and user.role == User.ROLE_HUMAN_MODERATOR:
                # thread.need_moderator_bot = False
                thread.speakers[user.id] = 'Moderator'
            else:
                thread.speakers[user.id] = speakers[-1]
                # thread.user_1st = user.id
                # thread.speaker_1st = speakers[-1]

            thread.assignment_id_dict[user.id] = ext_id
            if data.get(ext_src):
                thread.submit_url_dict[user.id] = data.get(ext_src).get('submit_url')

            thread.thread_state = 1
            log.info("Set thread state to 1")
            log.info(f'1st user is: {user.id}, 1st speaker is: {thread.speakers[user.id]}')

            thread.users.append(user)
            thread.users.append(self.bot_user)
            thread.users.append(self.context_user)

            thread.human_user_1 = user.id

            db.session.add(thread)
            db.session.flush()  # flush it to get thread_id
            for m in topic.data['conversation']:
                # assumption: messages are pre-transformed to reduce wait times
                text = m['text']
                data = dict(text_orig=m.get('text_orig'),
                            speaker_id=m.get('speaker_id'),
                            fake_start=True)
                msg = ChatMessage(text=text, user_id=self.context_user.id, thread_id=thread.id, is_seed=True, data=data)
                db.session.add(msg)
                thread.messages.append(msg)
            thread.thread_state = 2
            
            # if moderator: 
            if topic.human_moderator == 'yes':
                log.info("Set thread state to 2")
                
            db.session.merge(thread)
            db.session.flush()
            db.session.commit()
        return thread

    def get_thread(self, thread_id) -> Optional[ChatThread]:
        result = ChatThread.query.get(thread_id)
        result.messages = sorted(result.messages, key=lambda x: x.id)
        return result

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

        return {tid: count for tid, count in thread_counts if ChatTopic.query.get(tid)}

    def get_thread_counts_of_super_topic(self, episode_done=True) -> Mapping[str, int]:
        """
        Based on the get_thread_counts func, we want to get the thread count of each super topic
        @param episode_done: whether you want to consider the completed or uncompleted threads
        @return: a dict containing the thread count of each super topic.
        """
        tmp_res = self.get_thread_counts(episode_done)
        all_topics = ChatTopic.query.all()
        topic_thread_counts = [(topic, tmp_res.get(topic.id, 0)) for topic in all_topics]
        super_topic_thread_counts_dict = {}
        for topic, count in topic_thread_counts:
            cur_super_topic = SuperTopic.query.get(topic.super_topic_id)
            super_topic_thread_counts_dict[cur_super_topic.id] = \
                super_topic_thread_counts_dict.get(cur_super_topic.id, 0) + count
        return super_topic_thread_counts_dict

    def update_thread_ratings(self, thread: ChatThread, ratings: dict, user_id: str):
        if thread.data is None:
            thread.data = {}
        # Initialize ratings dict
        if thread.data.get('ratings') is None:
            thread.data['ratings'] = {}
        # Update ratings dict based on the user_id
        thread.data.get('ratings').update(dict([[user_id, ratings]]))

        if len(thread.data.get('ratings')) == thread.max_human_users_per_thread:
            thread.data.update(dict(rating_done=True))
            thread.episode_done = True

        thread.flag_data_modified()
        db.session.merge(thread)
        db.session.flush()
        db.session.commit()
        if len(thread.data.get('ratings')) == thread.max_human_users_per_thread:
            self.exporter.export_thread(thread, rating_questions=self.ratings, engine=thread.engine,
                                        persona_id=thread.persona_id,
                                        max_threads_per_topic=thread.max_threads_per_topic,
                                        max_turns_per_thread=thread.max_turns_per_thread,
                                        human_moderator=thread.human_moderator, reward=thread.reward)

    # @functools.lru_cache(maxsize=256)
    def get_dialog_man(self, thread: ChatThread) -> DialogBotChatManager:
        cur_bot_agent = self.bot_agent_dict[(thread.engine, thread.persona_id)]
        return DialogBotChatManager(thread=thread,
                                    bot_agent=cur_bot_agent,
                                    max_turns=thread.max_turns_per_thread,
                                    bot_transforms=self.bot_transforms,
                                    human_transforms=self.human_transforms)

    def new_message(self, msg: ChatMessage, thread: ChatThread) -> tuple[ChatMessage, bool]:
        dialog = self.get_dialog_man(thread)
        reply, episode_done = dialog.observe_and_reply_message(thread, msg)
        return reply, episode_done

    def current_thread(self, thread:ChatThread) -> tuple[ChatMessage, bool]: 
        dialog = self.get_dialog_man(thread)
        reply, episode_done = dialog.bot_init_reply(thread)
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
                max_assignments=topic.max_threads_per_topic,
                reward=topic.reward,
            )
            
            ext_src = self.crowd_service.name
            if ext_id:
                topic.ext_id = ext_id
                topic.ext_src = ext_src
                topic.data[ext_src] = dict(
                    is_sandbox = self.crowd_service.is_sandbox,
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

    # @staticmethod
    def delete_topic(self, topic: ChatTopic):
        db.session.delete(topic)
        db.session.commit()

    def generate_limits(self, topic: ChatTopic):
        limit_dict = {
            'max_threads_per_user': topic.max_threads_per_user,
            'max_threads_per_topic': topic.max_threads_per_topic,
            'max_turns_per_thread': topic.max_turns_per_thread,
            'reward': topic.reward
        }
        return limit_dict
