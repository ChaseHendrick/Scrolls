"""Volume-to-volume transforms, superseded data and vc-delta3d copies in the open-data catalog (Nov 2026 schema).

On 16 Nov 2026 the Vesuvius Challenge open data re-registered 14 volume pairs (revision 2: an affine plus, for 13
of them, a thin-plate-spline correction), re-derived the cross-volume coordinate sets of 233 segments as `-t2`
(the t1 sets stay for now with `properties.superseded_by`), and published a lossless vc-delta3d copy of every
masked OME-Zarr volume. `volume.properties.transforms` is deprecated and goes away after 2026-12-31.

This module is the one place kit code reads those parts of `metadata.json`:

- `volume_affines(sample, vid)`: the replacement for `volume.properties.transforms`, built from
  `sample.properties.volume_transforms` (same row shape, plus `revision`); the deprecated list is read only when
  the sample has no table.
- `chain_spec`, `load_chain`: the full transform between two volumes, step by step, each step's
  `<sample>/transforms/<from>-to-<to>-r<N>/fit/transform.json` with its spline, so points move exactly as the
  organizers' pipeline moves them (villa `foundation/volume-registration/pipeline/volreg/cores/deformable.py`,
  MIT: matrix plus a spline displacement; the inverse direction uses the fitted inverse spline).
- `current(entries)`, `is_superseded`, `replacement`: drop or follow superseded data entries.
- `vcd3d_url(volume_entry)`, `open_volume(url)`: the vc-delta3d copy of a masked volume and a zarr reader for it
  (`pip install "vc-delta3d[zarr]>=0.3.2"`, zarr >= 3.1.1).

numpy is needed only to move points; the catalog helpers are standard library.
"""

import gzip
import json
import os
import re
import urllib.request
import warnings
from pathlib import Path

BUCKET_URL = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
TRANSFORM_PATH = "{sample}/transforms/{src}-to-{dst}-r{rev}/fit/transform.json"
VCD3D_TYPE = "ome-zarr-vcd3d"
VCD3D_MIN = (0, 3, 2)
BATCH = 50_000


class TransformError(ValueError):
    pass


# ------------------------------------------------------------------ catalog: superseded entries

def _props(entry):
    return (entry or {}).get("properties") or {}


def is_superseded(entry):
    """True when a data entry (or a volume) carries `superseded_by`, in its properties or at its top level."""
    return bool(_props(entry).get("superseded_by") or (entry or {}).get("superseded_by"))


def replacement(entry):
    """The `superseded_by` record of an entry ({path, parameters, date, reason, retain_until}), or None."""
    return _props(entry).get("superseded_by") or (entry or {}).get("superseded_by") or None


def current(entries):
    """The entries that nothing supersedes, in their order."""
    return [d for d in entries or [] if not is_superseded(d)]


def transform_revision(entry):
    """The `transform_revision` a derived entry was made through (int), 1 when it names none."""
    rev = ((entry or {}).get("parameters") or {}).get("transform_revision")
    try:
        return int(rev) if rev not in (None, "") else 1
    except (TypeError, ValueError):
        return 1


def pick_current(entries, key=None):
    """The newest current entry per key (default: one overall): superseded entries are skipped, and when two
    current entries share a key the higher `transform_revision` wins. Returns {key: entry}."""
    key = key or (lambda d: None)
    out = {}
    for d in entries or []:
        if is_superseded(d):
            continue
        k = key(d)
        if k not in out or transform_revision(d) > transform_revision(out[k]):
            out[k] = d
    return out


def path_revision(path):
    """1 or 2 (or N) for a cross-volume path: `-tN` before `.tifxyz`, `.zarr` or `-<model>` marks revision N."""
    m = re.search(r"-t(\d+)(?=\.tifxyz|\.zarr|-|/|$)", str(path or ""))
    return int(m.group(1)) if m else 1


# ------------------------------------------------------------------ catalog: transforms table

def _sample_entry(cat, sample):
    samples = (cat or {}).get("samples") or {}
    if sample in samples:
        return samples[sample]
    lower = {k.lower(): k for k in samples}
    if str(sample).lower() in lower:
        return samples[lower[str(sample).lower()]]
    raise TransformError(f"no sample {sample!r} in the catalog")


def table(sample_entry):
    """[{from, to, revision, steps, matrix, derivation_path, created}] from sample.properties.volume_transforms."""
    rows = []
    for group in (((sample_entry or {}).get("sample") or {}).get("properties") or {}).get("volume_transforms") or []:
        a = group.get("from_volume_id")
        for t in group.get("transforms") or []:
            rows.append({"from": a, "to": t.get("to_volume_id"), "revision": t.get("revision"),
                         "steps": t.get("steps") or [], "matrix": t.get("matrix") or t.get("transformation_matrix"),
                         "derivation_path": t.get("derivation_path"), "created": t.get("created")})
    return rows


def volume_affines(sample_entry, vid):
    """What `volume.properties.transforms` used to hold for volume `vid`: [{to_volume_id, transformation_matrix,
    revision, from_landmarks, to_landmarks}] for every registration fitted from `vid` (a one-step, not inverted
    chain in the sample's table). Falls back to the deprecated per-volume list only when the sample has no table,
    with a DeprecationWarning. The matrix is the affine part only; a bent (spline) transform needs `load_chain`."""
    rows = table(sample_entry)
    vol = ((sample_entry or {}).get("volumes") or {}).get(vid) or {}
    legacy = _props(vol).get("transforms") or []
    if rows:
        def same(a, b):
            try:
                return a is not None and b is not None and all(
                    abs(float(x) - float(y)) <= 1e-9 * max(1.0, abs(float(x)))
                    for ra, rb in zip(a, b) for x, y in zip(ra, rb)) and len(a) >= 3 and len(b) >= 3
            except (TypeError, ValueError):
                return False

        def landmarks(to, matrix):
            # the deprecated list's landmarks, only while its matrix is the table's (the same registration)
            for t in legacy:
                if t.get("to_volume_id") == to and same(t.get("transformation_matrix") or t.get("matrix"), matrix):
                    return t.get("from_landmarks"), t.get("to_landmarks")
            return None, None
        out = []
        for r in rows:
            steps = r["steps"]
            direct = (len(steps) == 1 and not steps[0].get("inverted") and steps[0].get("from_volume_id") == vid) \
                if steps else (r["from"] == vid and r["derivation_path"] in (None, f"{r['from']}-{r['to']}"))
            if r["from"] == vid and direct:
                fl, tl = landmarks(r["to"], r["matrix"])
                out.append({"to_volume_id": r["to"], "transformation_matrix": r["matrix"],
                            "revision": r["revision"], "from_landmarks": fl, "to_landmarks": tl})
        # a registration only the deprecated list still names (none in the live catalog) is kept as it was
        have = {t["to_volume_id"] for t in out}
        out += [dict(t) for t in legacy if t.get("to_volume_id") not in have]
        return out
    if legacy:
        warnings.warn("volume.properties.transforms is deprecated (removed after 2026-12-31); this sample has no "
                      "volume_transforms table", DeprecationWarning, stacklevel=2)
    return list(legacy)


def chain_spec(cat, sample, src, dst):
    """The sample table's row from src to dst (with its steps), or a TransformError naming what exists."""
    s = _sample_entry(cat, sample)
    rows = table(s)
    for r in rows:
        if r["from"] == src and r["to"] == dst:
            if not r["steps"]:
                r = dict(r, steps=[{"from_volume_id": src, "to_volume_id": dst, "revision": r["revision"] or 1,
                                    "inverted": False}])
            return r
    have = sorted({r["to"] for r in rows if r["from"] == src})
    raise TransformError(f"{sample}: no transform from {src} to {dst}; from {src} the table reaches {have}")


def volume_transform_entries(sample_entry):
    """[{from, to, revision, bent, path, fit}] for every `volume-transform` data entry of the sample."""
    out = []
    for d in ((sample_entry or {}).get("sample") or {}).get("data") or []:
        if d.get("type") != "volume-transform":
            continue
        p = d.get("parameters") or {}
        out.append({"from": p.get("from_volume"), "to": p.get("to_volume"), "revision": p.get("revision"),
                    "bent": bool(_props(d).get("bent")), "fit": _props(d).get("fit"),
                    "path": ((d.get("origins") or [{}])[0]).get("path")})
    return out


def latest_revision(sample_entry, src, dst):
    """Highest published revision of the registration src -> dst (either direction stored), or None."""
    revs = [e["revision"] for e in volume_transform_entries(sample_entry)
            if {e["from"], e["to"]} == {src, dst} and e["revision"] is not None]
    return max(revs) if revs else None


# ------------------------------------------------------------------ moving points

def _np():
    import numpy
    return numpy


class Spline:
    """A thin-plate spline with kernel U(r) = -r on points normalised by (centre, scale), mapping a point to a
    displacement (villa volreg `Deformable.apply`)."""

    def __init__(self, record):
        np = _np()
        if record.get("model", "thin-plate-spline") != "thin-plate-spline":
            raise TransformError(f"unknown deformation model {record.get('model')!r}")
        if record.get("kernel", "-r") != "-r":
            raise TransformError(f"unknown deformation kernel {record.get('kernel')!r}")
        self.centre = np.asarray(record["centre"], float)
        self.scale = float(record["scale"])
        self.control = (np.asarray(record["control_points"], float) - self.centre) / self.scale
        self.weights = np.asarray(record["weights"], float)
        self.affine = np.asarray(record["affine"], float)
        if self.affine.shape != (4, 3) or self.weights.shape != (len(self.control), 3):
            raise TransformError("deformation arrays have the wrong shapes")

    def __call__(self, points):
        np = _np()
        pts = np.asarray(points, float).reshape(-1, 3)
        out = np.empty_like(pts)
        for i in range(0, len(pts), BATCH):
            x = (pts[i:i + BATCH] - self.centre) / self.scale
            d = np.sqrt(((x[:, None, :] - self.control[None, :, :]) ** 2).sum(-1))
            out[i:i + BATCH] = -d @ self.weights + np.hstack([np.ones((len(x), 1)), x]) @ self.affine
        return out


def invert_matrix(m):
    np = _np()
    m = np.asarray(m, float)
    lin = np.linalg.inv(m[:, :3])
    return np.hstack([lin, (-lin @ m[:, 3])[:, None]])


class Transform:
    """One registration in one direction: x -> M x + spline(x). Points are level-0 voxel XYZ."""

    def __init__(self, matrix, spline=None, inverse_spline=None, label=""):
        np = _np()
        self.matrix = np.asarray(matrix, float)
        if self.matrix.shape == (4, 4):
            self.matrix = self.matrix[:3]
        if self.matrix.shape != (3, 4):
            raise TransformError(f"matrix must be 3x4, got {self.matrix.shape}")
        self.spline, self.inverse_spline, self.label = spline, inverse_spline, label

    @property
    def bent(self):
        return self.spline is not None

    @classmethod
    def from_json(cls, record, label=""):
        d = record.get("deformation")
        return cls(record["transformation_matrix"], Spline(d) if d else None,
                   Spline(d["inverse"]) if d and d.get("inverse") else None, label)

    def apply(self, points):
        np = _np()
        pts = np.asarray(points, float).reshape(-1, 3)
        out = pts @ self.matrix[:, :3].T + self.matrix[:, 3]
        return out + self.spline(pts) if self.spline is not None else out

    def inverted(self):
        if self.spline is not None and self.inverse_spline is None:
            raise TransformError(f"{self.label or 'transform'} is bent but carries no fitted inverse")
        return Transform(invert_matrix(self.matrix), self.inverse_spline, self.spline,
                         (self.label + "^-1") if self.label else "")


class Chain:
    def __init__(self, steps):
        self.steps = list(steps)

    @property
    def bent(self):
        return any(t.bent for t in self.steps)

    def apply(self, points):
        np = _np()
        out = np.asarray(points, float).reshape(-1, 3)
        for t in self.steps:
            out = t.apply(out)
        return out


def fetch_json(url, cache_dir=None, opener=None):
    """A JSON file from the bucket (gzip-aware), cached by path under cache_dir when given."""
    cache = None
    if cache_dir:
        cache = Path(cache_dir) / re.sub(r"[^A-Za-z0-9._-]+", "__", url.split("://", 1)[-1])
        if cache.is_file():
            return json.loads(cache.read_text())
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with (opener or urllib.request.urlopen)(req, timeout=120) as resp:
        data = resp.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(cache.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, cache)
    return json.loads(data)


def transform_url(sample, src, dst, revision, bucket=BUCKET_URL):
    return f"{bucket}/{TRANSFORM_PATH.format(sample=sample, src=src, dst=dst, rev=int(revision))}"


def load_step(sample, src, dst, revision, fetch=None):
    """The registration src -> dst at `revision` (as stored, not inverted) from its transform.json."""
    fetch = fetch or fetch_json
    return Transform.from_json(fetch(transform_url(sample, src, dst, revision)), f"{src}-to-{dst}-r{revision}")


def load_chain(cat, sample, src, dst, fetch=None, revision=None):
    """The full map from volume src to volume dst, splines included, following the steps the sample's table
    names. `revision` forces every step to that revision (for comparing r1 with r2); otherwise each step uses the
    revision the table gives, which is the current one."""
    spec = chain_spec(cat, sample, src, dst)
    steps = []
    for st in spec["steps"]:
        a, b, inv = st["from_volume_id"], st["to_volume_id"], bool(st.get("inverted"))
        t = load_step(sample, a, b, revision or st.get("revision") or 1, fetch)
        steps.append(t.inverted() if inv else t)
    return Chain(steps)


def compare_revisions(cat, sample, src, dst, points, fetch=None, old=1, new=None):
    """How far `points` (src voxels) land apart under revision `old` and the current (or `new`) chain, in dst
    voxels: {"n", "median", "p90", "max"}."""
    np = _np()
    a = load_chain(cat, sample, src, dst, fetch, revision=old).apply(points)
    b = load_chain(cat, sample, src, dst, fetch, revision=new).apply(points)
    d = np.linalg.norm(a - b, axis=1)
    return {"n": int(len(d)), "median": float(np.median(d)), "p90": float(np.percentile(d, 90)),
            "max": float(d.max())}


# ------------------------------------------------------------------ vc-delta3d copies

def _version(text):
    return tuple(int(x) for x in re.findall(r"\d+", str(text))[:3])


def vcd3d_entry(volume_entry):
    """The current `ome-zarr-vcd3d` data entry of a catalog volume, or None."""
    hits = [d for d in current((volume_entry or {}).get("data")) if d.get("type") == VCD3D_TYPE]
    hits.sort(key=lambda d: _version((d.get("parameters") or {}).get("vc_delta3d_version", "0")), reverse=True)
    return hits[0] if hits else None


def vcd3d_url(volume_entry, bucket=BUCKET_URL):
    """HTTPS URL (no trailing slash) of the vc-delta3d copy of a masked volume, or None."""
    d = vcd3d_entry(volume_entry)
    if not d:
        return None
    origin = (d.get("origins") or [{}])[0]
    for root in origin.get("access_roots") or []:
        if root.get("type") == "https" and root.get("url"):
            return f"{root['url'].rstrip('/')}/{origin['path'].strip('/')}"
    return f"{bucket}/{origin['path'].strip('/')}"


def vcd3d_sibling(masked_url):
    """Best guess at the vc-delta3d copy next to a `...-masked.zarr` URL, for code that has no catalog entry."""
    u = str(masked_url).rstrip("/")
    if not u.endswith("-masked.zarr"):
        return None
    return u[:-len(".zarr")] + "-fast-q1-c64-v0.3.2.vcd3d.zarr"


def have_vcd3d():
    """True when vc_delta3d >= 0.3.2 and zarr >= 3.1.1 are importable (the codec registers itself with zarr)."""
    try:
        import vc_delta3d  # noqa: F401
        import zarr
    except ImportError:
        return False
    try:
        from importlib.metadata import version
        return _version(version("vc-delta3d")) >= VCD3D_MIN and _version(zarr.__version__) >= (3, 1, 1)
    except Exception:
        return False


def open_volume(url, level=0, prefer_vcd3d=True, volume_entry=None):
    """A zarr array for one level of a volume: the vc-delta3d copy when it exists and the codec is installed,
    else the URL given. Returns (array, url used). Voxels are identical either way (the copy is lossless)."""
    import zarr
    use = url
    if prefer_vcd3d and have_vcd3d():
        use = (vcd3d_url(volume_entry) if volume_entry else None) or vcd3d_sibling(url) or url
    try:
        group = zarr.open_group(use.rstrip("/"), mode="r")
    except Exception:
        if use == url:
            raise
        use = url
        group = zarr.open_group(use.rstrip("/"), mode="r")
    return group[str(level)], use


def load_catalog(cache_dir, max_age=86400, opener=None):
    """The open-data metadata.json, cached under cache_dir for max_age seconds."""
    import time
    cache = Path(cache_dir) / "open-data-metadata.json"
    if cache.is_file() and time.time() - cache.stat().st_mtime < max_age:
        return json.loads(cache.read_text())
    cat = fetch_json(f"{BUCKET_URL}/metadata.json", opener=opener)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".part")
    tmp.write_text(json.dumps(cat))
    os.replace(tmp, cache)
    return cat


# ------------------------------------------------------------------ command line

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m kit.voltransform", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("table", help="every transform of a sample: from, to, revision, steps, bent")
    a.add_argument("sample")
    b = sub.add_parser("map", help="move points (x y z per line on stdin) from one volume to another")
    b.add_argument("sample"), b.add_argument("src"), b.add_argument("dst")
    b.add_argument("--revision", type=int, help="force every step to this revision")
    c = sub.add_parser("superseded", help="superseded data entries of a sample's segments, with replacements")
    c.add_argument("sample")
    for p in (a, b, c):
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cache = Path(os.environ.get("KIT_VC3D_HOME", Path.home() / ".cache" / "kit-vc3d")) / "cache"
    cat = load_catalog(cache)
    s = _sample_entry(cat, args.sample)
    if args.cmd == "table":
        bent = {(e["from"], e["to"], e["revision"]): e["bent"] for e in volume_transform_entries(s)}
        rows = [dict(r, steps=[f"{x['from_volume_id']}-to-{x['to_volume_id']}-r{x['revision']}"
                               + ("^-1" if x.get("inverted") else "") for x in r["steps"]],
                     bent=any(bent.get((x["from_volume_id"], x["to_volume_id"], x["revision"])) for x in r["steps"]))
                for r in table(s)]
        for r in rows:
            r.pop("matrix", None)
        print(json.dumps(rows, indent=1) if args.json else
              "\n".join(f"{r['from']} -> {r['to']}  r{r['revision']}  {'bent' if r['bent'] else 'affine'}  "
                        f"{' . '.join(r['steps'])}" for r in rows))
    elif args.cmd == "map":
        import sys
        np = _np()
        pts = np.loadtxt(sys.stdin, ndmin=2)
        fetch = lambda u: fetch_json(u, cache / "transforms")  # noqa: E731
        out = load_chain(cat, args.sample, args.src, args.dst, fetch, args.revision).apply(pts)
        print(json.dumps(out.tolist()) if args.json else "\n".join(" ".join(f"{v:.3f}" for v in p) for p in out))
    else:
        rows = []
        for sid, seg in sorted((s.get("segments") or {}).items()):
            for d in seg.get("data") or []:
                if is_superseded(d):
                    rows.append({"segment": sid, "type": d.get("type"),
                                 "path": ((d.get("origins") or [{}])[0]).get("path"),
                                 "replacement": (replacement(d) or {}).get("path")})
        print(json.dumps(rows, indent=1) if args.json else
              "\n".join(f"{r['segment']}  {r['type']}  {r['path']}  ->  {r['replacement']}" for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
