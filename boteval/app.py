import sys
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from pathlib import Path
import importlib

import flask
from flask import Flask, Blueprint
#from flask_socketio import SocketIO
from flask_login import LoginManager

from . import log, __version__, db, C, TaskConfig, R
from .controller import user_controllers, admin_controllers, init_login_manager, register_app_hooks
from .service import ChatService
from .utils import register_template_filters


app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.config['SECRET_KEY'] = 'abcd1234'
#socket = SocketIO(app, cors_allowed_origins='*')
login_manager = LoginManager()


def parse_args():
    parser = ArgumentParser(
        prog="boteval",
        description="Deploy chat bot evaluation",
        formatter_class=ArgumentDefaultsHelpFormatter)

    parser.add_argument('task_dir', type=Path, metavar='DIR',
                        help='Path to task dir. See "example-chat-task"')
    parser.add_argument('-c', '--config', type=Path, metavar='FILE',
                        help='Path to config file. Default is <task-dir>/conf.yml')
    parser.add_argument("-b", "--base", type=str, metavar='/prefix',
                        default="/boteval",
                        help="Base path prefix for all url routes. Eg: /boteval")

    parser.add_argument("-d", "--debug", action="store_true", help="Run Flask server in debug mode")
    parser.add_argument("-a", "--addr", type=str, help="Address to bind to", default='0.0.0.0')
    parser.add_argument("-p", "--port", type=int, help="port to run server on", default=C.DEF_PORT)
    parser.add_argument("-v", "--version", action="version", version=__version__)
    args = vars(parser.parse_args())
    return args

def load_dir_as_module(dir_path: Path):
    log.info(f'Going to import {dir_path} as a python module.')
    module_name = dir_path.name
    parent_dir = dir_path.resolve().parent

    log.info(f'adding "{parent_dir}" to PYTHONPATH and importing "{module_name}"')
    assert module_name not in sys.modules, f'{module_name} collide with existing module. please rename dir to something else'
    sys.path.append(str(parent_dir))

    _module = importlib.import_module(module_name)
    log.info(f'import success! {_module=}')


def init_app(**args):

    R._register_all()  # register all modules

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
        assert '/' not in db_file_name
        db_uri = f'sqlite:///{task_dir.resolve()}/{db_file_name}'
        app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
        log.info(f'SQLALCHEMY_DATABASE_URI = {db_uri}')

    if (task_dir / '__init__.py').exists(): # task dir has python code
        log.info(f'{task_dir} is a python module. Going to import it.')
        load_dir_as_module(task_dir)

    service = ChatService(config=config, task_dir=task_dir)

    with app.app_context():
        login_manager.init_app(app)
        db.init_app(app)
        db.create_all(app=app)
        service.init_db()
        init_login_manager(login_manager=login_manager)
        register_app_hooks(app, service)
        register_template_filters(app)


    bp = Blueprint('app', __name__, template_folder='templates', static_folder='static')
    user_controllers(router=bp, service=service)
    base_prefix = args.get('base') or ''
    app.register_blueprint(bp, url_prefix=base_prefix)

    admin_bp = Blueprint('admin', __name__, template_folder='templates', static_folder='static')
    admin_controllers(router=admin_bp, service=service)
    app.register_blueprint(admin_bp, url_prefix=f'{base_prefix}/admin')

    if args.pop('debug'):
        app.debug = True

args = parse_args()
init_app(**args)
with app.test_request_context():
    ext_url = flask.url_for('app.index', _external=True)
    log.info(f'External server URL: {ext_url}')
    app.config['EXT_URL_BASE'] = ext_url

# uwsgi can take CLI args too
# e.g. uwsgi --http :7070 --module boteval.wsgi:app --pyargv "darma-task -c darma-task/conf-local.yml -b /boteval" --master --processes 4 --threads 2

def main():

    host, port = args.get('addr', C.DEF_ADDR), args.get('port', C.DEF_PORT)
    base_prefix = args.get('base') or '/'
    log.info(f'Internal URL http://{host}:{port}{base_prefix}')
    #socket.run(app, port=port, host=host, debug=app.debug)
    app.run(port=port, host=host)

if __name__ == "__main__":
    main()
