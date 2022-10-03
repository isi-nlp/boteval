

from ruamel.yaml import YAML

from . import constants as C  # constants
from . import log 

yaml = YAML(typ='safe')   # default, if not specfied, is 'rt' (round-trip)


class TaskConfig(dict):
    
    def __init__(self, *args, _path=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._path = _path
        self.is_seemless_crowd_login = False
        if C.MTURK in self:
            self.is_seemless_crowd_login = self[C.MTURK].get('seemless_login', False)
            log.info(f'seemless crowd login enabled? {self.is_seemless_crowd_login}')


    @classmethod
    def load(cls, path):
        with open(path, 'rb') as stream:
            data = yaml.load(stream)
        return cls(data, _path=path)
    
