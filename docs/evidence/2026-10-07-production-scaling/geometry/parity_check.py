"""Exact old/new triangle and full projection parity; no performance selection."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import sys,json,importlib,importlib.util,hashlib
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def package(folder):
    name='parity_'+folder
    spec=importlib.util.spec_from_file_location(name,ROOT/folder/'kit/__init__.py',submodule_search_locations=[str(ROOT/folder/'kit')])
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return importlib.import_module(name+'._surface_geometry'),importlib.import_module(name+'.surfacefix')
def freeze():
    files=[Path(__file__),ROOT/'profile-rule.json',ROOT/'baseline/kit/_surface_geometry.py',ROOT/'optimized/kit/_surface_geometry.py']
    p=ROOT/'parity-rule.json'
    if p.exists():raise RuntimeError('Parity rule already frozen')
    p.write_text(json.dumps(dict(hashes={str(f):sha(f) for f in files},seed=93118,
        triangles='float32/float64;batch0,1,2,8,17;scales1e-6,1,1000,1e7;12batches/case;degenerate/collinear/exactplane/ties',
        closest='64 random quads,budgets1/5/17/65,exactallfields',
        larger='Exactall5projectionarrays on frozen64x64/fullreference case',no_numerical_tolerance=True),indent=2)+'\n');print('FROZEN',sha(p))
def run():
    rule=json.loads((ROOT/'parity-rule.json').read_text())
    for p,h in rule['hashes'].items():assert sha(Path(p))==h,p
    before,bs=package('baseline');after,as_=package('optimized');rng=np.random.default_rng(rule['seed']);triangles_count=0;closest_count=0
    for dtype in [np.float32,np.float64]:
        for size in [0,1,2,8,17]:
            for scale in [1e-6,1,1000,1e7]:
                for case in range(12):
                    t=(rng.normal(size=(size,3,3))*scale).astype(dtype);p=(rng.normal(size=3)*scale).astype(dtype)
                    if case==0:t[:]=0
                    elif case==1:t[:,2]=t[:,1]
                    elif case==2:t[:,2]=2*t[:,1]-t[:,0]
                    a=before._triangle_closest(p,t);b=after._triangle_closest(p,t)
                    assert all(np.array_equal(x,y,equal_nan=True) for x,y in zip(a,b)),(dtype,size,scale,case,a,b)
                    triangles_count+=1
    for _ in range(64):
        corners=rng.normal(size=(4,3))*30+100;p=rng.normal(size=3)*30+100
        for budget in [1,5,17,65]:
            a=before.closest_quad(p,corners,.001,budget);b=after.closest_quad(p,corners,.001,budget)
            assert all(np.array_equal(a[k],b[k],equal_nan=True) for k in a),(a,b)
            closest_count+=1
    source=bs._mesh('/workspace/scrolls-env/geometry-validation/w00.tifxyz');source=dict(source,xyz=source['xyz'][64:128,64:128],valid=source['valid'][64:128,64:128])
    reference=bs._mesh('/workspace/scrolls-env/geometry-validation/ag896.tifxyz');tol=max(bs._roundoff(source),bs._roundoff(reference))
    a=before.project(source,reference,50/9.366,tol);b=after.project(source,reference,50/9.366,tol)
    assert all(np.array_equal(a[k],b[k]) for k in a),'Largerprojection differs'
    output=dict(rule_sha256=sha(ROOT/'parity-rule.json'),triangle_batches_exact=triangles_count,closest_budget_cases_exact=closest_count,
        larger_projection_fields_exact=list(a),larger_points=int(source['valid'].sum()),all_pass=True)
    (ROOT/'parity-result.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output))
if __name__=='__main__':freeze() if sys.argv[1:]==['--freeze'] else run()
