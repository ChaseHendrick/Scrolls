# Working on an Apple Silicon Mac (M1 Pro)

Checked 2026-10-07. Apple Silicon has no CUDA. Much of the pipeline still runs, but full-segment ink inference is slow on stock villa.

```bash
python -m kit doctor              # on a Mac: "Apple Silicon, no CUDA" is a warning, not a failure
python -m kit plan PHerc0826 --mac
```

## What runs locally

| Step | On an M1 Pro | Source |
| --- | --- | --- |
| Browse scrolls, grow and fix surfaces (GrowPatch) | Yes: native `VC3D.app` for Apple Silicon | [VC3D README, macOS](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer) |
| Render a surface volume (`vc_render_tifxyz`) | Yes: CLI tools ship in `VC3D.app/Contents/MacOS/` | same |
| Flatten with lasagna | Yes, on the GPU: `--device mps` (float32 by default; `LASAGNA_MAX_PRECISION_FLOAT=64` for float64 on CPU) | [villa #1639](https://github.com/ScrollPrize/villa/pull/1639), merged 1 Sep 2026 |
| Ink inference, stock villa | CPU only (`cuda` if available, else `cpu`, in `inference_runtime.py`) | villa `e0bbb8b` |
| Ink inference on the Mac GPU | Open, unreviewed PRs; see below | [#1865](https://github.com/ScrollPrize/villa/pull/1865), [#1812](https://github.com/ScrollPrize/villa/pull/1812) |
| CPU analyses (scan atlas, catalog, audits) | Yes | [first-letters-scan-atlas](https://github.com/claudepro1515/first-letters-scan-atlas), [vesuvius-catalog](https://github.com/Schurkai/vesuvius-catalog) |
| Training ink models | Not practical; rent a CUDA GPU | [compute.md](compute.md) |

Known VC3D issue: the stable build crashes opening some catalog samples, PHerc0826 among them. The latest build fixes it. Re-opening a sample can show a blank view until VC3D restarts ([villa #1910](https://github.com/ScrollPrize/villa/issues/1910)).

## Mac GPU ink inference: already in progress upstream

Several people have written this patch already. Do not write another one.

| PR | Author | Evidence reported | Status 2026-10-07 |
| --- | --- | --- | --- |
| [#1865](https://github.com/ScrollPrize/villa/pull/1865) | nerln | M-series: 114 s CPU vs 38 s MPS on PHerc0139 w029; maps differ by at most 1/255 on 0.002% of pixels | Open; Copilot flagged a regression test that fails on Apple Silicon; a reviewer reported a torch 2.12.1 non-blocking copy bug and a fix |
| [#1812](https://github.com/ScrollPrize/villa/pull/1812) | AndreasHad04 | M1 Max: 0.427 vs 3.261 s per tile; MPS vs CPU max diff 9.5e-7; needs torch 2.14 (fails on 2.8) | Open, awaiting code owner |
| [#1770](https://github.com/ScrollPrize/villa/pull/1770) | SurgeFok | M5 Pro: 2.4x end to end | Closed for inactivity |

Related open work: training on MPS ([#1927](https://github.com/ScrollPrize/villa/pull/1927)), `vesuvius.predict` on MPS ([#1988](https://github.com/ScrollPrize/villa/pull/1988)), spiral fitting on MPS and CPU ([#1925](https://github.com/ScrollPrize/villa/pull/1925)).

To use one now:

```bash
cd villa
git fetch origin pull/1865/head:pr-1865 && git checkout pr-1865
```

Record the PR and commit in your ledger (`--villa-commit`). Before trusting MPS output, run the PHerc0139 w035 control on the CPU and on MPS and compare the two maps. If they differ by more than a few grey levels, use the CPU result and report the difference on the PR.

## A useful M1 Pro contribution

A fourth speed benchmark adds little. These would help:

1. **Reviewer-grade verification on the PRs.** Use the three checks from the [GENChase Apple GPU backend](https://github.com/ChaseHendrick/GENChase/blob/main/apps/validate/APPLE-GPU.md): MPS vs CPU difference under a stated tolerance; a deliberately wrong configuration that the comparison must catch (for example reversed depth order, which should move the map well beyond the tolerance); and an interrupted-and-resumed run that matches an uninterrupted one. Post the numbers on the PR with torch version, macOS version and chip. That kind of evidence is what lets a code owner merge.
2. **Reproduce the torch 2.12.1 bug report** on an M1 Pro, with and without the proposed fix, so #1865 can settle it.
3. **Fix the Apple Silicon regression test** flagged on #1865, coordinating with its author first.

Comment, then ask before pushing to someone else's branch.

## Long runs on a laptop

CPU inference on a full segment can take hours. Plug in, keep the lid open or use `caffeinate -i`, and watch temperatures. [Thermal Pilot](https://github.com/ChaseHendrick/ThermalPilot) shows live fan and SMC temperature readings in its default read-only mode. Do not use its experimental power tuning during runs you will report: its own README says above-stock clocks are unverified.
