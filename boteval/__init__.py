__version__ = '0.1'

import logging as log
from flask_sqlalchemy import SQLAlchemy

from . import (
    constants as C,  # constants
    registry as R,
)


log.basicConfig(level=log.INFO, format='%(asctime)s  %(process)d T%(thread)d %(module)s.%(funcName)s:%(lineno)s %(levelname)s:: %(message)s')
db: SQLAlchemy = SQLAlchemy()


from .config import TaskConfig, yaml
