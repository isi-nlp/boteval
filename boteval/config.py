import os

ERROR = 'error'
SUCCESS = 'success'

DEF_MAX_TURNS_PER_THREAD = 100
BOT_DISPLAY_NAME = 'Moderator'

class Auth:
    ADMIN_USER = 'admin'
    BOT_USER = 'bot01'
    DEV_USER = 'dev'
    CONTEXT_USER = 'contex'

    # TODO: better way to handle
    ADMIN_SECRET = os.environ.get('ADMIN_USER_SECRET', 'xyza')
    DEV_SECRET = os.environ.get('DEV_USER_SECRET', 'abcd')
