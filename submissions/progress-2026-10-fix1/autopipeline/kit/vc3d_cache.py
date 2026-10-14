"""VC3D's remote chunk cache: where it is, and whether the chunks it holds as empty are really missing.

VC3D keeps what it streams from a remote volume in a persistent cache, and a chunk the server answered with 404 as
an empty marker that stands for good: later renders and traces read that chunk as zeros and never ask again. S3
sometimes answers 404 for chunks that exist (kit/s3retry.py). Measured 2026-10-08: a 256 x 256 crop render of
the 2.4 um PHerc0139 scan with an empty cache left markers for 4 chunks the bucket holds, so the render had
holes and VC3D reported nothing. The kit therefore checks the markers around every remote run: before it, the
ones earlier runs left (each true one is remembered, so it is asked once); after it, the new ones. A false
marker is deleted, so the next read fetches the chunk, and a render that read one is run again.

Where (villa e0bbb8b: core/src/RemoteCacheSettings.cpp, core/src/Volume.cpp, core/src/render/ChunkCache.cpp):
the root is remote_cache_dir in the [viewer] section of VC3D.ini (in $VC3D_CONFIG_DIR, else ~/.VC3D), else
/volpkgs/remote_cache or /ephemeral/remote_cache when /volpkgs or /ephemeral exists, else ~/.VC3D/remote_cache.
A volume's folder is <last part of the URL>-<FNV-1a 64 of the URL without trailing slashes, 16 hex digits>.
Markers are level_<L>/<iz>/<iy>/<ix>.empty (chunk indices of pyramid level L), <zarr key>.empty (the mirror
layout) and .vc_cache_empty/<zarr key>.empty (the delta3d layout). Standard library.
"""

import contextlib
import json
import os
import re
import time
from pathlib import Path

from . import s3retry, vc3d_audit

LEDGER_KEEP = 2000           # deletions remembered per volume
DEFAULT_BUDGET = 4000        # requests per check
_LEGACY = re.compile(r"^level_(\d+)/(\d+)/(\d+)/(\d+)\.empty$")


class CacheError(ValueError):
    pass


def fnv1a64(text):
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def ini_value(path, section, key):
    """A value from a Qt-style INI file, or None."""
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return None
    current = None
    for line in lines:
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("[") and s.endswith("]"):
            current = s[1:-1]
            continue
        if current == section and "=" in s:
            k, _, v = s.partition("=")
            if k.strip() == key:
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] == '"':
                    v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
                return v
    return None


def cache_root(env=None, is_dir=os.path.isdir):
    """VC3D's remote cache root, found the way VC3D finds it."""
    env = os.environ if env is None else env
    home = Path(env.get("HOME") or Path.home())
    conf = Path(env["VC3D_CONFIG_DIR"]) if env.get("VC3D_CONFIG_DIR") else home / ".VC3D"
    configured = ini_value(conf / "VC3D.ini", "viewer", "remote_cache_dir")
    if configured:
        return Path(configured).expanduser()
    for root in ("/volpkgs", "/ephemeral"):
        if is_dir(root):
            return Path(root) / "remote_cache"
    return home / ".VC3D" / "remote_cache"


def volume_dir(url, env=None, root=None):
    """The cache folder VC3D uses for a remote volume URL (as given to VC3D: s3:// and https:// differ)."""
    norm = str(url).rstrip("/")
    name = norm.rsplit("/", 1)[-1] if "/" in norm else (norm or "remote")
    return Path(root or cache_root(env)) / f"{name}-{fnv1a64(norm):016x}"


def markers(vdir):
    """Relative paths (with /) of every empty-chunk marker under a volume's cache folder."""
    vdir = Path(vdir)
    out = []
    if not vdir.is_dir():
        return out
    for dirpath, _dirs, files in os.walk(vdir):
        for f in files:
            if f.endswith(".empty"):
                out.append(Path(dirpath, f).relative_to(vdir).as_posix())
    return sorted(out)


def parse_marker(rel):
    """("chunk", level, (iz, iy, ix)) for a legacy marker, ("key", None, zarr key) for a mirror or delta3d one."""
    m = _LEGACY.match(rel)
    if m:
        return "chunk", int(m.group(1)), tuple(int(v) for v in m.groups()[1:])
    key = rel[len(".vc_cache_empty/"):] if rel.startswith(".vc_cache_empty/") else rel
    return "key", None, key[:-len(".empty")]


def classify(store, rels, budget=DEFAULT_BUDGET, progress=None):
    """{rel: (present | missing | unknown, zarr key or note)} for markers of one volume, checked against `store`
    (a vc3d_audit store: HttpStore for a URL). Markers of one chunk are checked once."""
    lv, _ = vc3d_audit.levels(store)
    groups, out = {}, {}
    for rel in rels:
        kind, level, what = parse_marker(rel)
        if kind == "chunk":
            meta = lv[level]["meta"] if level < len(lv) else None
            if meta is None:
                out[rel] = (s3retry.UNKNOWN, f"level {level}: not in this volume's pyramid")
                continue
            check = ("key", vc3d_audit.chunk_key(meta, what)) if meta["inner"] is None else ("inner", level, what)
        else:
            check = ("key", what)
        groups.setdefault(check, []).append(rel)
    keys = [c[1] for c in groups if c[0] == "key"]
    states = store.states(keys, budget, progress) if keys else {}
    left = max(0, budget - len(keys))
    for level in sorted({c[1] for c in groups if c[0] == "inner"}):
        meta = lv[level]["meta"]
        core = {c[2] for c in groups if c[0] == "inner" and c[1] == level}
        st, used = vc3d_audit.presence(store, meta, core, set(), left, progress)
        left = max(0, left - used)
        states.update({("inner", level, i): v for i, v in st.items()})
    for check, members in groups.items():
        state = states.get(check[1] if check[0] == "key" else check, s3retry.UNKNOWN)
        label = check[1] if check[0] == "key" else f"level {check[1]} inner chunk {list(check[2])}"
        for rel in members:
            out[rel] = (state, label)
    return out


class Ledger:
    """What the kit knows about one volume's markers: the true ones (asked once) and the deletions, with times,
    so a run can learn that a marker it may have read was false even when another process deleted it."""

    def __init__(self, path):
        self.path = Path(path)

    @contextlib.contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "a") as lock:
            try:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            data = self.read()
            yield data
            data["deleted"] = data["deleted"][-LEDGER_KEEP:]
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, indent=1))
            os.replace(tmp, self.path)

    def read(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        return {"url": data.get("url"), "cache_url": data.get("cache_url") or data.get("url"),
                "genuine": data.get("genuine") or {}, "deleted": data.get("deleted") or []}


def check(url, env=None, ledger_dir=None, store=None, delete=True, recheck=False, budget=DEFAULT_BUDGET,
          progress=None, root=None, cache_url=None, **store_kw):
    """Check every empty-chunk marker in a remote volume's VC3D cache that the kit has not already found true;
    delete the false ones (delete=False only reports them). url is where the chunks are checked; cache_url is
    the URL VC3D was given, which names the cache folder (the relay's URL, kit/s3relay.py), default url.
    Returns a JSON-ready report."""
    vdir = volume_dir(cache_url or url, env, root)
    ledger = Ledger(Path(ledger_dir) / f"{vdir.name}.json") if ledger_dir else None
    rels = markers(vdir)
    known = (ledger.read()["genuine"] if ledger else {}) if not recheck else {}
    todo = [r for r in rels if r not in known]
    report = {"volume": str(url), "cache": str(vdir), "markers": len(rels), "known_true": len(rels) - len(todo),
              "checked": 0, "false": [], "true": 0, "unknown": [], "deleted": 0}
    if not todo:
        return report
    store = store or vc3d_audit.HttpStore(str(url), **store_kw)
    try:
        result = classify(store, todo, budget, progress)
    except vc3d_audit.AuditError as exc:
        report["error"] = str(exc)
        report["unknown"] = todo
        return report
    now = time.time()
    false = [r for r in todo if result[r][0] == s3retry.PRESENT]
    true = [r for r in todo if result[r][0] == s3retry.MISSING]
    report.update(checked=len(todo), false=false, true=len(true),
                  unknown=[r for r in todo if result[r][0] == s3retry.UNKNOWN],
                  keys={r: result[r][1] for r in false[:20]})
    if getattr(store, "false_404s", 0):
        report["false_404s"] = store.false_404s
    if getattr(store, "requests", 0):
        report["requests"] = store.requests
    if delete:
        for rel in false:
            with contextlib.suppress(FileNotFoundError):
                (vdir / rel).unlink()
                report["deleted"] += 1
    if ledger:
        with ledger.locked() as data:
            data["url"] = str(url)
            data["cache_url"] = str(cache_url or url)
            for rel in true:
                data["genuine"][rel] = round(now, 3)
            if delete:
                data["deleted"] += [{"marker": rel, "at": round(now, 3)} for rel in false]
            for rel in false:   # a marker that was true once and is false now: drop the old answer
                data["genuine"].pop(rel, None)
    return report


class Guard:
    """Markers around one VC3D run on a remote volume: before() repairs what earlier runs left; after() repairs
    what this run left and lists the false markers deleted since before() (by this guard or another process),
    which are chunks the run may have read as zeros."""

    def __init__(self, url, env=None, ledger_dir=None, store_factory=None, budget=DEFAULT_BUDGET, progress=None,
                 root=None, cache_url=None):
        self.url, self.env, self.ledger_dir, self.budget, self.progress = url, env, ledger_dir, budget, progress
        self.cache_url = cache_url or url
        self.store_factory = store_factory or (lambda: None)
        self.root = root
        self.started = None
        self.reports = []

    def _check(self):
        """check(), never raising: a check that fails is reported, and the run it guards goes on."""
        try:
            rep = check(self.url, self.env, self.ledger_dir, self.store_factory(), budget=self.budget,
                        progress=self.progress, root=self.root, cache_url=self.cache_url)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            rep = {"volume": str(self.url), "markers": None, "checked": 0, "false": [], "true": 0, "unknown": [],
                   "deleted": 0, "error": f"{type(exc).__name__}: {exc}"}
        self.reports.append(rep)
        return rep

    def before(self):
        rep = self._check()
        self.started = time.time()
        return rep

    def after(self):
        rep = self._check()
        since = self.started or 0.0
        affected = set(rep["false"])
        if self.ledger_dir:
            vdir = volume_dir(self.cache_url, self.env, self.root)
            data = Ledger(Path(self.ledger_dir) / f"{vdir.name}.json").read()
            affected |= {d["marker"] for d in data["deleted"] if d.get("at", 0) >= since}
        rep["affected"] = sorted(affected)
        self.started = time.time()
        return rep

    def summary(self):
        """One JSON-ready line of what the checks around this run found."""
        out = {"cache": str(volume_dir(self.cache_url, self.env, self.root)),
               "checked": sum(r["checked"] for r in self.reports),
               "false_deleted": sum(r["deleted"] for r in self.reports),
               "unknown": sorted({u for r in self.reports for u in r["unknown"]})[:20]}
        errors = [r["error"] for r in self.reports if r.get("error")]
        if errors:
            out["error"] = errors[-1]
        return out
