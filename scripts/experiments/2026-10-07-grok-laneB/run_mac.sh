#!/bin/bash
# lane B runs, 2026-10-07; resumable
set -o pipefail
PY=$HOME/scrolls-work/venv/bin/python
R=$HOME/scrolls-work/laneB/repo; D=$HOME/scrolls-work/laneB/data; O=$HOME/scrolls-work/laneB/out   # repo subset and data links (see the log)
M=$HOME/scrolls-work/0841-w00/maps; M45=$HOME/scrolls-work/w045/maps
C=$R/scripts/experiments/2026-10-07-grok-laneB/checks.py
TEAM=$(ls $D/inkdet/w00/*.tif)
L0=$D/0841-w00_labels; L45=$D/w045_labels
cd $R
run() { out=$1; shift; [ -s $O/$out ] && return; echo "== $out $(date)"; /usr/bin/time -l nice -n 10 $PY "$@" > $O/$out.tmp 2> $O/$out.log && mv $O/$out.tmp $O/$out; }
run auc_w00_s42.json -m kit auc $M/ink9um_s42.tif --control $M/ink9um_s42_reverse.tif --labels $L0/inklabels.zarr --mask $L0/supervision.zarr --level 2 --bootstrap 300 --json
run auc_w00_s43.json -m kit auc $M/ink9um_s43.tif --control $M/ink9um_s43_reverse.tif --labels $L0/inklabels.zarr --mask $L0/supervision.zarr --level 2 --bootstrap 300 --json
run auc_w045_s42.json -m kit auc $M45/ink9um_s42.tif --control $M45/ink9um_s42_reverse.tif --labels $L45/inklabels.zarr --mask $L45/supervision.zarr --level 2 --bootstrap 300 --json
run checks_w00_s42.json $C $D 0841-w00 $M/ink9um_s42.tif --control $M/ink9um_s42_reverse.tif --mesh $D/mesh/w00
run checks_w00_team.json $C $D 0841-w00 "$TEAM" --mesh $D/mesh/w00
run checks_w045_s42.json $C $D w045 $M45/ink9um_s42.tif --control $M45/ink9um_s42_reverse.tif
echo "== done $(date)"
