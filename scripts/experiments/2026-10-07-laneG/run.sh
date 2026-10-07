#!/bin/bash
# Lane G run on the Mac (CPU only, no GPU lock needed). Usage: bash run.sh  (from ~/scrolls-work/laneG)
set -euo pipefail
W=~/scrolls-work; PY=$W/venv/bin/python; L=$W/laneG
cd $L
mkdir -p "$L/out"
nice -n 10 $PY signals.py $L $W/data $L/out 2>&1 | tee $L/out/signals.log
for seg in w045 0841-w00; do
  if [ $seg = w045 ]; then C="3840 4480 2560 3200"; lab=w045_labels; z=w045_9um.zarr; else C="2624 3264 2688 3328"; lab=0841-w00_labels; z=0841-w00_9um.zarr; fi
  S=$($PY -c "import zarr;print(*zarr.open('$W/data/$z/0').shape[1:])")
  for sig in brightness dog_band noise_resid crackle relief phase_sym; do
    PYTHONPATH=$L nice -n 10 $PY -m kit auc out/maps/${seg}_${sig}.tif --labels $W/data/$lab/inklabels.zarr --mask $W/data/$lab/supervision.zarr \
      --control out/maps/${seg}_${sig}_shuf.tif --crop $C --surface-shape $S --inner 64 --bootstrap 300 --seed 20261007 --json \
      > out/boot_${seg}_${sig}.json
  done
done
