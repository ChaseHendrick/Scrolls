"""Render only the actual accepted corrected mesh with the frozen official CT pipeline."""
from pathlib import Path
import hashlib,importlib.util,json,os
import tifffile
import numpy as np
ROOT=Path('/workspace/scrolls-env/supervised-surfacefix');sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
report=ROOT/'actual-apply/report.json';record=json.loads(report.read_text())
if record['accepted_regions']<=0:raise RuntimeError('No accepted geometry; combined rerender is not applicable')
amend=ROOT/'schema2-code-amendment.json';frozen=json.loads(amend.read_text())
for p,h in frozen['input_sha256'].items():
 if sha(p)!=h:raise ValueError('Frozen implementation/input changed: '+p)
mesh=ROOT/'actual-apply/corrected.tifxyz';mesh_hashes={p.name:sha(p) for p in mesh.iterdir() if p.is_file()}
if set(mesh_hashes)!=set(['x.tif','y.tif','z.tif','meta.json']):raise ValueError('Unexpected corrected mesh files')
orientation=json.loads((ROOT/'published-audit-result.json').read_text())
if orientation['all_pass'] is not True or any(v['canonical_order']!='reversed_minus_N' for v in orientation['parts'].values()):raise ValueError('Published source raster/depth gate failed')
spec=importlib.util.spec_from_file_location('official_renderer_adapter',ROOT/'stage_and_render.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rule=m.verify_rule();m.render(rule,'combined',mesh)
raw=ROOT/'tif-combined';layers=ROOT/'layers-combined'
if layers.exists():raise ValueError('Refuse canonical output overwrite')
layers.mkdir()
for i in range(28):
 source=raw/f'{27-i:02d}.tif';a=tifffile.imread(source)
 if a.shape!=(640,640) or a.dtype!=np.uint8:raise ValueError('Unexpected actual combined renderer output')
 os.link(source,layers/f'{i:02d}.tif')
if mesh_hashes!={p.name:sha(p) for p in mesh.iterdir() if p.is_file()}:raise ValueError('Corrected geometry changed during renderer')
renderer_receipt=ROOT/'tif-combined-receipt.json';engine=json.loads(renderer_receipt.read_text())
if engine['source_mesh_hashes']!=mesh_hashes or engine['binary_sha256']!=rule['render']['official_binary_sha256']:raise ValueError('Render receipt geometry or official engine mismatch')
proof={'schema':1,'scope':'Actual accepted merged geometry rendered by official engine from rawCT; no surrogate map assembly',
       'corrected_mesh':str(mesh),'corrected_mesh_sha256':mesh_hashes,'surfacefix_report_sha256':sha(report),
       'renderer_receipt':str(renderer_receipt),'renderer_receipt_sha256':sha(renderer_receipt),
       'engine_sha256':engine['binary_sha256'],'engine_source_revision':'1e3f4c021f4e53bea3867772ed05f51a7e586a9c',
       'ct_cache_receipt_sha256':sha(ROOT/'ct-cache-receipt.json'),'canonical_layers_dir':str(layers),
       'canonical_depth_order':'published_minus_N_from_reversed_official_plus_N',
       'canonical_layer_sha256':{p.name:sha(p) for p in layers.iterdir()},
       'implementation_amendment_sha256':sha(amend),'renderer_adapter_sha256':sha(ROOT/'stage_and_render.py'),
       'combined_render_script_sha256':sha(__file__)}
with (ROOT/'combined-render-proof.json').open('x') as stream:json.dump(proof,stream,indent=2);stream.write('\n')
print(layers,flush=True)
