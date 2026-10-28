#!/usr/bin/env bash
# One command, on an Apple Silicon Mac: is villa's ink inference on the Mac GPU (MPS) the same
# as on the CPU? villa main picks MPS by itself since PRs #1812 and #1865 merged. Runs the
# PHerc0139 w035 control (a segment the released model was trained on) with villa main at a
# pinned commit: once forced onto the CPU, twice on MPS, then `kit verify` twice. Every run's
# log must name the device it was meant to use. Paste the summary it prints. See docs/mac.md.
#
#   bash scripts/mac-verify.sh            # from the Scrolls checkout
#   WORK=/Volumes/big/scrolls-work bash scripts/mac-verify.sh
#
# Needs: git, uv (brew install uv), about 3 GB free in $WORK. Nothing is uploaded.
# EXPECT_GPU=cpu lets the script run on a machine without MPS (used to test the script itself):
# then every run is forced onto the CPU and checked to have run there.
# VILLA_REV=origin/main tries the newest villa main instead of the pinned commit.
set -euo pipefail
unset PYTORCH_ENABLE_MPS_FALLBACK   # an op MPS lacks must fail, not quietly run on the CPU

SCROLLS="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$HOME/scrolls-work}"
VILLA="$WORK/villa"
PY="$WORK/venv/bin/python"
CKPT="$WORK/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"
ZARR="$WORK/data/w035_9um.zarr"
PRED="$WORK/predictions"
EXPECT_GPU="${EXPECT_GPU:-mps}"
# villa main at a pinned commit, as the scripts pin model revisions: 860f52cbf is the merge of
# PR #1865 (ink inference picks its device with get_accelerator(): CUDA, then MPS, then the CPU),
# after #1812; its ink inference code matches the final head of PR #1865, which this script ran before.
VILLA_REV="${VILLA_REV:-860f52cbfccb6a878032de12467d5e2f3d995560}"
case "$EXPECT_GPU" in
  mps|cpu) ;;
  *) echo "EXPECT_GPU must be mps or cpu" >&2; exit 2 ;;
esac
GPU_ARM=auto; [[ "$EXPECT_GPU" == mps ]] || GPU_ARM=cpu

say() { printf '\n== %s\n' "$*"; }
# villa's ink inference has no device option (--gpus takes CUDA ids only); get_accelerator() picks
# CUDA, then MPS, then the CPU, and prints "Using ... device". The CPU arm runs villa's own entry
# point with MPS reported unavailable and CUDA hidden, so get_accelerator() falls through to the
# CPU; villa's code is unchanged.
CPU_ONLY='import functools, runpy, sys, torch
torch.backends.mps.is_available = functools.lru_cache(lambda: False)   # cached as torch caches it: torch._dynamo reads __wrapped__
sys.argv[0] = "vesuvius.ink_detection.inference.infer"
runpy.run_module("vesuvius.ink_detection.inference.infer", run_name="__main__", alter_sys=True)'
log_device() {  # log_device LOG: the device villa says it used (cpu, mps, cuda), or nothing
  grep -o -m1 -E 'Using (CPU|MPS|CUDA) device' "$1" 2>/dev/null | awk '{print tolower($2)}' || true
}
ran_on() {  # ran_on DEVICE LOG: stop unless villa's log names DEVICE (no silent fallback either way)
  local got; got="$(log_device "$2")"
  [[ "$got" == "$1" ]] || { echo "$2: villa ran on ${got:-an unnamed device}, expected $1; see the log" >&2; exit 1; }
}

if [[ "$EXPECT_GPU" == "mps" && "$(uname -s)/$(uname -m)" != "Darwin/arm64" ]]; then
  echo "This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere)." >&2
  exit 2
fi
command -v git >/dev/null || { echo "git is missing (xcode-select --install)" >&2; exit 2; }
command -v uv >/dev/null || { echo "uv is missing: brew install uv" >&2; exit 2; }
mkdir -p "$WORK"/{checkpoints,data,logs,results} "$PRED"
# One GPU job at a time, the same lock as mac-w045.sh: both scripts check out commits in the one
# villa clone and write under $WORK, so a second run at once would clobber the first. A lock whose
# process is gone is taken over.
LOCK="$WORK/.gpu-job.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  other="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [[ -n "$other" ]] && kill -0 "$other" 2>/dev/null; then
    echo "Another run is using the GPU (pid $other: $(ps -o command= -p "$other" 2>/dev/null | cut -c1-80))." >&2
    echo "Wait for it, or stop it: kill $other" >&2
    exit 3
  fi
  echo "Taking over a stale lock left by pid ${other:-unknown}."
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

say "1/6 villa main at $VILLA_REV"
if [[ ! -d "$VILLA/.git" ]]; then
  git clone -q --filter=blob:none https://github.com/ScrollPrize/villa.git "$VILLA"
fi
git -C "$VILLA" fetch -q origin main
git -C "$VILLA" rev-parse -q --verify "$VILLA_REV^{commit}" >/dev/null \
  && git -C "$VILLA" merge-base --is-ancestor "$VILLA_REV" origin/main \
  || { echo "villa main has no commit $VILLA_REV" >&2; exit 2; }
git -C "$VILLA" checkout -q --detach "$VILLA_REV"
VILLA_SHA="$(git -C "$VILLA" rev-parse --short HEAD)"

say "2/6 Python 3.14 environment (villa's models stack, without its C++ volume-cartographer package)"
[[ -x "$PY" ]] || uv venv -q --python 3.14 "$WORK/venv"
"$PY" - "$VILLA/vesuvius/pyproject.toml" > "$WORK/models-reqs.txt" <<'EOF'
import sys, tomllib
skip = ("volume-cartographer", "cucim", "nnunetv2", "batchgeneratorsv2")
for req in tomllib.load(open(sys.argv[1], "rb"))["project"]["optional-dependencies"]["models"]:
    if not req.startswith(skip):
        print(req)
EOF
uv pip install -q --python "$PY" -e "$VILLA/vesuvius" -r "$WORK/models-reqs.txt" tifffile imagecodecs
TORCH="$("$PY" -c 'import torch; print(torch.__version__, "mps available:", torch.backends.mps.is_available())')"
echo "torch $TORCH"

say "3/6 data: w035 surface volume (about 1 GB) and the seed42 checkpoint"
(cd "$SCROLLS" && "$PY" -m kit fetch w035 "$ZARR")
[[ -f "$CKPT" ]] || uvx -q --from huggingface_hub hf download scrollprize/ink_9um \
  hybrid_3d2d-seed42/step-075000.pth --local-dir "$WORK/checkpoints/ink_9um"
CKPT_SHA="$(shasum -a 256 "$CKPT" 2>/dev/null || sha256sum "$CKPT")"
CKPT_SHA="${CKPT_SHA%% *}"

infer() {  # infer cpu|auto OUTPUT LOG [extra args]: cpu forces the CPU, auto lets villa choose
  local dev="$1" out="$2" log="$3"; shift 3
  local start=$SECONDS run   # a local array, assigned apart from local for bash 3.2
  run=("$PY" -m vesuvius.ink_detection.inference.infer)
  [[ "$dev" == cpu ]] && run=(env CUDA_VISIBLE_DEVICES= "$PY" -c "$CPU_ONLY")
  (cd "$WORK" && "${run[@]}" "$ZARR" "$CKPT" "$out" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile "$@") >"$log" 2>&1 \
    || { echo "inference failed, see $log" >&2; tail -20 "$log" >&2; exit 1; }
  echo "$(( SECONDS - start ))"
}

say "4/6 CPU reference on villa $VILLA_SHA, forced onto the CPU, both depth directions"
T_CPU="$(infer cpu "$PRED/w035_cpu.tif" "$WORK/logs/cpu.log" --direction both)"
ran_on cpu "$WORK/logs/cpu.log"
echo "CPU: ${T_CPU}s for both directions"

say "5/6 villa $VILLA_SHA: two runs on $EXPECT_GPU"
T_A="$(infer "$GPU_ARM" "$PRED/w035_gpu_a.tif" "$WORK/logs/gpu_a.log")"
T_B="$(infer "$GPU_ARM" "$PRED/w035_gpu_b.tif" "$WORK/logs/gpu_b.log")"
for log in gpu_a gpu_b; do  # no silent CPU fallback: the run must say it used the expected device
  ran_on "$EXPECT_GPU" "$WORK/logs/$log.log"
done
echo "GPU runs: ${T_A}s and ${T_B}s (forward only)"

say "6/6 kit verify"
cd "$SCROLLS"
set +e
"$PY" -m kit verify "$PRED/w035_cpu.tif" "$PRED/w035_gpu_a.tif" --control "$PRED/w035_cpu_reverse.tif" \
  --json > "$WORK/results/cpu_vs_gpu.json"; V1=$?
"$PY" -m kit verify "$PRED/w035_gpu_a.tif" "$PRED/w035_gpu_b.tif" --control "$PRED/w035_cpu_reverse.tif" \
  --json > "$WORK/results/gpu_repeat.json"; V2=$?
set -e

CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m)"
OS="$(sw_vers -productVersion 2>/dev/null || uname -sr)"
"$PY" - "$WORK/results" > "$WORK/results/summary.txt" <<EOF
import json, sys, pathlib
r = pathlib.Path(sys.argv[1])
print("kit mac-verify summary (paste this)")
print("chip: $CHIP | os: $OS | torch: $TORCH")
print("villa main $VILLA_SHA | reference on cpu (forced) | runs on $EXPECT_GPU | ckpt seed42 step-075000 sha256 $CKPT_SHA")
print("times: cpu both directions ${T_CPU}s | gpu forward ${T_A}s, ${T_B}s")
for name, code in (("cpu_vs_gpu", $V1), ("gpu_repeat", $V2)):
    res = json.loads((r / f"{name}.json").read_text())
    c, k = res["candidate"], res.get("control", {})
    print(f"{name}: verdict {res['verdict']} (exit {code}) | max|diff| {c.get('max_abs_diff')} | "
          f"over tol {c.get('fraction_over_tolerance', 0):.6%} | pearson {c.get('pearson')} | "
          f"control over tol {k.get('fraction_over_tolerance', 0):.2%}")
EOF
say "summary (also in $WORK/results/summary.txt)"
cat "$WORK/results/summary.txt"
if [[ "$V1" != 0 || "$V2" != 0 ]]; then   # the summary above says why; the exit code must say it too
  echo "kit verify did not pass (cpu_vs_gpu exit $V1, gpu_repeat exit $V2); see the summary above and $WORK/results" >&2
  exit 1
fi
