import os
os.environ.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
import sys,time,json,hashlib
from pathlib import Path
root=Path('/workspace/scrolls-env/production-speed');variant=sys.argv[1];sys.path.insert(0,str(root/variant))
from kit import auc,hpscore,rowscore,provenance
import zarr,numpy as np,tifffile
from scipy import ndimage
zarr.config.set({'async.concurrency':1,'threading.max_workers':1})
original_imread=tifffile.imread

def single_worker_imread(*args,**kwargs):
    kwargs.setdefault('maxworkers',1)
    return original_imread(*args,**kwargs)

tifffile.imread=single_worker_imread
freeze=json.loads((root/'scoring-input-freeze.json').read_text())
for item in freeze['inputs']:
    if provenance.fingerprint(item['path'])['sha256']!=item['sha256']:raise RuntimeError('Frozen input changed: '+item['path'])
forward=Path(freeze['inputs'][0]['path']);reverse=Path(freeze['inputs'][1]['path']);labels=Path(freeze['inputs'][2]['path']);mask=Path(freeze['inputs'][3]['path'])
kw={'prediction':forward,'labels':labels,'mask':mask,'control':reverse,'level':'2','crop':tuple(freeze['crop']),'surface_shape':tuple(freeze['surface_shape']),'inner':64}
operations={'auc_files':lambda:auc.score_files(**kw,keep_zero=True,bootstrap=1000,block_px=107,compare=reverse,seed=20261007),'hp_files':lambda:hpscore.score_files(**kw,voxel_um=9.366),'rows_files':lambda:rowscore.score_files([forward],9.366,reverse=[reverse])}
# Warm the actual full pipeline once, then retain every measured full-operation output.
for fn in operations.values():fn()
result={'variant':variant,'cpu_affinity':list(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,'operation_times_s':{},'outputs':{},'code_sha256':provenance.sha256_file(root/variant/'kit/auc.py')}
for name,fn in operations.items():
    start=time.perf_counter();value=fn();elapsed=time.perf_counter()-start
    result['operation_times_s'][name]=elapsed;result['outputs'][name]=value
start=time.perf_counter();pipeline={name:fn() for name,fn in operations.items()};result['operation_times_s']['full_pipeline']=time.perf_counter()-start
if pipeline!=result['outputs']:raise RuntimeError('Repeated operation output changed within variant')
print(json.dumps(result,sort_keys=True,allow_nan=False))
