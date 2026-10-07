import os
os.environ.update({k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')})
if hasattr(os,'sched_getaffinity'):os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
import json, hashlib
from pathlib import Path
import numpy as np,tifffile
root=Path('/workspace/scrolls-env/production-speed-v2')
receipt=json.loads((root/'large-input-review/public-input-receipt.json').read_text())
source=Path(receipt[0]['path'])
assert hashlib.sha256(source.read_bytes()).hexdigest()==receipt[0]['sha256']
box=(10240,12800,10240,12800)
full=tifffile.imread(source,maxworkers=1)
assert full.shape==(16460,18560)
crop=full[box[0]:box[1],box[2]:box[3]].copy();del full
out=root/'large-hp-fixture';out.mkdir(exist_ok=True)
tifffile.imwrite(out/'published-crop.tif',crop)
tifffile.imwrite(out/'synthetic-rolled-control.tif',np.roll(crop,523,axis=0))
record={'source':receipt[0],'source_shape':[16460,18560],'crop':list(box),'voxel_um':2.403,'control':'Synthetic523-row roll of public prediction, only performance/parity workload; not reverse-depth control or ink evidence.','files_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.tif'))},'shape':list(crop.shape),'zero_pixels':int((crop==0).sum())}
(root/'large-hp-fixture.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
