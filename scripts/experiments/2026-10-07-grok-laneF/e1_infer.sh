#!/bin/bash
# Lane F E1 inference: ink_9um forward on each matched w00 crop, both seeds, repo flags.
cd ~/scrolls-work
for z in w00_matched_self w00_matched_w045 w00_matched_perlayer; do for s in 42 43; do
  /usr/bin/time -p venv/bin/python -m vesuvius.ink_detection.inference.infer laneF/zarr/$z.zarr \
    checkpoints/ink_9um/hybrid_3d2d-seed$s/step-075000.pth laneF/maps/${z}_s$s.tif \
    --overlap 0.5 --blend-mode hann --batch-size 1 --no-compile --direction forward > laneF/e1_${z}_s$s.log 2>&1
  echo "$z s$s exit $? $(grep -c 'Using MPS device' laneF/e1_${z}_s$s.log) mps"
done; done
