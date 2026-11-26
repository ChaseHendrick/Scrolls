# simperm: the draft SRS-2 permutation pass rule for the realism judge

Draft SRS-2 rule for rating simulated scroll CT: SRS-1's critics, cross-fitted on whole units, with a stratified permutation p-value in place of SRS-1's fixed bar, so a perfect simulator fails about alpha of the time. Not in force until its preregistered calibration passes review.

| Field | Value |
| --- | --- |
| Id | `simperm` |
| Status | Experimental |
| Kind | kit module |
| Area | Scoring and controls |
| Run | `python -m kit.simperm rule`, `score`, `check`, `calibrate`; `from kit import simperm` |
| Code | `kit/simperm.py` |
| Tests | `tests/test_simperm.py` |
| Needs | Python 3.11+, numpy, scipy; torch for the `cnn` and `cnn_half` critics (`score` only); `kit.hardcases` for `calibrate` |
| Runs on | CPU or GPU. `calibrate` (feat critic only, the preregistered cells): 575 s for 200 replicates per cell on a 150-unit pool, 4 workers, 4-core cloud container shared with other jobs (26 Nov 2026); the frozen 400-unit pool adds feature time. A full `score` trains the three SRS-1 critics on four test sets (the set, blur, noise, self split), about twice SRS-1's training; Not measured |
| Network | None (the reference npz comes from `python -m kit.simscore reference`) |
| Writes | `score`: the record named by `--out`; `calibrate`: the JSON named by `--out`; `rule` and `check`: nothing |
| Go-ahead | Not needed |
| Released | Branch only (public PR, draft) |
| Checked | 2026-11-26 against commit `de415de` |

## What it does

SRS-1 ([simscore](simscore.md)) judges a simulated set with three critics (a feature critic, a CNN and a half-scale CNN) and passes it when the worst critic AUC is at most one real-against-real control draw plus 0.05. Its null calibration showed that this bar fails a perfect simulator 29 to 60 percent of the time, so SRS-1 can only rule sets out. `simperm` keeps every SRS-1 critic and training setting and replaces the bar with a permutation p-value.

A real **unit** is one reference slice the generator was not fitted to. The simulated tiles are cut, in file order, into **sim units** with about as many windows as the median slice. Units are dealt to 3 folds (real and sim separately, so each fold holds both). Each critic scores fold k with a model trained real against sim on fold k + 1 only (the ring design); a unit's score is its windows' mean, averaged over the training seeds. Within each fold the units are ranked; the real units' rank sum, standardized, gives Z per critic, and T is the largest Z. The p-value is T's rank among 9,999 within-fold relabelings, drawn once and shared by all critics so the max is taken inside each draw. FAIL when p is at most 0.05.

Three planted tests run on every score and make the record VOID when they go wrong: the set blurred (sigma 1.0) and the set with noise (sd 0.08) must FAIL, and the set split against itself must not (p above 0.01). A PASS also needs a reference with at least `ADMIT_GROUPS` eligible slices, which only the preregistered calibration can set; until then a would-be PASS is INCONCLUSIVE.

A PASS means no critic separated the set's units from the reference's slices at alpha 0.05, on a reference where the same judge caught a blurred and a noisy copy of the set. It is Model output, not proof that a set is real. Gray values only; no labels are scored.

## When to use it

- To try the SRS-2 draft on a set already scored under SRS-1, or to rerun its calibration.
- To test the rule's error rates on your own synthetic units (`calibrate` with development seeds).

Do not use it:

- As the standard of record: SRS-1 ([simscore](simscore.md)) stays in force until SRS-2's calibration passes and is reviewed.
- For ink, label or geometry questions: it compares gray-value windows only.

## Quick start

```bash
python -m kit.simperm rule
python -m kit.simperm calibrate --groups 6 --reps 20 --power-reps 10 --perms 999 --pool 60 --seed0 4629001 --oneseed-seed 4629901 --out OUT.json
```

OUT.json is a scratch file. The seeds are development seeds (the preregistered seeds are refused with `--freeze` unless unchanged, and must not be used before the frozen run). It worked when it prints a `metrics` line such as `{"admit_groups": null, "blur08_power_gmax": 1.0, "false_fail_max": 0.1, "srs1_false_fail_g6_max": 0.35}` (26 Nov 2026, 20 replicates, so the rates are coarse).

## Checks and controls

Every score carries its own planted tests (blur and noise must FAIL, the self split must not); a failed one makes the record VOID. `check` recomputes the p-value from the stored unit scores with the same seeded relabelings, then the gates and the status, and fails on any mismatch.

The rule's error rates are measured by the preregistered null calibration ([prereg](../prereg/2026-11-26-srs2-null-calibration.md)): a perfect simulator (exchangeable synthetic units) must fail at most 8 percent of the time in every cell, with SRS-1's bar on the same draws and a blurred simulator as controls. Development results (development seeds, ring design, 200 replicates per cell): false FAIL 0.015 to 0.06 where SRS-1's bar on the same draws gave 0.20 to 0.485; a sigma 0.8 blur caught in every replicate ([prereg, section Development runs](../prereg/2026-11-26-srs2-null-calibration.md#development-runs-before-the-freeze)). The plain cross-fitted design gave 0.06 to 0.10 and was dropped.

Cross-scroll validation: claim-dependent. A record rates a set against one named reference; a realism claim across scans needs a record on each. The calibration is synthetic and feat-critic only.

Claim label: Untested idea for the rule as a standard until the frozen calibration is collected; Model output for any record it writes.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `PermError()` | exception | | Bad sizes, folds or arguments |
| `sim_units(window_tile, n_tiles, per_unit)` | unit id per tile (-1 for a dropped short tail) | | Consecutive tiles in file order |
| `deal(real_ids, sim_ids, folds=FOLDS, seed=FOLD_SEED)` | `{unit: fold}` | `PermError` with fewer units than folds | Real and sim dealt separately |
| `train_folds(k, folds, design)` | training folds for fold K, or None when K is not tested | `PermError` on an unknown design | |
| `unit_scores(A, uA, B, uB, critic, fold_of, seeds=SEEDS, steps=STEPS, device='cpu', design=None)` | `{unit: score}` | | Held-out scores; feature rows for `feat`, windows otherwise |
| `tested_folds(fold_of, design=None)` | the part of FOLD_OF the test reads | | |
| `permtest(scores, real_units, fold_of, perms=PERMS, seed=PERM_SEED)` | `{"z", "t", "p", "auc_unit", "perms"}` | `PermError` when a fold holds one kind | Max over critics inside each relabeling |
| `test_units(data, real_units, sim_units_, fold_of, ...)` | `permtest` result plus `scores` | | Runs every critic in DATA |
| `gates(planted)` | `{planted_blur, planted_noise, self_split}` | | From the planted p-values |
| `status(p, n_real_units, gate=None, admit=..., smoke=False)` | `(status, reason)` | | PASS, FAIL, INCONCLUSIVE, VOID, SMOKE |
| `scorer_digests()` | SHA-256 of simcritic, simscore and simperm | | |
| `score(ref, tiles, generator, attempts, trained_on=(), ...)` | the record | `PermError` on sizes, steps, attempts or names | |
| `record_digest(rec)` | SHA-256 of the record without its digest | | |
| `check(rec)` | list of problems | | `[]` when consistent |
| `calibration_features(pool=..., workers=1, progress=print, seed0=..., oneseed_seed=...)` | per-unit feature rows | | |
| `calibrate(groups=..., ks=..., reps=200, power_reps=100, perms=PERMS, pool=..., workers=1, progress=print, feats=None)` | the calibration result | | The preregistered cells |
| `summarize(cal)` | the `metrics` the readout rule reads | | |
| `main(argv=None)` | exit code | | |

## Commands and options

### rule

`python -m kit.simperm rule`: prints the fixed settings.

| Option | Default | Meaning |
| --- | --- | --- |
| `--json` | off | Print the settings and `admit_groups` as JSON |

### score

| Option | Default | Meaning |
| --- | --- | --- |
| `--reference` | required | Reference npz (`python -m kit.simscore reference`) |
| `--sim` | required | npz of simulated tiles |
| `--key` | `image` | npz key of the tiles |
| `--n` | 240 | Read the first N tiles, in file order |
| `--generator` | required | The simulator's name and version, for the record |
| `--attempts` | required | Sets your team scored before this one |
| `--trained-on` | none | Reference slice names the generator was fitted to; left out of every test |
| `--device` | `cpu` | Torch device for the CNN critics |
| `--smoke` | off | Small sizes and `--steps` for a pipeline check; never a verdict |
| `--steps` | 800 | CNN steps (other values need `--smoke`) |
| `--perms` | 9999 | Relabelings (other values make `check` report a setting mismatch unless `--smoke`) |
| `--out` | required | Record path |

### check

| Option | Default | Meaning |
| --- | --- | --- |
| `record` | required | The record to recompute |
| `--json` | off | Print `ok`, `problems` and `status` as JSON |

### calibrate

| Option | Default | Meaning |
| --- | --- | --- |
| `--out` | required | Result path |
| `--reps` | 200 | Null replicates per cell |
| `--power-reps` | 100 | Blur and one-seed replicates per cell |
| `--perms` | 9999 | Relabelings per test |
| `--pool` | 400 | Pool units |
| `--groups` | 6 12 24 | G values |
| `--workers` | 1 | Processes for the pool features |
| `--seed0` | 4621001 | First pool seed; change only for development runs |
| `--oneseed-seed` | 4622001 | One-seed sim seed; change only for development runs |
| `--freeze` | none | Freeze id written into the result; refuses non-preregistered seeds |

## Inputs

- `--reference`: a reference npz in `kit.simscore.load_reference`'s layout (`ct` slices, optional `cover`, `name`, `id`), as written by `python -m kit.simscore reference`.
- `--sim`: an npz of simulated 2D tiles under `--key` (default `image`); the first `--n` (default 240) are read, in file order.
- `--trained-on`: names of reference slices the generator was fitted to; they are left out of every test.

## Outputs

`score` prints the status, p and T, and writes a record:

| Field | Type | Meaning |
| --- | --- | --- |
| `standard` | string | `SRS-2-draft` |
| `settings` | object | Every fixed setting |
| `reference`, `set` | object | Slices used, unit sizes, window digests |
| `fold_of` | object | Fold of every unit |
| `result` | object | `z`, `t`, `p`, `auc_unit` per critic, `scores` per unit |
| `planted` | object | `blur`, `noise`, `split` test results |
| `gates`, `status`, `reason` | | As recomputed by `check` |

`calibrate` writes per cell (`G6_K6` and so on) the false FAIL rate, p quartiles, SRS-1's false FAIL rate on the same draws, the one-seed rate, power per sigma and a SHA-256 of the per-replicate p-values, plus `metrics`.

| Exit code | Meaning |
| --- | --- |
| `0` | Done (`check`: the record is consistent) |
| `1` | `check` found problems |
| `2` | Unreadable record, or a frozen calibration asked for non-preregistered seeds |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `a frozen run uses the preregistered seeds` | `--freeze` with other seeds | Drop `--seed0` and `--oneseed-seed` for the frozen run |
| `SRS-2 uses...CNN steps; other values need smoke=True` | Steps changed on a real score | Use `--smoke` for a pipeline check |
| `attempts must be the count of sets scored before this one (0 for the first)` | Missing or negative attempts | Count every set scored before this one |
| `trained_on names...are not slices of the reference` | A name not in the reference | Use the reference's slice names |
| `...units cannot fill...folds` | Fewer than 3 real or sim units | Use a larger reference or set |
| `fold...holds only one kind of unit` | A hand-made fold map | Use `deal` |
| `unknown design` | A design other than ring, cross, holdout or half | Use the default |
| `cannot read record...:...` | Missing or broken JSON | Check the path |

## How it works

1. Units: eligible slices; sim units of `median(windows per slice)` windows from consecutive tiles.
2. Folds: `deal`, seed `FOLD_SEED` 0, 3 folds, the same for every training seed; `DESIGN` "ring": fold k is scored by a model trained on fold k + 1 (mod 3). `train_folds` also offers "cross", "holdout" and "half" for development comparisons only.
3. Critics: `kit.simcritic`'s `_logistic` on its features (feat) and `_cnn` (cnn, cnn_half), SRS-1's 800 steps and seeds 0 and 1.
4. Statistic: within-fold ranks of the unit scores; S per critic; Z = (S - E) / sd with E and sd those of a within-fold random relabeling; T = max Z.
5. p = (1 + number of relabelings with max Z at least T) / (1 + 9,999), relabelings seeded `PERM_SEED` 20261127.
6. Gates and status as above; `ALPHA` 0.05, `SPLIT_MIN_P` 0.01, `PLANT_BLUR` 1.0, `PLANT_NOISE` 0.08.

Under exchangeable units each fold's held-out scores do not depend on that fold's labels. With ordinary cross-fitting each pair of folds enters two folds' tests, which inflated the false FAIL rate to 0.06 to 0.10 on development seeds; in the ring each pair enters one. The fold tests are still not independent, so exactness is checked by the calibration rather than assumed.

## Cost and time

`calibrate`: 575 s wall for the development cells (above). `score`: four tests of three critics with two seeds and three folds, 72 trainings, each on one fold (a third of the data, against SRS-1's two thirds); Not measured end to end. CPU only for the feat critic; a GPU is faster for the CNNs.

## For agents

- **Command:** `python -m kit.simperm score --reference REF.npz --sim SIM.npz --generator NAME --attempts N --out REC.json`, then `python -m kit.simperm check REC.json --json`.
- **Parse:** `status`, `result.p`, `result.t`, `gates`; `check --json` gives `ok` and `problems`.
- **Rerun:** safe; overwrites `--out`.
- **Success:** exit 0 and `check` ok.
- **Not a pass:** INCONCLUSIVE, SMOKE or VOID; any status before `ADMIT_GROUPS` is set.
- **Go-ahead:** Nothing for scoring; a public claim of realism follows the standard's text.
- **Never:** call a PASS proof of realism; tune a generator on the scored slices; run the frozen calibration seeds outside the frozen run.

## Tests

`python -m unittest tests.test_simperm`: unit cutting and fold dealing, the permutation test on separated, one-critic and exchangeable scores (the false FAIL rate stays near alpha), the feat critic on shifted and same-source synthetic units, the status and gate rules, and `check` on a consistent and a tampered record. They do not train CNN critics.

## History

- 2026-11-26: first version (draft SRS-2), with its calibration preregistration (this branch, based on `de415de`).

## Related

- [simscore](simscore.md): SRS-1, the standard in force.
- [simcritic](simcritic.md): the critics.
- [SRS-1 calibration](../evidence/srs1-calibration-1126/README.md): why the fixed bar fails a perfect simulator.
- [Sim realism standard](../standards/sim-realism.md).
