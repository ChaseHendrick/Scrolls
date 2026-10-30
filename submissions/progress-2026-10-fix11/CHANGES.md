# AutoPipeline 0.1.11: self-intersections and flattening on current VC3D builds

This package follows AutoPipeline 0.1.10 at public commit `eea2df521d234fb2e0984b0dd79c5f2a8754eef2`. Earlier released branches and tags stay unchanged. Every surface, label and score the pipeline makes is model output, not a reading.

## Why

villa main removed `vc_tifxyz_selfcross` and `vc_flatten` in `e1aa625a6` (29 October 2026, villa #2358). A VC3D build made after that has neither tool. On such a build AutoPipeline 0.1.10 rejected every trace with its self-intersections not measured, and flattened nothing. This version keeps both steps working, with a backend for each that a plan can pick.

## Self-intersections: two backends

`qa.selfcross` (plan setting) or the `selfcross` stage (`plan --use selfcross=NAME`) picks the backend:

- `villa`: villa's `vc_tifxyz_selfcross`, on builds that still have it (villa `7154682e1` or older).
- `kernel`: the same census kernel from villa's source. `python -m kit selfcross build` fetches one file, villa's `vc_tifxyz_selfcross_impl.hpp` at commit `7154682e1`, refuses it unless its sha256 matches, and compiles it on your machine with a small Apache-2.0 driver and a header-only stand-in for the two OpenCV types it uses. villa's code is GPL-3.0; it is never copied into this package, and the compiled program stays on the machine that built it. The kernel reads the surface the way VC3D's loader does (z at or below 0 and a masked cell are invalid, nothing else) and writes the same report as villa's tool.
- `auto` (the default): `villa` where the build has it, else `kernel`. With neither, a run says so and rejects the trace as before, with the reason in its record.

`python -m kit selfcross run --surface SURFACE -o OUT.json` runs either backend alone and `python -m kit selfcross status` says which one `auto` picks. Region crop and the winding benchmark's per-winding score (`kit surfbench gscore`) go through the same backends. The agent tool `check_surface` takes `selfcross_backend` and names the backend in its result.

Parity: on 51 synthetic surfaces (11 named shapes, one for each rule of the census and of VC3D's loader, and 40 seeded random crumpled sheets; 29 of the 51 have transverse contacts), the kernel's report matched villa's tool from the archived VC3D 7154682e1 AppImage in every count, contact list and contact site. Two controls show the comparison could fail: the kernel fed the grid with mask.tif ignored differed on 15 surfaces, and fed it with x = -1 cells also invalidated on 1. `scripts/selfcross/parity.py` reruns it.

## Flattening: vc_flatten or flatboi

`flatten.tool` (plan setting) or the `flatten` stage picks the flattener: `villa` (`vc_flatten`), `flatboi` (villa's SLIM flattener in its tifxyz mode, the replacement #2358 points to) or `auto` (the default: `vc_flatten` where the build has it, else `flatboi`). `flatten.flatboi` sets flatboi's iterations (50), energy (`symmetric_dirichlet`), keep percent and inpainting. flatboi's result goes through the same distortion limits as before; a stretched, diverged or missing result keeps the original surface, with the reason recorded. A flatboi build that only flattens OBJ files is refused, with a message that says so. The agent tool `flatten` takes `tool`, `slim_iterations`, `energy`, `keep_percent` and `inpaint`.

`python -m kit vc3d which` names the replacement for each removed tool, and a render that fails because the build no longer takes `--flatten` says so.

Every new plan setting is absent unless a plan gives it, so every plan made before keeps its digest.

## Other changes since 0.1.10

- `kit snap --source ct --mode rectoedge`: ScrollFiesta's RectoRefine with midline off (its own default), which aims each vertex at the dark-to-bright edge of its sheet. Opt in, for comparisons; its authors measured it harmful on their core, and `midline` stays the default. Its output matches `recto_refine.c` built with a stub sampler, pinned in the tests.
- `kit surfacepred`: `--overlap` now means the share of a patch its neighbor covers, as villa's `vesuvius.predict` reads it since villa #1989 (`6ae6eaadb`, 30 October 2026). Before, it was the step itself; the two agree only at 0.5.
- The README's ink detection paragraph names Reader V3 as the default reader (it has been since 0.1.8; the paragraph still said Reader v2).

## Checks

`tests/test_selfcross.py` checks the loader rule, the backend choice and, where a compiler and villa's header are present, the compiled kernel against villa's recorded counts on the named shapes. `tests/test_autopipe.py` runs the whole chain as a build after #2358 with stand-in tools (flatboi and the kernel), and checks that the kernel rejects a crossing trace, that a run with no backend rejects with the reason, that a plan can pick the backend, and that a stretched or diverged flatboi result is not used. These show the steps run and that the kernel counts as villa's tool counts; they are not a test of any trace.

## Package

Version metadata changes from 0.1.10 to 0.1.11. The Dockerfile runs `python -m kit selfcross build` (and goes on without it if the build fails), so an image built from it holds villa's header and the kernel built from it, both GPL-3.0 like the VC3D AppImage it already holds. The Docker image was not rebuilt for this version. This package does not assert a Progress Prize form submission or award.
