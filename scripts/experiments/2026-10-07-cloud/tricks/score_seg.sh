# Score every tricks map of one crop with the tricks score.py; saves $S/tricks/scores_<seg>.json.
set -euo pipefail
seg=$1; S="${S:-$HOME/scrolls-cpu}"; PY=$S/smoke-work/venv/bin/python
HERE="$(cd "$(dirname "$0")" && pwd)"; SCORE=$HERE/../../2026-10-07-tricks/score.py
args=()
for r in s42 soup42 d9v2 rv2; do
  base=$r; [ $r = s42 ] && base=ink9um_s42
  args+=("$r=$base")
  for w in z0-20 z3-23 z5-25 z8-27; do args+=("${r}_$w=${r}_$w"); done
  args+=("${r}_zmean=${r}_z0-20,${r}_z3-23,${r}_z5-25,${r}_z8-27")
  args+=("${r}_shuf=${r}_shuf")
done
args+=(s42_tta=s42_tta d9v2_tta=d9v2_tta
  "d9v2+s42_mean=d9v2,ink9um_s42" "d9v2+s42_rank=d9v2,ink9um_s42:rank"
  "d9v2+rv2_mean=d9v2,rv2" "d9v2+rv2_rank=d9v2,rv2:rank")
S=$S $PY $SCORE SEGS=$seg "${args[@]}" &
pid=$!; wait $pid
mv $S/tricks/scores_$pid.json $S/tricks/scores_$seg.json
echo "scored $seg"
