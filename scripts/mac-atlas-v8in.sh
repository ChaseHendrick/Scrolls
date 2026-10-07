#!/usr/bin/env bash
# First Letters target run, on an Apple Silicon Mac: v8in on the 81 public automatic meshes of
# PHerc0813, PHerc0358 and PHerc0826 (rodriguescarson's eligible-scroll-atlas renders), both depth
# directions. Preregistered in docs/prereg/2026-10-07-v8in-atlas.md; this script copies that rule
# into the local ledger before the first inference and refuses to run on a different one.
#
#   bash scripts/mac-w045.sh          # first: sets up $WORK and checks v8in on MPS against the CPU
#   bash scripts/mac-atlas-v8in.sh    # then this; resumable, already-finished meshes are skipped
#   ATLAS_HOURS=12 bash scripts/mac-atlas-v8in.sh   # budget: picks the stride from w045's measured speed (default 12)
#   V8IN_STRIDE=42 bash scripts/mac-atlas-v8in.sh   # or set the stride (v8in's own is 21)
#   ONLY="PHerc0813/z8288_w020 PHerc0358/z11280_w020" bash scripts/mac-atlas-v8in.sh   # a subset
#   SECOND_STRIDE=21 ONLY="PHerc0813/z8288_w020" bash scripts/mac-atlas-v8in.sh     # the rule's re-run
#
# Maps stay in $WORK/atlas, outside the repository. The summary it prints is model output on
# eligible scrolls: do not post it publicly before you have looked (docs/WORKFLOW.md).
# Needs about 2 GB free at a time (each mesh's volume is deleted after inference).
# EXPECT_GPU=cpu runs without MPS (used to test the script itself).
set -euo pipefail
unset PYTORCH_ENABLE_MPS_FALLBACK

SCROLLS="$(cd "$(dirname "$0")/.." && pwd)"
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WORK="${WORK:-$HOME/scrolls-work}"
PY="$WORK/venv/bin/python"
V8IN="$WORK/checkpoints/ink-8um-v8in"
EXPECT_GPU="${EXPECT_GPU:-mps}"
STRIDE="${SECOND_STRIDE:-${V8IN_STRIDE:-}}"
ATLAS_REV=0c0566ccd07652ef4bc9fa1926491983d520942f
MANIFEST_URL="https://raw.githubusercontent.com/rodriguescarson/eligible-scroll-atlas/$ATLAS_REV/data/manifest.csv"
RENDERS="https://huggingface.co/datasets/rodriguescarson/eligible-scroll-atlas-renders/resolve/main"
SCROLL_SET="PHerc0813 PHerc0358 PHerc0826"
SLUG=v8in-atlas-0813-0358-0826
# Overridden only to test the script on non-target data (file:// URLs work):
MANIFEST_URL="${TEST_MANIFEST_URL:-$MANIFEST_URL}"; RENDERS="${TEST_RENDERS:-$RENDERS}"
SCROLL_SET="${TEST_SCROLL_SET:-$SCROLL_SET}"; SLUG="${TEST_SLUG:-$SLUG}"
PREREG="$SCROLLS/docs/prereg/2026-10-07-v8in-atlas.md"
OUT="$WORK/atlas"

say() { printf '\n== %s\n' "$*"; }
sha() { local s; s="$(shasum -a 256 "$1" 2>/dev/null || sha256sum "$1")"; echo "${s%% *}"; }

[[ -x "$PY" && -f "$V8IN/model.safetensors" ]] || { echo "Run scripts/mac-w045.sh first: it builds $WORK and downloads v8in." >&2; exit 2; }
V8IN_DEVICE=mps
if [[ "$EXPECT_GPU" == "mps" ]]; then
  "$PY" - "$WORK/w045/results/v8in_device.json" <<'EOF' || { echo "v8in has not passed the CPU vs MPS check (scripts/mac-w045.sh step 5)." >&2; exit 2; }
import json, sys
sys.exit(0 if json.load(open(sys.argv[1]))["verdict"] == "pass" else 1)
EOF
else
  V8IN_DEVICE=cpu
fi
MEM_GB="$(( $(sysctl -n hw.memsize 2>/dev/null || awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo) / 1073741824 ))"
if [[ -n "${V8IN_BATCH:-}" ]]; then BATCH="$V8IN_BATCH"
elif (( MEM_GB <= 16 )); then BATCH=4
elif (( MEM_GB <= 32 )); then BATCH=8
else BATCH=16; fi
FLAGS=(--batch-size "$BATCH")
[[ "${V8IN_FP16:-0}" == "1" && "$V8IN_DEVICE" == "mps" ]] && FLAGS+=(--fp16)
mkdir -p "$OUT"
# One GPU job at a time: two v8in runs at once do not fit in 16 GB and swap (seen 2026-10-07:
# 56 s per tile instead of 1.3). Both Mac scripts share this lock; a lock whose process is gone
# is taken over.
LOCK="$WORK/.gpu-job.lock"
mkdir -p "$WORK"
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
# Keep the Mac awake while this runs (an idle sleep would pause inference; closing the lid still sleeps it).
command -v caffeinate >/dev/null 2>&1 && { caffeinate -i -w $$ >/dev/null 2>&1 & }
cd "$SCROLLS"

say "1/4 preregistration: $PREREG"
READOUT="$("$PY" - "$PREREG" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"<!-- readout:start -->\n(.*?)\n<!-- readout:end -->", text, re.S)
print(m.group(1).strip())
EOF
)"
if [[ ! -f "experiments/$SLUG/run.json" ]]; then
  "$PY" -m kit run init "$SLUG" --scroll PHerc0813 \
    --question "Does v8in show ink on the 81 public automatic meshes of PHerc0813, 0358 and 0826 (atlas $ATLAS_REV)?" \
    --readout "$READOUT"
  "$PY" -m kit run status "$SLUG" running --note "v8in d89166b on $V8IN_DEVICE"
fi
"$PY" - "experiments/$SLUG/run.json" "$READOUT" <<'EOF' || { echo "The ledger's readout rule differs from the preregistration; stopping." >&2; exit 2; }
import json, sys
sys.exit(0 if json.load(open(sys.argv[1]))["readout_rule"] == sys.argv[2] else 1)
EOF
echo "readout rule matches the ledger (sha256 $(printf %s "$READOUT" | (shasum -a 256 2>/dev/null || sha256sum) | cut -c1-16)...)"

say "2/4 mesh list (atlas $ATLAS_REV)"
curl -fsSL "$MANIFEST_URL" -o "$OUT/manifest.csv"
# Order: held-back meshes, then by Hecate rank, so a partial run has read the likeliest first.
MESHES="$("$PY" - "$OUT/manifest.csv" "$SCROLL_SET" "${ONLY:-}" <<'EOF'
import csv, sys
scrolls = set(sys.argv[2].split())
only = set(sys.argv[3].split())
rows = [r for r in csv.DictReader(open(sys.argv[1]))
        if r["scroll"] in scrolls and (not only or f"{r['scroll']}/{r['mesh']}" in only)]
for r in sorted(rows, key=lambda r: (r.get("maps_held") != "True", int(r.get("hecate_rank") or 10**6))):
    print(f"{r['scroll']}/{r['mesh']}")
EOF
)"
N="$(echo "$MESHES" | grep -c . || true)"
(( N > 0 )) || { echo "no meshes selected" >&2; exit 2; }
if [[ -z "$STRIDE" ]]; then   # finest stride that fits ATLAS_HOURS, from w045's crop timing
  STRIDE="$("$PY" - "$OUT/manifest.csv" "$MESHES" "$WORK/logs/w045_crop_gpu.log" "${ATLAS_HOURS:-12}" <<'EOF'
import csv, re, sys
keys = set(sys.argv[2].split())
px = sum(int(r.get("valid_px") or 0) for r in csv.DictReader(open(sys.argv[1])) if f"{r['scroll']}/{r['mesh']}" in keys)
try:
    m = re.search(r"tiles=(\d+) done in (\d+)s", open(sys.argv[3]).read())
    per_tile = float(m.group(2)) / int(m.group(1))
except (OSError, AttributeError, ZeroDivisionError):
    per_tile = None
choice = 64
for stride in (21, 32, 42, 64):
    tiles = 2 * px / stride ** 2                     # both directions
    known = per_tile is not None and px > 0
    print(f"stride {stride}: about {tiles:,.0f} tiles, "
          f"{f'{tiles * per_tile / 3600:.1f} h' if known else 'time unknown (no w045 timing)'}", file=sys.stderr)
    if known and tiles * per_tile <= float(sys.argv[4]) * 3600:
        choice = stride
        break
print(choice)
EOF
)"
fi
TAG="s$STRIDE"
FLAGS+=(--stride "$STRIDE")
echo "$N meshes, v8in on $V8IN_DEVICE, stride $STRIDE, batch $BATCH${V8IN_FP16:+, fp16 $V8IN_FP16}"

say "3/4 v8in, both directions (resumable)"
i=0
for key in $MESHES; do
  i=$(( i + 1 ))
  dir="$OUT/$key"
  if [[ -f "$dir/v8in_${TAG}_rev.tif" ]]; then
    echo "[$i/$N] $key: done earlier"
    continue
  fi
  mkdir -p "$dir"
  start=$SECONDS
  rm -rf "$dir/tmp" && mkdir -p "$dir/tmp"
  curl -fsSL --retry 4 "$RENDERS/$key/surface-volumes.tar" -o "$dir/tmp/sv.tar"
  # The volume is deleted after inference, so its hash is taken now, for the provenance record.
  printf '%s  %s\n' "$(sha "$dir/tmp/sv.tar")" "$key/surface-volumes.tar" > "$dir/input.sha256"
  tar xf "$dir/tmp/sv.tar" -C "$dir/tmp" && rm "$dir/tmp/sv.tar"
  zarr_path="$(find "$dir/tmp" -maxdepth 3 -name '*.zarr' -type d | head -1)"
  "$PY" -m kit layers "$zarr_path" "$dir/tmp/layers" > /dev/null
  for d in fwd rev; do
    extra=(); [[ "$d" == "rev" ]] && extra=(--reverse)
    "$PY" "$SCROLLS/scripts/v8in_run.py" --model-dir "$V8IN" --layers "$dir/tmp/layers" \
      --output "$dir/v8in_${TAG}_$d.npy" --device "$V8IN_DEVICE" "${FLAGS[@]}" ${extra[@]+"${extra[@]}"} \
      > "$dir/v8in_${TAG}_$d.log" 2>&1 \
      || { echo "$key $d failed, see $dir/v8in_${TAG}_$d.log" >&2; tail -20 "$dir/v8in_${TAG}_$d.log" >&2; exit 1; }
    "$PY" - "$dir/v8in_${TAG}_$d.npy" "$dir/v8in_${TAG}_$d.tif" <<'EOF'
import sys, numpy as np, tifffile
p = np.load(sys.argv[1])
tifffile.imwrite(sys.argv[2], np.round(np.clip(p, 0, 1) * 255).astype(np.uint8), compression="zlib")
EOF
    rm "$dir/v8in_${TAG}_$d.npy"
  done
  rm -rf "$dir/tmp"
  echo "[$i/$N] $key: $(( SECONDS - start ))s"
done

say "4/4 triage (row score: a reading order, not a verdict)"
"$PY" -m kit run record "$SLUG" --command "bash scripts/mac-atlas-v8in.sh (stride $STRIDE, $V8IN_DEVICE, batch $BATCH)" \
  --file "$V8IN/model.safetensors" > /dev/null
"$PY" - "$OUT" "$TAG" "$MESHES" <<'EOF' > "$OUT/triage_$TAG.tsv"
import json, subprocess, sys
out, tag, meshes = sys.argv[1], sys.argv[2], sys.argv[3].split()
from kit import prizes                                   # each scroll's own voxel size sets the row band
snap = prizes.load()
voxel = lambda key: str(prizes.eligible_entry(snap, key.split("/")[0])["voxel_um"]) if prizes.eligible_entry(snap, key.split("/")[0]) else "9.362"
print("mesh\trow_fwd\trow_rev\tperiod_fwd_mm\tperiod_rev_mm")
for key in meshes:
    res = json.loads(subprocess.run([sys.executable, "-m", "kit", "rowscore", f"{out}/{key}/v8in_{tag}_fwd.tif",
                                     "--reverse", f"{out}/{key}/v8in_{tag}_rev.tif", "--voxel-um", voxel(key), "--json"],
                                    capture_output=True, text=True, check=True).stdout)
    f, r = res["forward"], res["reverse"]
    print(f"{key}\t{f.get('score')}\t{r.get('score')}\t{f.get('period_mm')}\t{r.get('period_mm')}")
EOF
"$PY" - "$OUT/triage_$TAG.tsv" <<'EOF'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1]), delimiter="\t"))
num = lambda v: float(v) if v not in ("None", "") else -1.0
held = {"PHerc0358/z11280_w020", "PHerc0813/z5888_w020", "PHerc0813/z7696_w020", "PHerc0813/z12496_w060", "PHerc0813/z13088_w040"}
look = set()
for col in ("row_fwd", "row_rev"):
    look |= {r["mesh"] for r in sorted(rows, key=lambda r: -num(r[col]))[:10]}
look |= held & {r["mesh"] for r in rows}
print(f"{len(rows)} meshes scored; the readout rule says look at these {len(look)} (top 10 per direction, plus held-back):")
for r in sorted(rows, key=lambda r: -max(num(r["row_fwd"]), num(r["row_rev"]))):
    if r["mesh"] in look:
        print(f"  {r['mesh']:<24} fwd {r['row_fwd']:>6}  rev {r['row_rev']:>6}{'  (held back by rodriguescarson)' if r['mesh'] in held else ''}")
EOF
# Provenance: operator, machine, times, code, the model, every mesh volume's hash and every map,
# as a private record (kept with the maps) and one digest. The digest alone reveals nothing and can
# be committed or published as a timestamped commitment; it is also stored in the ledger.
PROV=(--model "$V8IN/model.safetensors" --input "$OUT/manifest.csv" --output "$OUT/triage_$TAG.tsv")
for key in $MESHES; do
  for f in "$OUT/$key/input.sha256" "$OUT/$key/v8in_${TAG}_fwd.tif" "$OUT/$key/v8in_${TAG}_rev.tif"; do
    [[ -f "$f" ]] || continue
    [[ "$f" == *input.sha256 ]] && PROV+=(--input "$f") || PROV+=(--output "$f")
  done
done
"$PY" -m kit provenance write "$OUT/provenance_$TAG.json" --run "$SLUG stride $STRIDE" --repo "$SCROLLS" \
  --started "$STARTED_UTC" --note "atlas $ATLAS_REV" "${PROV[@]}" > "$OUT/provenance_$TAG.digest"
"$PY" -m kit run record "$SLUG" --command "provenance record for stride $STRIDE" --file "$OUT/provenance_$TAG.json" > /dev/null
echo "provenance: $(cat "$OUT/provenance_$TAG.digest")"
echo
echo "Maps: $OUT/<scroll>/<mesh>/v8in_${TAG}_{fwd,rev}.tif. Look privately, then record the verdict:"
echo "  python -m kit run status $SLUG null --note \"...\"        or        ... candidate --note \"...\""
echo "Do not post maps or this list publicly before deciding (docs/WORKFLOW.md section 3b)."
