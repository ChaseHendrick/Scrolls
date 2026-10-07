"""Cold process worker: all imports, correction, I/O and exit are timed by parent."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
version,manifest,out,metadata,options,negative=sys.argv[1:]
sys.path.insert(0,str(ROOT/version))
import numpy as np
import kit._surface_geometry as geometry
from kit.surfacefix import correct
original=geometry.project;capture=dict(seconds=0.,projection={})
def timed(*args,**kwargs):
    t=time.perf_counter();result=original(*args,**kwargs);capture['seconds']=time.perf_counter()-t
    capture['projection']={k:v.copy() for k,v in result.items()};return result
geometry.project=timed
started=time.perf_counter()
try:report=correct(manifest,out,**json.loads(options))
except Exception as exc:
    if negative!='1':raise
    result=dict(full_seconds=time.perf_counter()-started,geometry_seconds=capture['seconds'],error=str(exc),type=type(exc).__name__,output_exists=Path(out).exists())
else:
    if negative=='1':raise AssertionError('Negative candidate accepted')
    result=dict(full_seconds=time.perf_counter()-started,geometry_seconds=capture['seconds'],report=report,
        output_hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(out).rglob('*') if p.is_file()})
    np.savez(metadata+'.npz',**capture['projection'])
Path(metadata+'.json').write_text(json.dumps(result,indent=2)+'\n')
