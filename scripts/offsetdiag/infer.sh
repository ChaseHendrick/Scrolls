#!/usr/bin/env bash
# Map every arm of the ink offset diagnostic with villa's own ink inference, in both depth directions.
#
#   bash scripts/offsetdiag/infer.sh CHECKPOINT WORK MODEL
#
# Reads WORK/arms/KEY/ARM.zarr (from offsetdiag.py fetch and arms) and writes WORK/maps/MODEL_KEY_ARM.tif and
# MODEL_KEY_ARM_reverse.tif, the names offsetdiag.py score reads. Maps that exist are skipped, so a rerun resumes.
# Needs villa's vesuvius package (https://github.com/ScrollPrize/villa, `uv sync --extra models` in villa/vesuvius)
# and a CUDA GPU; set VILLA_PYTHON to that environment's python. INFER_ARGS replaces the villa arguments; the default
# is the Reader V3 setting of the 30 October 2026 run (layers 6 to 23, hann blending, overlap 0.5).
# DRY_RUN=1 prints the commands and runs nothing. Every map is model output, not a reading. Bash 3.2 compatible.
set -eu

if [ "$#" -ne 3 ]; then
  echo "usage: infer.sh CHECKPOINT WORK MODEL" >&2
  exit 2
fi
CKPT=$1
WORK=$2
MODEL=$3
PY=${VILLA_PYTHON:-python}
ARGS=${INFER_ARGS:---overlap 0.5 --blend-mode hann --batch-size 64 --no-compile --layer-start 6 --layer-end 23}
DRY=${DRY_RUN:-0}

if [ "$DRY" != "1" ] && [ ! -f "$CKPT" ]; then
  echo "infer.sh: error: no checkpoint at $CKPT" >&2
  exit 3
fi
if [ ! -d "$WORK/arms" ]; then
  echo "infer.sh: error: no $WORK/arms; run offsetdiag.py fetch and arms first" >&2
  exit 3
fi
mkdir -p "$WORK/maps"
n=0
done_=0
for z in "$WORK"/arms/*/*.zarr; do
  [ -d "$z" ] || continue
  key=$(basename "$(dirname "$z")")
  arm=$(basename "$z" .zarr)
  out="$WORK/maps/${MODEL}_${key}_${arm}.tif"
  n=$((n + 1))
  if [ -f "$out" ] && [ -f "${out%.tif}_reverse.tif" ]; then
    done_=$((done_ + 1))
    continue
  fi
  # shellcheck disable=SC2086
  if [ "$DRY" = "1" ]; then
    echo "$PY -m vesuvius.ink_detection.inference.infer $z $CKPT $out $ARGS --direction both"
  else
    echo "map $key $arm"
    "$PY" -m vesuvius.ink_detection.inference.infer "$z" "$CKPT" "$out" $ARGS --direction both
  fi
done
if [ "$n" -eq 0 ]; then
  echo "infer.sh: error: no arms under $WORK/arms" >&2
  exit 3
fi
echo "DONE $n arms, $done_ already mapped, maps in $WORK/maps"
