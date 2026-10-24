#!/bin/bash
# HF Job: train our ICDAR head-to-head candidates (icdar_train.py) on Hell-Char only.
#   RESULTS=BUCKET_URL bash train_job.sh RUN_DIR OUT_DIR [--smoke]
# RUN_DIR holds icdar_train.py (copied into your HF bucket); OUT_DIR is on that bucket's mount;
# RESULTS is the bucket URL of this run's folder, for the upload at the end.
set -euo pipefail
RUN_DIR=$1; OUT=$2; SMOKE=${3:-}
pip install -q --no-cache-dir timm==1.0.30 "opencv-python-headless<5" "huggingface_hub>=1.33" 2>&1 | grep -v -i warning || true
python -c "import torch, timm, cv2; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'timm', timm.__version__)"
if [ "$SMOKE" = "--smoke" ]; then
  python "$RUN_DIR/icdar_train.py" smoke --out /tmp/smoke
  exit 0
fi
cd /tmp
# Hell-Char at aeef8466 (hellchar.csv and cliplets.zip, staged beside this script; sha256 in hellchar.sha256)
mkdir -p hc/data/hellchar
cp "$RUN_DIR/hellchar.csv" hc/data/hellchar/
(cd "$RUN_DIR" && sha256sum -c hellchar.sha256)
python -c "import zipfile; z = zipfile.ZipFile('$RUN_DIR/cliplets.zip'); [z.extract(n, 'hc/data/hellchar') for n in z.namelist() if n.startswith('cliplets/') and not n.endswith('/')]"
ls hc/data/hellchar/cliplets | wc -l
mkdir -p "$OUT" /tmp/out
# specs.txt beside this script: one run per line, "NAME ARGS..." (the 24 Oct round 1 ran s0, s1, s2, z128)
n=$(grep -c . "$RUN_DIR/specs.txt"); i=0
while read -r name args; do
  [ -z "$name" ] && continue
  i=$((i + 1))
  echo "PROGRESS run $i/$n $name"
  python "$RUN_DIR/icdar_train.py" train --hellchar hc/data/hellchar --out "/tmp/out/$name" $args 2>&1 | grep -E "PROGRESS [0-9]+0{3}/|crops|Error|error" || true
  test -f "/tmp/out/$name/model.pt"
  cp -r "/tmp/out/$name" "$OUT/" || true
done < "$RUN_DIR/specs.txt"
# dev posteriors (ICDAR training photos, choices only) for these runs and any listed in extra_runs.txt
if [ -f "$RUN_DIR/dev-crops.npz" ]; then
  runs=$(ls -d /tmp/out/*/ | sed 's:/$::')
  [ -f "$RUN_DIR/extra_runs.txt" ] && runs="$runs $(cat "$RUN_DIR/extra_runs.txt")"
  python "$RUN_DIR/icdar_train.py" devpost --crops "$RUN_DIR/dev-crops.npz" --runs $runs --out /tmp/out/devpost
fi
sha256sum "$RUN_DIR/icdar_train.py" > /tmp/out/code.sha256
cp /tmp/out/code.sha256 "$OUT/" || true
# the mount lost every write of the first full run, so the results also go up through the Hub API
hf buckets sync /tmp/out "${RESULTS:?set RESULTS to the bucket URL of this run}"
echo DONE
