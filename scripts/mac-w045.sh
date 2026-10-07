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
#   SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh   # the same test on PHerc0841, a scroll neither
#                                              # model saw (also 0841-ag896, 0841-ag405)
#   QUICK=1 bash scripts/mac-w045.sh           # under an hour: v8in on the 640 px crop only (densest
#                                              # labelled text), every model scored on that same crop
#   MODEL=v8in-1447 SEGMENT=0841-w00 QUICK=1 bash scripts/mac-w045.sh   # Youssef's PHerc1447 fine-tune
#   V8IN_HOURS=2 bash scripts/mac-w045.sh      # time budget for the full v8in pass (picks the stride)
#   V8IN_STRIDE=21 bash scripts/mac-w045.sh    # or set the stride (21 is v8in's own default)
#   V8IN_FP16=1 bash scripts/mac-w045.sh       # fp16 on MPS (about 1.4x), checked once against fp32 on the GPU
#   QUICK_REV_STRIDE=21 ...                    # reverse control at full density (default 42: 4x fewer tiles)
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
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WORK="${WORK:-$HOME/scrolls-work}"
VILLA="$WORK/villa"
PY="$WORK/venv/bin/python"
EXPECT_GPU="${EXPECT_GPU:-mps}"
SMOKE="${SMOKE:-0}"
QUICK="${QUICK:-0}"
PR=1865
# MODEL picks the v8in-architecture weights (same code, so the CPU vs MPS check carries over).
MODEL="${MODEL:-v8in}"
case "$MODEL" in
  v8in)        V8IN_REPO=YoussefMoNader/ink-8um-v8in
               V8IN_REV=d89166b41a3f5fad7749b3d7c0fdd1bd3695d844 ;;   # 2026-09-28 base model
  v8in-1447)   V8IN_REPO=YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062
               V8IN_REV=2bf9f421862cda0ed41dcae6e8274c12e295d03a ;;   # 2026-09-28 PHerc1447 fine-tune
  *) echo "MODEL must be v8in or v8in-1447" >&2; exit 2 ;;
esac
MTAG="${MODEL//-/}"                   # v8in, v8in1447: map, log and result names
V8IN="$WORK/checkpoints/${V8IN_REPO#*/}"
# SEGMENT picks the labelled test segment. CROP: 640 px fully on the surface with the densest
# labelled ink (y0 y1 x0 x1), found on the published labels. PHerc0841 is in neither model's
# training set (Bullo27's unseen-scroll calibration), so it is the harder test.
SEGMENT="${SEGMENT:-w045}"
case "$SEGMENT" in
  w045)
    SEG=PHerc0139/segments/20260126000000-w045_2026012619
    LABELS="$SEG/ink-labels/2.399um-volume-20260102150214/20260918"
    SV=w045; CROP=(3840 4480 2560 3200); SURFACE=(5980 8240); VOXEL=9.362 ;;
  0841-w00)
    SEG=PHerc0841/segments/20260220213127-w00
    CROP=(2624 3264 2688 3328); SURFACE=(4220 4760) ;;
  0841-ag896)
    SEG=PHerc0841/segments/20260220214732-auto_grown_20260220144552896
    CROP=(2496 3136 1600 2240); SURFACE=(4640 4720) ;;
  0841-ag405)
    SEG=PHerc0841/segments/20260221022814-auto_grown_20260220174252405
    CROP=(1024 1664 2496 3136); SURFACE=(3760 4900) ;;
  *) echo "SEGMENT must be w045, 0841-w00, 0841-ag896 or 0841-ag405" >&2; exit 2 ;;
esac
if [[ "$SEGMENT" == 0841-* ]]; then
  LABELS="$SEG/ink-labels/2.403um-volume-20260319124803/20260918"
  SV="$SEG/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr"; VOXEL=9.366
fi
NAME="$SEGMENT"                      # outputs and logs; data below is shared between modes
[[ "$SMOKE" == "1" ]] && NAME="${SEGMENT}-smoke"   # test maps never land where a real rerun would reuse them
ZARR="$WORK/data/${SEGMENT}_9um.zarr"
LAB="$WORK/data/${SEGMENT}_labels"
OUT="$WORK/$NAME"
FRESH="${FRESH:-0}"                  # 1: rerun everything; otherwise finished runs are reused (see below)

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
FP16_ON=0
[[ "${V8IN_FP16:-0}" == "1" && "$V8IN_DEVICE" == "mps" ]] && { FP16+=(--fp16); FP16_ON=1; }
echo "memory ${MEM_GB} GB: v8in batch $BATCH${V8IN_FP16:+, fp16 $V8IN_FP16}"

say "2/7 data: $SEGMENT surface volume (0.6 to 1.7 GB), its labels, three checkpoints"
(cd "$SCROLLS" && "$PY" -m kit fetch "$SV" "$ZARR")
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
  CROP=($(( CROP[0] + 160 )) $(( CROP[0] + 416 )) $(( CROP[2] + 140 )) $(( CROP[2] + 396 )))   # 256 px inside the crop
  INPUT="$WORK/data/${SEGMENT}_crop.zarr"
  "$PY" - "$ZARR" "$INPUT" "${CROP[@]}" <<'EOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
EOF
  AUC_CROP=(--level 2 --crop "${CROP[@]}" --surface-shape "${SURFACE[@]}")
elif [[ "$QUICK" == "1" ]]; then   # every quick score is on the crop, so ink_9um reads only the crop too
  INPUT="$WORK/data/${SEGMENT}_quickcrop_${CROP[0]}_${CROP[2]}.zarr"
  [[ -d "$INPUT" && "$FRESH" != 1 ]] || "$PY" - "$ZARR" "$INPUT" "${CROP[@]}" <<'EOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
EOF
  AUC_CROP=(--level 2 --crop "${CROP[@]}" --surface-shape "${SURFACE[@]}")
fi
INK=ink9um; [[ "$QUICK" == "1" ]] && INK=ink9um_quick   # crop-only maps are never reused by a full run
# v8in costs about 50x ink_9um per pixel, and AUC counts only supervised pixels, so by default
# v8in reads the box around the supervision mask (plus a 256 px margin), not the whole segment.
V8IN_AUC=("${AUC_CROP[@]}")
V8IN_CROP=()
if [[ "$SMOKE" != "1" && "$QUICK" != "1" && "${V8IN_REGION:-labels}" == "labels" ]]; then
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
  log="$WORK/logs/${NAME}_${INK}_s$seed.log"
  start=$SECONDS
  # Reuse a finished seed: both maps present, and on a Mac its log shows it ran on MPS.
  if [[ "$FRESH" != "1" && -f "$OUT/maps/${INK}_s$seed.tif" && -f "$OUT/maps/${INK}_s${seed}_reverse.tif" && -f "$log" ]] \
     && { [[ "$EXPECT_GPU" != "mps" ]] || grep -q "Using MPS device" "$log"; }; then
    printf -v "T_ink9um_s$seed" %s "earlier"
    echo "seed $seed: finished in an earlier run, reused (FRESH=1 to redo)"
    continue
  fi
  (cd "$WORK" && "$PY" -m vesuvius.ink_detection.inference.infer "$INPUT" \
     "$WORK/checkpoints/ink_9um/hybrid_3d2d-seed$seed/step-075000.pth" "$OUT/maps/${INK}_s$seed.tif" \
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
if [[ "$QUICK" == "1" ]]; then
  echo "quick: only the crop is exported"
elif [[ "$SMOKE" == "1" ]]; then
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
  # Reuse a finished pass: its map exists and its log's last line names the same device, fp16,
  # direction and stride (v8in_run.py writes "device=... fp16=... reverse=... stride=... done in Ns").
  local log="$WORK/logs/${NAME}_$name.log" fp16=False reverse=False
  [[ " ${flags[*]} " == *" --fp16 "* ]] && fp16=True
  [[ "$dir" == "rev" ]] && reverse=True
  if [[ "$FRESH" != "1" && -f "$OUT/maps/$name.tif" && -f "$log" ]] \
     && grep -q "^device=$device fp16=$fp16 reverse=$reverse stride=$stride .*done in [0-9]*s" "$log"; then
    printf -v "T_$name" %s "$(sed -n 's/.*done in \([0-9]*\)s.*/\1/p' "$log" | tail -1)"
    echo "v8in $name: finished in an earlier run, reused (FRESH=1 to redo)"
    return 0
  fi
  "$PY" "$SCROLLS/scripts/v8in_run.py" --model-dir "$V8IN" --layers "$layers" --output "$OUT/maps/$name.npy" \
    --device "$device" "${flags[@]}" > "$WORK/logs/${NAME}_$name.log" 2>&1 \
    || { echo "v8in $name failed, see $WORK/logs/${NAME}_$name.log" >&2; tail -20 "$WORK/logs/${NAME}_$name.log" >&2; exit 1; }
  "$PY" - "$OUT/maps/$name.npy" "$OUT/maps/$name.tif" <<'EOF'
import sys, numpy as np, tifffile
p = np.load(sys.argv[1])
tifffile.imwrite(sys.argv[2], np.round(np.clip(p, 0, 1) * 255).astype(np.uint8), compression="zlib")
EOF
  printf -v "T_$name" %s "$(( SECONDS - start ))"
}

DEV=crop; DEVJSON=v8in_device       # base v8in keeps its original names (mac-atlas-v8in.sh reads them)
[[ "$MODEL" != v8in ]] && { DEV="${MTAG}_crop"; DEVJSON="${MTAG}_device"; }
[[ "$FP16_ON" == 1 ]] && DEVJSON="${DEVJSON}_fp16"
CROP_LOG="$WORK/logs/${NAME}_${DEV}_gpu.log"   # per-tile speed for the stride estimate
W045_DEVICE="$WORK/w045/results/v8in_device.json"
[[ "$FP16_ON" == 1 ]] && W045_DEVICE="$WORK/w045/results/v8in_device_fp16.json"
passed() { "$PY" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["verdict"] == "pass" else 1)' "$1" 2>/dev/null; }
# The device check answers one question (does v8in on this Mac's GPU give the CPU's map?), so other
# segments and models reuse w045's pass rather than spend another CPU pass (40 min on an M1 Pro).
# fp16 is checked once against fp32 on the GPU, which w045's pass already tied to the CPU.
# DEVICE_CHECK=1 forces a fresh check.
if [[ ( "$SEGMENT" != w045 || "$MODEL" != v8in ) && "${DEVICE_CHECK:-0}" != 1 && "$FRESH" != 1 && "$SMOKE" != 1 ]] \
   && passed "$W045_DEVICE"; then
  say "5/7 v8in device check: reusing the pass from w045 (DEVICE_CHECK=1 to redo it here)"
  [[ "$W045_DEVICE" -ef "$OUT/results/$DEVJSON.json" ]] || cp "$W045_DEVICE" "$OUT/results/$DEVJSON.json"
  CROP_LOG="$WORK/logs/w045_crop_gpu.log"
  T_crop_cpu="w045"; T_crop_gpu="w045"
elif [[ "$FP16_ON" == 1 ]]; then
  say "5/7 fp16 check on a crop: $V8IN_DEVICE fp16 against $V8IN_DEVICE fp32, reverse fp16 as the control"
  [[ "$SMOKE" == 1 ]] || passed "$WORK/w045/results/v8in_device.json" \
    || { echo "Run once without V8IN_FP16 first: fp16 is checked against fp32, which must first match the CPU." >&2; exit 2; }
  v8in "${DEV}_gpu" "$OUT/crop_layers" "$V8IN_DEVICE" 64 fwd --batch-size "$BATCH"
  v8in "${DEV}_gpu_fp16" "$OUT/crop_layers" "$V8IN_DEVICE" 64 fwd "${FP16[@]}"
  v8in "${DEV}_gpu_fp16_reverse" "$OUT/crop_layers" "$V8IN_DEVICE" 64 rev "${FP16[@]}"
  t="T_${DEV}_gpu"; T_crop_cpu="fp32 ${!t}"; t="T_${DEV}_gpu_fp16"; T_crop_gpu="${!t}"
  CROP_LOG="$WORK/logs/${NAME}_${DEV}_gpu_fp16.log"
  set +e
  "$PY" -m kit verify "$OUT/maps/${DEV}_gpu.tif" "$OUT/maps/${DEV}_gpu_fp16.tif" --control "$OUT/maps/${DEV}_gpu_fp16_reverse.tif" \
    --json > "$OUT/results/$DEVJSON.json"; VDEV=$?
  set -e
  [[ "$VDEV" == 0 ]] || { echo "v8in fp16 does not match fp32 on $V8IN_DEVICE; run without V8IN_FP16" >&2; exit 1; }
  echo "crop: fp32 ${T_crop_cpu#fp32 }s, fp16 ${T_crop_gpu}s"
else
say "5/7 v8in device check on a crop ($(( CROP[1] - CROP[0] )) px): CPU vs $V8IN_DEVICE, reverse as the control"
v8in "${DEV}_cpu" "$OUT/crop_layers" cpu 64 fwd --batch-size "$BATCH"
v8in "${DEV}_gpu" "$OUT/crop_layers" "$V8IN_DEVICE" 64 fwd "${FP16[@]}"
v8in "${DEV}_gpu_reverse" "$OUT/crop_layers" "$V8IN_DEVICE" 64 rev "${FP16[@]}"
t="T_${DEV}_cpu"; T_crop_cpu="${!t}"; t="T_${DEV}_gpu"; T_crop_gpu="${!t}"
set +e
"$PY" -m kit verify "$OUT/maps/${DEV}_cpu.tif" "$OUT/maps/${DEV}_gpu.tif" --control "$OUT/maps/${DEV}_gpu_reverse.tif" \
  --json > "$OUT/results/$DEVJSON.json"; VDEV=$?
set -e
[[ "$VDEV" == 0 || "$EXPECT_GPU" != "mps" ]] || { echo "v8in on MPS does not match the CPU${V8IN_FP16:+ (fp16 on: try again without V8IN_FP16)}; stopping before the full run" >&2; exit 1; }
echo "crop: cpu ${T_crop_cpu}s, $V8IN_DEVICE ${T_crop_gpu}s"
fi

V8IN_MAP="$MTAG"
INK_AUC=("${AUC_CROP[@]}")   # where ink_9um maps are scored; QUICK narrows it to the crop
STRIDE="${V8IN_STRIDE:-}"
if [[ "$QUICK" == "1" ]]; then
  say "6/7 quick: v8in on the crop on $V8IN_DEVICE at full density, both directions"
  STRIDE="${STRIDE:-21}"
  V8IN_MAP="${MTAG}_quick"   # its own name, so a later full run never reuses a crop-only map
  v8in "${MTAG}_quick" "$OUT/crop_layers" "$V8IN_DEVICE" "$STRIDE" fwd "${FP16[@]}"
  REV_STRIDE="${QUICK_REV_STRIDE:-42}"   # the control only has to show that flipped depth reads no ink
  v8in "${MTAG}_quick_reverse" "$OUT/crop_layers" "$V8IN_DEVICE" "$REV_STRIDE" rev "${FP16[@]}"
  t="T_${MTAG}_quick"; T_v8in="${!t}"; t="T_${MTAG}_quick_reverse"; T_v8in_reverse="${!t}"
  echo "v8in: ${T_v8in}s and ${T_v8in_reverse}s"
  V8IN_AUC=(--level 2 --crop "${CROP[@]}" --surface-shape "${SURFACE[@]}" --inner 64)
  INK_AUC=("${V8IN_AUC[@]}")
else
say "6/7 v8in over the segment on $V8IN_DEVICE, both directions"
if [[ -z "$STRIDE" && "$SMOKE" == "1" ]]; then
  STRIDE=64
elif [[ -z "$STRIDE" ]]; then   # pick the finest stride whose estimate fits V8IN_HOURS, from the measured speed
  STRIDE="$("$PY" - "$OUT/layers" "$CROP_LOG" "${V8IN_HOURS:-4}" "$V8IN" <<'EOF'
import re, sys
sys.path.insert(0, sys.argv[4])
import numpy as np, tifffile
from ink8um.inference import coverage_mask, tile_positions, list_layer_files
files = list_layer_files(sys.argv[1])[2:26]           # the central 24 of 28, as predict.py reads them
top = None
for f in files:
    a = tifffile.imread(f)
    top = a if top is None else np.maximum(top, a)
mask = coverage_mask(top[..., None])
m = re.search(r"tiles=(\d+) done in (\d+)s", open(sys.argv[2]).read())   # the crop run on the GPU
per_tile = float(m.group(2)) / int(m.group(1))
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
v8in "$MTAG" "$OUT/layers" "$V8IN_DEVICE" "$STRIDE" fwd "${FP16[@]}"
v8in "${MTAG}_reverse" "$OUT/layers" "$V8IN_DEVICE" "$STRIDE" rev "${FP16[@]}"
t="T_$MTAG"; T_v8in="${!t}"; t="T_${MTAG}_reverse"; T_v8in_reverse="${!t}"
echo "v8in: ${T_v8in}s and ${T_v8in_reverse}s"
fi

say "7/7 scores"
auc() {  # auc MAP CONTROL [crop args]
  local map="$1" control="$2"; shift 2
  "$PY" -m kit auc "$map" --control "$control" --labels "$LAB/inklabels.zarr" --mask "$LAB/supervision.zarr" "$@" --json
}
rows() { "$PY" -m kit rowscore "$@" --voxel-um "$VOXEL" --json; }
M="$OUT/maps"
for seed in 42 43; do
  auc "$M/${INK}_s$seed.tif" "$M/${INK}_s${seed}_reverse.tif" "${INK_AUC[@]}" > "$OUT/results/auc_ink9um_s$seed.json"
done
auc "$M/$V8IN_MAP.tif" "$M/${V8IN_MAP}_reverse.tif" "${V8IN_AUC[@]}" > "$OUT/results/auc_$MTAG.json"
rows "$M/${INK}_s42.tif" "$M/${INK}_s43.tif" --reverse "$M/${INK}_s42_reverse.tif" "$M/${INK}_s43_reverse.tif" \
  > "$OUT/results/rows_ink9um.json"
rows "$M/$V8IN_MAP.tif" --reverse "$M/${V8IN_MAP}_reverse.tif" > "$OUT/results/rows_$MTAG.json"

CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m)"
OS="$(sw_vers -productVersion 2>/dev/null || uname -sr)"
"$PY" - "$OUT/results" > "$OUT/results/summary.txt" <<EOF
import json, sys, pathlib
r = pathlib.Path(sys.argv[1])
j = lambda n: json.loads((r / f"{n}.json").read_text())
print("kit mac-w045 summary for $SEGMENT (paste this)")
print("chip: $CHIP | os: $OS | torch: $TORCH | smoke: $SMOKE | quick: $QUICK")
if "$QUICK" == "1":
    print("quick: every AUC below is on the crop ${CROP[*]} (rows, columns) less a 64 px edge, so the models face the same test")
    print("quick: row scores need about 1 cm of map, so the crop has none")
print(f"villa PR #$PR $PR_SHA on $EXPECT_GPU | $MODEL $V8IN_REV on $V8IN_DEVICE, stride $STRIDE (reverse ${REV_STRIDE:-$STRIDE}), batch $BATCH, fp16 ${V8IN_FP16:-0}, region {'crop' if '$QUICK' == '1' else '${V8IN_CROP[*]:-all}'}")
print("sha256 seed42 $SHA42 | seed43 $SHA43 | v8in $SHAV8")
print("times (s): ink_9um s42 ${T_ink9um_s42}, s43 ${T_ink9um_s43} (both directions) | v8in ${T_v8in} + ${T_v8in_reverse}")
d = j("$DEVJSON"); c = d["candidate"]
print(f"v8in cpu vs $V8IN_DEVICE (crop): {d['verdict']} | max|diff| {c.get('max_abs_diff')} | pearson {c.get('pearson')}")
for name in ("ink9um_s42", "ink9um_s43", "$MTAG"):
    a = j(f"auc_{name}")
    f, k = a["forward"], a["control"]
    print(f"AUC {name}: as stored {f['auc']} | reversed {k['auc']} | ink px {f['ink_px']}, background px {f['background_px']}")
for name in ("ink9um", "$MTAG"):
    s = j(f"rows_{name}")
    print(f"row score {name}: as stored {s['forward'].get('score')} | reversed {s['reverse'].get('score')}")
EOF
# Provenance: who ran it, when, on which machine, from which code, models, inputs and outputs, as
# a record and one digest (kit provenance). The digest alone can be published or committed as a
# timestamped commitment; it reveals nothing, and the record proves it later.
PROV=(--model "$WORK/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"
      --model "$WORK/checkpoints/ink_9um/hybrid_3d2d-seed43/step-075000.pth"
      --model "$V8IN/model.safetensors"
      --input "$ZARR" --input "$LAB/inklabels.zarr" --input "$LAB/supervision.zarr")
for f in "$M/${INK}_s42.tif" "$M/${INK}_s42_reverse.tif" "$M/${INK}_s43.tif" "$M/${INK}_s43_reverse.tif" \
         "$M/$V8IN_MAP.tif" "$M/${V8IN_MAP}_reverse.tif" "$OUT/results"/*.json "$OUT/results/summary.txt"; do
  [[ -f "$f" && "$f" != "$OUT/results/provenance.json" ]] && PROV+=(--output "$f")
done
"$PY" -m kit provenance write "$OUT/results/provenance.json" --run "mac-w045 $SEGMENT $MODEL quick=$QUICK smoke=$SMOKE" \
  --repo "$SCROLLS" --code-repo "$VILLA" --started "$STARTED_UTC" "${PROV[@]}" > "$OUT/results/provenance.digest"
say "summary (also in $OUT/results/summary.txt)"
cat "$OUT/results/summary.txt"
echo "provenance: $(cat "$OUT/results/provenance.digest")"
