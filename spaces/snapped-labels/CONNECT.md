# Connect your tool: Snapped Labels

The snapped meshes, their records and the CT they sit on read straight from these URLs, logged out. Every segment is a tifxyz folder, so VC3D, villa and anything that reads tifxyz opens it as it is.

Checked 2026-10-27. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## Snapped labels: every segment, with index.json and checksums

`https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data). One folder per segment, SCROLL/SEGMENT/: snapped.tifxyz, abstain.tif, confidence.tif, reason.tif, source.tif (finesnap), release_mask.tif and release.json (source URLs, sha256 of every file, summary). index.json lists every segment; viewer/ holds the page's cross sections.

### Python (huggingface_hub) (tested 2026-10-24)

```python
# pip install huggingface_hub
from huggingface_hub import hf_hub_download, snapshot_download

path = hf_hub_download("SharpMeow/vesuvius-snapped-labels", "index.json", repo_type="dataset")  # one file, cached
folder = snapshot_download("SharpMeow/vesuvius-snapped-labels", repo_type="dataset")
```

### Command line (hf) (tested 2026-10-24)

```bash
pip install -U huggingface_hub
hf download SharpMeow/vesuvius-snapped-labels index.json --repo-type dataset --local-dir vesuvius-snapped-labels
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels/resolve/main/index.json
```

## One snapped mesh (tifxyz): PHerc0841 w00

`https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels/resolve/main/PHerc0841/20260220213127-w00/snapped.tifxyz`

License: CC BY-NC 4.0 (derived from Vesuvius Challenge open data). Same grid and voxel frame as the published mesh it came from (release.json names it), so the two line up vertex for vertex; -1 where there is no vertex or it was held back.

### Python (numpy, tifffile) (tested 2026-10-24)

```python
# pip install numpy tifffile
import io, json, urllib.request
import numpy as np, tifffile

T = "https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels/resolve/main/PHerc0841/20260220213127-w00/snapped.tifxyz"
meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format
get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{T}/{c}.tif").read()))
xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface
```

## The CT that mesh is in, PHerc0841 9.366 um

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr`

License: CC BY-NC 4.0 (Vesuvius Challenge open data). Read live from the open-data bucket, never copied here. Mesh coordinates are level-0 voxels of this scan.

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr", mode="r")  # OME-Zarr, zarr v2
a = root["2"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[3600:3664, 600:664, 500:564]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/2")  # one pyramid level
block = v[3600:3664, 600:664, 500:564]
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
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fvesuvius-challenge-open-data.s3.us-east-1.amazonaws.com%2FPHerc0841%2Fvolumes%2F20250821151531-9.366um-1.2m-113keV-masked.zarr%2F%22%2C%22name%22%3A%22The%20CT%20that%20mesh%20is%20in%2C%20PHerc0841%209.366%20um%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/2/.zarray     # one level: shape, chunks, dtype, codec
```

## This page's own files

`https://sharpmeow-snapped-labels.static.hf.space/`

License: Page code Apache 2.0; data as above. In the browser console, window.snappedLabels.segments() lists the index and window.snappedLabels.open(SEGMENT, Z) opens a segment at a plane; ?seg=SEGMENT&z=Z links to a view.

### Links and embed (tested 2026-10-24)

```text
The dataset card: https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels
A segment's cross sections for the viewer (float32 rows, see the .json beside it): https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels/resolve/main/viewer/PHerc0841/20260220213127-w00.json
Page source: https://github.com/ChaseHendrick/Scrolls/tree/main/spaces/snapped-labels
```
