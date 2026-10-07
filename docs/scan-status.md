# Scan availability and our processing status

Snapshot assembled 2026-10-07. This page answers two different questions: which physical CT scans the organizers publicly list, and which processing jobs this repository has recorded. A published CT scan can still have no completed segmentation or ink test here. A completed benchmark crop is not a completed scroll.

## Our processing

**Done** means the named scope has saved results. **Partial** means some work finished but the requested comparison or controls did not. **Planned** means a queue or preregistration exists without a completed result in the reviewed record. **Not started** is used only for a named task with no recorded run. These are repository records, not a monitor of the user's Mac or the old cloud jobs. No job below is asserted to be running now.

The evidence is [`results.json`](results.json), dated logs, the [Mac Phase 0 queue](../scripts/mac-phase0.sh), the [atlas preregistration](prereg/2026-10-07-v8in-atlas.md), and the saved cloud branches linked below. Community benchmark rows are comparison sources, not runs completed by this repository. CPU and MPS results are kept separate.

| Volume or segment | Model or task | Device | Recorded status | Evidence and remaining scope |
| --- | --- | --- | --- | --- |
| PHerc0139 w035, `20260317000000-w035_2026031718` | `ink_9um` seed42; forward/reverse; CPU vs MPS | Linux CPU; user's M1 Pro CPU/MPS | Done: pipeline and device control | [w035 log](logs/2026-10-07-w035-cpu.md). Training segment; this establishes pipeline reproduction, not generalization. |
| PHerc0139 w045, `20260126000000-w045_2026012619` | `ink_9um` seeds42/43 and their mean; forward/reverse; full maps and crops | CPU; MPS crop check | Done: labelled control | [Results ledger](results.json) and [community-scan log](logs/2026-10-07-community-scan.md). CPU/MPS seed crops agree; full-map and crop scores must not be mixed. |
| PHerc0139 w045 | Base `v8in` at `d89166b`; crop, forward/reverse; CPU vs MPS check | M1 Pro MPS; CPU/MPS verification | Done: recorded crop and device check | [Results ledger](results.json). The recorded MPS crop AUC is 0.7382, reverse 0.3269; this is not a whole-scroll result. |
| PHerc0139 w045 | `d9v2`; crop, forward/reverse | CPU | Done: recorded crop | [Results ledger](results.json). Reader v2 trained on w045, so it is not a fair held-out control for Reader v2. |
| PHerc0139 w045 | Raw CT intensity baseline | CPU | Partial: stopped on memory failure | [Overlap/baseline log](logs/2026-10-07-overlap-and-baseline.md); no successful rerun recorded. |
| PHerc0841 w00, `20260220213127-w00` | `ink_9um` seed42 full map; `ink_9um`, `d9v2`, Reader v2 crop controls | CPU | Done: named maps and crop tests | [Results ledger](results.json), [novel-checks log](logs/2026-10-07-novel-checks.md), [PR #8 saved tricks](https://github.com/ChaseHendrick/Scrolls/pull/8). Includes reverse/shuffle and depth-window diagnostics in the saved branch. |
| PHerc0841 ag896, `20260220214732-auto_grown_20260220144552896` | `ink_9um` seed42 full map; `ink_9um`, `d9v2`, Reader v2 crop controls | CPU | Done: named maps and crop tests | Same sources as w00. Reader v2 controls are recorded on these two traces only. |
| PHerc0841 ag405, `20260221022814-auto_grown_20260220174252405` | `ink_9um` seed42 full map; `ink_9um` and `d9v2` crop controls | CPU | Done: named maps and crop tests | [Results ledger](results.json), [novel-checks log](logs/2026-10-07-novel-checks.md), [PR #9 partial job](https://github.com/ChaseHendrick/Scrolls/pull/9). `d9v2` forward/reverse 0.8319/0.6572 reproduced. |
| PHerc0841 w00 | Released `v8in-1447` at `2bf9f42`, plus `d9v2` mean/rank ensembles | CPU | Partial: scores saved, matched-stride comparison missing | [PR #7](https://github.com/ChaseHendrick/Scrolls/pull/7). Forward stride42, reverse stride64; 0.8381/0.5932 are preserved historical scores, not a comparison with identical settings. |
| PHerc0841 ag405 | Released `v8in-1447`, plus intended ensembles | CPU | Partial: fine-tune interrupted | [PR #9 notes](https://github.com/ChaseHendrick/Scrolls/blob/claude/gallant-pasteur-b1y2si-v8in1447-ag405/scripts/experiments/2026-10-07-cloud/v8in1447-ag405/notes.md). 172/196 tiles at stop; only `d9v2` has a saved scored map. No completed fine-tune or ensemble score. |
| PHerc0841 ag896 | Released `v8in-1447` | CPU job script | Planned: no saved result in reviewed branch | [PR #10](https://github.com/ChaseHendrick/Scrolls/pull/10) contains run/score scripts, no results JSON. Actual completion outside that record is unknown. |
| PHerc0841 w00/ag896/ag405 | Base `v8in`; intended crop forward/reverse/shuffle and denser-stride runs | CPU cloud jobs | Partial: reproduction queue stopped | [Cloud-partial log](logs/2026-10-07-cloud-partial.md). ag896/ag405 branch results contain `ink_9um`/`d9v2` bars, not completed base-v8in scores; w00 has no saved results JSON. |
| PHerc0841 w00/ag896/ag405 | Base `v8in` and `v8in-1447` crop comparisons | Mac MPS, fp32 queue | Planned: completed Mac results not recorded here | [`mac-phase0.sh`](../scripts/mac-phase0.sh) queues six jobs and skips already scored local results. Check the user's local ledger before restarting. Earlier handoff reports are not live status. |
| PHerc0841 ag405 | Reader v2 reverse/shuffle and letter-scale audit | Device not selected | Not started in reviewed record: proposed follow-up | [Cloud-partial log](logs/2026-10-07-cloud-partial.md); saved Reader v2 depth controls cover w00/ag896, not this independent surface. |
| PHerc0841 w00/ag896/ag405 | Raw CT baselines; overlap/collation diagnostics; published null-rule tests | CPU | Done: baselines and geometry diagnostics; null rules on w00 only | [Overlap/baseline log](logs/2026-10-07-overlap-and-baseline.md), [thresholds branch](https://github.com/ChaseHendrick/Scrolls/tree/claude/gallant-pasteur-b1y2si-thresholds/scripts/experiments/2026-10-07-cloud/thresholds). Threshold job parts 2/3 ran on w00 only; independent-sheet calibration part 1 remains unrun. These are diagnostic/model outputs, not readings. |
| PHerc0841 w00/ag896, geometry-selected patch | `surfacefix` baseline/reference and +/-1 voxel candidates; forward/reverse/shuffle | Cloud CPU | Done: bounded rejection test; accuracy unestablished | [Real validation](logs/2026-10-07-real-surfacefix-validation.md): 12 maps, 16 flagged regions, zero edits accepted; zero supervision. Eight full-search nulls also accepted zero edits. |
| PHerc0139 w045 structural cubes | Original/pag0/pag50 raw-CT registration | Cloud CPU | Done: feasibility test failed; recipe ink comparison unrun | [Reconstruction test](logs/2026-10-07-reconstruction-tests.md): four shift-recovery controls passed, both held-back registrations failed by 18.724 um. |
| PHerc0813 | Base `v8in` atlas, 75 automatic meshes | Mac MPS planned | Planned: no target run recorded | [Preregistration](prereg/2026-10-07-v8in-atlas.md); [atlas runner](../scripts/mac-atlas-v8in.sh). Public CT and meshes already exist; this is processing still to do here. |
| PHerc0358 | Base `v8in` atlas, 3 automatic meshes | Mac MPS planned | Planned: no target run recorded | Same preregistration; gated on the labelled device/model checks. |
| PHerc0826 | Base `v8in` atlas, 3 automatic meshes | Mac MPS planned | Planned: no target run recorded | Same preregistration. Together these are 81 planned meshes; no target maps, triage scores or verdicts are listed here. |
| Other publicly catalogued samples below | No further own target-processing task established by this inventory | Not recorded | No completed processing recorded here | Public availability is not a commitment to process every scan. Community runs are separate evidence. |

w00 and ag896 are traces of the same PHerc0841 sheet, with disjoint scoring crops; ag405 is a different surface. Their crop results are useful descriptive measurements, but w00/ag896 are not independent sheet replications. See the [overlap measurements](logs/2026-10-07-overlap-and-baseline.md). Passing one component above does not mean Phase 0 or the target readout has passed in full.

## Community CT acquisition and public availability

The official [Data Browser](https://scrollprize.org/data_browser/) describes released samples, not the organizers' complete physical collection or future beamtime schedule. The table below is extracted from its [public source index](https://github.com/ScrollPrize/villa/blob/e0bbb8b40a2db58b1d71864f286eb85717e59e64/scrollprize.org/static/data_browser/index.json), at villa `e0bbb8b40a2d`, reviewed 2026-10-07. That file's internal `updated` date is **2026-06-15**; treat this as a versioned catalogue snapshot and consult the live browser for changes.

This snapshot marks **45 samples scanned: 35 scrolls and 10 fragments**. That counts physical samples, not CT acquisitions or volume files. Some have several resolutions or separate reconstructed volumes from one scan. CT counts below are the number of `ctVolumes` entries, and voxel sizes are their recorded sizes. Neither column measures how much has been unrolled or read. All sample links open the official browser; no CT chunks were downloaded to build this inventory.

| Sample | Type | CT acquisition status in catalogue | Indexed CT volumes | Recorded voxel sizes (um) |
| --- | --- | --- | ---: | --- |
| [PHercParis4](https://scrollprize.org/data_browser/PHercParis4) | scroll | Scanned; public CT listed | 7 | 1.129, 2.4, 7.91, 45.532 |
| [PHerc1667](https://scrollprize.org/data_browser/PHerc1667) | scroll | Scanned; public CT listed | 4 | 1.129, 2.399, 3.24, 7.91 |
| [PHerc0172](https://scrollprize.org/data_browser/PHerc0172) | scroll | Scanned; public CT listed | 2 | 7.91 |
| [PHerc0139](https://scrollprize.org/data_browser/PHerc0139) | scroll | Scanned; public CT listed | 9 | 1.129, 2.399, 2.403, 9.362 |
| [PHerc0814](https://scrollprize.org/data_browser/PHerc0814) | scroll | Scanned; public CT listed | 3 | 1.129, 2.399, 9.362 |
| [PHerc0343P](https://scrollprize.org/data_browser/PHerc0343P) | fragment | Scanned; public CT listed | 2 | 2.215, 8.64 |
| [PHerc0500P2](https://scrollprize.org/data_browser/PHerc0500P2) | fragment | Scanned; public CT listed | 4 | 0.55, 2.215, 4.317, 9.362 |
| [PHerc0009B](https://scrollprize.org/data_browser/PHerc0009B) | fragment | Scanned; public CT listed | 3 | 2.401, 8.64 |
| [PHerc0841](https://scrollprize.org/data_browser/PHerc0841) | scroll | Scanned; public CT listed | 2 | 2.403, 9.366 |
| [PHerc0332](https://scrollprize.org/data_browser/PHerc0332) | scroll | Scanned; public CT listed | 4 | 2.399, 3.24, 7.91 |
| [PHerc1451](https://scrollprize.org/data_browser/PHerc1451) | scroll | Scanned; public CT listed | 2 | 2.399, 8.64 |
| [PHercMANBp](https://scrollprize.org/data_browser/PHercMANBp) | fragment | Scanned; public CT listed | 2 | 1.129, 2.399 |
| [PHerc0846A](https://scrollprize.org/data_browser/PHerc0846A) | scroll | Scanned; public CT listed | 2 | 2.403, 9.362 |
| [PHerc1203](https://scrollprize.org/data_browser/PHerc1203) | scroll | Scanned; public CT listed | 2 | 2.403, 9.362 |
| [PHerc1299](https://scrollprize.org/data_browser/PHerc1299) | scroll | Scanned; public CT listed | 1 | 2.399 |
| [PHercMAN5](https://scrollprize.org/data_browser/PHercMAN5) | scroll | Scanned; public CT listed | 1 | 2.399 |
| [PHercMANB](https://scrollprize.org/data_browser/PHercMANB) | scroll | Scanned; public CT listed | 1 | 2.399 |
| [PHercParis3](https://scrollprize.org/data_browser/PHercParis3) | scroll | Scanned; public CT listed | 1 | 2.4 |
| [PHerc0175A](https://scrollprize.org/data_browser/PHerc0175A) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0175B](https://scrollprize.org/data_browser/PHerc0175B) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0268](https://scrollprize.org/data_browser/PHerc0268) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0306B](https://scrollprize.org/data_browser/PHerc0306B) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0343](https://scrollprize.org/data_browser/PHerc0343) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0483A](https://scrollprize.org/data_browser/PHerc0483A) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0483B](https://scrollprize.org/data_browser/PHerc0483B) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0490A](https://scrollprize.org/data_browser/PHerc0490A) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0490B](https://scrollprize.org/data_browser/PHerc0490B) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0800](https://scrollprize.org/data_browser/PHerc0800) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc1218](https://scrollprize.org/data_browser/PHerc1218) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc1447](https://scrollprize.org/data_browser/PHerc1447) | scroll | Scanned; public CT listed | 1 | 8.64 |
| [PHerc0125](https://scrollprize.org/data_browser/PHerc0125) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc0191](https://scrollprize.org/data_browser/PHerc0191) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc0211](https://scrollprize.org/data_browser/PHerc0211) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc0257](https://scrollprize.org/data_browser/PHerc0257) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc0358](https://scrollprize.org/data_browser/PHerc0358) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc0813](https://scrollprize.org/data_browser/PHerc0813) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc0826](https://scrollprize.org/data_browser/PHerc0826) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc0846B](https://scrollprize.org/data_browser/PHerc0846B) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc1545](https://scrollprize.org/data_browser/PHerc1545) | scroll | Scanned; public CT listed | 1 | 9.362 |
| [PHerc1667Cr1Fr3](https://scrollprize.org/data_browser/PHerc1667Cr1Fr3) | fragment | Scanned; [legacy release](https://dl.ash2txt.org/fragments/Frag5/PHerc1667Cr1Fr3.volpkg/) | 0 | Not indexed; legacy data link |
| [PHerc51Cr4Fr8](https://scrollprize.org/data_browser/PHerc51Cr4Fr8) | fragment | Scanned; [legacy release](https://dl.ash2txt.org/fragments/Frag6/PHerc51Cr4Fr8.volpkg/) | 0 | Not indexed; legacy data link |
| [PHercParis1Fr34](https://scrollprize.org/data_browser/PHercParis1Fr34) | fragment | Scanned; [legacy release](https://dl.ash2txt.org/fragments/Frag3/PHercParis1Fr34.volpkg/) | 0 | Not indexed; legacy data link |
| [PHercParis1Fr39](https://scrollprize.org/data_browser/PHercParis1Fr39) | fragment | Scanned; [legacy release](https://dl.ash2txt.org/fragments/Frag4/PHercParis1Fr39.volpkg/) | 0 | Not indexed; legacy data link |
| [PHercParis2Fr143](https://scrollprize.org/data_browser/PHercParis2Fr143) | fragment | Scanned; [legacy release](https://dl.ash2txt.org/fragments/Frag2/PHercParis2Fr143.volpkg/) | 0 | Not indexed; legacy data link |
| [PHercParis2Fr47](https://scrollprize.org/data_browser/PHercParis2Fr47) | fragment | Scanned; [legacy release](https://dl.ash2txt.org/fragments/Frag1/PHercParis2Fr47.volpkg/) | 0 | Not indexed; legacy data link |

The six legacy fragment entries report zero indexed CT volumes but explicitly mark `stages.scanned = true` and link released `.volpkg` data. Zero in this column does **not** mean unscanned.

### CT acquisitions still to do

| Question | Publicly supported status as reviewed 2026-10-07 |
| --- | --- |
| Which named scrolls have not yet been physically scanned? | Not publicly documented by this catalogue. Absence from a released-data index cannot establish that a specimen is unscanned. |
| Which new scans or rescans are scheduled, with dates or resolution? | No authoritative future acquisition list was established from the sources used for this page. Do not infer a schedule from processing plans or old browser timeline entries. |
| Which scans are physically complete but not released? | Not established here. These require a current organizer announcement or explicit acquisition record. |

These are unknowns, not an empty acquisition queue. Add a named pending scan only with a dated official source; record physical acquisition, reconstruction and public release separately.

### Prize-volume subset and exact public S3 locations

The [2026-10-06 prize snapshot](../kit/data/prizes-2026-10-06.json) resolves **13 Grand Prize and 22 First Letters entries**, with 12 in both lists: **23 distinct CT volume records**. Each row below is an already listed public CT volume. Eligibility is dated; it is not a judgement about whether a scan has text or a prediction about prize results. [The live prize page](https://scrollprize.org/prizes) wins on changes. PHerc1447 leaving First Letters did not remove its CT data.

Every S3 path uses `s3://vesuvius-challenge-open-data/<sample>/volumes/<zarr>/`. The volume-link column below points to `.zattrs` metadata under that path over public HTTPS; its exact Zarr filename is the link label. These paths were resolved in the dated repository snapshot, not individually re-downloaded or revalidated in this status update.

| Sample | Dated eligibility | Voxel size (um) | Public CT volume |
| --- | --- | ---: | --- |
| PHerc0125 | Grand, First Letters | 9.362 | [20250821151825-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0125/volumes/20250821151825-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0175A | First Letters | 8.64 | [20250521115057-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0175B | First Letters | 8.64 | [20250521125822-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175B/volumes/20250521125822-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0191 | Grand, First Letters | 9.362 | [20250821151635-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0191/volumes/20250821151635-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0211 | Grand, First Letters | 9.362 | [20250821151803-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0211/volumes/20250821151803-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0257 | Grand, First Letters | 9.362 | [20250821151750-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0257/volumes/20250821151750-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0268 | Grand, First Letters | 8.64 | [20251110183117-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0268/volumes/20251110183117-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0306B | First Letters | 8.64 | [20250521133212-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0306B/volumes/20250521133212-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0343 | First Letters | 8.64 | [20250521140437-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0358 | Grand, First Letters | 9.362 | [20250821151737-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0358/volumes/20250821151737-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0483A | First Letters | 8.64 | [20250521140913-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0483A/volumes/20250521140913-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0483B | First Letters | 8.64 | [20251124083638-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0483B/volumes/20251124083638-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0490A | First Letters | 8.64 | [20250521151210-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0490A/volumes/20250521151210-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0490B | First Letters | 8.64 | [20250521151215-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0490B/volumes/20250521151215-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0800 | Grand, First Letters | 8.64 | [20250521135224-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0800/volumes/20250521135224-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc0813 | Grand, First Letters | 9.362 | [20250821151723-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0813/volumes/20250821151723-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0826 | Grand, First Letters | 9.362 | [20250821151701-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0826/volumes/20250821151701-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0846A | First Letters | 9.362 | [20250728152254-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0846A/volumes/20250728152254-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc0846B | First Letters | 9.362 | [20250804142305-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0846B/volumes/20250804142305-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc1203 | Grand, First Letters | 9.362 | [20250820131727-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc1203/volumes/20250820131727-9.362um-1.2m-113keV-masked.zarr/.zattrs) |
| PHerc1218 | Grand, First Letters | 8.64 | [20250521120456-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc1218/volumes/20250521120456-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc1447 | Grand | 8.64 | [20250521151220-8.640um-1.2m-116keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc1447/volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr/.zattrs) |
| PHerc1545 | Grand, First Letters | 9.362 | [20250821151648-9.362um-1.2m-113keV-masked.zarr](https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc1545/volumes/20250821151648-9.362um-1.2m-113keV-masked.zarr/.zattrs) |

This prize subset excludes control-scroll volumes and additional resolutions in the broader Data Browser, including the finer PHerc0139/PHerc0841 label volumes and PHercParis4 scans. The official browser and its source index link those releases. Availability of these scans is already established in the catalogue; producing meshes, renders, labels and controlled model tests is the remaining software/annotation work.

## Keeping this list current

When a job finishes, link its scored result and record device, checkpoint revision, crop/full-map scope and depth controls. For an interrupted job, retain the last completed artifact and leave the remaining work partial. Update this dated page from saved evidence, not an old "running" message. Target artifacts and candidate decisions stay in the private local ledger under the [workflow](WORKFLOW.md), not in this table.

For community acquisition changes, use the official Data Browser or a dated organizer announcement. Create a new dated prize snapshot rather than modifying the historical one. Do not change "not publicly documented" to "not scanned" without direct evidence.
