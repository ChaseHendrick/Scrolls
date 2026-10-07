#!/usr/bin/env bash
# Job v8in1447-ag896 (scripts/experiments/2026-10-07-cloud/README.md): v8in-1447 on the PHerc0841
# ag896 crop (forward s21, reverse s42, forward s42), d9v2 on the same crop (villa, both
# directions), then ensembles v8in-1447 + d9v2 (mean and rank). Resumable: finished outputs are
# skipped. Needs the SMOKE setup of the README first (venv, villa pr-1865, checkpoints, data).
#   nohup bash run.sh > $W/job.log 2>&1 &
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCROLLS="$(cd "$HERE/../../../.." && pwd)"
W="${W:-$HOME/scrolls-work}"
PY=$W/venv/bin/python
SEG=0841-ag896
CROP=(2496 3136 1600 2240)
ZARR=$W/data/${SEG}_9um.zarr
J=$W/job-v8in1447-ag896
V8=$W/checkpoints/ink-8um-v8in-pherc1447-loo-w062
D9=$W/models/d9v2/d9v2_ft-012000.pth
mkdir -p $J/maps $J/logs
cd "$SCROLLS"

if [[ ! -f $J/crop_layers/.done ]]; then
  rm -rf $J/crop_layers
  $PY -m kit layers $ZARR $J/crop_layers --crop "${CROP[@]}"
  touch $J/crop_layers/.done
fi

v8() {  # v8 NAME STRIDE fwd|rev
  local name=$1 stride=$2 dir=$3 flags=()
  [[ $dir == rev ]] && flags=(--reverse)
  if [[ -f $J/maps/$name.npy ]] && grep -q "done in" $J/logs/$name.log 2>/dev/null; then
    echo "$name: done earlier"; return 0
  fi
  echo "$name: start $(date -u +%H:%M:%S)"
  $PY scripts/v8in_run.py --model-dir $V8 --layers $J/crop_layers --output $J/maps/$name.npy \
    --device cpu --batch-size 4 --stride $stride "${flags[@]}" > $J/logs/$name.log 2>&1
  tail -1 $J/logs/$name.log
}

# d9v2 first (minutes), so the pipeline is checked against the bar before the long v8in runs.
if [[ ! -d $J/crop.zarr ]]; then
  $PY - $ZARR $J/crop.zarr "${CROP[@]}" <<'PYEOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
PYEOF
fi
if [[ ! -f $J/maps/d9v2_reverse.tif ]]; then
  git -C $W/villa checkout -q --detach pr-1865
  t=$SECONDS
  (cd $W && $PY -m vesuvius.ink_detection.inference.infer $J/crop.zarr $D9 $J/maps/d9v2.tif \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) > $J/logs/d9v2.log 2>&1
  echo "d9v2 done in $((SECONDS - t))s" | tee -a $J/logs/d9v2.log
fi
$PY "$HERE/score.py" $J > "$HERE/results.json" || true

v8 v8in1447_fwd_s42 42 fwd
$PY "$HERE/score.py" $J > "$HERE/results.json" || true
v8 v8in1447_rev_s42 42 rev
$PY "$HERE/score.py" $J > "$HERE/results.json" || true
v8 v8in1447_fwd_s21 21 fwd

for m in mean rank; do
  $PY -m kit ensemble $J/maps/ens_v8in1447_d9v2_$m.npy $J/maps/v8in1447_fwd_s21.npy $J/maps/d9v2.tif --method $m
  $PY -m kit ensemble $J/maps/ens_v8in1447_d9v2_${m}_reverse.npy $J/maps/v8in1447_rev_s42.npy $J/maps/d9v2_reverse.tif --method $m
done
$PY "$HERE/score.py" $J > "$HERE/results.json"
echo "all done $(date -u +%H:%M:%S)"
