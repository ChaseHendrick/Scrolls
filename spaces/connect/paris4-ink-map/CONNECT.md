# Connect your tool: Paris 4 Ink Map

The map on this page is the organizers' published ink map of PHerc. Paris 4; this Space streams it and reads the published mesh and CT, so every file below is linked at the Vesuvius Challenge open data, never copied here. The page's own API and its MCP server turn a map pixel into a winding and scan coordinates, cut crops, draw the spiral at one height, compare a place with the turns beside it and build a VC3D project. The Space is public and needs no account.

Checked 2026-10-29. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).

## MCP Server for Agents

`https://sharpmeow-paris4-ink-map.hf.space/mcp`

License: Vesuvius Challenge open data, CC BY-NC 4.0; the map and fit are the organizers'. Streamable HTTP, no session, JSON replies. Seven tools: get_info, find_winding, point_info, crop_image (returns a PNG), cross_section (optionally with the CT slice), neighbor_turns (optionally with the three windows) and view_link.

### Links and embed (tested 2026-10-24)

```text
MCP endpoint (Streamable HTTP, POST): https://sharpmeow-paris4-ink-map.hf.space/mcp
```

## The Page's API

`https://sharpmeow-paris4-ink-map.hf.space/api/info`

License: Vesuvius Challenge open data, CC BY-NC 4.0; the map and fit are the organizers'. Map pixels: x 0 to 142,282 from the outer end, y 0 to 2,389 from the top, 0.0768 mm each.

### Links and embed (tested 2026-10-24)

```text
Size, scale, orientation, windings and every source with its SHA-256 (JSON): https://sharpmeow-paris4-ink-map.hf.space/api/info
One map pixel: winding, distance from each end, scan height, voxel (JSON): https://sharpmeow-paris4-ink-map.hf.space/api/point?x=71000&y=1200
One winding's pixel range (JSON): https://sharpmeow-paris4-ink-map.hf.space/api/winding/60
A region as a raw TIFF of any size (scale 1, 2, 4, 8 or 16; fmt png adds colors, up to 60 Mpx): https://sharpmeow-paris4-ink-map.hf.space/api/crop?x0=70000&y0=600&x1=72000&y1=1800&scale=1&fmt=tif
Where the sheet crosses one scan height (JSON): https://sharpmeow-paris4-ink-map.hf.space/api/section?z_mm=105&step=2
The turns just outside and inside one place: where, how far, how alike, against a baseline (JSON): https://sharpmeow-paris4-ink-map.hf.space/api/neighbors?x=120000&y=1800
A VC3D project: the 2.4 um CT streamed from the open data, the spiral fit as a tifxyz segment (zip): https://sharpmeow-paris4-ink-map.hf.space/api/vc3d.zip
The fit's mesh as a point cloud for 3D views: layout and counts (JSON); binary at /api/mesh3d.bin: https://sharpmeow-paris4-ink-map.hf.space/api/mesh3d.json?stride=8
The map as a streamable OME-Zarr 0.4 (zarr v2, 9 levels, 512 px zlib chunks): https://sharpmeow-paris4-ink-map.hf.space/zarr/.zattrs
Every endpoint with an example (JSON); interactive docs at /docs: https://sharpmeow-paris4-ink-map.hf.space/api
Deep-zoom descriptor of the map (DZI, 256 px JPEG tiles): https://sharpmeow-paris4-ink-map.hf.space/tiles/ink.dzi
The whole map wrapped into rows (PNG): https://sharpmeow-paris4-ink-map.hf.space/api/overview.png?rows=4&width=1600
```

## Ink Map, Full Resolution

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/segments/20260926044226-spiral-output-generation-19/ink-detection/PHercParis4-20260926044226-2.4um-0.22m-78keV-volume-20260411134726-ink3d-20260926084000-student-v12A-25000-c7766be9-l128-accmax4-max-52-76-scale0.0625-nearest.tif`

License: Vesuvius Challenge open data, CC BY-NC 4.0. BigTIFF, 142,283 by 2,390 pixels, uint8, deflate, 64 px tiles, no overviews, 236 MB. tifffile reads it.

### Python (tested 2026-10-24)

```python
import urllib.request

raw = urllib.request.urlopen("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/segments/20260926044226-spiral-output-generation-19/ink-detection/PHercParis4-20260926044226-2.4um-0.22m-78keV-volume-20260411134726-ink3d-20260926084000-student-v12A-25000-c7766be9-l128-accmax4-max-52-76-scale0.0625-nearest.tif").read()
```

### curl (tested 2026-10-24)

```bash
curl -L -O https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/segments/20260926044226-spiral-output-generation-19/ink-detection/PHercParis4-20260926044226-2.4um-0.22m-78keV-volume-20260411134726-ink3d-20260926084000-student-v12A-25000-c7766be9-l128-accmax4-max-52-76-scale0.0625-nearest.tif
```

## The Whole Segment Folder: Ink, Mesh, Spiral Fit

`s3://vesuvius-challenge-open-data/PHercParis4/segments/20260926044226-spiral-output-generation-19/`

License: Vesuvius Challenge open data, CC BY-NC 4.0.

### Python (list the folder) (tested 2026-10-24)

```python
import re, urllib.request

B = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
xml = urllib.request.urlopen(B + "/?list-type=2&delimiter=/&prefix=PHercParis4/segments/20260926044226-spiral-output-generation-19/").read().decode()
print(re.findall(r"<Prefix>([^<]+)</Prefix>", xml))  # subfolders; <Key> gives files
```

## The Fit's Mesh (tifxyz, 9.6 um Voxels of Scan 20260411134726)

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/segments/20260926044226-spiral-output-generation-19/mesh/intermediate/tifxyz_normalized/`

License: Vesuvius Challenge open data, CC BY-NC 4.0. 956 by 56,913 nodes at 0.192 mm. This grid is already the fit rotated 180 degrees, as the map is (grid_transform in meta.json): map x = 2.5 times the column, map y = 2.5 times the row. Multiply the coordinates by 4 for 2.4 um voxels.

### Python (numpy, tifffile) (tested 2026-10-24)

```python
# pip install numpy tifffile
import io, json, urllib.request
import numpy as np, tifffile

T = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/segments/20260926044226-spiral-output-generation-19/mesh/intermediate/tifxyz_normalized"
meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format
get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{T}/{c}.tif").read()))
xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface
```

## CT, 2.4 um 78 keV Scan 20260411134726

`https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/`

License: Vesuvius Challenge open data, CC BY-NC 4.0. Uncompressed, 128 cubed chunks; level 4 is 38.4 um, the level the scroll map on this page reads.

### Python (zarr) (tested 2026-10-24)

```python
# pip install "zarr>=3" fsspec aiohttp
import zarr

root = zarr.open_group("https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/", mode="r")  # OME-Zarr, zarr v2
a = root["4"]  # level 0 is full resolution; level L is 2**L times coarser
print(a.shape, a.dtype, a.chunks)
block = a[2688:2752, 896:960, 896:960]  # (z, y, x); reads only the chunks it touches
```

### villa's vesuvius package (tested 2026-10-24)

```python
# pip install "vesuvius[volume-only]"
from vesuvius import Volume

v = Volume(type="zarr", path="https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/4")  # one pyramid level
block = v[2688:2752, 896:960, 896:960]
```

### VC3D (from villa's source)

```text
In VC3D (villa's volume-cartographer), open or create a project, then
File > Attach Remote Zarr... and paste:

https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/

It accepts http, https and s3 OME-Zarr roots.
```

### neuroglancer (tested 2026-10-24)

```text
https://neuroglancer-demo.appspot.com/#!%7B%22layers%22%3A%5B%7B%22type%22%3A%22image%22%2C%22source%22%3A%22zarr%3A%2F%2Fhttps%3A%2F%2Fvesuvius-challenge-open-data.s3.us-east-1.amazonaws.com%2FPHercParis4%2Fvolumes%2F20260411134726-2.400um-0.2m-78keV-masked.zarr%2F%22%2C%22name%22%3A%22CT%2C%202.4%20um%2078%20keV%20Scan%2020260411134726%22%7D%5D%2C%22layout%22%3A%224panel%22%7D
```

### curl (tested 2026-10-24)

```bash
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/.zattrs            # OME multiscales metadata
curl -s https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/4/.zarray     # one level: shape, chunks, dtype, codec
```
