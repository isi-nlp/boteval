"""

"""

from typing import Any

from boteval import log, C, registry as R
from boteval.bots import BotAgent


@R.register(R.BOT, name="my-dummy-bot")
class MyDummpyBot(BotAgent):
    
    def __init__(self, **kwargs):
        super().__init__(name="dummybot", **kwargs)
        self.args = kwargs
        log.info(f"{self.name} initialized; args={self.args}")

    def talk(self) -> dict[str, Any]:
        if not self.last_msg:
            reply = f"Hello there! I am {C.BOT_DISPLAY_NAME}."
        elif 'ping' in self.last_msg['text'].lower():
            reply = 'pong'
        else:
            reply = f"Dummy reply for -- {self.last_msg['text']}"
        return dict(text=reply)

    def hear(self, msg: dict[str, Any]):
        self.last_msg = msg
