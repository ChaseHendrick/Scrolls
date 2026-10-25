"""Lasagnetta (scripts/lasagnetta): the agreement metrics and zarr reading run on numpy alone; the net, the ensemble
recipe and the self-check need torch and skip without it."""
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lasagnetta"))

try:
    import numpy as np
    C = importlib.import_module("lgcommon")
except ImportError:                 # numpy missing
    np = C = None

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(C is None, "numpy not installed")
class CommonTest(unittest.TestCase):
    def test_normal_round_trip_and_sign(self):
        n = np.array([[0.3], [-0.4], [-0.866]], np.float32)
        nx, ny = C.encode_normal(n)
        back = C.decode_normal(nx, ny)
        self.assertGreater(abs(float((back[:, 0] * n[:, 0]).sum())), 0.99)
        self.assertGreaterEqual(back[2, 0], 0.0)              # villa keeps nz >= 0

    def test_line_peaks_and_matching(self):
        v = np.zeros((1, 1, 12), np.float32)
        v[0, 0, [2, 7]] = 0.9
        v[0, 0, 9] = 0.3                                          # under the 0.5 cut
        mask = np.ones_like(v, bool)
        self.assertEqual(C.line_peaks(v, mask).sum(), 2)
        s = np.zeros_like(v)
        s[0, 0, [3, 10]] = 0.8                                    # one within a voxel, one not
        m, ns, nt = C.peak_counts(s, v, mask)
        self.assertEqual((m, ns, nt), (1, 2, 2))

    def test_crop_metrics_agree_with_themselves_and_the_shift_control_fails(self):
        rng = np.random.default_rng(0)
        n = 128
        z = np.arange(n // 2)[:, None, None] * np.ones((1, n // 2, n // 2))
        cos = (0.5 + 0.5 * np.cos(z / 2.0 + (np.arange(n // 2)[None, :, None] / 3.0))).astype(np.float32)
        nrm = np.zeros((3, n // 4, n // 4, n // 4), np.float32)
        nrm[2] = 1.0
        pred = {"cos": cos[None], "gm": rng.uniform(0, 1, (1, n // 4, n // 4, n // 4)).astype(np.float32),
                "normal": nrm}
        tgt = dict(pred, mask_cos=np.ones((1,) + cos.shape, bool),
                   mask_other=np.ones((1, n // 4, n // 4, n // 4), bool))
        r = C.crop_metrics(pred, tgt)
        self.assertAlmostEqual(r["cos_r"], 1.0, places=5)
        self.assertAlmostEqual(r["peak_f1"], 1.0, places=5)
        self.assertLess(r["normal_deg"], 1e-3)
        ctl = C.crop_metrics(pred, tgt, shift=3)
        self.assertLess(ctl["cos_r"], 0.8)

    def test_read_box_from_a_local_zarr_fills_outside(self):
        with tempfile.TemporaryDirectory() as d:
            arr = np.arange(4 * 4 * 4, dtype=np.uint8).reshape(4, 4, 4)
            (Path(d) / ".zarray").write_text(json.dumps({"zarr_format": 2, "shape": [4, 4, 4], "chunks": [2, 2, 2],
                                                         "dtype": "|u1", "compressor": None, "fill_value": 0,
                                                         "order": "C", "filters": None}))
            for i in range(2):
                for j in range(2):
                    for k in range(2):
                        (Path(d) / f"{i}.{j}.{k}").write_bytes(
                            np.ascontiguousarray(arr[2 * i:2 * i + 2, 2 * j:2 * j + 2, 2 * k:2 * k + 2]).tobytes())
            meta, get = C.local_zarr(d)
            box, present = C.read_box_from(meta, get, ((1, 5), (0, 4), (0, 4)))
            self.assertTrue(present)
            self.assertTrue((box[:3] == arr[1:]).all())
            self.assertTrue((box[3] == 0).all())


@unittest.skipIf(C is None or torch is None, "numpy and torch needed")
class NetTest(unittest.TestCase):
    def setUp(self):
        self.M = importlib.import_module("lasnet")
        self.S = importlib.import_module("selfcheck")

    def test_ensemble_blur_and_offset(self):
        torch.manual_seed(0)
        a, b = self.M.build("s16").eval(), self.M.build("m24").eval()
        x = torch.rand(1, 1, 32, 32, 32)
        with torch.no_grad():
            plain = [self.M.to_maps(n(x)) for n in (a, b)]
            avg = self.M.predict_maps(self.M.Ensemble([a, b]), x)
            off = self.M.predict_maps(self.M.Ensemble([a, b]), x, cos_offset=0.04)
        self.assertTrue(torch.allclose(avg["cos"], (plain[0]["cos"] + plain[1]["cos"]) / 2, atol=1e-6))
        self.assertTrue(torch.allclose(off["cos"], (avg["cos"] - 0.04).clamp(0, 1), atol=1e-6))
        self.assertFalse(off["cos"].requires_grad)

    def test_preview_loads_comma_joined_checkpoints(self):
        P = importlib.import_module("preview")
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i, cfg in enumerate(("s16", "m24")):
                p = Path(d) / f"{i}.pt"
                torch.save({"config": cfg, "state_dict": self.M.build(cfg).state_dict()}, p)
                paths.append(str(p))
            net, config = P.load(",".join(paths), torch.device("cpu"))
        self.assertIsInstance(net, self.M.Ensemble)
        self.assertEqual(config, "ens(s16,m24)")

    def test_selfcheck_spots_and_decision(self):
        per = self.S.candidates(((0, 1000), (0, 448), (300, 900)), (1000, 448, 2000))
        self.assertEqual(per, [[128, 256, 384, 512, 640], [128], [384, 512]])
        self.assertEqual(self.S.widen(((100, 200), (0, 50), (990, 1000)), (1000, 1000, 1000), span=300),
                         ((0, 300), (0, 300), (700, 1000)))
        self.assertEqual(self.S.widen(((0, 512),) * 3, (512,) * 3), ((0, 512),) * 3)
        full, empty = np.ones((320,) * 3, np.uint8), np.zeros((320,) * 3, np.uint8)
        got = self.S.draw(((0, 2000),) * 3, (2000,) * 3, lambda o: full if o[0] == 128 else empty, spots=3)
        self.assertTrue(len(got) == 3 and all(o[0] == 128 for o, _ in got))
        rows = [{"peak_f1": v} for v in (0.9, 0.85, 0.83, 0.84, 0.86, 0.88, 0.81, 0.87)]
        self.assertEqual(self.S.decide(rows)[0], "student")
        self.assertEqual(self.S.decide(rows[:7])[0], "villa")
        self.assertEqual(self.S.decide(rows + [{"peak_f1": 0.5}] * 8)[0], "villa")

    def test_selfcheck_end_to_end_with_the_stub_teacher(self):
        TF = importlib.import_module("teacher")
        rng = np.random.default_rng(2)
        vol = rng.integers(40, 200, (512, 512, 512), dtype=np.uint8)
        meta = {"shape": [512] * 3, "chunks": [128] * 3, "dtype": "|u1", "compressor": None, "fill_value": 0}
        get = lambda k: np.ascontiguousarray(vol[k[0] * 128:(k[0] + 1) * 128, k[1] * 128:(k[1] + 1) * 128,
                                                  k[2] * 128:(k[2] + 1) * 128]).tobytes()
        torch.manual_seed(0)
        rec = self.S.check(self.M.build("s16").eval(), TF.StubTeacher(torch.device("cpu")), meta, get,
                           ((0, 512),) * 3, torch.device("cpu"), spots=1, min_spots=1, log=lambda *_: None)
        self.assertEqual((rec["spots_drawn"], rec["spots_scored"]), (1, 1))
        self.assertIn(rec["decision"], ("student", "villa"))


if __name__ == "__main__":
    unittest.main()
