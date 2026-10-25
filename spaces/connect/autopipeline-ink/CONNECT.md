# Connect your tool: AutoPipeline ink

The segments this page analyzes and the model it runs are public, and both read straight from these URLs in your own tool.

Checked 2026-10-25. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## Call the analysis from code

`https://huggingface.co/spaces/SharpMeow/autopipeline-ink`

License: Code Apache 2.0; Reader V3 MIT; scans CC BY-NC 4.0. The Space has no MCP server; use gradio_client or curl. Each call spends the caller's ZeroGPU quota, which is small when logged out: pass hf_token= to Client (or an Authorization header to curl) for your own.

### Python /on_sample (tested 2026-10-24)

```python
# pip install gradio_client
from gradio_client import Client

client = Client("SharpMeow/autopipeline-ink")
result = client.predict(title="PHerc0841 w00 (development segment)", api_name="/on_sample")
```

### curl /on_sample (tested 2026-10-24)

```bash
URL=https://sharpmeow-autopipeline-ink.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/on_sample -H 'Content-Type: application/json' \
  -d '{"data": ["PHerc0841 w00 (development segment)"]}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN $URL/gradio_api/call/on_sample/$EVENT
```

## The layers it reads, example PHerc0841 w00 (9.366 um surface volume)

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

## The model: Reader V3 (Domenico Russo)

`https://huggingface.co/domenicor046/reader-v3/resolve/main/reader-v3.pth`

License: MIT. sha256 ea405417450abd8ace1b8ff79ebce3adb646c5e48ab95da46844d77efe984d8a; an ink_9um-format checkpoint for villa's ink detection, with 384 px patches in its config.

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/domenicor046/reader-v3/resolve/main/reader-v3.pth
```
