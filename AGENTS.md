# AGENTS.md

Entry point for AI agents (and people) working in this repository. Read this file first, then the files in "Read first". Rules here bind every agent; the full rulebook is [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md).

## What this repository is

A workbench for the [Vesuvius Challenge](https://scrollprize.org/): reading carbonized Herculaneum scrolls from X-ray CT. It does not reimplement the official pipeline ([ScrollPrize/villa](https://github.com/ScrollPrize/villa)); it plans runs of it, scores ink maps against published labels, checks results across devices, records provenance, and keeps dated research notes. Owner: Chase Hendrick (GitHub ChaseHendrick). Machine: Apple M1 Pro (MPS GPU, no CUDA).

## Public and private work

**[ChaseHendrick/Scrolls-private](https://github.com/ChaseHendrick/Scrolls-private) is the home for all work that cannot be public** (user decision, 2026-10-07). Read its handoff and relevant branches before starting or continuing a private investigation. Keep candidate outputs, private research notes and submission material there or in its ignored local data directories. This public repository holds tools, public-data benchmarks and material cleared for public release. Never copy private findings into public commits, PRs, CI logs or documentation.

## Read first, in this order

When the private checkout is available, refresh the combined session context from that checkout with `python3 -m kit.repo_handoff context --private-root . --public-root ../Scrolls`. Its handoff helper installs local Git hooks in both checkouts and writes combined context only inside the private workspace. Hooks do not push, run hosted jobs or copy private notes into this repository. Read the generated private context before private work; never paste it into public artifacts.

Many files here are long: read the top of each and search the rest.

1. [`docs/HANDOFF.md`](docs/HANDOFF.md): **the one handoff**, open items first, then recent dated sections, newest first (rule 14). Older sections are in [`docs/HANDOFF-archive.md`](docs/HANDOFF-archive.md); search it, do not read it whole.
2. [`docs/README.md`](docs/README.md): the docs index, one home per topic. Check it before any research or writing (rule 13).
3. [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md): the rulebook.
4. [`docs/MAP.md`](docs/MAP.md): the repository map, one row per module and script. Search it for a tool or a path.

Released tools are listed in the README's ["Released tools"](README.md#released-tools) section, including [Unroll](https://huggingface.co/spaces/SharpMeow/unroll), the interactive 3D viewer released as a Hugging Face Space (v1.0.0, Apache 2.0 code; guide: [`docs/unroll-space.md`](docs/unroll-space.md)).

Terms used in the code and docs are defined, A to Z, in [`GLOSSARY.md`](GLOSSARY.md). Add a term there when you introduce one.

Open these when the task needs them:

- [`docs/plans/roadmap.md`](docs/plans/roadmap.md): pointer to the roadmap, which now lives in Scrolls-private (access required). Gate A's public rule is in `kit/gate.py`.
- [`docs/results.json`](docs/results.json): every benchmark number with its settings and source. It is over 200 KB, so print only the part you need; `python3 -c "import json; print(list(json.load(open('docs/results.json'))))"` lists its sections.
  The README section "Novel findings" lists only results not published elsewhere; reproductions stay in results.json and the logs. Keep both in step when numbers change.
- [`docs/logs/`](docs/logs/): dated research notes; open the one a handoff row or the docs index names, and the newest for the latest numbers.
  Literature (arXiv, journals, Zenodo, Kaggle): [`docs/logs/2026-10-07-literature.md`](docs/logs/2026-10-07-literature.md) and machine-readable [`docs/papers.json`](docs/papers.json).

## Hard rules (short form)

1. **Never publish or describe a possible finding.** Target-scroll maps, triage lists and verdicts belong in Scrolls-private or its ignored local data directories. The prize terms forbid disclosure before the official announcement. This repository is public.
2. **An ink map is model output, not a reading.** Never write that letters were found or read.
3. **Preregister before looking.** Readout rules are fixed (`python -m kit run init`, or a committed file in `docs/prereg/`) before any target map exists.
4. **Every check must be able to fail.** Device agreement needs a control (`kit verify --control`); AUC needs the reverse-depth map as control.
5. **Cite real URLs and dates** for facts about prizes, people and published results. Label claims: Sourced fact, Community report, Model output, Interpretation, Untested idea ([`docs/NOVELTY.md`](docs/NOVELTY.md)).
6. **No scroll data, maps or weights in git.**
7. **`kit/` changes need tests** in `tests/`.
8. **Nothing outward without the user's go-ahead:** no posting, submitting, renting compute or opening upstream PRs. Forum posts, Hugging Face uploads and Spaces are allowed, each only after the user says yes to that post, and never with private work or target-scroll data (user decision, 2026-10-13; it lifts the 2026-10-07 ban).
9. **Log local compute.** Wrap every local run (Mac CPU or MPS) with `python -m kit run local SLUG -- COMMAND` so wall time and electricity cost reach the ledger ([`docs/compute.md`](docs/compute.md)).
10. **Style:** plain sentences; never U+2014 or U+2013 dashes; commit messages end with the session's attribution lines.
11. **GPU work goes to Modal, not hours of CPU** (user decision, 2026-10-08). Before starting any job, estimate its time. A job that needs a GPU, or more than about an hour on CPU, runs on Modal. Claude's cloud sessions cannot reach Modal, even with the CLI installed, because their proxy does not carry Modal's gRPC traffic, so never try to sign in to Modal from one. Write an exact run spec in [`docs/compute/modal-specs/`](docs/compute/modal-specs/README.md) and give the user a short prompt to paste into an agent that runs Modal, such as Codex, or commands to run on their own computer. Default machine (user decision, 2026-10-12): B300 with fallbacks, `gpu=["B300", "B200", "H200", "H100"]` (B300 needs a CUDA 13.1 or newer image; a CUDA 12 image drops B300 from the list), and for CPU work 16 reserved cores, `cpu=(16, 16)`, with threads set to match, unless a measurement shows the job scales differently; never past the approved budget without asking with a cost estimate. The workspace is on Modal's Starter plan (checked 2026-10-13): at most 10 GPUs and 100 containers at once, counting every live job, so no spec fans out wider; logs are kept 1 day, so anything a check needs goes to a Volume or is copied within a day; never pin a region (1.15 to 1.75 times base prices) or ask for non-preemptible containers (3 times), and price estimates at the plain preemptible rates ([plan limits](docs/compute/modal-pricing.md#2-plans-credits-limits-and-budgets)). Costs, rates and the [defaults](docs/compute/modal-pricing.md#default-gpu-and-cpu-for-new-jobs): [`docs/compute/modal-pricing.md`](docs/compute/modal-pricing.md). Only generic, public-data jobs get a spec here; anything about a target scroll belongs in Scrolls-private's own `docs/compute/modal-specs/`.
12. **Public writing for villa and the community** (user decision, 2026-10-12). Issues, PRs, comments and prize submissions get a clear, specific title that says what is wrong or what changes. Use the community's established villa and VC3D terms; never our internal names (growcut, arm B, autopipeline and the like) unless the text defines them. Keep it short, in the user's own voice, with no long dashes. Maintainers close issues with unclear titles, invented terms, or text that does not read as written by the person. Agents draft; the user posts to villa. Guide: [`docs/AI-AGENTS.md`](docs/AI-AGENTS.md#public-writing-for-villa-and-the-community).
13. **Check the docs index before you research or write** (user decision, 2026-10-13). [`docs/README.md`](docs/README.md) names one home per topic. Read the home and grep `docs/` first; extend the existing note instead of starting a new one, and add any new note to the index. Do not repeat research that is already written down.
14. **One handoff** (user decision, 2026-10-13). [`docs/HANDOFF.md`](docs/HANDOFF.md) is the only handoff for this repository and every agent: update its open-items table when you start or finish something, link longer notes from their row, and merge the handoff change into `main` at once. Private work hands off only in Scrolls-private's `docs/HANDOFF.md`.
15. **Releases list themselves in the README** (user decision, 2026-10-14). Whatever is released from Scrolls-private into this repository adds its entry to [`docs/releases.json`](docs/releases.json) in the same change, with `python -m kit releases add ENTRY.json`, which rewrites the README's "Released tools" section from that list. Each tool has one entry: a new version or fix of a released tool replaces that tool's entry, under the same id and title, instead of adding another (user decision, 2026-10-14). AutoPipeline is pinned to the top of the section (`python -m kit releases pin`), so new releases go below it until Chase says to unpin it (user decision, 2026-10-14). Never edit the section by hand: `python -m kit releases check`, run by the tests, fails when it and the list disagree. The entry is part of the file list the user approves. For a Progress Prize package, the private exporter writes the entry itself and pushes it as a `release-readme/<submission_id>` branch for a PR into `main`.

## Standing user decisions

| Date | Decision |
| --- | --- |
| 2026-10-07 | Private operational plans and submission material live in Scrolls-private |
| 2026-10-07 | Leave `docs/contrib/villa-1865-m1pro-comment.md` alone |
| 2026-10-07 | No Hugging Face or forum posting (lifted on 2026-10-13) |
| 2026-10-07 | No paid compute without the user's budget decision |
| 2026-10-08 | Use Modal for any job that needs a GPU or hours of CPU. Claude cloud sessions cannot reach Modal: write a run spec and hand it to Codex, or give the user commands for their computer (rule 11) |
| 2026-10-12 | Default Modal GPU is B300, falling back to the fastest card free; CPU jobs reserve more cores (16 by default) because Modal offers no faster CPU model. Speed over saving money, inside the approved budget (rule 11) |
| 2026-10-13 | Modal runs fit the Starter plan: at most 10 GPUs and 100 containers at once, 1 day of logs, no region selection and no non-preemptible containers (rule 11) |
| 2026-10-12 | Public writing for villa and the community: clear, specific titles, the community's established terms, short, in the user's own voice, no long dashes; the user posts to villa (rule 12) |
| 2026-10-13 | Hugging Face uploads, model cards and Spaces are allowed, each with the user's go-ahead like any outward action; forum posts were also lifted later the same day (next row), and hard rule 1 still applies: nothing private and no target-scroll data goes to Hugging Face |
| 2026-10-13 | The forum ban is lifted too ("lift the ban. we can post.. just ask before doing so", 01:41 UTC): forum, Discord and Hugging Face posts are allowed, but an agent drafts and asks the user before each post. For now the user does not want to post in forums (01:41 UTC), so do not draft or suggest forum posts until he asks. Hard rule 1 still applies: nothing private and no target-scroll data |
| 2026-10-13 | Call the owner Chase (Chase Hendrick) in docs, commits, PRs and messages. His account may still show the name Bob; never use it |
| 2026-10-14 | The README updates itself when something is released from private to public: each release adds its entry to `docs/releases.json`, and the README's "Released tools" section is generated from that list (rule 15) |
| 2026-10-14 | One entry per tool under "Released tools" ("we dont need multiple things for each tool", "make it one autopipeline thing", Chase, 12:42 UTC): a fix release updates its tool's entry, under the same id and title, and that entry describes the latest version (rule 15) |
| 2026-10-14 | Keep AutoPipeline the top released tool on the public README ("keep autopipeline the top newly released tool on my public scrolls repo so people see it. at least for a bit", Chase, 23:44 UTC): it is pinned in `docs/releases.json`, so later releases are listed below it; unpin it (`python -m kit releases unpin autopipeline`) only when Chase says (rule 15) |
| 2026-10-14 | AutoPipeline's short name is AP, not APL ("we should change the acronym from APL to AP", "since ya know, its Pipeline", Chase, 01:57 UTC). Define it once per document as "AutoPipeline (AP)". In text for villa and the community write AutoPipeline in full, because AP there usually means average precision. Files already published or approved, such as the released copy at `faada83` and its approved file lists, keep APL; the next fix release, under a new submission id, carries AP |
| 2026-10-14 | No stranger's GitHub account among public Scrolls' contributors ("remove them", Chase, 12:48 UTC, about github.com/noreply). GitHub credits a commit to the account that owns its author email, and `LOGIN@users.noreply.github.com` belongs to the account LOGIN: the exporter's old `noreply@users.noreply.github.com` made github.com/noreply a contributor. A tool that sets its own commit identity for public Scrolls uses Chase's `326338179+ChaseHendrick@users.noreply.github.com`; never make up an address at `users.noreply.github.com`. Removing an account already listed means rewriting public `main`, which waits on Chase's yes |
| 2026-10-14 | No new AI accounts among public Scrolls' contributors ("ya remove grok bot and codex too as contributors", "i dont like seeing that", Chase, 13:11 UTC). Codex, Grok and any other agent that commits to public Scrolls sets author and committer to `Chase Hendrick <326338179+ChaseHendrick@users.noreply.github.com>`, never `grok-bot@users.noreply.github.com`, `codex@openai.com` or another address GitHub links to an account. Chase chose not to rewrite their older commits (13:19 UTC), so Grok-Bot and codex stay listed for those. Claude is covered too ("yes", Chase, 13:31 UTC): before committing in a public Scrolls checkout, run `git config user.name "Chase Hendrick"` and `git config user.email 326338179+ChaseHendrick@users.noreply.github.com`, since the default `Claude <noreply@anthropic.com>` is credited to the account github.com/claude |

## Repository map

The full map, one row per module and script, is [`docs/MAP.md`](docs/MAP.md); search it for a tool or a path. The top level:

| Path | What it is |
| --- | --- |
| `kit/` | The `python -m kit` package: standard library only, except numpy, tifffile and zarr for the map tools; every subcommand is in `kit/cli.py` |
| `scripts/` | Mac GPU scripts (bash 3.2), the letter reader's training and benchmarks, the scroll centre finder (`scripts/umbilicus/`), and `scripts/experiments/`: saved records of past public-data jobs, keep their wording |
| `docs/` | Docs, indexed by [`docs/README.md`](docs/README.md): the handoff, benchmark numbers (`docs/results.json`), dated logs, Modal pricing and specs, and frozen evidence archives with hashes in `docs/evidence/` (do not edit) |
| `tests/` | `python -m unittest discover -s tests`; `tests/test_repo.py` checks the repository itself |
| `experiments/`, `templates/` | The local experiment ledger (gitignored except its README) and its record template |

## Commands

```bash
python -m unittest discover -s tests -v        # all tests; map tests skip without their numerical dependencies
python -m kit prizes                            # open prizes from the snapshot
python -m kit run all --dry-run --refresh        # AutoPipeline over every open-data bucket volume: priced plan, launches nothing
python -m kit run watch --exit-code             # scheduled: queue new or changed bucket volumes, priced (exit 3 if any)
python -m kit auc MAP.tif --control MAP_reverse.tif --labels L/inklabels.zarr --mask L/supervision.zarr \
    [--crop Y0 Y1 X0 X1 --surface-shape H W] [--inner 64] [--json]
python -m kit provenance write OUT.json --run NAME --model M --input I --output O
python -m kit provenance check OUT.json --files
bash -n scripts/*.sh                            # syntax check; scripts must stay bash 3.2 compatible (macOS)
```

Testing the Mac scripts off a Mac: `SMOKE=1 EXPECT_GPU=cpu WORK=<scratch dir> bash scripts/mac-w045.sh` (a 256 px window on CPU). Never edit a script in place while a run of it is going: bash reads scripts as it runs; replace files atomically.

## Glossary

| Term | Meaning here |
| --- | --- |
| `ink_9um` | The team's released 9 µm ink model (`scrollprize/ink_9um`), seeds 42 and 43 at step 75,000 |
| v8in | Youssef Nader's ResNet3D-50 ink model (`YoussefMoNader/ink-8um-v8in`, 2026-09-28); `v8in-1447` is its PHerc1447 fine-tune |
| d9v2, Reader v2 | Community fine-tunes of `ink_9um` (TAUIL-Abd-Elilah; Domenico Russo); drop-in `ink_9um` checkpoints |
| w035 | PHerc0139 training segment: a pipeline check only (the model reproduces its own labels there) |
| w045 | PHerc0139 segment unseen by v8in but not held out from `ink_9um`, which trained on its 2.4 um render (pherc0139-w029); d9v2 and Reader v2 inherit that, and Reader v2 also trained on it; so did Hecate and its base model ([log](docs/logs/2026-10-08-w045-not-held-out.md), [exposure log](docs/logs/2026-10-16-reader-exposure.md)) |
| PHerc0841 | Scroll with labelled segments w00, ag896, ag405, in the training data of none of `ink_9um`, v8in, v8in-1447, d9v2 and Reader v2: the fair generalization test for them. Not held out from Hecate: its base model's committed trainer lists all three segments, although Hecate's own published split rule, applied to the published masks, would keep PHerc0841 validation-only ([log](docs/logs/2026-10-16-reader-exposure.md), `held_out` in [results.json](docs/results.json)) |
| AUC | Probability a labelled ink pixel scores above a labelled background pixel, inside the supervision mask |
| As stored / reversed | Depth order of the surface volume; reversed is the control and should sit near or below 0.5 |
| Crop, `--inner 64` | The 640 px window of densest labelled ink per segment; 64 px edge left out so bare-crop and full-map scores match |
| QUICK | `mac-w045.sh` mode that scores everything on the crop only |
| Atlas | rodriguescarson's renders of 340 automatic meshes on eligible scrolls |
| Provenance digest | SHA-256 over a run's record; publishable alone as a timestamped commitment |
