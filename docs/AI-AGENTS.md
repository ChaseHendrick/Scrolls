# Guidelines for AI agents (and humans editing with AI)

Start at [`../AGENTS.md`](../AGENTS.md) (map, commands, standing decisions, glossary). This file is the full rulebook.

This repository mixes **sourced research notes** about the Vesuvius Challenge with a **small tested helper package** (`kit/`) that plans and records runs of the official pipeline. Agents must keep those layers separate, and must never leak a possible discovery.

## Hard rules

1. **Never publish a candidate.** If any output might show letters, do not commit it, push it, paste it into an issue, a PR, a chat with third parties, or any public place. The prize terms forbid disclosure before the official announcement. Keep it under `work/` or `experiments/` (both gitignored) and tell the user. This repository is public.
2. **Do not claim letters.** An ink probability map is **model output**, not a reading. Only the Vesuvius Challenge papyrology team decides legibility. Never write "we found letters" or "this reads ..." in this repo.
3. **Cite real URLs** for facts about prizes, scrolls, results and people. Prefer scrollprize.org, the villa source, arXiv, and the organizers' Substack. Do not invent links. Date every prize fact.
4. **Re-check prizes before acting on them.** Amounts, deadlines and eligible scrolls change (PHerc. 1447 left First Letters on 24 Sep 2026). Update `kit/data/` with a new dated snapshot rather than editing the old one.
5. **Preregister.** Write the readout rule (`python -m kit run init`) before viewing any target output. Do not edit it afterwards; `run check` will flag it.
6. **Control first, and the right control.** PHerc0139 w035 checks only that a pipeline runs (the model reproduces its training labels there). Generalization claims need a held-out labelled segment through the identical pipeline: PHerc0841 (in no candidate's training set), scored with `kit auc` and the reverse-depth control. w045 is held out from v8in only; `ink_9um` and its fine-tunes trained on its 2.4 um render ([log](logs/2026-10-08-w045-not-held-out.md)).
7. **One engine.** villa is the engine. Do not reimplement VC3D, rendering or ink inference here. Useful general fixes go upstream as villa PRs.
8. **Tools need tests.** Any change to `kit/` adds or updates a test in `tests/`.
9. **Research logs are not claims.** Dated notes go in `docs/logs/YYYY-MM-DD.md`. Do not promote log speculation into `state-of-play.md` without a source.
10. **No scroll data in Git.** No volumes, renders, ink maps, checkpoints or large binaries. They are large and some carry non-commercial licenses.
11. **Plain style.** Plain sentences. Do not put U+2014 or U+2013 dashes in new text.
12. **GPU work goes to Modal.** A job that needs a GPU or would take more than about an hour on CPU runs on Modal. Claude's cloud sessions cannot reach Modal (their proxy does not carry its gRPC traffic), so they write a run spec in [`compute/modal-specs/`](compute/modal-specs/README.md) and hand it to Codex, or give the user commands to run on their own computer (user decision, 2026-10-08; AGENTS.md hard rule 11).

## Evidence discipline

The [Research-Integrity](https://github.com/ChaseHendrick/Research-Integrity) skill fits this repository: say how each claim is known, what each search could and could not reach, and whether each check could have failed. A First Letters readout that cannot come out negative is not a check. Install it in Claude Code with:

```
/plugin marketplace add ChaseHendrick/Research-Integrity
/plugin install research-integrity@research-integrity
```

## Quality bar

See [`QUALITY.md`](QUALITY.md) and [`NOVELTY.md`](NOVELTY.md).

## Allowed work

- Improve docs with citations.
- Extend `kit/` with tested helpers for planning, recording and checking runs.
- When the user wants to run the pipeline: use `.claude/skills/scroll-session/SKILL.md`, print the plan, help them run it on their machine or a rented GPU, and record results in the ledger.
- Draft villa issues and PRs for bugs hit along the way (the user submits them).
- Summarize published runs and prize results with links.

## Disallowed work

- Announcing, hinting at, or committing evidence of a possible finding.
- Shipping stub tools that do not do what their docs say.
- Treating an LLM's or an agent's visual judgment as a legibility verdict.
- Submitting to the Vesuvius Challenge, posting on Discord, or opening upstream PRs without the user's explicit go-ahead.
