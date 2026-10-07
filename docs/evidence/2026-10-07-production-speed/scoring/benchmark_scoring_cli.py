import os
os.environ.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
import sys
from pathlib import Path
root=Path('/workspace/scrolls-env/production-speed');variant=sys.argv[1];sys.path.insert(0,str(root/variant))
import zarr,tifffile
zarr.config.set({'async.concurrency':1,'threading.max_workers':1})
original=tifffile.imread

def imread(*args,**kwargs):
    kwargs.setdefault('maxworkers',1)
    return original(*args,**kwargs)

tifffile.imread=imread
from kit import cli
base='/workspace/scrolls-env/supervised-surfacefix/reader-baseline/'
labels='/workspace/scrolls-env/geometry-validation/labels-w00/'
raise SystemExit(cli.main(['auc',base+'forward_s42.tif','--control',base+'reverse_s42.tif',
    '--labels',labels+'inklabels.zarr','--mask',labels+'supervision.zarr','--level','2',
    '--crop','2720','3360','2720','3360','--surface-shape','4220','4760','--inner','64',
    '--keep-zero','--bootstrap','1000','--block-px','107','--compare',base+'reverse_s42.tif',
    '--seed','20261007','--json']))
