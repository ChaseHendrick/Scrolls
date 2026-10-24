# gate: rank released ink readers on PHerc0841 by the Gate A rule

`python -m kit gate` ranks ink readers by mean forward AUC on PHerc0841's three standard crops, from the committed CPU scores and any Mac results, requires each crop to beat its reverse-depth control, and says whether the leader wins by Gate A's 0.02 rule.

| Field | Value |
| --- | --- |
| Id | `gate` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Scoring and controls |
| Run | `python -m kit gate`, `from kit import gate` |
| Code | `kit/gate.py`, `kit/cli.py` (`cmd_gate`) |
| Tests | `tests/test_gate.py` |
| Needs | Python 3.10 or newer, standard library only. A clone of the repository, because it reads `docs/results.json` (an installed `scrolls-workbench` package does not have it). For Mac rows, the `auc_*.json` files that `scripts/mac-w045.sh` writes |
| Runs on | Any CPU, about 0.1 s (measured 2026-10-16, 4-core 2.1 GHz Xeon cloud container, committed scores only) |
| Network | None |
| Writes | Nothing (prints only). `scripts/mac-phase0.sh` saves what it prints to `WORK/phase0-gate.txt` |
| Go-ahead | Not needed |
| Released | Public `main` since 2026-10-07 (`bec6fb9`). The AutoPipeline release package carries the module (same code, older docstring) but no `gate` command |
| Guide | [STANDARDS.md](../STANDARDS.md) (the Gate A row and its known gap), [mac.md](../mac.md) (the Phase 0 queue that ends with this table) |
| Checked | 2026-10-17 against commit `a6beee7` |

## What it does

Several released ink readers (ink models) can be run on the same surface. Gate A is this repository's fixed rule for saying which of them is best before choosing one for further work. The rule belongs to Phase 0 of the project roadmap, which is now kept privately; the public statement of the rule is the docstring of `kit/gate.py`, and the [glossary](../../GLOSSARY.md) entry "Gate A" repeats it.

The rule: score each reader on three 640 px crops of PHerc0841 (one each on segments w00, ag896 and ag405, the windows of densest labeled ink, with a 64 px edge left out), with [`auc`](auc.md) against the organizers' labels of 2026-09-18. Rank readers by their mean forward AUC over the three crops. A reader counts only if its forward AUC is at least 0.10 above its reverse-depth AUC on every crop (the reverse-depth map is the same model run with the volume's layers in the opposite order; see [auc](auc.md)). One reader beats another only by a lead of at least 0.02 in mean AUC.

`kit gate` applies that rule mechanically. It reads two sources of scores. The committed "bars" are the CPU scores in [`results.json`](../results.json) (rows of `results` with `window` "crop" and `inner_px` 64). The Mac results are the `kit auc --json` files that `scripts/mac-w045.sh` writes under `WORK/SEGMENT/results/` when run in QUICK mode (crop only) by `scripts/mac-phase0.sh`. A Mac file counts only if it was scored on the same crop with the same 64 px edge. As a device check, the Mac's `ink_9um` seed 42 score must equal the committed CPU bar to four decimals; a mismatch is printed as MISMATCH, blocks the verdict (no winner or lead) and makes the exit code 1.

It does not run any model, score any map, or test whether a lead is beyond sampling noise: it only reads AUCs that already exist. A Gate A winner is the reader with the best agreement with human ink labels on these crops. It is not a reader of letters, and its maps are model output, not readings.

## When to use it

- After `scripts/mac-phase0.sh` (or any new crop scores) to see the Gate A table and verdict.
- Before choosing which released reader to run on new data, to check which one the committed scores favor and by how much.
- As a device check: a Mac `ink_9um` seed 42 run that does not reproduce the CPU bar shows up here.

Do not use it:

- To score a map: use [`auc`](auc.md) (with `--control`, `--crop ... --inner 64` for these crops).
- To decide whether a small lead is real: use `kit auc MAP.tif --compare OTHER.tif --bootstrap 300` on each crop ([auc](auc.md)); the 0.02 lead sits inside the measured noise (Checks and controls).
- To rank readers on any other segment or scroll: the segments are fixed in `SEGMENTS`. For w045 or other labeled segments, run [`auc`](auc.md) and compare by hand.
- To rank Hecate on PHerc0841: PHerc0841 may be in Hecate's training data (`held_out` in `results.json`, [log](../logs/2026-10-09-pherc0841-hecate.md)), so its scores there are not a fair test.

## Quick start

```bash
# From a clone of the repository; committed CPU scores only (or also ~/scrolls-work if that folder exists)
python -m kit gate

# With Mac results from scripts/mac-phase0.sh, as JSON
python -m kit gate WORK --json
```

- `WORK`: the Mac work folder that holds `0841-w00/results/auc_*.json`, `0841-ag896/results/...` and `0841-ag405/results/...`; `scripts/mac-phase0.sh` uses `~/scrolls-work` unless `WORK` is set.

Run on 2026-10-16 in a clone with no `~/scrolls-work`, on the committed scores, it printed:

```
| Reader | w00 | ag896 | ag405 | Mean | Control |
| --- | ---: | ---: | ---: | ---: | --- |
| d9v2 | 0.8994 (0.586) | 0.8230 (0.532) | 0.8319 (0.657) | 0.8514 | ok |
| ink_9um seed42 | 0.8061 (0.536) | 0.6594 (0.558) | 0.7838 (0.642) | 0.7498 | ok |

Forward AUC (reverse in brackets), 640 px crops less a 64 px edge.
Not ranked yet (missing crops): Reader v2
Gate A: d9v2 leads ink_9um seed42 by 0.1016 mean AUC: a clear win (at least 0.02)
```

With a synthetic `WORK` folder (made-up Mac files: a reader `v8in` at 0.86, 0.80, 0.81, and an `ink_9um` seed 42 file that differs from the CPU bar on ag405), the extra lines were:

```
check 0841-w00: Mac ink_9um s42 0.8061 vs CPU 0.8061: match
check 0841-ag405: Mac ink_9um s42 0.7900 vs CPU 0.7838: MISMATCH (crop, labels or code differ; do not rank until explained)
skipped /tmp/.../0841-ag405/results/auc_v8in1447.json: not the standard crop with a 64 px edge (crop [0, 640, 0, 640], inner 64)
```

and the exit code was 1. It worked when the exit code is 0 and the last line starts with `Gate A:`. The verdict means something only when the controls are `ok`, no check says MISMATCH, and the lead is checked against noise (see Checks and controls).

## Checks and controls

- **Reverse-depth control on every crop** (`--min-gap`, default `MIN_GAP` 0.10). A reader whose forward AUC is less than 0.10 above its reverse AUC on any crop, or that has no reverse AUC, is listed with `too close (min gap ...)` and cannot win, even when its mean is highest (`tests/test_gate.py`, `test_weak_control_is_flagged`). On a synthetic reader with forward 0.95 and reverse 0.90 on all three crops it printed `too close (min gap 0.05)` and the verdict went to the next reader. The committed readers pass with little room: the smallest committed gap is 0.1015 (`ink_9um` seed 42 on ag896, 0.6594 against 0.5579, `results` in `results.json`).
- **Mac against CPU** (`consistency`). The Mac's `ink_9um` seed 42 forward AUC must be within 0.0001 of the committed CPU bar on every crop both have. A mismatch prints `MISMATCH`, sets `verdict.blocked` to true, clears `winner` and `lead`, sets `clear` to false and makes the exit code 1. The table remains visible for diagnosis; its order is not an accepted winner.
- **Sampling noise.** The gate applies no interval. A 1 mm block bootstrap on PHerc0841 gave 95 % interval half-widths of 0.008 (w00) to 0.038 (ag405) for the team's maps (README finding 8, [overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md)), so a lead near 0.02 is within noise; [STANDARDS.md](../STANDARDS.md) lists this as a known gap and asks for a paired comparison (`kit auc --compare --bootstrap 300`) beside the gate. The current committed lead, 0.1016, is well outside that range (Interpretation).
- **Crops are not independent.** w00 and ag896 are patches of one shared sheet, so a three-crop mean weights that sheet twice ([tricks tables](../../scripts/experiments/2026-10-07-cloud/tricks/tables.md)).
- **Held-out data.** PHerc0841 is outside the training data of `ink_9um`, v8in, v8in-1447, d9v2 and Reader v2 (`held_out` in `results.json`), which is why the gate uses it. Do not add Hecate to the table.

Claim label: Model output, for the AUCs it ranks (scored against the organizers' labels of 2026-09-18); the verdict "a clear win" is Interpretation under this repository's own rule, not a significance test.

## Commands and options

### `python -m kit gate`

```
usage: python -m kit gate [-h] [--results RESULTS] [--min-lead MIN_LEAD]
                          [--min-gap MIN_GAP] [--json]
                          [work]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `work` | none | The Mac work folder holding `SEGMENT/results/auc_*.json`. When left out, `~/scrolls-work` is used if it is a folder; otherwise only the committed scores are read. The JSON output does not record which folder was read, so give it explicitly when it matters |
| `--results RESULTS` | `docs/results.json`, in the clone the code runs from (`gate.RESULTS`, an absolute path) | The committed scores and crop windows. The command stops with exit code 2 when this file does not exist |
| `--min-lead MIN_LEAD` | `0.02` | Lead in mean forward AUC that counts as a win (`MIN_LEAD`). Changing it after seeing the scores is no longer Gate A |
| `--min-gap MIN_GAP` | `0.1` | Forward minus reverse AUC needed on every crop for a reader to be eligible (`MIN_GAP`) |
| `--json` | off | Print the result as JSON (fields under Outputs) instead of the Markdown table |

## Python API

```python
from kit import gate
result = gate.run("WORK")            # or gate.run(None) for the committed scores only
print(gate.format_result(result))
print(result["verdict"]["winner"], result["verdict"]["clear"])
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `committed(path=RESULTS)` | `(table, crops)`: `table` is `{reader: {segment: (auc_as_stored, auc_reversed or None, "results.json")}}`; `crops` is `{segment: [Y0, Y1, X0, X1]}` from `segments` | `OSError` for a missing file, `ValueError` for bad JSON, `KeyError` when `segments`, a segment's `crop`, or a matching row's `reader` is missing | Keeps rows whose `segment` is in `SEGMENTS`, `window` is "crop", `inner_px` is 64 and `auc_as_stored` is not null. It does not look at `map_from`; a later row for the same reader and segment replaces an earlier one |
| `from_mac(work, crops)` | `(table, skipped)`: `table` as above with the file path as third item; `skipped` is a list of `PATH: reason` strings | `KeyError` when `crops` lacks a segment; a file whose `forward` or `control` is not an object is skipped, not raised | Reads `work/SEGMENT/results/auc_*.json` in sorted order. Names come from `MAC_NAMES`: `ink9um_s42` is `ink_9um seed42 (Mac)`, `ink9um_s43` is `ink_9um seed43 (Mac)`, `v8in` is `v8in`, `v8in1447` is `v8in-1447`; any other file stem is used as it is |
| `decide(table, min_lead=MIN_LEAD, min_gap=MIN_GAP)` | Dict with `ranked`, `incomplete`, `verdict` and `rule` (see Outputs) | Nothing of its own | The rule itself, on a table of `{reader: {segment: (forward, reverse, source)}}` |
| `consistency(bars, mac)` | List of `{"segment", "cpu", "mac", "match"}`, one per crop where both `ink_9um seed42` (committed) and `ink_9um seed42 (Mac)` have a forward AUC | Nothing of its own | `match` is true when the two differ by at most 0.0001 |
| `run(work=None, results=RESULTS, min_lead=MIN_LEAD, min_gap=MIN_GAP)` | `decide`'s dict plus `checks`, `skipped` and `replaced`; a device mismatch adds `verdict.blocked: true` | As `committed` and `from_mac` | What the command runs. Mac cells replace committed cells of the same reader name and segment, with each replacement recorded. Any failed device check suppresses the winner and lead |
| `format_result(result)` | str: the Markdown table and lines the command prints | `KeyError` on a dict without `checks` and `skipped`, such as `decide`'s output alone | Forward AUC to 4 decimals, reverse to 3 in brackets (`?` when missing) |

Module constants: `SEGMENTS = ("0841-w00", "0841-ag896", "0841-ag405")`, `MIN_LEAD = 0.02`, `MIN_GAP = 0.10`, `INNER = 64`, `RESULTS` (the clone's `docs/results.json`), `MAC_NAMES`.

## Inputs

| Input | Format | Notes |
| --- | --- | --- |
| `docs/results.json` (or `--results`) | JSON object | `segments.SEGMENT.crop` gives each crop as `[Y0, Y1, X0, X1]` in surface pixels (now `0841-w00` `[2624, 3264, 2688, 3328]`, `0841-ag896` `[2496, 3136, 1600, 2240]`, `0841-ag405` `[1024, 1664, 2496, 3136]`). Rows of `results` give `segment`, `window`, `inner_px`, `reader`, `auc_as_stored` (forward AUC) and `auc_reversed` (reverse AUC, may be null). The repository's file is about 290 KB; the gate reads it whole |
| `WORK/SEGMENT/results/auc_NAME.json` | `python -m kit auc --json` output | Read: `forward.auc`, `forward.inner` (must be 64), `control.auc` (may be missing), `control.inner` (when present, must be 64) and `crop` (must equal the committed crop for that segment). `SEGMENT` is `0841-w00`, `0841-ag896` or `0841-ag405`; `NAME` names the reader (see `from_mac`). `scripts/mac-w045.sh` writes `auc_ink9um_s42.json`, `auc_ink9um_s43.json` and `auc_MTAG.json` (`v8in`, `v8in1447`) |

Scores are pixel AUCs on the 9.366 um surface grid of each segment; see [auc](auc.md) for how they are made.

## Outputs

By default a Markdown table, one row per complete reader sorted by mean forward AUC, then lines for readers not ranked yet, each Mac check, each replaced committed bar, each skipped file, and the verdict (see Quick start). The Control column says `ok`, or `too close (min gap X)` where X is the smallest forward minus reverse gap (`None` when a reverse AUC is missing). The verdict line is one of:

- `Gate A: R1 leads R2 by L mean AUC: a clear win (at least 0.02)`
- `Gate A: R1 leads R2 by L mean AUC: within 0.02, so not a win; prefer the reader already in use, or score more crops`
- `Gate A: R1 is the only reader with all three crops and a clean control`
- `Gate A: no reader has all three crops with a clean control`
- `Gate A: blocked: the Mac's ink_9um seed 42 does not match the committed CPU bar on SEGMENT (crop, labels or code differ); explain the mismatch before ranking`

With `--json`, one object:

| Field | Type | Meaning |
| --- | --- | --- |
| `ranked` | list of objects | Every reader with a forward AUC on all three crops, highest mean first, eligible or not |
| `ranked[].reader` | str | Reader name (committed `reader`, or the Mac name) |
| `ranked[].mean` | float (4 decimals) | Mean forward AUC over the three crops |
| `ranked[].cells` | object | `{segment: [forward AUC, reverse AUC or null]}` |
| `ranked[].control_ok` | bool | True when forward minus reverse is at least `min_gap` on every crop |
| `ranked[].min_gap` | float (4 decimals) or null | Smallest forward minus reverse gap; null when a reverse AUC is missing |
| `incomplete` | list of str | Readers missing a crop or a forward AUC, sorted |
| `verdict.winner` | str or null | The eligible reader with the highest mean; null when none is eligible or a device mismatch blocks the verdict |
| `verdict.lead` | float or null | Winner's mean minus the second eligible reader's mean (both already rounded to 4 decimals); null with fewer than two eligible readers or when the verdict is blocked |
| `verdict.clear` | bool | True when `lead` is at least `min_lead`, and also true when only one reader is eligible (then nothing was beaten); false when blocked |
| `verdict.blocked` | bool, optional | Present and true when any Mac/CPU consistency check mismatches; otherwise absent. Use `verdict.get("blocked", False)` in Python |
| `verdict.text` | str | The verdict sentence, without `Gate A: ` |
| `rule.min_lead`, `rule.min_gap`, `rule.inner`, `rule.segments` | float, float, int, list of str | The rule used, as given |
| `checks` | list of objects | `{"segment", "cpu", "mac", "match"}` per crop, from `consistency` |
| `replaced` | list of objects | Each local cell that replaced a committed cell: `reader`, `segment`, `committed` forward AUC, `local` forward AUC (possibly null), and source `file` |
| `skipped` | list of str | `PATH: unreadable`, `PATH: forward and control must be objects with an auc; rescore this crop`, `PATH: not the standard crop with a 64 px edge (crop ..., inner ...)`, or `PATH: control scored with a N px edge, not 64` |

| Exit code | Meaning |
| --- | --- |
| `0` | Printed, and no Mac `ink_9um` seed 42 check mismatched. Any verdict, including "no reader", gives 0: read `verdict` |
| `1` | A Mac `ink_9um` seed 42 check mismatched (the table is still printed), or an error the command does not catch, with a traceback |
| `2` | The scores file is missing or unreadable (message on stderr), or a usage error from the argument parser |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `cannot read the scores: no PATH. The gate reads the repository's docs/results.json, which an installed package does not have: run it from a clone (git clone https://github.com/ChaseHendrick/Scrolls), or give --results` | `--results` (or the default, `docs/results.json` next to the code) is not a file; an installed `scrolls-workbench` has no `docs/` | Run from a clone, or pass `--results PATH` |
| `cannot read the scores: 'KEY'`, exit code 2 | The scores file lacks a key the gate needs, such as `segments`, a segment's `crop`, or `reader` in a matching row | Use the repository's `docs/results.json`, or fix the file |
| `cannot read the scores: Expecting ...`, exit code 2 | The scores file is not valid JSON | Fix or restore the file (`git checkout docs/results.json` in a clone) |
| `skipped PATH: forward and control must be objects with an auc; rescore this crop` | A Mac `auc_*.json` whose `forward` or `control` is not an object (such as a list); the file is left out, not fatal | Rescore that crop with `kit auc --json`, or remove the file |
| `skipped PATH: unreadable` | A Mac file that is not JSON, or lacks `forward` | Rerun its `kit auc --json`; the file is left out, not fatal |
| `skipped PATH: not the standard crop with a 64 px edge (crop [...], inner N)` | The Mac file was scored on another window or edge | Score with `--crop` equal to `segments.SEGMENT.crop` in `results.json` and `--inner 64` (QUICK mode of `scripts/mac-w045.sh` does) |
| `check SEGMENT: Mac ink_9um s42 A vs CPU B: MISMATCH (crop, labels or code differ; do not rank until explained)`, exit code 1 | The Mac `ink_9um` seed 42 score differs from the committed CPU bar by more than 0.0001 | Find the cause (crop, labels version, villa commit, device) before accepting a verdict. The diagnostic table remains, but `winner` and `lead` are null, `clear` is false and `blocked` is true |
| `skipped PATH: control scored with a N px edge, not 64` | The reverse control used another edge exclusion | Rescore forward and reverse on the same crop with `--inner 64`; a missing `control.inner` keeps the legacy 64 px assumption |
| `Not ranked yet (missing crops): R` | Reader R lacks a score on at least one crop (now Reader v2, which has no ag405 crop row) | Score the missing crop |
| `too close (min gap X)` in the Control column of reader R | R's forward AUC is less than `--min-gap` above its reverse on some crop, or a reverse is missing | R cannot win; check its reverse maps |
| `Gate A: no reader has all three crops with a clean control` | No reader is both complete and eligible | Score the missing crops and controls |
| `Gate A: ... within 0.02, so not a win; prefer the reader already in use, or score more crops` | The lead is below `--min-lead` | Keep the reader in use; do not report the leader as better |

## How it works

1. `cmd_gate` picks the work folder: the `work` argument, else `~/scrolls-work` when it is a folder, else none. It stops with exit code 2 if `--results` is not a file.
2. `committed` reads the crops of `SEGMENTS` from `segments`, and every `results` row on those segments with `window` "crop", `inner_px` 64 (`INNER`) and a forward AUC.
3. `from_mac` reads each `WORK/SEGMENT/results/auc_*.json`, keeps it only if its `crop` equals the committed crop and `forward.inner` is 64, and `control.inner`, if recorded, is also 64; it names the reader from the file stem (`MAC_NAMES`). Mac cells are merged over committed cells of the same reader name, recording replacements in `replaced`; the Mac `ink_9um` files get their own names ending in ` (Mac)`, so they do not overwrite the CPU bars.
4. `decide` leaves out readers missing any crop. For the rest it takes the mean forward AUC over the three crops (rounded to 4 decimals) and the forward minus reverse gap on each crop; a reader is eligible (`control_ok`) when every gap is at least `min_gap`. Readers are sorted by mean, highest first.
5. The verdict uses eligible readers only: none gives no winner; one gives that reader with `clear` true; two or more give the top one, its lead over the second (from the rounded means), and `clear` when the lead is at least `min_lead` (`MIN_LEAD`, 0.02).
6. `consistency` compares `ink_9um seed42 (Mac)` with the committed `ink_9um seed42` on each crop; more than 0.0001 apart (one unit in the fourth decimal, plus 1e-9 for float rounding) is a mismatch. `run` replaces the verdict with a blocked message, null winner and lead, and `clear: false`; `cmd_gate` returns 1.

The rule's numbers are fixed in code (`MIN_LEAD`, `MIN_GAP`, `INNER`, `SEGMENTS`), so the readout is set before new scores arrive, as preregistration asks. The 0.10 gap is this repository's reading of the rule's "reverse well below forward"; the 0.02 lead is the rule's own number. Neither is a published community standard ([STANDARDS.md](../STANDARDS.md): TAUIL ranks by a plain mean over segments; ShribyrLabs counts no difference under 0.005 run-to-run noise; Community reports).

## Cost and time

About 0.1 s wall time on committed scores only (measured with `time` on 2026-10-16, 4-core 2.1 GHz Xeon cloud container); it reads one JSON file of about 290 KB and a few small files. Memory is negligible. It runs anywhere; nothing here needs Modal or a GPU. The scores it reads cost far more: about 20 minutes per reader and crop on the M1 Pro in fp32 ([mac.md](../mac.md)).

## For agents

- **Command:** `python -m kit gate --json` from a clone (committed scores, plus `~/scrolls-work` if it exists); with Mac results, `python -m kit gate WORK --json`.
- **Parse:** `verdict.winner`, `verdict.lead`, `verdict.clear` and `verdict.text`; `ranked[].control_ok` and `ranked[].min_gap`; `incomplete`; `checks[].match`; optional `verdict.blocked`; `replaced`; `skipped`.
- **Rerun:** Safe; it only reads its inputs and writes nothing.
- **Success:** Exit code 0, `verdict.clear` true and `verdict.lead` not null (the winner beat a second eligible reader by at least `min_lead`).
- **Not a pass:** Exit code 1 (a Mac/CPU mismatch), even though a table and verdict are printed; `verdict.clear` true with `verdict.lead` null (only one eligible reader, nothing was beaten); a reader with `control_ok` false, however high its mean; a lead under about 0.04 with no paired `kit auc --compare --bootstrap 300` interval on each crop; any result with `--min-lead` or `--min-gap` changed from the defaults after seeing scores; files listed in `skipped` that you expected to count.
- **Go-ahead:** Nothing.
- **Never:** Call the winner a reader of letters or its maps readings; edit a Mac file's `crop` or `inner` to make it count; add Hecate scores on PHerc0841 to the table as a fair comparison.

## Tests

```bash
python -m unittest tests.test_gate -v
```

They cover ranking from committed bars alone with a clear win, a Mac reader whose lead is under 0.02 (not a win), an incomplete reader, a Mac file on the wrong crop and one whose forward or control is not an object (both skipped), a reader with a weak control that has the highest mean but does not win, the Mac `ink_9um` seed 42 check through the command line (exit code 1 and the MISMATCH and match lines), and the missing scores file (exit code 2 and the clone hint). They use a synthetic `results.json` and need only the standard library. They do not cover `--json`, the `~/scrolls-work` default, unreadable Mac files, the one-reader and no-reader verdicts, or the repository's real `results.json`.

## History

- 2026-10-17: reference corrected to describe behavior already present in `cfb6792`: the blocked verdict, `replaced` records and mismatched control-edge rejection. No scoring behavior change.
- 2026-10-17: a Mac `auc_*.json` whose `forward` or `control` is not an object is skipped with a message; before, it stopped the gate with an `AttributeError` traceback and exit code 1 (`107b379`).
- 2026-10-14: a missing `docs/results.json`, as in an installed package, gives the "run it from a clone" message and exit code 2 instead of a traceback (`ca7b143`).
- 2026-10-09: the docstring states the rule itself, since the roadmap moved to the private repository, and names the smallest committed gap (0.1015); no behavior change (`3ba683f`).
- 2026-10-07: first version, with committed bars, Mac `auc_*.json` files, the 0.10 control gap and the Mac against CPU check, run at the end of `scripts/mac-phase0.sh` (`bec6fb9`).

## Related

- [`auc`](auc.md): makes every score the gate reads, with the reverse-depth control and `--compare` for paired intervals.
- [`mac-phase0`](mac-phase0.md): the Mac queue that scores v8in and v8in-1447 on the three crops and ends with this table.
- [`mac-w045`](mac-w045.md): the Mac script whose QUICK mode writes the `auc_*.json` files.
- [`ensemble`](ensemble.md): averages maps; an ensemble scored on the crops can be compared by hand, not ranked here unless its files follow the Mac naming.
- [STANDARDS.md](../STANDARDS.md): the Gate A row, the community rules it is compared with, and the known gap about noise.
- [Overlap and baseline log](../logs/2026-10-07-overlap-and-baseline.md): the bootstrap intervals that put 0.02 at the noise floor.
- [PHerc0841 and Hecate log](../logs/2026-10-09-pherc0841-hecate.md): why Hecate is not ranked on PHerc0841.
- [`results.json`](../results.json): `segments` (the crops), `results` (the committed bars) and `held_out`.
