"""Adversarial exact-parity review of batched geometry bounds, outside repo."""
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
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(name, directory):
    package = importlib.util.spec_from_file_location(name, directory/'__init__.py', submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(package)
    sys.modules[name] = module
    package.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location(name+'._surface_geometry', directory/'_surface_geometry.py')
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value

baseline_path = ROOT/'baseline/kit/_surface_geometry.py'
candidate_path = ROOT/'optimized/kit/_surface_geometry.py'
frozen_hashes = {str(p): sha(p) for p in [baseline_path, candidate_path]}
base = load('independent_base', baseline_path.parent)
new = load('independent_candidate', candidate_path.parent)

def exact(a, b):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            exact(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for av, bv in zip(a, b):
            exact(av, bv)
    elif isinstance(a, np.ndarray):
        assert a.dtype == b.dtype and a.shape == b.shape
        assert a.tobytes() == b.tobytes()
    else:
        assert type(a) == type(b)
        assert a == b, (a, b)

class HeapRecorder:
    def __init__(self):
        self.events = []
    def heappush(self, heap, item):
        self.events.append(('push', item))
        return heapq.heappush(heap, item)
    def heappop(self, heap):
        value = heapq.heappop(heap)
        self.events.append(('pop', value))
        return value

started = time.monotonic()
# Check unchanged functions structurally, rather than relying only on tests.
def functions(path):
    return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(path.read_text()).body if isinstance(node, ast.FunctionDef)}
original_ast, updated_ast = functions(baseline_path), functions(candidate_path)
unchanged = sorted(set(original_ast) - {'closest_quad'})
for name in unchanged:
    assert original_ast[name] == updated_ast[name], name
assert set(updated_ast) - set(original_ast) == {'_child_bounds'}

rng = np.random.default_rng(66492810)
bound_groups = 0
for scale, translation in [(1e-7, 0.), (1., 100.), (200., 15000.), (1e6, 1e12)]:
    for sample in range(30):
        corners = rng.normal(size=(4, 3))*scale + translation
        point = rng.normal(size=3)*scale + translation
        ends = np.sort(rng.random((2, 2)), axis=1)
        u0, u1, v0, v1 = ends.ravel()
        um, vm = (u0+u1)/2, (v0+v1)/2
        children = ((u0,um,v0,vm), (u0,um,vm,v1), (um,u1,v0,vm), (um,u1,vm,v1))
        expected = [base._cell_bounds(point, corners, child) for child in children]
        actual = new._child_bounds(point, corners, children)
        exact(expected, actual)
        bound_groups += 1

base_corners = np.array([[100,100,50], [120,100,50], [100,120,50], [120,120,62]], float)
cases = [
    ('warped', np.array([109.,110.,49.]), base_corners),
    ('symmetric_saddle', np.array([100.,100.,101.]), np.array([[99,99,102],[101,99,98],[99,101,98],[101,101,102]], float)),
    ('flat_tie', np.array([110.,110.,51.]), base_corners * [1,1,0] + [0,0,50]),
    ('edge', np.array([120.,110.,51.]), base_corners),
    ('near_edge', np.array([np.nextafter(120.,0),110.,51.]), base_corners),
    ('degenerate', np.array([0.,0.,1.]), np.zeros((4,3))),
    ('collinear', np.array([1.,0.,1.]), np.array([[0,0,0],[1,0,0],[2,0,0],[3,0,0]], float)),
    ('large_translation', np.array([109.,110.,49.])+1e8, base_corners+1e8),
]
for i in range(8):
    cases.append(('random_warp_'+str(i), rng.uniform(99,121,3), base_corners + rng.normal(size=(4,3))*3))
closest_cases = 0
budget_failures = 0
heap_events = 0
for name, point, corners in cases:
    for tolerance in [1e-3, 1e-8]:
        for budget in [1,4,5,9,17,64,256]:
            old_heap, new_heap = HeapRecorder(), HeapRecorder()
            base.heapq, new.heapq = old_heap, new_heap
            before_point, before_corners = point.copy(), corners.copy()
            expected = base.closest_quad(point, corners, tolerance, budget=budget)
            actual = new.closest_quad(point, corners, tolerance, budget=budget)
            exact(expected, actual)
            exact(old_heap.events, new_heap.events)
            exact(before_point, point)
            exact(before_corners, corners)
            budget_failures += not expected['converged']
            closest_cases += 1
            heap_events += len(old_heap.events)
base.heapq = new.heapq = heapq

def mesh(x, valid=None):
    x = np.asarray(x, dtype=float)
    return dict(xyz=x, valid=np.ones(x.shape[:2],bool) if valid is None else valid)
def point(x):
    return mesh(np.asarray(x, dtype=float).reshape(1,1,3))
def plane(n):
    r,c = np.indices((n,n))
    return np.stack([100+20*r,100+20*c,np.zeros_like(r)+50], -1).astype(float)

project_cases = []
for distance in [0., np.nextafter(5.,0), 5., np.nextafter(5.,np.inf), 5.000001, 5.01]:
    for xy in [[110,110], [120,110], [119.99999999,110]]:
        project_cases.append(('threshold',point(xy+[50+distance]),mesh(plane(3)),5.,.001))
hole = plane(3)
valid = np.ones((3,3),bool)
valid[1,1] = False
project_cases.append(('hole',point([110,110,51]),mesh(hole,valid),5.,.001))
project_cases.append(('no_reference',point([110,110,51]),mesh(hole,np.zeros((3,3),bool)),5.,.001))
project_cases.append(('invalid_source',mesh([[[np.nan,np.inf,-np.inf]]],np.array([[False]])),mesh(plane(3)),5.,.001))
folded = plane(2)
folded[1,1] = [90,110,50]
project_cases.append(('folded',point([110,110,51]),mesh(folded),5.,.001))
saddle = cases[1][2][[0,2,1,3]].reshape(2,2,3)
project_cases.append(('nonunique_saddle',point([100,100,101]),mesh(saddle),2.,.001))
for separation in [0.,4.,5.,5.0001,10.]:
    xyz = plane(6)
    valid = np.zeros((6,6),bool)
    valid[:2,:2] = valid[4:,4:] = True
    xyz[4:,4:] = xyz[:2,:2] + [0,0,separation]
    project_cases.append(('remote_rival',point([110,110,51]),mesh(xyz,valid),5.,.001))
flags = dict(valid=0, ambiguous=0, unresolved=0)
for name, source, reference, limit, tol in project_cases:
    expected = base.project(source,reference,limit,tol)
    actual = new.project(source,reference,limit,tol)
    exact(expected, actual)
    for key in flags:
        flags[key] += int(expected[key].sum())

for path, expected in frozen_hashes.items():
    assert sha(Path(path)) == expected
receipt = dict(code_hashes=frozen_hashes, unchanged_functions_ast=unchanged,
    exact_batched_bound_groups=bound_groups, exact_scalar_child_bounds=4*bound_groups,
    closest_quad_cases=closest_cases, exact_heap_events=heap_events,
    budget_abstention_cases=budget_failures, exact_project_cases=len(project_cases),
    project_flag_counts=flags, certificates_or_thresholds_changed=False,
    input_mutation_detected=False, defects=[], elapsed_seconds=time.monotonic()-started,
    script_sha256=sha(Path(__file__)))
(ROOT/'independent-review.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
