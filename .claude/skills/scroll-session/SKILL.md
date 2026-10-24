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
head -40 docs/HANDOFF.md   # the one handoff: its rules and open items come first
python -m kit prizes
python -m kit doctor
python -m kit run list
```

If the prize snapshot is older than about a month, tell the user and suggest re-checking https://scrollprize.org/prizes (or villa's `scrollprize.org/docs/34_prizes.md` and `src/data/prizeEligibility.json`) and adding a new dated snapshot.

## 2. Pick a target with the user

Read `docs/state-of-play.md`. Do not propose repeating a published null unchanged. Name the one variable the run will test.

This repository is public. A target run (an eligible scroll without public labels) belongs in [Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private): do steps 3 to 5 from that checkout, so the preregistration, the ledger record and any candidate record never enter this repository, its PRs or its CI logs. Here, run only public labeled benchmarks (PHerc0841, w045, w035) and generic tools.

## 3. Plan and preregister

```sh
python -m kit plan SCROLL --batch N
python -m kit run init SLUG --scroll SCROLL --question "..." --readout "..."
```

The readout rule is the user's decision. Write it before anyone looks at target output.

## 4. Run

Estimate the job's time first (AGENTS.md hard rule 11). A job that needs a GPU, or more than about an hour of CPU, runs on Hugging Face ([Jobs](https://huggingface.co/docs/huggingface_hub/guides/jobs), ZeroGPU or the inference router) since 23 Oct 2026; there are no new paid Modal launches. Launch rules, per-run caps, the ledger and the spend guard are in Scrolls-private's AGENTS.md rule 10 (access required). Only generic, public-data jobs are described in this repository; a target-scroll job and its records go in Scrolls-private. `docs/compute/modal-specs/` and `docs/compute/modal-pricing.md` record past Modal runs.

Shorter local jobs (Mac CPU or MPS) run under `python -m kit run local SLUG -- COMMAND`, so wall time and electricity cost reach the ledger (hard rule 9). Run the control first. Use `set -o pipefail`. Log other costs with `python -m kit run cost`.

## 5. Record the outcome

- Null: `python -m kit run status SLUG null --note "..."`, then help write a report with commands, control, costs and limits.
- Possible letters: `python -m kit run status SLUG candidate --note "..."`. Stop. Do not commit, push, or describe the output anywhere public. Tell the user, point them to `docs/WORKFLOW.md` section 3b, and wait for their decision.

Either way, update the open-items table in `docs/HANDOFF.md` (AGENTS.md rule 14); private outcomes go only in Scrolls-private's handoff.

Never mark a run `published --announced` unless the user gives you the official announcement URL.
