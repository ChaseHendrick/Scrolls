# 2026-10-07: Grok lane J, title hunt (plan only, no runs)

Research notes, not claims. Labels per [`../NOVELTY.md`](../NOVELTY.md). Nothing here is a reading or a title.

## Prize rules (Sourced fact, checked 2026-10-07 10:55 ET)

- Source: [scrollprize.org/prizes](https://scrollprize.org/prizes), section "PHerc. Paris 4's Title Prize"; repo snapshot [`../prizes.md`](../prizes.md).
- Only one title prize is open: $50,000 for the title of PHerc. Paris 4 (Scroll 1), from any of its published scans including the 2.4 um ESRF volumes. Deadline 25 Jun 2027, 11:59pm Pacific; submissions stay open until won. [Form](https://forms.gle/4zeVPPBtNdSCAQa88).
- Already found: PHerc. 172 (Philodemus, *On Vices*, May 2025, [Substack](https://scrollprize.substack.com/p/60000-first-title-prize-awarded)) and PHerc. 139 (Philodemus, *On Gods* book 8, June 2026, [firstscroll](https://scrollprize.org/firstscroll)). Neither is eligible now.
- The organisers say the expected title region of Scroll 1 has shown no detectable ink so far, possibly a different ink, and its top rows are physically missing ([data browser](https://scrollprize.org/data_browser/PHercParis4)).
- Submission: tifxyz mesh with low-distortion flattening; a programmatically generated image showing the title in its spatial context, no manual annotation of characters; scan named; 1 cm scale bar and pixel and mm sizes of a few letters; image named after its mesh; methodology, reproduction (Docker suggested), false-positive mitigation, held-out validation on public ground truth; no training/prediction overlap; no public disclosure before the announcement.
- Community report: a Zenodo dataset (Tschudi, 2026-09-10) releases a 13-depth ink-reader atlas of tracing 20260701183124-w010-027, the region after the last paragraph, and reports no readable title in the reviewed places ([record via search](https://exa.ai/library/publication/lhbs9hkl0ry)). Not checked here.

## Target

PHerc. Paris 4, innermost wraps after the last body column. It is the only eligible scroll. Published scans: 7.91 um DLS (20230205180739, 20230206171837), 2.4 um ESRF (20260411134726 at 78 keV, 20260323153942 at 137 keV), 1.129 um ESRF (20260608103018); 80 published segments and a spiral-input dataset (about 49.6 GB) ([data browser](https://scrollprize.org/data_browser/PHercParis4)).

## What was possible today (Sourced fact)

- `ListMachines` at 10:50 ET: the Mac (`Chases-MacBook-Pro.local`) shows `connected: false`. No Mac command ran; `~/scrolls-work` was not inspected; no job was disturbed.
- The box cannot reach the S3 bucket (403) or Hugging Face (task brief). No data, no ink map, no candidate image exists from this lane.
- No local cost logger exists on main (`rg -i "cost.?log"` found none); `python3 -m kit cost` was used for estimates only.
- Commands run: `git worktree add -b grok/laneJ-title /workspace/Scrolls-laneJ origin/main` (at e2fd0c0); `python3 -m kit cost --gpu-hours 16 --rate 1.10` printed `$17.60`; `--rate 0.60` printed `$9.60`.

Results: none. Candidate regions: none. Letter-like shapes: none observed, because no map was made.

## Plan (Untested idea)

1. Preregister: commit the readout rule in [`../plans/2026-10-07-laneJ-title-job.json`](../plans/2026-10-07-laneJ-title-job.json) via `python -m kit run init` before any map exists.
2. Mac, when connected: `mkdir -p ~/scrolls-work/laneJ`; check `curl -sI https://vesuvius-challenge-open-data.s3.amazonaws.com/` and existing `~/scrolls-work` data; do not touch running jobs (`ps aux | grep -E "infer|v8in"` first).
3. Fetch only the innermost-wrap segment(s) of PHercParis4 past the last column (the w010-027 tracing region first), 7.91 um surface volume, with `kit fetch` style resumable anonymous reads.
4. Run `ink_9um` seeds 42 and 43, forward and reverse, plus `kit shuffle` control, on MPS (`scripts/mac-w045.sh` pattern). Pipeline check on PHerc0139 w035, generalization check on held-out w045.
5. Title signature search, scored by the preregistered rule only (take letter-size and layout priors from `docs/research/title-priors.json` on branch `grok/research-titles` once it lands; not on the remote at 10:54 ET; its author/title strings are search priors only, never a claimed title): an isolated short block (at most 4 rows) of components larger than body letters, extra letter spacing, at least 10 mm blank before it, optional coronis or paragraphos-like mark. Also scan depth offsets (the Tschudi atlas suggests the ink may sit off the traced surface).
6. If 9 um shows nothing, plan step 7 on the 2.4 um volume (the organisers report ink directly visible in it for body text), which needs the cloud spec.
7. Cloud spec: [`../plans/2026-10-07-laneJ-title-job.json`](../plans/2026-10-07-laneJ-title-job.json), about 16 GPU hours, estimated $9.60 to $17.60, proposed cap $25. Not launched; needs the owner's budget decision.

## Image policy

Candidate images, if any are ever made, stay in `~/scrolls-work/laneJ` on the Mac. The repo's hard rule 1 and the prize's no-disclosure term forbid committing them to this public repository, so this PR contains no previews.

Assisted-by: Grok Bot
