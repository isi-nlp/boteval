__version__ = '0.1'

from loguru import logger as log
from flask_sqlalchemy import SQLAlchemy

from . import (
    constants as C,  # constants
    registry as R,
)


# log.basicConfig(level=log.INFO)
db: SQLAlchemy = SQLAlchemy()


from .config import TaskConfig, yaml
