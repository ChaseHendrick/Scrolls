"""StrokeNet dataset: 128 x 128 windows of the organizers' public PHerc. Paris 4 ink maps.

Every step starts from public files and is deterministic, so two machines that run it get the
same windows byte for byte (`manifest` prints their SHA-256).

  python scripts/strokenet/data.py all --work WORK [--jobs 2] [--keep-tif]
  python scripts/strokenet/data.py fetch|pool|label|crops --work WORK [--segments w028-037,...]
  python scripts/strokenet/data.py manifest --work WORK [--out manifest.json]

Steps, per segment:
  fetch   download the organizers' 2.4 um ink prediction (one TIFF, about 1.3 GB) into WORK/raw/,
          resumable, recording its size and SHA-256 in WORK/raw/<seg>.json
  pool    20 x 20 mean to 48 um (0.048 mm per pixel), rounded to uint8: WORK/pooled/<seg>_48.npy
  label   text, blank papyrus and dense non-periodic areas from the pooled map: WORK/labels/<seg>.npz
          (0 unusable, 1 blank, 2 text, 3 ambiguous, 4 dense but not line-periodic)
  crops   128 x 128 windows (6.1 mm) of each class: WORK/crops/<seg>.npz (uint8 plus positions)

Labels come from the ink map itself (line periodicity and ink density), not from people, so a
text-against-blank score partly measures agreement with this rule; docs/strokenet.md says what
that does and does not show. Nothing here is a reading.

Source: https://data.aws.ash2txt.org/samples/PHercParis4/segments/ (organizer ink predictions of
the July 2026 tracings on volume 20260411134726, model new_canon_autoresearch_recipe).
The innermost tracing, w010-027, is not used at all.
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

BASE = "https://data.aws.ash2txt.org/samples/PHercParis4/segments"
TIF = ("PHercParis4-{stamp}-2.4um-0.22m-78keV-volume-20260411134726-20260417190342-"
       "new_canon_autoresearch_recipe-tile256-stride128.tif")
SOURCE_UM = 2.4
POOL = 20                      # 2.4 um x 20 = 48 um
PX = 0.048                     # mm per pooled pixel
CROP = 128                     # 6.1 mm windows

# The July 2026 tracings, outermost last, with their upload stamps. The fixed split rule (written
# 7 October 2026, before any model was trained) runs over the 28-segment order that starts with
# the innermost tracing w010-027: index i % 4 == 0 -> test, i % 4 == 2 -> validation, odd -> train.
# w010-027 (index 0, test) is then left out of every split.
ORDER = [("w010-027", "20260701183124"), ("w028-037", "20260701183125"), ("w038-045", "20260701183126"),
         ("w046-052", "20260701183127"), ("w053-058", "20260701183128"), ("w059-063", "20260701183129"),
         ("w064-068", "20260701183130"), ("w069-072", "20260701183131"), ("w073-076", "20260701183132"),
         ("w077-080", "20260701183133"), ("w081-084", "20260701183134"), ("w085-088", "20260701183135"),
         ("w089-091", "20260701183136"), ("w092-094", "20260701183137"), ("w095-097", "20260701183138"),
         ("w098-100", "20260701183139"), ("w101-103", "20260701183140"), ("w104-106", "20260701183141"),
         ("w107-109", "20260701183142"), ("w110-112", "20260701183143"), ("w113-115", "20260701183144"),
         ("w116-117", "20260701183145"), ("w118-119", "20260701183146"), ("w120-121", "20260701183147"),
         ("w122-123", "20260701183148"), ("w124-125", "20260701183149"), ("w126-127", "20260701183150"),
         ("w128-129", "20260701183151")]
EXCLUDED = {"w010-027"}
STAMP = dict(ORDER)


def split_of(index):
    return "test" if index % 4 == 0 else "validation" if index % 4 == 2 else "train"


def splits():
    """{"train": [...], "validation": [...], "test": [...]} without the excluded segments."""
    out = {"train": [], "validation": [], "test": []}
    for i, (seg, _) in enumerate(ORDER):
        if seg not in EXCLUDED:
            out[split_of(i)].append(seg)
    return out


def segment_split(seg):
    for k, v in splits().items():
        if seg in v:
            return k
    raise KeyError(f"{seg} is not in any split")


def url(seg):
    stamp = STAMP[seg]
    return f"{BASE}/{stamp}-{seg}/ink-detection/{TIF.format(stamp=stamp)}"


# ------------------------------------------------------------------ fetch
def _remote_length(u):
    """The server's length of a file (HEAD request), or None."""
    try:
        with urllib.request.urlopen(urllib.request.Request(u, method="HEAD"), timeout=60) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n is not None else None
    except OSError:
        return None


def fetch(work, seg, retries=6):
    """Download one TIFF (resumable, checked against the server's length); record its size and
    SHA-256. Returns the record."""
    import urllib.error
    raw = Path(work) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    dest, rec_path = raw / f"{seg}.tif", raw / f"{seg}.json"
    if rec_path.exists() and dest.exists() and json.loads(rec_path.read_text())["bytes"] == dest.stat().st_size:
        return json.loads(rec_path.read_text())
    part = raw / f"{seg}.tif.part"
    total = None
    for attempt in range(retries + 1):
        have = part.stat().st_size if part.exists() else 0
        if total is not None and have == total:
            break
        try:
            req = urllib.request.Request(url(seg), headers={"Range": f"bytes={have}-"} if have else {})
            with urllib.request.urlopen(req, timeout=120) as r:
                if have and r.status != 206:          # the server ignored the range: start again
                    have = 0
                    part.unlink(missing_ok=True)
                cr, cl = r.headers.get("Content-Range"), r.headers.get("Content-Length")
                if cr and "/" in cr and not cr.endswith("/*"):
                    total = int(cr.rsplit("/", 1)[1])
                elif cl is not None:
                    total = int(cl) + have
                else:                                 # no length given: ask for it separately
                    total = _remote_length(url(seg))
                with open(part, "ab") as f:
                    while True:
                        b = r.read(1 << 22)
                        if not b:
                            break
                        f.write(b)
        except urllib.error.HTTPError as e:
            if e.code == 416:                         # nothing left to send: the part may be complete
                cr = e.headers.get("Content-Range") if e.headers else None
                total = int(cr.rsplit("/", 1)[1]) if cr and "/" in cr else _remote_length(url(seg))
                if total is not None and have > total:
                    part.unlink(missing_ok=True)      # longer than the file: start again
            else:
                print(f"{seg}: download error {e}; retrying", flush=True)
        except OSError as e:                          # network errors: back off and resume
            print(f"{seg}: download error {e}; retrying", flush=True)
        have = part.stat().st_size if part.exists() else 0
        if total is not None and have == total:
            break
        if attempt == retries:
            raise OSError(f"{seg}: download incomplete ({have} of {total} bytes)")
        print(f"{seg}: have {have} of {total} bytes; resuming", flush=True)
        time.sleep(2 ** min(attempt + 1, 5))
    h = hashlib.sha256()
    with open(part, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    part.rename(dest)
    rec = {"segment": seg, "url": url(seg), "bytes": dest.stat().st_size, "sha256": h.hexdigest()}
    rec_path.write_text(json.dumps(rec, indent=1) + "\n")
    return rec


# ------------------------------------------------------------------ pool
def pool_array(z, strip=5120):
    """20 x 20 mean pool of a 2D uint8 array-like (numpy or zarr), rounded half to even, as uint8.
    Rows and columns past the last whole block are dropped."""
    H, W = z.shape
    H20, W20 = (H // POOL) * POOL, (W // POOL) * POOL
    out = np.zeros((H20 // POOL, W20 // POOL), np.uint8)
    assert strip % POOL == 0
    for y in range(0, H20, strip):
        y1 = min(H20, y + strip)
        blk = np.asarray(z[y:y1, :W20])
        s = blk.reshape((y1 - y) // POOL, POOL, W20 // POOL, POOL).sum(axis=(1, 3), dtype=np.uint32)
        out[y // POOL:y1 // POOL] = np.round(s / float(POOL * POOL)).astype(np.uint8)
    return out


def pool(work, seg):
    import tifffile
    import zarr
    src = Path(work) / "raw" / f"{seg}.tif"
    dst = Path(work) / "pooled" / f"{seg}_48.npy"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tifffile.TiffFile(str(src)) as t:
        z = zarr.open(t.aszarr(), mode="r")
        if not hasattr(z, "shape"):
            z = z[sorted(z.keys())[0]]
        shape = z.shape
        a = pool_array(z)
    tmp = dst.with_suffix(".part.npy")
    np.save(tmp, a)
    tmp.rename(dst)
    return {"segment": seg, "source_shape": list(shape), "pooled_shape": list(a.shape)}


# ------------------------------------------------------------------ label
def acf_map(ink, win_y_mm=26.0, win_x_mm=8.0, step_mm=2.0):
    """Line periodicity on a coarse grid: row-profile autocorrelation peak at 4.5 to 9 mm lag minus
    its mean at 2 to 3.5 mm (half a line pitch), in windows 26 mm tall and 8 mm wide."""
    H, W = ink.shape
    wy, wx, st = int(win_y_mm / PX), int(win_x_mm / PX), int(step_mm / PX)
    ys = list(range(0, max(1, H - wy), st))
    xs = list(range(0, max(1, W - wx), st))
    out = np.zeros((len(ys), len(xs)), np.float32)
    lo, hi = int(4.5 / PX), int(9.0 / PX)
    hlo, hhi = int(2.0 / PX), int(3.5 / PX)
    cs = np.cumsum(np.pad(ink, ((0, 0), (1, 0))), axis=1)
    for j, x in enumerate(xs):
        prof_all = (cs[:, x + wx] - cs[:, x]) / wx
        for i, y in enumerate(ys):
            p = prof_all[y:y + wy]
            p = p - p.mean()
            v = (p * p).sum()
            if v < 1e-9:
                continue
            f = np.fft.rfft(p, 2 * len(p))
            ac = np.fft.irfft(f * np.conj(f))[:len(p)] / v
            out[i, j] = ac[lo:hi].max() - ac[hlo:hhi].mean()
    return out, ys, xs, wy, wx


def label_map(a):
    """Label a pooled 48 um map (uint8). Returns (labels uint8, summary dict).

    Text: line periodicity above 0.20 and ink density above 0.06, closed and opened, in blocks of
    at least 150 mm2. Blank: usable papyrus at least 3 mm from text with periodicity below 0.12 and
    ink density below 0.15. Dense: the same but with density at least 0.15 (kept out of training
    and of the text-against-blank test). Usable: map value above 3, opened, holes filled, at least
    1.5 mm from its edge."""
    from scipy import ndimage as ndi
    a = np.asarray(a, np.float32)
    usable = ndi.binary_fill_holes(ndi.binary_opening(a > 3, iterations=3))
    core = ndi.distance_transform_edt(usable) > 1.5 / PX
    v = a[core]
    bg = float(np.median(v)) if v.size else 0.0
    mad = float(np.median(np.abs(v - bg))) * 1.4826 + 1e-6 if v.size else 1.0
    ink = np.clip((a - bg) / mad, 0, 20) * core
    dens = ndi.gaussian_filter((ink > 3).astype(np.float32), 1.5 / PX)
    acm, ys, xs, wy, wx = acf_map(ink)
    per = np.zeros_like(a)
    cnt = np.zeros_like(a)
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            cy, cx = y + wy // 2, x + wx // 2
            per[cy - 21:cy + 21, cx - 21:cx + 21] += acm[i, j]
            cnt[cy - 21:cy + 21, cx - 21:cx + 21] += 1
    per = np.where(cnt > 0, per / np.maximum(cnt, 1), 0)
    per = ndi.gaussian_filter(per, 2.0 / PX)
    text = core & (per > 0.20) & (dens > 0.06)
    sz = (int(4 / PX), int(6 / PX))
    text = ndi.minimum_filter(ndi.maximum_filter(text.astype(np.uint8), size=sz), size=sz) > 0
    sz = (int(3 / PX), int(3 / PX))
    text = ndi.maximum_filter(ndi.minimum_filter(text.astype(np.uint8), size=sz), size=sz) > 0
    lab, n = ndi.label(text)
    sizes = ndi.sum(text, lab, np.arange(1, n + 1)) * PX * PX
    text = np.isin(lab, 1 + np.nonzero(sizes >= 150.0)[0]) & core
    near = (ndi.distance_transform_edt(~text) < 3 / PX) if text.any() else np.zeros_like(text)
    far = core & ~near & (per < 0.12)
    blank = far & (dens < 0.15)
    dense = far & (dens >= 0.15)
    out = np.zeros(a.shape, np.uint8)
    out[core] = 3
    out[blank] = 1
    out[text] = 2
    out[dense] = 4
    summ = {"shape_48um": list(a.shape), "usable_mm2": round(float(core.sum() * PX * PX)),
            "text_mm2": round(float(text.sum() * PX * PX)), "blank_mm2": round(float(blank.sum() * PX * PX)),
            "dense_nonperiodic_mm2": round(float(dense.sum() * PX * PX)), "bg": round(bg, 2), "mad": round(mad, 2)}
    return out, summ


def label(work, seg):
    a = np.load(Path(work) / "pooled" / f"{seg}_48.npy")
    lab, summ = label_map(a)
    d = Path(work) / "labels"
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / f"{seg}.npz", label=lab)
    summ["segment"] = seg
    (d / f"{seg}.json").write_text(json.dumps(summ, indent=1) + "\n")
    return summ


# ------------------------------------------------------------------ crops
# Window strides in pooled pixels: training windows overlap; held-out text windows do not.
STRIDE = {"train": {"text": 64, "blank": 32, "dense": 64},
          "validation": {"text": 128, "blank": 64, "dense": 128},
          "test": {"text": 128, "blank": 64, "dense": 128}}


def crops_from(a, lab, split):
    """Windows whose pixels are at least 99 % usable and at least 90 % of the class; blank and dense
    windows hold no text pixel. Returns {kind: uint8 (N, 128, 128), kind_pos: int (N, 2)}."""
    ii = lambda m: np.pad(m.astype(np.float64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    I = {k: ii(lab == v) for k, v in (("text", 2), ("blank", 1), ("dense", 4))}
    Iu = ii(lab > 0)
    box = lambda S, y, x: (S[y + CROP, x + CROP] - S[y, x + CROP] - S[y + CROP, x] + S[y, x]) / (CROP * CROP)
    H, W = lab.shape
    out = {}
    for kind in ("text", "blank", "dense"):
        st = STRIDE[split][kind]
        crops, pos = [], []
        for y in range(0, H - CROP, st):
            for x in range(0, W - CROP, st):
                if box(Iu, y, x) < 0.99 or box(I[kind], y, x) < 0.9:
                    continue
                if kind != "text" and box(I["text"], y, x) > 0:
                    continue
                crops.append(a[y:y + CROP, x:x + CROP])
                pos.append((y, x))
        out[kind] = np.array(crops, np.uint8).reshape(-1, CROP, CROP)
        out[kind + "_pos"] = np.array(pos, np.int64).reshape(-1, 2)
    return out


def crops(work, seg):
    a = np.load(Path(work) / "pooled" / f"{seg}_48.npy")
    lab = np.load(Path(work) / "labels" / f"{seg}.npz")["label"]
    split = segment_split(seg)
    out = crops_from(a, lab, split)
    d = Path(work) / "crops"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{seg}.part.npz"
    np.savez(tmp, **out)                    # uncompressed: byte-identical across machines
    tmp.rename(d / f"{seg}.npz")
    return {"segment": seg, "split": split, **{k: int(len(v)) for k, v in out.items() if not k.endswith("_pos")}}


def load_split(work, segs, kinds=("text", "blank"), with_segments=False, with_positions=False):
    """Concatenate the windows of the given segments. with_segments adds "<kind>_seg", each window's
    segment index into segs; with_positions adds "<kind>_pos", its (y, x) in the pooled map."""
    out = {k: [] for k in kinds}
    sid = {k: [] for k in kinds}
    pos = {k: [] for k in kinds}
    for i, s in enumerate(segs):
        f = Path(work) / "crops" / f"{s}.npz"
        if not f.exists():
            raise FileNotFoundError(f"{f}: run data.py crops first")
        z = np.load(f)
        for k in kinds:
            out[k].append(z[k])
            sid[k].append(np.full(len(z[k]), i, np.int64))
            pos[k].append(z[k + "_pos"])
    res = {k: (np.concatenate(v) if v else np.zeros((0, CROP, CROP), np.uint8)) for k, v in out.items()}
    if with_segments:
        res.update({k + "_seg": (np.concatenate(v) if v else np.zeros(0, np.int64)) for k, v in sid.items()})
    if with_positions:
        res.update({k + "_pos": (np.concatenate(v) if v else np.zeros((0, 2), np.int64)) for k, v in pos.items()})
    return res


def load_maps(work, segs):
    """The pooled 48 um maps of the given segments, in the order of segs (for seam-matched windows)."""
    return [np.load(Path(work) / "pooled" / f"{s}_48.npy") for s in segs]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def manifest(work):
    """SHA-256 of every source TIFF, pooled map, label map and window file, with window counts."""
    w = Path(work)
    out = {"source": BASE, "excluded": sorted(EXCLUDED), "splits": splits(), "segments": {}}
    for seg, _ in ORDER:
        if seg in EXCLUDED:
            continue
        r = {"split": segment_split(seg)}
        rec = w / "raw" / f"{seg}.json"
        if rec.exists():
            j = json.loads(rec.read_text())
            r["tif_bytes"], r["tif_sha256"] = j["bytes"], j["sha256"]
        for key, p in (("pooled_sha256", w / "pooled" / f"{seg}_48.npy"), ("labels_sha256", w / "labels" / f"{seg}.npz"),
                       ("crops_sha256", w / "crops" / f"{seg}.npz")):
            if p.exists():
                r[key] = sha256_file(p)
        if (w / "crops" / f"{seg}.npz").exists():
            z = np.load(w / "crops" / f"{seg}.npz")
            r["windows"] = {k: int(len(z[k])) for k in ("text", "blank", "dense")}
        out["segments"][seg] = r
    return out


# ------------------------------------------------------------------ driver
def one(work, seg, steps, keep_tif, force=False):
    t0 = time.time()
    w = Path(work)
    info = {"segment": seg}
    try:
        if "fetch" in steps and (force or not (w / "pooled" / f"{seg}_48.npy").exists()):
            info["fetch"] = fetch(work, seg)
        if "pool" in steps and (force or not (w / "pooled" / f"{seg}_48.npy").exists()):
            info["pool"] = pool(work, seg)
        if not keep_tif and (w / "pooled" / f"{seg}_48.npy").exists():
            tif = w / "raw" / f"{seg}.tif"
            if tif.exists():
                tif.unlink()
        if "label" in steps and (force or not (w / "labels" / f"{seg}.npz").exists()):
            info["label"] = label(work, seg)
        if "crops" in steps and (force or not (w / "crops" / f"{seg}.npz").exists()):
            info["crops"] = crops(work, seg)
    except Exception as e:                            # report and go on with the other segments
        info["error"] = f"{type(e).__name__}: {e}"
    info["wall_s"] = round(time.time() - t0, 1)
    print(json.dumps(info), flush=True)
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["fetch", "pool", "label", "crops", "all", "manifest", "splits"])
    ap.add_argument("--work", default="work/strokenet")
    ap.add_argument("--segments", default=None, help="comma-separated short names (default: all 27)")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--keep-tif", action="store_true", help="keep the 1.3 GB source TIFFs after pooling")
    ap.add_argument("--force", action="store_true", help="redo steps whose outputs exist")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.step == "splits":
        print(json.dumps(splits(), indent=1))
        return
    if a.step == "manifest":
        m = json.dumps(manifest(a.work), indent=1) + "\n"
        if a.out:
            Path(a.out).write_text(m)
        else:
            sys.stdout.write(m)
        return
    segs = a.segments.split(",") if a.segments else [s for s, _ in ORDER if s not in EXCLUDED]
    bad = [s for s in segs if s not in STAMP or s in EXCLUDED]
    if bad:
        raise SystemExit(f"unknown or excluded segments: {bad}")
    steps = ("fetch", "pool", "label", "crops") if a.step == "all" else (a.step,)
    keep = a.keep_tif or a.step == "fetch"
    if a.jobs > 1:
        with ProcessPoolExecutor(a.jobs) as ex:
            res = list(ex.map(one, [a.work] * len(segs), segs, [steps] * len(segs), [keep] * len(segs),
                              [a.force] * len(segs)))
    else:
        res = [one(a.work, s, steps, keep, a.force) for s in segs]
    bad = [r["segment"] for r in res if "error" in r]
    if bad:
        raise SystemExit(f"failed: {', '.join(bad)}")


if __name__ == "__main__":
    main()
