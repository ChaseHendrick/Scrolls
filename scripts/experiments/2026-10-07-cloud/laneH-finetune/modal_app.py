"""Modal launcher for the lane H job (one A10G, pay per second). Not launched by the agent.

  pip install modal && modal token new          # user's own Modal account
  modal run --detach scripts/experiments/2026-10-07-cloud/laneH-finetune/modal_app.py            # full job
  modal run scripts/experiments/2026-10-07-cloud/laneH-finetune/modal_app.py --smoke-steps 5     # pipeline test first
  modal volume get scrolls-laneH laneH/results.json .   # then commit results.json and logs

Data come from the public bucket and Hugging Face inside the container (the setup step of the repo's mac-w045.sh).
"""
import subprocess
import modal

BRANCH = "grok/laneH-finetune"
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("git", "curl", "build-essential")
         .run_commands("curl -LsSf https://astral.sh/uv/install.sh | sh", "ln -s /root/.local/bin/uv /usr/local/bin/uv",
                       "ln -s /root/.local/bin/uvx /usr/local/bin/uvx"))
vol = modal.Volume.from_name("scrolls-laneH", create_if_missing=True)
app = modal.App("scrolls-laneH-finetune")


@app.function(image=image, gpu="A10G", cpu=8, memory=32768, timeout=4 * 3600, volumes={"/work": vol})
def run(smoke_steps: int = 0):
    sh = f"""set -euo pipefail
    [ -d /work/Scrolls ] || git clone -q -b {BRANCH} https://github.com/ChaseHendrick/Scrolls.git /work/Scrolls
    cd /work/Scrolls && git fetch -q origin {BRANCH} && git checkout -q FETCH_HEAD
    WORK=/work/scrolls-work OUT=/work/laneH SMOKE_STEPS={smoke_steps} bash scripts/experiments/2026-10-07-cloud/laneH-finetune/run_job.sh 2>&1 | tee /work/laneH_run.log
    cp scripts/experiments/2026-10-07-cloud/laneH-finetune/results.json /work/laneH/results.json"""
    try:
        subprocess.run(["bash", "-c", sh], check=True)
    finally:
        vol.commit()


@app.local_entrypoint()
def main(smoke_steps: int = 0):
    run.remote(smoke_steps)
