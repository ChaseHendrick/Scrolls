"""Count the kollesis_termination ends that villa's load_fibers returns as known, by file version.

    python count.py VILLA/vesuvius/src FIBER_DIR

The vesuvius package chain is stubbed so only the annotation modules load (numpy, scipy).
"""
import os, sys, types, json, collections
SRC, DIR = sys.argv[1], sys.argv[2]
sys.path.insert(0, SRC)
for name in ["vesuvius", "vesuvius.neural_tracing", "vesuvius.neural_tracing.tracers",
             "vesuvius.neural_tracing.tracers.shared", "vesuvius.neural_tracing.tracers.shared.annotations"]:
    m = types.ModuleType(name); m.__path__ = [os.path.join(SRC, *name.split("."))]; sys.modules[name] = m
from vesuvius.neural_tracing.tracers.shared.annotations.vc3d import load_fibers
fibers = load_fibers(DIR)
ver = {f: json.load(open(os.path.join(DIR, f)))["version"] for f in os.listdir(DIR)}
c = collections.Counter()
for fb in fibers:
    c[(ver[fb.name], "loaded")] += 1
    c[(ver[fb.name], "known ends")] += sum(fb.endpoint_stop)
print(len(fibers), dict(sorted(c.items())))
