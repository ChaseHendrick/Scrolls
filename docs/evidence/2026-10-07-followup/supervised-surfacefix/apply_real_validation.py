"""Frozen real-map correction, geometry failure, and eight full-selection nulls."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import numpy as np
import tifffile

sys.path.insert(0, '/workspace/Scrolls')
from kit.surfacefix import correct, _hashes
from kit.verify import VerifyError

ROOT = Path('/workspace/scrolls-env/supervised-surfacefix')
MODEL_DIGEST = '50d2ad0ef7690a6a422640804d38f01409da8bc96cfc1ab72f45324a4a18f966'
MODEL = 'd9v2_ft-012000@sha256:' + MODEL_DIGEST
KINDS = ('forward', 'reverse', 'shuffle')
RULE = json.loads((ROOT / 'rule.json').read_text())
NULL_RULE = {'cases': [{'axis': 0 if dy else 1, 'shift_px': dy or dx} for dy, dx in RULE['null_test']['reference_map_triplet_joint_no_wrap_shifts_yx']]}
OPTIONS = RULE['apply_config']
AMENDMENT = json.loads((ROOT / 'schema2-code-amendment.json').read_text())
for frozen_file, expected_hash in AMENDMENT['input_sha256'].items():
    if hashlib.sha256(Path(frozen_file).read_bytes()).hexdigest() != expected_hash:
        raise RuntimeError('Frozen implementation/harness/input changed: ' + frozen_file)

def dump(path, record):
    with path.open('x') as stream:
        json.dump(record, stream, indent=2, allow_nan=False)
        stream.write('\n')

def maps(tag):
    directory = ROOT / ('reader-' + tag)
    observed = json.loads((directory / 'inference_manifest.json').read_text())
    if (observed['status'] != 'inference_completed_scoring_pending' or
            observed['checkpoint_sha256'] != MODEL_DIGEST or observed['stride'] != 42 or
            observed['villa_revision'] != 'e0bbb8b40a2db58b1d71864f286eb85717e59e64' or
            observed['selected_source_layers'] != list(range(6, 23)) or
            observed['reverse_source_layers'] != list(range(22, 5, -1)) or
            observed['shuffle_seed'] != 20261007 or observed['mirror_tta'] or
            observed['blend_mode'] != 'hann'):
        raise RuntimeError('Inference settings do not match frozen reader amendment')
    result = {}
    for kind in KINDS:
        file = directory / (kind + '_s42.tif')
        array = tifffile.imread(file)
        if array.shape != (640, 640) or array.dtype != np.uint8:
            raise RuntimeError('Invalid actual reader output')
        result[kind] = {'path': str(file.relative_to(ROOT)), 'model': MODEL, 'stride': 42}
    return result

def summarize(report):
    regions = report['regions']
    n = OPTIONS['min_points']
    return {'status': report['status'], 'accepted_regions': report['accepted_regions'],
            'flagged_regions': report['flagged_regions'], 'regions_examined': len(regions),
            'evaluable_regions': sum(min(r['selection_points'], r['held_back_points']) >= n for r in regions),
            'candidate_selection_attempted_regions': sum('winner' in r for r in regions),
            'selection_points': sum(r['selection_points'] for r in regions),
            'held_back_points': sum(r['held_back_points'] for r in regions),
            'covered_points': sum(r['selection_points'] + r['held_back_points'] for r in regions),
            'native_valid_points': sum(r['points'] for r in regions)}

manifest = json.loads((ROOT / 'w00-crop-candidates/manifest.json').read_text())
manifest.update(model=MODEL, stride=42)
manifest['baseline']['mesh'] = 'w00-crop.tifxyz'
manifest['baseline']['maps'] = maps('baseline')
manifest['reference'] = {'mesh': 'ag896-crop.tifxyz', 'hashes': _hashes(ROOT / 'ag896-crop.tifxyz'),
                         'maps': maps('reference')}
for record, tag in zip(manifest['candidates'], ('minus1', 'plus1')):
    record['mesh'] = 'w00-crop-candidates/' + record['mesh']
    record['maps'] = maps(tag)
manifest['frozen_rules'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                            [ROOT / 'rule.json', ROOT / 'label-evaluation-rule.json', ROOT / 'schema2-code-amendment.json',
                             ROOT / 'published-audit-result.json']}
actual_path = ROOT / 'actual-maps-manifest.json'
dump(actual_path, manifest)

# Hashes are recomputed deliberately: refusal must be geometric, not a stale-hash check.
bad_mesh = ROOT / 'tangential-candidate.tifxyz'
shutil.copytree(ROOT / manifest['candidates'][1]['mesh'], bad_mesh)
x = tifffile.imread(bad_mesh / 'x.tif')
if x[8, 12] < 0:
    raise RuntimeError('Frozen tampering point is not a valid native node')
x[8, 12] += .5
tifffile.imwrite(bad_mesh / 'x.tif', x)
bad = copy.deepcopy(manifest)
bad['candidates'][1].update(mesh=bad_mesh.name, hashes=_hashes(bad_mesh))
bad_path = ROOT / 'tangential-manifest.json'
dump(bad_path, bad)
try:
    correct(bad_path, ROOT / 'must-not-exist-tangential-output', **OPTIONS)
except VerifyError as exc:
    if 'normal offset' not in str(exc):
        raise RuntimeError('Tangential negative failed for the wrong reason: ' + str(exc)) from exc
    tampering = {'refused': True, 'changed_vox': .5, 'changed_axis': 'x', 'native_node': [8, 12],
                 'candidate_hashes_recomputed': True, 'error': str(exc),
                 'output_created': (ROOT / 'must-not-exist-tangential-output').exists()}
else:
    raise RuntimeError('Tangential candidate was accepted despite normal-only rule')
if tampering['output_created']:
    raise RuntimeError('Rejected tangential geometry left a corrected output')

report = correct(actual_path, ROOT / 'actual-apply', **OPTIONS)
summary = {'scope': 'Fixed supervised public PHerc0841 same-sheet model-output consistency; labels never choose offsets and final merged geometry requires official rerender before label-improvement assessment',
           'normal': summarize(report), 'tangential_geometry_negative': tampering,
           'source_hashes_unchanged': _hashes(ROOT / 'w00-crop.tifxyz') == RULE['meshes']['baseline']['hashes'],
           'null_rule_sha256': hashlib.sha256((ROOT / 'rule.json').read_bytes()).hexdigest(),
           'nulls': [], 'significance': 'No statistical significance claim: eight null cases are dependent and some may lack coverage.'}
dump(ROOT / 'actual-apply-summary.json', summary)
print('normal', json.dumps(summary['normal']), flush=True)
reference_maps = {kind: tifffile.imread(ROOT / manifest['reference']['maps'][kind]['path']) for kind in KINDS}
for case in NULL_RULE['cases']:
    axis, shift = case['axis'], case['shift_px']
    tag = 'axis' + str(axis) + '-shift' + str(shift)
    null = copy.deepcopy(manifest)
    directory = ROOT / ('null-' + tag)
    directory.mkdir()
    for kind, array in reference_maps.items():
        moved = np.zeros_like(array)
        destination, source = [slice(None)] * 2, [slice(None)] * 2
        destination[axis] = slice(shift, None) if shift > 0 else slice(None, shift)
        source[axis] = slice(None, -shift) if shift > 0 else slice(-shift, None)
        moved[tuple(destination)] = array[tuple(source)]
        file = directory / (kind + '.tif')
        tifffile.imwrite(file, moved)
        null['reference']['maps'][kind]['path'] = str(file.relative_to(ROOT))
    null_path = ROOT / ('null-manifest-' + tag + '.json')
    dump(null_path, null)
    result = correct(null_path, ROOT / ('null-apply-' + tag), **OPTIONS)
    row = dict(case, **summarize(result))
    summary['nulls'].append(row)
    print('null', json.dumps(row), flush=True)
dump(ROOT / 'actual-validation-with-nulls.json', summary)
print('complete', ROOT / 'actual-validation-with-nulls.json', flush=True)
