#!/usr/bin/env bash
# Lane H cloud job: fine-tune ink_9um seed 42 (variants P90, P80, S1, S2), then score. Resumable.
# Phases (PHASE=...): prepare (CPU: env, data, crops), base (GPU: pseudo-label source map, base crop maps and scores),
# variant (GPU, VARIANT=P90|P80|S1|S2: train, infer, score), collect, or all (sequential, any CUDA machine).
# Run from the repo root. Readout rules are in README.md of this folder and were committed before any training.
set -euo pipefail
REPO="$(pwd)"; J="$REPO/scripts/experiments/2026-10-07-cloud/laneH-finetune"
W="${WORK:-$HOME/scrolls-work}"; O="${OUT:-$W/laneH}"; PY="$W/venv/bin/python"
PHASE="${PHASE:-all}"; VARIANT="${VARIANT:-}"
SMOKE_STEPS="${SMOKE_STEPS:-0}"   # >0: pipeline test only, numbers are not results; written to a separate tree
[[ "$SMOKE_STEPS" == 0 ]] || O="$O-smoke"
mkdir -p "$O"/{ckpt,maps,crops,scores,logs,timing}
say() { echo "[$(date +%H:%M:%S)] $*"; }
TAG="${PHASE}${VARIANT:+_$VARIANT}"; TF="$O/timing/$TAG.jsonl"
mark() { echo "{\"phase\": \"$TAG\", \"step\": \"$1\", \"event\": \"$2\", \"utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"epoch_s\": $(date +%s)}" >> "$TF"; }

declare -A SV=( [0841-w00]=$W/data/0841-w00_9um.zarr [w045]=$W/data/w045_9um.zarr )
declare -A LB=( [0841-w00]=$W/data/0841-w00_labels [w045]=$W/data/w045_labels )
declare -A CR=( [0841-w00]="2624 3264 2688 3328" [w045]="3840 4480 2560 3200" )
declare -A SH=( [0841-w00]="4220 4760" [w045]="5980 8240" )
BASE="$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"

infer() {  # infer IN.zarr CKPT OUT.tif  (writes OUT.tif and OUT_reverse.tif)
  [[ -f "$3" ]] || (cd "$W" && $PY -m vesuvius.ink_detection.inference.infer "$1" "$2" "$3" \
    --overlap 0.5 --blend-mode hann --batch-size 8 --no-compile --direction both > "$3.log" 2>&1)
}
score() {  # score MODEL SEG KIND(""|_shuf)
  local m=$1 seg=$2 kind=$3 f="$O/scores/${1}_${2}${3}.json"; [[ -f "$f" ]] && return 0
  local cmp=(); [[ $m == base ]] || cmp=(--compare "$O/maps/base_${seg}${kind}.tif")
  (cd "$REPO" && $PY -m kit auc "$O/maps/${m}_${seg}${kind}.tif" --control "$O/maps/${m}_${seg}${kind}_reverse.tif" \
    --labels "${LB[$seg]}/inklabels.zarr" --mask "${LB[$seg]}/supervision.zarr" --level 2 \
    --crop ${CR[$seg]} --surface-shape ${SH[$seg]} --inner 64 --bootstrap 300 "${cmp[@]}" --json) > "$f.tmp" && mv "$f.tmp" "$f"
}
gpu_check() { $PY -c "import torch; assert torch.cuda.is_available(), 'no CUDA'; print(torch.cuda.get_device_name(0))" | tee "$O/logs/gpu_$TAG.txt"; }

prepare() {
  mark data_fetch start
  for seg in 0841-w00 w045; do
    [[ -d "${SV[$seg]}" && -d "${LB[$seg]}/inklabels.zarr" && -f "$BASE" ]] || \
      SMOKE=1 EXPECT_GPU=cpu WORK="$W" SEGMENT=$seg bash scripts/mac-w045.sh > "$O/logs/setup_$seg.log" 2>&1
  done
  sha256sum "$BASE" > "$O/logs/base_sha256.txt"
  mark data_fetch end; mark crops start
  # test crops: as stored, and depth-shuffled with a fixed permutation (seed 20261007)
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

  mark crops end
}

base_phase() {
  git -C "$W/villa" checkout -q --detach pr-1865; gpu_check
  mark base_full_map start   # arm P's pseudo-label source; base s42 on the whole w00 surface
  infer "${SV[0841-w00]}" "$BASE" "$O/maps/base_full_0841-w00.tif"
  mark base_full_map end; mark base_crops start
  for seg in 0841-w00 w045; do
    infer "$O/crops/${seg}_stored.zarr" "$BASE" "$O/maps/base_${seg}.tif"
    infer "$O/crops/${seg}_shuffled.zarr" "$BASE" "$O/maps/base_${seg}_shuf.tif"
  done
  mark base_crops end; mark score start
  for seg in 0841-w00 w045; do score base $seg ""; score base $seg _shuf; done
  mark score end
}

EXTRA=(); [[ "$SMOKE_STEPS" == 0 ]] || EXTRA=(--smoke "$SMOKE_STEPS")
FT=(--epochs 3 --steps-per-epoch 400 --batch-size 8 --lr 1e-5 --gap 64 "${EXTRA[@]}")
w00c=(${CR[0841-w00]}); w45c=(${CR[w045]})
train() { local name=$1; shift; [[ -f "$O/ckpt/$name/last.pth" ]] || \
  (cd "$W" && $PY "$J/finetune_ink9um.py" --checkpoint "$BASE" --out "$O/ckpt/$name" "$@" "${FT[@]}" > "$O/logs/train_$name.log" 2>&1); }

variant_phase() {
  local m=$1; git -C "$W/villa" checkout -q --detach pr-1865; gpu_check
  [[ -f "$O/maps/base_full_0841-w00.tif" ]] || { echo "base phase has not finished" >&2; exit 1; }
  mark train start
  case $m in
    P90) train P90 --volume "${SV[0841-w00]}" --pseudo-map "$O/maps/base_full_0841-w00.tif" --ink-thr 0.90 --bg-thr 0.10 --exclude "${w00c[@]}" ;;
    P80) train P80 --volume "${SV[0841-w00]}" --pseudo-map "$O/maps/base_full_0841-w00.tif" --ink-thr 0.80 --bg-thr 0.20 --exclude "${w00c[@]}" ;;
    S1)  train S1 --volume "${SV[w045]}" --labels "${LB[w045]}/inklabels.zarr" --mask "${LB[w045]}/supervision.zarr" --exclude "${w45c[@]}" ;;
    S2)  train S2 --volume "${SV[0841-w00]}" --labels "${LB[0841-w00]}/inklabels.zarr" --mask "${LB[0841-w00]}/supervision.zarr" --exclude "${w00c[@]}" ;;
    *) echo "VARIANT must be P90, P80, S1 or S2" >&2; exit 2 ;;
  esac
  mark train end; mark infer start
  for seg in 0841-w00 w045; do
    infer "$O/crops/${seg}_stored.zarr" "$O/ckpt/$m/last.pth" "$O/maps/${m}_${seg}.tif"
    infer "$O/crops/${seg}_shuffled.zarr" "$O/ckpt/$m/last.pth" "$O/maps/${m}_${seg}_shuf.tif"
  done
  mark infer end; mark score start
  for seg in 0841-w00 w045; do score $m $seg ""; score $m $seg _shuf; done
  mark score end
}

mark phase start
case $PHASE in
  prepare) prepare ;;
  base) base_phase ;;
  variant) variant_phase "$VARIANT" ;;
  collect) ;;
  all) prepare; base_phase; for v in P90 P80 S1 S2; do TAG=variant_$v TF="$O/timing/variant_$v.jsonl" variant_phase $v; done ;;
  *) echo "unknown PHASE $PHASE" >&2; exit 2 ;;
esac
mark phase end
if [[ $PHASE == collect || $PHASE == all ]]; then
  $PY "$J/collect.py" "$O" "$J/results.json" "$SMOKE_STEPS"; say "results in $J/results.json"
fi
