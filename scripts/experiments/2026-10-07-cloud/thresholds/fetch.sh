#!/usr/bin/env bash
# thresholds job: after the budget cut (2026-10-07), ag896 and ag405 skip the SMOKE run; this fetches only their
# surface volume and labels, with the same kit fetch calls and bucket paths as scripts/mac-w045.sh.
set -uo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
W="${WORK:-$HOME/scrolls-work}"; PY="$W/venv/bin/python"
until [[ -x "$PY" ]]; do sleep 30; done
for s in 0841-ag896:PHerc0841/segments/20260220214732-auto_grown_20260220144552896 \
         0841-ag405:PHerc0841/segments/20260221022814-auto_grown_20260220174252405; do
  seg=${s%%:*}; SEG=${s#*:}
  [[ -f "$W/data/${seg}_labels/.fetched" ]] && continue
  echo "== $seg fetch $(date -u +%H:%M:%S)"
  (cd "$SCROLLS" && "$PY" -m kit fetch "$SEG/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr" "$W/data/${seg}_9um.zarr") || { echo "== $seg fetch FAILED"; continue; }
  for z in inklabels supervision; do
    (cd "$SCROLLS" && "$PY" -m kit fetch "$SEG/ink-labels/2.403um-volume-20260319124803/20260918/$z.zarr" "$W/data/${seg}_labels/$z.zarr" --workers 8) || { echo "== $seg labels FAILED"; continue 2; }
  done
  touch "$W/data/${seg}_labels/.fetched"; echo "== $seg fetched $(date -u +%H:%M:%S)"
done
