__version__ = '0.1'

import logging as log
from flask_sqlalchemy import SQLAlchemy

from . import constants as C  # constants

log.basicConfig(level=log.INFO)
db: SQLAlchemy = SQLAlchemy()


from .config import TaskConfig, yaml
