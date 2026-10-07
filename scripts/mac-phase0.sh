#!/usr/bin/env bash
# Phase 0 on the Mac in one command: every reader x PHerc0841 crop not scored yet, one at a time
# (scripts/mac-w045.sh with QUICK=1), then the Gate A table (python -m kit gate).
#
#   bash scripts/mac-phase0.sh                 # from the Scrolls checkout; about 20 min per job
#   JOBS="v8in:0841-ag896 v8in:0841-ag405" bash scripts/mac-phase0.sh   # a chosen queue
#   KEEP_GOING=1 bash scripts/mac-phase0.sh    # a failed job does not stop the queue
#   DRY_RUN=1 bash scripts/mac-phase0.sh       # print what would run, run nothing
#
# Resumable: a job whose score is already in WORK/<segment>/results (the standard crop, 64 px
# edge) is skipped, so Ctrl-C and a rerun lose at most the job in progress (and mac-w045.sh
# reuses that job's finished passes too). The Mac stays awake while it runs (caffeinate; closing
# the lid still sleeps it). A notification says when the queue is done or a job failed.
# Logs: WORK/logs/phase0_<segment>_<model>.log. Gate table: WORK/phase0-gate.txt.
set -euo pipefail

SCROLLS="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$HOME/scrolls-work}"
JOBS="${JOBS:-v8in:0841-w00 v8in:0841-ag896 v8in:0841-ag405 v8in-1447:0841-w00 v8in-1447:0841-ag896 v8in-1447:0841-ag405}"
KEEP_GOING="${KEEP_GOING:-0}"
DRY_RUN="${DRY_RUN:-0}"
KPY="$(command -v python3)"   # kit gate is standard library only
mkdir -p "$WORK/logs"

say() { printf '\n== %s\n' "$*"; }
notify() {  # a macOS notification when possible; always a line in the terminal
  echo "$1"
  command -v osascript >/dev/null 2>&1 && osascript -e "display notification \"$1\" with title \"Scrolls Phase 0\"" >/dev/null 2>&1 || true
}
reader_name() { case "$1" in v8in) echo v8in ;; v8in-1447) echo v8in-1447 ;; *) echo "$1" ;; esac; }
scored() {  # scored MODEL SEGMENT: true when kit gate already has this cell from the Mac
  PYTHONPATH="$SCROLLS" "$KPY" - "$WORK" "$(reader_name "$1")" "$2" <<'EOF'
import sys
from kit import gate
_, crops = gate.committed()
mac, _ = gate.from_mac(sys.argv[1], crops)
sys.exit(0 if sys.argv[3] in mac.get(sys.argv[2], {}) else 1)
EOF
}

for job in $JOBS; do
  case "$job" in
    v8in:0841-*|v8in-1447:0841-*) ;;
    *) echo "unknown job $job (expected v8in|v8in-1447:0841-w00|0841-ag896|0841-ag405)" >&2; exit 2 ;;
  esac
done

if [[ "$DRY_RUN" != 1 ]] && command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i -w $$ >/dev/null 2>&1 &   # no idle sleep until this script exits
fi

total=0; for job in $JOBS; do total=$((total + 1)); done
n=0; ran=0; failed=""
START=$SECONDS
for job in $JOBS; do
  n=$((n + 1))
  model="${job%%:*}"; seg="${job#*:}"
  if scored "$model" "$seg"; then
    echo "[$n/$total] $model on $seg: already scored, skipped"
    continue
  fi
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "[$n/$total] $model on $seg: would run MODEL=$model SEGMENT=$seg QUICK=1 bash scripts/mac-w045.sh"
    continue
  fi
  say "[$n/$total] $model on $seg (about 20 min; log $WORK/logs/phase0_${seg}_${model}.log)"
  t=$SECONDS
  if MODEL="$model" SEGMENT="$seg" QUICK=1 bash "$SCROLLS/scripts/mac-w045.sh" 2>&1 | tee "$WORK/logs/phase0_${seg}_${model}.log"; then
    ran=$((ran + 1))
    echo "[$n/$total] $model on $seg: done in $(( (SECONDS - t) / 60 )) min"
  else
    failed="$failed $model:$seg"
    notify "$model on $seg failed after $(( (SECONDS - t) / 60 )) min; see its log"
    [[ "$KEEP_GOING" == 1 ]] || { echo "Stopping (KEEP_GOING=1 to continue past failures). Rerun to resume." >&2; exit 1; }
  fi
done

say "Gate A"
set +e
PYTHONPATH="$SCROLLS" "$KPY" -m kit gate "$WORK" | tee "$WORK/phase0-gate.txt"
GATE=${PIPESTATUS[0]}
set -e
[[ "$DRY_RUN" == 1 ]] && exit 0
if [[ -n "$failed" ]]; then
  notify "Phase 0: $ran job(s) ran, failed:$failed"
  exit 1
fi
notify "Phase 0 done: $ran job(s) in $(( (SECONDS - START) / 60 )) min. Gate table in $WORK/phase0-gate.txt"
exit "$GATE"
