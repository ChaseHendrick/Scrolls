"""Check whether this machine can run the villa First Letters workflow.

Thresholds come from published runs, not from guesses:
- 12 GB GPU: the Bullo27/first-letters-survey run (RTX 3060 12 GB) and the July 2026
  progress prize that made the spiral fitter run on 12 GB cards.
- 25 GB free disk: the single tutorial segment of the ink-labels dataset is about 25 GB
  (scrollprize.org/tutorial5). Streamed chunk caches add more.

Apple Silicon has no CUDA. On a Mac the GPU check reports what runs locally instead of
failing; see docs/mac.md.

Three checks catch slowdowns that give no error of their own:
- rosetta: on an Apple Silicon Mac, a Python (or torch) built for Intel runs translated by Rosetta, cannot use the
  GPU (MPS) and runs NumPy and torch several times slower. macOS reports a translated process through
  `sysctl sysctl.proc_translated` and an Apple Silicon machine through `sysctl hw.optional.arm64`.
- threads: in a container (Docker, RunPod, a cloud job) the CPU quota can be smaller than the CPUs Python sees, and
  Numba, OpenMP and torch size their thread pools from the CPUs they see. Too many threads on a small quota spend
  the quota waiting. The quota comes from cgroup v2 `cpu.max` or v1 `cpu.cfs_quota_us` / `cpu.cfs_period_us`.
- disk speed: writes a 64 MB file under --disk, syncs it, drops it from the page cache where the system allows, and
  reads it back: a network or overlay file system (RunPod's volumes, a synced cloud folder) can be ten times slower
  than a local SSD, and volume chunk reads then dominate run time. --no-speed skips it.
"""

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

MIN_GPU_MB = 12 * 1024
MIN_DISK_GB = 25
TOOLS = ("git", "uv", "docker")

MIN_RAM_GB = 16
MAC_VC_BIN = Path("/Applications/VC3D.app/Contents/MacOS")

PASS, WARN, FAIL = "pass", "warn", "fail"


def is_apple_silicon(system=None, machine=None):
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    return system == "Darwin" and machine == "arm64"


def ram_gb():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (AttributeError, ValueError, OSError):
        return None


def gpus(run=subprocess.run):
    """Return [(name, memory_mb)] from nvidia-smi, or [] when it is absent or fails."""
    if shutil.which("nvidia-smi") is None:
        return []
    try:
        out = run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_nvidia_smi(out)


def parse_nvidia_smi(text):
    found = []
    for line in text.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            found.append((name.strip(), int(float(mem.strip()))))
        except ValueError:
            continue
    return found


def check_gpu(found, apple_silicon=False):
    if not found and apple_silicon:
        return WARN, (
            "Apple Silicon, no CUDA. Runs locally: VC3D app, rendering, lasagna (--device mps). "
            "Stock villa ink inference uses the CPU; open PRs #1865/#1812 add MPS. "
            "Full segments: rent a GPU. See docs/mac.md"
        )
    if not found:
        return FAIL, "No NVIDIA GPU found (nvidia-smi absent or failed). Ink inference needs CUDA; see docs/compute.md for rentals."
    best = max(mem for _, mem in found)
    names = "; ".join(f"{name} {mem // 1024} GB" for name, mem in found)
    if best >= MIN_GPU_MB:
        return PASS, names
    return WARN, f"{names}. Below 12 GB: use batch size 1 or rent a GPU."


def check_disk(path):
    free_gb = shutil.disk_usage(path).free / 1024**3
    status = PASS if free_gb >= MIN_DISK_GB else WARN
    return status, f"{free_gb:.0f} GB free at {path} (one tutorial segment is about 25 GB)"


def check_ram(gb, apple_silicon=False):
    if gb is None:
        return WARN, "could not read installed memory"
    # A "16 GB" machine reports slightly less than 16 GiB usable.
    status = PASS if round(gb) >= MIN_RAM_GB else WARN
    shared = ", shared with the GPU" if apple_silicon else ""
    return status, f"{gb:.0f} GB memory{shared}"


def check_tools(which=shutil.which):
    missing = [tool for tool in TOOLS if which(tool) is None]
    if not missing:
        return PASS, "git, uv and docker on PATH"
    return WARN, "missing: " + ", ".join(missing) + " (uv runs villa; docker runs the VC3D image)"


def check_villa(path):
    if path is None:
        return WARN, "VILLA not set. Clone https://github.com/ScrollPrize/villa and export VILLA=/path/to/villa"
    villa = Path(path)
    if (villa / "vesuvius").is_dir() and (villa / "volume-cartographer").is_dir():
        return PASS, f"villa checkout at {villa}"
    return FAIL, f"{villa} does not look like a villa checkout (no vesuvius/ and volume-cartographer/)"


def check_vc_bin(path, apple_silicon=False):
    if path is None and apple_silicon and MAC_VC_BIN.is_dir():
        path = str(MAC_VC_BIN)
    if path is None and apple_silicon:
        return WARN, "VC3D.app not in /Applications. Install the macos-arm64 .dmg from https://github.com/ScrollPrize/villa/releases"
    if path is None:
        return WARN, "VC_BIN not set. Needed for vc_grow_seg_from_seed and vc_render_tifxyz built from villa main"
    missing = [b for b in ("vc_grow_seg_from_seed", "vc_render_tifxyz") if not (Path(path) / b).exists()]
    if missing:
        return WARN, f"{path} lacks {', '.join(missing)}"
    return PASS, f"VC3D tools in {path}"


def sysctl(name, run=subprocess.run):
    """The value of a macOS sysctl as a string, or None."""
    try:
        out = run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def check_rosetta(system=None, machine=None, read=sysctl, torch_info=None):
    """None off macOS; else (status, detail) on whether Python and torch run natively on Apple Silicon."""
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    if system != "Darwin":
        return None
    arm_mac = machine == "arm64" or read("hw.optional.arm64") == "1"
    if not arm_mac:
        return PASS, "Intel Mac"
    if machine != "arm64" or read("sysctl.proc_translated") == "1":
        return FAIL, ("this Python is an Intel build running under Rosetta: no MPS GPU and slow NumPy. Install an "
                      "arm64 Python (python.org's universal2 installer, Homebrew in /opt/homebrew, or uv python "
                      "install), make a new venv with it, and check: python3 -c 'import platform; "
                      "print(platform.machine())' prints arm64")
    info = torch_info() if torch_info else _torch_mps()
    if info is None:
        return PASS, "arm64 Python (torch not installed)"
    built, available = info
    if available:
        return PASS, "arm64 Python; torch sees the MPS GPU"
    if not built:
        return WARN, "arm64 Python, but this torch has no MPS support: pip install --upgrade torch"
    return WARN, "arm64 Python, torch has MPS but it is not available (macOS 12.3 or newer is needed)"


def _torch_mps():
    import importlib.util
    if importlib.util.find_spec("torch") is None:
        return None
    try:
        import torch
        return bool(torch.backends.mps.is_built()), bool(torch.backends.mps.is_available())
    except Exception:  # a broken torch install: report it as no MPS
        return False, False


def _own_cgroups(proc="/proc/self/cgroup"):
    """{controller or "": path} of this process's cgroups ("" is cgroup v2)."""
    out = {}
    try:
        for line in Path(proc).read_text().splitlines():
            _, ctrl, path = line.split(":", 2)
            for c in (ctrl.split(",") if ctrl else [""]):
                out[c] = path
    except (OSError, ValueError):
        pass
    return out


def _quota_at(d):
    try:
        q, period = (d / "cpu.max").read_text().split()[:2]
        return None if q == "max" else int(q) / int(period)
    except (OSError, ValueError):
        pass
    try:
        q, period = int((d / "cpu.cfs_quota_us").read_text()), int((d / "cpu.cfs_period_us").read_text())
    except (OSError, ValueError):
        return None
    return None if q <= 0 or period <= 0 else q / period


def cpu_quota(root="/sys/fs/cgroup", proc="/proc/self/cgroup"):
    """CPUs allowed by this process's cgroup quota (the smallest from its cgroup up to the root; cgroup v2 cpu.max
    or v1 cpu.cfs_quota_us over cpu.cfs_period_us), or None when unlimited or unknown."""
    root = Path(root)
    own = _own_cgroups(proc)
    bases = []
    if "" in own:
        bases.append((root, own[""]))
    if "cpu" in own:
        bases += [(root / "cpu", own["cpu"]), (root / "cpu,cpuacct", own["cpu"])]
    bases.append((root, "/"))
    found = []
    for base, path in bases:
        d = base.joinpath(*[s for s in path.split("/") if s])
        while True:
            q = _quota_at(d)
            if q is not None:
                found.append(q)
            if d == base or base not in d.parents:
                break
            d = d.parent
    return min(found) if found else None


THREAD_VARS = ("NUMBA_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")


def check_threads(visible=None, quota=None, env=None):
    """(status, detail): is the CPU quota smaller than the CPUs Python sees, and are thread counts set to match?"""
    env = os.environ if env is None else env
    if visible is None:
        try:
            visible = len(os.sched_getaffinity(0))
        except AttributeError:
            visible = os.cpu_count() or 1
    if quota is None:
        quota = cpu_quota()
    if quota is None or quota >= visible * 0.9:
        return PASS, f"{visible} CPUs, no smaller CPU quota"
    n = max(1, int(quota))
    set_vars = {k: env[k] for k in THREAD_VARS if k in env}
    if set_vars and all(v.isdigit() and int(v) <= max(n, 1) for v in set_vars.values()) and len(set_vars) == len(THREAD_VARS):
        return PASS, f"{visible} CPUs visible, quota {quota:g}; thread counts already set ({', '.join(f'{k}={v}' for k, v in set_vars.items())})"
    exports = " ".join(f"{k}={n}" for k in THREAD_VARS)
    return WARN, (f"{visible} CPUs visible but the CPU quota is {quota:g}: Numba, OpenMP and torch start {visible} "
                  f"threads and wait on the quota. Before running: export {exports} (and torch.set_num_threads({n}))")


SPEED_BYTES = 64 << 20
MIN_READ_MBS = 200


def check_disk_speed(path, nbytes=SPEED_BYTES, clock=time.perf_counter):
    """(status, detail): write, sync, uncache and read back a temporary file under path."""
    import tempfile
    try:
        fd, name = tempfile.mkstemp(prefix=".kit-doctor-", dir=path)
    except OSError as exc:
        return WARN, f"could not write a test file under {path}: {exc}"
    block = os.urandom(1 << 20)
    cached = True
    try:
        t0 = clock()
        with os.fdopen(fd, "wb") as fh:
            for _ in range(nbytes // len(block)):
                fh.write(block)
            fh.flush()
            os.fsync(fh.fileno())
        tw = clock() - t0
        rfd = os.open(name, os.O_RDONLY)
        try:
            if hasattr(os, "posix_fadvise"):
                os.posix_fadvise(rfd, 0, 0, os.POSIX_FADV_DONTNEED)
                cached = False
            else:
                import fcntl
                if hasattr(fcntl, "F_NOCACHE"):
                    fcntl.fcntl(rfd, fcntl.F_NOCACHE, 1)
                    cached = False
            t0 = clock()
            while os.read(rfd, 1 << 22):
                pass
            tr = clock() - t0
        finally:
            os.close(rfd)
    except OSError as exc:
        return WARN, f"disk speed test under {path} failed: {exc}"
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass
    mb = nbytes / 1e6
    w, r = mb / max(tw, 1e-6), mb / max(tr, 1e-6)
    note = " (read may come from memory: this system cannot drop the file from its cache)" if cached else ""
    detail = f"{path}: write {w:.0f} MB/s, read {r:.0f} MB/s{note}"
    if r < MIN_READ_MBS:
        return WARN, (detail + f". Under {MIN_READ_MBS} MB/s: keep volume chunk caches on a local SSD (on RunPod, "
                      "the container disk rather than an overlay or network volume)")
    return PASS, detail


def run_checks(env=None, disk_path=".", speed=True):
    env = os.environ if env is None else env
    mac = is_apple_silicon()
    extra = []
    rosetta = check_rosetta()
    if rosetta:
        extra.append(("rosetta", *rosetta))
    if platform.system() == "Linux":
        extra.append(("threads", *check_threads(env=env)))
    if speed:
        extra.append(("speed", *check_disk_speed(disk_path)))
    return extra + [
        ("gpu", *check_gpu(gpus(), apple_silicon=mac)),
        ("memory", *check_ram(ram_gb(), apple_silicon=mac)),
        ("disk", *check_disk(disk_path)),
        ("tools", *check_tools()),
        ("villa", *check_villa(env.get("VILLA"))),
        ("vc_bin", *check_vc_bin(env.get("VC_BIN"), apple_silicon=mac)),
    ]


def format_report(results):
    lines = [f"[{status:>4}] {name:<7} {detail}" for name, status, detail in results]
    worst = FAIL if any(r[1] == FAIL for r in results) else WARN if any(r[1] == WARN for r in results) else PASS
    lines.append("")
    lines.append(f"overall: {worst}")
    return "\n".join(lines), worst
