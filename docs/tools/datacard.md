# datacard: check a scroll dataset's card, checksums, provenance and spent list

Checks a Hugging Face dataset, or a folder about to become one, against the scroll dataset card standard: per-file SHA-256 sums, a provenance record with sources, licenses and code commit, caveats, and a list of the seeds and truth the release has used up.

| Field | Value |
| --- | --- |
| Id | `datacard` |
| Status | Experimental |
| Kind | kit module |
| Area | Records and provenance |
| Run | `python -m kit.datacard check DIR_OR_OWNER/NAME [--revision R] [--max-download-mb N] [--json]`; `python -m kit.datacard sums DIR [--write]`; `python -m kit.datacard template OUT [--synthetic]`; `from kit import datacard` |
| Code | `kit/datacard.py`, `tests/test_datacard.py` |
| Tests | `tests/test_datacard.py` |
| Needs | Python 3.10 or newer, standard library only |
| Runs on | Any CPU. A Hub check of SharpMeow/scrollsim-tiles (1,570 listed files, 1.8 GB) took 22 s with `--max-download-mb 200`, cloud container, 26 November 2026; a local check reads every listed file once |
| Network | For `OWNER/NAME` only: huggingface.co (the repository tree API and file downloads, no token). None for a folder |
| Writes | `check`: nothing. `sums --write`: `DIR/SHA256SUMS`. `template`: `OUT/README.md` and `OUT/provenance.json`, never over an existing file |
| Go-ahead | Not needed to check. Uploading a card or dataset that it passes still needs the owner's yes for each upload |
| Released | Public `main` from the PR that adds this page (2026-11-26) |
| Checked | 2026-11-26 against commit `95d731b` |

## What it does

A scroll dataset is reused far from where it was made, so its card has to answer four questions: can I check my
download, where did each file come from and under what license, what can it not show, and which seeds and labels has
it already used up, so that a later test on them is not called held out. The
[scroll dataset card standard](../standards/dataset-card.md) asks for three files to answer them: `README.md` (the
card, with fixed sections), `SHA256SUMS` and `provenance.json`.

`check` reads those files and applies every rule of the standard: front matter, required sections, the provenance
record, license inheritance from the sources (a noncommercial or share-alike source cannot be dropped, and Vesuvius
Challenge open data must be declared noncommercial), the model-output wording, the spent list, and every line of
`SHA256SUMS` against the files. On the Hub, files in LFS or Xet are checked against the SHA-256 the Hub already
stores, so large files are not downloaded; small files are downloaded up to a budget and hashed.

`sums` writes `SHA256SUMS` the way the standard wants it (sorted, relative paths, the card left out). `template`
writes a skeleton card and provenance record that pass the structural rules once filled in.

It checks form and consistency, not truth: a card can pass and still describe the data wrongly, and a passing card
does not make an ink map anything other than model output.

## When to use it

- Before uploading a new dataset or a new version: `check` on the local folder.
- After an upload: `check OWNER/NAME` to confirm the Hub copy matches its sums.
- Before using a dataset as test data: read its spent list, here or on the card.
- When starting a card: `template`.

Do not use it:

- To score or judge the data itself: use the tool that measures it (`kit auc`, `kit atlas`, `kit.simcritic`).
- On a private dataset: `check` reads without a token and sees public datasets only; check the local folder instead.

## Quick start

```bash
python -m kit.datacard template ./NEWSET --synthetic
python -m kit.datacard sums ./NEWSET --write
python -m kit.datacard check ./NEWSET
python -m kit.datacard check SharpMeow/scrollsim-tiles --max-download-mb 200
```

`NEWSET` is the folder that will become the dataset. On 26 November 2026 the last command printed:

```
hf://datasets/SharpMeow/scrollsim-tiles@main: FAIL against scroll-dataset-card/0.1 (3 failing, 2 warnings)
  FAIL  section.spent: no section headed 'Spent seeds and truth' (or spent list, spent truth)
  FAIL  section.changelog: no section headed 'Changelog' (or changes, versions)
  FAIL  provenance.present: no provenance.json
  WARN  section.citation: no citation section
  WARN  sums.card: SHA256SUMS lists README.md: the next card edit breaks `sha256sum -c`; leave it out
  ...
  files 1572, listed in SHA256SUMS 1570, hashes checked 1570, not checked 0
```

That dataset predates the standard; every one of its 1,570 hashes matched. Exit 0 means no rule failed.

## Checks and controls

Each rule can fail. `tests/test_datacard.py` writes the template into a folder, checks that it passes, then plants
one fault per rule (a changed byte, an unlisted file, a listed file removed, a bad sums line, a license that drops a
noncommercial source, a Vesuvius source declared CC0, a missing commit, no caveats, synthetic data with no seeds, a
seed missing from the card, a bad truth `use`, a missing or empty section, model output not labeled, a sentence
saying letters were read) and requires each to turn the verdict to FAIL through its own rule. The Hub path is tested
with a fake server: an LFS digest that differs fails, and a zero download budget leaves small files unverified with a
warning rather than a pass. The negation guard is tested on the ink atlas's own sentence "Nothing here says that
letters were found or read", which must not trip the reading rule.

The four reference datasets were checked read-only on 26 November 2026; the results are in the standard's
[reference table](../standards/dataset-card.md#reference-datasets).

Cross-scroll validation: not applicable (a format and consistency check; it makes no scientific claim about any
scroll).

Claim label: Sourced fact for the reference results (the command's own output, 26 November 2026).

## Commands and options

### `python -m kit.datacard check`

| Option | Default | Meaning |
| --- | --- | --- |
| `target` | required | A local dataset folder, or `OWNER/NAME` of a public Hugging Face dataset |
| `--revision R` | `main` | Branch, tag or commit of a Hub dataset |
| `--max-download-mb N` | `20` | Download budget in MB for hashing small non-LFS Hub files |
| `--json` | off | One JSON record instead of lines |

### `python -m kit.datacard sums`

| Option | Default | Meaning |
| --- | --- | --- |
| `folder` | required | The folder to list |
| `--write` | off | Write `FOLDER/SHA256SUMS` instead of printing |

### `python -m kit.datacard template`

| Option | Default | Meaning |
| --- | --- | --- |
| `out` | required | Folder for the skeleton `README.md` and `provenance.json` (created if needed) |
| `--synthetic` | off | A synthetic dataset: spent seeds instead of scans |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `InputError()` | | | The dataset or folder cannot be read. |
| `front_matter(text)` | `(dict, str)` | | Top-level YAML keys of a card (scalars, lists; nested blocks become True) and the body |
| `headings(body)` | `dict` | | Heading (lowercase) to the text under it, subsections included; code blocks skipped |
| `find_section(heads, aliases)` | `(heading, text)` or `(None, None)` | | First heading matching an alias exactly or as a prefix |
| `parse_sums(text)` | `([(sha256, path)], [bad line numbers])` | | Accepts `./` and the binary mark |
| `sha256_file(path, chunk=1 << 20)` | hex string | `OSError` | Streams the file |
| `seed_items(seeds)` | `[(lo, hi)]` | `ValueError` | Integers and `A-B`, `A..B` ranges |
| `reading_claims(text)` | `[sentence]` | | Sentences saying letters or text were found or read, with no negation |
| `Folder(root)` | source | `InputError` | A local dataset folder |
| `HubDataset(repo, revision='main', opener=None)` | source | `InputError` | A public Hub dataset; `opener` replaces `urllib.request.urlopen` in tests |
| `source_for(target, revision='main', opener=None)` | `Folder` or `HubDataset` | `InputError` | A folder when the path exists, else `OWNER/NAME` |
| `check(src, max_download_mb=20.0, workers=8)` | record (see Outputs) | `InputError` | Every rule; `workers` threads hash and download |
| `make_sums(root)` | text | `InputError` | `SHA256SUMS` for a folder |
| `template(synthetic=False)` | `(README text, provenance dict)` | | Skeletons |
| `main(argv=None)` | exit code | | The command line |

## Inputs

A folder or a public Hugging Face dataset id (`OWNER/NAME`, optional `--revision` branch, tag or commit). The files
read are `README.md`, `SHA256SUMS`, `provenance.json` and, to hash them, every file `SHA256SUMS` lists. The formats
are in the [standard](../standards/dataset-card.md#the-three-files).

## Outputs

Lines on stdout (verdict, then FAIL, WARN and PASS findings, then counts), or with `--json` one record:

| Field | Type | Meaning |
| --- | --- | --- |
| `dataset` | string | The folder, or `hf://datasets/OWNER/NAME@REVISION` |
| `standard` | string | `scroll-dataset-card/0.1` |
| `verdict` | string | `PASS` when no rule failed, else `FAIL` |
| `fails`, `warnings` | int | Counts of failing and warning findings |
| `counts.files` | int | Files in the dataset |
| `counts.listed` | int | Lines in `SHA256SUMS` |
| `counts.verified` | int | Listed files whose SHA-256 was checked (they may match or not; see `sums.match`) |
| `counts.unverified` | int | Listed files not hashed (past the download budget) |
| `findings[]` | list | `{rule, level, message}`, level `pass`, `warn` or `fail` |

| Exit code | Meaning |
| --- | --- |
| `0` | No rule failed (warnings allowed); for `sums` and `template`, done |
| `1` | At least one rule failed |
| `2` | The dataset or folder cannot be read, or `template` would overwrite a file |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `...: give the dataset folder, not a file` | A file path was given | Give the folder holding `README.md` |
| `datacard: ...` | The input could not be read; the rest of the line says why | Fix the path, id or network |
| `seed...is not an integer` | A spent seed is `true` or `false` | Write the seed as an integer |
| `...: not a folder` | `Folder` got a path that is not a directory | Give the dataset folder |
| `...: not OWNER/NAME` | Neither an existing folder nor a Hub id | Check the spelling, or give a folder that exists |
| `seed range...runs backward` | `"B-A"` with B above A | Write the range low to high |
| `seed...is neither an integer nor a range A-B` | A seed string like `"abc"` | Use integers or `A-B` |
| `not an object` | `provenance.json` parses but is a list or a value | Make it one JSON object |
| `...: dataset or revision not found` | No such public dataset or revision | Check the id; a private dataset needs a local check |
| `sums.unverified` warning | Small files past `--max-download-mb` | Raise the budget, or check a local copy |

## How it works

1. Read `README.md`: front matter by a small YAML reader for top-level keys, then headings outside code blocks.
2. Each required section must exist (any heading level, with the accepted aliases) and hold text.
3. Read `provenance.json` and check its fields, then the license rules: the card and record agree; a source on a
   Vesuvius Challenge host (`scrollprize.org`, `dl.ash2txt.org`) is declared noncommercial or `other`; a
   noncommercial or share-alike source keeps that term in the dataset's license; a no-derivatives source fails.
4. If the record or kind says model output, the card must say "model output"; no card may say letters or text were
   found or read outside a sentence with a negation.
5. The spent list must be present, with seeds for synthetic data, every seed written in the card (digits compared
   with thousands separators removed), and each truth item with `what`, `scope` and a `use` from `training`,
   `tuning`, `testing`, `released`.
6. `SHA256SUMS`: format, unique and safe paths, coverage of every file but `README.md`, `SHA256SUMS` and
   `.gitattributes`, then each listed file's SHA-256 (local files hashed; Hub LFS files from the tree's `lfs.oid`;
   other Hub files downloaded within the budget, 8 threads).

## Cost and time

Free. 22 s for the 1,570 files of SharpMeow/scrollsim-tiles over the Hub (26 November 2026, cloud container); a
local check is bound by disk speed, one read per file. The 31 tests run in under 0.1 s.

## For agents

- **Command:** `python -m kit.datacard check DIR --json` before any dataset upload; `python -m kit.datacard check OWNER/NAME --json` after it.
- **Parse:** `verdict`, `fails`, and the `findings` with level `fail`; `counts.unverified` above 0 means some hashes were not checked.
- **Rerun:** safe; `check` writes nothing.
- **Success:** exit 0 and `verdict` `PASS`, with `counts.unverified` 0 for a release check.
- **Not a pass:** a PASS with unverified files; a PASS on a card whose facts were not checked against the data (the tool checks form, not truth).
- **Go-ahead:** uploading or changing a public card needs the owner's yes for each upload.
- **Never:** list reserved or unreleased test sites, or anything private, in a public spent list; never describe an ink map as a reading to satisfy a section.

## Tests

`python -m unittest tests.test_datacard -v`: the template passes; one planted fault per rule fails it; parsing of
front matter, sums lines, seed ranges and headings; the Hub source with a fake server. Not covered: live Hub calls
(the reference table was produced by hand on 26 November 2026).

## History

- 2026-11-26: first version with standard 0.1 (`3865a21`).

## Related

- [Scroll dataset card standard](../standards/dataset-card.md): the rules this tool applies.
- [atlas](atlas.md), [ink-atlas](ink-atlas.md), [snapped-labels](snapped-labels.md), [hardcases](hardcases.md): the tools behind the reference datasets.
- [provenance](provenance.md): digests of single runs.
