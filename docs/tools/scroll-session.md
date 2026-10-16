# scroll-session: the Claude Code skill that runs a Vesuvius Challenge session step by step

The project skill `.claude/skills/scroll-session/` tells an agent how to start or continue Vesuvius Challenge work here: read the handoff, check prizes and the machine, plan and preregister a run, run it in the right place, and record the outcome without publishing a finding.

| Field | Value |
| --- | --- |
| Id | `scroll-session` |
| Status | Current |
| Kind | skill |
| Area | Pipeline and agents |
| Run | `/scroll-session` in Claude Code, or the Skill tool with the name `scroll-session` |
| Code | `.claude/skills/scroll-session/` |
| Tests | None: no test reads the skill's text. The commands it names are tested by their own tools' tests |
| Needs | Claude Code (or another agent that reads `.claude/skills/`), a clone of this repository, Python 3.10 or newer for `python -m kit` |
| Runs on | Wherever the agent runs. Step 1's commands take seconds; the run in step 4 goes where the Modal rule (hard rule 11) sends it |
| Network | None of its own. A run it plans may download data, and the prize re-check it suggests reads https://scrollprize.org/prizes |
| Writes | Nothing by itself. Its steps write a ledger record under `experiments/SLUG/` (`python -m kit run init`, `run local`, `run cost`, `run status`), a run spec in `docs/compute/modal-specs/` when a job goes to Modal, and the open-items table of `docs/HANDOFF.md` |
| Go-ahead | Needed for paid compute (the user's budget decision) and for anything outward; never for a possible finding, which stays private (the go-ahead rule, hard rule 8) |
| Released | Public `main` since 2026-10-06 |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

A skill is a Markdown file of instructions that Claude Code loads when its description matches the task, or when the user types its name. This one, `SKILL.md`, describes a session of prize work in five steps, each with the exact commands: orient (read the handoff, `python -m kit prizes`, `python -m kit doctor`, `python -m kit run list`), pick a target with the user, plan and preregister (`python -m kit plan`, `python -m kit run init`), run, and record the outcome (`python -m kit run status`).

Its main job is to keep the repository's hard rules in the agent's path at the moment they matter: the readout rule is written before anyone looks at target output (the preregistration rule), a GPU job or a long CPU job goes to Modal through a written run spec because Claude's cloud sessions cannot reach Modal (the Modal rule), local runs are wrapped in `python -m kit run local` so their cost reaches the ledger, and a possible finding is marked `candidate` and then not committed, pushed or described anywhere public (the no-findings rule).

It also routes target work out of this repository. This repository is public; a run on an eligible scroll without public labels belongs in the private workbench repository, and steps 3 to 5 are done from that checkout. Here the skill runs only public labelled benchmarks (PHerc0841, w045, w035) and generic tools.

It runs nothing by itself and makes no claim. An ink map a session produces is model output, not a reading, and the skill never lets an agent mark a run `published --announced` without the official announcement URL from the user.

## When to use it

- The user wants to attempt a prize, run the pipeline, or log results, and the agent needs the order of steps and the rules that apply.
- Starting a session in this repository with no other task named, to orient from the handoff and the prize snapshot.
- Recording a null result with its commands, control, costs and limits.

Do not use it:

- To publish, describe or commit a possible finding: the skill itself says never; stop and ask the user (`docs/WORKFLOW.md` section 3b).
- For target-scroll work from this public checkout: do it from the private repository.
- For a single tool question, such as scoring a map: read that tool's page ([`auc`](auc.md), [`verify`](verify.md)) instead.
- To run a GPU job from a Claude cloud session: write a run spec and hand it over, as step 4 says.

## Quick start

In Claude Code, from the repository root:

```bash
# type in the Claude Code prompt:
/scroll-session
# or ask for prize work ("let's try a First Letters run"); the description makes Claude load it.
# Step 1 then runs:
head -40 docs/HANDOFF.md
python -m kit prizes
python -m kit doctor
python -m kit run list
```

Step 1's commands, run by hand in a cloud container on 2026-10-16, printed (excerpts):

```
Open prizes, snapshot checked 2026-10-11 (https://scrollprize.org/prizes)

2027 Grand Prize             $1,000,000  2027-06-25  252 days left
...
[fail] gpu     No NVIDIA GPU found (nvidia-smi absent or failed). Ink inference needs CUDA; see docs/compute.md for rentals.
[pass] memory  16 GB memory
...
overall: fail
```

`python -m kit doctor` exits 1 there because the container has no GPU, which is expected in a cloud session; `python -m kit run list` printed nothing because the ledger was empty. It worked when the agent reports the open items, the prize snapshot's date and the machine's state, and asks the user which target and variable to test before planning anything.

## Checks and controls

- **The control comes first.** Step 4 says to run the control before the map (the reverse-depth map, the rule that every check must be able to fail). The skill itself has no pass or fail; its runs are judged by the tools it calls, such as [`auc`](auc.md) with `--control` and [`verify`](verify.md) with `--control`.
- **Preregistration before looking.** Step 3 writes the readout rule with `python -m kit run init ... --readout "..."` before any target output exists.
- **A stale prize snapshot is flagged.** Step 1 asks the agent to tell the user when the snapshot is older than about a month and to suggest re-checking the prize page. The snapshot in use was checked 2026-10-11 (`python -m kit prizes`, above).

Claim label: None; the skill makes no claim. The runs it leads to carry the labels of their own results.

## Commands and options

The skill has no options of its own. Its front matter, which Claude Code reads to decide when to load it:

| Front matter key | Value |
| --- | --- |
| `name` | `scroll-session` |
| `description` | "Start or continue Vesuvius Challenge work in this repo: check prizes, check the machine, plan a First Letters run, record it in the ledger. Use when the user wants to attempt a prize, run the pipeline, or log results. Never use it to publish, describe or commit a possible finding." |

### The steps and the commands they run

| Step | Commands | Tool page |
| --- | --- | --- |
| 1. Orient | `head -40 docs/HANDOFF.md`, `python -m kit prizes`, `python -m kit doctor`, `python -m kit run list` | [`prizes`](prizes.md), [`doctor`](doctor.md), [`run-ledger`](run-ledger.md) |
| 2. Pick a target with the user | Read `docs/state-of-play.md`; no published null repeated unchanged; name the one variable the run tests | |
| 3. Plan and preregister | `python -m kit plan SCROLL --batch N`, `python -m kit run init SLUG --scroll SCROLL --question "..." --readout "..."` | [`plan`](plan.md), [`run-ledger`](run-ledger.md) |
| 4. Run | Estimate the time; GPU or more than about an hour of CPU goes to Modal through a run spec in `docs/compute/modal-specs/`; shorter local jobs under `python -m kit run local SLUG -- COMMAND`; other costs with `python -m kit run cost`; `set -o pipefail` | [`run-local`](run-local.md), [`run-ledger`](run-ledger.md) |
| 5. Record the outcome | `python -m kit run status SLUG null --note "..."`, or `python -m kit run status SLUG candidate --note "..."` and stop; then update the open items in `docs/HANDOFF.md` | [`run-ledger`](run-ledger.md) |

- `SCROLL`: a scroll id such as `PHerc0826`. `N`: the inference batch size (`plan`'s default is 4, or 1 with `--mac`).
- `SLUG`: the ledger record's name. `COMMAND`: the command to run and time.

## Python API

Not applicable: a skill is instructions for an agent, not a library.

## Inputs

| Input | Where | Notes |
| --- | --- | --- |
| The user's request | The conversation | The description matches prize attempts, pipeline runs and logging results |
| `docs/HANDOFF.md` | This repository | Its rules and open items come first, so step 1 reads the top 40 lines |
| `docs/state-of-play.md` | This repository | What has been tried and published, so no null is repeated unchanged |
| The prize snapshot | Inside `kit` (`python -m kit prizes`) | Re-check https://scrollprize.org/prizes when it is older than about a month |
| `docs/compute/modal-pricing.md` | This repository | Rates for a Modal run spec's cost estimate |

## Outputs

What a session following the skill leaves behind:

| Output | Written by | Notes |
| --- | --- | --- |
| `experiments/SLUG/run.json` | `python -m kit run init`, `run local`, `run cost`, `run status` | The ledger record; `experiments/` is gitignored except its README |
| A run spec in `docs/compute/modal-specs/` | The agent | Only for generic, public-data jobs; a target-scroll spec goes in the private repository |
| A row in `docs/HANDOFF.md`'s open items | The agent | Private outcomes go only in the private repository's handoff |
| A report of a null | The agent, with the user | Commands, control, costs and limits |

The ledger statuses step 5 uses are `null` and `candidate`; `python -m kit run status` also accepts `planned`, `running`, `submitted` and `published`, and `--announced` only with the user's official announcement URL.

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| Claude does not load the skill | The request did not match the description, or the session did not start in this repository | Type `/scroll-session`, or start Claude Code from the repository root |
| `[fail] gpu     No NVIDIA GPU found ...` and `overall: fail` from `python -m kit doctor` | No CUDA GPU on this machine, as in Claude cloud sessions | Expected there; GPU work goes to Modal through a run spec (step 4) |
| `no experiment at ROOT/SLUG/run.json` from a `run` action | The ledger record was never started | Run `python -m kit run init SLUG ...` first (step 3) |
| The prize snapshot is more than about a month old | The snapshot inside `kit` was not refreshed | Tell the user and suggest re-checking the prize page and adding a dated snapshot |
| A Modal sign-in fails from a Claude cloud session | Its proxy does not carry Modal's gRPC traffic | Do not retry; write the run spec and give the user a prompt for an agent that runs Modal, or commands for their computer |
| The run looks like possible letters | A candidate | `python -m kit run status SLUG candidate --note "..."`, then stop: no commit, push or public description; tell the user and wait |

## How it works

Claude Code lists each project skill in `.claude/skills/` by its `name` and `description`. When a request matches, or the user types `/scroll-session`, the agent loads `SKILL.md` and follows its five sections in order, running their commands from the repository root. Two lines in the repository's instruction files point agents at it: `CLAUDE.md` ("For Vesuvius Challenge runs, use the project skill") and the private workbench's own copy of that line.

The skill names its rules by their public `AGENTS.md` numbers: hard rule 9 (log local compute), hard rule 11 (GPU work goes to Modal) and rule 14 (one handoff). If those numbers change, the skill's text must change with them.

## Cost and time

The skill costs nothing; step 1 takes seconds. A run's cost is estimated in step 4 before it starts, priced from `docs/compute/modal-pricing.md`, and needs the user's budget decision when it rents compute.

## For agents

- **Command:** load the skill (`/scroll-session` or the Skill tool), then run step 1: `head -40 docs/HANDOFF.md`, `python -m kit prizes`, `python -m kit doctor`, `python -m kit run list`.
- **Parse:** the handoff's open items; the prize snapshot's date in the first line of `python -m kit prizes`; the `[pass]`, `[warn]` and `[fail]` lines and `overall:` of `python -m kit doctor`.
- **Rerun:** Safe to load again. Step 3's `run init` refuses or duplicates nothing silently only if the slug is new; pick a new slug for a new run.
- **Success:** A preregistered ledger record before any target output exists, the run done where the Modal rule says, its control scored, and the outcome recorded with `run status` and in the handoff.
- **Not a pass:** A map with no control; a readout rule written after looking; a local run outside `python -m kit run local`; a "candidate" described anywhere public.
- **Go-ahead:** Paid compute (a budget decision), posting, uploading or submitting, and marking a run `published --announced` (only with the official announcement URL).
- **Never:** Publish, describe or commit a possible finding; run target-scroll work in this public repository; sign in to Modal from a Claude cloud session; call an ink map a reading.

## Tests

Not applicable: no test reads `SKILL.md`. The tools it calls have their own tests (`tests/test_prizes.py`, `tests/test_ledger.py` and others, run with `python -m unittest discover -s tests`), and `python -m kit.tooldocs check` checks that this page exists and names the skill's folder.

## History

- 2026-10-13: step 1 reads the top 40 lines of the one handoff, and step 5 updates its open items (`fbd5a9e`, [PR #54](https://github.com/ChaseHendrick/Scrolls/pull/54)).
- 2026-10-09: target runs move to the private repository; step 4 sends GPU and long CPU jobs to Modal through a run spec, and local jobs run under `python -m kit run local` (`3ba683f`, merged in [PR #37](https://github.com/ChaseHendrick/Scrolls/pull/37)).
- 2026-10-06: first version (`2daee8e`).

## Related

- [`docs/WORKFLOW.md`](../WORKFLOW.md): the full workflow, with section 3b on what to do with a candidate.
- [`prizes`](prizes.md), [`doctor`](doctor.md), [`plan`](plan.md): step 1 and step 3 tools.
- [`run-ledger`](run-ledger.md) and [`run-local`](run-local.md): the ledger the session records into.
- [Modal pricing](../compute/modal-pricing.md) and [Modal run specs](../compute/modal-specs/README.md): where step 4 sends GPU work.
- [`AGENTS.md`](../../AGENTS.md): the hard rules the skill applies.
