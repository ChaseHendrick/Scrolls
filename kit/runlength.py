"""kit runlength cpu: how long a CPU job takes on a cloud CPU flavor, from one task timed in a 4-core container.

A task timed in a small container does not scale to a big CPU machine by dividing core-seconds by its vCPUs: memory
bandwidth and shared cores (SMT) slow every worker down as more run at once. This module holds measured slowdown
tables per flavor (from kit.cpudiag) and turns a container timing into a wall time and a job timeout:

  python -m kit.runlength cpu --task-s S --tasks N [--flavor cpu-performance] [--workers W]
                              [--kind max|stream|scrollsim2|compute] [--json]

Only the CPU estimate is here; GPU run-length estimates are not part of this repository.
"""

import argparse
import json
import math
import sys

TIMEOUT_MARGIN = 1.5       # a job's timeout is about 1.5 times its estimate
TIMEOUT_SETUP_MIN = 5      # plus start-up and export, minutes

# Hugging Face CPU flavors measured with kit.cpudiag (18 Nov 2026, docs/evidence/2026-11-18-hf-cpu-diag/).
# cpu-performance is an AMD EPYC 7R13 (Zen 3, AVX2, no AVX-512) with 2 threads per core: its 32 vCPU are 16 physical
# cores on 2 NUMA nodes, cgroup quota 32. One process there runs as fast as one in a 4-core Intel Xeon cloud
# container (scrollsim2 pilot block 6.69 s against 6.83 s), but memory bandwidth saturates near 68 GB/s from 8
# processes (STREAM-like triad: 31.8 GB/s for one process, 2.3 GB/s each at 32), and SMT siblings halve each other
# past 16. SLOWDOWN maps workers to seconds per task per worker over the same task timed in the container
# (Interpretation from two diagnostic jobs), one row per kind of work:
#   stream      pure memory bandwidth (cpudiag's triad; container P=1 1.95 s; HF 1.05, 3.90, 7.58, 14.83 s at
#               1, 8, 16, 32): the worst case for array-streaming numpy
#   scrollsim2  kit.scrollsim2's sheet render (the same 32 blocks: 4.33 s median in the container, 20.9 s each at 32)
#   compute     cache-resident numpy ufuncs (container 2.02 s; HF 3.87, 3.83, 4.01, 7.22 s)
# The default kind "max" takes the largest slowdown of the three at the worker count, so a cap sized from it covers a
# bandwidth-bound job; pass the measured kind when the work is one of them. Check against a real job: a scrollsim2
# pilot with 32 workers rendered all 2,912 blocks (2,458 sheet) in 1,512 s, about 1.63 sheet blocks/s; kind
# scrollsim2 predicts 1,600 s. Estimate CPU jobs with cpu_wall_s, never as container core-seconds over vCPUs.
CPU_FLAVORS = {
    "cpu-performance": {"vcpu": 32, "cores": 16, "numa": 2, "model": "AMD EPYC 7R13 (Zen 3, AVX2)",
                        "stream_gb_s_total": 68, "stream_gb_s_one": 31.8,
                        "slowdown": {"stream": {1: 0.54, 8: 2.0, 16: 3.9, 32: 7.6},
                                     "scrollsim2": {1: 1.0, 8: 1.0, 16: 1.9, 32: 4.8},
                                     "compute": {1: 1.9, 8: 1.9, 16: 2.0, 32: 3.6}}},
}
CPU_KINDS = ("max", "stream", "scrollsim2", "compute")


def cpu_slowdown(flavor, workers, kind="max"):
    """Seconds per task per worker on FLAVOR at WORKERS over the same task in our container, interpolated linearly
    between measured worker counts (flat below them, time-shared above); kind "max" is the largest over the measured
    kinds. None for an unmeasured flavor or kind."""
    kinds = CPU_FLAVORS.get(flavor, {}).get("slowdown", {})
    if kind == "max":
        fs = [cpu_slowdown(flavor, workers, k) for k in kinds]
        return max(fs) if fs else None
    t = kinds.get(kind)
    if not t:
        return None
    w = max(1, int(workers))
    ks = sorted(t)
    if w <= ks[0]:
        return t[ks[0]]
    for a, b in zip(ks, ks[1:]):
        if w <= b:
            return t[a] + (t[b] - t[a]) * (w - a) / (b - a)
    return t[ks[-1]] * w / ks[-1]          # past the vCPUs: processes time-share


def cpu_wall_s(task_s, tasks, flavor, workers, kind="max"):
    """Wall seconds for TASKS tasks of TASK_S seconds each (timed in our container) on FLAVOR with WORKERS."""
    f = cpu_slowdown(flavor, workers, kind)
    if f is None:
        return None
    w = max(1, int(workers))
    return math.ceil(tasks / w) * task_s * f


def cpu_best_workers(flavor, kind="max"):
    """The measured worker count with the most tasks per second on FLAVOR (fewest when tied within 5 percent)."""
    kinds = CPU_FLAVORS.get(flavor, {}).get("slowdown", {})
    if kind != "max" and kind not in kinds:
        return None
    ws = sorted({w for t in kinds.values() for w in t}) if kind == "max" else sorted(kinds[kind])
    if not ws:
        return None
    rate = {w: w / cpu_slowdown(flavor, w, kind) for w in ws}
    top = max(rate.values())
    return min(w for w, r in rate.items() if r >= 0.95 * top)


def cap_minutes(estimate_min):
    """The timeout for a job estimated at ESTIMATE_MIN minutes: about 1.5 times it plus start-up and export, whole
    minutes, at least 10."""
    return max(10, math.ceil(float(estimate_min) * TIMEOUT_MARGIN) + TIMEOUT_SETUP_MIN)


def add_arguments(p):
    sub = p.add_subparsers(dest="rl_cmd", required=True)
    c = sub.add_parser("cpu", help="wall time of a CPU job from a task timed in a 4-core container (kit.cpudiag tables)")
    c.add_argument("--flavor", default="cpu-performance")
    c.add_argument("--task-s", type=float, required=True, help="seconds per task, timed in a cloud container")
    c.add_argument("--tasks", type=int, required=True)
    c.add_argument("--workers", type=int, help="default: the measured best for --kind")
    c.add_argument("--kind", choices=CPU_KINDS, default="max",
                   help="max (the largest slowdown of the measured kinds: safe for unknown work), stream (memory "
                   "bandwidth bound), scrollsim2 (its render), or compute (cache-resident math)")
    c.add_argument("--json", action="store_true")


def run(a):
    w = a.workers or cpu_best_workers(a.flavor, a.kind)
    wall = cpu_wall_s(a.task_s, a.tasks, a.flavor, w or 1, a.kind)
    if wall is None:
        print(f"kit runlength cpu: no kit.cpudiag table for {a.flavor}; measure it first (python -m kit.cpudiag run)",
              file=sys.stderr)
        return 2
    out = {"flavor": a.flavor, "kind": a.kind, "workers": w, "best_workers": cpu_best_workers(a.flavor, a.kind),
           "slowdown": round(cpu_slowdown(a.flavor, w, a.kind), 2), "wall_s": round(wall),
           "cap_min": cap_minutes(wall / 60)}
    print(json.dumps(out, indent=1) if a.json else
          f"{a.tasks} tasks of {a.task_s} s on {a.flavor} with {w} workers ({a.kind}): about {wall / 60:.1f} min "
          f"(slowdown {out['slowdown']} x per task; best workers {out['best_workers']}); cap --timeout-min "
          f"{out['cap_min']}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.runlength", description=__doc__.split("\n")[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
