"""Residual profiles pinned to c43c41a; fixed larger crop selected before readout."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,time,cProfile,pstats,hashlib,resource
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'baseline'))
from kit.surfacefix import correct,_mesh,_roundoff
from kit._surface_geometry import project
MANIFEST=Path('/workspace/scrolls-env/supervised-surfacefix/actual-maps-manifest.json')
FULL=Path('/workspace/scrolls-env/geometry-validation')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze():
    p=ROOT/'profile-rule.json'
    if p.exists():raise RuntimeError('Already frozen')
    d=json.loads(MANIFEST.read_text());files=[Path(__file__),MANIFEST,MANIFEST.parent/'rule.json']
    for r in [d['baseline'],d['reference']]+d['candidates']:
        files += [MANIFEST.parent/r['mesh']/f for f in ['x.tif','y.tif','z.tif','meta.json']]
        files += [MANIFEST.parent/v['path'] for v in r['maps'].values()]
    for name in ['w00','ag896']:files += [FULL/(name+'.tifxyz')/f for f in ['x.tif','y.tif','z.tif','meta.json']]
    files+=list((ROOT/'baseline/kit').glob('*.py'))
    rule=dict(baseline_revision='c43c41a',input_hashes={str(f):sha(f) for f in files},
        options=json.loads((MANIFEST.parent/'rule.json').read_text())['apply_config'],
        larger=dict(source='w00.tifxyz',source_native_crop=[64,128,64,128],reference='ag896.tifxyz',reference_crop='entire published cachedmesh',
            selection='Fixed64x64 quarter-position nativecrop; no optimization orperformance/reader-based selection',voxel_um=9.366,physical_radius_um=50,
            tolerance='max nativefloat32roundoff ofcroppedsource/fullreference',scope='geometry-only same-sheet publicdata, no reader/mesh export/materialtruth'),
        resources=dict(threads=1,initial_cpu_budget_seconds=180,no_network=True),frozen_before_profiles=True)
    p.write_text(json.dumps(rule,indent=2)+'\n');print('FROZEN',sha(p))
def run():
    rule=json.loads((ROOT/'profile-rule.json').read_text())
    for p,h in rule['input_hashes'].items():assert sha(Path(p))==h,p
    allowed=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,{allowed[min(1,len(allowed)-1)]})
    full=cProfile.Profile();t=time.perf_counter();report=full.runcall(correct,MANIFEST,ROOT/'profile-correct-output',**rule['options']);fulltime=time.perf_counter()-t
    with (ROOT/'full-profile.txt').open('w') as f:pstats.Stats(full,stream=f).sort_stats('cumulative').print_stats(32)
    source=_mesh(FULL/'w00.tifxyz');source=dict(source,xyz=source['xyz'][64:128,64:128].copy(),valid=source['valid'][64:128,64:128].copy())
    reference=_mesh(FULL/'ag896.tifxyz');tol=max(_roundoff(source),_roundoff(reference))
    large=cProfile.Profile();t=time.perf_counter();result=large.runcall(project,source,reference,50/9.366,tol);large_time=time.perf_counter()-t
    with (ROOT/'larger-profile.txt').open('w') as f:pstats.Stats(large,stream=f).sort_stats('cumulative').print_stats(32)
    outcome=dict(rule_sha256=sha(ROOT/'profile-rule.json'),full_profile_seconds=fulltime,larger_profile_seconds=large_time,
        larger_shape=list(source['valid'].shape),larger_valid_source=int(source['valid'].sum()),larger_valid_reference=int(reference['valid'].sum()),
        larger_eligible=int(result['valid'].sum()),larger_unresolved=int(result['unresolved'].sum()),larger_ambiguous=int(result['ambiguous'].sum()),
        full_accepted_regions=report['accepted_regions'],peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    (ROOT/'profile-result.json').write_text(json.dumps(outcome,indent=2)+'\n');print(json.dumps(outcome))
if __name__=='__main__':freeze() if sys.argv[1:]==['--freeze'] else run()
