# readerseen: which public surfaces Reader V3 trained on, and whether a site is fresh for it

Resolves Reader V3's published training list (99 keys) to 91 public segments on 8 scrolls, adds the units its author scored before release, and checks any scroll and segment: TRAINED, SELECTED, SAME-SCROLL, SAME-ROLL or FRESH-BY-LIST.

| Field | Value |
| --- | --- |
| Id | `readerseen` |
| Status | Current |
| Kind | kit module,data |
| Area | Scoring and controls |
| Run | `python -m kit.readerseen check --reader READER --scroll SCROLL [--segment NAME ...] [--json]`, `python -m kit.readerseen list`, `python -m kit.readerseen readers`, `python -m kit.readerseen verify`, `python -m kit.readerseen build` |
| Code | `kit/readerseen.py` |
| Tests | `tests/test_readerseen.py` |
| Needs | Python 3.10 or newer, standard library only. The three pinned source copies in `docs/evidence/readerseen/` for `build` and `verify` |
| Runs on | Any CPU; under 0.1 s for a check (measured 2026-11-27, 4-core cloud container, including Python start-up) |
| Network | None. The source files were fetched once on 2026-11-27 and are pinned by sha256 |
| Writes | `check`, `list`, `readers`, `verify`: nothing (prints only). `build`: `kit/data/readerseen.json` (or `--out`), replacing it |
| Go-ahead | Not needed |
| Released | Not yet (pending public merge) |
| License | Code: Apache 2.0 (this repository's). The pinned copies keep their own terms: Reader V3's and Reader v2's `train_config.json` come from their authors' repositories (Reader V3 is MIT); the ink_9um README is the organizers' (`scrollprize/datasets` bucket) |
| Checked | 2026-11-27 |

## What it does

A score is only held out for a reader if the reader never saw that surface. Reader V3 is the ink model most First Letters submissions use, and its published training list names surfaces three ways: public segment ids, bare 14-digit stamps, and the ink_9um annotation names, which "do not track the public segment w-numbering" (the organizers' `pherc0139-w029` is public w045). A check by eye misses these.

`readerseen` builds one registry, `kit/data/readerseen.json`, from three published files pinned by sha256: Reader V3's `train_config.json` (github.com/DomRusso2/reader-v3 at `4a9f1c63`), Reader v2's (huggingface.co/domenicor046/reader-v2 at `72633d8`, the same 99 keys) and the ink_9um label dataset README, whose source-volume table maps every aligned and native9 annotation name to its public segment. Every key becomes a row with its public id, the names it was trained under, the dataset blocks, the label kind (human or pseudo) and the readers that inherited it (ink_9um, Reader v2, Reader V3, and the fine-tunes Argus V2 and Reader-PU). It adds selection rows: units Reader V3's author scored before release (the `results/` suite of the Reader V3 repository: PHerc0841 w00 and two auto-grown segments, PHerc0009B ag487, PHerc1447 w058 and w060, PHerc0139 w047 and w053).

`check` takes a reader, a scroll and segment names, and gives a verdict by a fixed rule (below). Names are matched by training name, by winding window however padded or tagged, and by short ids, so `w45`, `w045`, `20260126000000-w045_2026012619` and the organizers' `pherc0139-w029` all meet public w045.

It reads no label, CT layer, preview, mesh or map. FRESH-BY-LIST means fresh by the published list only, not geometrically certified: two traces with different names can be one sheet, so a SAME-SCROLL site needs a geometric check against the training meshes before anyone calls it held out. The registry is Sourced fact for the files and Community report that they are what was trained.

## When to use it

- Before using a segment as a test for Reader V3, Reader v2 or a fine-tune of them: run `check` on it, and copy the verdict and registry digest into the write-up.
- When a new labeled set arrives: run `check` on its segments before reading any of it.
- To list what Reader V3 trained on for a scroll: `list --scroll`.

Do not use it:
- for other readers (ink_9um alone, v8in, d9v2, Hecate, Rectina): it refuses them; check their own lists ([exposure log](../logs/2026-10-16-reader-exposure.md));
- to show a SAME-SCROLL surface is held out: that needs a geometric check against the training meshes;
- to say anything about a fine-tune's own extra data (Argus V2, Reader-PU): a site Reader V3 never saw is DERIVED-UNKNOWN for them.

## Quick start

```bash
python -m kit.readerseen check --reader reader-v3 --scroll PHerc0139 --segment w045
```

Printed on 2026-11-27:

```
TRAINED  reader-v3 on PHerc0139
  TRAINED          w045 [training name, winding window or short id]  20260126000000-w045_2026012619 (human/pseudo, datasets 1,8)
  training surfaces on this scroll: 26; exit 5
```

It worked when the first line holds a verdict and the exit code matches it (5 here).

## Checks and controls

`verify` rebuilds the registry from the pinned copies and fails (exit 1) when the committed file differs; `build` refuses any source file whose sha256 is not the pinned one. The tests check known cases both ways: w045, `w45`, its full id and the organizers' `pherc0139-w029` must be TRAINED on public w045 and on nothing else; public w029 must resolve to `20250108000004-w029_2025010827`, not w045; ag487 must be SELECTED, not TRAINED; PHerc1545 must be FRESH-BY-LIST for Reader V3 and DERIVED-UNKNOWN for Argus V2; an organizer annotation name must never meet a public window by its number. Counts are fixed in the tests: 99 keys, 91 public segments, PHerc0139 26 surfaces in 34 representations.

Cross-scroll validation: not applicable (a metadata lookup, no scientific claim; it covers all eight training scrolls and any queried scroll by the same rule).

Claim label: Sourced fact for the training files and the README table; Community report that they are what was trained and for the author's suite; Interpretation for the pseudo folder's naming and the same-roll pieces.

## Verdicts

| Verdict | Meaning | Exit |
| --- | --- | --- |
| TRAINED | a named segment is a training surface (human or pseudo labels) by name, window or short id | 5 |
| TRAINED-POSSIBLE | it meets only the other reading of an ambiguous pseudo-label name (public w017, w028, w029 of PHerc0139) | 5 |
| SELECTED | not trained, but Reader V3's author scored it before release; a whole-scroll query on a scroll that holds such units | 4 |
| SAME-SCROLL | the scroll has training surfaces or selected units and no name meets them | 3 |
| SAME-ROLL | another piece of the same roll was trained on (PHerc0343 against PHerc0343P) | 3 |
| DERIVED-UNKNOWN | a fine-tune of Reader V3 on a site Reader V3 never saw: its own data decides | 3 |
| FRESH-BY-LIST | no training surface, selection row or roll piece on that scroll | 0 |

A whole-scroll query (no segment) on a training scroll is TRAINED. With several segments the overall verdict is the worst of them.

## Commands and options

### `python -m kit.readerseen check`

| Option | Default | Meaning |
| --- | --- | --- |
| `--reader READER` | required | reader-v3, reader-v2, argus-v2, reader-pu (aliases: `python -m kit.readerseen readers`) |
| `--scroll SCROLL` | required | scroll id, e.g. PHerc0139 (0139, PHerc139 and Paris4 also work) |
| `--segment SEGMENT` | none | segment name (repeat for several) |
| `--json` | off | print the verdict record as JSON |

### `python -m kit.readerseen list`

| Option | Default | Meaning |
| --- | --- | --- |
| `--reader READER` | `reader-v3` | which reader's selection rows to show (training rows are the same for all) |
| `--scroll SCROLL` | none | only this scroll |
| `--json` | off | the rows as JSON |

### `python -m kit.readerseen readers`

Prints each reader the registry covers, its aliases and a note on its weights and data. No options.

### `python -m kit.readerseen verify`

Rebuilds the registry from the pinned copies and compares. No options.

### `python -m kit.readerseen build`

| Option | Default | Meaning |
| --- | --- | --- |
| `--config CONFIG` | `docs/evidence/readerseen/reader-v3-train_config.json` | Reader V3's list; must match the pinned sha256 |
| `--rv2-config RV2_CONFIG` | `docs/evidence/readerseen/reader-v2-train_config.json` | Reader v2's list (lineage and key comparison) |
| `--ink9um-readme INK9UM_README` | `docs/evidence/readerseen/ink_9um-README.md` | the annotation name to public segment table |
| `--out OUT` | `kit/data/readerseen.json` | where to write the registry |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `check(reader, scroll, segments=(), reg=None)` | dict: `verdict`, `exit`, `held_out_by_list`, `segments`, `why`, `registry_digest` | `SeenError` on an unknown reader or an empty scroll | the verdict rule above |
| `name_meets(query, public, names=())` | bool | none | the name matcher |
| `build(cfg, rv2, readme)` | the registry dict | `SeenError` on a file that is not the pinned one | metadata only |
| `load(path=None)` | the registry dict | `SeenError` when the digest is out of step | |
| `scroll_key(s)`, `roll_of(s)` | str | none | scroll and roll keys |

## Inputs

Reader name, scroll name and segment names. `build` reads only the three pinned copies.

## Outputs

Text or JSON on stdout. Exit codes:

| Exit code | Meaning |
| --- | --- |
| 0 | FRESH-BY-LIST, or `verify` and `build` passed |
| 1 | `verify`: the registry differs from a rebuild |
| 2 | bad input: unknown reader, empty scroll, registry out of step |
| 3 | SAME-SCROLL, SAME-ROLL or DERIVED-UNKNOWN |
| 4 | SELECTED |
| 5 | TRAINED or TRAINED-POSSIBLE |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `no registry for reader` | the reader is not Reader V3 or one derived from its list | check that reader against its own published list |
| `sha256 ... is not the pinned` | a source file changed | review the new file, then pin it in `SOURCES` in a reviewed change |
| `digest out of step` | `kit/data/readerseen.json` was edited by hand | `python -m kit.readerseen build` |
| SAME-SCROLL on a surface you believe is new | names cannot show two traces are different sheets | check the geometry against the training meshes |

## How it works

`build` reads Reader V3's 13 dataset blocks, resolves each key to a public segment (the key itself, a 14-digit stamp, or the ink_9um README's table for the aligned and native9 annotation names), groups the 99 keys into 91 public segments, marks label kind and which readers inherited each surface, and records the three pseudo-label names whose other reading is kept as a possible row. `check` compares the queried names with each training row of that scroll, then with possible rows, then with selection rows, then applies the scroll and roll rules.

## Cost and time

Free; under 0.1 s on any CPU.

## For agents

- **Command:** `python -m kit.readerseen check --reader reader-v3 --scroll SCROLL --segment NAME --json`
- **Parse:** `verdict`, `exit`, `held_out_by_list`, `registry_digest`
- **Rerun:** safe; it writes nothing
- **Success:** exit 0 means FRESH-BY-LIST only; any other exit means the site is not fresh by list
- **Not a pass:** FRESH-BY-LIST as proof of held out; it is a list check
- **Go-ahead:** not needed
- **Never:** call a SAME-SCROLL site held out without a geometric check

## Tests

`python -m unittest tests.test_readerseen` (standard library, under a second).

## History

- 2026-11-27: first public version: Reader V3's training list, Reader v2's lineage, the ink_9um name table and the author's suite.

## Related

- [Reader exposure log](../logs/2026-10-16-reader-exposure.md): which readers saw PHerc0841, PHerc0139 w045 and others, from public sources.
