# Connect your tool: Ink Lens

The sample segments Ink Lens reads are open data, and each one reads straight from its URL in your own tool. The page is also an API and an MCP server.

Checked 2026-10-24. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## Sample layers, PHerc0841 w00 (9.366 um surface volume)

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data).

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["0"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[0:64, 2800:2864, 2900:2964]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr/0")  # one pyramid level
block = v[0:64, 2800:2864, 2900:2964]
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/9.366um-1.2m-113keV-volume-20250821151531.zarr/0/.zarray     # one level: shape, chunks, dtype, codec
```

## Its surface (tifxyz)

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/mesh/20260220213127-on-20250821151531-9.366um.tifxyz`

License: CC BY-NC 4.0 (Vesuvius Challenge open data).

### Python (numpy, tifffile) (tested 2026-10-24)

```python
# pip install numpy tifffile
import io, json, urllib.request
import numpy as np, tifffile

T = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/mesh/20260220213127-on-20250821151531-9.366um.tifxyz"
meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format
get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{T}/{c}.tif").read()))
xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface
```

## The same segment's 2.4 um surface volume (what every model reads in Compare models)

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/2.403um-0.22m-77keV-volume-20260319124803.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data).

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/2.403um-0.22m-77keV-volume-20260319124803.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["0"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[0:64, 11200:11264, 11600:11664]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/2.403um-0.22m-77keV-volume-20260319124803.zarr/0")  # one pyramid level
block = v[0:64, 11200:11264, 11600:11664]
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/2.403um-0.22m-77keV-volume-20260319124803.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/surface-volumes/2.403um-0.22m-77keV-volume-20260319124803.zarr/0/.zarray     # one level: shape, chunks, dtype, codec
```

## Its 2.4 um surface (tifxyz), the mesh the 3D models are read onto

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/mesh/20260220213127-on-20260319124803-2.403um.tifxyz`

License: CC BY-NC 4.0 (Vesuvius Challenge open data).

### Python (numpy, tifffile) (tested 2026-10-24)

```python
# pip install numpy tifffile
import io, json, urllib.request
import numpy as np, tifffile

T = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/segments/20260220213127-w00/mesh/20260220213127-on-20260319124803-2.403um.tifxyz"
meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format
get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{T}/{c}.tif").read()))
xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface
```

## Call Ink Lens from code or an agent

`https://huggingface.co/spaces/SharpMeow/ink-lens`

License: Code Apache 2.0; models MIT (each credited in list_models); scans CC BY-NC 4.0. Checked live on 24 Oct 2026: /list_samples and /lens_sample answered (gradio_client, the 0841-w00 sample). Model output, not a reading.

### Python /lens_sample (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/ink-lens")
result = client.predict(sample_id="0841-w00", size=640, reader="d9v2", windows=3, api_name="/lens_sample")
```

### Python /list_samples (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/ink-lens")
result = client.predict(api_name="/list_samples")
```

### Python /compare_sample (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/ink-lens")
result = client.predict(sample_id="0841-w00", models="ink_9um-s42,reader-v3,hecate-9.6", size=384, scan="2.4", centers="0", steps="1", api_name="/compare_sample")
```

### Python /list_models (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/ink-lens")
result = client.predict(api_name="/list_models")
```

### curl /lens_sample (tested 2026-10-24)

```bash
URL=https://sharpmeow-ink-lens.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/lens_sample -H 'Content-Type: application/json' \
  -d '{"data": ["0841-w00", 640, "d9v2", 3]}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN $URL/gradio_api/call/lens_sample/$EVENT
```

### MCP (Claude, Cursor and other agents) (tested 2026-10-24)

```json
{
  "mcpServers": {
    "ink-lens": {
      "url": "https://sharpmeow-ink-lens.hf.space/gradio_api/mcp/sse"
    }
  }
}

Tool list: https://sharpmeow-ink-lens.hf.space/gradio_api/mcp/schema
```
