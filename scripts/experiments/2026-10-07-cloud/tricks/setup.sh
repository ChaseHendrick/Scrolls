# Builds the $S layout of scripts/experiments/2026-10-07-tricks/README.md in a Linux container
# without running the Mac script's v8in smoke (this job needs no v8in). Resumable.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"
S="${S:-$HOME/scrolls-cpu}"; W=$S/smoke-work; PY=$W/venv/bin/python; VILLA=$W/villa
mkdir -p $W/checkpoints $S/data/p0841 $S/models/d9v2 $S/models/reader_v2 $S/tricks $S/readers
echo "== villa main + PR #1865, Python 3.14"
[ -d $VILLA/.git ] || git clone -q --filter=blob:none https://github.com/ScrollPrize/villa.git $VILLA
git -C $VILLA fetch -q origin main "+pull/1865/head:pr-1865"
[ -x $PY ] || uv venv -q --python 3.14 $W/venv
git -C $VILLA checkout -q --detach origin/main
$PY - $VILLA/vesuvius/pyproject.toml > $W/models-reqs.txt <<'PYEOF'
import sys, tomllib
skip = ("volume-cartographer", "cucim", "nnunetv2", "batchgeneratorsv2")
for req in tomllib.load(open(sys.argv[1], "rb"))["project"]["optional-dependencies"]["models"]:
    if not req.startswith(skip):
        print(req)
PYEOF
uv pip install -q --python $PY --index-strategy unsafe-best-match --extra-index-url https://download.pytorch.org/whl/cpu \
  -e $VILLA/vesuvius -r $W/models-reqs.txt tifffile imagecodecs scipy opencv-python-headless safetensors huggingface_hub
git -C $VILLA checkout -q --detach pr-1865
echo "villa main $(git -C $VILLA rev-parse --short origin/main), PR $(git -C $VILLA rev-parse --short pr-1865)"
echo "== data"
cd $REPO
declare -A SEGS=( [20260220213127-w00]=1 [20260220214732-auto_grown_20260220144552896]=1 [20260221022814-auto_grown_20260220174252405]=1 )
for s in "${!SEGS[@]}"; do
  B=PHerc0841/segments/$s; D=$S/data/p0841/$s
  $PY -m kit fetch $B/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr $D/sv.zarr
  for z in inklabels supervision; do $PY -m kit fetch $B/ink-labels/2.403um-volume-20260319124803/20260918/$z.zarr $D/$z.zarr --workers 8; done
done
B=PHerc0139/segments/20260126000000-w045_2026012619
$PY -m kit fetch w045 $S/data/w045_9um.zarr
for z in inklabels supervision; do $PY -m kit fetch $B/ink-labels/2.399um-volume-20260102150214/20260918/$z.zarr $S/data/w045_labels/$z.zarr --workers 8; done
echo "== checkpoints"
for st in 040000 050000 060000 075000; do
  f=$W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-$st.pth
  [ -s $f ] || { curl -sSfL --create-dirs -o $f.part https://huggingface.co/scrollprize/ink_9um/resolve/main/hybrid_3d2d-seed42/step-$st.pth && mv $f.part $f; }
done
f=$S/models/d9v2/d9v2_ft-012000.pth
[ -s $f ] || { curl -sSfL -o $f.part https://github.com/TAUIL-Abd-Elilah/pherc0826-first-letters-search/releases/download/v1.0/d9v2_ft-012000.pth && mv $f.part $f; }
f=$S/models/reader_v2/reader-v2-step040000.pth
[ -s $f ] || { curl -sSfL -o $f.part https://huggingface.co/domenicor046/reader-v2/resolve/main/reader-v2-step040000.pth && mv $f.part $f; }
sha256sum $W/checkpoints/ink_9um/hybrid_3d2d-seed42/*.pth $S/models/*/*.pth
echo "== soup"
[ -s $S/tricks/soup42_last4.pth ] || $PY scripts/soup.py $S/tricks/soup42_last4.pth $W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-0{4,5,6}0000.pth $W/checkpoints/ink_9um/hybrid_3d2d-seed42/step-075000.pth
sha256sum $S/tricks/soup42_last4.pth
echo SETUP DONE
