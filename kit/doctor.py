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

GPUs other than NVIDIA: an AMD card is found with `rocm-smi --showproductname --showmeminfo vram --json` (keys "Card
Series" and "VRAM Total Memory (B)" per card, from ROCm's rocm_smi.py), else through a ROCm build of torch
(torch.version.hip, which reports the card through torch.cuda); an Intel GPU through torch.xpu. torch is imported only
when nvidia-smi finds nothing and the machine is not an Apple Silicon Mac. villa's spiral fitting asks for "an NVIDIA
GPU" (https://scrollprize.org/tutorial_spiral, read 24 Oct 2026), so these report as warnings, never as a pass.

--remote, for a rented or cloud machine: where VC3D will keep its remote chunk cache, found the way VC3D finds it
(villa main volume-cartographer/core/src/RemoteCacheSettings.cpp and core/include/vc/core/util/GlobalCacheRoot.hpp,
read 24 Oct 2026): $VC3D_CONFIG_DIR (else ~/.VC3D)/cache.json "root" when that file exists; else remote_cache_dir in
the [viewer] section of VC3D.ini there; else /volpkgs/remote_cache or /ephemeral/remote_cache when /volpkgs or
/ephemeral exists; else ~/.VC3D/remote_cache. It reports the free space (and with the speed test, the speed) there,
and on RunPod (RUNPOD_POD_ID set) whether that folder survives a stop, quoting RunPod's storage page.
"""

import json
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


def parse_rocm_smi(text):
    """[(name, memory_mb)] from `rocm-smi --showproductname --showmeminfo vram --json`."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    found = []
    for card, info in sorted((data or {}).items()) if isinstance(data, dict) else []:
        if not card.startswith("card") or not isinstance(info, dict):
            continue
        name = str(info.get("Card Series") or info.get("Device Name") or info.get("Card Model") or card).strip()
        try:
            mb = int(int(str(info.get("VRAM Total Memory (B)", "")).strip()) / 1024**2)
        except ValueError:
            mb = 0
        found.append((name, mb))
    return found


def amd_gpus(run=subprocess.run, which=shutil.which):
    """[(name, memory_mb)] from rocm-smi, or [] when it is absent or fails."""
    if which("rocm-smi") is None:
        return []
    try:
        out = run(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"],
                  capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_rocm_smi(out)


def torch_gpus():
    """{"hip": ROCm version of this torch or None, "amd": [(name, mb)], "xpu": [(name, mb)]}, empty without torch."""
    out = {"hip": None, "amd": [], "xpu": []}
    try:
        import torch
    except Exception:  # no torch, or a broken install: nothing to report
        return out
    try:
        out["hip"] = getattr(torch.version, "hip", None)
        if out["hip"] and torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                p = torch.cuda.get_device_properties(i)
                out["amd"].append((p.name, int(p.total_memory / 1024**2)))
        xpu = getattr(torch, "xpu", None)
        if xpu is not None and xpu.is_available():
            for i in range(xpu.device_count()):
                p = xpu.get_device_properties(i)
                out["xpu"].append((p.name, int(getattr(p, "total_memory", 0) / 1024**2)))
    except Exception:  # a driver error while asking: report what was found so far
        pass
    return out


def rocm_present(exists=os.path.exists):
    """True when the ROCm kernel driver's device node or the ROCm install folder is on this machine."""
    return exists("/dev/kfd") or exists("/opt/rocm")


def _names(found):
    return "; ".join(f"{name} {mem // 1024} GB" if mem else name for name, mem in found)


def check_gpu(found, apple_silicon=False, amd=(), xpu=(), hip=None, rocm=False):
    if not found and apple_silicon:
        return WARN, (
            "Apple Silicon, no CUDA. Runs locally: VC3D app, rendering, lasagna (--device mps). "
            "Stock villa ink inference uses the CPU; open PRs #1865/#1812 add MPS. "
            "Full segments: rent a GPU. See docs/mac.md"
        )
    nvidia_only = ("villa's spiral fitting asks for an NVIDIA GPU (scrollprize.org/tutorial_spiral); other villa steps "
                   "are not tested on it here")
    if not found and amd:
        small = "" if max(mem for _, mem in amd) >= MIN_GPU_MB else " Below 12 GB."
        torch_note = (f"torch {hip} (ROCm) sees it through torch.cuda" if hip else
                      "this Python's torch is not a ROCm build: install one from https://pytorch.org")
        return WARN, f"AMD GPU (ROCm): {_names(amd)}.{small} {torch_note}. {nvidia_only}"
    if not found and xpu:
        return WARN, f"Intel GPU (torch.xpu): {_names(xpu)}. {nvidia_only}"
    if not found and rocm:
        return WARN, ("ROCm is installed (/dev/kfd or /opt/rocm) but neither rocm-smi nor torch listed an AMD GPU: "
                      "check the driver with rocm-smi, and that this user is in the video and render groups")
    if not found:
        return FAIL, ("No GPU found (nvidia-smi, rocm-smi and torch found none). Ink inference needs CUDA; see "
                      "docs/compute.md for rentals.")
    best = max(mem for _, mem in found)
    names = "; ".join(f"{name} {mem // 1024} GB" for name, mem in found)
    if best >= MIN_GPU_MB:
        return PASS, names
    return WARN, f"{names}. Below 12 GB: use batch size 1 or rent a GPU."


def check_disk(path):
    free_gb = shutil.disk_usage(path).free / 1024**3
    status = PASS if free_gb >= MIN_DISK_GB else WARN
    return status, f"{free_gb:.0f} GB free at {path} (one tutorial segment is about 25 GB)"


def vc3d_cache_root(env=None, exists=os.path.exists, read=lambda p: Path(p).read_text()):
    """(folder, how it was chosen) where VC3D keeps streamed chunks, found the way VC3D finds it (module docstring).
    Raises ValueError for a cache.json VC3D itself would refuse."""
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    conf = Path(env["VC3D_CONFIG_DIR"]) if env.get("VC3D_CONFIG_DIR") else home / ".VC3D"
    if exists(str(conf / "cache.json")):
        try:
            data = json.loads(read(conf / "cache.json"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{conf / 'cache.json'} does not read as JSON: {exc}") from None
        root = str(data.get("root") or "") if isinstance(data, dict) else ""
        if not isinstance(data, dict) or data.get("version") != 1 or not root.startswith("/"):
            raise ValueError(f"{conf / 'cache.json'} needs version 1 and an absolute root; VC3D refuses it otherwise")
        return Path(root), f"root in {conf / 'cache.json'}"
    try:
        ini = read(conf / "VC3D.ini") if exists(str(conf / "VC3D.ini")) else ""
    except OSError:
        ini = ""
    section = None
    for line in ini.splitlines():
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
        elif section == "viewer" and "=" in s and s.split("=", 1)[0].strip() == "remote_cache_dir":
            v = s.split("=", 1)[1].strip()
            if len(v) >= 2 and v[0] == v[-1] == '"':
                v = v[1:-1]
            if v:
                return Path(v).expanduser(), f"remote_cache_dir in {conf / 'VC3D.ini'}"
    for mount in ("/volpkgs", "/ephemeral"):
        if exists(mount):
            return Path(mount) / "remote_cache", f"{mount} exists"
    return home / ".VC3D" / "remote_cache", "VC3D's default"


def _existing(path, exists=os.path.exists):
    path = Path(path)
    while not exists(str(path)) and path.parent != path:
        path = path.parent
    return path


RUNPOD_STORAGE = "https://docs.runpod.io/pods/storage/types"


def check_cache(env=None, exists=os.path.exists, disk_usage=shutil.disk_usage, read=None):
    """Where VC3D will cache remote chunks, the free space there, and on RunPod whether it survives a stop."""
    env = os.environ if env is None else env
    try:
        root, how = vc3d_cache_root(env, exists, read) if read else vc3d_cache_root(env, exists)
    except ValueError as exc:
        return FAIL, str(exc)
    base = _existing(root, exists)
    free_gb = disk_usage(str(base)).free / 1024**3
    status = PASS if free_gb >= MIN_DISK_GB else WARN
    detail = f"VC3D caches remote chunks in {root} ({how}); {free_gb:.0f} GB free there"
    if env.get("RUNPOD_POD_ID"):
        on_workspace = str(root) == "/workspace" or str(root).startswith("/workspace/")
        if on_workspace and env.get("RUNPOD_VOLUME_ID"):
            detail += (". RunPod: a network volume at /workspace, kept after the Pod is deleted; run the speed check "
                       f"on it (--disk {base}) ({RUNPOD_STORAGE})")
        elif on_workspace:
            detail += (". RunPod: the volume disk at /workspace \"survives Pod stops and restarts, but is deleted when "
                       f"the Pod is terminated\" ({RUNPOD_STORAGE})")
        else:
            detail += (". RunPod: outside /workspace, on the container disk, which \"is cleared when the Pod stops\"; "
                       "set remote_cache_dir in VC3D.ini to a folder under /workspace to keep the cache "
                       f"({RUNPOD_STORAGE})")
    if status == WARN:
        detail += f". Under {MIN_DISK_GB} GB: a long trace can fill it"
    return status, detail


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


def run_checks(env=None, disk_path=".", speed=True, remote=False):
    env = os.environ if env is None else env
    mac = is_apple_silicon()
    nvidia = gpus()
    other = torch_gpus() if not nvidia and not mac else {"hip": None, "amd": [], "xpu": []}
    amd = amd_gpus() if not nvidia and not mac else []
    extra = []
    rosetta = check_rosetta()
    if rosetta:
        extra.append(("rosetta", *rosetta))
    if platform.system() == "Linux":
        extra.append(("threads", *check_threads(env=env)))
    if speed:
        extra.append(("speed", *check_disk_speed(disk_path)))
    if remote:
        cache = check_cache(env)
        extra.append(("cache", *cache))
        if speed and cache[0] != FAIL:
            base = _existing(vc3d_cache_root(env)[0])
            if os.path.realpath(base) != os.path.realpath(disk_path):
                extra.append(("cacheio", *check_disk_speed(base)))
    return extra + [
        ("gpu", *check_gpu(nvidia, apple_silicon=mac, amd=amd or other["amd"], xpu=other["xpu"], hip=other["hip"],
                           rocm=not nvidia and not mac and rocm_present())),
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
