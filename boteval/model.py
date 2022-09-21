from enum import unique
from typing import Dict, List, Mapping, Optional, Any
from dataclasses import dataclass, field
import time
import hashlib
import abc
from dataclasses import dataclass

from sqlalchemy import orm, sql
import json

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
            id = self.id,
            data = self.data,
            time_created=self.time_created and self.time_created.isoformat(),
            time_updated=self.time_updated and self.time_updated.isoformat(),
        )


class BaseModelWithExternal(BaseModel):

    __abstract__ = True

    ext_id: str = db.Column(db.String(64), nullable=True)
    ext_src: str = db.Column(db.String(32), nullable=True)

    #Example, for MTurk, ext_src=mturk;
    #       ext_id= workerId for user,
    #       HITID for ChatTopic,
    #       AssignmentID for ChatThread

    def as_dict(self) -> Dict[str, Any]:
        return super().as_dict() | dict(ext_id = self.ext_id, ext_src = self.ext_src)



class User(BaseModelWithExternal):

    __tablename__ = 'user'

    ANONYMOUS = 'Anonymous'
    ROLE_BOT = 'bot'
    ROLE_HUMAN = 'human'
    ROLE_ADMIN = 'admin'
    ROLE_HIDDEN = 'hidden'

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
                   role: str = None, data=None):
        name = name or cls.ANONYMOUS
        role = role or cls.ROLE_HUMAN
        user = User(id=id, secret=cls._hash(secret), name=name, role=role, data=data)
        log.info(f'Creating User {user.id}')
        db.session.add(user)
        db.session.commit()
        return cls.get(user.id)

    def as_dict(self):
        return super().as_dict() | dict(
            id=self.id,
            name= self.name,
            role=self.role,
        )


class ChatMessage(BaseModelWithExternal):

    __tablename__ = 'message'

    id: int = db.Column(db.Integer, primary_key=True)
    text: str = db.Column(db.String(2048), nullable=False)
    user_id: str = db.Column(
        db.String(31), db.ForeignKey('user.id'), nullable=False)
    thread_id: int = db.Column(
        db.Integer, db.ForeignKey('thread.id'), nullable=False)

    @property
    def time(self):
        return self.time_created

    def as_dict(self):
        return super().as_dict() |  dict(
            text=self.text,
            user_id=self.user_id,
            thread_id=self.thread_id,
        )

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

    def count_turns(self, user: User):
        return sum(msg.user_id == user.id for msg in self.messages)

    def as_dict(self):
        return super().as_dict() | dict(
            topic_id=self.topic_id,
            episode_done=self.episode_done,
            users=[u.as_dict() for u in self.users],
            messages=[m.as_dict() for m in self.messages]
        )


class ChatTopic(BaseModelWithExternal):

    __tablename__ = 'topic'

    id: str = db.Column(db.String(32), primary_key=True)  # redefine id as str
    name: str = db.Column(db.String(100), nullable=False)

    def as_dict(self):
        return super().as_dict() | dict(name=self.name)
