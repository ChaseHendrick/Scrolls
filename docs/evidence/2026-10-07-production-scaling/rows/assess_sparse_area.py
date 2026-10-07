"""Compatibility assessment on real fixed crop and adversarial arrays."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import time
import warnings
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
import numpy as np
from scipy import ndimage
from sparse_area_prototype import sparse_area_resize, sparse_area_weights

OUT = Path(__file__).resolve().parent
sys.path.insert(0, '/workspace/Scrolls')
spec = importlib.util.spec_from_file_location('kit._assess_baseline_rowscore', OUT/'baseline_rowscore.py')
rows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rows)
dense = rows._area_resize
rng = np.random.default_rng(314159)
records = []

def ordered_bits(a):
    b = a.view(np.uint32)
    return np.where(b>>31, ~b, b|np.uint32(0x80000000)).astype(np.int64)

def check(name, a, score_input=None, voxel_um=9.366, valid=None):
    times = {'dense':[], 'sparse':[]}
    values = {}
    for repeat in range(3):
        for method in (('dense','sparse') if repeat%2==0 else ('sparse','dense')):
            start=time.perf_counter()
            values[method] = (dense if method=='dense' else sparse_area_resize)(np,a,4)
            times[method].append(time.perf_counter()-start)
    b, s = values['dense'], values['sparse']
    errors = np.abs(b.astype(np.float64)-s.astype(np.float64))
    record = {'case':name, 'shape':list(a.shape), 'input_range':[float(a.min()),float(a.max())],
              'input_bytes_sha256':hashlib.sha256(a.tobytes()).hexdigest(),
              'all_weights_equal':all(np.array_equal(sparse_area_weights(n,n//4).toarray(),rows._area_weights(np,n,n//4)) for n in set(a.shape)),
              'exact_output':bool(np.array_equal(b,s)), 'max_absolute_difference':float(errors.max()),
              'different_values':int(np.count_nonzero(b!=s)),
              'max_output_ulp_difference':int(np.abs(ordered_bits(b)-ordered_bits(s)).max()),
              'elapsed_seconds':times}
    if score_input is not None:
        scores={}
        for method in ('dense','sparse'):
            rows._area_resize=dense if method=='dense' else sparse_area_resize
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning)
                scores[method]=rows.score_array(score_input,voxel_um,valid=valid)
        rows._area_resize=dense
        record['scores']=scores
        record['rounded_score_records_equal']=json.dumps(scores['dense'],sort_keys=True)==json.dumps(scores['sparse'],sort_keys=True)
    records.append(record)

real = np.load(OUT/'fixed-origin-4096-crop.npy')
real_normalized = rows._normalize(np,real)
check('real_public_fixed_origin_4096',np.clip((real_normalized-.25)/.5,0,1),score_input=real,voxel_um=2.403)
del real, real_normalized
for shape in [(64,80),(65,83),(640,640),(639,641),(1024,1024)]:
    positive = rng.random(shape,dtype=np.float32)
    check('bounded_positive_'+str(shape),positive)
    cancellation = rng.choice(np.array([-1,1],dtype=np.float32),size=shape)*np.float32(1e20)
    cancellation.flat[::7] = np.float32(1.)
    check('signed_cancellation_'+str(shape),cancellation)
for name in ['random_probability','quantized_ties','two_close_fft_peaks','high_dynamic_clipped','near_clip_thresholds']:
    h,w = 1024,1024
    if name=='random_probability':a=rng.random((h,w),dtype=np.float32)
    elif name=='quantized_ties':a=rng.choice(np.array([0,.25,.5,.75,1],dtype=np.float32),size=(h,w))
    elif name=='two_close_fft_peaks':
        y,x=np.indices((h,w));a=(.5+.1*np.sin(2*np.pi*y/90)+.1*np.sin(2*np.pi*x/91)).astype(np.float32)
    elif name=='high_dynamic_clipped':a=rng.choice(np.array([-1e20,0,1,1e20],dtype=np.float32),size=(h,w))
    else:a=rng.choice(np.array([.25,np.nextafter(np.float32(.25),np.float32(1)),.75,np.nextafter(np.float32(.75),np.float32(0))],dtype=np.float32),size=(h,w))
    v=np.clip((rows._normalize(np,a)-.25)/.5,0,1)
    check(name,v,score_input=a,valid=np.ones((h,w),bool))
for h,w in [(1023,1025),(1023,1023)]:
    for name in ['nondivisible_random','nondivisible_quantized_ties','symmetric_fft_tie']:
        if name=='nondivisible_random':a=rng.random((h,w),dtype=np.float32)
        elif name=='nondivisible_quantized_ties':a=rng.choice(np.array([0,.25,.5,.75,1],dtype=np.float32),size=(h,w))
        else:
            y,x=np.indices((h,w));a=(.5+.1*np.cos(2*np.pi*y*3/h)+.1*np.cos(2*np.pi*x*3/w)).astype(np.float32)
        v=np.clip((rows._normalize(np,a)-.25)/.5,0,1)
        check(name+'_'+str((h,w)),v,score_input=a,valid=np.ones((h,w),bool))
(OUT/'sparse-area-assessment.json').write_text(json.dumps({'status':'external_optional_prototype_only','cases':records,
    'limits':['Not universal bitwise parity. Default optimization gate fails.',
              'No full-canvas native map scoring or production CLI was run.',
              'Real fixed crop abstains; synthetic score compatibility does not establish real full-map FFT stability.']},indent=2)+'\n')
for r in records:print(r['case'],r['max_absolute_difference'],r['max_output_ulp_difference'],r.get('rounded_score_records_equal'),r['elapsed_seconds'])
