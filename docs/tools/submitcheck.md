# submitcheck: preflight a prize submission folder against the prize page's file rules

`python -m kit submitcheck FOLDER` checks a folder you plan to submit for a Vesuvius Challenge milestone prize against the file rules on the prize page, quotes the rule behind every flag, and lists the rest of the page's requirements for you to check.

| Field | Value |
| --- | --- |
| Id | `submitcheck` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Planning and prizes |
| Run | `python -m kit submitcheck`, `from kit import submitcheck` |
| Code | `kit/submitcheck.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_submitcheck.py` |
| Needs | Python 3.10 or newer. numpy and tifffile for the grid numbers (they come from [`kit tifxyz`](tifxyz.md)); without them, or with `--no-grids`, the file checks still run |
| Runs on | Any machine. 0.23 to 0.36 s on a 200 x 150 node made-up mesh (3 runs), 2.4 s on PHerc0139 w035 at 2.399 um (1,132 x 1,020 nodes), measured 24 Oct 2026 in a 4-core cloud container |
| Network | None: the rules are quoted in the code, read from the page on the date below |
| Writes | Nothing |
| Go-ahead | Not needed: it reads a local folder. Submitting stays the entrant's own act |
| Released | Public `main` from the change that adds it (24 Oct 2026) |
| Checked | 2026-10-24 against commit `cc03099` |

## What it does

The prize page ([scrollprize.org/prizes](https://scrollprize.org/prizes), read 24 October 2026) states what a 2027 Grand Prize, First Letters or PHerc. Paris 4 title submission must contain. Some of that is about files: meshes in tifxyz format with a flattening, images named after the mesh they were rendered from, and for the Grand Prize meshes named `column_01.tifxyz`, `column_02.tifxyz` and so on "following the order of the windings". `submitcheck` applies only those file rules, each with the page's own sentence:

- **problem** (exit 1): no `.tifxyz` folder; a mesh missing `x.tif`, `y.tif`, `z.tif` or `meta.json`; a grid that does not load or has no valid node; no image; an image named after no mesh in the folder; for the Grand Prize, a mesh not named `column_NN.tifxyz`, or a column number missing or used twice.
- **note**: a stated rule the folder may break that a script cannot decide: for First Letters, more than one image (the page asks for "a single static image"); for the Grand Prize, no image besides the per-mesh ones (so no banner image, whose name the page does not set), or a mesh with no image named after it (allowed when one image shows "a sequence of consecutive wraps").
- **info**: each mesh's area, holes, folds and stretched nodes from `kit tifxyz check`, and its median edge length against the step `meta.json` promises with the share of edges within 10 %. The page asks for "a low-distortion isometric 2D parametrization" and states no number, so these are figures to show the reviewers, never a flag.
- **you check**: every other requirement the page states for that prize, quoted: the 1 cm scale bar and letter sizes, no manual annotation of characters, which scroll, legibility, no training overlap, the Docker image, false-positive mitigation, held-out validation, the Discord registration.

An image is "named after" a mesh when its name, without the extension, is the mesh's name without `.tifxyz`, or starts with it followed by a character that is not a letter or digit (`patch_a_ink.png` for `patch_a.tifxyz`; `col10.png` is not named after `col1.tifxyz`).

It never says a submission will win or pass review: legibility, false-positive mitigation and the methodology are judged by the organizers' Technical and Papyrology Teams. Its numbers describe mesh geometry, not ink, and make no claim about any scroll.

## When to use it

- Before emailing or filling in a prize form: on the exact folder you will send.
- While building an exporter that writes submission folders, as its last step.

Do not use it:

- As a review of the result: it does not look at the images.
- For a Progress Prize: those have no fixed file layout.
- After the prize page changes: the quotes are from 24 October 2026; compare them with the live page ([prizes.md](../prizes.md) has the same quotes as a table).

## Quick start

```bash
python -m kit submitcheck MY_SUBMISSION --prize first-letters --voxel-um 7.91
python -m kit submitcheck MY_SUBMISSION --prize grand --json
```

`MY_SUBMISSION` is the folder; `--voxel-um` is the voxel size of the volume your meshes are on, so areas print in cm2. On a made-up First Letters folder holding `patch_a.tifxyz` (a 200 x 150 node sheet), `patch_a_ink.png` and `overview.png`, it printed, with exit code 1:

```
  info    patch_a.tifxyz: 7.44 cm2, 0 hole, 0 fold and 0 stretched nodes (kit tifxyz check); median edge length 1.003 and 1.0 of the step meta.json promises, 100.0% of edges within 10 %; the page states no numeric limit
          rule: "already including a low-distortion isometric 2D parametrization (flattening)"
  problem overview.png is named after no mesh in the folder
          rule: "Name each image after the tifxyz mesh (from the same package) used to generate it, so it is traceable to the exact surface it was rendered from."
  note    2 images; the page asks for a single static image
          rule: "Submit a single static image showing the text region."
```

then the "You check" list and `1 problem(s). This checks file rules only; the review teams judge the rest.` With the public PHerc0139 w035 mesh (2.399 um) copied in as `column_01.tifxyz`, beside `column_01.png` and `banner.png`, `--prize grand --voxel-um 2.399` reported 22.07 cm2, no holes or folds, 43 stretched nodes and 99.8 % of edges within 10 %, and exit code 0. It worked when the last line starts `No file problems found`.

## Checks and controls

- **Each file rule can fail** (`tests/test_submitcheck.py`): an empty folder gives two problems (no mesh, no image); a mesh without `z.tif`, an image named after nothing, an unreadable `z.tif`, a mesh named `extra.tifxyz` or `column_03b.tifxyz` in a Grand Prize folder, a gap (columns 1 and 3) and a repeat (two `column_01`) are each named. A clean folder passes, and its area matches the sheet's (19 x 15 cells of 20 x 20 voxels at 2 um).
- **Every quote is the page's**: on 24 October 2026 each of the 40 quoted sentences in `RULES` and `MANUAL` was found in the text of scrollprize.org/prizes, with whitespace and curly apostrophes normalized. Sentences with a long dash were cut before it.
- **No invented limit**: no threshold on area or distortion is applied, because the page states none.

Claim label: Sourced fact for the quoted rules; Interpretation for which rules a script can decide (problem, note) and which it cannot (you check).

## Commands and options

### `python -m kit submitcheck`

```
usage: python -m kit submitcheck [-h] [--prize {first-letters,grand,title}]
                                 [--voxel-um VOXEL_UM] [--no-grids] [--json]
                                 folder
```

| Option | Default | Meaning |
| --- | --- | --- |
| `folder` | required | the folder you plan to submit |
| `--prize {first-letters,grand,title}` | `first-letters` | which prize's rules to apply |
| `--voxel-um VOXEL_UM` | none | voxel size of the meshes' volume in um, for areas in cm2; without it, areas print in vox2 unless the mesh folder name carries `-N.NNNum.tifxyz` |
| `--no-grids` | off | file checks only; skip loading the grids |
| `--json` | off | print the report as JSON |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `submitcheck(folder, prize="first-letters", voxel_um=None, grids=True)` | dict: `prize`, `folder`, `page`, `read`, `meshes`, `images`, `flags`, `manual`, `problems`, `ok` | `VerifyError` for an unknown prize or a missing folder | Meshes are every folder ending `.tifxyz` under `folder`; images every `.png`, `.tif`, `.tiff`, `.jpg`, `.jpeg` or `.webp` file not inside a mesh |
| `format_report(r)` | the printed text | Nothing | |
| `build_parser(p)` | the parser | Nothing | |
| `cmd_submitcheck(args)` | exit code | Nothing | |

Constants: `PAGE`, `READ`, `PRIZES`, `IMAGE_EXT`, `TIFXYZ_FILES`, `COLUMN`, `RULES` (the quoted file rules, by rule and prize), `MANUAL` (the quoted requirements for the person, by prize).

## Inputs

A local folder. Mesh folders end in `.tifxyz` and hold `x.tif`, `y.tif`, `z.tif` and `meta.json` (VC3D's tifxyz layout, [how-to](../segments-without-vc3d.md)); images sit anywhere outside them.

## Outputs

Text, or with `--json` the dict from `submitcheck`. Each entry of `flags` has `level` (`problem`, `note` or `info`), `rule` (a key of `RULES`, or null), `text` and `quote`.

| Exit code | Meaning |
| --- | --- |
| `0` | No problem (notes and info may be present) |
| `1` | One or more problems |
| `2` | No such folder, an unknown prize, or a usage error |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit submitcheck: no folder at PATH` | The folder does not exist | Check the path |
| `kit submitcheck: unknown prize 'X'; choose one of first-letters, grand, title` | From Python, a prize name it does not know | Use one of the three |
| `info    grid numbers skipped: pip install numpy tifffile to get them` | numpy or tifffile is not installed | Install them, or accept file checks only |
| `problem no tifxyz mesh (a folder whose name ends in .tifxyz)` | No mesh folder | Put the meshes in, named `NAME.tifxyz` |
| `problem MESH: missing x.tif, ...` | A mesh folder lacks some of its four files | Copy the whole tifxyz folder |
| `problem MESH: cannot read the tifxyz folder ...` or `problem MESH: the grid has no valid nodes` | A TIFF does not read, the three grids differ in shape, or every node is missing | Re-export the mesh |
| `problem no image (png, tif, jpg or webp)` | No image file outside the meshes | Add the rendered image |
| `problem IMAGE is named after no mesh in the folder` | An image's name does not start with any mesh's name | Rename it after its mesh, or remove it |
| `problem MESH: not named column_NN.tifxyz` (Grand Prize) | A mesh named otherwise | Rename by column, in winding order |
| `problem column numbers used twice: [...]` or `problem column numbers missing between A and B: [...]` (Grand Prize) | Repeated or skipped column numbers | Renumber |
| `problem images named after no mesh: ... (one, NAME, is taken as the banner)` (Grand Prize) | More than one image that is not a per-mesh image | Keep one banner image; rename the others after their meshes |
| `note    no image other than the per-mesh ones, so no banner image; the page sets no name for it` (Grand Prize) | Every image is named after a mesh | Add the banner image the page asks for |
| `note    MESH.tifxyz has no image named after it (fine only if it is part of a sequence of consecutive wraps shown in another image)` (Grand Prize) | A mesh with no image of its name | Add its image, or make sure another image covers it |
| `note    N images; the page asks for a single static image` (First Letters) | More than one image | Send one image of the text region |

## How it works

1. Find meshes (folders ending `.tifxyz`) and images (image files outside them) anywhere under the folder.
2. For each mesh, check its four files, then load it with `kit tifxyz` and take `info`, `stretch` and `check`.
3. For the Grand Prize, match each mesh name against `column_(\d+).tifxyz` and look for repeats and gaps in the numbers.
4. Match each image to the longest mesh name it starts with, followed by a non-alphanumeric character or nothing.
5. Collect flags with their quotes, add the prize's "you check" list, and exit 1 when any flag is a problem.

## Cost and time

Free. Seconds per full-size mesh, almost all of it reading the three TIFFs; see Runs on.

## For agents

- **Command:** `python -m kit submitcheck FOLDER --prize PRIZE --voxel-um UM --json`.
- **Parse:** `ok`, `problems`, `flags[].level`, `flags[].text`, `flags[].quote`, `meshes[].area_cm2`.
- **Rerun:** Safe; read-only.
- **Success:** exit 0 (`ok` true). Exit 1 is a finished report with problems.
- **Not a pass:** `ok` true says the file rules it knows hold, nothing about legibility, ink, or review; never describe it as a submission passing.
- **Go-ahead:** Nothing to run. Submitting needs the entrant's own decision.
- **Never:** put a private or target-scroll folder's report into a public file; the report names meshes and areas.

## Tests

`python -m unittest tests.test_submitcheck -v`: a clean First Letters folder; each file rule failing on its own planted fault; the image-name matching (`col1_render` matches `col1`, `col10` does not); the Grand Prize names, gap, repeat and banner note; an unreadable grid; every flag carrying its rule's quote and no quote holding a long dash; exit codes 0, 1 and 2. The quote check against the live page was run by hand on 24 Oct 2026 (Checks and controls). No network.

## History

- 2026-10-24: added, with the rules read from scrollprize.org/prizes that day (`0da03d1`).

## Related

- [prizes.md, "Questions people ask"](../prizes.md#questions-people-ask-answered-in-the-pages-words): the same rules as quoted answers.
- [tifxyz](tifxyz.md): where the grid numbers come from.
- [tracing tools](../tracing-tools.md): tools that make the meshes.
