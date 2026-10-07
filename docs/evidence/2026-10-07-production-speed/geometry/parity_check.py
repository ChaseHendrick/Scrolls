"""Exact scalar/batched geometry parity checks before repeated timing."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import importlib.util,importlib,sys,json,hashlib
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
def package(name,folder):
    spec=importlib.util.spec_from_file_location(name,ROOT/folder/'kit/__init__.py',submodule_search_locations=[str(ROOT/folder/'kit')])
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return importlib.import_module(name+'._surface_geometry')
before=package('speed_before','baseline');after=package('speed_after','optimized')
rng=np.random.default_rng(911074);checked=0;closest=0
for i in range(160):
    corners=rng.normal(size=(4,3))*rng.choice([.01,1,30,1000])+rng.normal(size=3)*300
    point=rng.normal(size=3)*30+corners.mean(0)
    u0,v0=rng.uniform(0,.4,2);u1,v1=rng.uniform(.6,1,2);um,vm=(u0+u1)/2,(v0+v1)/2
    boxes=((u0,um,v0,vm),(u0,um,vm,v1),(um,u1,v0,vm),(um,u1,vm,v1))
    batch=after._child_bounds(point,corners,boxes)
    for box,result in zip(boxes,batch):
        scalar=before._cell_bounds(point,corners,box)
        assert scalar[:2]==result[:2],(i,scalar,result)
        assert np.array_equal(scalar[2],result[2]),(i,scalar,result)
        checked+=1
    for budget in [1,5,17,65]:
        a=before.closest_quad(point,corners,.001,budget);b=after.closest_quad(point,corners,.001,budget)
        assert all(np.array_equal(a[k],b[k]) for k in a),(i,budget,a,b)
        closest+=1
(ROOT/'parity-result.json').write_text(json.dumps(dict(seed=911074,child_bounds_exact=checked,closest_quad_exact=closest,all_pass=True),indent=2)+'\n')
print('Exact parity:',checked,'child bounds;',closest,'budgeted closest-quads')
