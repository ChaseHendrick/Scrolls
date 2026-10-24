# Connect your tool: Segment Lens

Every number and preview on this page comes from the Segment Atlas dataset, and every mesh it measures is a tifxyz folder on the open-data bucket. Both read straight from these URLs, with no account.

Checked 2026-10-24. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## Segment Atlas (one row per published mesh)

`https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data). Each row has the mesh's open-data url, its grid size, area, filled share, edge statistics and the holes, folds and stretched area that kit tifxyz check reports. lens/ holds the decimated 3D previews.

### Python (huggingface_hub) (tested 2026-10-24)

```python
# pip install huggingface_hub
from huggingface_hub import hf_hub_download, snapshot_download

path = hf_hub_download("SharpMeow/vesuvius-segment-atlas", "atlas.jsonl", repo_type="dataset")  # one file, cached
folder = snapshot_download("SharpMeow/vesuvius-segment-atlas", repo_type="dataset")
```

### Python (datasets) (tested 2026-10-24)

```python
# pip install datasets
from datasets import load_dataset

default = load_dataset("SharpMeow/vesuvius-segment-atlas", "default", split="train")
```

### pandas (tested 2026-10-24)

```python
# pip install pandas huggingface_hub
import pandas as pd

df = pd.read_json("hf://datasets/SharpMeow/vesuvius-segment-atlas/atlas.jsonl", lines=True)
```

### Command line (hf) (tested 2026-10-24)

```bash
pip install -U huggingface_hub
hf download SharpMeow/vesuvius-segment-atlas atlas.jsonl --repo-type dataset --local-dir vesuvius-segment-atlas
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas/resolve/main/atlas.jsonl
```

## A measured mesh (tifxyz), example PHerc0009B 20250510172639

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0009B/segments/20250510172639/mesh/20250510172639-on-20250521125136-8.64um.tifxyz`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). Every row of the atlas names its mesh folder in url; the table's mesh folder link opens it. Read live from the open-data bucket, never copied here.

### Python (numpy, tifffile) (tested 2026-10-24)

```python
# pip install numpy tifffile
import io, json, urllib.request
import numpy as np, tifffile

T = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0009B/segments/20250510172639/mesh/20250510172639-on-20250521125136-8.64um.tifxyz"
meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format
get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{T}/{c}.tif").read()))
xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface
```

## This page's code and data

`https://sharpmeow-segment-lens.static.hf.space/`

License: Page code Apache 2.0; data as above. python -m kit atlas show SCROLL and python -m kit tifxyz check MESH_URL reproduce the numbers from a clone of ChaseHendrick/Scrolls.

### Links and embed (tested 2026-10-24)

```text
The whole atlas as one CSV: https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas/resolve/main/atlas.csv
Page source: https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/segment-lens
```
