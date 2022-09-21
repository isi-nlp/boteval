import os

ERROR = 'error'
SUCCESS = 'success'

DEF_MAX_TURNS_PER_THREAD = 100
BOT_DISPLAY_NAME = 'Moderator'

USER_ACTIVE_UPDATE_FREQ = 2 * 60 # seconds
MAX_PAGE_SIZE = 40

class Auth:
    ADMIN_USER = 'admin'
    BOT_USER = 'bot01'
    DEV_USER = 'dev'
    CONTEXT_USER = 'context'

    # TODO: better way to handle
    ADMIN_SECRET = os.environ.get('ADMIN_USER_SECRET', 'xyza')
    DEV_SECRET = os.environ.get('DEV_USER_SECRET', 'abcd')


MTURK = 'mturk'
MTURK_SANDBOX = 'https://mturk-requester-sandbox.us-east-1.amazonaws.com'
AWS_MAX_RESULTS = 100
