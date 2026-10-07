# The engine: villa, and what `kit/` adds

## villa is the engine

[ScrollPrize/villa](https://github.com/ScrollPrize/villa) is the Vesuvius Challenge monorepo (MIT). It is what the organizers use and what the Grand Prize requires integration with. Do not build a competing one here. Components as of commit `e0bbb8b` (2026-10-06):

| Component | Role |
| --- | --- |
| [`vesuvius/`](https://github.com/ScrollPrize/villa/tree/main/vesuvius) | Python library: data access (remote Zarr), training, `vesuvius.predict`, rendering, `ink_detection` subpackage |
| [`volume-cartographer/`](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer) (VC3D) | C++ app and CLI tools: viewing, GrowPatch tracing, `vc_render_tifxyz`, `vc_grow_seg_from_seed` |
| [`lasagna/`](https://github.com/ScrollPrize/villa/tree/main/lasagna) | PyTorch mesh growing and refinement, multi-sheet, fiber tracing |
| [`spiral-fitting/`](https://github.com/ScrollPrize/villa/tree/main/spiral-fitting) | Fits one global spiral to a whole scroll |
| [`ink-detection/`](https://github.com/ScrollPrize/villa/tree/main/ink-detection) | Ink models built on the 2023 Grand Prize model |
| [`dinovol/`](https://github.com/ScrollPrize/villa/tree/main/dinovol) | Self-supervised 3D DINO for CT volumes |
| [`foundation/`](https://github.com/ScrollPrize/villa/tree/main/foundation) | Dataset and cloud infrastructure tools |
| [`scrollprize.org/`](https://github.com/ScrollPrize/villa/tree/main/scrollprize.org) | The website, including the prize page and eligibility data |

Models: [huggingface.co/scrollprize](https://huggingface.co/scrollprize). Training logs: [W&B](https://wandb.ai/vesuvius-challenge/projects).

## What `kit/` adds on top

Small, standard-library helpers for the parts villa does not cover:

| `kit` | Gap it fills |
| --- | --- |
| `prizes` | One dated, tested place for amounts, deadlines and eligible volumes, with S3 names resolved |
| `doctor` | Tells a newcomer what is missing before a 25 GB download fails |
| `plan` | Copies the official commands for a scroll, control first, and prints the 8.64 µm resampling caveat |
| `run` ledger | Preregistered readout rule with a hash, costs, provenance hashes, attached checks, status history, and a gate against early disclosure |
| `verify` | CPU vs MPS (or any two runs) map agreement, valid only when a control map is caught |
| `rowscore` | Text-row periodicity triage score for ink maps (port of Bullo27's), forward vs reverse |

## Where to grow it

Add to `kit/` only what is specific to running and recording experiments. Anything that would help other participants (a QA check, a renderer fix, a better tracer) belongs upstream as a villa pull request, where it can win a Progress Prize and actually get used. Keep a link to the PR here.

Candidates, roughly in order of value:

1. Done: `kit run record` (command lines and SHA-256 of checkpoints or outputs) and `kit verify` (map agreement with a control).
2. Done: `kit rowscore`, Bullo27's row-periodicity triage score, forward against reverse and averaged over checkpoints. Still open: candidate components above a control-derived threshold (millerandmuller's method).
3. A thin wrapper over [`vesuvius-catalog`](https://github.com/Schurkai/vesuvius-catalog) to refresh the volume table instead of the one-off bucket listing.
4. A Modal or RunPod launcher that enforces a cost cap.
