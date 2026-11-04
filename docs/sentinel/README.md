# Bucket Sentinel data

Files written or read by [`kit sentinel`](../tools/sentinel.md). Derived numbers only: no scan data, labels or maps (hard rule 6).

| File | What it is |
| --- | --- |
| [`dev-pool.json`](dev-pool.json) | The 20 open-data S3 segment surface volumes (PHerc. 0343P, PHerc. 0814, PHerc. 0009B) the planted-defect controls ran on, picked by a fixed rule (one surface volume per segment, evenly spaced through the sorted list) |
| [`offsets.json`](offsets.json) | The offset table of the Hugging Face `ink/` folders measured by the preregistered back-test (schema `bucket-sentinel-offsets/1`); read it with `kit/sentinel_table.py` |
| [`findings.json`](findings.json) | Every defect the back-test and the live sweep of 4 November 2026 flagged, one row per item and defect (Model output) |

The offsets are a data correction measured with CT only; a folder with no entry was not measured or was not opened. Each entry is pinned to the sha256 of its folder's `meta.json`, `x.tif`, `y.tif` and `z.tif`: check them with `Entry.verify(folder)` before use.
