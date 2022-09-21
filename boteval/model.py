from typing import List, Optional
from dataclasses import dataclass, field
import time
import hashlib
from dataclasses import dataclass
from flask_login import UserMixin

from sqlalchemy import orm, sql
import json

from . import db, log

# Docs for flask SQLAlchemy https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/

UserThread = db.Table('user_thread',
                      db.Column('user_id', db.String(31), db.ForeignKey(
                          'user.id'), primary_key=True),
                      db.Column('thread_id', db.Integer, db.ForeignKey(
                          'thread.id'), primary_key=True)
                      )


class User(db.Model):

    __tablename__ = 'user'

    ANONYMOUS = 'Anonymous'
    ROLE_BOT = 'bot'
    ROLE_HUMAN = 'human'
    ROLE_ADMIN = 'admin'
    ROLE_HIDDEN = 'hidden'

    id: str = db.Column(db.String(31), primary_key=True)
    name: str = db.Column(db.String(100), nullable=False)
    secret: str = db.Column(db.String(100), nullable=False)
    time_created = db.Column(db.DateTime(timezone=True),
                             server_default=sql.func.now())
    time_updated = db.Column(db.DateTime(
        timezone=True), onupdate=sql.func.now())

    email: str = db.Column(db.String(31), nullable=True)
    # eg: bot, human, admin
    role: str = db.Column(db.String(30), nullable=True)
    data: str = db.Column(db.JSON(), nullable=False, server_default='{}')

    @property
    def is_active(self):
        return True

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
    def create_new(cls, id: str, secret: str, name: str = None, role: str = None, data=None):
        name = name or cls.ANONYMOUS
        role = role or cls.ROLE_HUMAN
        user = User(id=id, secret=cls._hash(secret), name=name, role=role, data=data)
        log.info(f'Creating User {user.id}')
        db.session.add(user)
        db.session.commit()
        return cls.get(user.id)

    def as_dict(self):
        return dict(
            id=self.id,
            name= self.name,
            time_created=self.time_created and self.time_created.isoformat(),
            time_updated=self.time_updated and self.time_updated.isoformat(),
            role=self.role,
            data=self.data
        )

class ChatMessage(db.Model):

    __tablename__ = 'message'

    id: int = db.Column(db.Integer, primary_key=True)
    text: str = db.Column(db.String(2048), nullable=False)
    user_id: str = db.Column(
        db.String(31), db.ForeignKey('user.id'), nullable=False)
    thread_id: int = db.Column(
        db.Integer, db.ForeignKey('thread.id'), nullable=False)
    time = db.Column(db.DateTime(timezone=True), server_default=sql.func.now())
    data: str = db.Column(db.JSON(), nullable=False, server_default='{}')

    def as_dict(self):
        return dict(
            id=self.id,
            text=self.text,
            user_id=self.user_id,
            thread_id=self.thread_id,
            time=self.time and self.time.isoformat(),
            data=self.data
        )

class ChatThread(db.Model):

    __tablename__ = 'thread'

    id: int = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.String(31), db.ForeignKey(
        'topic.id'), nullable=False)
    episode_done = db.Column(
        db.Boolean, server_default=sql.expression.false(), nullable=False)
    # one-to-many
    messages: List[ChatMessage] = db.relationship(
        'ChatMessage', backref='thread', lazy=False, uselist=True)
    # many-to-many : https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/#many-to-many-relationships
    users: List[User] = db.relationship('User', secondary=UserThread, lazy='subquery',
                                        backref=db.backref('threads', lazy=True))

    time_created = db.Column(db.DateTime(timezone=True),
                             server_default=sql.func.now())
    time_updated = db.Column(db.DateTime(
        timezone=True), onupdate=sql.func.now())
    data: str = db.Column(db.JSON(), nullable=False, server_default='{}')

    def count_turns(self, user: User):
        return sum(msg.user_id == user.id for msg in self.messages)

    def as_dict(self):
        return dict(
            id=self.id,
            topic_id=self.topic_id,
            episode_done=self.episode_done,
            users=[u.as_dict() for u in self.users],
            messages=[m.as_dict() for m in self.messages],
            time_created=self.time_created and self.time_created.isoformat(),
            time_updated=self.time_updated and self.time_updated.isoformat(),
            data=self.data
        )


class ChatTopic(db.Model):

    __tablename__ = 'topic'

    id: str = db.Column(db.String(32), primary_key=True)
    name: str = db.Column(db.String(100), nullable=False)
    #data: str = db.Column(db.Text, nullable=False)
    time_created = db.Column(db.DateTime(timezone=True),
                             server_default=sql.func.now())
    time_updated = db.Column(db.DateTime(timezone=True),
                             onupdate=sql.func.now())
    data: str = db.Column(db.JSON(), nullable=False, server_default='{}')

    def as_dict(self):
        return dict(
            id=self.id,
            name=self.name,
            time_created=self.time_created and self.time_created.isoformat(),
            time_updated=self.time_updated and self.time_updated.isoformat(),
            data=self.data
        )
