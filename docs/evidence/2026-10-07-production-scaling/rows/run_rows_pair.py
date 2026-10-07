"""Watch capped isolated scoring children; run only after explicit quiet-window GO."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time

OUT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--map',required=True)
parser.add_argument('--tag',required=True)
parser.add_argument('--repeats',type=int,default=1)
args=parser.parse_args()
env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
records=[]
for repeat in range(args.repeats):
    for mode in (['baseline','fast'] if repeat%2==0 else ['fast','baseline']):
        dst=OUT/'quiet-runs'/args.tag/(str(repeat)+'-'+mode)
        dst.parent.mkdir(parents=True,exist_ok=True)
        log=dst.parent/(dst.name+'.log')
        command=['/workspace/Scrolls/.venv/bin/python',str(OUT/'profile_rows_cli_child.py'),
                 '--mode',mode,'--map',args.map,'--out',str(dst)]
        start=time.monotonic()
        with log.open('w') as handle:
            process=subprocess.Popen(command,stdout=handle,stderr=subprocess.STDOUT,env=env)
            status='completed'
            while process.poll() is None:
                elapsed=time.monotonic()-start
                try:
                    lines=Path('/proc/'+str(process.pid)+'/status').read_text().splitlines()
                    rss=next(int(s.split()[1])*1024 for s in lines if s.startswith('VmRSS:'))
                except (OSError,StopIteration):rss=0
                if elapsed>120 or rss>10*1024**3:
                    status='wall_cap' if elapsed>120 else 'rss_cap'
                    process.kill()
                    break
                time.sleep(.1)
            returncode=process.wait()
        entry={'repeat':repeat,'mode':mode,'status':status,'returncode':returncode,
               'wall_seconds':time.monotonic()-start,'path':str(dst),'log':str(log)}
        records.append(entry)
        (dst.parent/'run-status.json').write_text(json.dumps(records,indent=2)+'\n')
        if returncode!=0:
            raise SystemExit('Stopped: '+json.dumps(entry))
print(json.dumps(records,indent=2))
