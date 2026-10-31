# lasagna-fields: whole-scan lasagna fields for 24 scrolls, listed by scroll, and villa's field for any box on demand

Whole-scan lasagna fields for 24 scrolls, listed by scroll (villa's own in the open data and 22 public datasets made with villa's lasagna or Lasagnetta 0.1.1), and a Space that runs villa's lasagna on ZeroGPU for any box of any public scan, from its page, API or MCP server.

| Field | Value |
| --- | --- |
| Id | `lasagna-fields` |
| Status | Current |
| Kind | data, app |
| Area | Data and downloads |
| Run | [huggingface.co/spaces/SharpMeow/lasagna-fields](https://huggingface.co/spaces/SharpMeow/lasagna-fields) (the page: Every field, Make a field, How-to guides, Agents and API), `Client("SharpMeow/lasagna-fields").predict(..., api_name="/make_field")` or the MCP server `https://sharpmeow-lasagna-fields.hf.space/gradio_api/mcp/` (a box), `hf download SharpMeow/SCAN-lasagna --repo-type dataset` (a whole scan), `zarr.open_array(URL)` on the bucket (stream), `python load_example.py` in a downloaded dataset |
| Code | `spaces/lasagna-fields/app.py` (the page, API and MCP tools), `spaces/lasagna-fields/lasfield.py` (`main`; the box, villa's run, the check, pictures and the download), `spaces/lasagna-fields/guide/index.html` (the Every field guide), `spaces/lasagna-fields/fields.json` (the list of every whole-scan field, by scroll, that the guide and `list_fields` read). The data lives on Hugging Face (datasets SharpMeow/SCAN-lasagna and SharpMeow/SCAN-lasagnetta, and the bucket SharpMeow/lasagna-fields for every one of them, unpacked so it streams by URL) and in the open data (villa's own fields); each dataset carries its own load_example.py, index.json and SHA256SUMS |
| Tests | `tests/test_lasagna_fields_space.py` (the box, villa's crop, the ZeroGPU worker fix, `lasfield.py selftest`, the field list); the data is checked by sha256sum -c SHA256SUMS in each dataset, and each dataset's load_example.py was run on the real parts before upload (dataset cards) |
| Needs | A browser for the page. `gradio_client` to call it from Python, any MCP client for agents, and a Hugging Face token for a field (it uses the caller's ZeroGPU time). `huggingface_hub[cli]` for downloads; `zarr` and `numpy` to read; for streaming, `zarr` 3 with `fsspec`, `aiohttp` and `requests`. villa's lasagna tools read the manifest and the downloaded box as is |
| Runs on | Make a field: the Space's ZeroGPU slice (A10G class); a 256 box took 21 to 27 s on 25 Oct 2026, a 512 box 60 s. Downloads and streaming: any machine with a network. Streaming one 256 x 256 patch of cos at level 1 from the bucket worked from a 4-core cloud container (2026-10-24; not timed). A whole-scan field is 0.4 to 136 GB to download |
| Network | `huggingface.co` and `sharpmeow-lasagna-fields.hf.space` (datasets, bucket, Space); the Space itself reads `vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com` |
| Writes | Downloads write where you point `--local-dir`; streaming writes nothing; a made field comes back as one zip (gradio_client saves it in its temp folder) |
| Go-ahead | Not needed to use. Making the datasets and Space public was Chase's yes (24 Oct 2026); turning the Space into the Make a field app was his yes on 25 Oct 2026; other changes to their cards or files need his yes per change, except redeploys under the standing yes (rule 8) |
| Released | Public on Hugging Face since 2026-10-24 (datasets, bucket and Space); Make a field since 2026-10-25 (Space 2.0.0); the list of every field since 2026-10-30 (Space 2.1.0); README "Released tools" entry `lasagna-fields` |
| License | CC BY-NC 4.0, the same as the scans they derive from; model and code are ScrollPrize/villa's lasagna, credit to its authors |
| Checked | 2026-10-24 against commit `76beeba` |

## What it does

villa's lasagna surface fitting, and the spiral fit that builds on it, read a lasagna field: the output of villa's lasagna model over a scan, with a cos channel (a signal that repeats once per papyrus layer), its gradient size (grad_mag) and the surface normals (nx, ny). The open data has such fields for only some scans. Predicting one for a whole scan takes a GPU for hours.

The Space's first tab, **Every field**, lists every whole-scan field it knows for 24 scrolls, one row per field, with the volume, voxel size, the level the model read, the model, where it lives, its size and four links (Dataset, Manifest, Preview and Copy URL, on every field): villa's own fields in the open data for seven scrolls on no prize list (linked, not copied), and 22 public datasets made here for scans that had none. Twelve of those were made with villa's lasagna model and ten with [Lasagnetta](lasagnetta.md) 0.1.1, a faster copy of it, whose fields are previews where exact values matter. The list is `spaces/lasagna-fields/fields.json`; `list_fields` returns it.

The first ten datasets hold villa's field for ten whole scans that had none: PHerc0175A, PHerc0175B, PHerc0306B, PHerc0483A, PHerc0483B, PHerc0490A, PHerc0490B, PHerc0841, PHerc0846A and PHerc0846B. Each is in villa's own layout (`SCAN.lasagna.json` and four `SCAN_{cos,grad_mag,nx,ny}.ome.zarr` channels), so lasagna's tools open it without changes. The same fields sit unpacked in the public bucket SharpMeow/lasagna-fields, laid out like the open data (`SCAN/representations/predictions/lasagna/RUN/`), so any zarr reader can open them by URL.

They are raw model output that nobody has checked by eye. They are geometry inputs, not a reading of any text.

**Make a field** (since 25 Oct 2026) covers every other public scan, one box at a time. Pick a scan and a level-0 point; the Space reads the CT around the box from the open data (level 0 of 8.6 to 9.4 um scans, level 2 of 2.4 um scans, with a margin of one tile), calls villa's own `predict3d` in-process on ZeroGPU with the pinned commit and checkpoint, and returns three things: a picture of the middle slices, a receipt with the check below, and a zip with villa's output folder, `field.npz` and the receipt. Nothing is reimplemented, and the box's field is the field a whole-scan run makes there, because boxes are whole 256-voxel blocks on villa's own tile lattice.

![Making a field on the page: press the button, about half a minute later the picture and the check appear](https://huggingface.co/spaces/SharpMeow/lasagna-fields/resolve/main/media/howto-make.gif)

![PHerc0139, one box: the CT, cos and the normal, stepping through z](https://huggingface.co/spaces/SharpMeow/lasagna-fields/resolve/main/media/howto-slices.gif)

The pictures show PHerc0139, which is on no prize list; they live on the Space, not in this repository. The page's How-to guides tab walks through making a field, reading the result, picking a point, using the download, calling it from code and running villa yourself for bigger regions. A model slot (`list_models`) keeps room for a faster or better model as a second option, offered only after it passes a held-out test against villa's field.

## When to use it

- To find whether a scroll already has a lasagna field, which model made it and where to get it: the Every field tab or `list_fields`.
- To run villa's lasagna fit or the spiral fit on one of these scans without predicting the field yourself.
- To read surface normals or the layer signal at any point of these scans, by URL, without a download.
- To get villa's field for one box of any other public scan without installing villa or renting a GPU: Make a field, on the page or from code.
- With a center line from [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) (every scan here but PHerc0841 has one; [centerline](centerline.md) gets it).

Do not use it:

- For a whole scan not in the list: run villa's lasagna (or Lasagnetta) yourself (How-to guides, section 6); the Space makes boxes of at most 512 voxels a side.
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
| `/list_fields` | `scroll=""` (part of a scroll name, or empty for all) | every whole-scan field the first tab lists: scroll, volume, zarr, voxel_um, read_level, model, source, made_by, bytes, url, dataset, manifest, stream (a run folder zarr reads by URL, or null), note |
| `/list_scans` | none | every open-data volume it can read, with the level the model reads |
| `/list_models` | none | the model slot: models, which are offered, what they were tested on |
| `/example_points` | none | ready points inside the papyrus of scans on no prize list |
| `/plan_field` | `volume, z, y, x, size=256, model="lasagna"` | the box (input level and level 0: `center_level0_zyx` is your point, `origin_level0_zyx` and `size_level0_zyx` the box), the CT it reads, tiles, the GPU seconds it asks for, and the field it will be checked against; runs nothing |
| `/make_field` | the same | the picture (PNG), the receipt (JSON) and the zip |

`volume` is the 14-digit open-data volume id; z, y, x are level-0 voxels; `size` is 256 or 512. The same calls are MCP tools at `https://sharpmeow-lasagna-fields.hf.space/gradio_api/mcp/`. Locally, `python lasfield.py selftest` checks the parts that need neither network nor model, and `python lasfield.py run VOLUME Z Y X [SIZE]` makes one box on this machine (it needs villa's lasagna and the checkpoint; on 4 CPUs a 256 box took 958 s).

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| None for the data | | | Read the arrays with `zarr` or any OME-Zarr reader |
| `app.list_fields(scroll="")` | list of dicts, one per field | never | In `spaces/lasagna-fields/`; reads `fields.json` |
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
| `README.txt` | what the files are, and the licenses |

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

- **List the fields:** `Client("SharpMeow/lasagna-fields").predict("PHerc0139", api_name="/list_fields")`, or the MCP tool `list_fields`.
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

`tests/test_lasagna_fields_space.py`: the box holds the point on whole 256-voxel blocks, villa's `--crop` is level-0 x y z, sizes and points outside are refused, the plan names the point `center_level0_zyx`, the ten own fields match the card, the field list (`fields.json`) is complete and sorted, links every dataset the card names, never names a held or target scroll, adds no scroll on a prize list beyond the ten listed since 24 Oct 2026, shows the fields being made without any link, reaches the guide whole with every element id used once, `list_fields` leaves the pending ones out, and Make a field names the listed dataset of a scan with no field to check against, the page carries the one-scroll fragment (`onescroll.html` in its head), the guide's frame has no fixed height and its code blocks grow instead of scrolling, the receipt and the download's file row grow after a run, `lasfield.py selftest` passes, and a worker pool starts inside a daemon process only with the ZeroGPU fix (the control: without it, the pool is refused). For the data, none in this repository: The datasets' `SHA256SUMS` and `load_example.py` are the checks; the streaming snippet above was run on 2026-10-24.

## History

- 2026-10-31: the guide's theme is set before the first paint: the reader's saved choice (the Theme button, `lf-theme`), else the theme the Space page was opened with (Gradio follows Hugging Face's `?__theme=`), else the system, so the guide matches the rest of the Space (Chase asked on 31 Oct for every Space to remember the reader's theme).
- 2026-10-30: Every field decluttered (`f853b64`; deployed with the twelve new Lasagnetta datasets as Space commit `9cbb7ec6`, from `main` `d8ed50e`). Four sections instead of nine: a calmer hero (its drawing, one line, the stats, two buttons; the guide's own nav is gone, since the Gradio tabs cover it), the field list (compact scroll cards that keep their pictures; a card with several fields shows its models, voxel sizes and sources and keeps its rows and their four links behind "Show the N fields"), one **Stream, download and load** section (pick one of the ten bucket fields, then tabs for Connect your tool, Whole scan, Only a region, Load in Python and Format, so long code shows only when asked for) and a short **About** with the limits and credit, How it was made and Cite folded. Code blocks wrap instead of scrolling sideways. The preview box and the Copied toast now open in the part of the guide's frame that is on screen (inside the Space they sat in the middle of the whole frame, out of sight).
- 2026-10-30: Every field shows one card per scroll with a preview picture, and the hero drawing again on every width ([#290](https://github.com/ChaseHendrick/Scrolls/pull/290)). Every field gets the same four links ([#293](https://github.com/ChaseHendrick/Scrolls/pull/293)): Dataset (the SharpMeow dataset, or the run folder in the open data's file browser), Manifest, Preview (its xy and xz pictures in a box over the page) and Copy URL. The twelve SharpMeow datasets that were only tar parts are unpacked into the bucket SharpMeow/lasagna-fields (`SCAN/representations/predictions/lasagna/VOLSTAMP-lasagnetta-0.1.1` or `VOLSTAMP-lasagna`), so each streams by URL with its own lasagna.json; villa's seven fields in the open data get xy and xz previews (`make_previews.py`). fields.json and `list_fields` add `preview_xy`, `preview_xz` and `browse`.
- 2026-10-30: Space 2.1.0 (`5c4ac6f`), approved by Chase on 30 Oct. The first tab becomes **Every field**: one row per whole-scan field for 24 scrolls, with volume, voxel size, read level, model, where, size and links, filterable by scroll and by model, from the new `fields.json` (villa's own fields in the open data for seven scrolls on no prize list, and the 22 public SharpMeow datasets, adding PHercMANBp, PHerc0343P, the five Lasagnetta 0.1.1 fields of 29 Oct and five of 30 Oct: PHerc0009B scans 20250820154339 and 20260319104112, PHerc0814 scans 20250804134230 (9.362 um) and 20260521123630 (1.129 um, read at level 3) and PHerc0841 scan 20260319124803, each kept by the release's self-check on its whole scan). Fields still being made are listed in one separate key, shown without links. A `list_fields` API and MCP tool returns the list, and Make a field names a scan's listed dataset when no field streams by URL to check against. The ten bucket fields keep their preview, streaming and region tools.
- 2026-10-27: one scroll bar (user decision, 27 October 2026): the page carries `onescroll.html`, which fits the guide's frame to the guide, so the page scrolls and the frame does not; the guide's code blocks grow instead of scrolling (wide lines still scroll sideways) and its tab buttons wrap on a phone; after a run, the receipt (Gradio's JSON stopped at 500 px) and the download's file row grow too. American spelling throughout: `plan_field`'s JSON and the receipt now name the point `center_level0_zyx` (receipts made before 27 Oct 2026 spell it the British way). Not deployed yet; made [PR #253](https://github.com/ChaseHendrick/Scrolls/pull/253).
- 2026-10-25: the page uses the window's width (up to 1600 px) and the ten scan previews load again; they had 404ed since 2.0.0 (`63a2d05`).
- 2026-10-25: Space 2.0.0 (Space commit `0640a74`), a Gradio app on ZeroGPU: Make a field for any box of any public scan with villa's own lasagna, checked against published fields; How-to guides with pictures; API, MCP server and Connect your tool panel (Chase's yes, 25 Oct 2026).
- 2026-10-24: all ten datasets, the bucket and the guide Space public; README "Released tools" entry added (`76beeba` is the commit this page was checked against).

## Related

- [umbilici](umbilici.md): its Lasagna tab shows a sample of the PHerc0175A field with the center line.
- [centerline](centerline.md): gets a center line for these scans.
