# fibercheck: are papyrus fibers visible on a traced surface?

A per-patch fiber map of a tifxyz segment, judged by a small free model (no key) or by Claude with your own key, with a self-check on every run; also the Fiber Checker Space.

| Field | Value |
| --- | --- |
| Id | `fibercheck` |
| Status | Current |
| Kind | script folder,app,model |
| Area | Scoring and controls |
| Run | `python3 scripts/fibercheck/fibercheck.py score`, `python3 scripts/fibercheck/fibercheck.py compare`, `python3 scripts/fibercheck/fcmodel.py judge`, the Space [SharpMeow/fiber-checker](https://huggingface.co/spaces/SharpMeow/fiber-checker) (`spaces/fiber-checker/app.py`) |
| Code | `scripts/fibercheck/fibercheck.py`, `scripts/fibercheck/fcmodel.py`, `spaces/fiber-checker/app.py` |
| Tests | `tests/test_fibercheck.py` |
| Needs | Python 3.10 or later; numpy, scipy, tifffile, imagecodecs, numcodecs, pillow, torch (CPU is enough); anthropic only for `--judge claude`; the weights `fibercheck-local.pt` (SHA-256 `e43c25b3...`, a file of the Space) |
| Runs on | CPU: 60 patches of an open-data segment in about 80 s on the free Space CPU and about 2.5 minutes from a cold cache in a cloud container (measured 2026-10-26) |
| Network | The CT's OME-zarr when `--ct` is an https URL (the Vesuvius Challenge open-data bucket); api.anthropic.com for `--judge claude` |
| Writes | `--out`: `fiber.json`, `fiber_map.png`, `fiber.tif`, `report.html`, `tiles/`; CT chunks in `--cache` (default `~/.cache/fibercheck`) |
| Go-ahead | Not needed for the free judge; `--judge claude` spends on your own Anthropic key, up to `--max-usd` |
| Release id | `fiber-checker` |
| License | Code and weights Apache 2.0; scans and meshes it reads CC BY-NC 4.0 (Vesuvius Challenge open data) |
| Released | Public `main` and the Space SharpMeow/fiber-checker since 2026-10-26 |
| Checked | 2026-10-26 against commit `2cbb856` |

## What it does

The Progress Prize asks entrants to "show visually that papyrus fibers are visible on your output surface"
([scrollprize.org/prizes](https://scrollprize.org/prizes)). fibercheck measures that. It cuts a traced segment (a
tifxyz mesh: `x.tif`, `y.tif`, `z.tif`) into square patches of 28 x 28 vertices, renders the CT along each patch, and
asks a judge whether the render shows papyrus fibers (long, thin, parallel strands) more clearly than a copy with the
same texture but its strands scrambled (a phase scramble). The judge's preference is the patch's **fiber evidence**:
near 1 where fibers show, near 0.5 where the render looks no more fibrous than scrambled texture.

There are two judges. The **free local model** (`fcmodel.py`, about 40,000 weights) runs on a CPU with no key; it was
trained on Claude's answers about renders of four public scrolls. **Claude** (`--judge claude`) asks the same
question with your own Anthropic key, in both orders. Every run also checks the judge against noised, blurred and
scrambled copies of its own patches and says if the judge did not beat them.

It does not tell which sheet a trace is on. Each patch is rendered at the brightest depth within 5 voxels of the
trace (the tested rule), and sheets lie close together, so a trace a few voxels off, or on the neighboring sheet, can
still show fibers. A clear map says fibers show on and near the surface. Its output is model output about texture,
never a reading of text.

## When to use it

- Showing that fibers are visible on a surface you traced, for a prize entry (`report.html`).
- Checking a tracer's or an edit's surfaces against each other, patch by patch (`compare`).
- Finding stretches of a segment where the CT along the trace shows no fiber texture (air, gaps, unclear CT).

Do not use it:

- To tell whether a trace stays on one sheet: see [sheetcheck](sheetcheck.md) for the neighbor-sheet check.
- To score ink: see [auc](auc.md).

## Quick start

```bash
pip install numpy scipy tifffile imagecodecs numcodecs pillow torch
B=https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com
M=$B/PHerc0500P2/segments/20250611171318-z_dbg_gen_00440_inp_hr/mesh/20250611171318-on-20250526151718-2.215um.tifxyz
mkdir -p seg && for f in x.tif y.tif z.tif; do curl -sS -o seg/$f $M/$f; done
curl -sSL -o fibercheck-local.pt https://huggingface.co/spaces/SharpMeow/fiber-checker/resolve/main/weights/fibercheck-local.pt
python3 scripts/fibercheck/fibercheck.py score seg --ct $B/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr \
    --level 2 --max-patches 60 --weights fibercheck-local.pt --out out
```

It printed (2026-10-26):

```text
PROGRESS 50/60 patches rendered (101 s)
judging 55 patches with the local judge
self-check: the judge against noised, blurred and scrambled copies
fibercheck: 55 patches, fibers visible on 100% (median evidence 0.99), self-check passed; wrote out/fiber.json, fiber_map.png, fiber.tif, report.html
```

It worked when the last line says `self-check passed`. Or use the Space: pick the same example and press Check fibers.

## Checks and controls

Every run judges the render against a noised, a blurred and a phase-scrambled copy of itself on up to 40 of its
patches (`--check-n`); the self-check passes when the judge prefers the render at least 80% of the time against each.
A failed self-check means that run's numbers cannot be trusted.

The free judge passed a preregistered test, run once, on two public scrolls it never saw (2026-10-26), against the
frozen fiber controls. Shares are the fraction of pairs where the judge preferred the real render; the pixel measure is
structure-tensor coherence:

| Pair | PHerc0500P2 (120 patches) | PHerc0343P (62 patches) | Pixel measure |
| --- | --- | --- | --- |
| Sheet vs the gap beside it | 1.00 | 1.00 | 0.79, 0.76 |
| Sheet vs a 14-pixel tile shuffle (a size never trained on) | 0.98 | 0.92 | 0.53, 0.57 |
| Sheet vs 3 voxels off | 0.87 | 0.68 | |

Both sets were also valid on leave-one-segment-out. A first round failed (it preferred tile-shuffled renders,
rewarding the edges a shuffle adds) and is kept on record; round two added shuffles of 7, 21 and 28 pixels to
training. The tests used built controls, not real faulty traces.

Claim label: Model output (fiber evidence and maps); the test numbers above are Model output from a preregistered test.
Jump hints, fiber direction and best depth are Untested ideas.

## Commands and options

### score

```text
usage: fibercheck score [-h] --ct CT [--level LEVEL] [--p P] [--k K]
                        [--check-n CHECK_N] [--stride STRIDE]
                        [--max-patches MAX_PATCHES] [--judge {local,claude}]
                        [--weights WEIGHTS] [--max-usd MAX_USD]
                        [--cache CACHE] --out OUT [--json]
                        segment
```

| Option | Default | Meaning |
| --- | --- | --- |
| `segment` | required | a tifxyz folder (`x.tif`, `y.tif`, `z.tif` in the scan's level-0 voxels) |
| `--ct` | required | the scan's OME-zarr root, a path or an https URL |
| `--level` | `2` | pyramid level to read: 2 for 2.2 to 2.4 um scans (tested), 0 for 7.9 to 9.4 um |
| `--p` | `28` | vertices per patch side |
| `--k` | `5` | upsampling per vertex step; 5 is tested; 0 picks the median vertex spacing |
| `--check-n` | `40` | patches sampled for each self-check control |
| `--stride` | `--p` | grid step in vertices |
| `--max-patches` | `400` | at most this many patches, sampled with a fixed seed |
| `--judge` | `local` | `local` (free model) or `claude` (your key) |
| `--weights` | `scripts/fibercheck/weights/fibercheck-local.pt` | the free judge's weights |
| `--max-usd` | `2.0` | `--judge claude`: stop asking past this spend |
| `--cache` | `~/.cache/fibercheck` | CT chunk cache |
| `--out` | required | output folder |
| `--json` | off | print only the summary as JSON |

### compare

```text
usage: fibercheck compare [-h] [--out OUT] [--json] a b
```

| Option | Default | Meaning |
| --- | --- | --- |
| `a`, `b` | required | two `score` output folders |
| `--out` | none | also write `compare.json` there |
| `--json` | off | one-line JSON |

### fcmodel.py judge

`python3 scripts/fibercheck/fcmodel.py judge --weights W.pt --set DIR --out replies.jsonl` answers every pair of a
frozen-format manifest. `cv` and `train` need the training sets, which are not public.

| Option | Default | Meaning |
| --- | --- | --- |
| `--weights` | required | `judge`: the weights file |
| `--set` | required | `judge`: a folder with a frozen-format `manifest.json` and its images |
| `--out` | required (`cv`: `work/fibercheck/cv.json`) | `judge`: replies.jsonl; `train`: the weights file; `cv`: the settings table |
| `--sets` | required | `cv`, `train`: the folder of training sets |
| `--epochs` | `cv`: `6 12`; `train`: required | passes over the training pairs (the released weights: 12) |
| `--lr` | `cv`: `0.002`; `train`: required | learning rate (the released weights: 0.002) |
| `--negatives` | `phase` | `train`: synthetic negatives; the released weights used `phase,shuf7,shuf21,shuf28` |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | unset | your own key, for `--judge claude` only |
| `SPACE_HOST` | unset | set by Hugging Face on the Space; the page uses it to print its own API address |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `fibercheck.score(a, say=None, api_key=None)` | the record (dict, as `fiber.json`) | `SystemExit` with a message | `a` holds the `score` options; `say` gets progress lines |
| `fibercheck.render_patches(folder, ct, level, P, K, ...)` | (patches, valid, K) | `FileNotFoundError` | each patch has `r`, `c`, `t0` and the depth stack |
| `fibercheck.CT(root, level, cache)` | a reader with `.values(zyx)` | `urllib.error.HTTPError` | zarr v2, local or https, nearest voxel, 0 outside |
| `fibercheck.LocalJudge(weights).prefer(a, b)` | (P(a over b), unsure) | | inputs through `fibercheck.to_input` |

## Inputs

- A tifxyz mesh: three float TIFFs of the same shape, the x, y and z of each vertex in level-0 voxels of the scan;
  -1, NaN or all-zero vertices are holes. Open-data meshes are under each segment's `mesh/` folder, one per scan.
- The scan's OME-zarr (zarr v2), read at `--level`.

## Outputs

| File | What it is |
| --- | --- |
| `fiber.json` | the record: options, `summary`, `jump_hints`, every patch |
| `fiber.tif` | float32, the mesh's own grid (same shape as `x.tif`): each scored vertex holds its patch's evidence, NaN elsewhere |
| `fiber_map.png` | the map in color: yellow clear, purple weak, grey no sign, slate not scored, black no surface |
| `report.html` | one page: the summary, the map, the six clearest and six weakest patches, the method in the prize's words |
| `tiles/` | those twelve renders as PNG |

| Field | Type | Meaning |
| --- | --- | --- |
| `summary.patches` | int | patches scored |
| `summary.share_fibers_visible` | float | share with evidence 0.75 or more |
| `summary.median_evidence` | float | 0.5 none, 1 clear |
| `summary.share_unsure` | float | share whose answer changed under quarter turns |
| `summary.self_check` | object | `against` (share per control) and `passed` |
| `patches[].evidence` | float | that patch's fiber evidence |
| `patches[].t0` | int | depth of the render, voxels from the trace |
| `jump_hints`, `best_depth`, `direction` | | untested ideas |

| Exit code | Meaning |
| --- | --- |
| `0` | the map was written; read `summary.self_check.passed` before using it |
| `1` | a refusal (message on stderr), such as no renderable patch or no key for Claude |
| `2` | a missing or wrong argument |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `fibercheck: no patch of the segment could be rendered (holes, masked CT or wrong --ct)` | Every 28 x 28 patch has holes, or more than 1% masked CT, or the mesh is not in that scan's voxels | Check `--ct` and `--level` match the mesh's scan |
| `fibercheck: --judge claude needs ANTHROPIC_API_KEY (your own key)` | No key in the environment | Export your own key, or use the free judge |
| `upload a zip of your tifxyz folder (x.tif, y.tif and z.tif)` | The Space got no file | Upload the zip |
| `give two fiber.json files from this Space or the command line tool` | Compare got something else | Give two `fiber.json` files |
| `the Claude judge needs your own Anthropic API key (it is used for this run only)` | Claude chosen on the Space with no key | Paste your key, or use the free judge |
| `the game's pictures are not on this copy of the Space` | `assets/game.npz` was not uploaded | Run `spaces/fiber-checker/tools/build_game.py` |
| `you already have a check running; wait for it to finish (one at a time)` | One check per visitor on the Space | Wait |
| `the zip needs x.tif, y.tif and z.tif (a tifxyz folder)` | The zip lacks a coordinate file | Zip the whole tifxyz folder |
| `...is over 400 MB` | The Space caps each coordinate file | Run the command line tool instead |

## How it works

1. Read the mesh, scale it to `--level`, and compute vertex normals by central differences.
2. Take patches of `P = 28` vertices on a grid; skip any with a hole; sample at most `--max-patches` (seed 0).
3. Upsample each patch by `K = 5` and read the CT at `DEPTHS = -5..5` voxels along the normals; the render is the
   depth with the brightest mean (the frozen rule); skip patches with more than 1% zero voxels.
4. Scale each render to its 1 and 99 percentiles, z-score it, and ask the judge to prefer it or its phase-scrambled
   copy. The local judge scores each image under four quarter turns and takes sigmoid of the mean score difference.
5. Self-check against noise, blur (Gaussian, sigma 3) and phase scramble on `--check-n` patches; pass at 0.8 each.
6. Write the map, the record and the report.

## Cost and time

Free judge: CPU only; 60 patches in about 80 s on the Space's free CPU (2026-10-26), most of it reading CT. A whole
segment of 400 patches takes about 15 minutes. Claude judge: about two calls per patch plus the self-check, on your
key, capped by `--max-usd`.

## For agents

- **Command:** `python3 scripts/fibercheck/fibercheck.py score SEG --ct URL --level 2 --weights W --out OUT --json`, or the Space's `/check_segment` endpoint (gradio_client or MCP).
- **Parse:** the printed JSON summary: `share_fibers_visible`, `median_evidence`, `self_check.passed`.
- **Rerun:** safe; it overwrites `--out`; the CT cache is reused.
- **Success:** exit 0 and `self_check.passed` true.
- **Not a pass:** any number from a run whose self-check failed; a high share on a mesh outside the tested setting is a first look only.
- **Go-ahead:** nothing for the free judge; Claude spends on the user's own key.
- **Never:** call a fiber map a reading or evidence of text; claim it proves a trace stayed on one sheet.

## Tests

`python -m unittest tests.test_fibercheck`: upsampling, normals, auto upsampling, the zarr reader on a local array,
phase scramble moments, map colors, jump hints, fiber direction and the frozen prompt (skipped where the frozen
procedure is absent). Not covered: the network reads and the judges themselves, which the Space's live check covers.

## History

- 2026-10-26: Fiber Checker: free fiber map of traced segments, Space and command line tool (`2cbb856`).
- 2026-10-27: the Space gains a Welcome tab (hero mosaic, the judge's pairs, an example map), GIFs and stills in its How-to guides, a side-by-side Compare table, and tab links that work on phones.

## Related

- [sheetcheck](sheetcheck.md): the neighbor-sheet check, which fibercheck does not do.
- [lasagna-fields](lasagna-fields.md): the Space whose look this one follows.
- `spaces/fiber-checker/`: the Space's source, connect panel and deploy script. Its pictures stay on the Space, never in git: `tools/build_game.py` (the game), `tools/record_howto.js` (frames of the How-to guides, with Playwright) and `tools/build_media.py --run DIR --shot PNG --frames DIR` (the welcome page's pictures and the guides' GIFs).
