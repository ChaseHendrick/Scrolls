"""kit cpudiag: why a CPU job runs slower per core than expected (18 Nov 2026).

Fixed micro-benchmarks that run the same way in a cloud container, on a Mac or inside a Hugging Face Job, so their numbers
can be compared and the per-core factor for estimates read off:

  python -m kit.cpudiag run [--procs 1,8,32] [--mount DIR] [--scrollsim2] [--out FILE.json]
  python -m kit.cpudiag compare HERE.json THERE.json      per-core factors THERE over HERE, kernel by kernel

`run` prints the machine (lscpu, nproc, os.cpu_count, cgroup CPU quota, affinity, the thread variables in force,
numpy's SIMD build), then times, at each process count P in --procs (P processes forked at once, each its own work):

  pyloop   pure Python arithmetic (interpreter speed: clock and IPC, no memory traffic)
  compute  numpy elementwise math on a cache-resident array (SIMD and clock)
  stream   a STREAM-like triad on 128 MB arrays per process (memory bandwidth; GB/s per process and in all)
  blas     512 x 512 matmuls, once with the thread variables as given and once with them set to 1 per process
           (oversubscription: P processes times T BLAS threads on N cores)

With --mount DIR it times writing, renaming and reading back 32 files of 2 MB (a zarr chunk's size) on local disk and
in DIR (a bucket mount), from 8 writers at once. With --scrollsim2 it builds the scrollsim2 pilot geometry once and
renders sheet blocks with 1 process and with the largest P (the real workload whose slowdown started this tool).

Every kernel's result is seconds per process (median and max over the P processes) and its slowdown against P=1.
Interpretation guide (printed as `reading`): a slowdown at P=1 against another machine is per-core speed (clock,
SIMD width, image); one that grows with P in compute or pyloop but not at P=1 is shared cores (SMT siblings or a
CPU quota under nproc); one only in stream is memory bandwidth; one only in blas with inherited threads is thread
oversubscription. No scroll data is read.
"""

import argparse
import json
import multiprocessing as mp
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

THREAD_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMBA_NUM_THREADS",
               "NUMEXPR_MAX_THREADS", "VECLIB_MAXIMUM_THREADS")
KERNELS = ("pyloop", "compute", "stream", "blas")


# ---------------------------------------------------------------- machine facts

def cgroup_cpus(root="/sys/fs/cgroup"):
    """CPUs the cgroup quota allows (cpu.max, or cgroup v1 cfs quota over period), or None when unlimited."""
    root = Path(root)
    try:
        q, r = (root / "cpu.max").read_text().split()[:2]
    except (OSError, ValueError):
        try:
            q = (root / "cpu" / "cpu.cfs_quota_us").read_text().strip()
            r = (root / "cpu" / "cpu.cfs_period_us").read_text().strip()
        except OSError:
            return None
    if q == "max" or q.startswith("-"):
        return None
    try:
        return round(int(q) / int(r), 2) if int(r) > 0 else None
    except ValueError:
        return None


def _cmd(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def lscpu_fields(text):
    """The lscpu lines that decide per-core speed: model, cores, threads per core, sockets, caches, NUMA, MHz."""
    keep = ("Model name", "CPU(s)", "Thread(s) per core", "Core(s) per socket", "Socket(s)", "NUMA node(s)",
            "L2 cache", "L3 cache", "CPU max MHz", "CPU MHz", "Hypervisor vendor", "Vendor ID")
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if k.strip() in keep and k.strip() not in out:
            out[k.strip()] = v.strip()
    return out


def machine():
    import numpy as np
    try:
        aff = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        aff = None
    simd = {}
    try:
        from numpy._core._multiarray_umath import __cpu_baseline__, __cpu_dispatch__, __cpu_features__
        simd = {"baseline": list(__cpu_baseline__), "dispatch_on": [f for f in __cpu_dispatch__
                                                                     if __cpu_features__.get(f)]}
    except ImportError:
        pass
    mem = ""
    try:
        mem = Path("/proc/meminfo").read_text().splitlines()[0]
    except OSError:
        pass
    return {"host": platform.node()[:40], "python": platform.python_version(), "numpy": np.__version__,
            "nproc": _cmd(["nproc"]).strip() or None, "os_cpu_count": os.cpu_count(), "affinity": aff,
            "cgroup_cpus": cgroup_cpus(), "lscpu": lscpu_fields(_cmd(["lscpu"])), "meminfo": mem,
            "threads_env": {v: os.environ.get(v) for v in THREAD_VARS + ("PYTHON_CPU_COUNT", "KIT_CPUS")},
            "numpy_simd": simd}


# ---------------------------------------------------------------- kernels (each a fixed amount of work)

def k_pyloop(scale=1.0):
    n = int(40_000_000 * scale)
    t = time.perf_counter()
    s = 0
    for i in range(n):
        s += (i * i) % 7
    return time.perf_counter() - t


def k_compute(scale=1.0):
    import numpy as np
    x = np.random.default_rng(0).random(1 << 14)
    y = np.empty_like(x)
    t = time.perf_counter()
    for _ in range(int(40000 * scale)):
        np.multiply(x, 1.0001, out=y)
        np.add(y, 0.5, out=y)
        np.sqrt(y, out=y)
        np.exp(-y, out=y)
    return time.perf_counter() - t


STREAM_N = 1 << 24       # 128 MB of float64 per array


def k_stream(scale=1.0):
    """Triad a = b + s*c over STREAM_N doubles, as two numpy passes; returns seconds for the timed passes."""
    import numpy as np
    b = np.ones(STREAM_N)
    c = np.full(STREAM_N, 2.0)
    a = np.empty(STREAM_N)
    np.multiply(c, 3.0, out=a)        # touch every page before timing
    t = time.perf_counter()
    for _ in range(max(1, int(50 * scale))):
        np.multiply(c, 3.0, out=a)
        np.add(a, b, out=a)
    return time.perf_counter() - t


def stream_bytes(scale=1.0):
    """Bytes the timed triad passes move (read c, write a; read a and b, write a), per process."""
    return max(1, int(50 * scale)) * 5 * 8 * STREAM_N


def k_blas(scale=1.0):
    import numpy as np
    m = np.random.default_rng(0).random((512, 512))
    t = time.perf_counter()
    for _ in range(int(500 * scale)):
        m2 = m @ m
        m = m2 / (m2.max() + 1.0)
    return time.perf_counter() - t


KFUN = {"pyloop": k_pyloop, "compute": k_compute, "stream": k_stream, "blas": k_blas}


def _child(args):
    name, scale, barrier = args
    barrier.wait()
    return KFUN[name](scale)


def scale_run(name, procs, scale=1.0):
    """Seconds per process for kernel NAME with PROCS processes started at once (forked, one barrier)."""
    if procs <= 1:
        return [KFUN[name](scale)]
    ctx = mp.get_context("fork")
    with ctx.Manager() as man:
        bar = man.Barrier(procs)
        with ctx.Pool(procs) as pool:
            return pool.map(_child, [(name, scale, bar)] * procs, chunksize=1)


def summarize(times):
    return {"median_s": round(statistics.median(times), 4), "max_s": round(max(times), 4), "n": len(times)}


def blas_subprocess(procs, threads, scale=1.0, timeout=600):
    """The blas kernel in a fresh interpreter, so the thread variables take effect at numpy's import. THREADS None
    keeps the environment as given; an int sets every thread variable to it."""
    env = dict(os.environ)
    if threads is not None:
        env.update({v: str(threads) for v in THREAD_VARS})
    code = (f"import json, kit.cpudiag as c; print(json.dumps(c.scale_run('blas', {int(procs)}, {float(scale)})))")
    pr = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=env, cwd=str(Path(__file__).resolve().parent.parent), start_new_session=True)
    try:
        so, se = pr.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        import signal
        os.killpg(pr.pid, signal.SIGKILL)      # the forked pool workers too, so none keeps burning the CPUs
        pr.communicate()
        raise
    if pr.returncode:
        raise RuntimeError(f"blas subprocess failed: {se[-400:]}")
    return json.loads(so.strip().splitlines()[-1])


# ---------------------------------------------------------------- I/O

def _io_child(args):
    d, i, files, size = args
    blob = os.urandom(size)
    t = time.perf_counter()
    for j in range(files):
        p = Path(d) / f"w{i}-{j}.bin"
        tmp = p.with_suffix(".partial")
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, p)
    tw = time.perf_counter() - t
    t = time.perf_counter()
    for j in range(files):
        with open(Path(d) / f"w{i}-{j}.bin", "rb") as f:
            f.read()
    return tw, time.perf_counter() - t


def io_run(base, writers=8, files=4, size=2 << 20):
    """Write (temp file plus rename, as zarr does) and read back WRITERS x FILES files of SIZE bytes under BASE."""
    d = Path(tempfile.mkdtemp(prefix="cpudiag-", dir=str(base)))
    try:
        ctx = mp.get_context("fork")
        t = time.perf_counter()
        with ctx.Pool(writers) as pool:
            res = pool.map(_io_child, [(str(d), i, files, size) for i in range(writers)])
        wall = time.perf_counter() - t
        landed = len(list(d.glob("*.bin")))
        mb = writers * files * size / 2 ** 20
        return {"dir": str(base), "mb": mb, "wall_s": round(wall, 3), "write_mb_s": round(mb / max(1e-9, max(
            r[0] for r in res)), 1), "read_mb_s": round(mb / max(1e-9, max(r[1] for r in res)), 1),
                "files_landed": landed, "files_expected": writers * files}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- scrollsim2, the real workload

_SC = None


def _ss2_child(args):
    b, barrier = args
    barrier.wait()
    t = time.perf_counter()
    _SC.scan_block(*b, air=False)
    return time.perf_counter() - t


def scrollsim2_run(procs_list, preset="pilot", per_proc=1):
    """Build the scrollsim2 geometry once, then time sheet blocks near the center with each P in PROCS_LIST."""
    global _SC
    from . import scrollsim2 as s2
    t = time.perf_counter()
    sc = s2.Scroll2(dict(s2.params(None, preset)))
    t_init = time.perf_counter() - t
    h = sc.halo()
    blocks = s2._blocks((sc.Z, sc.Y, sc.X), 128)
    cz, cy, cx = sc.Z / 2, sc.Y / 2, sc.X / 2
    blocks.sort(key=lambda b: ((b[0] + b[1]) / 2 - cz) ** 2 + ((b[2] + b[3]) / 2 - cy) ** 2 + ((b[4] + b[5]) / 2 - cx) ** 2)
    sheet = [b for b in blocks[:4 * max(procs_list) * per_proc + 64]
             if not sc.block_is_air(b[0] - h, b[1] + h, b[2] - h, b[3] + h, b[4] - h, b[5] + h)]
    _SC = sc
    out = {"seconds_init": round(t_init, 1), "by_procs": {}}
    try:
        ctx = mp.get_context("fork")
        for p in procs_list:
            work = sheet[:p * per_proc]
            if len(work) < p * per_proc:
                out["by_procs"][str(p)] = {"error": f"only {len(sheet)} sheet blocks near the center"}
                continue
            if p == 1:
                ts = [_ss2_child((b, _NoBarrier())) for b in work]
            else:
                with ctx.Manager() as man:
                    bar = man.Barrier(p)
                    with ctx.Pool(p) as pool:
                        ts = pool.map(_ss2_child, [(b, bar) for b in work], chunksize=1)
            out["by_procs"][str(p)] = summarize(ts)
    finally:
        _SC = None
    return out


class _NoBarrier:
    def wait(self):
        return None


# ---------------------------------------------------------------- run and compare

def reading(res):
    """Plain-language reading of one run's slowdowns (Interpretation, not a measurement)."""
    lines = []
    sc = res.get("scaling", {})
    big = max((int(p) for p in sc.get("compute", {})), default=1)
    for k in ("pyloop", "compute", "stream"):
        d = sc.get(k, {})
        if "1" in d and str(big) in d and big > 1:
            f = d[str(big)]["median_s"] / max(1e-9, d["1"]["median_s"])
            lines.append(f"{k}: {f:.2f} x slower per process at P={big} than at P=1")
    bl = res.get("blas", {})
    if bl.get("inherited", {}).get("timeout_s") and bl.get("one_thread"):
        lines.append(f"blas at P={bl.get('procs')}: inherited threads did not finish in {bl['inherited']['timeout_s']} s "
                     f"(1 thread per process: {bl['one_thread']['median_s']} s)")
    elif bl.get("inherited") and bl.get("one_thread"):
        f = bl["inherited"]["median_s"] / max(1e-9, bl["one_thread"]["median_s"])
        lines.append(f"blas at P={bl.get('procs')}: inherited threads {f:.2f} x the time of 1 thread per process")
    return lines


def run(procs=(1, 8, 32), scale=1.0, mount=None, scrollsim2=False, progress=print, kernels=KERNELS, out=None):
    """Every phase in order of value (scrollsim2, I/O, the plain kernels, BLAS last, as it can run away); with OUT
    the result so far is saved after each phase, so a Job stopped at its timeout keeps what it measured."""
    nmax = max(procs)
    res = {"tool": "kit.cpudiag run", "when_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "machine": machine(), "procs": list(procs), "scale": scale, "scaling": {}}

    def save():
        res["reading"] = reading(res)
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(json.dumps(res, indent=1) + "\n")

    progress(f"PROGRESS machine: {json.dumps(res['machine']['lscpu'])}; cgroup cpus {res['machine']['cgroup_cpus']}")
    if scrollsim2:
        res["scrollsim2"] = scrollsim2_run(list(procs))
        progress(f"PROGRESS scrollsim2: {json.dumps(res['scrollsim2'])}")
        save()
    if mount:
        res["io"] = {"local": io_run(tempfile.gettempdir()), "mount": io_run(mount)}
        progress(f"PROGRESS io: {json.dumps(res['io'])}")
        save()
    for k in ("pyloop", "compute", "stream"):
        if k not in kernels:
            continue
        res["scaling"][k] = {}
        for p in procs:
            ts = scale_run(k, p, scale)
            s = summarize(ts)
            if k == "stream":
                gb = stream_bytes(scale) / 1e9
                s["gb_s_per_proc"] = round(gb / s["median_s"], 2)
                s["gb_s_total"] = round(gb * p / s["max_s"], 1)
            res["scaling"][k][str(p)] = s
            progress(f"PROGRESS {k} P={p}: {json.dumps(s)}")
        save()
    if "blas" in kernels:
        # A tenth of the work, and a time limit: with inherited threads, P processes each start as many BLAS threads
        # as there are CPUs (32 x 32 on cpu-performance), which ran a first diagnostic Job past its timeout.
        bs = scale / 10
        res["blas"] = {"procs": nmax, "scale": bs, "one_thread": summarize(blas_subprocess(nmax, 1, bs)),
                       "single_proc_inherited": summarize(blas_subprocess(1, None, bs))}
        try:
            res["blas"]["inherited"] = summarize(blas_subprocess(nmax, None, bs, timeout=BLAS_LIMIT_S))
        except subprocess.TimeoutExpired:
            res["blas"]["inherited"] = {"timeout_s": BLAS_LIMIT_S}
        progress(f"PROGRESS blas: {json.dumps(res['blas'])}")
        save()
    save()
    return res


BLAS_LIMIT_S = 120


def compare(here, there):
    """Per-core factors THERE over HERE: seconds per process at matching P, kernel by kernel (above 1 = slower)."""
    out = {}
    for k, d in there.get("scaling", {}).items():
        for p, s in d.items():
            h = here.get("scaling", {}).get(k, {}).get(p)
            if h:
                out[f"{k} P={p}"] = round(s["median_s"] / max(1e-9, h["median_s"]), 2)
    for p, s in there.get("scrollsim2", {}).get("by_procs", {}).items():
        h = here.get("scrollsim2", {}).get("by_procs", {}).get(p)
        if h and "median_s" in s and "median_s" in h:
            out[f"scrollsim2 P={p}"] = round(s["median_s"] / max(1e-9, h["median_s"]), 2)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kit.cpudiag", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--procs", default="1,8,32", help="comma-separated process counts (default 1,8,32)")
    r.add_argument("--scale", type=float, default=1.0, help="work per kernel (1 = about 1 to 4 s a kernel on a 2026 Xeon core)")
    r.add_argument("--mount", help="a directory (bucket mount) to time small-file writes in, beside local disk")
    r.add_argument("--scrollsim2", action="store_true", help="also time scrollsim2 pilot sheet blocks")
    r.add_argument("--kernels", default=",".join(KERNELS), help="which of pyloop,compute,stream,blas to time "
                   "(default all; none for scrollsim2 and I/O only)")
    r.add_argument("--out", help="write the JSON result here (saved after each phase)")
    c = sub.add_parser("compare")
    c.add_argument("here")
    c.add_argument("there")
    a = ap.parse_args(argv)
    if a.cmd == "compare":
        print(json.dumps(compare(json.loads(Path(a.here).read_text()), json.loads(Path(a.there).read_text())),
                         indent=1))
        return 0
    procs = tuple(sorted({max(1, int(x)) for x in a.procs.split(",") if x.strip()}))
    kernels = tuple(k for k in a.kernels.split(",") if k in KERNELS)
    res = run(procs, a.scale, a.mount, a.scrollsim2, kernels=kernels, out=a.out)
    print(json.dumps(res, indent=1))
    for line in res["reading"]:
        print("reading:", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
