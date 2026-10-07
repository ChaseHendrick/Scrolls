#!/usr/bin/env bash
# thresholds job, step 0: one SMOKE run of scripts/mac-w045.sh per segment fetches the venv, villa,
# ink_9um checkpoints, surface volume and labels. Resumable: a segment whose smoke summary exists is skipped.
set -uo pipefail
SCROLLS="$(cd "$(dirname "$0")/../../../.." && pwd)"
W="${WORK:-$HOME/scrolls-work}"
for seg in 0841-w00 0841-ag896 0841-ag405; do   # w045 dropped 2026-10-07 (budget)
  if [[ -f "$W/${seg}-smoke/results/summary.txt" ]]; then echo "== $seg: setup done earlier"; continue; fi
  echo "== $seg: smoke setup $(date -u +%H:%M:%S)"
  SMOKE=1 EXPECT_GPU=cpu WORK="$W" SEGMENT="$seg" bash "$SCROLLS/scripts/mac-w045.sh" || echo "== $seg: smoke FAILED"
done
echo "== setup finished $(date -u +%H:%M:%S)"
