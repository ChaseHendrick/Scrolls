#!/usr/bin/env bash
# Score every finished map of run.sh on the ag405 crop (64 px edge out, labels level 2):
# kit auc and kit hpscore. Only the default window (w2) has a reverse map (budget cut), so its
# reverse map is the control for every forward map. One JSON per map.
set -uo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
W="${W:-$HOME/scrolls-work}"
PY="$W/venv/bin/python"
OUT="$W/v8inwin-ag405"
L="$W/data/0841-ag405_labels"
A=(--labels "$L/inklabels.zarr" --mask "$L/supervision.zarr" --level 2
   --crop 1024 1664 2496 3136 --surface-shape 3760 4900 --inner 64 --json)
mkdir -p "$OUT/scores"
cd "$SCROLLS"
for pair in w2:w2_fwd_s64:w2_rev_s64 w0:w0_fwd_s64:w2_rev_s64 w4:w4_fwd_s64:w2_rev_s64 \
            mean:mean_fwd:w2_rev_s64; do
  IFS=: read -r tag f r <<< "$pair"
  [[ -f "$OUT/maps/$f.npy" && -f "$OUT/maps/$r.npy" ]] || continue
  "$PY" -m kit auc "$OUT/maps/$f.npy" --control "$OUT/maps/$r.npy" "${A[@]}" > "$OUT/scores/${tag}_auc.json"
  "$PY" -m kit hpscore "$OUT/maps/$f.npy" --control "$OUT/maps/$r.npy" --voxel-um 9.366 "${A[@]}" \
    > "$OUT/scores/${tag}_hp.json"
  echo "$tag scored"
done
