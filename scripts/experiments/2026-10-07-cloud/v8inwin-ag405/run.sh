#!/usr/bin/env bash
# v8inwin-ag405: base v8in on the PHerc0841 ag405 crop, one map per 24-layer depth window of the
# 28 stored layers. Budget cut by the coordinating session (about 1 h of CPU): windows starting at
# 0, 2 (v8in's default, centred) and 4, forward at stride 64, plus their mean; reverse only for the
# default window, stride 64. Resumable: maps that exist are skipped.
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

for s in 0 2 4; do
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

run w2_fwd_s64 "$OUT/layers_w2" 64
run w2_rev_s64 "$OUT/layers_w2" 64 --reverse
run w0_fwd_s64 "$OUT/layers_w0" 64
run w4_fwd_s64 "$OUT/layers_w4" 64

"$PY" -m kit ensemble "$OUT/maps/mean_fwd.npy" "$OUT"/maps/w{0,2,4}_fwd_s64.npy --method mean
echo "all done $(date -u +%FT%TZ)"
