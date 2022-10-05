# Bot Eval

This project offers a web interface to evaluate chat bots, with optional mturk integration

## Setup

> Requires Python 3.9 or newer

Create an environment (if there is not one already)
```bash
conda create -n boteval python=3.9
conda activate boteval
```

```bash
git clone https://github.com/isi-nlp/boteval
cd boteval
pip install -e .

python -m boteval -h
```

Make sure to nstall PyTorch / Tensorflow / Flax. 

## Start Server

```bash
python -m boteval -h
usage: boteval [-h] [-c FILE] [-b /prefix] [-d] [-a ADDR] [-p PORT] [-v] DIR

Deploy chat bot evaluation

positional arguments:
  DIR                   Path to task dir. See "example-chat-task"

optional arguments:
  -h, --help            show this help message and exit
  -c FILE, --config FILE
                        Path to config file. Default is <task-dir>/conf.yml (default: None)
  -b /prefix, --base /prefix
                        Base path prefix for all url routes. Eg: /boteval (default: None)
  -d, --debug           Run Flask server in debug mode (default: False)
  -a ADDR, --addr ADDR  Address to bind to (default: 0.0.0.0)
  -p PORT, --port PORT  port to run server on (default: 7070)
  -v, --version         show program's version number and exit

```

### Development mode

```bash
# add -d for debug
BASE_URL_PATH="/boteval" # prefix to use for url paths
python -m boteval example-chat-task -d -b BASE_URL_PATH
```
`-d` enables live reload mode of server, which means when you edit files (and save) and hit refresh webpage it automatically reloads new changes. 


# Deployment
```bash
python -m boteval example-chat-task
# TODO: uwsgi 
python -m boteval example-chat-task -b BASE_URL_PATH
```

This starts a service on http://localhost:7070 by default.


## Config file

Look at `example-chat-task/conf.yml` for an example



## Development

* Model view controller pattern: https://en.wikipedia.org/wiki/Model%E2%80%93view%E2%80%93controller
* Flask for server side propgramming: https://flask.palletsprojects.com/en/2.2.x/api/
* Server side templating is using Jinja2: https://jinja.palletsprojects.com/en/3.1.x/templates/
* Login and user session manager: https://flask-login.readthedocs.io/en/latest/
* Database backend and ORM: persistance: https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/
  * If you do not know how Dabase and ORM works or how you could use them, then this could be most complex piece of the system. Good news is that we build on top of battele-tested SqlAlchemy. See its documentation at https://docs.sqlalchemy.org/en/14/
  * Some examples for CRUD ops https://flask-sqlalchemy.palletsprojects.com/en/2.x/queries/

* Sockets and stuff: https://flask-socketio.readthedocs.io/en/latest/intro.html
* Themes and styles via Bootstrap : https://getbootstrap.com/docs/4.5/getting-started/introduction/
* jQuery: for DOM manipulation and client side templating




## SSL and HTTPS Notes

* For MTurk integration, running server via HTTPS is required.
* For HTTPS, an SSL certificate is required. 
* For SSL, a domain name is required.
   > It doesnt have to be top level, you can also configure one of sub domains of your existing domain name.

* It has been a trouble configuring SSL with `uwsgi` or other `flask` runners. Easy option: _don't bother https or ssl at python/flask layer_, but instead handle it at a reverse proxy such as `nginx`.
* Where to get? How to install ? https://certbot.eff.org/  Follow the steps and install certificate on server. 
* For `nginx` config, see docs/nginx-conf.adoc

