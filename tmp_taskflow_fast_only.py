import os
os.environ.setdefault('FLAGS_enable_pir_api', '0')
print('before import', flush=True)
from paddlenlp import Taskflow
print('after import', flush=True)
print('init fast start', flush=True)
seg = Taskflow('word_segmentation', mode='fast', batch_size=1)
print('init fast ok', flush=True)
out = seg(['切特疯了，申京上场了吗？'])
print(f'call fast ok: {out}', flush=True)
