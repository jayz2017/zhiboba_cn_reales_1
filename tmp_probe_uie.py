import os
os.environ.setdefault('FLAGS_enable_pir_api', '0')
try:
    from paddlenlp import Taskflow
    ie = Taskflow('information_extraction', schema=['球员'], model='uie-base')
    result = ie('库里助攻追梦格林上篮命中')
    print('IE_OK')
    print(result)
except Exception as exc:
    print('IE_ERROR')
    print(repr(exc))
