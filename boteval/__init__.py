__version__ = '0.1'

from loguru import logger as log
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

from . import (
    constants as C,  # constants
    registry as R,
)

# get date as string
date =  datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
log.add(f"{date}.log")

# log.basicConfig(level=log.INFO)
db: SQLAlchemy = SQLAlchemy()


from .config import TaskConfig, yaml
