
from pathlib import Path
import json
from typing import List
from  . import log, db
from .model import ChatTopic, User, ChatMessage, ChatThread, UserThread


class ChatService:

    def __init__(self, config):
        self.config = config

    def load_topics(self, topics_file=None):

        if not topics_file:
            topics_file = Path(self.config['chatbot']['topics_file']).resolve()

        topics_file.exists(), f'{topics_file} not found'

        with open(topics_file, encoding='utf-8') as out:
            topics = json.load(out)
        assert isinstance(topics, list)
        log.info(f'found {len(topics)} topics in {topics_file}')
        if topics:
            objs = []
            for topic in topics:
                obj = ChatTopic.query.get(topic['id'])
                if obj:
                    log.warning(f'Chat topic exisits {topic["id"]}, so skipping')
                    continue
                obj = ChatTopic(id=topic['id'], name=topic['name'], data=json.dumps(topic))
                objs.append(obj)
            if objs:
                log.info(f"Inserting {len(objs)} topics to db")
                db.session.add_all(objs)
                db.session.commit()

    def get_topics(self):
        return ChatTopic.query.all()

    def get_topic(self, topic_id):
        return ChatTopic.query.get(topic_id)

    def get_thread_for_topic(self, user, topic, create_if_missing=True):
        topic_threads = ChatThread.query.filter_by(topic_id=topic.id).all()
        # TODO: appply this second filter directly into sqlalchemy
        thread = None
        for tt in topic_threads:
            if any(user.id == tu.id for tu in tt.users):
                log.info('Topic thread alredy exists; reusing it')
                thread = tt

        if not thread and create_if_missing:
            log.info(f'creating a thread: user: {user.id} topic: {topic.id}')
            thread = ChatThread(topic_id=topic.id)
            thread.users.append(user)
            db.session.add(thread)
            db.session.commit()
        return thread


    def get_threads(self, user: User) -> List[ChatThread]:
        log.info(f'Querying {user.id}')
        threads = UserThread.query.filter(user_id=user.id).all()
        #threads = ChatThread.query.filter_by(user_id=user.id).all()
        log.info(f'Found {len(threads)} threads found')
        return threads





