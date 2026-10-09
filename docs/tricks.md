# Tricks and tips from the community, and what they did here (2026-10-07)

What other teams found makes ink readers better, makes a read more trustworthy, or saves time; each with its source, whether this repository has it, and what it measured on PHerc0841, a labelled scroll that `ink_9um`, v8in, d9v2 and Reader v2 did not train on (possibly not held out from Hecate, whose base model's committed trainer lists all three PHerc0841 segments: [log](logs/2026-10-09-pherc0841-hecate.md)). Labels as in [`NOVELTY.md`](NOVELTY.md). Measurements are on the three 640 px crops `scripts/mac-w045.sh` uses, 64 px edge left out, against the 20260918 human labels (`kit auc`); the letter-scale score is `kit hpscore`.

## Measured here on PHerc0841

w00 only below. The tricks job stopped early on 2026-10-07 after also scoring ag896 and Reader v2 (default window: forward, reverse and depth-shuffled, on w00 and ag896): see [`tables.md`](../scripts/experiments/2026-10-07-cloud/tricks/tables.md) ([PR #8](https://github.com/ChaseHendrick/Scrolls/pull/8)). ag405 and w045 were not scored. Forward AUC, reverse in brackets; letter-scale r (`kit hpscore`) after it. CPU, villa PR #1865, 2026-10-07.

| Map | 0841 w00 AUC (reverse) | Letter-scale r |
| --- | --- | ---: |
| `ink_9um` seed 42 (bar) | 0.8061 (0.536) | 0.029 |
| + checkpoint soup (`soup42_last4`) | 0.8326 (0.504) | 0.032 |
| + soup and 4 z windows | 0.8465 (0.499) | 0.035 |
| `ink_9um` seed 42, 4 z windows | 0.8427 (0.546) | 0.030 |
| d9v2 (bar) | 0.8994 (0.586) | 0.015 |
| d9v2, 4 z windows | 0.9198 (0.615) | 0.019 |
| d9v2, mirror TTA | 0.9202 (0.571) | 0.021 |
| d9v2 + `ink_9um` map mean | 0.8677 (0.557) | |
| d9v2 + `ink_9um` rank mean | 0.8750 (0.576) | |
| Depth-shuffled input: `ink_9um`, soup, d9v2 | 0.4996, 0.4807, 0.4906 | -0.011, -0.009, +0.002 |

Model output on one 640 px crop, not yet a result: ag405, a different surface, is still unscored.

## Better maps for free (no training)

| Trick | Source | In this repo | Notes |
| --- | --- | --- | --- |
| **Checkpoint soup**: average the weights of the last few checkpoints of one run | Nieuwlaar, [ink9um-dense-native](https://github.com/Nieuwlaar/ink9um-dense-native) (`soup42_last4`, +0.03 to +0.06 AUC on PHerc0139); Armando Gaona's checkpoint-averaging Progress Prize | `scripts/soup.py` (bit-identical to his file) | Only within one run. **Averaging two seeds' weights broke the model (AUC 0.49)**; average their maps instead. `soup.py` refuses mixed seeds. |
| **z-window ensemble**: run the same model on several depth windows and average the maps | Nieuwlaar `zavg_infer.sh` (windows `0:20 3:23 5:25 8:27` on 28-layer volumes) | villa's `--layer-start/--layer-end` + `kit ensemble` | Costs one inference per window. |
| **Mirror test-time augmentation** | villa's own `--tta-mirror` flag | villa | Twice the compute. |
| **Map ensembles across readers** | Reader v2 model card (Reader v2 + Hecate 0.866 on PHerc0841, where Hecate may not be held out); TAUIL (d9v2 + Reader v2 0.840) | `kit ensemble` (`--method rank` across models) | Helps only when the members are about equally good; see the table above. |
| **Depth sharpening** after inference | [villa #1898](https://github.com/ScrollPrize/villa/issues/1898), measured by Bullo27 | Not added | +0.018 to +0.062 pixel AUC on PHerc0841 but only +0.002 to +0.004 letter-scale, and no letter became legible. Blur-type gains look like this. |

## Measuring honestly

| Trick | Source | In this repo | Notes |
| --- | --- | --- | --- |
| **Letter-scale score**: correlate map and key after removing a 48 um blur | Chris Scheirer, [vesuvius-reports 02](https://github.com/ShribyrLabs/vesuvius-reports) | `kit hpscore` (against human labels, rolled-key null) | Pixel AUC and plain correlation reward blobs and blur; this rewards strokes. On his scale noise 0.01, blobs 0.04, four letters made out 0.076. **A blur raises it too: compare at the same blur.** |
| **Reverse-depth control** | Common practice (nerln, millerandmuller, Bullo27) | `kit auc --control`, `kit verify --control` | A read that also shows in the reversed volume is brightness, not ink. |
| **Depth-shuffle control**: permute the layers and read again | aviad12g, [vesuvius-depth-order-control](https://github.com/aviad12g/vesuvius-depth-order-control) (Hecate's eligible-scroll positives survive shuffling) | Measured here (table above); not yet a script option | A cleaner null than reverse: reversed volumes keep a depth structure, shuffled ones do not. |
| **Threshold from a labelled control, plus a size floor** | millerandmuller, [first-light-pherc0826](https://github.com/millerandmuller/first-light-pherc0826): median ink probability on w035 (0.7843), 0.5 mm floor | Not added (in `docs/engine.md` as open) | Their 9 candidates: 8 were vertical bands at rendering boundaries. Render seams are the first artifact to rule out. |
| **Blind, shuffled panel reading with hashed verdicts** | nerln, [vesuvius-first-letters-pherc0800](https://github.com/nerln/vesuvius-first-letters-pherc0800) | Rule in `docs/AI-AGENTS.md`; no tool | Panels shuffled with lettered controls, a hash of the verdicts published before reading the other reader's. Four automatic criteria failed for them; the verdict stays visual. |
| **On-prediction support** of a traced patch | [villa #1906](https://github.com/ScrollPrize/villa/pull/1906), measured by Bullo27 | Not added | Share of a patch's vertices on the surface prediction it grew from: 45 to 63 % on patches that follow the sheet, 26 to 35 % on ones that swirl across layers. A cheap filter before reading a patch. |
| **Slab centring check** | bnleft, [first-light-pherc0211](https://github.com/bnleft/first-light-pherc0211) (`slab_profiles`) | Not added | On automatic surfaces the brightness peak wanders through the slab (46 % of blocks centred, against 77 % on a curated mesh). Re-centring per tile found less, not more, so it is a diagnostic, not a fix. |
| **Preregistration** | bnleft `prereg/readout.md` | `docs/prereg/`, `kit run init` | Already standard here. |
| **Legibility proxy** for triage | LimeGS, [herculaneum-legibility-proxy-v5](https://huggingface.co/LimeGS/herculaneum-legibility-proxy-v5) | Not added | Self-described experimental, no held-out evaluation. Second triage score at most. |

## Things that did not work, so we need not try them

| Idea | Who tried | Result |
| --- | --- | --- |
| Six training levers at 9 um: window jitter, a 9-slice window, a DINO-guided 3D model, geometry-consistency cleanup, dropping the worst keys, the 2.4 um model fine-tuned at 9 um | Scheirer (report 02) | None cleared run-to-run noise (0.005) on the letter-scale score; the ones that "gained" also raised the known-bad exam, which is smoothing. |
| The raw-darkness veto ("ink is darker than papyrus") | Nieuwlaar `vetoes.py` | Known ink is sign-neutral at 113 keV; the veto removes half to two thirds of real ink. The CT-void veto costs about 9 % of real ink. |
| Cross-seed weight soups | Nieuwlaar | AUC 0.49. |
| Hecate rank as evidence | aviad12g | Shuffled input gives more positives than real input on eligible surfaces: a reading order only. |

## Training tips (for Phase 3)

- **Window depth and z-jitter are coupled** (pscamillo, [ink9-depth-window](https://github.com/pscamillo/ink9-depth-window)): 13, 9 and even 5 slices match the 17-slice recipe if the jitter shrinks with the window; 5 slices with the default ±2 jitter breaks. A 5-slice window trains about 60 % faster. Released `ink_9um` uses 17 slices, ±2 (its config).
- **A small ink window cannot invent letters** (PHerc. 1667 paper, [arXiv:2606.29085](https://arxiv.org/abs/2606.29085)): the team read at 2.4 um with a 256 px (614 um) window, deliberately smaller than a letter, then five rounds of per-scroll pseudo-labels.
- **Resample, do not relabel, the voxel size** (Scheirer, report 02 addendum): Hecate refuses renders more than 2 % from 9.6 um. Resampling scored better than telling it the render was 9.6 um.
- **Sampling removes most letter signal** (Scheirer): the canonical 2.4 um model scores 0.95 on native 2.4 um layers and 0.11 on the same layers downsampled to 9 um.

## Practical

- **VC3D's remote cache** grows to gigabytes; move it with `VC3D_CONFIG_DIR` pointing at a folder whose `VC3D.ini` has `[viewer]` and `remote_cache_dir=/big/disk/remote_cache` (Bullo27).
- **Pay-per-second GPUs** avoid paying for idle pods (bnleft: Modal, 13.53 USD for a full PHerc0211 run; [`compute.md`](compute.md)).
- **One GPU job at a time on a 16 GB Mac** (ours: two concurrent v8in runs swapped to 56 s per tile); the Mac scripts share a lock.
- **fp16 on an M1 Pro is slower** (ours: about 5x); the script now drops it by itself.
