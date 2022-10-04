from textwrap import indent
from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO

import copy

from . import constants as C  # constants
from . import log 

yaml = YAML(typ='rt')


class TaskConfig(dict):
    
    def __init__(self, data, _path=None, **kwargs):
        super().__init__(data, **kwargs)
        self._path = _path
        #self._data = data
        self.is_seamless_crowd_login = False
        if C.MTURK in self:
            self.is_seamless_crowd_login = self[C.MTURK].get('seamless_login', False)
            log.info(f'seamless crowd login enabled? {self.is_seamless_crowd_login}')


    @classmethod
    def load(cls, path):
        with open(path, 'rb') as stream:
            data = yaml.load(stream)
        return cls(data, _path=path)
    
    def as_yaml_str(self) -> str:
        stream = StringIO()
        obj = dict(self.items())
        yaml.dump(obj, stream=stream)
        return stream.getvalue()

