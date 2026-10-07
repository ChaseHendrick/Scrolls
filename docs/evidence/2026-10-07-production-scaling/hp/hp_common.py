import os
os.environ.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
import sys,json
from pathlib import Path
ROOT=Path('/workspace/scrolls-env/production-speed-v2')
def setup(variant):
    sys.path.insert(0,str(ROOT/variant))
    import zarr,tifffile
    zarr.config.set({'async.concurrency':1,'threading.max_workers':1})
    original=tifffile.imread
    def read(*a,**kw):
        kw.setdefault('maxworkers',1)
        return original(*a,**kw)
    tifffile.imread=read
    from scipy import ndimage
    from kit import auc,hpscore,rowscore,provenance
    return auc,hpscore,rowscore,provenance

def cases():
    base=Path('/workspace/scrolls-env/supervised-surfacefix/reader-baseline')
    labels=Path('/workspace/scrolls-env/geometry-validation/labels-w00')
    large=ROOT/'large-hp-fixture'
    ll=ROOT/'large-input-review/public-inputs/ink-labels/2.403um-volume-20260319124803/20260918'
    return {
      'real640':{'prediction':str(base/'forward_s42.tif'),'control':str(base/'reverse_s42.tif'),
       'labels':str(labels/'inklabels.zarr'),'mask':str(labels/'supervision.zarr'),
       'level':'2','crop':(2720,3360,2720,3360),'surface_shape':(4220,4760),'inner':64,'voxel_um':9.366},
      'public2560':{'prediction':str(large/'published-crop.tif'),'control':str(large/'synthetic-rolled-control.tif'),
       'labels':str(ll/'inklabels.zarr'),'mask':str(ll/'supervision.zarr'),
       'level':'2','crop':(10240,12800,10240,12800),'surface_shape':(16460,18560),'inner':64,'voxel_um':2.403}}

def operations(modules,case):
    auc,hp,rows,_=modules
    cfg=cases()[case];kw={k:v for k,v in cfg.items() if k!='voxel_um'}
    result={'hp_files':lambda:hp.score_files(**kw,voxel_um=cfg['voxel_um'])}
    if case=='real640':
        result['auc_files']=lambda:auc.score_files(**kw,keep_zero=True,bootstrap=1000,block_px=107,compare=cfg['control'],seed=20261007)
        result['rows_files']=lambda:rows.score_files([cfg['prediction']],cfg['voxel_um'],reverse=[cfg['control']])
    return result
