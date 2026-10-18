# Guidelines for AI agents (and humans editing with AI)

Start at [`../AGENTS.md`](../AGENTS.md) (rules, standing decisions, commands, glossary; the full repository map is [`MAP.md`](MAP.md)). This file is the full rulebook.

This repository mixes **sourced research notes** about the Vesuvius Challenge with a **small tested helper package** (`kit/`) that plans and records runs of the official pipeline. Agents must keep those layers separate, and must never leak a possible discovery.

## Hard rules

1. **Never publish a candidate.** If any output might show letters, do not commit it, push it, paste it into an issue, a PR, a chat with third parties, or any public place. The prize terms forbid disclosure before the official announcement. Keep it under `work/` or `experiments/` (both gitignored) and tell the user. This repository is public.
2. **Do not claim letters.** An ink probability map is **model output**, not a reading. Only the Vesuvius Challenge papyrology team decides legibility. Never write "we found letters" or "this reads ..." in this repo.
3. **Cite real URLs** for facts about prizes, scrolls, results and people. Prefer scrollprize.org, the villa source, arXiv, and the organizers' Substack. Do not invent links. Date every prize fact.
4. **Re-check prizes before acting on them.** Amounts, deadlines and eligible scrolls change (PHerc. 1447 left First Letters on 24 Sep 2026). Update `kit/data/` with a new dated snapshot rather than editing the old one.
5. **Preregister.** Write the readout rule (`python -m kit run init`) before viewing any target output. A preregistration splits its frozen files into two sets. The readout set (data split, held-out list, labels, thresholds, metrics and scoring code, model and training configuration, controls, bars) changes only by a dated amendment. The plumbing set (container image, interpreter path, package installs, retries, logging, I/O paths) may be fixed by a dated deviation line in the run record with the new file hash, only before any map, model or score of the run exists, or when a fixed test input gives identical output before and after. `run check` still flags every changed file and names its set (2026-10-18).
6. **Control first, and the right control.** PHerc0139 w035 checks only that a pipeline runs (the model reproduces its training labels there). Generalization claims need a held-out labeled segment through the identical pipeline: PHerc0841 (in the training data of none of `ink_9um`, v8in, v8in-1447, d9v2 and Reader v2; not held out from Hecate, whose base model's committed trainer lists all three PHerc0841 segments, although Hecate's own published split rule, applied to the published masks, would keep them validation-only: [log](logs/2026-10-16-reader-exposure.md)), scored with `kit auc` and the reverse-depth control. w045 is held out from v8in only; `ink_9um` and its fine-tunes trained on its 2.4 um render ([log](logs/2026-10-08-w045-not-held-out.md)). w043 is in-sample for `ink_9um`, d9v2, Reader v2 and very likely Hecate.
7. **Prefer villa.** Use villa where it does the job. Build our own model, engine or viewer only when its tool page records a fair comparison with the villa tool it overlaps (rule 16 of AGENTS.md). General fixes go upstream as villa PRs (2026-10-18).
8. **Tools need tests.** Any change to `kit/` adds or updates a test in `tests/`.
9. **Research logs are not claims.** Dated notes go in `docs/logs/YYYY-MM-DD.md`. Do not promote log speculation into `state-of-play.md` without a source.
10. **No scroll data in Git.** No volumes, segments, surface volumes (rendered layer stacks), ink maps, checkpoints or large binaries. They are large and some carry non-commercial licenses. Release pictures and clips live under `docs/assets/`, each labeled, with a sidecar, and listed in [`assets/README.md`](assets/README.md), under the public media rule ([`media/README.md`](media/README.md), set on Chase's delegation, 18 October 2026): concept illustrations, synthetic demos, interface screenshots, and real-data stills and short clips of public scans that are not prize-eligible and show no held-out labels; at most 1920 px wide and 4 MB each (heroes 300 KB). Model output of any scroll and every real-data picture of a prize-eligible scroll stay in Scrolls-private's `docs/media/`.
11. **Plain style.** Plain sentences. Do not put U+2014 or U+2013 dashes in new text.
12. **GPU work goes to Modal.** GPU work always runs on Modal. On Chase's Mac a CPU job runs locally unless it would take over 10 minutes there (no heavy Mac jobs while he is in class); in a Claude cloud container it runs locally when it fits the container's cores and memory, finishes within about 30 minutes and adds under about 5 GB to the disk; otherwise it runs on Modal with 16 reserved cores (2026-10-18). A Claude cloud session can run Modal after `pip install 'modal[api-proxy-support]'`, Chase's sign-in and an allow rule (18 Oct 2026); an agent without Modal writes a run spec in [`compute/modal-specs/`](compute/modal-specs/README.md) and hand it to Codex, or give the user commands to run on their own computer (user decision, 2026-10-08; AGENTS.md hard rule 11). Default to a B300 (with fallbacks) and, for CPU work, 16 reserved cores; see [the defaults](compute/modal-pricing.md#default-gpu-and-cpu-for-new-jobs).

13. **Freezes end when their run is collected.** A hash freeze is live from its freezing commit until the run's evidence is collected. Then it is spent, and its preregistration or spec records that. For a live freeze, launchers and tests check the working-tree bytes. For a spent freeze, checks compare each recorded sha256 with `git show COMMIT:PATH` at the recorded commit, and the working-tree file may change; a rerun launches from `git worktree add DIR COMMIT`, and a launcher refuses a spent freeze outside a checkout at that commit. A new freeze lists the files its run executes (checked inside the container against `sys.modules`), never a whole folder such as `kit/` or an earlier version's list. Published documents (preregistrations, `docs/evidence/`, `docs/logs/`) stay byte-frozen (2026-10-18).

## Session start: repository routines

Chase moves between Claude accounts, Codex and ChatGPT during a day ("i move from claude account to claude account to chatgpt daily or even every few hours lately due to usage limits", 16 Oct 2026, 10:02 UTC; "ok yes give the repos all the necessary routines", 10:03 UTC), so recurring checks live in the repository, not in one account's scheduler. At the start of every session, whichever agent you are, run `python3 -m kit routines run --due` (add `--background` to keep working while it runs), then read `python3 -m kit routines status` and act on any row marked attention, fail or timeout. Claude Code does the first step itself through the SessionStart hook in `.claude/settings.json`, and the daily workflow `.github/workflows/routines.yml` runs the routines marked ci, with the whole test suite, on GitHub's free runners, so a failure reaches Chase by email. The routines, in [`routines.json`](routines.json) (`kit/routines.py`), only check: the live prize page against the snapshot (rule 4), the README's release list, the AutoPipeline watcher in dry run, the handoff's size and age, and the repository tests. They never post, comment, open issues, upload, push or start Modal, and their results stay in the ignored `work/routines/`. A new recurring check goes in `routines.json`, not in an account-bound scheduler.

The routine `stale` ([`kit stale`](tools/stale.md), also run by the workflow) lists what live pages still say that is no longer true: handoff rows unchanged for a week, branches a row names that are gone or merged without saying so, retired names from [`renames.json`](renames.json), dead links and `MAP.md` rows; fix what it finds in the same session, never in dated logs or evidence.

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
- When the user wants to run the pipeline: use `.claude/skills/scroll-session/SKILL.md`, print the plan, estimate its time, help them run it on their machine or, for GPU work or more than about an hour of CPU, through a Modal run spec (rule 12), and record results in the ledger. Target runs and their records belong in Scrolls-private.
- Draft villa issues and PRs for bugs hit along the way (the user submits them), following [Public writing for villa and the community](#public-writing-for-villa-and-the-community).
- Summarize published runs and prize results with links.

## Disallowed work

- Announcing, hinting at, or committing evidence of a possible finding.
- Shipping stub tools that do not do what their docs say.
- Treating an LLM's or an agent's visual judgment as a legibility verdict.
- Submitting to the Vesuvius Challenge, posting on Discord, or opening upstream PRs without the user's explicit go-ahead.

## Public writing for villa and the community

User decision, 2026-10-12. This covers anything meant for villa or the wider Vesuvius community: issues, PRs, review comments, forum-style replies and prize submissions. Agents draft it; the user posts to villa.

- **Title.** Clear and specific: name the component and what is wrong or what changes, for example "VC3D caches a chunk as empty after a 404 from S3". A reader should know what the issue is about from the title alone.
- **Terms.** Use the community's established terms (villa, VC3D, tifxyz, surface volume, segment, winding, ink detection, the official tool and flag names). Never use our internal names (growcut, arm B, autopipeline, lane letters and the like) unless the text defines them in plain words.
- **Voice.** Short, in the user's own voice, as a person writing to maintainers. Lead with what happens, how to reproduce it and what you expected. No headings or boilerplate a person would not write for a short report, and no long dashes.
- **Why.** Maintainers close issues with unclear titles, invented terminology, or text that does not read as written by the person. A closed issue costs the fix and the user's standing with the team.
- **Before handing a draft over,** reread it as a maintainer who has never seen this repository: is every term one they use, and does the title alone say what the report is about?
