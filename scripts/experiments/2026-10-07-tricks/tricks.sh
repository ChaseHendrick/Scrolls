set -euo pipefail
S="${S:-$HOME/scrolls-cpu}"; W=$S/smoke-work; PY=$W/venv/bin/python; R=$S/readers; T=$S/tricks
declare -A CK=( [s42]=$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth [soup42]=$T/soup42_last4.pth [d9v2]=$S/models/d9v2/d9v2_ft-012000.pth )
inf() { # zarr ckpt out extra...
  local z=$1 c=$2 o=$3; shift 3
  [ -s "$o" ] && return 0
  local t=$SECONDS
  (cd $W && $PY -m vesuvius.ink_detection.inference.infer "$z" "$c" "$o" --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile "$@" > "${o%.tif}.log" 2>&1)
  echo "$(basename $o) $((SECONDS-t)) s"
}
for seg in 0841-w00 0841-ag896 0841-ag405 w045; do
  z=$R/${seg}_crop.zarr
  # depth-shuffled copy of the crop (fixed seed), for the shuffle control
  [ -d $T/${seg}_shuf.zarr ] || $PY -I - "$z" "$T/${seg}_shuf.zarr" <<'PYEOF'
import sys, zarr, numpy as np
a = zarr.open(sys.argv[1], mode="r")["0"][:]
perm = np.random.default_rng(20261007).permutation(a.shape[0])
zarr.open_group(sys.argv[2], mode="w").create_array("0", data=a[perm], chunks=(a.shape[0], 128, 128))
print("perm", perm.tolist())
PYEOF
  inf $z ${CK[soup42]} $T/${seg}_soup42.tif --direction both
  for m in s42 soup42 d9v2; do
    for w in 0:20 3:23 5:25 8:27; do
      inf $z ${CK[$m]} $T/${seg}_${m}_z${w/:/-}.tif --direction both --layer-start ${w%%:*} --layer-end ${w##*:}
    done
    inf $T/${seg}_shuf.zarr ${CK[$m]} $T/${seg}_${m}_shuf.tif --direction forward
  done
  inf $z ${CK[d9v2]} $T/${seg}_d9v2_tta.tif --direction both --tta-mirror
  inf $z ${CK[s42]} $T/${seg}_s42_tta.tif --direction both --tta-mirror
done
echo ALL DONE
