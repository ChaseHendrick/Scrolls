#!/usr/bin/env bash
# Cloud job v8in1447-ag405 (CPU): v8in-1447 (Youssef's PHerc1447 fine-tune) on the PHerc0841 ag405
# crop, forward stride 21, reverse stride 42, forward stride 42; d9v2 on the same crop (villa, both
# directions); ensembles v8in-1447 + d9v2 (mean and rank, reverse ensembled the same way); AUC and
# hp_r for every map. Resumable: a map that exists is not recomputed.
#
#   nohup bash scripts/experiments/2026-10-07-cloud/v8in1447-ag405/run.sh > $W/logs/job.log 2>&1 &
#
# Needs the shared setup first (SMOKE=1 ... MODEL=v8in-1447 bash scripts/mac-w045.sh) and
# $W/checkpoints/d9v2/d9v2_ft-012000.pth (v1.0 release of TAUIL-Abd-Elilah/pherc0826-first-letters-search).
set -euo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${W:-$HOME/scrolls-work}"
PY="$W/venv/bin/python"
SEG=0841-ag405
CROP=(1024 1664 2496 3136); SURFACE=(3760 4900); VOXEL=9.366
V8IN="$W/checkpoints/ink-8um-v8in-pherc1447-loo-w062"
D9V2="$W/checkpoints/d9v2/d9v2_ft-012000.pth"
LAB="$W/data/${SEG}_labels"
J="$W/job-v8in1447-ag405"; M="$J/maps"; L="$J/logs"; S="$HERE/scores"
mkdir -p "$M" "$L" "$S"
cd "$SCROLLS"

# Inputs: crop zarr for villa, crop layers for v8in.
ZC="$J/${SEG}_crop.zarr"
[[ -d "$ZC" ]] || "$PY" - "$W/data/${SEG}_9um.zarr" "$ZC" "${CROP[@]}" <<'EOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
EOF
[[ -f "$J/layers.done" ]] || { rm -rf "$J/layers"; "$PY" -m kit layers "$W/data/${SEG}_9um.zarr" "$J/layers" --crop "${CROP[@]}" && touch "$J/layers.done"; }

score() {  # score NAME MAP [CONTROL]: AUC and hp_r on the crop, 64 px edge left out
  local name="$1" map="$2" ctl="${3:-}" c=()
  [[ -n "$ctl" ]] && c=(--control "$ctl")
  "$PY" -m kit auc "$map" "${c[@]}" --labels "$LAB/inklabels.zarr" --mask "$LAB/supervision.zarr" --level 2 \
    --crop "${CROP[@]}" --surface-shape "${SURFACE[@]}" --inner 64 --json > "$S/auc_$name.json"
  "$PY" -m kit hpscore "$map" "${c[@]}" --labels "$LAB/inklabels.zarr" --mask "$LAB/supervision.zarr" --level 2 \
    --crop "${CROP[@]}" --surface-shape "${SURFACE[@]}" --inner 64 --voxel-um "$VOXEL" --json > "$S/hp_$name.json"
  echo "scored $name"
}

v8in() {  # v8in NAME STRIDE fwd|rev
  local name="$1" stride="$2" dir="$3" flags=()
  [[ "$dir" == rev ]] && flags+=(--reverse)
  [[ -f "$M/$name.npy" ]] && { echo "$name: exists"; return 0; }
  "$PY" scripts/v8in_run.py --model-dir "$V8IN" --layers "$J/layers" --output "$M/$name.tmp.npy" \
    --device cpu --batch-size 4 --stride "$stride" "${flags[@]}" > "$L/$name.log" 2>&1
  mv "$M/$name.tmp.npy" "$M/$name.npy"
  tail -1 "$L/$name.log"
}

villa() {  # villa NAME CKPT: both directions on the crop zarr
  local name="$1" ck="$2" t=$SECONDS
  [[ -f "$M/$name.tif" && -f "$M/${name}_reverse.tif" ]] && { echo "$name: exists"; return 0; }
  git -C "$W/villa" checkout -q --detach pr-1865
  (cd "$W" && "$PY" -m vesuvius.ink_detection.inference.infer "$ZC" "$ck" "$M/$name.tif" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) > "$L/$name.log" 2>&1
  git -C "$W/villa" checkout -q --detach origin/main
  echo "$name: done in $(( SECONDS - t ))s" | tee -a "$L/$name.log"
}

villa d9v2 "$D9V2"
score d9v2 "$M/d9v2.tif" "$M/d9v2_reverse.tif"

v8in v8in1447_s42 42 fwd
v8in v8in1447_s42_reverse 42 rev
score v8in1447_s42 "$M/v8in1447_s42.npy" "$M/v8in1447_s42_reverse.npy"

v8in v8in1447_s21 21 fwd
score v8in1447_s21 "$M/v8in1447_s21.npy" "$M/v8in1447_s42_reverse.npy"

for method in mean rank; do
  e="$M/ens_v8in1447_d9v2_$method"
  "$PY" -m kit ensemble "$e.npy" "$M/v8in1447_s21.npy" "$M/d9v2.tif" --method "$method" > /dev/null
  "$PY" -m kit ensemble "${e}_reverse.npy" "$M/v8in1447_s42_reverse.npy" "$M/d9v2_reverse.tif" --method "$method" > /dev/null
  score "ens_v8in1447_d9v2_$method" "$e.npy" "${e}_reverse.npy"
done
echo "ALL DONE"
