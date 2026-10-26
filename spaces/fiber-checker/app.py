"""Fiber Checker: are papyrus fibers visible on a traced scroll surface?

The web page and the API. Pick a traced segment of the open data (or upload your own tifxyz), and the Space renders
the CT along the surface patch by patch and asks a judge whether each render shows papyrus fibers: a small free model
that runs here on the CPU (no key), or Claude with your own Anthropic key. The checking itself is fibercheck.py (the
command line tool, also in ChaseHendrick/Scrolls scripts/fibercheck/); the segment list is fibercat.py.
  python3 app.py            serve the page (on a Space, or on any computer)
"""
import collections
import functools
import hashlib
import html
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent.parent / "scripts" / "fibercheck"):    # on the Space both sit in HERE
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.append(str(_p))
import numpy as np  # noqa: E402
import fibercat as C  # noqa: E402
import fibercheck as FC  # noqa: E402
from fibercat import CatalogError  # noqa: E402

VERSION = "0.1.0"
WEIGHTS = HERE / "weights" / "fibercheck-local.pt"
WEIGHTS_SHA256 = "e43c25b322816f9f821a154a472eb51e0af86baa194ca5d65094083e8c4b35d7"
OUT = Path(tempfile.gettempdir()) / "fiber-checker-out"
CT_CACHE = C.CACHE / "ct"
CT_KEEP = int(8e9)                  # CT chunks kept between runs; the oldest go first
GAME = HERE / "assets" / "game.npz"
CONNECT_HTML = HERE / "connect.html"
PATCHES = [("Quick: 60 patches, about 2 minutes", 60), ("Thorough: 150 patches, about 5 minutes", 150),
           ("Whole segment: up to 400 patches, about 15 minutes", 400)]
CLAUDE_PATCHES, CLAUDE_CHECK_N = 40, 10
SETUP = {"weights": None, "error": None}

# Public scrolls on no prize list, scans from 2025 or later, the setting both held-out tests used (2.2 to 2.4 um
# scans at level 2). PHerc0139 w030 was a training winding of the free judge; the other four were never trained on.
EXAMPLES = [
    {"label": "PHerc0500P2 · z_dbg_gen_00440", "sample": "PHerc0500P2", "segment": "20250611171318",
     "volume": "20250526151718"},
    {"label": "PHerc0343P · -3_b2", "sample": "PHerc0343P", "segment": "20250902170447", "volume": "20260304131111"},
    {"label": "PHerc0009B · auto_grown_20250918234353", "sample": "PHerc0009B", "segment": "20250919064353",
     "volume": "20250820154339"},
    {"label": "PHerc0814 · auto_grown_20250925161630", "sample": "PHerc0814", "segment": "20250925161630",
     "volume": "20260309142202"},
    {"label": "PHerc0139 · w030 (a training winding)", "sample": "PHerc0139", "segment": "20250108000005",
     "volume": "20260102150214"},
]


def log(message):
    print(f"[fiber-checker {time.strftime('%H:%M:%S')}] {message}", flush=True)


def startup():
    for folder in (OUT,):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
    if not WEIGHTS.is_file():
        SETUP["error"] = f"the free judge's weights are missing ({WEIGHTS.name})"
    else:
        sha = hashlib.sha256(WEIGHTS.read_bytes()).hexdigest()
        SETUP["weights"] = sha
        if sha != WEIGHTS_SHA256:
            SETUP["error"] = f"the free judge's weights have SHA-256 {sha[:16]}…, not the tested {WEIGHTS_SHA256[:16]}…"
    try:
        log(f"{sum(len(v) for v in C.catalog().values())} traced segment meshes in the open data")
    except CatalogError as exc:
        log(f"segment list not loaded yet: {exc}")
    log(SETUP["error"] or "free judge ready")


# ---------------------------------------------------------------- one run per visitor

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
    """One check at a time per visitor or caller, so one script cannot hold the CPU for everyone."""

    def __init__(self, request):
        self.key = client_of(request)

    def __enter__(self):
        with RUN_LOCK:
            if self.key and RUNNING[self.key] >= 1:
                raise CatalogError("you already have a check running; wait for it to finish (one at a time)")
            RUNNING[self.key] += 1

    def __exit__(self, *exc):
        with RUN_LOCK:
            RUNNING[self.key] -= 1
            if RUNNING[self.key] <= 0:
                del RUNNING[self.key]
        return False


# ---------------------------------------------------------------- the check

def _progress_say(progress):
    def say(line):
        line = str(line)
        if not progress:
            return
        if line.startswith("PROGRESS "):
            done, total = line.split()[1].split("/")
            progress(0.08 + 0.6 * int(done) / max(int(total), 1), desc=f"Rendering the CT along the surface: "
                     f"{done} of {total} patches")
        elif line.startswith("judging"):
            progress(0.72, desc=line[0].upper() + line[1:])
        elif line.startswith("self-check"):
            progress(0.88, desc="Self-check: the judge against noised, blurred and scrambled copies")
    return say


def run_check(mesh, row, patches, judge="local", api_key=None, max_usd=3.0, progress=None):
    """fibercheck on one mesh folder; returns (output folder, record)."""
    if judge == "local" and SETUP["error"]:
        raise CatalogError(SETUP["error"])
    patches = int(patches)
    if judge == "claude":
        if not (api_key or "").strip():
            raise CatalogError("the Claude judge needs your own Anthropic API key (it is used for this run only)")
        patches = min(patches, CLAUDE_PATCHES)
    out = Path(tempfile.mkdtemp(prefix="check-", dir=OUT))
    a = types.SimpleNamespace(segment=mesh, ct=row["ct"].rstrip("/"), level=row["level"], p=28,
                              k=5 if row["tested"] else 0, stride=None, max_patches=patches, judge=judge,
                              weights=str(WEIGHTS), max_usd=float(max_usd), cache=CT_CACHE, out=str(out), json=False,
                              check_n=CLAUDE_CHECK_N if judge == "claude" else 40)
    if progress:
        progress(0.04, desc="Reading the segment's mesh and the CT from the open data")
    try:
        rec = FC.score(a, say=_progress_say(progress), api_key=(api_key or "").strip() or None)
    except SystemExit as exc:          # the command line tool's refusals
        raise CatalogError(str(exc).replace("fibercheck: ", "")) from None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if api_key:
            msg = msg.replace(api_key.strip(), "[your key]")
        raise CatalogError(f"{type(exc).__name__}: {msg[:400]}") from None
    finally:
        try:
            C.prune(CT_CACHE, CT_KEEP)
        except OSError:
            pass
    rec["source"] = {k: row.get(k) for k in ("sample", "segment", "name", "volume", "voxel_um", "level", "tested")}
    (out / "fiber.json").write_text(json.dumps(rec, indent=1))
    return out, rec


def bundle(out, rec):
    name = f"fiber-{rec['source'].get('sample') or 'mesh'}-{rec['source'].get('segment') or 'upload'}.zip"
    zpath = out / name
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ("fiber.json", "fiber.tif", "fiber_map.png", "report.html"):
            z.write(out / f, f)
        for f in sorted((out / "tiles").glob("*.png")):
            z.write(f, f"tiles/{f.name}")
    return str(zpath)


def check_segment(sample, segment, volume="", patches=60, request=None, progress=None,
                  judge="local", api_key=None, max_usd=3.0):
    """Check one traced segment of the open data with the free judge.

    Renders the CT along the segment patch by patch (28 x 28 mesh vertices each) and gives each patch a fiber
    evidence from 0.5 (no sign of fibers) to 1 (clear fibers), with a self-check against noised, blurred and
    scrambled copies. Returns the fiber map picture, the record (summary, self-check, every patch) and a zip with
    fiber.json, fiber.tif (one value per mesh vertex, on the segment's own grid), fiber_map.png and report.html.
    sample: a scroll such as PHerc0500P2; segment: its 14-digit segment id or name (list_segments); volume: the
    14-digit scan id (empty: the tested scan); patches: at most this many patches (60, 150 or up to 400).
    """
    with one_run(request):
        row = C.find(str(sample).strip(), str(segment).strip(), str(volume or "").strip() or None)
        mesh = C.fetch_mesh(row)
        out, rec = run_check(mesh, row, patches, judge, api_key, max_usd, progress)
        return str(out / "fiber_map.png"), rec, bundle(out, rec)


def check_upload(upload, volume, patches=60, request=None, progress=None, judge="local", api_key=None, max_usd=3.0):
    """Check your own tifxyz mesh: a zip holding x.tif, y.tif and z.tif in level-0 voxels of the scan named."""
    if not upload:
        raise CatalogError("upload a zip of your tifxyz folder (x.tif, y.tif and z.tif)")
    sc = C.scan(volume)
    with one_run(request):
        work = Path(tempfile.mkdtemp(prefix="mesh-", dir=OUT))
        with zipfile.ZipFile(upload) as z:
            names = {Path(n).name: n for n in z.namelist() if not n.endswith("/")}
            if not {"x.tif", "y.tif", "z.tif"} <= set(names):
                raise CatalogError("the zip needs x.tif, y.tif and z.tif (a tifxyz folder)")
            for f in ("x.tif", "y.tif", "z.tif"):
                info = z.getinfo(names[f])
                if info.file_size > 400e6:
                    raise CatalogError(f"{f} is over 400 MB")
                (work / f).write_bytes(z.read(names[f]))
        row = dict(sc, segment="upload", name=Path(str(upload)).stem)
        out, rec = run_check(work, row, patches, judge, api_key, max_usd, progress)
        return str(out / "fiber_map.png"), rec, bundle(out, rec)


def compare_results(a_json, b_json):
    """Compare two fiber.json records: summary side by side, and patch by patch when both share a mesh grid."""
    ra, rb = (json.loads(Path(f).read_text()) if isinstance(f, str) and Path(f).is_file() else f
              for f in (a_json, b_json))
    if not (isinstance(ra, dict) and isinstance(rb, dict) and "summary" in ra and "summary" in rb):
        raise CatalogError("give two fiber.json files from this Space or the command line tool")
    rows = {k: [ra["summary"].get(k), rb["summary"].get(k)]
            for k in ("patches", "median_evidence", "share_fibers_visible", "share_unsure")}
    paired = None
    if ra.get("grid") == rb.get("grid") and ra.get("patch_vertices") == rb.get("patch_vertices"):
        ea = {(p["r"], p["c"]): p["evidence"] for p in ra["patches"]}
        both = [(ea[(p["r"], p["c"])], p["evidence"]) for p in rb["patches"] if (p["r"], p["c"]) in ea]
        if both:
            d = np.array([x - y for x, y in both])
            paired = {"patches": len(both), "a_better": round(float((d > 0.05).mean()), 3),
                      "b_better": round(float((d < -0.05).mean()), 3), "mean_diff": round(float(d.mean()), 4)}
    return {"summary": rows, "paired_same_grid": paired,
            "a": ra.get("source") or ra.get("segment"), "b": rb.get("source") or rb.get("segment")}


# ---------------------------------------------------------------- what the page shows

def pct(v):
    return "n/a" if v is None or v != v else f"{v:.0%}"


def summary_html(rec):
    s, src = rec["summary"], rec.get("source") or {}
    ck = s["self_check"]
    name = html.escape(str(src.get("name") or src.get("segment") or ""))
    setting = ("the tested setting (2.2 to 2.4 um scan, level 2)" if src.get("tested") else
               f"<b>outside the tested setting</b> ({src.get('voxel_um')} um scan at level {src.get('level')}): "
               "treat the numbers as a first look")
    cost = f" · Claude spend {rec['usd']:.2f} USD" if "usd" in rec else ""
    verdict = ("Fibers show on most of this surface." if s["share_fibers_visible"] >= 0.75 else
               "Fibers show on part of this surface; the map shows where." if s["share_fibers_visible"] >= 0.3 else
               "Few patches show fibers: the trace may be off the sheet, or the CT is unclear here.")
    if not ck["passed"]:
        verdict = "The self-check failed, so this judge's answers on this segment cannot be trusted."
    jumps = len(rec.get("jump_hints") or [])
    return f"""
<div class="fc-verdict">{verdict}</div>
<div class="fc-cards">
 <div class="fc-card"><div class="fc-big">{pct(s['share_fibers_visible'])}</div>of patches show fibers
  <span>evidence 0.75 or more</span></div>
 <div class="fc-card"><div class="fc-big">{s['median_evidence']:.2f}</div>median fiber evidence
  <span>0.5 none · 1 clear</span></div>
 <div class="fc-card"><div class="fc-big">{s['patches']}</div>patches checked<span>{pct(s['share_unsure'])} unsure</span></div>
 <div class="fc-card"><div class="fc-big {'fc-ok' if ck['passed'] else 'fc-bad'}">{'passed' if ck['passed'] else 'failed'}</div>
  self-check<span>noise {pct(ck['against']['noise'])} · blur {pct(ck['against']['blur'])} ·
  scramble {pct(ck['against']['scramble'])}</span></div>
</div>
<p class="fc-meta">{html.escape(str(src.get('sample') or ''))} · {name} · scan {html.escape(str(src.get('volume')))}
 · {setting} · judge: {'free local model' if rec['judge'] == 'local' else 'Claude, your key'}{cost}</p>
<details class="fc-untested"><summary>Untested hints ({jumps} possible jumps)</summary>
<p>These have not passed a test of their own yet, so read them as ideas, not results.
<b>Jump hints</b>: {jumps} patches with low evidence where every neighbour is clear, which can mark a sheet jump or a
stretch off the sheet. <b>Fiber direction</b>: {pct(s['direction_share_horizontal'])} of patches have strands
running along the mesh's columns (horizontal in the map), the rest along its rows. <b>Best depth</b>: the median
patch looks most fibrous {s['depth_offset_median']:+g} voxels from the traced surface.</p></details>
"""


def tiles_of(out):
    files = sorted(Path(out).glob("tiles/*.png"))
    return [(str(f), f"{f.stem.split('-')[-1]} {f.stem.split('-')[1]}") for f in files]


def report_frame(out):
    page = (Path(out) / "report.html").read_text()
    return f'<iframe class="fc-report" title="Report" srcdoc="{html.escape(page, quote=True)}"></iframe>'


def sample_choices():
    try:
        cat = C.catalog()
    except CatalogError:
        return [e["sample"] for e in EXAMPLES]
    return [(f"{s} · {len(rows)} meshes" + (" · prize scroll" if rows[0]["prize"] else ""), s)
            for s, rows in sorted(cat.items())]


def segment_choices(sample):
    try:
        rows = C.segments(sample)
    except CatalogError:
        return []
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["name"]):
        if r["segment"] in seen:
            continue
        seen.add(r["segment"])
        tag = r["name"][len(r["segment"]) + 1:] if r["name"].startswith(r["segment"] + "-") else r["name"]
        out.append((f"{r['segment']} · {tag}" if tag and tag != r["segment"] else r["segment"], r["segment"]))
    return out


def volume_choices(sample, segment):
    try:
        rows = [r for r in C.segments(sample) if r["segment"] == segment]
    except CatalogError:
        return []
    rows.sort(key=lambda r: (not r["tested"], r["volume"]))
    return [(f"{r['volume']} · {r['voxel_um']:g} um · level {r['level']}" + (" · tested" if r["tested"] else ""),
             r["volume"]) for r in rows]


def list_scrolls():
    """Every scroll with traced segments in the open data, with its segment count and whether it is a prize scroll."""
    return [{"sample": s, "meshes": len(rows), "segments": len({r["segment"] for r in rows}),
             "prize_scroll": rows[0]["prize"]} for s, rows in sorted(C.catalog().items())]


def list_segments(sample):
    """Every traced segment of one scroll, with the scans it has a mesh on (tested: the setting the judge passed on)."""
    return [{k: r[k] for k in ("segment", "name", "volume", "voxel_um", "level", "tested", "mesh")}
            for r in C.segments(str(sample).strip())]


def example_segments():
    """Ready segments of public scrolls on no prize list, in the tested setting."""
    return EXAMPLES


# ---------------------------------------------------------------- the game

class Game:
    """Fiber or not? Two renders of the same patch: one as the CT shows it on the traced surface, one changed so its
    strands are gone (or a few voxels off the sheet). Pick the one with fibers, then see what the free judge says."""
    KINDS = {"scramble": "the same patch with its texture kept and its strands scrambled",
             "shuffle": "the same patch cut into 14-pixel tiles, turned and shuffled",
             "blur": "the same patch blurred",
             "noise": "the same patch with strong noise",
             "off": "the CT 5 voxels off the traced surface"}

    def __init__(self, path):
        self.ok = Path(path).is_file()
        if self.ok:
            z = np.load(path)
            self.on, self.off, self.src = z["on"].astype(np.float64), z["off"].astype(np.float64), list(z["src"])
        self.judge = None

    def other(self, i, kind, rng):
        on = self.on[i]
        if kind == "off":
            return self.off[i]
        if kind == "shuffle":
            from fcmodel import tile_shuffle
            t = tile_shuffle(on, 14, f"game:{i}:{rng.integers(1 << 30)}")      # z-scored: back to the CT's scale
            return t * on.std() + on.mean()
        return FC.controls(on, rng)[kind]

    def judge_pair(self, a, b, ref):
        """P(the free judge picks a), both scaled by the on render's grey scale as in the checker."""
        if self.judge is None:
            self.judge = FC.LocalJudge(str(WEIGHTS))
        p, _ = self.judge.prefer([FC.to_input(a, ref)], [FC.to_input(b, ref)])
        return float(p[0])


GAME_STATE0 = {"round": 0, "you": 0, "model": 0, "answered": True, "i": None}


def png_of(a):
    from PIL import Image
    lo, hi = np.percentile(a, [1, 99])
    b = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1)
    im = Image.fromarray((b * 255).astype(np.uint8)).resize((a.shape[1] * 3, a.shape[0] * 3), Image.BICUBIC)
    return np.asarray(im)


def score_line(st):
    if not st["round"]:
        return "Which picture shows papyrus fibers: long, thin, parallel strands? Press **New pair** to start."
    return (f"Round {st['round']} · you {st['you']} of {st['round'] - (0 if st['answered'] else 1)} · "
            f"the free judge {st['model']} of {st['round'] - (0 if st['answered'] else 1)}")


# ---------------------------------------------------------------- the page

INTRO = """\
Pick a traced segment and press **Check fibers**. The Space renders the CT along the surface, patch by patch, and a
judge says how clearly each render shows papyrus fibers. Fibers on the output surface are what the Progress Prize
asks entrants to show, and they are a sign the trace sits on the sheet.
"""

ABOUT_JUDGE = """\
**Free local model** (default, no key): a small network (about 40,000 weights) trained on Claude's answers to 817
patches of four public scrolls. On two scrolls it never saw it passed its preregistered test: it told the sheet from
the gap beside it on every patch (pixel measure 0.76 to 0.79), and the sheet from a tile-shuffled copy on 92 to 98% of
patches (pixel measure 0.53 to 0.57). Weights SHA-256 `{sha}`.

**Claude, your own key**: the same question, asked of Claude in both orders, as in the test where Claude's fiber
answers were valid on four scrolls. Your key is used for this run only and is never stored or logged. It checks at
most {cp} patches and stops at your spending cap.
"""

HOW_TO = """\
<p class="fc-toc">Guides: <a href="#what">What it checks</a> · <a href="#first">Your first check</a> ·
<a href="#read">Read the result</a> · <a href="#own">Check your own trace</a> · <a href="#ab">Compare two traces</a>
· <a href="#prize">For prize entries</a> · <a href="#research">For researchers</a> · <a href="#cli">Run it
yourself</a> · <a href="#limits">What is tested, what is not</a> · <a href="#wrong">When something goes wrong</a></p>

<h3 id="what">What it checks</h3>

Papyrus is made of plant strips laid in two crossing layers, so a surface traced on a sheet shows long, thin, parallel
strands in the CT. Where a trace runs through air, a gap or unclear CT, the strands fade into noise. The Progress Prize asks entrants to "show visually that papyrus fibers are visible on your
output surface" ([scrollprize.org/prizes](https://scrollprize.org/prizes)). This Space measures that, patch by patch.

For each patch it renders the CT on the surface and asks the judge one question: does this render show fibers more
clearly than a copy with the same texture but its strands scrambled? The answer is the **fiber evidence**: near 1
where fibers show, near 0.5 where the render looks no more fibrous than scrambled texture. It is model output about
texture: it never reads or finds text.

<h3 id="first">1. Your first check (two minutes)</h3>

1. Open **Check a segment**. It starts on an example from PHerc0500P2, a public scroll on no prize list.
2. Press **Check fibers**. The Space reads the mesh and about 700 MB of CT from the open data, renders 60 patches and
   judges them on the CPU.
3. The map, the summary and the download appear on the right. Try the **Fiber or not?** tab while you wait.

<h3 id="read">2. Read the result</h3>

- **The map** is the segment as traced, flattened on its own mesh grid. Yellow and green: clear fibers. Purple: weak.
  Grey: no sign of fibers. Slate: traced but not scored (holes nearby, masked CT, or not sampled). Black: no surface.
- **Fibers show on** is the share of patches with evidence 0.75 or more. **Median evidence** is the typical patch.
- **Self-check**: on 40 of your patches, the judge must prefer the real render over a noised, a blurred and a
  scrambled copy at least 80% of the time. If it fails, do not trust that run.
- **Unsure**: the judge's answer changed when the patch was turned by a quarter turn.
- **Clearest and weakest patches** are the renders themselves, so you can see what the judge saw.

<h3 id="own">3. Check your own trace</h3>

Zip your tifxyz folder (x.tif, y.tif and z.tif; VC3D and villa write these) and upload it on **Check a segment**,
under **Your own mesh**, with the 14-digit id of the scan its coordinates are in (level-0 voxels). The Space reads the
CT of that scan from the open data. Meshes on 2.2 to 2.4 um scans are checked in the tested setting.

<h3 id="ab">4. Compare two traces</h3>

Check both (two segments, or your trace before and after an edit), download each zip, and give the two
`fiber.json` files to **Compare**. When both are meshes of the same grid, it compares them patch by patch: the share
of patches where each is clearly better, and the mean difference.

<h3 id="prize">5. For prize entries</h3>

`report.html` in the download is a one-page summary in the prize's words: the map, the self-check, the clearest and
weakest patches and the method. Attach it, or its numbers, as evidence that fibers show on your surface. Run the free
judge first; Claude with your own key gives a second opinion on up to 40 patches. Say which judge you used.

<h3 id="research">6. For researchers</h3>

The free judge was preregistered and tested once on two public scrolls it never saw (PHerc0500P2 and PHerc0343P,
scans of 2025 and 2026 at level 2). Each test pair asks which of two renders shows fibers more clearly.

| Test pair | PHerc0500P2 (120 patches) | PHerc0343P (62 patches) | Pixel measure |
| --- | --- | --- | --- |
| Sheet vs the gap beside it | 1.00 | 1.00 | 0.79, 0.76 |
| Sheet vs a 14-pixel tile shuffle (a size never trained on) | 0.98 | 0.92 | 0.53, 0.57 |
| Sheet vs 3 voxels off | 0.87 | 0.68 | |

The pixel measure is structure-tensor coherence. A first round failed (it preferred tile-shuffled renders, because it
rewarded the edges a shuffle adds) and is kept on record; the second round added shuffles at other tile sizes to
training. Claude's own answers to the same pairs were valid on four public scrolls. All of it is model output.

<h3 id="cli">7. Run it yourself</h3>

```bash
git clone https://github.com/ChaseHendrick/Scrolls && cd Scrolls
pip install numpy scipy tifffile numcodecs pillow torch
# the weights: this Space's file weights/fibercheck-local.pt
python3 scripts/fibercheck/fibercheck.py score SEGMENT.tifxyz \\
    --ct https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr \\
    --level 2 --weights fibercheck-local.pt --out out/
python3 scripts/fibercheck/fibercheck.py compare out_a out_b
```

`fiber.tif` has one value per mesh vertex on the segment's own grid, the same shape as `x.tif`, so it lines up with
the segment in tools that read tifxyz channels. `--judge claude` uses `ANTHROPIC_API_KEY` from your environment.

<h3 id="limits">What is tested, what is not</h3>

- **Tested**: the free judge's answers on 2.2 to 2.4 um scans at level 2 with open-data tifxyz meshes, against built
  controls (the gap beside the sheet, tile shuffles, blur, noise, 3 voxels off). Not tested on real faulty traces.
- **Outside the tested setting** (other voxel sizes, your own meshes at other spacings): it still runs, and says so.
- **Untested hints**: jump hints, fiber direction and best depth are ideas until a test of their own passes.
- **Which sheet**: each patch is rendered at the brightest depth within 5 voxels of the trace (the tested rule), and
  papyrus sheets lie close together, so a trace a few voxels off, or on the neighbouring sheet, can still show fibers.
  A clear map says fibers show on and near your surface; it does not prove the trace stayed on one sheet.

<h3 id="wrong">When something goes wrong</h3>

| What you see | What to do |
| --- | --- |
| "no patch of the segment could be rendered" | The mesh has holes everywhere at 28 x 28 vertices, the CT is masked there, or the scan id is wrong. |
| "you already have a check running" | One check at a time per visitor; wait for it to finish. |
| "is not a scan this Space reads" | Give the 14-digit volume id from the open data. PHercParis4 is never read. |
| Self-check failed | The judge did not beat its own controls on this segment: do not use the numbers. |
| The Claude judge stops early | It reached your spending cap; unanswered patches are left out. |
"""

AGENTS = """\
Every control on this page is also an API endpoint and an **MCP tool**. MCP clients (Claude, Cursor and others) add
the server `{host}/gradio_api/mcp/`. The API uses the free judge, so it needs no key.

| Call | What it returns |
| --- | --- |
| `/list_scrolls` | every scroll with traced segments in the open data |
| `/list_segments` | one scroll's segments and the scans each has a mesh on |
| `/example_segments` | ready segments of public scrolls on no prize list |
| `/check_segment` | the fiber map, the record (summary, self-check, every patch) and the zip |
| `/compare_results` | two fiber.json records side by side, and patch by patch on a shared grid |

```python
from gradio_client import Client
c = Client("SharpMeow/fiber-checker")
ex = c.predict(api_name="/example_segments")[0]
picture, record, zip_path = c.predict(ex["sample"], ex["segment"], ex["volume"], 60, api_name="/check_segment")
print(record["summary"])
```

Plain HTTP works too (`POST {host}/gradio_api/call/check_segment` with `{{"data": [...]}}`, then read the event
stream it names). A check takes about two minutes for 60 patches.
"""

CSS = """
:root, .dark { --fc-accent:#9a5b1f; }
.gradio-container { width: 100% !important; max-width: 1600px !important; margin: 0 auto !important; }
.fc-head { display:flex; align-items:center; gap:14px; padding:6px 2px 2px; }
.fc-head .weave { width:30px; height:30px; border-radius:6px; flex:none;
  background: repeating-linear-gradient(90deg, rgba(120,72,24,.55) 0 3px, transparent 3px 6px),
              repeating-linear-gradient(0deg, #e8cf9c 0 3px, #c99a52 3px 6px); }
.fc-head h1 { white-space:nowrap; font-family: Fraunces, Georgia, serif; font-weight:650; font-size:30px; margin:0;
  letter-spacing:-.01em; }
.fc-head span { color: var(--body-text-color-subdued); font-size:15px; }
.fc-note p { font-size:13px; color: var(--body-text-color-subdued); margin:0; }
.fc-verdict { font-size:18px; font-weight:600; margin:4px 0 12px; }
.fc-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }
.fc-card { background: var(--block-background-fill); border:1px solid var(--border-color-primary); border-radius:12px;
  padding:12px 14px; font-size:14px; line-height:1.35; }
.fc-card span { display:block; color: var(--body-text-color-subdued); font-size:12.5px; margin-top:2px; }
.fc-big { font-size:26px; font-weight:650; font-variant-numeric: tabular-nums; }
.fc-ok { color:#1f7a4d; } .dark .fc-ok { color:#5fd39a; }
.fc-bad { color:#b3261e; } .dark .fc-bad { color:#ff8a80; }
.fc-meta { font-size:13px; color: var(--body-text-color-subdued); margin:12px 0 4px; }
.fc-untested { font-size:13.5px; margin-top:8px; } .fc-untested summary { cursor:pointer; }
.fc-legend { font-size:12.5px; color: var(--body-text-color-subdued); }
.fc-legend i { display:inline-block; width:11px; height:11px; border-radius:3px; margin:0 4px -1px 10px; }
.fc-report { width:100%; height:80vh; border:0; border-radius:12px; }
.fc-howto { max-width: 1000px; margin: 0 auto !important; }
.fc-howto h3 { scroll-margin-top: 16px; margin-top: 1.6em !important; }
.fc-toc { font-size: 14px; line-height: 1.9; padding: 10px 14px; border-radius: 10px;
  background: var(--block-background-fill); border: 1px solid var(--border-color-primary); }
.fc-game img { image-rendering: auto; }
.fc-score p { font-size:15px; }
.fc-credit { text-align:center; font-size:13px; color: var(--body-text-color-subdued); padding:18px 0 6px; }
.fc-credit a { color: var(--fc-accent) !important; }
#fc-dl .empty { min-height: 64px !important; height: 64px !important; }
@media (max-width: 640px) {
  .fc-head h1 { font-size:24px; }
  .fc-head span { display:none; }
  #fc-tabs .tab-container button { padding:6px 6px !important; font-size:12.5px !important; }
}
"""

LEGEND = ('<div class="fc-legend"><i style="background:#fde725"></i>clear fibers<i style="background:#21918c"></i>'
          'some<i style="background:#440154"></i>weak<i style="background:#6e6e6e"></i>no sign<i '
          'style="background:#343640"></i>not scored<i style="background:#18181c"></i>no surface</div>')

HEAD = """
<meta name="description" content="Fiber Checker: are papyrus fibers visible on a traced Herculaneum scroll surface?
A free fiber map of any segment of the open data, or your own tifxyz. API and MCP server for agents.">
<meta property="og:title" content="Fiber Checker">
<meta property="og:description" content="A per-patch fiber map of traced scroll surfaces, judged by a small free
model or by Claude with your own key. Model output, not a reading.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,650&display=swap" rel="stylesheet">
"""

TAB_JS = """
() => {
  const pick = (name) => {
    const ids = {check: 0, game: 1, compare: 2, howto: 3, agents: 4};
    const btns = document.querySelectorAll('#fc-tabs button[role="tab"]');
    if (name in ids && btns[ids[name]]) btns[ids[name]].click();
  };
  const q = new URLSearchParams(window.location.search).get('tab');
  if (q) setTimeout(() => pick(q), 300);
}
"""


def theme():
    import gradio as gr
    t = gr.themes.Base(primary_hue=gr.themes.Color(c50="#fbf4ea", c100="#f5e4cc", c200="#ebc999", c300="#dfa964",
                                                   c400="#c9853c", c500="#9a5b1f", c600="#83491a", c700="#6b3b16",
                                                   c800="#552f12", c900="#3f230e", c950="#291608"),
                       neutral_hue="stone", radius_size="md",
                       font=(gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"),
                       font_mono=(gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"))
    return t.set(body_background_fill="#f6f1e7", body_background_fill_dark="#14120f",
                 block_background_fill="#fffdf8", block_background_fill_dark="#1f1c18",
                 block_border_color="#e3d7c3", block_border_color_dark="#332e28",
                 button_primary_background_fill="#9a5b1f", button_primary_background_fill_dark="#d89a52",
                 button_primary_background_fill_hover="#83491a", button_primary_background_fill_hover_dark="#e8b273")


def build_demo():
    import gradio as gr

    def guard(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except CatalogError as exc:
                raise gr.Error(str(exc)) from None
            except gr.Error:
                raise
            except Exception as exc:  # noqa: BLE001
                import traceback
                log(f"{fn.__name__} failed: {traceback.format_exc()}")
                raise gr.Error(f"{type(exc).__name__}: {str(exc)[:400]}") from None
        return wrapped

    host = (f"https://{os.environ['SPACE_HOST']}" if os.environ.get("SPACE_HOST")
            else "https://sharpmeow-fiber-checker.hf.space")
    first = EXAMPLES[0]
    game = Game(GAME)

    def shown(pic, rec, zpath):
        out = Path(zpath).parent
        return pic, summary_html(rec), tiles_of(out), zpath, report_frame(out), rec

    def on_check(sample, segment, volume, patches, judge, own_key, max_usd, request: gr.Request, progress=gr.Progress()):
        return shown(*check_segment(sample, segment, volume, patches, request=request, progress=progress,
                                    judge=judge, api_key=own_key, max_usd=max_usd))

    def on_upload(upload, volume, patches, judge, own_key, max_usd, request: gr.Request, progress=gr.Progress()):
        return shown(*check_upload(upload, volume, patches, request=request, progress=progress,
                                   judge=judge, api_key=own_key, max_usd=max_usd))

    def on_example(i):
        e = EXAMPLES[int(i or 0) % len(EXAMPLES)]
        segs = segment_choices(e["sample"])
        vols = volume_choices(e["sample"], e["segment"])
        return (gr.update(value=e["sample"]), gr.update(choices=segs, value=e["segment"]),
                gr.update(choices=vols, value=e["volume"]))

    def on_sample(sample):
        segs = segment_choices(sample)
        seg = segs[0][1] if segs else None
        vols = volume_choices(sample, seg) if seg else []
        return gr.update(choices=segs, value=seg), gr.update(choices=vols, value=vols[0][1] if vols else None)

    def on_segment(sample, segment):
        vols = volume_choices(sample, segment)
        return gr.update(choices=vols, value=vols[0][1] if vols else None)

    def on_judge(judge):
        return gr.update(visible=judge == "claude")

    def new_pair(st):
        st = dict(st or GAME_STATE0)
        if not game.ok:
            raise CatalogError("the game's pictures are not on this copy of the Space")
        rng = np.random.default_rng()
        i = int(rng.integers(len(game.on)))
        kind = str(rng.choice(list(Game.KINDS)))
        on, other = game.on[i], game.other(i, kind, rng)
        n = min(on.shape[0], other.shape[0])           # a shuffle keeps whole tiles only
        on, other = on[:n, :n], other[:n, :n]
        fiber_is_a = bool(rng.integers(2))
        a, b = (on, other) if fiber_is_a else (other, on)
        p_a = game.judge_pair(a, b, on)
        st.update(round=st["round"] + (1 if st["answered"] else 0), answered=False, i=i, kind=kind,
                  fiber_is_a=fiber_is_a, model_says_a=p_a > 0.5, p_a=p_a)
        return png_of(a), png_of(b), "", score_line(dict(st, answered=True, round=st["round"] - 1)), st

    def answer(choice, st):
        st = dict(st or GAME_STATE0)
        if st.get("i") is None or st["answered"]:
            return gr.update(), score_line(st), st
        right = (choice == "A") == st["fiber_is_a"]
        model_right = st["model_says_a"] == st["fiber_is_a"]
        st["you"] += int(right)
        st["model"] += int(model_right)
        st["answered"] = True
        fiber_side = "A" if st["fiber_is_a"] else "B"
        conf = st["p_a"] if st["model_says_a"] else 1 - st["p_a"]
        reveal = (f"**{'Right!' if right else 'Not this time.'}** {fiber_side} is the CT on the traced surface; the "
                  f"other is {Game.KINDS[st['kind']]}. The free judge picked "
                  f"{'A' if st['model_says_a'] else 'B'} ({conf:.0%} sure){'' if model_right else ', and got it wrong'}."
                  f"\n\n<span class='fc-note'>From {html.escape(game.src[st['i']])}. Public scroll on no prize list; "
                  "CT from the Vesuvius Challenge open data, CC BY-NC 4.0.</span>")
        return reveal, score_line(st), st

    with gr.Blocks(title="Fiber Checker", delete_cache=(1800, 3600)) as demo:
        gr.HTML('<div class="fc-head"><div class="weave"></div><h1>Fiber Checker</h1><span>Are papyrus fibers '
                'visible on a traced scroll surface? A free fiber map of any segment, patch by patch.</span></div>')
        with gr.Tabs(elem_id="fc-tabs"):
            with gr.Tab("Check a segment", id="check"):
                gr.Markdown(INTRO)
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2, min_width=300):
                        ex = gr.Dropdown([(e["label"], i) for i, e in enumerate(EXAMPLES)], value=0,
                                         label="Example (public scrolls on no prize list)")
                        with gr.Tabs():
                            with gr.Tab("Open-data segment"):
                                sample = gr.Dropdown(sample_choices(), value=first["sample"], label="Scroll",
                                                     filterable=True)
                                segment = gr.Dropdown(segment_choices(first["sample"]), value=first["segment"],
                                                      label="Segment", filterable=True)
                                volume = gr.Dropdown(volume_choices(first["sample"], first["segment"]),
                                                     value=first["volume"], label="Scan its mesh is on")
                                go = gr.Button("Check fibers", variant="primary", size="lg")
                            with gr.Tab("Your own mesh"):
                                upload = gr.File(label="Zip of your tifxyz folder (x.tif, y.tif, z.tif)",
                                                 file_types=[".zip"], type="filepath", height=100)
                                up_vol = gr.Textbox(label="14-digit scan id its coordinates are in (level-0 voxels)",
                                                    placeholder="20250526151718")
                                go_up = gr.Button("Check my mesh", variant="primary", size="lg")
                        patches = gr.Radio(PATCHES, value=60, label="How much to check")
                        judge = gr.Radio([("Free local model (no key)", "local"),
                                          ("Claude (your own Anthropic key)", "claude")], value="local", label="Judge")
                        with gr.Group(visible=False) as claude_box:
                            key = gr.Textbox(label="Your Anthropic API key (used for this run only, never stored)",
                                             type="password", placeholder="your key")
                            max_usd = gr.Slider(0.5, 20, value=3, step=0.5, label="Spending cap (USD)")
                        gr.Markdown("Meshes are read from the open data; the CT is read live from its bucket, never "
                                    "copied here.", elem_classes="fc-note")
                    with gr.Column(scale=3, min_width=320):
                        pic = gr.Image(None, label="Fiber map over the segment's mesh grid", type="filepath",
                                       format="png", interactive=False, height=460)
                        gr.HTML(LEGEND)
                        summary = gr.HTML("<p class='fc-meta'>Your map and summary appear here. 60 patches take "
                                          "about two minutes; try <b>Fiber or not?</b> while you wait.</p>")
                        tiles = gr.Gallery(label="Clearest and weakest patches (the renders the judge saw)",
                                           columns=6, height=300, object_fit="contain", allow_preview=True)
                        dl = gr.File(label="Download: fiber.json, fiber.tif, fiber_map.png, report.html, tiles/",
                                     height=88, elem_id="fc-dl")
                        with gr.Accordion("Full report (report.html)", open=False):
                            report = gr.HTML()
                        with gr.Accordion("Record (fiber.json)", open=False):
                            record = gr.JSON()
                        with gr.Accordion("About the judges", open=False):
                            gr.Markdown(ABOUT_JUDGE.format(sha=WEIGHTS_SHA256[:16] + "…", cp=CLAUDE_PATCHES))
            with gr.Tab("Fiber or not?", id="game") as game_tab:
                gr.Markdown("Two renders of the same patch of a scroll. **One is the CT on the traced surface; the "
                            "other has lost its strands**, or sits a few voxels off the sheet. Which one shows "
                            "papyrus fibers? Then see if you beat the free judge.")
                st = gr.State(dict(GAME_STATE0))
                score_md = gr.Markdown(score_line(GAME_STATE0), elem_classes="fc-score")
                with gr.Row(elem_classes="fc-game"):
                    img_a = gr.Image(label="A", type="numpy", interactive=False, height=420)
                    img_b = gr.Image(label="B", type="numpy", interactive=False, height=420)
                with gr.Row():
                    pick_a = gr.Button("A has fibers", variant="primary")
                    pick_b = gr.Button("B has fibers", variant="primary")
                    nxt = gr.Button("New pair")
                reveal = gr.Markdown()
            with gr.Tab("Compare", id="compare"):
                gr.Markdown("Give two `fiber.json` files (from the downloads, or the command line tool): two "
                            "segments, two tracers, or one trace before and after an edit.")
                with gr.Row():
                    ca = gr.File(label="A: fiber.json", file_types=[".json"], type="filepath", height=100)
                    cb = gr.File(label="B: fiber.json", file_types=[".json"], type="filepath", height=100)
                cgo = gr.Button("Compare", variant="primary")
                cout = gr.JSON(label="Side by side")
            with gr.Tab("How-to guides", id="howto"):
                gr.Markdown(HOW_TO, elem_classes="fc-howto")
            with gr.Tab("Agents and API", id="agents"):
                gr.Markdown(AGENTS.format(host=host))
                with gr.Accordion("Connect your tool: the scans and meshes by URL", open=True):
                    gr.HTML(CONNECT_HTML.read_text() if CONNECT_HTML.exists() else "")
        gr.HTML('<footer class="fc-credit">Made by <a href="https://github.com/ChaseHendrick">Chase Hendrick</a> · '
                'scans and meshes: <a href="https://scrollprize.org">Vesuvius Challenge</a> open data, CC BY-NC 4.0 · '
                f'Fiber Checker {VERSION} · model output, not a reading</footer>')

        # hidden: the API endpoints and MCP tools for scripts and agents
        with gr.Row(visible=False):
            a_sample, a_segment, a_volume = (gr.Textbox(label=k) for k in ("sample", "segment", "volume"))
            a_patches = gr.Number(60, precision=0, label="patches")
            a_fa, a_fb = gr.File(), gr.File()
            a_json, a_img, a_file = gr.JSON(), gr.Image(type="filepath", format="png"), gr.File()
            a_btns = [gr.Button() for _ in range(5)]

        hidden = dict(api_visibility="private")
        ex.input(on_example, ex, [sample, segment, volume], **hidden)
        sample.input(on_sample, sample, [segment, volume], **hidden)
        segment.input(on_segment, [sample, segment], volume, **hidden)
        judge.change(on_judge, judge, claude_box, **hidden)
        outs = [pic, summary, tiles, dl, report, record]
        go.click(guard(on_check), [sample, segment, volume, patches, judge, key, max_usd], outs,
                 concurrency_id="check", concurrency_limit=2, **hidden)
        go_up.click(guard(on_upload), [upload, up_vol, patches, judge, key, max_usd], outs,
                    concurrency_id="check", concurrency_limit=2, **hidden)
        nxt.click(guard(new_pair), st, [img_a, img_b, reveal, score_md, st], **hidden)

        def first_pair(s):
            if (s or {}).get("i") is not None or not game.ok:
                return gr.update(), gr.update(), gr.update(), gr.update(), s
            return new_pair(s)
        game_tab.select(guard(first_pair), st, [img_a, img_b, reveal, score_md, st], **hidden)
        pick_a.click(lambda s: answer("A", s), st, [reveal, score_md, st], **hidden)
        pick_b.click(lambda s: answer("B", s), st, [reveal, score_md, st], **hidden)
        cgo.click(guard(compare_results), [ca, cb], cout, **hidden)

        def api_check(sample_, segment_, volume_, patches_, request: gr.Request, progress=gr.Progress()):
            return check_segment(sample_, segment_, volume_, int(patches_ or 60), request=request, progress=progress)
        api_check.__doc__ = check_segment.__doc__
        for btn, fn, i, o, name in ((a_btns[0], list_scrolls, [], a_json, "list_scrolls"),
                                    (a_btns[1], list_segments, [a_sample], a_json, "list_segments"),
                                    (a_btns[2], example_segments, [], a_json, "example_segments"),
                                    (a_btns[3], api_check, [a_sample, a_segment, a_volume, a_patches],
                                     [a_img, a_json, a_file], "check_segment"),
                                    (a_btns[4], compare_results, [a_fa, a_fb], a_json, "compare_results")):
            heavy = name == "check_segment"
            btn.click(guard(fn), i, o, api_name=name, api_description=fn.__doc__.split("\n\n")[0],
                      concurrency_id="check" if heavy else None, concurrency_limit=2 if heavy else 8)
        demo.load(None, None, None, js=TAB_JS)
    return demo


def fix_mcp_multiple_outputs():
    """Gradio 6.28's MCP server joins a queued tool's several outputs into one text; hand them over one by one, so
    check_segment's picture reaches an agent as a picture (as Lasagna Fields does)."""
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
    return dict(theme=theme(), css=CSS, head=HEAD, footer_links=["api", "gradio"], mcp_server=True,
                max_file_size="200mb", allowed_paths=[str(OUT)])


if __name__ == "__main__":
    startup()
    fix_mcp_multiple_outputs()
    build_demo().queue(max_size=64, default_concurrency_limit=8).launch(**launch_kwargs())
