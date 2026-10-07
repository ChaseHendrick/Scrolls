"""Read out the frozen PHerc0841 structural orientation diagnostic."""
from pathlib import Path
import hashlib
import json
import numpy as np
import tifffile

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(a, b):
    a = a[:, 64:-64, 64:-64].astype(np.float64).ravel()
    b = b[:, 64:-64, 64:-64].astype(np.float64).ravel()
    return {'correlation': float(np.corrcoef(a, b)[0, 1]),
            'mean_absolute_error_uint8': float(np.abs(a - b).mean()),
            'rms_error_uint8': float(np.sqrt(np.mean((a - b) ** 2))),
            'equal_fraction': float(np.mean(a == b)), 'voxels': int(a.size)}


published = np.load(ROOT / 'official-published-crop.npy')
paths = [ROOT.parent / 'layers-baseline' / f'{i:02d}.tif' for i in range(28)]
generated = np.stack([tifffile.imread(p) for p in paths])
assert generated.shape == published.shape == (28, 640, 640)
out = {'rule_sha256': sha(ROOT / 'rule.json'), 'script_sha256': sha(Path(__file__)),
       'scope': 'Structural order verification, no ink labels or reader selection',
       'published_sha256': sha(ROOT / 'official-published-crop.npy'),
       'existing_canonical_layer_hashes': {str(p): sha(p) for p in paths},
       'existing_canonical_negative_normal': metrics(published, generated),
       'existing_order_reversed_positive_normal': metrics(published, generated[::-1])}
for name in ['existing_canonical_negative_normal', 'existing_order_reversed_positive_normal']:
    m = out[name]
    m['passes_frozen_reproduction_bar'] = m['correlation'] >= .98 and m['mean_absolute_error_uint8'] <= 3
out['limits'] = ('One real public crop. The old run keeps its original forward/reverse names and cannot be retroactively reclassified as a preregistered published-order run. Input normal sign and correction-offset sign are separate concepts.')
target = ROOT / 'orientation-result.json'
if target.exists():
    raise RuntimeError('Refusing to overwrite result')
target.write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps({k:v for k,v in out.items() if k != 'existing_canonical_layer_hashes'}, indent=2))
print('RESULT_SHA256', sha(target))
