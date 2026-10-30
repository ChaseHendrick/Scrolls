# Connect your tool: Lasagna Fields

The ten whole-scan fields in the public bucket read straight by URL, logged out, with no download step; villa's fields in the open data stream the same way from the run folders the Every field tab lists, and the other datasets download whole. The scans they came from are open data. The page is also an API and an MCP server that lists every field and makes a field for any box of any public scan.

Checked 2026-10-25. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## A whole-scan field: PHerc0175A cos, level 1 (every 2nd scan voxel)

`https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve/PHerc0175A/representations/predictions/lasagna/20250521115057-lasagna-de45f011/PHerc0175A_cos.ome.zarr`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data). Model output (villa lasagna at db3dbea2, scrollprize/lasagna at de45f011). grad_mag, nx and ny sit beside it, from level 2; PHerc0175A.lasagna.json in the same folder is villa's manifest. The other nine bucket scans: replace the scan and run folder as listed on the Every field tab.

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve/PHerc0175A/representations/predictions/lasagna/20250521115057-lasagna-de45f011/PHerc0175A_cos.ome.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["1"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[3186:3250, 2900:2964, 2200:2264]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve/PHerc0175A/representations/predictions/lasagna/20250521115057-lasagna-de45f011/PHerc0175A_cos.ome.zarr/1")  # one pyramid level
block = v[3186:3250, 2900:2964, 2200:2264]
```

### VC3D (from villa's source)

```text
In VC3D (villa's volume-cartographer), open or create a project, then
File > Attach Remote Zarr... and paste:

https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve/PHerc0175A/representations/predictions/lasagna/20250521115057-lasagna-de45f011/PHerc0175A_cos.ome.zarr

It accepts http, https and s3 OME-Zarr roots.
```

### neuroglancer (tested 2026-10-24)

```text
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fhuggingface.co%2Fbuckets%2FSharpMeow%2Flasagna-fields%2Fresolve%2FPHerc0175A%2Frepresentations%2Fpredictions%2Flasagna%2F20250521115057-lasagna-de45f011%2FPHerc0175A_cos.ome.zarr%2F%22%2C%22name%22%3A%22A%20whole-scan%20field%3A%20PHerc0175A%20cos%2C%20level%201%20%28every%202nd%20scan%20voxel%29%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve/PHerc0175A/representations/predictions/lasagna/20250521115057-lasagna-de45f011/PHerc0175A_cos.ome.zarr/.zattrs            # OME multiscales metadata
curl -s https://huggingface.co/buckets/SharpMeow/lasagna-fields/resolve/PHerc0175A/representations/predictions/lasagna/20250521115057-lasagna-de45f011/PHerc0175A_cos.ome.zarr/1/.zarray     # one level: shape, chunks, dtype, codec
```

## X-ray CT that field came from, PHerc0175A 8.640 um

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). Read live from the open-data bucket, never copied here. The field's level 1 is the scan's level 1 grid.

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["2"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[1593:1657, 1170:1234, 1170:1234]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr/2")  # one pyramid level
block = v[1593:1657, 1170:1234, 1170:1234]
```

### VC3D (from villa's source)

```text
In VC3D (villa's volume-cartographer), open or create a project, then
File > Attach Remote Zarr... and paste:

https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr

It accepts http, https and s3 OME-Zarr roots.
```

### neuroglancer (tested 2026-10-24)

```text
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fvesuvius-challenge-open-data.s3.us-east-1.amazonaws.com%2FPHerc0175A%2Fvolumes%2F20250521115057-8.640um-1.2m-116keV-masked.zarr%2F%22%2C%22name%22%3A%22X-ray%20CT%20that%20field%20came%20from%2C%20PHerc0175A%208.640%20um%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0175A/volumes/20250521115057-8.640um-1.2m-116keV-masked.zarr/2/.zarray     # one level: shape, chunks, dtype, codec
```

## Make a field for any box, from code or an agent

`https://huggingface.co/spaces/SharpMeow/lasagna-fields`

License: Code Apache 2.0; villa lasagna and its checkpoint MIT; scans and fields CC BY-NC 4.0. make_field (same arguments as plan_field) runs villa's lasagna on ZeroGPU and uses the caller's ZeroGPU time, so pass a Hugging Face token. Model output, not a reading.

### Python /list_models (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/lasagna-fields")
result = client.predict(api_name="/list_models")
```

### Python /example_points (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/lasagna-fields")
result = client.predict(api_name="/example_points")
```

### Python /plan_field (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/lasagna-fields")
result = client.predict(volume="20260930100252", z=39424, y=10752, x=13824, size=256, model="lasagna", api_name="/plan_field")
```

### curl /list_models (tested 2026-10-24)

```bash
URL=https://sharpmeow-lasagna-fields.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/list_models -H 'Content-Type: application/json' \
  -d '{"data": []}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN $URL/gradio_api/call/list_models/$EVENT
```

### MCP (Claude, Cursor and other agents) (tested 2026-10-24)

```json
{
  "mcpServers": {
    "lasagna-fields": {
      "url": "https://sharpmeow-lasagna-fields.hf.space/gradio_api/mcp/sse"
    }
  }
}

Tool list: https://sharpmeow-lasagna-fields.hf.space/gradio_api/mcp/schema
```
