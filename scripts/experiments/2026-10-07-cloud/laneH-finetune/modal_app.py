"""Modal launcher for lane H: 4 fine-tune variants in parallel, one H100 each. Not launched by the agent.

  pip install modal && modal token new
  modal run scripts/experiments/2026-10-07-cloud/laneH-finetune/modal_app.py --smoke-steps 5   # all 4 in parallel, briefly; not results
  modal run --detach scripts/experiments/2026-10-07-cloud/laneH-finetune/modal_app.py          # full job
  modal volume get scrolls-laneH laneH/results.json scripts/experiments/2026-10-07-cloud/laneH-finetune/results.json

Flow: prepare (CPU container: villa env, ink_9um checkpoints, volumes, labels, test crops; cached on the Volume and
skipped when present) -> base (1 H100: pseudo-label source map, base crop maps and scores) -> P90, P80, S1, S2 via
.map (4 H100s at once: train, infer, score) -> collect (CPU). Everything persists on Volume `scrolls-laneH`, so a
rerun or the full run after the smoke run reuses the environment, data and base maps.
"""
import json, subprocess, time
import modal

BRANCH = "grok/laneH-finetune"
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("git", "curl", "build-essential")
         .run_commands("curl -LsSf https://astral.sh/uv/install.sh | sh",
                       "ln -s /root/.local/bin/uv /usr/local/bin/uv", "ln -s /root/.local/bin/uvx /usr/local/bin/uvx"))
vol = modal.Volume.from_name("scrolls-laneH", create_if_missing=True)
app = modal.App("scrolls-laneH-finetune")
VARIANTS = ["P90", "P80", "S1", "S2"]


def _run(phase, smoke_steps, variant=""):
    t0 = time.time()
    tag = phase + (f"_{variant}" if variant else "")
    sh = f"""set -euo pipefail
    [ -d /work/Scrolls ] || git clone -q -b {BRANCH} https://github.com/ChaseHendrick/Scrolls.git /work/Scrolls
    cd /work/Scrolls && git fetch -q origin {BRANCH} && git checkout -q FETCH_HEAD
    mkdir -p /work/logs
    WORK=/work/scrolls-work OUT=/work/laneH PHASE={phase} VARIANT={variant} SMOKE_STEPS={smoke_steps} \
      bash scripts/experiments/2026-10-07-cloud/laneH-finetune/run_job.sh 2>&1 | tee /work/logs/{tag}.log"""
    try:
        vol.reload()
        subprocess.run(["bash", "-c", sh], check=True)
    finally:
        out = "/work/laneH" + ("-smoke" if smoke_steps else "")
        rec = {"tag": tag, "container_start_epoch_s": t0, "container_end_epoch_s": time.time()}
        subprocess.run(["bash", "-c", f"mkdir -p {out}/timing && echo '{json.dumps(rec)}' > {out}/timing/container_{tag}.json"])
        vol.commit()
    return tag


# The base checkpoint, volumes and labels are fetched once by prepare and then read from the Volume.
@app.function(image=image, cpu=8, memory=32768, timeout=3 * 3600, volumes={"/work": vol})
def prepare(smoke_steps: int = 0):
    return _run("prepare", smoke_steps)


@app.function(image=image, gpu="H100", cpu=8, memory=65536, timeout=2 * 3600, volumes={"/work": vol})
def base(smoke_steps: int = 0):
    return _run("base", smoke_steps)


@app.function(image=image, gpu="H100", cpu=8, memory=65536, timeout=3 * 3600, volumes={"/work": vol})
def variant(name: str, smoke_steps: int = 0):
    return _run("variant", smoke_steps, name)


@app.function(image=image, cpu=2, memory=8192, timeout=1800, volumes={"/work": vol})
def collect(smoke_steps: int = 0):
    out = "/work/laneH" + ("-smoke" if smoke_steps else "")
    _run("collect", smoke_steps)
    subprocess.run(["bash", "-c", f"cp /work/Scrolls/scripts/experiments/2026-10-07-cloud/laneH-finetune/results.json {out}/results.json"])
    vol.commit()


@app.local_entrypoint()
def main(smoke_steps: int = 0):
    t = time.time()
    print(prepare.remote(smoke_steps), f"{time.time() - t:.0f} s")
    print(base.remote(smoke_steps), f"{time.time() - t:.0f} s")
    for tag in variant.map(VARIANTS, kwargs={"smoke_steps": smoke_steps}):
        print(tag, f"{time.time() - t:.0f} s")
    collect.remote(smoke_steps)
    print(f"wall {time.time() - t:.0f} s; results on the Volume under laneH{'-smoke' if smoke_steps else ''}/results.json")
