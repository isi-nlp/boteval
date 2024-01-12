# import resource
import json
from typing import Tuple, List
import sys
import time
from datetime import datetime

import flask
import flask_login as FL

from . import log, C
from .model import ChatThread, ChatTopic, User

FLOAT_POINTS = 4


def render_template(*args, **kwargs):
    return flask.render_template(*args, environ=C.ENV,
                                 cur_user=FL.current_user, C=C, **kwargs)


# def max_RSS(who=resource.RUSAGE_SELF) -> Tuple[int, str]:
#     """Gets memory usage of current process, maximum so far.
#     Maximum so far, since the system call API doesnt provide "current"
#     :returns (int, str)
#        int is a value from getrusage().ru_maxrss
#        str is human friendly value (best attempt to add right units)
#     """
#     mem = resource.getrusage(who).ru_maxrss
#     h_mem = mem
#     if 'darwin' in sys.platform:  # "man getrusage 2" says we get bytes
#         h_mem /= 10 ** 3  # bytes to kilo
#     unit = 'KB'
#     if h_mem >= 10 ** 3:
#         h_mem /= 10 ** 3  # kilo to mega
#         unit = 'MB'
#     return mem, f'{int(h_mem)}{unit}'


def format_bytes(bytes):
    if bytes >= 10 ** 6:
        return f'{bytes / 10 ** 6:.2f} MB'
    elif bytes >= 10 ** 3:
        return f'{bytes / 10 ** 3:.2f} KB'
    else:
        return f'{bytes} B'


def jsonify(obj):
    if obj is None or isinstance(obj, (int, bool, str)):
        return obj
    elif isinstance(obj, float):
        return round(obj, FLOAT_POINTS)
    elif isinstance(obj, dict):
        return {key: jsonify(val) for key, val in obj.items()}
    elif isinstance(obj, list):
        return [jsonify(it) for it in obj]
    elif hasattr(obj, 'as_dict'):
        return jsonify(obj.as_dict())
    # elif isinstance(ob, np.ndarray):
    #    return _jsonify(ob.tolist())
    else:
        log.warning(f"Type {type(obj)} maybe not be json serializable")
        return obj


def register_template_filters(app):
    @app.template_filter('ctime')
    def timectime(s) -> str:
        if isinstance(s, datetime):
            return str(s)
        elif isinstance(s, int):
            return time.ctime(s)  # datetime.datetime.fromtimestamp(s)
        elif s is None:
            return ''
        else:
            return str(s)

    @app.template_filter('flat_single')
    def flatten_singleton(obj):
        res = obj
        try:
            if len(obj) == 0:
                res = ''
            elif len(obj) == 1:
                res = obj[0]
        except:
            pass
        return res


def get_speak_order(topic: ChatTopic) -> List[str]:
    """
        Define the order of speakers in one turn for a topic.
        This function is called when creating a new thread.
        Customize this function to change the order of speakers.
        The speaker order is the same as the order of the returned list.

        You can have a speaker speak multiple times in one turn by adding the speaker multiple times in the list.
        For example, if you want to have User1 speak twice in one turn, you can return ['User1', 'User1', 'Moderator'].

        Chat room with existing conversation: the order is ['Moderator', 'b', 'Moderator', 'a', ...]
        and User1 is the last speaker in the conversation, User2 is the second last speaker, etc.
        :param human_users: number of human users in the chat room
        :param topic: The topic of the thread
        :return: A list of speaker ids
        """
    if len(topic.data['conversation']) == 0:
        # This is an empty chat room
        return ['User1', 'Moderator']
    else:
        # This is a chat room with existing conversation
        all_roles = [m['speaker_id'] for m in reversed(topic.data['conversation']) if
                     m['speaker_id'] != 'Topic']
        speak_order = []
        human_moderators = int(topic.human_moderator == 'yes')
        human_users = topic.max_human_users_per_thread - human_moderators
        for role in all_roles[:human_users]:
            if role not in speak_order:
                speak_order.append('Moderator')
                speak_order.append(role)
        return speak_order


def get_next_human_role(user: User, thread: ChatThread, topic: ChatTopic) -> str:
    """
    Assign a role to a user in a thread.
    :param user: Currently unused
    :param thread: The thread to assign role to
    :param topic: The topic of the thread
    :return: 'Moderator', 'User1', 'a', 'b', 'c', etc.
    """
    has_moderator = thread.need_moderator_bot or any(thread.speakers[u] == 'Moderator' for u in thread.speakers.keys())

    if topic.human_moderator == 'yes' and not has_moderator:
        return 'Moderator'

    # Assign a speaker role
    if len(topic.data['conversation']) == 0:
        # This is an empty chat room
        return 'User1'
    else:
        # This is a chat room with existing conversation
        speaker_dict: dict = thread.speakers
        existing_speakers = len([k for k, v in speaker_dict.items() if v != 'Moderator'])
        all_roles = [m['speaker_id'] for m in reversed(topic.data['conversation']) if m['speaker_id'] != 'Topic']

        assert existing_speakers < len(all_roles), \
            f'Error when assign speaker role. Existing speakers {existing_speakers} >= {len(all_roles)}'

        return all_roles[existing_speakers]
