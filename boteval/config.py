

from ruamel.yaml import YAML

from . import constants as C  # constants

yaml = YAML(typ='safe')   # default, if not specfied, is 'rt' (round-trip)


class TaskConfig(dict):
    
    def __init__(self, *args, _path=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._path = _path


    @classmethod
    def load(cls, path):
        with open(path, 'rb') as stream:
            data = yaml.load(stream)
        return cls(data, _path=path)
    
    