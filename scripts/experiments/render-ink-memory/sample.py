import json, subprocess, sys, time
def trace(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    t0 = time.time(); pts = []
    while p.poll() is None:
        try:
            for line in open(f'/proc/{p.pid}/status'):
                if line.startswith('VmRSS'):
                    pts.append((time.time() - t0, int(line.split()[1]) / 2**20))
        except FileNotFoundError:
            pass
        time.sleep(0.01)
    out = p.stdout.read(); pts.append((time.time() - t0, 0.0))
    return pts, out
py = sys.argv[1]
res = {}
for name, cmd in (('current', [py, 'old2.py']), ('patched', [py, 'new2.py', sys.argv[2]])):
    best = None
    for _ in range(3):
        pts, out = trace(cmd)
        print(name, out.strip().splitlines()[0], 'sampled peak', max(v for _, v in pts))
        if best is None or pts[-1][0] < best[-1][0]: best = pts
    res[name] = best
json.dump(res, open('trace.json', 'w'))
