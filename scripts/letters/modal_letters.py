"""Modal: synthetic Greek line data on CPU containers, then the CTC line reader trained on one GPU.

Spec, costs and checks: docs/compute/modal-specs/2026-10-08-letter-reader-training.md. Claude's cloud
sessions cannot reach Modal; the owner or an agent that runs Modal launches this. It refuses to
start without --allow-gpu. Every container checks out the same pushed commit of the public
Scrolls repository, so the code that ran is the code on GitHub. Only synthetic data is made and
read: no scroll data, maps or labels.

  LETTERS_GPU=B200 modal run scripts/letters/modal_letters.py --allow-gpu
  modal volume get scrolls-letters letters-v1/model/linenet.npz work/letters/
  modal volume get scrolls-letters letters-v1/model/train.json work/letters/
"""
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import modal

GPU = os.environ.get("LETTERS_GPU", "B200")
REPO = "https://github.com/ChaseHendrick/Scrolls.git"
OPTIONAL_FONTS = ("fonts-noto-core fonts-gfs-artemisia fonts-gfs-baskerville fonts-gfs-bodoni-classic "
                  "fonts-gfs-complutum fonts-gfs-didot fonts-gfs-neohellenic fonts-gfs-olga fonts-gfs-porson "
                  "fonts-gfs-solomos fonts-gfs-theokritos")

image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("git", "fonts-dejavu-core", "fonts-freefont-ttf", "fonts-liberation2")
         # Greek font packages are optional: one that does not exist is skipped, not fatal.
         .run_commands(f"for p in {OPTIONAL_FONTS}; do apt-get install -y --no-install-recommends $p "
                       "|| echo skipped $p; done")
         .pip_install("numpy==2.1.3", "pillow==11.0.0", "torch==2.5.1"))
vol = modal.Volume.from_name("scrolls-letters", create_if_missing=True)
app = modal.App("scrolls-letter-reader")


def _checkout(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("need a full commit SHA")
    code = Path(tempfile.mkdtemp(prefix="Scrolls-")) / "src"
    subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", REPO, str(code)], check=True)
    subprocess.run(["git", "-C", str(code), "fetch", "origin", commit], check=True)
    subprocess.run(["git", "-C", str(code), "checkout", "--detach", commit], check=True)
    return code


@app.function(image=image, cpu=8, memory=8192, timeout=1800, volumes={"/work": vol})
def generate(seed: int, n: int, split: str, run: str, commit: str):
    code = _checkout(commit)
    out = Path("/work") / run / "data" / split
    t0 = time.time()
    subprocess.run(["python", str(code / "scripts/letters/gen_dataset.py"), str(out), "--n", str(n),
                    "--shard", "1000", "--seed", str(seed), "--procs", "16"], check=True, cwd=code)
    vol.commit()
    return f"{split} seed {seed}: {n} lines in {time.time() - t0:.0f} s"


@app.function(image=image, gpu=GPU, cpu=8, memory=65536, timeout=3600, volumes={"/work": vol})
def train(run: str, commit: str, steps: int, batch: int, channels: str, dilations: str, lr: float):
    vol.reload()
    code = _checkout(commit)
    root = Path("/work") / run
    model = root / "model"
    model.mkdir(parents=True, exist_ok=True)
    cmd = ["python", str(code / "scripts/letters/train_linenet.py"), str(root / "data/train"), str(model),
           "--val", str(root / "data/val"), "--steps", str(steps), "--batch", str(batch), "--lr", str(lr),
           "--channels", channels, "--dilations", dilations, "--device", "cuda", "--amp",
           "--workers", "6", "--threads", "2", "--eval-every", "2000"]
    (model / "command.txt").write_text(" ".join(cmd) + f"\ncommit {commit}\ngpu {GPU}\n")
    t0 = time.time()
    try:
        with (model / "train.log").open("w") as log:
            subprocess.run(cmd, check=True, cwd=code, stdout=log, stderr=subprocess.STDOUT)
    finally:
        vol.commit()
    return f"trained {steps} steps on {GPU} in {time.time() - t0:.0f} s"


@app.local_entrypoint()
def main(run: str = "letters-v1", train_lines: int = 600000, val_lines: int = 4000, containers: int = 30,
         steps: int = 30000, batch: int = 128, channels: str = "48,96,160,192,256", dilations: str = "1,2,4",
         lr: float = 2e-3, skip_generate: bool = False, allow_gpu: bool = False):
    if not allow_gpu:
        raise SystemExit("Not run: pass --allow-gpu once the owner has approved the spend (see the spec)")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run):
        raise SystemExit("run name: letters, digits, dot, dash, underscore")
    src = Path(__file__).resolve().parents[2]
    commit = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.run(["git", "-C", str(src), "diff", "--quiet", "HEAD", "--", "scripts/letters", "kit"]).returncode:
        raise SystemExit("scripts/letters or kit has uncommitted changes; the containers run the pushed commit only")
    t = time.time()
    if not skip_generate:
        per = max(1000, (train_lines // containers) // 1000 * 1000)
        jobs = [(seed, per, "train", run, commit) for seed in range(1, containers + 1)]
        jobs.append((9001, val_lines, "val", run, commit))     # val seeds never overlap the training seeds
        for msg in generate.starmap(jobs):
            print(msg, f"({time.time() - t:.0f} s)")
    print(train.remote(run, commit, steps, batch, channels, dilations, lr), f"({time.time() - t:.0f} s)")
    print(f"Outputs on Volume scrolls-letters under {run}/model: linenet.npz, train.json, train.log, command.txt")
