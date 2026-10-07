#!/usr/bin/env bash
# Lane D evaluation: kit fibertensor (structure-tensor features + tiny MLP) against the
# brightness-only ablation (same learner, --kind raw), cross-surface on PHerc0841.
# Train on one surface's crop, predict another's; w00 and ag896 are one sheet traced twice,
# so the independent pairs are (w00 or ag896) <-> ag405.
#   DATA=/path/with/0841-<seg>_9um.zarr and 0841-<seg>_labels  PY=python  bash run.sh OUT
set -euo pipefail
OUT="${1:?output dir}"; DATA="${DATA:?}"; PY="${PY:-python3}"
mkdir -p "$OUT"
crop() { case "$1" in w00) echo "2624 3264 2688 3328";; ag896) echo "2496 3136 1600 2240";; ag405) echo "1024 1664 2496 3136";; esac; }
shape() { case "$1" in w00) echo "4220 4760";; ag896) echo "4640 4720";; ag405) echo "3760 4900";; esac; }
PAIRS="${PAIRS:-w00:ag405 ag405:w00 ag405:ag896 w00:ag896}"
for pair in $PAIRS; do
  tr="${pair%%:*}"; te="${pair##*:}"
  for kind in fibre raw; do
    m="$OUT/model_${kind}_${tr}.npz"
    [[ -f "$m" ]] || $PY -m kit fibertensor train "$DATA/0841-${tr}_9um.zarr" "$DATA/0841-${tr}_labels" \
        --crop $(crop "$tr") --surface-shape $(shape "$tr") --kind "$kind" -o "$m" > "$m.json"
    for dir in fwd rev; do
      flag=""; [[ "$dir" == rev ]] && flag="--reverse"
      $PY -m kit fibertensor predict "$m" "$DATA/0841-${te}_9um.zarr" --crop $(crop "$te") $flag \
          -o "$OUT/map_${kind}_${tr}_to_${te}_${dir}.tif" > /dev/null
    done
  done
  L="$DATA/0841-${te}_labels"
  $PY -m kit auc "$OUT/map_fibre_${tr}_to_${te}_fwd.tif" --control "$OUT/map_fibre_${tr}_to_${te}_rev.tif" \
      --labels "$L/inklabels.zarr" --mask "$L/supervision.zarr" --crop $(crop "$te") --surface-shape $(shape "$te") \
      --inner 64 --bootstrap 300 --compare "$OUT/map_raw_${tr}_to_${te}_fwd.tif" --json > "$OUT/auc_${tr}_to_${te}.json"
  $PY -m kit auc "$OUT/map_raw_${tr}_to_${te}_fwd.tif" --control "$OUT/map_raw_${tr}_to_${te}_rev.tif" \
      --labels "$L/inklabels.zarr" --mask "$L/supervision.zarr" --crop $(crop "$te") --surface-shape $(shape "$te") \
      --inner 64 --bootstrap 300 --json > "$OUT/auc_raw_${tr}_to_${te}.json"
  echo "done $tr -> $te"
done
