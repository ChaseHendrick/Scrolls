#!/usr/bin/env bash
# v8inwin-ag405: base v8in on the PHerc0841 ag405 crop, one map per 24-layer depth window of the
# 28 stored layers (windows start at 0..4), forward at stride 42 and reverse at stride 64, then the
# mean of the five windows (forward and reverse). Resumable: maps that exist are skipped.
#
# How v8in picks layers (ink8um/inference.py read_stack, revision in notes.md): with no
# --layer-start it takes the centred 24 of the numbered files in the folder, start
# (n - 24) // 2. Each window is therefore exported as its own folder of exactly 24 layers
# (kit layers --start S --count 24), so read_stack takes all 24 and nothing else.
#
#   W=$HOME/scrolls-work nohup bash run.sh > run.log 2>&1 &
set -euo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
W="${W:-$HOME/scrolls-work}"
PY="$W/venv/bin/python"
SEG=0841-ag405
CROP=(1024 1664 2496 3136)
ZARR="$W/data/${SEG}_9um.zarr"
OUT="$W/v8inwin-ag405"
mkdir -p "$OUT/maps" "$OUT/logs"
cd "$SCROLLS"

for s in 0 1 2 3 4; do
  d="$OUT/layers_w$s"
  if [[ ! -f "$d/23.tif" ]]; then
    rm -rf "$d.tmp"
    "$PY" -m kit layers "$ZARR" "$d.tmp" --crop "${CROP[@]}" --start "$s" --count 24
    n=$(ls "$d.tmp" | grep -c '\.tif$')
    [[ "$n" == 24 ]] || { echo "window $s: $n layers, expected 24" >&2; exit 1; }
    mv "$d.tmp" "$d"
  fi
done

run() {  # run NAME LAYERS STRIDE [--reverse]
  local name="$1" layers="$2" stride="$3"; shift 3
  if [[ -f "$OUT/maps/$name.npy" ]]; then echo "$name: exists, skipped"; return; fi
  echo "$name: start $(date -u +%FT%TZ)"
  "$PY" scripts/v8in_run.py --model-dir "$W/checkpoints/ink-8um-v8in" --layers "$layers" \
    --output "$OUT/maps/$name.tmp.npy" --device cpu --batch-size 4 --stride "$stride" "$@" \
    > "$OUT/logs/$name.log" 2>&1 || { tail -20 "$OUT/logs/$name.log"; exit 1; }
  mv "$OUT/maps/$name.tmp.npy" "$OUT/maps/$name.npy"
  tail -1 "$OUT/logs/$name.log"
  echo "$name: done $(date -u +%FT%TZ)"
}

# Default window (w2) first, then the others; forward s42 before reverse s64.
for s in 2 0 1 3 4; do
  run "w${s}_fwd_s42" "$OUT/layers_w$s" 42
  run "w${s}_rev_s64" "$OUT/layers_w$s" 64 --reverse
done

"$PY" -m kit ensemble "$OUT/maps/mean_fwd.npy" "$OUT"/maps/w{0,1,2,3,4}_fwd_s42.npy --method mean
"$PY" -m kit ensemble "$OUT/maps/mean_rev.npy" "$OUT"/maps/w{0,1,2,3,4}_rev_s64.npy --method mean
echo "all done $(date -u +%FT%TZ)"
