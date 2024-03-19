from typing import Dict, List, Optional, Any, Tuple
import hashlib
from sqlalchemy import orm, sql

from . import db, log

"""
# Docs for flask-SQLAlchemy https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/
SqlAlchemy  https://docs.sqlalchemy.org/en/14/

flask-sqlalchemy binds many of sqlalchemy's classes into db.* namespace.
Some important classes:
 - Column https://docs.sqlalchemy.org/en/14/core/metadata.html?highlight=column#sqlalchemy.schema.Column 

TG's comments:
  We are using data column as JSON type -- which is nice to store any arbitrary key=value pairs.
  Catch, I believe, is JSON not indexable (atleast without some complications).
  So reverse look up of record based on a key=value in JSON field may not be the
"""


def save_to_db(obj):
    db.session.add(obj)
    db.session.flush()
    db.session.commit()


def update_in_db(obj):
    db.session.merge(obj)
    db.session.flush()
    db.session.commit()


class BaseModel(db.Model):
    __abstract__ = True

    id: int = db.Column(db.Integer, primary_key=True)
    data: str = db.Column(db.JSON(), nullable=False, server_default='{}')
    time_created = db.Column(db.DateTime(timezone=True),
                             server_default=sql.func.now())
    time_updated = db.Column(db.DateTime(timezone=True),
                             onupdate=sql.func.now())

    def __eq__(self, other):
        """
        Checks the equality of two objects using `get_id`.
        """
        try:
            return self._primary_key == other._primary_key
        except:
            return False

    @property
    def _primary_key(self):
        return self.id

    def __hash__(self) -> int:
        return hash(self._primary_key)

    def as_dict(self) -> Dict[str, Any]:
        return dict(
            id=self.id,
            data=self.data if self.data is not None else dict(),
            time_created=self.time_created and self.time_created.isoformat(),
            time_updated=self.time_updated and self.time_updated.isoformat(),
        )

    def flag_data_modified(self):
        # seql alchemy isnt reliable in recognising modifications to JSON, so we explicitely tell it
        orm.attributes.flag_modified(self, 'data')


class BaseModelWithExternal(BaseModel):
    __abstract__ = True

    ext_id: str = db.Column(db.String(64), nullable=True)
    ext_src: str = db.Column(db.String(32), nullable=True)

    # Example, for MTurk, ext_src=mturk;
    #       ext_id= workerId for user,
    #       HITID for ChatTopic,
    #       AssignmentID for ChatThread

    def as_dict(self) -> Dict[str, Any]:
        return super().as_dict() | dict(ext_id=self.ext_id, ext_src=self.ext_src)


class User(BaseModelWithExternal):
    __tablename__ = 'user'

    ANONYMOUS = 'Anonymous'
    ROLE_BOT = 'bot'
    ROLE_HUMAN = 'human'
    ROLE_ADMIN = 'admin'
    ROLE_HIDDEN = 'hidden'
    ROLE_HUMAN_MODERATOR = 'human_moderator'

    id: str = db.Column(db.String(31), primary_key=True)
    name: str = db.Column(db.String(100), nullable=False)
    secret: str = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, server_default=sql.expression.true(),
                       nullable=False)

    last_active = db.Column(db.DateTime(timezone=True), nullable=True)
    email: str = db.Column(db.String(31), nullable=True)
    # eg: bot, human, admin
    role: str = db.Column(db.String(30), nullable=True)

    @property
    def is_active(self):
        return self.active

    @property
    def is_authenticated(self):
        return self.is_active

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def is_bot(self):
        return self.role == self.ROLE_BOT

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return self.id

    def __eq__(self, other):
        """
        Checks the equality of two objects using `get_id`.
        """
        return self.get_id() == other.get_id()

    @classmethod
    def _hash(cls, secret):
        return hashlib.sha3_256(secret.encode()).hexdigest()

    def verify_secret(self, secret):
        if not self.secret:  # empty secret => login disabled
            return False
        return self.secret == self._hash(secret)

    @classmethod
    def get(cls, id: str) -> Optional['User']:
        if not id:
            return None
        try:
            return cls.query.get(id)
        except Exception as e:
            log.warning(e)
            return None

    @classmethod
    def create_new(cls, id: str, secret: str, name: str = None,
                   role: str = None, data=None, ext_id=None, ext_src=None):
        name = name or cls.ANONYMOUS
        role = role or cls.ROLE_HUMAN
        user = User(id=id, secret=cls._hash(secret), name=name, role=role, data=data, ext_id=ext_id, ext_src=ext_src)
        log.info(f'Creating User {user.id}')
        db.session.add(user)
        db.session.commit()
        return cls.get(user.id)

    def as_dict(self):
        return super().as_dict() | dict(
            id=self.id,
            name=self.name,
            role=self.role,
        )


class ChatMessage(BaseModelWithExternal):
    __tablename__ = 'message'

    id: int = db.Column(db.Integer, primary_key=True)
    text: str = db.Column(db.String(2048), nullable=False)
    is_seed: bool = db.Column(db.Boolean)

    user_id: str = db.Column(
        db.String(31), db.ForeignKey('user.id'), nullable=False)
    thread_id: int = db.Column(
        db.Integer, db.ForeignKey('thread.id'), nullable=False)

    @property
    def time(self):
        return self.time_created

    def as_dict(self):
        return super().as_dict() | dict(
            text=self.text,
            is_seed=self.is_seed,
            user_id=self.user_id,
            thread_id=self.thread_id,
        )

    def save_message_to_db(self):
        save_to_db(self)


UserThread = db.Table(
    'user_thread',
    db.Column('user_id', db.String(31), db.ForeignKey('user.id'),
              primary_key=True),
    db.Column('thread_id', db.Integer, db.ForeignKey('thread.id'),
              primary_key=True)
)


class ChatThread(BaseModelWithExternal):
    __tablename__ = 'thread'

    id: int = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.String(31),
                         db.ForeignKey('topic.id'),
                         nullable=False)
    episode_done = db.Column(db.Boolean,
                             server_default=sql.expression.false(),
                             nullable=False)
    # one-to-many
    messages: List[ChatMessage] = db.relationship(
        'ChatMessage', backref='thread', lazy=False, uselist=True)
    # many-to-many : https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/#many-to-many-relationships
    users: List[User] = db.relationship(
        'User', secondary=UserThread, lazy='subquery',
        backref=db.backref('threads', lazy=True))

    # key: userid;  value: speaker_id
    speakers = db.Column(db.JSON(), nullable=False, server_default='{}')
    # key: userid;  value: assignment_id
    # Originally, ChatThread.ext_id is used to store the Assignment_Id.
    # However, in a multi-user chat, there are multiple assignments, and each user needs their unique assignment_id
    # to get credits. Thus we need to store the assignment_id for each user.
    assignment_id_dict = db.Column(db.JSON(), nullable=False, server_default='{}')
    # key: userid;  value: submit_url
    submit_url_dict = db.Column(db.JSON(), nullable=False, server_default='{}')

    thread_state: int = db.Column(db.Integer, nullable=False)

    need_moderator_bot = db.Column(db.Boolean, server_default=sql.expression.true(), nullable=False)

    speak_order = db.Column(db.JSON(), nullable=False, server_default='[]')

    current_speaker = db.Column(db.String(64), nullable=True)

    current_speaker_idx = db.Column(db.Integer, nullable=False, server_default='0')

    current_turns = db.Column(db.Integer, nullable=False, server_default='0')

    remaining_turns = db.Column(db.Integer, nullable=True)

    # We include the following rows because the topic may be deleted.
    # But we still need to see the content of one thread even if the corresponding
    # topic is gone.
    bot_name: str = db.Column(db.String(64), nullable=True)
    engine: str = db.Column(db.String(64), nullable=True)
    persona_id: str = db.Column(db.String(64), nullable=True)
    max_threads_per_topic: int = db.Column(db.Integer, nullable=True)
    max_turns_per_thread: int = db.Column(db.Integer, nullable=True)
    max_human_users_per_thread: int = db.Column(db.Integer, nullable=True)
    human_moderator: str = db.Column(db.String(32), nullable=True)
    reward: str = db.Column(db.String(32), nullable=True)
    parameters: str = db.Column(db.JSON(), nullable=False, server_default='{}')

    __avoid_double_create = set()

    @classmethod
    def get_thread_by_id(cls, thread_id: str) -> Optional['ChatThread']:
        """
        Get a thread instance by thread id.
        :param thread_id: the id of the thread
        :return: the chat thread instance
        """
        thread = ChatThread.query.get(thread_id)
        return thread

    @classmethod
    def get_next_vacancy_thread_for_topic(cls, topic: 'ChatTopic') -> Optional['ChatThread']:
        """
        Get a thread instance that has vacancy.
        :return: the chat thread instance
        """
        threads = ChatThread.query.filter(
            ChatThread.topic_id == topic.id
        ).all()
        for thread in threads:
            if len([u for u in thread.users
                    if u.role in [User.ROLE_HUMAN, User.ROLE_HUMAN_MODERATOR]]) < thread.max_human_users_per_thread:
                return thread

    @classmethod
    def get_thread_by_topic_and_user(cls, topic: 'ChatTopic', user: User) -> Optional['ChatThread']:
        """
        Query a thread instance of a topic that the user can be in (or already in).
        :param topic: the topic of the chat thread
        :param user: the user that the chat thread involves
        :return: a chat thread instance
        """
        threads = ChatThread.query.filter(
            ChatThread.topic_id == topic.id
        ).all()
        for thread in threads:
            if user in thread.users:
                return thread

    @classmethod
    def create_thread_of_topic(cls, topic: 'ChatTopic', bot_name: str = 'gpt') -> Optional['ChatThread']:
        """
        Create a new chat thread.
        :param topic: the topic of the chat thread
        :param bot_name: the bot to user
        :return: a chat thread instance if success, or None
        """
        from .utils import get_speak_order

        if topic.id in cls.__avoid_double_create:
            return None

        cls.__avoid_double_create.add(topic.id)

        speak_order = get_speak_order(topic)

        thread = ChatThread(
            topic_id=topic.id,
            data=topic.data,
            bot_name=bot_name,
            engine=topic.endpoint,
            persona_id=topic.persona_id,
            max_turns_per_thread=topic.max_turns_per_thread,
            human_moderator=topic.human_moderator,
            reward=topic.reward,
            max_threads_per_topic=topic.max_threads_per_topic,
            max_human_users_per_thread=topic.max_human_users_per_thread,
            parameters=topic.parameters,
            need_moderator_bot=bool(topic.human_moderator != 'yes'),
            speak_order=speak_order,
            current_speaker_idx=0,
            current_speaker=speak_order[0],
            remaining_turns=topic.max_turns_per_thread,
        )

        thread.thread_state = 1

        db.session.add(thread)
        db.session.flush()

        for cv in topic.data['conversation']:
            text = cv['text']
            data = dict(
                text_orig=cv.get('text_orig'),
                speaker_id=cv.get('speaker_id'),
                fake_start=True
            )
            msg = ChatMessage(thread_id=thread.id, user_id='context', is_seed=True, text=text, data=data)
            save_to_db(msg)
            thread.messages.append(msg)

        thread.thread_state = 2

        db.session.commit()

        cls.__avoid_double_create.remove(topic.id)
        return thread

    def set_external_info_for_user(self, user: User, ext_id=None, ext_src=None, data=None):
        if self.ext_id is None:
            self.ext_id = ext_id

        if self.ext_src is None:
            self.ext_src = ext_src

        if self.assignment_id_dict is None:
            self.assignment_id_dict = {}

        self.assignment_id_dict[user.id] = ext_id

        if self.submit_url_dict is None:
            self.submit_url_dict = {}

        if data and data.get(ext_src) is not None:
            self.submit_url_dict[user.id] = data.get(ext_src).get('submit_url')

        if user not in self.users:
            self.users.append(user)

        self.flag_speakers_modified()
        self.flag_assignment_id_dict_modified()
        self.flag_submit_url_dict_modified()

    def add_user(self, user: User, role: str = None):
        if user not in self.users:
            self.users.append(user)
        if role is not None:
            speaker_dict = dict(self.speakers)
            speaker_dict[user.id] = role
            self.speakers = speaker_dict
            user.role = User.ROLE_HUMAN_MODERATOR if role == 'Moderator' else User.ROLE_HUMAN

    def append_message(self, message: ChatMessage) -> Tuple[bool, str]:
        """
        Append a message to the thread. Maintain the thread's current speaker.
        :param message: the message to append
        :return: a tuple of (success, info)
        """
        if message.user_id not in [u.id for u in self.users]:
            return False, f'User {message.user_id} not part of thread {self.id}'
        if message.data['speaker_id'] != self.current_speaker:
            return False, f'User {message.user_id} is not current speaker ({self.current_speaker})'

        # Update thread state
        self.current_speaker_idx += 1
        if self.current_speaker_idx >= len(self.speak_order):
            self.current_speaker_idx = 0
            self.current_turns += 1
            self.remaining_turns -= 1
            if self.current_turns >= self.max_turns_per_thread:
                self.episode_done = True

        self.current_speaker = self.speak_order[self.current_speaker_idx]

        self.messages.append(message)

        return True, 'Success'

    def count_turns(self, user: User):
        return sum(msg.user_id == user.id for msg in self.messages)

    def flag_speakers_modified(self):
        # seql alchemy isnt reliable in recognising modifications to JSON, so we explicitely tell it
        orm.attributes.flag_modified(self, 'speakers')

    def flag_assignment_id_dict_modified(self):
        # sql alchemy isn't reliable in recognising modifications to JSON, so we explicitly tell it
        orm.attributes.flag_modified(self, 'assignment_id_dict')

    def flag_submit_url_dict_modified(self):
        orm.attributes.flag_modified(self, 'submit_url_dict')

    def as_dict(self):
        return super().as_dict() | dict(
            topic_id=self.topic_id,
            episode_done=self.episode_done,
            users=[u.as_dict() for u in self.users],
            messages=[m.as_dict() for m in self.messages],
            speakers=self.speakers,
            current_speaker=self.current_speaker,
            current_turns=self.current_turns,
            speak_order=self.speak_order,
            current_speaker_idx=self.current_speaker_idx,
            need_moderator_bot=self.need_moderator_bot,
            max_turns_per_thread=self.max_turns_per_thread,
        )

    @property
    def socket_name(self):
        return f'sock4thread_{self.id}'

    def update_thread_in_db(self):
        update_in_db(self)

    def save_thread_to_db(self):
        save_to_db(self)


class SuperTopic(BaseModelWithExternal):
    """
    A model represents a "macro“-topic. Each topic has an one-to-one relationship with one Mturk assignment.
    So, by introducing a super_topic model, we are able to launch multiple assignments(topics) with one super_topic.
    """
    __tablename__ = 'super_topic'

    id: str = db.Column(db.String(32), primary_key=True)  # redefine id as str
    name: str = db.Column(db.String(100), nullable=False)
    # A super topic contains a list of topics.
    topics = db.relationship('ChatTopic', backref='super_topic', lazy=True)
    next_task_id: int = db.Column(db.Integer)

    def as_dict(self):
        return super().as_dict() | dict(name=self.name)


class ChatTopic(BaseModelWithExternal):
    """
    A model represents a task. Each topic has an one-to-one relationship with one Mturk assignment.
    """

    __tablename__ = 'topic'

    id: str = db.Column(db.String(64), primary_key=True)  # redefine id as str
    name: str = db.Column(db.String(100), nullable=False)
    super_topic_id: str = db.Column(db.String(32), db.ForeignKey('super_topic.id'), nullable=True)
    endpoint: str = db.Column(db.String(64), nullable=False)
    persona_id: str = db.Column(db.String(64), nullable=False)
    max_threads_per_topic: int = db.Column(db.Integer, nullable=False)
    max_turns_per_thread: int = db.Column(db.Integer, nullable=False)
    max_human_users_per_thread: int = db.Column(db.Integer, nullable=False)
    human_moderator: str = db.Column(db.String(32), nullable=True)
    reward: str = db.Column(db.String(32), nullable=False)
    parameters: str = db.Column(db.JSON(), nullable=False, server_default='{}')

    def as_dict(self):
        return super().as_dict() | dict(name=self.name)

    @classmethod
    def create_new(cls, super_topic: SuperTopic, endpoint, persona_id, max_threads_per_topic,
                   max_turns_per_thread, max_human_users_per_thread, human_moderator, reward, parameters):
        cur_task_id = super_topic.next_task_id
        cur_id = f'{super_topic.id}_{cur_task_id:03d}'
        cur_name = f'{super_topic.name}_{cur_task_id:03d}'

        # update target user ids: 

        topic = ChatTopic(id=cur_id, name=cur_name, data=super_topic.data, super_topic_id=super_topic.id,
                          ext_id=super_topic.ext_id, ext_src=super_topic.ext_src, endpoint=endpoint,
                          persona_id=persona_id, max_threads_per_topic=max_threads_per_topic,
                          max_turns_per_thread=max_turns_per_thread,
                          max_human_users_per_thread=max_human_users_per_thread,
                          human_moderator=human_moderator,
                          reward=reward,
                          parameters=parameters)
        # log.info(f'Creating New Task {topic.id}')
        super_topic.next_task_id += 1
        db.session.add(topic)
        db.session.commit()
        return cls.query.get(topic.id)

    @classmethod
    def get_topics_user_not_done(cls, user) -> List['ChatTopic']:
        """
        Get all topics that user has not done
        :param user:
        :return:
        """
        topics = ChatTopic.query.all()
        res = []
        for topic in topics:
            thread = ChatThread.get_thread_by_topic_and_user(topic, user)
            if thread is None:
                res.append(topic)
        return res
