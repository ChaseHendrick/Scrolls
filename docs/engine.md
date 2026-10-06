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
| `run` ledger | Preregistered readout rule with a hash, costs, status history, and a gate against early disclosure |

## Where to grow it

Add to `kit/` only what is specific to running and recording experiments. Anything that would help other participants (a QA check, a renderer fix, a better tracer) belongs upstream as a villa pull request, where it can win a Progress Prize and actually get used. Keep a link to the PR here.

Candidates, roughly in order of value:

1. `kit run` hooks that record villa commit, checkpoint SHA-256 and exact command lines automatically.
2. A forward/reverse depth comparison report for an inference output pair.
3. A thin wrapper over [`vesuvius-catalog`](https://github.com/Schurkai/vesuvius-catalog) to refresh the volume table instead of the one-off bucket listing.
4. A Modal or RunPod launcher that enforces a cost cap.
