#!/usr/bin/env python
#
# Authors:
# - Thamme Gowda [tg (at) isi (dot) edu]

from . import log

from typing import Any


BOT = 'bot'
TRANSFORM = 'transform'


global registry

registry = {
    BOT: dict(),
    TRANSFORM: dict(),
}


def register(kind, name):
    """
    A decorator for registering modules; must be used on classes
    :param kind: what kind of component :py:const:BOT, :py:const:TRANSFORM
    :param name: name for this component
    :return:
    """
    global registry
    assert kind in registry
    assert name
    assert name not in registry[kind], f'{name} is already taken; duplicates not allowed'

    def _wrap_cls(cls):
        registry[kind][name] = cls
        return cls

    return _wrap_cls


def _register_all():
    # import, so register() calls can happen
    from importlib import import_module
    modules = [
        'boteval.bots',
        'boteval.transforms',
    ]
    for name in modules:
        import_module(name)
    msg = []
    for k, v in registry.items():
        msg.append(f'{k}:\t' + ', '.join(v.keys()))
    msg = '\n  '.join(msg)
    log.debug(f"Registered all components; your choices are ::\n  {msg}")


if __name__ == '__main__':
   _register_all()
   print(registry)

