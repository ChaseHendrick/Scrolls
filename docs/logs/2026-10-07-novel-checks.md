# Three checks on PHerc0841 with its human labels (2026-10-07)

PHerc0841 is the labelled scroll no released reader trained on. All numbers are model output on public labelled data (no target scroll), CPU, villa PR #1865, `ink_9um` seed 42 step 75,000 unless stated. Crops are the 640 px windows of `scripts/mac-w045.sh`, 64 px edge left out; whole-segment numbers use the full maps of [`2026-10-07-community-scan.md`](2026-10-07-community-scan.md). Scripts: `scripts/experiments/2026-10-07-tricks/`.

## 1. A threshold taken from a training segment keeps 2 to 4 % of real ink on an unseen scroll

millerandmuller's PHerc0826 null ([first-light-pherc0826](https://github.com/millerandmuller/first-light-pherc0826), August 2026 Progress Prize) thresholds `ink_9um` at 0.7843 = 200/255, "the median probability on labeled ink" of PHerc0139 w035, a segment in the model's training set (Sourced fact). Share of human-labelled ink pixels at or above that value, whole segments:

| Segment | Labelled ink px | Median map value on ink | Ink at or above 0.7843 | Background at or above 0.7843 |
| --- | ---: | ---: | ---: | ---: |
| PHerc0139 w035 (training; their calibration) | | 0.7843 | 50 % by construction | |
| PHerc0139 w045 (held out, training scroll) | 149,192 | 0.565 | 9.5 % | 0.27 % |
| PHerc0841 w00 (unseen scroll) | 355,098 | 0.431 | 2.3 % | 0.001 % |
| PHerc0841 ag896 | 318,252 | 0.435 | 2.4 % | 0.07 % |
| PHerc0841 ag405 | 289,928 | 0.388 | 3.7 % | 0.03 % |

(Model output.) The same rule they used for candidates (8-connected pixels at or above the threshold, bounding box long side at least 0.5 mm, their `analyze_target.py`) on these team-traced surfaces, where text is known to be present:

| Segment | Map area | Forward candidates | Of them mostly on labelled ink | Reverse candidates | Forward candidates per cm² |
| --- | ---: | ---: | ---: | ---: | ---: |
| w045 | 40.0 cm² | 86 | 5 | 11 | 2.1 |
| 0841 w00 | 14.0 cm² | 13 | 3 | 4 | 0.93 |
| 0841 ag896 | 14.2 cm² | 10 | 2 | 2 | 0.70 |
| 0841 ag405 | 13.3 cm² | 12 | 4 | 8 | 0.90 |

Their PHerc0826 target gave 9 candidates on about 1.79 billion pixels, 0.006 per cm² if those pixels were all surface (their count may include empty canvas, which would raise the density).

**Interpretation.** A threshold calibrated on a training segment does not transfer: real ink on an unseen scroll mostly scores far below it (median 0.39 to 0.44 against 0.78). The rule still finds about one candidate per cm² on PHerc0841's good surfaces, so it is not blind there, but it sees only the brightest 2 to 4 % of the ink, and a third or fewer of its candidates sit on labelled ink. A null from such a threshold says little about faint ink. A threshold calibrated on an unseen labelled scroll (PHerc0841) would be the fairer choice for target runs; ours are preregistered without a fixed threshold. Not found in the community repositories and papers we read (2026-10-07).

## 2. Averaging depth windows reaches the best window without labels

The 17-layer window `ink_9um`-family readers take from a 28-layer surface volume was moved by villa's `--layer-start/--layer-end` (centre layer 10, 13, 14 = default, 15, 17). Forward AUC on the crops:

| Crop, reader | Centre 10 | 13 | 14 (default) | 15 | 17 |
| --- | ---: | ---: | ---: | ---: | ---: |
| w00, `ink_9um` | 0.685 | 0.801 | 0.806 | 0.835 | **0.847** |
| w00, d9v2 | 0.805 | 0.889 | 0.899 | 0.906 | **0.928** |
| ag896, `ink_9um` | **0.744** | 0.656 | 0.659 | 0.642 | 0.695 |
| ag896, d9v2 | 0.795 | 0.823 | 0.823 | **0.845** | 0.824 |
| ag405, `ink_9um` | **0.785** | 0.759 | 0.784 | 0.771 | 0.760 |

(Model output.) The best window moves by up to 4 layers between segments, and between readers on one segment, worth up to +0.085 AUC (ag896, `ink_9um`). Neither the depth of the brightness peak (bnleft's centring diagnostic) nor five map statistics chose it reliably; the forward map's standard deviation picked it in 5 of 8 reader-crop cases (chance 1.6), weak after five tries. But the plain mean of four windows (Nieuwlaar's `0:20 3:23 5:25 8:27`) matched the best single window chosen with the labels, over 8 reader-crop cases (`ink_9um`, its soup, d9v2 on three crops): mean AUC 0.820 against 0.819 (oracle), 0.808 (picked by standard deviation), 0.785 (default). On ag405 it beat every single window (0.815 against 0.785). **Interpretation:** on a scroll without labels, average the windows rather than try to find the right depth. Nieuwlaar measured the window average on PHerc0139, a training scroll; this is the unseen-scroll test, with the oracle comparison.

## 3. Depth-shuffle control: lower than reverse, and not always 0.5

Layers permuted in a fixed order (`kit shuffle`, seed 20261007), forward AUC on the crops (reverse AUC of the same reader in brackets):

| Reader | w00 | ag896 | ag405 |
| --- | ---: | ---: | ---: |
| `ink_9um` | 0.500 (0.536) | 0.558 (0.558) | 0.563 (0.642) |
| its soup | 0.481 (0.504) | 0.503 | 0.607 |
| d9v2 | 0.491 (0.586) | 0.476 (0.532) | running |

(Model output.) Shuffled input reads at or below the reversed input everywhere: reversing keeps a depth structure the readers partly use. On ag405, 0.06 to 0.11 above 0.5 survives any depth order, a brightness share of the AUC that differs by segment. **Interpretation:** report the shuffle control beside the reverse one; a reader's AUC above its shuffled AUC is the part that depends on depth order.
