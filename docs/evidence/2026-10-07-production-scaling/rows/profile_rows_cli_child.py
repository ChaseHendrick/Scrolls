"""Whole CLI/file path timing; invoke only in a parent-approved quiet window."""
from pathlib import Path
import argparse
import contextlib
import hashlib
import io
import json
import os
import resource
import sys
import time

os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
resource.setrlimit(resource.RLIMIT_AS, (16*1024**3, 16*1024**3))
parser=argparse.ArgumentParser()
parser.add_argument('--mode',choices=['baseline','fast'],required=True)
parser.add_argument('--map',required=True)
parser.add_argument('--out',required=True)
args=parser.parse_args()
out=Path(args.out)
out.mkdir(parents=True,exist_ok=False)
start=time.perf_counter()
sys.path.insert(0,'/workspace/scrolls-env/production-speed-v2/rows-fixed')
from kit import cli,rowscore
import numpy as np
resize_timings=[]
resized=[]

def wrap(original):
    def timed(np,array,k):
        before=time.perf_counter()
        result=original(np,array,k)
        resize_timings.append(time.perf_counter()-before)
        resized.append(result)
        return result
    return timed

rowscore._area_resize=wrap(rowscore._area_resize)
rowscore._sparse_area_resize=wrap(rowscore._sparse_area_resize)
command=['rowscore',args.map,'--voxel-um','2.403','--json']
if args.mode=='fast':command.append('--fast-resize')
stdout=io.StringIO()
with contextlib.redirect_stdout(stdout):
    code=cli.main(command)
whole_seconds=time.perf_counter()-start
assert code==0 and len(resized)==1
record={'mode':args.mode,'file_path':args.map,'command':['python','-m','kit',*command],
        'whole_command_seconds_including_import_and_file_read':whole_seconds,
        'resize_seconds':resize_timings,
        'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'cpu_affinity':list(os.sched_getaffinity(0)),
        'score_record':json.loads(stdout.getvalue()),
        'resized_shape':list(resized[0].shape),
        'resized_float_sha256':hashlib.sha256(resized[0].tobytes()).hexdigest(),
        'notes':['CLI invoked in-process with the exact command arguments; includes package import and file read.',
                 'Timing excludes result hashing/array archival; a retained resize reference may increase later peak RSS.']}
np.save(out/'resized.npy',resized[0])
(out/'result.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
