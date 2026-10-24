# lasagna-fields: villa's lasagna field for ten whole scans, ready to download or stream

Ten public Hugging Face datasets, a public bucket and a guide Space holding villa's lasagna `predict3d` output for ten whole scans that had no lasagna field in the open data, so lasagna's fit and the spiral fit can start without a GPU run.

| Field | Value |
| --- | --- |
| Id | `lasagna-fields` |
| Status | Current |
| Kind | data, app |
| Area | Data and downloads |
| Run | [huggingface.co/spaces/SharpMeow/lasagna-fields](https://huggingface.co/spaces/SharpMeow/lasagna-fields) (the guide page), `hf download SharpMeow/SCAN-lasagna --repo-type dataset` (a whole scan), `zarr.open_array(URL)` on the bucket (stream), `python load_example.py` in a downloaded dataset |
| Code | None in this repository: the data lives on Hugging Face (ten datasets SharpMeow/SCAN-lasagna, the bucket and the Space, both named SharpMeow/lasagna-fields); each dataset carries its own load_example.py, index.json and SHA256SUMS. This page is the public record |
| Tests | None here: the data is checked by sha256sum -c SHA256SUMS in each dataset, and each dataset's load_example.py was run on the real parts before upload (dataset cards) |
| Needs | `huggingface_hub[cli]` for downloads; `zarr` and `numpy` to read; for streaming, `zarr` 3 with `fsspec`, `aiohttp` and `requests`. villa's lasagna tools read the manifest as is |
| Runs on | Any machine with a network. Streaming one 256 x 256 patch of cos at level 1 from the bucket worked from a 4-core cloud container (2026-10-24; not timed). A whole scan is 32 to 82 GB to download |
| Network | `huggingface.co` (datasets, bucket, Space) |
| Writes | Downloads write where you point `--local-dir`; streaming writes nothing |
| Go-ahead | Not needed to use. Making the datasets and Space public was Chase's yes (24 Oct 2026); changing their cards or files needs his yes per change, except redeploys under the standing yes (rule 8) |
| Released | Public on Hugging Face since 2026-10-24 (datasets, bucket and Space); README "Released tools" entry `lasagna-fields` |
| License | CC BY-NC 4.0, the same as the scans they derive from; model and code are ScrollPrize/villa's lasagna, credit to its authors |
| Checked | 2026-10-24 against commit `76beeba` |

## What it does

villa's lasagna surface fitting, and the spiral fit that builds on it, read a lasagna field: the output of villa's lasagna model over a scan, with a cos channel (a signal that repeats once per papyrus layer), its gradient size (grad_mag) and the surface normals (nx, ny). The open data has such fields for only some scans. Predicting one for a whole scan takes a GPU for hours.

These datasets hold that field for ten whole scans that had none: PHerc0175A, PHerc0175B, PHerc0306B, PHerc0483A, PHerc0483B, PHerc0490A, PHerc0490B, PHerc0841, PHerc0846A and PHerc0846B. Each is in villa's own layout (`SCAN.lasagna.json` and four `SCAN_{cos,grad_mag,nx,ny}.ome.zarr` channels), so lasagna's tools open it without changes. The same fields sit unpacked in the public bucket SharpMeow/lasagna-fields, laid out like the open data (`SCAN/representations/predictions/lasagna/RUN/`), so any zarr reader can open them by URL.

They are raw model output that nobody has checked by eye. They are geometry inputs, not a reading of any text.

## When to use it

- To run villa's lasagna fit or the spiral fit on one of these ten scans without predicting the field yourself.
- To read surface normals or the layer signal at any point of these scans, by URL, without a download.
- With a center line from [SharpMeow/vesuvius-center-lines](https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines) (every scan here but PHerc0841 has one; [centerline](centerline.md) gets it).

Do not use it:

- On a scan not in the list: predict the field with villa's lasagna, or use the field the open data already has.
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

It worked when `sha256sum -c` prints OK for every file, or the stream prints a shape of half the scan's size for cos at level 1. For another scan, swap the scan id; the run folder of each is on its dataset card and the Space.

## Checks and controls

Each field was checked for seams where the parts meet: the step across every tile edge against the steps nearby, with a limit of 1.5. The worst ratios were 1.106 to 1.36 on nine scans. PHerc0841 flagged 1.62 at z 1,024; one run across that edge gave output byte-identical to the joined parts, so the flag was cleared. Level 4 chunks that straddle a tile edge were rebuilt from the joined level 3 with villa's own `omezarr_pyramid` (dataset cards give the exact differences). Every file has a sha256 in `SHA256SUMS`.

There is no accuracy check here: these are the model's predictions, made with the same settings as villa's published fields. Whether another input scale works better was not tested.

Claim label: Model output (the fields); Measurement (the seam ratios and hashes).

## Commands and options

### Download

`hf download SharpMeow/SCAN-lasagna --repo-type dataset --local-dir DIR [--include PATTERN]`, where SCAN is the scan id in lower case. `--include "parts/003.tar"` and the like fetch only the parts a region needs; the Space's region tool writes the exact command for a point and size.

### Stream

`zarr.open_array(BASE + "/SCAN_CHANNEL.ome.zarr/LEVEL", mode="r", zarr_format=2)`, where BASE is the bucket run folder, CHANNEL is `cos`, `grad_mag`, `nx` or `ny`, and LEVEL is the OME-Zarr level (cos starts at level 1, the others at level 2).

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| None | | | Read the arrays with `zarr` or any OME-Zarr reader |

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

## How it works

Every step ran on Hugging Face Jobs from scripts, with each part's record kept and nothing edited by hand. Each scan was cut into parts whose edges sit on chunk lines for levels 1 to 3, and villa's lasagna at commit `db3dbea2` ran `lasagna-preprocess predict3d --tile-size 192` with default chunks and levels on each part, using the `scrollprize/lasagna` model `model_current.pt` at revision `de45f011`, on the scan at its native voxel size with no resampling. The parts were joined, level 4 rebuilt across tile edges, seams checked, and the result uploaded as the dataset and copied into the bucket.

## Cost and time

Free to use: users rent nothing. A whole scan is 32 to 82 GB (about 470 GB for all ten); a region needs only the parts it touches. Making them took GPU Jobs on RTX PRO 6000 cards, recorded in the private compute ledger.

## For agents

- **Command:** `hf download SharpMeow/SCAN-lasagna --repo-type dataset --local-dir DIR`, then `sha256sum -c SHA256SUMS`; or open the bucket URL with `zarr.open_array`.
- **Parse:** the arrays; `index.json` gives each part's box in scan voxels.
- **Rerun:** Safe; a download skips files already there.
- **Success:** every hash OK, and arrays of half (cos) or a quarter (others) of the scan's shape.
- **Not a pass:** a field that loads is not a correct field; it is model output.
- **Go-ahead:** Nothing to use it. Any change to the datasets or Space needs Chase's yes.
- **Never:** call the field a reading, or rehost it without the CC BY-NC 4.0 terms and credit.

## Tests

None in this repository. The datasets' `SHA256SUMS` and `load_example.py` are the checks; the streaming snippet above was run on 2026-10-24.

## History

- 2026-10-24: all ten datasets, the bucket and the guide Space public; README "Released tools" entry added (`76beeba` is the commit this page was checked against).

## Related

- [umbilici](umbilici.md): its Lasagna tab shows a sample of the PHerc0175A field with the center line.
- [centerline](centerline.md): gets a center line for these scans.
