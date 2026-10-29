# The public media rule

What pictures, GIFs and clips public Scrolls may hold, and how the rule is checked. The files themselves live in [`docs/assets/`](../assets/README.md), each with a row there and a sidecar JSON; this folder holds the rule and charts drawn from published numbers, which are SVG drawings and not pictures under the rule (below), each with a sidecar JSON: [`greek-restoration-by-gap-length.svg`](greek-restoration-by-gap-length.svg) ([sidecar](greek-restoration-by-gap-length.json)), made by `python -m kit.greekfill chart` from the Greek gap restoration benchmark's frozen `score.json`; [`windlabel-box-heldout.svg`](windlabel-box-heldout.svg) ([sidecar](windlabel-box-heldout.json)), made by `scripts/media/windings_chart.py` from windlabel-box's frozen test numbers. Scrolls-private's own `docs/media/` keeps the real-data media that stay private.

## Where the rule comes from

On 18 October 2026 Chase left this decision to the agents. The coordinating agent set the rule below under that delegation the same day. Hard rule 6's short form in AGENTS.md ("No scroll data, maps or weights in git") is unchanged: a still or a short clip made to show what a released tool looks like is an illustration, not scroll data, and volumes, segments, surface volumes, ink maps and weights stay out of Git as before. Its full form, rule 10 of [the rulebook](../AI-AGENTS.md), did change the same day: it banned all renders and kept scan pixels out of `docs/assets/`, and it now bans surface volumes (rendered layer stacks) but allows the stills and clips this rule allows. Chase can change or withdraw the rule at any time; record that here and in the AGENTS.md row.

## The rule

Public Scrolls' Git may hold:

1. **Concept illustrations, synthetic demos and interface-only screenshots, always.** Procedural or generated art, tools running on made-up data, and screenshots of an interface that shows no scan pixels.
2. **Real data renders of public scans that are not prize-eligible.** Illustrative stills, GIFs and short videos rendered from the Vesuvius Challenge open-data CT of a scroll that is on none of the prize lists (below), and that draw no held-out labels: none of PHerc1447's labels and none of PHerc0841 ag405's. PHerc0841's other labels (w00, ag896) and PHerc0139's are not held out here.

Every file under `docs/assets/`, of any label, is at most **1920 px wide** and at most **4 MB** (4,000,000 bytes), and is described by a **sidecar** JSON beside it. A Real data render's sidecar names:

| Field | What it holds |
| --- | --- |
| `data.scan` | The scroll, such as `PHerc0139` or `PHerc0172` |
| `data.voxel_size` | The scan's voxel size, such as `2.399 um` |
| `data.labels` | `none`, or the published labels drawn on it |
| `data.credit` | Exactly `Vesuvius Challenge open data, CC BY-NC 4.0`, repeated in the caption. The older credit `Data: Vesuvius Challenge, CC BY-NC 4.0`, which Scrolls-private's media scripts and sidecars still write, fails here: re-make such a render with these scripts, or update its sidecar and caption, before it moves to public |
| `data.segment`, `data.volume` | The segment and the volume id, when they apply |
| `license` | `CC BY-NC 4.0`, the license of the scan data |
| `command`, `tool.scripts`, `tool.base_commit` | The command, the scripts and the commit that made it (`scripts/media/common.py` `write_sidecar()` fills the last two) |

Public Scrolls never holds:

- **Model output of any scroll**: ink maps, StrokeNet or reader output, scores drawn on a scroll, or any model's map of real data, whatever the scroll. These stay in Scrolls-private's `docs/media/`.
- **Any real-data media of a prize-eligible scroll**: CT slices, surface renders or orbits of a scroll on the Grand Prize or First Letters lists, or of PHerc. Paris 4 (Scroll 1), the title prize's scroll. These stay in Scrolls-private's `docs/media/`.
- **Volumes, segments, surface volumes or weights** (hard rule 6, unchanged).

Hard rule 1 still applies on top: no picture describes or hints at a possible finding, and no caption calls an ink map a reading.

## The prize-eligible scrolls

Sourced fact: on https://scrollprize.org/prizes, read 18 October 2026, the Grand Prize lists 13 volumes (PHerc0125, 0191, 0211, 0257, 0268, 0358, 0800, 0813, 0826, 1203, 1218, 1447 and 1545), First Letters lists 21 (PHerc0125, 0175A, 0175B, 0191, 0211, 0257, 0268, 0306B, 0358, 0483A, 0483B, 0490A, 0490B, 0800, 0813, 0826, 0846A, 0846B, 1203, 1218 and 1545), and the title prize takes any scan of PHerc. Paris 4. That is the same list, with the same volume ids, as the snapshot `kit/data/prizes-2026-10-11.json`, which the checks read. A scroll named without its A or B part (PHerc0175 for PHerc0175A and PHerc0175B) counts as eligible.

Interpretation: public open-data scrolls off those lists include PHerc0139, PHerc0172 (Scroll 5), PHerc0332 (Scroll 3), PHerc1667 (Scroll 4), PHerc. Paris 3 (Scroll 2) and PHerc0841. The live prize page wins over the snapshot: when the page changes, add a new `kit/data/prizes-DATE.json` (the newest is the one the checks use) and check this list again.

## How it is checked

`scripts/media/common.py` (standard library only) holds the rule, and three places use it:

- **Before writing.** `write_guard()` refuses model output under any `docs/assets/` folder, and a Real data render whose record fails `real_data_problems()`: a missing data field, credit or license, an eligible scroll named in its data, caption, alt text or file names (scroll numbers, Paris and Scroll 1 to 5 names, and volume ids), or held-out labels drawn. `hero.py` and `encode.py` call it before they render or encode.
- **After writing.** `size_guard()` removes a file written under `docs/assets/` that is over 1920 px wide or 4 MB; `encode.py` also caps its GIF and MP4 at 4 MB there.
- **In the tests.** `tests/test_repo.py` runs `public_problems()` on every sidecar under `docs/assets/` (schema, label, caption, license, command, commit, every output's width and bytes, and the real-data checks), checks each file's real pixel size and bytes against its row and sidecar, and fails on a picture or clip tracked outside `docs/assets/` and `docs/images/`. SVG files are vector drawings, not pictures under this rule, so charts drawn from published numbers may sit anywhere; the test fails on any tracked SVG that embeds or links a raster picture (`svg_embeds_raster()`). `tests/test_media.py` shows each check failing on a bad record.

The eligible list comes from the newest `kit/data/prizes-*.json`; without one, the checks fail instead of passing. A label is only a claim, so a reviewer still looks at every new picture before it is merged.

## Audit, 18 October 2026

Every file on branch `claude/release-media` was checked against the rule when it was set. All 29 pictures and clips under `docs/assets/` are concept illustrations or synthetic demos (no Real data render yet), all within 1920 px and 4 MB (the widest 1920 px, the largest 2,247,301 bytes), described by 18 sidecars that pass `public_problems()`. The monitor's surface cards show a stand-in model's stripes on made-up data, labeled Model output inside the interface; that is output of no scroll, so it stays a Synthetic demo. The three screenshots in `docs/images/workbench/` show interfaces and drawn practice pixels only. Nothing moved or was removed.
