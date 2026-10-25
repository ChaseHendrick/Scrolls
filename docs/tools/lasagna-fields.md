# lasagna-fields: villa's lasagna field for ten whole scans, and for any box of any public scan on demand

villa's lasagna field for ten whole scans that had none, as public datasets and a bucket, and a Space that runs villa's own lasagna on ZeroGPU for any box of any public scan, checked against a published field, from its page, API or MCP server.

| Field | Value |
| --- | --- |
| Id | `lasagna-fields` |
| Status | Current |
| Kind | data, app |
| Area | Data and downloads |
| Run | [huggingface.co/spaces/SharpMeow/lasagna-fields](https://huggingface.co/spaces/SharpMeow/lasagna-fields) (the page: Ten whole scans, Make a field, How-to guides, Agents and API), `Client("SharpMeow/lasagna-fields").predict(..., api_name="/make_field")` or the MCP server `https://sharpmeow-lasagna-fields.hf.space/gradio_api/mcp/` (a box), `hf download SharpMeow/SCAN-lasagna --repo-type dataset` (a whole scan), `zarr.open_array(URL)` on the bucket (stream), `python load_example.py` in a downloaded dataset |
| Code | `spaces/lasagna-fields/app.py` (the page, API and MCP tools), `spaces/lasagna-fields/lasfield.py` (`main`; the box, villa's run, the check, pictures and the download), `spaces/lasagna-fields/guide/index.html` (the Ten whole scans guide). The data lives on Hugging Face (ten datasets SharpMeow/SCAN-lasagna and the bucket SharpMeow/lasagna-fields); each dataset carries its own load_example.py, index.json and SHA256SUMS |
| Tests | `tests/test_lasagna_fields_space.py` (the box, villa's crop, the ZeroGPU worker fix, `lasfield.py selftest`); the data is checked by sha256sum -c SHA256SUMS in each dataset, and each dataset's load_example.py was run on the real parts before upload (dataset cards) |
| Needs | A browser for the page. `gradio_client` to call it from Python, any MCP client for agents, and a Hugging Face token for a field (it uses the caller's ZeroGPU time). `huggingface_hub[cli]` for downloads; `zarr` and `numpy` to read; for streaming, `zarr` 3 with `fsspec`, `aiohttp` and `requests`. villa's lasagna tools read the manifest and the downloaded box as is |
| Runs on | Make a field: the Space's ZeroGPU slice (A10G class); a 256 box took 21 to 27 s on 25 Oct 2026, a 512 box 60 s. Downloads and streaming: any machine with a network. Streaming one 256 x 256 patch of cos at level 1 from the bucket worked from a 4-core cloud container (2026-10-24; not timed). A whole scan is 32 to 82 GB to download |
| Network | `huggingface.co` and `sharpmeow-lasagna-fields.hf.space` (datasets, bucket, Space); the Space itself reads `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` |
| Writes | Downloads write where you point `--local-dir`; streaming writes nothing; a made field comes back as one zip (gradio_client saves it in its temp folder) |
| Go-ahead | Not needed to use. Making the datasets and Space public was Chase's yes (24 Oct 2026); turning the Space into the Make a field app was his yes on 25 Oct 2026; other changes to their cards or files need his yes per change, except redeploys under the standing yes (rule 8) |
| Released | Public on Hugging Face since 2026-10-24 (datasets, bucket and Space); Make a field since 2026-10-25 (Space 2.0.0); README "Released tools" entry `lasagna-fields` |
| License | CC BY-NC 4.0, the same as the scans they derive from; model and code are ScrollPrize/villa's lasagna, credit to its authors |
| Checked | 2026-10-24 against commit `76beeba` |

## What it does

villa's lasagna surface fitting, and the spiral fit that builds on it, read a lasagna field: the output of villa's lasagna model over a scan, with a cos channel (a signal that repeats once per papyrus layer), its gradient size (grad_mag) and the surface normals (nx, ny). The open data has such fields for only some scans. Predicting one for a whole scan takes a GPU for hours.

These datasets hold that field for ten whole scans that had none: PHerc0175A, PHerc0175B, PHerc0306B, PHerc0483A, PHerc0483B, PHerc0490A, PHerc0490B, PHerc0841, PHerc0846A and PHerc0846B. Each is in villa's own layout (`SCAN.lasagna.json` and four `SCAN_{cos,grad_mag,nx,ny}.ome.zarr` channels), so lasagna's tools open it without changes. The same fields sit unpacked in the public bucket SharpMeow/lasagna-fields, laid out like the open data (`SCAN/representations/predictions/lasagna/RUN/`), so any zarr reader can open them by URL.

They are raw model output that nobody has checked by eye. They are geometry inputs, not a reading of any text.

**Make a field** (since 25 Oct 2026) covers every other public scan, one box at a time. Pick a scan and a level-0 point; the Space reads the CT around the box from the open data (level 0 of 8.6 to 9.4 um scans, level 2 of 2.4 um scans, with a margin of one tile), calls villa's own `predict3d` in-process on ZeroGPU with the pinned commit and checkpoint, and returns three things: a picture of the middle slices, a receipt with the check below, and a zip with villa's output folder, `field.npz` and the receipt. Nothing is reimplemented, and the box's field is the field a whole-scan run makes there, because boxes are whole 256-voxel blocks on villa's own tile lattice.

![Making a field on the page: press the button, about half a minute later the picture and the check appear](https://huggingface.co/spaces/SharpMeow/lasagna-fields/resolve/main/media/howto-make.gif)

![PHerc0139, one box: the CT, cos and the normal, stepping through z](https://huggingface.co/spaces/SharpMeow/lasagna-fields/resolve/main/media/howto-slices.gif)

The pictures show PHerc0139, which is on no prize list; they live on the Space, not in this repository. The page's How-to guides tab walks through making a field, reading the result, picking a point, using the download, calling it from code and running villa yourself for bigger regions. A model slot (`list_models`) keeps room for a faster or better model as a second option, offered only after it passes a held-out test against villa's field.

## When to use it

- To run villa's lasagna fit or the spiral fit on one of these ten scans without predicting the field yourself.
- To read surface normals or the layer signal at any point of these scans, by URL, without a download.
- To get villa's field for one box of any other public scan without installing villa or renting a GPU: Make a field, on the page or from code.
- With a center line from [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) (every scan here but PHerc0841 has one; [centerline](centerline.md) gets it).

Do not use it:

- For a whole scan not in the list: run villa's lasagna yourself (How-to guides, section 6); the Space makes boxes of at most 512 voxels a side.
- As a check of the model: it is the model's output, not ground truth.

## Quick start

```bash
pip install -U "huggingface_hub[cli]" "zarr<3" numpy
hf download SharpMeow/pherc0175a-lasagna --repo-type dataset --local-dir pherc0175a-lasagna
cd pherc0175a-lasagna && sha256sum -c SHA256SUMS
for f in parts/*.tar; do tar -xf "$f"; done
tar -xf PHerc0175A-lasagna-pyramid-fix.tar   # last: it holds the joined manifest and level-4 pyramid
python load_example.py
```

Or stream a patch with no download (zarr 3, with `fsspec`, `aiohttp` and `requests`). BASE is the run folder URL in the "Stream it, no download" section of the [PHerc0175A dataset card](https://huggingface.co/datasets/SharpMeow/pherc0175a-lasagna):

```python
import zarr
base = "BASE"
cos = zarr.open_array(base + "/PHerc0175A_cos.ome.zarr/1", mode="r", zarr_format=2)
print(cos.shape, cos.dtype, cos.chunks)
patch = cos[3186, 2900:3156, 2200:2456]
print(patch.shape, int(patch.min()), int(patch.max()), round(float(patch.mean()), 1))
```

Run on 2026-10-24, it printed:

```text
(6374, 4682, 4682) uint8 (64, 64, 64)
(256, 256) 0 255 133.9
```

Make a field from Python (your token: the run uses your ZeroGPU time):

```python
from gradio_client import Client
c = Client("SharpMeow/lasagna-fields", token="hf_...")
pt = c.predict(api_name="/example_points")[0]
picture, receipt, zip_path = c.predict(pt["volume"], pt["z"], pt["y"], pt["x"], 256, "lasagna",
                                       api_name="/make_field")
print(receipt["timings"], receipt["agreement"]["same_box"])
```

Run on 2026-10-25 against the live Space, it printed:

```text
{'stage_s': 1.88, 'stage_bytes': 452984832, 'model_s': 18.12} {'cos_r': 1.0, 'grad_mag_r': 1.0, 'normal_median_deg': 1.12, 'voxels': 2084257, 'normal_median_deg_strong': 1.47}
```

It worked when `sha256sum -c` prints OK for every file, or the stream prints a shape of half the scan's size for cos at level 1. For another scan, swap the scan id; the run folder of each is on its dataset card and the Space.

## Checks and controls

Each field was checked for seams where the parts meet: the step across every tile edge against the steps nearby, with a limit of 1.5. The worst ratios were 1.106 to 1.36 on nine scans. PHerc0841 flagged 1.62 at z 1,024; one run across that edge gave output byte-identical to the joined parts, so the flag was cleared. Level 4 chunks that straddle a tile edge were rebuilt from the joined level 3 with villa's own `omezarr_pyramid` (dataset cards give the exact differences). Every file has a sha256 in `SHA256SUMS`.

There is no accuracy check here: these are the model's predictions, made with the same settings as villa's published fields. Whether another input scale works better was not tested.

Make a field checks every box it makes against a published field of the same scan: the open data's own lasagna run where there is one, else this Space's whole-scan field for the ten scans above. It reports Pearson r of cos and grad_mag and the median angle between normals, over every voxel and over the strong half (grad_mag at or above its median, where the normal is well defined), and the same numbers for a control: the published field read 48 input voxels away in y and x, a few papyrus layers off, which must agree less. Runs on 2026-10-25:

| Scan, point (z, y, x), box | Against | cos r | grad_mag r | normals, all / strong half | Control: cos r, normals all / strong |
| --- | --- | --- | --- | --- | --- |
| PHerc0139 20260102150214, (39424, 10752, 13824), 256, CPU | open data | 1.0 | 0.9998 | 1.26° / not measured | -0.023, 12.98° / not measured |
| PHerc0139 20260930100252, same point, 256, ZeroGPU | open data | 1.0 | 1.0 | 1.12° / 1.47° | -0.023, 13.0° / 12.58° |
| PHerc0139 20260930100252, (39424, 16896, 16896), 256 | open data | 1.0 | 1.0 | 17.06° / not measured | 0.079, 22.1° / not measured |
| PHerc0332 20251211183505, (16896, 7680, 4608), 512 | open data | 1.0 | 1.0 | 17.95° / 9.53° | -0.009, 28.4° / 23.55° |
| PHerc1667 20251217075048, (18944, 11776, 5632), 256 | open data | 1.0 | 1.0 | 0.03° / not measured | 0.161, 10.93° / not measured |
| PHerc0175A 20250521115057, (6400, 4608, 4608), 256 | this Space's field | 1.0 | 1.0 | 0.0° / 0.0° | not run |

Against this Space's own PHerc0175A field, made with the same villa commit and checkpoint, the box was byte-identical on 99.90% of cos voxels, 99.85% of grad_mag, 99.96% of nx and 99.98% of ny, with cos and grad_mag never more than 1 apart. Against the open data, cos and grad_mag match exactly but the normals of some boxes differ in bands while matching to 0° elsewhere in the same box. The open data's fields carry April 2026 run names, and villa's normal estimation code changed after that (commits touching `estimate_normal` between 2026-04-27 and 2026-08-01 in villa's history), so the likely cause is the code version, not this Space; the page says so when the strong-half angle is over 5°. That cause is an Interpretation: the April code was not rerun to prove it.

Claim label: Model output (the fields); Measurement (the seam ratios, hashes and the agreement numbers above).

## Commands and options

### Download

`hf download SharpMeow/SCAN-lasagna --repo-type dataset --local-dir DIR [--include PATTERN]`, where SCAN is the scan id in lower case. `--include "parts/003.tar"` and the like fetch only the parts a region needs; the Space's region tool writes the exact command for a point and size.

### Stream

`zarr.open_array(BASE + "/SCAN_CHANNEL.ome.zarr/LEVEL", mode="r", zarr_format=2)`, where BASE is the bucket run folder, CHANNEL is `cos`, `grad_mag`, `nx` or `ny`, and LEVEL is the OME-Zarr level (cos starts at level 1, the others at level 2).

### Make a field (page, API and MCP)

| Call | Arguments | Returns |
| --- | --- | --- |
| `/list_scans` | none | every open-data volume it can read, with the level the model reads |
| `/list_models` | none | the model slot: models, which are offered, what they were tested on |
| `/example_points` | none | ready points inside the papyrus of scans on no prize list |
| `/plan_field` | `volume, z, y, x, size=256, model="lasagna"` | the box (input level and level 0), the CT it reads, tiles, the GPU seconds it asks for, and the field it will be checked against; runs nothing |
| `/make_field` | the same | the picture (PNG), the receipt (JSON) and the zip |

`volume` is the 14-digit open-data volume id; z, y, x are level-0 voxels; `size` is 256 or 512. The same calls are MCP tools at `https://sharpmeow-lasagna-fields.hf.space/gradio_api/mcp/`. Locally, `python lasfield.py selftest` checks the parts that need neither network nor model, and `python lasfield.py run VOLUME Z Y X [SIZE]` makes one box on this machine (it needs villa's lasagna and the checkpoint; on 4 CPUs a 256 box took 958 s).

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| None for the data | | | Read the arrays with `zarr` or any OME-Zarr reader |
| `lasfield.plan(vid, z, y, x, size=256)` | dict: the box, reads, tiles, GPU ask | `FieldError` for a point outside the scan, a size not offered or an unknown volume | In `spaces/lasagna-fields/`; reads the open data's metadata |
| `lasfield.make(plan, device=None, work=None, out_root=None)` | dict: pictures, receipt, zip path | `FieldError` when villa fails or the field is empty | Runs villa's `predict3d` in this process |
| `lasfield.agreement(p, arrays, boxes)` | dict: `same_box`, `control_shifted` | never: errors are reported in the dict | The check above |

## Inputs

Nothing: the fields are ready made. They were made from each scan's masked level-0 volume in the open data (named on each card, 8.64 um for seven scans, 9.362 or 9.366 um for the PHerc0841 and PHerc0846 scans).

## Outputs

| File | Meaning |
| --- | --- |
| `SCAN.lasagna.json` | villa's lasagna manifest, with relative paths to the four channels |
| `SCAN_cos.ome.zarr` | cos, uint8, from level 1 (every 2nd scan voxel), with its pyramid |
| `SCAN_grad_mag.ome.zarr` | gradient size, uint8, from level 2 (every 4th scan voxel) |
| `SCAN_nx.ome.zarr`, `SCAN_ny.ome.zarr` | surface normal x and y, uint8 stored as v x 127 + 128, from level 2; nz is not stored, take sqrt(1 - nx^2 - ny^2) |
| `parts/NNN.tar` | the parts (boxes of the scan) as computed, one tar each |
| `SCAN-lasagna-pyramid-fix.tar` | the joined manifest and the rebuilt level-4 chunks; unpack it last |
| `index.json`, `SHA256SUMS`, `load_example.py` | part boxes, hashes and a runnable loading example |

A made field comes back as one zip, `SCAN-VOLUME-zZ-yY-xX-sSIZE.zip`:

| File | Meaning |
| --- | --- |
| `villa/` | villa's own output folder: `*.lasagna.json` and the four OME-Zarr channels, in the scan's coordinates with only the box written; lasagna's fit opens it as is |
| `field.npz` | the box's arrays: cos at half, grad_mag, nx and ny at a quarter of the input level's grid |
| `receipt.json` | the plan, villa commit, checkpoint and its SHA-256, the exact `predict3d` command line, timings and the check |
| `README.txt` | what the files are, and the licences |

Coordinates are the scan's own voxels (z, y, x), divided by 2 for cos and by 4 for the other channels. Regions the masked scan leaves empty are absent and read as 0.

| Exit code | Meaning |
| --- | --- |
| `0` | `sha256sum -c` found every file intact |
| `1` | A file failed its hash: download it again |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `HTTPFileSystem requires "requests" and "aiohttp"` | Streaming needs fsspec's HTTP back end | `pip install aiohttp requests` |
| `sha256sum` reports missing files | A partial download | Add `--ignore-missing` |
| The manifest names parts you did not unpack | The per-part manifests overwrote the joined one | Unpack the fix tar last |
| Arrays read as zeros | Outside the masked scan, or a part you did not download | Check the box in `index.json` |
| "ZeroGPU refused this run: You have exceeded your ZeroGPU runs limit" | Make a field uses the caller's ZeroGPU quota; logged-out visitors get very little | Sign in to Hugging Face, or pass a token to `gradio_client` |
| "the field is empty" | The box is outside the scroll, where the masked CT is all zero | Move the point into the papyrus |
| "the point ... is outside the scan" | The point is past the scan's level-0 shape | Use level-0 voxels, not a coarser level |
| "the model is still loading" | The Space has just woken up and is fetching villa and the checkpoint | Wait a minute and press again |
| Normals far apart in the check, cos r 1.0 | The open data's field was made with older villa normal code | Nothing to fix; see Checks and controls |

## How it works

Every step ran on Hugging Face Jobs from scripts, with each part's record kept and nothing edited by hand. Each scan was cut into parts whose edges sit on chunk lines for levels 1 to 3, and villa's lasagna at commit `db3dbea2` ran `lasagna-preprocess predict3d --tile-size 192` with default chunks and levels on each part, using the `scrollprize/lasagna` model `model_current.pt` at revision `de45f011`, on the scan at its native voxel size with no resampling. The parts were joined, level 4 rebuilt across tile edges, seams checked, and the result uploaded as the dataset and copied into the bucket.

## Cost and time

Make a field uses the caller's ZeroGPU quota: a 256 box asks for at most 72 s and used 15 to 22 s of model time on 25 Oct 2026, plus 1 to 5 s to read the CT; a 512 box asks for at most 151 s and used 37 s. The first call after the Space wakes also loads villa and the checkpoint, about a minute.

Downloads are free to use: users rent nothing. A whole scan is 32 to 82 GB (about 470 GB for all ten); a region needs only the parts it touches. Making them took GPU Jobs on RTX PRO 6000 cards, recorded in the private compute ledger.

## For agents

- **Make a field:** `Client("SharpMeow/lasagna-fields", token=TOKEN).predict(VOLUME, Z, Y, X, 256, "lasagna", api_name="/make_field")`, or the MCP tool `make_field`. Call `plan_field` first to see the box and GPU ask for free.
- **Parse it:** `receipt["agreement"]["same_box"]` and `["control_shifted"]`; success is cos r near 1.0 and a control far lower. The zip's `field.npz` holds the arrays.
- **Command:** `hf download SharpMeow/SCAN-lasagna --repo-type dataset --local-dir DIR`, then `sha256sum -c SHA256SUMS`; or open the bucket URL with `zarr.open_array`.
- **Parse:** the arrays; `index.json` gives each part's box in scan voxels.
- **Rerun:** Safe; a download skips files already there.
- **Success:** every hash OK, and arrays of half (cos) or a quarter (others) of the scan's shape.
- **Not a pass:** a field that loads is not a correct field; it is model output.
- **Go-ahead:** Nothing to use it. Any change to the datasets or Space needs Chase's yes.
- **Never:** call the field a reading, or rehost it without the CC BY-NC 4.0 terms and credit.

## Tests

`tests/test_lasagna_fields_space.py`: the box holds the point on whole 256-voxel blocks, villa's `--crop` is level-0 x y z, sizes and points outside are refused, the ten own fields match the card, `lasfield.py selftest` passes, and a worker pool starts inside a daemon process only with the ZeroGPU fix (the control: without it, the pool is refused). For the data, none in this repository: The datasets' `SHA256SUMS` and `load_example.py` are the checks; the streaming snippet above was run on 2026-10-24.

## History

- 2026-10-25: the page uses the window's width (up to 1600 px) and the ten scan previews load again; they had 404ed since 2.0.0 (`63a2d05`).
- 2026-10-25: Space 2.0.0 (Space commit `0640a74`), a Gradio app on ZeroGPU: Make a field for any box of any public scan with villa's own lasagna, checked against published fields; How-to guides with pictures; API, MCP server and Connect your tool panel (Chase's yes, 25 Oct 2026).
- 2026-10-24: all ten datasets, the bucket and the guide Space public; README "Released tools" entry added (`76beeba` is the commit this page was checked against).

## Related

- [umbilici](umbilici.md): its Lasagna tab shows a sample of the PHerc0175A field with the center line.
- [centerline](centerline.md): gets a center line for these scans.
