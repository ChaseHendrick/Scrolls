"""Print a First Letters run plan for one eligible scroll.

The commands are copied from the official ink detection tutorial
(https://scrollprize.org/tutorial5, villa commit e0bbb8b, checked 2026-10-06). This
module prints them; it never runs them. Paths and flags change upstream, so treat the
tutorial as the authority when a command fails.
"""

from . import prizes

CONTROL = """\
# 1. Control first: a PHerc. 0139 segment the released models were trained on.
#    If you cannot see letters here, the pipeline is broken, not the scroll.
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
  --voxel-size {voxel} --voxel-unit micrometer
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
# 4. If you see letters: tell nobody in public. Keep it in work/ (gitignored),
#    and follow docs/WORKFLOW.md to submit: {submit}
"""


def first_letters(scroll, batch=4, snapshot=None):
    snapshot = snapshot or prizes.load()
    entry = prizes.eligible_entry(snapshot, scroll)
    if entry is None:
        names = ", ".join(e["scroll"] for e in prizes.find(snapshot, "first-letters-2027")["eligible"])
        raise ValueError(f"{scroll} is not First Letters eligible in the {snapshot['checked']} snapshot. Eligible: {names}")
    canonical = entry["scroll"]
    slug = canonical.lower()
    resample = ""
    if abs(entry["voxel_um"] - NATIVE_UM) > 0.1:
        resample = RESAMPLE_NOTE.format(voxel=entry["voxel_um"])
    submit = prizes.find(snapshot, "first-letters-2027")["submit"]
    return "\n".join([
        f"# First Letters plan for {canonical} (prize snapshot {snapshot['checked']}; check scrollprize.org/prizes first)",
        "",
        SETUP,
        CONTROL.format(batch=batch),
        TARGET.format(scroll=canonical, volume=entry["volume"], zarr=entry["zarr"], voxel=entry["voxel_um"],
                      browser=prizes.DATA_BROWSER + canonical, slug=slug, batch=batch, resample=resample),
        RULES.format(slug=slug, submit=submit),
    ])


def cost(gpu_hours, rate_per_hour, cpu_hours=0.0, cpu_rate=0.0, storage_usd=0.0):
    return round(gpu_hours * rate_per_hour + cpu_hours * cpu_rate + storage_usd, 2)
