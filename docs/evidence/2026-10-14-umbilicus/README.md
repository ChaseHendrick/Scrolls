# Scroll centre finder: end-point rule evidence

Published data only: the 13 scrolls with a published centre line (PHerc0125, 0211, 0826, 0191, 0257, 0268, 0358, 0800, 0813, 1203, 1218, 1447, 1545). Both files were made on 14 October 2026 with the code in [`scripts/umbilicus/`](../../../scripts/umbilicus/README.md), whose guide explains the end-point rule and the scores. `calibrate.json` was made with the released code. `heldout-endrule.json` was made with an earlier revision of `endcheck.py`, `pipeline.py` and `slices.py` whose scoring and rule give the same results at the shipped settings (it lacked the one-stage-per-folder check and the stored missing-chunk count).

| File | What | How it was made |
| --- | --- | --- |
| `calibrate.json` | The end-point rule at the published centres (held constant past each line's first and last points): per scroll the papyrus level, slices, scored slices, slices each end trim keeps, points dropped at each end, middle slices under the bar and absent chunk reads (`missing_chunks`); pooled, the share of middle slices under the bar. Our measurement of the published lines | `python scripts/umbilicus/endcheck.py calibrate --cache CACHE --out calibrate.json`, starting from an empty cache, so every slice was read from the open-data bucket with range requests |
| `heldout-endrule.json` | The held-out scores of the first stage and of both stages over all 3,414 scored slices, over the slices the mount and cap trim keeps and over the slices both end trims keep, pooled; per scroll, the median over all scored slices and how many scored slices the end-point rule dropped on each scroll and their median error; the check that the all-slices scores equal the run records; the SHA-256 and size of the 14 released weight files (release `umbilicus-v1`). Model output | `python scripts/umbilicus/endcheck.py score RUN_DIR --cache CACHE` (the earlier revision named above) on each stage's folder of held-out answers from the two training runs of 13 October 2026, reading the bucket (no `--data`); the numbers are copied unchanged from its output, the weight files listed under their public names |

Notes:

- The held-out answers themselves (the runs' per-slice records) are not published; the guide's "Reproduce" section rebuilds them.
- Without `--data`, `endcheck.py` computes the mount and cap trim from level-5 planes, a stand-in for the level-3 papyrus area the pipeline uses; the end-point rule reads level-3 windows round each centre, as the pipeline does.
- `missing_chunks` counts chunk reads (one per plane and chunk) that the bucket answered with NoSuchKey. Such chunks read as 0 (air), as they do in the pipeline's slice files. The counts are stored with the cached reads: run again from the cache the first run filled, `calibrate` wrote the same file byte for byte.
- The radius sweep at 2, 3 and 5 mm (`endcheck.py calibrate --radius R`) is reported in the guide and is not stored here.

`SHA256SUMS` covers the two JSON files (`sha256sum -c SHA256SUMS` in this folder).
