"""Prepare frozen schema2 ±1 normal candidates after parent geometry-test GO."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path('/workspace/scrolls-env/supervised-surfacefix');REPO=Path('/workspace/Scrolls')
sys.path.insert(0,str(REPO))
from kit.surfacefix import prepare,_hashes
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
rule=json.loads((ROOT/'rule.json').read_text())
source=Path(rule['meshes']['baseline']['path'])
if _hashes(source)!=rule['meshes']['baseline']['hashes']:raise ValueError('Source geometry changed')
inputs=[REPO/'kit/surfacefix.py',REPO/'kit/_surface_geometry.py',REPO/'kit/hpscore.py',REPO/'kit/verify.py',REPO/'tests/test_surfacefix.py',REPO/'tests/test_surface_geometry.py',Path('/workspace/scrolls-env/followup-tests-frozen.log'),ROOT/'rule.json',ROOT/'label-evaluation-rule.json',ROOT/'published-audit-result.json',ROOT/'stage_and_render.py',ROOT/'apply_real_validation.py',Path(__file__),Path('/workspace/scrolls-env/infer_layers_cpu.py'),Path('/tmp/villa-edge-renderer.cpp'),Path('/tmp/villa-edge-QuadSurface.cpp')]
inputs += sorted(ROOT.glob('layers-*/*.tif'))
frozen={str(p):sha(p) for p in inputs}
candidate_path=ROOT/'w00-crop-candidates/manifest.json'
if candidate_path.exists():
    manifest=json.loads(candidate_path.read_text())
    geometry=json.loads((ROOT/'candidate-geometry-record.json').read_text())
    if sha(candidate_path)!=geometry['candidate_manifest_sha256']:raise ValueError('Prepared geometry manifest changed')
    for c in manifest['candidates']:
        if _hashes(ROOT/'w00-crop-candidates'/c['mesh'])!=c['hashes']:raise ValueError('Candidate geometry changed')
else:
    manifest=prepare(source,ROOT/'w00-crop-candidates',rule['voxel_um'],rule['offsets_vox'],max_shift_um=rule['max_shift_um'])
if manifest['schema']!=2 or manifest['matching_mode']!='certified_bilinear_reference_v1':raise ValueError('Final implementation must prepare declared schema2')
if frozen!={str(p):sha(p) for p in inputs}:raise ValueError('Implementation/inputs changed during preparation')
record={'scope':'Frozen supervised schema2 geometry/reader/render/control implementation before any new maps','input_sha256':frozen,'candidate_manifest_sha256':sha(ROOT/'w00-crop-candidates/manifest.json'),'candidate_mesh_hashes':{c['mesh']:_hashes(ROOT/'w00-crop-candidates'/c['mesh']) for c in manifest['candidates']},'thresholds':rule['apply_config'],'offsets_vox':rule['offsets_vox'],'voxel_um':rule['voxel_um'],'max_shift_um':rule['max_shift_um'],'official_linear_position_evidence':'Pinned source1e3f4c QuadSurface::gen lines730..811 calls four-corner warpBilinearReplicateVec3f; no position-interpolation flag exists in this engine','render_geometry':manifest['render_geometry'],'test_evidence':'Parent full suite passes146 tests, including remote rival and same-quad nearest-point ambiguity refusals; independent geometry review signoff required before this freeze/inference','labels_never_choose_offsets':True,'final_combined_rerender_required_if_accepted':True}
p=ROOT/'schema2-code-amendment.json'
with p.open('x') as stream:json.dump(record,stream,indent=2);stream.write('\n')
print('FROZEN',sha(p),flush=True)
print(json.dumps(manifest,indent=2),flush=True)
