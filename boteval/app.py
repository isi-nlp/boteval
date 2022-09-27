from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from datetime import datetime
from pathlib import Path
import time

import flask
from flask import Flask, Blueprint
from flask_socketio import SocketIO
from flask_login import LoginManager

from . import log, __version__, db, C, TaskConfig
from .controller import user_controllers, admin_controllers, init_login_manager, register_app_hooks
from .service import ChatService


log.basicConfig(level=log.INFO)


app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.config['SECRET_KEY'] = 'abcd1234'
socket = SocketIO(app)
login_manager = LoginManager()

@app.template_filter('ctime')
def timectime(s) -> str:
    if isinstance(s, datetime):
        return str(s)
    elif isinstance(s, int):
        return time.ctime(s) # datetime.datetime.fromtimestamp(s)
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


def parse_args():
    parser = ArgumentParser(
        prog="boteval",
        description="Deploy chat bot evaluation",
        formatter_class=ArgumentDefaultsHelpFormatter)

    parser.add_argument('-t', '--task-dir', type=Path, help='Path to task dir.',
                    required=True)
    parser.add_argument('-c', '--config', type=Path, help='Path to config file. Default is <task-dir>/conf.yml')
    parser.add_argument("-b", "--base", type=str, help="Base path prefix for all urls")

    parser.add_argument("-d", "--debug", action="store_true", help="Run Flask server in debug mode")
    parser.add_argument("-a", "--addr", type=str, help="Address to bind to", default='0.0.0.0')
    parser.add_argument("-p", "--port", type=int, help="port to run server on", default=C.DEF_PORT)
    parser.add_argument("-v", "--version", action="version", version=__version__)
    args = vars(parser.parse_args())
    return args


# uwsgi can take CLI args too
# uwsgi --http 127.0.0.1:5000 --module boteval.app:app # --pyargv "--foo=bar"



def init_app(**args):
    
    task_dir: Path = args['task_dir']
    config_file: Path = args.get('config') or (task_dir / 'conf.yml')
    assert config_file.exists() and config_file.is_file(), f'Expected config YAML file at {config_file}, but it is not found'
    
    config = TaskConfig.load(config_file)
    # load flask configs; this includes flask-sqlalchemy
    app.config.from_mapping(config['flask_config'])
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    if not db_uri:
        #relative_path = task_dir.resolve().relative_to(Path('.').resolve())
        db_file_name = app.config.get('DATABASE_FILE_NAME', C.DEF_DATABSE_FILE)
        assert  '/' not in db_file_name
        db_uri = f'sqlite:///{task_dir.resolve()}/{db_file_name}'
        app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
        log.info(f'>>SQLALCHEMY_DATABASE_URI={db_uri}')
        
    service = ChatService(config=config, task_dir=task_dir)

    with app.app_context():
        login_manager.init_app(app)
        db.init_app(app)
        db.create_all(app=app)
        service.init_db()
        init_login_manager(login_manager=login_manager)
        register_app_hooks(app)

    bp = Blueprint('app', __name__, template_folder='templates', static_folder='static')
    user_controllers(router=bp, socket=socket, service=service)
    base_prefix = args.get('base') or ''
    app.register_blueprint(bp, url_prefix=base_prefix)

    admin_bp = Blueprint('admin', __name__, template_folder='templates', static_folder='static')
    admin_controllers(router=admin_bp, service=service)
    app.register_blueprint(admin_bp, url_prefix=f'{base_prefix}/admin')

    if args.pop('debug'):
        app.debug = True
        log.root.setLevel(level=log.DEBUG)

args = parse_args()
init_app(**args)
with app.test_request_context():
    ext_url = flask.url_for('app.index', _external=True)
    log.info(f'Server URL: {ext_url}')
    app.config['EXT_URL_BASE'] = ext_url


def main():
    #app.run(port=cli_args["port"], host=cli_args.get('addr', '0.0.0.0'))
    host, port = args.get('addr', C.DEF_ADDR), args.get('port', C.DEF_PORT)
    socket.run(app, port=port, host=host, debug=app.debug)


if __name__ == "__main__":
    main()
