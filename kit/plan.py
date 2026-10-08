"""Print a First Letters run plan for one eligible scroll.

The commands are copied from the official ink detection tutorial
(https://scrollprize.org/tutorial5, villa commit e0bbb8b, checked 2026-10-06). This
module prints them; it never runs them. Paths and flags change upstream, so treat the
tutorial as the authority when a command fails.
"""

from . import prizes

SETUP_MAC = """\
# 0. Setup on Apple Silicon (once). Nothing here uses CUDA.
#    VC3D: install VC3D-<version>-macos-arm64.dmg from https://github.com/ScrollPrize/villa/releases
#    Use the latest build: the stable build crashes opening PHerc0826 (villa issue #1910).
brew install uv awscli
#    First launch of VC3D: right-click > Open, or
xattr -dr com.apple.quarantine /Applications/VC3D.app
export VC_BIN=/Applications/VC3D.app/Contents/MacOS   # vc_render_tifxyz and friends ship here
export PATH="$VC_BIN:$PATH"
git clone https://github.com/ScrollPrize/villa.git
cd villa/vesuvius && uv sync --extra models
#    Not yet tried on macOS by this repo. If the volume-cartographer Python package fails to
#    build, follow the macOS section of villa/volume-cartographer/README.md (scripts/build_macos.sh).
uv run --extra models python -c "import torch; print(torch.__version__, '| mps:', torch.backends.mps.is_available())"
uvx --from huggingface_hub hf download scrollprize/ink_9um \\
  hybrid_3d2d-seed42/step-075000.pth --local-dir checkpoints/ink_9um
uvx --from huggingface_hub hf download scrollprize/ink_9um \\
  hybrid_3d2d-seed43/step-075000.pth --local-dir checkpoints/ink_9um
#    Stock villa ink inference ignores the Mac GPU and runs on the CPU: correct, but slow
#    (about 114 s CPU vs 38 s MPS for one PHerc0139 segment in villa PR #1865's test).
#    To try the GPU, check out an open, unreviewed PR branch and record which one you used:
#      git fetch origin pull/1865/head:pr-1865 && git checkout pr-1865
#    Reported risk on #1865: with torch 2.12.1, non-blocking host-to-MPS copies can read freed
#    memory. Run the control on CPU and on MPS and compare before trusting MPS output.
#    Full-scroll work: rent a CUDA GPU (docs/compute.md).
"""

CONTROL = """\
# 1. Control first: a PHerc. 0139 segment the released models were trained on.
#    If you cannot see letters here, the pipeline is broken, not the scroll.
#    The clean letters it shows are the training labels, reproduced (docs/logs/2026-10-07-w035-cpu.md).
#    That proves the pipeline runs, not that the model finds ink it was not trained on.
aws s3 sync --no-sign-request \\
  s3://vesuvius-challenge-open-data/PHerc0139/segments/20260317000000-w035_2026031718/mesh/20260317000000-on-20250728140407-9.362um.tifxyz/ \\
  ink-dataset/pherc0139/w035/w035.tifxyz
vc_render_tifxyz \\
  --volume volume-cache/20250728140407.zarr \\
  --remote-url s3://vesuvius-challenge-open-data/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/ \\
  --segmentation ink-dataset/pherc0139/w035/w035.tifxyz \\
  --zarr-output ink-dataset/pherc0139/w035/w035_9um.zarr \\
  --scale 1 --group-idx 0 --num-slices 28 --cache-gb 16 \\
  --voxel-size 9.362 --voxel-unit micrometer --flip-normals
uv run --extra models python -m vesuvius.ink_detection.inference.infer \\
  ink-dataset/pherc0139/w035/w035_9um.zarr \\
  checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth \\
  predictions/w035_9um.tif \\
  --overlap 0.5 --blend-mode hann --batch-size {batch}
"""

SETUP = """\
# 0. Setup (once). Linux or WSL2, NVIDIA GPU with CUDA.
git clone https://github.com/ScrollPrize/villa.git
cd villa/vesuvius && uv sync --extra models
uv run --extra models python -c "import torch; print(torch.__version__, '| cuda:', torch.cuda.is_available())"
uvx --from huggingface_hub hf download scrollprize/ink_9um \\
  hybrid_3d2d-seed42/step-075000.pth --local-dir checkpoints/ink_9um
uvx --from huggingface_hub hf download scrollprize/ink_9um \\
  hybrid_3d2d-seed43/step-075000.pth --local-dir checkpoints/ink_9um
# Build vc_render_tifxyz from current villa main. The published VC3D container was
# reported stale (villa issue #1588) and lacked --flip-normals.
"""

HELD_OUT = """\
# 1b. Labelled check: PHerc0139 w045, unseen by v8in. ink_9um trained on its 2.4 um render
#     (pherc0139-w029), so here it shows cross-scan reading of a training surface, not
#     generalization; PHerc0841 is the held-out test. Score it before you look at any
#     target: Bullo27 reports row scores 73-148 on w045 and w033.
python -m kit fetch w045 ink-dataset/pherc0139/w045/w045_9um.zarr
uv run --extra models python -m vesuvius.ink_detection.inference.infer \\
  ink-dataset/pherc0139/w045/w045_9um.zarr \\
  checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth \\
  predictions/w045_seed42.tif \\
  --overlap 0.5 --blend-mode hann --batch-size {batch} --direction both
python -m kit rowscore predictions/w045_seed42.tif --reverse predictions/w045_seed42_reverse.tif --voxel-um 9.362
"""

V8IN = """\
#    Newer model: YoussefMoNader/ink-8um-v8in (MIT, released 2026-09-28), a ResNet3D-50 that
#    responds near the team's announced PHerc1447 text, which it never saw (Bullo27, 2026-09-30).
#    Every published First Letters null used ink_9um. v8in reads a folder of 24 layer TIFFs
#    (00.tif, 01.tif, ...), not a zarr; export the render's layers first. Not yet run by this repo.
uvx --from huggingface_hub hf download YoussefMoNader/ink-8um-v8in --local-dir checkpoints/ink-8um-v8in --exclude "training/*"
python checkpoints/ink-8um-v8in/predict.py --layers work/{slug}/layers --output work/{slug}/v8in_forward.tif{device}
python checkpoints/ink-8um-v8in/predict.py --layers work/{slug}/layers --output work/{slug}/v8in_reverse.tif --reverse{device}
"""

QA = """\
#    Before rendering, check the surface (both read the tifxyz only, CPU, minutes):
#      tifxyz-doctor (github.com/aviad12g/tifxyz-doctor): file, metadata and topology checks
#      windcheck check work/{slug}/surface.tifxyz (github.com/joe-carr-data/windcheck):
#        self-intersections, i.e. places the trace passes through itself
#    A trace that fails either is fixed in VC3D before any ink model sees it.
"""

TARGET = """\
# 2. Target: {scroll}, eligible volume {volume} ({voxel} um voxels)
#    Browse: {browser}{resample}
#    Grow a surface in VC3D: open the scroll from the data catalog, Create Segment (GrowPatch)
#    on the recto surface prediction, and fix sheet switches by hand. Tutorial:
#    https://scrollprize.org/tutorial_VC3D
#    Then render it the same way as the control:
vc_render_tifxyz \\
  --volume volume-cache/{volume}.zarr \\
  --remote-url s3://vesuvius-challenge-open-data/{scroll}/volumes/{zarr}/ \\
  --segmentation work/{slug}/surface.tifxyz \\
  --zarr-output work/{slug}/surface_9um.zarr \\
  --scale 1 --group-idx 0 --num-slices 28 --cache-gb 16 \\
  --voxel-size {voxel} --voxel-unit micrometer --flip-normals
#    --flip-normals puts layers in the team's order, as for the control. Without it the
#    forward and reverse maps swap (pscamillo's eligible-mesh maps, corrected 2026-09-15).
#    Run both seeds, both depth directions (a surface's facing is unknown):
uv run --extra models python -m vesuvius.ink_detection.inference.infer \\
  work/{slug}/surface_9um.zarr \\
  checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth \\
  work/{slug}/ink_seed42.tif \\
  --overlap 0.5 --blend-mode hann --batch-size {batch} --direction both
"""

NATIVE_UM = 9.362
RESAMPLE_NOTE = """
#    Note: this scan is {voxel} um, the ink_9um models were trained near 9.36 um.
#    Published runs on 8.64 um scans also tried resampling to 9.362 um
#    (nerln/vesuvius-first-letters-pherc0800). Try both and record which you used."""

RULES = """\
# 3. Before you look at the target output:
#    - Write your readout rule in experiments/{slug}/run.json (python -m kit run init).
#    - Use `set -o pipefail`: a failed render piped through tee looks like success.
#    - Compare forward and reverse depth. Ink should appear in one, not both.
#    - Triage with python -m kit rowscore (forward maps, --reverse maps); then look anyway.
# 4. If you see letters: tell nobody in public. Keep it in work/ (gitignored),
#    and follow docs/WORKFLOW.md to submit: {submit}
"""


def first_letters(scroll, batch=None, snapshot=None, mac=False):
    snapshot = snapshot or prizes.load()
    entry = prizes.eligible_entry(snapshot, scroll)
    if entry is None:
        names = ", ".join(e["scroll"] for e in prizes.find(snapshot, "first-letters-2027")["eligible"])
        raise ValueError(f"{scroll} is not First Letters eligible in the {snapshot['checked']} snapshot. Eligible: {names}")
    canonical = entry["scroll"]
    slug = canonical.lower()
    if batch is None:
        batch = 1 if mac else 4
    resample = ""
    if abs(entry["voxel_um"] - NATIVE_UM) > 0.1:
        resample = RESAMPLE_NOTE.format(voxel=entry["voxel_um"])
    submit = prizes.find(snapshot, "first-letters-2027")["submit"]
    return "\n".join([
        f"# First Letters plan for {canonical} (prize snapshot {snapshot['checked']}; check scrollprize.org/prizes first)",
        "",
        SETUP_MAC if mac else SETUP,
        CONTROL.format(batch=batch),
        HELD_OUT.format(batch=batch),
        QA.format(slug=slug),
        TARGET.format(scroll=canonical, volume=entry["volume"], zarr=entry["zarr"], voxel=entry["voxel_um"],
                      browser=prizes.DATA_BROWSER + canonical, slug=slug, batch=batch, resample=resample),
        V8IN.format(slug=slug, device=" --device mps" if mac else ""),
        RULES.format(slug=slug, submit=submit),
    ])


def cost(gpu_hours, rate_per_hour, cpu_hours=0.0, cpu_rate=0.0, storage_usd=0.0):
    return round(gpu_hours * rate_per_hour + cpu_hours * cpu_rate + storage_usd, 2)
