
from boteval.model import ChatMessage
from boteval import registry as R, log
from typing import List


class BaseTransform:
    
    def __call__(self, msg: ChatMessage) -> ChatMessage:
        return self.transform(msg)

    def transform(self, msg: ChatMessage):
        return msg

class Transforms:

    def __init__(self, transforms) -> None:
        self.transforms = transforms or []

    def __call__(self, msg: ChatMessage) -> ChatMessage:
        x = msg
        for transform in self.transforms:
            x = transform(x)
        return x


def load_transform(name, args=None) -> BaseTransform:
    transforms = R.registry[R.TRANSFORM]
    assert name in transforms, f'{name=} is unknown transform; known={transforms.keys()}'
    args = args or {}
    log.info(f'loading transform {name=} {args=}')
    return transforms[name](**args)


def load_transforms(chain: List) -> Transforms:
    tfms = []
    for conf in chain:
        tfm = load_transform(conf['name'], conf.get('args'))
        tfms.append(tfm)
    return Transforms(tfms)


@R.register(R.TRANSFORM, 'dummy')
class DummyTransform(BaseTransform):
    pass


class SpacySplitter():
    
    _instance = None 
    def __init__(self, max_toks=80) -> None:
        from spacy.lang.en import English          
        self.pipeline = English()
        self.pipeline.add_pipe('sentencizer')
        self.max_toks = max_toks
        
    
    def __call__(self, text: str) -> List[str]:
        res = []
        for s in self.pipeline(text).sents:
            line = s.text
            if len(toks := line.split()) <= self.max_toks:
                res.append(line)
            else:
                while toks:
                    res.append(' '.join(toks[:self.max_toks]))
                    toks = toks[self.max_toks:]
        return res

    @classmethod
    def get_instance(cls): # singleton, lazy init
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance 


@R.register(kind=R.TRANSFORM, name='huggingface-mt')
class HuggingfaceMT(BaseTransform):
    
    
    def __init__(self, model_name: str, max_length=256) -> None:
        super().__init__()
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM 
        self.model_name = model_name
        log.info(f' Loading Huggingface MT model {model_name}')
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        self.sentence_splitter = SpacySplitter.get_instance()
        self.max_length = max_length or 256

    def transform(self, msg: ChatMessage):
        text = msg.text
        msg.data['text_orig'] = text
        msg.text = self.translate(text)
        return msg

    def translate(self, text: str) -> str:
        log.debug(f"Translating {text}...")
        sents: List[str] = self.sentence_splitter(text)
        batch = self.tokenizer(sents, return_tensors="pt", padding=True,
         max_length=self.max_length)
        gen = self.model.generate(**batch)
        outputs = self.tokenizer.batch_decode(
            gen, skip_special_tokens=True)
        return ' '.join(outputs)

