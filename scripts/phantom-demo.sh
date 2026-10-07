#!/bin/bash
# Demo of kit phantom and kit view on synthetic data only (no scroll data). Logs every command.
set -eu
OUT=${OUT:-/tmp/phantom-demo}
mkdir -p "$OUT"
LOG="$OUT/commands.log"
: > "$LOG"
run() { echo "\$ $*" >> "$LOG"; "$@" | tee -a "$LOG"; }
run python3 -m kit phantom make "$OUT/ph" --shape 256 256 --depth 16 --seed 7 --letter-px 64
run python3 -m kit phantom stress --shape 256 256 --depth 16 --seed 0 --n 4 --letter-px 64 --save-maps "$OUT/maps"
run python3 -m kit phantom calibrate --shape 256 256 --letter-px 64 --n 10 --quality 0.3 --draws 200 --block-px 32
run python3 - "$OUT" <<'PY'
import sys, numpy as np
from kit import phantom
d = sys.argv[1]
p = {k: np.load(f"{d}/ph/{k}.npy") for k in ("volume", "ink", "mask")}
np.save(f"{d}/surface.npy", phantom.surface_detector(p["volume"]))
np.save(f"{d}/surface_reversed.npy", phantom.surface_detector(p["volume"][::-1]))
np.save(f"{d}/sim_q1.npy", phantom.simulated_reader(p["ink"], quality=1.0, seed=1))
np.save(f"{d}/sim_q3.npy", phantom.simulated_reader(p["ink"], quality=3.0, seed=2))
print("maps written")
PY
run python3 -m kit view "$OUT/viewer.html" surface="$OUT/surface.npy" reversed="$OUT/surface_reversed.npy" \
    sim_q1="$OUT/sim_q1.npy" sim_q3="$OUT/sim_q3.npy" --labels "$OUT/ph/ink.npy" --mask "$OUT/ph/mask.npy" \
    --title "Phantom seed 7: four readers" --png "$OUT/viewer.png"
