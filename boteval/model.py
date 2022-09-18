from typing import List, Optional
from dataclasses import dataclass, field
import time
import hashlib
from dataclasses import dataclass
from flask_login import UserMixin
from sqlalchemy.sql import func
from sqlalchemy import orm
import json

from . import db, log

# Docs for flask SQLAlchemy https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/

UserThread = db.Table('user_thread',
    db.Column('user_id', db.String(31), db.ForeignKey('user.id'), primary_key=True),
    db.Column('thread_id', db.Integer, db.ForeignKey('thread.id'), primary_key=True)
)



class User(db.Model):
    __tablename__ = 'user'
    ANONYMOUS = 'Anonymous'

    id: str = db.Column(db.String(31), primary_key=True)
    name: str = db.Column(db.String(100), nullable=False)
    secret: str = db.Column(db.String(100), nullable=False)
    time_created = db.Column(db.DateTime(timezone=True), server_default=func.now())
    time_updated = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    role: str = db.Column(db.String(30), nullable=True)

    # relationships
    #threads = db.relationship('thread', secondary=UserThread, backref='user_threads')

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
        return str(self.id)

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
    def create_new(cls, id: str, secret: str, name: str=None):
        name = name or cls.ANONYMOUS
        user = User(id=id, secret=cls._hash(secret), name=name)
        log.info(f'Creating User {user.id}')
        db.session.add(user)
        db.session.commit()
        return cls.get(user.id)

class ChatMessage(db.Model):
    __tablename__ = 'message'
    id: int = db.Column(db.Integer, primary_key=True)
    text: str = db.Column(db.String(2048), nullable=False)
    time: int =  db.Column(db.Integer, nullable=False)
    user_id: str = db.Column(db.String(31), db.ForeignKey('user.id'), nullable=False)
    thread_id: int = db.Column(db.Integer, db.ForeignKey('thread.id'), nullable=False)
    time_created = db.Column(db.DateTime(timezone=True), server_default=func.now())


class ChatThread(db.Model):

    __tablename__ = 'thread'

    id: int = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.String(31), db.ForeignKey('topic.id'), nullable=False)

    # one-to-many
    messages: List[ChatMessage] = db.relationship('ChatMessage', backref='thread', lazy=False, uselist=True)
    # many-to-many : https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/#many-to-many-relationships 
    users: List[User] = db.relationship('User', secondary=UserThread, lazy='subquery',
                                        backref=db.backref('threads', lazy=True))

    time_created = db.Column(db.DateTime(timezone=True), server_default=func.now())
    time_updated = db.Column(db.DateTime(timezone=True), onupdate=func.now())


class ChatTopic(db.Model):

    __tablename__ = 'topic'

    id: str = db.Column(db.String(32), primary_key=True)
    name: str = db.Column(db.String(100), nullable=False)
    data: str = db.Column(db.Text, nullable=False)
    time_created = db.Column(db.DateTime(timezone=True), server_default=func.now())
    time_updated = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    def get_data(self):
        if isinstance(self.data, str):
            data = json.loads(self.data)
        return data

    def set_data(self, data):
        if not isinstance(data, str):
            self.data = json.dumps(data, ensure_ascii=False)

if False:

    class PrivateChatThread(db.Model):
        """Private chat with the bot (by single user)"""
        __tablename__ = 'private_thread'
        id: int = db.Column(db.Integer, primary_key=True)
        user_id: int = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
        messages: List[ChatMessage] = db.relationship('ChatMessage', backref='messages', lazy=False, uselist=True)
        time_created = db.Column(db.DateTime(timezone=True), server_default=func.now())