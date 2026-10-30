"""Lasagna Fields: every whole-scan lasagna field, listed by scroll, or villa's field made for any box of a public scan.

The web page and the API. The guide to the whole-scan fields is guide/index.html, shown in the first tab, with its
list read from fields.json (villa's fields in the open data and the public SharpMeow datasets); making
a field (reading the CT, villa's predict3d, the check against the published field, pictures and the download) is
lasfield.py. On a ZeroGPU Space the GPU is attached only to `gpu_run`, for the model call alone: the CT is read
before it and the field is read back after it, so a visitor's GPU time goes to the model.
  python3 app.py            serve the page (on a Space, or on any computer: CUDA if present, else the CPU, slowly)
"""
import collections
import functools
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
try:
    import spaces  # first, before torch: on a ZeroGPU Space it attaches the GPU to spaces.GPU functions
except ImportError:
    spaces = None
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import lasfield as L  # noqa: E402
from lasfield import FieldError  # noqa: E402

VERSION = "2.1.0"
ON_ZERO_GPU = bool(spaces) and os.environ.get("SPACES_ZERO_GPU", "").lower() in ("1", "true")
WORK = Path(tempfile.gettempdir()) / "lasagna-fields-work"
OUT = Path(tempfile.gettempdir()) / "lasagna-fields-out"
GUIDE = HERE / "guide" / "index.html"
FIELDS = HERE / "fields.json"        # every whole-scan field the first tab lists, by scroll
MEDIA = HERE / "media"
CONNECT_HTML = HERE / "connect.html"
MAX_GPU_S = 240                     # the longest call this Space asks ZeroGPU for (a 512 box asks about 150 s)
READY = threading.Event()
SETUP = {"error": None, "code": None, "checkpoint": None, "seconds": None}

# Points inside the papyrus of public scans that are on no prize list (kit/data/prizes-2026-10-11.json): the 256-voxel
# blocks where each scan's published lasagna field is densest at mid-height (25 Oct 2026); z, y, x in level-0 voxels.
EXAMPLES = [
    {"label": "PHerc0139 (2.4 um), mid-height", "volume": "20260930100252", "z": 39424, "y": 10752, "x": 13824},
    {"label": "PHerc0332, Scroll 3 (2.4 um)", "volume": "20251211183505", "z": 16896, "y": 7680, "x": 4608},
    {"label": "PHerc1667, Scroll 4 (2.4 um)", "volume": "20251217075048", "z": 18944, "y": 11776, "x": 5632},
    {"label": "PHerc. Paris 3, Scroll 2 (2.4 um)", "volume": "20260427095331", "z": 34304, "y": 28160, "x": 17920},
    {"label": "PHerc0139 (2.4 um), near the core", "volume": "20260930100252", "z": 39424, "y": 16896, "x": 16896},
]


def log(message):
    L.log(message)


# ---------------------------------------------------------------- start-up

def _setup():
    """villa's code and the checkpoint, in the background, so the page answers while they download."""
    t = time.time()
    try:
        SETUP["code"] = L.ensure_villa()
        SETUP["checkpoint"] = str(L.ensure_weights())
        import preprocess_cos_omezarr  # noqa: F401  (fail here, not in a visitor's run)
        SETUP["seconds"] = round(time.time() - t, 1)
        log(f"villa {L.VILLA['commit'][:12]} and the checkpoint ready in {SETUP['seconds']} s")
    except Exception as exc:  # noqa: BLE001  (shown to visitors who try to make a field)
        SETUP["error"] = f"{type(exc).__name__}: {exc}"
        log(f"set-up failed: {SETUP['error']}")
    finally:
        READY.set()


def startup():
    for folder in (WORK, OUT):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
    try:
        log(f"{len(L.catalog())} volumes in the open data; ZeroGPU {'on' if ON_ZERO_GPU else 'off'}")
    except FieldError as exc:
        log(f"scan list not loaded yet: {exc}")
    threading.Thread(target=_setup, name="setup", daemon=True).start()


def ready(wait_s=5.0):
    if not READY.wait(wait_s):
        raise FieldError("the model is still loading (about a minute after the Space wakes up); try again shortly")
    if SETUP["error"]:
        raise FieldError(f"the model failed to load: {SETUP['error']}")


# ---------------------------------------------------------------- the one GPU call

def _gpu_duration(p, ct_input, out_dir, checkpoint):
    return int(min(MAX_GPU_S, max(30, p["gpu_s"])))


def _on_gpu(fn):
    return spaces.GPU(duration=_gpu_duration)(fn) if ON_ZERO_GPU else fn


@_on_gpu
def gpu_run(p, ct_input, out_dir, checkpoint):
    """The chosen model on the staged box, on the GPU ZeroGPU attaches for this call."""
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return L.MODELS[p["model"]]["run"](p, ct_input, out_dir, device, checkpoint)


# ZeroGPU's refusals, by the titles the spaces package gives them (as Scroll Lens reads them)
GPU_REFUSALS = ("ZeroGPU quota exceeded", "ZeroGPU illegal duration", "ZeroGPU pending credits exceeded",
                "ZeroGPU queue timeout", "ZeroGPU client error")


def _gpu_text(exc):
    return str(getattr(exc, "message", None) or exc).strip().strip("'\"").strip()


RUNNING = collections.Counter()
RUN_LOCK = threading.Lock()


def client_of(request):
    if request is None:
        return None
    user = getattr(request, "username", None)
    if user:
        return f"user:{user}"
    headers = getattr(request, "headers", None) or {}
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[-1].strip()
    host = getattr(getattr(request, "client", None), "host", "") or ""
    return forwarded or host or getattr(request, "session_hash", None)


class one_run:
    """One field at a time per visitor or caller, so one script cannot hold the GPU and the queue for everyone."""

    def __init__(self, request):
        self.key = client_of(request)

    def __enter__(self):
        with RUN_LOCK:
            if self.key and RUNNING[self.key] >= 1:
                raise FieldError("you already have a field being made; wait for it to finish (one at a time)")
            RUNNING[self.key] += 1

    def __exit__(self, *exc):
        with RUN_LOCK:
            RUNNING[self.key] -= 1
            if RUNNING[self.key] <= 0:
                del RUNNING[self.key]
        return False


def run_field(p, progress=None):
    """Stage the CT, run the model on the GPU, read the field back. Returns lasfield.finish's result."""
    ready()
    work = Path(tempfile.mkdtemp(prefix="run-", dir=WORK))
    try:
        if progress:
            progress(0.05, desc=f"Reading {p['chunks']} CT chunks from the open data")
        stage = L.stage(p, work / "ct")
        prep = {"code": SETUP["code"], "checkpoint": SETUP["checkpoint"], "stage": stage}
        if progress:
            progress(0.35, desc=f"Running villa lasagna on {p['tiles']} tiles (GPU up to {_gpu_duration(p, 0, 0, 0)} s)")
        try:
            ran = gpu_run(p, stage["input"], str(work / "out"), SETUP["checkpoint"])
        except Exception as exc:  # noqa: BLE001
            title = str(getattr(exc, "title", "") or "")
            if title in GPU_REFUSALS or "No GPU was available" in str(exc):
                raise FieldError(f"ZeroGPU refused this run: {_gpu_text(exc)[:300]} ZeroGPU time comes back each "
                                 "day, and signing in to Hugging Face gives more. Bigger jobs: see How-to guides, "
                                 "Run it yourself.") from None
            if title == "ZeroGPU worker error":
                raise FieldError(f"the model failed on the GPU: {_gpu_text(exc)[:300]}") from None
            raise
        if progress:
            progress(0.85, desc="Reading the field, checking it against the published one, drawing")
        out = L.finish(p, prep, ran, work, Path(tempfile.mkdtemp(prefix="dl-", dir=OUT)))
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- what the page and the API show

def volume_choices():
    try:
        vols = L.catalog()
    except FieldError:
        return [(f"{e['label'].split(',')[0]} {e['volume']}", e["volume"]) for e in EXAMPLES[:1]]
    rows = sorted(vols.values(), key=lambda v: (v["sample"], -v["voxel_um"], v["volume"]))
    return [(f"{v['sample']} · {v['voxel_um']:g} um · {v['volume']}"
             + (" (superseded)" if v.get("superseded_by") else ""), v["volume"]) for v in rows]


def volume_text(vid):
    try:
        v = L.volume(vid)
    except FieldError as exc:
        return f"⚠ {exc}"
    shape = v.get("shape_zyx") or ["?"] * 3
    f = 2 ** v["level"]
    pub = L.published_field(v)
    if pub and pub.get("source") == "lasagna-fields":
        pub_line = "This Space has a whole-scan field for this scan, so each box is checked against it."
    elif pub:
        pub_line = "The open data has villa's field for this scan, so each box is checked against it."
    else:
        listed = [f for f in field_doc().get("fields", []) if f["volume"] == v["volume"] and f.get("dataset")]
        pub_line = ("Boxes are checked only against the open data's fields and the ten in the Preview tab, so there is "
                    "nothing to check against for this scan."
                    + (f" Its whole-scan field ({listed[0]['model']}) is on the Every field tab as "
                       f"{listed[0]['dataset']}." if listed else ""))
    return (f"{' × '.join(map(str, shape))} voxels (z × y × x) at {v['voxel_um']:g} um. The model reads level "
            f"{v['level']} ({v['voxel_um'] * f:.2f} um), nearest to the 9.4 um it was trained at. {pub_line}")


def estimate_text(vid, z, y, x, size):
    try:
        p = L.plan(vid, z, y, x, int(size))
    except (FieldError, ValueError, TypeError) as exc:
        return f"⚠ {exc}"
    f = 2 ** p["level"]
    mb = p["chunks"] * p["chunk_bytes"] / 1e6
    um = p["voxel_um"] * f
    return (f"Box: {p['size_zyx'][0]} × {p['size_zyx'][1]} × {p['size_zyx'][2]} voxels at level {p['level']} "
            f"(about {p['size_zyx'][2] * um / 1000:.1f} mm a side), from level-0 voxel "
            f"({', '.join(map(str, p['origin_level0_zyx']))}). It reads up to {mb:,.0f} MB of CT and runs "
            f"{p['tiles']} model tiles; it asks ZeroGPU for {_gpu_duration(p, 0, 0, 0)} s at most and uses less.")


def result_text(r):
    rec = r["receipt"]
    p = rec["plan"]
    t = rec["timings"]
    a = rec["agreement"]
    lines = [f"**Done.** {p['sample']} {p['volume']}, box of {p['size_zyx'][0]}³ at level {p['level']}: "
             f"CT read in {t['stage_s']:.0f} s ({t['stage_bytes'] / 1e6:,.0f} MB), model in {t['model_s']:.0f} s."]
    same = a.get("same_box")
    if same:
        ctl = a.get("control_shifted") or {}

        def fmt(v, unit=""):
            return "n/a" if v is None else f"{v}{unit}"
        where = ("this Space's whole-scan field" if a.get("published_source") == "lasagna-fields"
                 else "the open data's field")
        lines.append(
            f"\n**Check against {where}** (`" + a["published"] + "`): "
            f"cos r = {fmt(same['cos_r'])}, grad_mag r = {fmt(same['grad_mag_r'])}, normals "
            f"{fmt(same.get('normal_median_deg_strong'), '°')} apart where the layer signal is strong "
            f"({fmt(same['normal_median_deg'], '°')} over every voxel; medians). Control, the same field "
            f"{L.CONTROL_SHIFT} voxels away: cos r = {fmt(ctl.get('cos_r'))}, normals "
            f"{fmt(ctl.get('normal_median_deg_strong'), '°')}. The same box should agree far better than the control.")
        if a.get("normals_note") and (same.get("normal_median_deg_strong") or 0) > 5:
            lines.append(f"\n{a['normals_note']}.")
    elif a.get("note") or a.get("error"):
        lines.append(f"\nCheck: {a.get('note') or a.get('error')}")
    lines.append("\nThe download holds villa's own output folder (open `villa/*.lasagna.json` with lasagna's fit), "
                 "`field.npz` for numpy, and `receipt.json`. Model output: geometry, not a reading of any text.")
    return "\n".join(lines)


# ---------------------------------------------------------------- API (also the MCP tools)

def list_scans():
    """List the scans this Space can make a lasagna field for.

    Every volume of the Vesuvius Challenge open data (its metadata.json) except PHercParis4, with its voxel size,
    shape, and the CT level the model reads. Returns a list of {volume, sample, voxel_um, shape_zyx, level, url}.
    """
    return [{k: v[k] for k in ("volume", "sample", "voxel_um", "shape_zyx", "level", "url")}
            for v in sorted(L.catalog().values(), key=lambda v: (v["sample"], v["volume"]))]


@functools.lru_cache(maxsize=1)
def field_doc():
    """fields.json: the whole-scan fields the first tab lists ({"fields": [...]}, and any not public yet)."""
    try:
        return json.loads(FIELDS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(f"fields.json not read: {exc}")
        return {"fields": []}


def list_fields(scroll: str = ""):
    """List every whole-scan lasagna field this Space lists, one row per field, sorted by scroll.

    villa's own fields in the Vesuvius Challenge open data and the public SharpMeow datasets (made with villa's
    lasagna predict3d or with Lasagnetta 0.1.1, a faster copy of it). Args: scroll, part of a scroll name to keep
    only its fields (empty for all). Returns a list of {scroll, volume, zarr, voxel_um, read_level, model, source,
    made_by, bytes, url, dataset, manifest, stream, preview_xy, preview_xz, browse, note}: stream is the run folder
    that zarr reads by URL, manifest its lasagna.json, preview_xy and preview_xz pictures of cos and normals, and
    browse the page to download it from (the dataset, or the open data's file browser).
    """
    keep = ("scroll", "volume", "zarr", "voxel_um", "read_level", "model", "source", "made_by", "bytes", "url",
            "dataset", "manifest", "stream", "preview_xy", "preview_xz", "browse", "note")
    q = str(scroll or "").strip().lower()
    return [{k: f.get(k) for k in keep} for f in field_doc().get("fields", []) if q in f["scroll"].lower()]


def field_counts():
    rows = field_doc().get("fields", [])
    return {"scrolls": len({f["scroll"] for f in rows}), "fields": len(rows),
            "made_here": sum(f["source"] == "dataset" for f in rows)}


def list_models():
    """List the models that can make a field, and which are offered now.

    'lasagna' is villa's own lasagna predict3d with the scrollprize/lasagna checkpoint. Other entries (a faster
    student, a better net) appear here, with offered false, until they pass their held-out tests.
    """
    return [{"id": k, "title": m["title"], "offered": m["offered"], "about": m["about"]} for k, m in L.MODELS.items()]


def example_points():
    """Points inside the papyrus of public scans on no prize list, ready to pass to make_field.

    Returns a list of {label, volume, z, y, x}; z, y, x are level-0 (full resolution) voxels.
    """
    return EXAMPLES


def plan_field(volume: str, z: float, y: float, x: float, size: float = 256, model: str = "lasagna"):
    """Say what make_field would do for a point, without running anything.

    Args:
        volume: the open-data volume id (14 digits), such as 20260102150214 (PHerc0139, 2.4 um); see list_scans.
        z: the point's z in level-0 (full resolution) voxels of that volume.
        y: the point's y in level-0 voxels.
        x: the point's x in level-0 voxels.
        size: the box side in voxels of the level the model reads, 256 or 512; the box is whole 256-voxel blocks.
        model: a model id from list_models; 'lasagna' is villa's own.

    Returns the box (origin and size at the input level and at level 0), the CT chunks it reads, the model tiles,
    the GPU seconds it asks for, and the published field it will be checked against, if any.
    """
    p = L.plan(volume, z, y, x, int(size), model=model)
    pub = L.published_field(L.volume(p["volume"]))
    return dict(p, gpu_ask_s=_gpu_duration(p, 0, 0, 0), published=pub["run"] if pub else None)


def make_field(volume: str, z: float, y: float, x: float, size: float = 256, model: str = "lasagna",
               request=None, progress=None):
    """Make villa's lasagna field (cos, grad_mag, nx, ny) for the box around one point of a public scan.

    Args:
        volume: the open-data volume id (14 digits), such as 20260102150214 (PHerc0139, 2.4 um); see list_scans.
        z: the point's z in level-0 (full resolution) voxels of that volume.
        y: the point's y in level-0 voxels.
        x: the point's x in level-0 voxels.
        size: the box side in voxels of the level the model reads, 256 or 512.
        model: a model id from list_models; 'lasagna' is villa's own predict3d.

    Returns a picture (middle slices along z, y and x: CT, cos, grad_mag, normals as color), the receipt (the
    box, the model and its pinned commit and checkpoint, timings, and the agreement with the open data's own field
    with a shifted control), and a zip with villa's output folder, field.npz and receipt.json. Uses the caller's
    ZeroGPU time. Model output: geometry, not a reading.
    """
    p = L.plan(volume, z, y, x, int(size), model=model)
    with one_run(request):
        r = run_field(p, progress)
    c = p["center_level0_zyx"]
    pic = L.compose(r["pictures"], f"{p['sample']} · {p['size_zyx'][0]}-voxel box at z {c[0]}, y {c[1]}, x {c[2]}")
    return pic, r["receipt"], r["zip"]


# ---------------------------------------------------------------- the page

INTRO = """\
Pick a scan and a point: the Space runs **villa's own lasagna model** on the box around it, checks the result
against the field the open data already publishes for that scan, and gives you pictures and a download in villa's
layout. New here? Start with the example and press **Make the field**.
"""

ABOUT_MODEL = """\
**villa lasagna (exact)** runs villa's own code, `lasagna/preprocess_cos_omezarr.py predict3d` at commit
`{commit}`, with the `scrollprize/lasagna` checkpoint (SHA-256 `{sha}`), both MIT. Nothing is reimplemented: the
Space reads the CT around your box into villa's layout and calls villa's command line in-process.

**Coming later, in the same slot:** faster or better models, once each passes a held-out test against villa's
field. Each will be marked here with what it was tested on.
"""

HOW_TO = """\
<p class="lf-toc">Guides: <a href="#what">What a lasagna field is</a> · <a href="#first">Make your first field</a> ·
<a href="#read">Read the result</a> · <a href="#point">Pick your own point</a> · <a href="#download">Use the
download</a> · <a href="#agents">Call it from code or an agent</a> · <a href="#yourself">Run it yourself</a> ·
<a href="#wrong">When something goes wrong</a></p>

<h3 id="what">What a lasagna field is</h3>

A scroll's CT shows papyrus layers rolled and squashed together. villa's lasagna model turns the CT into a smooth
field that surface tools can follow: **cos** goes once from bright to dark and back per papyrus layer, so counting
bands counts layers; **grad_mag** says how sharply cos changes (how tightly the layers are packed); the **normal**
says which way the sheet faces at each point. villa's lasagna surface fit and the spiral fit read these channels.

![The CT of one box of PHerc0139 next to villa's lasagna field, stepping through the box](/gradio_api/file=media/howto-slices.gif)

*PHerc0139 (not on any prize list), one box about 2.5 mm a side: the CT, cos and the normal as color, stepping
through z. Model output: geometry, not a reading of any text.*

<h3 id="first">1. Make your first field (one minute)</h3>

1. Open **Make a field**. It starts on an example point in PHerc0139; more examples are in the first list.
2. Press **Make the field**. The Space reads about 450 MB of CT from the open data, then runs villa's model on the
   GPU for about 20 seconds. The first run after the Space wakes up also loads the model (about a minute).
3. The picture, the check and the download appear on the right.

![Making a field on this page: press the button, wait about half a minute, read the check](/gradio_api/file=media/howto-make.gif)

<h3 id="read">2. Read the result</h3>

![A result: three rows of slices, each row CT, cos, grad_mag and normal](/gradio_api/file=media/example-result.png)

- **Rows** are the middle slice of your box along z, y and x. **Columns** are the CT, cos, grad_mag and the
  normal as color (red for x, green for y, blue for z).
- **cos** should run along the papyrus in the CT, one bright and one dark band per layer. Where layers touch or
  the CT is unclear, the bands bend or merge: that is where surface tracing is hard too.
- **The check** compares your field with the published one for the same box, and with a **control**: the same
  published field read 48 voxels away. A correct run gives cos r = 1.0 and grad_mag r = 1.0 for the same box and
  near 0 for the control.
- **Normals** are compared where the layer signal is strong; where it is weak the normal is barely defined. On the
  open data's fields they can differ in parts of a box, because villa changed how lasagna estimates normals after
  those fields were made (April 2026, by their run names). This Space runs the later code, the same as the ten
  whole-scan fields in its bucket; on PHerc0175A it matched that field on 99.9% of voxels, with a median normal angle of 0°.

![The check under a result](/gradio_api/file=media/howto-check.png)

<h3 id="point">3. Pick your own point</h3>

1. Find a point inside the papyrus in the [Vesuvius Challenge data browser](https://scrollprize.org/data_browser/),
   VC3D or neuroglancer, in full-resolution (level 0) voxels: z, then y, then x.
2. Choose the same scan in **Scan**: type part of the scroll name or the 14-digit volume id to filter the list.
3. Type the point. The line under the button says the box it will make, how much CT it reads, how many model
   tiles it runs and how much GPU time it asks.
4. Choose **256** (about 2.5 mm a side at 9.4 um) or **512** (eight times the volume, about a minute of GPU).

![Choosing a scan, a point and a box size](/gradio_api/file=media/howto-point.png)

Boxes are whole 256-voxel blocks of the scan, because villa writes the field in 64-voxel chunks of its quarter
grid and puts its tiles on one lattice over the whole scan: that is why a box's field is the whole-scan field
there. The box is the block nearest your point, so your point is inside it but not always at its center.

<h3 id="download">4. Use the download</h3>

The zip holds three things:

| Item | What it is | Open it with |
| --- | --- | --- |
| `villa/` | villa's own output folder: `*.lasagna.json` and four OME-Zarr channels, in the scan's coordinates with only your box written | lasagna's fit, as you would a published run |
| `field.npz` | the box's four arrays (cos at half, the others at a quarter of the input level's grid) | numpy |
| `receipt.json` | the plan, villa commit, checkpoint hash, timings and the check | any JSON reader |

```bash
unzip PHerc0139-*.zip -d box && cd box
python - <<'EOF'
import numpy as np, json
f = np.load("field.npz"); r = json.load(open("receipt.json"))
print({k: f[k].shape for k in f}, r["boxes"])
nx, ny = (f["nx"] - 128) / 127, (f["ny"] - 128) / 127        # normals are stored as v x 127 + 128
EOF
```

<h3 id="agents">5. Call it from code or an agent</h3>

The page is also an API and an MCP server. See **Agents and API** for the calls, a Python example and the MCP
address. An agent can list the scans, plan a box without running it, then make it, and read the check from the
receipt. Each field uses the caller's own ZeroGPU time.

<h3 id="yourself">6. Run it yourself, for big regions or whole scans</h3>

The Space is for boxes. For a whole scan, run villa's lasagna on a GPU of your own or a cloud job:

```bash
git clone https://github.com/ScrollPrize/villa && cd villa/lasagna
python scripts/bootstrap_venv.py --venv .venv
.venv/bin/lasagna-preprocess predict3d --input SCAN.zarr/0 --output SCAN.lasagna.json \\
    --unet-checkpoint model_current.pt --device cuda
```

Measured on an NVIDIA L4 (25 Oct 2026): about 2 million voxels a second end to end, so about ten minutes per
cubic centimeter at 9.4 um. It fits in 5.6 GB of GPU memory at its default tile, 2.3 GB at `--tile-size 128`.

<h3 id="wrong">When something goes wrong</h3>

| What you see | What to do |
| --- | --- |
| "ZeroGPU refused this run" | Your ZeroGPU time or runs are used up; visitors who are not signed in get very little. Sign in to Hugging Face for more, or come back tomorrow. |
| "the field is empty" | The box is outside the scroll, where the masked CT is all zero. Move the point toward the papyrus. |
| "the point is outside the scan" | The point is past the scan's level-0 shape; check you used level-0 voxels, not a coarser level. |
| "not a volume in the open data" | Use the 14-digit volume id (list it with `list_scans`). |
| "the model is still loading" | The Space has just woken up; wait a minute. |
"""

AGENTS = """\
Every control on this page is also an API endpoint and an **MCP tool**. MCP clients (Claude, Cursor and
others) add the server `{host}/gradio_api/mcp/`; Hugging Face's MCP settings (huggingface.co/settings/mcp) can
add this Space too. A field uses the caller's ZeroGPU time, so pass your Hugging Face token.

| Call | What it returns |
| --- | --- |
| `/list_fields` | every whole-scan field the first tab lists, by scroll: volume, voxel size, model, size and links |
| `/list_scans` | every open-data volume it can read, with the level the model reads |
| `/list_models` | the model slot: which models exist and which are offered |
| `/example_points` | ready points inside the papyrus of scans on no prize list |
| `/plan_field` | the box, CT reads, tiles and GPU ask for a point, without running anything |
| `/make_field` | the picture, the receipt (with the agreement check) and the zip |

```python
from gradio_client import Client
c = Client("SharpMeow/lasagna-fields", token="hf_...")      # your token: the run uses your ZeroGPU time
pt = c.predict(api_name="/example_points")[0]
print(c.predict(pt["volume"], pt["z"], pt["y"], pt["x"], 256, "lasagna", api_name="/plan_field"))
picture, receipt, zip_path = c.predict(pt["volume"], pt["z"], pt["y"], pt["x"], 256, "lasagna",
                                       api_name="/make_field")
print(receipt["agreement"])
```

Plain HTTP works too (`POST {host}/gradio_api/call/make_field` with `{{"data": [...]}}`, then read the event
stream it names). Coordinates are level-0 (full resolution) voxels, z then y then x.
"""

CSS = """
:root, .dark { --lf-accent:#c2462b; }
.gradio-container { width: 100% !important; max-width: 1600px !important; margin: 0 auto !important; }
.lf-head { display:flex; align-items:center; gap:14px; padding:6px 2px 2px; }
.lf-head .layers { width:30px; height:24px; border-radius:5px; flex:none;
  background:repeating-linear-gradient(180deg,#c2462b 0 4px,#e07a3f 4px 7px,#f3e2bf 7px 10px,#4f7a3a 10px 11px,#f3e2bf 11px 12px); }
.lf-head h1 { white-space:nowrap; font-family: Fraunces, Georgia, serif; font-weight:650; font-size:30px; margin:0; letter-spacing:-.01em; }
.lf-head span { color: var(--body-text-color-subdued); font-size:15px; }
/* no fixed height: onescroll.html fits the guide's frame to the guide, so the page scrolls and the frame does not;
   min-height only holds the place until it has */
.lf-guide iframe { width:100%; min-height:640px; border:0; border-radius:12px; background:#f7f2ea; }
.lf-note p { font-size:13px; color: var(--body-text-color-subdued); margin:0; }
.lf-est p { font-size:13.5px; color: var(--body-text-color-subdued); }
.lf-point { flex-wrap: nowrap !important; }
.lf-credit { text-align:center; font-size:13px; color: var(--body-text-color-subdued); padding:18px 0 6px; }
.lf-credit a { color: var(--lf-accent) !important; padding:0 !important; margin:0 !important; }
.lf-howto img { border-radius:10px; border:1px solid var(--border-color-primary); max-width:min(100%, 760px); display:block; margin:8px 0; }
#lf-dl .empty { min-height: 64px !important; height: 64px !important; }
#lf-dl .empty .icon { height: 28px; }
/* one page scroll bar: the download's file row and the receipt grow with what they hold, so the page scrolls */
#lf-dl .file-preview-holder { max-height:none !important; overflow:visible !important; }
#lf-receipt { max-height:none !important; overflow:visible !important; }
.lf-howto { max-width: 1000px; margin: 0 auto !important; }
.lf-howto h3 { scroll-margin-top: 16px; margin-top: 1.6em !important; }
.lf-howto em { color: var(--body-text-color-subdued); font-size: 13.5px; }
.lf-toc { font-size: 14px; line-height: 1.9; padding: 10px 14px; border-radius: 10px;
  background: var(--block-background-fill); border: 1px solid var(--border-color-primary); }
@media (max-width: 640px) {
  .lf-head h1 { font-size:24px; }
  .lf-head span { display:none; }
  #lf-tabs .tab-container button { padding:6px 6px !important; font-size:12.5px !important; }
}
"""

HEAD = """
<meta name="description" content="Lasagna Fields: whole-scan lasagna fields for {scrolls} Herculaneum scrolls, listed by
scroll, or villa's field made for any box of a public scan on ZeroGPU. API and MCP server for agents.">
<meta property="og:title" content="Lasagna Fields">
<meta property="og:description" content="Lasagna fields (cos, grad_mag, normals) for Herculaneum scroll CT:
{scrolls} scrolls listed by scroll, and any box made on demand. Model output, not a reading.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,650&display=swap" rel="stylesheet">
""".format(scrolls=field_counts()["scrolls"])
# one page scroll bar: fits the guide's frame to its content (written by python -m kit spaceconnect render)
ONESCROLL = HERE / "onescroll.html"
HEAD += ONESCROLL.read_text() if ONESCROLL.is_file() else ""


def theme():
    import gradio as gr
    t = gr.themes.Base(primary_hue=gr.themes.Color(c50="#fdf1ec", c100="#fadfd4", c200="#f3bca8", c300="#ea957a",
                                                   c400="#df6d4f", c500="#c2462b", c600="#a8321c", c700="#8a2917",
                                                   c800="#6c2113", c900="#4e180e", c950="#300f09"),
                       neutral_hue="stone", radius_size="md",
                       font=(gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"),
                       font_mono=(gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"))
    return t.set(body_background_fill="#f7f2ea", body_background_fill_dark="#141210",
                 block_background_fill="#fffdf9", block_background_fill_dark="#1f1c18",
                 block_border_color="#e2d8c8", block_border_color_dark="#332e28",
                 button_primary_background_fill="#c2462b", button_primary_background_fill_dark="#ef7650",
                 button_primary_background_fill_hover="#a8321c", button_primary_background_fill_hover_dark="#f2a15f")


def guide_html():
    """The guide to the whole-scan fields, with its list from fields.json and its pictures from assets/."""
    if not GUIDE.is_file():
        return "<p>The guide is missing from this copy.</p>"
    import html
    page = GUIDE.read_text()
    # its pictures (assets/..., built in its script) point at Gradio's file route; a <base> cannot do it, because a
    # base of /gradio_api/file= resolves assets/x to /gradio_api/assets/x. Anchors scroll to their section (the frame
    # is as tall as the guide, so the page scrolls, not the frame)
    page = page.replace("'assets/", "'/gradio_api/file=assets/").replace('"assets/', '"/gradio_api/file=assets/')
    fix = ('<style>.wrap{max-width:1480px!important}</style>'
           '<script>document.addEventListener("click",function(e){var a=e.target.closest&&e.target.closest("a");'
           'if(!a)return;var h=a.getAttribute("href")||"";if(h.charAt(0)==="#"){e.preventDefault();'
           'var t=document.getElementById(h.slice(1));if(t)t.scrollIntoView({behavior:"smooth"});}'
           'else if(h.indexOf("?tab=")===0){e.preventDefault();window.parent.postMessage({lfTab:h.slice(5)},"*");}'
           'else if(/^https?:/.test(h)){a.target="_blank";a.rel="noopener";}},true);</script>')
    page = page.replace("<head>", "<head>" + fix, 1)
    # the list of every field (fields.json), as JSON a <script> cannot end early
    data = json.dumps(field_doc(), ensure_ascii=False).replace("</", "<\\/")
    page = page.replace('<script id="fieldlist" type="application/json">null</script>',
                        f'<script id="fieldlist" type="application/json">{data}</script>', 1)
    return f'<iframe title="Every lasagna field" srcdoc="{html.escape(page, quote=True)}"></iframe>'


TAB_JS = """
() => {
  const pick = (name) => {
    const ids = {scans: 0, make: 1, howto: 2, agents: 3};
    const btns = document.querySelectorAll('#lf-tabs button[role="tab"]');
    if (name in ids && btns[ids[name]]) btns[ids[name]].click();
  };
  window.addEventListener('message', (e) => { if (e.data && e.data.lfTab) pick(e.data.lfTab); });
  const q = new URLSearchParams(window.location.search).get('tab');
  if (q) setTimeout(() => pick(q), 300);
}
"""


def build_demo():
    import gradio as gr

    def guard(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except FieldError as exc:
                raise gr.Error(str(exc)) from None
            except gr.Error:
                raise
            except Exception as exc:  # noqa: BLE001
                import traceback
                log(f"{fn.__name__} failed: {traceback.format_exc()}")
                raise gr.Error(f"{type(exc).__name__}: {str(exc)[:400]}") from None
        return wrapped

    choices = volume_choices()
    first = EXAMPLES[0]
    host = (f"https://{os.environ['SPACE_HOST']}" if os.environ.get("SPACE_HOST")
            else "https://sharpmeow-lasagna-fields.hf.space")
    offered = [(m["title"], k) for k, m in L.MODELS.items() if m["offered"]]

    def on_make(vid, z, y, x, size, model, request: gr.Request, progress=gr.Progress()):
        pic, receipt, zpath = make_field(vid, z, y, x, size, model, request=request, progress=progress)
        return pic, result_text({"receipt": receipt}), zpath, receipt

    def on_example(i):
        e = EXAMPLES[int(i or 0) % len(EXAMPLES)]
        return e["volume"], e["z"], e["y"], e["x"]

    with gr.Blocks(title="Lasagna Fields", delete_cache=(1800, 3600)) as demo:
        n = field_counts()
        gr.HTML('<div class="lf-head"><div class="layers"></div><h1>Lasagna Fields</h1><span>Lasagna fields for '
                f'{n["scrolls"]} Herculaneum scrolls, listed by scroll, and villa’s field made for any box on demand.'
                '</span></div>')
        with gr.Tabs(elem_id="lf-tabs"):
            with gr.Tab("Every field", id="scans"):
                gr.HTML(guide_html(), elem_classes="lf-guide")
            with gr.Tab("Make a field", id="make"):
                gr.Markdown(INTRO)
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2, min_width=300):
                        ex = gr.Dropdown([(e["label"], i) for i, e in enumerate(EXAMPLES)], value=0,
                                         label="Example point (scans on no prize list)")
                        vid = gr.Dropdown(choices, value=first["volume"], label="Scan (any public volume)",
                                          filterable=True)
                        vinfo = gr.Markdown(volume_text(first["volume"]), elem_classes="lf-note")
                        with gr.Row(elem_classes="lf-point"):
                            z = gr.Number(first["z"], label="z", precision=0, minimum=0, min_width=80)
                            y = gr.Number(first["y"], label="y", precision=0, minimum=0, min_width=80)
                            x = gr.Number(first["x"], label="x", precision=0, minimum=0, min_width=80)
                        gr.Markdown("Point in full-resolution (level 0) voxels, as the data browser and VC3D show "
                                    "them.", elem_classes="lf-note")
                        size = gr.Radio([("256 voxels", 256), ("512 voxels", 512)], value=256, label="Box side")
                        model = gr.Radio(offered, value="lasagna", label="Model")
                        go = gr.Button("Make the field", variant="primary", size="lg")
                        est = gr.Markdown(estimate_text(first["volume"], first["z"], first["y"], first["x"], 256),
                                          elem_classes="lf-est")
                    with gr.Column(scale=3, min_width=320):
                        example = MEDIA / "example-result.png"
                        pic = gr.Image(str(example) if example.is_file() else None,
                                       label="Middle slices along z, y, x: CT · cos · grad_mag · normal",
                                       type="numpy", format="png", interactive=False, show_label=False)
                        summary = gr.Markdown("Above: what a result looks like (the first example point). Your "
                                              "field replaces it. The first run after the Space wakes up also loads "
                                              "the model (about a minute).")
                        dl = gr.File(label="Download: villa output folder, field.npz, receipt.json", height=88,
                                     elem_id="lf-dl")
                        with gr.Accordion("Receipt", open=False):
                            receipt = gr.JSON(max_height=None, elem_id="lf-receipt")
                        with gr.Accordion("About the model", open=False):
                            gr.Markdown(ABOUT_MODEL.format(commit=L.VILLA["commit"][:12],
                                                           sha=L.WEIGHTS["sha256"][:16] + "…"))
            with gr.Tab("How-to guides", id="howto"):
                gr.Markdown(HOW_TO, elem_classes="lf-howto")
            with gr.Tab("Agents and API", id="agents"):
                gr.Markdown(AGENTS.format(host=host))
                with gr.Accordion("Connect your tool: the fields and scans by URL", open=True):
                    # the data's URLs and ready snippets, made by python -m kit spaceconnect render from connect.json
                    gr.HTML(CONNECT_HTML.read_text() if CONNECT_HTML.exists() else "")
        gr.HTML('<footer class="lf-credit">Made by <a href="https://github.com/ChaseHendrick">Chase Hendrick</a> · '
                'model and code: <a href="https://github.com/ScrollPrize/villa">villa</a> lasagna (MIT) · scans: '
                '<a href="https://scrollprize.org">Vesuvius Challenge</a> open data, CC BY-NC 4.0 · '
                f'Lasagna Fields {VERSION} · model output, not a reading</footer>')

        # hidden: the API endpoints and MCP tools for scripts and agents
        with gr.Row(visible=False):
            a_vid, a_model = gr.Textbox(label="volume"), gr.Textbox("lasagna", label="model")
            a_z, a_y, a_x = (gr.Number(0, precision=0, label=k) for k in "zyx")
            a_size = gr.Number(256, precision=0, label="size")
            a_json, a_img, a_file = gr.JSON(), gr.Image(type="numpy", format="png"), gr.File()
            a_scroll = gr.Textbox("", label="scroll")
            a_btns = [gr.Button() for _ in range(6)]

        hidden = dict(api_visibility="private")
        vid.change(volume_text, vid, vinfo, **hidden)
        for comp in (vid, z, y, x, size):
            comp.change(estimate_text, [vid, z, y, x, size], est, show_progress="hidden", **hidden)
        ex.input(on_example, ex, [vid, z, y, x], **hidden)
        go.click(guard(on_make), [vid, z, y, x, size, model], [pic, summary, dl, receipt],
                 concurrency_id="model", concurrency_limit=2, **hidden)
        ins = [a_vid, a_z, a_y, a_x, a_size, a_model]
        for btn, fn, i, o, name in ((a_btns[0], list_scans, [], a_json, "list_scans"),
                                    (a_btns[1], list_models, [], a_json, "list_models"),
                                    (a_btns[2], example_points, [], a_json, "example_points"),
                                    (a_btns[3], plan_field, ins, a_json, "plan_field"),
                                    (a_btns[4], make_field, ins, [a_img, a_json, a_file], "make_field"),
                                    (a_btns[5], list_fields, [a_scroll], a_json, "list_fields")):
            heavy = name == "make_field"
            btn.click(guard(fn), i, o, api_name=name, api_description=fn.__doc__.split("\n\n")[0],
                      concurrency_id="model" if heavy else None, concurrency_limit=2 if heavy else 8)
        demo.load(None, None, None, js=TAB_JS)
    return demo


def fix_mcp_multiple_outputs():
    """Gradio 6.28's MCP server joins a queued tool's several outputs into one text; hand them over one by one, so
    make_field's picture reaches an agent as a picture (as Scroll Lens does)."""
    try:
        from gradio.mcp import GradioMCPServer
        from anyio.to_thread import run_sync
    except ImportError:
        return

    async def without_progress(self, job):
        result = await run_sync(job.result)
        return list(result) if isinstance(result, tuple) else [result]

    GradioMCPServer._execute_tool_without_progress = without_progress


def launch_kwargs():
    import gradio as gr
    static = [p for p in (HERE / "assets", MEDIA) if p.is_dir()]
    if static:
        gr.set_static_paths(paths=[str(p) for p in static])
    os.chdir(HERE)                     # the guide's assets/... resolve against the Space's folder
    return dict(theme=theme(), css=CSS, head=HEAD, footer_links=["api", "gradio"], mcp_server=True,
                max_file_size="1mb", allowed_paths=[str(OUT)])


if __name__ == "__main__":
    startup()
    fix_mcp_multiple_outputs()
    build_demo().queue(max_size=64, default_concurrency_limit=8).launch(**launch_kwargs())
