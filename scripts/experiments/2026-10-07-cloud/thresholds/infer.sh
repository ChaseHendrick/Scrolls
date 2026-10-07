#!/usr/bin/env bash
# thresholds job, step 1: whole-segment ink_9um seed 42 maps, both directions (villa PR #1865, CPU),
# one segment at a time. Resumable: a segment whose forward and reverse maps exist is skipped.
# Waits for setup.sh's data. Maps stay in $WORK/thresholds/maps (never in git).
set -uo pipefail
W="${WORK:-$HOME/scrolls-work}"
PY="$W/venv/bin/python"
OUT="$W/thresholds/maps"; mkdir -p "$OUT" "$W/logs"
CK="$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"
# setup.sh switches villa between main and the PR, so wait until it has finished for all segments.
until grep -q "setup finished" "$W/logs/thresholds_setup.log" 2>/dev/null; do sleep 60; done
for seg in 0841-w00 0841-ag896 0841-ag405; do   # w045 dropped 2026-10-07 (budget)
  map="$OUT/${seg}_ink9um_s42.tif"
  if [[ -f "$map" && -f "${map%.tif}_reverse.tif" ]]; then echo "== $seg: maps exist"; continue; fi
  [[ "$seg" == 0841-w00 ]] || until [[ -f "$W/data/${seg}_labels/.fetched" ]]; do sleep 60; done   # fetch.sh
  git -C "$W/villa" checkout -q --detach pr-1865
  echo "== $seg: inference start $(date -u +%H:%M:%S)"
  start=$SECONDS
  (cd "$W" && "$PY" -m vesuvius.ink_detection.inference.infer "$W/data/${seg}_9um.zarr" "$CK" "$OUT/.${seg}_tmp.tif" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) > "$W/logs/thresholds_${seg}_infer.log" 2>&1 \
    || { echo "== $seg: inference FAILED (see log)"; tail -5 "$W/logs/thresholds_${seg}_infer.log"; continue; }
  mv "$OUT/.${seg}_tmp_reverse.tif" "${map%.tif}_reverse.tif" && mv "$OUT/.${seg}_tmp.tif" "$map"
  echo "== $seg: done in $(( SECONDS - start )) s ($(date -u +%H:%M:%S))"
  echo "$seg $(( SECONDS - start ))" >> "$OUT/seconds.txt"
done
echo "== all inference finished $(date -u +%H:%M:%S)"
