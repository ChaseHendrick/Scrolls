# Scroll dataset card standard, version 0.1

A short, checkable format for publishing a Vesuvius Challenge dataset on Hugging Face (or anywhere a folder can
hold files): what is in it, where it came from, under what license, what it cannot do, and which seeds and labels it
has used up. Anyone can follow it; `python -m kit.datacard check` says whether a dataset does.

Status: draft, 26 November 2026. Version 0.1 may change before 1.0; the version a dataset follows is written in its
`provenance.json`, so a later version never silently changes an earlier verdict.

## Why

Scroll datasets are reused far from where they were made. Four things go wrong again and again:

1. **A download cannot be checked.** Without per-file checksums nobody can tell a truncated or changed file from the
   release, or know two people trained on the same bytes.
2. **The license drifts.** The scans are [Vesuvius Challenge open data](https://scrollprize.org/data), CC BY-NC 4.0
   unless otherwise noted for specific assets, and the scrolls and fragments scanned at DLS before 2025 come from the
   EduceLab-Scrolls dataset under its own permission terms (Sourced fact, data page read 26 November 2026). A
   derived map, mesh or table cannot be looser than its sources, but derived data is easy to label CC BY or MIT by
   habit.
3. **Caveats get lost.** An ink map is model output, not a reading; synthetic CT is not real CT; a label set has its
   own errors. When a card leaves these out, the next user learns them the hard way.
4. **Test data gets reused as if it were fresh.** A seed that built a public synthetic set, or labels that scored a
   released result, are no longer held out for anyone. If the card does not say so, a later "held-out" test may not be.

The fourth is the one general guides miss. Datasheets for Datasets (Gebru et al., 2018,
[arXiv:1803.09010](https://arxiv.org/abs/1803.09010)) asks for motivation, composition, collection, uses and
maintenance, and Hugging Face's [dataset card guide](https://huggingface.co/docs/hub/datasets-cards) defines the YAML
metadata block the Hub reads (both Sourced fact, read 26 November 2026). This standard keeps both and adds the parts a
scroll dataset needs: checksums, a machine-readable provenance record and a spent list.

## The three files

At the top of the dataset:

| File | What | Rule |
| --- | --- | --- |
| `README.md` | The card: YAML front matter and the sections below | Required |
| `SHA256SUMS` | One `sha256sum` line per file | Required |
| `provenance.json` | Sources, licenses, code commit, caveats and the spent list, as JSON | Required |

### `SHA256SUMS`

- The format `sha256sum` writes: 64 lowercase hex digits, two spaces, the path relative to the dataset root
  (a leading `./` and the binary mark `*` are accepted). Sorted by path.
- Lists every file except `README.md`, `SHA256SUMS` itself and `.gitattributes`. The card is left out because it is
  edited more often than the data: listing it means the next card edit breaks `sha256sum -c`.
- Is regenerated with every data change (`python -m kit.datacard sums DIR --write`), including by jobs that rebuild a
  dataset on a schedule.
- The card shows users the check: `sha256sum -c SHA256SUMS` after download.

On the Hub, a file stored in LFS or Xet already carries its SHA-256 in the repository tree, so `kit.datacard` checks
those against `SHA256SUMS` without downloading them, and downloads small files (up to a budget) to hash them.

### `provenance.json`

```json
{
  "standard": "scroll-dataset-card/0.1",
  "dataset": "OWNER/NAME",
  "version": "1.0.0",
  "updated": "2026-11-26",
  "kind": ["real-derived", "geometry"],
  "license": "cc-by-nc-4.0",
  "sources": [
    {"name": "Vesuvius Challenge open data", "url": "https://scrollprize.org/data",
     "license": "cc-by-nc-4.0", "ref": "PHerc0814, volume 20250804134230"}
  ],
  "code": {"repo": "https://github.com/OWNER/REPO", "commit": "51a17e6", "command": "python -m TOOL ..."},
  "model_output": false,
  "caveats": ["One plain sentence per limit, the same ones the card lists."],
  "spent": {
    "seeds": [20261126001, "20261126201-20261126260"],
    "truth": [{"what": "ink labels", "scope": "PHerc0841 w00", "use": "testing", "note": "scored in this release"}],
    "held_back": [{"what": "evaluation regions", "scope": "release_mask.tif = 1", "note": "not in this release"}],
    "none_reason": ""
  }
}
```

| Field | Meaning | Rule |
| --- | --- | --- |
| `standard` | `scroll-dataset-card/0.1` | Required, exact |
| `dataset`, `version`, `updated` | Repository id, release version, date of this release (YYYY-MM-DD) | Required |
| `kind` | One or more of `real-derived`, `synthetic`, `model-output`, `labels`, `geometry`, `tabular`, `images`, `volumes` | Required |
| `license` | The dataset's license id, as in the card's front matter | Required, must match the card |
| `sources[]` | `name`, `license`, and a `url` or `ref` (scan id, commit, file digest) for each input | At least one |
| `code` | `repo` and the hex `commit` that built the release; `command` recommended | Required |
| `model_output` | True when any file is a model's prediction (ink maps, surface predictions) | Required when true |
| `caveats[]` | The limits, one sentence each | At least one |
| `spent.seeds[]` | Every random seed that built or tested this release: integers or `"A-B"` ranges | Required for `synthetic` |
| `spent.truth[]` | Labels or truth this release used: `what`, `scope`, `use` (`training`, `tuning`, `testing` or `released`), `note` | When any |
| `spent.held_back[]` | Truth deliberately left out of the release for later tests: `what`, `scope`, `note` | When any |
| `spent.none_reason` | Why nothing is spent (for example, a measurement table that used no labels or seeds) | When the three lists are empty |

## The card

### Front matter

The YAML block Hugging Face reads, with at least `license` (one id), `pretty_name` and the tag
`vesuvius-challenge` (recommended, so the community can find every scroll dataset with one filter). Keep `configs`
to one file type: the `datasets` library infers one builder per repository, and a Parquet or CSV config beside an
image config loads no rows (Interpretation, from what we saw uploading the reference datasets below, 26 November
2026).

### Sections

Any heading level; the names in brackets are accepted too.

| Section | What it says | Rule |
| --- | --- | --- |
| What is in it [Contents, Dataset structure] | Each part with counts and sizes; how to download and check it | Required |
| How it was made [Provenance] | Sources with versions, code with its commit, the steps | Required |
| Limits [Uses and limits, Caveats, Limitations, Notes] | One bullet per limit: what the data cannot show | Required, not empty |
| Spent seeds and truth [Spent list] | In words, every item of `provenance.json`'s `spent`; every spent seed written out | Required |
| License and credit [License] | The license, why it is no looser than its sources, and whom to credit | Required |
| Changelog | Dated entries; say when no data file changed | Required |
| Citation | A BibTeX entry | Recommended |

### Wording

- Model output is called model output. An ink map is never described as letters or text found or read; the checker
  fails a card that says so outside a negation.
- Synthetic data says so in its first paragraph.
- The data server's terms ([LICENSE.txt](https://dl.ash2txt.org/LICENSE.txt), read 26 November 2026) forbid making
  public, outside the official Vesuvius Challenge Discord, any revelation of hidden text without the consent of the
  Vesuvius Challenge and its Papyrology Team. A dataset is a publication: check those terms before releasing
  anything derived from a scroll.
- A spent list names only what is already public. Never list reserved or unreleased test sites, or anything about a
  prize-eligible scroll that is not yet public.

## Rules the checker applies

Every rule can fail: `tests/test_datacard.py` plants one fault per rule and requires the verdict to turn to FAIL.

| Rule | Fails when |
| --- | --- |
| `front-matter.license`, `front-matter.pretty_name` | Missing |
| `section.*` | A required section is missing or empty |
| `provenance.*` | `provenance.json` missing or not JSON; a required field missing; a bad `kind`; no hex `commit`; no caveat |
| `license.match` | Card and `provenance.json` disagree |
| `license.vesuvius` | A source on a Vesuvius Challenge host (scrollprize.org, dl.ash2txt.org) is declared neither noncommercial nor `other` (for assets under their own terms) |
| `license.inherit` | A source is noncommercial or share-alike and the dataset's license drops it, or a source is no-derivatives |
| `model-output.label` | The data is model output and the card never says "model output" |
| `model-output.reading` | The card says letters or text were found or read |
| `spent.present` | No spent list, or an empty one with no `none_reason` |
| `spent.seeds` | Synthetic data with no seeds, or a seed that is not an integer or range |
| `spent.seeds-in-card` | A spent seed is in `provenance.json` but not written in the card |
| `spent.truth`, `spent.held_back` | An item without `what` and `scope`, or a `use` outside the four values |
| `sums.present`, `sums.format`, `sums.unique`, `sums.paths`, `sums.self` | No file, a bad line, a repeated, absolute or `..` path, or the file lists itself |
| `sums.coverage`, `sums.missing` | A file is not listed, or a listed file is absent |
| `sums.match` | A file's SHA-256 differs from its line |

Warnings (the verdict stays PASS): no `vesuvius-challenge` tag, no Citation, limits not written as bullets, no
`sha256sum -c` in the card, `README.md` listed in `SHA256SUMS`, and small Hub files left unhashed past the download
budget.

```bash
python -m kit.datacard check ./my-dataset              # a folder before upload: hashes every file
python -m kit.datacard check OWNER/NAME --json         # a public Hugging Face dataset, read only
python -m kit.datacard sums ./my-dataset --write       # write SHA256SUMS
python -m kit.datacard template ./my-dataset --synthetic   # skeleton README.md and provenance.json
```

Exit 0 when no rule fails, 1 when one does, 2 when the dataset cannot be read. Tool page:
[`../tools/datacard.md`](../tools/datacard.md).

## Reference datasets

Four public datasets under `SharpMeow` were the models for this draft. Each already does part of it; none had a
`provenance.json` yet, because the standard did not exist. Checked read-only on 26 November 2026 with
`python -m kit.datacard check SharpMeow/NAME --max-download-mb 5`:

| Dataset | SHA256SUMS | Hashes | Spent list | Changelog | Fails | What it already does well |
| --- | --- | --- | --- | --- | ---: | --- |
| [scrollsim-tiles](https://huggingface.co/datasets/SharpMeow/scrollsim-tiles) | Yes, lists the card too | 1,570 of 1,570 match | Seeds in "How it was made", no section | No | 3 | Every seed written out; synthetic caveat first; `sha256sum -c` shown |
| [first-letters-ink-atlas](https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas) | No (per-render SHA-256 in each `meta.json`) | Not checked | No section | Yes | 3 | Model output labeled; "Uses and limits"; license inherited from scans and meshes |
| [vesuvius-segment-atlas](https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas) | No (rebuilt daily) | Not checked | No section (uses no labels or seeds) | Yes | 3 | Every step of the build named, with the code path |
| [vesuvius-snapped-labels](https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels) | Yes, lists the card too | 1,027 of 1,027 match | Held-back regions in "How it was made", no section | Yes | 2 | Source mesh digest in each `release.json`; held-back evaluation regions; dated changelog |

Every card failed `provenance.present` (no `provenance.json`) and `section.spent`; scrollsim-tiles also lacks a
Changelog, and the two atlases lack `SHA256SUMS`. The two `SHA256SUMS` files matched every file they list, checked
against the Hub's LFS digests and by download (scrollsim-tiles in 22 s with `--max-download-mb 200`).

Bringing the four cards up to the standard is a separate change to public datasets and waits for the owner's yes.

## Changelog

- **2026-11-26**: version 0.1 drafted, with the checker `kit.datacard`.
