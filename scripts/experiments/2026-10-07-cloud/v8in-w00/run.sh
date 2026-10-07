#!/usr/bin/env bash
# Job v8in-w00 (scripts/experiments/2026-10-07-cloud/README.md): base v8in, ink_9um seed 42 and d9v2
# on the PHerc0841 w00 crop, CPU. Resumable: every step skips a map that already exists.
# Linux bash. Needs the shared setup (SMOKE=1 EXPECT_GPU=cpu WORK=$W SEGMENT=0841-w00 bash scripts/mac-w045.sh)
# and d9v2 at $W/models/d9v2/d9v2_ft-012000.pth.
set -euo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
W="${W:-$HOME/scrolls-work}"; PY=$W/venv/bin/python
SEG=0841-w00; CROP=(2624 3264 2688 3328)
O=$W/job-v8in-w00; M=$O/maps; mkdir -p "$M" "$O/logs"
V8IN=$W/checkpoints/ink-8um-v8in
D9V2=$W/models/d9v2/d9v2_ft-012000.pth
INK=$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth
T=$O/times.txt; touch "$T"
stamp() { echo "$1 $2" >> "$T"; echo "$(date -u +%H:%M:%S) $1 done in $2 s"; }

cd "$SCROLLS"
[[ -d $O/crop.zarr ]] || "$PY" - "$W/data/${SEG}_9um.zarr" "$O/crop.zarr" "${CROP[@]}" <<'PYEOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
PYEOF
[[ -f $O/layers.done ]] || { rm -rf "$O/layers"; "$PY" -m kit layers "$W/data/${SEG}_9um.zarr" "$O/layers" --crop "${CROP[@]}" && touch "$O/layers.done"; }
[[ -f $O/shuf.done ]] || { rm -rf "$O/layers_shuf"; "$PY" -m kit layers "$W/data/${SEG}_9um.zarr" "$O/layers_shuf" --crop "${CROP[@]}" --shuffle 20261007 && touch "$O/shuf.done"; }

v8in() {  # NAME LAYERS STRIDE [--reverse]
  local name=$1 layers=$2 stride=$3; shift 3
  [[ -f $M/$name.npy ]] && { echo "$name: exists"; return 0; }
  local s=$SECONDS
  "$PY" scripts/v8in_run.py --model-dir "$V8IN" --layers "$layers" --output "$M/$name.tmp.npy" \
    --device cpu --batch-size 4 --stride "$stride" "$@" > "$O/logs/$name.log" 2>&1
  mv "$M/$name.tmp.npy" "$M/$name.npy"
  stamp "$name" $(( SECONDS - s ))
}
villa() {  # NAME CKPT
  local name=$1 ck=$2
  [[ -f $M/$name.tif && -f $M/${name}_reverse.tif ]] && { echo "$name: exists"; return 0; }
  local s=$SECONDS
  git -C "$W/villa" checkout -q --detach pr-1865
  (cd "$W" && "$PY" -m vesuvius.ink_detection.inference.infer "$O/crop.zarr" "$ck" "$M/$name.tif" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) > "$O/logs/$name.log" 2>&1
  stamp "$name" $(( SECONDS - s ))
}

villa ink9um_s42 "$INK"
villa d9v2 "$D9V2"
v8in v8in_s42 "$O/layers" 42
v8in v8in_s42_reverse "$O/layers" 42 --reverse
v8in v8in_shuf_s42 "$O/layers_shuf" 42
v8in v8in_s21 "$O/layers" 21
echo "all maps done"
