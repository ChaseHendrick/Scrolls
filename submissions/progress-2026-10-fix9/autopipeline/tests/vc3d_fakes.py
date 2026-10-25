"""Stand-ins for VC3D's tools and app, and small fixture writers, for the agent, MCP and ink tests.

Each fake takes the real tool's command line and follows the conventions measured on villa
e0bbb8b (docs/vc3d-headless.md) closely enough to test the layer above it, not VC3D itself:

  vc_render_tifxyz       samples a local zarr (or a URL mapped to one by FAKE_REMOTE_MAP) along a
                         tifxyz surface: bilinear on the grid, nearest voxel in the volume, layer k at
                         (k - (n - 1) / 2) * slice-step voxels along +N = d/dcol x d/drow (along -N
                         with --flip-normals), crop, scale, --scale-segmentation, pyramid level,
                         composites, TIFF and zarr output (levels 0 and 1). FAKE_OLD=1 hides
                         --flip-normals like the published container; FAKE_FAIL_FILE with
                         FAKE_FAIL_TIMES=N fails the first N runs, as a dropped chunk fetch would.
                         FAKE_URL_VOLUME=1 acts as villa since ba2bf75: it takes a remote URL as --volume
                         (or --remote-url alone), prints --remote-url as deprecated in its help, and
                         exits 1 when --volume and --remote-url name different sources.
                         FAKE_RENDER_VC3D_MASK=1 leaves empty, as VC3D does, a pixel whose nearest grid
                         vertex is on the border, a hole or next to one (kit labelxfer.rendered_mask).
  vc_grow_seg_from_seed  writes a flat 9 x 9 tifxyz at the seed's z (32 without a seed; with FAKE_TRACE_ARC=
                         cx,cy a 9 x 9 piece of the cylinder through the seed around that axis, rows along
                         z, both grid steps 4 voxels; with FAKE_TRACE_TURN_DEG=a too, the grid turned in plane
                         so that +z runs along grid direction a, from +row toward +col), or the resumed
                         surface 4 voxels further along z; gen_neighbor moves the surface 12 voxels in
                         or out, but finds nothing unless neighbor_max_distance is set (as the real
                         tracer found nothing on the fixture with its defaults); FAKE_TRACE_EMPTY=1
                         writes nothing. With normal_grid_path it prints the folder and its streaming URL,
                         creates the files in FAKE_GRID_FETCH and a .missing marker for each in
                         FAKE_GRID_MISSING (JSON lists of paths in the folder). It prints villa's "gen N
                         processing" and "-> done" lines for generations 2 to FAKE_TRACE_GENS (default 4), each
                         after a GridStore hit-rate warning, and meta.json gets max_gen. FAKE_TRACE_HANG=S then
                         sleeps S seconds before writing (a trace a timeout stops): with "snapshot-interval" in
                         its parameters it first writes the surface as a snapshot (stop_reason running), as villa
                         does every N generations. FAKE_TRACE_TIME_LIMIT=1 with "time_limit_s" acts as
                         a villa patch of the source repository: it stops, saves, and writes stop_reason time_limit.
                         FAKE_TRACE_SAVE_FALLBACK=1 with a hang and snapshots then writes the next snapshot into
                         .tmp_140230/NAME and removes the folder before sleeping (villa's save fallback without
                         RENAME_EXCHANGE, stopped between its two steps). FAKE_TRACE_SIGNAL=N with a hang kills
                         the fake with signal N after its snapshot (a kill kit did not send); FAKE_TRACE_HANG_AFTER=S
                         sleeps S seconds after the final save (a timeout that comes after it).
                         FAKE_TRACE_GENERATIONS=1 also writes generations.tif: each vertex's ring around the grid
                         center (1 to 5), and on a resume the source's channel, so a resume adds no growth.
  vc_flatten             copies the surface and marks meta.json flattened.
  vc_extend_edge         copies the surface, marks meta.json extended and writes a --report naming 2 vertices
                         per line per round on each side (no geometry is added).
  vc_tifxyz_selfcross    writes a clean report, or 3 transverse crossings with FAKE_SELFCROSS=dirty; with
                         FAKE_SELFCROSS=crash it exits 1 and writes no report.
  vc_gen_umbilicus       one control point per .grid file in the input's xy folder (or per --slices), on a
                         straight axis x = 32 + 0.01 z, y = 30; the slices in FAKE_UMB_OUTLIERS sit 400
                         voxels off it.
  vc_sleep SECONDS       prints a tick every 0.1 s, then exits with --exit N; writes its pid to --pid;
                         --stubborn-child FILE starts a child that ignores SIGTERM (as a torch
                         data-loader worker can) and writes its pid there.
  VC3D                   the app: prints the agent bridge handshake and answers ping, rpc.describe,
                         state.get, volume.open and screenshot.capture over a Unix socket.

Every fake appends its argv to $FAKE_LOG when that is set. Standard library only.
"""

import array
import gzip
import json
import os
import stat
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kit import vc3d, vc3d_io  # noqa: E402

PRELUDE = f'''#!{sys.executable}
import json, math, os, sys, time
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from kit import vc3d_io
argv = sys.argv[1:]
if os.environ.get("FAKE_LOG"):
    with open(os.environ["FAKE_LOG"], "a") as fh:
        fh.write(json.dumps([Path(sys.argv[0]).name, *argv]) + "\\n")
def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default
'''

RENDER = PRELUDE + r'''
old = os.environ.get("FAKE_OLD") == "1"
# FAKE_URL_VOLUME=1: villa since ba2bf75 (#1863, 12 Oct 2026) takes a remote URL as --volume, marks
# --remote-url deprecated, and exits 1 when --volume and --remote-url name different sources.
url_volume = os.environ.get("FAKE_URL_VOLUME") == "1"
if "--help" in argv:
    print("vc_render_tifxyz: render a surface volume along a tifxyz surface")
    if url_volume:
        print("  -v [ --volume ] arg                   Local OME-Zarr volume directory, or a remote OME-Zarr")
        print("                                        URL (http(s)://, s3://) to stream")
        print("  --remote-url arg                      [DEPRECATED] Same as passing the remote OME-Zarr URL as")
        print("                                        --volume")
        print("  --segmentation --scale --group-idx --num-slices --slice-step --tif-output --zarr-output")
        print("  --zarr-compressor --surface-interpolation --crop-x --crop-y --scale-segmentation")
    else:
        print("  --volume --segmentation --scale --group-idx --num-slices --slice-step --tif-output --zarr-output")
        print("  --zarr-compressor --surface-interpolation --remote-url --crop-x --crop-y --scale-segmentation")
    if not old:
        print("  --flip-normals  Negate surface normals")
    sys.exit(0)
FLAGS = {"--flip-normals", "--auto-crop", "--resume", "--flatten", "--composite-collapse"}
opts, i = {}, 0
while i < len(argv):
    if argv[i] in FLAGS:
        opts[argv[i]], i = True, i + 1
    else:
        opts[argv[i]], i = argv[i + 1], i + 2
if old and "--flip-normals" in opts:
    sys.exit("unrecognised option '--flip-normals'")
fail = os.environ.get("FAKE_FAIL_FILE")
if fail:
    done = Path(fail).read_text().count("x") if Path(fail).exists() else 0
    if done < int(os.environ.get("FAKE_FAIL_TIMES", "1")):
        Path(fail).write_text("x" * (done + 1))
        print("chunk fetch failed: connection reset by peer")
        sys.exit(1)
src = opts.get("--volume") or (opts.get("--remote-url") if url_volume else None)   # ba2bf75: --remote-url alone
if src is None:
    sys.exit("the option '--volume' is required but missing")
if url_volume and "--remote-url" in opts and opts["--remote-url"] != src:
    print("Error: --volume (%s) and --remote-url (%s) name different sources; --remote-url is deprecated, "
          "pass the remote URL as --volume" % (src, opts["--remote-url"]), file=sys.stderr)
    sys.exit(1)
if url_volume and "://" in src:
    opts["--remote-url"] = src
if "--remote-url" in opts:
    import urllib.parse
    url = opts["--remote-url"]
    remote = json.loads(os.environ.get("FAKE_REMOTE_MAP", "{}"))
    # a URL maps by itself, or by its path (the relay's URL keeps the volume's path)
    src = remote.get(url) or remote.get(urllib.parse.urlsplit(url).path.rstrip("/"))
    if src is None:
        sys.exit("cannot open remote volume " + url)
    once = os.environ.get("FAKE_EMPTY_ONCE")
    if os.environ.get("FAKE_EMPTY_MARKERS") and not (once and Path(once).exists()):
        # what VC3D does with a false 404: an empty marker in its persistent cache, for good
        from kit import vc3d_cache
        folder = vc3d_cache.volume_dir(url, os.environ)
        for rel in json.loads(os.environ["FAKE_EMPTY_MARKERS"]):
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(b"")
        if once:
            Path(once).write_text("x")
level = int(opts.get("--group-idx", 0))
vol = vc3d_io.open_zarr(src, level)
Z, Y, X = vol.shape
data, _ = vol.read([(0, Z), (0, Y), (0, X)])

def voxel(x, y, z):
    x, y, z = int(math.floor(x + 0.5)), int(math.floor(y + 0.5)), int(math.floor(z + 0.5))
    return data[(z * Y + y) * X + x] if 0 <= z < Z and 0 <= y < Y and 0 <= x < X else 0

seg = Path(opts["--segmentation"])
meta = json.loads((seg / "meta.json").read_text())
sx, sy = meta["scale"][:2]
gx, gy, gz = (vc3d_io.read_tiff(seg / (a + ".tif")) for a in "xyz")
rows, cols = gx.h, gx.w
s = float(opts.get("--scale-segmentation", 1))
f = float(opts.get("--scale", 1)) * s / 2 ** level
coord = s / 2 ** level
full_h, full_w = int(rows / sy * f), int(cols / sx * f)

# FAKE_RENDER_VC3D_MASK=1: leave a pixel empty, as VC3D does, when the grid vertex nearest it is on the grid's
# border, a hole, or next to one (no render normal there; kit labelxfer's rendered_mask)
vc3d_mask = os.environ.get("FAKE_RENDER_VC3D_MASK") == "1"

def hole(rr, cc):
    k = rr * cols + cc
    return (gx.data[k], gy.data[k], gz.data[k]) == (-1.0, -1.0, -1.0)

def surface_at(r, c):
    """Point and unit normal (+N) at output pixel (r, c), or None off the grid."""
    u, v = (c + 0.5) * sx / f, (r + 0.5) * sy / f
    if not (0 <= u <= cols - 1 and 0 <= v <= rows - 1):
        return None
    if vc3d_mask:
        nr, nc = int(math.floor(v + 0.5)), int(math.floor(u + 0.5))
        if not (1 <= nr <= rows - 2 and 1 <= nc <= cols - 2) or any(
                hole(a, b) for a, b in ((nr, nc), (nr - 1, nc), (nr + 1, nc), (nr, nc - 1), (nr, nc + 1))):
            return None
    c0, r0 = min(int(u), cols - 2), min(int(v), rows - 2)
    fu, fv = u - c0, v - r0
    corners = []
    for rr, cc in ((r0, c0), (r0, c0 + 1), (r0 + 1, c0), (r0 + 1, c0 + 1)):
        k = rr * cols + cc
        p = (gx.data[k], gy.data[k], gz.data[k])
        if p == (-1.0, -1.0, -1.0):
            return None
        corners.append(p)
    a, b, cc_, d = corners
    point = [((a[k] + (b[k] - a[k]) * fu) * (1 - fv) + (cc_[k] + (d[k] - cc_[k]) * fu) * fv) * coord for k in range(3)]
    du = [b[k] - a[k] for k in range(3)]
    dv = [cc_[k] - a[k] for k in range(3)]
    n = [du[1] * dv[2] - du[2] * dv[1], du[2] * dv[0] - du[0] * dv[2], du[0] * dv[1] - du[1] * dv[0]]
    norm = math.sqrt(sum(t * t for t in n)) or 1.0
    return point, [t / norm for t in n]

x0, y0 = int(opts.get("--crop-x", 0)), int(opts.get("--crop-y", 0))
w, h = int(opts.get("--crop-width", full_w - x0)), int(opts.get("--crop-height", full_h - y0))
if opts.get("--auto-crop"):
    hits = [(r, c) for r in range(full_h) for c in range(full_w) if surface_at(r, c)]
    rs, cs = [r for r, _ in hits], [c for _, c in hits]
    x0, y0, w, h = min(cs), min(rs), max(cs) - min(cs) + 1, max(rs) - min(rs) + 1
sign = -1.0 if opts.get("--flip-normals") else 1.0
step = float(opts.get("--slice-step", 1))
if opts.get("--composite-collapse"):
    offsets = [[float(t) for t in range(int(opts["--composite-start"]), int(opts["--composite-end"]) + 1)]]
    how = opts.get("--accum-type", "max")
else:
    n = int(opts.get("--num-slices", 1))
    offsets = [[sign * (k - (n - 1) / 2) * step] for k in range(n)]
    how = None
layers = []
for offs in offsets:
    img = bytearray(w * h)
    for r in range(h):
        for c in range(w):
            hit = surface_at(y0 + r, x0 + c)
            if hit is None:
                continue
            (px, py, pz), (nx, ny, nz) = hit
            vals = [voxel(px + o * nx, py + o * ny, pz + o * nz) for o in offs]
            img[r * w + c] = int(max(vals) if how in (None, "max") else sum(vals) / len(vals))
    layers.append(bytes(img))
print(f"rendered {len(layers)} layers of {w} x {h}", flush=True)
if opts.get("--tif-output"):
    out = Path(opts["--tif-output"])
    out.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(layers) - 1)))
    for k, img in enumerate(layers):
        vc3d_io.write_tiff(out / f"{k:0{width}d}.tif", vc3d_io.Raster(h, w, "u8", img))
if opts.get("--zarr-output"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
    import fakezarr
    stack = b"".join(layers)
    fakezarr.write_group(opts["--zarr-output"], [len(layers), h, w], lambda z, y, x: stack[(z * h + y) * w + x],
                         chunk=[len(layers), 32, 32], compressor=opts.get("--zarr-compressor"), levels=2)
'''

TRACER = PRELUDE + r'''
import array
if "--help" in argv:
    print("vc_grow_seg_from_seed: -v VOLUME -t TARGET -p PARAMS [-s X Y Z] [--resume TIFXYZ] [--segment-name NAME]")
    sys.exit(0)
params = json.loads(Path(opt("-p")).read_text())
mode = params.get("mode", "seed")
print(f"mode {mode}, threads {params.get('thread_limit')}", flush=True)
if params.get("normal_grid_path"):
    # as VC3D's NormalGridVolume: a folder with normal-grids-remote.json streams its files; FAKE_GRID_FETCH lists
    # files the trace fetched, FAKE_GRID_MISSING files that answered 404 (VC3D leaves <file>.missing for good),
    # FAKE_GRID_FAIL files it got no answer for
    ngp = Path(params["normal_grid_path"])
    marker = ngp / "normal-grids-remote.json"
    remote = json.loads(marker.read_text())["url"] if marker.is_file() else None
    print(f"normal grids {ngp} remote {remote}", flush=True)
    for rel in json.loads(os.environ.get("FAKE_GRID_FETCH", "[]")):
        (ngp / rel).parent.mkdir(parents=True, exist_ok=True)
        (ngp / rel).write_bytes(b"grid")
    for rel in json.loads(os.environ.get("FAKE_GRID_MISSING", "[]")):
        (ngp / rel).parent.mkdir(parents=True, exist_ok=True)
        (ngp / (rel + ".missing")).write_bytes(b"")
    for rel in json.loads(os.environ.get("FAKE_GRID_FAIL", "[]")):   # no answer: VC3D says so and leaves no marker
        print(f"normal-grid fetch for {rel} returned HTTP 0", file=sys.stderr, flush=True)
if os.environ.get("FAKE_TRACE_EMPTY") == "1":
    print("no seed point found on the sheet")
    sys.exit(0)
gens = int(os.environ.get("FAKE_TRACE_GENS", "4"))
area, per_day = 0.0, 0.0
for g in range(2, gens + 1):
    print(f"[GridStore Cache] Hitrate Warning Triggered: Hits: {1000 * g}, Misses: {20 * g}, Total: {1020 * g}, "
          "Hit Rate: 98.04%", flush=True)
    print(f"gen {g} processing {8 * g - 4} fringe cands (total done {4 * (g - 1) ** 2 - 4} fringe: {8 * g - 12})",
          flush=True)
    area = (4 * g * g - 4) * 0.0351
    per_day = 0.000864 * g        # 0.01 g mm^2/s: elapsed = area / speed
    print(f"-> done {4 * g * g - 4} | fringe {8 * g - 4} | area {area:.2f} mm^2 ({area / 1e6:.6f} m^2) | avg speed "
          f"{per_day * 1e6 / 86400:.2f} mm^2/s ({per_day:.6f} m^2/day) | current speed 0.05 mm^2/s", flush=True)
hang = float(os.environ.get("FAKE_TRACE_HANG", "0"))
limited = os.environ.get("FAKE_TRACE_TIME_LIMIT") == "1" and params.get("time_limit_s")
if limited:
    print(f"stopping before generation {gens + 1}: 30 s used, the next generation would take about 10 s, "
          f"time_limit_s {params['time_limit_s']}", flush=True)
target = Path(opt("-t"))
name = opt("--segment-name")
seg = target if name else target / ("auto_grown_" + time.strftime("%Y%m%d%H%M%S") + "%06d" % (time.time_ns() // 1000 % 10**6))
rows = cols = 9
if opt("--resume"):
    src = Path(opt("--resume"))
    g = [vc3d_io.read_tiff(src / (a + ".tif")).data for a in "xyz"]
    if mode == "gen_neighbor":
        dz = 12.0 if params.get("neighbor_dir", "out") == "out" else -12.0
        if "neighbor_max_distance" not in params:
            dz = None
    else:
        dz = 4.0
    pts = [(-1.0, -1.0, -1.0) if dz is None or g[0][k] == -1 else (g[0][k], g[1][k], g[2][k] + dz)
           for k in range(rows * cols)]
else:
    if "-s" in argv:
        sxyz = [float(v) for v in argv[argv.index("-s") + 1:argv.index("-s") + 4]]
    else:
        sxyz = [24.0, 24.0, 32.0]
    arc = os.environ.get("FAKE_TRACE_ARC")
    if arc:
        cx, cy = (float(v) for v in arc.split(","))
        rad = math.hypot(sxyz[0] - cx, sxyz[1] - cy)
        a0 = math.atan2(sxyz[1] - cy, sxyz[0] - cx)
        turn = math.radians(float(os.environ.get("FAKE_TRACE_TURN_DEG", "0")))
        if turn:
            # the grid turned in plane: +z runs along grid direction turn (from +row toward +col), not the rows
            along = lambda r, c: (r - 4) * math.cos(turn) + (c - 4) * math.sin(turn)
            across = lambda r, c: -(r - 4) * math.sin(turn) + (c - 4) * math.cos(turn)
        else:
            along, across = (lambda r, c: r - 4), (lambda r, c: c - 4)
        pts = [(cx + rad * math.cos(a0 + 4 * across(r, c) / rad), cy + rad * math.sin(a0 + 4 * across(r, c) / rad),
                sxyz[2] + 4 * along(r, c)) for r in range(rows) for c in range(cols)]
    else:
        pts = [(8.0 + 4 * c, 8.0 + 4 * r, sxyz[2]) for r in range(rows) for c in range(cols)]
def save(stop_reason, max_gen):
    seg.mkdir(parents=True, exist_ok=True)
    for k, a in enumerate("xyz"):
        vc3d_io.write_tiff(seg / (a + ".tif"), vc3d_io.Raster(rows, cols, "f32",
                                                             array.array("f", [p[k] for p in pts])))
    meta = {"scale": [0.25, 0.25], "format": "tifxyz", "type": "seg", "uuid": name or seg.name,
            "source": "vc_grow_seg_from_seed", "vc_gsfs_mode": mode, "area_vx2": 1024.0, "area_cm2": 1024.0 * 7.8e-7,
            "max_gen": max_gen, "elapsed_time_s": round(area / (per_day * 1e6 / 86400), 3) if per_day else 0.0}
    if stop_reason:
        meta["stop_reason"] = stop_reason
    (seg / "meta.json").write_text(json.dumps(meta))
    if os.environ.get("FAKE_TRACE_GENERATIONS") == "1":
        # villa's generations channel (uint16): the ring around the grid's center a vertex was added in, and on a
        # resume the source's channel unchanged, so a resume adds no new growth
        src = Path(opt("--resume")) / "generations.tif" if opt("--resume") else None
        if src is not None and src.is_file():
            gl = vc3d_io.read_tiff(src).data
        else:
            gl = array.array("H", [max(abs(r - 4), abs(c - 4)) + 1 for r in range(rows) for c in range(cols)])
        vc3d_io.write_tiff(seg / "generations.tif", vc3d_io.Raster(rows, cols, "u16", array.array("H", gl)))
if hang:
    if params.get("snapshot-interval"):
        save("running", gens)
        print(f"saved snapshot {seg}", flush=True)
        if os.environ.get("FAKE_TRACE_SAVE_FALLBACK") == "1":
            # villa's save on a filesystem without RENAME_EXCHANGE, stopped between its two steps: the next
            # snapshot is complete in .tmp_<thread>/NAME and the old folder is already removed
            import shutil
            final, seg = seg, seg.parent / ".tmp_140230" / seg.name
            gens += 1
            save("running", gens)
            shutil.rmtree(final)
            print(f"saving snapshot {final}", flush=True)
    if os.environ.get("FAKE_TRACE_SIGNAL"):
        # a signal from outside kit (the out-of-memory killer): the process dies with the snapshot on disk
        import signal as _signal
        os.kill(os.getpid(), int(os.environ["FAKE_TRACE_SIGNAL"]))
    time.sleep(hang)
if limited:
    save("time_limit", gens + 1)
else:
    save(None, int(params.get("generations") or 100))
print(f"wrote {seg}", flush=True)
if float(os.environ.get("FAKE_TRACE_HANG_AFTER", "0")):
    time.sleep(float(os.environ["FAKE_TRACE_HANG_AFTER"]))      # stopped after its final save (a slow exit)
'''

FLATTEN = PRELUDE + r'''
import shutil
if "--help" in argv:
    print("vc_flatten: -i TIFXYZ -o OUT [--iterations N] [--downsample N] [--lscm-only] [--no-scale]")
    sys.exit(0)
shutil.copytree(opt("-i"), opt("-o"))
meta = json.loads((Path(opt("-o")) / "meta.json").read_text())
meta.update(flattened=True, iterations=int(opt("--iterations", 10)))
(Path(opt("-o")) / "meta.json").write_text(json.dumps(meta))
print("flattened", flush=True)
'''

EXTEND = PRELUDE + r'''
import shutil
if "--help" in argv:
    print("vc_extend_edge: -i TIFXYZ -o OUT -n NORMALS [--sides LIST] [--cells N] [--rounds N] [--report FILE]")
    sys.exit(0)
shutil.copytree(opt("-i"), opt("-o"), dirs_exist_ok="--overwrite" in argv)
meta = json.loads((Path(opt("-o")) / "meta.json").read_text())
meta.update(extended=True, normals=opt("-n"))
(Path(opt("-o")) / "meta.json").write_text(json.dumps(meta))
sides, rounds = opt("--sides", "up,down,left,right").split(","), int(opt("--rounds", 8))
steps = [{"round": r, "side": d, "lines": 9, "added": 18, "steps_without_normal": 0}
         for r in range(1, rounds + 1) for d in sides]
report = {"added": sum(x["added"] for x in steps), "grid_before": [9, 9], "grid_after": [9, 9], "steps": steps}
if opt("--report"):
    Path(opt("--report")).write_text(json.dumps(report))
print("extended", flush=True)
'''

SELFCROSS = PRELUDE + r'''
if "--help" in argv:
    print("vc_tifxyz_selfcross: --surface TIFXYZ -o REPORT.json [--threads N]")
    sys.exit(0)
if os.environ.get("FAKE_SELFCROSS") == "crash":
    print("vc_tifxyz_selfcross: could not open the surface")
    sys.exit(1)
dirty = os.environ.get("FAKE_SELFCROSS") == "dirty"
Path(opt("-o")).write_text(json.dumps({"clean_of_transverse_self_intersection": not dirty,
                                        "census": [{"diagonal": 0, "transverse": 3 if dirty else 0},
                                                   {"diagonal": 1, "transverse": 0}]}))
'''

UMBILICUS = PRELUDE + r'''
if "--help" in argv:
    print("vc_gen_umbilicus: -i GRIDS -o OUT.json [--slices LIST] [--seed N] [--repeats N] [--threads N]")
    sys.exit(0)
grids = Path(opt("-i"))
zs = sorted(int(p.stem) for p in (grids / "xy").glob("*.grid"))
if opt("--slices"):
    zs = [z for z in zs if z in {int(v) for v in opt("--slices").split(",")}]
bad = {int(v) for v in os.environ.get("FAKE_UMB_OUTLIERS", "").split(",") if v}
pts = [{"x": 32.0 + 0.01 * z + (400.0 if z in bad else 0.0), "y": 30.0, "z": float(z)} for z in zs]
Path(opt("-o")).write_text(json.dumps({"control_points": pts}))
print(f"Refined umbilicus estimate for {len(pts)} slices", flush=True)
'''

SLEEP = PRELUDE + r'''
if "--help" in argv:
    print("vc_sleep SECONDS [--exit N] [--pid FILE]: a stand-in for a long VC3D run")
    sys.exit(0)
seconds = float(argv[0]) if argv and not argv[0].startswith("--") else 1.0
if opt("--stubborn-child"):
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import signal, time; "
                              "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"])
    Path(opt("--stubborn-child")).write_text(str(child.pid))
if opt("--pid"):
    Path(opt("--pid")).write_text(str(os.getpid()))
end, n = time.time() + seconds, 0
while time.time() < end:
    n += 1
    print(f"tick {n}", flush=True)
    time.sleep(0.1)
sys.exit(int(opt("--exit", 0)))
'''

APP = PRELUDE + r'''
import base64, shutil, signal, socket, tempfile, threading
if "--help" in argv:
    print("VC3D [--agent-bridge-name NAME]")
    sys.exit(0)
name = opt("--agent-bridge-name")
if name is None:
    sys.exit("could not connect to display")
folder = tempfile.mkdtemp(prefix="vcb", dir="/tmp" if os.path.isdir("/tmp") else None)
path = os.path.join(folder, "bridge.sock")
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path)
server.listen(8)
state = {"volume": None}
METHODS = {
    "ping": {"params": {"type": "object", "properties": {}}},
    "state.get": {"params": {"type": "object", "properties": {}}},
    "volume.open": {"params": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    "screenshot.capture": {"params": {"type": "object", "properties": {"target": {"type": "string"},
                                                                       "maxDim": {"type": "integer"}}},
                           "mcp": {"tool": "vc3d_screenshot"}},
    "segmentation.grow_patch_from_seed": {"params": {"type": "object", "properties": {"x": {"type": "number"}}}},
}

def handle(req):
    method, params = req.get("method"), req.get("params") or {}
    if method == "ping":
        return {"pong": True}
    if method == "rpc.describe":
        prefix = params.get("prefix", "")
        return {"methods": {k: v for k, v in METHODS.items() if k.startswith(prefix)}, "coverage": {"total": len(METHODS)}}
    if method == "state.get":
        return dict(state, platform=os.environ.get("QT_QPA_PLATFORM"), display=os.environ.get("DISPLAY"))
    if method == "volume.open":
        if not os.path.exists(params.get("path", "")):
            raise LookupError(-32004, "no such project", {"path": params.get("path")})
        state["volume"] = params["path"]
        return {"opened": params["path"]}
    if method == "segments.attach":
        loc = params.get("location", "")
        if not os.path.isdir(loc):
            raise LookupError(-32004, "no such surface", {"location": loc})
        state.setdefault("segments", []).append({"id": os.path.basename(loc.rstrip("/")), "path": loc})
        return {"attached": loc}
    if method == "segments.list":
        return {"segments": state.get("segments", [])}
    if method == "segments.activate":
        if params.get("segmentId") not in [g["id"] for g in state.get("segments", [])]:
            raise LookupError(-32004, "no such segment", None)
        state["active"] = params["segmentId"]
        return {"active": params["segmentId"]}
    if method == "screenshot.capture":
        png = vc3d_io.png_bytes(4, 6, bytes(range(0, 240, 10)))
        return {"format": "png", "width": 6, "height": 4, "base64": base64.b64encode(png).decode("ascii")}
    raise LookupError(-32601, "method not found: " + str(method), None)

def serve(conn):
    with conn:
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                req = json.loads(line)
                conn.sendall(b'{"jsonrpc": "2.0", "method": "event.log", "params": {"note": "before the reply"}}\n')
                try:
                    reply = {"jsonrpc": "2.0", "id": req["id"], "result": handle(req)}
                except LookupError as exc:
                    code, message, data = exc.args
                    err = {"code": code, "message": message}
                    if data:
                        err["data"] = data
                    reply = {"jsonrpc": "2.0", "id": req["id"], "error": err}
                conn.sendall((json.dumps(reply) + "\n").encode())

def stop(*_):
    shutil.rmtree(folder, ignore_errors=True)
    os._exit(0)

signal.signal(signal.SIGTERM, stop)
print("VC3D-AGENT-BRIDGE: listening name=" + name + " path=" + path, flush=True)
while True:
    conn, _ = server.accept()
    threading.Thread(target=serve, args=(conn,), daemon=True).start()
'''

FAKEZARR = f'''"""Zarr writer shared by the fakes and the tests (standard library; blosc through numcodecs)."""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
from vc3d_fakes import write_group  # noqa: F401
'''

FAKES = {vc3d.PROBE: RENDER, vc3d.TRACER: TRACER, "vc_flatten": FLATTEN, "vc_extend_edge": EXTEND,
         "vc_tifxyz_selfcross": SELFCROSS,
         "vc_sleep": SLEEP, "VC3D": APP, "vc_gen_umbilicus": UMBILICUS}


def make_bin(folder, names=None):
    """Write the fakes (all, or the given names) into folder; returns kit's Tools for it."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in FAKES.items():
        if names is None or name in names:
            exe = folder / name
            exe.write_text(text)
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    (folder / "fakezarr.py").write_text(FAKEZARR)
    return vc3d.Tools("VC_BIN", folder)


# ---------------------------------------------------------------- fixture writers

def _compress(raw, compressor):
    if not compressor or compressor == "none":
        return raw, None
    if compressor == "gzip":
        return gzip.compress(raw, 1), {"id": "gzip", "level": 1}
    if compressor == "zlib":
        return zlib.compress(raw, 1), {"id": "zlib", "level": 1}
    import numcodecs
    codec = numcodecs.get_codec({"id": compressor} if compressor != "blosc" else {"id": "blosc", "cname": "lz4"})
    return bytes(codec.encode(raw)), codec.get_config()


def write_array(path, shape, value, chunk, compressor=None, zarr_format=2, sep="/", fill=0, skip=None):
    """A uint8 zarr array holding value(z, y, x) (any number of axes: value gets one index per axis).
    zarr_format 3 writes zarr.json with a bytes codec and gzip; skip(chunk index) leaves a chunk out."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    dims = len(shape)
    if zarr_format == 2:
        _, spec = _compress(b"", compressor)
        (p / ".zarray").write_text(json.dumps({
            "zarr_format": 2, "shape": list(shape), "chunks": list(chunk), "dtype": "|u1", "compressor": spec,
            "fill_value": fill, "filters": None, "order": "C", "dimension_separator": sep}))
        key = lambda idx: sep.join(str(i) for i in idx)  # noqa: E731
    else:
        codecs = [{"name": "bytes", "configuration": {"endian": "little"}}]
        if compressor == "gzip":
            codecs.append({"name": "gzip", "configuration": {"level": 1}})
        (p / "zarr.json").write_text(json.dumps({
            "zarr_format": 3, "node_type": "array", "shape": list(shape), "data_type": "uint8",
            "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": list(chunk)}},
            "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
            "codecs": codecs, "fill_value": fill}))
        key = lambda idx: "c/" + "/".join(str(i) for i in idx)  # noqa: E731
    counts = [-(-s // c) for s, c in zip(shape, chunk)]

    def indices(ranges):
        if not ranges:
            yield ()
            return
        for i in ranges[0]:
            for rest in indices(ranges[1:]):
                yield (i,) + rest

    def chunk_bytes(idx):
        lo = [i * c for i, c in zip(idx, chunk)]
        raw = bytearray()
        for head in indices([range(l, l + c) for l, c in zip(lo[:-1], chunk[:-1])]):
            inside = all(v < s for v, s in zip(head, shape))
            row = range(lo[-1], lo[-1] + chunk[-1])
            raw += bytes(value(*head, x) if inside and x < shape[-1] else fill for x in row)
        return bytes(raw)

    for idx in indices([range(n) for n in counts]):
        if skip is not None and skip(idx):
            continue
        raw = chunk_bytes(idx)
        out = p / key(idx)
        out.parent.mkdir(parents=True, exist_ok=True)
        if zarr_format == 3:
            out.write_bytes(gzip.compress(raw, 1) if compressor == "gzip" else raw)
        else:
            out.write_bytes(_compress(raw, compressor)[0])
    assert dims == len(chunk)
    return p


def write_group(path, shape, value, chunk=(32, 32, 32), compressor=None, levels=1, zarr_format=2, binned="yx"):
    """An OME-Zarr group: level 0 holds value(z, y, x); level k samples level 0 every 2^k along the
    binned axes ("yx" like a rendered surface volume, whose levels keep every layer; "zyx" like a CT scan)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    names = []
    for k in range(levels):
        f = [2 ** k if a in binned else 1 for a in "zyx"]
        if k and any(s < g for s, g in zip(shape, f)):
            break
        sh = [max(1, s // g) for s, g in zip(shape, f)]
        ch = [min(c, s) for c, s in zip(chunk, sh)]
        write_array(p / str(k), sh, (lambda g: lambda z, y, x: value(z * g[0], y * g[1], x * g[2]))(f), ch, compressor,
                    zarr_format=zarr_format)
        names.append((str(k), f))
    ms = [{"version": "0.4", "name": "kit-test", "axes": [{"name": a, "type": "space"} for a in "zyx"],
           "datasets": [{"path": n, "coordinateTransformations": [{"type": "scale", "scale": [float(g) for g in f]}]}
                        for n, f in names]}]
    if zarr_format == 2:
        (p / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
        (p / ".zattrs").write_text(json.dumps({"multiscales": ms}))
    else:
        (p / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group",
                                                 "attributes": {"ome": {"version": "0.5", "multiscales": ms}}}))
    return p


def write_tifxyz(path, point, rows=9, cols=9, scale=0.25, meta=None):
    """A tifxyz surface: point(r, c) -> (x, y, z), or None for an invalid vertex (-1, -1, -1)."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    grids = [array.array("f") for _ in range(3)]
    for r in range(rows):
        for c in range(cols):
            v = point(r, c) or (-1.0, -1.0, -1.0)
            for k in range(3):
                grids[k].append(float(v[k]))
    for k, a in enumerate("xyz"):
        vc3d_io.write_tiff(p / f"{a}.tif", vc3d_io.Raster(rows, cols, "f32", grids[k]))
    m = {"scale": [scale, scale], "format": "tifxyz", "type": "seg", "uuid": p.name}
    m.update(meta or {})
    (p / "meta.json").write_text(json.dumps(m))
    return p


def plane(z, x0=8.0, step=4.0):
    """Vertices of a flat surface at height z, x0 + step * column by x0 + step * row; +N points to +z."""
    return lambda r, c: (x0 + step * c, x0 + step * r, z)


def sheet(z, y, x):
    """A papyrus sheet 3 voxels thick at z = 32 between neighboring windings at z = 20 and 44."""
    if abs(z - 32) <= 1:
        return 200
    if abs(z - 20) <= 1 or abs(z - 44) <= 1:
        return 150
    return 20


def ramp(z, y, x):
    """Brighter with depth: 4 + 3 z, so a layer's value tells which way the stack runs."""
    return min(255, 4 + 3 * z)


def textured_ramp(z, y, x):
    """The ramp less a small texture, (y + 2 x) % 3, on the deep side of z = 32: a stand-in ink map of a surface at
    z = 32 then varies across it (ink.py refuses a map of one value on the surface), and each layer is still brighter
    than the one before it."""
    return ramp(z, y, x) - ((y + 2 * x) % 3 if z > 32 else 0)


def write_layers(folder, layers, h, w):
    """Numbered u8 layer TIFFs from a list of byte strings."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for k, img in enumerate(layers):
        vc3d_io.write_tiff(folder / f"{k:02d}.tif", vc3d_io.Raster(h, w, "u8", bytes(img)))
    return folder


# An ink "model" for the command engine, standard library only: ink where the front half of the
# stack (toward layer 0) is brighter than the back half (the middle layer of an odd stack left out),
# so reading the layers reversed must change the answer, and a symmetric stack scores exactly 0.5.
INK_MODEL = f'''import array, math, sys
sys.path.insert(0, {str(ROOT)!r})
from kit import vc3d_io
layers, out, reverse = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
files = vc3d_io.layer_files(layers)
if reverse:
    files = files[::-1]
planes = [vc3d_io.read_tiff(f).data for f in files]
first = vc3d_io.read_tiff(files[0])
n, half = len(planes), len(planes) // 2
vals = array.array("f")
for i in range(first.h * first.w):
    front = sum(planes[k][i] for k in range(half)) / half
    back = sum(planes[k][i] for k in range(n - half, n)) / half
    vals.append(1.0 / (1.0 + math.exp(-(front - back) / 8.0)))
vc3d_io.write_tiff(out, vc3d_io.Raster(first.h, first.w, "f32", vals))
print("ink model wrote", out)
'''


def env_for(bin_dir, home, **extra):
    """An environment for kit tools: the fake bin first, the work home, nothing from a real VC3D. VC3D's remote
    cache is a folder of the test (VC3D.ini in VC3D_CONFIG_DIR), and the false-404 relay is off unless a test
    turns it on (KIT_VC3D_RELAY=1)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VC_", "KIT_", "FAKE_", "VC3D_"))}
    conf = Path(home).parent / "vc3d-config"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "VC3D.ini").write_text(f"[viewer]\nremote_cache_dir={Path(home).parent / 'remote_cache'}\n")
    env.update(VC_BIN=str(bin_dir), KIT_VC3D_HOME=str(home), KIT_VC3D_PROGRESS_SECONDS="0.3",
               PYTHONPATH=str(ROOT), VC3D_CONFIG_DIR=str(conf), KIT_VC3D_RELAY="0")
    env.update({k: str(v) for k, v in extra.items()})
    return env


class S3LikeServer:
    """A local HTTP server over a folder that answers like S3, false 404s included. A missing key gets 404 with
    <Code>NoSuchKey</Code>; the first `false` requests for each key get 404 with <Code>NoSuchBucket</Code>, and a
    key in `always_false` gets it every time (S3 sends such answers for keys it holds; kit/s3retry.py). Range
    and HEAD work. Use as a context manager; .url is the server's base URL and .hits counts requests per key."""

    def __init__(self, root, false=1, always_false=()):
        import collections
        import http.server
        import threading
        import urllib.parse
        self.root, self.false, self.always_false = Path(root), false, set(always_false)
        self.hits = collections.Counter()
        lock = threading.Lock()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _error(self, code, s3code, head):
                body = b"" if head else (f"<?xml version=\"1.0\"?><Error><Code>{s3code}</Code>"
                                         f"<Message>test</Message></Error>").encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _serve(self, head):
                key = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
                with lock:
                    n = outer.hits[key]
                    outer.hits[key] += 1
                if key in outer.always_false or n < outer.false:
                    return self._error(404, "NoSuchBucket", head)
                f = outer.root / key
                if not f.is_file():
                    return self._error(404, "NoSuchKey", head)
                data, status, extra = f.read_bytes(), 200, {}
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, _, b = rng[6:].partition("-")
                    a, b = int(a), min(int(b) if b else len(data) - 1, len(data) - 1)
                    extra["Content-Range"] = f"bytes {a}-{b}/{len(data)}"
                    data, status = data[a:b + 1], 206
                self.send_response(status)
                for k, v in extra.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if not head:
                    self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                self._serve(False)

            def do_HEAD(self):  # noqa: N802
                self._serve(True)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def no_proxy_opener():
    """urlopen that ignores proxy settings, for the local test servers."""
    import urllib.request
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open
