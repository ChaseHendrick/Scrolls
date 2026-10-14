# StrokeNet: held-out run and tile grid pilot evidence

Public data only: the organisers' published ink maps of PHerc. Paris 4 (July 2026 tracings, `new_canon_autoresearch_recipe-tile256-stride128`). Made on 14 October 2026 with the code in [`scripts/strokenet/`](../../../scripts/strokenet/) and [`kit/strokenet.py`](../../../kit/strokenet.py), under the preregistrations [`2026-10-14-strokenet.md`](../../prereg/2026-10-14-strokenet.md) and [`2026-10-14-gridpilot.md`](../../prereg/2026-10-14-gridpilot.md), on rented cloud GPUs. The model card [`../../strokenet.md`](../../strokenet.md) explains every measure and gives the reading. All numbers are Model output.

| File | What |
| --- | --- |
| `results.json` | Run `20261014T141348Z`: the verdict line, every measure of every model (released, seeds 1 and 2, ablations, both controls) and every baseline on the six held-out segments, per-segment values, block-bootstrap intervals, the comparisons with simple scores, the controls on test, the ablations, the data check and the SHA-256 of every executed file (`provenance`) |
| `gate.json` | The validation gate, passed before the test split was read |
| `calibration.json` | Platt parameters, blank threshold and validation reference values of each model |
| `choice.json` | The six sweep rows and the configuration the preregistered rule chose |
| `baselines.json` | The eleven simple baselines fitted on training windows |
| `data-manifest.json` | The run's rebuild of the 27 segments' maps, equal to [`../../strokenet-data-manifest.json`](../../strokenet-data-manifest.json) |
| `runs/*.history.json` | Training histories of the sweep, seeds, ablations and controls |
| `gridpilot-result.json` | The tile grid pilot (run `20261014T161031Z`, one NVIDIA B300): region, render speeds, the readout and the full re-render projection in GPU hours. Public extract: the cost fields are removed |

Not published, as the preregistration says: window positions, score grids, evaluation arrays and the pilot's pooled renders. The released weights are the GitHub release `strokenet-paris4-v1` (SHA-256 in [`kit/data/strokenet-weights.json`](../../../kit/data/strokenet-weights.json)).

Both preregistrations are published byte for byte as they were frozen (their SHA-256 are in the run records), so their links to the private run spec and cloud runner do not resolve here.

`SHA256SUMS` covers every file in this folder except itself and this README (`sha256sum -c SHA256SUMS` here).
