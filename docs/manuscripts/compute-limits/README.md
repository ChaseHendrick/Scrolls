# More Compute Is Not Enough: Measured Limits of Self-Training, GPU Throughput and Tracer Scaling on Public Vesuvius Challenge Data

**Chase Hendrick**, Independent Researcher · [ORCID 0009-0002-9754-6087](https://orcid.org/0009-0002-9754-6087)

**Draft, shelved on 12 October 2026.** A preprint draft, not peer reviewed, not submitted anywhere and not archived on Zenodo. It may change before any release.

**[Read the preprint (PDF, 10 pages)](paper/compute-limits.pdf)**

## Abstract

Reading the carbonized Herculaneum scrolls from X-ray CT is often described as a problem that larger GPUs and longer training will solve. We tested that on our own work for the Vesuvius Challenge, on public data, with rules fixed before each run. For ink detection on PHerc. 841, two rounds of self-training from an ensemble of the released readers led the best released reader, Reader v2, by +0.0055 and +0.0038 in pixel AUC on two development segments, against a preregistered gate of +0.015. The second round ran on NVIDIA B300 GPUs, cost about 3.3 times the first, and scored lower. A throughput probe on one B300 showed the training step waiting on data for 43% of its time at batch 16, and that packing up to eight trainings on one card raised no total throughput. An error analysis located the loss: the teacher led Reader v2 on both segments (+0.0187 and +0.0134), but the students kept 75% of that lead on one segment and -23% on the other, and every trained model stayed a near-copy of Reader v2 (per-pixel Spearman 0.885 to 0.971). A plain rank mean of two released readers, with no training, led by +0.0112, more than any trained model. For surface tracing, one 60-generation trace with villa's tracer took 960 s on 2 CPU cores, 1494 s on 4 and 2119 s on 8, and ended on the wrong winding every time; holding the seed fixed in the solver, at no extra compute, moved the same trace from a 0.511 share on the wrong winding to 0.972 on the right one. Compute did help: it turned a round of nine trainings into an hour and gave a negative answer the day each run was planned. Our reading is that the limits we met are how well training transfers signal, what signal the current readers have at all, and constraints that keep a trace on its sheet, and that compute multiplies good ideas without replacing them.

## Status of the results

- **Measured:** every number in the tables, the figures and the text, each copied from a run record into `data/`. The ink detection results are pixel AUC on two development segments of PHerc. 841 (w00 and ag896, one sheet traced twice), under rules fixed before each run; the held-out segment ag405 was not read. The tracing results are one seed on PHerc. 139.
- **Sourced:** prices, the released readers and the upstream villa issues and pull requests, cited with dates.
- **Interpretation:** what limits the score, and what would help. These are labelled in the text.
- **Not shown:** anything about methods not tried here (a large new architecture, new labelled data at scale, other CT inputs). A third self-training round and a test of a different reader architecture were under way at the time of writing and are not reported. No ink map in this paper is a reading of text, and nothing concerns a scroll eligible for a prize.

## Contents

| Folder | What is in it |
|---|---|
| [`paper/`](paper/) | The manuscript: [`compute-limits.tex`](paper/compute-limits.tex) (LaTeX, the only source), its build [`compute-limits.pdf`](paper/compute-limits.pdf) and `figures/` |
| [`data/`](data/) | The numbers behind every table and figure, each file with the SHA-256 of the run record it was copied from; `SHA256SUMS` over the files |
| [`code/`](code/) | The two programs below and `requirements.txt` |

| File | What it holds |
|---|---|
| `data/selftrain_rounds.json` | Development AUC of every map of self-training rounds 1 and 2, per seed and per arm, forward and reverse, both registrations, with each round's verdict |
| `data/b300_probe.json` | The B300 throughput probe: the step alone by batch, an online six-map teacher, packed trainings, the loader by threads and processes, the real training step |
| `data/error_analysis.json` | The verified summary of the development error analysis |
| `data/costs.json` | Per-app Modal cost reports of the ink line on 12 October 2026 |
| `data/tracer_cores.json` | One 60-generation trace on 2, 4, 8 and 16 cores |
| `data/seed_anchor.json`, `data/false404.json` | The numbers of villa issues #2059 and #2058 and pull requests #2063 and #2060 |

| Program | What it does | Time |
|---|---|---|
| [`code/check_numbers.py`](code/check_numbers.py) | Checks `data/` against `SHA256SUMS`, recomputes every derived number (leads, costs, waiting shares, ratios) from `data/` and requires each, formatted as printed, in the manuscript; exits with an error on any mismatch. Standard library only | under a second |
| [`code/make_figures.py`](code/make_figures.py) | Redraws the three figures from `data/` | seconds |

## Reproduce

From this folder (needs Python 3 and, for the figures and the PDF, matplotlib and pdflatex):

```
python3 code/check_numbers.py            # prints "all checks passed"
python3 -m pip install -r code/requirements.txt
python3 code/make_figures.py
cd paper && pdflatex compute-limits.tex && pdflatex compute-limits.tex && pdflatex compute-limits.tex
```

The runs themselves used the Vesuvius Challenge's open data, the released readers and paid GPU time; their maps and weights are not included, and this record does not rerun them.

## License

The manuscript in `paper/` is Copyright (c) 2026 Chase Hendrick, all rights reserved. The programs in `code/` and the data in `data/` are under the Apache License 2.0. See `NOTICE`.
