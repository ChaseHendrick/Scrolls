"""Unrun Modal plan. Default entrypoint refuses any remote launch.

Future GPU execution requires separate budget authorization and explicit --allow-gpu.
Each worker checks out the same supplied commit into its own temporary code directory.
Only immutable environment/data and distinct output files share the Volume.
"""
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import modal

image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("git", "curl", "build-essential")
         .run_commands("curl -LsSf https://astral.sh/uv/install.sh | sh",
                       "ln -s /root/.local/bin/uv /usr/local/bin/uv", "ln -s /root/.local/bin/uvx /usr/local/bin/uvx"))
vol = modal.Volume.from_name("scrolls-laneH", create_if_missing=True)
app = modal.App("scrolls-laneH-finetune")
VARIANTS = ["P90", "P80", "S1", "S2"]


def _run(phase, smoke_steps, repo_commit, variant=""):
    if phase not in ('prepare', 'base', 'variant', 'collect') or variant and variant not in VARIANTS:
        raise ValueError('unsupported phase or variant')
    if smoke_steps < 0 or not re.fullmatch(r'[0-9a-f]{40}', repo_commit):
        raise ValueError('require nonnegative smoke steps and a full frozen commit SHA')
    t0 = time.time()
    tag = phase + (f"_{variant}" if variant else "")
    code = Path(tempfile.mkdtemp(prefix='Scrolls-' + tag + '-')) / 'source'
    out = Path('/work/laneH' + ('-smoke' if smoke_steps else ''))
    try:
        vol.reload()
        subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout',
                        'https://github.com/ChaseHendrick/Scrolls.git', str(code)], check=True)
        subprocess.run(['git', '-C', str(code), 'fetch', 'origin', repo_commit], check=True)
        subprocess.run(['git', '-C', str(code), 'checkout', '--detach', repo_commit], check=True)
        environment = dict(os.environ, WORK='/work/scrolls-work', OUT='/work/laneH', PHASE=phase,
                           VARIANT=variant, SMOKE_STEPS=str(smoke_steps), LANEH_EXECUTE='1', LANEH_GPU_AUTHORIZED='1')
        log = Path('/work/logs') / (tag + '.log');log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('w') as stream:
            subprocess.run(['bash', str(code/'scripts/experiments/2026-10-07-cloud/laneH-finetune/run_job.sh')],
                           cwd=code, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True)
    finally:
        timing = out/'timing';timing.mkdir(parents=True, exist_ok=True)
        (timing/('container_' + tag + '.json')).write_text(json.dumps({
            'tag': tag, 'container_start_epoch_s': t0, 'container_end_epoch_s': time.time(),
            'scrolls_commit': repo_commit}) + '\n')
        vol.commit()
    return tag


@app.function(image=image, cpu=8, memory=32768, timeout=3 * 3600, volumes={"/work": vol})
def prepare(smoke_steps: int = 0, repo_commit: str = ''):
    return _run('prepare', smoke_steps, repo_commit)


@app.function(image=image, gpu="H100", cpu=8, memory=65536, timeout=2 * 3600, volumes={"/work": vol})
def base(smoke_steps: int = 0, repo_commit: str = ''):
    return _run('base', smoke_steps, repo_commit)


@app.function(image=image, gpu="H100", cpu=8, memory=65536, timeout=3 * 3600, volumes={"/work": vol})
def variant(name: str, smoke_steps: int = 0, repo_commit: str = ''):
    return _run('variant', smoke_steps, repo_commit, name)


@app.function(image=image, cpu=2, memory=8192, timeout=1800, volumes={"/work": vol})
def collect(smoke_steps: int = 0, repo_commit: str = ''):
    return _run('collect', smoke_steps, repo_commit)


@app.local_entrypoint()
def main(smoke_steps: int = 0, allow_gpu: bool = False):
    if not allow_gpu:
        raise ValueError('Not run: no remote launch without --allow-gpu and separate budget authorization')
    if smoke_steps < 0:
        raise ValueError('smoke steps must be nonnegative')
    source = Path(__file__).resolve().parents[4]
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    t = time.time()
    print(prepare.remote(smoke_steps, commit), f'{time.time() - t:.0f} s')
    print(base.remote(smoke_steps, commit), f'{time.time() - t:.0f} s')
    for tag in variant.map(VARIANTS, kwargs={'smoke_steps': smoke_steps, 'repo_commit': commit}):
        print(tag, f'{time.time() - t:.0f} s')
    collect.remote(smoke_steps, commit)
    print('Results remain outside the source checkout on the Volume; smoke scores are pipeline diagnostics only.')
