#!/usr/bin/env bash
# Job v8in-ag405 (scripts/experiments/2026-10-07-cloud/README.md): base v8in, ink_9um seed 42
# and d9v2 on the 640 px crop of PHerc0841 ag405, CPU only. Resumable: a map that exists is
# kept. Run after the shared SMOKE setup with SEGMENT=0841-ag405. Then run score.sh.
#   nohup bash run.sh > $W/logs/v8in-ag405_run.log 2>&1 &
set -euo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
W="${W:-$HOME/scrolls-work}"
PY="$W/venv/bin/python"
SEG=0841-ag405
CROP=(1024 1664 2496 3136)
ZARR="$W/data/${SEG}_9um.zarr"
J="$W/job-v8in-ag405"
V8IN="$W/checkpoints/ink-8um-v8in"
D9V2="$W/checkpoints/d9v2/d9v2_ft-012000.pth"
INK42="$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"
mkdir -p "$J"/{maps,logs}
cd "$SCROLLS"

say() { printf '\n== %s %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# Layers: as stored, and depth-shuffled with the README's seed.
[[ -f "$J/layers/27.tif" ]] || { rm -rf "$J/layers"; "$PY" -m kit layers "$ZARR" "$J/layers" --crop "${CROP[@]}"; }
[[ -f "$J/layers_shuf/27.tif" ]] || { rm -rf "$J/layers_shuf"; "$PY" -m kit layers "$ZARR" "$J/layers_shuf" --crop "${CROP[@]}" --shuffle 20261007; }
# Crop zarr for villa (same 5 lines as crops_and_bars.sh).
[[ -d "$J/crop.zarr" ]] || "$PY" - "$ZARR" "$J/crop.zarr" "${CROP[@]}" <<'EOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
EOF

v8in() {  # v8in NAME LAYERS STRIDE [--reverse]
  local name="$1" layers="$2" stride="$3"; shift 3
  if [[ -f "$J/maps/$name.tif" ]]; then echo "$name: exists, kept"; return 0; fi
  say "v8in $name (stride $stride $*)"
  "$PY" scripts/v8in_run.py --model-dir "$V8IN" --layers "$layers" --output "$J/maps/$name.npy" \
    --device cpu --batch-size 4 --stride "$stride" "$@" > "$J/logs/$name.log" 2>&1
  "$PY" - "$J/maps/$name.npy" "$J/maps/$name.tif" <<'EOF'
import sys, numpy as np, tifffile
p = np.load(sys.argv[1])
tifffile.imwrite(sys.argv[2], np.round(np.clip(p, 0, 1) * 255).astype(np.uint8), compression="zlib")
EOF
  tail -1 "$J/logs/$name.log"
}

villa() {  # villa NAME CKPT: both directions on the crop zarr
  local name="$1" ck="$2"
  if [[ -f "$J/maps/$name.tif" && -f "$J/maps/${name}_reverse.tif" ]]; then echo "$name: exists, kept"; return 0; fi
  say "villa $name"
  git -C "$W/villa" checkout -q --detach pr-1865
  local t=$SECONDS
  (cd "$W" && "$PY" -m vesuvius.ink_detection.inference.infer "$J/crop.zarr" "$ck" "$J/maps/$name.tif" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both) > "$J/logs/$name.log" 2>&1
  echo "villa $name: done in $(( SECONDS - t ))s" | tee -a "$J/logs/$name.log"
}

# Cheapest first, so a reclaimed container loses the least.
villa ink9um_s42 "$INK42"
villa d9v2 "$D9V2"
# Budget cut from the coordinating session (2026-10-07): forward s42 is the main map,
# reverse and shuffled at s64, no s21 run.
v8in v8in_s42 "$J/layers" 42
v8in v8in_s64_reverse "$J/layers" 64 --reverse
v8in v8in_shuf_s64 "$J/layers_shuf" 64
say "all maps done"
