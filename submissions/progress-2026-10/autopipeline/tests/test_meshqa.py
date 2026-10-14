"""kit meshqa: VC3D loader validity and stale bbox (tifxyz-repair port), the winding audit (ScrollFiesta wind_audit
port) and garbage prediction cubes (ScrollFiesta pred_reject port). Synthetic fixtures only."""

import contextlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, meshqa, vc3d_io, vc3d_orient

try:
    import numpy as np
except ImportError:  # the core kit is standard library only
    np = None
try:
    import tifffile
except ImportError:
    tifffile = None
try:  # only to cross-check the numpy union-find labelling
    from scipy import ndimage
except ImportError:
    ndimage = None

ROOT = Path(__file__).resolve().parent.parent


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def write_grid(path, arr):
    vc3d_io.write_tiff(path, vc3d_io.raster_from_numpy(arr))


def write_patch(d, X, Y, Z, bbox="auto", mask=None, extra_meta=None, scale=(0.05, 0.05)):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    for name, arr in zip("xyz", (X, Y, Z)):
        write_grid(d / f"{name}.tif", np.asarray(arr, np.float32))
    meta = {"format": "tifxyz", "scale": list(scale), "type": "seg", "uuid": d.name}
    if bbox == "auto":
        valid = (np.asarray(X) != -1) & ~(np.asarray(Z) <= 0)
        meta["bbox"] = [[float(a[valid].min()) for a in (X, Y, Z)], [float(a[valid].max()) for a in (X, Y, Z)]]
    elif bbox is not None:
        meta["bbox"] = bbox
    meta.update(extra_meta or {})
    (d / "meta.json").write_text(json.dumps(meta, indent=4) + "\n")
    if mask is not None:
        tifffile.imwrite(d / "mask.tif", mask)
    return d


def plane(shape=(20, 30), origin=(100.0, 200.0, 300.0), spacing=20.0):
    """tifxyz-repair's make_patch grid: column in x, row in y, constant z."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    return origin[0] + xs * spacing, origin[1] + ys * spacing, np.full(shape, origin[2])


def spiral(d, rows=20, pitch=20.0, w0=10.0, turns=2.0, step=5.0, hand=1, switch=None, hole_col=None,
           centre=(500.0, 400.0), theta0=0.0, holes=(), crush=1.0):
    """A sheet on the spiral r = pitch (w + hand theta / 2 pi), theta along the columns (arc step about `step`
    voxels), rows 5 voxels apart in z. switch = (r0, r1, c0): rows r0..r1-1 jump to the next wrap from column c0
    on. hole_col: an invalid column (x = -1), which splits the grid into two components. holes: (r0, r1, c0, c1)
    blocks made invalid. crush: x scaled by it about the centre (a scroll flattened along x)."""
    th_max = turns * TWO_PI
    ncol = int(th_max * pitch * (w0 + turns / 2) / step) + 1
    th = theta0 + np.linspace(0.0, th_max, ncol)
    X, Y, Z = (np.zeros((rows, ncol)) for _ in range(3))
    for r in range(rows):
        w = np.full(ncol, w0)
        if switch and switch[0] <= r < switch[1]:
            w[switch[2]:] += 1
        u = (th - theta0) / TWO_PI
        rad = pitch * (w + u) if hand > 0 else pitch * (w + turns - u)
        X[r], Y[r], Z[r] = centre[0] + crush * rad * np.cos(th), centre[1] + rad * np.sin(th), 100.0 + 5 * r
    if hole_col is not None:
        X[:, hole_col] = Y[:, hole_col] = Z[:, hole_col] = -1
    for r0, r1, c0, c1 in holes:
        X[r0:r1, c0:c1] = Y[r0:r1, c0:c1] = Z[r0:r1, c0:c1] = -1
    return write_patch(d, X, Y, Z)


TWO_PI = 2 * math.pi


def get(findings, check):
    return [f for f in findings if f["check"] == check]


@unittest.skipIf(np is None or tifffile is None, "numpy and tifffile are needed for kit meshqa validity tests")
class ValidityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_patch_validates_ok(self):
        p = meshqa.load_patch(write_patch(self.d / "p", *plane()))
        findings = meshqa.validate_patch(p)
        self.assertEqual(meshqa.worst_severity(findings), "info")
        self.assertEqual(meshqa.compare_trim_rule(p)["disagree"], 0)

    def test_loader_rules_z_nonpositive_sentinel_and_nan(self):
        X, Y, Z = plane((10, 10))
        Z[0, :] = -5.0          # z <= 0: the loader rewrites these to (-1, -1, -1)
        Z[1, 0] = 0.0
        X[9, 9] = -1.0          # x == -1: QuadSurface::bbox() skips it
        Z[5, 5] = np.nan        # NaN <= 0 is false: VC3D keeps it
        X[9, 8] = 9999.0        # a far outlier the loader keeps
        p = meshqa.load_patch(write_patch(self.d / "p", X, Y, Z, bbox=None))
        self.assertFalse(p.valid[0, :].any())
        self.assertFalse(p.valid[1, 0])
        self.assertFalse(p.valid[9, 9])
        self.assertTrue(p.valid[5, 5])
        self.assertEqual(int(p.valid.sum()), 100 - 10 - 1 - 1)
        low, high = meshqa.compute_bbox(p)
        self.assertEqual(high[0], 9999.0)
        self.assertEqual(low[1], 200.0 + 20 * 1)          # row 0 is gone; (1, 0) too, (1, 1) keeps y = 220
        self.assertEqual(low[2], 300.0)                    # NaN z is left out of the box
        self.assertTrue(get(meshqa.validate_patch(p), "nan-vertices"))

    def test_mask_at_grid_size(self):
        X, Y, Z = plane((10, 10))
        mask = np.full((10, 10), 255, np.uint8)
        mask[:, 9] = 0
        mask[0, 0] = 254          # anything under 255 is dropped
        p = meshqa.load_patch(write_patch(self.d / "p", X, Y, Z, mask=mask))
        self.assertFalse(p.valid[:, 9].any())
        self.assertFalse(p.valid[0, 0])
        self.assertEqual(int(p.valid.sum()), 100 - 10 - 1)
        self.assertEqual(meshqa.compute_bbox(p)[1][0], 100 + 8 * 20)

    def test_mask_block_decimation_any_pixel_kills_the_vertex(self):
        X, Y, Z = plane((8, 8))
        mask = np.full((16, 24), 255, np.uint8)      # 2x along rows, 3x along columns
        mask[0, 23] = 0                               # one pixel of the block of grid cell (0, 7)
        mask[9, 4] = 17                               # one pixel of the block of grid cell (4, 1)
        p = meshqa.load_patch(write_patch(self.d / "p", X, Y, Z, mask=mask))
        self.assertFalse(p.valid[0, 7])
        self.assertFalse(p.valid[4, 1])
        self.assertEqual(int(p.valid.sum()), 62)
        _, note = p.mask_valid()
        self.assertIn("decimated 2x3", note)
        warn = get(meshqa.validate_patch(p), "mask-shape")
        self.assertTrue(warn and "decimated" in warn[0]["message"])

    def test_mask_of_other_size_is_ignored_as_vc3d_does(self):
        X, Y, Z = plane((8, 8))
        mask = np.zeros((12, 16), np.uint8)          # 12 is not a multiple of 8
        p = meshqa.load_patch(write_patch(self.d / "p", X, Y, Z, mask=mask))
        self.assertTrue(p.valid.all())
        self.assertIn("ignored by VC3D", get(meshqa.validate_patch(p), "mask-shape")[0]["message"])

    def test_mask_first_page_and_channel_zero(self):
        X, Y, Z = plane((10, 10))
        d = write_patch(self.d / "pages", X, Y, Z)
        m0 = np.full((10, 10), 255, np.uint8)
        m0[:, 9] = 0
        tifffile.imwrite(d / "mask.tif", np.stack([m0, np.zeros((10, 10), np.uint8)]))   # page 1 must not count
        p = meshqa.load_patch(d)
        self.assertFalse(p.valid[:, 9].any())
        self.assertTrue(p.valid[:, :9].all())
        planar = np.full((3, 10, 10), 255, np.uint8)
        planar[0, :, 9] = 0
        planar[1:, :, :5] = 0                     # later channels do not count
        d2 = write_patch(self.d / "planar", X, Y, Z)
        tifffile.imwrite(d2 / "mask.tif", planar, planarconfig="separate", photometric="rgb")
        p = meshqa.load_patch(d2)
        self.assertEqual(int(p.valid.sum()), 90)
        self.assertFalse(p.valid[:, 9].any())
        contig = np.moveaxis(planar, 0, -1).copy()
        d3 = write_patch(self.d / "contig", X, Y, Z)
        tifffile.imwrite(d3 / "mask.tif", contig, photometric="rgb")
        self.assertEqual(int(meshqa.load_patch(d3).valid.sum()), 90)

    def test_no_false_positive_from_masked_and_nonpositive_outliers(self):
        X, Y, Z = plane((10, 10))
        mask = np.full((10, 10), 255, np.uint8)
        X[0, 0] = Y[0, 0] = 9999.0
        mask[0, 0] = 0
        X[9, 9] = Y[9, 9] = -9999.0
        Z[9, 9] = -1.0
        true_box = [[100.0, 200.0, 300.0], [280.0, 380.0, 300.0]]
        p = meshqa.load_patch(write_patch(self.d / "p", X, Y, Z, bbox=true_box, mask=mask))
        self.assertFalse(get(meshqa.validate_patch(p), "bbox-stale"))
        self.assertEqual(meshqa.repair_plan(p), (None, None))

    def test_trim_rule_disagreement_is_counted_by_cause(self):
        X, Y, Z = plane((10, 10))
        Y[2, 2] = Y[2, 3] = -1.0       # valid for VC3D (partial sentinel), not for the trim rule
        X[3, 3] = 0.0                   # valid for VC3D, not for X > 0
        Z[4, 4] = Z[4, 5] = Z[4, 6] = 0.0   # z <= 0 for VC3D, but the trim rule only tests != -1
        mask = np.full((10, 10), 255, np.uint8)
        mask[7, 0:4] = 0                # VC3D masks them; the trim rule ignores mask.tif
        p = meshqa.load_patch(write_patch(self.d / "p", X, Y, Z, mask=mask))
        cmp = meshqa.compare_trim_rule(p)
        self.assertEqual(cmp["disagree"], 10)
        self.assertEqual(cmp["vc3d_only"], {"total": 3, "y_sentinel": 2, "x_not_positive": 1})
        self.assertEqual(cmp["trim_only"], {"total": 7, "z_not_positive": 3, "masked": 4})
        self.assertTrue(get(meshqa.validate_patch(p), "partial-sentinel"))

    def test_stale_bbox_cli_fix_writes_a_copy(self):
        src = write_patch(self.d / "stale", *plane(), bbox=[[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]],
                          extra_meta={"custom": {"a": 1}})
        before = (src / "meta.json").read_bytes()
        findings = meshqa.validate_patch(meshqa.load_patch(src))
        stale = get(findings, "bbox-stale")
        self.assertEqual(len(stale), 1)
        self.assertGreater(stale[0]["frac_outside"], 0.9)
        out = self.d / "fixed"
        code, text, _ = run_cli(["meshqa", "validity", str(src), "--fix", str(out)])
        self.assertEqual(code, 1)              # the source had an error-severity finding
        self.assertIn("bbox-stale", text)
        self.assertEqual((src / "meta.json").read_bytes(), before)     # never in place
        meta = json.loads((out / "meta.json").read_text())
        self.assertEqual(meta["bbox"], [[100.0, 200.0, 300.0], [100.0 + 29 * 20, 200.0 + 19 * 20, 300.0]])
        self.assertEqual(meta["custom"], {"a": 1})
        self.assertEqual(list(meta), list(json.loads(before)))          # key order kept
        self.assertTrue((out / "meta.json").read_text().endswith("}\n"))
        self.assertFalse(get(meshqa.validate_patch(meshqa.load_patch(out)), "bbox-stale"))
        code, _, _ = run_cli(["meshqa", "validity", str(out)])
        self.assertEqual(code, 0)
        code, text, _ = run_cli(["meshqa", "validity", str(src), "--fix", str(out)])    # exists, no --overwrite
        self.assertEqual(code, 1)
        self.assertIn("--overwrite", text)
        code, _, _ = run_cli(["meshqa", "validity", str(src), "--fix", str(out), "--overwrite"])
        self.assertEqual(code, 1)
        with self.assertRaises(meshqa.MeshQAError):
            meshqa.fix_copy(src, src)
        with self.assertRaises(meshqa.MeshQAError):
            meshqa.fix_copy(src, src / "inside")

    def test_fix_bake_invalid_makes_the_rules_agree(self):
        X, Y, Z = plane((10, 10))
        Z[4, 4] = 0.0
        mask = np.full((10, 10), 255, np.uint8)
        mask[7, 0:4] = 0
        src = write_patch(self.d / "p", X, Y, Z, mask=mask, bbox=[[0, 0, 0], [1, 1, 1]])
        res = meshqa.fix_copy(src, self.d / "baked", bake=True)
        self.assertEqual(res["baked_vertices"], 5)
        self.assertIn("recompute bbox", res["change"])
        q = meshqa.load_patch(self.d / "baked")
        self.assertEqual(float(q.x[4, 4]), -1.0)
        self.assertEqual(float(q.z[7, 0]), -1.0)
        self.assertEqual(meshqa.compare_trim_rule(q)["trim_only"]["total"], 0)
        self.assertEqual(int(q.valid.sum()), int(meshqa.load_patch(src).valid.sum()))
        self.assertEqual(json.loads((self.d / "baked" / "meta.json").read_text())["bbox"],
                         [list(v) for v in meshqa.compute_bbox(q)])

    def test_strip_bbox_and_missing_bbox_is_not_added(self):
        src = write_patch(self.d / "p", *plane())
        meshqa.fix_copy(src, self.d / "stripped", strip=True)
        self.assertNotIn("bbox", json.loads((self.d / "stripped" / "meta.json").read_text()))
        nobox = write_patch(self.d / "nobox", *plane(), bbox=None)
        f = get(meshqa.validate_patch(meshqa.load_patch(nobox)), "bbox-missing")
        self.assertEqual(f[0]["severity"], "info")
        res = meshqa.fix_copy(nobox, self.d / "nobox-copy")
        self.assertIsNone(res["change"])
        self.assertNotIn("bbox", json.loads((self.d / "nobox-copy" / "meta.json").read_text()))

    def test_tree_json_and_bad_paths(self):
        write_patch(self.d / "t" / "a", *plane())
        write_patch(self.d / "t" / "b", *plane(), bbox=[[0, 0, 0], [1, 1, 1]])
        code, text, _ = run_cli(["meshqa", "validity", str(self.d / "t"), "--json"])
        self.assertEqual(code, 1)
        data = json.loads(text)
        self.assertEqual([Path(r["path"]).name for r in data], ["a", "b"])
        self.assertEqual([r["status"] for r in data], ["info", "error"])
        code, _, _ = run_cli(["meshqa", "validity", str(self.d / "t"), "--fix", str(self.d / "out")])
        self.assertTrue((self.d / "out" / "a" / "x.tif").is_file() and (self.d / "out" / "b" / "meta.json").is_file())
        code, _, err = run_cli(["meshqa", "validity", str(self.d / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)
        (self.d / "empty").mkdir()
        self.assertEqual(run_cli(["meshqa", "validity", str(self.d / "empty")])[0], 2)

    def test_meta_and_grid_errors_are_reported_not_raised(self):
        d = write_patch(self.d / "badscale", *plane(), scale=(0.0, 0.05), extra_meta={"voxelsize": 0})
        findings = meshqa.validate_patch(meshqa.load_patch(d))
        self.assertTrue(get(findings, "meta-scale") and get(findings, "meta-voxelsize"))
        d = write_patch(self.d / "shape", *plane())
        write_grid(d / "y.tif", np.zeros((5, 5), np.float32))
        p = meshqa.load_patch(d)
        self.assertFalse(p.valid.any())
        self.assertTrue(get(meshqa.validate_patch(p), "grid-shape"))
        self.assertIsNone(meshqa.compare_trim_rule(p))
        d = write_patch(self.d / "nometa", *plane())
        (d / "meta.json").unlink()
        (d / "x.tif").write_bytes(b"not a tiff")
        findings = meshqa.validate_patch(meshqa.load_patch(d))
        self.assertTrue(get(findings, "meta-parse") and get(findings, "tif-read"))

    def test_float64_grids_are_judged_as_the_float32_vc3d_reads(self):
        X, Y, Z = plane((6, 6))
        Z[0, 0] = 1e-46               # positive as a double, 0.0f after VC3D's static_cast<float>: z <= 0
        X[1, 1] = -1.0000000001       # -1.0f: bbox() skips it
        d = write_patch(self.d / "f64", X, Y, Z, bbox=None)
        for name, arr in zip("xyz", (X, Y, Z)):
            tifffile.imwrite(d / f"{name}.tif", np.asarray(arr, np.float64))
        p = meshqa.load_patch(d)
        self.assertFalse(p.valid[0, 0] or p.valid[1, 1])
        self.assertEqual(int(p.valid.sum()), 34)
        self.assertEqual(meshqa.compute_bbox(p)[0], [100.0, 200.0, 300.0])
        self.assertEqual(len(get(meshqa.validate_patch(p), "grid-dtype")), 3)

    def test_mask_sample_types_follow_vc3d_to_valid(self):
        X, Y, Z = plane((2, 4))
        cases = (
            (np.array([[255, 254, 65535, 0]] * 2, np.uint16), [True, False, True, False]),
            (np.array([[255.0, 254.9, np.nan, 1e9]] * 2, np.float32), [True, False, False, True]),
            # VC3D's default branch reads the sample's first byte: 255 -> 0xff, 256 -> 0x00, 511 -> 0xff
            (np.array([[255, 256, 511, 1000]] * 2, np.uint64), [True, False, True, False]),
            (np.array([[255.0, 300.0, 1e4, 0.0]] * 2, np.float16), [False, False, False, False]),
        )
        for k, (mask, expect) in enumerate(cases):
            with self.subTest(str(mask.dtype)):
                p = meshqa.load_patch(write_patch(self.d / f"m{k}", X, Y, Z, mask=mask))
                self.assertEqual(p.valid[0].tolist(), expect)

    def test_fix_leaves_no_partial_copy_and_keeps_the_old_one(self):
        X, Y, Z = plane()
        Z[0, 0] = -1.0
        src = write_patch(self.d / "src", X, Y, Z, bbox=[[0, 0, 0], [1, 1, 1]])
        before = {f.name: f.read_bytes() for f in src.iterdir()}
        (src / "dangling.tif").symlink_to(self.d / "no-such-file")
        with self.assertRaises(Exception):
            meshqa.fix_copy(src, self.d / "out")
        (src / "dangling.tif").unlink()
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["src"])      # no OUT, no temporary folder
        real, calls = meshqa._write_grid, []

        def full_disk(path, arr):
            calls.append(path)
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            real(path, arr)
        with mock.patch.object(meshqa, "_write_grid", full_disk):
            with self.assertRaises(OSError):
                meshqa.fix_copy(src, self.d / "out", bake=True)
        self.assertFalse((self.d / "out").exists())
        meshqa.fix_copy(src, self.d / "out")
        good = (self.d / "out" / "x.tif").read_bytes()
        calls.clear()
        with mock.patch.object(meshqa, "_write_grid", full_disk):
            with self.assertRaises(OSError):
                meshqa.fix_copy(src, self.d / "out", bake=True, overwrite=True)
        self.assertEqual((self.d / "out" / "x.tif").read_bytes(), good)        # the old copy survives
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["out", "src"])
        self.assertEqual({f.name: f.read_bytes() for f in src.iterdir()}, before)

    def test_fix_overwrite_restores_the_old_copy_when_the_swap_fails(self):
        X, Y, Z = plane()
        src = write_patch(self.d / "src", X, Y, Z, bbox=[[0, 0, 0], [1, 1, 1]])
        out = self.d / "out"
        meshqa.fix_copy(src, out)
        good = {f.name: f.read_bytes() for f in out.iterdir()}
        real = meshqa.os.replace

        def no_rename_onto_out(a, b):
            if Path(b) == out and Path(a).name == "copy":        # the finished stage moving into place
                raise OSError(18, "Invalid cross-device link")
            return real(a, b)
        with mock.patch.object(meshqa.os, "replace", no_rename_onto_out):
            with self.assertRaises(OSError):
                meshqa.fix_copy(src, out, bake=True, overwrite=True)
        self.assertEqual({f.name: f.read_bytes() for f in out.iterdir()}, good)    # moved aside, then put back
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["out", "src"])

    def test_fix_of_several_patches_and_unsafe_targets(self):
        a = write_patch(self.d / "pa", *plane(), bbox=[[0, 0, 0], [1, 1, 1]])
        b = write_patch(self.d / "pb", *plane(origin=(5000.0, 200.0, 300.0)), bbox=[[0, 0, 0], [1, 1, 1]])
        run_cli(["meshqa", "validity", str(a), str(b), "--fix", str(self.d / "out")])
        for name, x0 in (("pa", 100.0), ("pb", 5000.0)):
            self.assertEqual(json.loads((self.d / "out" / name / "meta.json").read_text())["bbox"][0][0], x0)
        twin = write_patch(self.d / "other" / "pa", *plane(), bbox=[[0, 0, 0], [1, 1, 1]])
        code, _, err = run_cli(["meshqa", "validity", str(a), str(twin), "--fix", str(self.d / "out2")])
        self.assertEqual(code, 2)
        self.assertIn("both be written", err)
        self.assertFalse((self.d / "out2").exists())
        tree = self.d / "tree"
        write_patch(tree / "a", *plane(), bbox=[[0, 0, 0], [1, 1, 1]])
        write_patch(tree / "b", *plane())
        listing = sorted(p.relative_to(tree) for p in tree.rglob("*"))
        code, _, err = run_cli(["meshqa", "validity", str(tree), "--fix", str(tree / "b" / "fixed")])
        self.assertEqual(code, 2)
        self.assertIn("source patch", err)
        self.assertEqual(sorted(p.relative_to(tree) for p in tree.rglob("*")), listing)     # nothing written
        code, _, err = run_cli(["meshqa", "validity", str(a), "--bake-invalid"])
        self.assertEqual(code, 2)
        self.assertIn("--fix", err)

    def test_standard_library_reader_without_tifffile(self):
        X, Y, Z = plane((6, 7))
        Z[0, 0] = -3.0
        d = write_patch(self.d / "p", X, Y, Z)
        with mock.patch.object(meshqa, "_tifffile", return_value=None):
            p = meshqa.load_patch(d)
            self.assertEqual(p.x.dtype, np.float32)
            self.assertEqual(int(p.valid.sum()), 41)
            self.assertEqual(meshqa.worst_severity(meshqa.validate_patch(p)), "info")


@unittest.skipIf(np is None, "numpy is needed for kit meshqa windaudit")
class WindAuditTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def audit(self, d, **kw):
        kw.setdefault("centre", (500.0, 400.0))
        return meshqa.wind_audit(d, **kw)

    def test_wrap_and_union_min(self):
        a = np.array([math.pi, -math.pi, 3 * math.pi, -3 * math.pi, 0.5, -0.5, 7.0])
        self.assertTrue(np.allclose(meshqa._wrap_pmpi(np, a), [math.pi, math.pi, math.pi, math.pi, 0.5, -0.5,
                                                               7.0 - TWO_PI]))
        roots = meshqa.union_min(np, 7, [5, 1, 6, 2, 4], [0, 5, 1, 6, 3])
        self.assertEqual(roots.tolist(), [0, 0, 0, 3, 3, 0, 0])

    def test_clean_spiral_passes_and_the_pitch_is_found(self):
        rep = self.audit(spiral(self.d / "clean"))
        self.assertEqual(rep["pitch"]["source"], "auto (grid)")
        self.assertAlmostEqual(rep["pitch"]["value"], 20.0, delta=0.2)
        self.assertEqual(rep["handedness"]["value"], 1)
        self.assertGreater(rep["pitch"]["auto"]["concentration"], 0.99)
        self.assertEqual((rep["mergers"]["full_turn"], rep["mergers"]["outer"], rep["mergers"]["core"]), (0, 0, 0))
        self.assertFalse(rep["gate"]["local_failed"])
        c = rep["component_table"][0]
        self.assertEqual((rep["components"], c["euler_chi"], c["boundary_loops"], c["genus"]), (1, 1, 1, 0.0))
        self.assertAlmostEqual(c["turns"], 2.0, delta=0.05)
        self.assertLess(c["phase_span"], 0.01)

    def test_planted_sheet_switch_is_flagged(self):
        r0, r1, c0 = 5, 15, 300
        rep = self.audit(spiral(self.d / "switch", switch=(r0, r1, c0)), local_span_tol=0.5, list_limit=5000)
        m = rep["mergers"]
        self.assertGreater(m["full_turn"], 0)
        self.assertEqual(m["full_turn"], m["outer"])            # every merger is a one-turn jump
        self.assertAlmostEqual(m["mean_dr"], 20.0, delta=0.5)
        self.assertEqual(m["full_turn_rows"], [r0 - 1, r1])
        self.assertEqual(m["full_turn_cols"][0], c0 - 1)
        listed = [e for e in m["listed"] if e["full_turn"]]
        self.assertEqual(len(listed), m["full_turn"])

        def inside(rc):
            return r0 <= rc[0] < r1 and rc[1] >= c0
        self.assertTrue(all(inside(e["a"]) != inside(e["b"]) for e in listed))    # each crosses the block's edge
        # dw = dT - wrap(dtheta) / 2 pi is exactly one turn here, positive into the block (the next wrap out); with
        # the theta term's sign reversed the edges along a row would be off by 2 dtheta / 2 pi, about 0.008
        self.assertTrue(all(abs(abs(e["dw"]) - 1.0) < 1e-3 for e in listed))
        self.assertTrue(all((e["dw"] > 0) == inside(e["b"]) for e in listed))
        self.assertTrue(rep["gate"]["local_failed"])
        self.assertEqual(rep["broad_fusion"]["components"], 1)
        self.assertAlmostEqual(rep["component_table"][0]["phase_span"], 1.0, delta=0.02)
        self.assertEqual(rep["component_table"][0]["full_turn_fusions"], m["full_turn"])

    def test_opposite_handedness_is_detected_and_matters(self):
        d = spiral(self.d / "neg", hand=-1)
        rep = self.audit(d, local_span_tol=0.5)
        self.assertEqual(rep["handedness"]["value"], -1)
        self.assertEqual(rep["mergers"]["outer"], 0)
        self.assertFalse(rep["gate"]["local_failed"])
        forced = self.audit(d, pitch=20.0, handedness="1", local_span_tol=0.5)
        self.assertEqual(forced["mergers"]["outer"], 0)          # one edge barely changes theta
        self.assertAlmostEqual(forced["component_table"][0]["phase_span"], 4.0, delta=0.05)
        self.assertTrue(forced["gate"]["local_failed"])           # the source's fixed sign would call it a fusion
        given = self.audit(d, pitch=20.0, local_span_tol=0.5)    # pitch given, sign still found from the grid
        self.assertEqual(given["handedness"]["value"], -1)
        self.assertTrue(given["handedness"]["source"].startswith("auto"))

    def test_a_wrong_pitch_moves_the_counts(self):
        d = spiral(self.d / "switch", switch=(5, 15, 300))
        good = self.audit(d, pitch=20.0)
        source_default = self.audit(d, pitch=9.5)     # wind_audit's built-in default
        self.assertEqual(good["mergers"]["full_turn"], self.audit(d)["mergers"]["full_turn"])
        self.assertEqual(source_default["mergers"]["full_turn"], 0)              # dw = 20/9.5, about 2 turns
        self.assertEqual(source_default["mergers"]["outer"], good["mergers"]["full_turn"])
        self.assertGreater(source_default["mergers"]["histogram"]["1.30-2.30 (~2)"], 0)

    def test_pitch_table(self):
        t = meshqa.PitchTable([(50, 20), (450, 20)])
        self.assertAlmostEqual(float(t.dturns(np.array([60.0]), np.array([400.0]))[0]), 340 / 20)
        self.assertAlmostEqual(float(t.pitch_at(10.0)), 20.0)
        csv_path = self.d / "ramp.csv"
        csv_path.write_text("# measured\nr,pitch,count\n100,10,5\n200,30,5\n300,20,5\n")
        ramp = meshqa.PitchTable.load(csv_path)
        rs = 120.0 + (280.0 - 120.0) * (np.arange(200000) + 0.5) / 200000
        numeric = float(((280.0 - 120.0) / 200000 / ramp.pitch_at(rs)).sum())
        analytic = float(ramp.dturns(np.array([120.0]), np.array([280.0]))[0])
        self.assertAlmostEqual(analytic, numeric, places=6)
        self.assertAlmostEqual(float(ramp.dturns(np.array([280.0]), np.array([120.0]))[0]), -analytic, places=12)
        p = float(ramp.pitch_at(150.0))
        self.assertTrue(0.85 < float(ramp.dturns(np.array([150.0]), np.array([150.0 + p]))[0]) < 1.15)
        # beyond the knots the end pitches hold (table_turns_at): 50 voxels at 10, the two log segments, 100 at 20
        whole = (100 - 50) / 10 + math.log(30 / 10) / 0.2 + math.log(20 / 30) / -0.1 + (400 - 300) / 20
        self.assertAlmostEqual(float(ramp.dturns(np.array([50.0]), np.array([400.0]))[0]), whole, places=9)
        (self.d / "dup.csv").write_text("r,pitch\n100,10\n100,12\n")
        with self.assertRaises(meshqa.MeshQAError):
            meshqa.PitchTable.load(self.d / "dup.csv")
        (self.d / "flat.csv").write_text("r,pitch\n50,20\n450,20\n")
        d = spiral(self.d / "switch", switch=(5, 15, 300))
        a, b = self.audit(d, pitch=20.0), self.audit(d, pitch_table=self.d / "flat.csv")
        self.assertEqual(b["pitch"]["source"], "table at the median radius")
        self.assertEqual((a["mergers"]["full_turn"], a["mergers"]["histogram"]),
                         (b["mergers"]["full_turn"], b["mergers"]["histogram"]))

    def test_umbilicus_file_matches_fixed_centre_and_centre_at(self):
        d = spiral(self.d / "switch", switch=(5, 15, 300))
        umb = self.d / "umb.json"
        umb.write_text(json.dumps([[0, 400.0, 500.0], [1000, 400.0, 500.0]]))
        a = self.audit(d, pitch=20.0)
        b = meshqa.wind_audit(d, umbilicus=umb, pitch=20.0)
        self.assertEqual(a["mergers"], b["mergers"])
        pts = vc3d_orient.parse_umbilicus("0, 10, 20\n50, 14, 30\n50, 18, 34\n120, 2, 8\n")
        axis = meshqa.Axis(points=pts)
        zs = np.array([-5.0, 0.0, 10.0, 49.9, 50.0, 50.1, 119.0, 120.0, 300.0])
        cx, cy = axis.centre(np, zs)
        for z, x, y in zip(zs, cx, cy):
            ex, ey = vc3d_orient.centre_at(pts, float(z))
            self.assertAlmostEqual(x, ex)
            self.assertAlmostEqual(y, ey)
        with self.assertRaises(meshqa.MeshQAError):
            meshqa.wind_audit(d, pitch=20.0)                           # neither umbilicus nor centre

    def test_a_non_finite_axis_is_refused_not_passed(self):
        d = spiral(self.d / "switch", switch=(5, 15, 300))
        umb = self.d / "umb.txt"
        umb.write_text("0, nan, 500\n1000, 400, 500\n")
        with self.assertRaises(meshqa.MeshQAError):
            meshqa.wind_audit(d, umbilicus=umb, pitch=20.0)
        for axis in (["--umbilicus", str(umb)], ["--centre", "nan", "400"]):
            code, _, err = run_cli(["meshqa", "windaudit", str(d), *axis, "--pitch", "20", "--fail-on-local"])
            self.assertEqual(code, 2, axis)
            self.assertIn("not finite", err)

    def test_split_contact_between_components(self):
        d = spiral(self.d / "split", hole_col=100)
        rep = self.audit(d, pitch=20.0)
        self.assertEqual(rep["components"], 2)
        s = rep["splits"]
        self.assertGreater(s["pairs"], 0)
        self.assertEqual(s["component_pairs"], 1)
        top = s["top"][0]
        self.assertEqual((top["a"], top["b"]), (0, 1))
        q = meshqa.load_patch(d)
        P = np.stack([q.x, q.y, q.z], -1).astype(float)
        self.assertAlmostEqual(top["min_gap"], float(np.linalg.norm(P[:, 99] - P[:, 101], axis=1).min()), places=3)
        self.assertLessEqual(abs(top["representative"]["dw"]), 0.25)
        self.assertEqual(rep["mergers"]["full_turn"], 0)
        off = self.audit(spiral(self.d / "split2", hole_col=100), pitch=20.0, split_audit=False)
        self.assertEqual(off["splits"]["pairs"], 0)
        # at pitch 10 the next wrap is within --split-gap too; those contacts are a turn off and left out, as by
        # the compiled wind_audit.c on this mesh (94 pairs, and 19,014 with --split-wtol 1.5)
        tight = spiral(self.d / "split10", pitch=10.0, hole_col=100)
        self.assertEqual(self.audit(tight, pitch=10.0)["splits"]["pairs"], s["pairs"])
        self.assertEqual(s["pairs"], 94)
        self.assertEqual(self.audit(tight, pitch=10.0, split_wtol=1.5)["splits"]["pairs"], 19014)

    def test_core_edges_are_kept_apart_from_outer_ones(self):
        d = spiral(self.d / "switch", switch=(5, 15, 300))
        counts = []
        for core in (3.0, 11.5, 20.0):        # core radius 60, 230 (inside the switched radii 222 to 260), 400
            m = self.audit(d, pitch=20.0, core_pitches=core)["mergers"]
            counts.append((m["outer"], m["core"], m["full_turn"]))
        self.assertEqual(counts, [(1030, 0, 1030), (555, 475, 555), (0, 1030, 0)])   # as wind_audit.c counts them
        self.assertFalse(self.audit(d, pitch=20.0, core_pitches=20.0)["gate"]["local_failed"])

    def test_runs_that_start_on_another_branch_are_unwrapped_to_their_neighbours(self):
        # rows 10 to 19 start at column 400, 1.45 turns in, where atan2 reads 0.45 turns: their run must be
        # shifted by one whole turn to meet row 9, or the phase would jump by two turns at the join
        d = spiral(self.d / "late", holes=[(10, 20, 0, 400)])
        rep = self.audit(d, pitch=20.0, local_span_tol=0.5)
        c = rep["component_table"][0]
        self.assertEqual(rep["components"], 1)
        self.assertLess(c["phase_span"], 0.01)
        self.assertAlmostEqual(c["turns"], 2.0, delta=0.05)
        self.assertFalse(rep["gate"]["local_failed"])

    def test_interior_hole_topology(self):
        X, Y, Z = plane((12, 12), origin=(600.0, 400.0, 100.0), spacing=4.0)
        X[5:7, 5:7] = -1
        rep = meshqa.wind_audit(write_patch(self.d / "hole", X, Y, Z), centre=(0.0, 0.0), pitch=20.0)
        c = rep["component_table"][0]
        self.assertEqual((c["boundary_loops"], c["euler_chi"], c["genus"]), (2, 0, 0.0))

    def test_obj_vertex_order_is_vc_tifxyz2obj_first_use(self):
        rng = np.random.default_rng(3)
        valid = rng.random((9, 11)) < 0.8
        Q, _, _, order, _ = meshqa._grid_mesh(np, valid)
        seen, ref = set(), []
        for j in range(8):
            for i in range(10):
                if Q[j, i]:
                    for rc in ((j, i), (j, i + 1), (j + 1, i), (j + 1, i + 1)):
                        if rc not in seen:
                            seen.add(rc)
                            ref.append(rc[0] * 11 + rc[1])
        self.assertEqual(order.tolist(), ref)

    def test_auto_pitch_refuses_a_small_patch(self):
        d = spiral(self.d / "small", turns=0.3)
        with self.assertRaises(meshqa.MeshQAError):
            self.audit(d)
        code, _, err = run_cli(["meshqa", "windaudit", str(d), "--centre", "500", "400"])
        self.assertEqual(code, 2)
        self.assertIn("--pitch", err)
        rep = self.audit(d, pitch=20.0)
        self.assertEqual(rep["handedness"]["value"], 1)
        self.assertIn("source default", rep["handedness"]["source"])
        self.assertEqual(rep["mergers"]["outer"], 0)

    def test_auto_pitch_says_why_it_failed(self):
        # too little of a turn, and two turns crushed to 70 % along x: both refused, each with its own reason, so a
        # caller (autopipe's qa) need not tell them apart by message; both name --pitch auto
        with self.assertRaises(meshqa.PitchFitError) as small:
            self.audit(spiral(self.d / "small", turns=0.3))
        self.assertEqual(small.exception.reason, "span")
        crushed = spiral(self.d / "crushed", crush=0.7)
        with self.assertRaises(meshqa.PitchFitError) as flat:
            self.audit(crushed)
        self.assertEqual(flat.exception.reason, "concentration")
        self.assertIn("--pitch auto", str(flat.exception))
        self.assertIsInstance(flat.exception, meshqa.MeshQAError)   # the CLI and older callers still catch it
        code, _, err = run_cli(["meshqa", "windaudit", str(crushed), "--centre", "500", "400"])
        self.assertEqual(code, 2)
        self.assertIn("concentration", err)
        rep = self.audit(spiral(self.d / "whole"))                  # the same two turns uncrushed: fitted
        self.assertGreater(rep["pitch"]["auto"]["concentration"], 0.99)

    def test_cli_round_trip_gate_and_png(self):
        d = spiral(self.d / "switch", switch=(5, 15, 300))
        png = self.d / "flags.png"
        code, text, _ = run_cli(["meshqa", "windaudit", str(d), "--centre", "500", "400", "--pitch", "20", "--json",
                                 "--png", str(png)])
        self.assertEqual(code, 0)
        rep = json.loads(text)
        self.assertGreater(rep["mergers"]["full_turn"], 0)
        h, w, channels, pix = vc3d_io.read_png_gray(png.read_bytes())
        self.assertEqual(channels, 1)
        self.assertEqual((h, w), tuple(rep["grid"]))
        pix = np.frombuffer(bytes(pix), np.uint8).reshape(h, w)
        self.assertTrue((pix[5:15, 300] == 255).all() and (pix[5:15, 299] == 255).all())
        self.assertEqual(int(pix[0, 0]), 60)
        code, text, _ = run_cli(["meshqa", "windaudit", str(d), "--centre", "500", "400", "--pitch", "20",
                                 "--fail-on-local"])
        self.assertEqual(code, 4)
        self.assertIn("FULL-TURN fusions", text)
        self.assertIn("local gate: FAIL", text)
        clean = spiral(self.d / "clean")
        self.assertEqual(run_cli(["meshqa", "windaudit", str(clean), "--centre", "500", "400",
                                  "--fail-on-local"])[0], 0)
        self.assertEqual(run_cli(["meshqa", "windaudit", str(clean), "--centre", "500", "400", "--pitch", "x"])[0], 2)


def block(v, z0, z1, y0, y1, x0, x1, value=255):
    v[z0:z1, y0:y1, x0:x1] = value


def source_cases(n=64):
    """The eight synthetic volumes of PredReject_selftest, with the verdict and empty flag it expects."""
    out = []
    v = np.zeros((n,) * 3, np.uint8)
    block(v, 12, 52, 12, 52, 12, 52)
    out.append(("solid 40^3 slab", v, 1, 0))
    v = np.zeros((n,) * 3, np.uint8)
    block(v, 0, n, 20, 22, 0, n)
    block(v, 0, n, 0, n, 40, 42)
    out.append(("two 2-voxel sheets", v, 0, 0))
    v = np.zeros((n,) * 3, np.uint8)
    block(v, 30, 32, 7, 57, 7, 57)
    out.append(("flat face-on patch", v, 0, 0))
    v = np.zeros((n,) * 3, np.uint8)
    block(v, 10, 50, 10, 50, 10, 45)
    block(v, 28, 31, 28, 31, 45, 60)
    out.append(("slab and protrusion", v, 1, 0))
    out.append(("empty", np.zeros((n,) * 3, np.uint8), 1, 1))
    v = np.zeros((n,) * 3, np.uint8)
    block(v, 20, 27, 20, 27, 20, 27)
    out.append(("tiny speck", v, 1, 1))
    v = np.zeros((n,) * 3, np.uint8)
    block(v, 30, 31, 10, 35, 10, 35)
    out.append(("small sheet", v, 0, 0))
    v = np.zeros((n,) * 3, np.uint8)
    block(v, 4, 11, 4, 11, 4, 11)
    block(v, 4, 11, 4, 11, 40, 47)
    block(v, 40, 47, 40, 47, 40, 47)
    out.append(("sub-threshold scatter", v, 1, 1))
    return out


def write_zarr(path, arr, chunk=32):
    """A one-level OME-Zarr group of a uint8 array, uncompressed (as tests/test_vc3d_landmarks.py writes it)."""
    p = Path(path)
    (p / "0").mkdir(parents=True, exist_ok=True)
    (p / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (p / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4", "axes": [
        {"name": a, "type": "space"} for a in "zyx"], "datasets": [{"path": "0", "coordinateTransformations": [
            {"type": "scale", "scale": [1.0, 1.0, 1.0]}]}]}]}))
    (p / "0" / ".zarray").write_text(json.dumps({
        "zarr_format": 2, "shape": list(arr.shape), "chunks": [chunk] * 3, "dtype": "|u1", "compressor": None,
        "fill_value": 0, "filters": None, "order": "C", "dimension_separator": "/"}))
    for iz in range(-(-arr.shape[0] // chunk)):
        for iy in range(-(-arr.shape[1] // chunk)):
            for ix in range(-(-arr.shape[2] // chunk)):
                blk = np.zeros((chunk,) * 3, np.uint8)
                part = arr[iz * chunk:(iz + 1) * chunk, iy * chunk:(iy + 1) * chunk, ix * chunk:(ix + 1) * chunk]
                blk[:part.shape[0], :part.shape[1], :part.shape[2]] = part
                out = p / "0" / str(iz) / str(iy) / str(ix)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blk.tobytes())
    return p


@unittest.skipIf(np is None, "numpy is needed for kit meshqa predcubes")
class PredCubesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_source_selftest_cases(self):
        for name, vol, verdict, empty in source_cases():
            with self.subTest(name):
                st = meshqa.pred_reject(vol)
                self.assertEqual((st["verdict"], st["empty"]), (verdict, empty), st["reason"])
        st = meshqa.pred_reject(source_cases()[0][1])
        self.assertEqual(st["reason"], "reject: solid slab")
        self.assertEqual((st["max_rect_run"], st["max_thickness"]), (40, 17))
        self.assertEqual(meshqa.pred_reject(source_cases()[2][1])["reason"], "keep: thin (low erosion interior)")
        self.assertEqual(meshqa.pred_reject(source_cases()[7][1])["largest_cc"], 343)

    def test_erosion_counts_borders_as_background(self):
        v = np.ones((5, 5, 5), bool)
        once, n1 = meshqa.erode6(np, v)
        self.assertEqual(n1, 27)
        self.assertTrue(once[1:4, 1:4, 1:4].all())
        self.assertEqual(meshqa.erode6(np, once)[1], 1)

    def test_thick_but_not_rectangular_is_kept(self):
        zz, yy, xx = np.mgrid[0:64, 0:64, 0:64]
        octa = (abs(zz - 32) + abs(yy - 32) + abs(xx - 32)) <= 28     # thick; each slice is a diamond, half its box
        st = meshqa.pred_reject(octa.astype(np.uint8))
        self.assertGreater(st["interior_frac"], 0.5)
        self.assertEqual((st["verdict"], st["reason"]), (0, "keep: not a persistent rectangle"))
        ball = ((zz - 32) ** 2 + (yy - 32) ** 2 + (xx - 32) ** 2) <= 18 ** 2
        st = meshqa.pred_reject(ball.astype(np.uint8))          # a disc fills pi/4 of its box, over the 0.75 bar
        self.assertEqual((st["verdict"], st["reason"]), (1, "reject: solid slab"))

    def test_float32_bars_ties_and_floors_as_the_source(self):
        # every expected value below is what the compiled pred_reject.c gives on the same volume
        v = np.zeros((65, 64, 64), np.uint8)
        v[10:23, 16:47, 16:47] = 1                  # rectangle frames on 13 of 65 slices: 0.2 in double, under 0.2f
        st = meshqa.pred_reject(v)
        self.assertEqual((st["rect_axis"], st["rect_frac"], st["max_rect_run"]), (0, 0.2, 13))
        self.assertEqual((st["verdict"], st["reason"]), (0, "keep: not a persistent rectangle"))
        lr = np.zeros((40, 40, 40), np.uint8)
        lr[:, 0:21, 0:5] = lr[:, 0:5, 5:26] = 1      # an L of 210 voxels per slice, 38 percent of its box, met first
        lr[:, 25:40, 25:39] = 1                      # a filled 15 x 14 rectangle of the same 210 voxels
        rl = np.zeros_like(lr)
        rl[:, 0:15, 0:14] = 1                        # the same two shapes, rectangle first
        rl[:, 19:40, 13:18] = rl[:, 35:40, 18:39] = 1
        for vol, axis0, whole in ((lr, (0.0, 0), (2, 39)), (rl, (1.0, 40), (0, 40))):
            self.assertEqual(meshqa.axis_rect_scan(np, vol != 0, np.flatnonzero(vol), 0), axis0)
            st = meshqa.pred_reject(vol)
            self.assertEqual((st["rect_axis"], st["max_rect_run"]), whole)
        s = 10
        zz, yy, xx = np.indices((2 * s + 1,) * 3) - s
        bipyramid = (np.maximum(abs(yy), abs(xx)) + abs(zz)) <= s       # square slices; erodes to the s - 2 one
        st = meshqa.pred_reject(bipyramid.astype(np.uint8))
        self.assertGreater(st["interior_frac"], 0.5)
        self.assertEqual((st["interior_count"], st["max_rect_run"]), (1649, 15))    # rectangles, but under 2,000
        self.assertEqual((st["verdict"], st["reason"]), (0, "keep: thin (low erosion interior)"))

    def test_threshold_is_value_at_or_above_in_the_volume_type(self):
        f = np.zeros((40, 40, 40), np.float32)
        f[5:35, 5:35, 5:35] = 0.7                    # float32 0.7 is just under the double 0.7
        self.assertEqual(meshqa.pred_reject(f, 0.7)["largest_cc"], 27000)
        self.assertEqual(meshqa.pred_reject(f, np.float32(0.7))["largest_cc"], 27000)
        self.assertEqual(meshqa.pred_reject(f, 0.71)["empty"], 1)

    @unittest.skipIf(ndimage is None, "scipy is only used to cross-check the labelling")
    def test_labelling_matches_scipy(self):
        rng = np.random.default_rng(1)
        for p in (0.2, 0.3, 0.5):
            fg = rng.random((30, 40, 25)) < p
            idx = np.flatnonzero(fg)
            lab, n = ndimage.label(fg)
            self.assertEqual(meshqa.largest_cc6(np, fg, idx), int(np.bincount(lab.ravel())[1:].max()))
            roots = meshqa._label(np, fg, idx, (0, 1, 2))
            self.assertEqual(len(np.unique(lab.ravel()[idx] * (idx.size + 1) + roots)), n)
            for ax in range(3):
                st = np.zeros((3, 3, 3), bool)
                st[1, 1, 1] = True
                for q in (a for a in range(3) if a != ax):
                    s = [1, 1, 1]
                    s[q] = 0
                    st[tuple(s)] = True
                    s[q] = 2
                    st[tuple(s)] = True
                lab2, n2 = ndimage.label(fg, structure=st)
                r2 = meshqa._label(np, fg, idx, tuple(a for a in range(3) if a != ax))
                self.assertEqual(len(np.unique(r2)), n2)
                self.assertEqual(len(np.unique(lab2.ravel()[idx] * (idx.size + 1) + r2)), n2)

    def row_volume(self):
        cases = {name: vol for name, vol, _, _ in source_cases()}
        return np.concatenate([cases["solid 40^3 slab"], cases["two 2-voxel sheets"], cases["empty"]], axis=2)

    def test_zarr_region_cli_round_trip(self):
        z = write_zarr(self.d / "pred.zarr", self.row_volume())
        csv_path, rej = self.d / "stats.csv", self.d / "reject.txt"
        code, text, err = run_cli(["meshqa", "predcubes", str(z), "--cube", "64", "--csv", str(csv_path),
                                   "--out", str(rej)])
        self.assertEqual(code, 0)
        lines = text.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("z00000_y00000_x00000") and "reject: solid slab" in lines[0])
        self.assertIn("keep: thin", lines[1])
        self.assertIn("reject: empty", lines[2])
        self.assertIn("3 cubes -> 2 REJECT (1 slab, 1 empty), 1 keep, 0 err", err)
        self.assertEqual(rej.read_text().split(), ["z00000_y00000_x00000", "z00000_y00000_x00128"])
        rows = csv_path.read_text().splitlines()
        self.assertEqual(rows[0].split(","), list(meshqa.CSV_COLUMNS))
        self.assertTrue(rows[1].startswith("z00000_y00000_x00000,1,"))
        code, text, _ = run_cli(["meshqa", "predcubes", str(z), "--cube", "64", "--box", "0", "64", "0", "64",
                                 "70", "90", "--json"])
        rep = json.loads(text)
        self.assertEqual([c["cube_id"] for c in rep["cubes"]], ["z00000_y00000_x00064"])
        self.assertFalse(rep["cubes"][0]["partial"])

    def test_npy_partial_cubes_threshold_and_limits(self):
        vol = np.zeros((64, 64, 100), np.uint8)
        block(vol, 12, 52, 12, 52, 12, 52, value=50)       # faint slab
        block(vol, 0, 64, 20, 22, 0, 64, value=200)         # a sheet through it
        path = self.d / "cube.npy"
        np.save(path, vol)
        rep = meshqa.pred_cubes(path, cube=64)
        self.assertEqual([c["cube_id"] for c in rep["cubes"]], ["z00000_y00000_x00000", "z00000_y00000_x00064"])
        self.assertEqual([c["partial"] for c in rep["cubes"]], [False, True])
        self.assertEqual(rep["cubes"][0]["reason"], "reject: solid slab")
        strict = meshqa.pred_cubes(path, cube=64, threshold=128)
        self.assertEqual(strict["cubes"][0]["verdict"], 0)
        self.assertEqual(strict["threshold"], 128)
        with self.assertRaises(meshqa.MeshQAError):
            meshqa.pred_cubes(path, cube=8, max_cubes=10)
        code, _, err = run_cli(["meshqa", "predcubes", str(path), "--cube", "8", "--max-cubes", "10"])
        self.assertEqual(code, 2)
        self.assertIn("--max-cubes", err)
        self.assertEqual(meshqa.cube_boxes([64, 64, 100], [[0, 10], [0, 10], [65, 70]], 64),
                         [[[0, 64], [0, 64], [64, 100]]])


class MeshQAStandardLibraryTest(unittest.TestCase):
    def test_pitch_fit_error_survives_pickle_and_copy(self):
        # a process pool pickles an exception to send it back; without __reduce__ that raised a TypeError (the
        # reason missing) in place of the real error
        import copy
        import pickle
        e = meshqa.PitchFitError("--pitch auto: the best pitch leaves a winding concentration of 0.30", "concentration")
        for back in (pickle.loads(pickle.dumps(e)), copy.copy(e), copy.deepcopy(e)):
            self.assertIs(type(back), meshqa.PitchFitError)
            self.assertEqual((str(back), back.reason), (str(e), "concentration"))
            self.assertIsInstance(back, meshqa.MeshQAError)

    def test_help_without_numpy(self):
        code = ("import sys; sys.modules['numpy'] = None; sys.modules['tifffile'] = None\n"
                "from kit import cli\n"
                "try:\n    cli.main(['meshqa', '--help'])\nexcept SystemExit as e:\n    sys.exit(e.code)\n")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("windaudit", r.stdout)

    def test_missing_numpy_is_a_clear_error(self):
        code = ("import sys; sys.modules['numpy'] = None\n"
                "from kit import cli\n"
                "sys.exit(cli.main(['meshqa', 'predcubes', 'nothing.npy']))\n")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs numpy", r.stderr)


def write_support_grid(folder, X, Y, Z):
    """A tifxyz folder of float32 x, y, z rasters (uncompressed) and a minimal meta.json."""
    p = Path(folder)
    p.mkdir(parents=True, exist_ok=True)
    for name, a in zip("xyz", (X, Y, Z)):
        tifffile.imwrite(str(p / f"{name}.tif"), np.asarray(a, np.float32))
    (p / "meta.json").write_text(json.dumps({"type": "seg", "format": "tifxyz", "scale": [1.0, 1.0]}))
    return p


@unittest.skipIf(np is None or tifffile is None, "numpy and tifffile are needed for kit meshqa support")
class SupportTest(unittest.TestCase):
    """kit meshqa support: villa PR #1906's on-prediction share against a background rate, plus a moved control."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        v = np.zeros((96, 96, 96), np.uint8)
        for z in (14, 46, 78):                       # three sheets, 5 voxels thick, 32 voxels apart
            v[z:z + 5] = 200
        self.pred = write_zarr(self.d / "pred.zarr", v)
        yy, xx = np.mgrid[16:80, 16:80].astype(np.float32)
        self.flat = write_support_grid(self.d / "flat", xx, yy, np.full_like(xx, 48.0))
        # Rows climb 1 voxel per row through the sheets: a surface that cuts across windings.
        self.tilt = write_support_grid(self.d / "tilt", xx, yy, 16.0 + (yy - 16.0))

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["meshqa", "support", *map(str, argv), "--json"])
        return code, json.loads(out.getvalue())

    def test_sheet_following_surface_passes_and_its_moved_copy_is_caught(self):
        code, rep = self.run_cli(self.flat, self.pred, "--shift", 12, "--strict")
        self.assertEqual(code, 0)
        self.assertEqual(rep["verdict"], "pass", rep["reasons"])
        self.assertEqual(rep["surface"]["share"], 1.0)
        self.assertLess(rep["background"]["share"], 0.3)          # about 15 sheet voxels in 96
        self.assertEqual(rep["shifted"]["share"], 0.0)
        self.assertTrue(rep["shifted"]["caught"])

    def test_surface_across_windings_warns(self):
        code, rep = self.run_cli(self.tilt, self.pred, "--strict")
        self.assertEqual(code, 3)
        self.assertEqual(rep["verdict"], "warn")
        self.assertLess(rep["surface"]["share"], 0.4)
        self.assertTrue(any("under 0.4" in r for r in rep["reasons"]))

    def test_dense_prediction_is_no_better_than_background(self):
        dense = write_zarr(self.d / "dense.zarr", np.full((96, 96, 96), 200, np.uint8))
        code, rep = self.run_cli(self.flat, dense, "--shift", 12)
        self.assertEqual(code, 0)                                   # report only without --strict
        self.assertEqual((rep["surface"]["share"], rep["background"]["share"]), (1.0, 1.0))
        self.assertEqual(rep["verdict"], "warn")
        self.assertFalse(rep["shifted"]["caught"])                  # the check could not have failed here
        self.assertTrue(any("background" in r for r in rep["reasons"]))

    def test_within_reaches_a_nearby_sheet_and_background_is_reproducible(self):
        X, Y, Z = (tifffile.imread(str(self.flat / f"{a}.tif")) for a in "xyz")
        from kit import vc3d_region
        off = Z + 4.0                                               # 2 voxels above the sheet's top face (z 50)
        r0 = meshqa.surface_support(X, Y, off, vc3d_region.Volume(self.pred))
        r3 = meshqa.surface_support(X, Y, off, vc3d_region.Volume(self.pred), within=3)
        self.assertEqual(r0["surface"]["share"], 0.0)
        self.assertEqual(r3["surface"]["share"], 1.0)
        again = meshqa.surface_support(X, Y, off, vc3d_region.Volume(self.pred))
        self.assertEqual(again["background"], r0["background"])

    def test_bad_margin_and_empty_surface_are_errors(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            self.assertEqual(cli.main(["meshqa", "support", str(self.flat), str(self.pred), "--margin", "2"]), 2)
        self.assertIn("--margin must be within [0, 1]", out.getvalue())
        X = np.full((4, 4), -1.0)
        from kit import vc3d_region
        with self.assertRaises(meshqa.MeshQAError):
            meshqa.surface_support(X, X, X, vc3d_region.Volume(self.pred))

    def test_background_off_is_not_a_warning(self):
        code, rep = self.run_cli(self.flat, self.pred, "--background", 0, "--strict")
        self.assertEqual(code, 0)
        self.assertEqual(rep["verdict"], "pass", rep["reasons"])
        self.assertIsNone(rep["background"]["share"])
        self.assertIn("off", rep["background"]["unavailable"])
        # A flat box (dilate 0 on a level surface) is still sampled: here it is the surface's own plane, all on
        # the sheet, so the margin test rightly warns.
        code, rep = self.run_cli(self.flat, self.pred, "--dilate", 0)
        self.assertEqual((rep["background"]["points"], rep["background"]["share"]), (2000, 1.0))

    def test_shift_scores_the_same_vertices_and_judges_only_a_passing_surface(self):
        X, Y, Z = (tifffile.imread(str(self.flat / f"{a}.tif")).astype(np.float64) for a in "xyz")
        holes = np.random.default_rng(1).random(X.shape) < 0.1
        X[holes] = -1
        from kit import vc3d_region
        plain = meshqa.surface_support(X, Y, Z, vc3d_region.Volume(self.pred))
        moved = meshqa.surface_support(X, Y, Z, vc3d_region.Volume(self.pred), shift=12)
        self.assertEqual(plain["surface"], moved["surface"])          # the control does not change the main share
        self.assertLess(moved["shifted"]["points"], moved["surface"]["points"])
        self.assertEqual(moved["shifted"]["unshifted_share"], 1.0)
        code, rep = self.run_cli(self.tilt, self.pred, "--shift", 12)
        self.assertFalse(rep["shifted"]["caught"])
        self.assertEqual(rep["verdict"], "warn")
        self.assertFalse(any("cannot fail here" in r for r in rep["reasons"]))
        code, rep = self.run_cli(self.flat, self.pred, "--shift", 32)      # one sheet spacing: lands on a sheet
        self.assertTrue(any("cannot fail here" in r for r in rep["reasons"]))

    def test_verdict_uses_exact_fractions_and_1906s_margin_rule(self):
        def fake(surface, background):
            def on_share(vol, level, pts, dirs, threshold, within):
                d = surface if len(pts) != 2000 else background
                return dict(d, outside=0, share=round(d["on"] / d["points"], 4))
            return on_share
        X, Y, Z = (tifffile.imread(str(self.flat / f"{a}.tif")) for a in "xyz")
        from kit import vc3d_region
        vol = vc3d_region.Volume(self.pred)
        with mock.patch.object(meshqa, "_on_share", fake({"points": 25000, "on": 9999},
                                                         {"points": 2000, "on": 0})):
            rep = meshqa.surface_support(X, Y, Z, vol)
        self.assertEqual(rep["surface"]["share"], 0.4)                 # shown rounded, judged exactly
        self.assertTrue(any("under 0.4" in r for r in rep["reasons"]))
        with mock.patch.object(meshqa, "_on_share", fake({"points": 2000 * 2, "on": 1100 * 2},
                                                         {"points": 2000, "on": 900})):
            rep = meshqa.surface_support(X, Y, Z, vol)                 # 0.55 against 0.45 + 0.1: a tie warns
        self.assertEqual(rep["verdict"], "warn")
        self.assertTrue(any("background" in r for r in rep["reasons"]))

    def test_unreadable_inputs_and_bad_options_exit_2(self):
        bad = self.d / "bad.zarr"
        write_zarr(bad, np.zeros((64, 64, 64), np.uint8))
        (bad / "0" / "1" / "1" / "1").write_bytes(b"abc")
        for argv, text in (([self.flat, self.d / "nope.zarr"], "cannot open"),
                           ([self.flat, bad], "chunk"),
                           ([self.flat, self.pred, "--background", "-1"], "--background"),
                           ([self.flat, self.pred, "--within", "-1"], "--within"),
                           ([self.flat, self.pred, "--stride", "0"], "--stride")):
            err = io.StringIO()
            with self.subTest(text), contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["meshqa", "support", *map(str, argv)]), 2)
                self.assertTrue(err.getvalue().startswith("kit meshqa support:"), err.getvalue())
                self.assertIn(text, err.getvalue())


if __name__ == "__main__":
    unittest.main()
