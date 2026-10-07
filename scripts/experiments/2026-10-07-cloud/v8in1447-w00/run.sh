#!/usr/bin/env bash
# Job v8in1447-w00 (README of 2026-10-07-cloud): v8in-1447 on the PHerc0841 w00 crop, CPU.
#   forward and reverse stride 42; preserve historical reverse stride 64 as provisional.
#   d9v2 on the crop (villa, both
#   directions); ensemble v8in-1447 + d9v2 (mean and rank); every map scored by score.py.
# Resumable: a map that exists is not rebuilt. After each map: score, commit, push.
#   nohup bash scripts/experiments/2026-10-07-cloud/v8in1447-w00/run.sh > $W/logs/job.log 2>&1 &
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
W="${W:-$HOME/scrolls-work}"
PY="$W/venv/bin/python"
SEG=0841-w00
CROP=(2624 3264 2688 3328)
OUT="$W/job-v8in1447-w00"
V8=$W/checkpoints/ink-8um-v8in-pherc1447-loo-w062
D9=$W/checkpoints/d9v2/d9v2_ft-012000.pth
mkdir -p "$OUT/maps" "$OUT/logs"
cd "$REPO"

publish() {  # score every map that exists, then commit and push the small files
  "$PY" "$HERE/score.py" "$OUT" > "$OUT/logs/score.log" 2>&1 || { tail -20 "$OUT/logs/score.log"; return 0; }
  cp "$OUT/timings.json" "$HERE/timings.json" 2>/dev/null || true
  git add "$HERE"
  git commit -q -m "v8in1447-w00: results after $1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RfoqEbtxYDRgPbeBdxo5QK" || true
  for d in 2 4 8 16; do git push -q -u origin HEAD && break || sleep $d; done || true
}
timing() {  # timing NAME SECONDS
  "$PY" - "$OUT/timings.json" "$1" "$2" <<'EOF'
import json, sys, os
p = sys.argv[1]; t = json.load(open(p)) if os.path.exists(p) else {}
t[sys.argv[2]] = int(sys.argv[3]); json.dump(t, open(p, "w"), indent=1)
EOF
}

# Inputs: crop zarr for villa, crop layers for v8in
CZ="$W/data/${SEG}_quickcrop_${CROP[0]}_${CROP[2]}.zarr"
[[ -d "$CZ" ]] || "$PY" - "$W/data/${SEG}_9um.zarr" "$CZ" "${CROP[@]}" <<'EOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
EOF
LAYERS="$OUT/crop_layers"
[[ -f "$LAYERS/.done" ]] || { rm -rf "$LAYERS"; "$PY" -m kit layers "$W/data/${SEG}_9um.zarr" "$LAYERS" --crop "${CROP[@]}"; touch "$LAYERS/.done"; }

# d9v2 on the crop, both directions (villa PR #1865, as the Mac script)
if [[ ! -f "$OUT/maps/d9v2.tif" || ! -f "$OUT/maps/d9v2_reverse.tif" ]]; then
  git -C "$W/villa" checkout -q --detach pr-1865
  t=$SECONDS
  (cd "$W" && "$PY" -m vesuvius.ink_detection.inference.infer "$CZ" "$D9" "$OUT/maps/d9v2.tif" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) > "$OUT/logs/d9v2.log" 2>&1
  timing d9v2_both $(( SECONDS - t ))
  git -C "$W/villa" checkout -q --detach origin/main
  publish "d9v2"
fi

v8() {  # v8 NAME STRIDE fwd|rev
  local name="$1" stride="$2" dir="$3" t=$SECONDS flags=()
  [[ "$dir" == rev ]] && flags+=(--reverse)
  [[ -f "$OUT/maps/$name.tif" ]] && return 0
  "$PY" "$REPO/scripts/v8in_run.py" --model-dir "$V8" --layers "$LAYERS" --output "$OUT/maps/$name.npy" \
    --device cpu --batch-size 4 --stride "$stride" "${flags[@]}" > "$OUT/logs/$name.log" 2>&1
  "$PY" - "$OUT/maps/$name.npy" "$OUT/maps/$name.tif" <<'EOF'
import sys, numpy as np, tifffile
p = np.load(sys.argv[1])
tifffile.imwrite(sys.argv[2], np.round(np.clip(p, 0, 1) * 255).astype(np.uint8), compression="zlib")
EOF
  timing "$name" $(( SECONDS - t ))
  publish "$name"
}
v8 v8in1447_s42 42 fwd
v8 v8in1447_s42_reverse 42 rev
echo "all done"
