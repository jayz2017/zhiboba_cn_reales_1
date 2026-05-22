import os
from pathlib import Path
from app.modules.nba_live_text.nlp.tokenizer import Tokenizer

out = Path('tmp_tokenizer_force_exit.txt')
text = '库明加这么打有前途'
tokenizer = Tokenizer()
result = tokenizer.tokenize_batch([text])[0].tokens
out.write_text(str(result), encoding='utf-8')
print(out.read_text(encoding='utf-8'), flush=True)
os._exit(0)
