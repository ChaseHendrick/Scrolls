"""Independent seeded numerical check of UFSM's published Euler injectivity bound.

No Scrolls inputs, fitting, training or source changes. Numerical smoke test only.
"""
import json
import sys
from pathlib import Path
import numpy as np
import torch

ROOT = Path('/workspace/scrolls-env/ufsm-review/source')
sys.path.insert(0, str(ROOT / 'tools'))
from sheet_reconstruct import flow, lipschitz_bound

torch.set_num_threads(1)
rng = np.random.default_rng(713893)
lo = np.array([-2., 3., -1.])
hi = np.array([4., 16., 8.])
rows = []
for index in range(20):
    field = torch.tensor(rng.normal(size=(1, 3, 4, 5, 6)) * .15, dtype=torch.float64)
    bound = lipschitz_bound(field, lo, hi)
    steps = max(1, int(np.ceil(bound / .4)))
    # Include points outside the field box to exercise border clamping too.
    pairs = rng.uniform(lo - 3, hi + 3, (400, 2, 3))
    points = torch.tensor(pairs.reshape(-1, 3), dtype=torch.float64)
    # One Euler map is flow using velocity/steps and one step.
    out = flow(points, field / steps, lo, hi, 1).numpy().reshape(-1, 2, 3)
    before = np.linalg.norm(pairs[:, 1] - pairs[:, 0], axis=1)
    after = np.linalg.norm(out[:, 1] - out[:, 0], axis=1)
    lower = (1 - bound / steps) * before
    margin = float(np.min(after - lower))
    assert margin >= -1e-11, (index, margin)
    rows.append(dict(index=index, lipschitz_bound=bound, steps=steps,
                     min_pair_ratio=float(np.min(after / before)),
                     theoretical_ratio_floor=1 - bound / steps,
                     min_lower_bound_margin=margin))
print(json.dumps(dict(seed=713893, fields=20, pairs_per_field=400,
                     anisotropic_grid=[4, 5, 6], outside_points_included=True,
                     passed=True, rows=rows), indent=2))
