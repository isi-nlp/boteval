# Chat Bot Evaluation


## Features and Tech stack
* Bootstrap: for CSS theming and layout
* Flask server: Python based server side programming
  * Flask-Login: User authentication
  * Flask-SocketIO: Socket.IO for bicirectional messaging between server-client
  * Flask-sqlalchemy: Object relational mapping
  * jinja2: server side templating
  * MVCS kind of setup
* jQuery: for DOM manipulation and client side templating


## Setup

```bash
pip install -e .
```

## Run



```bash
# deevelopment/debugging: autoreloads when files are changes
python -m boteval -d

# no debug mode
python -m boteval
```



