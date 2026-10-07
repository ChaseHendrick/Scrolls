"""Read-only verification of the saved adaptive geometry experiment."""
import os
os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
import sys
sys.dont_write_bytecode = True
import hashlib
import importlib.util
import json
import time
from pathlib import Path
import numpy as np
import tifffile

ROOT = Path('/workspace/scrolls-env/adaptive-margin')
OUT = Path('/workspace/scrolls-env/pr-merge-review')
UM = 9.366
os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def interpolation(corners, uv):
    u, v = np.moveaxis(np.asarray(uv), -1, 0)
    weights = np.stack([(1-u)*(1-v), u*(1-v), (1-u)*v, u*v], -1)
    return weights @ corners

def regular(x):
    valid = np.isfinite(x).all(-1) & (x >= 0).all(-1) & (x.sum(-1) > 0)
    a, b, c, d = x[:-1, :-1], x[1:, :-1], x[:-1, 1:], x[1:, 1:]
    derivatives = [(b-a, c-a), (b-a, d-b), (d-c, c-a), (d-c, d-b)]
    normals = np.stack([np.cross(dr, dc) for dr, dc in derivatives])
    average = np.mean(normals, axis=0)
    good = np.all(np.sum(normals * average[None], -1) > 1e-12, axis=0)
    return good & valid[:-1, :-1] & valid[1:, :-1] & valid[:-1, 1:] & valid[1:, 1:]

def fine_interpolation(x, uv):
    positions = 2 * np.asarray(uv)
    ij = np.minimum(np.floor(positions).astype(int), 1)
    residual = positions - ij
    values = []
    for (i, j), st in zip(ij, residual):
        values.append(interpolation(x[[i, i+1, i, i+1], [j, j, j+1, j+1]], st))
    return np.array(values)

started = time.monotonic()
manifest_checks = []
for line in (ROOT/'SHA256SUMS').read_text().splitlines():
    digest, name = line.split('  ', 1)
    actual = sha(ROOT/name)
    assert digest == actual, name
    manifest_checks.append(dict(file=name, sha256=actual))

rules = [ROOT/'rule.json']
input_checks = []
for path in rules:
    rule = json.loads(path.read_text())
    assert (path.parent/'preregistration.sha256').read_text().split()[0] == sha(path)
    saved = json.loads((path.parent/'result.json').read_text())
    assert saved['rule_sha256'] == sha(path)
    for name, expected in rule['input_hashes'].items():
        actual = sha(Path(name))
        assert expected == actual, name
        input_checks.append(dict(file=name, sha256=actual))

# Independently evaluated bilinear/subcell functions and fresh random UV samples.
rng = np.random.default_rng(310079)
random_bound_checks = []
vertex_uv = np.array([(i/2, j/2) for i in range(3) for j in range(3)])
for k in range(300):
    x = rng.normal(size=(3, 3, 3)) * 25 + np.array([2000, 3000, 15000])
    corners = x[[0, 2, 0, 2], [0, 0, 2, 2]]
    bound = np.linalg.norm(x.reshape(-1, 3) - interpolation(corners, vertex_uv), axis=-1).max()
    uv = rng.random((150, 2))
    observed = np.linalg.norm(fine_interpolation(x, uv) - interpolation(corners, uv), axis=-1).max()
    assert observed <= bound + 1e-9
    random_bound_checks.append(float(observed - bound))

sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('frozen_audit', ROOT/'audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
control = audit.controls()
assert control['passed']
traces = []
for rule_path in rules:
    rule = json.loads(rule_path.read_text())
    result = json.loads((rule_path.parent/'result.json').read_text())
    for saved in result['traces']:
        name = saved['trace']
        directory = ROOT/(name+'.tifxyz')
        arrays = [tifffile.imread(directory/(axis+'.tif')) for axis in 'xyz']
        x = np.stack(arrays, -1).astype(float)
        assert np.isfinite(x).all()
        ulp = max(float(np.spacing(np.asarray(np.max(np.abs(x[..., i])), dtype=a.dtype))) for i, a in enumerate(arrays))
        tolerance = max(.001, 2*np.sqrt(3)*ulp)
        count = int(regular(x).sum())
        blocks = []
        for row in range(0, x.shape[0]-2, 2):
            for col in range(0, x.shape[1]-2, 2):
                patch = x[row:row+3, col:col+3]
                if not regular(patch).all():
                    continue
                corners = patch[[0, 2, 0, 2], [0, 0, 2, 2]]
                bound = float(np.linalg.norm(patch.reshape(-1, 3) - interpolation(corners, vertex_uv), axis=-1).max() * UM)
                blocks.append((row, col, bool(regular(patch[::2, ::2]).all()), bound))
        accepted = np.array([b[2] and b[3] <= rule['max_error_um'] for b in blocks])
        uniform = np.array([b[2] for b in blocks])
        random = np.zeros(len(blocks), bool)
        random[np.random.default_rng(rule['random_mask_seed']).choice(np.flatnonzero(uniform), accepted.sum(), replace=False)] = True
        assert int(accepted.sum()) == saved['selected_blocks']
        assert count == saved['native_regular_quads']
        assert len(blocks) == saved['complete_2x2_blocks']
        assert 3 * int(accepted.sum()) / count == saved['hypothetical_primitive_reduction']
        query_ids = np.random.default_rng(rule['query_seed']).choice(len(blocks), min(40, len(blocks)), replace=False)
        assert [(q['block_index'], q['offset_um']) for q in saved['queries']] == [(int(i), d) for i in query_ids for d in [0, 40, -40]]
        for q in saved['queries']:
            i = q['block_index']
            row, col, _, _ = blocks[i]
            assert (q['row'], q['col']) == (row, col)
            baseline, coarse = audit.query(x[row:row+3, col:col+3], q['offset_um'], tolerance)
            for mode, use_coarse in [('baseline', False), ('adaptive', accepted[i]), ('uniform2', uniform[i]), ('count_matched_random', random[i])]:
                value = coarse if use_coarse else baseline
                assert q[mode] == value, (name, i, q['offset_um'], mode)
        fresh_dense = []
        for i in np.random.default_rng(11070).choice(np.flatnonzero(accepted), 40, replace=False):
            row, col, _, bound = blocks[i]
            patch = x[row:row+3, col:col+3]
            uv = np.random.default_rng(int(i)+17).random((170, 2))
            observed = float(np.linalg.norm(fine_interpolation(patch, uv)-interpolation(patch[[0,2,0,2],[0,0,2,2]], uv), axis=-1).max()*UM)
            assert observed <= bound + 1e-7
            fresh_dense.append(observed-bound)
        summaries = {}
        for mode in ['adaptive', 'uniform2', 'count_matched_random']:
            retained = sum(q['baseline']['valid'] and q[mode]['valid'] for q in saved['queries'])
            native = sum(q['baseline']['valid'] for q in saved['queries'])
            assert retained == saved['query_summaries'][mode]['retained']
            assert native == saved['query_summaries'][mode]['native_eligible']
            assert sum(q[mode]['valid'] for q in saved['queries']) == saved['query_summaries'][mode]['total_eligible']
            summaries[mode] = dict(retained=retained, native=native, total_eligible=saved['query_summaries'][mode]['total_eligible'], unresolved=saved['query_summaries'][mode]['unresolved'])
        assert not saved['primary_hypothesis_passed']
        assert saved['hypothetical_primitive_reduction'] < rule['minimum_primitive_reduction']
        traces.append(dict(trace=name, native_regular_quads=count, blocks=len(blocks), selected=int(accepted.sum()), primitive_reduction=saved['hypothetical_primitive_reduction'], query_summaries=summaries, all_120_saved_queries_exactly_replayed=True, fresh_random_uv_patch_checks=len(fresh_dense), maximum_sample_minus_bound_um=max(fresh_dense)))

receipt = dict(scope='Independent read-only audit; no mesh export or inference', existing_manifest_sha256=sha(ROOT/'SHA256SUMS'), manifest_files_checked=manifest_checks, frozen_input_hashes_checked=input_checks, interpolation_random_patches=300, interpolation_random_uv_per_patch=150, maximum_synthetic_sample_minus_bound_voxels=max(random_bound_checks), frozen_controls=control, traces=traces, defects=[], timing_seconds=time.monotonic()-started, script_sha256=sha(Path(__file__)))
(OUT/'margin-independent-review.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps({k: receipt[k] for k in ['existing_manifest_sha256', 'traces', 'defects', 'timing_seconds']}, indent=2))
