"""kit villafmt: community format checks and handoff files for villa and VC3D, on synthetic files.

TIFFs are written here byte by byte (classic and Big TIFF, both byte orders), so the header, project, ink map, seed
and label tests need only the standard library; the tifxyz pixel checks need numpy and skip without it. Every check
has a case that must fail: a missing meta field, a band of another size, NaN vertices, a stale bbox, a segments
folder with no segment, a transposed ink map or a crop of another aspect, a map of the wrong size under
--expect-size, a record for another segment, a seed with a 0 coordinate, label files of different sizes or named for
another segment. The aspect check's known blind spots (a same-aspect crop, another segment's map of the same aspect,
a turned map on a square canvas) are pinned as passing, so a change to them shows.

preds export (needs numpy): the written file is read back for villa's encoding (uint8, tiles, LZW compression 5, Big
TIFF magic 43) and pixels (villa's own formula, infer.py:791-812); its name is parsed with villa's direction rule and
matched with villa's folder-inference glob, both reimplemented below from villa main 8aa507c12; NaN and infinite maps,
an out-of-range scale, a model name villa would read as the other direction, a merged_ name, a size clash in preds/,
a wrong surface volume size and a wrong aspect under --register are refused. The LZW codec is checked on edge lengths
and against Pillow's libtiff encoder when Pillow is installed. No network."""

import contextlib
import fnmatch
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

from kit import villafmt as vf

FMT = {"f": (32, 3), "B": (8, 1), "H": (16, 1)}


def write_tiff(path, rows, cols, values, fmt="f", big=False, order="<", samples=1):
    """An uncompressed one-strip TIFF of rows x cols (x samples) values, written by hand."""
    bits, sf = FMT[fmt]
    data = struct.pack(f"{order}{len(values)}{fmt}", *values)
    tags = [(256, 4, cols), (257, 4, rows), (258, 3, bits), (259, 3, 1), (262, 3, 1), (273, 4, None),
            (277, 3, samples), (278, 4, rows), (279, 4, len(data)), (339, 3, sf)]
    if big:
        head = b"II" if order == "<" else b"MM"
        head += struct.pack(order + "HHHQ", 43, 8, 0, 16)
        esz, nsz = 20, 8
    else:
        head = (b"II" if order == "<" else b"MM") + struct.pack(order + "HI", 42, 8)
        esz, nsz = 12, 2
    ifd_len = nsz + len(tags) * esz + (8 if big else 4)
    data_off = len(head) + ifd_len
    ifd = struct.pack(order + ("Q" if big else "H"), len(tags))
    for tag, typ, val in tags:
        val = data_off if val is None else val
        if big:
            raw = struct.pack(order + ("H6x" if typ == 3 else "I4x"), val)
            ifd += struct.pack(order + "HHQ", tag, typ, 1) + raw
        else:
            raw = struct.pack(order + ("H2x" if typ == 3 else "I"), val)
            ifd += struct.pack(order + "HHI", tag, typ, 1) + raw
    ifd += b"\0" * (8 if big else 4)
    Path(path).write_bytes(head + ifd + data)


def write_png_header(path, w, h):
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", w, h,
                                                                                               8, 0, 0, 0, 0))


def make_segment(d, rows=6, cols=8, scale=0.5, meta=None, bands=None, nan_at=None, partial_at=None, zero_z_at=None):
    """A flat tifxyz: x = 10 + col / scale, y = 20 + row / scale, z = 30; -1 in the last column of row 0."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    xs, ys, zs = [], [], []
    for r in range(rows):
        for c in range(cols):
            x, y, z = 10 + c / scale, 20 + r / scale, 30.0
            if (r, c) == (0, cols - 1):
                x = y = z = -1.0
            if nan_at == (r, c):
                x = float("nan")
            if partial_at == (r, c):
                y = -1.0
            if zero_z_at == (r, c):
                z = 0.0
            xs.append(x)
            ys.append(y)
            zs.append(z)
    vals = {"x": xs, "y": ys, "z": zs}
    for b in "xyz":
        rr, cc = (bands or {}).get(b, (rows, cols))
        write_tiff(d / f"{b}.tif", rr, cc, (vals[b] + [0.0] * rr * cc)[:rr * cc])
    m = {"type": "seg", "uuid": "3f2c3c56-1b7e-4d7f-9a63-0d4f4c3b2a10", "format": "tifxyz",
         "scale": [scale, scale], "bbox": [[10.0, 20.0, 30.0], [10 + (cols - 1) / scale, 20 + (rows - 1) / scale,
                                                                 30.0]]}
    m.update(meta or {})
    m = {k: v for k, v in m.items() if v is not None}
    (d / "meta.json").write_text(json.dumps(m))
    return d


def make_zarr_volume(d):
    d = Path(d)
    (d / "0").mkdir(parents=True)
    (d / ".zgroup").write_text('{"zarr_format": 2}')
    (d / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4", "datasets": [{"path": "0"}]}]}))
    (d / "0" / ".zarray").write_text(json.dumps({"shape": [64, 64, 64], "chunks": [64, 64, 64], "dtype": "|u1",
                                                 "zarr_format": 2}))
    return d


def run(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = vf.main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None), err.getvalue()


class Tmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class TiffHeader(Tmp):
    def test_classic_big_and_byte_orders(self):
        for big in (False, True):
            for order in ("<", ">"):
                p = self.d / f"t{big}{order == '<'}.tif"
                write_tiff(p, 3, 5, [1.0] * 15, big=big, order=order)
                info = vf.tiff_info(p)
                self.assertEqual((info["width"], info["height"], info["dtype"], info["samples"], info["bigtiff"]),
                                 (5, 3, "float32", 1, big))

    def test_not_a_tiff(self):
        p = self.d / "x.tif"
        p.write_bytes(b"hello world, not a tiff")
        with self.assertRaises(vf.FormatError):
            vf.tiff_info(p)

    def test_image_size_png_and_tiff(self):
        write_png_header(self.d / "a.png", 40, 20)
        write_tiff(self.d / "a.tif", 20, 40, [0] * 800, fmt="B")
        self.assertEqual(vf.image_size(self.d / "a.png"), (40, 20, "png"))
        self.assertEqual(vf.image_size(self.d / "a.tif"), (40, 20, "tiff"))

    @unittest.skipUnless(np is not None, "needs numpy")
    def test_pixels_read_back(self):
        vals = [float(i) for i in range(12)]
        for big, order in ((False, "<"), (True, ">")):
            p = self.d / f"p{big}.tif"
            write_tiff(p, 3, 4, vals, big=big, order=order)
            a = vf.read_tiff_pixels(p)
            self.assertEqual(a.shape, (3, 4))
            self.assertEqual(a.ravel().tolist(), vals)


class Tifxyz(Tmp):
    def test_good_segment_passes(self):
        seg = make_segment(self.d / "seg")
        r = vf.check_tifxyz(seg)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual(r["grid"], [6, 8])
        self.assertEqual(r["scale"], [0.5, 0.5])
        if np is not None:
            self.assertEqual(r["pixels"], "checked")
            self.assertEqual(r["valid_vertices"], 47)
            self.assertEqual(r["warnings"], [])

    def test_meta_errors(self):
        cases = {"format": {"format": None}, "type": {"type": "vol"}, "uuid": {"uuid": None},
                 "scale": {"scale": [0.5]}}
        for rule, meta in cases.items():
            seg = make_segment(self.d / rule, meta=meta)
            r = vf.check_tifxyz(seg, pixels=False)
            self.assertFalse(r["ok"], rule)
            self.assertIn(rule, [e["rule"] for e in r["errors"]])
            self.assertTrue(all("source" in e for e in r["errors"]))

    def test_band_size_mismatch_and_missing_band(self):
        seg = make_segment(self.d / "s", bands={"z": (6, 7)})
        r = vf.check_tifxyz(seg, pixels=False)
        self.assertIn("shape", [e["rule"] for e in r["errors"]])
        (seg / "y.tif").unlink()
        r = vf.check_tifxyz(seg, pixels=False)
        self.assertIn("bands", [e["rule"] for e in r["errors"]])

    def test_catalog_placeholder(self):
        seg = make_segment(self.d / "ph", meta={"vc_open_data_lazy_placeholder": True, "tiff_dimensions": [8, 6]})
        for b in "xyz":
            (seg / f"{b}.tif").unlink()
        r = vf.check_tifxyz(seg)
        self.assertTrue(r["ok"], r["errors"])
        self.assertEqual((r["placeholder"], r["grid"]), (True, [6, 8]))
        meta = json.loads((seg / "meta.json").read_text())
        del meta["tiff_dimensions"]
        (seg / "meta.json").write_text(json.dumps(meta))
        self.assertFalse(vf.check_tifxyz(seg)["ok"])

    def test_uint8_band_warns(self):
        seg = make_segment(self.d / "s")
        write_tiff(seg / "z.tif", 6, 8, [30] * 48, fmt="B")
        r = vf.check_tifxyz(seg, pixels=False)
        self.assertTrue(r["ok"])
        self.assertIn("dtype", [w["rule"] for w in r["warnings"]])

    @unittest.skipUnless(np is not None, "needs numpy")
    def test_pixel_failures(self):
        r = vf.check_tifxyz(make_segment(self.d / "nan", nan_at=(2, 2)))
        self.assertIn("nan", [e["rule"] for e in r["errors"]])
        r = vf.check_tifxyz(make_segment(self.d / "partial", partial_at=(3, 3)))
        self.assertTrue(r["ok"])
        self.assertIn("partial_sentinel", [w["rule"] for w in r["warnings"]])
        self.assertEqual(r["valid_vertices"], 46)
        r = vf.check_tifxyz(make_segment(self.d / "zero", zero_z_at=(4, 4)))
        self.assertIn("z_nonpositive", [w["rule"] for w in r["warnings"]])
        self.assertEqual(r["valid_vertices"], 46)
        r = vf.check_tifxyz(make_segment(self.d / "bbox", meta={"bbox": [[0, 0, 0], [5, 5, 5]]}))
        self.assertIn("bbox", [w["rule"] for w in r["warnings"]])

    def test_cli_exit_codes(self):
        make_segment(self.d / "segs" / "a")
        make_segment(self.d / "segs" / "b", meta={"format": "obj"})
        code, rep, _ = run(["tifxyz", str(self.d / "segs"), "--no-pixels"])
        self.assertEqual(code, 1)
        self.assertEqual(rep["checked"], 2)
        self.assertEqual([Path(p).name for p in rep["failing"]], ["b"])
        code, rep, _ = run(["tifxyz", str(self.d / "segs" / "a")])
        self.assertEqual(code, 0)


class Project(Tmp):
    def setUp(self):
        super().setUp()
        self.vol = make_zarr_volume(self.d / "data" / "scan.zarr")
        make_segment(self.d / "run" / "traces" / "t1")
        make_segment(self.d / "run" / "traces" / "t2")
        self.umb = self.d / "run" / "umbilicus.json"
        self.umb.write_text(json.dumps({"control_points": [{"x": 30, "y": 30, "z": 0}, {"x": 31, "y": 30, "z": 60}],
                                        "metadata": {"voxelsize_um": 9.362, "volume": "scan"}}))
        grids = self.d / "data" / "grids"
        for s in ("xy", "xz", "yz"):
            (grids / s).mkdir(parents=True)
        (grids / "metadata.json").write_text("{}")
        self.grids = grids

    def test_write_and_check(self):
        out = self.d / "proj" / "w.volpkg.json"
        code, rep, err = run(["project", str(out), "--volume", str(self.vol), "--segments",
                              str(self.d / "run" / "traces"), "--normal-grids", str(self.grids), "--umbilicus",
                              str(self.umb), "--output-segments", str(self.d / "run" / "vc3d")])
        self.assertEqual(code, 0, (rep, err))
        doc = json.loads(out.read_text())
        self.assertEqual(sorted(doc), sorted(["name", "version", "volumes", "segments", "normal_grids",
                                              "lasagna_datasets", "output_segments", "umbilicus"]))
        self.assertEqual(doc["name"], "w")
        self.assertEqual(doc["volumes"], ["../data/scan.zarr"])
        self.assertEqual(doc["segments"], ["../run/traces"])
        self.assertEqual(rep["segments"][0]["found"], 2)
        self.assertEqual(rep["umbilicus"]["points"], 2)
        code, rep, _ = run(["project", "--check", str(out)])
        self.assertEqual(code, 0, rep)
        code, _, err = run(["project", str(out), "--volume", str(self.vol)])
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", err)

    def test_refusals(self):
        empty = self.d / "empty"
        empty.mkdir()
        out = self.d / "x.volpkg.json"
        code, rep, _ = run(["project", str(out), "--volume", str(self.vol), "--segments", str(empty)])
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())
        self.assertIn("segments", [e["rule"] for e in rep["errors"]])
        code, rep, _ = run(["project", str(out), "--volume", str(self.d / "run"), "--segments",
                            str(self.d / "run" / "traces")])
        self.assertEqual(code, 1)
        self.assertIn("volume", [e["rule"] for e in rep["errors"]])
        code, _, err = run(["project", str(self.d / "x.json"), "--volume", str(self.vol)])
        self.assertEqual(code, 2)
        self.assertIn("volpkg.json", err)
        bad = self.d / "bad_umb.json"
        bad.write_text(json.dumps({"control_points": [{"x": 1, "y": 2}]}))
        code, rep, _ = run(["project", str(out), "--volume", str(self.vol), "--umbilicus", str(bad)])
        self.assertEqual(code, 1)
        self.assertIn("umbilicus", [e["rule"] for e in rep["errors"]])

    def test_failing_segment_blocks(self):
        make_segment(self.d / "run" / "traces" / "t3", meta={"scale": None})
        out = self.d / "y.volpkg.json"
        code, rep, _ = run(["project", str(out), "--volume", str(self.vol), "--segments",
                            str(self.d / "run" / "traces")])
        self.assertEqual(code, 1)
        self.assertEqual([f["segment"] for f in rep["segments"][0]["failing"]], ["t3"])

    def test_remote_volume_tags(self):
        doc = vf.build_project(self.d / "r.volpkg.json", ["https://bucket.example/PHerc0139/volumes/a.zarr/"],
                               anonymous=True, voxel_um=2.399)
        self.assertEqual(doc["volumes"], [{"location": "https://bucket.example/PHerc0139/volumes/a.zarr/",
                                           "tags": [vf.ANON_TAG, "vc-open-data-voxel-size-um:2.399"]}])
        rep = vf.check_project(doc, self.d)
        self.assertTrue(rep["ok"])
        rep = vf.check_project({"volumes": ["https://bucket.example/PHerc0139/volumes/"],
                                "segments": ["https://bucket.example/segs/"]}, self.d)
        self.assertIn("volume", [w["rule"] for w in rep["warnings"]])
        self.assertIn("segments", [e["rule"] for e in rep["errors"]])

    def test_from_autopipe(self):
        run_dir = self.d / "run"
        (run_dir / "plan.json").write_text(json.dumps({"resolved": {
            "sample": "PHerc0139", "volume": "20250728140407", "voxel_um": 9.362,
            "volume_url": "https://bucket.example/PHerc0139/volumes/20250728140407.zarr/",
            "prediction_url": "https://bucket.example/PHerc0139/pred/m7.zarr/"}}))
        out = self.d / "ap.volpkg.json"
        code, rep, err = run(["project", str(out), "--from-autopipe", str(run_dir), "--anonymous"])
        self.assertEqual(code, 0, (rep, err))
        doc = json.loads(out.read_text())
        self.assertEqual(doc["name"], "PHerc0139-20250728140407")
        self.assertEqual(len(doc["volumes"]), 2)
        self.assertIn("vc-open-data-voxel-size-um:9.362", doc["volumes"][0]["tags"])
        self.assertEqual(doc["segments"], ["run/traces"])
        self.assertEqual(doc["umbilicus"], "run/umbilicus.json")
        code, _, err = run(["project", str(self.d / "z.volpkg.json"), "--from-autopipe", str(self.d / "data")])
        self.assertEqual(code, 2)

    def test_segments_sharing_a_vc3d_id_are_refused(self):
        # VC3D keys a segment by its folder name (Segmentation.cpp:42-56) and skips a second one with the same id
        # (VolumePkg.cpp:2086-2090): a flattened copy named like its trace would never load
        make_segment(self.d / "run" / "flat" / "t1")
        doc = vf.build_project(self.d / "run" / "p.volpkg.json", [self.vol],
                               [self.d / "run" / "traces", self.d / "run" / "flat"])
        rep = vf.check_project(doc, self.d / "run")
        self.assertFalse(rep["ok"])
        self.assertIn("duplicate_id", [e["rule"] for e in rep["errors"]])
        self.assertEqual(vf.vc3d_segment_id(self.d / "run" / "flat" / "t1"), "t1")
        # the same folder reached twice is one segment, not a clash
        doc = vf.build_project(self.d / "run" / "p.volpkg.json", [self.vol],
                               [self.d / "run" / "traces", self.d / "run" / "traces" / "t1"])
        self.assertNotIn("duplicate_id", [e["rule"] for e in vf.check_project(doc, self.d / "run")["errors"]])
        # an Open Data catalog representation is keyed by its uuid instead
        cat = make_segment(self.d / "cat" / "t1", meta={"vc_open_data_representation": {"kind": "x"},
                                                       "uuid": "rep-1"})
        self.assertEqual(vf.vc3d_segment_id(cat), "rep-1")
        doc = vf.build_project(self.d / "run" / "p.volpkg.json", [self.vol], [self.d / "run" / "traces", cat])
        self.assertNotIn("duplicate_id", [e["rule"] for e in vf.check_project(doc, self.d / "run")["errors"]])

    def test_write_project_writes_only_a_passing_project(self):
        out = self.d / "run" / "w.volpkg.json"
        doc = vf.build_project(out, [self.vol], [self.d / "run" / "traces"], umbilicus=self.umb)
        rep = vf.write_project(out, doc)
        self.assertTrue(rep["written"], rep)
        self.assertEqual(json.loads(out.read_text()), doc)
        with self.assertRaises(vf.FormatError):
            vf.write_project(out, doc)                                   # exists, no overwrite
        self.assertTrue(vf.write_project(out, doc, overwrite=True)["written"])
        bad = vf.build_project(self.d / "run" / "b.volpkg.json", [self.vol], [self.d / "empty-none"])
        rep = vf.write_project(self.d / "run" / "b.volpkg.json", bad)
        self.assertFalse(rep["written"])
        self.assertFalse((self.d / "run" / "b.volpkg.json").exists())
        with self.assertRaises(vf.FormatError):
            vf.write_project(self.d / "run" / "b.json", doc)


class InkMap(Tmp):
    def setUp(self):
        super().setUp()
        # 6 rows x 8 cols at scale 0.5: the render canvas is 16 x 12 px, aspect 4/3
        self.seg = make_segment(self.d / "segs" / "w035")
        self.map = self.d / "maps" / "w035_forward.tif"
        self.map.parent.mkdir()
        write_tiff(self.map, 12, 16, [7] * 192, fmt="B")

    def test_add_then_check(self):
        code, rep, err = run(["inkmap", "add", str(self.seg), str(self.map), "--label", "ink_9um forward"])
        self.assertEqual(code, 0, (rep, err))
        recs = json.loads((self.seg / "ink-detections.json").read_text())
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["segment_id"], "w035")
        self.assertEqual(recs[0]["local_file"], str(self.map.resolve()))
        self.assertEqual(recs[0]["label"], "ink_9um forward")
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(self.map)])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads((self.seg / "ink-detections.json").read_text())), 1)
        code, rep, _ = run(["inkmap", "check", str(self.seg)])
        self.assertEqual(code, 0, rep)
        self.map.unlink()
        code, rep, _ = run(["inkmap", "check", str(self.seg)])
        self.assertEqual(code, 1)

    def test_copy_makes_relative_record(self):
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(self.map), "--copy"])
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["record"]["local_file"], "ink/w035_forward.tif")
        self.assertTrue((self.seg / "ink" / "w035_forward.tif").is_file())

    def test_wrong_shapes_refused(self):
        turned = self.d / "maps" / "turned.tif"
        write_tiff(turned, 16, 12, [7] * 192, fmt="B")
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(turned)])
        self.assertEqual(code, 1)
        self.assertIn("transposed", rep["errors"][0]["message"])
        self.assertFalse((self.seg / "ink-detections.json").exists())
        crop = self.d / "maps" / "crop.tif"
        write_tiff(crop, 12, 10, [7] * 120, fmt="B")
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(crop)])
        self.assertEqual(code, 1)
        self.assertIn("crop", rep["errors"][0]["message"])

    def test_aspect_only_blind_spots_pinned(self):
        # Only the aspect is compared. These pass without --expect-size; the page and the audit say so.
        half = self.d / "maps" / "half.tif"
        write_tiff(half, 6, 8, [7] * 48, fmt="B")       # a half-size crop of the 16 x 12 canvas, same aspect
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(half)])
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["canvas_px"], [16.0, 12.0])
        other = self.d / "maps" / "w099_forward.tif"    # named for another segment, 400 x 300, same aspect
        write_tiff(other, 300, 400, [7] * 120000, fmt="B")
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(other)])
        self.assertEqual(code, 0, rep)
        square = make_segment(self.d / "segs" / "sq", rows=8, cols=8)   # 16 x 16 canvas: a turned map fits
        turned = self.d / "maps" / "sq_turned.tif"
        write_tiff(turned, 16, 16, [7] * 256, fmt="B")
        code, rep, _ = run(["inkmap", "add", str(square), str(turned)])
        self.assertEqual(code, 0, rep)

    def test_expect_size_refuses_same_aspect_crop(self):
        half = self.d / "maps" / "half.tif"
        write_tiff(half, 6, 8, [7] * 48, fmt="B")
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(half), "--expect-size", "16", "12"])
        self.assertEqual(code, 1)
        self.assertEqual([e["rule"] for e in rep["errors"]], ["size"])
        self.assertFalse((self.seg / "ink-detections.json").exists())
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(self.map), "--expect-size", "16", "12"])
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["expect_size"], [16, 12])

    def test_float_map_warns_and_png_accepted(self):
        f = self.d / "maps" / "float.tif"
        write_tiff(f, 24, 32, [0.5] * 768)
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(f)])
        self.assertEqual(code, 0)
        self.assertIn("dtype", [w["rule"] for w in rep["warnings"]])
        png = self.d / "maps" / "m.png"
        write_png_header(png, 160, 120)
        code, rep, _ = run(["inkmap", "add", str(self.seg), str(png)])
        self.assertEqual(code, 0, rep)

    def test_catalog_key_and_mismatch(self):
        seg = make_segment(self.d / "segs" / "cat", meta={"vc_open_data_segment_long_id": "PHerc0139/w035/long"})
        code, rep, _ = run(["inkmap", "add", str(seg), str(self.map)])
        self.assertEqual(rep["record"]["segment_id"], "PHerc0139/w035/long")
        recs = json.loads((seg / "ink-detections.json").read_text())
        recs[0]["segment_id"] = "w036"
        (seg / "ink-detections.json").write_text(json.dumps(recs))
        code, rep, _ = run(["inkmap", "check", str(seg)])
        self.assertEqual(code, 1)
        self.assertIn("does not match", rep["errors"][0]["message"])

    def test_not_a_segment(self):
        code, _, err = run(["inkmap", "add", str(self.d / "maps"), str(self.map)])
        self.assertEqual(code, 2)


class Seeds(Tmp):
    def test_autopipe_to_vc3d_round_trip(self):
        src = self.d / "seeds.json"
        src.write_text(json.dumps({"seeds": [[100.5, 200, 300], [101, 201, 301]], "stats": {}}))
        out = self.d / "points.json"
        code, rep, _ = run(["seeds", str(src), "--to", "vc3d", "--out", str(out), "--name", "ap-seeds"])
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["input_format"], "autopipe")
        doc = json.loads(out.read_text())
        self.assertEqual(doc["vc_pointcollections_json_version"], "1")
        col = doc["collections"]["1"]
        self.assertEqual(col["name"], "ap-seeds")
        self.assertEqual(col["points"]["1"]["p"], [100.5, 200.0, 300.0])
        self.assertEqual(vf.read_seeds(out), ([[100.5, 200.0, 300.0], [101.0, 201.0, 301.0]], "vc3d"))

    def test_other_inputs_and_targets(self):
        txt = self.d / "s.txt"
        txt.write_text("# x y z\n10 20 30\n11,21,31\n")
        code, rep, _ = run(["seeds", str(txt), "--to", "argv", "--volume", "V.zarr", "--params", "p.json",
                            "--target", "out"])
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["output"].splitlines()[0],
                         "vc_grow_seg_from_seed -v V.zarr -t out -p p.json --seed 10 20 30")
        code, rep, _ = run(["seeds", str(txt), "--to", "explicit"])
        self.assertEqual(json.loads(rep["output"]), {"explicit_seed": [[10.0, 20.0, 30.0], [11.0, 21.0, 31.0]]})
        meta = self.d / "meta.json"
        meta.write_text(json.dumps({"format": "tifxyz", "type": "seg", "seed": [5, 6, 7]}))
        self.assertEqual(vf.read_seeds(meta), ([[5.0, 6.0, 7.0]], "tifxyz-meta"))
        ex = self.d / "explicit.json"
        ex.write_text(json.dumps({"explicit_seed": [[1, 2, 3]]}))
        self.assertEqual(vf.read_seeds(ex)[1], "explicit")

    def test_collection_filter_and_version(self):
        doc = vf.vc3d_points([[1, 2, 3]], "a")
        doc["collections"]["2"] = {"name": "b", "points": {"5": {"p": [4, 5, 6]}}}
        p = self.d / "pc.json"
        p.write_text(json.dumps(doc))
        self.assertEqual(vf.read_seeds(p, "b")[0], [[4.0, 5.0, 6.0]])
        with self.assertRaises(vf.FormatError):
            vf.read_seeds(p, "c")
        doc["vc_pointcollections_json_version"] = "2"
        p.write_text(json.dumps(doc))
        with self.assertRaises(vf.FormatError):
            vf.read_seeds(p)

    def test_zero_and_negative(self):
        src = self.d / "z.txt"
        src.write_text("0 20 30\n")
        code, rep, _ = run(["seeds", str(src), "--to", "argv", "--volume", "V", "--params", "P", "--target", "T"])
        self.assertEqual(code, 1)
        self.assertIn("zero", [e["rule"] for e in rep["errors"]])
        code, rep, _ = run(["seeds", str(src), "--to", "vc3d"])
        self.assertEqual(code, 0)
        self.assertIn("zero", [w["rule"] for w in rep["warnings"]])
        src.write_text("-1 20 30\n")
        code, rep, _ = run(["seeds", str(src)])
        self.assertEqual(code, 1)
        src.write_text("1 2\n")
        code, _, _ = run(["seeds", str(src)])
        self.assertEqual(code, 2)


class Points(Tmp):
    """check_points against VC3D's PointCollections::loadFromJSON (PointCollections.cpp:603-645, 147-181, 58-69):
    one bad collection makes VC3D refuse the whole file."""

    def good(self):
        return vf.vc3d_points([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], name="seeds")

    def test_our_own_collections_pass(self):
        rep = vf.check_points(self.good())
        self.assertTrue(rep["ok"], rep)
        self.assertEqual((rep["points"], rep["collections"][0]["name"]), (2, "seeds"))
        doc = self.good()
        doc["collections"]["1"]["uuid"] = "3f2c3c56-1b7e-4d7f-9a63-0d4f4c3b2a10"
        doc["collections"]["1"]["anchor2d"] = None
        doc["collections"]["1"]["points"]["2"]["wind_a"] = 1.5
        self.assertTrue(vf.check_points(doc)["ok"])

    def test_what_vc3d_refuses(self):
        def broken(change):
            doc = self.good()
            change(doc, doc["collections"]["1"], doc["collections"]["1"]["points"]["1"])
            return vf.check_points(doc)
        cases = {
            "version": lambda d, c, p: d.update(vc_pointcollections_json_version=1),
            "collections": lambda d, c, p: d.update(collections=[]),
            "key": lambda d, c, p: d["collections"].update({"first": d["collections"].pop("1")}),
            "uuid": lambda d, c, p: c.update(uuid="not-a-uuid"),
            "name": lambda d, c, p: c.pop("name"),
            "points": lambda d, c, p: c.pop("points"),
            "point key": lambda d, c, p: c["points"].update({"p1": c["points"].pop("1")}),
            "p": lambda d, c, p: p.update(p=[1.0, 2.0]),
            "p text": lambda d, c, p: p.update(p=["1", 2.0, 3.0]),
            "wind_a": lambda d, c, p: p.update(wind_a="a"),
            "creation_time": lambda d, c, p: p.update(creation_time="now"),
            "color": lambda d, c, p: c.update(color=["red", 0, 0]),
            "anchor2d": lambda d, c, p: c.update(anchor2d=[1.0]),
        }
        for what, change in cases.items():
            rep = broken(change)
            self.assertFalse(rep["ok"], what)
            self.assertEqual({e["rule"] for e in rep["errors"]}, {"points"}, what)
        self.assertFalse(vf.check_points([1, 2, 3])["ok"])

    def test_seeds_to_vc3d_checks_the_file_it_writes(self):
        src = self.d / "seeds.json"
        src.write_text(json.dumps({"seeds": [[1, 2, 3]]}))
        out = self.d / "p.json"
        code, rep, _ = run(["seeds", str(src), "--to", "vc3d", "--out", str(out)])
        self.assertEqual(code, 0, rep)
        self.assertTrue(vf.check_points(json.loads(out.read_text()))["ok"])


class Labels(Tmp):
    def test_parse_villa_vocabulary(self):
        p = vf.parse_label_name
        self.assertEqual(p("w045_inklabels.tif"), {"prefix": "w045", "kind": "inklabels", "version": 1,
                                                   "extension": ".tif"})
        self.assertEqual(p("w045_supervision_mask_v2.zarr")["version"], 2)
        self.assertEqual(p("foo_v2_inklabels.TIFF")["prefix"], "foo_v2")
        self.assertIsNone(p("w045_inklabels.png"))
        self.assertIsNone(p("supervision.tif"))

    def _zarr(self, path, shape):
        (path / "0").mkdir(parents=True)
        (path / "0" / ".zarray").write_text(json.dumps({"shape": shape}))

    def test_find_selection(self):
        seg = self.d / "pherc0139-w016"
        for name, shape in (("pherc0139-w016_inklabels.zarr", [65, 40, 50]),
                            ("pherc0139-w016_inklabels_v2.zarr", [65, 40, 50]),
                            ("pherc0139-w016_supervision_mask.zarr", [65, 40, 50]),
                            ("w017_inklabels.zarr", [40, 50])):
            self._zarr(seg / name, shape)
        rep = vf.find_labels(seg)
        self.assertTrue(rep["ok"], rep["errors"])
        self.assertEqual(rep["selected"], {"inklabels": "pherc0139-w016_inklabels_v2.zarr",
                                           "supervision_mask": "pherc0139-w016_supervision_mask.zarr",
                                           "validation_mask": None})
        rules = [w["rule"] for w in rep["warnings"]]
        self.assertIn("mixed_versions", rules)
        self.assertIn("prefix", rules)
        layouts = {a["name"]: a["layout"] for a in rep["assets"]}
        self.assertEqual(layouts["pherc0139-w016_inklabels.zarr"], "villa-zyx")
        self.assertEqual(layouts["w017_inklabels.zarr"], "2d")
        rep = vf.find_labels(seg, version="v2")
        self.assertFalse(rep["ok"])
        rep = vf.find_labels(seg, extension=".tif")
        self.assertEqual(sorted(e["rule"] for e in rep["errors"]), ["missing", "missing"])

    def test_export_then_find(self):
        src = self.d / "xfer"
        src.mkdir()
        write_tiff(src / "inklabels.tif", 4, 6, [0, 255] * 12, fmt="B")
        write_tiff(src / "supervision.tif", 4, 6, [255] * 24, fmt="B")
        out = self.d / "train" / "w035"
        code, rep, _ = run(["labels", "export", "--ink", str(src / "inklabels.tif"), "--supervision",
                            str(src / "supervision.tif"), "--segment", "w035", "--out", str(out)])
        self.assertEqual(code, 0, rep)
        self.assertTrue((out / "w035_inklabels.tif").is_file())
        self.assertTrue((out / "w035_supervision_mask.tif").is_file())
        self.assertIn("create_label_zarrs", rep["next"][0])
        # villa's trainer reads only .zarr labels: with the default extension the TIFFs are not picked
        code, rep, _ = run(["labels", "find", str(out)])
        self.assertEqual(code, 1)
        self.assertEqual(sorted(e["rule"] for e in rep["errors"]), ["missing", "missing"])
        self.assertIn("tiff_only", [w["rule"] for w in rep["warnings"]])
        code, rep, _ = run(["labels", "find", str(out), "--extension", ".tif"])
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["selected"]["inklabels"], "w035_inklabels.tif")
        self.assertIn("trainer_zarr", [w["rule"] for w in rep["warnings"]])
        code, _, err = run(["labels", "export", "--ink", str(src / "inklabels.tif"), "--supervision",
                            str(src / "supervision.tif"), "--segment", "w035", "--out", str(out)])
        self.assertEqual(code, 2)

    def test_export_size_mismatch(self):
        write_tiff(self.d / "i.tif", 4, 6, [0] * 24, fmt="B")
        write_tiff(self.d / "s.tif", 4, 5, [0] * 20, fmt="B")
        code, rep, _ = run(["labels", "export", "--ink", str(self.d / "i.tif"), "--supervision",
                            str(self.d / "s.tif"), "--segment", "w1", "--out", str(self.d / "o"), "--version", "2"])
        self.assertEqual(code, 1)
        self.assertFalse((self.d / "o").exists())


def villa_direction(name):
    """villa's parse_prediction_direction, merge_predictions.py:112-118 at villa main 8aa507c12, reimplemented."""
    lower = Path(name).stem.lower()
    if "_forward_" in lower or lower.endswith("_forward"):
        return "forward"
    if "_reverse_" in lower or lower.endswith("_reverse"):
        return "reverse"
    return None


def villa_skip_glob(segment, model, direction, prefix=""):
    """The glob villa's folder inference skips a segment and direction on, infer.py:1213, 1224-1231 at 8aa507c12."""
    return f"{prefix + '_' if prefix else ''}{segment}_{model}_{direction}_*.tif"


def villa_u8(prob):
    """villa's iter_probability_tiles encoding, infer.py:808-811: clip to 0..1 in float32, times 255, truncate."""
    p = np.asarray(prob, dtype=np.float32).copy()
    np.clip(p, 0, 1, out=p)
    p *= 255
    return p.astype(np.uint8)


def have_pillow_libtiff():
    try:
        from PIL import features
        return bool(features.check("libtiff"))
    except Exception:
        return False


class Lzw(unittest.TestCase):
    def test_round_trip_edge_lengths(self):
        rng = __import__("random").Random(7)
        for n in (0, 1, 2, 3, 255, 256, 257, 510, 511, 512, 1023, 2047, 4093, 4094, 4095, 9000, 20000):
            for kind in ("random", "zeros", "ramp"):
                data = (bytes(rng.randrange(256) for _ in range(n)) if kind == "random" else
                        bytes(n) if kind == "zeros" else bytes(i % 256 for i in range(n)))
                code = vf.lzw_encode(data)
                self.assertEqual(code[:2][0] >> 7, 1, "the stream opens with the clear code 256")
                self.assertEqual(vf.lzw_decode(code), data, (n, kind))

    def test_broken_streams_refused(self):
        code = vf.lzw_encode(b"villa" * 50)
        with self.assertRaisesRegex(vf.FormatError, "without an end code"):
            vf.lzw_decode(code[:len(code) // 2])
        with self.assertRaisesRegex(vf.FormatError, "starts with code 258"):
            vf.lzw_decode(b"\x80\x40\x80")          # clear (256), then code 258 with nothing in the table

    @unittest.skipUnless(np is not None and have_pillow_libtiff(), "needs numpy and Pillow with libtiff")
    def test_same_codes_as_libtiff(self):
        import io as _io
        from PIL import Image
        rng = np.random.default_rng(3)
        tiles = {"random": rng.integers(0, 256, (64, 64), dtype=np.uint8), "zeros": np.zeros((64, 64), np.uint8),
                 "smooth": np.clip(rng.normal(0, 1, (64, 64)).cumsum(1) * 3 + 128, 0, 255).astype(np.uint8)}
        for kind, t in tiles.items():
            buf = _io.BytesIO()
            Image.fromarray(t).save(buf, format="TIFF", compression="tiff_lzw", tiffinfo={278: 64})
            data = buf.getvalue()
            with Image.open(_io.BytesIO(data)) as im:
                off, cnt = im.tag_v2[273][0], im.tag_v2[279][0]
            self.assertEqual(vf.lzw_decode(data[off:off + cnt]), t.tobytes(), kind)
            # Under 10000 bytes libtiff never takes its optional ratio clear, so the codes must be identical.
            self.assertEqual(vf.lzw_encode(t.tobytes()), data[off:off + cnt], kind)


@unittest.skipUnless(np is not None, "preds export needs numpy")
class Preds(Tmp):
    def setUp(self):
        super().setUp()
        # 6 rows x 8 cols at scale 0.125: the render canvas is 64 x 48 px
        self.seg = make_segment(self.d / "segs" / "w035", scale=0.125)
        yy, xx = np.mgrid[0:48, 0:64]
        self.prob = (0.5 + 0.5 * np.sin(xx / 7.0) * np.cos(yy / 5.0)).astype(np.float32)
        self.map = self.d / "maps" / "ink.npy"
        self.map.parent.mkdir()
        np.save(self.map, self.prob)

    def export(self, *extra, map_path=None, seg=None, model="ink_9um", direction="forward"):
        return run(["preds", "export", str(map_path or self.map), "--segment", str(seg or self.seg), "--model", model,
                    "--direction", direction, "--date", "191026", "--tile", "16", *extra])

    def read_back(self, path):
        """Pixels through kit's own decoder and, when installed, Pillow; both must agree."""
        a = vf.read_lzw_pixels(path)
        try:
            from PIL import Image
        except ImportError:
            return a
        with Image.open(path) as im:
            b = np.asarray(im)
        self.assertTrue(np.array_equal(a, b))
        return a

    def test_float_map_written_as_villa_prediction(self):
        code, rep, err = self.export()
        self.assertEqual(code, 0, (rep, err))
        out = self.seg / "preds" / "w035_ink_9um_forward_191026.tif"
        self.assertEqual(rep["file"], str(out))
        raw = out.read_bytes()
        self.assertEqual(raw[:4], b"II+\x00")                       # Big TIFF magic 43
        info = vf.tiff_info(out)
        self.assertEqual((info["dtype"], info["samples"], info["compression"], info["tiled"], info["bigtiff"]),
                         ("uint8", 1, 5, True, True))
        self.assertEqual((info["width"], info["height"], info["tile_width"], info["tile_length"]), (64, 48, 16, 16))
        self.assertEqual(len(info["tile_offsets"]), 12)
        self.assertTrue(np.array_equal(self.read_back(out), villa_u8(self.prob)))
        self.assertEqual(villa_direction(out.name), "forward")
        self.assertTrue(fnmatch.fnmatchcase(out.name, villa_skip_glob("w035", "ink_9um", "forward")))
        self.assertEqual(rep["scale"]["used"], "prob")
        self.assertEqual(rep["villa_view"]["merge_inputs"], [out.name])
        self.assertEqual(sorted(p.name for p in (self.seg / "preds").iterdir()), [out.name])   # no leftovers

    def test_uint8_map_kept_and_partial_tiles(self):
        vals = [(r * 7 + c * 3) % 256 for r in range(30) for c in range(41)]
        src = self.d / "maps" / "u8.tif"
        write_tiff(src, 30, 41, vals, fmt="B")
        code, rep, err = self.export(map_path=src, direction="reverse")
        self.assertEqual(code, 0, (rep, err))
        self.assertEqual(rep["scale"]["used"], "u8")
        out = Path(rep["file"])
        self.assertEqual(villa_direction(out.name), "reverse")
        got = self.read_back(out)
        self.assertEqual(got.shape, (30, 41))
        self.assertEqual(got.ravel().tolist(), vals)

    def test_nan_and_infinite_refused(self):
        for bad in (float("nan"), float("inf")):
            m = self.prob.copy()
            m[3, 4] = bad
            np.save(self.map, m)
            code, rep, _ = self.export()
            self.assertEqual(code, 1)
            self.assertEqual([e["rule"] for e in rep["errors"]], ["nonfinite"])
            self.assertFalse((self.seg / "preds").exists())

    def test_scales(self):
        u8 = self.d / "maps" / "u8.npy"
        np.save(u8, (self.prob * 255).astype(np.uint8))
        code, rep, _ = self.export("--scale", "prob", map_path=u8)
        self.assertEqual(code, 1)
        self.assertEqual(rep["errors"][0]["rule"], "scale")
        wide = self.d / "maps" / "wide.npy"
        np.save(wide, self.prob * 5 - 1)
        code, rep, _ = self.export(map_path=wide)
        self.assertEqual(code, 1)
        self.assertIn("pass --scale", rep["errors"][0]["message"])
        code, rep, _ = self.export("--scale", "minmax", map_path=wide)
        self.assertEqual(code, 0, rep)
        got = self.read_back(Path(rep["file"]))
        self.assertEqual((int(got.min()), int(got.max())), (0, 255))
        const = self.d / "maps" / "const.npy"
        np.save(const, np.full((48, 64), 3.0, np.float32))
        code, rep, _ = self.export("--scale", "minmax", "--overwrite", map_path=const)
        self.assertEqual(code, 1)

    def test_names_villa_would_misread(self):
        code, rep, _ = self.export(model="cnn_forward_v2", direction="reverse")
        self.assertEqual(code, 1)
        self.assertEqual(rep["errors"][0]["rule"], "direction")
        self.assertFalse((self.seg / "preds").exists())
        merged = make_segment(self.d / "segs" / "merged_w1", scale=0.125)
        code, rep, _ = self.export(seg=merged)
        self.assertEqual(code, 1)
        self.assertEqual(rep["errors"][0]["rule"], "merged")
        code, _, err = self.export(model="ink*9um")
        self.assertEqual(code, 2)
        self.assertIn("checkpoint stem", err)
        code, _, err = run(["preds", "export", str(self.map), "--segment", str(self.seg), "--model", "m",
                            "--direction", "forward", "--date", "2026-10-19"])
        self.assertEqual(code, 2)
        self.assertIn("DDMMYY", err)
        code, rep, _ = self.export("--output-prefix", "run3", model="ckpts/ink_9um.pth")
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["name"], "run3_w035_ink_9um_forward_191026.tif")
        self.assertTrue(fnmatch.fnmatchcase(rep["name"], villa_skip_glob("w035", "ink_9um", "forward", "run3")))

    def test_existing_file_and_merge_clashes(self):
        self.assertEqual(self.export()[0], 0)
        code, _, err = self.export()
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", err)
        self.assertEqual(self.export("--overwrite")[0], 0)
        write_tiff(self.seg / "preds" / "w035_ink_9um_forward_010126.tif", 48, 64, [0] * 3072, fmt="B")
        code, rep, _ = self.export("--overwrite")
        self.assertEqual(code, 0, rep)
        self.assertIn("skip", [w["rule"] for w in rep["warnings"]])
        self.assertEqual(len(rep["villa_view"]["merge_inputs"]), 2)
        write_tiff(self.seg / "preds" / "w035_other_forward_010126.tif", 40, 64, [0] * 2560, fmt="B")
        code, rep, _ = self.export("--overwrite")
        self.assertEqual(code, 1)
        self.assertEqual(rep["errors"][0]["rule"], "merge_shape")

    def test_surface_volume_size(self):
        vol = self.d / "villa" / "w016"
        (vol / "w016.zarr" / "0").mkdir(parents=True)
        (vol / "w016.zarr" / ".zgroup").write_text('{"zarr_format": 2}')
        (vol / "w016.zarr" / "0" / ".zarray").write_text(json.dumps({"shape": [21, 48, 64], "zarr_format": 2}))
        code, rep, _ = self.export(seg=vol)
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["villa_view"]["surface_volume"]["height"], 48)
        self.assertEqual(rep["villa_view"]["folder_inference"], "skips this model and direction")
        (vol / "w016.zarr" / "0" / ".zarray").write_text(json.dumps({"shape": [21, 50, 64], "zarr_format": 2}))
        code, rep, _ = self.export("--overwrite", seg=vol)
        self.assertEqual(code, 1)
        self.assertEqual(rep["errors"][0]["rule"], "surface_size")

    def test_register_then_inkmap_check(self):
        code, rep, err = self.export("--register", "--label", "ink_9um forward")
        self.assertEqual(code, 0, (rep, err))
        recs = json.loads((self.seg / "ink-detections.json").read_text())
        self.assertEqual(recs[0]["local_file"], "preds/w035_ink_9um_forward_191026.tif")
        self.assertEqual(recs[0]["label"], "ink_9um forward")
        self.assertEqual(recs[0]["kit_villafmt"]["villa_prediction"]["scale"]["used"], "prob")
        self.assertEqual(rep["registered"]["warnings"], [])           # uint8: VC3D shows it as stored
        code, rep, _ = run(["inkmap", "check", str(self.seg)])
        self.assertEqual(code, 0, rep)

    def test_register_refuses_wrong_aspect_before_writing(self):
        np.save(self.map, self.prob[:, :40])
        code, rep, _ = self.export("--register")
        self.assertEqual(code, 1)
        self.assertEqual(rep["errors"][0]["rule"], "aspect")
        self.assertFalse((self.seg / "preds").exists())
        self.assertFalse((self.seg / "ink-detections.json").exists())
        code, _, err = self.export("--register", seg=self.d / "maps")
        self.assertEqual(code, 2)
        self.assertIn("not a loadable tifxyz segment", err)

    @unittest.skipUnless(have_pillow_libtiff(), "needs Pillow with libtiff")
    def test_large_maps_pass_pillow_pixel_limit(self):
        # Pillow refuses images over 2 x MAX_IMAGE_PIXELS (about 179 megapixels by default); a whole segment's map
        # can be larger. A limit of 100 pixels stands in for that here, and must be back in place afterwards.
        from PIL import Image
        old = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = 100
        try:
            code, rep, err = self.export()
            self.assertEqual(code, 0, (rep, err))
            self.assertIn("Pillow", rep["encoding"]["verified_with"])
            self.assertEqual(Image.MAX_IMAGE_PIXELS, 100)
        finally:
            Image.MAX_IMAGE_PIXELS = old

    def test_lzw_maps_read_when_tifffile_has_no_imagecodecs(self):
        from unittest import mock
        u8 = villa_u8(self.prob)
        a = self.d / "a.tif"
        self.assertTrue(vf.write_pred_tiff(a, u8, tile=16, codec="python")["ok"])
        try:
            import tifffile
        except ImportError:
            self.skipTest("tifffile is not installed")
        err = ValueError("<COMPRESSION.LZW: 5> requires the 'imagecodecs' package")
        with mock.patch.object(tifffile, "imread", side_effect=err):
            self.assertTrue(np.array_equal(vf.read_tiff_pixels(a), u8))
            with mock.patch.dict("sys.modules", {"PIL": None}):
                self.assertTrue(np.array_equal(vf.read_tiff_pixels(a), u8))   # kit's own LZW reader
        with mock.patch.object(tifffile, "imread", side_effect=ValueError("something else")):
            with self.assertRaises(ValueError):
                vf.read_tiff_pixels(a)

    def test_pure_python_codec_matches(self):
        u8 = villa_u8(self.prob)
        a, b = self.d / "a.tif", self.d / "b.tif"
        ra = vf.write_pred_tiff(a, u8, tile=16, codec="python")
        rb = vf.write_pred_tiff(b, u8, tile=16, codec="auto")
        self.assertTrue(ra["ok"] and rb["ok"], (ra, rb))
        self.assertEqual(ra["codec"], "kit pure-Python LZW")
        self.assertTrue(np.array_equal(vf.read_lzw_pixels(a), u8))
        self.assertTrue(np.array_equal(vf.read_lzw_pixels(b), u8))
        with self.assertRaises(vf.FormatError):
            vf.write_pred_tiff(self.d / "c.tif", u8, tile=24)


if __name__ == "__main__":
    unittest.main()
