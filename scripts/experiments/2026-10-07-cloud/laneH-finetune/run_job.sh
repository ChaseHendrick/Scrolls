#!/usr/bin/env bash
# Lane H cloud job: fine-tune ink_9um seed 42 (arms P, S1, S2), then score. Resumable.
# Run from the repo root on a Linux CUDA machine:  bash scripts/experiments/2026-10-07-cloud/laneH-finetune/run_job.sh
# Readout rules are in README.md of this folder and were committed before any training.
set -euo pipefail
REPO="$(pwd)"; J="$REPO/scripts/experiments/2026-10-07-cloud/laneH-finetune"
W="${WORK:-$HOME/scrolls-work}"; O="${OUT:-$W/laneH}"; PY="$W/venv/bin/python"
SMOKE_STEPS="${SMOKE_STEPS:-0}"   # >0: pipeline test only, numbers are not results
mkdir -p "$O"/{ckpt,maps,crops,scores,logs}
say() { echo "[$(date +%H:%M:%S)] $*"; }

# 1. data and environment, reusing the repo's setup (villa main + PR #1865, ink_9um s42/s43, volumes, labels)
for seg in 0841-w00 w045; do
  [[ -d "$W/data/${seg}_9um.zarr" && -d "$W/data/${seg}_labels/inklabels.zarr" ]] || \
    SMOKE=1 EXPECT_GPU=cpu WORK="$W" SEGMENT=$seg bash scripts/mac-w045.sh > "$O/logs/setup_$seg.log" 2>&1
done
git -C "$W/villa" checkout -q --detach pr-1865
$PY -c "import torch; assert torch.cuda.is_available(), 'no CUDA'; print(torch.cuda.get_device_name(0))" | tee "$O/logs/gpu.txt"
BASE="$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"
sha256sum "$BASE" > "$O/logs/base_sha256.txt"

declare -A SV=( [0841-w00]=$W/data/0841-w00_9um.zarr [w045]=$W/data/w045_9um.zarr )
declare -A LB=( [0841-w00]=$W/data/0841-w00_labels [w045]=$W/data/w045_labels )
declare -A CR=( [0841-w00]="2624 3264 2688 3328" [w045]="3840 4480 2560 3200" )
declare -A SH=( [0841-w00]="4220 4760" [w045]="5980 8240" )

infer() {  # infer IN.zarr CKPT OUT.tif  (writes OUT.tif and OUT_reverse.tif)
  [[ -f "$3" ]] || (cd "$W" && $PY -m vesuvius.ink_detection.inference.infer "$1" "$2" "$3" \
    --overlap 0.5 --blend-mode hann --batch-size 8 --no-compile --direction both > "$3.log" 2>&1)
}

# 2. test crops: as stored, and depth-shuffled with a fixed permutation (seed 20261007)
for seg in 0841-w00 w045; do
  read y0 y1 x0 x1 <<< "${CR[$seg]}"
  for kind in stored shuffled; do
    [[ -d "$O/crops/${seg}_$kind.zarr" ]] || $PY - "${SV[$seg]}" "$O/crops/${seg}_$kind.zarr" $y0 $y1 $x0 $x1 $kind <<'PYEOF'
import sys, zarr, numpy as np
src, dst, y0, y1, x0, x1, kind = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:7]), sys.argv[7]
data = zarr.open(src, mode="r")["0"][:, y0:y1, x0:x1]
if kind == "shuffled":
    data = data[np.random.default_rng(20261007).permutation(data.shape[0])]
zarr.open_group(dst, mode="w").create_array("0", data=data, chunks=(data.shape[0], 128, 128))
PYEOF
  done
done

# 3. arm P needs the base forward map on the whole w00 surface (pseudo-label source)
say "base s42 whole-surface map on 0841-w00 (pseudo-label source)"
infer "${SV[0841-w00]}" "$BASE" "$O/maps/base_full_0841-w00.tif"

EXTRA=(); [[ "$SMOKE_STEPS" == 0 ]] || EXTRA=(--smoke "$SMOKE_STEPS")
FT=(--epochs 3 --steps-per-epoch 400 --batch-size 8 --lr 1e-5 --gap 64 "${EXTRA[@]}")
w00c=(${CR[0841-w00]}); w45c=(${CR[w045]})
train() { local name=$1; shift; [[ -f "$O/ckpt/$name/last.pth" ]] || \
  (cd "$W" && $PY "$J/finetune_ink9um.py" --checkpoint "$BASE" --out "$O/ckpt/$name" "$@" "${FT[@]}" > "$O/logs/train_$name.log" 2>&1); }

say "arm P: self-training on w00 pseudo-labels outside the w00 crop (+64 px gap)"
train P90 --volume "${SV[0841-w00]}" --pseudo-map "$O/maps/base_full_0841-w00.tif" --ink-thr 0.90 --bg-thr 0.10 --exclude "${w00c[@]}"
train P80 --volume "${SV[0841-w00]}" --pseudo-map "$O/maps/base_full_0841-w00.tif" --ink-thr 0.80 --bg-thr 0.20 --exclude "${w00c[@]}"
say "arm S1: supervised on w045 labels (w045 crop +64 px excluded), test on w00"
train S1 --volume "${SV[w045]}" --labels "${LB[w045]}/inklabels.zarr" --mask "${LB[w045]}/supervision.zarr" --exclude "${w45c[@]}"
say "arm S2: supervised on w00 labels (w00 crop +64 px excluded), test on w045"
train S2 --volume "${SV[0841-w00]}" --labels "${LB[0841-w00]}/inklabels.zarr" --mask "${LB[0841-w00]}/supervision.zarr" --exclude "${w00c[@]}"

# 4. inference on both test crops: base and every model, as stored (forward + reverse) and shuffled
for seg in 0841-w00 w045; do
  infer "$O/crops/${seg}_stored.zarr" "$BASE" "$O/maps/base_${seg}.tif"
  infer "$O/crops/${seg}_shuffled.zarr" "$BASE" "$O/maps/base_${seg}_shuf.tif"
  for m in P90 P80 S1 S2; do
    infer "$O/crops/${seg}_stored.zarr" "$O/ckpt/$m/last.pth" "$O/maps/${m}_${seg}.tif"
    infer "$O/crops/${seg}_shuffled.zarr" "$O/ckpt/$m/last.pth" "$O/maps/${m}_${seg}_shuf.tif"
  done
done

# 5. scoring: kit auc with 300-draw block bootstrap, paired --compare against base s42
for seg in 0841-w00 w045; do
  for m in base P90 P80 S1 S2; do
    for kind in "" _shuf; do
      f="$O/scores/${m}_${seg}${kind}.json"; [[ -f "$f" ]] && continue
      cmp=(); [[ $m == base ]] || cmp=(--compare "$O/maps/base_${seg}${kind}.tif")
      (cd "$REPO" && $PY -m kit auc "$O/maps/${m}_${seg}${kind}.tif" --control "$O/maps/${m}_${seg}${kind}_reverse.tif" \
        --labels "${LB[$seg]}/inklabels.zarr" --mask "${LB[$seg]}/supervision.zarr" --level 2 \
        --crop ${CR[$seg]} --surface-shape ${SH[$seg]} --inner 64 --bootstrap 300 "${cmp[@]}" --json) > "$f"
    done
  done
done
$PY "$J/collect.py" "$O" "$J/results.json"
say "done; results in $J/results.json"
