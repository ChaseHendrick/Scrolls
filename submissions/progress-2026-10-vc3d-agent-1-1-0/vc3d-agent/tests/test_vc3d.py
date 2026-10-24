"""Tests for kit.vc3d: tool lookup, the headless environment, the TIFF reader and the self-test.

The self-test runs here against a fake vc_render_tifxyz (a Python script), so it is checked without
VC3D. Set KIT_VC3D_SELFTEST=1 with VC_BIN or VC_ROOTFS to also run it against a real build.
"""
import base64
import contextlib
import importlib.util
import io
import json
import os
import stat
import struct
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, vc3d

# Layer 02 of `vc_render_tifxyz --num-slices 5 --tif-output` on the self-test fixture, villa
# e0bbb8b (2026-10-06): 32 x 32, tiled 32 x 16, LZW with the horizontal predictor. 576 pixels on
# the surface hold the ramp value at z = 32 (116); the rest is 0.
VC3D_LAYER = base64.b64decode(
    "SUkqAJoAAACAACBQOCQWDQeEQmFQs6QuHIyDw2HQqIQaJROERWCxeMQaNQSOR2CR+ByGRQKSQKTSeUgCVyKWy+OzGTx6IzWCzScQ"
    "OdTsAT2dySAggAAAB0gUFg0HhEFRkJgkJh0JhcIhsPikCiMHicVh8Xg0ZjUQhkfikcgsekUGkkCk0ni0hlkIlMDl8wmc1m03nE5n"
    "U7ncBAwAAAEDAAEAAAAgAAAAAQEDAAEAAAAgAAAAAgEDAAEAAAAIAAAAAwEDAAEAAAAFAAAABgEDAAEAAAABAAAAFQEDAAEAAAAB"
    "AAAAPQEDAAEAAAACAAAAQgEDAAEAAAAgAAAAQwEDAAEAAAAQAAAARAEEAAIAAAAwAQAARQEDAAIAAABMAEYAUwEDAAEAAAABAAAA"
    "AAAAAAgAAABUAAAA")

# A stand-in for vc_render_tifxyz that follows villa e0bbb8b's measured conventions on the self-test's
# flat plane (x = 16 + 4 * column, y = 16 + 4 * row, z = 32): output pixel p samples grid point
# (p + 0.5) / (scale * 4), samples within half a grid cell of the edge stay empty, layers sit
# (k - (n - 1) / 2) * slice-step voxels along +z, and the volume value is trilinear (exact on these
# linear ramps) truncated to a byte. The ramp is named in the volume's .zattrs.
# FAKE_MODE: "good"; "flat" returns one value everywhere (a broken sampler); "old" lacks
# --flip-normals like the published container; "nearest" samples the nearest voxel; "corner" maps
# pixel p to grid point p / (scale * 4).
FAKE_RENDER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, math, os, struct, sys
    from pathlib import Path
    mode = os.environ.get("FAKE_MODE", "good")
    argv = sys.argv[1:]
    if "--help" in argv:
        print("--volume  --segmentation  --num-slices  --tif-output")
        if mode != "old":
            print("--flip-normals  Negate surface normals")
        sys.exit(0)
    if mode == "old" and "--flip-normals" in argv:
        sys.exit("unrecognised option '--flip-normals'")
    opt = lambda name, default: argv[argv.index(name) + 1] if name in argv else default
    n, step, scale = int(opt("--num-slices", 1)), float(opt("--slice-step", 1)), float(opt("--scale", 1))
    attrs = json.loads((Path(opt("--volume", "")) / ".zattrs").read_text())
    ramp = attrs["multiscales"][0]["name"]
    value = {"kit-vc3d-selftest": lambda z, y, x: 20 + 3 * z,
             "kit-vc3d-steep-z": lambda z, y, x: max(0, min(255, 8 * (z - 16))),
             "kit-vc3d-ramp-x": lambda z, y, x: min(255, 10 + 4 * x),
             "kit-vc3d-ramp-y": lambda z, y, x: min(255, 10 + 4 * y)}[ramp]
    out = Path(opt("--tif-output", ""))
    out.mkdir(parents=True)
    sign = -1 if "--flip-normals" in argv else 1
    size = int(32 * scale)
    shift = 0.0 if mode == "corner" else 0.5
    def at(p):
        u = (p + shift) / (scale * 4)
        return (16 + 4 * u) if 0.5 <= u <= 6.5 else None
    for k in range(n):
        z = 32 + sign * (k - (n - 1) / 2) * step
        img = bytearray(size * size)
        for r in range(size):
            for c in range(size):
                y, x = at(r), at(c)
                if x is None or y is None:
                    continue
                if mode == "nearest":
                    z_, y, x = math.floor(z + 0.5), math.floor(y + 0.5), math.floor(x + 0.5)
                else:
                    z_ = z
                img[r * size + c] = 116 if mode == "flat" else int(value(z_, y, x))
        tags = [(256, size), (257, size), (258, 8), (259, 1), (262, 1), (273, 8 + 2 + 12 * 8 + 4), (278, size), (279, len(img))]
        ifd = struct.pack("<H", len(tags)) + b"".join(struct.pack("<HHII", t, 4, 1, v) for t, v in tags)
        (out / f"{k:02d}.tif").write_bytes(b"II*\\x00" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + bytes(img))
''')


# A stand-in for vc_grow_seg_from_seed: a 5 x 5 tifxyz around the seed, vertices 20 voxels apart, on a plane through
# the seed. FAKE_TRACE picks the plane's slope:
#   "follow": from the normal grids (the xz grid through the seed's y and the yz grid through its x, first and last
#             point of each GridStore polyline); without grids the seed quad's plane z = seed z exactly (villa e0bbb8b
#             with default weights reads nothing from the volume);
#   "ignore": never reads the grids (a tracer whose grids do nothing): always the seed quad's plane;
#   "volume": from the bright voxels of the volume, grids ignored (a tracer that follows a surface prediction only);
#   "both":   from the grids when it has them, from the volume when it has none.
# FAKE_NOGROW names a --segment-name for which it exits 0 and writes nothing.
FAKE_TRACER = textwrap.dedent(f'''\
    #!{sys.executable}
    import json, os, struct, sys
    from pathlib import Path
    sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
    from kit import vc3d
    mode = os.environ.get("FAKE_TRACE", "follow")
    argv = sys.argv[1:]
    opt = lambda name: argv[argv.index(name) + 1]
    sx, sy, sz = (float(v) for v in argv[argv.index("-s") + 1:argv.index("-s") + 4])
    grids = json.loads(Path(opt("-p")).read_text()).get("normal_grid_path")
    if opt("--segment-name") == os.environ.get("FAKE_NOGROW"):
        sys.exit(0)
    def ends(path):
        raw = Path(path).read_bytes()
        paths_at = struct.unpack(">I", raw[40:44])[0]
        u, v, n = struct.unpack(">iiI", raw[paths_at:paths_at + 12])
        steps = struct.unpack(f">{{n}}b", raw[paths_at + 12:paths_at + 12 + n])
        return (u, v), (u + sum(steps[0::2]), v + sum(steps[1::2]))
    vol = Path(opt("-v")) / "0"
    chunk, size = (json.loads((vol / ".zarray").read_text())[k][0] for k in ("chunks", "shape"))
    chunks = dict()
    def voxel(z, y, x):
        key = "/".join(str(c // chunk) for c in (z, y, x))
        if key not in chunks:
            chunks[key] = (vol / key).read_bytes()
        return chunks[key][((z % chunk) * chunk + y % chunk) * chunk + x % chunk]
    def bright_z(x, y):
        # mean z of the bright voxels in the column at (x, y)
        zs = [z for z in range(size) if voxel(z, y, x)]
        return sum(zs) / len(zs)
    dzdx = dzdy = 0.0
    if grids and mode in ("follow", "both"):
        (x0, z0), (x1, z1) = ends(Path(grids) / "xz" / f"{{int(sy):06d}}.grid")
        (y0, w0), (y1, w1) = ends(Path(grids) / "yz" / f"{{int(sx):06d}}.grid")
        dzdx, dzdy = (z1 - z0) / (x1 - x0), (w1 - w0) / (y1 - y0)
    elif mode == "volume" or (mode == "both" and not grids):
        x, y = int(sx), int(sy)
        dzdx, dzdy = (bright_z(x + 20, y) - bright_z(x, y)) / 20, (bright_z(x, y + 20) - bright_z(x, y)) / 20
    rows = [[(sx + 20 * c, sy + 20 * r, sz + 20 * (dzdx * c + dzdy * r)) for c in range(-2, 3)] for r in range(-2, 3)]
    out = Path(opt("-t"))
    out.mkdir(parents=True)
    for k, a in enumerate("xyz"):
        vc3d.write_tiff_f32(out / f"{{a}}.tif", [[p[k] for p in row] for row in rows])
    (out / "meta.json").write_text(json.dumps({{"format": "tifxyz", "type": "seg", "uuid": out.name, "scale": [0.05, 0.05]}}))
''')


def strip_tiff(rows, compression=1, payload=None):
    """An 8-bit single-strip TIFF; payload overrides the (already compressed) strip bytes."""
    h, w = len(rows), len(rows[0])
    data = payload if payload is not None else b"".join(bytes(r) for r in rows)
    tags = [(256, 4, w), (257, 4, h), (258, 3, 8), (259, 3, compression), (262, 3, 1),
            (273, 4, 8 + 2 + 12 * 8 + 4), (278, 4, h), (279, 4, len(data))]
    ifd = struct.pack("<H", len(tags))
    for tag, typ, value in tags:
        ifd += struct.pack("<HHI", tag, typ, 1) + (struct.pack("<HH", value, 0) if typ == 3 else struct.pack("<I", value))
    return b"II*\x00" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + data


def fake_bin(d, tracer=None):
    """A bin folder with the fake renderer and, when tracer is given, that script as the tracer."""
    Path(d).mkdir(parents=True, exist_ok=True)
    exe = Path(d) / vc3d.PROBE
    exe.write_text(FAKE_RENDER)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    if tracer:
        (Path(d) / vc3d.TRACER).write_text(tracer)
        (Path(d) / vc3d.TRACER).chmod(0o755)
    return vc3d.Tools("VC_BIN", d)


class TestLookup(unittest.TestCase):
    def test_order_rootfs_then_bin_then_path(self):
        with tempfile.TemporaryDirectory() as d:
            fake_bin(d)
            env = {"VC_ROOTFS": "/r", "VC_BIN": "/b", "PATH": d}
            self.assertEqual(vc3d.find_tools(env).kind, "VC_ROOTFS")
            self.assertEqual(vc3d.find_tools({"VC_BIN": "/b", "PATH": d}).bindir, Path("/b"))
            found = vc3d.find_tools({"PATH": d})
            self.assertEqual((found.kind, found.bindir), ("PATH", Path(d)))
            with mock.patch.object(vc3d, "MAC_BIN", Path(d) / "absent"):
                self.assertIsNone(vc3d.find_tools({"PATH": str(Path(d) / "empty")}))

    def test_rootfs_runs_through_its_own_loader(self):
        tools = vc3d.Tools("VC_ROOTFS", "/r/usr/local/bin", rootfs="/r")
        with mock.patch.object(vc3d.platform, "machine", return_value="x86_64"):
            argv = tools.argv(vc3d.PROBE, "--scale", 1)
        self.assertEqual(argv[0], "/r/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2")
        self.assertEqual(argv[1], "--library-path")
        self.assertIn("/r/usr/lib/x86_64-linux-gnu", argv[2].split(":"))
        self.assertEqual(argv[3:], ["/r/usr/local/bin/vc_render_tifxyz", "--scale", "1"])
        loader, libs = vc3d.rootfs_loader("/r", "aarch64")
        self.assertEqual(str(loader), "/r/usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1")
        self.assertEqual(vc3d.Tools("VC_BIN", "/b").argv("x", Path("/p")), ["/b/x", "/p"])


class TestEnvironment(unittest.TestCase):
    def test_cpu_max(self):
        self.assertIsNone(vc3d.parse_cpu_max("max 100000\n"))
        self.assertEqual(vc3d.parse_cpu_max("400000 100000"), 4)
        self.assertEqual(vc3d.parse_cpu_max("150000 100000"), 2)
        self.assertGreaterEqual(vc3d.cpu_limit(), 1)

    def test_headless_env(self):
        base = {"DISPLAY": ":0", "OMP_NUM_THREADS": "6"}
        env = vc3d.headless_env(base)
        self.assertEqual(base, {"DISPLAY": ":0", "OMP_NUM_THREADS": "6"})
        self.assertEqual((env["QT_QPA_PLATFORM"], env["OMP_NUM_THREADS"], env["OPENBLAS_NUM_THREADS"]),
                         ("offscreen", "6", "1"))
        self.assertEqual(vc3d.headless_env(dict(base, VC_THREADS="3"))["OMP_NUM_THREADS"], "3")
        self.assertEqual(vc3d.headless_env(base, threads=2)["OMP_NUM_THREADS"], "2")
        self.assertEqual(vc3d.headless_env({"OPENBLAS_NUM_THREADS": "4"})["OPENBLAS_NUM_THREADS"], "4")

    def test_cli_env_and_missing_tools(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["vc3d", "env", "--threads", "2"]), 0)
        self.assertIn("export QT_QPA_PLATFORM=offscreen", out.getvalue())
        self.assertIn("export OMP_NUM_THREADS=2", out.getvalue())
        with mock.patch.object(vc3d, "find_tools", return_value=None), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["vc3d", "which"]), 2)


class TestTiff(unittest.TestCase):
    def test_reads_real_vc3d_output(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "02.tif").write_bytes(VC3D_LAYER)
            h, w, data = vc3d.read_tiff_u8(Path(d) / "02.tif")
        self.assertEqual((h, w), (32, 32))
        self.assertEqual(sorted(set(data)), [0, 116])
        self.assertEqual(sum(1 for v in data if v), 576)

    def test_strip_layouts_and_packbits(self):
        rows = [[(3 * y + x) % 256 for x in range(5)] for y in range(3)]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "0.tif").write_bytes(strip_tiff(rows))
            (Path(d) / "1.tif").write_bytes(strip_tiff(rows))
            shape, data = vc3d.read_layers(d)
            self.assertEqual(shape, (2, 3, 5))
            self.assertEqual(data[:15], b"".join(bytes(r) for r in rows))
            packed = bytes.fromhex("FEAA0280002AFDAA0380002A22F7AA")  # the TIFF 6.0 PackBits example
            (Path(d) / "p.tif").write_bytes(strip_tiff([[0] * 24], compression=32773, payload=packed))
            self.assertEqual(vc3d.read_tiff_u8(Path(d) / "p.tif")[2].hex(),
                             "aaaaaa80002aaaaaaaaa80002a22" + "aa" * 10)
            (Path(d) / "x.tif").write_bytes(strip_tiff(rows, compression=7))
            with self.assertRaises(ValueError):
                vc3d.read_tiff_u8(Path(d) / "x.tif")

    def test_fixture_files(self):
        with tempfile.TemporaryDirectory() as d:
            vol = vc3d.write_zarr_u8(Path(d) / "v.zarr", [4, 4, 4], 2, lambda z: 10 + z)
            meta = json.loads((vol / "0" / ".zarray").read_text())
            self.assertEqual((meta["shape"], meta["chunks"], meta["compressor"]), ([4, 4, 4], [2, 2, 2], None))
            self.assertEqual((vol / "0/1/0/1").read_bytes(), bytes([12]) * 4 + bytes([13]) * 4)
            vol = vc3d.write_zarr_u8(Path(d) / "w.zarr", [4, 4, 4], 2,
                                     lambda z, y: bytes(16 * z + 4 * y + x for x in range(4)), axis="row")
            self.assertEqual(list((vol / "0/1/0/1").read_bytes()), [34, 35, 38, 39, 50, 51, 54, 55])
            # a shape that is not a whole number of chunks: the last chunk along x is padded with zeros
            vol = vc3d.write_zarr_u8(Path(d) / "p.zarr", [2, 2, 3], 2,
                                     lambda z, y: bytes(1 + 16 * z + 4 * y + x for x in range(3)), axis="row")
            self.assertEqual(list((vol / "0/0/0/1").read_bytes()), [3, 0, 7, 0, 19, 0, 23, 0])
            seg = vc3d.write_plane(Path(d) / "plane")
            raw = (seg / "z.tif").read_bytes()
            n = vc3d.PLANE_N
            self.assertEqual(struct.unpack(f"<{n * n}f", raw[-4 * n * n:]), (float(vc3d.PLANE_Z),) * n * n)


class TestSelftest(unittest.TestCase):
    def test_order(self):
        up = [vc3d.ramp(vc3d.PLANE_Z + k - 2) for k in range(5)]
        self.assertEqual(vc3d.read_order(up), "+N")
        self.assertEqual(vc3d.read_order(up[::-1]), "-N")
        self.assertIsNone(vc3d.read_order([116] * 5))
        self.assertIsNone(vc3d.read_order(up[:4] + [None]))
        self.assertEqual(vc3d.reverse_layers((2, 1, 2), b"abcd"), b"cdab")

    def run_fake(self, mode, tracer=None, trace="follow", nogrow=""):
        env = {"FAKE_MODE": mode, "FAKE_TRACE": trace, "FAKE_NOGROW": nogrow}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env):
            tools = fake_bin(Path(d), tracer=tracer)
            return vc3d.selftest(tools, Path(d) / "work", timeout=60)

    def test_good_binary_passes(self):
        report = self.run_fake("good")
        self.assertEqual(report["verdict"], "PASS", report)
        self.assertEqual((report["flip_normals"], report["default_order"]), ("supported", "+N"))
        self.assertEqual([c["check"] for c in report["checks"]],
                         ["render_starts", "render_default", "render_flip_normals", "flip_reverses",
                          "flip_equals_reversed_stack", "render_trilinear", "render_registration"])
        conv = report["conventions"]
        self.assertEqual((conv["sampling"], conv["pixel_origin"], conv["edge_loss_cells"]), ("trilinear", 0.5, 0.5))
        self.assertIn("pixel centers", vc3d.format_report(report))

    def test_nearest_sampling_fails(self):
        report = self.run_fake("nearest")
        self.assertEqual(report["verdict"], "FAIL")
        check = next(c for c in report["checks"] if c["check"] == "render_trilinear")
        self.assertFalse(check["pass"])
        self.assertEqual(report["conventions"]["sampling"], "nearest")

    def test_corner_registration_is_reported(self):
        report = self.run_fake("corner")
        self.assertEqual(report["conventions"]["pixel_origin"], 0.0, report)
        self.assertIn("pixel corners", vc3d.format_report(report))

    def test_convention_readers(self):
        zs = [vc3d.PLANE_Z + (k - 1.5) * 0.5 for k in range(4)]
        self.assertEqual(vc3d.read_sampling([vc3d.steep(z) for z in zs]), "trilinear")
        self.assertEqual(vc3d.read_sampling([vc3d.steep(z) for z in zs][::-1]), "trilinear")
        self.assertEqual(vc3d.read_sampling([120, 128, 128, 136]), "nearest")
        self.assertIsNone(vc3d.read_sampling([130] * 4))
        line = [0, 0] + [vc3d.xy_ramp(16.5 + c) for c in range(2, 26)] + [0] * 6
        got = vc3d.read_registration(line, 1)
        self.assertTrue(got["linear"])
        self.assertEqual((got["pixel_origin"], got["valid_pixels"]), (0.5, [2, 25]))
        self.assertEqual(got["edge_bracket"], [0.375, 0.625])
        bent = line[:10] + [v + 8 for v in line[10:26]] + line[26:]
        self.assertFalse(vc3d.read_registration(bent, 1)["linear"])
        self.assertIsNone(vc3d.read_registration([0] * 30 + [50], 1))

    def test_wrong_values_fail(self):
        report = self.run_fake("flat")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertFalse(next(c for c in report["checks"] if c["check"] == "render_default")["pass"])

    def test_old_binary_reports_missing_flag(self):
        report = self.run_fake("old")
        self.assertEqual((report["verdict"], report["flip_normals"]), ("PASS", "absent"))
        self.assertIn("cannot put layers in the team's order", vc3d.format_report(report))

    def test_failed_trace_fails(self):
        report = self.run_fake("good", tracer="#!/bin/sh\nexit 3\n")
        self.assertEqual(report["verdict"], "FAIL")
        self.assertIn("exit 3, no surface", report["checks"][-1]["detail"])

    def trace_check(self, report):
        check = report["checks"][-1]
        self.assertEqual(check["check"], "trace_follows_grids")
        return check

    def test_tracer_that_follows_grids_passes(self):
        report = self.run_fake("good", tracer=FAKE_TRACER)
        self.assertEqual(report["verdict"], "PASS", vc3d.format_report(report))
        check, trace = self.trace_check(report), report["trace"]
        self.assertTrue(check["pass"])
        self.assertNotIn("void", check)
        self.assertEqual((trace["verdict"], trace["grids"]["vertices"], trace["grids"]["share"]), ("PASS", 25, 1.0))
        self.assertEqual((trace["tilt"], trace["mirror_tilt"]), ([0.6, 0.3], [-0.6, -0.3]))
        control = trace["mirror_grids"]
        self.assertEqual((control["vertices"], control["share_on_mirror"]), (25, 1.0))   # it followed the mirror grids
        self.assertLess(control["share"], vc3d.TRACE_SHARE)
        self.assertLess(trace["no_grids"]["share"], vc3d.TRACE_SHARE)
        self.assertIn("so the grids put the grow on it and this check can fail", check["detail"])
        self.assertIn("without grids (reported, not scored): exit 0, 25 vertices", check["detail"])

    def test_tracer_that_follows_only_the_volume_is_void(self):
        # the grow lands on the sheet whatever grids it is given, so the check cannot show that it reads them
        report = self.run_fake("good", tracer=FAKE_TRACER, trace="volume")
        trace, check = report["trace"], self.trace_check(report)
        self.assertEqual((report["verdict"], trace["verdict"], check.get("void")), ("FAIL", "VOID", True))
        self.assertEqual((trace["grids"]["share"], trace["mirror_grids"]["share"]), (1.0, 1.0))
        self.assertIn("could have passed with grids the tracer ignores", check["detail"])

    def test_tracer_that_follows_the_volume_without_grids_passes(self):
        # a tracer that follows its grids, and the prediction when it has none: the no-grid run lands on the sheet,
        # which made the check VOID while that run was its control; the mirror grids still take the grow off it
        report = self.run_fake("good", tracer=FAKE_TRACER, trace="both")
        trace = report["trace"]
        self.assertEqual((report["verdict"], trace["verdict"]), ("PASS", "PASS"), vc3d.format_report(report))
        self.assertEqual((trace["no_grids"]["share"], trace["mirror_grids"]["share_on_mirror"]), (1.0, 1.0))
        self.assertLess(trace["mirror_grids"]["share"], vc3d.TRACE_SHARE)

    def test_tracer_that_ignores_grids_fails(self):
        # what the old check could not see: a tracer that grows the seed quad's plane whatever the grids say
        report = self.run_fake("good", tracer=FAKE_TRACER, trace="ignore")
        self.assertEqual(report["verdict"], "FAIL")
        check = self.trace_check(report)
        self.assertFalse(check["pass"])
        self.assertNotIn("void", check)
        self.assertEqual(report["trace"]["verdict"], "FAIL")
        self.assertIn("[FAIL] trace_follows_grids", vc3d.format_report(report))

    def test_check_that_cannot_fail_is_void(self):
        # the old fixture's flaw: a sheet in the seed quad's plane is its own mirror, so the control stays on it too
        with mock.patch.object(vc3d, "SHEET_TILT", (0.0, 0.0)):
            report = self.run_fake("good", tracer=FAKE_TRACER)
        self.assertEqual(report["verdict"], "FAIL")
        check = self.trace_check(report)
        self.assertEqual((check["pass"], check.get("void"), report["trace"]["verdict"]), (False, True, "VOID"))
        self.assertEqual(report["trace"]["mirror_grids"]["share"], 1.0)
        self.assertIn("[VOID] trace_follows_grids", vc3d.format_report(report))
        self.assertIn("cannot show that the grids put the grow on the sheet", check["detail"])

    def test_surface_left_in_work_is_not_scored(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FAKE_MODE": "good"}):
            work = Path(d) / "work"
            first = vc3d.selftest(fake_bin(Path(d) / "a", tracer=FAKE_TRACER), work, timeout=60)
            second = vc3d.selftest(fake_bin(Path(d) / "b", tracer="#!/bin/sh\nexit 0\n"), work, timeout=60)
        self.assertEqual((first["verdict"], second["verdict"]), ("PASS", "FAIL"))
        self.assertEqual(second["trace"]["grids"]["vertices"], 0)

    def test_control_that_grows_nothing_is_void(self):
        report = self.run_fake("good", tracer=FAKE_TRACER, nogrow="grown-mirror")
        self.assertEqual((report["verdict"], report["trace"]["verdict"]), ("FAIL", "VOID"))
        self.assertIn("(control): exit 0, no surface", self.trace_check(report)["detail"])


class TestTraceFixture(unittest.TestCase):
    def test_sheet(self):
        c = vc3d.SHEET_SEED
        self.assertEqual(vc3d.sheet_z(c, c), c)
        self.assertNotEqual(vc3d.sheet_z(c + 20, c), c)   # tilted out of the seed quad's plane z = c
        sx, sy = vc3d.SHEET_TILT
        n = (1 + sx * sx + sy * sy) ** 0.5
        self.assertAlmostEqual(vc3d.sheet_distance((c - 3 * sx / n, c - 3 * sy / n, c + 3 / n)), 3.0)
        self.assertEqual((vc3d.sheet_value(c, c, c), vc3d.sheet_value(c + 10, c, c)), (255, 0))
        self.assertEqual((vc3d.mirror_tilt(), vc3d.mirror_tilt((0.2, -0.5))), ((-sx, -sy), (-0.2, 0.5)))

    def test_sheet_rows_match_sheet_value(self):
        # sheet_row computes sheet_value only near the sheet; every voxel of its rows must still equal sheet_value
        size = vc3d.SHEET_SIZE
        for tilt in (vc3d.SHEET_TILT, vc3d.mirror_tilt(), (0.0, 0.0), (0.0, 0.5), (3.0, -0.2), (1e-6, 0.3)):
            with mock.patch.object(vc3d, "SHEET_TILT", tilt):
                for z in range(0, size, 7):
                    for y in range(0, size, 9):
                        row = vc3d.sheet_row(z, y)
                        self.assertEqual(row, bytes(vc3d.sheet_value(z, y, x) for x in range(size)), (tilt, z, y))
        lit = sum(vc3d.sheet_row(z, y).count(255) for z in range(size) for y in range(size))
        self.assertGreater(lit, 50000)    # the cube holds the sheet

    def test_grid_store_layout(self):
        line = [(0, 10), (100, 30), (127, 40)]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "000001.grid"
            vc3d.write_grid_store(path, [line, [(5, 5)]], 128, 100)
            raw = path.read_bytes()
            with self.assertRaises(ValueError):
                vc3d.write_grid_store(Path(d) / "far.grid", [[(0, 0), (128, 0)]], 256, 256)
        head = struct.unpack(">13I", raw[:52])
        self.assertEqual(head[:9], (0x56434753, 3, 0, 0, 128, 100, 64, 4, 1))   # 2 x 2 buckets, one path
        bucket_index = struct.unpack(">5I", raw[52:72])
        self.assertEqual(bucket_index, (0, 1, 2, 2, 2))   # the path's points lie in buckets 0 and 1 (top row)
        paths_at, meta_at = head[10], head[11]
        u, v, n = struct.unpack(">iiI", raw[paths_at:paths_at + 12])
        self.assertEqual(((u, v), n), ((0, 10), 4))
        self.assertEqual(struct.unpack(">4b", raw[paths_at + 12:paths_at + 16]), (100, 20, 27, 10))
        self.assertEqual(raw[meta_at:], b"{}")

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "needs numpy")
    @unittest.skipUnless((Path(vc3d.__file__).parent / "surfacepred.py").is_file(),
                         "a module of AutoPipeline, which reads grid stores, ships with AutoPipeline")
    def test_grid_store_reads_back(self):
        from kit import surfacepred
        line = [(3, 120), (60, 100), (127, 90)]
        with tempfile.TemporaryDirectory() as d:
            vc3d.write_grid_store(Path(d) / "g.grid", [line], 128, 128)
            head, lines = surfacepred.read_grid(Path(d) / "g.grid")
        self.assertEqual((head["bounds"], head["cell"], head["paths"]), ([0, 0, 128, 128], 64, 1))
        self.assertEqual([[tuple(int(a) for a in p) for p in got] for got in lines], [line])

    def test_sheet_grids_lie_on_the_sheet(self):
        with tempfile.TemporaryDirectory() as d:
            root = vc3d.write_sheet_grids(Path(d) / "grids")
            meta = json.loads((root / "metadata.json").read_text())
            self.assertEqual((meta["spiral-step"], meta["sparse-volume"]), (vc3d.TRACE_STEP, 1))
            for plane in ("xy", "xz", "yz"):
                self.assertEqual(len(list((root / plane).glob("*.grid"))), vc3d.SHEET_SIZE)
        seen = 0
        for plane, to3d in (("xy", lambda u, v, s: (u, v, s)), ("xz", lambda u, v, s: (u, s, v)),
                            ("yz", lambda u, v, s: (s, u, v))):
            for s in range(0, vc3d.SHEET_SIZE, 9):
                for line in vc3d.sheet_grid_lines(plane, s):
                    for u, v in line:
                        self.assertLessEqual(vc3d.sheet_distance(to3d(u, v, s)), 0.5, (plane, s, u, v))
                        seen += 1
        self.assertGreater(seen, 300)
        self.assertEqual(vc3d.sheet_grid_lines("xy", 70, (0.0, 0.0)), [])

    def test_trace_rule(self):
        c = vc3d.SHEET_SEED
        grid = [(c + 20 * i, c + 20 * j) for i in range(-2, 3) for j in range(-2, 3)]
        on = vc3d.trace_fit([(x, y, vc3d.sheet_z(x, y)) for x, y in grid])
        flat = vc3d.trace_fit([(x, y, c) for x, y in grid])
        seed_quad = vc3d.trace_fit([(c + 0.1 * i, c + 0.1 * j, c) for i in (0, 1) for j in (0, 1)])
        empty = vc3d.trace_fit([])
        mirror = [(x, y, vc3d.sheet_z(x, y, vc3d.mirror_tilt())) for x, y in grid]
        self.assertEqual((on["vertices"], on["share"], on["median"]), (25, 1.0, 0.0))
        self.assertLess(flat["share"], vc3d.TRACE_SHARE)
        self.assertEqual((vc3d.trace_fit(mirror)["share"], vc3d.trace_fit(mirror, vc3d.mirror_tilt())["share"]),
                         (0.12, 1.0))   # only the 3 vertices on the line where the two sheets cross
        self.assertEqual(vc3d.trace_verdict(0, on, 0, vc3d.trace_fit(mirror)), "PASS")
        self.assertEqual((seed_quad["share"], vc3d.trace_grew(seed_quad)), (1.0, False))
        self.assertEqual(vc3d.trace_verdict(0, on, 0, flat), "PASS")
        self.assertEqual(vc3d.trace_verdict(0, flat, 0, flat), "FAIL")
        self.assertEqual(vc3d.trace_verdict(1, on, 0, flat), "FAIL")
        self.assertEqual(vc3d.trace_verdict(0, seed_quad, 0, flat), "FAIL")
        self.assertEqual(vc3d.trace_verdict(0, on, 0, on), "VOID")
        self.assertEqual(vc3d.trace_verdict(0, on, 0, empty), "VOID")
        self.assertEqual(vc3d.trace_verdict(0, on, "timeout", flat), "VOID")


# A stand-in for an extracted AppImage (squashfs-root): AppRun picks the tool by the name it was started as and
# marks the environment, as villa's AppRun starts each tool through the AppImage's own loader; the tools in usr/bin
# print that mark, so a test sees whether a tool came through AppRun.
APPRUN = """#!/bin/sh
here=$(dirname "$(readlink -f "$0")")
FAKE_APPRUN=yes exec "$here/usr/bin/$(basename "$0")" "$@"
"""
APPTOOL = """#!/bin/sh
echo "$(basename "$0") apprun=${FAKE_APPRUN:-no} $*"
"""


def fake_squashfs(root, tools=("vc_render_tifxyz", "vc_grow_seg_from_seed", "VC3D")):
    root = Path(root)
    (root / "usr" / "bin").mkdir(parents=True)
    (root / "AppRun").write_text(APPRUN)
    (root / "AppRun").chmod(0o755)
    for name in tools:
        (root / "usr" / "bin" / name).write_text(APPTOOL)
        (root / "usr" / "bin" / name).chmod(0o755)
    (root / "usr" / "bin" / "qt.conf").write_text("[Paths]\n")      # not a program: no link
    return root


def fake_appimage(path, template, count):
    """A stand-in .AppImage: --appimage-extract copies template to ./squashfs-root and counts the extraction."""
    Path(path).write_text(f"""#!/bin/sh
[ "$1" = --appimage-extract ] || exit 3
echo x >> {count}
cp -R {template} squashfs-root
""")
    Path(path).chmod(0o755)
    return Path(path)


class TestAppImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.home = self.d / "kithome"

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, **kw):
        return {"KIT_HOME": str(self.home), "PATH": os.environ.get("PATH", ""), **kw}

    def run_tool(self, tools, name):
        import subprocess
        return subprocess.run(tools.argv(name, "a"), capture_output=True, text=True, check=True).stdout.strip()

    def test_extracted_folder_gets_apprun_links_in_kit_home(self):
        root = fake_squashfs(self.d / "squashfs-root")
        tools = vc3d.find_tools(self.env(VC_APPIMAGE=str(root)))
        self.assertEqual(tools.kind, "VC_APPIMAGE")
        self.assertTrue(tools.bindir.is_relative_to(self.home / "work" / "vc3d" / "appimage"), tools.bindir)
        self.assertEqual(sorted(p.name for p in tools.bindir.iterdir()), ["VC3D", "vc_grow_seg_from_seed",
                                                                          "vc_render_tifxyz"])
        self.assertEqual(os.readlink(tools.bindir / "vc_render_tifxyz"), str(root.resolve() / "AppRun"))
        self.assertTrue(tools.has("vc_render_tifxyz") and not tools.has("vc_flatten"))
        self.assertEqual(self.run_tool(tools, "vc_render_tifxyz"), "vc_render_tifxyz apprun=yes a")
        self.assertIn("AppRun", tools.describe())
        # the folder that holds squashfs-root works too, and a second lookup reuses the links
        again = vc3d.find_tools(self.env(VC_APPIMAGE=str(self.d)))
        self.assertEqual(again.bindir, tools.bindir)

    def test_an_appimage_file_is_extracted_once(self):
        template = fake_squashfs(self.d / "template")
        count = self.d / "count"
        image = fake_appimage(self.d / "VC3D-test-linux-x86_64.AppImage", template, count)
        env = self.env(VC_APPIMAGE=str(image))
        tools = vc3d.find_tools(env)
        self.assertEqual(self.run_tool(tools, "vc_grow_seg_from_seed"), "vc_grow_seg_from_seed apprun=yes a")
        self.assertTrue((tools.bindir.parent / "squashfs-root" / "AppRun").is_file())
        self.assertEqual(vc3d.find_tools(env).bindir, tools.bindir)
        self.assertEqual(count.read_text().count("x"), 1)
        self.assertEqual([p.name for p in tools.bindir.parent.iterdir() if p.name.startswith("extract-")], [])

    def test_vc_bin_inside_an_extracted_appimage_starts_through_apprun(self):
        root = fake_squashfs(self.d / "squashfs-root")
        # started directly, the real binaries crash (exit 139); kit routes VC_BIN and PATH through AppRun links
        for env in (self.env(VC_BIN=str(root / "usr" / "bin")), {"KIT_HOME": str(self.home),
                                                                  "PATH": str(root / "usr" / "bin")}):
            tools = vc3d.find_tools(env)
            self.assertNotEqual(tools.bindir, root / "usr" / "bin")
            self.assertEqual(self.run_tool(tools, "vc_render_tifxyz"), "vc_render_tifxyz apprun=yes a")
            self.assertIn("crash when started directly", tools.describe())
            self.assertIn("AppRun, by links", tools.describe())
            self.assertIn(f"VC_APPIMAGE={root}", tools.describe())
        # a plain build's bin folder is left as it is
        plain = self.d / "build" / "bin"
        plain.mkdir(parents=True)
        self.assertEqual(vc3d.find_tools(self.env(VC_BIN=str(plain))).bindir, plain)

    def test_unusable_appimage_says_why(self):
        bad = self.d / "not-executable.AppImage"
        bad.write_text("")
        empty = self.d / "empty"
        empty.mkdir()
        for given, words in ((self.d / "absent.AppImage", "does not exist"), (bad, "chmod +x"),
                             (empty, "not an extracted AppImage")):
            with self.subTest(given=given), self.assertRaises(vc3d.SetupError) as err:
                vc3d.find_tools(self.env(VC_APPIMAGE=str(given)))
            self.assertIn(words, str(err.exception))
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"VC_APPIMAGE": str(empty)}, clear=True), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["vc3d", "which"]), 2)
        self.assertIn("not an extracted AppImage", err.getvalue())

    def test_env_needs_no_tools(self):
        # `eval "$(python -m kit vc3d env)"` must work before the tools are set up, and must not unpack anything
        for given in (self.d / "absent.AppImage", fake_squashfs(self.d / "squashfs-root")):
            out = io.StringIO()
            with self.subTest(given=given), mock.patch.dict(os.environ, self.env(VC_APPIMAGE=str(given)), clear=True), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["vc3d", "env"]), 0)
            self.assertIn("export QT_QPA_PLATFORM=offscreen", out.getvalue())
        self.assertFalse((self.home / "work").exists())

    def test_a_tool_gone_from_the_appimage_is_missing(self):
        # extracting another AppImage (villa's `stable` lacks two of the five) into the same folder leaves
        # links behind; neither the old set of tools nor a new lookup may count them
        root = fake_squashfs(self.d / "squashfs-root", tools=[t[0] for t in vc3d.PIPELINE_TOOLS])
        env = self.env(VC_APPIMAGE=str(root))
        tools = vc3d.find_tools(env)
        self.assertTrue(all(r["found"] for r in vc3d.pipeline_tools(tools)))
        for gone in ("vc_tifxyz_selfcross", "vc_gen_umbilicus"):
            (root / "usr" / "bin" / gone).unlink()
        self.assertFalse(tools.has("vc_tifxyz_selfcross"))
        self.assertTrue(tools.has("vc_render_tifxyz"))
        again = vc3d.find_tools(env)
        self.assertEqual(again.bindir, tools.bindir)
        self.assertEqual(sorted(p.name for p in again.bindir.iterdir()),
                         ["vc_flatten", "vc_grow_seg_from_seed", "vc_render_tifxyz"])
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["vc3d", "which"]), 1)
        self.assertIn("vc_tifxyz_selfcross: missing", out.getvalue())
        self.assertIn("3 of its 5 VC3D tools found", out.getvalue())


class TestPipelineTools(unittest.TestCase):
    @unittest.skipUnless((Path(vc3d.__file__).parent / "autopipe.py").is_file(),
                         "the VC3D agent package ships without AutoPipeline")
    def test_the_five_tools_autopipeline_runs(self):
        self.assertEqual([t[0] for t in vc3d.PIPELINE_TOOLS],
                         ["vc_gen_umbilicus", "vc_grow_seg_from_seed", "vc_tifxyz_selfcross", "vc_flatten",
                          "vc_render_tifxyz"])
        src = (Path(vc3d.__file__).parent / "autopipe.py").read_text()
        named = {t for t in ("vc_gen_umbilicus", "vc_grow_seg_from_seed", "vc_tifxyz_selfcross", "vc_flatten")
                 if t in src}
        self.assertEqual(len(named), 4)          # vc_render_tifxyz runs through the render tool

    def which(self, tools):
        out = io.StringIO()
        with mock.patch.object(vc3d, "find_tools", return_value=tools), contextlib.redirect_stdout(out):
            rc = cli.main(["vc3d", "which"])
        return rc, out.getvalue()

    def test_which_names_the_stage_of_a_missing_tool(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = self.which(fake_bin(d, tracer="#!/bin/sh\n"))
        self.assertEqual(rc, 1)
        self.assertIn("vc_render_tifxyz: found (render stage)", out)
        self.assertIn("vc_tifxyz_selfcross: missing: AutoPipeline's qa stage runs it", out)
        self.assertIn("vc_gen_umbilicus: missing: AutoPipeline's umbilicus stage runs it", out)
        self.assertIn("vc_flatten: missing: AutoPipeline's flatten stage runs it", out)
        self.assertEqual(out.count(vc3d.RELEASE), 3)
        self.assertIn("2 of its 5 VC3D tools found", out)

    def test_which_passes_with_all_five(self):
        with tempfile.TemporaryDirectory() as d:
            for name, _, _ in vc3d.PIPELINE_TOOLS:
                (Path(d) / name).write_text("#!/bin/sh\n")
            rc, out = self.which(vc3d.Tools("VC_BIN", d))
        self.assertEqual(rc, 0, out)
        self.assertIn("5 of its 5 VC3D tools found", out)
        self.assertNotIn("missing:", out)

    def test_selftest_reports_missing_tools_beside_its_verdict(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FAKE_MODE": "good"}):
            report = vc3d.selftest(fake_bin(Path(d)), Path(d) / "work", timeout=60)
        self.assertEqual(report["verdict"], "PASS")
        missing = [r["tool"] for r in report["pipeline_tools"] if not r["found"]]
        self.assertEqual(missing, ["vc_gen_umbilicus", "vc_grow_seg_from_seed", "vc_tifxyz_selfcross", "vc_flatten"])
        text = vc3d.format_report(report)
        self.assertIn("[MISSING] vc_tifxyz_selfcross: missing: AutoPipeline's qa stage runs it", text)
        self.assertIn("the verdict covers the checks above, not the missing tools", text)


@unittest.skipUnless(os.environ.get("KIT_VC3D_SELFTEST") == "1" and vc3d.find_tools(), "set KIT_VC3D_SELFTEST=1 and VC_BIN")
class TestRealBuild(unittest.TestCase):
    def test_selftest_passes(self):
        with tempfile.TemporaryDirectory() as d:
            report = vc3d.selftest(vc3d.find_tools(), d)
        self.assertEqual(report["verdict"], "PASS", vc3d.format_report(report))


if __name__ == "__main__":
    unittest.main()
