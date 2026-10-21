"""Ink Lens (spaces/ink-lens): the gate, the engine's algorithm with a stand-in model, VC3D's files and the client's
refusals. numpy only, except the torch checks (skipped without torch) and the comparison with villa's own
normalisation (run when VILLA_SRC names a villa vesuvius/src). No network, no gradio, no real model."""

import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "ink-lens"
if str(SPACE) not in sys.path:
    sys.path.insert(0, str(SPACE))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

if np is not None:
    import engine  # noqa: E402
    import gate  # noqa: E402
    import inklens  # noqa: E402
    import vc3dout  # noqa: E402
    import volio  # noqa: E402

try:
    import torch
except ImportError:
    torch = None


# ---------------------------------------------------------------- stand-ins

def stand_in_predict(images):
    """A stand-in reader that reads depth order: high where the first layers are brighter than the last ones."""
    x = np.asarray(images, np.float32)[:, 0]
    d = x[:, :8].mean(axis=1) - x[:, 9:].mean(axis=1)
    return 1.0 / (1.0 + np.exp(-2.0 * d))


def synthetic_volume(size=384, layers=28, ink=True, seed=0):
    """Papyrus with noise; where there is ink, the shallow layers (low indices) are brighter in a band of strokes."""
    rng = np.random.default_rng(seed)
    v = rng.normal(120, 12, (layers, size, size))
    if ink:
        m = np.zeros((size, size), bool)
        for r in range(40, size - 40, 70):
            m[r:r + 18, 40:size - 40] = True
        v[: layers // 2, m] += 40
    return np.clip(v, 1, 255).astype(np.uint8), (m if ink else None)


def tiff_bytes(arr):
    """A classic little-endian uncompressed single-strip TIFF of a 2-D float32 or uint8 array."""
    a = np.ascontiguousarray(arr)
    h, w = a.shape
    bits, fmt = (32, 3) if a.dtype == np.float32 else (8, 1)
    data = a.tobytes()
    tags = [(256, 4, w), (257, 4, h), (258, 3, bits), (259, 3, 1), (262, 3, 1), (273, 4, 0), (277, 3, 1),
            (278, 4, h), (279, 4, len(data)), (339, 3, fmt)]
    ifd_off = 8
    n = len(tags)
    data_off = ifd_off + 2 + n * 12 + 4
    out = b"II*\x00" + struct.pack("<I", ifd_off) + struct.pack("<H", n)
    for tag, typ, val in tags:
        if tag == 273:
            val = data_off
        out += struct.pack("<HHI", tag, typ, 1) + (struct.pack("<HH", val, 0) if typ == 3 else struct.pack("<I", val))
    return out + struct.pack("<I", 0) + data


def fake_segment(folder, rows=21, cols=24, scale=0.05, holes=False, meta_extra=None):
    """A tifxyz folder: a flat sheet at z = 500 + row, x = 10 * col + 100, y = 10 * row + 200."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rr, cc = np.mgrid[0:rows, 0:cols].astype(np.float32)
    x, y, z = 10 * cc + 100, 10 * rr + 200, 500 + rr
    if holes:
        x[0, 0] = y[0, 0] = z[0, 0] = -1
    for name, band in (("x", x), ("y", y), ("z", z)):
        (folder / f"{name}.tif").write_bytes(tiff_bytes(band.astype(np.float32)))
    meta = {"format": "tifxyz", "type": "seg", "uuid": folder.name, "scale": [scale, scale]}
    meta.update(meta_extra or {})
    (folder / "meta.json").write_text(json.dumps(meta))
    return folder


def quiet(fn, *args, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(*args, **kw)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- the gate

@unittest.skipIf(np is None, "needs numpy")
class Gate(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        self.ct = rng.integers(60, 200, (400, 400)).astype(np.uint8)
        self.R = rng.uniform(0, 0.6, (400, 400)).astype(np.float32)
        self.F = rng.uniform(0, 0.6, (400, 400)).astype(np.float32)
        self.F[100:160, 50:350] = 0.95                   # 11.25 % of the region: strong ink above the control

    def test_ink_passes_and_swapped_fails(self):
        d = gate.decide(self.F, self.R, self.ct)
        self.assertEqual(d["status"], "ink")
        self.assertGreater(d["excess"], 10)
        self.assertAlmostEqual(d["control_above"], 0.01, places=3)
        swapped = gate.decide(self.R, self.F, self.ct)
        self.assertNotEqual(swapped["status"], "ink")

    def test_same_distribution_is_none(self):
        rng = np.random.default_rng(2)
        F = rng.uniform(0, 0.6, self.R.shape).astype(np.float32)
        d = gate.decide(F, self.R, self.ct)
        self.assertEqual(d["status"], "none")
        self.assertLess(d["excess"], gate.WEAK_EXCESS)

    def test_weak_band(self):
        F = self.R.copy()
        F[:12, :] = 0.99                                  # 3 % above T: excess about 3.9 -> ink; 1.5 % -> weak
        F2 = self.R.copy()
        F2[:6, :] = 0.99
        self.assertEqual(gate.decide(F, self.R, self.ct)["status"], "ink")
        self.assertEqual(gate.decide(F2, self.R, self.ct)["status"], "weak")

    def test_unreadable_and_too_small(self):
        self.assertEqual(gate.decide(self.R, self.R, self.ct)["status"], "unreadable")
        self.assertEqual(gate.decide(np.full_like(self.R, 0.3), self.R, self.ct)["status"], "unreadable")
        bad = self.F.copy()
        bad[0, 0] = np.nan
        self.assertEqual(gate.decide(bad, self.R, self.ct)["status"], "unreadable")
        small = gate.decide(self.F[:200, :200], self.R[:200, :200], self.ct[:200, :200])
        self.assertEqual(small["status"], "too_small")
        with self.assertRaises(gate.GateError):
            gate.decide(self.F, self.R[:10], self.ct)

    def test_papyrus_leaves_out_air(self):
        ct = self.ct.copy()
        ct[:, :200] = 0
        m = gate.papyrus(ct)
        self.assertFalse(m[:, :200].any())
        self.assertGreater(m[:, 200:].mean(), 0.9)
        self.assertFalse(gate.papyrus(np.zeros((10, 10), np.uint8)).any())

    def test_kept_and_u8(self):
        d = gate.decide(self.F, self.R, self.ct)
        k = gate.kept(self.F, d, self.ct)
        pap = gate.papyrus(self.ct)[100:160, 50:350]
        self.assertTrue((k[100:160, 50:350][pap] > 0).all())
        self.assertFalse(k[100:160, 50:350][~pap].any())    # pixels at or below the CT floor are never kept
        self.assertTrue((k[k > 0] > d["threshold"]).all())
        u = gate.to_u8(k)
        self.assertEqual(u.dtype, np.uint8)
        self.assertTrue(((u > 0) == (k > 0)).all())
        none = gate.kept(self.F, {"status": "none", "threshold": 0.0}, self.ct)
        self.assertFalse(none.any())

    def test_ink_that_does_not_beat_the_control_is_dropped(self):
        F = self.F.copy()
        F[300:360, 50:350] = 0.55                        # high, but under the control's 99th percentile (about 0.594)
        d = gate.decide(F, self.R, self.ct)
        self.assertEqual(d["status"], "ink")
        self.assertGreater(d["threshold"], 0.55)
        k = gate.kept(F, d, self.ct)
        self.assertFalse(k[300:360, 50:350].any())
        self.assertTrue(k[100:160, 50:350].any())
        # the same faint block alone: the control explains it, so the region is none and nothing is kept
        faint = self.R.copy()
        faint[300:360, 50:350] = 0.55
        d2 = gate.decide(faint, self.R, self.ct)
        self.assertEqual(d2["status"], "none")
        self.assertFalse(gate.kept(faint, d2, self.ct).any())

    def test_label_shares(self):
        kept = np.zeros((300, 300), np.float32)
        kept[100:150, 100:200] = 0.9
        ink = np.zeros((300, 300), bool)
        ink[100:150, 100:200] = True
        sup = np.ones((300, 300), bool)
        s = gate.label_shares(kept, ink, sup)
        self.assertEqual(s["ink_kept_share"], 1.0)
        self.assertEqual(s["background_kept_share"], 0.0)
        self.assertTrue(s["ink_share_larger"])
        self.assertFalse(gate.label_shares(kept, ~ink, sup)["ink_share_larger"])

    def test_prereg_states_the_coded_rule(self):
        text = (ROOT / "docs" / "prereg" / "2026-10-20-ink-lens-gate.md").read_text()
        self.assertIn(gate.RULE_ID, text)
        for phrase in ("5th percentile", "99th percentile", "divided by 0.01", "excess >= 3", "1.5 <= excess < 3",
                       "100,000 papyrus"):
            self.assertIn(phrase, text)
        self.assertEqual((gate.CT_PERCENTILE, gate.CONTROL_PERCENTILE, gate.BASE_RATE, gate.INK_EXCESS,
                          gate.WEAK_EXCESS, gate.MIN_PAPYRUS), (5.0, 99.0, 0.01, 3.0, 1.5, 100_000))


# ---------------------------------------------------------------- the engine, numpy side

@unittest.skipIf(np is None, "needs numpy")
class EngineNumpy(unittest.TestCase):
    def test_positions_and_patches(self):
        self.assertEqual(engine.positions(128), [0])
        self.assertEqual(engine.positions(300), [0, 64, 128, 172])
        self.assertEqual(engine.patches(1024, 1024, 3), 15 * 15 * 6)
        self.assertEqual(engine.patches(1024, 1024, 1, "both"), 15 * 15 * 4)
        self.assertEqual(engine.gpu_seconds(1350), 21)
        self.assertEqual(engine.gpu_seconds(1922), 28)
        with self.assertRaises(engine.EngineError):
            engine.gpu_seconds(engine.patches(2048, 2048, 3))
        est = engine.estimate(2048, 2048, 3)
        self.assertIsNone(est["gpu_seconds_requested"])
        self.assertIn("refused", est)
        with self.assertRaises(engine.EngineError):
            engine.estimate(100, 1024)
        with self.assertRaises(engine.EngineError):
            engine.patches(512, 512, 2)

    def test_layers(self):
        vol = np.arange(28)[:, None, None] * np.ones((1, 4, 4), np.uint8)
        st = engine.stack(vol, 3)
        self.assertEqual(st[:, 0, 0].tolist(), list(range(4, 25)))      # villa's center crop of 21 from 28
        self.assertEqual(engine.window_indices(21, 2, "forward"), list(range(2, 19)))
        self.assertEqual(engine.window_indices(21, 0, "reverse"), list(range(16, -1, -1)))
        # the center window of the 21-layer stack is villa's own 17-layer window of the whole volume
        self.assertEqual([4 + i for i in engine.window_indices(21, 2, "forward")], list(range(6, 23)))
        self.assertEqual(engine.window_indices(17, 0, "forward"), list(range(17)))
        self.assertEqual(len(engine.passes(3)), 6)

    def test_check_volume_refuses(self):
        good, _ = synthetic_volume(256)
        self.assertEqual(engine.check_volume(good), (28, 256, 256))
        for bad, why in ((good[0], "3 axes"), (good.astype(np.uint16), "uint8"), (good[:18], "layers"),
                         (np.zeros_like(good), "all zero"), (good[:, :100], "height")):
            with self.assertRaises(engine.EngineError) as cm:
                engine.check_volume(bad)
            self.assertIn(why, str(cm.exception))
        self.assertEqual(engine.check_volume(good[:17], windows=1)[0], 17)

    def test_hann(self):
        w = engine.hann2d()
        self.assertEqual(w.shape, (128, 128))
        self.assertAlmostEqual(float(w.min()), 0.001, places=6)
        self.assertTrue(np.allclose(w, w.T) and np.allclose(w, w[::-1]))
        self.assertLessEqual(float(w.max()), 1.0)

    def test_robust_np(self):
        rng = np.random.default_rng(3)
        p = rng.integers(0, 255, (17, 32, 32)).astype(np.uint8)
        out = engine.robust_np(p)
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(float(np.median(out)), 0.0, places=5)
        flat = engine.robust_np(np.full((17, 8, 8), 9, np.uint8))
        self.assertTrue(np.all(flat == 0))

    @unittest.skipUnless(os.environ.get("VILLA_SRC"), "set VILLA_SRC to a villa vesuvius/src to compare with villa")
    def test_robust_np_is_villas(self):
        sys.path.insert(0, os.environ["VILLA_SRC"])
        from vesuvius.image_proc.intensity.normalization import normalize_robust
        rng = np.random.default_rng(4)
        for p in (rng.integers(0, 255, (17, 64, 64)).astype(np.uint8), np.full((17, 8, 8), 3, np.uint8)):
            self.assertEqual(float(np.abs(normalize_robust(p.astype(np.float32)) - engine.robust_np(p)).max()), 0.0)

    def test_reference_reads_depth_order(self):
        vol, ink = synthetic_volume(256)
        maps = engine.run_reference(vol, stand_in_predict, windows=3)
        F, R = maps["forward"], maps["reverse"]
        self.assertGreater(float(F[ink].mean()), float(F[~ink].mean()) + 0.2)
        self.assertLess(float(R[ink].mean()), float(F[ink].mean()) - 0.3)
        self.assertEqual(F.dtype, np.float32)


# ---------------------------------------------------------------- the engine, torch side

@unittest.skipIf(np is None or torch is None, "needs numpy and torch")
class EngineTorch(unittest.TestCase):
    def test_robust_torch_matches_numpy(self):
        rng = np.random.default_rng(5)
        batch = rng.integers(0, 255, (4, 17 * 32 * 32)).astype(np.float32)
        batch[1] = 7.0                         # constant: villa's fallback
        batch[2, : batch.shape[1] // 2] = 0    # half empty
        got = engine.robust_torch(torch.from_numpy(batch)).numpy()
        for i in range(4):
            want = engine.robust_np(batch[i].reshape(17, 32, 32)).reshape(-1)
            self.assertLess(float(np.abs(got[i] - want).max()), 1e-4, i)

    def test_hann_matches_torch(self):
        w = torch.outer(torch.hann_window(128, periodic=False), torch.hann_window(128, periodic=False))
        w = torch.clamp(w / w.max(), min=0.001).numpy()
        self.assertLess(float(np.abs(w - engine.hann2d()).max()), 1e-6)

    def test_engine_matches_reference(self):
        class StandIn(torch.nn.Module):
            def forward(self, x):
                d = x[:, 0, :8].mean(1) - x[:, 0, 9:].mean(1)
                return (2.0 * d)[:, None]               # logits; the engine applies the sigmoid
        vol, _ = synthetic_volume(256)
        eng = engine.Engine(models={"d9v2": (StandIn(), "tifxyz_robust", None, {"name": "stand-in"})},
                            place_on_cuda=False)
        run = eng.run(vol, "d9v2", windows=3, device="cpu", batch=7)
        ref = engine.run_reference(vol, stand_in_predict, windows=3)
        for d in ("forward", "reverse"):
            self.assertLess(float(np.abs(run[d] - ref[d]).max()), 1e-5, d)
        self.assertEqual(run["patches"], engine.patches(256, 256, 3))
        with self.assertRaises(engine.EngineError):
            eng.run(vol, "ink_9um")


# ---------------------------------------------------------------- VC3D's files

@unittest.skipIf(np is None, "needs numpy")
class VC3DFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.seg = fake_segment(self.dir / "seg")

    def tearDown(self):
        self.tmp.cleanup()

    def test_png_round_trip_and_filters(self):
        a = (np.arange(35 * 17) % 256).astype(np.uint8).reshape(35, 17)
        self.assertTrue((vc3dout.read_png_gray(vc3dout.png_bytes(a)) == a).all())
        import zlib
        rows = b"".join(bytes([1]) + bytes([a[y, 0]]) + bytes(np.diff(a[y].astype(np.int16)).astype(np.uint8))
                        for y in range(a.shape[0]))       # filter 1 (Sub) on every row
        png = vc3dout.png_bytes(a)
        i = png.index(b"IDAT") - 4
        n = struct.unpack(">I", png[i:i + 4])[0]
        data = zlib.compress(rows)
        crc = struct.pack(">I", zlib.crc32(b"IDAT" + data) & 0xFFFFFFFF)
        sub = png[:i] + struct.pack(">I", len(data)) + b"IDAT" + data + crc + png[i + 12 + n:]
        self.assertTrue((vc3dout.read_png_gray(sub) == a).all())
        with self.assertRaises(vc3dout.VC3DError):
            vc3dout.png_bytes(np.zeros((3, 3), np.float32))

    def test_segment_and_key(self):
        s = vc3dout.segment(self.seg)
        self.assertEqual(s["grid"], [21, 24])
        self.assertEqual(s["canvas_px"], [480, 420])
        self.assertEqual(s["key"], "seg")
        other = fake_segment(self.dir / "cat", meta_extra={"vc_open_data_segment_long_id": "PHercX/seg-123"})
        self.assertEqual(vc3dout.segment(other)["key"], "PHercX/seg-123")
        rep = fake_segment(self.dir / "rep", meta_extra={"vc_open_data_representation": "surface", "uuid": "rep-9"})
        self.assertEqual(vc3dout.segment(rep)["key"], "rep-9")       # Segmentation::id() for a representation
        (self.dir / "bad").mkdir()
        with self.assertRaises(vc3dout.VC3DError):
            vc3dout.segment(self.dir / "bad")

    def test_canvas_keeps_aspect_and_place(self):
        s = vc3dout.segment(self.seg)
        m = np.full((100, 120), 200, np.uint8)
        c, div = vc3dout.canvas(s, (40, 80, 100, 120), m, pool=1)
        self.assertEqual(div, 1)
        rows, cols = s["grid"]
        expected = (cols / 0.05) / (rows / 0.05)
        self.assertLessEqual(abs((c.shape[1] / c.shape[0]) / expected - 1), vc3dout.ASPECT_TOL)
        self.assertTrue((c[40:140, 80:200] == 200).all())
        self.assertEqual(int(c.sum()), 200 * 100 * 120)
        c4, div4 = vc3dout.canvas(s, (40, 80, 400, 480), np.full((100, 120), 9, np.uint8), pool=4)
        self.assertEqual((div4, c4.shape), (4, (105, 120)))
        cbig, k = vc3dout.canvas(s, (0, 0, 100, 120), m, pool=1, max_side=100)
        self.assertEqual(k, 5)
        self.assertLessEqual(max(cbig.shape), 100)
        with self.assertRaises(vc3dout.VC3DError):
            vc3dout.canvas(s, (5000, 5000, 100, 120), m, pool=1)

    def test_records_merge_and_refuse(self):
        s = vc3dout.segment(self.seg)
        mine = {"local_file": "ink/theirs.png", "label": "someone else's map", "segment_id": "seg"}
        (self.seg / "ink-detections.json").write_text(json.dumps([mine]))
        r1 = vc3dout.record(s, "inklens/a.png", "Ink Lens a", "00", (480, 420))
        vc3dout.merge_records(self.seg, [r1])
        r2 = vc3dout.record(s, "inklens/a.png", "Ink Lens a again", "11", (480, 420))
        info = vc3dout.merge_records(self.seg, [r2])
        recs = json.loads((self.seg / "ink-detections.json").read_text())
        self.assertEqual(info["records"], 2)
        self.assertEqual(recs[0], mine)
        self.assertEqual(recs[1]["label"], "Ink Lens a again")
        for r in recs[1:]:                      # VC3D offers a record only when its id is the segment's key
            self.assertIn(s["key"], (r.get("segment_id"), r.get("segment_long_id")))
            self.assertFalse(r.get("segment_long_id"))     # else a catalog JPEG in its group hides the PNG
        (self.seg / "ink-detections.json").write_text('{"not": "a list"}')
        with self.assertRaises(vc3dout.VC3DError):
            vc3dout.merge_records(self.seg, [r1])
        self.assertEqual(json.loads((self.seg / "ink-detections.json").read_text()), {"not": "a list"})

    def test_records_keep_the_catalog_list(self):
        s = vc3dout.segment(self.seg)
        cat = {"local_file": "ink-detections/a.jpg", "label": "catalog", "segment_id": "seg",
               "segment_long_id": "long-seg"}
        (self.seg / "catalog-origin.json").write_text(json.dumps({"ink_detections": [cat, "junk"]}))
        (self.seg / "ink-detections.json").write_text("[]")        # empty: VC3D shows the catalog list
        vc3dout.merge_records(self.seg, [vc3dout.record(s, "inklens/a.png", "Ink Lens a", "00", (480, 420))])
        recs = json.loads((self.seg / "ink-detections.json").read_text())
        self.assertEqual([r["label"] for r in recs], ["catalog", "Ink Lens a"])

    def test_mosaic(self):
        p = self.dir / "m.png"
        a = np.zeros((10, 12), np.uint8)
        a[2, 3] = 50
        b = np.zeros((10, 12), np.uint8)
        b[2, 3], b[5, 5] = 20, 90
        m, merged = vc3dout.merge_mosaic(p, a)
        self.assertFalse(merged)
        p.write_bytes(vc3dout.png_bytes(m))
        m2, merged = vc3dout.merge_mosaic(p, b)
        self.assertTrue(merged)
        self.assertEqual((int(m2[2, 3]), int(m2[5, 5])), (50, 90))
        m3, merged = vc3dout.merge_mosaic(p, np.zeros((5, 5), np.uint8))
        self.assertFalse(merged)

    def test_points(self):
        doc = vc3dout.points_doc("Ink Lens r1", [[1.0, 2.0, 3.0], [4, 5, 6]])
        self.assertEqual(vc3dout.check_points_doc(doc), [])
        self.assertEqual(doc["collections"]["1"]["points"]["1"]["wind_a"], None)
        saved = {"vc_pointcollections_json_version": "1",
                 "collections": {"3": {"name": "my seeds", "points": {"1": {"p": [9, 9, 9], "creation_time": 0,
                                                                            "wind_a": 2.5}}},
                                 "4": {"name": "Ink Lens r1", "points": {}}}}
        merged = vc3dout.merge_points(saved, doc)
        self.assertEqual(vc3dout.check_points_doc(merged), [])
        names = sorted(c["name"] for c in merged["collections"].values())
        self.assertEqual(names, ["Ink Lens r1", "my seeds"])
        self.assertIn("4", merged["collections"])
        self.assertEqual(len(merged["collections"]["4"]["points"]), 2)
        self.assertTrue(vc3dout.check_points_doc({"vc_pointcollections_json_version": "2"}))
        self.assertTrue(vc3dout.check_points_doc({"vc_pointcollections_json_version": "1",
                                                  "collections": {"1": {"name": "x", "points": {"1": {}}}}}))
        with self.assertRaises(vc3dout.VC3DError):
            vc3dout.merge_points({"collections": []}, doc)

    def test_points_ids_time_and_file_keys(self):
        import time
        doc = vc3dout.points_doc("Ink Lens r2", [[1.0, 2.0, 3.0], [4, 5, 6]])
        t = doc["collections"]["1"]["points"]["1"]["creation_time"]
        self.assertLess(abs(t - time.time() * 1000), 60_000)     # milliseconds, as VC3D stamps its points
        saved = {"vc_pointcollections_json_version": "1", "spiral_workspace": {"keep": True},
                 "collections": {"2": {"name": "seeds", "points": {"1": {"p": [0, 0, 1]}, "7": {"p": [0, 0, 2]}}}}}
        merged = vc3dout.merge_points(saved, doc)
        self.assertEqual(merged["spiral_workspace"], {"keep": True})
        ids = [p for c in merged["collections"].values() for p in c["points"]]
        self.assertEqual(len(ids), len(set(ids)))                # point ids are unique across collections
        self.assertEqual(sorted(merged["collections"]["3"]["points"]), ["8", "9"])

    def test_tiff_size_and_grid_mapping(self):
        self.assertEqual(vc3dout.tiff_size(self.seg / "x.tif"), (24, 21))
        rr, cc = np.mgrid[0:21, 0:24].astype(np.float32)
        xyz = np.stack([10 * cc + 100, 10 * rr + 200, 500 + rr])
        self.assertEqual(vc3dout.grid_to_voxel(xyz, 2.5, 3.25), [132.5, 225.0, 502.5])
        self.assertIsNone(vc3dout.grid_to_voxel(xyz, 30, 0))
        holed = xyz.copy()
        holed[:, 2, 3] = -1
        self.assertIsNone(vc3dout.grid_to_voxel(holed, 2.5, 3.25))
        r, c, d = vc3dout.voxel_to_grid(xyz, [131, 221, 502])
        self.assertEqual((r, c), (2, 3))
        s = vc3dout.segment(self.seg)
        self.assertEqual(vc3dout.render_to_grid(s, 100, 60), (5.0, 3.0))

    @unittest.skipUnless(__import__("importlib").util.find_spec("tifffile"), "needs tifffile")
    def test_load_xyz(self):
        xyz = vc3dout.load_xyz(self.seg)
        self.assertEqual(xyz.shape, (3, 21, 24))
        self.assertEqual(float(xyz[2, 3, 0]), 503.0)


# ---------------------------------------------------------------- reading regions

@unittest.skipIf(np is None, "needs numpy")
class Reading(unittest.TestCase):
    def test_pool(self):
        self.assertEqual(volio.pool_factor(2.4), 4)
        self.assertEqual(volio.pool_factor(9.366), 1)
        self.assertEqual(volio.pool_factor(3.24), 3)
        a = np.arange(8 * 8 * 8, dtype=np.uint8).reshape(8, 8, 8)
        p = volio.pool(a, 4)
        self.assertEqual(p.shape, (2, 2, 2))
        self.assertEqual(int(p[0, 0, 0]), int(round(a[:4, :4, :4].mean())))
        self.assertIs(volio.pool(a, 1).dtype, a.dtype)
        self.assertEqual(volio.to_uint8(np.array([65535, 257], np.uint16)).tolist(), [255, 1])

    def test_uncompressed_zarr_v2(self):
        with tempfile.TemporaryDirectory() as d:
            arr = (np.arange(6 * 20 * 30) % 251).astype(np.uint8).reshape(6, 20, 30)
            z = Path(d) / "v.zarr"
            (z / "0").mkdir(parents=True)
            (z / ".zattrs").write_text(json.dumps({"multiscales": [{"datasets": [{"path": "0"}]}]}))
            (z / "0" / ".zarray").write_text(json.dumps({"zarr_format": 2, "shape": [6, 20, 30], "chunks": [6, 8, 8],
                                                         "dtype": "|u1", "compressor": None, "fill_value": 0,
                                                         "order": "C", "filters": None, "dimension_separator": "/"}))
            for j in range(3):
                for k in range(4):
                    chunk = np.zeros((6, 8, 8), np.uint8)
                    part = arr[:, j * 8:(j + 1) * 8, k * 8:(k + 1) * 8]
                    chunk[:, :part.shape[1], :part.shape[2]] = part
                    if (j, k) == (2, 3):
                        continue                         # a missing chunk reads as the fill value
                    p = z / "0" / "0" / str(j) / str(k)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(chunk.tobytes())
            got, info = volio.read_region(z, (3, 5, 12, 20))
            self.assertTrue((got == arr[:, 3:15, 5:25]).all())
            corner, _ = volio.read_region(z, (16, 24, 4, 6))
            self.assertFalse(corner.any())
            with self.assertRaises(volio.VolumeError):
                volio.read_region(z, (15, 0, 10, 10))

    def test_files(self):
        with tempfile.TemporaryDirectory() as d:
            a = np.ones((3, 10, 12), np.uint8)
            np.save(Path(d) / "v.npy", a)
            np.savez(Path(d) / "v.npz", volume=a)
            np.savez(Path(d) / "w.npz", other=a)
            self.assertEqual(volio.read_file(Path(d) / "v.npy", (2, 3, 4, 5)).shape, (3, 4, 5))
            self.assertEqual(volio.read_file(Path(d) / "v.npz").shape, (3, 10, 12))
            with self.assertRaises(volio.VolumeError):
                volio.read_file(Path(d) / "w.npz")
            with self.assertRaises(volio.VolumeError):
                volio.read_file(Path(d) / "v.npy", (8, 0, 5, 5))


# ---------------------------------------------------------------- the client

@unittest.skipIf(np is None, "needs numpy")
class Client(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # 21 x 24 grid at scale 0.05: a 420 x 480 px canvas at the native 9.4 um (pool 1)
        self.seg = fake_segment(self.dir / "seg")
        vol, self.ink = synthetic_volume(384)
        full = np.zeros((28, 420, 480), np.uint8)
        full[:, 20:404, 40:424] = vol
        self.sv = self.dir / "surface.npy"
        np.save(self.sv, full)
        patcher = mock.patch.object(inklens, "run_local", self.fake_local)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def fake_local(volume, reader="d9v2", windows=3, device=None):
        maps = engine.run_reference(volume, stand_in_predict, windows)
        return {**maps, "readers": [reader], "windows": windows, "patches": engine.patches(*volume.shape[1:], windows),
                "device": "cpu", "device_name": "stand-in", "seconds": 0.0, "where": "local", "engine": {"stand_in": 1}}

    def run_cli(self, *args):
        return quiet(inklens.main, list(args))

    def base(self):
        return ["run", "--segment", str(self.seg), "--surface-volume", str(self.sv), "--um-per-px", "9.4",
                "--box", "40", "20", "384", "384", "--local", "--json"]

    def test_full_local_run_writes_vc3d_files(self):
        code, out, err = self.run_cli(*self.base(), "--no-pins")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["gate"]["status"], "ink")
        files = res["files"]
        png = vc3dout.read_png_gray(Path(files["png"]).read_bytes())
        self.assertEqual(png.shape, (420, 480))                  # the whole canvas, VC3D's stretch keeps it in place
        self.assertTrue((png[:20] == 0).all() and (png[:, :40] == 0).all())
        on = png[20:404, 40:424] > 0
        self.assertGreater(on[self.ink].mean(), 0.5)
        self.assertLess(on[~self.ink].mean(), 0.05)
        recs = json.loads((self.seg / "ink-detections.json").read_text())
        self.assertEqual({r["local_file"] for r in recs}, {f"inklens/{res['run']}.png", "inklens/mosaic.png"})
        receipt = json.loads(Path(files["receipt"]).read_text())
        self.assertEqual(receipt["gate"]["status"], "ink")
        self.assertEqual(receipt["box_render_px"], [20, 40, 384, 384])
        self.assertEqual(receipt["canvas_size"], [480, 420])
        # a second run adds to the mosaic and keeps the first run's record
        code, out, _ = self.run_cli(*self.base(), "--no-pins")
        self.assertEqual(code, 0)
        recs2 = json.loads((self.seg / "ink-detections.json").read_text())
        self.assertGreaterEqual(len(recs2), 2)

    def test_none_region_exits_3_and_writes_an_empty_overlay(self):
        flat, _ = synthetic_volume(384, ink=False, seed=9)
        full = np.zeros((28, 420, 480), np.uint8)
        full[:, 20:404, 40:424] = flat
        np.save(self.sv, full)
        code, out, err = self.run_cli(*self.base(), "--no-pins")
        self.assertEqual(code, inklens.EXIT_NONE, err)
        res = json.loads(out)
        self.assertEqual(res["gate"]["status"], "none")
        self.assertFalse(vc3dout.read_png_gray(Path(res["files"]["png"]).read_bytes()).any())

    def test_dry_run(self):
        code, out, _ = self.run_cli(*self.base(), "--dry-run")
        self.assertEqual(code, 0)
        plan = json.loads(out)
        self.assertEqual(plan["estimate"]["patches"], engine.patches(384, 384, 3))
        self.assertFalse((self.seg / "inklens").exists())

    def test_refusals(self):
        cases = [
            (["run", "--segment", str(self.seg), "--surface-volume", str(self.sv), "--box", "0", "0", "384", "384",
              "--local"], "--um-per-px"),
            (["run", "--segment", str(self.seg), "--surface-volume", str(self.sv), "--um-per-px", "9.4",
              "--box", "300", "300", "384", "384", "--local"], "outside the segment canvas"),
            (["run", "--segment", str(self.dir), "--surface-volume", str(self.sv), "--um-per-px", "9.4",
              "--box", "0", "0", "384", "384", "--local"], "meta.json"),
            (["run", "--segment", str(self.seg), "--um-per-px", "9.4", "--box", "40", "20", "384", "384", "--local"],
             "--surface-volume"),
        ]
        for args, why in cases:
            code, _, err = self.run_cli(*args)
            self.assertEqual(code, inklens.EXIT_REFUSED, args)
            self.assertIn(why, err)
        (self.seg / "ink-detections.json").write_text('"not a list"')
        code, _, err = self.run_cli(*self.base(), "--no-pins")
        self.assertEqual(code, inklens.EXIT_REFUSED)
        self.assertIn("not a JSON array", err)
        self.assertEqual((self.seg / "ink-detections.json").read_text(), '"not a list"')

    def test_out_writes_only_into_the_run_folder(self):
        before = sorted(str(f.relative_to(self.seg)) for f in self.seg.rglob("*"))
        run = self.dir / "run"
        args = ["run", "--segment", str(self.seg), "--surface-volume", str(self.sv), "--um-per-px", "9.4",
                "--crop", "20", "404", "40", "424", "--local", "--offline", "--out", str(run), "--json", "--no-pins"]
        with mock.patch.dict(os.environ, {"INKLENS_OFFLINE": ""}):
            code, out, err = self.run_cli(*args)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(str(f.relative_to(self.seg)) for f in self.seg.rglob("*")), before)
        import tifffile
        kept = tifffile.imread(run / "inklens.tif")
        ctrl = tifffile.imread(run / "inklens_reverse.tif")
        self.assertEqual((kept.shape, kept.dtype.name), ((420, 480), "uint8"))      # the whole canvas, 8-bit
        self.assertEqual(ctrl.shape, (420, 480))
        on = kept[20:404, 40:424] > 0
        self.assertGreater(on[self.ink].mean(), 0.5)
        self.assertGreater(on.mean(), (ctrl[20:404, 40:424] > 0).mean())
        receipt = json.loads((run / "inklens.json").read_text())
        self.assertEqual(receipt["box_render_px"], [20, 40, 384, 384])          # --crop is the same box as --box
        self.assertFalse(receipt["wrote_into_segment"])
        self.assertEqual(json.loads(out)["gate"]["status"], "ink")
        # a region with nothing kept still exits 0 with --out: the files are the result, the status is in them
        flat, _ = synthetic_volume(384, ink=False, seed=9)
        full = np.zeros((28, 420, 480), np.uint8)
        full[:, 20:404, 40:424] = flat
        np.save(self.sv, full)
        code, out, err = self.run_cli(*args[:-4], "--out", str(self.dir / "run2"), "--json", "--no-pins")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["gate"]["status"], "none")
        code, _, err = self.run_cli(*[a for a in args if a != "--local"])
        self.assertEqual(code, inklens.EXIT_REFUSED)
        self.assertIn("local mode", err)

    def test_offline_refuses_to_download(self):
        with mock.patch.dict(os.environ, {"INKLENS_OFFLINE": "1", "INKLENS_D9V2": ""}), \
                mock.patch.object(engine, "_download", side_effect=AssertionError("downloaded")):
            with self.assertRaisesRegex(engine.EngineError, "downloads are off"):
                engine.ensure_checkpoint("d9v2", cache=self.dir / "cache")
            with mock.patch.dict(os.environ, {"VILLA_SRC": ""}), \
                    self.assertRaisesRegex(engine.EngineError, "downloads are off"):
                engine.ensure_villa(cache=self.dir / "cache")

    def test_space_needs_the_users_token(self):
        vol, _ = synthetic_volume(256)
        with mock.patch.dict(os.environ, {"HF_TOKEN": ""}), mock.patch.object(inklens, "hf_token", lambda t=None: None):
            with self.assertRaises(inklens.Refused) as cm:
                inklens.run_space(vol)
        self.assertIn("token", str(cm.exception))

    def test_space_result_must_match_local_gate(self):
        vol, _ = synthetic_volume(384)
        maps = engine.run_reference(vol, stand_in_predict, 3)
        maps_path = self.dir / "maps.npz"
        np.savez_compressed(maps_path, forward=maps["forward"], reverse=maps["reverse"])

        class FakeClient:
            def __init__(self, status):
                self.status = status

            def predict(self, f, reader, windows, api_name):
                assert api_name == "/lens_region" and Path(f).is_file()
                with zipfile.ZipFile(f) as zf:
                    assert zf.namelist() == ["volume.npy"]
                return {"gate": {"status": self.status}, "readers": [reader], "patches": 1}, str(maps_path), None

        for status, ok in (("ink", True), ("none", False)):
            run = inklens.run_space(vol, token="hf_test", client_factory=lambda src, s=status: (FakeClient(s), str))
            d, _, _ = inklens.analyze(run["forward"], run["reverse"], vol)
            if ok:
                inklens.check_space_gate(run, d)
            else:
                with self.assertRaises(inklens.Refused):
                    inklens.check_space_gate(run, d)

    def test_upload_limit(self):
        vol, _ = synthetic_volume(256)
        with mock.patch.object(inklens, "MAX_UPLOAD_BYTES", 1000), self.assertRaises(inklens.Refused):
            inklens.pack_volume(vol, self.dir / "r.npz")

    def test_letter_points_need_a_passing_read(self):
        res = {"control": {"status": "strong"},
               "lines": [{"letters": [{"glyph": "Α", "p": 0.9, "kept": True, "box": [10, 30, 40, 60]},
                                      {"glyph": "Β", "p": 0.2, "kept": False, "box": [0, 1, 0, 1]}]}]}
        pts = inklens.letter_points(res, (100, 200), 4)
        self.assertEqual(pts, [{"row": 180.0, "col": 400.0, "glyph": "Α", "p": 0.9}])
        res["control"]["status"] = "none"
        self.assertEqual(inklens.letter_points(res, (100, 200), 4), [])

    def test_pins_land_on_the_surface(self):
        rid = "t1"
        files, voxels = inklens.write_vc3d(self.seg, rid, (20, 40, 384, 384), 1, np.zeros((384, 384), np.uint8),
                                           {"status": "ink", "excess": 5.0}, {"reader": "d9v2"},
                                           pins=[{"row": 100.0, "col": 60.0}, {"row": 9999.0, "col": 0.0}],
                                           xyz=np.stack([10 * np.mgrid[0:21, 0:24][1] + 100.0,
                                                         10 * np.mgrid[0:21, 0:24][0] + 200.0,
                                                         500 + np.mgrid[0:21, 0:24][0] * 1.0]).astype(np.float32))
        self.assertEqual(voxels, [[130.0, 250.0, 505.0]])        # grid (5, 3); the off-grid pin is dropped
        doc = json.loads(Path(files["pins"]).read_text())
        self.assertEqual(vc3dout.check_points_doc(doc), [])

    def test_estimate_and_samples_commands(self):
        code, out, _ = self.run_cli("estimate", "1024", "1024", "--json")
        self.assertEqual((code, json.loads(out)["gpu_seconds_requested"]), (0, 21))
        code, out, _ = self.run_cli("samples")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["samples"]), 4)


# ---------------------------------------------------------------- the Space

@unittest.skipIf(np is None, "needs numpy")
class Space(unittest.TestCase):
    def test_samples_are_public_and_not_prize_eligible(self):
        prizes = json.loads((ROOT / "kit" / "data" / "prizes-2026-10-11.json").read_text())["prizes"]
        eligible = {e["scroll"] for p in prizes for e in p.get("eligible", [])}
        data = inklens.load_samples()
        for s in data["samples"]:
            self.assertNotIn(s["scroll"], eligible, s["id"])
            self.assertIn(s["scroll"], ("PHerc0841", "PHerc0139"))
            self.assertIn(s["role"], ("development", "training"))
            box = inklens.sample_box(s)
            self.assertEqual((box[1] - box[0], box[3] - box[2]), (640, 640))
        with self.assertRaises(inklens.Refused):
            inklens.sample_by("PHerc1667")
        with self.assertRaises(inklens.Refused):
            inklens.sample_box(data["samples"][0], 1024)

    def test_app_reads_only_a_plain_npz(self):
        import app
        with tempfile.TemporaryDirectory() as d:
            vol, _ = synthetic_volume(256)
            good = Path(d) / "a.npz"
            np.savez_compressed(good, volume=vol)
            self.assertEqual(app.read_npz(good).shape, vol.shape)
            self.assertFalse(good.exists())                  # the upload is deleted once read
            other = Path(d) / "b.npz"
            np.savez(other, nope=vol)
            with self.assertRaises(app.LensError):
                app.read_npz(other)
            huge = Path(d) / "c.npz"
            with zipfile.ZipFile(huge, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("volume.npy", b"\0" * (app.MAX_VOXELS + 10_000))
            with self.assertRaises(app.LensError) as cm:
                app.read_npz(huge)
            self.assertIn("larger", str(cm.exception))
            txt = Path(d) / "d.txt"
            txt.write_text("x")
            with self.assertRaises(app.LensError):
                app.read_npz(txt)

    def test_space_card_and_files(self):
        card = (SPACE / "README.md").read_text()
        head = card.split("---")[1]
        for line in ("sdk: gradio", "app_file: app.py", "suggested_hardware: zero-a10g", "license: apache-2.0",
                     "python_version:", "sdk_version:", "mcp-server"):
            self.assertIn(line, head)
        self.assertIn("model output, not a reading", card.lower())
        sys.path.insert(0, str(SPACE / "tools"))
        import deploy
        files = deploy.space_files()
        for name in ("app.py", "engine.py", "gate.py", "inklens.py", "vc3dout.py", "volio.py", "kit/auc.py"):
            self.assertIn(name, files)
        reqs = (SPACE / "requirements.txt").read_text()
        for pin in ("torch==2.13.0", "numpy==2.5.2", "mcp=="):
            self.assertIn(pin, reqs)

    def test_plugin_manifest(self):
        m = json.loads((SPACE / "vc3d-plugin.json").read_text())
        self.assertEqual(m["id"], "ink-lens")
        self.assertEqual(m["version"], engine.VERSION)
        cmd = m["actions"][0]["command"]
        self.assertIn("${PLUGIN_DIR}/inklens.py", cmd)
        # every flag the manifest passes is one the client accepts
        flags = {c for c in cmd if c.startswith("--")}
        known = {a for act in inklens.parser()._subparsers._group_actions[0].choices["run"]._actions
                 for a in act.option_strings}
        self.assertLessEqual(flags, known)


if __name__ == "__main__":
    unittest.main()
