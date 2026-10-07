"""Exercise the actual row-scoring CLI with real forward and reverse maps."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

root = Path('/workspace/Scrolls')
baseline = Path('/workspace/scrolls-env/production-speed-v2/scoring-baseline')
maps = Path('/workspace/scrolls-env/supervised-surfacefix/reader-baseline')
forward, reverse = maps / 'forward_s42.tif', maps / 'reverse_s42.tif'
command = [str(root / '.venv/bin/python'), '-m', 'kit', 'rowscore', str(forward),
           '--reverse', str(reverse), '--voxel-um', '9.366', '--json']
env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (forward, reverse)}
records = {}
outputs = {}
for name, cwd, extra in [('baseline', baseline, []), ('default', root, []),
                         ('fast', root, ['--fast-resize'])]:
    process = subprocess.run(command + extra, cwd=cwd, env=env, capture_output=True, check=True)
    assert not process.stderr, process.stderr.decode()
    records[name] = json.loads(process.stdout)
    outputs[name] = process.stdout
assert outputs['baseline'] == outputs['default']
assert records['fast']['fast_resize'] is True
matches = {}
for direction in ('forward', 'reverse'):
    assert records['fast'][direction]['resize_mode'] == 'sparse_area_float32'
    original = records['default'][direction]
    matches[direction] = original == {k: records['fast'][direction][k] for k in original}
assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (forward, reverse)}
record = {'command': command, 'baseline_ref': 'c43c41a59ac3793b9a653fa236165f6f6b9d47a4',
          'default_stdout_bytes_identical': True, 'input_hashes_unchanged': before,
          'fast_historical_field_matches_on_this_input': matches, 'records': records,
          'note': 'Real 640 crop CLI check; not a timing test or general exactness promise for sparse resizing.'}
Path(__file__).with_name('rows-cli-check.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({k: record[k] for k in ('default_stdout_bytes_identical',
                                       'fast_historical_field_matches_on_this_input')}))
