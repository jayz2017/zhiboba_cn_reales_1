import os
import sys
import json
import subprocess
from tempfile import TemporaryDirectory

texts = ['库里助攻格林上篮命中', '霍姆格伦封盖申京上篮', '阿门抢断后快攻暴扣']
schema = [
    {'进攻球员': ['防守球员', '协作球员', '进攻动作', '结果', '得分值']},
    {'防守球员': ['进攻球员', '防守动作', '结果']},
]

with TemporaryDirectory(prefix='uie_diag_') as temp_root:
    payload_path = os.path.join(temp_root, 'payload.json')
    result_path = os.path.join(temp_root, 'result.json')
    with open(payload_path, 'w', encoding='utf-8') as fp:
        json.dump({'texts': texts, 'schema': schema, 'model_name': 'uie-base'}, fp, ensure_ascii=False)

    runner_code = r'''
import json
import os
import sys
os.environ.setdefault("FLAGS_enable_pir_api", "0")
print('IMPORT_START', flush=True)
from paddlenlp import Taskflow
print('TASKFLOW_IMPORTED', flush=True)
with open(sys.argv[1], 'r', encoding='utf-8') as fp:
    payload = json.load(fp)
print('PAYLOAD_LOADED', flush=True)
extractor = Taskflow('information_extraction', schema=payload['schema'], model=payload['model_name'])
print('EXTRACTOR_READY', flush=True)
results = extractor(payload['texts'])
print('RESULT_READY', flush=True)
with open(sys.argv[2], 'w', encoding='utf-8') as fp:
    json.dump(results, fp, ensure_ascii=False)
print('SIAMESE_UIE_OK', flush=True)
'''
    completed = subprocess.run(
        [sys.executable, '-X', 'faulthandler', '-c', runner_code, payload_path, result_path],
        capture_output=True,
        text=True,
        timeout=240,
        env=os.environ.copy(),
    )
    print('RETURNCODE=', completed.returncode)
    print('STDOUT_START')
    print(completed.stdout)
    print('STDOUT_END')
    print('STDERR_START')
    print(completed.stderr)
    print('STDERR_END')
    print('RESULT_EXISTS=', os.path.exists(result_path))
