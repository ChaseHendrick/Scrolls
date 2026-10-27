# Connect your tool: Ink Atlas

Every map on this page is a PNG in a public Hugging Face dataset, and each surface's meta.json links the mesh and the CT it was rendered from; here they are for your own tools, with the page's API and MCP server.

Checked 2026-10-27. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## The atlas: every map of every surface (SharpMeow/first-letters-ink-atlas)

`https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data and ketchupbyheinz's meshes). atlas.json lists every surface and its folder. Each folder holds maps/MODEL/WINDOW_s1_ORDER.png (8-bit, 0 to 1 as 0 to 255), ensemble/ and ensemble-rev/, ct_mid.png, preview.jpg and meta.json. Model output, not a reading.

### Python (huggingface_hub) (tested 2026-10-24)

```python
# pip install huggingface_hub
from huggingface_hub import hf_hub_download, snapshot_download

path = hf_hub_download("SharpMeow/first-letters-ink-atlas", "atlas.json", repo_type="dataset")  # one file, cached
folder = snapshot_download("SharpMeow/first-letters-ink-atlas", repo_type="dataset")  # about 1.7 GB in 1,447 files; allow_patterns=[...] fetches part of it
```

### Command line (hf) (tested 2026-10-24)

```bash
pip install -U huggingface_hub
hf download SharpMeow/first-letters-ink-atlas atlas.json --repo-type dataset --local-dir first-letters-ink-atlas
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/atlas.json
```

## One map: the ensemble of PHerc0343 reference surface 4937_3336_11593

`https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/surfaces/PHerc0343/kbh-PHerc0343_4937_3336_11593/ensemble/forward.png`

License: CC BY-NC 4.0. 2016 x 2016 pixels at 9.6 um, the same grid as every other map of that surface, so maps stack pixel for pixel. The ensemble PNG maps z from -2 to 4 onto 0 to 255.

### Python (tested 2026-10-24)

```python
import io, urllib.request
from PIL import Image

img = Image.open(io.BytesIO(urllib.request.urlopen("https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/surfaces/PHerc0343/kbh-PHerc0343_4937_3336_11593/ensemble/forward.png").read()))  # pip install pillow
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/datasets/SharpMeow/first-letters-ink-atlas/resolve/main/surfaces/PHerc0343/kbh-PHerc0343_4937_3336_11593/ensemble/forward.png
```

## The traced mesh behind that surface (tifxyz, ketchupbyheinz)

`https://raw.githubusercontent.com/ketchupbyheinz/vesuvius-scroll-survey/1f12c1ceb14c1f24acc48249eaad60bcdf541721/results/meshes/PHerc0343_4937_3336_11593`

License: Meshes CC BY-NC 4.0, code MIT (vesuvius-scroll-survey). x.tif, y.tif and z.tif in level-0 voxels of the 8.64 um PHerc0343 scan. Every surface's meta.json names its mesh in mesh.base.

### Python (numpy, tifffile) (tested 2026-10-24)

```python
# pip install numpy tifffile
import io, json, urllib.request
import numpy as np, tifffile

T = "https://raw.githubusercontent.com/ketchupbyheinz/vesuvius-scroll-survey/1f12c1ceb14c1f24acc48249eaad60bcdf541721/results/meshes/PHerc0343_4937_3336_11593"
meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format
get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{T}/{c}.tif").read()))
xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface
```

## The CT that mesh is on: PHerc0343, 8.64 um

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). Read live from the open-data bucket; the atlas rendered level 0. Every surface's meta.json names its CT in ct.

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["2"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[2880:2944, 832:896, 1216:1280]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr/2")  # one pyramid level
block = v[2880:2944, 832:896, 1216:1280]
```

### VC3D (from villa's source)

```text
In VC3D (villa's volume-cartographer), open or create a project, then
File > Attach Remote Zarr... and paste:

https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr

It accepts http, https and s3 OME-Zarr roots.
```

### neuroglancer (tested 2026-10-24)

```text
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fvesuvius-challenge-open-data.s3.us-east-1.amazonaws.com%2FPHerc0343%2Fvolumes%2F20250521140437-8.640um-1.2m-116keV-masked.zarr%2F%22%2C%22name%22%3A%22The%20CT%20that%20mesh%20is%20on%3A%20PHerc0343%2C%208.64%20um%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0343/volumes/20250521140437-8.640um-1.2m-116keV-masked.zarr/2/.zarray     # one level: shape, chunks, dtype, codec
```

## Browse the atlas from code or an agent

`https://huggingface.co/spaces/SharpMeow/ink-atlas`

License: Code Apache 2.0; data CC BY-NC 4.0. get_map and compare_models return pictures and records; surface_info gives every file's URL. Runs on the Space's CPU, no key. Model output, not a reading.

### Python /atlas_summary (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/ink-atlas")
result = client.predict(api_name="/atlas_summary")
```

### Python /list_scrolls (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/ink-atlas")
result = client.predict(api_name="/list_scrolls")
```

### Python /list_surfaces (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/ink-atlas")
result = client.predict(scroll="PHerc0343", api_name="/list_surfaces")
```

### curl /atlas_summary (tested 2026-10-24)

```bash
URL=https://sharpmeow-ink-atlas.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/atlas_summary -H 'Content-Type: application/json' \
  -d '{"data": []}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN $URL/gradio_api/call/atlas_summary/$EVENT
```

### MCP (Claude, Cursor and other agents) (tested 2026-10-24)

```json
{
  "mcpServers": {
    "ink-atlas": {
      "url": "https://sharpmeow-ink-atlas.hf.space/gradio_api/mcp/sse"
    }
  }
}

Tool list: https://sharpmeow-ink-atlas.hf.space/gradio_api/mcp/schema
```
