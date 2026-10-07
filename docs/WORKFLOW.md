# Experiment workflow: idea, run, null or candidate, submission

**Private work belongs in [ChaseHendrick/Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private)** (user decision, 2026-10-07). Check that repository's handoff and branches before continuing a private investigation. Keep candidate maps, private research notes and submission material there or in its ignored local data directories. The public Scrolls repository is for tools, public-data benchmarks and releasable reports. Do not copy private content into public PRs, documentation or CI logs. The local ledger examples below also apply in the private checkout.

Every experiment moves through the ledger states `planned`, `running`, then `null` or `candidate`, then `submitted` and finally `published`. The ledger enforces the order.

The private repository's `kit.repo_handoff` helper automates continuity between checkouts. Local Git hooks refresh its ignored combined context after commits, merges and checkouts; the public main/PR snapshot requires an explicit refresh. It preserves existing hooks, performs no automatic push, and never writes private context back here. Future sessions should read the private handoff for installation and refresh commands; hosted scheduled jobs are not required.

```text
planned ──> running ──> null ──────────────> published   (a null can be shared any time)
                  └──> candidate ──> submitted ──> published   (only after the official announcement)
```

## 1. Plan

```bash
python -m kit prizes                       # is the scroll still eligible today?
mkdir -p work && python -m kit plan PHerc0826 > work/pherc0826-plan.sh
python -m kit run init p0826-a --scroll PHerc0826 \
  --question "What exactly are you testing?" \
  --readout "What will count as ink, decided now, before looking" \
  --villa-commit "$(git -C "$VILLA" rev-parse HEAD)"
```

Check what others already published on the scroll ([`state-of-play.md`](state-of-play.md)). A repeat of a published null is worth less than a variation that tests one new thing (hand-refined surface, different depth window, resampling, all 14 checkpoints, a fine-tuned model).

A good readout rule names the threshold source (for example the median prediction on the control's labelled ink), a minimum size, the forward vs reverse comparison, and the row structure you expect. See [bnleft's preregistration](https://github.com/bnleft/first-light-pherc0211) for a worked example.

## 2. Run

```bash
python -m kit run status p0826-a running
set -o pipefail
# run the control, then the target, following the plan
python -m kit run cost p0826-a --usd 7.15 --what "Modal A10, 6.5 h"
```

For private runs, execute these ledger examples in the private checkout. Outputs go under its `work/` (gitignored). Record the checkpoint SHA-256, the command lines and the villa commit in the experiment folder.

## 3a. Null

```bash
python -m kit run status p0826-a null --note "0 candidates above rule; control 61"
```

Write it up: question, control, commands, failures, costs, what it does and does not show. A useful null can go public right away (`run status ... published`), as a report in `docs/logs/` or its own repository, and as a Progress Prize submission. Fix and upstream any villa bug you hit.

## 3b. Candidate

```bash
python -m kit run status p0826-a candidate --note "row-like strokes, forward only"
```

Then:

1. **Tell nobody in public.** No commit, push, tweet, Discord post, issue or PR that shows or describes it. This repository is public.
2. Re-run with a second checkpoint seed and the reverse depth direction. Check a held-out region. Make sure the region does not overlap any training data.
3. Assemble what the prize page asks for ([`prizes.md`](prizes.md)): tifxyz mesh with flattening, a programmatic image with a 1 cm scale bar and letter sizes, row annotations that do not cover letters, methodology and reproduction steps, false-positive mitigation, held-out validation.
4. Submit through the official form, or by email for the Grand Prize. Make sure you are registered on the Discord.
5. `python -m kit run status p0826-a submitted --note "form sent YYYY-MM-DD"`.

## 4. Published

Only after Vesuvius Challenge announces the result:

```bash
python -m kit run status p0826-a published --announced --note "announcement URL"
```

Then open-source the method under a permissive license, as the prize terms require.
