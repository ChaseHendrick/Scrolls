# PR14 final-head review

Reviewed commit: `ca9c8c43fc94bdebe8d1fb49ee014d2b9e2922ca` against `99c71f3d4de10e08316ebe5ee81515db88da2548`.

The new commit changes documentation and results only; no executable code changed. Grok reports a real CPU Mac experiment on published labelled PHerc0841 w00 and PHerc0139 w045 data. This reviewer did not run or independently reproduce that experiment. The earlier exact-script syntax/dispatch checks and isolated code tests remain applicable.

## Required merge cleanup

1. Remove all 15 newly added AppleDouble `._*` files. Exact relative paths are in `remove-appledouble-paths.txt`; preserve their ordinary JSON counterparts unchanged.
2. Qualify `docs/logs/2026-10-07-grok-laneD.md:40`. The observed null supports failure of this feature set and tiny learner on these three fixed splits. It does not prove that fibre texture lacks ink information, identify what ink_9um reads, or establish that untested larger training/3D features cannot work. A proposed replacement paragraph is saved in `grok-log-qualified.md`.

## Findings and checks

- Fifteen ordinary JSON files parse, contain finite numbers, and include nine AUC records plus six model metadata records.
- Paired score records share crops, class counts, forward/reverse scores, and explicit inner64/bootstrap300/seed0 settings. The reported raw comparison AUCs agree with separate raw score records.
- Grok reports fibre forward AUCs .4726 (w045→w00), .4223 (w00→w045), and .5018 (disjoint w00 window→w00). All reported fibre AUC intervals contain .5; no fibre-versus-brightness comparison establishes an improvement. The w045→w00 comparison establishes a decrease under this reported bootstrap.
- ink_9um comparison values are .8061 on w00 and .9199 on w045. These are Grok-reported seed42 Mac comparisons, not the independently run cloud D9 benchmark and not directly interchangeable with it.
- The comparison point estimates use the existing 1024-bin bootstrap estimator, while forward AUC uses the existing 65536-bin estimator. This explains the .4223 standalone versus .4380 paired estimate on w045. Keep both raw records; do not silently rewrite the values.
- No raw surface data, prediction maps, or model weights were added. The results are useful negative evidence about the tested implementation. They do not support a general claim about fibre information or future approaches.

Machine-readable checks and raw-file SHA256 values are in `review-checks.json`. Shared checkout source files and branch were untouched.
