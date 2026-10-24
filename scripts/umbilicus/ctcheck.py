"""Draw umbilicus (scroll center) files on CT slices so a person can check them by eye.

    python ctcheck.py --a DIR_A --b DIR_B --out OUT [--scrolls S ...] [--n 6] [--cache DIR]

DIR_A holds the centers to check (drawn red), DIR_B the ones to compare with (drawn cyan); both hold
<scroll>_umbilicus.json or <scroll>/umbilicus.json files (predict.py --vc3d-name) with control points in level-0
voxels. For each scroll, slices are taken at
control-point heights spread along the file's band, plus the height where A and B differ most and the height
where A moves fastest sideways. Each slice is shown whole (level 2) and zoomed around A's center (level 1 and
level 0). Planes are read from the open-data bucket with HTTP range requests (chunks are raw 128^3 uint8).
Writes OUT/<scroll>_ct_check.png (one sheet), OUT/<scroll>/<scroll>_z<z>.png (one row per slice) and
OUT/summary.json. The pictures show CT from the open-data bucket (CC BY-NC 4.0); keep OUT out of Git like other scan
data. Needs numpy, requests, matplotlib and Pillow (pip install matplotlib brings Pillow).
"""
import argparse, hashlib, json, os, sys, time
import numpy as np
import requests
from concurrent.futures import ThreadPoolExecutor

B = "https://vesuvius-challenge-open-data.s3.amazonaws.com/"
C = 128
_S = requests.Session()
_S.mount("https://", requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64))


def get_range(url, lo, hi, retries=6):
    """Bytes lo..hi of url; None only on NoSuchKey (S3 sometimes answers 404 for keys it holds)."""
    last = None
    for i in range(retries):
        try:
            r = _S.get(url, headers={"Range": f"bytes={lo}-{hi}"}, timeout=60)
        except Exception as e:
            last = e; time.sleep(min(2 ** i, 20)); continue
        if r.status_code in (200, 206):
            return r.content if r.status_code == 206 else r.content[lo:hi + 1]
        if r.status_code == 404 and b"NoSuchKey" in r.content:
            return None
        last = r.status_code; time.sleep(min(2 ** i, 20))
    raise RuntimeError(f"{url}: {last}")


class Level:
    def __init__(self, vol, level):
        self.vol, self.level = vol.rstrip("/"), level
        m = json.loads(_S.get(f"{B}{self.vol}/{level}/.zarray", timeout=60).content)
        assert m["compressor"] is None and m["chunks"] == [C, C, C] and m["dtype"] == "|u1" and m["order"] == "C", m
        self.shape, self.sep = m["shape"], m.get("dimension_separator", ".")
        self.missing = 0

    def plane(self, z, y0=0, y1=None, x0=0, x1=None, threads=48):
        """One z plane (level coordinates), rows y0:y1, columns x0:x1 (clipped to the volume; outside is 0)."""
        y1 = self.shape[1] if y1 is None else y1; x1 = self.shape[2] if x1 is None else x1
        out = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cz, zi = divmod(int(z), C)
        ya, yb = max(0, y0), min(self.shape[1], y1); xa, xb = max(0, x0), min(self.shape[2], x1)
        if ya >= yb or xa >= xb:
            return out
        jobs = [(cy, cx) for cy in range(ya // C, (yb - 1) // C + 1) for cx in range(xa // C, (xb - 1) // C + 1)]

        def one(j):
            cy, cx = j
            url = f"{B}{self.vol}/{self.level}/" + self.sep.join(map(str, (cz, cy, cx)))
            return get_range(url, zi * C * C, (zi + 1) * C * C - 1)

        with ThreadPoolExecutor(threads) as ex:
            res = list(ex.map(one, jobs))
        for (cy, cx), raw in zip(jobs, res):
            if raw is None:
                self.missing += 1; continue
            t = np.frombuffer(raw, np.uint8).reshape(C, C)
            gy, gx = cy * C, cx * C
            sy, ey = max(gy, ya), min(gy + C, yb); sx, ex_ = max(gx, xa), min(gx + C, xb)
            out[sy - y0:ey - y0, sx - x0:ex_ - x0] = t[sy - gy:ey - gy, sx - gx:ex_ - gx]
        return out


def umb_files(folder):
    """{scroll: path} of the umbilicus files in folder: <scroll>_umbilicus.json and <scroll>/umbilicus.json (the name
    VC3D looks for, written by predict.py --vc3d-name). A scroll in both layouts is refused."""
    out = {}
    for f in sorted(os.listdir(folder)):
        p = os.path.join(folder, f)
        s = f[:-len("_umbilicus.json")] if f.endswith("_umbilicus.json") and os.path.isfile(p) else None
        if s is None and os.path.isfile(os.path.join(p, "umbilicus.json")):
            s, p = f, os.path.join(p, "umbilicus.json")
        if s is None:
            continue
        if s in out:
            raise SystemExit(f"{folder}: {s} has both {s}_umbilicus.json and {s}/umbilicus.json; keep one")
        out[s] = p
    return out


def load_umb(path):
    with open(path) as fh:
        j = json.load(fh)
    P = np.array([[p["z"], p["y"], p["x"]] for p in sorted(j["control_points"], key=lambda p: p["z"])], float)
    return P, j["metadata"]


def at(P, z):
    return np.array([np.interp(z, P[:, 0], P[:, 1]), np.interp(z, P[:, 0], P[:, 2])])


def pick_slices(A, Bp, n):
    """n control-point heights spread along A's band, plus where A and B differ most and where A moves fastest."""
    z = A[:, 0]
    fr = np.linspace(0.03, 0.97, n)
    idx = sorted({int(round(f * (len(z) - 1))) for f in fr})
    why = {i: "spread" for i in idx}
    d = np.array([np.hypot(*(at(A, zz) - at(Bp, zz))) for zz in z])
    sp = np.r_[0, np.hypot(np.diff(A[:, 1]), np.diff(A[:, 2])) / np.diff(z)]
    for i, w in ((int(np.argmax(d)), "largest red-cyan gap"), (int(np.argmax(sp)), "fastest sideways move")):
        if min(abs(i - k) for k in why) > max(2, len(z) // 30):
            why[i] = w
        else:
            k = min(why, key=lambda k: abs(i - k))
            why[k] += f", near the {w}"
    return [(int(z[i]), why[i]) for i in sorted(why)], d, sp


def norm(img, lo=None, hi=None):
    v = img[img > 0]
    if lo is None:
        lo, hi = (np.percentile(v, 1), np.percentile(v, 99.7)) if v.size > 100 else (0, 255)
    return np.clip((img.astype(np.float32) - lo) / max(1.0, hi - lo), 0, 1), (lo, hi)


def cyan(ax, p, shape, gap_mm):
    """Cyan x at p (row, col); if it falls outside the panel, an arrow at the edge pointing to it."""
    Y, X = shape
    if 0 <= p[0] < Y and 0 <= p[1] < X:
        ax.plot(p[1], p[0], "x", color="cyan", ms=9, mew=1.6); return
    c = np.array([Y / 2, X / 2]); v = p - c
    t = min((Y / 2 * 0.9) / max(abs(v[0]), 1e-9), (X / 2 * 0.9) / max(abs(v[1]), 1e-9))
    e = c + v * t
    ax.annotate("", xy=(e[1], e[0]), xytext=(c[1] + v[1] * t * 0.8, c[0] + v[0] * t * 0.8),
                arrowprops=dict(arrowstyle="->", color="cyan", lw=1.6))
    s = c + v * t * 0.8
    ax.text(s[1], s[0], f"cyan {gap_mm:.1f} mm ", color="cyan", fontsize=9,
            ha="right" if v[1] > 0 else "left", va="center")


def draw_row(ax3, r, s, zr, um, a, plt, Rectangle, Circle):
    w = r["whole"]; nz = np.argwhere(w > 0)
    if len(nz):
        (ya, xa), (yb, xb) = nz.min(0), nz.max(0)
    else:
        ya, xa, yb, xb = 0, 0, w.shape[0] - 1, w.shape[1] - 1
    m = 20; ya, xa = max(0, ya - m), max(0, xa - m); yb, xb = min(w.shape[0], yb + m), min(w.shape[1], xb + m)
    img, lohi = norm(w[ya:yb, xa:xb])
    ax = ax3[0]; ax.imshow(img, cmap="gray", interpolation="lanczos")
    pa = (r["ca"] / 4 - [ya, xa]); pb = (r["cb"] / 4 - [ya, xa])
    ax.plot(pb[1], pb[0], "x", color="cyan", ms=9, mew=1.6)
    ax.plot(pa[1], pa[0], "+", color="red", ms=11, mew=1.6)
    hh = r["h1"] / 2; ax.add_patch(Rectangle((pa[1] - hh, pa[0] - hh), 2 * hh, 2 * hh, fill=False, ec="yellow", lw=1))
    px = 1000 / um / 4 * 5; Y, X = img.shape
    ax.plot([X * 0.04, X * 0.04 + px], [Y * 0.96] * 2, color="white", lw=3)
    ax.text(X * 0.04, Y * 0.935, "5 mm", color="white", fontsize=9)
    pos = (r["z"] - zr[0]) / max(1, zr[1] - zr[0])
    ax.set_title(f"{s}  z {r['z']}, {pos*100:.0f}% up the center line\n({r['why']}); whole slice, level 2", fontsize=10)
    ax = ax3[1]; img, _ = norm(r["zoom"], *lohi); ax.imshow(img, cmap="gray", interpolation="lanczos")
    pa = r["ca"] / 2 - r["org1"]; pb = r["cb"] / 2 - r["org1"]
    rr = 0.25 * 1000 / um / 2
    ax.add_patch(Circle((pa[1], pa[0]), rr, fill=False, ec="red", lw=1.4))
    cyan(ax, pb, r["zoom"].shape, r["gap_mm"])
    hh = r["h0"] / 2; ax.add_patch(Rectangle((pa[1] - hh, pa[0] - hh), 2 * hh, 2 * hh, fill=False, ec="yellow", lw=1))
    px = 1000 / um / 2; Y, X = r["zoom"].shape
    ax.plot([X * 0.04, X * 0.04 + px], [Y * 0.96] * 2, color="white", lw=3)
    ax.text(X * 0.04, Y * 0.935, "1 mm", color="white", fontsize=9)
    ax.set_title(f"{2*a.zoom_mm:.0f} mm window, level 1\nred and cyan {r['gap_mm']:.2f} mm apart", fontsize=10)
    ax = ax3[2]; img, _ = norm(r["close"], *lohi); ax.imshow(img, cmap="gray", interpolation="nearest")
    pa = r["ca"] - r["org0"]; pb = r["cb"] - r["org0"]
    ax.add_patch(Circle((pa[1], pa[0]), rr * 2, fill=False, ec="red", lw=1.4))
    cyan(ax, pb, r["close"].shape, r["gap_mm"])
    px = 1000 / um; Y, X = r["close"].shape
    ax.plot([X * 0.04, X * 0.04 + px], [Y * 0.96] * 2, color="white", lw=3)
    ax.text(X * 0.04, Y * 0.935, "1 mm", color="white", fontsize=9)
    ax.set_title(f"{2*a.close_mm:.0f} mm close-up, level 0\nred circle 0.25 mm radius", fontsize=10)
    for ax, im in zip(ax3, (w[ya:yb, xa:xb], r["zoom"], r["close"])):
        ax.set_xlim(-0.5, im.shape[1] - 0.5); ax.set_ylim(im.shape[0] - 0.5, -0.5)
        ax.set_xticks([]); ax.set_yticks([])


def stack(rowfiles, out, title, sub, plt, scale=0.75):
    from PIL import Image
    ims = [Image.open(f).convert("RGB") for f in rowfiles]
    W = int(ims[0].width * scale); ims = [im.resize((W, int(im.height * scale)), Image.LANCZOS) for im in ims]
    fig = plt.figure(figsize=(W / 100, 0.8)); fig.text(0.5, 0.62, title, ha="center", fontsize=13, weight="bold")
    fig.text(0.5, 0.18, sub, ha="center", fontsize=9.5)
    hf = out + ".head.png"; fig.savefig(hf, dpi=100); plt.close(fig)
    head = Image.open(hf).convert("RGB"); head = head.resize((W, int(head.height * W / head.width)))
    sheet = Image.new("RGB", (W, head.height + sum(im.height for im in ims)), "white")
    sheet.paste(head, (0, 0)); y = head.height
    for im in ims:
        sheet.paste(im, (0, y)); y += im.height
    sheet.save(out, optimize=True); os.remove(hf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True); ap.add_argument("--b", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--scrolls", nargs="*"); ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--a-label", default="centers A")
    ap.add_argument("--b-label", default="centers B")
    ap.add_argument("--zoom-mm", type=float, default=6.0, help="half width of the level-1 zoom")
    ap.add_argument("--close-mm", type=float, default=2.0, help="half width of the level-0 close-up")
    a = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Circle

    os.makedirs(a.out, exist_ok=True)
    cache = a.cache or os.path.join(a.out, ".cache"); os.makedirs(cache, exist_ok=True)
    fa, fb = umb_files(a.a), umb_files(a.b)
    scrolls = a.scrolls or sorted(fa)
    summary = {}
    for s in scrolls:
        if s not in fa or s not in fb:
            raise SystemExit(f"{s}: no umbilicus file in {a.a if s not in fa else a.b}")
        A, meta = load_umb(fa[s])
        Bp, _ = load_umb(fb[s])
        vol = meta["source_volume"]; um = float(meta["voxelsize_um"])
        L2, L1, L0 = Level(vol, 2), Level(vol, 1), Level(vol, 0)
        tag = hashlib.sha256(str(vol).rstrip("/").encode()).hexdigest()[:12]
        picks, gap, speed = pick_slices(A, Bp, a.n)
        rows = []
        for z, why in picks:
            ca, cb = at(A, z), at(Bp, z)           # (y, x) level 0
            key = os.path.join(cache, f"{s}_{tag}_z{z}")   # per scan: two scans of one scroll never share a cache file

            def cached(name, fn):
                f = f"{key}_{name}.npy"
                if os.path.exists(f):
                    return np.load(f)
                arr = fn(); np.save(f, arr); return arr

            whole = cached("l2", lambda: L2.plane(z // 4))
            h1 = int(round(a.zoom_mm * 1000 / um / 2)); y1c, x1c = int(round(ca[0] / 2)), int(round(ca[1] / 2))
            zoom = cached(f"l1_{h1}", lambda: L1.plane(z // 2, y1c - h1, y1c + h1, x1c - h1, x1c + h1))
            h0 = int(round(a.close_mm * 1000 / um)); y0c, x0c = int(round(ca[0])), int(round(ca[1]))
            close = cached(f"l0_{h0}", lambda: L0.plane(z, y0c - h0, y0c + h0, x0c - h0, x0c + h0))
            rows.append(dict(z=z, why=why, ca=ca, cb=cb, whole=whole, zoom=zoom, close=close, h1=h1, h0=h0,
                             org1=(y1c - h1, x1c - h1), org0=(y0c - h0, x0c - h0),
                             gap_mm=float(np.hypot(*(ca - cb)) * um / 1000)))
            print(f"{s} z={z} ({why}) gap {rows[-1]['gap_mm']:.2f} mm", flush=True)

        # one figure per slice (whole, zoom, close-up), then one sheet per scroll stacking them
        zr = (A[0, 0], A[-1, 0]); rowfiles = []
        os.makedirs(os.path.join(a.out, s), exist_ok=True)
        for r in rows:
            fig, ax3 = plt.subplots(1, 3, figsize=(15, 5.6))
            draw_row(ax3, r, s, zr, um, a, plt, Rectangle, Circle)
            fig.subplots_adjust(top=0.88, bottom=0.01, left=0.005, right=0.995, wspace=0.03)
            f = os.path.join(a.out, s, f"{s}_z{r['z']:05d}.png"); fig.savefig(f, dpi=120); plt.close(fig); rowfiles.append(f)
        fn = os.path.join(a.out, f"{s}_ct_check.png")
        stack(rowfiles, fn, f"{s}: automatic scroll center on CT slices (Model output, not yet checked by a person)",
              f"red circle: {a.a_label}   cyan x: {a.b_label}   "
              f"yellow box: the next panel's window   scan {meta['volume']}", plt)
        summary[s] = dict(slices=[dict(z=r["z"], why=r["why"], gap_mm=round(r["gap_mm"], 3)) for r in rows],
                          gap_mm_median=round(float(np.median(gap) * um / 1000), 3), gap_mm_max=round(float(gap.max() * um / 1000), 3),
                          missing_chunks=L2.missing + L1.missing + L0.missing, file=fn)
        print(json.dumps({s: summary[s]}), flush=True)
    with open(os.path.join(a.out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)


if __name__ == "__main__":
    main()
