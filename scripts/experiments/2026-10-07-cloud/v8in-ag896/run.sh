#!/usr/bin/env bash
# Job v8in-ag896 (scripts/experiments/2026-10-07-cloud/README.md): base v8in on the PHerc0841 ag896 crop,
# CPU. Resumable: every map that already exists is skipped. Run after the shared SMOKE setup:
#   SMOKE=1 EXPECT_GPU=cpu WORK=$W SEGMENT=0841-ag896 bash scripts/mac-w045.sh
#   nohup bash scripts/experiments/2026-10-07-cloud/v8in-ag896/run.sh > $W/logs/v8in-ag896.log 2>&1 &
# Linux bash (not meant for macOS bash 3.2). Maps stay in $W/job-v8in-ag896, never in git.
set -euo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
W="${W:-$HOME/scrolls-work}"
PY="$W/venv/bin/python"
SEG=0841-ag896
CROP=(2496 3136 1600 2240)
ZARR="$W/data/${SEG}_9um.zarr"
V8IN="$W/checkpoints/ink-8um-v8in"
D9V2="$W/checkpoints/d9v2/d9v2_ft-012000.pth"
INK42="$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"
J="$W/job-v8in-ag896"
M="$J/maps"; L="$J/logs"
mkdir -p "$M" "$L"
cd "$SCROLLS"

# Inputs: crop layers (v8in), depth-shuffled crop layers (control), crop zarr (villa).
[[ -f "$J/layers/27.tif" ]] || "$PY" -m kit layers "$ZARR" "$J/layers" --crop "${CROP[@]}"
[[ -f "$J/layers_shuf/27.tif" ]] || "$PY" -m kit layers "$ZARR" "$J/layers_shuf" --crop "${CROP[@]}" --shuffle 20261007 \
  | tee "$J/shuffle_order.txt"
[[ -d "$J/crop.zarr" ]] || "$PY" - "$ZARR" "$J/crop.zarr" "${CROP[@]}" <<'EOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
EOF

villa() {  # villa NAME CKPT: both directions on the crop zarr
  local name="$1" ck="$2" t=$SECONDS
  if [[ -f "$M/$name.tif" && -f "$M/${name}_reverse.tif" ]]; then echo "$name: exists"; return 0; fi
  git -C "$W/villa" checkout -q --detach pr-1865
  (cd "$W" && "$PY" -m vesuvius.ink_detection.inference.infer "$J/crop.zarr" "$ck" "$M/$name.tif" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) > "$L/$name.log" 2>&1
  echo "$name: $(( SECONDS - t )) s (both directions)" | tee -a "$J/times.txt"
}

v8in() {  # v8in NAME LAYERS STRIDE [--reverse]
  local name="$1" layers="$2" stride="$3" t=$SECONDS
  shift 3
  if [[ -f "$M/$name.npy" ]]; then echo "$name: exists"; return 0; fi
  "$PY" "$SCROLLS/scripts/v8in_run.py" --model-dir "$V8IN" --layers "$layers" --output "$M/$name.tmp.npy" \
    --device cpu --batch-size 4 --stride "$stride" "$@" > "$L/$name.log" 2>&1
  mv "$M/$name.tmp.npy" "$M/$name.npy"
  echo "$name: $(( SECONDS - t )) s ($(tail -1 "$L/$name.log"))" | tee -a "$J/times.txt"
}

score_results() {
  W="$W" "$PY" "$SCROLLS/scripts/experiments/2026-10-07-cloud/v8in-ag896/score.py"
}

# Cheapest first, so partial results land early; one inference at a time.
villa ink9um_s42 "$INK42"
score_results
villa d9v2 "$D9V2"
score_results
# Budget cut by the coordinating session (2026-10-07): forward stride 42 is the main map,
# reverse and depth-shuffled controls at stride 64; no stride 21 run.
v8in v8in_s42 "$J/layers" 42
score_results
v8in v8in_s64_reverse "$J/layers" 64 --reverse
score_results
v8in v8in_shuf_s64 "$J/layers_shuf" 64
score_results
echo "all maps done"
