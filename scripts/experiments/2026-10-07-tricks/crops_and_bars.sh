set -euo pipefail
S="${S:-$HOME/scrolls-cpu}"; W=$S/smoke-work; PY=$W/venv/bin/python; R=$S/readers; mkdir -p $R
declare -A SV=( [w045]=$S/data/w045_9um.zarr [0841-w00]=$S/data/p0841/20260220213127-w00/sv.zarr [0841-ag896]=$S/data/p0841/20260220214732-auto_grown_20260220144552896/sv.zarr [0841-ag405]=$S/data/p0841/20260221022814-auto_grown_20260220174252405/sv.zarr )
declare -A CR=( [w045]="3840 4480 2560 3200" [0841-w00]="2624 3264 2688 3328" [0841-ag896]="2496 3136 1600 2240" [0841-ag405]="1024 1664 2496 3136" )
declare -A CK=( [ink9um_s42]=$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth [d9v2]=$S/models/d9v2/d9v2_ft-012000.pth )
for seg in w045 0841-w00 0841-ag896 0841-ag405; do
  read y0 y1 x0 x1 <<< "${CR[$seg]}"
  $PY - "${SV[$seg]}" "$R/${seg}_crop.zarr" $y0 $y1 $x0 $x1 <<'PYEOF'
import sys, zarr
src, dst, y0, y1, x0, x1 = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
PYEOF
  for m in ink9um_s42 d9v2; do
    t=$SECONDS
    (cd $W && $PY -m vesuvius.ink_detection.inference.infer "$R/${seg}_crop.zarr" "${CK[$m]}" "$R/${seg}_$m.tif" \
      --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction both > "$R/${seg}_$m.log" 2>&1)
    echo "$seg $m $((SECONDS-t)) s"
  done
done
