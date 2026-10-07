"""Read-only checks of PR1996 against its base and linked study helper."""
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

pr = load('pr1996', ROOT / 'grow_track_graph.py')
base = load('pr1996base', ROOT / 'base-grow_track_graph.py')
study = load('study1996', '/tmp/scrolls-pr1996-evidence/vendor/output-spacing-10/support_safe_finalize.py')
rng = np.random.default_rng(1996)
rows = []
for factor in [0.8, 1., 1.0005, 2., 2.5, 4.]:
    for kind in ['plane', 'bent']:
        for i in range(20):
            valid = rng.random((33, 29)) > 0.02
            y, x = np.indices(valid.shape)
            z = np.full(valid.shape, 100.) if kind == 'plane' else 100 + 2*np.sin(x/3.) + 3*np.cos(y/4.)
            grid = np.stack((x+100., y+100., z), -1)
            grid[~valid] = -1.
            coarse = pr.resample_grid(grid, factor)
            default = pr.finalize_coarse_grid(coarse)
            expected = base.finalize_coarse_grid(base.resample_grid(grid, factor))
            support = pr.finalize_coarse_grid(coarse, pr.support_coarse_mask(coarse, valid, factor))
            linked, receipt = study.finalize(coarse, valid, factor)
            rows.append(dict(factor=factor, kind=kind, default_byte_equal=default.tobytes()==expected.tobytes(), linked_byte_equal=support.tobytes()==linked.tobytes(), retained_finite=bool(np.isfinite(support[support[...,0]>=0]).all()), supported=receipt['independent_brute_support']['passed']))

# A complete fine validity mask is not a geometric regularity test.
grid = np.array([[[100.,100.,100.],[101.,100.,100.]],[[101.,101.,100.],[100.,101.,100.]]])
keep = pr.support_coarse_mask(grid, np.ones((2,2), bool), 1.)
# The bow-tie's bilinear derivatives become parallel at u=v=.5.
du = .5*(grid[0,1]-grid[0,0]+grid[1,1]-grid[1,0])
dv = .5*(grid[1,0]-grid[0,0]+grid[1,1]-grid[0,1])
result = dict(cases=rows, summary={k:sum(x[k] for x in rows) for k in ['default_byte_equal','linked_byte_equal','retained_finite','supported']}, bow_tie=dict(all_vertices_kept=bool(keep.all()), center_jacobian_area=float(np.linalg.norm(np.cross(du,dv)))), limitations='Synthetic algorithm equivalence and invariant checks only; not a real-data coverage or performance reproduction.')
(ROOT/'review-checks.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'n':len(rows),'summary':result['summary'],'bow_tie':result['bow_tie']}))
