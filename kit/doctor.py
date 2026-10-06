"""Check whether this machine can run the villa First Letters workflow.

Thresholds come from published runs, not from guesses:
- 12 GB GPU: the Bullo27/first-letters-survey run (RTX 3060 12 GB) and the July 2026
  progress prize that made the spiral fitter run on 12 GB cards.
- 25 GB free disk: the single tutorial segment of the ink-labels dataset is about 25 GB
  (scrollprize.org/tutorial5). Streamed chunk caches add more.
"""

import os
import shutil
import subprocess
from pathlib import Path

MIN_GPU_MB = 12 * 1024
MIN_DISK_GB = 25
TOOLS = ("git", "uv", "docker")

PASS, WARN, FAIL = "pass", "warn", "fail"


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


def check_gpu(found):
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


def check_vc_bin(path):
    if path is None:
        return WARN, "VC_BIN not set. Needed for vc_grow_seg_from_seed and vc_render_tifxyz built from villa main"
    missing = [b for b in ("vc_grow_seg_from_seed", "vc_render_tifxyz") if not (Path(path) / b).exists()]
    if missing:
        return WARN, f"{path} lacks {', '.join(missing)}"
    return PASS, f"VC3D tools in {path}"


def run_checks(env=None, disk_path="."):
    env = os.environ if env is None else env
    return [
        ("gpu", *check_gpu(gpus())),
        ("disk", *check_disk(disk_path)),
        ("tools", *check_tools()),
        ("villa", *check_villa(env.get("VILLA"))),
        ("vc_bin", *check_vc_bin(env.get("VC_BIN"))),
    ]


def format_report(results):
    lines = [f"[{status:>4}] {name:<7} {detail}" for name, status, detail in results]
    worst = FAIL if any(r[1] == FAIL for r in results) else WARN if any(r[1] == WARN for r in results) else PASS
    lines.append("")
    lines.append(f"overall: {worst}")
    return "\n".join(lines), worst
