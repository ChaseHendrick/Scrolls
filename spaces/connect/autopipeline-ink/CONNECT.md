# Connect your tool: AutoPipeline ink

The segments this page analyzes and the model it runs are public, and both read straight from these URLs in your own tool.

Checked 2026-10-27. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## Call the analysis from code or an agent (API and MCP)

`https://huggingface.co/spaces/SharpMeow/autopipeline-ink`

License: Code Apache 2.0; Reader V3 MIT; scans CC BY-NC 4.0. Every tool is an API endpoint and an MCP tool: ink_sample (a public sample crop; a JSON record with both AUCs, and a PNG preview), ink_upload (your own surface volume by URL; JSON only) and list_samples. Each GPU call spends the caller's ZeroGPU quota, which is small when logged out: pass your own Hugging Face token (token= in gradio_client 2, an Authorization: Bearer header in curl and MCP). MCP clients see the tools with the Space's prefix: autopipeline_ink_ink_sample, autopipeline_ink_ink_upload and autopipeline_ink_list_samples. Model output, not a reading.

### Python /ink_sample (tested 2026-10-24)

```python
# pip install gradio_client
import os
from gradio_client import Client

client = Client("SharpMeow/autopipeline-ink", token=os.environ.get("HF_TOKEN"))  # your token: your own ZeroGPU quota
result = client.predict(sample="0841-w00", size=640, api_name="/ink_sample")
```

### Python /list_samples (tested 2026-10-24)

```python
# pip install gradio_client
import os
from gradio_client import Client

client = Client("SharpMeow/autopipeline-ink", token=os.environ.get("HF_TOKEN"))  # your token: your own ZeroGPU quota
result = client.predict(api_name="/list_samples")
```

### curl /ink_sample (tested 2026-10-24)

```bash
# HF_TOKEN, when set, is your own token: the call spends your ZeroGPU quota
URL=https://sharpmeow-autopipeline-ink.hf.space
EVENT=$(curl -s -X POST $URL/gradio_api/call/ink_sample -H 'Content-Type: application/json' ${HF_TOKEN:+-H "Authorization: Bearer $HF_TOKEN"} \
  -d '{"data": ["0841-w00", 640]}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["event_id"])')
curl -sN ${HF_TOKEN:+-H "Authorization: Bearer $HF_TOKEN"} $URL/gradio_api/call/ink_sample/$EVENT
```

### MCP (Claude, Cursor and other agents) (tested 2026-10-24)

```json
{
  "mcpServers": {
    "autopipeline-ink": {
      "url": "https://sharpmeow-autopipeline-ink.hf.space/gradio_api/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_HF_TOKEN"
      }
    }
  }
}

YOUR_HF_TOKEN is your own Hugging Face token (huggingface.co/settings/tokens): each call spends your ZeroGPU quota; without it, calls share the small logged-out quota.

Tool list: https://sharpmeow-autopipeline-ink.hf.space/gradio_api/mcp/schema
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
