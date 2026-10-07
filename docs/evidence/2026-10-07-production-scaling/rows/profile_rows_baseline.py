"""Bounded baseline c43 rowscore profile on a fixed real public-map crop."""
from pathlib import Path
import cProfile
import hashlib
import importlib.util
import json
import os
import pstats
import resource
import sys
import time

os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
import numpy as np
import tifffile

OUT = Path(__file__).resolve().parent
sys.path.insert(0, '/workspace/Scrolls')
source = OUT/'baseline_rowscore.py'
spec = importlib.util.spec_from_file_location('kit._profile_baseline_rowscore', source)
rows = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rows)
image_path = next((OUT/'public-inputs/ink-detection').glob('*.tif'))
start = time.perf_counter()
full = tifffile.imread(image_path, maxworkers=1)
assert full.shape == (16460, 18560) and full.dtype == np.uint8
image = full[:4096, :4096].copy()
del full
decode_seconds = time.perf_counter()-start
np.save(OUT/'fixed-origin-4096-crop.npy', image)
profiler = cProfile.Profile()
start = time.perf_counter()
profiler.enable()
result = rows.score_array(image, voxel_um=2.403)
profiler.disable()
elapsed = time.perf_counter()-start
profiler.dump_stats(str(OUT/'baseline-4096.prof'))
with (OUT/'baseline-4096-profile.txt').open('w') as handle:
    pstats.Stats(profiler, stream=handle).sort_stats('cumulative').print_stats(30)
record = {'baseline_revision':'c43c41a59ac3793b9a653fa236165f6f6b9d47a4',
          'baseline_rowscore_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'input_path':str(image_path),
          'input_file_sha256':hashlib.sha256(image_path.read_bytes()).hexdigest(),
          'source_shape':[16460,18560], 'crop_yxyx':[0,4096,0,4096],
          'crop_bytes_sha256':hashlib.sha256(image.tobytes()).hexdigest(),
          'voxel_um':2.403, 'cpu_affinity':list(os.sched_getaffinity(0)),
          'decode_full_and_crop_seconds':decode_seconds, 'score_seconds':elapsed,
          'peak_rss_bytes_including_full_decode':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
          'result':result,
          'limits':['One fixed upper-left crop of a real public map, not full-canvas scoring.',
                    'No reader, rendering, labels, target CT or synthetic benchmark input.',
                    'Timing includes cProfile overhead and is diagnostic, not a matched optimization benchmark.']}
(OUT/'baseline-4096-result.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
