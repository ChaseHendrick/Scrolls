# Exposure Atlas records, 4 November 2026

Written by `python -m kit expatlas` ([page](../../tools/expatlas.md)) in Hugging Face CPU Jobs, from public meshes and
the open-data catalog (`metadata.json`, Last-Modified 2 Nov 2026 11:32:29 GMT, ETag
`274f64b9261982444dfd2881f48ae766`). No labels and no CT were read. Every call is Model output of mesh geometry; the
training lists it starts from are Sourced fact or Community report, as each model's entry in
[`kit/data/expatlas-models.json`](../../../kit/data/expatlas-models.json) says.

| File | What | Job, commit |
| --- | --- | --- |
| `plant-v1-attempt2-2026-11-04.json` | Instrument checks, rule version 1: FAIL on the adjacent-winding control ([prereg](../../prereg/2026-11-04-expatlas-instrument.md)) | `6aeaa27a0e0338d1bb7f85ec`, `34c3683` |
| `plant-v2-2026-11-04.json` | Instrument checks, rule version 2: PASS ([prereg](../../prereg/2026-11-04-expatlas-instrument-v2.md)) | `6aeaa4410e0338d1bb7f866e`, `7741f8b` |
| `matrix-2026-11-04.json` | The matrix: 20 labeled segments by 10 models, with each cell's call, shares, covering training meshes and flags, and the labeled segments' overlaps with each other. Rerun after the review fixes of `913e932` (unknown, not clear, wherever exposure is left open) | local run `expatlas-matrix-r2-20261104` (4-core cloud container, 217 s), `913e932` |
| `matrix-2026-11-04.txt` | The same, as `python -m kit expatlas show` prints it | |
| `matrix-2026-11-04-first-run.json`, `.txt` | The first matrix, kept as a record. Every share is the same as in the rerun; 8 cells differ in their call: ink_canonical_2um on the 8 PHercParis4 segments read clear there and unknown now (two of its train names have no scroll), and Reader V3's 3 PHerc0841 cells read clear in both, now from its card's statement instead of by default | `6aeaa4cfc78863f9c6322578`, `7741f8b` |

Rebuild: `python -m kit expatlas matrix --out DIR --scroll PHerc0009B --scroll PHerc0500P2 --scroll PHerc0814
--scroll PHerc0841 --scroll PHerc1667 --scroll PHercParis4` (76 s on an 8-vCPU HF cpu-upgrade Job, 217 s in a 4-core cloud container).

Shares and other decimals are rounded to 4 places from the Jobs' output; each file's `rounding` field holds the
sha256 of the raw output.

"clear" means no covering training mesh was found among the names that resolve to catalog meshes; it does not
prove a model held out. "unknown" cells say why in their `why` and `flags` fields.
