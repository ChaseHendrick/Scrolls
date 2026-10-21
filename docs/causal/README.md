# Causal links: from every result to what caused it, and forward to what it changed

Chase asked on 15 October 2026 for causal links between results and what produced them, and on 20 October 2026 (about 20:14 UTC) to "create more causal links in the repos". This page describes how this repository keeps them: every result, README claim, preregistration, run record, release and decision can be traced back to its causes (Chase's decision, the preregistration, the run spec, the run token or record, the code commit, the inputs with their hashes, the control) and forward to its effects (a verdict, a README claim, a tool page, a later decision, a result that supersedes it).

The tool is `python -m kit causal` ([page](../tools/causal.md)); run records come from `python -m kit runrecord` ([page](../tools/runrecord.md)) and, by default, from every `python -m kit run local` wrapper ([page](../tools/run-local.md)). A link records what produced or cited something. It never shows that a change caused a gain: that still needs a matched null arm with its own preregistered rule.

The design is "derive first, write ids once, enforce at the run chokepoints": the tool reads the fields the repository already has, joins them where there is exactly one candidate, and asks for a written link only where nothing can be derived. `kit/causal.py` and `kit/runrecord.py` are shared code, byte-identical in Scrolls-private (as `kit/stale.py` is); a repository with private registries adds its own extractors through `causal.HOOKS`, and public Scrolls registers none.

## The link line

Every written link is one line, `REL REF [PIN]`, separated by single spaces, schema `causal/1`. Text after ` # ` is a note the tool ignores. A line always reads "the carrier (the effect) REL REF (the cause)". Check one with `python -m kit causal parse 'LINE'`.

| REL | REF may be | Example |
| --- | --- | --- |
| `decision` | `D<n>` (a row of [DECISIONS.md](../DECISIONS.md), by row order until the Id column exists) | `decision D21` |
| `prereg` | a preregistration path pinned with `@<commit>` or a sha256 pin, a `sha256:` of a committed version, or `none:<reason>` | `prereg docs/prereg/2026-10-14-strokenet.md@abc1234` |
| `spec` | a `docs/compute/modal-specs/*.md` path | `spec docs/compute/modal-specs/2026-10-21-example.md` |
| `run` | a run token `YYYYMMDDTHHMMSSZ[-slug]`, a record (`sha256:<digest>` or its path), `private:<64 hex>` or `none:<reason>` | `run 20261021T101500Z-auc` |
| `code` | a commit of this repository (7 to 40 hex), `REPO@hex` (such as `villa@`), or `OWNER/REPO#N` (a PR) | `code villa@6723ad1` |
| `input` | a path (optionally `@commit`), an https URL (a model on Hugging Face is an input), or `sha256:`, each with an optional pin | `input https://huggingface.co/scrollprize/ink_9um` |
| `control` | `r:<id>`, `field:<key>` (a key of the same entry), `sha256:` (the control map or the null arm's record), a path, a run token, or `none:<reason>` | `control field:auc_reversed` |
| `source` | a tracked doc, log or `docs/evidence/` path (`#anchor` allowed; an evidence folder's pin is the sha256 of its `SHA256SUMS`), an https URL, `r:<id>`, `c:<id>`, `D<n>` or `tool:<id>` | `source docs/evidence/2026-10-14-strokenet/` |
| `supersedes`, `corrects` | a node of the same family: result to result (a new result may also supersede `r:pending@<sha8>`), claim to claim, decision to decision, log to log | `corrects r:letter_reader_checks/7` |

The grammar also names `approval` and `freeze`, which only repositories that keep approval and freeze registries use; `check` refuses them in this repository (rule E9). The parser names the replacement if you write a relation that was folded into another one (`model` is `input`, `record` is `run`, `evidence` is `source`, `qualifies` is `corrects`).

A **pin** is `sha256:<64 hex>` for the bytes of REF; a path may also carry `@<commit>`. Local paths (`work/`, `experiments/`, `/Users`, `/home`, `/tmp`) and untracked paths are refused in new links: commit the file or link something tracked.

**`none:` reasons** are a closed list per relation, so nobody writes a free-text excuse (`python -m kit causal gaps --counts` reports how many `none:` lines each relation has):

| REL | Allowed reasons |
| --- | --- |
| `run` | `community-report`, `literature`, `upstream-report`, `metadata`, `pending`, `no-compute` |
| `prereg` | `plumbing`, `development`, `benchmark-reproduction`, `community-report`, `not-a-readout` |
| `control` | `not-a-score`, `metadata`, `pending`; `community-report` only in the `community` section. Never for an entry with a score or a verdict (the every-check-can-fail rule, hard rule 4) |

## Where links live

Each link is stored once, at its effect end. Effects are never stored: they are the graph turned around, so nothing frozen is ever edited.

| Carrier | Holds links for | Written by |
| --- | --- | --- |
| [`docs/results.json`](../results.json): `"id"` and `"causal"` on an entry (the link block below) | results entries | the agent who records the result, or `python -m kit causal add result --from-run TOKEN --write` |
| [`docs/DECISIONS.md`](../DECISIONS.md): an Id column (after the `decision-ids` pass), and a newer row's `Replaces D<n>`, `Lifts D<n>` or `Retires D<n>` | decision rows | whoever adds the row |
| `docs/causal/claims.json` | README "Novel findings" claims | `python -m kit causal add claim`, or the `claims` backfill pass, then review |
| a ` ```causal ` fence in a new spec, preregistration, log or tool page | that file (written before it freezes) | its author |
| `"causal": [...]` in [`docs/releases.json`](../releases.json) entries | releases | whoever adds the entry |
| id tokens `r:<id>`, `c:<id>`, `tool:<id>` (and `D<n>` on a line naming DECISIONS.md) in a tool page's Related, Checks and controls or History section, or in a log | `source` links from that page | the page's author |
| `docs/causal/edges.jsonl` (append-only, `merge=union` in `.gitattributes`) | an effect end that has no slot of its own: a frozen log, preregistration, spec or evidence folder, or a commit | `python -m kit causal link` only |
| `docs/causal/runs/TOKEN.json` | a run record adopted with `python -m kit runrecord adopt` (or by `add result`); only records with `public` true | kit runrecord |

The tool also reads, without any change to them, the fields these files already have (the alias map below), committed provenance and run records, runner records in `docs/evidence/` (`RECORD_SHAPES`: `driver.json`, `run.json`, `launch.json`, `report.json`, `result.json`, `receipt.json` and `provenance.json` files that carry a token, commit, prereg or rule hash), `SHA256SUMS` files, tool pages' History bullets, the Modal ledger's `app_id` column, Modal runner scripts, and docs/HANDOFF.md (read only, shown as "mentioned in"; it never satisfies a requirement). Git commit trailers are not carriers.

## The link block in docs/results.json

A results entry may carry two keys besides its numbers:

```json
{
 "id": "example_checks/0",
 "date": "2026-10-21",
 "auc": 0.71,
 "auc_reversed": 0.49,
 "source": "docs/logs/2026-10-21-example.md",
 "causal": [
  "run 20261021T101500Z-auc",
  "prereg docs/prereg/2026-10-21-example.md@abc1234",
  "code abc1234",
  "control field:auc_reversed"
 ]
}
```

- **`id`**: `<section>/<slug>`, matching `[a-z0-9][a-z0-9_./-]*` and unique across the file. A dict section's key is its id, so dict sections need no `id` key. Ids written by the `ids` backfill pass are the row's index at the cutover (`letter_reader_checks/5` for what was `letter_reader_checks[5]`); after that they are labels, not positions. Cite a unit as `r:<id>`, never by index: indexes move.
- **`causal`**: link lines holding only what the entry's own fields cannot say, usually the run, decision, preregistration pin, code commit, control and any supersession. Do not restate a field the alias map already reads (rule A1).
- The metadata sections (`schema`, `updated`, `about`, `held_out`, `held_out_by_reader`, `segments`) and the `pending` strings need no id; a pending string is the node `r:pending@<first 8 hex of its sha256>`.
- **`unit_sha256`** is the sha256 of the entry's canonical JSON (sorted keys, separators `,` and `:`) without `id` and `causal`. It is computed, never stored. Adding links never changes it; changing a number does, and a README claim pinned to the old hash then fails (rule E17) until someone reviews it and runs `python -m kit causal add claim --repin c:<id> --write`.
- **The `community` section** holds other people's results: its rows get `run`, `prereg` and `control` `none:community-report` from code, never written.

**Alias map** (fields read as links, never rewritten): `source`, `log` and `evidence` are `source` (an `evidence_sha256` beside `evidence` is its pin; a `source` that is a preregistration or spec path also counts as that link); `prereg` and `amendment` are `prereg` (a `frozen at <hex>` phrase becomes the `@commit`); `rule_sha256` is `prereg sha256:`; `spec` is `spec`; `records` is `run`; `token`, `run`, `app` and `app_id` are `run` (a `run` object's `commit` is `code`); `*_commit` is `code` (in `community`, and for `villa*` keys, someone else's repository); `checkpoint_sha256` and `model` are `input`; keys with `reversed`, `reverse`, `control`, `null`, `sham`, `permuted` or `shuffled` as a word are `control field:<key>`; any other key whose value is exactly a tracked `docs/evidence/` or `docs/logs/` path is `source`. Tokens in `measured_by` prose are hints only. A `*_sha256` key beside a path key must still match that file (rule E5).

## How requirements are met

Edges have three classes: **hash** (pinned or covered by a record digest), **typed** (a field, an alias, a written line, a fence, an edges.jsonl overlay, an id token, a section default, or a single-candidate join) and **hint** (prose, regular expressions). Only hash and typed edges satisfy a requirement; hint edges show up as weak suggestions in `gaps --suggest`.

A requirement is met by a direct hash or typed edge, or, for `decision`, `spec`, `prereg`, `code`, `control` and `input`, through a chain of hash or typed edges whose relations are all `run`, `spec` or `prereg`, ending at a node that meets it directly. Example: a result names its run token, the token's adopted run record carries the code commit, so the result meets `code`. A control passes only from a run record that itself carries a control line. Joins with more than one candidate never pass; they are reported (rule A2). `python -m kit causal show REF` prints how each requirement was met, with the path.

## Required links (rule E10, for nodes added after the cutover)

| Node | Needs |
| --- | --- |
| Results entry | `source` (a tracked file, https URL or evidence path); `run`, or `run none:<reason>`; `code` when run is not none; `control` when the entry has a score key (`auc*`, `row_score*`, `pearson*`, `max_abs_diff`, `*_agreement`) or a verdict, with no `none:` (hard rule 4); `prereg` pinned when it has a verdict (hard rule 3), otherwise `prereg` or `none:<reason>` |
| README "Novel findings" item | a `claims.json` entry (rule E17) whose quote occurs exactly once in its item, with a label from [NOVELTY.md](../NOVELTY.md), at least one `r:` or `docs/evidence` cause, pins equal to each cited unit's current `unit_sha256`, and not only `community` rows |
| Spec | a `decision` |
| Preregistration | a `decision` or a `spec` |
| Adopted run record | `code`; a `decision`, `spec` or `prereg` (or `prereg none:development`) |
| Release | `decision` (Chase's yes) and `code` (a commit or PR) |
| Decision row | once DECISIONS.md has an Id column: a row that says it was replaced, lifted or retired is the target of a newer row's `Replaces D<n>` |
| Tool page History bullet dated after the cutover that reports a measurement | an `r:<id>`, a run token or a `docs/evidence/` path |
| Evidence folder | a `*.provenance.json`, `*.runrecord.json` or `RECORD_SHAPES` file, or a mention in an adopted run record's outputs |
| Modal runner script (rule E14) | `from kit import runrecord`, `runrecord.run(`, `kit runrecord wrap`, `kit run local` or `provenance write --causal`, or a header `# causal: exempt REASON` in its first 15 lines with REASON one of `library`, `plot`, `test-helper`, `no-output`, `frozen-copy` |

## The rules

`python -m kit causal check` reports errors (exit 1) and attention findings (exit 3). Errors: E1 grammar, E2 ids, E3 a strong edge whose cause does not resolve, E4 a local or untracked path in a new line, E5 a pin that differs from its bytes, E6 a reference kind wrong for its relation, E7 a `field:` key that is missing, E8 a supersession cycle or one across families, E9 a private reference in a public file, E10 a new node without its required links, E11 baseline integrity, E12 run record integrity, E13 a write into a frozen path, E14 a new Modal runner without the run record helper, E16 an entry that contradicts its adopted run record, E17 claims. Attention: A1 prose or local-only references in old entries, A2 ambiguous joins and commits this clone cannot reach, A4 index citations, A6 record inputs recorded from an uncommitted tree, A8 baselined gaps now filled, A10 a run record with no preregistration line, and the others the tool page lists. E15 and A5 (Modal ledger rows and approvals) apply only in repositories that keep approvals.

## The ratchet and the pass ledger

`docs/causal/baseline.json` lists, for every node that existed at the cutover (21 October 2026), the links it lacked then: 207 pairs over 112 nodes at the landing commit (result 79, finding 14, evidence 8, release 6, prereg 5; by missing link: prereg 75, run 74, control 15, claim 14, decision 11, code 9, record 8, source 1). `python -m kit causal check` (run by `tests/test_causal_repo.py`, so by every test run and by CI) fails on:

- anything added after the cutover without its required links (E10, E14, E17), and a results entry added without an `id` (E2);
- an old node that gains a gap the baseline does not list (E11), and any change that grows the baseline: a key or a gap not in its `initial` set, or `initial` no longer matching `initial_sha256`, which the repository test pins with `INITIAL_SHA256` and `BASELINE_MAX` (207).

Old list rows without an `id` are recognized by their `unit_sha256` (so moving a row keeps it old) and else by their position (so editing a row in place keeps it old); a row both moved and edited counts as new. README findings work the same way. When a gap is filled, `check` says so (A8) and `python -m kit causal ratchet --write` drops it; the baseline never takes a new key. A deliberate rebuild is `python -m kit causal ratchet --repin --reason TEXT --write`, recorded under `repins`, with the test's pins updated in the same commit.

**Backfill is bounded** (Chase, 21 October 2026: the gap fill must not waste tokens or loop forever). Each named pass (`ids`, `decision-ids`, `joins`, `claims`, `frozen`) is mechanical, never reads prose to invent a link, stops at `--limit`, and records itself with `--write` in the baseline's `passes` ledger. A recorded pass exits 3 unless `--again --reason TEXT` is given, and that reason is recorded too. Whatever a pass cannot fill stays in the baseline and leaves only when new work touches that node. Judgement links (`link --basis review`) are capped at 10 per session.

Dry runs at the landing commit: `ids` 86 changes, `decision-ids` 22 rows, `joins` 0, `claims` 0 changes with 14 to review (no item has both a NOVELTY label and a single results unit or evidence cause), `frozen` 0. None has been written yet.

To fix a failure, read its line: it names the node, what it lacks and where to add it. Typical fixes:

```bash
python -m kit causal gaps --new                      # what is new since the cutover and lacks links
python -m kit causal show r:SECTION/ID               # what a node has, and how each requirement is met
python -m kit causal add result --section SECTION --from-run TOKEN --write   # links from a run record, adopted
python -m kit causal link docs/prereg/X.md 'decision D21' --basis "docs/DECISIONS.md:30"   # a frozen file
python -m kit causal add claim --repin c:ID --write  # after reviewing a changed number under a claim
python -m kit causal ratchet --write                 # after filling old gaps
```

## Working rule for new work

From the cutover, in the same session as the result commit (work/ does not survive a cloud container):

1. Run local work through `python -m kit run local SLUG --causal LINE ... -- COMMAND` (it writes a run record by default, marked public in this repository; `--adopt` adopts it), or wrap any other run with `python -m kit runrecord wrap --public --tool TOOL --causal LINE ... -- COMMAND`. A Modal runner calls `runrecord.run(..., public=True)` in-process.
2. Record the result with an `id` and a `causal` list: `python -m kit causal add result --section SECTION --from-run TOKEN --write` fills both and adopts the record in the same change.
3. A new spec or preregistration carries a ` ```causal ` fence before it is frozen; a new release entry carries a `causal` list; a new README finding gets its `claims.json` entry (`python -m kit causal add claim`).
4. Run `python -m kit causal check` (or `check --new`, the fast path) before committing.

## Never

- Never edit a frozen file to add a link: docs/prereg, docs/evidence, docs/logs, archive, scripts/experiments, files in `HASH_PINNED_WITH_DASHES`, docs/HANDOFF.md, or docs/contrib/villa-1865-m1pro-comment.md. The writers refuse them (rule E13); put the edge in `docs/causal/edges.jsonl` with `python -m kit causal link`.
- Never put a private reference in this repository. The only bridge from Scrolls-private is `private:<64 hex>`, the digest of one private provenance or run record, which covers its timestamps and so cannot be guessed. The first one waits for Chase's yes in its PR. `check` refuses approval and freeze links, Modal app ids, `public:` references, commits public history lacks and untracked paths here (rule E9).
- Never invent a control, a run or a decision to close a gap; a real gap stays in the baseline.
- Never treat a link as proof that a change caused a gain, and never call an ink map a reading.
