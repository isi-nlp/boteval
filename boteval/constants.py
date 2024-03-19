import os
import logging


DEF_PORT = 7070
DEF_ADDR = '0.0.0.0'

ERROR = 'error'
SUCCESS = 'success'
BOT_DISPLAY_NAME = 'Moderator'

LIMIT_MAX_THREADS_PER_USER = 'max_threads_per_user'
LIMIT_MAX_THREADS_PER_TOPIC = 'max_threads_per_topic'
LIMIT_MAX_TURNS_PER_THREAD = 'max_turns_per_thread'
LIMIT_REWARD = 'reward'
DEF_MAX_THREADS_PER_TOPIC = 3
DEF_MAX_THREADS_PER_USER = 10
DEF_MAX_TURNS_PER_THREAD = 100
DEF_REWARD = '0.0'

USER_ACTIVE_UPDATE_FREQ = 2 * 60 # seconds
MAX_PAGE_SIZE = 300

PING_WAIT_TIME = 4 # secs
MAX_TEXT_LENGTH = 2048

DEF_TOPICS_FILE = 'topics.json'
DEF_INSTRUCTIONS_FILE = 'instructions.html'
DEF_AGREEMENT_FILE = 'user-agreement.html'
DEF_DATABSE_FILE = 'boteval.sqlite.db'

ENV = {}
for env_key in ['GTAG']:
    ENV[env_key] = os.environ.get(env_key)


class Auth:
    ADMIN_USER = 'admin'
    BOT_USER = 'Moderator'
    DEV_USER = 'dev'
    CONTEXT_USER = 'context'

    # TODO: find a better way to handle
    ADMIN_SECRET = os.environ.get('ADMIN_USER_SECRET', 'xyza')
    DEV_SECRET = os.environ.get('DEV_USER_SECRET', 'abcd')


MTURK = 'mturk'
MTURK_SANDBOX = 'mturk_sandbox'
MTURK_SANDBOX_URL = 'https://mturk-requester-sandbox.us-east-1.amazonaws.com'
AWS_MAX_RESULTS = 100 
MTURK_LOG_LEVEL = logging.INFO

