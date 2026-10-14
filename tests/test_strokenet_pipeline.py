"""Tests for StrokeNet's dataset, nulls, training, run driver and evaluation (scripts/strokenet/);
metrics and baselines are in test_strokenet_stats.py. numpy is needed; torch and scipy parts skip
without them."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts" / "strokenet"

try:
    import numpy as np
    sys.path.insert(0, str(SCRIPTS))
    import data as D
    import metrics as M
except ImportError:  # the core kit is standard library only
    np = D = M = None
try:
    import torch
    import baselines as BL
    import evaluate as EV
    import nulls as NL
    import pipeline as PL
    import train as T
except ImportError:
    torch = BL = EV = NL = PL = T = None
try:
    import scipy  # noqa: F401
except ImportError:
    scipy = None
finally:
    if str(SCRIPTS) in sys.path:
        sys.path.remove(str(SCRIPTS))


def brute_auc(pos, neg):
    return float(np.mean([(p > n) + 0.5 * (p == n) for p in pos for n in neg]))


@unittest.skipIf(M is None, "numpy not installed")
class ProvenanceTest(unittest.TestCase):
    """prov.py runs on the computer that launches the cloud run, which may have no numpy or torch."""

    def test_prov_is_standard_library_and_names_every_file(self):
        import ast
        src = (SCRIPTS / "prov.py").read_text()
        mods = {a.name.split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module.split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(mods, set(sys.stdlib_module_names))
        sys.path.insert(0, str(SCRIPTS))
        try:
            import prov
        finally:
            sys.path.remove(str(SCRIPTS))
        runner = "scripts/strokenet/modal_strokenet.py"          # the cloud runner is not in the public copy
        for f in prov.CODE_FILES:
            self.assertTrue((ROOT / f).exists() or f == runner, f)
        pilot = {"scripts/strokenet/gridpilot.py", "scripts/strokenet/modal_gridpilot.py"}   # not part of the run
        here = {p.relative_to(ROOT).as_posix() for p in SCRIPTS.glob("*.py")} - pilot
        self.assertLessEqual(here, set(prov.CODE_FILES))      # every script of the run is hashed
        out = prov.code_provenance(ROOT)
        absent = set() if (ROOT / runner).exists() else {runner}
        self.assertEqual(set(out["files"]), set(prov.CODE_FILES) - absent)
        self.assertEqual(out["missing"], sorted(absent))


@unittest.skipIf(D is None, "numpy not installed")
class DataTest(unittest.TestCase):
    def test_splits_follow_the_rule(self):
        sp = D.splits()
        self.assertEqual([len(sp[k]) for k in ("train", "validation", "test")], [14, 7, 6])
        allsegs = sp["train"] + sp["validation"] + sp["test"]
        self.assertEqual(len(set(allsegs)), 27)
        self.assertNotIn("w010-027", allsegs)
        order = [s for s, _ in D.ORDER]
        for k, segs in sp.items():
            for s in segs:
                self.assertEqual(D.split_of(order.index(s)), k)
        self.assertEqual(sp["test"][0], "w053-058")
        with self.assertRaises(KeyError):
            D.segment_split("w010-027")

    def test_url(self):
        u = D.url("w095-097")
        self.assertTrue(u.startswith("https://data.aws.ash2txt.org/samples/PHercParis4/segments/20260701183138-w095-097/"))
        self.assertTrue(u.endswith("new_canon_autoresearch_recipe-tile256-stride128.tif"))

    def test_pool_array_is_a_rounded_block_mean(self):
        rng = np.random.default_rng(2)
        a = rng.integers(0, 256, (130, 95), dtype=np.uint8)
        p = D.pool_array(a, strip=40)
        self.assertEqual(p.shape, (6, 4))
        ref = np.round(a[:120, :80].reshape(6, 20, 4, 20).astype(np.float64).mean(axis=(1, 3))).astype(np.uint8)
        self.assertTrue(np.array_equal(p, ref))

    @unittest.skipIf(scipy is None, "scipy not installed")
    def test_label_map_finds_lines_and_blank(self):
        rng = np.random.default_rng(3)
        H, W = 1400, 1200                                   # 67 by 58 mm at 0.048 mm
        a = rng.normal(30, 2, (H, W))
        y = np.arange(H)[:, None]
        lines = ((y % 140) < 60) & (rng.random((H, W)) < 0.5)   # a 6.7 mm line pitch, half-filled bands
        a[:, :500] += 120 * lines[:, :500]
        a = np.clip(a, 0, 255).astype(np.uint8)
        lab, summ = D.label_map(a)
        self.assertGreater((lab[200:1200, 100:400] == 2).mean(), 0.8)       # text in the lined half
        self.assertGreater((lab[200:1200, 800:1100] == 1).mean(), 0.8)      # blank papyrus in the other
        self.assertGreater(summ["text_mm2"], 300)
        out = D.crops_from(a, lab, "validation")
        self.assertGreater(len(out["text"]), 0)
        self.assertGreater(len(out["blank"]), 0)
        for (yy, xx) in out["blank_pos"]:
            self.assertFalse((lab[yy:yy + 128, xx:xx + 128] == 2).any())
        for (yy, xx) in out["text_pos"]:
            self.assertGreaterEqual((lab[yy:yy + 128, xx:xx + 128] == 2).mean(), 0.9)

    def test_load_split_positions_and_maps(self):
        with tempfile.TemporaryDirectory() as d:
            rng = np.random.default_rng(9)
            (Path(d) / "crops").mkdir()
            (Path(d) / "pooled").mkdir()
            for i, s in enumerate(("sa", "sb")):
                m = rng.integers(0, 255, (300, 400), dtype=np.uint8)
                np.save(Path(d) / "pooled" / f"{s}_48.npy", m)
                pos = np.array([[0, 0], [100, 200 + i]], np.int64)
                np.savez(Path(d) / "crops" / f"{s}.npz", text=np.stack([m[y:y + 128, x:x + 128] for y, x in pos]),
                         text_pos=pos, blank=np.zeros((0, 128, 128), np.uint8), blank_pos=np.zeros((0, 2), np.int64))
            r = D.load_split(d, ["sa", "sb"], with_segments=True, with_positions=True)
            self.assertEqual(r["text"].shape, (4, 128, 128))
            self.assertEqual(list(r["text_seg"]), [0, 0, 1, 1])
            self.assertEqual(r["text_pos"].tolist(), [[0, 0], [100, 200], [0, 0], [100, 201]])
            maps = D.load_maps(d, ["sa", "sb"])
            y, x = r["text_pos"][3]
            self.assertTrue(np.array_equal(maps[1][y:y + 128, x:x + 128], r["text"][3]))


@unittest.skipIf(NL is None, "torch not installed")
class NullsTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(4)
        y = np.arange(128)[:, None]
        w = ((y % 40) < 15) * 150.0 + rng.integers(0, 30, (3, 128, 128))
        self.w = np.clip(w, 0, 255).astype(np.uint8)
        self.x = torch.from_numpy(self.w.astype(np.float32))[:, None]

    def test_value_keeping_nulls_keep_each_windows_values(self):
        for kind in ("iaaft20", "shuffle", "rot90", "strip"):
            out = NL.make(kind, self.x, np.random.default_rng(0), torch.Generator().manual_seed(0))[:, 0].numpy()
            for i in range(3):
                self.assertTrue(np.array_equal(np.sort(out[i].ravel()), np.sort(self.w[i].ravel().astype(np.float32))), kind)

    def test_iaaft_iterations(self):
        g = lambda: torch.Generator().manual_seed(3)
        a20 = NL.make("iaaft20", self.x, None, g())
        self.assertTrue(torch.equal(a20, NL.iaaft(self.x, g(), 20)))
        self.assertEqual(NL.IAAFT_ITERS, 200)
        amp = lambda t: np.abs(np.fft.rfft2(t[:, 0].numpy().astype(np.float64)))
        e20 = np.abs(amp(a20) - amp(self.x)).mean()
        e200 = np.abs(amp(NL.make("iaaft", self.x, None, g())) - amp(self.x)).mean()
        self.assertLessEqual(e200, e20 * 1.05)            # more iterations do not move away from the spectrum

    def test_phase_keeps_amplitude_and_is_whole(self):
        out = NL.phase(self.x, torch.Generator().manual_seed(0))[:, 0].numpy()
        self.assertTrue(np.array_equal(out, np.clip(np.rint(out), 0, 255)))      # whole values in 0..255
        y = np.arange(128)[:, None]
        mid = (100 + 20 * np.sin(y / 5.0) + np.random.default_rng(1).normal(0, 5, (2, 128, 128))).astype(np.float32)
        out = NL.phase(torch.from_numpy(mid)[:, None], torch.Generator().manual_seed(0))[:, 0].numpy()
        a = lambda z: np.abs(np.fft.rfft2(z - z.mean(axis=(1, 2), keepdims=True)))[:, :20, :20]   # rounding adds white noise
        self.assertLess(np.abs(a(out) - a(mid.astype(np.float64))).mean() / a(mid.astype(np.float64)).mean(), 0.05)

    def test_shuffle_moves_whole_tiles(self):
        out = NL.shuffle(self.x, np.random.default_rng(1))[:, 0].numpy()
        tiles = lambda im: [im[r:r + 32, c:c + 32] for r in range(0, 128, 32) for c in range(0, 128, 32)]
        for i in range(3):
            src = tiles(self.w[i].astype(np.float32))
            variants = [np.rot90(t, k) for t in src for k in range(4)]
            variants += [v[:, ::-1] for v in variants]
            for t in tiles(out[i]):
                self.assertTrue(any(np.array_equal(t, v) for v in variants))

    def test_strip_keeps_rows_and_rot90(self):
        out = NL.strip(self.x, np.random.default_rng(2))[:, 0].numpy()
        for r in range(0, 128, 17):
            self.assertTrue(np.array_equal(np.sort(out[0, r]), np.sort(self.w[0, r].astype(np.float32))))
        self.assertTrue(np.array_equal(NL.rot90(self.x)[0, 0].numpy(), np.rot90(self.w[0]).astype(np.float32)))

    def test_jitter_takes_each_piece_from_the_map_nearby(self):
        rng = np.random.default_rng(5)
        m = rng.integers(0, 255, (200, 300), dtype=np.uint8)
        pos = np.array([[0, 0], [40, 100], [72, 172]])               # corners clip the offsets
        for lattice, n_pieces in (("tile", 16), ("strip", 16)):
            out = NL.jitter([m], np.zeros(3, int), pos, lattice, np.random.default_rng(1))
            self.assertEqual(out.shape, (3, 128, 128))
            pcs = NL.pieces(lattice)
            self.assertEqual(len(pcs), n_pieces)
            for i, (y, x) in enumerate(pos):
                for (y0, x0, h, w) in pcs:
                    piece = out[i, y0:y0 + h, x0:x0 + w]
                    hits = [(dy, dx) for dy in range(-3, 4) for dx in range(-3, 4)
                            if 0 <= y + y0 + dy and y + y0 + dy + h <= 200 and 0 <= x + x0 + dx and x + x0 + dx + w <= 300
                            and np.array_equal(m[y + y0 + dy:y + y0 + dy + h, x + x0 + dx:x + x0 + dx + w], piece)]
                    self.assertTrue(hits, (lattice, i, y0, x0))
        a = NL.jitter([m], np.zeros(3, int), pos, "tile", np.random.default_rng(1))
        b = NL.jitter([m], np.zeros(3, int), pos, "tile", np.random.default_rng(1))
        self.assertTrue(np.array_equal(a, b))

    def eval_input(self):
        rng = np.random.default_rng(6)
        m = rng.integers(0, 60, (400, 400)).astype(np.uint8)
        m[::40] = 200
        pos = np.array([[0, 0], [10, 200], [200, 30], [250, 250]])
        cut = lambda p: np.stack([m[y:y + 128, x:x + 128] for y, x in p])
        d = {"text": cut(pos[:3]), "text_seg": np.zeros(3, int), "text_pos": pos[:3],
             "blank": cut(pos[3:]), "blank_seg": np.zeros(1, int), "blank_pos": pos[3:], "dense": cut(pos[1:2])}
        return d, [m]

    def test_eval_sets_are_fixed_by_the_seed_and_subsets_match(self):
        d, maps = self.eval_input()
        a1, a2, a3 = NL.eval_sets(d, 5, maps), NL.eval_sets(d, 5, maps), NL.eval_sets(d, 6, maps)
        self.assertEqual(set(a1), {"text", "blank", "dense"} | {f"{k}_{s}" for k, s in NL.PAIRS})
        for k in a1:
            self.assertEqual(NL.array_sha256(a1[k]), NL.array_sha256(a2[k]))
            self.assertEqual(a1[k].dtype, np.uint8, k)
        self.assertNotEqual(NL.array_sha256(a1["iaaft_text"]), NL.array_sha256(a3["iaaft_text"]))
        sub = NL.eval_sets(d, 5, maps, pairs=NL.MONITOR_PAIRS)
        for k, s in NL.MONITOR_PAIRS:
            self.assertTrue(np.array_equal(sub[f"{k}_{s}"], a1[f"{k}_{s}"]), k)


@unittest.skipIf(T is None, "torch not installed")
class TrainTest(unittest.TestCase):
    def test_numpy_export_matches_torch(self):
        from kit import strokenet as KN
        torch.manual_seed(0)
        model = T.Net(width=4, depth=3)
        with torch.no_grad():                         # non-trivial batch-norm statistics
            for m in model.modules():
                if isinstance(m, torch.nn.BatchNorm2d):
                    m.running_mean.uniform_(-0.5, 0.5)
                    m.running_var.uniform_(0.5, 2.0)
                    m.weight.uniform_(0.5, 1.5)
                    m.bias.uniform_(-0.2, 0.2)
        model.eval()
        w = np.random.default_rng(7).integers(0, 255, (5, 128, 128)).astype(np.uint8)
        ref = T.score(model, w, "cpu")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "net.npz"
            T.export_numpy(model, p, {"name": "t"})
            got = KN.StrokeNet(p).logits(w)
        self.assertLess(float(np.abs(got - ref).max()), 1e-3)

    def test_score_runs_without_tf32(self):
        model = T.Net(width=4, depth=2).eval()
        torch.backends.cudnn.allow_tf32 = True
        seen = []
        orig = model.forward
        model.forward = lambda x: (seen.append(torch.backends.cudnn.allow_tf32), orig(x))[1]
        T.score(model, np.zeros((2, 128, 128), np.uint8), "cpu")
        self.assertEqual(seen, [False])
        self.assertTrue(torch.backends.cudnn.allow_tf32)      # restored

    def test_parse_mix_jitter_and_run_args(self):
        self.assertTrue(np.allclose(T.parse_mix("blank=1"), [1, 0, 0, 0, 0]))
        self.assertTrue(np.allclose(T.parse_mix("blank=0.4,shuffle=0.2,rot90=0.2"), [0.5, 0, 0.25, 0.25, 0]))
        self.assertTrue(np.allclose(T.parse_mix("iaaft=1,shuffle=1,strip=1"), [0, 1 / 3, 1 / 3, 0, 1 / 3]))
        with self.assertRaises(ValueError):
            T.parse_mix("phase=1")
        self.assertTrue(np.allclose(T.parse_jitter("0.25,0.25"), [0.5, 0.25, 0.25]))
        with self.assertRaises(ValueError):
            T.parse_jitter("0.7,0.7")
        args = PL.run_args("seed1", PL.SWEEP["B_w16_d4_lr1e-3"])
        ns = T_args(args)
        self.assertEqual((ns["seed"], ns["lr"], ns["steps"]), ("1", "1e-3", "6000"))
        self.assertEqual(T_args(PL.run_args("abl_no_iaaft_s2", PL.SWEEP["A_w16_d4_lr2e-3"]))["seed"], "2")
        self.assertEqual(T_args(PL.run_args("abl_no_iaaft_s0", PL.SWEEP["A_w16_d4_lr2e-3"]))["neg_mix"],
                         "blank=0.4,shuffle=0.2,rot90=0.2")
        self.assertIn("--permute-labels", PL.run_args("control_permuted", PL.SWEEP["A_w16_d4_lr2e-3"]))
        self.assertEqual(T_args(PL.run_args("control_artifact", PL.SWEEP["A_w16_d4_lr2e-3"]))["positives"], "blank")
        self.assertEqual(len(PL.FINALS), 17)
        with self.assertRaises(ValueError):
            PL.run_args("seed1")

    def test_windows_mixes_plain_and_jittered(self):
        rng = np.random.default_rng(8)
        m = rng.integers(0, 255, (300, 300), dtype=np.uint8)
        pos = np.array([[10, 10], [100, 150], [160, 20]] * 20)
        src = {"w": np.stack([m[y:y + 128, x:x + 128] for y, x in pos]), "seg": np.zeros(len(pos), int), "pos": pos}
        x = T.windows(src, np.arange(len(pos)), [m], np.array([0.5, 0.25, 0.25]), np.random.default_rng(0))
        self.assertEqual(tuple(x.shape), (len(pos), 1, 128, 128))
        same = [(x[i, 0].numpy() == src["w"][i]).all() for i in range(len(pos))]
        self.assertTrue(10 < sum(same) < 50)                 # about half are plain

    def test_choose_breaks_ties_by_size(self):
        with tempfile.TemporaryDirectory() as d:
            def put(n, v, p):
                (Path(d) / n).mkdir(exist_ok=True)
                (Path(d) / n / "history.json").write_text(json.dumps(
                    {"final_select": v, "best_select": v, "best_step": 6000, "config": {"n_params": p}}))
            vals = {"A_w16_d4_lr2e-3": (0.990, 300), "D_w8_d4_lr2e-3": (0.9896, 80), "E_w32_d4_lr2e-3": (0.995, 1200)}
            for n, (v, p) in vals.items():
                put(n, v, p)
            self.assertEqual(PL.choose(d, names=tuple(vals))["chosen"], "E_w32_d4_lr2e-3")
            put("E_w32_d4_lr2e-3", 0.9915, 1200)            # within 0.002 of A and of D: fewest parameters
            self.assertEqual(PL.choose(d, names=tuple(vals))["chosen"], "D_w8_d4_lr2e-3")

    def test_read_refuses_a_second_read_and_dirty_test_code(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "read_test.started.json").write_text("{}")
            with self.assertRaises(SystemExit):
                PL.read(d, "test", "cpu", provenance={"dirty": False})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                PL.read(d, "test", "cpu", provenance={"dirty": True})
            with self.assertRaises(SystemExit):
                PL.eval_windows(d, d, "validation", segments=["w053-058"])

    def test_an_interrupted_test_read_resumes_only_in_its_own_run_folder(self):
        orig = PL.model_hashes, PL.report_models
        try:
            PL.report_models = lambda runs: {"released": "A"}
            h = {"released": {"npz": "a" * 64, "final_pt": "c" * 64}}
            PL.model_hashes = lambda runs: h
            with tempfile.TemporaryDirectory() as w, tempfile.TemporaryDirectory() as r:
                (Path(r) / "read_validation.json").write_text(json.dumps({"model_sha256": h}))
                (Path(r) / "evalsets_test.json").write_text(json.dumps({"sha256": {"text": "e"}}))
                mk = {"runs": str(Path(r)), "model_sha256": h, "evalsets_sha256": {"text": "e"},
                      "started": "t0", "attempts": ["t0"]}
                for f in (Path(r) / "read_test.started.json", Path(w) / "read_test.started.json"):
                    f.write_text(json.dumps(mk))
                left = [Path(r) / f for f in ("read_test.json", "read_test.part.npz", "read_test.part.json")]
                for f in left:                                # what the cut-short attempt wrote
                    f.write_bytes(b"scores")
                with self.assertRaises(FileNotFoundError):    # past every marker check, stopped at the missing windows
                    PL.read(r, "test", "cpu", provenance={"dirty": False}, work=w)
                self.assertEqual(len(json.loads((Path(r) / "read_test.started.json").read_text())["attempts"]), 2)
                self.assertFalse(any(f.exists() for f in left))   # deleted before the redo, never used
                (Path(r) / "evalsets_test.json").write_text(json.dumps({"sha256": {"text": "other"}}))
                with self.assertRaises(SystemExit):           # other test windows: refused
                    PL.read(r, "test", "cpu", provenance={"dirty": False}, work=w)
                (Path(r) / "read_test.npz").write_bytes(b"x")
                with self.assertRaises(SystemExit):           # a finished read is never redone
                    PL.read(r, "test", "cpu", provenance={"dirty": False}, work=w)
        finally:
            PL.model_hashes, PL.report_models = orig

    def test_a_read_writes_its_record_before_the_npz_that_marks_it_finished(self):
        """A container lost between the two writes leaves no npz, so the read may be redone."""
        orig = (PL.model_hashes, PL.report_models, T.load_model, T.score, BL.load_models, BL.score_all)
        real_replace, order = Path.replace, []

        def replace(self, target):
            order.append(Path(target).name)
            return real_replace(self, target)
        try:
            h = {"released": {"npz": "a" * 64, "final_pt": "c" * 64}}
            PL.report_models, PL.model_hashes = (lambda runs: {"released": "A"}), (lambda runs: h)
            T.load_model = lambda d, dev: (None, None)
            T.score = lambda model, v, dev: np.zeros(len(v), np.float32)
            BL.load_models, BL.score_all = (lambda p: {}), (lambda v, models: {})
            Path.replace = replace
            with tempfile.TemporaryDirectory() as r:
                (Path(r) / "read_validation.json").write_text(json.dumps({"model_sha256": h}))
                np.savez(Path(r) / "evalsets_test.npz", text=np.zeros((2, 8, 8), np.uint8), text_seg=np.zeros(2, int))
                (Path(r) / "evalsets_test.json").write_text(json.dumps({"sha256": {"text": "e"}}))
                PL.read(r, "test", "cpu", provenance={"dirty": False})
                self.assertEqual(order[-2:], ["read_test.json", "read_test.npz"])
                self.assertEqual(sorted(np.load(Path(r) / "read_test.npz").files), ["cnn/released/text", "text_seg"])
        finally:
            Path.replace = real_replace
            PL.model_hashes, PL.report_models, T.load_model, T.score, BL.load_models, BL.score_all = orig

    def test_test_split_is_read_once_per_dataset(self):
        """A marker in the data folder refuses a second test read from a fresh run folder."""
        with tempfile.TemporaryDirectory() as w, tempfile.TemporaryDirectory() as r:
            (Path(w) / "read_test.started.json").write_text(json.dumps({"runs": "/elsewhere"}))
            with self.assertRaises(SystemExit) as cm:
                PL.read(r, "test", "cpu", provenance={"dirty": False}, work=w)
            self.assertIn("/elsewhere", str(cm.exception))
            self.assertFalse((Path(r) / "read_test.started.json").exists())

    def test_a_finished_validation_read_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "read_validation.npz").write_bytes(b"x")
            (Path(d) / "read_validation.json").write_text(json.dumps({"split": "validation", "kept": True}))
            self.assertEqual(PL.read(d, "validation", "cpu"), {"split": "validation", "kept": True})

    def test_test_read_refuses_models_other_than_the_validated_ones(self):
        orig = PL.model_hashes, PL.report_models
        try:
            PL.report_models = lambda runs: {"released": "A"}
            PL.model_hashes = lambda runs: {"released": {"npz": "b" * 64, "final_pt": "c" * 64}}
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "read_validation.json").write_text(json.dumps(
                    {"model_sha256": {"released": {"npz": "a" * 64, "final_pt": "c" * 64}}}))
                with self.assertRaises(SystemExit) as cm:
                    PL.read(d, "test", "cpu", provenance={"dirty": False})
                self.assertIn("differ", str(cm.exception))
                self.assertFalse((Path(d) / "read_test.started.json").exists())
        finally:
            PL.model_hashes, PL.report_models = orig

    def test_validate_resumes_without_refitting_calibration(self):
        orig = PL.fit_randcnn, PL.read
        try:
            PL.fit_randcnn = lambda *a, **k: None
            PL.read = lambda *a, **k: {}
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "read_validation.npz").write_bytes(b"read one")
                cal = {"gate": {"ok": True, "checks": {"x": {"ok": True}}},
                       "validation_read_sha256": PL.sha256_bytes(Path(d) / "read_validation.npz")}
                (Path(d) / "calibration.json").write_text(json.dumps(cal))
                ok, checks = PL.validate(d, d)
                self.assertTrue(ok)
                g = json.loads((Path(d) / "gate.json").read_text())
                self.assertEqual(g["calibration_sha256"], PL.sha256_bytes(Path(d) / "calibration.json"))
                (Path(d) / "gate.json").write_text(json.dumps({"ok": True, "kept": 1}))
                PL.validate(d, d)                                # an existing gate.json is never rewritten
                self.assertEqual(json.loads((Path(d) / "gate.json").read_text()), {"ok": True, "kept": 1})
                (Path(d) / "read_validation.npz").write_bytes(b"another read")
                with self.assertRaises(SystemExit):
                    PL.validate(d, d)
        finally:
            PL.fit_randcnn, PL.read = orig


def T_args(argv):
    """Last value of each --flag in an argument list (argparse keeps the last)."""
    out = {}
    for i, a in enumerate(argv):
        if a.startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out[a[2:].replace("-", "_")] = argv[i + 1]
    return out


@unittest.skipIf(EV is None, "torch not installed")
class EvaluateTest(unittest.TestCase):
    KEYS = ["text", "blank", "dense"] + [f"{k}_{s}" for k, s in NL.PAIRS] if NL else []
    MODELS = ["released", "seed1", "seed2"] + [f"{a}_s{k}" for a in EV.ABLATIONS for k in (0, 1, 2)] + \
        ["abl_no_jitter", "control_permuted", "control_artifact"] if EV else []

    def fake_runs(self, d, control_good=False, artifact_good=False, base_strong=False):
        """Validation and test reads with 6 segments in which StrokeNet separates text from every
        other array, the controls do not (unless asked), and baselines are weaker (unless asked)."""
        rng = np.random.default_rng(8)
        segs = [f"s{i}" for i in range(6)]
        for split in ("validation", "test"):
            n = {k: 120 for k in self.KEYS}
            n.update({"blank": 90, "dense": 60})
            for k in self.KEYS:
                if k.endswith("_blank"):
                    n[k] = n["blank"]
            arr = {}
            for src in ("text", "blank", "dense"):
                arr[src + "_seg"] = np.repeat(np.arange(6), n[src] // 6)
                arr[src + "_pos"] = np.stack([np.zeros(n[src], int), (np.arange(n[src]) * 97) % 2000], 1)
            pos_keys = ("text", "tilejit_text", "stripjit_text")
            for m in self.MODELS:
                good = (m != "control_permuted" or control_good) and (m != "control_artifact" or artifact_good)
                for k in self.KEYS:
                    mu = 4.0 if (k in pos_keys and good) else 0.0
                    arr[f"cnn/{m}/{k}"] = rng.normal(mu, 1, n[k])
            for b in ("density", "skew", "lines", "spectrum"):
                for k in self.KEYS:
                    mu = (4.0 if base_strong else 0.6) if k in pos_keys else 0.0
                    arr[f"base/{b}/{k}"] = rng.normal(-mu if b == "lines" else mu, 1, n[k])
            np.savez(Path(d) / f"read_{split}.npz", **arr)
            meta = {"split": split, "models": {m: {"run": m} for m in self.MODELS}}
            if split == "validation":
                meta["numpy_check"] = {"max_abs_logit_diff": 1e-6}
            (Path(d) / f"read_{split}.json").write_text(json.dumps(meta))
            (Path(d) / f"evalsets_{split}.json").write_text(json.dumps({"segments": segs, "n": n, "sha256": {}}))
        (Path(d) / "choice.json").write_text(json.dumps({"chosen": "A"}))

    def run_all(self, d):
        cal = EV.calibrate(d)
        (Path(d) / "gate.json").write_text(json.dumps(
            {"ok": cal["gate"]["ok"], "calibration_sha256": PL.sha256_bytes(Path(d) / "calibration.json")}))
        return cal, EV.results(d)

    def test_good_model_weak_baselines(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_runs(d)
            cal, r = self.run_all(d)
            self.assertTrue(cal["gate"]["ok"])
            self.assertEqual(cal["baselines"]["lines"]["directions"]["T1"], -1.0)   # direction set on validation
            self.assertTrue(r["models"]["released"]["bar"]["T1"]["pass"])
            self.assertEqual(len(r["models"]["released"]["T1"]["per_segment"]), 6)
            self.assertEqual(r["verdict"]["void_measures"], [])
            for m in EV.PRIMARY:
                c = r["comparisons"][m]
                self.assertEqual(c["k_positive"], 6, m)
                self.assertAlmostEqual(c["sign_flip_p"], 1 / 64, places=9)
                self.assertTrue(c["adds_over_simple_scores"], m)
            self.assertIn("T2", r["verdict"]["adds_over_simple_scores_primary"])
            self.assertIn("ci95", r["models"]["released"]["T2"])
            with self.assertRaises(SystemExit):                 # calibration is written once
                EV.calibrate(d)
            json.dumps(r, default=float)

    def test_strong_baselines_take_the_credit(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_runs(d, base_strong=True)
            _, r = self.run_all(d)
            self.assertEqual(r["verdict"]["adds_over_simple_scores_primary"], [])

    def test_controls_void_and_withhold(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_runs(d, control_good=True)
            cal, _ = self.run_all(d)
            self.assertFalse(cal["gate"]["ok"])
            self.assertTrue(cal["validity"]["control_permuted"]["T1"]["void"])
        with tempfile.TemporaryDirectory() as d:
            self.fake_runs(d, artifact_good=True)
            cal, r = self.run_all(d)
            self.assertTrue(cal["gate"]["ok"])
            self.assertIn("T2", r["verdict"]["not_interpretable_as_text_structure"])
            self.assertFalse(r["comparisons"]["T2"]["adds_over_simple_scores"])
            self.assertIn("withheld", r["comparisons"]["T2"])

    def test_void_measures_are_not_counted(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_runs(d, control_good=True)
            cal, r = self.run_all(d)
            v = r["verdict"]
            self.assertIn("T1", v["void_measures"])
            self.assertNotIn("T1", v["counted_items"])
            self.assertNotIn("T1", v["failed_items"])
            self.assertNotIn("T1", v["simple_scores_meet_items"])
            self.assertFalse(r["comparisons"]["T1"]["adds_over_simple_scores"])
            self.assertIn("void", r["comparisons"]["T1"])
            self.assertIn("of " + str(len(v["counted_items"])) + " counted bar items", v["simple_scores_meet"])

    def test_ablation_effects_in_both_directions(self):
        def run(vals):
            return {m: {"value": float(np.mean(vals)), "per_segment": list(vals)} for m in ("T1", "T2", "T3", "T4", "T7", "T8")}
        base = np.array([0.90, 0.91, 0.92, 0.90, 0.91, 0.92])
        res = {"models": {"released": run(base), "seed1": run(base + 0.005), "seed2": run(base - 0.005)}}
        for k in range(3):
            res["models"][f"abl_no_iaaft_s{k}"] = run(base - 0.10)            # lower in every segment
            res["models"][f"abl_no_rot90_s{k}"] = run(base + 0.05)            # higher in every segment
            res["models"][f"abl_no_shuffle_s{k}"] = run(base)                 # inside the seed range
            res["models"][f"abl_no_nulls_s{k}"] = run(base + np.array([0.15, 0.15, 0.15, 0.15, -0.2, -0.2]))
        a = EV.ablations(res)
        self.assertEqual((a["abl_no_iaaft"]["T2"]["direction"], a["abl_no_iaaft"]["T2"]["effect"]), ("down", True))
        self.assertEqual(a["abl_no_iaaft"]["T2"]["segments_same_sign"], 6)
        self.assertEqual((a["abl_no_rot90"]["T1"]["direction"], a["abl_no_rot90"]["T1"]["effect"]), ("up", True))
        self.assertEqual((a["abl_no_shuffle"]["T1"]["direction"], a["abl_no_shuffle"]["T1"]["effect"]), (None, False))
        self.assertEqual(a["abl_no_nulls"]["T1"]["segments_same_sign"], 4)    # mean is up, only 4 segments agree
        self.assertFalse(a["abl_no_nulls"]["T1"]["effect"])

    def test_results_refuse_a_changed_calibration(self):
        with tempfile.TemporaryDirectory() as d:
            self.fake_runs(d)
            self.run_all(d)
            p = Path(d) / "calibration.json"
            p.write_text(p.read_text().replace('"mixture"', '"mixture" ', 1))
            with self.assertRaises(SystemExit):
                EV.results(d)


if __name__ == "__main__":
    unittest.main()
