"""Bucket Sentinel (kit/sentinel.py, kit/sentinel_table.py): every check on synthetic stores with known answers, no
network. Each check is shown both ways: it passes a clean copy and flags the planted defect."""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import numpy as np
except ImportError:      # the map tests skip without numpy
    np = None

from kit import sentinel_table as st

if np is not None:
    from kit import sentinel as sn


def write_zarr(root, levels, scales, axes_unit=None, sep="/", attrs=None, compressor=None):
    """An OME-Zarr v2 folder: one level per array, chunks of 8 x 64 x 64, uncompressed unless a codec is given."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    datasets = []
    for k, (a, s) in enumerate(zip(levels, scales)):
        d = root / str(k)
        d.mkdir(exist_ok=True)
        ch = [min(8, a.shape[0]), 64, 64]
        za = {"chunks": ch, "compressor": compressor.get_config() if compressor else None, "dtype": "|u1",
              "fill_value": 0, "filters": None, "order": "C", "shape": list(a.shape), "zarr_format": 2,
              "dimension_separator": sep}
        (d / ".zarray").write_text(json.dumps(za))
        for i in range(math.ceil(a.shape[0] / ch[0])):
            for j in range(math.ceil(a.shape[1] / ch[1])):
                for m in range(math.ceil(a.shape[2] / ch[2])):
                    blk = np.zeros(ch, np.uint8)
                    sub = a[i * ch[0]:(i + 1) * ch[0], j * ch[1]:(j + 1) * ch[1], m * ch[2]:(m + 1) * ch[2]]
                    if not sub.any():
                        continue                      # absent chunk: reads as the fill value
                    blk[:sub.shape[0], :sub.shape[1], :sub.shape[2]] = sub
                    raw = blk.tobytes()
                    if compressor:
                        raw = compressor.encode(raw)
                    key = sep.join(str(v) for v in (i, j, m))
                    p = d / key
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(raw)
        datasets.append({"path": str(k), "coordinateTransformations": [{"type": "scale", "scale": list(s)}]})
    axes = [{"name": n, "type": "space", **({"unit": axes_unit} if axes_unit else {})} for n in "zyx"]
    doc = {"multiscales": [{"axes": axes, "datasets": datasets, "version": "0.4"}]}
    doc.update(attrs or {})
    (root / ".zattrs").write_text(json.dumps(doc))
    return root


def pool(a, fz, fy, fx):
    Z, Y, X = (a.shape[0] // fz) * fz, (a.shape[1] // fy) * fy, (a.shape[2] // fx) * fx
    b = a[:Z, :Y, :X].astype(float).reshape(Z // fz, fz, Y // fy, fy, X // fx, fx).mean((1, 3, 5))
    return np.clip(np.round(b), 0, 255).astype(np.uint8)


def texture(h, w, seed=0):
    """A smooth multi-scale texture in 30..230, so registration works at 4 and 16 px."""
    rng = np.random.default_rng(seed)
    f = np.fft.fft2(rng.normal(size=(h, w)))
    ky, kx = np.meshgrid(np.fft.fftfreq(h), np.fft.fftfreq(w), indexing="ij")
    k = np.hypot(ky, kx) + 1.0 / max(h, w)
    t = np.real(np.fft.ifft2(f / k ** 1.2))
    t = (t - t.min()) / (t.max() - t.min())
    return 30 + 200 * t


def bilinear(img, y, x):
    H, W = img.shape
    y = np.clip(y, 0, H - 1.001)
    x = np.clip(x, 0, W - 1.001)
    i, j = np.floor(y).astype(int), np.floor(x).astype(int)
    ty, tx = y - i, x - j
    return ((1 - ty) * (1 - tx) * img[i, j] + (1 - ty) * tx * img[i, j + 1] + ty * (1 - tx) * img[i + 1, j]
            + ty * tx * img[i + 1, j + 1])


SMALL = dict(FINE_WIN=32, FINE_SEARCH=8, FINE_GRID=3, COARSE_WIN=24, COARSE_SEARCH=10, COARSE_GRID=2,
             MIN_WINDOWS=4, SIGMA=2.0)


@unittest.skipIf(np is None, "needs numpy")
class Synthetic(unittest.TestCase):
    """A 16 x 768 x 768 CT whose texture does not change with depth, a flat mesh at z = 8 (scale 0.1), and canvases
    rendered from it with a known offset field, so the canvas check has an exact answer."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.T = texture(768, 768)
        ct0 = np.repeat(np.clip(cls.T, 0, 255).astype(np.uint8)[None], 16, 0)
        levels = [ct0] + [pool(ct0, 2 ** k, 2 ** k, 2 ** k) for k in range(1, 5)]
        cls.ct = write_zarr(root / "ct" / "20990101000000-2.000um-test.zarr", levels,
                            [[2.0 ** k] * 3 for k in range(5)])
        # mesh: 70 x 70 nodes, 10 voxels apart, z = 8
        g = np.arange(70, dtype=np.float32) * 10
        yy, xx = np.meshgrid(g, g, indexing="ij")
        cls.mesh = sn.Mesh(np.stack([xx, yy, np.full_like(xx, 8.0)], -1), [0.1, 0.1], {"name": "m"})
        cls.ctsrc = [sn.ct_source(str(cls.ct))]
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def canvas(self, name, field, shape=(640, 640), depth=5, zscale=1, truncate=None):
        """Render a canvas with content at (y, x) = CT at cell (y + dy, x + dx)."""
        H, W = shape
        yy, xx = np.meshgrid(np.arange(H, dtype=float), np.arange(W, dtype=float), indexing="ij")
        dy, dx = field(yy, xx)
        img = bilinear(self.T, yy + dy, xx + dx)
        a = np.repeat(np.clip(np.round(img), 1, 255).astype(np.uint8)[None], depth, 0)
        levels, scales = [a], [[1, 1, 1]]
        for k in range(1, 5):
            p = pool(a, 1, 2 ** k, 2 ** k)
            if truncate and k >= truncate[0]:
                p = p[:truncate[1]]
            levels.append(p)
            scales.append([zscale ** k if zscale > 1 else 1, 2 ** k, 2 ** k])
        store = sn.Store(str(write_zarr(self.root / name, levels, scales)))
        return sn.Canvas(store)

    def run_canvas(self, canvas):
        with mock.patch.multiple(sn, **SMALL):
            return sn.check_canvas(canvas, self.mesh, self.ctsrc[0])

    def test_register_sign(self):
        a = texture(64, 64, 3)
        b = np.roll(a, (3, -5), (0, 1))            # b(y) = a(y - 3): b shows a at y + d with d = (-3, 5)
        dy, dx, psr = sn.register(a, b, 10)
        self.assertAlmostEqual(dy, -3, delta=0.2)
        self.assertAlmostEqual(dx, 5, delta=0.2)
        self.assertGreater(psr, 8)

    def test_aligned_canvas(self):
        out = self.run_canvas(self.canvas("al.zarr", lambda y, x: (0 * y, 0 * x)))
        self.assertEqual(out["kind"], "aligned", out.get("detail"))
        self.assertEqual(out["verdict"], "ok")
        self.assertLess(out["max_offset"], sn.ALIGN_TOL)

    def test_constant_offset(self):
        out = self.run_canvas(self.canvas("co.zarr", lambda y, x: (6.0 + 0 * y, -10.0 + 0 * x)))
        self.assertEqual(out["kind"], "constant")
        self.assertAlmostEqual(out["median_offset"][0], 6.0, delta=0.8)
        self.assertAlmostEqual(out["median_offset"][1], -10.0, delta=0.8)

    def test_affine_offset(self):
        f = lambda y, x: (3.0 + 0.02 * y, -4.0 + 0.015 * x)     # noqa: E731
        out = self.run_canvas(self.canvas("af.zarr", f))
        self.assertIn(out["kind"], ("affine", "regions"))
        a = out["affine"]
        self.assertAlmostEqual(a["dy"][1], 0.02, delta=0.004)
        self.assertAlmostEqual(a["dx"][2], 0.015, delta=0.004)
        e = st.Entry({"path": "p", "model": "affine", "affine": a})
        cy, cx = e.cell(300.0, 300.0)
        ty, tx = f(300.0, 300.0)
        self.assertLess(math.hypot(cy - 300 - ty, cx - 300 - tx), 1.5)

    def test_size_prior_catches_large_drift(self):
        # a canvas 5 % smaller than the grid it was drawn from: offsets reach 30 px at the far edge
        H = 608
        mesh_rows = self.mesh.grid_shape[0]
        s = mesh_rows / H - 1.0
        out = self.run_canvas(self.canvas("dr.zarr", lambda y, x: (s * y, s * x), shape=(H, H)))
        self.assertIn(out["kind"], ("affine", "regions"))
        self.assertAlmostEqual(out["affine"]["dy"][1], s, delta=0.004)

    def test_planted_shift_and_scale(self):
        base_c = self.canvas("pb.zarr", lambda y, x: (0 * y, 0 * x))
        base = {"checks": [self.run_canvas(base_c)], "plant": None}
        for plant in ({"kind": "shift", "dy": 7.5, "dx": -12.0}, {"kind": "scale", "s": 0.97}):
            pc, truth = sn.plant_canvas(base_c, plant)
            res = {"checks": [self.run_canvas(pc)], "plant": plant}
            caught, err, what = sn.score_plant(base, res)
            self.assertTrue(caught, (plant, what))
            self.assertIsNotNone(err)
            self.assertLess(err, 2.0, (plant, err))

    def test_truncated_pyramid_flagged_and_used(self):
        c = self.canvas("tr.zarr", lambda y, x: (0 * y, 0 * x), depth=65, truncate=(1, 33))
        p = sn.check_pyramid(c.meta)
        self.assertEqual(p["verdict"], "defect")
        self.assertTrue(any(q["kind"] == "missing_slices" and q["axis"] == "z" for q in p["problems"]))
        # plane 32 lives at level 1 only (33 planes, true z factor 1); level 2 holds 33 planes too here, so it is used
        k, fy, plane = c.plan(4.0)
        self.assertEqual(plane, 32)

    def test_pooled_depth_pyramid_ok(self):
        H = 128
        a = np.full((64, H, H), 100, np.uint8)
        levels = [a] + [pool(a, 2 ** k, 2 ** k, 2 ** k) for k in (1, 2)]
        store = sn.Store(str(write_zarr(self.root / "pd.zarr", levels, [[2.0 ** k] * 3 for k in range(3)])))
        self.assertEqual(sn.check_pyramid(store.meta())["verdict"], "ok")

    def test_blank_plane(self):
        c = self.canvas("bl.zarr", lambda y, x: (0 * y, 0 * x), depth=9)
        self.assertEqual(sn.check_blank(c, probe=(320, 320))["verdict"], "ok")
        pc, _ = sn.plant_canvas(c, {"kind": "drop_planes", "level": 1, "planes": [4]})
        out = sn.check_blank(pc, probe=(320, 320))
        self.assertEqual(out["verdict"], "defect")
        self.assertEqual(out["problems"][0]["plane"], 4)

    def test_absent_chunks_read_as_fill(self):
        lv = sn.Store(str(self.ct)).level(0)
        a = lv.read(-2, 3, 700, 800, 0, 10)
        self.assertEqual(a.shape, (5, 100, 10))
        self.assertTrue((a[:2] == 0).all())            # outside the array
        self.assertTrue((a[2:, 68:] == 0).all())       # beyond y 768

    def test_compressed_store(self):
        try:
            import numcodecs
        except ImportError:
            self.skipTest("numcodecs not installed")
        a = np.arange(8 * 64 * 64, dtype=np.uint32).astype(np.uint8).reshape(8, 64, 64)
        root = write_zarr(self.root / "bz.zarr", [a], [[1, 1, 1]], compressor=numcodecs.Blosc(cname="zstd"))
        b = sn.Store(str(root)).level(0).read(0, 8, 0, 64, 0, 64)
        self.assertTrue((a == b).all())


@unittest.skipIf(np is None, "needs numpy")
class Metadata(unittest.TestCase):
    def meta(self, shapes, scales, unit=None):
        return {"axes": [{"name": n, "type": "space", **({"unit": unit} if unit else {})} for n in "zyx"],
                "levels": [{"path": str(k), "shape": s, "scale": c} for k, (s, c) in enumerate(zip(shapes, scales))]}

    def test_issue_2107_shape(self):
        m = self.meta([[65, 15872, 18944], [33, 7936, 9472], [17, 3968, 4736]],
                      [[1, 1, 1], [1, 2, 2], [1, 4, 4]])
        out = sn.check_pyramid(m)
        self.assertEqual(out["verdict"], "defect")
        self.assertEqual({p["level"] for p in out["problems"]}, {1, 2})
        self.assertEqual(sn.true_z_factor(m, 2), 1.0)

    def test_declared_depth_pooling_passes(self):
        m = self.meta([[65, 24120, 29900], [33, 12060, 14950], [17, 6030, 7475]],
                      [[1, 1, 1], [2, 2, 2], [4, 4, 4]])
        self.assertEqual(sn.check_pyramid(m)["verdict"], "ok")
        self.assertEqual(sn.true_z_factor(m, 2), 4.0)

    def test_missing_level(self):
        m = self.meta([[65, 100, 100], None], [[1, 1, 1], [1, 2, 2]])
        self.assertEqual(sn.check_pyramid(m)["problems"][0]["kind"], "missing_level")

    def test_scale_reset_with_known_pitch(self):
        m = self.meta([[10, 10, 10]], [[1, 1, 1]])
        out = sn.check_scale(m, 2.401, "metadata.min.json")
        self.assertEqual((out["verdict"], out["kind"], out["fallback_um"]), ("defect", "scale_reset", 2.401))
        self.assertEqual(sn.check_scale(m)["verdict"], "info")             # a pixel grid, nothing known

    def test_scale_ok_and_mismatch(self):
        m = self.meta([[10, 10, 10]], [[2.4, 2.4, 2.4]], unit="micrometer")
        self.assertEqual(sn.check_scale(m, 2.4, "name")["verdict"], "ok")
        self.assertEqual(sn.check_scale(m, 8.64, "name")["kind"], "scale_mismatch")

    def test_plant_reset_and_fix(self):
        m = self.meta([[10, 10, 10], [5, 5, 5]], [[1, 1, 1], [2, 2, 2]])
        fake = sn._MetaOnly(None, m)
        fixed = sn.plant_canvas(fake, {"kind": "fix_scale", "pitch": 8.64})[0].meta
        self.assertEqual(sn.check_scale(fixed, 8.64, "name")["verdict"], "ok")
        reset = sn.plant_canvas(sn._MetaOnly(None, fixed), {"kind": "reset_scale"})[0].meta
        self.assertEqual(sn.check_scale(reset, 8.64, "name")["kind"], "scale_reset")
        dropped = sn.plant_canvas(sn._MetaOnly(None, m), {"kind": "drop_meta", "level": 1, "keep": 2})[0].meta
        self.assertEqual(sn.check_pyramid(dropped)["verdict"], "defect")

    def test_known_pitch_sources(self):
        self.assertEqual(sn.known_pitch("20260411134726-2.400um-0.2m-78keV-masked.zarr"), (2.4, "name"))
        mm = {"samples": {"S": {"scans": {"20250101000000": {"properties": {"pixel_size_um": 8.64}}},
                                "volumes": {"20250102000000": {"scan_id": "20250101000000"}}}}}
        self.assertEqual(sn.known_pitch("vol.zarr", "20250102000000", mm), (8.64, "metadata.min.json"))
        self.assertEqual(sn.known_pitch("vol.zarr", "1", mm), (None, None))

    def test_issue_2369_label_shape(self):
        out = sn.check_labels((24120, 29900), {"MAN5_outer_3_inklabels.zarr": (24061, 29841),
                                               "front_inklabels.zarr": (24120, 29900)}, (24120.0, 29900.0))
        self.assertEqual(out["verdict"], "defect")
        self.assertEqual([p["label"] for p in out["problems"]], ["MAN5_outer_3_inklabels.zarr"])
        self.assertEqual(out["problems"][0]["short_by"], [59, 59])
        ok = sn.check_labels((100, 100), {"a_inklabels.zarr": (100, 100)})
        self.assertEqual(ok["verdict"], "ok")

    def test_grid_drift_slope(self):
        out = sn.check_labels((65419, 56889), {}, (65698.0, 56669.0))
        self.assertAlmostEqual(out["drift_slope"][0], 65698 / 65419 - 1)
        self.assertIn("grid_note", out)

    def test_declared_volume(self):
        cands = [("20251217075048", "https://x/20251217075048-2.399um-0.2m-78keV-masked.zarr", 2.399),
                 ("20251217075049", "https://x/20251217075049-2.399um-0.2m-78keV.zarr", 2.399)]
        m = sn.Mesh(np.zeros((2, 2, 3)), [1, 1], {"volume": "SCROLLS_HEL_2.399um_78keV_0.22m_TA_0001_masked.zarr"})
        self.assertEqual(sn.declared_volume(m, cands), ("20251217075048", "name"))
        m = sn.Mesh(np.zeros((2, 2, 3)), [1, 1], {"name": "20250101-on-20251217075049-2.399um.tifxyz"})
        self.assertEqual(sn.declared_volume(m, cands), ("20251217075049", "id"))
        self.assertEqual(sn.declared_volume(sn.Mesh(np.zeros((2, 2, 3)), [1, 1], {}), cands)[0], None)

    def test_sample_of(self):
        self.assertEqual(sn.sample_of("841"), "PHerc0841")
        self.assertEqual(sn.sample_of("0009b"), "PHerc0009B")
        self.assertEqual(sn.sample_of("phercparis4"), "PHercParis4")
        self.assertEqual(sn.sample_of("man5"), "PHercMAN5")


@unittest.skipIf(np is None, "needs numpy")
class Rules(unittest.TestCase):
    def test_excluded_item_is_never_opened(self):
        rule = sn.Rule(["hf:ink/zz/*"])
        with mock.patch.object(sn, "hf_item", side_effect=AssertionError("opened")), \
                mock.patch.object(sn, "Store", side_effect=AssertionError("opened")):
            out = sn.check_item("hf:ink/zz/secret_segment", rule)
        self.assertTrue(out["skipped"])
        self.assertNotIn("secret", json.dumps(out))
        cov = rule.coverage()
        self.assertEqual(cov["skipped_by_rule"], 1)
        self.assertNotIn("secret", json.dumps(cov))

    def test_rule_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "x.json")
            p.write_text(json.dumps({"patterns": ["s3:A/*"]}))
            r = sn.Rule.load(str(p))
            self.assertTrue(r.excluded("s3:A/segments/b"))
            self.assertFalse(r.excluded("s3:B/segments/b"))
            self.assertEqual(sn.Rule.load(None, env={}).patterns, [] if not sn.EXCLUDE_DEFAULT.exists()
                             else sn.Rule.load(str(sn.EXCLUDE_DEFAULT)).patterns)

    def test_scan_queues_new_and_changed(self):
        class Item:
            def __init__(self, path, type_, size=None, xet=None):
                self.path, self.type, self.size, self.xet_hash = path, type_, size, xet

        tree = {"ink": [Item("ink/s1", "directory")],
                "ink/s1": [Item("ink/s1/a", "directory"), Item("ink/s1/b", "directory")],
                "ink/s1/a": [Item("ink/s1/a/meta.json", "file", 3, "h1")],
                "ink/s1/b": [Item("ink/s1/b/meta.json", "file", 3, "h2")]}

        class Api:
            def list_bucket_tree(self, bucket, prefix, recursive=False):
                return tree.get(prefix, [])

        with tempfile.TemporaryDirectory() as d:
            state = Path(d, "state.json")
            first = sn.scan(state, s3=False, api=Api())
            self.assertEqual(first["new"], ["hf:ink/s1/a", "hf:ink/s1/b"])
            tree["ink/s1/b"][0].xet_hash = "h3"
            second = sn.scan(state, s3=False, api=Api())
            self.assertEqual((second["new"], second["changed"]), ([], ["hf:ink/s1/b"]))
            third = sn.scan(state, s3=False, api=Api(), rule=sn.Rule(["hf:ink/s1/a"]))
            self.assertEqual(third["coverage"]["skipped_by_rule"], 1)
            self.assertEqual(third["gone"], [])


@unittest.skipIf(np is None, "needs numpy")
class Preflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        a = np.zeros((16, 64, 64), np.uint8)
        self.vol = str(write_zarr(d / "20250101000000-2.4um-vol.zarr", [a], [[1, 1, 1]]))
        self.seg = d / "segment"
        for name, bb in (("1-on-20250101000000-2.4um.tifxyz", [[1, 1, 1], [60, 60, 15]]),
                         ("1-on-20240101000000-8.0um.tifxyz", [[1, 1, 1], [20, 20, 5]])):
            p = self.seg / name
            p.mkdir(parents=True)
            (p / "meta.json").write_text(json.dumps({"bbox": bb, "scale": [0.1, 0.1]}))

    def tearDown(self):
        self.tmp.cleanup()

    def listing(self):
        return [p.name for p in self.seg.iterdir()]

    def test_matching_mesh_passes(self):
        out = sn.preflight(self.seg / "1-on-20250101000000-2.4um.tifxyz", self.vol, listing=self.listing())
        self.assertEqual(out["verdict"], "ok", out)

    def test_issue_1845_other_frame_warns(self):
        out = sn.preflight(self.seg / "1-on-20240101000000-8.0um.tifxyz", self.vol, listing=self.listing())
        self.assertEqual(out["verdict"], "defect")
        self.assertTrue(any("named for volume 20240101000000" in w for w in out["warnings"]))
        self.assertTrue(any("mesh made in volume 20250101000000" in w for w in out["warnings"]))

    def test_bbox_outside_volume_warns(self):
        p = self.seg / "2.tifxyz"
        p.mkdir()
        (p / "meta.json").write_text(json.dumps({"bbox": [[0, 0, 0], [500, 500, 500]]}))
        out = sn.preflight(p, self.vol, listing=[])
        self.assertTrue(any("does not fit" in w for w in out["warnings"]))

    def test_render_args(self):
        self.assertEqual(sn.render_args(["-s", "SEG", "--volume", "VOL", "--scale", "1"]), ("SEG", "VOL"))
        self.assertEqual(sn.render_args(["--segmentation=SEG", "-v", "VOL"]), ("SEG", "VOL"))

    def test_cli_refuses_render_on_warning(self):
        from kit import cli
        mesh = str(self.seg / "1-on-20240101000000-8.0um.tifxyz")
        with mock.patch("subprocess.call", side_effect=AssertionError("rendered")):
            code = cli.main(["sentinel", "preflight", "--", "vc_render_tifxyz", "-s", mesh, "-v", self.vol])
        self.assertEqual(code, 3)


class Table(unittest.TestCase):
    def doc(self, **entry):
        e = {"path": "ink/s/w01", "model": "affine",
             "affine": {"dy": [53.0, 0.004263, 0.0], "dx": [-51.5, 0.0, -0.003876]}}
        e.update(entry)
        return {"schema": st.SCHEMA, "entries": [e]}

    def test_lookup_cell_and_inverse(self):
        t = st.Table(self.doc())
        e = t.lookup("/data/ink/s/w01")
        self.assertIsNotNone(e)
        cy, cx = e.cell(10000.0, 20000.0)
        self.assertAlmostEqual(cy, 10000 + 53 + 42.63, places=6)
        y, x = e.pixel(cy, cx)
        self.assertAlmostEqual(y, 10000.0, places=4)
        self.assertAlmostEqual(x, 20000.0, places=4)
        self.assertIsNone(t.lookup("ink/s/other"))

    def test_aligned_and_regions(self):
        e = st.Entry({"path": "p", "model": "aligned"})
        self.assertEqual(e.cell(5.0, 6.0), (5.0, 6.0))
        g = {"y": [0.0, 100.0], "x": [0.0, 100.0], "dy": [[0.0, 2.0], [None, 4.0]], "dx": [[0, 0], [0, 0]]}
        r = st.Entry({"path": "p", "model": "regions", "affine": {"dy": [1, 0, 0], "dx": [0, 0, 0]}, "grid": g})
        self.assertAlmostEqual(r.offset(0.0, 50.0)[0], 1 + 1.0)
        self.assertAlmostEqual(r.offset(100.0, 100.0)[0], 1 + 4.0)
        self.assertAlmostEqual(r.offset(100.0, 0.0)[0], 1 + 0.0)          # unmeasured cell reads 0 residual

    def test_verify_pins(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "x.tif").write_bytes(b"abc")
            import hashlib
            e = st.Entry({"path": "p", "model": "aligned", "pins": {"x.tif": hashlib.sha256(b"abc").hexdigest(),
                                                                       "y.tif": "0" * 64}})
            self.assertEqual(e.verify(d), ["y.tif: missing"])
            Path(d, "x.tif").write_bytes(b"abd")
            self.assertIn("x.tif: sha256 differs from the table's pin", e.verify(d))

    def test_schema_refused(self):
        with self.assertRaises(st.TableError):
            st.Table({"schema": "other"})

    @unittest.skipIf(np is None, "needs numpy")
    def test_label_cells_and_build_table(self):
        e = st.Table(self.doc()).lookup("ink/s/w01")
        cy, cx = st.label_cells(e, 0, 2, 0, 3)
        self.assertEqual(cy.shape, (2, 3))
        self.assertAlmostEqual(float(cy[1, 0]), 1 + 53 + 0.004263)
        res = {"item": "hf:ink/s/w00", "checked": "t", "plant": None, "pins": {"x.tif": "h"},
               "checks": [{"check": "canvas", "kind": "aligned", "affine": {"dy": [0.3, 0, 0], "dx": [0.3, 0, 0]},
                           "resid_rms": 0.1, "max_offset": 0.4, "n_accepted": 20}]}
        doc = sn.build_table([res, dict(res, plant={"kind": "shift"})])
        self.assertEqual(len(doc["entries"]), 1)                 # planted copies never enter the table
        self.assertEqual(doc["entries"][0]["affine"]["dy"], [0.0, 0.0, 0.0])
        self.assertEqual(st.Table(doc).lookup("ink/s/w00").model, "aligned")


@unittest.skipIf(np is None, "needs numpy")
class Controls(unittest.TestCase):
    def test_plants_cover_every_defect_class(self):
        kinds = {p["kind"] for p in sn.control_plants()}
        self.assertTrue({"shift", "scale", "label_scale", "drop_meta", "drop_planes", "reset_scale"} <= kinds)
        mags = [math.hypot(p["dy"], p["dx"]) for p in sn.control_plants() if p["kind"] == "shift"]
        self.assertAlmostEqual(min(mags), 4, places=1)
        self.assertAlmostEqual(max(mags), 300, places=1)
        scales = [p["s"] for p in sn.control_plants() if p["kind"] == "scale"]
        self.assertEqual((min(scales), max(scales)), (0.9, 1.1))

    def test_summary_can_fail(self):
        rows = [{"item": "a", "plant": None, "flag": False},
                {"item": "a", "plant": {"kind": "shift"}, "caught": True, "error_px": 0.5},
                {"item": "a", "plant": {"kind": "shift"}, "caught": False, "error_px": None},
                {"item": "a", "plant": {"kind": "label_same"}, "caught": True, "error_px": None}]
        s = sn.summarize_controls(rows)
        self.assertEqual(s["recall"], 0.5)
        self.assertFalse(s["pass"])
        rows[2].update(caught=True, error_px=1.0)
        self.assertEqual(sn.summarize_controls(rows)["negatives"], 2)
        self.assertTrue(sn.summarize_controls(rows)["pass"])


if __name__ == "__main__":
    unittest.main()
