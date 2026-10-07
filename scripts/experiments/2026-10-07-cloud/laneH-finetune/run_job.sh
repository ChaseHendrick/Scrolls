#!/usr/bin/env bash
# Lane H cloud job: fine-tune ink_9um seed 42 (variants P90, P80, S1, S2), then score. Inputs and inference caches require binding receipts.
# Phases (PHASE=...): prepare (CPU: env, data, crops), base (GPU: pseudo-label source map, base crop maps and scores),
# variant (GPU, VARIANT=P90|P80|S1|S2: train, infer, score), collect, or all (sequential, any CUDA machine).
# Run from the repo root. Readout rules are in README.md of this folder and were committed before any training.
set -euo pipefail
REPO="$(pwd)"; J="$REPO/scripts/experiments/2026-10-07-cloud/laneH-finetune"
W="${WORK:-$HOME/scrolls-work}"; O="${OUT:-$W/laneH}"; PY="$W/venv/bin/python"
PHASE="${PHASE:-check}"; VARIANT="${VARIANT:-}"
SMOKE_STEPS="${SMOKE_STEPS:-0}"   # >0: pipeline test only, numbers are not results; written to a separate tree
case "$PHASE" in
  check) echo "Not run. CPU guard tests are in tests/test_laneh_job.py; execution requires an explicit phase and LANEH_EXECUTE=1."; exit 0 ;;
  prepare|base|variant|collect|all) ;;
  *) echo "unknown PHASE $PHASE" >&2; exit 2 ;;
esac
[[ "$SMOKE_STEPS" =~ ^[0-9]+$ ]] || { echo "SMOKE_STEPS must be nonnegative integer" >&2; exit 2; }
[[ "${LANEH_EXECUTE:-0}" == 1 ]] || { echo "Not run: explicit LANEH_EXECUTE=1 required" >&2; exit 2; }
if [[ "$PHASE" == base || "$PHASE" == variant || "$PHASE" == all ]]; then
  [[ "${LANEH_GPU_AUTHORIZED:-0}" == 1 ]] || { echo "No GPU execution without prior budget authorization and LANEH_GPU_AUTHORIZED=1" >&2; exit 2; }
fi
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
VILLA_PIN=e0bbb8b40a2db58b1d71864f286eb85717e59e64
MODEL_PIN=7109667e2607db1b90c37c8b09cb876ea7fe7bb1
BASE_SHA=e635558ae6a1a807a7e5ec1e83adfd45bc3c0ac53883ea43f1d4e085d62a9cab
binding() {
  local create=(); [[ "${1:-}" == create ]] && create=(--create)
  "$PY" "$J/protocol.py" "$O/input-binding.json" "${create[@]}" \
    --input "$BASE" --input "${SV[0841-w00]}" --input "${SV[w045]}" --input "${LB[0841-w00]}" --input "${LB[w045]}" \
    --setting "scrolls=$(git -C "$REPO" rev-parse HEAD)" --setting "villa=$VILLA_PIN" --setting "smoke_steps=$SMOKE_STEPS"
}

verify_inference() {
  local reverse="${3%.tif}_reverse.tif" receipt="$3.binding.json"
  [[ -f "$3" && -f "$reverse" ]] || { echo "partial or missing inference cache: complete base or choose fresh OUT" >&2; exit 2; }
  "$PY" "$J/protocol.py" "$receipt" --input "$1" --input "$2" --input "$3" --input "$reverse" \
    --setting "villa=$VILLA_PIN" --setting "inference=overlap0.5,hann,batch8,both,no-compile"
}
infer() {  # Both directions and their binding are required for cache reuse.
  local reverse="${3%.tif}_reverse.tif" receipt="$3.binding.json"
  if [[ -e "$3" || -e "$reverse" || -e "$receipt" ]]; then
    verify_inference "$1" "$2" "$3"
  else
    (cd "$W" && "$PY" -m vesuvius.ink_detection.inference.infer "$1" "$2" "$3" \
      --overlap 0.5 --blend-mode hann --batch-size 8 --no-compile --direction both > "$3.log" 2>&1)
    [[ -f "$3" && -f "$reverse" ]] || { echo "inference did not write both controls" >&2; exit 2; }
    "$PY" "$J/protocol.py" "$receipt" --create --input "$1" --input "$2" --input "$3" --input "$reverse" \
      --setting "villa=$VILLA_PIN" --setting "inference=overlap0.5,hann,batch8,both,no-compile"
  fi
}
score() {  # score MODEL SEG KIND(""|_shuf)
  local m=$1 seg=$2 kind=$3 f="$O/scores/${1}_${2}${3}.json"
  if [[ -f "$f" ]]; then echo "score cache requires fresh OUT; refusing silent reuse" >&2; exit 2; fi
  local cmp=(); [[ $m == base ]] || cmp=(--compare "$O/maps/base_${seg}${kind}.tif")
  (cd "$REPO" && $PY -m kit auc "$O/maps/${m}_${seg}${kind}.tif" --control "$O/maps/${m}_${seg}${kind}_reverse.tif" \
    --labels "${LB[$seg]}/inklabels.zarr" --mask "${LB[$seg]}/supervision.zarr" --level 2 \
    --crop ${CR[$seg]} --surface-shape ${SH[$seg]} --inner 64 --keep-zero --bootstrap 300 "${cmp[@]}" --json) > "$f.tmp" && mv "$f.tmp" "$f"
}
verify_crops() {
  local seg kind y0 y1 x0 x1
  for seg in 0841-w00 w045; do
    read -r y0 y1 x0 x1 <<< "${CR[$seg]}"
    for kind in stored shuffled; do
      "$PY" "$J/protocol.py" "$O/crops/${seg}_$kind.zarr" --input "${SV[$seg]}" \
        --crop "$y0" "$y1" "$x0" "$x1" --kind "$kind" --verify-only
    done
  done
}
gpu_check() { binding; verify_crops; [[ "$(git -C "$W/villa" rev-parse HEAD)" == "$VILLA_PIN" ]] || { echo "villa source changed" >&2; exit 2; }; "$PY" -c "import torch; assert torch.cuda.is_available(), 'no CUDA'; print(torch.cuda.get_device_name(0))" | tee "$O/logs/gpu_$TAG.txt"; }

prepare() {
  mark data_fetch start
  [[ -d "$W/villa/.git" ]] || git clone -q --filter=blob:none --no-checkout https://github.com/ScrollPrize/villa.git "$W/villa"
  git -C "$W/villa" fetch -q origin "$VILLA_PIN"
  git -C "$W/villa" checkout -q --detach "$VILLA_PIN"
  [[ -x "$PY" ]] || uv venv -q --python 3.14 "$W/venv"
  "$PY" -c 'import sys; assert sys.version_info[:2] == (3,14), "villa pin requires Python3.14"'
  "$PY" - "$W/villa/vesuvius/pyproject.toml" > "$W/laneH-models-reqs.txt" <<'PYEOF'
import sys,tomllib
skip = ("volume-cartographer", "cucim", "nnunetv2", "batchgeneratorsv2")
for req in tomllib.load(open(sys.argv[1], "rb"))["project"]["optional-dependencies"]["models"]:
    if not req.startswith(skip): print(req)
PYEOF
  uv pip install -q --python "$PY" -e "$W/villa/vesuvius" -r "$W/laneH-models-reqs.txt" tifffile imagecodecs scipy huggingface_hub
  uv pip freeze --python "$PY" > "$O/logs/dependencies.txt"
  mkdir -p "$W/data" "$W/checkpoints/ink_9um"
  for seg in 0841-w00 w045; do
    local source label_source
    if [[ "$seg" == 0841-w00 ]]; then
      source=PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr
      label_source=PHerc0841/segments/20260220213127-w00/ink-labels/2.403um-volume-20260319124803/20260918
    else
      source=w045
      label_source=PHerc0139/segments/20260126000000-w045_2026012619/ink-labels/2.399um-volume-20260102150214/20260918
    fi
    "$PY" -m kit fetch "$source" "${SV[$seg]}"
    for store in inklabels supervision; do "$PY" -m kit fetch "$label_source/$store.zarr" "${LB[$seg]}/$store.zarr"; done
  done
  [[ -f "$BASE" ]] || uvx --from huggingface_hub hf download scrollprize/ink_9um hybrid_3d2d-seed42/step-075000.pth \
    --revision "$MODEL_PIN" --local-dir "$W/checkpoints/ink_9um"
  [[ "$(sha256sum "$BASE" | cut -d ' ' -f 1)" == "$BASE_SHA" ]] || { echo "checkpoint digest mismatch" >&2; exit 2; }
  binding create
  sha256sum "$BASE" > "$O/logs/base_sha256.txt"
  mark data_fetch end; mark crops start
  # test crops: as stored, and depth-shuffled with a fixed permutation (seed 20261007)
  for seg in 0841-w00 w045; do
  read y0 y1 x0 x1 <<< "${CR[$seg]}"
  for kind in stored shuffled; do
    "$PY" "$J/protocol.py" "$O/crops/${seg}_$kind.zarr" --input "${SV[$seg]}" \
      --crop "$y0" "$y1" "$x0" "$x1" --kind "$kind"
  done
done

  mark crops end
}

base_phase() {
  gpu_check
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
FT=(--execute --allow-gpu --device cuda --villa-root "$W/villa" --epochs 3 --steps-per-epoch 400 --batch-size 8 --lr 1e-5 --gap 64 "${EXTRA[@]}")
w00c=(${CR[0841-w00]}); w45c=(${CR[w045]})
train() { local name=$1; shift; [[ ! -e "$O/ckpt/$name" ]] || { echo "training output exists; choose fresh OUT" >&2; exit 2; }; \
  (cd "$W" && $PY "$J/finetune_ink9um.py" --checkpoint "$BASE" --out "$O/ckpt/$name" "$@" "${FT[@]}" > "$O/logs/train_$name.log" 2>&1); }

variant_phase() {
  local m=$1; gpu_check
  # Check the teacher and all comparator maps before any training or new inference.
  verify_inference "${SV[0841-w00]}" "$BASE" "$O/maps/base_full_0841-w00.tif"
  local seg
  for seg in 0841-w00 w045; do
    verify_inference "$O/crops/${seg}_stored.zarr" "$BASE" "$O/maps/base_${seg}.tif"
    verify_inference "$O/crops/${seg}_shuffled.zarr" "$BASE" "$O/maps/base_${seg}_shuf.tif"
  done
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
  $PY "$J/collect.py" "$O" "$O/results.json" "$SMOKE_STEPS"; say "results in $O/results.json"
fi
