# Chat Admin

This project offers a web interface to admnister darma chats

## Setup

> Requires Python 3.9 or newer

```bash
git clone  https://github.com/isi-nlp/isi_darma
cd isi_darma/chat_admin
pip install -e .

python -m chat_admin -h
```

## Start Server

### Development mode

```bash

# add -d for debug
python -m chat_admin path-to-config.yml -d
```

# Deployment
```bash
python -m chat_admin path-to-config.yml
```

This starts a service on http://localhost:6060 by default.


## Config file

Look at `darma-task/conf.yml` for an example

## SSL and HTTPS Notes

* For MTurk integration, running server via HTTPS is required.
* For HTTPS, an SSL certificate is required
* You can buy an SSL certificate from trusted agents that all browsers trust 
  --OR-- you can create a self-signed certificate that some browsers might complain 
> I recommend getting a certificate that most browsers trust. and install it on server where you deploy this
* Recommendation: it has been a trouble configuring SSL with uwsgi or other flask runner. 
> Easy option is don't bother https or ssl at python/flask layer, but instead handle it at a reverse proxy such as nginx.
* Where to get? How to install ? https://certbot.eff.org/ 
Follow the steps and install certificate on server.
> NOTE: we need a publicly accessible domain name. SSL certificate on IP address isnt the way to go. 
 So buy a cheap domain name and point its DNS record to your server's IP address. 
> It doesnt have to be top level, you can also configure one of sub domains of your existing domain name.



## Development

* Model view controller pattern: https://en.wikipedia.org/wiki/Model%E2%80%93view%E2%80%93controller
* Flask: https://flask.palletsprojects.com/en/2.2.x/api/
  * Server side templating is using Jinja2: https://jinja.palletsprojects.com/en/3.1.x/templates/
* Login and user session manager: https://flask-login.readthedocs.io/en/latest/
* Database backend and ORM: persistance: https://flask-sqlalchemy.palletsprojects.com/en/2.x/models/
  * If you do not know how Dabase and ORM works or how you could use them, then this could be most complex piece of the system. Good news is that we build on top of battele-tested SqlAlchemy. See its documentation at https://docs.sqlalchemy.org/en/14/
  * Some examples for CRUD ops https://flask-sqlalchemy.palletsprojects.com/en/2.x/queries/

* Sockets and stuff: https://flask-socketio.readthedocs.io/en/latest/intro.html
* Themes and styles via Bootstrap : https://getbootstrap.com/docs/4.5/getting-started/introduction/

