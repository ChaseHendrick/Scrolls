"""Bounded real-control I/O-only profile; no model or target inference."""
from pathlib import Path
import ast
import collections
import dataclasses
import hashlib
import json
import math
import os
import resource
import shutil
import sys
import tempfile
import time

import numpy as np
import numcodecs
import tifffile
import zarr

OUT = Path(__file__).resolve().parent
numcodecs.blosc.set_nthreads(1)
zarr.config.set({'async.concurrency': 1, 'threading.max_workers': 1})
sys.path.insert(0, '/workspace/Scrolls')
from kit import layers

SOURCE = Path('/workspace/scrolls-env/inference-villa/vesuvius/src/vesuvius/ink_detection/inference/infer.py')
tree = ast.parse(SOURCE.read_text())
names = {'Block', 'FlatPatchReader', '_sliding_positions_1d', 'iter_blocks'}
nodes = [x for x in tree.body if isinstance(x, (ast.ClassDef, ast.FunctionDef)) and x.name in names]
scope = {'np': np, 'Path': Path, 'dataclass': dataclasses.dataclass, 'math': math,
         'open_volume': lambda path, _resolution: zarr.open(str(path), mode='r')['0']}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), scope)

sources = {
    'forward': Path('/workspace/scrolls-env/supervised-surfacefix/reader-baseline/selected_layers.zarr'),
    'reverse': Path('/workspace/scrolls-env/supervised-surfacefix/reader-baseline/selected_layers.zarr'),
    'shuffle': Path('/workspace/scrolls-env/supervised-surfacefix/reader-baseline/shuffled_layers.zarr'),
}
blocks = scope['iter_blocks']((640, 640), 128, 42)

def scan(mode):
    start = time.perf_counter()
    digest = hashlib.sha256()
    cache = {}
    decode_seconds = 0.
    for direction, path in sources.items():
        indices = np.arange(17)[::-1] if direction == 'reverse' else np.arange(17)
        reader = scope['FlatPatchReader'](input_path=path, resolution='0', depth_axis_first=True,
            height=640, width=640, layer_indices=indices, output_depth=17, preprocessing='divide_255')
        array = zarr.open(str(path), mode='r')['0']
        if mode == 'bounded_preload':
            if path not in cache:
                t = time.perf_counter(); cache[path] = np.asarray(array[:]); decode_seconds += time.perf_counter()-t
            reader._array = cache[path]
        else:
            reader._array = array
        for b in blocks:
            patch = reader.read(b.y0, b.x0, 128, 128)
            digest.update(patch.tobytes())
    return {'seconds_including_hash_and_preload':time.perf_counter()-start, 'preload_seconds':decode_seconds,
            'patch_sha256':digest.hexdigest(), 'patch_count':len(blocks)*3,
            'cached_raw_bytes':sum(x.nbytes for x in cache.values())}

reads = []
for i in range(3):
    for mode in (['zarr_per_patch','bounded_preload'] if i%2==0 else ['bounded_preload','zarr_per_patch']):
        reads.append({'repeat':i,'mode':mode,**scan(mode)})

render_source = Path('/workspace/scrolls-env/geometry-validation/render-baseline.zarr')
# Official renderer uses legacy '<u1', which Zarr3 rejects. Normalize only
# that equivalent one-byte unsigned metadata spelling in an isolated copy.
normalized_render = OUT/'render-profile.zarr'
if not normalized_render.exists():
    shutil.copytree(render_source, normalized_render)
    metadata_path = normalized_render/'0'/'.zarray'
    metadata = json.loads(metadata_path.read_text())
    assert metadata['dtype'] == '<u1'
    metadata['dtype'] = '|u1'
    metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
render = zarr.open(str(normalized_render),mode='r')['0']
exports = []
for mode in ['per_layer_fallback', 'existing_banded']:
    for i in range(3):
        with tempfile.TemporaryDirectory(dir=OUT) as dst:
            t=time.perf_counter()
            files=layers.export_layers(render, dst, max_bytes=0 if mode=='per_layer_fallback' else 4*1024**3)
            elapsed=time.perf_counter()-t
            digest=hashlib.sha256()
            for p in files:digest.update(tifffile.imread(p).tobytes())
            exports.append({'mode':mode,'repeat':i,'export_seconds':elapsed,'pixel_sha256':digest.hexdigest(),
                'tiff_bytes':sum(p.stat().st_size for p in files),'layers':len(files)})

result={'status':'io_profile_only_no_inference','source_infer_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'export_source_metadata_only_normalization':'isolated <u1 to |u1; same chunk bytes; source unchanged',
    'source_layers_sha256':hashlib.sha256(Path(layers.__file__).read_bytes()).hexdigest(),
    'runtime':{'python':sys.version.split()[0],'numpy':np.__version__,'zarr':zarr.__version__,'blosc_threads':1},
    'read_profile':reads,'export_profile':exports,
    'all_reader_pixels_identical':len({x['patch_sha256'] for x in reads})==1,
    'all_export_pixels_identical':len({x['pixel_sha256'] for x in exports})==1,
    'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
    'limitations':['Warm page-cache bounded crop profile, not full model or end-to-end throughput.',
        'Hashing/copying is included in reader times; no prediction maps are computed.',
        'Bounded preload proposal still needs official end-to-end map equivalence and memory budget tests.']}
(OUT/'profile-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
