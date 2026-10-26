"""fibercheck: are papyrus fibers visible on a traced surface? A per-patch fiber map of a tifxyz segment, judged by a
small local model (no key) or by Claude (your own Anthropic key).

For each square patch of the segment the CT is rendered along the surface (the depth with the brightest mean within
5 voxels, as in the frozen fiber procedure), and the judge compares that render with a phase-scrambled copy of itself
(same texture statistics, long strands destroyed). The fiber evidence is the judge's preference for the render: near
1 where fibers show, near 0.5 where the render looks no more fibrous than scrambled texture. Every run also judges
built-in controls (noise, blur, phase scramble) on a sample of its own patches and says if they did not fail.

Outputs in --out: fiber.json (every patch and the run's self-check), fiber_map.png, fiber.tif (one value per segment
vertex, NaN where unscored, the segment's grid so it lines up with x.tif), report.html, and tiles/ (the six clearest
and six weakest patch renders as PNG).

  python3 scripts/fibercheck/fibercheck.py score SEGMENT.tifxyz --ct CT_ZARR [--level 2] --out DIR
  python3 scripts/fibercheck/fibercheck.py compare DIR_A DIR_B --out DIR

CT_ZARR is an OME-zarr root (a local path or an https URL, for example the open-data bucket); the segment's
coordinates are in that volume's level-0 voxels. Model output, never a reading.
"""
import argparse, base64, html, io, json, math, sys, time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DEPTHS = np.arange(-5, 6)
# the frozen fiber prompt, word for word as in the tests where Claude's fiber answers were valid
PROMPT = ("Image A is shown first and image B second. Both are X-ray CT renderings of a small patch of a surface "
          "inside a rolled, carbonized papyrus scroll. Which image shows papyrus fibre texture (long, thin, parallel "
          "strands) more clearly? Answer with exactly one word: A, B, or SAME.")
OPEN_DATA = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"


# ---------- segment geometry ----------

def read_tifxyz(folder):
    """xyz (H, W, 3) in level-0 voxels and valid (H, W); -1, NaN and all-zero vertices are holes."""
    import tifffile
    folder = Path(folder)
    x, y, z = (tifffile.imread(folder / f"{c}.tif").astype(np.float64) for c in "xyz")
    xyz = np.stack([x, y, z], -1)
    valid = np.isfinite(xyz).all(-1) & (xyz != -1).all(-1) & (np.abs(xyz).sum(-1) > 0)
    return xyz, valid


def normals(xyz, valid):
    """Unit normal per vertex from central differences; ok where it and its four neighbours are valid."""
    du = np.zeros_like(xyz)
    dv = np.zeros_like(xyz)
    du[:, 1:-1] = xyz[:, 2:] - xyz[:, :-2]
    dv[1:-1] = xyz[2:] - xyz[:-2]
    n = np.cross(du, dv)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    n = n / np.maximum(ln, 1e-9)
    ok = valid.copy()
    ok[:, 1:-1] &= valid[:, 2:] & valid[:, :-2]
    ok[1:-1] &= valid[2:] & valid[:-2]
    ok[[0, -1], :] = False
    ok[:, [0, -1]] = False
    return n, ok & (ln[..., 0] > 0)


def auto_k(xyz, valid, level):
    """Upsampling per vertex step that gives about one voxel per pixel at `level`: the median vertex spacing."""
    d = np.linalg.norm(np.diff(xyz, axis=1), axis=-1)[valid[:, 1:] & valid[:, :-1]]
    if not d.size:
        return 5
    return int(np.clip(round(float(np.median(d)) * 0.5 ** level), 1, 12))


def upsample(a, k):
    """Bilinear upsampling of a (P, P, C) grid by k per step: ((P-1)*k+1, ...)."""
    p = a.shape[0]
    t = np.linspace(0, p - 1, (p - 1) * k + 1)
    i0 = np.clip(np.floor(t).astype(int), 0, p - 2)
    f = t - i0
    rows = a[i0] * (1 - f[:, None, None]) + a[i0 + 1] * f[:, None, None]
    return rows[:, i0] * (1 - f[None, :, None]) + rows[:, i0 + 1] * f[None, :, None]


# ---------- CT ----------

class CT:
    """Nearest-voxel samples of one level of an OME-zarr (zarr v2) volume, local or over https, with a chunk cache."""

    def __init__(self, root, level, cache=None):
        self.base = f"{str(root).rstrip('/')}/{level}"
        self.remote = self.base.startswith("http")
        self.cache = Path(cache or Path.home() / ".cache" / "fibercheck") / self.base.split("://")[-1].replace("/", "_")
        meta = json.loads(self._get(".zarray"))
        import numcodecs
        self.shape, self.chunks = tuple(meta["shape"]), tuple(meta["chunks"])
        self.dtype, self.order = np.dtype(meta["dtype"]), meta.get("order", "C")
        self.fill = meta.get("fill_value") or 0
        self.sep = meta.get("dimension_separator", ".")
        self.codec = numcodecs.get_codec(meta["compressor"]) if meta.get("compressor") else None
        self.mem = {}

    def _get(self, name, optional=False):
        f = self.cache / name
        if f.is_file() and f.stat().st_size:
            return f.read_bytes()
        if self.remote:
            import urllib.error, urllib.request
            for i in range(4):
                try:
                    with urllib.request.urlopen(f"{self.base}/{name}", timeout=60) as r:
                        data = r.read()
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (403, 404) and optional:
                        return None
                    if i == 3:
                        raise
                except OSError:
                    if i == 3:
                        raise
                time.sleep(2 * (i + 1))
        else:
            q = Path(self.base) / name
            if not q.is_file():
                if optional:
                    return None
                raise FileNotFoundError(q)
            return q.read_bytes()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(f)          # atomic, so a full disk never leaves a truncated chunk in the cache
        return data

    def chunk(self, idx):
        if idx not in self.mem:
            raw = self._get(self.sep.join(map(str, idx)), optional=True)
            if raw is None:
                a = np.full(self.chunks, self.fill, self.dtype)
            else:
                b = self.codec.decode(raw) if self.codec else raw
                a = np.frombuffer(b, self.dtype).reshape(self.chunks, order=self.order)
            if len(self.mem) > 512:
                self.mem.clear()
            self.mem[idx] = a
        return self.mem[idx]

    def values(self, zyx):
        """zyx (N, 3) voxel indices; outside the volume reads 0."""
        zyx = np.asarray(zyx, dtype=np.int64)
        out = np.zeros(len(zyx), dtype=np.float32)
        inside = ((zyx >= 0) & (zyx < np.array(self.shape))).all(1)
        q = zyx[inside]
        ci = q // np.array(self.chunks)
        keys, inv = np.unique(ci, axis=0, return_inverse=True)
        vals = np.zeros(len(q), np.float32)
        inv = inv.reshape(-1)
        for j, k in enumerate(keys):
            sel = inv == j
            r = q[sel] - k * np.array(self.chunks)
            vals[sel] = self.chunk(tuple(int(v) for v in k))[r[:, 0], r[:, 1], r[:, 2]]
        out[inside] = vals
        return out


# ---------- rendering ----------

def render_patches(folder, ct, level, P, K, stride=None, max_patches=None, masked=0.01, say=print):
    """Grid patches of P x P vertices, each rendered at DEPTHS along its normals. Returns a list of dicts with r, c,
    t0 (the brightest depth, the frozen rule) and stack (len(DEPTHS), n, n)."""
    xyz, valid = read_tifxyz(folder)
    if not K:
        K = auto_k(xyz, valid, level)
        say and say(f"upsampling {K} per vertex step (about one voxel per pixel at level {level})")
    xyz = xyz * 0.5 ** level
    nrm, ok = normals(xyz, valid)
    H, W = valid.shape
    stride = stride or P
    spots = [(r, c) for r in range(0, H - P + 1, stride) for c in range(0, W - P + 1, stride)
             if ok[r:r + P, c:c + P].all()]
    if max_patches and len(spots) > max_patches:
        keep = np.random.default_rng(0).choice(len(spots), max_patches, replace=False)
        spots = [spots[i] for i in sorted(keep)]
    out = []
    t0 = time.time()
    for i, (r, c) in enumerate(spots):
        up = upsample(xyz[r:r + P, c:c + P], K)
        nu = upsample(nrm[r:r + P, c:c + P], K)
        nu /= np.maximum(np.linalg.norm(nu, axis=-1, keepdims=True), 1e-9)
        pts = up[None] + DEPTHS[:, None, None, None] * nu[None]
        zyx = np.rint(pts.reshape(-1, 3)[:, ::-1])
        stack = ct.values(zyx).reshape(len(DEPTHS), *up.shape[:2]).astype(np.float64)
        means = stack.mean((1, 2))
        ti = int(np.argmax(means))
        if means[ti] <= 0 or (stack[ti] == 0).mean() > masked:
            continue
        out.append({"r": r, "c": c, "t0": int(DEPTHS[ti]), "stack": stack})
        if say and (i + 1) % 25 == 0:
            say(f"PROGRESS {i + 1}/{len(spots)} patches rendered ({time.time() - t0:.0f} s)")
    return out, valid, K


def to_input(img, ref):
    """The frozen PNG grey scale (1 and 99 percentiles of the on render), then z-scored, as the model was trained."""
    lo, hi = np.percentile(ref, [1, 99])
    a = np.clip((img - lo) / max(hi - lo, 1e-6), 0, 1)
    a = np.round(a * 255) / 255
    a = a.astype(np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)


# ---------- judges ----------

class LocalJudge:
    name = "local"

    def __init__(self, weights):
        import fcmodel as M
        self.M = M
        self.m = M.load_model(weights)

    def score(self, imgs):
        """Fiber score per image (mean over four quarter turns), imgs already through to_input."""
        import torch
        out = []
        with torch.no_grad():
            for a in imgs:
                n = min(a.shape)
                a = a[:n, :n]
                x = torch.from_numpy(np.stack([np.ascontiguousarray(np.rot90(a, r)) for r in range(4)]))[:, None]
                s = self.m(x)[:, 0].numpy()
                out.append(s)
        return np.array(out)          # (N, 4): one score per quarter turn

    def prefer(self, a_imgs, b_imgs):
        """P(a shows fiber more clearly than b) per pair, and whether the quarter turns disagree on the side."""
        sa, sb = self.score(a_imgs), self.score(b_imgs)
        d = sa - sb
        p = 1 / (1 + np.exp(-d.mean(1)))
        unsure = (np.sign(d).min(1) != np.sign(d).max(1))
        return p, unsure


class AnthropicJudge:
    """Claude with the user's own key (ANTHROPIC_API_KEY), the frozen fiber prompt, effort high, both orders."""
    name = "claude"
    MODEL = "claude-opus-5-5"

    def __init__(self, max_usd, api_key=None):
        import os
        import anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("fibercheck: --judge claude needs ANTHROPIC_API_KEY (your own key)")
        self.client = anthropic.Anthropic(api_key=key)      # held for this run only, never written anywhere
        self.max_usd, self.usd = max_usd, 0.0
        self.prompt = PROMPT

    def _png(self, a):
        from PIL import Image
        b = np.clip((a - a.min()) / max(np.ptp(a), 1e-6), 0, 1)
        im = Image.fromarray((b * 255).astype(np.uint8))
        im = im.resize((im.width * 3, im.height * 3), Image.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _ask(self, x, y):
        if self.usd >= self.max_usd:
            return None
        r = self.client.messages.create(
            model=self.MODEL, max_tokens=4000, thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": {
                "type": "object", "properties": {"answer": {"type": "string", "enum": ["A", "B", "SAME"]}},
                "required": ["answer"], "additionalProperties": False}}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": self._png(x)}},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": self._png(y)}},
                {"type": "text", "text": self.prompt}]}])
        u = r.usage
        self.usd += (u.input_tokens * 5 + u.output_tokens * 25) / 1e6
        txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        try:
            return json.loads(txt)["answer"]
        except Exception:
            return None

    def prefer(self, a_imgs, b_imgs):
        ps, unsure = [], []
        for a, b in zip(a_imgs, b_imgs):
            v1 = {"A": 1.0, "B": 0.0, "SAME": 0.5}.get(self._ask(a, b))
            v2 = {"A": 0.0, "B": 1.0, "SAME": 0.5}.get(self._ask(b, a))
            vs = [v for v in (v1, v2) if v is not None]
            ps.append(float(np.mean(vs)) if vs else np.nan)
            unsure.append(len(vs) < 2 or v1 != v2)
        return np.array(ps), np.array(unsure)


# ---------- controls ----------

def phase_scramble(a, seed):
    rng = np.random.default_rng(seed)
    f = np.fft.fft2(a)
    ph = np.angle(np.fft.fft2(rng.standard_normal(a.shape)))
    b = np.real(np.fft.ifft2(np.abs(f) * np.exp(1j * ph)))
    return (b - b.mean()) / (b.std() + 1e-6) * a.std() + a.mean()


def controls(on, rng):
    from scipy.ndimage import gaussian_filter
    return {"noise": on + rng.normal(0, on.std(), on.shape), "blur": gaussian_filter(on, 3.0),
            "scramble": phase_scramble(on, int(rng.integers(1 << 30)))}


# ---------- hints (untested ideas until their own tests pass) ----------

def fiber_direction(img):
    """Dominant strand direction in the segment's grid from the structure tensor: 'horizontal' (strands along the
    grid's columns axis, around the winding in most tifxyz traces, as recto fibers run) or 'vertical' (along its
    rows axis, the scroll axis, as verso fibers run), with its coherence. A recto/verso hint: untested idea."""
    from scipy.ndimage import gaussian_filter, sobel
    a = gaussian_filter(img.astype(np.float64), 1.0)
    gx, gy = sobel(a, 1), sobel(a, 0)
    jxx, jyy, jxy = (float((q).mean()) for q in (gx * gx, gy * gy, gx * gy))
    coh = math.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / max(jxx + jyy, 1e-9)
    # strands run perpendicular to the dominant gradient
    return ("horizontal" if jyy > jxx else "vertical"), round(coh, 3)


def jump_hints(patches, grid_step):
    """Patches whose evidence is under 0.5 while every scored neighbour is over 0.8: a drop that may mark a sheet jump
    or a stretch off the sheet. Untested idea."""
    at = {(p["r"], p["c"]): p["evidence"] for p in patches}
    out = []
    for p in patches:
        nb = [at.get((p["r"] + dr, p["c"] + dc)) for dr, dc in
              ((grid_step, 0), (-grid_step, 0), (0, grid_step), (0, -grid_step))]
        nb = [v for v in nb if v is not None]
        if len(nb) >= 2 and p["evidence"] < 0.5 and min(nb) > 0.8:
            out.append({"r": p["r"], "c": p["c"]})
    return out


# ---------- score ----------

def score(a, say=None, api_key=None):
    """Score one segment; `a` holds the score command's options. `say` gets progress lines (default: print)."""
    ct = CT(a.ct, a.level, a.cache)
    say = say or ((lambda *_: None) if a.json else print)
    pts, valid, K = render_patches(a.segment, ct, a.level, a.p, a.k, a.stride, a.max_patches, say=say)
    H, W = valid.shape
    if not pts:
        raise SystemExit("fibercheck: no patch of the segment could be rendered (holes, masked CT or wrong --ct)")
    judge = LocalJudge(a.weights) if a.judge == "local" else AnthropicJudge(a.max_usd, api_key)
    say(f"judging {len(pts)} patches with the {judge.name} judge")
    rng = np.random.default_rng(0)
    ons, scr, depth_in = [], [], []
    for p in pts:
        on = p["stack"][list(DEPTHS).index(p["t0"])]
        ons.append(to_input(on, on))
        scr.append(to_input(phase_scramble(on, 7), on))
    ev, unsure = judge.prefer(ons, scr)
    # best depth: the judge's preference for each depth against the frozen depth (local judge only, cheap)
    best = [p["t0"] for p in pts]
    if judge.name == "local":
        for i, p in enumerate(pts):
            on = p["stack"][list(DEPTHS).index(p["t0"])]
            sc = judge.score([to_input(s, on) for s in p["stack"]]).mean(1)
            best[i] = int(DEPTHS[int(np.argmax(sc))])
    # self-check: the judge must prefer the render over its own controls on a sample of patches
    say("self-check: the judge against noised, blurred and scrambled copies")
    idx = rng.choice(len(pts), min(len(pts), getattr(a, "check_n", 40)), replace=False)
    check = {}
    for kind in ("noise", "blur", "scramble"):
        A, B = [], []
        for i in idx:
            on = pts[i]["stack"][list(DEPTHS).index(pts[i]["t0"])]
            A.append(to_input(on, on))
            B.append(to_input(controls(on, np.random.default_rng(int(i)))[kind], on))
        pa, _ = judge.prefer(A, B)
        check[kind] = round(float(np.nanmean(pa > 0.5)), 3)
    passed = all(v >= 0.8 for v in check.values())
    patches = []
    for i, p in enumerate(pts):
        on = p["stack"][list(DEPTHS).index(p["t0"])]
        d, coh = fiber_direction(on)
        patches.append({"r": p["r"], "c": p["c"], "t0": p["t0"], "evidence": round(float(ev[i]), 4),
                        "unsure": bool(unsure[i]), "best_depth": best[i], "direction": d, "coherence": coh})
    vis = [p["evidence"] for p in patches]
    summary = {"patches": len(patches), "median_evidence": round(float(np.nanmedian(vis)), 3),
               "share_fibers_visible": round(float(np.nanmean(np.array(vis) >= 0.75)), 3),
               "share_unsure": round(float(np.mean([p["unsure"] for p in patches])), 3),
               "self_check": {"against": check, "passed": passed},
               "depth_offset_median": float(np.median([p["best_depth"] - p["t0"] for p in patches])),
               "direction_share_horizontal": round(float(np.mean([p["direction"] == "horizontal" for p in patches])), 3)}
    rec = {"tool": "fibercheck", "version": "0.1.0-dev", "judge": judge.name, "segment": str(a.segment),
           "ct": str(a.ct), "level": a.level, "patch_vertices": a.p, "upsample": K, "grid": [H, W],
           "summary": summary, "jump_hints": jump_hints(patches, a.stride or a.p), "patches": patches,
           "claims": "Model output. Best depth, direction and jump hints are untested ideas."}
    if judge.name == "claude":
        rec["usd"] = round(judge.usd, 4)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fiber.json").write_text(json.dumps(rec, indent=1))
    write_maps(rec, out, valid)
    write_report(rec, pts, out)
    if a.json:
        print(json.dumps(summary))
    else:
        print(f"fibercheck: {summary['patches']} patches, fibers visible on {summary['share_fibers_visible']:.0%} "
              f"(median evidence {summary['median_evidence']:.2f}), self-check "
              f"{'passed' if passed else 'FAILED'}; wrote {out}/fiber.json, fiber_map.png, fiber.tif, report.html")
    return rec


def write_maps(rec, out, valid=None):
    import tifffile
    from PIL import Image
    H, W = rec["grid"]
    P = rec["patch_vertices"]
    m = np.full((H, W), np.nan, np.float32)
    for p in rec["patches"]:
        m[p["r"]:p["r"] + P, p["c"]:p["c"] + P] = p["evidence"]
    tifffile.imwrite(out / "fiber.tif", m, compression="zlib")
    rgb = colour(m)
    if valid is not None:
        rgb[np.isnan(m) & valid] = (52, 54, 64)          # traced but not scored: the segment's shape
    im = Image.fromarray(rgb)
    s = max(1, 800 // max(H, W))
    im.resize((W * s, H * s), Image.NEAREST).save(out / "fiber_map.png")


def colour(m):
    """Evidence 0.5 to 1 on a colour-blind-safe scale (grey below 0.5 means no sign of fiber), holes transparent-dark."""
    stops = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]], float)
    v = np.clip((np.nan_to_num(m, nan=0) - 0.5) / 0.5, 0, 1)
    pos = v * (len(stops) - 1)
    i = np.clip(np.floor(pos).astype(int), 0, len(stops) - 2)
    f = (pos - i)[..., None]
    rgb = stops[i] * (1 - f) + stops[i + 1] * f
    rgb[np.isnan(m)] = (24, 24, 28)
    rgb[(~np.isnan(m)) & (m < 0.5)] = (110, 110, 110)
    return rgb.astype(np.uint8)


def _img_png(a, save=None):
    """PNG bytes of a render (1 and 99 percentile grey scale, drawn 2 pixels per voxel); also written to `save`."""
    from PIL import Image
    b = np.clip((a - np.percentile(a, 1)) / max(np.percentile(a, 99) - np.percentile(a, 1), 1e-6), 0, 1)
    im = Image.fromarray((b * 255).astype(np.uint8)).resize((a.shape[1] * 2, a.shape[0] * 2), Image.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    if save:
        Path(save).write_bytes(buf.getvalue())
    return buf.getvalue()


def _img_b64(a, save=None):
    return base64.b64encode(_img_png(a, save)).decode()


def write_report(rec, pts, out):
    """One page: the map, the self-check, the clearest and weakest patches, and the method, in the prize's words."""
    s = rec["summary"]
    order = sorted(range(len(pts)), key=lambda i: rec["patches"][i]["evidence"])
    top = order[-6:][::-1]
    pick = top + [i for i in order[:6] if i not in top]
    tiles = []
    (out / "tiles").mkdir(exist_ok=True)
    for n, i in enumerate(pick):
        p, q = pts[i], rec["patches"][i]
        on = p["stack"][list(DEPTHS).index(p["t0"])]
        kind = "clearest" if n < len(top) else "weakest"
        save = out / "tiles" / f"{n:02d}-{kind}-r{q['r']}-c{q['c']}-{q['evidence']:.2f}.png"
        tiles.append(f'<figure><img src="data:image/png;base64,{_img_b64(on, save)}" alt="patch r{q["r"]} c{q["c"]}">'
                     f'<figcaption>r {q["r"]}, c {q["c"]}: {q["evidence"]:.2f}{" (unsure)" if q["unsure"] else ""}'
                     f'</figcaption></figure>')
    with open(out / "fiber_map.png", "rb") as f:
        mp = base64.b64encode(f.read()).decode()
    ck = s["self_check"]
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Fiber check</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1f;--mut:#5f5f66;--card:#fff;--line:#e4e1da;--ok:#1f7a4d;--bad:#b3261e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#15161a;--fg:#ececf0;--mut:#a3a3ad;--card:#1e2026;--line:#30323a;--ok:#5fd39a;--bad:#ff8a80}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:19px;margin:32px 0 10px}}
.sub{{color:var(--mut)}} .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.big{{font-size:26px;font-weight:650}} .ok{{color:var(--ok)}} .bad{{color:var(--bad)}}
.map{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center}}
.map img{{max-width:100%;image-rendering:pixelated}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px}}
figure img{{width:100%;border-radius:6px}} figcaption{{font-size:13px;color:var(--mut);margin-top:4px}}
</style><main>
<h1>Fiber check</h1>
<div class="sub">{html.escape(Path(rec["segment"]).name)} &middot; judge: {rec["judge"]} &middot; level {rec["level"]}</div>
<div class="cards">
<div class="card"><div class="big">{s["share_fibers_visible"]:.0%}</div>patches with fibers visible (evidence 0.75 or more)</div>
<div class="card"><div class="big">{s["median_evidence"]:.2f}</div>median fiber evidence (0.5 is none, 1 is clear)</div>
<div class="card"><div class="big">{s["patches"]}</div>patches checked</div>
<div class="card"><div class="big {'ok' if ck['passed'] else 'bad'}">{'passed' if ck['passed'] else 'failed'}</div>self-check: noise {ck['against']['noise']:.0%}, blur {ck['against']['blur']:.0%}, scramble {ck['against']['scramble']:.0%}</div>
</div>
<h2>Fiber map</h2><div class="map"><img src="data:image/png;base64,{mp}" alt="fiber evidence over the segment">
<div class="sub">Yellow: clear fiber. Purple: weak. Grey: no sign of fiber. Slate: traced but not scored. Black: no surface.</div></div>
<h2>Clearest and weakest patches</h2><div class="grid">{''.join(tiles)}</div>
<h2>Method</h2><p>The Progress Prize asks entrants to "show visually that papyrus fibers are visible on your output surface"
(scrollprize.org/prizes). For each patch, the CT is rendered along the surface and the judge compares that render with
a copy whose texture is kept but whose strands are scrambled. The evidence is how strongly the judge prefers the real
render. The self-check confirms the judge prefers each render over its noised, blurred and scrambled copies. This is
model output; best depth, fiber direction and jump hints are untested ideas.</p>
</main></html>"""
    (out / "report.html").write_text(page)


# ---------- compare ----------

def compare(a):
    ra, rb = (json.loads((Path(d) / "fiber.json").read_text()) for d in (a.a, a.b))
    rows = []
    for k in ("patches", "median_evidence", "share_fibers_visible", "share_unsure"):
        rows.append((k, ra["summary"][k], rb["summary"][k]))
    same_grid = ra["grid"] == rb["grid"] and ra["patch_vertices"] == rb["patch_vertices"]
    paired = None
    if same_grid:
        ea = {(p["r"], p["c"]): p["evidence"] for p in ra["patches"]}
        both = [(ea[(p["r"], p["c"])], p["evidence"]) for p in rb["patches"] if (p["r"], p["c"]) in ea]
        if both:
            d = np.array([x - y for x, y in both])
            paired = {"patches": len(both), "a_better": round(float((d > 0.05).mean()), 3),
                      "b_better": round(float((d < -0.05).mean()), 3), "mean_diff": round(float(d.mean()), 4)}
    res = {"a": a.a, "b": a.b, "summary": {k: [x, y] for k, x, y in rows}, "paired_same_grid": paired}
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        (Path(a.out) / "compare.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=None if a.json else 1))


def main():
    ap = argparse.ArgumentParser(prog="fibercheck", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="fiber map of one tifxyz segment")
    s.add_argument("segment", type=Path)
    s.add_argument("--ct", required=True, help="OME-zarr root of the segment's volume (path or https URL)")
    s.add_argument("--level", type=int, default=2, help="pyramid level to read (2 for 2.4 um scans, 0 for 7.9 um)")
    s.add_argument("--p", type=int, default=28, help="vertices per patch side")
    s.add_argument("--k", type=int, default=5, help="upsampling per vertex step: 5 is the tested setting (open-data "
                   "tifxyz on 2.2 to 2.4 um scans at level 2); 0 picks the median vertex spacing, about one voxel per pixel")
    s.add_argument("--check-n", type=int, default=40, help="patches sampled for each self-check control")
    s.add_argument("--stride", type=int, default=None, help="grid step in vertices (default: --p, no overlap)")
    s.add_argument("--max-patches", type=int, default=400)
    s.add_argument("--judge", choices=["local", "claude"], default="local")
    s.add_argument("--weights", default=str(HERE / "weights" / "fibercheck-local.pt"))
    s.add_argument("--max-usd", type=float, default=2.0, help="--judge claude: stop asking past this spend")
    s.add_argument("--cache", type=Path, default=None)
    s.add_argument("--out", required=True)
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("compare", help="two fiber maps side by side (paired when they share a grid)")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--out")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args()
    {"score": score, "compare": compare}[a.cmd](a)


if __name__ == "__main__":
    main()
