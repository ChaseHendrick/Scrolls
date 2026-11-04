# Draft comment for ScrollPrize/villa#2370 (not posted)

Status: draft for Chase to read and post himself, or not (AGENTS.md rule 12). Nothing here has been posted. The numbers come from the back-test and controls in [the preregistration](../prereg/2026-11-04-bucket-sentinel.md) (4 November 2026, Model output).

Where: a comment on #2370, under stantheman0128's offer of a loader PR. It offers a table format and a checker to that PR, not a competing PR.

---

**Comment text:**

Thanks for the audit, it saved us a lot of debugging. I wrote a small checker that measures the same thing on its own, so it can run again whenever the `ink/` folders change, and writes a table a loader could read.

It samples the CT through each folder's tifxyz on the canvas pixel grid and phase-correlates that with slice 32 of the canvas (CT only, no labels), coarse to fine over about 25 windows, then fits dy and dx per folder as a + b*y + c*x. On Paris 4 the slopes come out near the canvas-to-grid size ratio, as you found, so a plain shift is not enough there; folders where the affine still leaves more than 2 px get a per-region grid on top.

On the folders I could check, without reading your tables, it flagged all 9 of the misaligned ones and none of the 4 you found aligned. It got (-19.20, -19.29) for the 0009b folder, and slopes of 0.00427 and -0.00388 on Paris 4 w01_r15, so it agrees with your numbers. The other Paris 4 intercepts come out near (-21, +12), and (-43, +23) for the two at scale 0.05.

Before that I checked it can fail: on 20 S3 segments rendered from their own meshes, copies with planted shifts of 4 to 300 px and canvases resampled by 0.9 to 1.1 were caught with 0.34 px median error, all within 2 px, and the unaltered renders read aligned at about +0.4 px, same as your S3 control.

The table is one JSON file, one entry per folder: the model, its coefficients, and sha256 pins of meta.json and x/y/z.tif, so a loader can refuse an entry that no longer matches the files. The reader is one file with no dependencies. If it helps your loader PR, happy for you to use the format or the numbers, or ignore it if the canvases get regenerated instead.

Code and table: https://github.com/ChaseHendrick/Scrolls/tree/main/docs/sentinel (once merged; until then the branch claude/bucket-sentinel).

---

Notes for Chase (not part of the comment):

- Terms are the thread's own: canvas, tifxyz, `full_3d`, HF65, slice 32. No internal names.
- The checker did not open every folder in the audit: some are kept closed by our held-out rules. The comment says "the folders I could check" and does not list which.
- Do not post until the PR with the table is merged; then the link above works.
