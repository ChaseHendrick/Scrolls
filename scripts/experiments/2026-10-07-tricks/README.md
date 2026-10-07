# Tricks on PHerc0841, CPU (2026-10-07)

The scripts behind [`docs/tricks.md`](../../../docs/tricks.md)'s measured table, as run in a Linux container (4 CPUs). Paths come from `S` (default `~/scrolls-cpu`); they assume the layout below, which an agent rebuilds in about 30 minutes. These are Linux bash (associative arrays), not for macOS bash 3.2.

| Path under `$S` | What | How |
| --- | --- | --- |
| `smoke-work/` | villa (PR #1865) venv and `ink_9um` checkpoints | `SMOKE=1 EXPECT_GPU=cpu WORK=$S/smoke-work bash scripts/mac-w045.sh` once (it builds the venv and downloads seeds 42 and 43) |
| `smoke-work/checkpoints/ink_9um/hybrid_3d2d-seed42/step-0{4,5,6}0000.pth` | for the soup | `curl -L` from `huggingface.co/scrollprize/ink_9um/resolve/main/hybrid_3d2d-seed42/` |
| `models/d9v2/d9v2_ft-012000.pth`, `models/reader_v2/reader-v2-step040000.pth` | community readers | TAUIL-Abd-Elilah v1.0 release; `domenicor046/reader-v2` (SHA-256 in `docs/results.json`) |
| `data/p0841/<segment>/{sv,inklabels,supervision}.zarr`, `data/w045_9um.zarr`, `data/w045_labels/` | surfaces and labels | `python -m kit fetch` (segment names and label paths in `docs/results.json` "segments") |
| `tricks/soup42_last4.pth` | the soup | `python scripts/soup.py ...` (see `docs/tricks.md`) |

Order: `crops_and_bars.sh` (crops and the `ink_9um`/d9v2 bars), `tricks.sh` (soup, z windows, mirror TTA, shuffle control), `reader_v2.sh`, then `python score.py NAME=map ...` (see the handoff for the exact list). `finetune_smoke.sh` is the fine-tune smoke test.
