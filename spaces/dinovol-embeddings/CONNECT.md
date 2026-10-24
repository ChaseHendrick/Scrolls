# Connect your tool: dinovol Embeddings

The features and the scan they came from read straight from these URLs, logged out, with no download step. The features are one zarr v2 group in a public Hugging Face bucket; Use it below has a tested Python snippet that opens it.

Checked 2026-10-24. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## dinovol embeddings of PHerc0841: the store's index

`https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126.zarr/index.json`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data). Model output (scrollprize/dinovol_8um_ps192_102126), not checked by eye. The group sits beside this file: arrays tokens_unit, dense and ink with their _scale arrays; .zattrs has the model, villa commit and tiling.

### Python (tested 2026-10-24)

```python
import json, urllib.request

data = json.load(urllib.request.urlopen("https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126.zarr/index.json"))
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126.zarr/index.json
```

## Color volume of the features: OME-Zarr metadata

`https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126-rgb.ome.zarr/.zattrs`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data). tokens_unit as one color per cube, a multiscale OME-Zarr (zarr v2, uint8, axes c, z, y, x, levels 0 to 3; 0 = outside the scroll). Open the folder this file sits in with zarr.open_group(URL, mode='r', zarr_format=2); the page's Open in neuroglancer button shows it with an RGB shader.

### Python (tested 2026-10-24)

```python
import json, urllib.request

data = json.load(urllib.request.urlopen("https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126-rgb.ome.zarr/.zattrs"))
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/buckets/SharpMeow/dinovol-embeddings/resolve/PHerc0841/20250821151531-dinovol_8um_ps192_102126-rgb.ome.zarr/.zattrs
```

## X-ray CT the features came from, PHerc0841 9.366 um

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). Read live from the open-data bucket, never copied here. Feature index i covers scan voxels [i*8, i*8+8) for tokens_unit and [i*4, i*4+4) for dense and ink, at level 0.

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["2"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[2400:2464, 1000:1064, 1000:1064]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/2")  # one pyramid level
block = v[2400:2464, 1000:1064, 1000:1064]
```

### VC3D (from villa's source)

```text
In VC3D (villa's volume-cartographer), open or create a project, then
File > Attach Remote Zarr... and paste:

https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr

It accepts http, https and s3 OME-Zarr roots.
```

### neuroglancer (tested 2026-10-24)

```text
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fvesuvius-challenge-open-data.s3.us-east-1.amazonaws.com%2FPHerc0841%2Fvolumes%2F20250821151531-9.366um-1.2m-113keV-masked.zarr%2F%22%2C%22name%22%3A%22X-ray%20CT%20the%20features%20came%20from%2C%20PHerc0841%209.366%20um%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/2/.zarray     # one level: shape, chunks, dtype, codec
```

## This page's own files

`https://sharpmeow-dinovol-embeddings.static.hf.space/`

License: Page code Apache 2.0; data as above. The page's numbers (slice, box, accuracy of its 32-number search) are the JSON in its data script tag.

### Links and embed (tested 2026-10-24)

```text
The bucket, with its README: https://huggingface.co/buckets/SharpMeow/dinovol-embeddings
The page's slice of features for search (32 numbers per cell, int8): https://huggingface.co/spaces/SharpMeow/dinovol-embeddings/resolve/main/assets/search.i8
Page source and build script: https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/dinovol-embeddings
```
