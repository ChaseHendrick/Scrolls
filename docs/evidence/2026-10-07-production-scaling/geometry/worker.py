"""Cold correction/large-geometry worker with inner stage timing and peak RSS."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,time,hashlib,resource
from pathlib import Path
ROOT=Path(__file__).resolve().parent
version,case_text,out,metadata=sys.argv[1:]
case=json.loads(case_text);sys.path.insert(0,str(ROOT/version))
import numpy as np
import kit._surface_geometry as geometry
from kit.surfacefix import correct,_mesh,_roundoff
original=geometry.project;capture=dict(seconds=0.,projection={})
def timed(*args,**kwargs):
    t=time.perf_counter();result=original(*args,**kwargs);capture['seconds']=time.perf_counter()-t
    capture['projection']={k:v.copy() for k,v in result.items()};return result
geometry.project=timed
if case['mode']=='geometry':
    source=_mesh(case['source']);r0,r1,c0,c1=case['source_crop']
    source=dict(source,xyz=source['xyz'][r0:r1,c0:c1].copy(),valid=source['valid'][r0:r1,c0:c1].copy())
    reference=_mesh(case['reference']);tol=max(_roundoff(source),_roundoff(reference))
    t=time.perf_counter();timed(source,reference,case['radius_um']/case['voxel_um'],tol)
    result=dict(full_seconds=time.perf_counter()-t,geometry_seconds=capture['seconds'],report=None,output_hashes={})
else:
    t=time.perf_counter()
    try:report=correct(case['manifest'],out,**case['options'])
    except Exception as exc:
        if case['mode']!='negative':raise
        result=dict(full_seconds=time.perf_counter()-t,geometry_seconds=capture['seconds'],error=str(exc),type=type(exc).__name__,output_exists=Path(out).exists())
    else:
        if case['mode']=='negative':raise AssertionError('Negative candidate accepted')
        result=dict(full_seconds=time.perf_counter()-t,geometry_seconds=capture['seconds'],report=report,
            output_hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(out).rglob('*') if p.is_file()})
if case['mode']!='negative':np.savez(metadata+'.npz',**capture['projection'])
result['peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
Path(metadata+'.json').write_text(json.dumps(result,indent=2)+'\n')
