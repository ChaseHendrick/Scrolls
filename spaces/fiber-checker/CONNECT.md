# Connect your tool: Fiber Checker

The Space reads open-data meshes and CT by URL and keeps none of it; here are the same sources for your own tools, and the page's API and MCP server, which checks any segment with the free judge.

Checked 2026-10-26. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## A traced segment's mesh: PHerc0500P2 z_dbg_gen_00440 on the 2.215 um scan

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/segments/20250611171318-z_dbg_gen_00440_inp_hr/mesh/20250611171318-on-20250526151718-2.215um.tifxyz/`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). x.tif, y.tif and z.tif in the scan's level-0 voxels. fiber.tif from a check has the same grid, so it lines up vertex for vertex.

### Python (numpy, tifffile) (tested 2026-10-24)

```python
# pip install numpy tifffile
import io, json, urllib.request
import numpy as np, tifffile

T = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/segments/20250611171318-z_dbg_gen_00440_inp_hr/mesh/20250611171318-on-20250526151718-2.215um.tifxyz"
meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format
get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{T}/{c}.tif").read()))
xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface
```

## The CT that mesh is on, PHerc0500P2 2.215 um

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). Read live from the open-data bucket, never copied here. The free judge reads level 2 of the 2.2 to 2.4 um scans (about 9 um).

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["2"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[1500:1564, 2000:2064, 3000:3064]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr/2")  # one pyramid level
block = v[1500:1564, 2000:2064, 3000:3064]
```

### VC3D (from villa's source)

```text
In VC3D (villa's volume-cartographer), open or create a project, then
File > Attach Remote Zarr... and paste:

https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr

It accepts http, https and s3 OME-Zarr roots.
```

### neuroglancer (tested 2026-10-24)

```text
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fvesuvius-challenge-open-data.s3.us-east-1.amazonaws.com%2FPHerc0500P2%2Fvolumes%2F20250526151718-2.215um-0.4m-111keV-masked.zarr%2F%22%2C%22name%22%3A%22The%20CT%20that%20mesh%20is%20on%2C%20PHerc0500P2%202.215%20um%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr/2/.zarray     # one level: shape, chunks, dtype, codec
```

## Check any segment, from code or an agent

`https://huggingface.co/spaces/SharpMeow/fiber-checker`

License: Code and weights Apache 2.0; scans and meshes CC BY-NC 4.0. check_segment (sample, segment, volume, patches) runs the free judge on the Space's CPU, about two minutes for 60 patches. Model output, not a reading.

### Python /list_scrolls (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/fiber-checker")
result = client.predict(api_name="/list_scrolls")
```

### Python /example_segments (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/fiber-checker")
result = client.predict(api_name="/example_segments")
```

### Python /list_segments (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/fiber-checker")
result = client.predict(sample="PHerc0343P", api_name="/list_segments")
```

### curl /list_scrolls (tested 2026-10-24)

```bash
URL=https://sharpmeow-fiber-checker.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/list_scrolls -H 'Content-Type: application/json' \
  -d '{"data": []}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN $URL/gradio_api/call/list_scrolls/$EVENT
```

### MCP (Claude, Cursor and other agents) (tested 2026-10-24)

```json
{
  "mcpServers": {
    "fiber-checker": {
      "url": "https://sharpmeow-fiber-checker.hf.space/gradio_api/mcp/sse"
    }
  }
}

Tool list: https://sharpmeow-fiber-checker.hf.space/gradio_api/mcp/schema
```
