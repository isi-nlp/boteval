import resource
from typing import Tuple
import sys
from . import log


FLOAT_POINTS = 4


def max_RSS(who=resource.RUSAGE_SELF) -> Tuple[int, str]:
    """Gets memory usage of current process, maximum so far.
    Maximum so far, since the system call API doesnt provide "current"
    :returns (int, str)
       int is a value from getrusage().ru_maxrss
       str is human friendly value (best attempt to add right units)
    """
    mem = resource.getrusage(who).ru_maxrss
    h_mem = mem
    if 'darwin' in sys.platform:  # "man getrusage 2" says we get bytes
        h_mem /= 10 ** 3  # bytes to kilo
    unit = 'KB'
    if h_mem >= 10 ** 3:
        h_mem /= 10 ** 3  # kilo to mega
        unit = 'MB'
    return mem, f'{int(h_mem)}{unit}'


def format_bytes(bytes):
    if bytes >= 10**6:
        return f'{bytes/10**6:.2f} MB'
    elif bytes >= 10**3:
        return f'{bytes/10**3:.2f} KB'
    else:
        return f'{bytes} B'


def jsonify(obj):

    if obj is None or isinstance(obj, (int, bool, str)):
        return obj
    elif isinstance(obj, float):
        return round(obj, FLOAT_POINTS)
    elif isinstance(obj, dict):
        return {key: jsonify(val) for key, val in obj.items()}
    elif isinstance(obj, list):
        return [jsonify(it) for it in obj]
    #elif isinstance(ob, np.ndarray):
    #    return _jsonify(ob.tolist())
    else:
        log.warning(f"Type {type(obj)} maybe not be json serializable")
        return obj
