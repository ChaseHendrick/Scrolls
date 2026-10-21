# causal: trace every result, claim and tool output to its causes and effects

Reads the links the repository already holds (results, decisions, README claims, preregistrations, run and provenance records, releases, tool pages), derives the rest, and checks that anything added after the cutover carries its required causal links.

| Field | Value |
| --- | --- |
| Id | `causal` |
| Status | Experimental |
| Kind | kit command, kit module |
| Area | Records and provenance |
| Run | `python -m kit causal why`, `python -m kit causal effects`, `python -m kit causal show`, `python -m kit causal gaps`, `python -m kit causal check`, `python -m kit causal parse`, `python -m kit causal link`, `python -m kit causal add`, `python -m kit causal backfill`, `python -m kit causal ratchet`, `python -m kit.causal`, `from kit import causal`; every test run, through `tests/test_causal_repo.py` |
| Code | `kit/causal.py`, `docs/causal/README.md`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_causal.py`, `tests/test_causal_repo.py`, `tests/test_causal_shared.py`, `tests/test_runrecord.py` |
| Needs | Python 3.10 or newer, standard library only, plus `kit/stale.py`, `kit/provenance.py` and `kit/tooldocs.py`; git for tracked files and pins (it falls back to the file tree without git); `gh` only with `--network` |
| Runs on | Any CPU. On this repository `check --no-hash` 1.1 s, full `check` 1.4 s and `gaps --counts` 1.3 s wall (measured 2026-10-21, 4-core Intel Xeon at 2.80 GHz cloud container, 90 results entries, 62 tool pages) |
| Network | None; `check --network` asks GitHub (`gh api repos/OWNER/REPO/commits/SHA`) about commits this clone cannot reach |
| Writes | Nothing for why, effects, show, gaps, check and parse. `link` appends to `docs/causal/edges.jsonl`; `add result --write` edits one `docs/results.json` entry and copies its run record to `docs/causal/runs/TOKEN.json`; `add claim --write` edits `docs/causal/claims.json`; `backfill --write` edits `docs/results.json`, `docs/DECISIONS.md`, `docs/causal/claims.json` or `docs/causal/edges.jsonl` (by pass) and records the pass in `docs/causal/baseline.json`; `ratchet --write` writes `docs/causal/baseline.json`. Every writer refuses frozen paths (rule E13) |
| Go-ahead | Not needed for the tool. A `private:` digest written into a public file needs Chase's yes in its PR (hard rule 8) |
| Released | Public `main` from the change that adds it (21 Oct 2026). `kit/causal.py` is shared code, byte-identical in Scrolls-private, as `kit/stale.py` is; `tests/test_causal_shared.py` pins its bytes in both |
| Checked | 2026-10-21 against commit `3bd77be` plus this tool |

## What it does

Chase asked on 15 October 2026 for causal links between results and what produced them, and on 20 October 2026 to "create more causal links in the repos". A causal link here is provenance: a typed edge from an effect (a result, a claim, a release, a tool page) to what caused it (Chase's decision, the preregistration and its pin, the run spec, the run token or run record, the code commit, the inputs with their hashes, the control). `kit causal` reads those links across the whole repository and answers two questions: why does this exist (`why`, `show`), and what depends on it (`effects`).

It derives first. Each extractor reads one carrier as it stands: an alias map turns fields the files already have, such as `source`, `evidence`, `prereg`, `rule_sha256`, `token`, `*_commit` and `*_reversed`, into links; committed provenance records and runner records in `docs/evidence/` (`RECORD_SHAPES`) add their code and inputs; a results entry whose evidence folder holds exactly one record is joined to it; and requirements are met through chains of run, spec and prereg edges (transitive satisfaction). Only where nothing can be derived does it ask for a written link, in one grammar: the link line `REL REF [PIN]` (schema `causal/1`, 10 relations). The grammar, carriers, alias map and requirement table are in [docs/causal/README.md](../causal/README.md).

`check` is a shrink-only ratchet: everything added after the cutover (21 October 2026) must carry its required links, while the gaps that existed then (207 pairs over 112 nodes on this repository) sit in `docs/causal/baseline.json`, which may only shrink. Backfill runs in five named, bounded passes, each recorded once in the baseline's pass ledger, so nobody loops over the same old gaps.

A link records what produced or cited something. It does not show that a change caused a gain; that needs a matched null arm or a controlled swap. Its output is provenance, never a reading of a scroll, and an ink map stays model output.

Status is Experimental: the cutover baseline is fresh; one backfill pass (`ids`, 86 ids) and the reviewed link lines of 21 October 2026 are written, and the baseline was repinned once after merging `main` (the reason is under `repins` in `docs/causal/baseline.json`).

## When to use it

- Before trusting or citing a number: `why r:ID` shows what produced it and `show r:ID` says which required links are met, how, and which are missing.
- Before changing a number, a preregistration or an evidence folder: `effects REF` (or `effects --since REV` for a branch) lists the claims, tool pages, verdicts and decisions that cite it.
- When recording a new result: `add result --section S --from-run TOKEN --write` gives it an id and links from its run record and adopts the record; `check --new` before committing.
- When adding a README Novel findings item: `add claim ITEM --quote ... --label ... --cause r:ID --write`.
- When a frozen file needs a link it lacks: `link EFFECT 'LINE' --basis B` (edges.jsonl).

Do not use it:

- to attribute a gain to a change: compare against a matched null arm, with its own preregistered rule;
- to record a run: use [runrecord](runrecord.md) (or [run-local](run-local.md), which writes a run record by default);
- to check prose for stale facts: use [stale](stale.md);
- to score a map: use [auc](auc.md) with the reverse-depth control;
- to hash and verify files: use [provenance](provenance.md).

## Quick start

```bash
python -m kit causal gaps --counts
python -m kit causal why r:letter_reader_checks/5 --strong --depth 2
python -m kit causal check --new
```

`r:letter_reader_checks/5` is a results unit: a dict section's key, or `SECTION/INDEX` for a list row until the `ids` pass writes ids. What it printed on 2026-10-21:

```
115 nodes, 210 missing links (207 at the cutover, 0 new, 3 not enforced yet), 0 ambiguous joins
by kind: decision 3, evidence 8, finding 14, prereg 5, release 6, result 79
by gap: claim 14, code 9, control 15, decision 11, prereg 75, record 8, run 74, source 1, superseded_by 3

r:letter_reader_checks/5 (result)
  source:
    source docs/logs/2026-10-14-letter-reader.md [frozen] (typed, alias, docs/results.json ...)
  met source: source docs/logs/2026-10-14-letter-reader.md (typed, alias)
  missing: run, control, prereg
```

It worked when `check --new` exits 0 and `gaps --counts` reports `0 new`.

## Checks and controls

The check itself must be able to fail (hard rule 4). `tests/test_causal.py` builds synthetic repositories in which each of these fails, and the test fails if the check passes them: a new result with an AUC and no control (E10), a public file holding an approval link (E9), an edited number under a pinned claim (E17), a grown baseline and an `initial` set that no longer matches its hash (E11), a new Modal runner script with no run record helper and one with a free-text exemption (E14), a write into docs/evidence and other frozen paths (E13), a result contradicting its adopted run record's code (E16), and a supersession cycle and a cross-family supersession (E8). Hint edges never satisfy a requirement, and a join with two candidates is never made (both tested).

On this repository `tests/test_causal_repo.py` runs `check` with the baseline pinned (`INITIAL_SHA256` `c2f25901...` since the repin of 21 October 2026, `938b1e0a...` before it; `BASELINE_MAX` 207 at the cutover, 110 after the backfill and the repin): 0 errors on 2026-10-21, and 17 attention findings after the backfill (A1: prose preregistration fields and rule hashes that match no committed preregistration in this clone; A2: 10 commits this clone cannot reach; A6: record inputs recorded from an uncommitted tree). The backfill is described in [docs/causal/README.md](../causal/README.md#the-ratchet-and-the-pass-ledger).

Claim label: None for the tool's own output (it makes no scientific claim); its counts describe this repository's link coverage on 2026-10-21.

## Commands and options

### `python -m kit causal why`

```
usage: python -m kit causal why [-h] [--depth DEPTH] [--kind KIND] [--strong]
                                [--runs RUNS] [--root ROOT] [--json]
                                ref
```

| Option | Default | Meaning |
| --- | --- | --- |
| `ref` | required | a node: r:ID, c:ID, D<n>, tool:ID, a path, an app id, a token, a commit, or fuzzy text such as '2026-10-20 row' or a short hash |
| `--depth DEPTH` | `3` | how many links to walk (default 3) |
| `--kind KIND` | none | comma-separated cause groups to keep: decision,approval,spec,prereg,freeze,run,ledger,code,inputs,control,source,supersedes |
| `--strong` | off | only hash and typed edges |
| `--runs RUNS` | none | a run folder an extension may read (repeatable) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal effects`

```
usage: python -m kit causal effects [-h] [--depth DEPTH] [--since REV]
                                    [--root ROOT] [--json]
                                    [ref]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `ref` | none | a node, as for why |
| `--depth DEPTH` | `3` | how many links to walk (default 3) |
| `--since REV` | none | everything downstream of the files changed since REV |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal show`

```
usage: python -m kit causal show [-h] [--root ROOT] [--json] ref
```

| Option | Default | Meaning |
| --- | --- | --- |
| `ref` | required | a node, as for why |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal gaps`

```
usage: python -m kit causal gaps [-h] [--kind KIND] [--need NEED] [--new]
                                 [--suggest] [--counts] [--limit LIMIT]
                                 [--root ROOT] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--kind KIND` | none | comma-separated node kinds: result,finding,claim,spec,prereg,run,release,decision,script,evidence,approval,freeze |
| `--need NEED` | none | comma-separated missing relations to keep, such as control,prereg |
| `--new` | off | only pairs absent from the baseline |
| `--suggest` | off | attach weak suggestions (hint edges) to each gap |
| `--counts` | off | print only the counts, with none: use per relation |
| `--limit LIMIT` | `25` | rows to print (default 25; 0 prints all) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal check`

```
usage: python -m kit causal check [-h] [--new]
                                  [--only {E1,E2,E3,E4,E5,E6,E7,E8,E9,E10,E11,E12,E13,E14,E15,E16,E17,A1,A2,A3,A4,A5,A6,A7,A8,A9,A10}]
                                  [--strict] [--since SINCE] [--network]
                                  [--no-hash] [--runs RUNS] [--root ROOT]
                                  [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--new` | off | only what was added after the cutover (fast, for hooks) |
| `--only ONLY` | none | report only this rule (repeatable) |
| `--strict` | off | attention fails too (exit 1) |
| `--since SINCE` | none | also list results units changed since this revision (A3) |
| `--network` | off | confirm commits this clone lacks with gh api (read only) |
| `--no-hash` | off | skip pin hashing and record rechecks |
| `--runs RUNS` | none | a run folder an extension may read (repeatable) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal parse`

```
usage: python -m kit causal parse [-h] [--json] line
```

| Option | Default | Meaning |
| --- | --- | --- |
| `line` | required | 'REL REF [PIN]' |
| `--json` | off | print JSON |

### `python -m kit causal link`

```
usage: python -m kit causal link [-h] [--basis BASIS] [--alias OLD NEW]
                                 [--retract SHA8] [--reason REASON] [--by BY]
                                 [--dry-run] [--root ROOT] [--json]
                                 [effect] [line]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `effect` | none | the effect end: a frozen prereg, spec, log or evidence path, a decision, a commit or a run |
| `line` | none | the link line, 'REL REF [PIN]' |
| `--basis BASIS` | none | path:line, a URL, review, or owner (Chase's words with the UTC time) |
| `--alias OLD NEW` | none | record that OLD now resolves to NEW |
| `--retract SHA8` | none | retract the edge of docs/causal/edges.jsonl whose sha8 this is |
| `--reason REASON` | none | why an edge is retracted |
| `--by BY` | none | who adds the edge (kept in the record) |
| `--dry-run` | off | print the record, write nothing |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal add`

```
usage: python -m kit causal add [-h] [--section SECTION] [--from-run TOKEN]
                                [--row ROW] [--id ID] [--quote QUOTE]
                                [--label {Sourced fact,Organizer result,Community report,Model output,Measurement,Null,Interpretation,Untested idea}]
                                [--cause REF] [--repin c:ID] [--write]
                                [--root ROOT] [--json]
                                {result,claim} [item]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `what` | required | what to add |
| `item` | none | claim: the Novel findings item number |
| `--section SECTION` | none | result: the results section |
| `--from-run TOKEN` | none | result: the run record's token |
| `--row ROW` | none | result: the row to fill (default the section's last row) |
| `--id ID` | none | result: the id (default SECTION/INDEX); claim: the claim id |
| `--quote QUOTE` | none | claim: text that occurs exactly once in the item |
| `--label LABEL` | none | claim: its NOVELTY.md label |
| `--cause REF` | none | claim: r:<id> or a docs/evidence path (repeatable); pinned automatically |
| `--repin c:ID` | none | claim: re-pin a reviewed claim to its units' current hashes |
| `--write` | off | write the change (default: dry run) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal backfill`

```
usage: python -m kit causal backfill [-h]
                                     --pass {ids,decision-ids,joins,claims,frozen}
                                     [--limit LIMIT] [--write] [--again]
                                     [--reason REASON] [--root ROOT] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--pass PASS_NAME` | required | the pass to run |
| `--limit LIMIT` | `200` | stop after this many changes (default 200) |
| `--write` | off | write the changes and record the pass (default: dry run) |
| `--again` | off | run a pass the ledger already records (needs --reason) |
| `--reason REASON` | none | why the pass runs again (recorded) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

### `python -m kit causal ratchet`

```
usage: python -m kit causal ratchet [-h] [--write] [--repin] [--reason REASON]
                                    [--root ROOT] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--write` | off | write the baseline (default: dry run) |
| `--repin` | off | rebuild the baseline from the tree (needs --reason) |
| `--reason REASON` | none | why the baseline is rebuilt (recorded) |
| `--root ROOT` | `.` | repository root (default: this checkout) |
| `--json` | off | print JSON (the dict the Python API returns) |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `CausalError()` | an exception (a ValueError) | nothing | Some carry `.candidates`, the nodes an ambiguous reference matched |
| `Graph(root, public=None)` | a graph with `nodes`, `edges`, `findings`, `carriers`, `ambiguous`, `causes(key)`, `effects(key)` | nothing | Built by `load`; `public` defaults to on when the repository has no `kit/causal_ext.py` (public Scrolls has none) |
| `parse(line)` | dict {rel, ref, kind, pin, at, path, anchor, note} | `CausalError` (rule E1) | Removed relations name their replacement |
| `ref_kind(ref)` | str, the reference kind or `unknown` | nothing | Decided by shape alone |
| `unit_sha256(entry)` | str, 64 hex | nothing | Without `id` and `causal` |
| `results_units(data)` | list of (section, index or None, entry) | nothing | Pending strings included |
| `load(root=ROOT, runs=(), public=None)` | a `Graph` | nothing (a malformed carrier becomes a finding) | Runs every extractor, any hooks, the joins and the evidence pass |
| `resolve(g, text)` | dict {key, kind, candidates} | `CausalError`, with `.candidates` when ambiguous | Fuzzy: ids, index citations, '2026-10-20 row', hash prefixes, paths, substrings |
| `why(g, ref, depth=3, kinds=(), strong=False)` | dict {node, kind, state, causes, missing, met, chains} | `CausalError` | `met` gives each requirement's path |
| `effects(g, ref, depth=3)` | dict {node, kind, effects, superseded_by, mentioned_in_handoff, stale_citers} | `CausalError` | Effects are the graph turned around |
| `show(g, ref)` | dict: the node, `causes`, `effects`, `requirements` {rel: {status, how or note}} | `CausalError` | Status is met, missing or baselined |
| `requirements(g)` | dict {key: {kind, missing, notes, met, enforceable}} | nothing | A repository with private extractors adds its own node kinds through `HOOKS` |
| `gaps(g, kinds=(), need=(), new=False, suggest=False)` | dict {gaps, counts} | nothing | `counts.none_lines` per relation; `provisional` for unenforced decision rows |
| `impact(root=ROOT, since='HEAD~1', graph=None)` | dict {since, results, files} | `CausalError` for an unreadable revision | Used by `effects --since` |
| `check(root=ROOT, only=(), strict=False, network=False, hash_pins=True, since=None, new_only=False, runs=(), public=None, graph=None, pinned_sha=None, pinned_max=None)` | dict {exit, findings, info, carriers, counts, errors, attention, public} | nothing | `new_only` keeps errors only and skips the slow scans |
| `link(root=ROOT, effect=None, line=None, basis=None, dry_run=False, alias=None, retract=None, reason=None, public=None, graph=None, by=None)` | dict {written, record, file, sha8} | `CausalError` | Retraction is by the edge's sha8, safe under union merges |
| `add_result(root=ROOT, section=None, from_run=None, rid=None, row=None, write=False)` | dict {section, id, causal, from, written, adopted} | `CausalError` | Adopts a work/ record into docs/causal/runs/ |
| `add_claim(root=ROOT, item=None, quote=None, label=None, causes=(), cid=None, repin=None, write=False, graph=None)` | dict {claim, entry, written} or, with repin, {claim, changes, written} | `CausalError` | Repin lists each old and new unit for review |
| `backfill(root=ROOT, pass_name='ids', write=False, limit=200, again=False, reason=None, graph=None)` | dict {pass, write, changes, review, exit} | `CausalError` | `exit` is 3 for a pass the baseline's pass ledger already records |
| `ratchet(root=ROOT, write=False, repin=False, reason=None, graph=None)` | dict {created, written, keys, ...} | `CausalError` for repin without a reason | Never adds a gap except through a recorded repin |
| `add_arguments(p)` | None | nothing | Adds the actions to an argparse parser; a repository's `HOOKS` may add more |
| `run(args)` | int exit code | nothing (prints `kit causal: MESSAGE` and returns 1 on `CausalError`) | The CLI entry `kit/cli.py` defers to |
| `main(argv=None)` | int exit code | argparse exits 2 on usage errors | `python -m kit.causal` |

## Inputs

Everything is read from the repository at `--root` (default this checkout); nothing is downloaded.

| Input | What it reads |
| --- | --- |
| `docs/results.json` | every unit: `id`, `causal` and the alias-map fields |
| `docs/DECISIONS.md` | the decisions table (`Date \| Decision`, or `Id \| Date \| Decision` after the decision-ids pass), and Replaces, Lifts, Retires D<n> |
| `README.md` and `docs/causal/claims.json` | the Novel findings items and their claims |
| `docs/prereg/`, `docs/compute/modal-specs/`, `docs/logs/`, `docs/tools/` | ```causal fences, id tokens, History bullets |
| `docs/causal/edges.jsonl`, `docs/causal/runs/*.json`, `docs/causal/baseline.json` | overlay edges, adopted run records, the cutover baseline and pass ledger |
| tracked `*provenance*.json`, `*.runrecord.json` and RECORD_SHAPES files | records, read after their digest verifies |
| `docs/evidence/**/SHA256SUMS` | pin targets for evidence folders |
| `docs/releases.json` | each release's `causal` list and fields |
| `docs/compute/modal-ledger.csv` | the `app_id` column, as a join target |
| `scripts/**/*.py` outside `scripts/experiments/` | Modal runner markers, helper signs and exemption headers (rule E14) |
| `tests/test_repo.py` | `HASH_PINNED_WITH_DASHES`, for the frozen-path guard |
| `docs/HANDOFF.md` | read only, as "mentioned in"; it never satisfies a requirement |
| `--runs DIR` | run folders an extension may read (none in public Scrolls) |

## Outputs

Text by default; `--json` prints the dict the Python API returns.

| Field | Type | Meaning |
| --- | --- | --- |
| `findings[].rule`, `.level`, `.where`, `.text` | str | one check finding: E1 to E17 are errors, A1 to A10 attention |
| `counts` (check) | object | findings per rule |
| `carriers` | object | each carrier's status (ok, skipped, failed), count and note |
| `gaps[].node`, `.kind`, `.missing`, `.old`, `.baselined`, `.new`, `.suggest` | mixed | one node's missing links, whether it predates the cutover and is in the baseline, and weak suggestions |
| `counts` (gaps) | object | nodes, pairs, by_kind, by_gap, old_pairs, new_pairs, provisional, none_lines, ambiguous |
| `causes` / `effects` | object | groups of edges with ref, rel, state, cls (hash, typed, hint), via, carrier, pin |
| `met` / `requirements` | object | how each requirement is met (the chain of edges), or missing, or baselined |
| `changes`, `review` (backfill) | list | what a pass writes, and what it leaves for a person |

| Exit code | Meaning |
| --- | --- |
| `0` | ok: no errors and nothing that needs a look (for why, effects and show: the node resolved) |
| `1` | failure: an E finding, or a refused request (`kit causal: MESSAGE` on stderr) |
| `2` | usage: a missing or wrong argument |
| `3` | attention: A findings, an ambiguous REF (candidates printed), or a backfill pass the baseline's pass ledger already records |
| `75` | skipped: no carrier is present (not a repository this tool reads) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `cannot rewrite a JSON file whose layout json.dumps does not reproduce; edit it by hand` | The JSON file is not in a layout the writer can reproduce byte for byte | Add the change by hand, keeping the file's layout |
| `no run record for token` | No `docs/causal/runs/TOKEN.json` or `work/causal/runs/TOKEN.json` | Finish the run with `python -m kit runrecord finish TOKEN`, or check the token |
| `a claim cause is r:<id> or a docs/evidence path, not` | `--cause` named something else | Cite the results unit (`r:ID`) or the evidence folder holding the number |
| `a link line must be a string` | A `causal` list holds a non-string | Write each link as one string |
| `not a link line (REL REF [PIN], single spaces):` | Wrong number of parts or double spaces | Write `REL REF [PIN]` with single spaces |
| `before the cutover; write` | `model`, `record`, `evidence` or `qualifies` were folded into other relations | Use the relation the message names |
| `unknown relation` | REL is not one of the 12 | Use a relation from docs/causal/README.md |
| `unknown reference` | REF matches no reference kind | Use an id, a tracked path, a URL, a token, a commit or `sha256:` |
| `a pin is sha256:<64 hex>, not` | The third part is not a sha256 pin | Pin with `sha256:` and 64 lowercase hex |
| `: it is frozen (docs/prereg, docs/evidence, docs/logs, archive, scripts/experiments, a hash-pinned or freeze-listed file, or docs/HANDOFF.md)` | A writer was pointed at a frozen file (rule E13) | Put the link in docs/causal/edges.jsonl with `kit causal link` |
| `nothing to resolve` | An empty REF | Give a node |
| `no node matches` | REF names nothing the graph holds | Check the id with `gaps` or `show` on a nearby node |
| `cannot read revision` | `--since` names a revision git does not have | Fetch it, or use another revision |
| `: digest does not match the record` | A run record was edited after it was written | Do not edit records; rerun or write a new record |
| `has no results section` | `--section` is not a results section | List sections with `python3 -c "import json; print(list(json.load(open('docs/results.json'))))"` |
| `must hold a list under "claims"` | docs/causal/claims.json is malformed | Restore `{"schema": "causal-claims/1", "claims": [...]}` |
| `Novel findings has no item` | ITEM is not an item number of the README's Novel findings | Count the items from 1 |
| `the quote must occur exactly once in item` | The quote is missing from the item or repeats | Quote a phrase unique to the item |
| `label must be one of` | The label is not a NOVELTY.md label | Use one of the labels the message lists |
| `a claim needs at least one --cause (r:<id> or a docs/evidence path)` | No cause given | Add `--cause r:ID` |
| `must be lowercase letters, digits, '.', '_' or '-'` | The claim id has other characters | Pick an id from lowercase words |
| `unknown pass` | `--pass` is not one of the five | Use ids, decision-ids, joins, claims or frozen |
| `--again needs --reason` | A recorded pass was asked to run again without a reason | Say why with `--reason TEXT` |
| `: create it with python -m kit causal ratchet --write first, so the pass ledger has a home` | No baseline yet | Create it with `ratchet --write` at the cutover commit (public Scrolls has one since 21 October 2026) |
| `--repin needs --reason` | A baseline rebuild without a reason | Give `--reason TEXT`; update the test's pins in the same commit |
| `cannot be none: in` | Only run, prereg and control take `none:` | Name the real cause |
| `reason; one of` | The `none:` reason is not on the relation's closed list | Use a listed reason, or link the real cause |
| `a retraction needs --reason` | `--retract` without `--reason` | Say why the edge was wrong |
| `has no live edge whose sha8 is` | No unretracted edge has that sha8 | Take the sha8 from `link` output or `show` |
| `has no rows; add the row first` | `add result` on an empty list section | Add the row, then run `add result` |
| `has no object row` | `--row` is out of range or not an object | Give the index of an object row |
| `must match [a-z0-9][a-z0-9_./-]*` | The id has other characters | Use lowercase letters, digits, `_`, `.`, `/`, `-` |
| `is not a results unit` | A claim cause `r:ID` names no unit | Check the id |
| `is not tracked` | A path is not in git | Commit the file first |
| `is not a claim in` | `--repin` names no claim | Check the claim id in docs/causal/claims.json |
| `an alias needs --basis` | `--alias` without a basis | Give `--basis` (path:line, URL, review or owner) |
| `does not resolve` | A node reference names nothing the graph holds | Fix the reference, or add the node first |
| `an edge needs --basis: file:line, a URL, review, or owner (Chase's words with the UTC time)` | `link` without `--basis` | Give the basis |
| `an edge needs an EFFECT` | `link` without the effect end | Give EFFECT before LINE |
| `carries its own links; write the line there, not in` | The effect has its own `causal` slot (a result, claim, release or record; approvals and freezes where a repository keeps them) | Write the line into that entry |
| `is a local path; link something tracked` | REF is under work/, experiments/ or an absolute path | Commit the file and link it |
| `cannot point to a` | The REF kind is wrong for the relation (rule E6) | See the REL table in docs/causal/README.md |
| `refused in a public repository:` | A private reference in public Scrolls (rule E9): an approval or freeze link, a Modal app id, a `public:` reference, an untracked path or a commit public history lacks | Use public references only; a `private:` record digest needs Chase's yes in its PR |

## How it works

1. `load` reads the baseline, then runs the extractors in order: DECISIONS, docs/causal (edges.jsonl with retractions by sha8, claims.json, adopted runs), results (ids, aliases, `causal`, the `community` defaults), README findings, preregistration and spec files, committed records (digest records, then RECORD_SHAPES), releases, the Modal ledger's app ids, tool pages, logs and runner scripts; then any `HOOKS` (public Scrolls registers none); then `_derive_joins` (a result's evidence folder holding exactly one record) and the evidence-folder pass.
2. Each edge gets a class: `hash` when pinned or covered by a digest, `hint` for prose and regular expressions, else `typed`, and a `via` tag (`VIAS`: field, alias, join, recorded, fence, overlay, token, default, regex).
3. `requirements` evaluates each node with `_meets`: a direct hash or typed edge of the relation, or, for `TRANSITIVE` relations (decision, spec, prereg, code, control, input), a chain of up to 4 hash or typed edges whose relations are in `CHAIN_RELS` (run, spec, prereg) ending at a node that meets it directly. A control passes only from a record that carries one. Joins with several candidates are never made.
4. `check` applies the rules (docs/causal/README.md lists them) and compares each node with the baseline: an old node is judged only against its listed gaps; a new one must have none. `unit_sha256` (canonical JSON without `id` and `causal`) recognizes old list rows after a move; position recognizes them after an edit.
5. Writers (`link`, `add`, `backfill`, `ratchet`) refuse frozen paths (`FROZEN_PREFIXES`, `FROZEN_FILES`, `HASH_PINNED_WITH_DASHES`) and write atomically; edges.jsonl is append-only.

Constants: `SCHEMA = "causal/1"`, `RELS` (10), `PRIVATE_RELS` (approval, freeze: refused in public files), `NONE` (closed reasons), `PASSES` (ids, decision-ids, joins, claims, frozen), `HASH_BUDGET = 256 MB` of pin hashing per check, `EXTERNAL_SECTIONS = ("community",)`.

## Cost and time

Local CPU only, seconds. Measured 2026-10-21 on a 4-core Intel Xeon at 2.80 GHz cloud container on this repository: `check --no-hash` 1.1 s, `check` 1.4 s, `gaps --counts` 1.3 s; `tests.test_causal`, `tests.test_runrecord` and `tests.test_causal_shared` together 54 tests in about 37 s. No compute is rented.

## For agents

- **Command:** `python -m kit causal check --json` (all rules) or `python -m kit causal check --new` (errors on new nodes only); `python -m kit causal show r:ID --json`; `python -m kit causal gaps --new --json`.
- **Parse:** check: `exit`, `errors`, and `findings[]` with `rule`, `where`, `text` (each text names what to add and where); show: `requirements` {rel: {status: met, missing or baselined, how}}; gaps: `counts.new_pairs` (must be 0) and `gaps[]`.
- **Rerun:** read-only actions are safe to rerun. `link` appends; `add --write` and `backfill --write` change carriers (a backfill pass records itself and exits 3 on a second run unless `--again --reason`); `ratchet --write` only shrinks the baseline.
- **Success:** `check` exit 0 (or 3 with only A findings on old nodes), `errors` 0, `gaps --counts` `0 new`.
- **Not a pass:** a requirement met only by a hint edge (it is not met); a result whose control is `none:` while it has a score (rule E10 fails it); a claim whose pins were refreshed without reading the changed unit; a link read as proof that a change caused a gain.
- **Go-ahead:** Nothing, except a `private:` digest in a public file (Chase's yes in its PR).
- **Never:** edit a frozen file, docs/evidence or docs/HANDOFF.md to add a link; invent a control, run or decision to close a gap; run a backfill pass again to hunt the same old gaps; put approval, freeze or private references in this repository; edit `kit/causal.py` here without landing the same bytes in Scrolls-private.

## Tests

`python -m unittest tests.test_causal tests.test_causal_repo tests.test_causal_shared -v`. `test_causal` (byte-identical in Scrolls-private) uses synthetic repositories only and covers the grammar, the alias map and its classes, the `community` defaults, transitive satisfaction through a run record, hint edges and two-candidate joins never satisfying, RECORD_SHAPES joins, the ratchet (new, moved, edited, grown, pinned, repinned), every rule's failing control listed under Checks and controls, the writers and frozen guard, the five passes and their ledger, `add result` adoption, claims and repins, and the CLI. `test_causal_repo` runs the check on this repository with the baseline pinned; `test_causal_shared` pins the shared files' bytes. Not covered here: `--network` (it needs GitHub) and the private extractors (approvals, freezes), which Scrolls-private tests.

## History

- 2026-10-21: Added to public Scrolls: the shared `kit/causal.py` (10 relations, hash, typed and hint edges, transitive satisfaction, RECORD_SHAPES, rules E1 to E17 and A1 to A10, five bounded backfill passes with a pass ledger), the cutover baseline in `docs/causal/baseline.json`, and the `causal` command (this change, on top of `3bd77be`)

## Related

- [docs/causal/README.md](../causal/README.md): the grammar, carriers, alias map, requirement table and working rule.
- [runrecord](runrecord.md): run records, the main source of new links; [run-local](run-local.md) writes one by default.
- [provenance](provenance.md): the record format run records extend.
- [stale](stale.md): the staleness checks this tool shares code with.
- [auc](auc.md): the score whose reverse-depth map is the control a scored result must link.
- [tooldocs](tooldocs.md): the tool pages whose History, Checks and Related sections carry id tokens.
