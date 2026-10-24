"""Print a First Letters run plan for one eligible scroll.

The commands are copied from the official ink detection tutorial
(https://scrollprize.org/tutorial5, villa commit e0bbb8b, checked 2026-10-06). This
module prints them; it never runs them. Paths and flags change upstream, so treat the
tutorial as the authority when a command fails.

`spiral_chain` prints the large-surface route instead: a public center line, a public lasagna
field, villa's spiral fit and flattening, a region render and an Ink Lens check, read from
villa's spiral-fitting code at VILLA_SPIRAL (checked 2026-10-24).
"""

import json
from pathlib import Path

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
#    The render commands below pass the bucket URL as --volume, which current builds stream
#    (villa e2254eb); an older build needs --volume DIR --remote-url URL instead.
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
  --volume s3://vesuvius-challenge-open-data/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/ \\
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
# Current vc_render_tifxyz streams a remote OME-Zarr given as --volume URL (villa e2254eb);
# it refuses a local --volume DIR next to a different --remote-url URL. Older builds need that pair.
"""

HELD_OUT = """\
# 1b. Labeled check: PHerc0139 w045, unseen by v8in. ink_9um trained on its 2.4 um render
#     (pherc0139-w029), so here it shows cross-scan reading of a training surface, not
#     generalization; PHerc0841 is the held-out test for ink_9um, v8in, v8in-1447, d9v2 and
#     Reader v2 (not for Hecate: its base model's trainer lists all three PHerc0841
#     segments). Score w045 before you look at any target: Bullo27 reports row scores 73-148
#     on w045 and w033.
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
  --volume s3://vesuvius-challenge-open-data/{scroll}/volumes/{zarr}/ \\
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
        letters = prizes.find(snapshot, "first-letters-2027")
        names = ", ".join(e["scroll"] for e in letters["eligible"])
        wanted = prizes.normalize_scroll(scroll)
        won = [a for a in letters.get("awarded", []) if prizes.normalize_scroll(a["scroll"]) == wanted]
        why = ""
        if won:
            source = (won[0].get("sources") or ["no source recorded"])[0]
            why = f" Its First Letters prize was awarded on {won[0].get('date', 'an unrecorded date')} ({source})."
        raise ValueError(f"{scroll} is not First Letters eligible in the {snapshot['checked']} snapshot.{why} Eligible: {names}")
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


VILLA_SPIRAL = "e2254ebe0168a232e5ba7b94997c749b4e6a4544"   # villa main, 23 Oct 2026
SPIRAL_INPUTS = Path(__file__).with_name("data") / "spiral-inputs-2026-10-24.json"
BUCKET_S3 = "s3://vesuvius-challenge-open-data"
# villa fit_spiral.py settings for a fit from the lasagna field and a center line alone: grad_mag spacing, every
# other input off, room for 300 windings, no outer shell. Not yet shown to put the surface on the sheets.
SPIRAL_OVERRIDES = {
    "optimizer_num_training_steps": 30000, "optimizer_random_seed": 1,
    "dense_spacing_mode": "grad_mag", "dense_grad_mag_factor": 0.14,
    "input_use_winding_inference": False, "input_use_verified_patches": False, "input_disable_patches": True,
    "input_use_tracks": False, "input_use_fibers": False, "input_use_fiber_directions": False,
    "input_use_pcl_absolute": False, "input_use_pcl_relative": False, "input_use_pcl_same_winding": False,
    "input_use_pcl_drawn_control_points": False, "input_use_outer_shell": False, "loss_weight_shell_outer": 0.0,
    "shell_outer_winding_idx": 300, "model_gap_expander_capacity_windings": 304,
    "model_initial_dr_per_winding": 16.0, "loss_start_unattached_pcl_dt": 30000,
}
REGION_PX = 1024

SPIRAL_HEAD = """\
# First Letters large-surface chain for {scroll}: center line, lasagna field, spiral fit, flatten, render, Ink Lens
# (prize snapshot {checked}, inputs read {inputs_checked}; check scrollprize.org/prizes first)
# Status: experimental. Not yet run end to end, and the fit settings are not yet shown to keep the surface
#   on one sheet: read step 7's surface checks before you trust a render. Each command was read from the tool's code or page at the pinned commits;
#   an upstream change can break one, and then the tool's own docs win.
# Needs: git, uv, the AWS CLI or the hf CLI, a VC3D build (vc_render_tifxyz on PATH), this Scrolls checkout
#   (python -m kit, spaces/ink-lens), and a CUDA GPU for the fit: villa's Triton kernels are CUDA only, and
#   the fitter falls back to MPS or the CPU without them. You pay for your own compute; nothing here uploads.
set -euo pipefail
export W="$PWD/work/{slug}" DS="$PWD/work/{slug}/spiral-dataset"
Z0="${{Z0:-0}}" Z1="${{Z1:-{slices}}}"        # the fit window in level-0 slices; the whole scan unless you set them
mkdir -p "$DS/lasagna_inputs"

# 0. Setup (once): villa at the commit these commands were read from, and its spiral-fitting environment.
git clone https://github.com/ScrollPrize/villa.git "$W/villa"
git -C "$W/villa" checkout {villa}
(cd "$W/villa/spiral-fitting" && UV_PYTHON=3.14 uv sync --frozen)
export SF="$W/villa/spiral-fitting" SPY="$W/villa/spiral-fitting/.venv/bin/python"

# 1. Center line: the best public line for {scroll}, sha256-checked, written as $DS/umbilicus.json.
python -m kit centerline get {scroll} --into "$DS"
#    Check the volume it prints: it must be {volume} (level-0 voxels). `kit centerline list {scroll}` shows the rest.
"""

SPIRAL_LASAGNA_BUCKET = """\
# 2. Lasagna field: the organizers' run in the open data, OME-Zarr level 2 (4x down) of the three stores the fit reads.
for c in nx ny grad_mag; do
  aws s3 sync --no-sign-request "{bucket}/{prefix}{scroll}_$c.ome.zarr/" "$DS/lasagna_inputs/{scroll}_$c.ome.zarr/" \\
    --exclude "*" --include ".z*" --include "2/*"
done
"""

SPIRAL_LASAGNA_HF = """\
# 2. Lasagna field: villa's lasagna predict3d over the whole scan, shared as {dataset} (CC BY-NC 4.0).
#    The open data has none for this volume. Its card: https://huggingface.co/datasets/{dataset}
hf download {dataset} --repo-type dataset --local-dir "$W/lasagna"
(cd "$W/lasagna" && sha256sum -c SHA256SUMS && for f in parts/*.tar; do tar -xf "$f"; done \\
  && tar -xf {scroll}-lasagna-pyramid-fix.tar)
for c in nx ny grad_mag; do mv "$W/lasagna/{scroll}_$c.ome.zarr" "$DS/lasagna_inputs/"; done
"""

SPIRAL_FIT = """\
# 3. The scroll specification villa's fitter requires ({spec_note}).
cat > "$DS/spiral-scroll.json" <<EOF
{spec}
EOF

# 4. Pack the lasagna stores: the fitter reads them only through these sidecars.
(cd "$SF" && PYTHONPATH="$SF" "$SPY" pack_resident_pools.py "$DS/lasagna_inputs" \\
  --what normals,grad_mag --normal-group 2 --verify 2000)

# 5. Fit one spiral from the lasagna field and the center line alone (no traces, fibers or point collections).
(cd "$SF" && FIT_SPIRAL_DEVICE=cuda WANDB_MODE=disabled FIT_SPIRAL_OUT_DIR="$W/fit" FIT_SPIRAL_CACHE_DIR="$W/fit-cache" \\
  FIT_SPIRAL_CONFIG_OVERRIDES="{{\\"z_begin\\": $Z0, \\"z_end\\": $Z1, {overrides}}}" \\
  PYTHONPATH="$SF" "$SPY" fit_spiral.py --dataset "$DS")
CKPT="$(find "$W/fit" -name checkpoint_fitted.ckpt | head -n 1)"

# 6. Flatten it with villa's one-shot exporter (a private Lasagna flatten; it never overwrites an output).
(cd "$SF" && PYTHONPATH="$SF" "$SPY" flatten_spiral_checkpoint.py "$CKPT" "$W/surface.tifxyz" \\
  --umbilicus "$DS/umbilicus.json" --lasagna-dir "$W/villa/lasagna" --voxel-size-um {voxel})
"""

SPIRAL_QA = """\
# 7. Check the surface before any ink model sees it (both read the tifxyz only):
#      tifxyz-doctor (github.com/aviad12g/tifxyz-doctor): file, metadata and topology checks
#      windcheck check "$W/surface.tifxyz" (github.com/joe-carr-data/windcheck): self-intersections
#    Nothing yet shows that a fit from the lasagna field and center line alone sits on the sheets: it can
#    follow their direction and spacing yet lie between them, where there is no ink. Measure how much of it
#    lies on papyrus in your area (for example against a traced segment) before you trust a map of it.
"""

SPIRAL_RULES = """\
# 8. Before any ink model runs on the surface:
#    - Write your readout rule in experiments/{slug}/run.json (python -m kit run init): the region, the
#      reader, and what counts as a pass. Pick the region from the geometry, not from an ink map.
#    - First Letters needs an ink model that never trained on your area: check each reader's training list.
"""

SPIRAL_INK = """\
# 9. Render one region of the surface ({px} px at the top left X, Y, in render pixels) and check it with
#    Ink Lens: both depth orders, three depth windows, ink kept only above the region's own reverse-depth control.
X="${{X:?set X}}" Y="${{Y:?set Y}}"
vc_render_tifxyz \\
  --volume {bucket}/{scroll}/volumes/{zarr}/ \\
  --segmentation "$W/surface.tifxyz" --zarr-output "$W/region_{x0}.zarr" \\
  --crop-x "$X" --crop-y "$Y" --crop-width {px} --crop-height {px} \\
  --scale 1 --group-idx 0 --num-slices 28 --cache-gb 16 \\
  --voxel-size {voxel} --voxel-unit micrometer {flip}
python3 spaces/ink-lens/inklens.py run --segment "$W/surface.tifxyz" \\
  --volume {bucket}/{scroll}/volumes/{zarr}/ \\
  --box "$X" "$Y" {px} {px} --um-per-px {voxel} --local --json > "$W/inklens.json"
#    gate.status ink or weak (exit 0) is model output that passed its control, not a reading; none exits 3,\n#    which stops this script.
#    --local keeps the region on your machine; without it the region goes to the SharpMeow/ink-lens Space,
#    which runs on your own Hugging Face token and keeps no upload.
"""

SPIRAL_AFTER = """\
# 10. If you see letters: tell nobody in public, keep everything in work/ (gitignored), and follow
#     docs/WORKFLOW.md to submit: {submit}
"""


def spiral_inputs(path=None):
    return json.loads(Path(path or SPIRAL_INPUTS).read_text())


def spiral_spec(scroll, voxel_um, row, group="2", scale=4):
    """spiral-scroll.json for villa's fitter: the catalog's two properties when both are known (villa then derives
    the sense, ACW exactly when they differ, and checks the one given), else a sense the user must supply."""
    spec = {"schema_version": 1, "name": scroll, "voxel_size_um": voxel_um}
    z, lh = row.get("z_direction_is_top_to_bottom"), row.get("left_handed_coordinates")
    if isinstance(z, bool) and isinstance(lh, bool):
        spec.update(z_direction_is_top_to_bottom=z, left_handed_coordinates=lh,
                    spiral_outward_sense="ACW" if z != lh else "CW")
    else:
        spec["spiral_outward_sense"] = "$SENSE"
    spec.update(normal_zarr_group=group, lasagna_scale=scale, umbilicus={"coordinate_scale": 1.0})
    return spec


def spiral_chain(scroll, snapshot=None, inputs=None):
    snapshot = snapshot or prizes.load()
    entry = prizes.eligible_entry(snapshot, scroll)
    if entry is None:
        first_letters(scroll, snapshot=snapshot)       # raises the same refusal as the ink plan
    inputs = inputs or spiral_inputs()
    canonical = entry["scroll"]
    row = inputs["scans"].get(canonical)
    if row is None or row.get("volume") != entry["volume"]:
        raise ValueError(f"{canonical}: no public spiral-fit inputs recorded for volume {entry['volume']} "
                         f"(inputs read {inputs['checked']}); see docs/tools/plan.md")
    slug = canonical.lower()
    las = row["lasagna"]
    if "bucket" in las:
        lasagna = SPIRAL_LASAGNA_BUCKET.format(bucket=BUCKET_S3, prefix=las["bucket"], scroll=canonical)
    else:
        lasagna = SPIRAL_LASAGNA_HF.format(dataset=las["dataset"], scroll=canonical)
    spec = spiral_spec(canonical, entry["voxel_um"], row, inputs["normal_zarr_group"], inputs["lasagna_scale"])
    known = spec["spiral_outward_sense"] != "$SENSE"
    if known:
        spec_note = (f"the catalog's two properties; villa derives {spec['spiral_outward_sense']} from them and "
                     "checks the sense given")
        sense_line = ""
    else:
        spec_note = ("the catalog gives no z direction for this volume, so villa needs the spiral's outward sense "
                     "read off the CT in VC3D by a person, or from an earlier fit: CW or ACW")
        sense_line = 'SENSE="${SENSE:?set SENSE to CW or ACW, read off the CT in VC3D}"\n'
    body = json.dumps(spec, indent=1)
    overrides = json.dumps(SPIRAL_OVERRIDES)[1:-1].replace('"', '\\"')
    fit = SPIRAL_FIT.format(spec_note=spec_note, spec=body, overrides=overrides, voxel=entry["voxel_um"])
    if sense_line:
        fit = fit.replace('cat > "$DS/spiral-scroll.json"', sense_line + 'cat > "$DS/spiral-scroll.json"', 1)
    lh = row.get("left_handed_coordinates")
    flip = "--flip-normals" if lh is False else "# --flip-normals when left_handed_coordinates is false (villa)"
    submit = prizes.find(snapshot, "first-letters-2027")["submit"]
    return "\n".join([
        SPIRAL_HEAD.format(scroll=canonical, checked=snapshot["checked"], inputs_checked=inputs["checked"],
                           slug=slug, slices=row["slices"], villa=VILLA_SPIRAL, volume=entry["volume"]),
        lasagna,
        fit,
        SPIRAL_QA,
        SPIRAL_RULES.format(slug=slug),
        SPIRAL_INK.format(px=REGION_PX, bucket=BUCKET_S3, scroll=canonical, zarr=entry["zarr"], voxel=entry["voxel_um"],
                          flip=flip, x0="$X-$Y"),
        SPIRAL_AFTER.format(submit=submit),
    ])
