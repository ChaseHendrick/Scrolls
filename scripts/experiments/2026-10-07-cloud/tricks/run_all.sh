# The tricks job, one crop at a time: crops and bars, tricks, Reader v2, score, collect.
# Resumable: finished maps are skipped. nohup bash run_all.sh > $S/run_all.log 2>&1 &
# (Commits and pushes after each crop are done by hand, not from this script.)
set -uo pipefail
S="${S:-$HOME/scrolls-cpu}"; export S
HERE="$(cd "$(dirname "$0")" && pwd)"
for seg in ${ORDER:-0841-w00 0841-ag896 0841-ag405 w045}; do
  echo "#### $seg start $(date -u +%FT%TZ)"
  SEGS=$seg bash $HERE/crops_and_bars.sh || { echo "crops_and_bars failed on $seg"; continue; }
  SEGS=$seg bash $HERE/tricks.sh || { echo "tricks failed on $seg"; continue; }
  SEGS=$seg bash $HERE/reader_v2.sh || { echo "reader_v2 failed on $seg"; continue; }
  bash $HERE/score_seg.sh $seg || { echo "score failed on $seg"; continue; }
  $S/smoke-work/venv/bin/python $HERE/collect.py $S/run_all.log || echo "collect failed"
  echo "#### $seg done $(date -u +%FT%TZ)"
done
echo "RUN_ALL DONE $(date -u +%FT%TZ)"
