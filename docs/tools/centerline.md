# centerline: a scroll's center line into your VC3D project in one command

`python -m kit centerline get SCROLL --into FOLDER` downloads the best public center line (umbilicus) for a scroll, checks its sha256, and writes it as `FOLDER/umbilicus.json`, the file VC3D and villa's spiral fitting look for.

| Field | Value |
| --- | --- |
| Id | `centerline` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Data and downloads |
| Run | `python -m kit centerline list`, `python -m kit centerline get`, `python -m kit.centerline`, `from kit import centerline` |
| Code | `kit/centerline.py`, `kit/find.py` (`centerlines`, `list_prefix`), `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_qol_tools.py` |
| Needs | Python 3.10 or newer, standard library only |
| Runs on | Any machine with HTTPS. `get PHerc0175A` took 0.74 s (measured 2026-10-23, cloud container) |
| Network | Reads, anonymously over HTTPS: `SharpMeow/vesuvius-center-lines`'s `index.json` and one line file on `huggingface.co`, the bucket's `SCROLL/representations/umbilicus/` listing and files, and `metadata.json` when stamping the grid size |
| Writes | `FOLDER/umbilicus.json` (with `--into`), or `--out` (default `SCROLL_umbilicus.json`); written to a `.part` file and renamed |
| Go-ahead | Not needed |
| Released | Public `main` from the change that adds it (23 Oct 2026) |
| Checked | 2026-10-23 against commit `cc03099` |

## What it does

VC3D draws a scroll's center line and uses it for winding numbers, and villa's spiral fitting reads it, but each wants a file named `umbilicus.json` in the right folder with the right fields: VC3D searches the volume package for `umbilicus.json` or `estimated_umbilicus.json`, refuses a folder with both, and needs `volume_width`, `volume_height` and `volume_slices` all present or all absent (villa main 8aa507c12, `volume-cartographer/core/src/ScrollUmbilicus.cpp`; see [umbilicus](umbilicus.md)). The lines themselves sit in two places: our public dataset [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) (person-made, bucket and model lines for the prize-eligible scans and, since v2.3 on 24 Oct 2026, 11 other public scans, each with a sha256) and the bucket's `SCROLL/representations/umbilicus/`. Since v2.4 (24 Oct 2026, commit `c67d4743`) each Center Finder line on a 1.2 m scan also has a polished copy, source `finder-polished` ([axispolish](axispolish.md)): it sat deeper in villa's traced sheet than the line before the polish on all ten scans of its frozen test, so `get` takes it before the original (`--source finder` takes the original). It is jumpier than the original and its ends were not re-checked: smooth it before any use that needs a smooth axis. Since v2.5 (commit `1b866db0`) the dataset marks each older version with `superseded_by`, the newer line's file, and `get` takes a line without it first, so a later polish needs no change here.

`centerline list` shows every line kit can find for a scroll, person-made first, then bucket files, then model output, with a polished finder line before its original. `centerline get` picks the first (or `--source NAME`), downloads it, checks its sha256 against the dataset's index when there is one, adds the volume's grid size from `metadata.json` when the file has none of the three fields, and writes it.

A model-made line is model output: `get` says so, and it should be checked on CT slices before it is relied on.

## When to use it

- Setting up a VC3D project or a spiral-fitting dataset for a scroll.
- To get a line on a scroll the dataset does not cover (PHerc0139, for example): the bucket file is listed too.

Do not use it:

- To make a new center line: that is the Center Finder ([umbilicus](umbilicus.md)).
- To grade a line or its ends: the dataset's card and the [Umbilici Space](https://huggingface.co/spaces/SharpMeow/umbilici) show the grades.
- For a line on another volume than your project's: the points are level-0 voxels of the volume the line names. Check `volume` in the output.

## Quick start

```bash
python -m kit centerline list PHerc0175A
python -m kit centerline get PHerc0175A --into ~/scrolls/PHerc0175A.volpkg
```

On 23 Oct 2026 into a scratch folder, `get` printed:

```
wrote FOLDER/umbilicus.json: finder line (model), 146 points, z 1760 to 11040, level-0 voxels of volume 20250521115057
  sha256 checked against the index
  usable ends: {'low': True, 'high': True}
  model output: check it on CT slices before relying on it
  credit: Chase Hendrick, Scrolls Center Finder (umbilicus-lines-v1), CC BY-NC 4.0
```

and the same command again exited 2 with `already has umbilicus.json; use --force to replace it`. `list PHerc0139` gave one line, the bucket's `PHerc0139/representations/umbilicus/20260102150214-umbilicus-20260826112529.json`. It worked when the exit code is 0 and the volume it names is your project's volume.

## Checks and controls

- **Integrity.** A file whose sha256 differs from the dataset's index is refused and nothing is written (tested by serving a changed byte).
- **No silent overwrite.** An existing `umbilicus.json` is replaced only with `--force`; a folder holding `estimated_umbilicus.json` is always refused, because VC3D would then refuse the project (both tested).
- **No guessed fields.** The grid size is added only when all three fields are missing and `metadata.json` gives the volume's shape; a file with one or two of them is left as its author wrote it. `--no-stamp` writes the published bytes exactly (tested byte for byte).
- **A file VC3D would refuse is refused.** A line with no `control_points` is not written.

Claim label: Sourced fact for what was downloaded and checked; the line's position is whatever its source says (a model line is Model output).

## Commands and options

### `python -m kit centerline list`

```
usage: python -m kit centerline list [-h] [--json] scroll
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | required | scroll id, for example PHerc0175A |
| `--json` | off | print the lines as JSON |

### `python -m kit centerline get`

```
usage: python -m kit centerline get [-h] [--into FOLDER] [--out OUT]
                                    [--source SOURCE] [--no-stamp] [--force]
                                    [--json]
                                    scroll
```

| Option | Default | Meaning |
| --- | --- | --- |
| `scroll` | required | scroll id, for example PHerc0175A |
| `--into FOLDER` | none | write FOLDER/umbilicus.json (your VC3D project or fit dataset) |
| `--out OUT` | none | write here instead (default: SCROLL_umbilicus.json) |
| `--source SOURCE` | none | pick a source by name (see list); default: person-made, then bucket, then model |
| `--no-stamp` | off | leave the file exactly as published |
| `--force` | off | replace an existing umbilicus.json |
| `--json` | off | print the report as JSON |

`python -m kit.centerline list|get ...` takes the same.

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `lines(scroll, get=find.http_get)` | [{"source", "kind", "volume", "points", "url", "sha256", "credit", "licence", "from", ...}] best first | `VerifyError` for a bad id | `kind` is `person`, `bucket` or `model` (`KIND_ORDER`) |
| `order(found)` | the lines best first | Nothing | `KIND_ORDER`, then a line with no `superseded_by` before one with it (the dataset's newest version first, since v2.5), then `SOURCE_ORDER` (a polished finder line before its original), then source name |
| `pick(found, source=None)` | one line | `VerifyError` | none found, or no such source |
| `stamp(data, scroll, volume, get=find.http_get)` | bool: stamped | Nothing | Adds `volume_slices`, `volume_height`, `volume_width` from `metadata.json`'s shape (z, y, x) |
| `get_line(scroll, folder=None, out=None, source=None, force=False, get=find.http_get, do_stamp=True)` | report dict (Outputs) | `VerifyError`, `OSError` | |
| `format_list(scroll, found)`, `format_get(r)` | the printed text | Nothing | |
| `build_parser(p)` | the parser with `list` and `get` | Nothing | |
| `cmd_centerline(args)` | exit code | Nothing | |
| `main(argv=None)` | exit code | Nothing | `python -m kit.centerline` |

## Inputs

A scroll id as the bucket spells it, and for `--into` an existing folder: the one that holds your VC3D project's volume package (`*.volpkg.json`) or a spiral-fitting dataset.

## Outputs

The file: the published JSON (`control_points` of `x`, `y`, `z` in level-0 voxels, and `metadata`), plus the three grid fields when stamped.

`get --json`: `scroll`, `written`, `source`, `kind`, `volume`, `points`, `z` ([min, max]), `sha256_checked`, `stamped_grid`, `credit`, `licence`, `usable_ends`, `url`, `others` (the other sources).

| Exit code | Meaning |
| --- | --- |
| `0` | Listed, or written |
| `2` | Refused (see Failure modes) or a failed download |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit centerline: give --into or --out, not both` | Both given | Pick one |
| `kit centerline: no center line found in the center lines dataset or the bucket` | Nothing published for that scroll | Make one with the Center Finder ([umbilicus](umbilicus.md)) |
| `kit centerline: no line from source 'X'; there are: A, B` | `--source` names no listed line | Use a name from `list` |
| `kit centerline: URL: sha256 differs from the dataset's index.json; not written` | The download is not the file the index lists (a cut transfer, a proxy, or the file changed) | Run again; if it repeats, report it on the dataset |
| `kit centerline: URL is not JSON: ERROR` | The download is not JSON (an error page) | Run again later |
| `kit centerline: URL has no control_points; VC3D refuses such a file` | The file has no points | Pick another `--source` |
| `kit centerline: no folder F: give the folder that holds your *.volpkg.json, or a spiral fit dataset` | `--into` does not exist | Create it or fix the path |
| `kit centerline: F has estimated_umbilicus.json; move it away first (VC3D refuses a folder with both it and umbilicus.json)` | VC3D would refuse the project | Move or delete that file, then rerun |
| `kit centerline: F already has umbilicus.json; use --force to replace it` | A line is already there | Keep it, or pass `--force` |
| `kit centerline: OUT exists; use --force to replace it` | `--out` exists | Pass `--force` or another `--out` |
| `kit centerline: not a scroll id: ...` | A malformed id ([find](find.md)) | Use the bucket's spelling |
| `kit centerline could not download or write: ERROR` | No network, or the folder is not writable | Check both, then rerun |

## How it works

1. `lines` reads the dataset index rows for the scroll ([find](find.md)'s `centerlines`) and lists `SCROLL/representations/umbilicus/` in the bucket; a bucket file the index already lists is not repeated. The 14-digit prefix of a bucket file's name is its volume.
2. Lines are sorted person, bucket, model, then by source name.
3. `get_line` downloads the chosen file, checks sha256, parses it, requires `control_points`, stamps the grid when allowed, checks the destination, writes `NAME.part` and renames it.

## Cost and time

Under a second and a few kilobytes. Nothing to rent.

## For agents

- **Command:** `python -m kit centerline get SCROLL --into FOLDER --json`.
- **Parse:** `written`, `volume`, `kind`, `sha256_checked`.
- **Rerun:** Safe; a second run refuses rather than overwrites.
- **Success:** exit 0 and `volume` equal to the project's volume id.
- **Not a pass:** a `model` line not yet checked on CT; a line whose `volume` differs from the project's volume.
- **Go-ahead:** Nothing.
- **Never:** pass `--force` over someone's hand-made `umbilicus.json` without asking them.

## Tests

`python -m unittest tests.test_qol_tools.TestCenterline -v`: list order (person before bucket), a get that checks the sha256 and stamps the grid, refusal to overwrite without `--force`, refusal beside `estimated_umbilicus.json` even with `--force`, a changed byte refused with nothing written, and `--no-stamp` writing the exact bytes. They use a fake Hub and bucket; the runs above were by hand.

## History

- 2026-10-23: added `list` and `get` (`3376687`).

## Related

- [umbilicus](umbilicus.md): the Center Finder, and how VC3D reads the file.
- [find](find.md): everything else public for the scroll.
- [tifxyz](tifxyz.md): `facing` uses a center line.
