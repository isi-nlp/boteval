
from .model import User, ChatMessage, ChatThread

class ChatService:

    def make_or_get_chatroom(self, user_id, thread_id):
        user = User.get(user_id)
        assert user

