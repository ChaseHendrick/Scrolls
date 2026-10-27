# Connect your tool: AFV Fibers

Six whole-scan fiber sets as public Hugging Face datasets, each a few .afv files (read-only SQLite) plus small per-cell tiles, logged out; the scans they came from are open data, read live. The page is also an API and an MCP server that returns the fibers in any box.

Checked 2026-10-27. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## Fibers of one 1024-voxel cell of PHerc0139 (178 MB; the whole-scan files PHerc0139_afv_v2.afv and PHerc0139_afv_v2_1mm.afv, and the other five scans, have the same format)

`https://huggingface.co/datasets/SharpMeow/pherc0139-afv-fibers`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data); model and generator Apache 2.0. Model output (Qualzz20/afv_fiber_9um_v2, AVF_SPLINE_GENERATOR). Native level-0 voxels, XYZ float64, VC3D fiber collection version 1; open with Python's sqlite3 or villa's import_afv.py.

### Python (huggingface_hub) (tested 2026-10-24)

```python
# pip install huggingface_hub
from huggingface_hub import hf_hub_download, snapshot_download

path = hf_hub_download("SharpMeow/pherc0139-afv-fibers", "tiles/z09216_y02048_x02048.afv", repo_type="dataset")  # one file, cached
folder = snapshot_download("SharpMeow/pherc0139-afv-fibers", repo_type="dataset")  # 65.7 GB in all; allow_patterns=[...] fetches part of it
```

### Command line (hf) (tested 2026-10-24)

```bash
pip install -U huggingface_hub
hf download SharpMeow/pherc0139-afv-fibers tiles/z09216_y02048_x02048.afv --repo-type dataset --local-dir pherc0139-afv-fibers
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/datasets/SharpMeow/pherc0139-afv-fibers/resolve/main/tiles/z09216_y02048_x02048.afv
```

## The tile index: one small .afv per 1024-voxel cell, for any box without the whole file

`https://huggingface.co/datasets/SharpMeow/pherc0139-afv-fibers`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data). Each entry gives the cell's box_zyx_l0 (level-0 voxels) and fiber count; tiles/<id>.afv holds every fiber with a block in that cell, whole, with its whole-scan id.

### Python (huggingface_hub) (tested 2026-10-24)

```python
# pip install huggingface_hub
from huggingface_hub import hf_hub_download, snapshot_download

path = hf_hub_download("SharpMeow/pherc0139-afv-fibers", "tiles/index.json", repo_type="dataset")  # one file, cached
folder = snapshot_download("SharpMeow/pherc0139-afv-fibers", repo_type="dataset")  # 65.7 GB in all; allow_patterns=[...] fetches part of it
```

### Command line (hf) (tested 2026-10-24)

```bash
pip install -U huggingface_hub
hf download SharpMeow/pherc0139-afv-fibers tiles/index.json --repo-type dataset --local-dir pherc0139-afv-fibers
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/datasets/SharpMeow/pherc0139-afv-fibers/resolve/main/tiles/index.json
```

## X-ray CT those fibers came from, PHerc0139 9.362 um

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). Read live from the open-data bucket, never copied here. The fibers' level-0 voxels are this scan's level 0.

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["0"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[10000:10064, 3000:3064, 3000:3064]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/0")  # one pyramid level
block = v[10000:10064, 3000:3064, 3000:3064]
```

### VC3D (from villa's source)

```text
In VC3D (villa's volume-cartographer), open or create a project, then
File > Attach Remote Zarr... and paste:

https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr

It accepts http, https and s3 OME-Zarr roots.
```

### neuroglancer (tested 2026-10-24)

```text
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fvesuvius-challenge-open-data.s3.us-east-1.amazonaws.com%2FPHerc0139%2Fvolumes%2F20250728140407-9.362um-1.2m-113keV-masked.zarr%2F%22%2C%22name%22%3A%22X-ray%20CT%20those%20fibers%20came%20from%2C%20PHerc0139%209.362%20um%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407-9.362um-1.2m-113keV-masked.zarr/0/.zarray     # one level: shape, chunks, dtype, codec
```

## Fibers in any box, from code or an agent

`https://huggingface.co/spaces/SharpMeow/afv-fibers`

License: Code Apache 2.0; fibers CC BY-NC 4.0. fibers_box(scan, z, y, x, half) lists every fiber touching a box; look(...) adds the CT picture, a 3D view and the box as .afv. Model output, not a reading.

### Python /list_scans (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/afv-fibers")
result = client.predict(api_name="/list_scans")
```

### Python /example_points (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/afv-fibers")
result = client.predict(api_name="/example_points")
```

### curl /list_scans (tested 2026-10-24)

```bash
URL=https://sharpmeow-afv-fibers.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/list_scans -H 'Content-Type: application/json' \
  -d '{"data": []}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN $URL/gradio_api/call/list_scans/$EVENT
```

### MCP (Claude, Cursor and other agents) (tested 2026-10-24)

```json
{
  "mcpServers": {
    "afv-fibers": {
      "url": "https://sharpmeow-afv-fibers.hf.space/gradio_api/mcp/sse"
    }
  }
}

Tool list: https://sharpmeow-afv-fibers.hf.space/gradio_api/mcp/schema
```
