#!/usr/bin/env bash
# Lane D on the Mac's data (~/scrolls-work): kit fibertensor, cross-scroll.
# Train on one labelled crop, predict the other: PHerc0139 w045 <-> PHerc0841 w00, and
# within PHerc0841 w00 from a disjoint labelled window (w00train, 192 px above the crop,
# the densest-labelled 640 px window not within 64 px of it).
# Each forward map is scored with kit auc (reverse-depth control, 64 px edge left out,
# 300 block-bootstrap draws) and compared on the same pixels with the brightness-only
# ablation (--kind raw, same learner) and with ink_9um seed 42 on the same crop.
#   WORK=~/scrolls-work PY=~/scrolls-work/venv/bin/python bash run_mac.sh OUT
set -euo pipefail
OUT="${1:?output dir}"; WORK="${WORK:-$HOME/scrolls-work}"; PY="${PY:-$WORK/venv/bin/python}"
mkdir -p "$OUT"
vol() { case "$1" in w00|w00train) echo "$WORK/data/0841-w00_9um.zarr";; w045) echo "$WORK/data/w045_9um.zarr";; esac; }
lab() { case "$1" in w00|w00train) echo "$WORK/data/0841-w00_labels";; w045) echo "$WORK/data/w045_labels";; esac; }
crop() { case "$1" in w00) echo "2624 3264 2688 3328";; w00train) echo "1792 2432 2944 3584";; w045) echo "3840 4480 2560 3200";; esac; }
shape() { case "$1" in w00|w00train) echo "4220 4760";; w045) echo "5980 8240";; esac; }
ink9() { case "$1" in w00) echo "$WORK/0841-w00/maps/ink9um_quick_s42.tif";; w045) echo "$WORK/w045/maps/ink9um_s42_crop.tif";; esac; }
score() {  # map control labels-seg out [compare]
  local cmp=""; [[ -n "${5:-}" ]] && cmp="--compare $5"
  $PY -m kit auc "$1" --control "$2" --labels "$(lab "$3")/inklabels.zarr" --mask "$(lab "$3")/supervision.zarr" \
      --crop $(crop "$3") --surface-shape $(shape "$3") --inner 64 --bootstrap 300 $cmp --json > "$4"
}
for pair in ${PAIRS:-w045:w00 w00:w045 w00train:w00}; do
  tr="${pair%%:*}"; te="${pair##*:}"
  for kind in fibre raw; do
    m="$OUT/model_${kind}_${tr}.npz"
    [[ -f "$m" ]] || $PY -m kit fibertensor train "$(vol "$tr")" "$(lab "$tr")" --crop $(crop "$tr") \
        --surface-shape $(shape "$tr") --kind "$kind" -o "$m" > "$m.json"
    for dir in fwd rev; do
      flag=""; [[ "$dir" == rev ]] && flag="--reverse"
      $PY -m kit fibertensor predict "$m" "$(vol "$te")" --crop $(crop "$te") $flag \
          -o "$OUT/map_${kind}_${tr}_to_${te}_${dir}.tif" > /dev/null
    done
  done
  f="$OUT/map_fibre_${tr}_to_${te}"; r="$OUT/map_raw_${tr}_to_${te}"
  score "${f}_fwd.tif" "${f}_rev.tif" "$te" "$OUT/auc_fibre_${tr}_to_${te}_vs_raw.json" "${r}_fwd.tif"
  score "${f}_fwd.tif" "${f}_rev.tif" "$te" "$OUT/auc_fibre_${tr}_to_${te}_vs_ink9um.json" "$(ink9 "$te")"
  score "${r}_fwd.tif" "${r}_rev.tif" "$te" "$OUT/auc_raw_${tr}_to_${te}.json"
  echo "done $tr -> $te"
done
