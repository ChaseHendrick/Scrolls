# 2026-10-07: phantom and viewer demo (synthetic data only)

All numbers below are Model output on synthetic phantoms, from `bash scripts/phantom-demo.sh` (box, CPU, numpy) and one re-run of the calibrate step with a smaller block (the first run used `--block-px 107`, which on a 256 px phantom leaves about 4 blocks; some resamples then hold one class and the bootstrap half width came out NaN). No scroll data was used. Nothing here is a reading.

## Stress test: baseline `surface_detector`, 4 phantoms

`python3 -m kit phantom stress --shape 256 256 --depth 16 --seed 0 --n 4 --letter-px 64`

| Seed | AUC as stored | AUC depth reversed |
| --- | --- | --- |
| 0 | 0.7377 | 0.3120 |
| 1 | 0.7097 | 0.3766 |
| 2 | 0.6984 | 0.2804 |
| 3 | 0.7016 | 0.2543 |

The control falls well below 0.5 on every phantom, so the check can fail and the detector reads depth order.

## AUC noise calibration

`python3 -m kit phantom calibrate --shape 256 256 --letter-px 64 --n 10 --quality 0.3 --draws 200 --block-px 32`

AUC over 10 phantoms: mean 0.7524; between-phantom 95 % half width 0.1352; mean block-bootstrap half width 0.0686 (ratio 0.508); one-phantom intervals covering the mean: 5/10.

Interpretation: on these small phantoms (5 to 10 letter cells each), the one-sample block bootstrap is about half as wide as the spread between independent phantoms of one difficulty, because the variation in stroke layout between sheets is not in a single sheet's blocks. If that carries over to real segments, a single-segment `kit auc --bootstrap` interval understates segment-to-segment noise. Untested idea: repeat at real size (about 1000 x 1000 px, 9 um letters of 2 to 3 mm) before using it.

## Viewer

Historical output: the viewer figures and PNG below predate the correction to use average ranks for tied values. They are retained as the original run record and must not be used as evidence from the corrected viewer. Constant maps previously acquired artificial rank gradients and could report an AUC of 1 instead of 0.5.

`python3 -m kit view /tmp/phantom-demo/viewer.html surface=... reversed=... sim_q1=... sim_q3=... --labels ink.npy --mask mask.npy --png viewer.png` on phantom seed 7 (256 x 256, 16 layers): HTML 654 KB, one file. AUC on view: surface 0.7754, reversed 0.3284, sim_q1 0.9377, sim_q3 0.9913; rank correlation surface vs reversed -0.8382, sim_q1 vs sim_q3 0.5483; mean disagreement 0.2372. Panels: [`../assets/phantom-viewer-demo.png`](../assets/phantom-viewer-demo.png) (left to right: surface, reversed, sim_q1, sim_q3, disagreement; green: label outline).

## Commands as logged

```
$ python3 -m kit phantom make /tmp/phantom-demo/ph --shape 256 256 --depth 16 --seed 7 --letter-px 64
$ python3 -m kit phantom stress --shape 256 256 --depth 16 --seed 0 --n 4 --letter-px 64 --save-maps /tmp/phantom-demo/maps
$ python3 -m kit phantom calibrate --shape 256 256 --letter-px 64 --n 10 --quality 1.0 --draws 200 --block-px 107
$ python3 - /tmp/phantom-demo
$ python3 -m kit view /tmp/phantom-demo/viewer.html surface=/tmp/phantom-demo/surface.npy reversed=/tmp/phantom-demo/surface_reversed.npy sim_q1=/tmp/phantom-demo/sim_q1.npy sim_q3=/tmp/phantom-demo/sim_q3.npy --labels /tmp/phantom-demo/ph/ink.npy --mask /tmp/phantom-demo/ph/mask.npy --title Phantom seed 7: four readers --png /tmp/phantom-demo/viewer.png
$ python3 -m kit phantom calibrate --shape 256 256 --letter-px 64 --n 10 --quality 0.3 --draws 200 --block-px 32
```
