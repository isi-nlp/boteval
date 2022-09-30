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

## Start Server

### Development mode

```bash

# add -d for debug
python -m boteval -d -c example-chat-task/conf.yml
```

# Deployment
```bash
python -m boteval -c example-chat-task/conf.yml
```

This starts a service on http://localhost:6060 by default.


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

