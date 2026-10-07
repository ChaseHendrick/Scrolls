"""Independent differential checks against the exact c43c41a scorer, using tiny synthetic data."""
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import warnings
import weakref
from unittest.mock import patch

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = Path('/workspace/scrolls-env/production-speed-v2')
sys.path.insert(0, str(ROOT / 'scoring'))
from kit import hpscore as candidate
spec = importlib.util.spec_from_file_location('kit._review_original_hpscore', ROOT / 'scoring-baseline/kit/hpscore.py')
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)

hash_before = hashlib.sha256(Path(candidate.__file__).read_bytes()).hexdigest()
counts = {'score_array_matches': 0, 'score_files_matches': 0, 'exception_matches': 0, 'format_matches': 0}
rng = np.random.default_rng(7712026)

def outcome(function, *args, **kwargs):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            result = function(*args, **kwargs)
        return ('result', json.dumps(result, sort_keys=True, allow_nan=True))
    except Exception as exc:
        return ('exception', type(exc).__name__, str(exc))

def check_array(pred, ink, mask, voxel, inner):
    old = outcome(original.score_array, pred, ink, mask, voxel, inner)
    new = outcome(candidate.score_array, pred, ink, mask, voxel, inner)
    assert old == new, ('array', pred.shape, voxel, inner, old, new)
    counts['score_array_matches' if old[0] == 'result' else 'exception_matches'] += 1

def check_files(pred, ctrl, ink, mask, voxel, inner=0, **kwargs):
    arrays = {'prediction': pred, 'control': ctrl}
    results = []
    for module in (original, candidate):
        with patch.object(module, '_load', side_effect=lambda name: arrays[name]), patch.object(module, 'labels_on_map', return_value=(ink, mask)):
            results.append(outcome(module.score_files, 'prediction', 'labels', 'mask', voxel, control='control' if ctrl is not None else None, inner=inner, **kwargs))
    assert results[0] == results[1], ('files', pred.shape, voxel, inner, kwargs, results)
    if results[0][0] == 'exception':
        counts['exception_matches'] += 1
    else:
        counts['score_files_matches'] += 1
        for module in (original, candidate):
            formatted = outcome(module.format_result, json.loads(results[0][1]))
            if module is original:
                reference = formatted
            else:
                assert reference == formatted, ('format', reference, formatted)
                counts['format_matches'] += 1

for shape in ((64, 96), (96, 80), (320, 32)):
    ink = rng.random(shape) > .65
    full = np.ones(shape, bool)
    holed = full.copy(); holed[18:27, 11:25] = False
    half = full.copy(); half[:, :shape[1]//2] = False
    sparse = rng.random(shape) > .8
    predictions = [rng.integers(1, 256, shape, dtype=np.uint8), rng.random(shape).astype(np.float32) + .01, np.full(shape, .25), np.zeros(shape)]
    for pred in predictions:
        pred = pred.copy(); pred[:7, 2:9] = 0
        ctrl = np.flip(pred, 0).copy(); ctrl[:, :11] = 0
        for mask in (full, holed, half, sparse, np.zeros(shape, bool)):
            for voxel in (9.362, 24., 96.):
                for inner in (0, 3):
                    check_array(pred, ink, mask, voxel, inner)
                    check_files(pred, ctrl, ink, mask, voxel, inner)
    # The transposed inputs are non-contiguous and have different shape.
    check_array(pred.T, ink.T, holed.T, 9.362, 0)
    check_files(pred.T, ctrl.T, ink.T, holed.T, 9.362, 0)

shape = (64, 80)
ink = rng.random(shape) > .5
mask = np.ones(shape, bool)
pred = rng.random(shape) + .01
ctrl = np.zeros(shape)
check_files(pred, None, ink, mask, 9.362)
check_files(pred, ctrl, ink, mask, 9.362)
check_files(pred[None], pred, ink, mask, 9.362)
check_files(np.stack([pred, pred]), ctrl, ink, mask, 9.362)
check_files(pred, ctrl[:-1], ink, mask, 9.362)
check_files(pred, ctrl, ink, mask, 9.362, crop=[0,64,0,80])
check_files(pred, ctrl, ink, mask, 9.362, inner=32)
check_files(pred, ctrl, ink, mask, 9.362, inner=-1)
for voxel in (0., -1., float('nan'), float('inf')):
    check_array(pred, ink, mask, voxel, 0)
    check_files(pred, ctrl, ink, mask, voxel, 0)
for value in (float('nan'), float('inf'), -1.):
    p = pred.copy(); p[24,24] = value
    check_array(p, ink, mask, 9.362, 0)
    check_files(p, ctrl, ink, mask, 9.362, 0)

# Actual file loading, label-grid crop selection, pyramid-level lookup, and shape checks.
import tifffile
import zarr
with tempfile.TemporaryDirectory(prefix='hp-review-') as temp:
    temp = Path(temp)
    labels = zarr.open_group(str(temp/'labels.zarr'), mode='w')
    masks = zarr.open_group(str(temp/'mask.zarr'), mode='w')
    label_array = rng.integers(0, 2, (96,112), dtype=np.uint8)
    label_mask = np.ones((96,112), np.uint8); label_mask[28:34,31:43] = 0
    labels.create_array('2', data=label_array)
    masks.create_array('2', data=label_mask)
    crop = [16,80,20,100]
    p = rng.random((64,80)).astype(np.float32) + .01
    c = np.flipud(p).copy(); c[:8] = 0
    np.save(temp/'prediction.npy', p)
    tifffile.imwrite(temp/'control.tif', c)
    args=(str(temp/'prediction.npy'),str(temp/'labels.zarr'),str(temp/'mask.zarr'),9.362)
    kwargs={'control':str(temp/'control.tif'),'crop':crop,'surface_shape':(96,112),'inner':3}
    a=outcome(original.score_files,*args,**kwargs); b=outcome(candidate.score_files,*args,**kwargs)
    assert a==b and a[0]=='result', ('real-files',a,b)
    counts['score_files_matches']+=1
    for changed in ({'level':'missing'}, {'crop':[16,81,20,100]}, {'surface_shape':(95,112)}):
        k=dict(kwargs); k.update(changed)
        a=outcome(original.score_files,*args,**k);b=outcome(candidate.score_files,*args,**k)
        assert a==b and a[0]=='exception', ('real-files-error',a,b)
        counts['exception_matches']+=1

# Label fields are local, leave no live arrays after score_files returns, and do not mutate inputs.
seen=[]
fields_function=candidate._label_fields

def tracked_fields(*args):
    fields=fields_function(*args)
    seen.extend(weakref.ref(a) for a in fields)
    return fields
snapshots=[a.copy() for a in (pred,ctrl,ink,mask)]
with patch.object(candidate,'_label_fields',side_effect=tracked_fields):
    check_files(pred,ctrl,ink,mask,9.362)
gc.collect()
assert len(seen)==3 and all(ref() is None for ref in seen)
for actual,before in zip((pred,ctrl,ink,mask),snapshots):
    np.testing.assert_array_equal(actual,before)

# Same exact gaussian operations, with three label-only filters eliminated from the paired call.
filter_counts={}
for module in (original,candidate):
    calls=[]
    def counted(*a,**k):
        calls.append(1)
        return gaussian_filter(*a,**k)
    with patch.object(module,'_gaussian',return_value=counted),patch.object(module,'_load',side_effect=lambda name: pred if name=='prediction' else ctrl),patch.object(module,'labels_on_map',return_value=(ink,mask)):
        module.score_files('prediction','labels','mask',9.362,control='control')
    filter_counts['baseline' if module is original else 'candidate']=len(calls)
assert filter_counts=={'baseline':10,'candidate':7}
assert hash_before==hashlib.sha256(Path(candidate.__file__).read_bytes()).hexdigest()
receipt={'candidate_hpscore_sha256':hash_before,'baseline_hpscore_sha256':hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest(),'counts':counts,'gaussian_filter_calls_paired':filter_counts,'input_mutation':'none','local_label_fields_after_return':'released','global_cache':'none by source inspection','status':'pass'}
(ROOT/'scoring-independent-review'/'evidence.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
