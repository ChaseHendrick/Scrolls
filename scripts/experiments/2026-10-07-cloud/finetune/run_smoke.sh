# Cloud job `finetune`: run scripts/experiments/2026-10-07-tricks/finetune_smoke.sh unchanged and
# record wall time and memory. A sampler writes, every 2 s, the summed RSS of all processes started
# from the fine-tune venv (trainer plus data-loader workers) to mem.log; the peak is printed at the end.
#   TRAIN_SRC=<clone of YoussefMoNader/ink-8um-v8in-pherc1447-loo-w062> FT=<work dir> bash run_smoke.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
FT="${FT:-$HOME/scrolls-cpu/ft}"; export FT
: "${TRAIN_SRC:?pass TRAIN_SRC}"; export TRAIN_SRC
mkdir -p "$FT"
(
  while true; do
    kb=$(ps -eo rss=,args= | awk -v v="$FT/venv/bin/python" 'index($0, v) {s += $1} END {print s + 0}')
    echo "$(date +%s) $kb" >> "$FT/mem.log"
    sleep 2
  done
) &
SAMPLER=$!
t0=$(date +%s)
bash "$REPO/scripts/experiments/2026-10-07-tricks/finetune_smoke.sh"
rc=$?
kill "$SAMPLER" 2>/dev/null
echo "exit=$rc wall=$(( $(date +%s) - t0 )) s"
awk '$2 > m {m = $2} END {printf "peak summed RSS %.2f GB\n", m / 1048576}' "$FT/mem.log"
exit $rc
