"""Bounded independent exact-parity audit of triangle edge vectorization."""
import os
os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
import sys
sys.dont_write_bytecode = True
import ast
import hashlib
import heapq
import importlib.util
import json
import time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
GEOMETRY = ROOT.parent/'geometry'
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(name, directory):
    package = importlib.util.spec_from_file_location(name, directory/'__init__.py', submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(package)
    sys.modules[name] = module
    package.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location(name+'._surface_geometry', directory/'_surface_geometry.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

basepath = GEOMETRY/'baseline/kit/_surface_geometry.py'
newpath = GEOMETRY/'optimized/kit/_surface_geometry.py'
base = load('v2_review_baseline', basepath.parent)
new = load('v2_review_candidate', newpath.parent)
hashes = {str(p):sha(p) for p in [basepath,newpath]}

def exact(a,b):
    if isinstance(a,dict):
        assert a.keys() == b.keys()
        for k in a: exact(a[k],b[k])
    elif isinstance(a,(list,tuple)):
        assert len(a)==len(b)
        for x,y in zip(a,b): exact(x,y)
    elif isinstance(a,np.ndarray):
        assert a.shape==b.shape and a.dtype==b.dtype,(a.shape,b.shape,a.dtype,b.dtype)
        if a.dtype.kind == 'f' and a.dtype.itemsize > 8:
            # The x87 extended type has non-value padding bytes on this platform.
            assert np.array_equal(a,b,equal_nan=True)
            assert np.array_equal(np.signbit(a),np.signbit(b))
        else:
            assert a.tobytes()==b.tobytes()
    elif isinstance(a,(float,np.floating)) and np.isnan(a):
        assert np.isnan(b)
    else:
        assert type(a)==type(b)
        assert a==b,(a,b)

class HeapRecorder:
    def __init__(self): self.events=[]
    def heappush(self,heap,item):
        self.events.append(('push',item))
        return heapq.heappush(heap,item)
    def heappop(self,heap):
        value=heapq.heappop(heap)
        self.events.append(('pop',value))
        return value

def capture(call):
    try:
        return {'result':call()}
    except Exception as error:
        return {'exception_class':type(error).__module__+'.'+type(error).__name__,'message':str(error)}

started=time.monotonic()
def functions(path):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef)}
before_ast,after_ast=functions(basepath),functions(newpath)
unchanged=sorted(set(before_ast)-{'_triangle_closest'})
for name in unchanged:assert before_ast[name]==after_ast[name],name
assert set(after_ast)-set(before_ast)=={'_triangle_closest_scalar'}
assert after_ast['_triangle_closest_scalar'].replace("name='_triangle_closest_scalar'","name='_triangle_closest'",1)==before_ast['_triangle_closest']

rng=np.random.default_rng(17893072)
triangle_cases=[]
for triangle_dtype in [np.float16,np.float32,np.float64,np.longdouble]:
    for point_dtype in [np.float32,np.float64,np.longdouble]:
        for n in [0,1,2,8,17]:
            for layout in ['c','fortran','strided']:
                values=rng.uniform(-3,3,(n,3,6)).astype(triangle_dtype)
                triangles=values[...,::2]
                if layout=='c':triangles=triangles.copy(order='C')
                if layout=='fortran':triangles=np.asfortranarray(triangles)
                point=rng.uniform(-4,4,3).astype(point_dtype)
                triangle_cases.append((f'{np.dtype(triangle_dtype)}/{np.dtype(point_dtype)}/{n}/{layout}',point,triangles))

controls=[]
for dtype in [np.float16,np.float32,np.float64,np.longdouble]:
    for label,point,triangle,expected in [
        ('interior',[1,1,1],[[0,0,0],[3,0,0],[0,3,0]],None),
        ('first_edge_tie',[1,0,1],[[0,0,0],[1,0,0],[2,0,0]],[0,1,0]),
        ('second_edge_tie',[1,0,1],[[0,0,0],[0,0,0],[2,0,0]],[0,.5,.5]),
        ('collapsed',[0,0,1],[[0,0,0],[0,0,0],[0,0,0]],[1,0,0]),
        ('vertex',[0,0,1],[[0,0,0],[3,0,0],[0,3,0]],[1,0,0]),
    ]:
        p=np.array(point,dtype=dtype); t=np.array([triangle],dtype=dtype)
        triangle_cases.append((label+'/'+str(np.dtype(dtype)),p,t))
        if expected is not None:
            a=new._triangle_closest(p,t)
            assert np.array_equal(a[1],np.array([expected],dtype=a[1].dtype)),label
            controls.append(label+'/'+str(np.dtype(dtype)))

# Signed zero, nonfinite values, and finite extreme magnitudes exercise the
# inherited numerical behavior without claiming malformed inputs are useful.
for dtype in [np.float32,np.float64]:
    for label,value in [('nan',np.nan),('positive_inf',np.inf),('negative_inf',-np.inf),('negative_zero',-0.0),('tiny',np.finfo(dtype).tiny),('large',np.sqrt(np.finfo(dtype).max)/4)]:
        t=np.array([[[0,0,0],[3,0,0],[0,3,0]]],dtype=dtype)
        t[0,1,2]=value
        triangle_cases.append((label+'/'+str(np.dtype(dtype)),np.array([1,1,1],dtype=dtype),t))

triangle_checks=0
for label,point,triangles in triangle_cases:
    before_point,before_triangles=point.copy(),triangles.copy()
    with np.errstate(all='ignore'):
        expected=capture(lambda:base._triangle_closest(point,triangles))
        actual=capture(lambda:new._triangle_closest(point,triangles))
    try:exact(expected,actual)
    except AssertionError as error:raise AssertionError('triangle case '+label) from error
    exact(point,before_point);exact(triangles,before_triangles)
    triangle_checks+=1

# Invalid shape and integer inputs must retain the inherited exception class.
invalid_shapes=[]
for shape in [(1,2,3),(1,4,3),(3,3),(1,3,2)]:
    triangles=np.ones(shape)
    expected=capture(lambda:base._triangle_closest(np.zeros(3),triangles))
    actual=capture(lambda:new._triangle_closest(np.zeros(3),triangles))
    if 'exception_class' in expected:
        assert expected['exception_class']==actual.get('exception_class'),shape
    else:exact(expected,actual)
    invalid_shapes.append({'shape':shape,'baseline_exception':expected.get('exception_class')})
for dtype in [np.int16,np.int64]:
    triangles=np.ones((1,3,3),dtype=dtype)
    expected=capture(lambda:base._triangle_closest(np.ones(3,dtype=dtype),triangles))
    actual=capture(lambda:new._triangle_closest(np.ones(3,dtype=dtype),triangles))
    assert expected.get('exception_class')==actual.get('exception_class')

solver_checks=0;budget_abstentions=0;heap_events=0
for dtype in [np.float32,np.float64,np.longdouble]:
    for warp in [0.,.1,4.,12.]:
        corners=np.array([[100,100,50],[120,100,50],[100,120,50],[120,120,50+warp]],dtype=dtype)
        point=np.array([109,110,49],dtype=dtype)
        for tolerance,budget in [(1e-3,1),(1e-3,5),(1e-3,17),(1e-3,256),(1e-8,5),(1e-8,64)]:
            hb,hn=HeapRecorder(),HeapRecorder();base.heapq,new.heapq=hb,hn
            expected=base.closest_quad(point,corners,tolerance,budget)
            actual=new.closest_quad(point,corners,tolerance,budget)
            exact(expected,actual);exact(hb.events,hn.events)
            solver_checks+=1;budget_abstentions+=not expected['converged'];heap_events+=len(hb.events)
base.heapq=new.heapq=heapq

def mesh(x,valid=None):
    x=np.asarray(x,float)
    return {'xyz':x,'valid':np.ones(x.shape[:2],bool) if valid is None else valid}
def point(x):return mesh(np.asarray(x).reshape(1,1,3))
def plane(n):
    r,c=np.indices((n,n));return np.stack([100+20*r,100+20*c,np.zeros_like(r)+50],-1).astype(float)
projects=[]
for z in [np.nextafter(55.,0),55.,np.nextafter(55.,np.inf),55.000001]:
    for xy in [[110,110],[120,110],[119.999999999,110]]:projects.append((point(xy+[z]),mesh(plane(3)),5.,.001))
valid=np.ones((3,3),bool);valid[1,1]=False
projects.append((point([110,110,51]),mesh(plane(3),valid),5.,.001))
projects.append((point([110,110,51]),mesh(plane(3),np.zeros((3,3),bool)),5.,.001))
projects.append((mesh([[[np.nan,np.inf,-np.inf]]],np.array([[False]])),mesh(plane(3)),5.,.001))
saddle=np.array([[[99,99,102],[99,101,98]],[[101,99,98],[101,101,102]]],float)
projects.append((point([100,100,101]),mesh(saddle),2.,.001))
for separation in [0.,4.,5.,5.0001,10.]:
    x=plane(6);valid=np.zeros((6,6),bool);valid[:2,:2]=valid[4:,4:]=True
    x[4:,4:]=x[:2,:2]+[0,0,separation]
    projects.append((point([110,110,51]),mesh(x,valid),5.,.001))
flags={k:0 for k in ['valid','ambiguous','unresolved']}
for source,reference,radius,tol in projects:
    expected=base.project(source,reference,radius,tol);actual=new.project(source,reference,radius,tol)
    exact(expected,actual)
    for k in flags:flags[k]+=int(expected[k].sum())

for p,digest in hashes.items():assert sha(Path(p))==digest
result={'source_hashes':hashes,'unchanged_functions_ast':unchanged,
 'triangle_cases_exact':triangle_checks,'explicit_tie_controls':controls,
 'invalid_shape_outcomes':invalid_shapes,'integer_exception_classes_unchanged':True,
 'closest_quad_cases_exact':solver_checks,'budget_abstentions':budget_abstentions,
 'heap_events_exact':heap_events,'projection_cases_exact':len(projects),
 'projection_flags':flags,'source_arrays_unchanged':True,'defects_in_reviewed_candidate':[],
 'longdouble_comparison':'Exact values, signs and dtype; ignores non-value x87 padding bytes',
 'elapsed_seconds':time.monotonic()-started,'review_script_sha256':sha(Path(__file__))}
(ROOT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
