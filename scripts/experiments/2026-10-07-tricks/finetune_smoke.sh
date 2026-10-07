# CPU smoke test of v8in's PHerc1447 fine-tune loop (YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062,
# training/finetune_loo_w062.py): 2 training batches and 2 validation batches, to check that the
# loop installs and runs before any GPU is rented. It says nothing about model quality.
# The script hard-codes --accelerator gpu --precision 16-mixed; this runs a scratch copy patched to
# read FT_ACCEL, FT_PRECISION and FT_LIMIT_VAL from the environment. Linux or macOS; about 3 GB.
#   FT=~/scrolls-cpu/ft TRAIN_SRC=<clone of the fine-tune repo> bash finetune_smoke.sh
set -euo pipefail
FT="${FT:-$HOME/scrolls-cpu/ft}"; TRAIN_SRC="${TRAIN_SRC:?clone https://huggingface.co/YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062 and pass its path}"
mkdir -p "$FT" && cd "$FT"
[ -x venv/bin/python ] || uv venv -q --python 3.12 venv
grep -v -E "^torch==|^torchvision==|^#|^$" "$TRAIN_SRC/training/requirements.txt" > reqs-rest.txt
uv pip install -q --python venv/bin/python --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 torchvision==0.23.0
uv pip install -q --python venv/bin/python -r reqs-rest.txt
rm -rf training && cp -r "$TRAIN_SRC/training" training
venv/bin/python - <<'PY'
p = "training/finetune_loo_w062.py"; s = open(p).read()
old = '"--devices", "1", "--accelerator", "gpu", "--precision", "16-mixed",'
assert old in s, "the script changed; patch it by hand"
s = s.replace(old, '"--devices", "1", "--accelerator", os.environ.get("FT_ACCEL", "gpu"), "--precision", os.environ.get("FT_PRECISION", "16-mixed"),')
old = '        argv += ["--limit_train_batches", str(args.smoke_test)]\n'
s = s.replace(old, old + '    if os.environ.get("FT_LIMIT_VAL"):\n        argv += ["--limit_val_batches", os.environ["FT_LIMIT_VAL"]]\n')
open(p, "w").write(s)
PY
INIT=$(venv/bin/python -c "from huggingface_hub import hf_hub_download as d; print(d('YoussefMoNader/ink-8um-v8in', 'model.safetensors', revision='d89166b41a3f5fad7749b3d7c0fdd1bd3695d844'))")
t=$SECONDS
FT_ACCEL=cpu FT_PRECISION=32 FT_LIMIT_VAL=2 NO_ALBUMENTATIONS_UPDATE=1 venv/bin/python training/finetune_loo_w062.py \
  --output-dir runs/smoke --init "$INIT" --smoke-test 2 > smoke_run.log 2>&1 && echo "smoke passed in $((SECONDS - t)) s" \
  || { echo "smoke FAILED after $((SECONDS - t)) s; see $FT/smoke_run.log"; tail -30 smoke_run.log; exit 1; }
