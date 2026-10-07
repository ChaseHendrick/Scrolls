---
name: scroll-session
description: >
  Start or continue Vesuvius Challenge work in this repo: check prizes, check the
  machine, plan a First Letters run, record it in the ledger. Use when the user wants
  to attempt a prize, run the pipeline, or log results. Never use it to publish,
  describe or commit a possible finding.
---

# Scroll session

Run from the repository root.

## 1. Orient

```sh
cat docs/HANDOFF.md
python -m kit prizes
python -m kit doctor
python -m kit run list
```

If the prize snapshot is older than about a month, tell the user and suggest re-checking https://scrollprize.org/prizes (or villa's `scrollprize.org/docs/34_prizes.md` and `src/data/prizeEligibility.json`) and adding a new dated snapshot.

## 2. Pick a target with the user

Read `docs/state-of-play.md`. Do not propose repeating a published null unchanged. Name the one variable the run will test.

## 3. Plan and preregister

```sh
python -m kit plan SCROLL --batch N
python -m kit run init SLUG --scroll SCROLL --question "..." --readout "..."
```

The readout rule is the user's decision. Write it before anyone looks at target output.

## 4. Run

The pipeline runs on the user's GPU machine or a rented one, not in a container without CUDA. Run the control first. Use `set -o pipefail`. Log costs with `python -m kit run cost`.

## 5. Record the outcome

- Null: `python -m kit run status SLUG null --note "..."`, then help write a report with commands, control, costs and limits.
- Possible letters: `python -m kit run status SLUG candidate --note "..."`. Stop. Do not commit, push, or describe the output anywhere public. Tell the user, point them to `docs/WORKFLOW.md` section 3b, and wait for their decision.

Never mark a run `published --announced` unless the user gives you the official announcement URL.
