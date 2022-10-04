
from boteval import registry as R, log
from boteval.transforms import BaseTransform, SpacySplitter
from boteval.model import ChatMessage



@R.register(R.TRANSFORM, name='my-transform')
class MyDummyTransform(BaseTransform):

    def __init__(self, **kwargs) -> None:
        super().__init__()
        self.args = kwargs
        self.splitter = SpacySplitter.get_instance()

    def transform(self, msg: ChatMessage) -> ChatMessage:
        try:
            text_orig = msg.text
            text = '\n'.join(self.splitter(text_orig))  + ' (transformed)' # sample transform
            msg.text = text
            msg.data['text_orig'] = text_orig
        except Exception as e:
            log.error(f'{e}')
        return msg
