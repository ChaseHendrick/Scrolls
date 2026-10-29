"""kit apcouple: AutoPipeline's coupled steps (labels, fibers, joins) on synthetic data.

Parity: each step's output equals its own tool run alone on the same input (kit labelsnap snap, weft_trace.py crop,
the kollesis finder's frame, extract, features and kfh1). Also the run-folder contracts, chain and swap and diff,
the scaled kollesis reader, and the AutoPipeline wiring (backend tables, plan settings, the stage registry).
Numerical tests skip without numpy, scipy and numcodecs.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from kit import apcouple as C

ROOT = Path(__file__).resolve().parents[1]
try:
    import numpy as np
    import numcodecs  # noqa: F401
    import scipy  # noqa: F401
    HAVE = True
except ImportError:  # pragma: no cover - the core kit is standard library only
    np = None
    HAVE = False

if HAVE:
    from kit import labelsnap as L
    from kit import snap
    from tests.test_snap import write_zarr
    from tests.test_snap_face import GAPS, LADDER_W, ladder_volume
    sys.path.insert(0, str(ROOT / "scripts" / "afvfibers"))
    import weft_trace as w
    from tests.test_weft_trace import LEVEL, SHAPE2, native_tube, write_blocks


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return fn(*a, **k)


def vertical_ladder(root):
    """The gap ladder of tests/test_snap_face.py turned so its sheets are planes of constant x (z runs along the
    ladder), a mesh at x = 30.4 inside the middle sheet, and a vertical scroll axis at x = -400 (the recto face is
    toward smaller x)."""
    v = ladder_volume(1.0, 0.0).transpose(2, 1, 0).copy()        # (nx, 24, 64): z, y, x
    write_zarr(root / "ladder.zarr", v)
    H, W = 9, LADDER_W * len(GAPS)
    r, c = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    xs = np.full((H, W), 30.4, np.float32)
    ys = (8.0 + r).astype(np.float32)
    zs = (4.0 + c).astype(np.float32)
    snap.write_mesh(None, root / "label", xs, ys, zs, np.ones(xs.shape, bool), {}, "synthetic")
    (root / "umbilicus.json").write_text(json.dumps([[0, 12, -400], [v.shape[0], 12, -400]]))
    return root / "label", root / "ladder.zarr", root / "umbilicus.json"


@unittest.skipUnless(HAVE, "needs numpy, scipy and numcodecs")
class LabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.surf, cls.vol, cls.umb = vertical_ladder(cls.root)
        cls.rdir = cls.root / "run"
        C.init(cls.rdir, [("s00", cls.surf)], cls.vol, 9.362, cls.umb, "TEST")
        cls.rec = C.run_labels(cls.rdir, {"method": "snapped"})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_snapped_matches_kit_labelsnap_run_alone(self):
        alone = self.root / "alone"
        args = C.labels_args(self.surf, self.vol, alone, C.settings_for("labels"), self.umb)
        code = quiet(L.main, ["snap"] + args)
        self.assertEqual(code, 0)
        mine = self.rdir / "labels" / "s00"
        files = sorted(str(p.relative_to(alone)) for p in alone.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(str(p.relative_to(mine)) for p in mine.rglob("*") if p.is_file()))
        for f in files:
            if f == "labelsnap.json":
                a, b = (json.loads((d / f).read_text().replace(str(d), "OUT")) for d in (alone, mine))
                a.pop("seconds"), b.pop("seconds")
                self.assertEqual(a, b)
            elif f in ("review.json", "snapped.tifxyz/meta.json"):
                continue        # they name the output folder and the time
            else:
                self.assertEqual((alone / f).read_bytes(), (mine / f).read_bytes(), f)

    def test_snapped_record_and_later_steps_read_the_snapped_surface(self):
        s = self.rec["surfaces"]["s00"]
        self.assertEqual(s["method"], "snapped")
        self.assertTrue(s["surface"].endswith("snapped.tifxyz"))
        self.assertEqual(s["surface"], "labels/s00/snapped.tifxyz")     # relative: the folder can move
        self.assertEqual(C.surface_of(self.rdir, "s00"), str(self.rdir / s["surface"]))
        self.assertGreater(s["record"]["vertices"]["measured"], 0)
        self.assertEqual(C.check_run(self.rdir), [])

    def test_mesh_baseline_writes_the_unsnapped_label(self):
        run = self.root / "run_mesh"
        C.init(run, [("s00", self.surf)], self.vol, 9.362, self.umb, "TEST")
        rec = C.run_labels(run, {"method": "mesh"})
        s = rec["surfaces"]["s00"]
        self.assertEqual(s["surface"], str(self.surf.resolve()))
        self.assertGreater(s["record"]["label"]["voxels"]["surface"], 0)
        self.assertEqual(s["record"]["label"]["voxels"]["ignore"], 0)
        self.assertNotEqual(rec["digests"]["s00"], self.rec["digests"]["s00"])

    def test_snapped_needs_the_axis(self):
        run = self.root / "run_noaxis"
        C.init(run, [("s00", self.surf)], self.vol, 9.362, None, "TEST")
        with self.assertRaises(C.CoupleError):
            C.run_labels(run, {"method": "snapped"})

    def test_swap_labels_mesh_against_snapped(self):
        rec = C.swap(self.rdir, "labels", "mesh", "snapped")
        self.assertIn("labels", rec["changed"])
        self.assertEqual(set(rec["arms"]), {"mesh", "snapped"})
        for arm in rec["arms"].values():
            self.assertIn("labels", arm["records"])
        self.assertTrue((self.rdir / "swap-labels-mesh-snapped.json").is_file())

    def test_a_moved_run_folder_still_checks(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "run_in"
            (run / "input").mkdir(parents=True)
            shutil.copytree(self.surf, run / "input" / "s00")
            shutil.copy2(self.umb, run / "umbilicus.json")
            C.init(run, [("s00", run / "input" / "s00")], self.vol, 9.362, run / "umbilicus.json", "TEST")
            quiet(C.run_labels, run, {"method": "snapped"})
            sw = quiet(C.swap, run, "labels", "mesh", "snapped")
            moved = Path(d) / "moved"
            shutil.move(str(run), str(moved))
            self.assertEqual(C.check_run(moved), [])
            for arm in sw["arms"].values():                     # the swap arms move with their run
                self.assertEqual(C.check_run(moved / arm["folder"]), [])
            self.assertTrue(Path(C.surface_of(moved, "s00")).is_dir())

    def test_swap_keeps_the_swapped_stages_own_settings(self):
        run = self.root / "run_swapset"
        C.init(run, [("s00", self.surf)], self.vol, 9.362, self.umb, "TEST")
        quiet(C.run_labels, run, {"method": "mesh", "label_level": 0, "max_move": 2})
        rec = quiet(C.swap, run, "labels", "mesh", "snapped")
        arm = json.loads((run / rec["arms"]["snapped"]["folder"] / "labels.json").read_text())
        self.assertEqual(arm["settings"]["max_move"], 2)
        self.assertEqual(arm["settings"]["method"], "snapped")

    def test_swap_against_off_keeps_the_surface(self):
        rec = C.swap(self.rdir, "labels", "off", "mesh")
        self.assertEqual(rec["arms"]["off"]["steps"]["labels"], {"status": "off"})


def fiber_world(root):
    """Probability blocks with one H tube along z at level (y, x) = (30.2, 70.6), i.e. L0 x = 282.4, y = 120.8, and a
    surface: a plane of constant x = 282 over y 100 to 140, z 40 to 340 (L0)."""
    nat = np.zeros((2,) + SHAPE2, np.uint8)
    nat[1] = native_tube(SHAPE2, 0, (30.2, 70.6))
    blocks = root / "blocks"
    write_blocks(blocks, nat)
    vol = {"scan": "TEST", "level": LEVEL, "voxel_um": 9.596, "shape_zyx": list(SHAPE2), "block": 64,
           "coordinate_space": "TEST/0", "ct": "https://example.invalid/TEST/volumes/v.zarr/2"}
    (blocks / "volume.json").write_text(json.dumps(vol))
    r, c = np.meshgrid(np.arange(41), np.arange(301), indexing="ij")
    xs = np.full(r.shape, 282.0, np.float32)
    snap.write_mesh(None, root / "surf", xs, (100.0 + r).astype(np.float32), (40.0 + c).astype(np.float32),
                    np.ones(r.shape, bool), {}, "synthetic")
    return blocks, root / "surf"


@unittest.skipUnless(HAVE, "needs numpy, scipy and numcodecs")
class FibersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.blocks, cls.surf = fiber_world(cls.root)
        cls.rdir = cls.root / "run"
        C.init(cls.rdir, [("s00", cls.surf)], "https://example.invalid/TEST/volumes/v.zarr", 2.399, None, "TEST")
        cls.rec = quiet(C.run_fibers, cls.rdir, None, blocks=cls.blocks)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_weft_step_matches_weft_trace_crop_alone(self):
        s = self.rec["surfaces"]["s00"]
        alone = self.root / "alone.afv"
        rc = quiet(w.main, ["crop", "--volume", str(self.blocks / "volume.json"), "--blocks", str(self.blocks),
                            "--crop-l0", *[str(v) for v in s["box_l0"]], "--out", str(alone), "--halo", "64"])
        self.assertEqual(rc, 0)
        a, b = w.read_afv(alone), w.read_afv(str(C._at(self.rdir, s["afv"])))
        self.assertEqual(len(a), len(b))
        for (ia, fa, pa, na), (ib, fb, pb, nb) in zip(a, b):
            self.assertEqual((ia, fa), (ib, fb))
            self.assertTrue(np.array_equal(pa, pb))
            self.assertEqual(na, nb)

    def test_fibers_record(self):
        s = self.rec["surfaces"]["s00"]
        self.assertEqual(s["status"], "done")
        self.assertGreaterEqual(s["families"]["H"], 1)
        self.assertEqual(s["box_l0"][:2], [218, 347])          # x 282 - 64 to 282 + 1 + 64
        self.assertGreater(s["near_share"], 0.5)                 # the tube runs 0.4 voxels off the plane
        self.assertEqual(C.check_run(self.rdir), [])

    def test_fibers_that_do_not_read_back_whole_are_refused(self):
        run = self.root / "run_readback"
        C.init(run, [("s00", self.surf)], "https://example.invalid/TEST/volumes/v.zarr", 2.399, None, "TEST")
        real = w.read_afv
        w.read_afv = lambda path, *a, **k: []          # a file that reads back empty, as on a bucket mount
        try:
            with self.assertRaises(C.CoupleError):
                quiet(C.run_fibers, run, None, blocks=self.blocks)
        finally:
            w.read_afv = real

    def test_frame_check_refuses_another_scan(self):
        run = self.root / "run_other"
        C.init(run, [("s00", self.surf)], "https://example.invalid/OTHER/volumes/v.zarr", 2.399, None, "TEST")
        with self.assertRaises(C.CoupleError):
            quiet(C.run_fibers, run, None, blocks=self.blocks)

    def test_scan_without_maps_is_not_run(self):
        run = self.root / "run_nomaps"
        C.init(run, [("s00", self.surf)], "https://example.invalid/TEST/volumes/v.zarr", 2.399, None, "PHerc9999")
        rec = C.run_fibers(run)
        self.assertEqual(rec["surfaces"]["s00"]["status"], "not run")


class Sheet:
    """A synthetic CT in scan voxels: a bright sheet at x = 50 (Gaussian across it), brighter for y above 1300 (a
    thickened band at the join). Counts its calls."""

    def __init__(self):
        self.calls = 0

    def __call__(self, level, zyx):
        self.calls += 1
        q = np.asarray(zyx, float) * 2 ** int(level)
        v = 180 * np.exp(-((q[:, 2] - 50) ** 2) / 18.0) + 20
        v = v + 40 * (q[:, 1] > 1300) * np.exp(-((q[:, 2] - 50) ** 2) / 60.0)
        return np.clip(np.rint(v), 0, 255).astype(np.uint8)


def joins_world(root, um):
    """A surface: the plane x = 50 over y 0 to 1499, z 0 to 40 (scan voxels), and fibers.afv with one H fiber
    along y at z = 20 ending at y = 1400 (and starting at y = 1100), plus fibers.json naming it."""
    r, c = np.meshgrid(np.arange(41), np.arange(1500), indexing="ij")
    snap.write_mesh(None, root / "surf", np.full(r.shape, 50.0, np.float32), c.astype(np.float32),
                    r.astype(np.float32), np.ones(r.shape, bool), {}, "synthetic")
    run = root / "run"
    C.init(run, [("s00", root / "surf")], "https://example.invalid/T/v.zarr", um, None, "TEST")
    y = np.arange(1100.0, 1400.5, 2.0)
    fib = np.stack([np.full(len(y), 50.0), y, np.full(len(y), 20.0)], 1)
    afv = run / "fibers" / "s00.afv"
    w.write_afv([("H", fib, None)], afv, {"coordinate_base_shape_zyx": [41, 1500, 100]}, "test", {}, um)
    C._write(run / "fibers.json", {"version": 1, "stage": "fibers", "settings": C.settings_for("fibers"),
                                   "surfaces": {"s00": {"status": "done", "afv": str(afv)}}})
    return run, fib


@unittest.skipUnless(HAVE, "needs numpy, scipy and numcodecs")
class JoinsTest(unittest.TestCase):
    def test_scaled_reader_is_the_identity_in_the_frozen_frame(self):
        sheet = Sheet()
        q = np.array([[10.0, 700.2, 49.6], [3.0, 1350.0, 52.0]])
        rd = C.ScaledReader(sheet, C.KOLL_UM / 2.399, C.read_level(2.399))
        self.assertEqual(C.read_level(2.399), 1)
        self.assertEqual(C.read_level(9.362), 0)
        self.assertTrue(np.array_equal(rd(1, q), sheet(1, q)))
        rd16 = C.ScaledReader(sheet, 1 / 16, 0)
        self.assertTrue(np.array_equal(rd16(1, q), sheet(0, q * 2 / 16)))

    def test_cut_back_and_surface_body(self):
        body = np.stack([np.zeros(11), np.arange(0, 110, 10.0), np.zeros(11)], 1)
        cut = C.cut_back(body, 25.0)
        self.assertAlmostEqual(cut[-1][1], 75.0)
        self.assertIsNone(C.cut_back(body, 200.0))
        G = np.stack(np.meshgrid(np.arange(5.0), np.arange(50.0), indexing="ij"), -1)
        G = np.concatenate([np.zeros(G.shape[:2] + (1,)), G[..., 1:2], G[..., 0:1]], -1)   # x 0, y col, z row
        valid = np.ones(G.shape[:2], bool)
        b, walked, d = C.surface_body(G, valid, np.array([0.0, 40.0, 2.0]), np.array([0.0, 1.0, 0.0]), 20.0)
        self.assertEqual(d, 0.0)
        self.assertGreaterEqual(walked, 20.0)
        self.assertEqual(b[-1].tolist(), [0.0, 40.0, 2.0])
        self.assertLess(b[0][1], 40.0)                          # walked behind the end, away from its tangent

    def test_joins_step_matches_the_kollesis_finder_alone(self):
        um = C.KOLL_UM * 16                                     # 1 scan voxel = 16 frozen-frame voxels
        with tempfile.TemporaryDirectory() as d:
            run, fib = joins_world(Path(d), um)
            sheet = Sheet()
            rec = C.run_joins(run, None, reader=sheet)
            rows = json.loads((run / "joins" / "s00.json").read_text())["rows"]
            end = [r for r in rows if r["point"][1] == 1400.0][0]
            self.assertEqual(end["status"], "scored")
            self.assertIsNotNone(end["kfh1_shifted"])
            # the same number from the kollesis finder's own functions on the same body
            fh, fs = C._koll()
            G, valid = C._grid(Path(d) / "surf")
            factor = C.KOLL_UM / um
            body, _, _ = C.surface_body(G, valid, fib[-1], np.array([0.0, 1.0, 0.0]),
                                        fh.BEHIND * factor + C.KOLL_SHIFT * factor)
            rd = C.ScaledReader(sheet, factor, C.read_level(um))
            fr = fh.frame(body / factor)
            raw, cen, _ = fh.extract(fr, rd)
            f = fh.features(raw, cen)
            self.assertAlmostEqual(end["kfh1"], fs.kfh1({**f, "s": fr["s"].astype(np.float32)}), places=6)
            s = rec["surfaces"]["s00"]
            self.assertEqual(s["ends"], 2)
            self.assertIn("scaled", rec["deviation"])
            self.assertEqual(C.check_run(run), [])

    def test_a_step_rerun_alone_makes_later_records_stale(self):
        with tempfile.TemporaryDirectory() as d:
            run, _ = joins_world(Path(d), C.KOLL_UM * 16)
            quiet(C.run_joins, run, None, reader=Sheet())
            self.assertEqual(C.check_run(run), [])
            fib = json.loads((run / "fibers.json").read_text())
            fib["token"] = "remade"                         # as if fibers ran again alone
            (run / "fibers.json").write_text(json.dumps(fib))
            self.assertTrue(any("joins.json was made from another fibers.json" in p for p in C.check_run(run)))

    def test_joins_refuses_a_local_volume_before_any_step(self):
        with tempfile.TemporaryDirectory() as d:
            run, _ = joins_world(Path(d), 9.362)
            c = json.loads((run / "couple.json").read_text())
            c["volume_url"] = str(Path(d) / "scan.zarr")
            (run / "couple.json").write_text(json.dumps(c))
            with self.assertRaises(C.CoupleError):
                C.run_joins(run, None)
            with self.assertRaises(C.CoupleError):
                C.chain(run, {"labels": None, "fibers": None, "joins": True})

    def test_surface_body_does_not_double_back(self):
        G = np.stack(np.meshgrid(np.arange(5.0), np.arange(50.0), indexing="ij"), -1)
        G = np.concatenate([np.zeros(G.shape[:2] + (1,)), G[..., 1:2], G[..., 0:1]], -1)
        valid = np.ones(G.shape[:2], bool)
        p = np.array([0.0, 39.6, 2.0])                         # the nearest vertex (y 40) lies beyond the end
        b, _, _ = C.surface_body(G, valid, p, np.array([0.0, 1.0, 0.0]), 20.0)
        self.assertTrue((np.diff(b[:, 1]) > 0).all())          # the body runs toward the end, never back

    def test_joins_needs_fibers(self):
        with tempfile.TemporaryDirectory() as d:
            run, _ = joins_world(Path(d), 9.362)
            (run / "fibers.json").unlink()
            with self.assertRaises(C.CoupleError):
                C.run_joins(run, None, reader=Sheet())


class SettingsTest(unittest.TestCase):
    def test_defaults_and_refusals(self):
        self.assertEqual(C.settings_for("labels")["method"], "snapped")
        with self.assertRaises(C.CoupleError):
            C.settings_for("labels", {"method": "magic"})
        with self.assertRaises(C.CoupleError):
            C.settings_for("fibers", {"box": 3})
        with self.assertRaises(C.CoupleError):
            C.settings_for("joins", {"max_ends": 0})
        with self.assertRaises(C.CoupleError):
            C.check_plan({"joins": C.settings_for("joins")})

    def test_contracts_name_every_step(self):
        self.assertEqual(set(C.CONTRACTS), set(C.ORDER))
        for st in C.ORDER:
            self.assertIn("off", C.STAGES[st]["choices"])
            for n, v in C.STAGES[st]["choices"].items():
                self.assertIn(v.get("maturity"), ("default", "experimental"), (st, n))

    def test_check_run_without_couple_json(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(C.check_run(d))


class AutoPipelineWiringTest(unittest.TestCase):
    def test_backend_tables_and_shorthand(self):
        from kit import apbackends as B
        for st in C.ORDER:
            self.assertIn(st, B.STAGES)
            self.assertEqual(B.PIPELINE_STAGE[st], "report")
        over = B.translate({"labels": "mesh", "fibers": "weft", "joins": "kfh1"})
        self.assertEqual(over["labels"], {"method": "mesh"})
        self.assertEqual(B.translate({"labels": "off"})["labels"], None)
        with self.assertRaises(B.BackendError):
            B.translate({"joins": "magic"})

    def test_frozen_files_stay_as_they_are(self):
        # the coupling adds its stages at import and does not edit kit/autopipe.py or kit/stagereg.py
        from kit import autopipe as A
        from kit import stagereg
        for st in C.ORDER:
            self.assertNotIn(st, A.OPTIONAL)
            self.assertIn(st, stagereg.STAGES)                  # added at import by kit/apcouple.py
        src = (ROOT / "kit" / "stagereg.py").read_text()
        self.assertNotIn("kollesis", src)

    def test_in_effect_lists_the_steps_only_when_on(self):
        from kit import apbackends as B
        self.assertNotIn("labels", B.in_effect("report", {"labels": None}))
        eff = B.in_effect("report", {"labels": {"method": "snapped"}, "joins": {"method": "kfh1"}})
        self.assertEqual(eff["labels"]["name"], "snapped")
        self.assertEqual(eff["joins"]["name"], "kfh1")
        self.assertNotIn("fibers", eff)

    @unittest.skipUnless(hasattr(__import__("kit.autopipe").autopipe, "apcouple"),
                         "the in-plan wiring comes in a later version")
    def test_plan_settings_are_optional_and_merge(self):
        from kit import autopipe as A
        base = A._merge(A.DEFAULTS, {})
        for st in C.ORDER:
            self.assertNotIn(st, base)                          # older plans keep their digest
        s = A._merge(A.DEFAULTS, {"labels": True, "fibers": {"box_l0": 512}, "joins": True})
        self.assertEqual(s["labels"]["method"], "snapped")
        self.assertEqual(s["fibers"]["box_l0"], 512)
        self.assertEqual(s["joins"]["method"], "kfh1")
        from kit import apbackends as B
        eff = B.in_effect("report", s)
        self.assertEqual(eff["labels"]["name"], "snapped")
        self.assertEqual(eff["joins"]["name"], "kfh1")
        self.assertEqual(B.in_effect("report", base)["fibers"]["name"], "off")

    def test_stage_registry_lists_the_steps(self):
        from kit import stagereg
        cat, defaults = stagereg.catalogue(refresh=True)
        for st, names in (("labels", ("snapped", "mesh", "off")), ("fibers", ("weft", "off")),
                          ("joins", ("kfh1", "off"))):
            for n in names:
                self.assertIn((st, n), cat)
            self.assertEqual(defaults["autopipeline"][st], "off")
        self.assertEqual(cat[("fibers", "weft")]["maturity"], "experimental")
        self.assertEqual(stagereg.check(), [])

    def test_from_run_reads_an_autopipeline_run_folder(self):
        with tempfile.TemporaryDirectory() as d:
            ap = Path(d) / "ap"
            (ap / "traces" / "t01").mkdir(parents=True)
            (ap / "traces" / "t02").mkdir(parents=True)
            for t in ("t01", "t02"):
                for f in ("x.tif", "y.tif", "z.tif"):
                    (ap / "traces" / t / f).write_bytes(b"")
            (ap / "umbilicus.json").write_text("[]")
            (ap / "plan.json").write_text(json.dumps({"digest": "abc123", "resolved": {
                "volume_url": "https://example.invalid/PHerc0814/volumes/v.zarr", "voxel_um": 9.362,
                "sample": "PHerc0814"}}))
            (ap / "state.json").write_text(json.dumps({"surfaces": {
                "t01": {"accepted": True, "surface": "traces/t01"},
                "t02": {"accepted": False, "surface": str(ap / "traces" / "t02")},
                "seg": {"accepted": True}}}))
            rec = C.from_run(ap)
            self.assertEqual(sorted(rec["surfaces"]), ["t01"])
            self.assertEqual(rec["sample"], "PHerc0814")
            self.assertTrue(str(rec["umbilicus"]).endswith("umbilicus.json"))
            self.assertTrue((ap / "coupled" / "couple.json").is_file())
            (ap / "state.json").write_text(json.dumps({"surfaces": {}}))
            with self.assertRaises(C.CoupleError):
                C.from_run(ap, Path(d) / "other")
            with self.assertRaises(C.CoupleError):
                C.from_run(Path(d) / "nothing")

    def test_command_line_backends_and_check(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(C.main(["backends"]), 0)
        self.assertIn("kfh1", buf.getvalue())
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(C.main(["check", d]), 1)


if __name__ == "__main__":
    unittest.main()
