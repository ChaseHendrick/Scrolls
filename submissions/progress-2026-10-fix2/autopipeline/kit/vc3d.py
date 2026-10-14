"""Headless VC3D: find the volume-cartographer tools, run them with no display, and self-test a build.

VC3D's command line tools (`vc_render_tifxyz`, `vc_grow_seg_from_seed` and the other `vc_*`) never
open a window, so they run on a server, in a container or on Modal as they are. The VC3D app itself
also runs with no display under Qt's offscreen platform; with `--agent-bridge` it is driven over
JSON-RPC (villa's `tools/vc3d-mcp`). See docs/vc3d-headless.md.

  python -m kit vc3d which                 # where the tools are and how they will be started
  python -m kit vc3d env [--threads N]     # shell exports for a headless run
  python -m kit vc3d run TOOL [ARGS ...]   # run one tool with the headless environment
  python -m kit vc3d selftest [--work DIR] [--json]
  python -m kit vc3d mcp                   # MCP server (stdio) with the agent tools, kit/vc3d_mcp.py
  python -m kit vc3d tools [--json]        # the agent tools: trace, render, check_surface, ink, ...
  python -m kit vc3d call TOOL '{"k": v}'  # one agent tool from a shell, JSON in and out
  python -m kit vc3d app-mcp [ARGS ...]    # villa's own MCP server for the VC3D app, offscreen

Tools are looked up in this order: `VC_ROOTFS` (a container root filesystem unpacked without
docker, started through its own loader), `VC_BIN`, `VC_APPIMAGE`, `PATH`, then the macOS app bundle.
`VC_APPIMAGE` is villa's release AppImage or the squashfs-root folder it extracts to: its tools need the
AppImage's own loader, so they start through AppRun, by links named after each tool that kit makes in the
kit home (work/vc3d/appimage/; KIT_HOME, kit/kithome.py). A `VC_BIN` or `PATH` entry that points at an
extracted AppImage's usr/bin, where the tools crash when started directly, gets the same links.

`which` checks the five tools AutoPipeline runs (PIPELINE_TOOLS) and names the stage that needs a missing
one; villa's `latest` release AppImage has all five.

`selftest` builds a tiny synthetic volume, renders a flat surface through it and checks the sampled
values, so a wrong build fails instead of producing plausible layers. It reports whether the binary
knows `--flip-normals` (the published container image does not) and which way its layers run. With
the tracer present it checks the tracer's normal-grid reader: a grow with synthetic normal grids for a
sheet tilted out of the seed quad's plane must stay on that sheet, and the same grow with grids for the
mirror sheet, the control, must miss it. With its default loss weights the tracer reads nothing from
the volume, so the check says nothing about how it uses a surface prediction. Standard library only.
"""

import json
import math
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from . import vc3d_io

MAC_BIN = Path("/Applications/VC3D.app/Contents/MacOS")
PROBE = "vc_render_tifxyz"
TRACER = "vc_grow_seg_from_seed"
RELEASE = "https://github.com/ScrollPrize/villa/releases/tag/latest"
# The VC3D tools AutoPipeline runs (kit/autopipe.py), the stage that runs each, and what for. villa's `stable`
# AppImage (fc25b4d, July 2026) lacks vc_tifxyz_selfcross and vc_gen_umbilicus; the `latest` one (4eecd08,
# 2026-10-12) has all five.
PIPELINE_TOOLS = (
    ("vc_gen_umbilicus", "umbilicus", "estimates the scroll axis from the normal grids when the catalog has none"),
    (TRACER, "trace", "grows a surface from each seed"),
    ("vc_tifxyz_selfcross", "qa", "counts a surface's self-intersections"),
    ("vc_flatten", "flatten", "flattens an accepted surface"),
    (PROBE, "render", "renders the surface volume"),
)

# Synthetic fixture: a 64-voxel cube whose value rises 3 per z slice, and a flat 8 x 8 surface at
# z = 32 with x along columns and y along rows, 4 voxels apart. By villa's definition the surface
# normal is d(point)/d(column) x d(point)/d(row), which here is +z.
RAMP_SIZE, RAMP_BASE, RAMP_STEP = 64, 20, 3
PLANE_Z, PLANE_N, PLANE_STEP, PLANE_X0 = 32, 8, 4.0, 16.0
SLICES = 5
# Tracer fixture: normal grids for one sheet through the seed (64, 64, 64), the plane z = 64 + 0.6 (x - 64) +
# 0.3 (y - 64), and a 128-voxel cube holding that sheet (the voxels within 2 of the plane). villa seeds every patch as
# a quad in the plane z = seed z (GrowPatch.cpp at e0bbb8b), so the sheet is tilted out of it: a grow with the sheet's
# grids must stay within TRACE_TOL voxels of it, and the same grow with grids for the mirror sheet (tilt negated,
# the control) must not. With its default loss weights (GrowPatch.cpp 1290 to 1302) no loss of the tracer reads the
# volume, with grids or without: on 9 October an all-zero cube gave the same PASS. So the cube only gives the tracer
# a volume of the right shape, and this check covers the normal-grid reader, not the tracer's use of a surface
# prediction. A grow without grids is run and reported, not scored.
SHEET_SIZE, SHEET_SEED, SHEET_HALF = 128, 64, 2
SHEET_TILT = (0.6, 0.3)           # dz/dx, dz/dy
GRID_MAGIC, GRID_VERSION, GRID_CELL, GRID_EVERY = 0x56434753, 3, 64, 8
TRACE_STEP, TRACE_GENERATIONS = 20, 3
# Pass rule for a grown surface: at least 9 valid vertices, one at least 25 voxels from the seed (a patch that
# grew past its seed quad), and at least 90 percent of them within 2 voxels of the sheet.
TRACE_MIN_VERTICES, TRACE_REACH, TRACE_TOL, TRACE_SHARE = 9, 25.0, 2.0, 0.9
# Convention fixtures, same cube size and plane. A steep z ramp, 8 per slice, separates trilinear
# sampling from nearest-voxel sampling at quarter-voxel offsets; x and y ramps, 4 per voxel, show
# which point of the volume each output pixel samples.
STEEP_STEP, STEEP_Z0, XY_STEP, XY_BASE = 8, 16, 4, 10
CONVENTION_SLICES, CONVENTION_SLICE_STEP = 4, 0.5
REGISTRATION_SCALES = (1, 2)


class SetupError(Exception):
    """VC3D's tools are named but cannot be used as given (a VC_APPIMAGE that is not one)."""


class Tools:
    """A set of VC3D binaries and how to start them."""

    def __init__(self, kind, bindir, rootfs=None, note=None, via=None):
        self.kind, self.bindir, self.rootfs = kind, Path(bindir), Path(rootfs) if rootfs else None
        self.note, self.via = note, via      # via: the program every tool starts through (an AppImage's AppRun)

    def path(self, name):
        return self.bindir / name

    def has(self, name):
        if self.via is not None:
            # a link to AppRun stands for the AppImage's usr/bin/<name>, which must still be there: the link
            # itself resolves to AppRun whatever the folder now holds
            real = Path(self.via).parent / "usr" / "bin" / name
            if not (real.is_file() and os.access(real, os.X_OK)):
                return False
        return self.path(name).is_file()

    def argv(self, name, *args):
        exe = str(self.path(name))
        if self.rootfs is None:
            return [exe, *map(str, args)]
        loader, libs = rootfs_loader(self.rootfs)
        return [str(loader), "--library-path", ":".join(str(p) for p in libs), exe, *map(str, args)]

    def describe(self):
        how = f"through {rootfs_loader(self.rootfs)[0]}" if self.rootfs else (
            f"through {self.via}, by links named after each tool" if self.via else "directly")
        return f"{self.kind}: {self.bindir} (started {how})" + (f"; {self.note}" if self.note else "")


def rootfs_loader(rootfs, machine=None):
    """The dynamic loader and library path of an unpacked Debian or Ubuntu root filesystem."""
    arch = {"arm64": "aarch64"}.get(machine or platform.machine(), machine or platform.machine())
    triplet = f"{arch}-linux-gnu"
    loader = "ld-linux-aarch64.so.1" if arch == "aarch64" else "ld-linux-x86-64.so.2"
    root = Path(rootfs)
    libs = [root / p for p in ("usr/local/lib", f"usr/lib/{triplet}", f"lib/{triplet}", "usr/lib",
                               f"usr/local/lib/{triplet}")]
    return root / "usr/lib" / triplet / loader, libs


def find_tools(env=None):
    """Return the first usable Tools, or None. Raises SetupError for a VC_APPIMAGE that cannot be used."""
    env = os.environ if env is None else env
    if env.get("VC_ROOTFS"):
        return Tools("VC_ROOTFS", Path(env["VC_ROOTFS"]) / "usr/local/bin", rootfs=env["VC_ROOTFS"])
    if env.get("VC_BIN"):
        return _bin_tools("VC_BIN", Path(env["VC_BIN"]).expanduser(), env)
    if env.get("VC_APPIMAGE"):
        return appimage_tools(env["VC_APPIMAGE"], env)
    found = shutil.which(PROBE, path=env.get("PATH"))
    if found:
        return _bin_tools("PATH", Path(found).parent, env)
    if (MAC_BIN / PROBE).is_file():
        return Tools("VC3D.app", MAC_BIN)
    return None


def _bin_tools(kind, bindir, env):
    """Tools in bindir, or, when bindir is an extracted AppImage's usr/bin, the same tools started through AppRun."""
    root = appimage_root(bindir)
    if root is None:
        return Tools(kind, bindir)
    return appimage_tools(root, env, kind=kind, note=(
        f"{kind} points at {bindir}, inside an extracted AppImage, whose tools crash when started directly, so kit "
        f"starts them through its AppRun (set VC_APPIMAGE={root} to say so)"))


def appimage_root(bindir):
    """The extracted AppImage (squashfs-root) whose usr/bin bindir is, or None."""
    b = Path(bindir)
    if b.name == "bin" and b.parent.name == "usr" and (b.parent.parent / "AppRun").is_file():
        return b.parent.parent
    return None


def _label(text, key):
    import hashlib
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in text)[:60]
    return f"{safe}-{hashlib.sha256(key.encode()).hexdigest()[:10]}"


def appimage_tools(given, env=None, kind="VC_APPIMAGE", note=None):
    """The tools of villa's release AppImage. given is the .AppImage file or the folder it was extracted into
    (squashfs-root, holding AppRun and usr/bin; or a folder holding squashfs-root). AppRun starts each tool with the
    AppImage's own loader and libraries, choosing the tool by the name it was started as, so kit makes a link to
    AppRun named after every program in usr/bin, in <kit home>/work/vc3d/appimage/<name>/bin, and returns those.
    A file is first extracted there with its own --appimage-extract, which needs no FUSE."""
    from . import kithome
    src = Path(given).expanduser()
    if not src.exists():
        raise SetupError(f"VC_APPIMAGE is {src}, which does not exist: set it to villa's release AppImage "
                         f"(*-linux-x86_64.AppImage from {RELEASE}) or to the squashfs-root folder it extracts to")
    src = src.resolve()
    store = kithome.path("work", "vc3d", "appimage", env=env)
    try:
        if src.is_file():
            st = src.stat()
            base = store / _label(src.name, f"{src}|{st.st_size}|{st.st_mtime_ns}")
            root = base / "squashfs-root"
            if not (root / "AppRun").is_file():
                extract_appimage(src, base)
        else:
            root = src / "squashfs-root" if not (src / "AppRun").exists() and (src / "squashfs-root").is_dir() else src
            base = store / _label(root.parent.name if root.name == "squashfs-root" else root.name, str(root))
        if not (root / "AppRun").is_file() or not (root / "usr" / "bin").is_dir():
            raise SetupError(f"{root} is not an extracted AppImage (it needs AppRun and usr/bin): point VC_APPIMAGE "
                             "at the .AppImage file, or at the squashfs-root folder its --appimage-extract writes")
        links = link_apprun(root, base / "bin")
    except OSError as exc:
        raise SetupError(f"could not unpack or link the AppImage under {store}: {exc}; set KIT_HOME to a folder "
                         "you can write") from exc
    return Tools(kind, links, note=note, via=root / "AppRun")


def extract_appimage(appimage, base, timeout=900):
    """Unpack an AppImage into base/squashfs-root with its own --appimage-extract (no FUSE needed). Two processes
    may race: each extracts into a folder of its own and the first rename wins."""
    base = Path(base)
    if not os.access(appimage, os.X_OK):
        raise SetupError(f"{appimage} is not executable: run chmod +x on it, then try again")
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="extract-", dir=base))
    try:
        try:
            r = subprocess.run([str(appimage), "--appimage-extract"], cwd=tmp, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SetupError(f"{appimage} --appimage-extract could not run: {exc}") from exc
        out = tmp / "squashfs-root"
        if r.returncode != 0 or not (out / "AppRun").is_file():
            raise SetupError(f"{appimage} --appimage-extract exited {r.returncode} without writing "
                             f"squashfs-root/AppRun: {(r.stderr or '').strip()[-300:]}")
        try:
            os.rename(out, base / "squashfs-root")
        except OSError:
            if not (base / "squashfs-root" / "AppRun").is_file():
                raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return base / "squashfs-root"


def link_apprun(root, links):
    """In links, a link to root/AppRun named after each program in root/usr/bin (made, or brought up to date).
    A link whose program is gone from usr/bin (the folder was extracted again from another AppImage) is removed,
    so `which` cannot count it."""
    apprun = Path(root) / "AppRun"
    links = Path(links)
    links.mkdir(parents=True, exist_ok=True)
    programs = [exe for exe in sorted((Path(root) / "usr" / "bin").iterdir())
                if exe.is_file() and os.access(exe, os.X_OK)]
    names = {exe.name for exe in programs}
    for old in links.iterdir():
        if old.is_symlink() and not old.name.startswith(".") and old.name not in names:
            try:
                old.unlink()
            except FileNotFoundError:       # another process removed it first
                pass
    for exe in programs:
        link = links / exe.name
        if link.is_symlink() and os.readlink(link) == str(apprun):
            continue
        tmp = links / f".{exe.name}.{os.getpid()}.tmp"
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        os.symlink(apprun, tmp)
        os.replace(tmp, link)
    return links


def pipeline_tools(tools):
    """For each tool AutoPipeline runs: whether this set has it, and the stage that needs it."""
    return [{"tool": name, "stage": stage, "what": what, "found": tools.has(name)}
            for name, stage, what in PIPELINE_TOOLS]


def missing_text(row):
    return (f"missing: AutoPipeline's {row['stage']} stage runs it ({row['what']}); villa's latest release "
            f"AppImage has it ({RELEASE})")


def parse_cpu_max(text):
    """CPUs allowed by a cgroup v2 `cpu.max` line ("max 100000" means no quota)."""
    quota, _, period = text.strip().partition(" ")
    if quota == "max" or not period:
        return None
    return max(1, -(-int(quota) // int(period)))


def cpu_limit():
    """CPUs this process may use: the smaller of its affinity mask and any cgroup quota.

    A container often sees every host core; without a cap the tracer's OpenMP and OpenBLAS pools
    size themselves to the host, not the container."""
    try:
        n = len(os.sched_getaffinity(0))
    except AttributeError:
        n = os.cpu_count() or 1
    quota = None
    try:
        quota = parse_cpu_max(Path("/sys/fs/cgroup/cpu.max").read_text())
    except (OSError, ValueError):
        try:
            q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            p = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            quota = max(1, -(-q // p)) if q > 0 else None
        except (OSError, ValueError):
            pass
    return min(n, quota) if quota else n


def headless_env(base=None, threads=None):
    """A copy of the environment for running VC3D with no display.

    Qt uses its offscreen platform, OpenMP gets `threads` workers (default: VC_THREADS, then an
    existing OMP_NUM_THREADS, then cpu_limit()), and the OpenBLAS pool is off, because the tracer
    already parallelizes with OpenMP and an uncapped BLAS pool spins on every core."""
    env = dict(os.environ if base is None else base)
    env["QT_QPA_PLATFORM"] = "offscreen"
    n = threads or env.get("VC_THREADS") or env.get("OMP_NUM_THREADS") or cpu_limit()
    env["OMP_NUM_THREADS"] = str(n)
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    return env


# ---------------------------------------------------------------- fixture files (standard library)

def write_zarr_u8(path, shape, chunk, fill, axis="z", name="kit-vc3d-selftest"):
    """Uncompressed zarr v2 OME-Zarr (one level) whose voxel values are fill(coordinate along axis). With
    axis "row", fill(z, y) returns the bytes of the whole row along x at (z, y)."""
    root = Path(path)
    (root / "0").mkdir(parents=True, exist_ok=True)
    (root / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (root / ".zattrs").write_text(json.dumps({"multiscales": [{
        "version": "0.4", "name": name, "axes": [{"name": a, "type": "space"} for a in "zyx"],
        "datasets": [{"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0, 1.0]}]}]}]}))
    (root / "0" / ".zarray").write_text(json.dumps({
        "zarr_format": 2, "shape": list(shape), "chunks": [chunk] * 3, "dtype": "|u1", "compressor": None,
        "fill_value": 0, "filters": None, "order": "C", "dimension_separator": "/"}))
    counts = [-(-s // chunk) for s in shape]
    for cz in range(counts[0]):
        for cy in range(counts[1]):
            if axis == "row":
                rows = [fill(z, y) for z in range(cz * chunk, (cz + 1) * chunk)
                        for y in range(cy * chunk, (cy + 1) * chunk)]
            for cx in range(counts[2]):
                if axis == "row":
                    data = b"".join(r[cx * chunk:(cx + 1) * chunk].ljust(chunk, b"\0") for r in rows)
                elif axis == "z":
                    data = b"".join(bytes([fill(z)]) * chunk * chunk for z in range(cz * chunk, (cz + 1) * chunk))
                elif axis == "y":
                    data = b"".join(bytes([fill(y)]) * chunk for y in range(cy * chunk, (cy + 1) * chunk)) * chunk
                else:
                    data = bytes(fill(x) for x in range(cx * chunk, (cx + 1) * chunk)) * chunk * chunk
                out = root / "0" / str(cz) / str(cy) / str(cx)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
    return root


_lzw_decode = vc3d_io.lzw_decode
_packbits_decode = vc3d_io.packbits_decode


def read_tiff_u8(path):
    """(height, width, bytes) of a single-sample 8-bit TIFF (vc_render_tifxyz writes tiled LZW
    with the horizontal predictor). Other sample types raise ValueError; see kit.vc3d_io."""
    raster = vc3d_io.read_tiff(path)
    if raster.kind != "u8":
        raise ValueError(f"{path}: expected one 8-bit sample per pixel, found {raster.kind}")
    return raster.h, raster.w, bytes(raster.data)


def read_layers(tif_dir):
    """vc_render_tifxyz --tif-output: (layers, height, width, bytes) from 00.tif, 01.tif, ..."""
    files = sorted(Path(tif_dir).glob("*.tif"), key=lambda p: int(p.stem))
    if not files:
        raise ValueError(f"{tif_dir}: no layer TIFFs")
    shapes, data = set(), b""
    for f in files:
        h, w, img = read_tiff_u8(f)
        shapes.add((h, w))
        data += img
    if len(shapes) != 1:
        raise ValueError(f"{tif_dir}: layers differ in size {shapes}")
    return (len(files), *shapes.pop()), data


def write_tiff_f32(path, rows):
    """Single-strip uncompressed little-endian float32 TIFF, the layout tifxyz readers accept."""
    h, w = len(rows), len(rows[0])
    data = b"".join(struct.pack(f"<{w}f", *r) for r in rows)
    tags = [(256, 4, w), (257, 4, h), (258, 3, 32), (259, 3, 1), (262, 3, 1), (273, 4, None),
            (277, 3, 1), (278, 4, h), (279, 4, len(data)), (339, 3, 3)]
    data_at = 8 + 2 + 12 * len(tags) + 4
    ifd = struct.pack("<H", len(tags))
    for tag, typ, value in tags:
        value = data_at if value is None else value
        ifd += struct.pack("<HHI", tag, typ, 1) + (struct.pack("<HH", value, 0) if typ == 3 else struct.pack("<I", value))
    Path(path).write_bytes(b"II*\x00" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + data)


def write_plane(path):
    """The flat tifxyz surface described at the top of this module."""
    seg = Path(path)
    seg.mkdir(parents=True, exist_ok=True)
    n, s, x0 = PLANE_N, PLANE_STEP, PLANE_X0
    write_tiff_f32(seg / "x.tif", [[x0 + s * c for c in range(n)] for _ in range(n)])
    write_tiff_f32(seg / "y.tif", [[x0 + s * r for _ in range(n)] for r in range(n)])
    write_tiff_f32(seg / "z.tif", [[float(PLANE_Z)] * n for _ in range(n)])
    far = x0 + s * (n - 1)
    (seg / "meta.json").write_text(json.dumps({
        "format": "tifxyz", "type": "seg", "uuid": "kit-vc3d-plane", "scale": [1 / s, 1 / s],
        "bbox": [[x0, x0, float(PLANE_Z)], [far, far, float(PLANE_Z)]]}))
    return seg


def ramp(z):
    return RAMP_BASE + RAMP_STEP * z


def steep(z):
    return max(0, min(255, STEEP_STEP * (z - STEEP_Z0)))


def xy_ramp(c):
    return min(255, XY_BASE + XY_STEP * c)


def sheet_z(x, y, tilt=None):
    """Height of the tracer fixture's sheet at (x, y)."""
    sx, sy = SHEET_TILT if tilt is None else tilt
    return SHEET_SEED + sx * (x - SHEET_SEED) + sy * (y - SHEET_SEED)


def sheet_distance(point, tilt=None):
    """Distance in voxels from (x, y, z) to the tracer fixture's sheet."""
    sx, sy = SHEET_TILT if tilt is None else tilt
    x, y, z = point
    return abs(z - sheet_z(x, y, (sx, sy))) / math.sqrt(1 + sx * sx + sy * sy)


def sheet_value(z, y, x):
    return 255 if sheet_distance((x, y, z)) <= SHEET_HALF else 0


def sheet_row(z, y, n=SHEET_SIZE):
    """sheet_value at x = 0 ... n - 1 as n bytes. The sheet crosses the row (z, y) in one x interval, so sheet_value
    runs only from one voxel before that interval to one after it; every other voxel is at least a voxel past it and
    is 0. The 128-voxel cube then takes 119,604 calls instead of 2,097,152."""
    sx, sy = SHEET_TILT
    if not sx:   # the value does not depend on x
        return bytes([sheet_value(z, y, 0)]) * n
    mid = SHEET_SEED + (z - SHEET_SEED - sy * (y - SHEET_SEED)) / sx    # where the sheet's plane crosses the row
    half = SHEET_HALF * math.sqrt(1 + sx * sx + sy * sy) / abs(sx)      # half the interval's width in x
    row = bytearray(n)
    for x in range(max(0, math.floor(mid - half) - 1), min(n, math.ceil(mid + half) + 2)):
        row[x] = sheet_value(z, y, x)
    return bytes(row)


# ---------------------------------------------------------------- normal grids (villa's NormalGridVolume)

def write_grid_store(path, lines, width, height, cell=GRID_CELL):
    """Polylines [[(u, v), ...], ...] of one slice as a GridStore v3 file, laid out as villa's GridStore::save writes
    it (core/src/GridStore.cpp at e0bbb8b): 13 big-endian header words, the bucket index, each bucket's path offsets,
    the paths (start point, then int8 steps; LineSegList) and an empty JSON meta. u, v are (x, y) on xy slices,
    (x, z) on xz and (y, z) on yz. kit.surfacepred.read_grid reads it back."""
    gw, gh = -(-width // cell), -(-height // cell)
    buckets = [[] for _ in range(gw * gh)]
    paths, offsets = b"", []
    for line in lines:
        if len(line) < 2:
            continue
        steps = [d for a, b in zip(line, line[1:]) for d in (b[0] - a[0], b[1] - a[1])]
        if any(not -128 <= d <= 127 for d in steps):
            raise ValueError("a polyline step does not fit in int8")
        offsets.append(len(paths))
        paths += struct.pack(">iiI", line[0][0], line[0][1], len(steps)) + struct.pack(f">{len(steps)}b", *steps)
        for c in sorted({(v // cell) * gw + u // cell for u, v in line if 0 <= u < width and 0 <= v < height}):
            buckets[c].append(len(offsets) - 1)
    index, flat = [0], []
    for bucket in buckets:
        flat += [offsets[h] for h in bucket]
        index.append(len(flat))
    meta = b"{}"
    paths_at = 52 + 4 * (len(index) + len(flat))
    head = struct.pack(">13I", GRID_MAGIC, GRID_VERSION, 0, 0, width, height, cell, len(buckets), len(offsets), 52,
                       paths_at, paths_at + len(paths), len(meta))
    Path(path).write_bytes(head + struct.pack(f">{len(index)}I", *index) + struct.pack(f">{len(flat)}I", *flat)
                           + paths + meta)


def _slice_line(point, n=SHEET_SIZE, every=GRID_EVERY):
    """The integer polyline through point(t) = (u, v) for t = 0, every, ..., n - 1, where it lies in the slice."""
    out = []
    for t in [*range(0, n, every), n - 1]:
        u, v = point(t)
        if 0 <= u <= n - 1 and 0 <= v <= n - 1:
            out.append((int(math.floor(u + 0.5)), int(math.floor(v + 0.5))))
    return out


def sheet_grid_lines(plane, s, tilt=None):
    """The tracer fixture's sheet where it cuts slice s of plane "xy" (z = s), "xz" (y = s) or "yz" (x = s)."""
    sx, sy = SHEET_TILT if tilt is None else tilt
    c = SHEET_SEED
    if plane == "xz":
        return [_slice_line(lambda x: (x, sheet_z(x, s, (sx, sy))))]
    if plane == "yz":
        return [_slice_line(lambda y: (y, sheet_z(s, y, (sx, sy))))]
    if sx:
        return [_slice_line(lambda y: (c + (s - c - sy * (y - c)) / sx, y))]
    if sy:
        return [_slice_line(lambda x: (x, c + (s - c) / sy))]
    return []   # an untilted sheet fills its own xy slice and misses the others


def write_sheet_grids(root, tilt=None):
    """Normal grids of the tracer fixture's sheet in villa's NormalGridVolume layout: a single-scale metadata.json
    (the tracer takes its step from spiral-step and refuses a different step_size) and a GridStore file for every
    slice, xy/000000.grid ... by z, xz by y and yz by x (sparse-volume 1)."""
    root = Path(root)
    for plane in ("xy", "xz", "yz"):
        (root / plane).mkdir(parents=True, exist_ok=True)
        for s in range(SHEET_SIZE):
            write_grid_store(root / plane / f"{s:06d}.grid", sheet_grid_lines(plane, s, tilt), SHEET_SIZE, SHEET_SIZE)
    (root / "metadata.json").write_text(json.dumps({"spiral-step": TRACE_STEP, "grid-step": GRID_CELL,
                                                    "sparse-volume": 1}))
    return root


def tifxyz_points(path):
    """The valid vertices (x, y, z) of a tifxyz surface; villa writes -1 for the others."""
    xs, ys, zs = (vc3d_io.read_tiff(Path(path) / f"{a}.tif").floats() for a in "xyz")
    return [(x, y, z) for x, y, z in zip(xs, ys, zs) if x != -1]


# ---------------------------------------------------------------- self-test

def layer_medians(shape, data):
    """Median of the nonzero (valid surface) pixels of each layer; None for an empty layer."""
    plane = shape[1] * shape[2]
    out = []
    for k in range(shape[0]):
        vals = sorted(v for v in data[k * plane:(k + 1) * plane] if v)
        out.append(vals[len(vals) // 2] if vals else None)
    return out


def reverse_layers(shape, data):
    """The same stack with its layers in reverse order (what --flip-normals does to a render)."""
    plane = shape[1] * shape[2]
    return b"".join(data[k * plane:(k + 1) * plane] for k in reversed(range(shape[0])))


def read_order(medians):
    """'+N' if layer values rise like the ramp along +z, '-N' if they fall, None if neither.

    Pure function so the check can be tested without a binary."""
    c = len(medians) // 2
    for sign, name in ((1, "+N"), (-1, "-N")):
        expected = [ramp(PLANE_Z + sign * (k - c)) for k in range(len(medians))]
        if all(m is not None and abs(m - e) <= 1 for m, e in zip(medians, expected)):
            return name
    return None


def _num(v):
    return int(v) if v == int(v) else round(v, 3)


def read_sampling(medians, step=CONVENTION_SLICE_STEP):
    """'trilinear' or 'nearest' from layer medians of the steep-ramp render (layers `step` voxels
    apart, centred on the plane), in either layer order; None if neither fits."""
    n = len(medians)
    zs = [PLANE_Z + (k - (n - 1) / 2) * step for k in range(n)]
    linear = [steep(z) for z in zs]
    nearest = [steep(int(z + 0.5)) for z in zs]
    for name, expected in (("trilinear", linear), ("nearest", nearest)):
        for order in (expected, expected[::-1]):
            if all(m is not None and abs(m - e) <= 1 for m, e in zip(medians, order)):
                return name
    return None


def read_registration(line, scale):
    """From one row (x ramp) or column (y ramp) of a one-layer render of the plane: whether output
    pixels map linearly onto voxels at 1/scale voxels per pixel, where pixel 0 samples (0.5 means
    pixel centres, 0 pixel corners, in output pixels from the first grid vertex), and how much of
    the outermost grid cells renders as empty (in cells, first and last edge)."""
    pts = [(c, (v - XY_BASE) / XY_STEP) for c, v in enumerate(line) if v]
    if len(pts) < 4:
        return None
    offsets = [x - PLANE_X0 - c / scale for c, x in pts]
    last_vertex = PLANE_X0 + PLANE_STEP * (PLANE_N - 1)
    pixel_cells = 1 / (scale * PLANE_STEP)
    first, last = (pts[0][1] - PLANE_X0) / PLANE_STEP, (last_vertex - pts[-1][1]) / PLANE_STEP
    return {"linear": max(offsets) - min(offsets) <= 1 / XY_STEP + 1e-6,
            "pixel_origin": round(sum(offsets) / len(offsets) * scale, 3),
            # the empty margin lies between the first valid sample and the empty one before it
            "edge_cells": [round(first, 4), round(last, 4)],
            "edge_bracket": [round(max(first, last) - pixel_cells, 4), round(min(first, last), 4)],
            "valid_pixels": [pts[0][0], pts[-1][0]], "width": len(line)}


def trace_fit(points, tilt=None):
    """How a grown surface's vertices sit on the tracer fixture's sheet: how many, how far the farthest is from the
    seed, the share within TRACE_TOL voxels of the sheet and the median distance."""
    if not points:
        return {"vertices": 0, "reach": 0.0, "share": 0.0, "median": None}
    dist = sorted(sheet_distance(p, tilt) for p in points)
    return {"vertices": len(points), "reach": round(max(math.dist(p, (SHEET_SEED,) * 3) for p in points), 1),
            "share": round(sum(d <= TRACE_TOL for d in dist) / len(dist), 3), "median": round(dist[len(dist) // 2], 2)}


def trace_grew(fit):
    return fit["vertices"] >= TRACE_MIN_VERTICES and fit["reach"] >= TRACE_REACH


def mirror_tilt(tilt=None):
    """The control's sheet: through the same seed, tilted the other way."""
    sx, sy = SHEET_TILT if tilt is None else tilt
    return (-sx, -sy)


def trace_verdict(rc, fit, rc_control, control):
    """PASS when the grow with the sheet's normal grids stayed on the sheet and the control (the same grow with grids
    for the mirror sheet; both fits measured against the true sheet) grew but missed it; FAIL when the grow with the
    sheet's grids did not; VOID when the control did not miss it (or grew nothing), so the check cannot show that the
    grids put the grow on the sheet. Pure function so the rule can be tested without a binary."""
    if not (rc == 0 and trace_grew(fit) and fit["share"] >= TRACE_SHARE):
        return "FAIL"
    if rc_control == 0 and trace_grew(control) and control["share"] < TRACE_SHARE:
        return "PASS"
    return "VOID"


def _fit_text(rc, fit, problem=None):
    if not fit["vertices"]:
        return f"exit {rc}, no surface" + (f" ({problem})" if problem else "")
    return (f"exit {rc}, {fit['vertices']} vertices reaching {fit['reach']} voxels from the seed, "
            f"{fit['share']:.0%} within {_num(TRACE_TOL)} voxels of the sheet (median {fit['median']})")


def _run(argv, env, log, timeout):
    with open(log, "w") as fh:
        try:
            return subprocess.run(argv, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return "timeout"
        except OSError as exc:
            fh.write(f"{exc}\n")
            return f"could not start: {exc}"


def _check(results, name, ok, detail, void=False):
    results.append({"check": name, "pass": bool(ok), "detail": detail, **({"void": True} if void else {})})
    return ok


def selftest(tools, work, threads=1, timeout=300):
    """Run the headless checks in `work`; return a JSON-ready report with an overall verdict.

    Renders go to --tif-output, which every vc_render_tifxyz has written the same way (tiled LZW),
    so the published container's older binary can be tested too."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    env = headless_env(threads=threads)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    checks = []
    report = {"tools": tools.describe(), "work": str(work), "checks": checks, "pipeline_tools": pipeline_tools(tools)}

    help_log = work / "render-help.log"
    rc = _run(tools.argv(PROBE, "--help"), env, help_log, timeout)
    help_text = help_log.read_text(errors="replace")
    if not _check(checks, "render_starts", "--volume" in help_text, f"{PROBE} --help exit {rc} with no display"):
        report["verdict"] = "FAIL"
        return report
    report["flip_normals"] = "supported" if "--flip-normals" in help_text else "absent"

    def render(volume, surface, slices, out, *extra, scale=1):
        rc = _run(tools.argv(PROBE, "--volume", volume, "--segmentation", surface, "--scale", scale, "--group-idx", "0",
                             "--num-slices", slices, "--cache-gb", "1", *extra, "--tif-output", out),
                  env, f"{out}.log", timeout)
        try:
            return rc, *read_layers(out)
        except (OSError, ValueError, KeyError) as exc:
            return rc, None, f"output unreadable: {exc}"

    vol = write_zarr_u8(work / "ramp.zarr", [RAMP_SIZE] * 3, RAMP_SIZE, ramp)
    seg = write_plane(work / "plane.tifxyz")
    expected = [ramp(PLANE_Z + k - SLICES // 2) for k in range(SLICES)]
    orders, stacks = {}, {}
    for label, extra in (("default", ()), ("flip_normals", ("--flip-normals",))):
        if extra and report["flip_normals"] == "absent":
            continue
        rc, shape, data = render(vol, seg, SLICES, work / f"render-{label}", *extra)
        if shape is None:
            _check(checks, f"render_{label}", False, f"exit {rc}; {data}")
            continue
        medians = layer_medians(shape, data)
        orders[label], stacks[label] = read_order(medians), (shape, data)
        _check(checks, f"render_{label}", rc == 0 and shape[0] == SLICES and orders[label] is not None,
               f"exit {rc}, shape {list(shape)}, layer medians {medians}, expected {expected} in either order")
    report["default_order"] = orders.get("default")
    if orders.get("default") and "flip_normals" in orders:
        _check(checks, "flip_reverses", orders["flip_normals"] not in (None, orders["default"]),
               f"default {orders['default']}, --flip-normals {orders['flip_normals']}")
        (shape, plain), (_, flipped) = stacks["default"], stacks["flip_normals"]
        _check(checks, "flip_equals_reversed_stack", reverse_layers(shape, plain) == flipped,
               "the --flip-normals render is the default render with its layers in reverse order, byte for byte")

    conventions = report["conventions"] = {"default_order": orders.get("default")}
    vol = write_zarr_u8(work / "steep.zarr", [RAMP_SIZE] * 3, RAMP_SIZE, steep, name="kit-vc3d-steep-z")
    rc, shape, data = render(vol, seg, CONVENTION_SLICES, work / "render-steep", "--slice-step", CONVENTION_SLICE_STEP)
    zs = [PLANE_Z + (k - (CONVENTION_SLICES - 1) / 2) * CONVENTION_SLICE_STEP for k in range(CONVENTION_SLICES)]
    if shape is None:
        _check(checks, "render_trilinear", False, f"exit {rc}; {data}")
    else:
        medians = layer_medians(shape, data)
        conventions["sampling"] = read_sampling(medians)
        _check(checks, "render_trilinear", rc == 0 and conventions["sampling"] == "trilinear",
               f"layers {CONVENTION_SLICE_STEP} voxels apart through a ramp of {STEEP_STEP} per voxel: medians {medians}; "
               f"trilinear gives {[_num(steep(z)) for z in zs]}, nearest voxel {[steep(int(z + 0.5)) for z in zs]}")

    found, problems = {}, []
    for axis in "xy":
        vol = write_zarr_u8(work / f"ramp-{axis}.zarr", [RAMP_SIZE] * 3, RAMP_SIZE, xy_ramp, axis=axis,
                            name=f"kit-vc3d-ramp-{axis}")
        for scale in REGISTRATION_SCALES:
            rc, shape, data = render(vol, seg, 1, work / f"render-{axis}-{scale}", scale=scale)
            if shape is None:
                problems.append(f"{axis} at scale {scale}: exit {rc}; {data}")
                continue
            h, w = shape[1:]
            line = data[(h // 2) * w:(h // 2 + 1) * w] if axis == "x" else data[w // 2::w][:h]
            got = read_registration(list(line), scale)
            if got is None:
                problems.append(f"{axis} at scale {scale}: fewer than 4 valid pixels")
                continue
            found[f"{axis}@{scale}"] = got
            if not got["linear"]:
                problems.append(f"{axis} at scale {scale}: pixels do not map linearly at {1 / scale} voxels per pixel")
    origins = {g["pixel_origin"] for g in found.values()}
    if len(origins) > 1:
        problems.append(f"pixel 0 samples different points per axis or scale: {sorted(origins)}")
    if found and not problems:
        conventions["pixel_origin"] = origins.pop()
        lo = max(g["edge_bracket"][0] for g in found.values())
        hi = min(g["edge_bracket"][1] for g in found.values())
        conventions["edge_loss_cells"] = round((lo + hi) / 2 * 8) / 8
        conventions["edge_loss_bracket"] = [lo, hi]
    _check(checks, "render_registration", found and not problems,
           "; ".join(problems) or ", ".join(f"{k}: pixels {g['valid_pixels'][0]}..{g['valid_pixels'][1]} of {g['width']}, "
                                            f"origin {g['pixel_origin']} px, edges {g['edge_cells']} cells"
                                            for k, g in found.items()))

    if tools.has(TRACER):
        # villa e0bbb8b's tracer reads only this cube's shape (see the tracer fixture above)
        pred = write_zarr_u8(work / "sheet.zarr", [SHEET_SIZE] * 3, SHEET_SIZE // 2, sheet_row, axis="row",
                             name="kit-vc3d-tilted-sheet")
        mirror = mirror_tilt()
        runs = {}
        for label, grids in (("grids", write_sheet_grids(work / "sheet.normal-grids")),
                             ("mirror", write_sheet_grids(work / "mirror.normal-grids", mirror)), ("nogrids", None)):
            params, grown = work / f"grow-{label}.json", work / f"grown-{label}"
            shutil.rmtree(grown, ignore_errors=True)   # never score a surface an earlier run left in --work
            params.write_text(json.dumps({"generations": TRACE_GENERATIONS, "step_size": TRACE_STEP, "min_area_cm": 0,
                                          "use_cuda": False, "thread_limit": threads, "voxelsize": 10.0,
                                          "cache_size": 1e8, **({"normal_grid_path": str(grids)} if grids else {})}))
            rc = _run(tools.argv(TRACER, "-v", pred, "-t", grown, "-p", params, "-s", *[SHEET_SEED] * 3,
                                 "--segment-name", grown.name), env, work / f"grow-{label}.log", timeout)
            points, problem = [], None
            try:
                points = tifxyz_points(grown)
            except (OSError, ValueError) as exc:
                problem = str(exc)
            runs[label] = (rc, points, problem)
        (rc, fit, problem), (rc_c, control, problem_c), (rc_n, bare, problem_n) = (
            (r[0], trace_fit(r[1]), r[2]) for r in (runs["grids"], runs["mirror"], runs["nogrids"]))
        control["share_on_mirror"] = trace_fit(runs["mirror"][1], mirror)["share"]
        verdict = trace_verdict(rc, fit, rc_c, control)
        report["trace"] = {"verdict": verdict, "tilt": list(SHEET_TILT), "mirror_tilt": list(mirror), "grids": fit,
                           "mirror_grids": control, "no_grids": bare}
        why = {"PASS": "the control missed the sheet, so the grids put the grow on it and this check can fail",
               "FAIL": (f"the grow with the sheet's grids needs at least {TRACE_MIN_VERTICES} vertices, one at least "
                        f"{_num(TRACE_REACH)} voxels from the seed, and {TRACE_SHARE:.0%} of them within "
                        f"{_num(TRACE_TOL)} voxels of the sheet"),
               "VOID": ("the control did not grow and miss the sheet, so this check cannot show that the grids put "
                        "the grow on the sheet; it could have passed with grids the tracer ignores, and does not "
                        "count as a pass")}[verdict]
        mirrored = "" if not control["vertices"] else f", {control['share_on_mirror']:.0%} on the mirror sheet"
        _check(checks, "trace_follows_grids", verdict == "PASS",
               f"{TRACER} on a sheet tilted {list(SHEET_TILT)} (dz/dx, dz/dy) out of the seed quad's plane, with "
               f"the sheet's normal grids: {_fit_text(rc, fit, problem)}; with grids for the mirror sheet "
               f"{list(mirror)} (control): {_fit_text(rc_c, control, problem_c)}{mirrored}; without grids "
               f"(reported, not scored): {_fit_text(rc_n, bare, problem_n)}; {why}", void=verdict == "VOID")
    report["verdict"] = "PASS" if checks and all(c["pass"] for c in checks) else "FAIL"
    return report


def format_report(report):
    lines = [f"tools: {report['tools']}", "display: none (QT_QPA_PLATFORM=offscreen, DISPLAY unset)"]
    lines += [f"[{'VOID' if c.get('void') else 'PASS' if c['pass'] else 'FAIL'}] {c['check']}: {c['detail']}"
              for c in report["checks"]]
    if "flip_normals" in report:
        lines.append(f"--flip-normals: {report['flip_normals']}")
    if report.get("default_order"):
        layers = "toward" if report["default_order"] == "+N" else "away from"
        lines.append(f"without --flip-normals, layer index grows {layers} the surface normal "
                     "d(point)/d(column) x d(point)/d(row)")
    conv = report.get("conventions", {})
    if conv.get("sampling"):
        lines.append(f"sampling: {conv['sampling']}")
    if conv.get("pixel_origin") is not None:
        where = {0.5: "pixel centres", 0.0: "pixel corners"}.get(conv["pixel_origin"], f"{conv['pixel_origin']} px")
        lines.append(f"output pixel p samples grid point (p + {conv['pixel_origin']}) / scale ({where}); "
                     f"the outer {conv['edge_loss_cells']} grid cell of every surface edge renders empty "
                     f"(measured between {conv['edge_loss_bracket'][0]} and {conv['edge_loss_bracket'][1]})")
    if report.get("flip_normals") == "absent":
        lines.append("this binary cannot put layers in the team's order; build villa main or reverse the stack")
    rows = report.get("pipeline_tools") or []
    missing = [r for r in rows if not r["found"]]
    if rows and not missing:
        lines.append(f"AutoPipeline's tools: all {len(rows)} present")
    for r in missing:
        lines.append(f"[MISSING] {r['tool']}: {missing_text(r)}")
    lines.append(f"verdict: {report['verdict']}  (work files in {report['work']})"
                 + ("; the verdict covers the checks above, not the missing tools" if missing else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------- command line

def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("which", help="where the VC3D tools are, how they will be started, and whether the five "
                                     "AutoPipeline runs are there (exit 1 when one is missing)")
    a = actions.add_parser("env", help="print shell exports for a headless run")
    a.add_argument("--threads", type=int, help="OpenMP threads (default: VC_THREADS, OMP_NUM_THREADS, then the CPU quota)")
    a = actions.add_parser("run", help="run one VC3D tool with the headless environment")
    a.add_argument("--threads", type=int)
    a.add_argument("tool", help="e.g. vc_render_tifxyz, vc_grow_seg_from_seed or VC3D")
    a.add_argument("args", nargs="*", help="passed through; put -- before arguments that start with a dash")
    a = actions.add_parser("selftest", help="render and trace a synthetic volume with no display and check the values")
    a.add_argument("--work", help="directory for the fixture and outputs (default: a new temporary directory)")
    a.add_argument("--threads", type=int, default=1)
    a.add_argument("--timeout", type=int, default=300, help="seconds per tool call")
    a.add_argument("--json", action="store_true")
    actions.add_parser("mcp", help="serve the agent tools over MCP on stdio (for Claude Code, Claude Desktop "
                                   "or any MCP client); docs/vc3d-agents.md")
    a = actions.add_parser("tools", help="list the agent tools the MCP server offers")
    a.add_argument("--json", action="store_true", help="with their input schemas")
    a = actions.add_parser("call", help="run one agent tool from a shell and print its JSON result")
    a.add_argument("tool", help="e.g. status, selftest, trace, render, check_surface, ink, preview, jobs")
    a.add_argument("arguments", nargs="?", default="{}", help="a JSON object of arguments, or @FILE holding one")
    a.add_argument("--background", action="store_true", help="start it as a background job; read it with the jobs tool")
    a = actions.add_parser("app-mcp", help="run villa's MCP server for the VC3D app (tools/vc3d-mcp) with "
                                           "the app offscreen; its first start installs the mcp package")
    a.add_argument("--villa", help="villa checkout (default: VILLA_DIR, the folders around the VC3D build, ~/villa)")
    a.add_argument("args", nargs="*", help="passed to vc3d-mcp, e.g. -- --volpkg PATH")
    return p


def find_villa_mcp(tools, given=None, env=None):
    """villa's tools/vc3d-mcp/run.sh: from --villa, VILLA_DIR, the build the tools came from, or beside us."""
    env = os.environ if env is None else env
    places = [given, env.get("VILLA_DIR")]
    if tools is not None:
        places += list(tools.bindir.parents)
    places += [Path.home() / "villa", Path(__file__).resolve().parents[2] / "villa"]
    for place in places:
        if not place:
            continue
        for run in (Path(place) / "volume-cartographer" / "tools" / "vc3d-mcp" / "run.sh",
                    Path(place) / "tools" / "vc3d-mcp" / "run.sh"):
            if run.is_file():
                return run
    return None


def app_mcp(args, tools):
    """Replace this process with villa's vc3d-mcp, which launches VC3D offscreen with its bridge on."""
    run = find_villa_mcp(tools, args.villa)
    if run is None:
        print("villa's tools/vc3d-mcp not found: pass --villa or set VILLA_DIR to a villa checkout", file=sys.stderr)
        return 2
    if tools is None or not tools.has("VC3D") or tools.rootfs is not None:
        print("app-mcp needs the VC3D app runnable directly (VC_BIN or PATH); the kit server's app_start and "
              "app_call tools drive the same bridge", file=sys.stderr)
        return 2
    env = headless_env()
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    env["VC3D_BINARY"] = str(tools.path("VC3D"))
    extra = list(args.args)
    if extra[:1] == ["--"]:
        extra = extra[1:]
    os.execvpe("bash", ["bash", str(run), "--launch", str(tools.path("VC3D")), *extra], env)


def cmd_vc3d(args):
    if args.action == "mcp":
        from . import vc3d_mcp
        return vc3d_mcp.main()
    if args.action in ("tools", "call"):
        from . import vc3d_agent
        return vc3d_agent.cli(args)
    if args.action == "env":            # needs no tools: never extract an AppImage or fail on one just to print
        env = headless_env(threads=args.threads)
        for k in ("QT_QPA_PLATFORM", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_WAIT_POLICY"):
            print(f"export {k}={env[k]}")
        print("unset DISPLAY WAYLAND_DISPLAY")
        return 0
    try:
        tools = find_tools()
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.action == "app-mcp":
        return app_mcp(args, tools)
    if tools is None:
        print(f"no VC3D tools found: set VC_APPIMAGE to villa's release AppImage ({RELEASE}) or the folder it "
              "extracts to, VC_BIN to a directory holding vc_render_tifxyz, VC_ROOTFS to an unpacked container "
              "root, or put the tools on PATH (docs/vc3d-headless.md)", file=sys.stderr)
        return 2
    if args.action == "which":
        print(tools.describe())
        rows = pipeline_tools(tools)
        for r in rows:
            print(f"  {r['tool']}: " + (f"found ({r['stage']} stage)" if r["found"] else missing_text(r)))
        print(f"  VC3D: {'found' if tools.has('VC3D') else 'missing'} (the app; AutoPipeline does not need it)")
        missing = [r["tool"] for r in rows if not r["found"]]
        print(f"AutoPipeline: {len(rows) - len(missing)} of its {len(rows)} VC3D tools found"
              + (f"; missing {', '.join(missing)}" if missing else ""))
        return 1 if missing else 0
    if args.action == "run":
        if not tools.has(args.tool):
            print(f"{args.tool} not in {tools.bindir}", file=sys.stderr)
            return 2
        env = headless_env(threads=args.threads)
        return subprocess.run(tools.argv(args.tool, *args.args), env=env).returncode
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="kit-vc3d-"))
    report = selftest(tools, work, threads=args.threads, timeout=args.timeout)
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0 if report["verdict"] == "PASS" else 1
