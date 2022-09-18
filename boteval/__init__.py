__version__ = '0.1'

import logging as log
from ruamel.yaml import YAML
from flask_sqlalchemy import SQLAlchemy


log.basicConfig(level=log.INFO)
yaml = YAML(typ='safe')   # default, if not specfied, is 'rt' (round-trip)

db = SQLAlchemy()