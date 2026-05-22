from app.modules.nba_live_text.nlp.tokenizer import Tokenizer

t = Tokenizer()
t.add_words(['切特', '阿尔佩伦申京'])
result = t.tokenize('切特疯了，申京上场了吗？')
print(result)
