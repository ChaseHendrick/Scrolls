#!/usr/bin/env bash
# One command, on an Apple Silicon Mac: do the ink models find ink they were not trained on?
# PHerc0139 segment w045 has published ink labels and is in neither model's training set
# (ink_9um: Bullo27's survey; v8in: its patch pack lists w033, w035, w041, w044). Runs, on the
# Mac GPU:
#   - ink_9um seeds 42 and 43 through villa PR #1865 (MPS), both depth directions;
#   - v8in (YoussefMoNader/ink-8um-v8in), first on a crop on CPU and MPS (kit verify: same map?),
#     then over the labelled part of the segment, both directions;
# and scores every map with kit auc (against the labels, reverse direction as the control) and
# kit rowscore. Paste the summary it prints. See docs/mac.md.
#
#   bash scripts/mac-w045.sh                   # from the Scrolls checkout
#   V8IN_HOURS=2 bash scripts/mac-w045.sh      # time budget for the full v8in pass (picks the stride)
#   V8IN_STRIDE=21 bash scripts/mac-w045.sh    # or set the stride (21 is v8in's own default)
#   V8IN_FP16=1 bash scripts/mac-w045.sh       # fp16 on MPS, kept only if the crop check still passes
#   V8IN_REGION=full bash scripts/mac-w045.sh  # whole segment, not just the labelled box (about 1.5x the tiles)
#   V8IN_BATCH=4 bash scripts/mac-w045.sh      # tiles per batch (default from memory: fp32 batch 8 needs about 10 GB)
#
# Needs: git, uv (brew install uv), about 6 GB free in $WORK. Shares $WORK with mac-verify.sh.
# Nothing is uploaded. w045 is a training scroll with published labels, so its maps are not a
# First Letters candidate.
# EXPECT_GPU=cpu runs without MPS and SMOKE=1 crops everything to one 640 px window (both
# used to test the script itself).
set -euo pipefail
unset PYTORCH_ENABLE_MPS_FALLBACK   # an op MPS lacks must fail, not quietly run on the CPU

SCROLLS="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$HOME/scrolls-work}"
VILLA="$WORK/villa"
PY="$WORK/venv/bin/python"
EXPECT_GPU="${EXPECT_GPU:-mps}"
SMOKE="${SMOKE:-0}"
PR=1865
V8IN_REPO=YoussefMoNader/ink-8um-v8in
V8IN_REV=d89166b41a3f5fad7749b3d7c0fdd1bd3695d844   # 2026-09-28 release
V8IN="$WORK/checkpoints/ink-8um-v8in"
SEG=PHerc0139/segments/20260126000000-w045_2026012619
LABELS="$SEG/ink-labels/2.399um-volume-20260102150214/20260918"
ZARR="$WORK/data/w045_9um.zarr"
LAB="$WORK/data/w045_labels"
OUT="$WORK/w045"
CROP=(3840 4480 2560 3200)   # 640 px fully on the surface, densest labelled ink (y0 y1 x0 x1)
SURFACE=(5980 8240)

say() { printf '\n== %s\n' "$*"; }
sha() { local s; s="$(shasum -a 256 "$1" 2>/dev/null || sha256sum "$1")"; echo "${s%% *}"; }

if [[ "$EXPECT_GPU" == "mps" && "$(uname -s)/$(uname -m)" != "Darwin/arm64" ]]; then
  echo "This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere)." >&2
  exit 2
fi
command -v git >/dev/null || { echo "git is missing (xcode-select --install)" >&2; exit 2; }
command -v uv >/dev/null || { echo "uv is missing: brew install uv" >&2; exit 2; }
mkdir -p "$WORK"/{checkpoints,data,logs} "$OUT"/{maps,results}

say "1/7 villa main and PR #$PR, Python 3.14 environment"
if [[ ! -d "$VILLA/.git" ]]; then
  git clone -q --filter=blob:none https://github.com/ScrollPrize/villa.git "$VILLA"
fi
git -C "$VILLA" fetch -q origin main "+pull/$PR/head:pr-$PR"
MAIN_SHA="$(git -C "$VILLA" rev-parse --short origin/main)"
PR_SHA="$(git -C "$VILLA" rev-parse --short "pr-$PR")"
[[ -x "$PY" ]] || uv venv -q --python 3.14 "$WORK/venv"
git -C "$VILLA" checkout -q --detach origin/main
"$PY" - "$VILLA/vesuvius/pyproject.toml" > "$WORK/models-reqs.txt" <<'EOF'
import sys, tomllib
skip = ("volume-cartographer", "cucim", "nnunetv2", "batchgeneratorsv2")
for req in tomllib.load(open(sys.argv[1], "rb"))["project"]["optional-dependencies"]["models"]:
    if not req.startswith(skip):
        print(req)
EOF
uv pip install -q --python "$PY" -e "$VILLA/vesuvius" -r "$WORK/models-reqs.txt" \
  tifffile imagecodecs scipy opencv-python-headless safetensors huggingface_hub
TORCH="$("$PY" -c 'import torch; print(torch.__version__, "mps available:", torch.backends.mps.is_available())')"
echo "torch $TORCH"
V8IN_DEVICE=mps; [[ "$EXPECT_GPU" == "mps" ]] || V8IN_DEVICE=cpu
MEM_GB="$(( $(sysctl -n hw.memsize 2>/dev/null || awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo) / 1073741824 ))"
if [[ -n "${V8IN_BATCH:-}" ]]; then BATCH="$V8IN_BATCH"
elif (( MEM_GB <= 16 )); then BATCH=4
elif (( MEM_GB <= 32 )); then BATCH=8
else BATCH=16; fi
FP16=(--batch-size "$BATCH")   # never empty, as AUC_CROP below
[[ "${V8IN_FP16:-0}" == "1" && "$V8IN_DEVICE" == "mps" ]] && FP16+=(--fp16)
echo "memory ${MEM_GB} GB: v8in batch $BATCH${V8IN_FP16:+, fp16 $V8IN_FP16}"

say "2/7 data: w045 surface volume (1.7 GB), its labels, three checkpoints"
(cd "$SCROLLS" && "$PY" -m kit fetch w045 "$ZARR")
for z in inklabels supervision; do
  (cd "$SCROLLS" && "$PY" -m kit fetch "$LABELS/$z.zarr" "$LAB/$z.zarr" --workers 8)
done
for seed in 42 43; do
  ck="$WORK/checkpoints/ink_9um/hybrid_3d2d-seed$seed/step-075000.pth"
  [[ -f "$ck" ]] || uvx -q --from huggingface_hub hf download scrollprize/ink_9um \
    "hybrid_3d2d-seed$seed/step-075000.pth" --local-dir "$WORK/checkpoints/ink_9um"
done
"$PY" - "$V8IN" "$V8IN_REPO" "$V8IN_REV" <<'EOF'
import sys
from huggingface_hub import snapshot_download
snapshot_download(sys.argv[2], revision=sys.argv[3], local_dir=sys.argv[1], ignore_patterns=["training/*"])
EOF
SHA42="$(sha "$WORK/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth")"
SHA43="$(sha "$WORK/checkpoints/ink_9um/hybrid_3d2d-seed43/step-075000.pth")"
SHAV8="$(sha "$V8IN/model.safetensors")"

INPUT="$ZARR"
AUC_CROP=(--level 2)   # never empty: bash 3.2 (macOS) treats an empty array as unset under set -u
if [[ "$SMOKE" == "1" ]]; then   # one small window only, to test the script end to end on any machine
  CROP=(4000 4256 2700 2956)
  INPUT="$WORK/data/w045_crop.zarr"
  "$PY" - "$ZARR" "$INPUT" "${CROP[@]}" <<'EOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
EOF
  AUC_CROP=(--level 2 --crop "${CROP[@]}" --surface-shape "${SURFACE[@]}")
fi
# v8in costs about 50x ink_9um per pixel, and AUC counts only supervised pixels, so by default
# v8in reads the box around the supervision mask (plus a 256 px margin), not the whole segment.
V8IN_AUC=("${AUC_CROP[@]}")
V8IN_CROP=()
if [[ "$SMOKE" != "1" && "${V8IN_REGION:-labels}" == "labels" ]]; then
  read -r -a V8IN_CROP <<< "$("$PY" - "$LAB/supervision.zarr" "${SURFACE[@]}" <<'EOF'
import sys, numpy as np, zarr
m = np.asarray(zarr.open(sys.argv[1], mode="r")["2"]) > 0
H, W = int(sys.argv[2]), int(sys.argv[3])
ys, xs = np.nonzero(m)
sy, sx = H / m.shape[0], W / m.shape[1]
pad = 256
print(max(0, int(ys.min() * sy) - pad), min(H, int((ys.max() + 1) * sy) + pad),
      max(0, int(xs.min() * sx) - pad), min(W, int((xs.max() + 1) * sx) + pad))
EOF
)"
  V8IN_AUC=(--level 2 --crop "${V8IN_CROP[@]}" --surface-shape "${SURFACE[@]}")
  echo "v8in region: rows ${V8IN_CROP[0]}-${V8IN_CROP[1]}, columns ${V8IN_CROP[2]}-${V8IN_CROP[3]}"
fi

say "3/7 ink_9um on $EXPECT_GPU (PR #$PR, $PR_SHA): seeds 42 and 43, both directions"
git -C "$VILLA" checkout -q --detach "pr-$PR"
for seed in 42 43; do
  log="$WORK/logs/w045_ink9um_s$seed.log"
  start=$SECONDS
  (cd "$WORK" && "$PY" -m vesuvius.ink_detection.inference.infer "$INPUT" \
     "$WORK/checkpoints/ink_9um/hybrid_3d2d-seed$seed/step-075000.pth" "$OUT/maps/ink9um_s$seed.tif" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) >"$log" 2>&1 \
    || { echo "ink_9um seed $seed failed, see $log" >&2; tail -20 "$log" >&2; exit 1; }
  printf -v "T_ink9um_s$seed" %s "$(( SECONDS - start ))"
  if [[ "$EXPECT_GPU" == "mps" ]]; then
    grep -q "Using MPS device" "$log" || { echo "seed $seed did not run on MPS; see $log" >&2; exit 1; }
  fi
  t="T_ink9um_s$seed"; echo "seed $seed: ${!t}s for both directions"
done
git -C "$VILLA" checkout -q --detach origin/main

say "4/7 layers for v8in (kit layers)"
cd "$SCROLLS"
rm -rf "$OUT/layers"
if [[ "$SMOKE" == "1" ]]; then
  "$PY" -m kit layers "$INPUT" "$OUT/layers"
elif (( ${#V8IN_CROP[@]} == 4 )); then
  "$PY" -m kit layers "$ZARR" "$OUT/layers" --crop "${V8IN_CROP[@]}"
else
  "$PY" -m kit layers "$ZARR" "$OUT/layers"
fi
rm -rf "$OUT/crop_layers"
"$PY" -m kit layers "$ZARR" "$OUT/crop_layers" --crop "${CROP[@]}"

v8in() {  # v8in NAME LAYERS DEVICE STRIDE fwd|rev [extra args]
  local name="$1" layers="$2" device="$3" stride="$4" dir="$5" start=$SECONDS
  shift 5
  local flags=(--stride "$stride" "$@")
  [[ "$dir" == "rev" ]] && flags+=(--reverse)
  "$PY" "$SCROLLS/scripts/v8in_run.py" --model-dir "$V8IN" --layers "$layers" --output "$OUT/maps/$name.npy" \
    --device "$device" "${flags[@]}" > "$WORK/logs/w045_$name.log" 2>&1 \
    || { echo "v8in $name failed, see $WORK/logs/w045_$name.log" >&2; tail -20 "$WORK/logs/w045_$name.log" >&2; exit 1; }
  "$PY" - "$OUT/maps/$name.npy" "$OUT/maps/$name.tif" <<'EOF'
import sys, numpy as np, tifffile
p = np.load(sys.argv[1])
tifffile.imwrite(sys.argv[2], np.round(np.clip(p, 0, 1) * 255).astype(np.uint8), compression="zlib")
EOF
  printf -v "T_$name" %s "$(( SECONDS - start ))"
}

say "5/7 v8in device check on a crop ($(( CROP[1] - CROP[0] )) px): CPU vs $V8IN_DEVICE, reverse as the control"
v8in crop_cpu "$OUT/crop_layers" cpu 64 fwd --batch-size "$BATCH"
v8in crop_gpu "$OUT/crop_layers" "$V8IN_DEVICE" 64 fwd "${FP16[@]}"
v8in crop_gpu_reverse "$OUT/crop_layers" "$V8IN_DEVICE" 64 rev "${FP16[@]}"
set +e
"$PY" -m kit verify "$OUT/maps/crop_cpu.tif" "$OUT/maps/crop_gpu.tif" --control "$OUT/maps/crop_gpu_reverse.tif" \
  --json > "$OUT/results/v8in_device.json"; VDEV=$?
set -e
[[ "$VDEV" == 0 || "$EXPECT_GPU" != "mps" ]] || { echo "v8in on MPS does not match the CPU${V8IN_FP16:+ (fp16 on: try again without V8IN_FP16)}; stopping before the full run" >&2; exit 1; }
echo "crop: cpu ${T_crop_cpu}s, $V8IN_DEVICE ${T_crop_gpu}s"

say "6/7 v8in over the segment on $V8IN_DEVICE, both directions"
STRIDE="${V8IN_STRIDE:-}"
if [[ -z "$STRIDE" && "$SMOKE" == "1" ]]; then
  STRIDE=64
elif [[ -z "$STRIDE" ]]; then   # pick the finest stride whose estimate fits V8IN_HOURS, from the measured speed
  STRIDE="$("$PY" - "$OUT/layers" "${T_crop_gpu}" "${V8IN_HOURS:-4}" "$V8IN" <<'EOF'
import sys
sys.path.insert(0, sys.argv[4])
import numpy as np, tifffile
from ink8um.inference import coverage_mask, tile_positions, list_layer_files
files = list_layer_files(sys.argv[1])[2:26]           # the central 24 of 28, as predict.py reads them
top = None
for f in files:
    a = tifffile.imread(f)
    top = a if top is None else np.maximum(top, a)
mask = coverage_mask(top[..., None])
per_tile = float(sys.argv[2]) / 100                    # the 640 px crop at stride 64 is 100 tiles
budget = float(sys.argv[3]) * 3600 / 2                 # two directions
for stride in (21, 32, 42, 64):
    n = len(tile_positions(mask, 64, stride))
    print(f"stride {stride}: {n} tiles, about {n * per_tile / 3600:.1f} h per direction", file=sys.stderr)
    if n * per_tile <= budget or stride == 64:
        print(stride)
        break
EOF
)"
fi
echo "stride $STRIDE"
v8in v8in "$OUT/layers" "$V8IN_DEVICE" "$STRIDE" fwd "${FP16[@]}"
v8in v8in_reverse "$OUT/layers" "$V8IN_DEVICE" "$STRIDE" rev "${FP16[@]}"
echo "v8in: ${T_v8in}s and ${T_v8in_reverse}s"

say "7/7 scores"
auc() {  # auc MAP CONTROL [crop args]
  local map="$1" control="$2"; shift 2
  "$PY" -m kit auc "$map" --control "$control" --labels "$LAB/inklabels.zarr" --mask "$LAB/supervision.zarr" "$@" --json
}
rows() { "$PY" -m kit rowscore "$@" --voxel-um 9.362 --json; }
M="$OUT/maps"
auc "$M/ink9um_s42.tif" "$M/ink9um_s42_reverse.tif" "${AUC_CROP[@]}" > "$OUT/results/auc_ink9um_s42.json"
auc "$M/ink9um_s43.tif" "$M/ink9um_s43_reverse.tif" "${AUC_CROP[@]}" > "$OUT/results/auc_ink9um_s43.json"
auc "$M/v8in.tif" "$M/v8in_reverse.tif" "${V8IN_AUC[@]}" > "$OUT/results/auc_v8in.json"
rows "$M/ink9um_s42.tif" "$M/ink9um_s43.tif" --reverse "$M/ink9um_s42_reverse.tif" "$M/ink9um_s43_reverse.tif" \
  > "$OUT/results/rows_ink9um.json"
rows "$M/v8in.tif" --reverse "$M/v8in_reverse.tif" > "$OUT/results/rows_v8in.json"

CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m)"
OS="$(sw_vers -productVersion 2>/dev/null || uname -sr)"
"$PY" - "$OUT/results" > "$OUT/results/summary.txt" <<EOF
import json, sys, pathlib
r = pathlib.Path(sys.argv[1])
j = lambda n: json.loads((r / f"{n}.json").read_text())
print("kit mac-w045 summary (paste this)")
print("chip: $CHIP | os: $OS | torch: $TORCH | smoke: $SMOKE")
print("villa PR #$PR $PR_SHA on $EXPECT_GPU | v8in $V8IN_REV on $V8IN_DEVICE, stride $STRIDE, batch $BATCH, fp16 ${V8IN_FP16:-0}, region ${V8IN_CROP[*]:-all}")
print("sha256 seed42 $SHA42 | seed43 $SHA43 | v8in $SHAV8")
print("times (s): ink_9um s42 ${T_ink9um_s42}, s43 ${T_ink9um_s43} (both directions) | v8in ${T_v8in} + ${T_v8in_reverse}")
d = j("v8in_device"); c = d["candidate"]
print(f"v8in cpu vs $V8IN_DEVICE (crop): {d['verdict']} | max|diff| {c.get('max_abs_diff')} | pearson {c.get('pearson')}")
for name in ("ink9um_s42", "ink9um_s43", "v8in"):
    a = j(f"auc_{name}")
    f, k = a["forward"], a["control"]
    print(f"AUC {name}: as stored {f['auc']} | reversed {k['auc']} | ink px {f['ink_px']}, background px {f['background_px']}")
for name in ("ink9um", "v8in"):
    s = j(f"rows_{name}")
    print(f"row score {name}: as stored {s['forward'].get('score')} | reversed {s['reverse'].get('score')}")
EOF
say "summary (also in $OUT/results/summary.txt)"
cat "$OUT/results/summary.txt"
