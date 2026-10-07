set -euo pipefail
S="${S:-$HOME/scrolls-cpu}"; W=$S/smoke-work; PY=$W/venv/bin/python; R=$S/readers; T=$S/tricks
CK=$S/models/reader_v2/reader-v2-step040000.pth
inf() { local z=$1 o=$2; shift 2; [ -s "$o" ] && return 0; local t=$SECONDS
  (cd $W && $PY -m vesuvius.ink_detection.inference.infer "$z" "$CK" "$o" --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile "$@" > "${o%.tif}.log" 2>&1)
  echo "$(basename $o) $((SECONDS-t)) s"; }
for seg in $(for s in ${SEGS:-0841-w00 0841-ag896 0841-ag405}; do [ $s = w045 ] || echo $s; done); do   # Reader v2 trained on w045: PHerc0841 only
  z=$R/${seg}_crop.zarr
  inf $z $T/${seg}_rv2.tif --direction both
  for w in 0:20 3:23 5:25 8:27; do inf $z $T/${seg}_rv2_z${w/:/-}.tif --direction both --layer-start ${w%%:*} --layer-end ${w##*:}; done
  inf $T/${seg}_shuf.zarr $T/${seg}_rv2_shuf.tif --direction forward
done
echo ALL DONE
