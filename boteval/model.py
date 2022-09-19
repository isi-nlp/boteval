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



class JsonExtraMixin:
    """
     a field named 'extra' is injected into all Models that extends this.
     The goal is not to use this 'extra' field, but in the unforeseen future
     you want to store some extra data which is hard to fit into RDBMS schema
     then you may use this.

     I have used this in ChatTopic where I store seed chat context
    """

    def get_extra(self):
        extra = self.extra
        if isinstance(extra, str):
            extra = json.loads(extra)
        return extra

    def set_extra(self, extra):
        if not isinstance(extra, str):
            extra = json.dumps(extra, ensure_ascii=False)
        self.extra = extra


class User(db.Model, JsonExtraMixin):

    __tablename__ = 'user'

    ANONYMOUS = 'Anonymous'
    ROLE_BOT = 'bot'
    ROLE_HUMAN = 'human'
    ROLE_ADMIN = 'admin'

    id: str = db.Column(db.String(31), primary_key=True)
    name: str = db.Column(db.String(100), nullable=False)
    secret: str = db.Column(db.String(100), nullable=False)
    time_created = db.Column(db.DateTime(timezone=True), server_default=func.now())
    time_updated = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    role: str = db.Column(db.String(30), nullable=True)  # eg: bot, human, admin
    extra: str = db.Column(db.Text, nullable=True)

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
    def create_new(cls, id: str, secret: str, name: str=None, role: str=None):
        name = name or cls.ANONYMOUS
        role =  role or cls.ROLE_HUMAN
        user = User(id=id, secret=cls._hash(secret), name=name, role=role)
        log.info(f'Creating User {user.id}')
        db.session.add(user)
        db.session.commit()
        return cls.get(user.id)

class ChatMessage(db.Model, JsonExtraMixin):

    __tablename__ = 'message'

    id: int = db.Column(db.Integer, primary_key=True)
    text: str = db.Column(db.String(2048), nullable=False)
    user_id: str = db.Column(db.String(31), db.ForeignKey('user.id'), nullable=False)
    thread_id: int = db.Column(db.Integer, db.ForeignKey('thread.id'), nullable=False)
    time = db.Column(db.DateTime(timezone=True), server_default=func.now())
    extra: str = db.Column(db.Text, nullable=True)


class ChatThread(db.Model, JsonExtraMixin):

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
    extra: str = db.Column(db.Text, nullable=True)


class ChatTopic(db.Model, JsonExtraMixin):

    __tablename__ = 'topic'

    id: str = db.Column(db.String(32), primary_key=True)
    name: str = db.Column(db.String(100), nullable=False)
    #data: str = db.Column(db.Text, nullable=False)
    time_created = db.Column(db.DateTime(timezone=True), server_default=func.now())
    time_updated = db.Column(db.DateTime(timezone=True), onupdate=func.now())
    extra: str = db.Column(db.Text, nullable=False)

