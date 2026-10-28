# snapped-labels: published surface labels moved onto the papyrus, as a dataset and a CT viewer

A Hugging Face dataset of the published surface labels of PHerc0139, PHerc0814, PHerc0841 and PHerc0172 with every vertex moved along its normal onto the recto face in the CT, and a static Space that draws them over live open-data CT.

| Field | Value |
| --- | --- |
| Id | `snapped-labels` |
| Status | Current |
| Kind | data,app |
| Area | Surfaces and tracing |
| Run | [huggingface.co/spaces/SharpMeow/snapped-labels](https://huggingface.co/spaces/SharpMeow/snapped-labels) (viewer); `hf download SharpMeow/vesuvius-snapped-labels --repo-type dataset`; the dataset's `load_example.py`; in the page, `window.snappedLabels`; `python -m kit vxsummary check`, `python -m kit vxsummary fixture` (the Voxel exact tab's data) |
| Code | `spaces/snapped-labels/index.html`, `spaces/snapped-labels/app.js`, `spaces/snapped-labels/vx.js`, `spaces/snapped-labels/style.css`, `spaces/snapped-labels/connect.json`, `kit/vxsummary.py`, `spaces/snapped-labels/vx/fixture/` |
| Tests | `tests/test_vxsummary.py` (the Voxel exact data contract, the tab's wiring and the snap media); `python -m kit spaceconnect check` (run by the tests) checks its Connect panel; the page was checked in headless Chromium (see Checks and controls) |
| Needs | A browser for the Space. For the data: Python 3.9+, `huggingface_hub`, `numpy`, `tifffile` and `imagecodecs` |
| Runs on | Any browser; a segment's cross sections are at most about 8 MB, and each CT view reads up to 16 uncompressed 128 voxel chunks |
| Network | `huggingface.co` (the dataset), `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` (CT and the published meshes, read live) |
| Writes | Nothing; `hf download` writes the folder you name |
| Go-ahead | Not needed to use. Releasing the dataset and the Space was Chase's yes (27 Oct 2026); the Space redeploys from merged `main` under the standing yes (rule 8) |
| Released | Public on Hugging Face since 2026-10-27 (dataset and Space); 1.0.1 the same day (`abstain.tif` code 2 for filled vertices); README "Released tools" entry `snapped-labels` |
| License | Data CC BY-NC 4.0, like the open data it comes from; page code Apache 2.0 |
| Checked | 2026-10-27 against commit `ff82a63` |

## What it does

A surface label is a tifxyz mesh that follows one wrap of papyrus in a scan. Published labels sit near the sheet but rarely on it: on fresh test sites, only about a quarter of their vertices were within one voxel of the recto face. Models trained on such labels learn that offset.

The dataset holds every published label of four scrolls after a snap: each vertex moved along its normal onto the face of the bright papyrus band, on the side toward the scroll's center line. On PHerc0139, PHerc0814 and PHerc0841 the face is found in a 2.4 µm scan of the same scroll registered vertex by vertex to the label's scan (finesnap); on PHerc0172 in the label's own 7.9 µm scan (labelsnap). Where a vertex's own face is unclear, nothing is measured at that vertex: it takes a Gaussian-weighted average of its measured neighbors' offsets when one lies within two grid cells (filled, `abstain.tif` 2), and otherwise keeps its published position (`abstain.tif` 1). Of 32.9 million released vertices, 66.0 % are snapped, 33.0 % filled (median move 2.7 voxels) and 1.0 % left in place. The snapped share counts measured vertices only; keep `abstain.tif` 0 to use only vertices whose own face was found. Version 1.0.1 (27 Oct 2026) added code 2; in 1.0.0 filled vertices were marked 1. Each mesh keeps the grid and voxel frame of its source, so it lines up with it vertex for vertex.

The Space draws a segment's published and snapped lines on the CT plane you pick, animates the snap (Animate snap: each line piece moves from its published position to its snapped one, slowly, on a loop), and lists every segment.

A Voxel exact tab shows the frozen voxel-exact tests (live since 28 Oct 2026; it is hidden whenever `vx/summary.json` is missing or does not validate). Per scroll it shows a claim level: Measured (each snapped vertex scored against the face seen in an independent, finer scan, with at least one class clearing the bar; in a two-scan test only on the covered share of sites, where two finer scans agree on the face, shown beside it with its own bar and a plain statement of what exact means there), Certified (a truth-free lower bound with its assumptions listed), or Not shown (with the reason; where a test ran, the card still shows what it measured, which makes no claim). A card gives the share within 0.5, 1 and 2 label voxels with one-sided 95% intervals and the bar, the abstain strata (C0 snapped, C0L snapped in the label scan, C2 filled, C1 left in place) each with its verdict as text and a shape, the signed residual histogram beside the published label's, and the negative controls (the published label, planted offsets, the verso face) with what each required. A segment listed as a showcase adds a per-vertex residual heatmap beside its CT with the truth face drawn dashed; a region appears there only once its truth positions are named as spent, because drawing them publishes where the face is. Below the cards, a cross-section diagram, the steps of a test, the three claim levels and the limits. The data comes from a private exporter through `python -m kit vxsummary check`, which refuses keys outside the contract, numbers that do not add up, costs, long dashes, the word "letter", prize-eligible scrolls and unsafe showcase paths; `?vx=fixture` shows a synthetic fixture (scrolls SYNTH-A to SYNTH-C) under a banner that says every number is made up.

Results shown (28 Oct 2026, Model output). PHerc0139 is Measured, by a two-scan test of 370 code 0 (snapped) sites in z 5384 to 5869 of the label scan, frozen before any site was drawn and scored once. A site is covered when the 1.129 µm scan and a second scan (2.403 µm) both name the recto face and agree within 1 voxel. Coverage: 238 of 370 drawn sites (64.3%, one-sided 95% lower bound 60.0%, bar 40%). On covered sites, 226 of 238 snapped vertices lie within 1 voxel of the two scans' consensus face (95.0%, lower bound 92.0%, bar 90%): PASS. So exact here means exact on the share of code 0 sites where two scans agree within 1 voxel, about 64% of drawn code 0 sites in one band of one scroll; it is never every vertex, codes 1 and 2 are outside it, and two scans cannot see an error they share. Every control held: the published label was within 1 voxel of the consensus face at 26.1% (required below 60%), the 2.399 µm face moved 1.5 voxels at 2.6% and 12.1% (below 50%), moved 3 voxels at 0% (below 20%), the verso face at 0% (below 50%), the second scan moved 1.5 voxels still agreed at 18.2% and 22.0% (below 50%), moved 3 voxels at 1.0% and 1.4% (below 20%), snapped offsets scored against other sites' faces at 22.3% (below 50%), and the 2.399 µm face itself at 92.9% (above 75%). Against the 1.129 µm scan alone the same sites are Not shown: 289 of 370 within 1 voxel counting every unscorable site as a miss, lower bound 74.3%, and the 2.399 µm scan reaches only 70.0% there, so one scan limits that test. An earlier frozen test (680 sites in z 4680 to 5184, against the 1.129 µm scan alone) gave Not shown for every class (code 0: 152 of 200, lower bound 70.5%); it is spent and listed on the card. PHerc0814, PHerc0841 and PHerc0172 have no frozen test yet.

The meshes are geometry. They say nothing about ink or text.

## When to use it

- Training or scoring surface and sheet models: snapped labels put the target on the face instead of beside it.
- Rendering a segment closer to the papyrus, in VC3D, villa or any tifxyz tool.
- Seeing, before you use a label, how far it was off.

Do not use it:

- To fix a label that follows the wrong wrap: a snap moves along the normal only. Check the wrap first.
- Where two sheets touch without a visible gap: the face found there can belong to the neighbor.
- For five PHerc0139 segments and PHerc0841 auto_grown_20260220174252405, which are held out for evaluation: they are not included.

## Quick start

```bash
pip install -U huggingface_hub numpy tifffile imagecodecs
hf download SharpMeow/vesuvius-snapped-labels load_example.py --repo-type dataset --local-dir snapped-labels
python snapped-labels/load_example.py
```

It reads PHerc0841 w00 from the dataset and its published mesh from the open data, and prints the grid, the counts and the median move. It worked when the last line is `matches release.json: True`.

## Checks and controls

- Accuracy (frozen tests on fresh sites, scored against the recto face in an independent 1.129 µm scan): PHerc0139, 60 sites, within 1 voxel 23.7% published, 79.4% labelsnap, 91.2% finesnap; PHerc0814, 60 sites, 24.2% published, 71.0% labelsnap. A 3D surface model trained on snapped PHerc0139 labels placed the surface 0.61 voxels closer on PHerc0814 than the same model trained on the published labels (95% interval 0.39 to 0.84; all 9 seed pairings). These tests could fail, and the published labels are their control.
- Release checks: every segment was snapped in overlapping row bands and stitched; on a test crop a banded finesnap run equals a whole run exactly. `release.json` carries the sha256 of every file and of the source mesh; the stitch refused any held-back vertex that came back valid.
- The page: opened in headless Chromium on the release folder before upload; published and snapped lines were drawn over the CT of PHerc0139, PHerc0841 and PHerc0172.
- The Voxel exact tab (28 Oct 2026): opened in headless Chromium on the synthetic fixture at 1360 px and 390 px, light and dark, with no horizontal scroll; without a summary the page keeps the tab hidden. The two-scan summary was opened the same way, local and live: the tab shows, `voxelExact()` equals the exporter output, no horizontal scroll at 390 px, no page errors. The real summary passes `kit vxsummary check --deploy --online`; its cards were rendered from the page script in Node and every share, bound and control matched the exporter output, which itself recomputes each count, bound and control from the frozen per-site rows and refuses any mismatch. The Animate snap button was played on PHerc0139 w054 over its live CT. `tests/test_vxsummary.py` shows each contract check failing on a summary that breaks it.

Claim label: Model output (the snapped meshes come from a band finder on CT; they are geometry, not a reading). The accuracy figures are the frozen tests' results on fresh sites. On the Voxel exact tab, shares, bounds and histograms are model output, measured; a certificate's bound is model output, certified; the truth face is model output too (found by a rule on the finer scan); which scrolls are prize-eligible is a sourced fact with its read date.

## Commands and options

### The Space

[huggingface.co/spaces/SharpMeow/snapped-labels](https://huggingface.co/spaces/SharpMeow/snapped-labels): Viewer (scroll, segment, z plane, a 96, 192 or 384 voxel window, layers, Animate snap), All segments (with a Claim column once voxel-exact results load), Voxel exact (hidden until results load), How it works, Connect your tool. Keys: left and right step along the label, up and down step z. URL parameters: `seg=SEGMENT`, `z=Z`, `data=URL` (another copy of the dataset), `vx=URL` (another voxel-exact summary; `vx=fixture` for the synthetic fixture), `tab=exact` (open the Voxel exact tab). Animate snap holds 1.2 s on the published line, moves 2.4 s to the snapped one, holds 1.6 s and moves back; with reduced motion it never plays by itself and each click steps published, halfway, snapped.

### `python -m kit vxsummary check`

```
usage: python -m kit vxsummary check [-h] [--deploy] [--online] path
```

| Option | Default | Meaning |
| --- | --- | --- |
| `path` | required | The summary JSON, such as `spaces/snapped-labels/vx/summary.json`; showcase files are read beside it |
| `--deploy` | off | Also refuse the fixture, its placeholder digest and SYNTH scroll ids: run it before a summary ships |
| `--online` | off | Also confirm on Hugging Face that the pinned dataset revision exists (network) |

| Exit code | Meaning |
| --- | --- |
| `0` | Valid |
| `1` | Problems found, one per line on stderr |
| `2` | The summary could not be read |

### `python -m kit vxsummary fixture`

```
usage: python -m kit vxsummary fixture [-h] out_dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `out_dir` | required | The folder to write `summary.json` and `show/` into, such as `spaces/snapped-labels/vx/fixture` |

| Exit code | Meaning |
| --- | --- |
| `0` | The fixture was written | The page has one scroll bar: the segment list grows with the page instead of scrolling on its own, picking a segment far down the list or the table brings the image back into view, and on a phone the list follows the viewer.

### `load_example.py` (in the dataset)

```
usage: load_example.py [-h] [--root ROOT] [--segment SEGMENT]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--root` | the Hub | A local copy of the dataset |
| `--segment` | `PHerc0841/20260220213127-w00` | A segment path from `index.json` |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `window.snappedLabels.segments()` (page) | the index rows | | In the browser console or a headless browser |
| `window.snappedLabels.open(SEGMENT, Z)` (page) | a promise | `Error` for an unknown segment | Opens a segment at the plane nearest Z |
| `window.snappedLabels.animate(ON)` (page) | `true` while it plays | | Starts or stops Animate snap; no argument toggles it |
| `window.snappedLabels.voxelExact()` (page) | the loaded summary, or `null` | | A copy of `vx/summary.json` once it validates |
| `window.snappedLabels.openShowcase(SEGMENT)` (page) | a promise | `Error` when no showcase is listed | Opens a showcase segment's heatmap and CT |
| `vxsummary.check(doc, deploy=False, base=None)` | a list of problems, `[]` when valid | | `base` is the summary's folder, for the showcase files |
| `vxsummary.load(path)` | the parsed summary | `OSError`, `ValueError` | |
| `vxsummary.fixture(out_dir)` | the fixture summary | `OSError` | Writes `summary.json` and `show/` |
| `vxsummary.online_problems(doc, timeout=30)` | a list of problems | | Asks the Hugging Face API for the pinned revision |
| `vxsummary.add_arguments(p)`, `vxsummary.run(args)`, `vxsummary.main(argv=None)` | an exit code (`run`, `main`) | | The command line |
| `window.snappedLabels.view()` (page) | the open view: planes, step, voxel size, `center` ([x, y] in voxels; spelled the British way before 27 Oct 2026) | | `null` before a segment opens |

## Inputs

None to use it. The dataset was made from the published meshes and scans of the Vesuvius Challenge open data; each `release.json` names its source mesh with sha256 and the scans used.

## Outputs

| File | Type | Meaning |
| --- | --- | --- |
| `SCROLL/SEGMENT/snapped.tifxyz/{x,y,z}.tif` | float32 grids | Moved vertices, level-0 voxels of the label scan; `-1` none or held back |
| `abstain.tif` | float32 grid of codes | 0 snapped (face measured at the vertex), 1 not measured and left at its published position, 2 not measured and moved by its measured neighbors' filled offset (since 1.0.1), 255 no vertex or held back |
| `confidence.tif` | float32 grid | 0 to 1 |
| `reason.tif` | float32 grid of codes | Why no face was measured at a vertex |
| `source.tif` | float32 grid of codes | finesnap only: 1 placed in the 2.4 µm scan, 2 in the label scan |
| `release_mask.tif` | float32 grid of codes | 0 released, 1 held back for evaluation, 255 not in the source |
| `release.json` | JSON | Source and scan URLs, sha256 of source and outputs, `release` (`1.0.1`), summary (`vertices_released`, `snapped`, `filled`, `left_in_place`, `abstained`, `move_voxels`, `placed_by`) |
| `index.json` | JSON | One row per segment with its summary |
| `viewer/SCROLL/SEGMENT.{bin,json}` | float32 rows, JSON | The viewer's line pieces per z plane: published ax ay bx by, snapped ax ay bx by |
| `SHA256SUMS` | text | Every file |
| `spaces/snapped-labels/vx/summary.json` (the Space, once approved) | JSON, schema `snapped-labels/voxel-exact@1` | `fixture`, `generated`, `dataset` (repo, release, 40 hex revision), `rule` (tolerances 0.5, 1 and 2, the bar, the interval), `prereg` (sha256, frozen), `prizes_read`, `scrolls` (claim, `why_not_shown`, label scan, truth and oracle scans, `certificate` with `assumptions`, `vertices.by_code`, `void`, `strata` with `within` slots `{basis, k, n, share, lower, upper}` or `null`, `residual_hist`, `published_hist`, `controls`; for a two-scan test also `coverage` `{k, n, share, lower, upper, bar, verdict, what}` with `within` basis `covered`, and `single_truth` `{verdict, instrument_limited, why, within_1, controls}`), per scroll optionally `scope` (what exact means there; required for a two-scan test), `second_truth` and `earlier` (spent earlier tests: `prereg`, `scope`, `summary`), `showcase` |
| `vx/show/SCROLL/SEGMENT.json` | JSON, schema `snapped-labels/voxel-exact-show@1` | A showcase segment, its grids as number lists (no binary files in public Git): `residual` per vertex in voxels (`null` where none), `state` (0 measured, 1 no value, 2 held back), `xyz` vertex positions, `planes` and `rows`, the line pieces per z plane (published, snapped, truth: 12 numbers each), `truth_note`, `volume` (the CT, or `null`) |

| Exit code | Meaning |
| --- | --- |
| `0` | `load_example.py` read the segment and printed its summary |
| `1` | A download or read failed (Python traceback) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| "CT read failed" in the viewer | The open-data bucket did not answer | Reload; the dataset itself is unaffected |
| No lines on a plane | The segment does not cross it, or that part is held back | Step z, or press the arrows |
| `showcase ...: N held-back cells carry a residual; a held-back cell is null` | The exporter wrote a value where the release mask holds the vertex back | Write `null` there; held-back cells are never drawn |
| No Voxel exact tab | No `vx/summary.json` in the Space yet, or it did not validate | Wait for the results; to preview, open `?vx=fixture` or `?vx=URL` (a bad file then shows its first problems) |
| `summary: keys not in the contract: ...` from `kit vxsummary check` | The exporter wrote a key the page does not show | Drop it in the exporter; only allowlisted keys ship |
| `--deploy: the synthetic fixture never deploys (fixture is true)` | `check --deploy` on the fixture | Run it on the real summary |
| `dataset revision ... could not be confirmed` | `--online` without the network, or a wrong revision | Rerun with the network; pin the revision the scorer used |
| `tifffile` cannot read a published mesh | Some source meshes are LZW compressed | `pip install imagecodecs` |

## How it works

The method, its constants and its tests are recorded with the snapping code, which is not part of this release. The release used finesnap's and labelsnap's defaults as frozen for their tests, with evaluation regions held back before any read. The viewer cuts each mesh cell of four released vertices with the z plane (marching squares on the corner z), applying the same edge fractions to the published and snapped meshes so their lines correspond point for point.

## Cost and time

The snap ran on Hugging Face CPU Jobs on 27 Oct 2026; stitching took minutes on a CPU. Using the dataset costs nothing. `kit vxsummary check` takes under a second; the Voxel exact tab reads one small JSON, and a showcase segment a few hundred kilobytes.

## For agents

- **Command:** `python load_example.py --segment SCROLL/SEGMENT`; or read `index.json` and each `release.json`.
- **Parse:** `index.json` rows: `vertices_released`, `snapped`, `move_voxels.median`, `vertices_held_back`; the grids above.
- **Rerun:** Safe; reads only.
- **Success:** `matches release.json: True`; `sha256sum -c SHA256SUMS` passes.
- **Not a pass:** A snapped vertex is not proof the label follows the right wrap.
- **Go-ahead:** Nothing to read it. Changing the dataset or making a new Space needs Chase's yes.
- **Never:** Call the meshes a reading, or train on held-back regions (`release_mask.tif` = 1). Never ship a `vx/summary.json` that the private exporter did not write from frozen, collected verdicts (Chase approved the tab with results on 28 Oct 2026), never ship the fixture as results, and never list a showcase region that is not spent.
- **Voxel exact:** `python -m kit vxsummary check spaces/snapped-labels/vx/summary.json --deploy --online` must exit 0 before a summary ships; in a headless browser, `window.snappedLabels.voxelExact()` returns it once it loads.

## Tests

`python -m unittest tests.test_vxsummary` shows every check of the voxel-exact data contract failing on a summary that breaks it, checks the committed fixture equals a fresh one, checks the tab is hidden until a summary loads and the fixture banner is wired, parses the page scripts with Node, and covers the snap media script's guards. `python -m kit spaceconnect check` covers the Connect panel.

## History

- 2026-10-28: the two-scan result: PHerc0139 Measured on the covered share (coverage 238 of 370, exactness 226 of 238, lower bound 92.0%), the first test kept as an earlier, spent test; `kit vxsummary` gains `coverage`, the `covered` basis, `single_truth`, `scope`, `second_truth` and `earlier`, and refuses a PASS whose bound is under the bar; the hero card now says the 91% counts scorable vertices.
- 2026-10-28: Voxel exact tab, `kit vxsummary`, the synthetic fixture and Animate snap ([PR #255](https://github.com/ChaseHendrick/Scrolls/pull/255)), deployed with the first frozen result: PHerc0139 Not shown (no class cleared the bar; instrument-limited), the other three scrolls not tested yet. A tested scroll that is Not shown keeps its numbers and controls on its card; Measured now needs a class that passed.
- 2026-10-27: one page scroll bar and American English ([PR #253](https://github.com/ChaseHendrick/Scrolls/pull/253)): the segment list grows with the page (after the viewer on phones), a pick from far down the list or table brings the image back into view, and `view()` returns `center` (was `centre`).
- 2026-10-27: dataset and Space released, page added (`bd34a59`).

## Related

- [`spaces/snapped-labels/`](../../spaces/snapped-labels/): the page source.
- [segment-lens](segment-lens.md): every published mesh's geometry.
- [umbilici](umbilici.md): the center lines the snap faces toward.
