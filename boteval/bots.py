


import argparse
from typing import Any, Dict, List


from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

from . import log, C, R


# here are other models https://huggingface.co/models?pipeline_tag=conversational&sort=downloads
BLENDERBOT_400M = "facebook/blenderbot-400M-distill"
BLENDERBOT_90M = "facebook/blenderbot_small-90M"


class BotAgent:
    
    NAME = None
    
    def __init__(self, *args, name=None, **kwargs) -> None:
        self.name = name or self.NAME
        self.signature = {} # for reproducibility
        self.update_signature(agent_name=name)
        self.last_msg = None

    def get_name(self) -> str:
        raise NotImplementedError()

    def update_signature(self, **kwargs):
        self.signature.update(kwargs)

    def hear(self, msg: Dict[str, Any]):
        self.last_msg = msg

    def talk(self) -> Dict[str, Any]:
        raise NotImplementedError(f'{type(self)} must implement talk() method')

    def interactive_shell(self):
        log.info(f'Launching an interactive shell with {type(self)}.\n'
                 'Type "exit" or press CTRL+D to quit.')
        try:
            import readline
        except:
            pass
        while True:
            line = input('[You]: ')
            line = line.strip()
            if not line:
                continue
            if line == "exit":
                break
            reply = self.talk(line)
            print(f"[Bot]: {reply}")


@R.register(R.BOT, 'dummybot')
class DummyBot(BotAgent):

    NAME = 'dummybot'

    def talk(self):
        context = (self.last_msg or {}).get('text', '')
        if context.lower() == 'ping':
            return 'pong'
        return dict(text="dummybot reply --" + context[-30:])


@R.register(R.BOT, 'hf-transformers')
class TransformerBot(BotAgent):

    NAME = 'transformers'

    def __init__(self, model_name=BLENDERBOT_90M, **kwargs) -> None:
        super().__init__(name=f'{self.NAME}:{model_name}')
        self.model_name = model_name
        self.update_signature(model_name=model_name)

        log.info(f'Loading model {model_name}')
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)


    def talk(self) -> str:
        context = (self.last_msg or {}) .get('text', '[start]')
        inputs = self.tokenizer([context], return_tensors="pt")
        reply_ids = self.model.generate(**inputs)
        reply = self.tokenizer.batch_decode(reply_ids, skip_special_tokens=True)[0]
        return dict(text=reply)


def load_bot_agent(name: str, args: Dict[str, Any]) -> BotAgent:
    # log.info(f'Going to load bot {name} with args: {args}')
    bot_engines = R.registry[R.BOT]
    assert name in bot_engines, f'{name} not found; found={bot_engines.keys()}'
    return R.registry[R.BOT][name](**args)


def parse_args():
    parser = argparse.ArgumentParser(description="launch interactive shell",
         formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-m', '--model', default=BLENDERBOT_90M,
                    help='Chat bot model name to load')
    parser.add_argument('-d', '--debug', action='store_true',
                    help='Enable debug logs')
    args = parser.parse_args()
    return vars(args)

def main(**args):
    args = args or parse_args()
    if args.pop('debug'):
         log.setLevel(log.DEBUG)
         log.debug('Debug mode enabled')
    model_name = args.pop('model')

    bot = load_bot_agent("transformers", args=dict(model_name=model_name))
    bot.interactive_shell()


if '__main__' == __name__:
    main()

