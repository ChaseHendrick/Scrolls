#!/usr/bin/env bash
# One command, on an Apple Silicon Mac: is villa's ink inference on the Mac GPU (MPS, villa
# PR #1865) the same as on the CPU? Runs the PHerc0139 w035 control (a segment the released
# model was trained on) on the CPU with stock villa main, twice on MPS with PR #1865, then
# `kit verify` twice. Paste the summary it prints. See docs/mac.md.
#
#   bash scripts/mac-verify.sh            # from the Scrolls checkout
#   WORK=/Volumes/big/scrolls-work bash scripts/mac-verify.sh
#
# Needs: git, uv (brew install uv), about 3 GB free in $WORK. Nothing is uploaded.
# EXPECT_GPU=cpu lets the script run on a machine without MPS (used to test the script itself).
set -euo pipefail

SCROLLS="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$HOME/scrolls-work}"
VILLA="$WORK/villa"
PY="$WORK/venv/bin/python"
CKPT="$WORK/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth"
ZARR="$WORK/data/w035_9um.zarr"
PRED="$WORK/predictions"
EXPECT_GPU="${EXPECT_GPU:-mps}"
PR=1865

say() { printf '\n== %s\n' "$*"; }

if [[ "$EXPECT_GPU" == "mps" && "$(uname -s)/$(uname -m)" != "Darwin/arm64" ]]; then
  echo "This needs an Apple Silicon Mac (or EXPECT_GPU=cpu to test the script elsewhere)." >&2
  exit 2
fi
command -v git >/dev/null || { echo "git is missing (xcode-select --install)" >&2; exit 2; }
command -v uv >/dev/null || { echo "uv is missing: brew install uv" >&2; exit 2; }
mkdir -p "$WORK"/{checkpoints,data,logs,results} "$PRED"

say "1/6 villa: main and PR #$PR"
if [[ ! -d "$VILLA/.git" ]]; then
  git clone -q --filter=blob:none https://github.com/ScrollPrize/villa.git "$VILLA"
fi
git -C "$VILLA" fetch -q origin main "+pull/$PR/head:pr-$PR"
MAIN_SHA="$(git -C "$VILLA" rev-parse --short origin/main)"
PR_SHA="$(git -C "$VILLA" rev-parse --short "pr-$PR")"

say "2/6 Python 3.14 environment (villa's models stack, without its C++ volume-cartographer package)"
[[ -x "$PY" ]] || uv venv -q --python 3.14 "$WORK/venv"
git -C "$VILLA" checkout -q --detach origin/main
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

infer() {  # infer OUTPUT LOG [extra args]
  local out="$1" log="$2"; shift 2
  local start=$SECONDS
  (cd "$WORK" && "$PY" -m vesuvius.ink_detection.inference.infer "$ZARR" "$CKPT" "$out" \
     --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile "$@") >"$log" 2>&1 \
    || { echo "inference failed, see $log" >&2; tail -20 "$log" >&2; exit 1; }
  echo "$(( SECONDS - start ))"
}

say "4/6 CPU reference on villa main ($MAIN_SHA), both depth directions"
git -C "$VILLA" checkout -q --detach origin/main
T_CPU="$(infer "$PRED/w035_cpu.tif" "$WORK/logs/cpu.log" --direction both)"
echo "CPU: ${T_CPU}s for both directions"

say "5/6 PR #$PR ($PR_SHA): two runs on $EXPECT_GPU"
git -C "$VILLA" checkout -q --detach "pr-$PR"
T_A="$(infer "$PRED/w035_gpu_a.tif" "$WORK/logs/gpu_a.log")"
T_B="$(infer "$PRED/w035_gpu_b.tif" "$WORK/logs/gpu_b.log")"
git -C "$VILLA" checkout -q --detach origin/main
for log in gpu_a gpu_b; do  # no silent CPU fallback: the run must say which device it used
  if [[ "$EXPECT_GPU" == "mps" ]]; then
    grep -q "Using MPS device" "$WORK/logs/$log.log" || { echo "$log did not run on MPS; see $WORK/logs/$log.log" >&2; exit 1; }
  fi
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
print("villa main $MAIN_SHA (CPU) | PR #$PR $PR_SHA ($EXPECT_GPU) | ckpt seed42 step-075000 sha256 $CKPT_SHA")
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
