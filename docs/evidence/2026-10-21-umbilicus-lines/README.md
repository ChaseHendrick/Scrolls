# Scroll center lines from the center finder (release `umbilicus-lines-v1`)

Center lines (umbilicus lines) for 11 scrolls that have no center line in the open-data bucket, made by this repository's scroll center finder ([guide](../../../scripts/umbilicus/README.md), weights release `umbilicus-v1`) and put through an automatic end check, with the status of every line end. **They are model output. No person has checked any of these lines or any of their ends on CT.** Some checks were made by AI agents looking at CT views; those are reported as agent looks and are not a human check.

The line files are not in git. They are the assets of the GitHub release [`umbilicus-lines-v1`](https://github.com/ChaseHendrick/Scrolls/releases/tag/umbilicus-lines-v1) of this repository, each at `https://github.com/ChaseHendrick/Scrolls/releases/download/umbilicus-lines-v1/<file>`. This folder holds this README, `status.json` (the per-end status, no coordinates) and `SHA256SUMS` of the release's files.

Labels follow [`docs/NOVELTY.md`](../../NOVELTY.md): Sourced fact, Model output, Interpretation.

## Quick start

```sh
U=https://github.com/ChaseHendrick/Scrolls/releases/download/umbilicus-lines-v1
mkdir -p work/umbilicus/lines && cd work/umbilicus/lines
curl -fLO $U/SHA256SUMS
for f in $(awk '{print $2}' SHA256SUMS); do curl -fLO $U/$f; done
sha256sum -c SHA256SUMS            # shasum -a 256 -c SHA256SUMS on macOS
# VC3D and spiral-fitting look for the name umbilicus.json:
mkdir -p PHerc0306B && cp PHerc0306B_20250521133212_umbilicus.json PHerc0306B/umbilicus.json
```

Then read `metadata.z_valid` and `metadata.usable_ends` of the file before you rely on it (next section).

## What a file holds

Each file is in the published umbilicus format that `predict.py` writes ([guide](../../../scripts/umbilicus/README.md#use-it-in-vc3d-and-spiral-fitting)): `control_points`, one per height, `x`, `y`, `z` in level-0 voxels of the scan named in `metadata.volume`, and `metadata` with `volume_width`, `volume_height` and `volume_slices` (the scan's level-0 grid, read from its `.zarray` on 21 October 2026), so VC3D can place the line at any pyramid level. Files are named `<scroll>_<scan id>_umbilicus.json`; copy one to `umbilicus.json` for VC3D or spiral-fitting.

The end check adds these metadata keys (all ends in the file's own z order):

| Key | Meaning |
| --- | --- |
| `z_valid` | The checked height range. Use the line only between these heights. |
| `papyrus_ends` | Where the papyrus round the center ends, as the end check found it (own-scan files) |
| `usable_ends` | `true` at an end only when coverage and support pass there, no check raises a flag there, and the mount there was seen or checked clear. Skip every other end. |
| `caps_verdict`, `void_checks`, `flags_low`, `flags_high`, `caps_status` | The end check's verdict per line (PASS, FLAG or VOID), the checks that could not be judged, the flags per end and the status of each check per end |
| `mount`, `ct_look` | Whether the mount past each end was seen (`seen`), or what the agent CT look past the end found (`not clear: papyrus`, `not clear: masked`); `unchecked` where none was made |
| `human_check` | `none` at every end: no person has looked |
| `extension`, `extension_left_out` | Points added past an end by a short fit (at most 5 mm), and the ends where they were left out because the mount there was not seen |
| `mapped_from` | For a file in another scan of the same scroll: the scan the line was made on, the catalog's affine that carried it over and the check that the affine is close to a similarity at the voxels' size ratio |
| `z_valid_mapped`, `z_valid_clipped`, `z_valid_note` | For a mapped file whose scan holds only part of the scroll's height: the unclipped range and the ends cut to the scan |

A point with `"source": "cap"` repeats the end point one step past it, so VC3D (which holds a line's end points) and spiral-fitting (which extends its last segment) read the same center there. Files whose extensions were left out have no cap points on their own scan, so past `z_valid` the two readers differ; stay inside `z_valid`.

## How the lines were made (Sourced fact, from our run records)

- **Eight scrolls on their 1.2 m scans** (PHerc0175A, 0175B, 0306B, 0483A, 0483B, 0490A, 0490B, 0846B): the finder's training run of 13 October 2026 predicted them with the released weights: the median of the 9 released first-stage models, refined by the median of the 5 released zoom models, then smoothed along z and trimmed at the mount and cap. `spread_mm_median` (0.09 to 0.41 mm) is how far the 5 zoom models disagree; agreement is not accuracy.
- **PHerc0814 and PHerc0841** (1.2 m scans) and **PHerc0172** (7.91 um scan, read at level 3): `predict.py` with `umbilicus-first-all.pt` and `umbilicus-zoom-all.pt` and both end trims, on 18 October 2026.
- **The end check** ran on every line on 18 October 2026, under rules fixed before the run: it found where the papyrus round the center ends, cut points lying in air past it, added at most 5 mm past an end by a robust fit where the support allowed, and judged each end. The rules and their code are not yet in this repository; this README states what each check means.
- **Mapped files**: the end check's last step carried PHerc0814's line into its 2.399 um scan `20260309142202` and PHerc0841's into its 2.403 um scan `20260319124803` with the open-data catalog's affines, left the extensions out (their mounts were not seen) and clipped `z_valid` to the target scan. `20260319124803` holds only part of PHerc0841's height: 60 of the 258 points lie inside its slices, and `z_valid` is 0 to 15,120.

## The checks at each end

- **Coverage**: the line reaches the papyrus end (within 3 mm) and does not run past it into the mount or air (`short`, `overrun`).
- **Support**: papyrus surrounds the center at the line's last heights (`unsupported`).
- **Tilt**: the last 5 mm do not swing sideways more than twice the line's own middle (`tilt`). Where a planted sweep (a 2 mm per mm ramp) is not caught against the line's bar, the tilt check is VOID at that end: it could not be judged. By the rule fixed before the run, a VOID tilt without a flag does not by itself make an end unusable, so those ends rest on coverage and support alone.
- **Band**: compares the end with a reference line; these scrolls have none, so it is not judged.
- **Mount**: the rule counts the mounts of the eight 1.2 m scans of the first group as seen, from CT sheets (6 to 8 slices per scroll, drawn 14 October 2026) that showed thin mount strips. **Those sheets were looked at by Claude agents, not by a person.** On the other scans each end waited for a CT look past the papyrus end.
- **Controls** (Model output): every check has a planted fault that must be caught on that scan (the CT set to air over the last 10 mm, a hollow round the last 3 mm, the line cut short, the line held into the mount, the sweep). Coverage and support caught theirs on every line here.
- **Known limit** (Interpretation, from a synthetic test): a solid mount that fills 30 % or more of the median papyrus area counts as papyrus, and no control catches it.

**Agent CT looks** (PHerc0814, 0841 and 0172, 18 October 2026; Model output of agent looks, not a human check): three independent Claude agents looked at CT views past each papyrus end (a careful reader, a papyrus hunter and a mount and mask reader), combined by a rule fixed before any answer was seen: an end is clear only when all three report air and two adversarial checkers both fail to refute it, else the most conservative word. All six ends read `not clear: papyrus`, so none of them is usable. Interpretation: the 1.2 m scans end on a slant, with papyrus still present a few millimeters off the line where the line itself meets mask or air.

## Status per line (Model output)

All 12 ends marked usable are on the eight 1.2 m scrolls of the first group. 12 of 22 ends of the 11 lines are usable; none of the mapped files has a usable end.

| Scroll | Scan | File frame | Points | `z_valid` (level-0 slices) | Verdict | Low end | High end |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| PHerc0175A | `20250521115057` 8.64 um | own scan | 146 | 1,824 to 10,976 (79.1 mm) | FLAG | not usable: tilt flag | usable |
| PHerc0175B | `20250521125822` 8.64 um | own scan | 200 | 1,376 to 13,984 (108.9 mm) | VOID | usable (tilt VOID) | usable (tilt VOID) |
| PHerc0306B | `20250521133212` 8.64 um | own scan | 189 | 2,016 to 13,920 (102.9 mm) | PASS | usable | usable |
| PHerc0483A | `20250521140913` 8.64 um | own scan | 196 | 1,248 to 13,600 (106.7 mm) | VOID | usable (tilt VOID) | usable (tilt VOID; stops 0.55 mm short of the papyrus end) |
| PHerc0483B | `20251124083638` 8.64 um | own scan | 150 | 1,824 to 11,232 (81.3 mm) | VOID | usable (tilt VOID) | usable (tilt VOID) |
| PHerc0490A | `20250521151210` 8.64 um | own scan | 125 | 1,888 to 9,696 (67.5 mm) | FLAG | usable (tilt VOID) | not usable: `short`, 5.53 mm from the papyrus end |
| PHerc0490B | `20250521151215` 8.64 um | own scan | 117 | 1,760 to 9,056 (63.0 mm) | VOID | usable (tilt VOID) | usable (tilt VOID) |
| PHerc0846B | `20250804142305` 9.362 um | own scan | 178 | 1,312 to 12,512 (104.9 mm) | FLAG | not usable: tilt flag | not usable: tilt flag |
| PHerc0814 | `20250804134230` 9.362 um | own scan | 262 | 1,760 to 18,464 (156.4 mm) | VOID | not usable: agent look, papyrus past the end (tilt VOID) | not usable: the same |
| PHerc0841 | `20250821151531` 9.366 um | own scan | 258 | 1,632 to 18,080 (154.1 mm) | PASS | not usable: agent look, papyrus past the end | not usable: the same; its 3.0 mm extension left out |
| PHerc0172 | `20241024131838` 7.91 um | own scan | 307 | 544 to 20,128 (154.9 mm) | VOID | not usable: agent look, papyrus past the end (tilt VOID) | not usable: the same |
| PHerc0814 | `20260309142202` 2.399 um | mapped | 264 | 6,004 to 71,021 | VOID | not usable | not usable |
| PHerc0841 | `20260319124803` 2.403 um | mapped, partial scan | 258 | 0 to 15,120 (clipped) | PASS | not usable | not usable |

"Usable" is the end check's word, not a person's. Where a usable end says "tilt VOID", only coverage and support were judged there.

**What the agent looks at the 14 October sheets suggest** (Model output of agent looks, not a human check; the sheets showed the lines before the end check, which changed points only at the ends): where a core was visible in the middle slices of PHerc0175A, 0175B, 0306B and 0490A, the line sat on it or within about 1 mm. PHerc0483A, 0483B, 0490B and 0846B looked crushed, with no visible spiral in most slices, so single slices can neither confirm nor rule out their lines.

**How accurate to expect** (Model output and Interpretation). On the 13 published center lines, each scroll held out of its own models' training, the finder's median distance was 0.73 mm and its 90th percentile 3.37 mm ([guide](../../../scripts/umbilicus/README.md#held-out-results)). These 11 scrolls have no published line to score against, so their accuracy is not measured. Crushed scrolls may be worse than the published ones, which the finder trained on.

## Scrolls not in this release

- Scrolls whose lines are kept for a test that has not run yet, and the scans held for it.
- Lines on PHerc0332 and PHerc1667 made on their 7.91 um scans, which are under the EduceLab Data License: it does not allow redistributing the data without approval.
- PHerc0846A: its line is still being improved and comes in a later version.
- PHerc0814's copy in its 1.129 um scan `20260521123630`: 6 of its points inside `z_valid` lie outside that partial scan's x and y range.
- The 13 scrolls with published center lines: use the published lines.

## Licenses, credits and citation

- **These line files**: CC BY-NC 4.0. They are derived from CT scans released under CC BY-NC 4.0 and made with weights released under CC BY-NC 4.0 ([`umbilicus-v1`](https://github.com/ChaseHendrick/Scrolls/releases/tag/umbilicus-v1)).
- **Code** (`scripts/umbilicus/`): Apache-2.0, like the rest of this repository.
- **CT scans**: Vesuvius Challenge open data, "CC-BY-NC 4.0 (unless otherwise noted for specific assets)" ([scrollprize.org/data](https://scrollprize.org/data), read 21 October 2026, Sourced fact); the open-data catalog lists CC BY-NC 4.0 for every scan named in this release (`metadata.json`, read 21 October 2026, Sourced fact). The scans are read from the bucket, not copied here. Cite them as the data page asks for scans released directly by Vesuvius Challenge: Giorgio Angelotti, Stephen Parsons, Sean Johnson, Elian Rafael Dal Prà, Johannes Rudolph, Paul Tafforeau, Alessandro Mirone, Paul Henderson, Hendrik Schilling, Forrest McDonald, David Josey, Youssef Nader, C. Seth Parker, W. Brent Seales. *Vesuvius Challenge - CT Scans of Herculaneum Papyri*. Vesuvius Challenge.
- **No published line**: on 21 October 2026 the open-data bucket held no file under `<scroll>/representations/umbilicus/` for any of the 11 scrolls here (our listing, Sourced fact).

## Files

`status.json` lists every file of the release with its scroll, scan, frame, licence, point count, `z_valid`, verdict and, per end, each check's status, the flags, the mount, the agent CT look, `human_check` and `usable`. `SHA256SUMS` covers every file of the release but this README (`sha256sum -c SHA256SUMS` in a folder holding them).
