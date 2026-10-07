"""Saved command body for the completed supplemental cancellation sweep."""
import os
os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
from pathlib import Path
import numpy as np
import json
import time

p = Path('/workspace/scrolls-env/production-speed-v2/geometry-independent-review/review.py')
ns = {'__file__': str(p), '__name__': 'adversarial'}
exec(p.read_text().split('started=time.monotonic()')[0], ns)
rng = np.random.default_rng(1158328)
records = []
count = 0
t0 = time.monotonic()
for td in [np.float32, np.float64]:
    for pd in [np.float32, np.float64, np.longdouble]:
        for layout in ['C', 'F']:
            for exponent in [10, 23, 24, 25, 51, 52, 53, 54, 60]:
                tri = np.array([[[0, 0, 0], [1, 1, 1], [2, 2, 2]]]*17, dtype=td, order=layout)
                point = np.array([2.**exponent, -2.**exponent, .9], dtype=pd)
                with np.errstate(all='ignore'):
                    a = ns['base']._triangle_closest(point, tri)
                    b = ns['new']._triangle_closest(point, tri)
                if any(not np.array_equal(x, y, equal_nan=True) for x, y in zip(a, b)):
                    records.append({'triangle_dtype': str(np.dtype(td)), 'point_dtype': str(np.dtype(pd)), 'layout': layout, 'exponent': exponent})
                count += 1
            for rep in range(100):
                tri = (rng.normal(size=(17, 3, 3))*10.**rng.integers(-4, 5, size=(17, 3, 3))).astype(td, order=layout)
                point = (rng.normal(size=3)*10.**rng.integers(-4, 5, size=3)).astype(pd)
                with np.errstate(all='ignore'):
                    a = ns['base']._triangle_closest(point, tri)
                    b = ns['new']._triangle_closest(point, tri)
                if any(not np.array_equal(x, y, equal_nan=True) for x, y in zip(a, b)):
                    records.append({'triangle_dtype': str(np.dtype(td)), 'point_dtype': str(np.dtype(pd)), 'layout': layout, 'random_rep': rep})
                count += 1
out = {'candidate_sha256': ns['hashes'][str(ns['newpath'])], 'cases': count, 'mismatches': records, 'elapsed_seconds': time.monotonic()-t0}
(p.parent/'cancellation-audit.json').write_text(json.dumps(out, indent=2)+'\n')
print(json.dumps(out, indent=2))
