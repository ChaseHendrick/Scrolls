"""Tests for kit.vc3d_io: the standard-library readers and writers behind the agent tools.

Each reader is checked on data whose values are known, so a decoder that drops a row, swaps bytes or
misreads a type fails. Where tifffile or Pillow is installed it writes inputs too (tiles, predictors,
compression, BigTIFF) as a second opinion; those tests skip otherwise.
"""
import array
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes  # noqa: E402
from test_vc3d import VC3D_LAYER, strip_tiff  # noqa: E402

from kit import vc3d_io  # noqa: E402

HAVE_TIFFFILE = importlib.util.find_spec("tifffile") is not None and importlib.util.find_spec("numpy") is not None
HAVE_PIL = importlib.util.find_spec("PIL") is not None


def npy(shape, typecode, values, descr):
    """A version 1.0 .npy file, written by hand."""
    header = repr({"descr": descr, "fortran_order": False, "shape": tuple(shape)}).encode("latin1")
    pad = 64 - (10 + len(header) + 1) % 64
    header += b" " * pad + b"\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + array.array(typecode, values).tobytes()


def f32_tiff(values, w, order="<", predictor=1):
    """A single-strip, deflate-compressed float32 TIFF in either byte order, with predictor 1, 2 (horizontal
    differencing of the sample bits, as libtiff and tifffile apply it to floats) or 3 (libtiff's fpDiff)."""
    h = len(values) // w
    rows = []
    for y in range(h):
        row = values[y * w:(y + 1) * w]
        if predictor == 3:
            be = struct.pack(">%df" % w, *row)                       # byte planes, most significant first
            planes = b"".join(be[k::4] for k in range(4))
            rows.append(bytes([planes[0]] + [(planes[i] - planes[i - 1]) & 255 for i in range(1, len(planes))]))
        elif predictor == 2:
            bits = struct.unpack(order + "%dI" % w, struct.pack(order + "%df" % w, *row))
            rows.append(struct.pack(order + "%dI" % w, bits[0], *[(bits[i] - bits[i - 1]) & 0xFFFFFFFF
                                                                     for i in range(1, w)]))
        else:
            rows.append(struct.pack(order + "%df" % w, *row))
    data = zlib.compress(b"".join(rows))
    tags = [(256, 4, w), (257, 4, h), (258, 3, 32), (259, 3, 8), (262, 3, 1), (273, 4, None), (277, 3, 1),
            (278, 4, h), (279, 4, len(data)), (317, 3, predictor), (339, 3, 3)]
    start = 8 + 2 + 12 * len(tags) + 4
    ifd = struct.pack(order + "H", len(tags))
    for tag, typ, value in tags:
        value = start if value is None else value
        ifd += struct.pack(order + "HHI", tag, typ, 1) + (struct.pack(order + "HH", value, 0) if typ == 3
                                                           else struct.pack(order + "I", value))
    head = (b"II*\x00" if order == "<" else b"MM\x00*") + struct.pack(order + "I", 8)
    return head + ifd + struct.pack(order + "I", 0) + data


class TestTiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_each_kind(self):
        for kind, values in (("u8", bytes(range(12))), ("u16", array.array("H", [0, 1, 300, 65535] * 3)),
                             ("f32", array.array("f", [-1.5, 0.0, 2.25, 1e6] * 3))):
            path = self.d / f"{kind}.tif"
            vc3d_io.write_tiff(path, vc3d_io.Raster(3, 4, kind, values))
            got = vc3d_io.read_tiff(path)
            self.assertEqual((got.h, got.w, got.kind), (3, 4, kind))
            self.assertEqual(list(got.data), list(values))
            info = vc3d_io.tiff_info(path)
            self.assertEqual((info["height"], info["width"], info["kind"], info["compression"]), (3, 4, kind, "none"))

    def test_real_vc3d_layer_tiled_lzw_predictor(self):
        (self.d / "02.tif").write_bytes(VC3D_LAYER)
        r = vc3d_io.read_tiff(self.d / "02.tif")
        self.assertEqual((r.h, r.w, r.kind), (32, 32, "u8"))
        self.assertEqual(sum(1 for v in r.data if v == 116), 576)
        info = vc3d_io.tiff_info(self.d / "02.tif")
        self.assertEqual((info["compression"], info["tiled"], info["bigtiff"]), ("lzw", True, False))

    def test_deflate_and_errors(self):
        rows = [[(7 * y + x) % 256 for x in range(6)] for y in range(4)]
        raw = b"".join(bytes(r) for r in rows)
        (self.d / "z.tif").write_bytes(strip_tiff(rows, compression=8, payload=zlib.compress(raw)))
        self.assertEqual(bytes(vc3d_io.read_tiff(self.d / "z.tif").data), raw)
        (self.d / "j.tif").write_bytes(strip_tiff(rows, compression=7))
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.read_tiff(self.d / "j.tif")
        (self.d / "bad.tif").write_bytes(b"GIF89a" + bytes(20))
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.read_tiff(self.d / "bad.tif")
        (self.d / "cut.tif").write_bytes(strip_tiff(rows)[:12])
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.read_tiff(self.d / "cut.tif")

    def test_float_predictors_both_byte_orders(self):
        # the catalog's newer tifxyz grids are LZW with predictor 3, its older ones LZW with predictor 2 on float32
        vals = [((x * 37 + y * 101) % 997) * 1.25 - 300.5 + (x * y) / 7.0 for y in range(5) for x in range(23)]
        vals[4] = -1.0
        for order in ("<", ">"):
            for pred in (1, 2, 3):
                with self.subTest(order=order, predictor=pred):
                    path = self.d / f"f{pred}{'le' if order == '<' else 'be'}.tif"
                    path.write_bytes(f32_tiff(vals, 23, order, pred))
                    r = vc3d_io.read_tiff(path)
                    self.assertEqual((r.h, r.w, r.kind), (5, 23, "f32"))
                    self.assertEqual(list(r.floats()), list(array.array("f", vals)))
        # predictor 3 is for float samples only: the same file marked as unsigned integers is refused
        fmt_float = struct.pack("<HHIHH", 339, 3, 1, 3, 0)
        raw = f32_tiff([1.0, 2.0], 2, "<", 3)
        self.assertIn(fmt_float, raw)
        (self.d / "u32p3.tif").write_bytes(raw.replace(fmt_float, struct.pack("<HHIHH", 339, 3, 1, 1, 0)))
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.read_tiff(self.d / "u32p3.tif")

    @unittest.skipUnless(HAVE_PIL, "needs Pillow")
    def test_float_predictor_against_libtiff(self):
        try:
            from PIL import Image, features
        except ImportError:
            self.skipTest("needs Pillow")
        if not features.check("libtiff"):
            self.skipTest("Pillow without libtiff")
        vals = [((x * 13 + y * 7) % 101) * 3.5 + 2000.0 for y in range(37) for x in range(53)]
        img = Image.frombytes("F", (53, 37), array.array("f", vals).tobytes())
        path = self.d / "p3.tif"
        try:
            img.save(path, compression="tiff_lzw", tiffinfo={317: 3})
        except (OSError, ValueError) as exc:
            self.skipTest(f"Pillow cannot write this here: {exc}")
        order, tags = vc3d_io.tiff_tags(path.read_bytes(), 0)
        if tags.get(317, (1,))[0] != 3:
            self.skipTest("libtiff did not apply predictor 3")
        self.assertEqual(list(vc3d_io.read_tiff(path).floats()), list(array.array("f", vals)))

    @unittest.skipUnless(HAVE_TIFFFILE, "needs numpy and tifffile")
    def test_against_tifffile(self):
        import numpy as np
        import tifffile
        rng = np.random.default_rng(3)
        cases = [
            ("u16-tiled-deflate-pred", rng.integers(0, 65535, (37, 70), dtype=np.uint16),
             dict(tile=(16, 32), compression="zlib", predictor=True)),
            ("u8-strips-deflate", rng.integers(0, 255, (45, 19), dtype=np.uint8), dict(compression="zlib", rowsperstrip=7)),
            ("f32-big-endian", rng.normal(size=(9, 11)).astype(">f4"), dict(byteorder=">")),
            ("f32-bigtiff", rng.normal(size=(5, 8)).astype(np.float32), dict(bigtiff=True)),
            ("i16-packbits", rng.integers(-3000, 3000, (13, 17), dtype=np.int16), dict(compression="packbits")),
        ]
        for name, data, kw in cases:
            with self.subTest(name):
                if kw.get("compression") == "packbits" and importlib.util.find_spec("imagecodecs") is None:
                    self.skipTest("tifffile writes PackBits only with imagecodecs")
                path = self.d / f"{name}.tif"
                big = kw.pop("bigtiff", False)
                tifffile.imwrite(str(path), data, bigtiff=big, **kw)
                got = vc3d_io.read_tiff(path)
                self.assertEqual((got.h, got.w), data.shape)
                expect = data.astype(data.dtype.newbyteorder("=")).ravel().tolist()
                self.assertEqual(list(got.data), expect)
                self.assertEqual(vc3d_io.tiff_info(path)["bigtiff"], big)

    @unittest.skipUnless(HAVE_PIL, "needs Pillow")
    def test_against_pillow_lzw(self):
        from PIL import Image
        rows = [[(x * y + 3 * x) % 251 for x in range(53)] for y in range(29)]
        img = Image.frombytes("L", (53, 29), b"".join(bytes(r) for r in rows))
        path = self.d / "lzw.tif"
        try:
            img.save(path, compression="tiff_lzw")
        except (OSError, ValueError) as exc:
            self.skipTest(f"Pillow cannot write LZW here: {exc}")
        self.assertEqual(vc3d_io.tiff_info(path)["compression"], "lzw")
        self.assertEqual(bytes(vc3d_io.read_tiff(path).data), b"".join(bytes(r) for r in rows))


class TestFloatsAndNpy(unittest.TestCase):
    def test_as_floats_reads_bytes_as_samples(self):
        # array.array("f", some_bytes) would read 4 bytes per float: 1600 bytes would become 400 floats
        got = vc3d_io.as_floats(bytes([0, 1, 254, 255]))
        self.assertEqual(list(got), [0.0, 1.0, 254.0, 255.0])
        self.assertEqual(list(vc3d_io.as_floats(array.array("H", [7, 65535]))), [7.0, 65535.0])
        same = array.array("f", [0.5])
        self.assertIs(vc3d_io.as_floats(same), same)
        raster = vc3d_io.Raster(40, 40, "u8", bytes(1600))
        self.assertEqual(len(raster.floats()), 1600)
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.Raster(3, 3, "u8", bytes(8))

    def test_npy_2d_3d_and_big_endian(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.npy"
            p.write_bytes(npy((2, 3), "f", [0.0, 0.5, 1.0, 1.5, 2.0, 2.5], "<f4"))
            r = vc3d_io.read_npy(p)
            self.assertEqual((r.h, r.w, r.kind, list(r.data)), (2, 3, "f32", [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]))
            p.write_bytes(npy((3, 2, 2), "B", list(range(12)), "|u1"))
            self.assertEqual(list(vc3d_io.read_npy(p).data), [4, 5, 6, 7])
            self.assertEqual(list(vc3d_io.read_npy(p, 2).data), [8, 9, 10, 11])
            with self.assertRaises(vc3d_io.IOFormatError):
                vc3d_io.read_npy(p, 3)
            big = array.array("H", [1, 2, 3, 4])
            big.byteswap()
            header = repr({"descr": ">u2", "fortran_order": False, "shape": (2, 2)}).encode()
            header += b" " * (64 - (10 + len(header) + 1) % 64) + b"\n"
            p.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + big.tobytes())
            self.assertEqual(list(vc3d_io.read_npy(p).data), [1, 2, 3, 4])
            p.write_bytes(npy((2,), "B", [1, 2], "|u1"))
            with self.assertRaises(vc3d_io.IOFormatError):
                vc3d_io.read_npy(p)
            p.write_bytes(npy((2, 2), "B", [1, 2, 3, 4], "<c8"))
            with self.assertRaises(vc3d_io.IOFormatError):
                vc3d_io.read_npy(p)


class TestZarr(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def check_box(self, z, box, value):
        buf, shape = z.read(box)
        expect = []
        for a in range(*box[0]):
            for b in range(*box[1]):
                for c in range(*box[2]):
                    expect.append(value(a, b, c))
        self.assertEqual(shape, [b - a for a, b in box])
        self.assertEqual(list(buf), expect)

    def test_v2_compressors_separators_and_edges(self):
        value = lambda z, y, x: (5 * z + 3 * y + x) % 256  # noqa: E731
        for comp in (None, "gzip", "zlib"):
            for sep in ("/", "."):
                with self.subTest(compressor=comp, separator=sep):
                    path = vc3d_fakes.write_array(self.d / f"a-{comp}-{sep}.zarr", [7, 9, 11], value, [3, 4, 5], comp, sep=sep)
                    z = vc3d_io.ZArray(path)
                    self.assertEqual((z.version, z.shape, z.chunks, z.kind), (2, [7, 9, 11], [3, 4, 5], "u8"))
                    self.check_box(z, [(0, 7), (0, 9), (0, 11)], value)  # every chunk, partial edge chunks too
                    self.check_box(z, [(2, 5), (3, 8), (4, 11)], value)  # a box across chunk borders

    def test_missing_chunks_read_as_fill(self):
        path = vc3d_fakes.write_array(self.d / "holes.zarr", [4, 4], lambda y, x: 9, [2, 2], fill=0,
                                      skip=lambda idx: idx == (1, 1))
        buf, _ = vc3d_io.ZArray(path).read([(0, 4), (0, 4)])
        self.assertEqual(bytes(buf), bytes([9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 0, 0, 9, 9, 0, 0]))

    def test_v3_and_ome_groups(self):
        value = lambda z, y, x: (z * 40 + y * 7 + x) % 256  # noqa: E731
        group = vc3d_fakes.write_group(self.d / "v3.zarr", [3, 20, 24], value, chunk=(2, 8, 8), compressor="gzip",
                                       levels=2, zarr_format=3)
        self.assertEqual(vc3d_io.zarr_levels(group), [("0", [3, 20, 24]), ("1", [3, 10, 12])])
        z = vc3d_io.open_zarr(group)
        self.assertEqual((z.version, z.compressor), (3, {"id": "gzip"}))
        self.check_box(z, [(0, 3), (5, 17), (3, 24)], value)
        z1 = vc3d_io.open_zarr(group, 1)
        self.check_box(z1, [(0, 3), (0, 10), (0, 12)], lambda a, b, c: value(a, 2 * b, 2 * c))
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.open_zarr(group, 4)
        v2 = vc3d_fakes.write_group(self.d / "v2.zarr", [2, 8, 8], value, chunk=(2, 4, 4), levels=3)
        self.assertEqual([n for n, _ in vc3d_io.zarr_levels(v2)], ["0", "1", "2"])
        self.assertTrue(vc3d_io.is_zarr(v2) and vc3d_io.is_zarr(v2 / "0"))
        self.assertEqual(vc3d_io.zarr_levels(v2 / "0"), [("", [2, 8, 8])])
        self.assertFalse(vc3d_io.is_zarr(self.d))

    def test_sharded_and_unknown_codecs_are_refused(self):
        path = vc3d_fakes.write_array(self.d / "s.zarr", [2, 2], lambda y, x: 1, [2, 2], zarr_format=3)
        meta = json.loads((path / "zarr.json").read_text())
        meta["codecs"] = [{"name": "sharding_indexed", "configuration": {}}]
        (path / "zarr.json").write_text(json.dumps(meta))
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.ZArray(path)

    def test_blosc_without_numcodecs_says_what_to_do(self):
        path = vc3d_fakes.write_array(self.d / "b.zarr", [2, 2], lambda y, x: 1, [2, 2])
        meta = json.loads((path / ".zarray").read_text())
        meta["compressor"] = {"id": "blosc", "cname": "lz4", "clevel": 5, "shuffle": 1}
        (path / ".zarray").write_text(json.dumps(meta))
        with mock.patch.dict(sys.modules, {"numcodecs": None}), self.assertRaises(vc3d_io.IOFormatError) as err:
            vc3d_io.ZArray(path).read([(0, 2), (0, 2)])
        self.assertIn("numcodecs", str(err.exception))

    @unittest.skipUnless(importlib.util.find_spec("numcodecs"), "needs numcodecs")
    def test_blosc_with_numcodecs(self):
        value = lambda y, x: (y * 13 + x) % 256  # noqa: E731
        path = vc3d_fakes.write_array(self.d / "blosc.zarr", [9, 10], value, [4, 4], compressor="blosc")
        buf, _ = vc3d_io.ZArray(path).read([(0, 9), (0, 10)])
        self.assertEqual(list(buf), [value(y, x) for y in range(9) for x in range(10)])


class TestPngAndPreview(unittest.TestCase):
    def test_png_round_trip_grey_and_rgb(self):
        grey = bytes((3 * i) % 256 for i in range(5 * 7))
        self.assertEqual(vc3d_io.read_png_gray(vc3d_io.png_bytes(5, 7, grey)), (5, 7, 1, grey))
        rgb = bytes(i % 256 for i in range(4 * 3 * 3))
        self.assertEqual(vc3d_io.read_png_gray(vc3d_io.png_bytes(4, 3, rgb, channels=3)), (4, 3, 3, rgb))
        with self.assertRaises(vc3d_io.IOFormatError):
            vc3d_io.png_bytes(2, 2, bytes(3))

    def test_png_filters(self):
        """Sub, Up, Average and Paeth rows, as other encoders write them."""
        h, w = 4, 5
        pixels = [[(17 * r + 29 * c) % 256 for c in range(w)] for r in range(h)]
        raw, prev = b"", [0] * w
        for r, f in enumerate((1, 2, 3, 4)):
            line = pixels[r]
            out = []
            for i, x in enumerate(line):
                a = line[i - 1] if i else 0
                b, c = prev[i], prev[i - 1] if i else 0
                p = a + b - c
                pred = {1: a, 2: b, 3: (a + b) // 2,
                        4: a if abs(p - a) <= abs(p - b) and abs(p - a) <= abs(p - c) else b if abs(p - b) <= abs(p - c) else c}[f]
                out.append((x - pred) % 256)
            raw += bytes([f] + out)
            prev = line
        good = vc3d_io.png_bytes(h, w, bytes(h * w))
        ihdr_end = 8 + 8 + 13 + 4
        idat = zlib.compress(raw)
        chunk = struct.pack(">I", len(idat)) + b"IDAT" + idat + struct.pack(">I", zlib.crc32(b"IDAT" + idat) & 0xFFFFFFFF)
        blob = good[:ihdr_end] + chunk + good[-12:]
        self.assertEqual(vc3d_io.read_png_gray(blob)[3], b"".join(bytes(r) for r in pixels))

    def test_downsample(self):
        r = vc3d_io.Raster(4, 4, "u8", bytes(range(16)))
        self.assertEqual(list(vc3d_io.downsample(r, 2, "mean").data), [2.5, 4.5, 10.5, 12.5])
        self.assertEqual(list(vc3d_io.downsample(r, 2, "max").data), [5.0, 7.0, 13.0, 15.0])
        self.assertEqual(list(vc3d_io.downsample(r, 2, "nearest").data), [5.0, 7.0, 13.0, 15.0])
        same = vc3d_io.downsample(r, 1)
        self.assertEqual((same.kind, list(same.data)), ("f32", [float(v) for v in range(16)]))

    def test_to_u8(self):
        r = vc3d_io.Raster(1, 5, "f32", array.array("f", [0, 10, 20, 30, 40]))
        data, (lo, hi) = vc3d_io.to_u8(r, 0, 100)
        self.assertEqual(((lo, hi), list(data)), ((10, 40), [0, 0, 85, 170, 255]))
        self.assertEqual(list(vc3d_io.to_u8(r, 0, 100, invert=True)[0]), [0, 255, 170, 85, 0])
        self.assertEqual(list(vc3d_io.to_u8(r, lo=0, hi=80)[0]), [0, 32, 64, 96, 128])
        uniform = vc3d_io.Raster(2, 2, "u8", bytes([90] * 4))
        self.assertEqual(list(vc3d_io.to_u8(uniform)[0]), [128] * 4)  # mid grey, not black
        self.assertEqual(vc3d_io.to_u8(vc3d_io.Raster(1, 2, "u8", bytes(2)))[0], bytes(2))

    def test_stats_and_threshold(self):
        r = vc3d_io.Raster(2, 4, "u8", bytes([0, 0, 64, 128, 128, 200, 255, 255]))
        s = vc3d_io.stats(r, threshold=vc3d_io.prob_threshold("u8"))
        self.assertEqual((s["min"], s["max"], s["nonzero_fraction"], s["above_threshold_fraction"]), (0, 255, 0.75, 0.625))
        self.assertEqual(vc3d_io.stats(r, skip_zero=True)["min"], 64)
        self.assertEqual((vc3d_io.prob_threshold("f32"), vc3d_io.prob_threshold("u16")), (0.5, 32767.5))
        self.assertEqual(vc3d_io.percentile([1, 2, 3, 4], 50), 2.5)
        self.assertIsNone(vc3d_io.percentile([], 50))


class TestFolders(unittest.TestCase):
    def test_layer_files_numeric_order_and_tifxyz(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name in ("10.tif", "2.tif", "01.tif", "mask.tif", "3.png", "notes.txt"):
                (d / name).write_bytes(b"")
            self.assertEqual([f.name for f in vc3d_io.layer_files(d)], ["01.tif", "2.tif", "10.tif"])
            self.assertFalse(vc3d_io.is_tifxyz(d))
            surface = vc3d_fakes.write_tifxyz(d / "s.tifxyz", vc3d_fakes.plane(32), rows=3, cols=4)
            self.assertTrue(vc3d_io.is_tifxyz(surface))
            z = vc3d_io.read_tiff(surface / "z.tif")
            self.assertEqual((z.h, z.w, set(z.data)), (3, 4, {32.0}))


class TestVolcomp(unittest.TestCase):
    """The lossy volcomp copies are known by their URL prefix or, locally, by the codec in the zarr metadata."""

    def test_prefix_and_codecs(self):
        url = "https://dl.ash2txt.org/community-uploads/forrest/volcomp/PHerc0139/volumes/20250728140407.zarr"
        self.assertIn("community volcomp copy", vc3d_io.volcomp_source(url))
        self.assertIsNone(vc3d_io.volcomp_source(
            "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0139/volumes/20250728140407.zarr"))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            group = d / "copy.zarr"
            (group / "0").mkdir(parents=True)
            (group / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "group", "attributes": {}}))
            # as the published copies store level 0: volcomp inside sharding
            codecs = [{"name": "sharding_indexed", "configuration": {
                "chunk_shape": [128, 128, 128], "codecs": [{"name": "volcomp", "configuration": {"q": 8.0}}],
                "index_codecs": [{"name": "bytes", "configuration": {"endian": "little"}}]}}]
            (group / "0" / "zarr.json").write_text(json.dumps({"zarr_format": 3, "node_type": "array",
                                                               "shape": [8, 8, 8], "codecs": codecs}))
            reason = vc3d_io.volcomp_source(group)
            self.assertIn("(q 8)", reason)
            self.assertIn("quarter", reason)
            plain = d / "plain.zarr"
            plain.mkdir()
            (plain / ".zarray").write_text(json.dumps({"zarr_format": 2, "shape": [8, 8, 8],
                                                       "compressor": {"id": "blosc", "cname": "zstd"}}))
            self.assertIsNone(vc3d_io.volcomp_source(plain))
            (plain / ".zarray").write_text(json.dumps({"zarr_format": 2, "compressor": {"id": "volcomp", "q": 4}}))
            self.assertIn("(q 4)", vc3d_io.volcomp_source(plain))
            self.assertIsNone(vc3d_io.volcomp_source(d / "missing.zarr"))

if __name__ == "__main__":
    unittest.main()
