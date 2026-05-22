import os
os.environ.setdefault('FLAGS_enable_pir_api', '0')
print('before import', flush=True)
from paddlenlp import Taskflow
print('after import', flush=True)
for mode in ('accurate','fast'):
    try:
        print(f'init {mode} start', flush=True)
        seg = Taskflow('word_segmentation', mode=mode, batch_size=1)
        print(f'init {mode} ok', flush=True)
        out = seg(['切特疯了，申京上场了吗？'])
        print(f'call {mode} ok: {out}', flush=True)
    except Exception as exc:
        print(f'{mode} error: {type(exc).__name__}: {exc}', flush=True)
