import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,cProfile,pstats,json,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'baseline'))
from kit.surfacefix import correct
import kit._surface_geometry as geometry
rule=json.loads((ROOT/'profile-rule.json').read_text())
for p,h in rule['input_hashes'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
original=geometry.project
geometry_seconds=[]
def timed(*args,**kwargs):
    t=time.perf_counter();result=original(*args,**kwargs);geometry_seconds.append(time.perf_counter()-t)
    return result
geometry.project=timed
prof=cProfile.Profile();t=time.perf_counter()
report=prof.runcall(correct,'/workspace/scrolls-env/supervised-surfacefix/actual-maps-manifest.json',ROOT/'baseline-profile',**rule['apply_config'])
elapsed=time.perf_counter()-t
prof.dump_stats(str(ROOT/'baseline.prof'))
with (ROOT/'baseline-profile.txt').open('w') as f:
    pstats.Stats(prof,stream=f).sort_stats('cumulative').print_stats(32)
(ROOT/'baseline-profile-result.json').write_text(json.dumps(dict(full_seconds=elapsed,geometry_seconds=geometry_seconds,
    accepted_regions=report['accepted_regions'],flagged_regions=report['flagged_regions']),indent=2)+'\n')
print('Full seconds',elapsed,'geometry seconds',geometry_seconds,flush=True)
