import contextlib
import hashlib
import inspect
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli

try:
    import numpy as np
    from kit import letterread as R
except ImportError:  # the core kit is standard library only
    np = R = None

ROOT = Path(__file__).resolve().parent.parent
ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"


def random_weights(path, c=(4, 4, 6, 6, 8), letter_px=16, seed=0):
    """A linenet-v1 file with random weights and the training script's layer layout."""
    rng = np.random.default_rng(seed)
    c1, c2, c3, c4, c5 = c
    arrs, layers, k = {}, [], 0

    def add(shape, op, **kw):
        nonlocal k
        arrs[f"w{k}"] = rng.normal(0, 0.3, shape).astype(np.float32)
        arrs[f"b{k}"] = rng.normal(0, 0.05, shape[0]).astype(np.float32)
        layers.append(dict(op=op, id=k, **kw))
        k += 1

    add((c1, 1, 3, 3), "conv2d", pad=1)
    layers.append({"op": "maxpool", "k": [2, 2]})
    add((c2, c1, 3, 3), "conv2d", pad=1)
    layers.append({"op": "maxpool", "k": [2, 2]})
    add((c3, c2, 3, 3), "conv2d", pad=1)
    add((c3, c3, 3, 3), "conv2d", pad=1)
    layers.append({"op": "maxpool", "k": [2, 1]})
    add((c4, c3, 3, 3), "conv2d", pad=1)
    add((c5, c4, 4, 1), "collapse")
    add((c5, c5, 3), "conv1d_res", dilation=1)
    add((c5, c5, 3), "conv1d_res", dilation=2)
    add((len(ALPHABET) + 1, c5, 1), "head")
    meta = {"alphabet": ALPHABET, "blank": 0, "letter_px": letter_px, "band": [1.1, 1.15], "stride": 4,
            "layers": layers, "format": "linenet-v1"}
    np.savez(path, meta=np.array(json.dumps(meta, ensure_ascii=False)), **arrs)
    return path


def lined_image(n_lines=4, pitch=30, letter=16, width=400, seed=0):
    rng = np.random.default_rng(seed)
    a = rng.normal(0.1, 0.03, (n_lines * pitch + pitch, width))
    for i in range(n_lines):
        y = pitch // 2 + i * pitch + pitch // 2
        for x in range(10, width - 20, 22):
            a[y - letter // 2:y + letter // 2, x:x + 3] = 0.9
            a[y - letter // 2:y - letter // 2 + 3, x:x + 12] = 0.9
    return a.astype(np.float32)


def two_column_image(gap=64, seed=0):
    """Two lined blocks side by side: 2 lines on the left, 3 on the right, `gap` px of background between."""
    left, right = lined_image(n_lines=2, width=200, seed=seed), lined_image(n_lines=3, width=200, seed=seed + 1)
    rng = np.random.default_rng(seed + 2)
    a = rng.normal(0.1, 0.03, (right.shape[0], 200 + gap + 200)).astype(np.float32)
    a[:left.shape[0], :200] = left
    a[:, 200 + gap:] = right
    return a


def block_mean(a, k):
    ny, nx = a.shape[0] // k, a.shape[1] // k
    return a[:ny * k, :nx * k].astype(np.float64).reshape(ny, k, nx, k).mean(axis=(1, 3))


def write_zarr_level(group, name, data, chunks=(16, 16)):
    """One array in a zarr group, with zarr 3's or zarr 2's call."""
    try:
        arr = group.create_array(name, shape=data.shape, dtype=data.dtype, chunks=chunks)
    except AttributeError:
        arr = group.create_dataset(name, shape=data.shape, dtype=data.dtype, chunks=chunks)
    arr[:] = data
    return arr


# The network's forward pass is most of the time these tests take, and many of them read the same synthetic image
# with the same weights under different options, so the same band goes through the same network again and again.
# This wrapper keeps each band's logits under a digest of the band and of every weight and layer of the network,
# and hands back a fresh copy for exactly the same inputs: LineNet.logits still runs once for every distinct input,
# and every read sees the same numbers. NetworkTest checks the forward pass itself.
_LOGITS = {}
_logits = R.LineNet.logits if R is not None else None


def _cached_logits(self, band):
    a = np.asarray(band, np.float32)
    h = hashlib.sha256(repr((a.shape, self.stride, self.meta["layers"])).encode())
    h.update(np.ascontiguousarray(a).tobytes())
    for k in sorted(self.w):
        v = np.asarray(self.w[k])
        h.update(repr((k, v.dtype.str, v.shape)).encode())
        h.update(np.ascontiguousarray(v).tobytes())
    key = h.hexdigest()
    if key not in _LOGITS:
        _LOGITS[key] = _logits(self, band)
    return _LOGITS[key].copy(order="K")   # keep the Fortran order logits returns, so values match exactly


_PATCHES = []


def setUpModule():
    if R is not None:
        p = mock.patch.object(R.LineNet, "logits", _cached_logits)
        p.start()
        _PATCHES.append(p)


def tearDownModule():
    while _PATCHES:
        _PATCHES.pop().stop()
    _LOGITS.clear()


def run_cli(argv):
    """(exit code, stdout, stderr) of python -m kit ARGV."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


@unittest.skipIf(np is None, "numpy not installed")
class NetworkTest(unittest.TestCase):
    def test_conv2d_matches_direct_sum(self):
        rng = np.random.default_rng(1)
        x = rng.normal(size=(3, 7, 9)).astype(np.float32)
        w = rng.normal(size=(2, 3, 3, 3)).astype(np.float32)
        b = rng.normal(size=2).astype(np.float32)
        got = R._conv2d(x, w, b, 1)
        xp = np.pad(x, ((0, 0), (1, 1), (1, 1)))
        want = np.zeros((2, 7, 9))
        for o in range(2):
            for i in range(7):
                for j in range(9):
                    want[o, i, j] = (xp[:, i:i + 3, j:j + 3] * w[o]).sum() + b[o]
        self.assertTrue(np.allclose(got, want, atol=1e-4))

    def test_conv1d_dilated_same_padding(self):
        rng = np.random.default_rng(2)
        x = rng.normal(size=(2, 11)).astype(np.float32)
        w = rng.normal(size=(3, 2, 3)).astype(np.float32)
        b = np.zeros(3, np.float32)
        got = R._conv1d(x, w, b, 2)
        xp = np.pad(x, ((0, 0), (2, 2)))
        want = np.stack([sum(w[o, :, j] @ xp[:, j * 2:j * 2 + 11] for j in range(3)) for o in range(3)])
        self.assertTrue(np.allclose(got, want, atol=1e-5))

    def test_log_probs_shape_and_normalised(self):
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
            self.assertEqual(net.band_rows, 36)
            lp = net.log_probs(np.random.default_rng(0).random((36, 101)).astype(np.float32))
            self.assertEqual(lp.shape, (26, 25))       # ceil(101 / 4) frames, 24 letters plus blank
            self.assertTrue(np.allclose(np.exp(lp).sum(axis=1), 1, atol=1e-5))

    def test_rejects_other_formats(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.npz"
            np.savez(p, meta=np.array(json.dumps({"format": "other"})))
            with self.assertRaises(ValueError):
                R.LineNet(p)

    def test_matches_torch_export(self):
        try:
            import torch
        except ImportError:
            self.skipTest("torch not installed")
        sys.path.insert(0, str(ROOT / "scripts" / "letters"))
        try:
            import train_linenet as T
        except ImportError as exc:
            self.skipTest(f"training script needs {exc.name}")
        finally:
            sys.path.pop(0)
        torch.manual_seed(0)
        model = T.LineNet(c=(4, 4, 6, 6, 8))
        for m in model.modules():          # non-trivial BatchNorm statistics, so folding is tested
            if isinstance(m, (torch.nn.BatchNorm1d, torch.nn.BatchNorm2d)):
                m.running_mean.uniform_(-0.2, 0.2)
                m.running_var.uniform_(0.5, 2.0)
                m.weight.data.uniform_(0.5, 1.5)
                m.bias.data.uniform_(-0.1, 0.1)
        model.eval()
        x = torch.rand(1, 1, 36, 64)
        with torch.no_grad():
            want = model(x)[0].numpy().T
        with tempfile.TemporaryDirectory() as d:
            T.export_npz(model, Path(d) / "w.npz")
            got = R.LineNet(Path(d) / "w.npz").logits(x[0, 0].numpy())
        self.assertLess(float(np.abs(got - want).max()), 1e-4)


@unittest.skipIf(np is None, "numpy not installed")
class DecodeTest(unittest.TestCase):
    def frames(self, seq):
        """Log-probs that put nearly all mass on the given class per frame (0 = blank)."""
        lp = np.full((len(seq), 25), math.log(1e-4))
        for t, k in enumerate(seq):
            lp[t, k] = math.log(1 - 24e-4)
        return lp

    def test_greedy_collapses_repeats_and_blanks(self):
        a, b = ALPHABET.index("Α") + 1, ALPHABET.index("Β") + 1
        out = R.ctc_greedy(self.frames([0, a, a, 0, a, b, b, 0]), ALPHABET)
        self.assertEqual("".join(o[0] for o in out), "ΑΑΒ")
        self.assertEqual((out[0][2], out[0][3]), (1, 2))
        self.assertGreater(out[0][1], 0.99)

    def test_beam_without_lm_agrees_with_greedy(self):
        a, b = ALPHABET.index("Ε") + 1, ALPHABET.index("Ν") + 1
        lp = self.frames([0, a, 0, b, b, 0])
        self.assertEqual(R.ctc_beam(lp, ALPHABET)[0], "ΕΝ")

    def test_lm_breaks_a_tie_and_only_then(self):
        e, o = ALPHABET.index("Ε") + 1, ALPHABET.index("Ο") + 1
        lp = np.full((3, 25), math.log(1e-4))
        lp[0, 0] = lp[2, 0] = math.log(1 - 24e-4)
        lp[1, e] = lp[1, o] = math.log(0.5 - 12e-4)    # an ambiguous letter

        class PreferO:
            def logp_next(self, prefix):
                p = np.full(24, 0.01)
                p[ALPHABET.index("Ο")] = 1 - 0.23
                return np.log(p)

        self.assertEqual(R.ctc_beam(lp, ALPHABET, PreferO(), lm_weight=1.0)[0], "Ο")
        # a clear letter is not overruled by a modest weight
        lp2 = self.frames([0, e, 0])
        self.assertEqual(R.ctc_beam(lp2, ALPHABET, PreferO(), lm_weight=0.5)[0], "Ε")

    def test_force_align_finds_each_letter(self):
        a, b, c = (ALPHABET.index(x) + 1 for x in "ΚΑΙ")
        lp = self.frames([0, a, a, 0, 0, b, 0, c, c, c, 0])
        al = R.force_align(lp, "ΚΑΙ", ALPHABET)
        self.assertEqual([(x[0], x[1], x[2]) for x in al], [("Κ", 1, 2), ("Α", 5, 5), ("Ι", 7, 9)])
        self.assertGreater(min(x[3] for x in al), 0.99)
        # a repeated letter needs a blank between its two copies
        n = ALPHABET.index("Ν") + 1
        al = R.force_align(self.frames([n, 0, n]), "ΝΝ", ALPHABET)
        self.assertEqual([(x[1], x[2]) for x in al], [(0, 0), (2, 2)])
        self.assertIsNone(R.force_align(self.frames([n, n]), "ΝΝ", ALPHABET))
        self.assertEqual(R.force_align(self.frames([0]), "", ALPHABET), [])

    def test_locate_finds_a_line_with_errors(self):
        text = "ΚΑΙΤΟΝΘΕΟΝΚΑΙΤΟΥϹΘΕΟΥϹΑΡΕΤΗΝΔΕΚΑΙϹΟΦΙΑΝΕΧΕΙΝΤΟΥϹΑΝΘΡΩΠΟΥϹ"
        start = text.index("ϹΟΦΙΑΝΕΧΕΙΝ")
        hits = R.locate("ϹΟΦΙΑΝΕΧΕΙΝ", text)
        self.assertEqual(hits[0], (start, start + 11, 0))
        noisy = R.locate("ϹΟΦΙΛΝΕΧΙΝ", text)          # one substitution, one deletion
        self.assertEqual(noisy[0][2], 2)
        self.assertLessEqual(abs(noisy[0][0] - start), 1)
        self.assertEqual(R.locate("", text), [])

    def test_edit_distance(self):
        self.assertEqual(R.edit_distance("ΚΑΙ", "ΚΑΙ"), 0)
        self.assertEqual(R.edit_distance("ΚΑΙ", "ΚΙ"), 1)
        self.assertEqual(R.edit_distance("", "ΑΒ"), 2)


@unittest.skipIf(np is None, "numpy not installed")
class PageTest(unittest.TestCase):
    def test_nulls_keep_grey_levels(self):
        a = lined_image()
        for kind, b in R.null_images(a, 16, n=2, seed=3):
            self.assertEqual(b.shape, a.shape)
            if kind == "phase":
                self.assertTrue(np.allclose(np.sort(b, axis=None), np.sort(a, axis=None)))
            else:
                self.assertAlmostEqual(float(b.sum()), float(a.sum()), places=0)
            self.assertFalse(np.allclose(a, b))

    def test_find_lines_and_pitch(self):
        a = lined_image(n_lines=5, pitch=30)
        pitch = R.line_pitch(a, lo=10)
        self.assertTrue(28 <= pitch <= 32, pitch)
        self.assertEqual(len(R.find_lines(a, 16, pitch)), 5)

    def test_deskew_undoes_a_shear(self):
        a = lined_image(n_lines=5, pitch=30)
        tilted = R.shear(a, -3.0)
        angle, _ = R.deskew(tilted, 16, max_deg=6, step=0.5)
        self.assertAlmostEqual(angle, 3.0, delta=0.6)

    def test_normalize_polarity(self):
        a = np.linspace(0, 1, 100).reshape(10, 10)
        self.assertGreater(R.normalize(a, "bright")[9, 9], 0.9)
        self.assertLess(R.normalize(a, "dark")[9, 9], 0.1)

    def test_normalize_sparse_binary_label(self):
        a = np.zeros((1000, 1000), np.uint8)
        a[500:516, 100:200] = 255                       # 0.16% ink, under the 99.8th percentile
        n = R.normalize(a)
        self.assertEqual((float(n[505, 150]), float(n[0, 0])), (1.0, 0.0))
        self.assertGreater(R.normalize(255 - a, "auto")[505, 150], 0.9)   # dark ink on a light ground
        self.assertFalse(R.normalize(np.full((50, 50), 7.0)).any())        # a constant image stays blank

    def test_load_image_crop(self):
        with tempfile.TemporaryDirectory() as d:
            a = np.arange(60 * 80, dtype=np.uint16).reshape(60, 80)
            np.save(Path(d) / "a.npy", a)
            got = R.load_image(Path(d) / "a.npy", crop=(10, 30, 5, 45))
            self.assertEqual((got.shape, got.dtype), ((20, 40), np.float32))
            self.assertEqual(float(got[0, 0]), float(a[10, 5]))
            with self.assertRaisesRegex(ValueError, "empty"):
                R.load_image(Path(d) / "a.npy", crop=(70, 90, 0, 10))
            try:
                import tifffile
            except ImportError:
                return
            tifffile.imwrite(Path(d) / "a.tif", a)
            self.assertTrue(np.array_equal(R.load_image(Path(d) / "a.tif", crop=(10, 30, 5, 45)), got))

    def test_orientation_reads_leave_the_language_model_off(self):
        try:
            from kit import greeklm
        except ImportError:
            self.skipTest("kit.greeklm not importable")
        from unittest import mock
        lm = greeklm.KNLetterLM(order=3).fit(["ΚΑΙΤΟΝΘΕΟΝ" * 50])
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            with mock.patch.object(R, "analyze", wraps=R.analyze) as spy:
                R.read(lined_image(), w, letter_px=16, nulls=1, lm=lm, lm_weight=0.5)
        self.assertEqual(spy.call_count, 1 + len(R.ORIENTATIONS) - 1)    # the read, then mirrored and three turns
        self.assertIs(spy.call_args_list[0].kwargs["lm"], lm)
        self.assertTrue(all(c.kwargs["lm"] is None for c in spy.call_args_list[1:]))

    def test_verdict_needs_nulls(self):
        self.assertIn("no control", R.verdict(10, []))
        self.assertIn("NOT above", R.verdict(3, [3, 1]))
        self.assertIn("well above", R.verdict(40, [2, 5]))

    def test_read_runs_end_to_end_with_controls(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            res = R.read(lined_image(), w, letter_px=16, nulls=2)
        self.assertIn("not a reading", res["note"])
        self.assertEqual(len(res["control"]["nulls"]), 2)
        self.assertEqual(list(res["orientation"]["letters_kept"]), ["as_is", "mirrored", "rot180", "rot90", "rot270"])
        self.assertGreaterEqual(res["p_min"], 0.5)
        for line in res["lines"]:
            self.assertEqual(len(line["ink_only"]), len(line["letters"]))
            for letter in line["letters"]:
                self.assertIn(letter["glyph"], ALPHABET)
                self.assertEqual(len(letter["box"]), 4)
        self.assertIn("control:", R.text_summary(res))

    def test_scale_search_reports_its_table(self):
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
            res = R.analyze(lined_image(), net, nulls=2)
            given = R.analyze(lined_image(), net, nulls=2, letter_px=16)
        self.assertEqual(len(res["scale_search"]), len(R.SCALE_STEPS))
        self.assertIn(res["letter_px"], [t["letter_px"] for t in res["scale_search"]])
        self.assertIn("scale search", res["letter_px_from"])
        self.assertNotIn("scale_search", given)
        self.assertFalse(given["letter_px_estimated"])

    def test_find_columns_splits_only_at_wide_gutters(self):
        a = R.normalize(two_column_image(gap=64))
        spans = R.find_columns(a, 16)
        self.assertEqual(len(spans), 2)
        self.assertTrue(200 <= spans[0][1] <= 264, spans)
        self.assertEqual((spans[0][0], spans[-1][1]), (0, a.shape[1]))
        self.assertEqual(R.find_columns(a, 16, min_gap=8.0), [(0, a.shape[1])])    # about 6 letters of blank: too narrow for 8
        self.assertEqual(len(R.find_columns(a, 16, n=2)), 2)
        self.assertEqual(R.find_columns(a, 16, n=3), spans)    # too many asked: the widest gutter still wins over a narrow gap beside it
        self.assertEqual(R.find_columns(a, 16, n=1), [(0, a.shape[1])])
        self.assertEqual(R.find_columns(R.normalize(lined_image()), 16), [(0, 400)])
        self.assertEqual(R.find_columns(R.normalize(two_column_image(gap=0)), 16), [(0, 400)])   # only the blocks' margins: no gutter
        self.assertEqual(R.find_columns(np.zeros((40, 400), np.float32), 16), [(0, 400)])

    def test_single_column_reads_as_before(self):
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
            auto = R.analyze(lined_image(), net, letter_px=16, nulls=2)
            off = R.analyze(lined_image(), net, letter_px=16, nulls=2, columns="off")
        self.assertEqual(auto["lines"], off["lines"])
        self.assertEqual(auto["control"], off["control"])
        self.assertEqual(len(auto["columns"]), 1)

    def test_two_columns_read_column_by_column(self):
        img = two_column_image(gap=64)
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
            res = R.analyze(img, net, letter_px=16, nulls=2)
            off = R.analyze(img, net, letter_px=16, nulls=2, columns="off")
            two = R.analyze(img, net, letter_px=16, nulls=2, columns=2)
        self.assertEqual([c["lines"] for c in res["columns"]], [2, 3])
        self.assertEqual([r["column"] for r in res["lines"]], [0, 0, 1, 1, 1])
        self.assertEqual([r["line"] for r in res["lines"]], list(range(5)))
        cut = res["columns"][1]["x0"]
        for r in res["lines"]:
            for letter in r["letters"]:
                mid = 0.5 * (letter["box"][2] + letter["box"][3])
                self.assertTrue(mid >= cut - 16 if r["column"] else mid <= cut + 16, (r["column"], letter["box"], cut))
        self.assertEqual(len(off["columns"]), 1)
        self.assertEqual(len(two["columns"]), 2)
        self.assertEqual(len(res["control"]["null_letters_kept"]), 2)
        self.assertIn("2 columns", R.text_summary(res))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "img.npy"
            np.save(img, lined_image())
            out = Path(d) / "res.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "2",
                                 "--no-orientation", "--json", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(buf.getvalue())["engine"], "linenet")
            for cols, n in (("off", 1), ("2", 2)):
                buf = io.StringIO()
                np.save(img, two_column_image())
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                    code = cli.main(["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "2",
                                     "--no-orientation", "--json", "--columns", cols])
                self.assertEqual((code, len(json.loads(buf.getvalue())["columns"])), (0, n))
            self.assertTrue(out.exists())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["letterread", str(img), "--weights", str(Path(d) / "missing.npz")]), 2)

    def test_cli_checks_outputs_before_reading_and_records_the_crop(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "img.npy"
            np.save(img, lined_image())
            base = ["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "1",
                    "--no-orientation"]
            bad = [["--out", str(Path(d) / "missing" / "res.json")]]
            try:
                import PIL  # noqa: F401
                bad.append(["--overlay", str(Path(d) / "letters")])   # no image extension
            except ImportError:
                pass
            for extra in bad:
                with mock.patch.object(R, "read", side_effect=AssertionError("read before checking outputs")), \
                        contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(cli.main(base + extra), 2)
                self.assertNotIn("read before", err.getvalue())
            out = Path(d) / "res.json"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(base + ["--crop", "0", "90", "0", "300", "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["crop"], [0, 90, 0, 300])

    def test_p172_split_is_fixed_and_disjoint(self):
        sys.path.insert(0, str(ROOT / "scripts" / "letters"))
        try:
            import eval_p172
        finally:
            sys.path.remove(str(ROOT / "scripts" / "letters"))
        ids = ["s5", "s1", "s3", "s2", "s4"]
        dev, test = eval_p172.split_segments(ids, "dev"), eval_p172.split_segments(ids, "test")
        self.assertEqual((dev, test), (["s1", "s2", "s3"], ["s4", "s5"]))
        self.assertEqual(eval_p172.split_segments(ids, "all"), sorted(ids))


@unittest.skipIf(np is None, "numpy not installed")
class BigImageTest(unittest.TestCase):
    """Block-averaging while loading, input pixels in the result, physical units, no-size stop."""

    def image_files(self, d, a):
        """The same uint16 image as .npy, plain TIFF, compressed tiled TIFF, PNG and zarr, where the libraries exist."""
        files = {"npy": Path(d) / "a.npy"}
        np.save(files["npy"], a)
        try:
            import tifffile
            files["tif"] = Path(d) / "a.tif"
            tifffile.imwrite(files["tif"], a)
            files["tif-tiled-zlib"] = Path(d) / "b.tif"
            tifffile.imwrite(files["tif-tiled-zlib"], a, tile=(32, 32), compression="zlib")
        except ImportError:
            pass
        try:
            from PIL import Image
            files["png"] = Path(d) / "a.png"
            Image.fromarray(a).save(files["png"])
        except ImportError:
            pass
        try:
            import zarr
            g = zarr.open_group(str(Path(d) / "a.zarr"), mode="w")
            write_zarr_level(g, "0", a)
            write_zarr_level(g, "1", block_mean(a, 2).astype(a.dtype))
            g.attrs["multiscales"] = [{"version": "0.4", "datasets": [{"path": "0"}, {"path": "1"}]}]
            files["zarr"] = Path(d) / "a.zarr"
        except ImportError:
            pass
        return files

    def test_reduce_factor(self):
        self.assertEqual(R.reduce_factor((100, 100), 64, 16, max_pixels=10_000), 1)      # within the budget
        self.assertEqual(R.reduce_factor((100, 101), 64, 16, max_pixels=10_000), 2)      # letters stay 32 px tall
        self.assertEqual(R.reduce_factor((100, 101), 95.9, 16, max_pixels=10_000), 2)
        self.assertEqual(R.reduce_factor((1000, 1000), 31, 16, max_pixels=10_000), 1)    # letters too small to reduce
        self.assertEqual(R.reduce_factor((1000, 1000), None, 16, max_pixels=10_000), 10)  # no size: fit the budget
        self.assertEqual(R.reduce_factor((41600, 79600), 1376), 43)                      # a whole 2.4 um map
        self.assertEqual(R.reduce_factor((2600, 4975), 86), 1)

    def test_load_reduced_block_averages_every_format(self):
        a = np.random.default_rng(0).integers(0, 60000, (203, 310)).astype(np.uint16)
        want = block_mean(a[3:200, 5:300], 4)
        with tempfile.TemporaryDirectory() as d:
            files = self.image_files(d, a)
            for kind, f in files.items():
                img, k, shape = R.load_reduced(f, crop=(3, 200, 5, 300), letter_px=128, max_pixels=1000)
                self.assertEqual((k, shape, img.shape, img.dtype), (4, (197, 295), want.shape, np.float32), kind)
                np.testing.assert_allclose(img, want, rtol=1e-6, err_msg=kind)
                # within the budget nothing changes: exactly load_image's array
                img, k, shape = R.load_reduced(f, crop=(3, 200, 5, 300), letter_px=128)
                self.assertEqual((k, shape), (1, (197, 295)), kind)
                self.assertTrue(np.array_equal(img, R.load_image(f, crop=(3, 200, 5, 300))), kind)
                self.assertTrue(np.array_equal(R.load_reduced(f)[0], R.load_image(f)), kind)
            if "tif-tiled-zlib" in files:   # a compressed TIFF without zarr: decoded in its stored type, then banded
                with mock.patch.dict(sys.modules, {"zarr": None}):
                    img, k, _ = R.load_reduced(files["tif-tiled-zlib"], letter_px=128, max_pixels=1000)
                np.testing.assert_allclose(img, block_mean(a, 4), rtol=1e-6)

    def test_block_mean_reads_tile_aligned_bands(self):
        a = np.random.default_rng(1).random((101, 47)).astype(np.float32)
        reads = []

        class Spy:
            shape, dtype, chunks = a.shape, a.dtype, (10, 47)

            def __getitem__(self, idx):
                reads.append((idx[0].start, idx[0].stop))
                return a[idx]

        src = R._Source(Spy(), "spy", chunk_rows=10)
        got = R._block_mean(src, 2, 101, 1, 47, 3, band_pixels=200)
        np.testing.assert_allclose(got, block_mean(a[2:101, 1:47], 3), rtol=1e-6)
        self.assertEqual(reads[0][0], 2)
        for (r0, r1), (n0, _) in zip(reads, reads[1:]):
            self.assertEqual(r1, n0)                   # contiguous, nothing read twice
            self.assertEqual(r1 % 10, 0)               # every band ends on a tile edge
        self.assertTrue(all(r1 - r0 <= 10 for r0, r1 in reads))

    def test_colour_png_is_reduced_to_pillow_grey(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        rgb = np.random.default_rng(2).integers(0, 256, (64, 96, 3)).astype(np.uint8)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.png"
            Image.fromarray(rgb).save(f)
            img, k, _ = R.load_reduced(f, letter_px=64, max_pixels=100)
            grey = np.asarray(Image.open(f).convert("F"), np.float64)
        self.assertEqual(k, 2)
        np.testing.assert_allclose(img, block_mean(grey, 2), atol=1e-3)

    def test_zarr_input_and_levels(self):
        try:
            import zarr
        except ImportError:
            self.skipTest("zarr not installed")
        a = np.arange(40 * 64, dtype=np.uint16).reshape(40, 64)
        with tempfile.TemporaryDirectory() as d:
            g = Path(self.image_files(d, a)["zarr"])
            self.assertTrue(np.array_equal(R.load_image(g), a))                      # OME-Zarr: level 0
            self.assertTrue(np.array_equal(R.load_image(g, key="1"), block_mean(a, 2).astype(np.uint16)))
            self.assertTrue(np.array_equal(R.load_image(g, crop=(5, 9, 10, 20)), a[5:9, 10:20]))
            with self.assertRaisesRegex(ValueError, "no array 'x'"):
                R.load_image(g, key="x")
            plain = zarr.open_group(str(Path(d) / "two.zarr"), mode="w")
            write_zarr_level(plain, "ink", a)
            write_zarr_level(plain, "mask", a)
            with self.assertRaisesRegex(ValueError, "pick one with --key"):
                R.load_image(Path(d) / "two.zarr")
            self.assertTrue(np.array_equal(R.load_image(Path(d) / "two.zarr", key="mask"), a))
            arr = zarr.open_array(str(Path(d) / "one.zarr"), mode="w", shape=a.shape, dtype=a.dtype, chunks=(8, 8))
            arr[:] = a
            self.assertTrue(np.array_equal(R.load_image(Path(d) / "one.zarr"), a))
            with self.assertRaisesRegex(ValueError, "does not apply"):
                R.load_image(Path(d) / "one.zarr", key="0")
            with mock.patch.dict(sys.modules, {"zarr": None}):
                with self.assertRaisesRegex(ImportError, "pip install zarr"):
                    R.load_image(g)

    def test_reduced_read_reports_input_pixels(self):
        small = lined_image()
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
        ref = R.analyze(small, net, letter_px=16, nulls=2, p_min=0.0)
        big = R.analyze(small, net, letter_px=48, nulls=2, p_min=0.0, input_scale=3)
        given = R.analyze(small, net, letter_px=48, nulls=2, p_min=0.0, input_scale=3, lines=[3 * L["y"] for L in ref["lines"]])
        self.assertEqual((big["letter_px"], big["input_scale"], big["reduced_shape"], big["input_shape"]),
                         (48.0, 3, [150, 400], [450, 1200]))
        self.assertEqual(ref["input_scale"], 1)
        self.assertNotIn("reduced_shape", ref)
        self.assertAlmostEqual(big["working_scale"], ref["working_scale"] / 3, places=4)
        self.assertEqual(big["control"], ref["control"])
        self.assertTrue(ref["lines"] and sum(len(L["letters"]) for L in ref["lines"]))
        for res in (big, given):
            self.assertEqual(len(res["lines"]), len(ref["lines"]))
            for L, R0 in zip(res["lines"], ref["lines"]):
                self.assertAlmostEqual(L["y"], 3 * R0["y"], delta=0.2)
                self.assertEqual([(l["glyph"], l["p"], l["kept"]) for l in L["letters"]],
                                 [(l["glyph"], l["p"], l["kept"]) for l in R0["letters"]])
                for l, l0 in zip(L["letters"], R0["letters"]):
                    np.testing.assert_allclose(l["box"], [3 * v for v in l0["box"]], atol=0.2)
        self.assertEqual([c["x1"] for c in big["columns"]], [3 * c["x1"] for c in ref["columns"]])
        self.assertIn("block-averaged by 3", R.text_summary(big))

    def test_cli_reads_a_big_image_block_averaged(self):
        big = np.kron(lined_image(), np.ones((4, 4), np.float32))          # letters 64 px tall
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "big.npy"
            np.save(img, big)
            code, out, err = run_cli(["letterread", str(img), "--weights", str(w), "--letter-px", "64", "--nulls", "1",
                                      "--max-mpx", "0.5", "--json"])
            self.assertEqual(code, 0, err)
            res = json.loads(out)
            self.assertEqual((res["input_scale"], res["input_shape"], res["reduced_shape"], res["letter_px"]),
                             (2, [600, 1600], [300, 800], 64.0))
            self.assertIn("block-averaging by 2", err)
            self.assertIn("orientation", res)
            # the same as reading the half-size image with every number doubled
            net = R.LineNet(w)
            ref = R.read(np.kron(lined_image(), np.ones((2, 2), np.float32)), net, letter_px=32, nulls=1)
            self.assertEqual([L["ink_only"] for L in res["lines"]], [L["ink_only"] for L in ref["lines"]])
            self.assertEqual(res["control"]["null_letters_kept"], ref["control"]["null_letters_kept"])
            self.assertEqual(res["orientation"]["letters_kept"], ref["orientation"]["letters_kept"])
            for L, L0 in zip(res["lines"], ref["lines"]):
                for l, l0 in zip(L["letters"], L0["letters"]):
                    np.testing.assert_allclose(l["box"], [2 * v for v in l0["box"]], atol=0.2)

    def test_cli_budget_default_matches_the_module(self):
        args = cli.build_parser().parse_args(["letterread", "x.png", "--weights", "w.npz"])
        self.assertEqual(args.max_mpx * 1e6, R.MAX_PIXELS)
        self.assertEqual(args.overlay_max_side, R.OVERLAY_MAX_SIDE)

    def test_letter_size_in_physical_units(self):
        self.assertAlmostEqual(R.letter_px_from_units(3.3, 38.4), 85.9375)
        for mm, um in ((3.3, None), (None, 38.4), (0, 38.4), (3.3, -1)):
            with self.assertRaises(ValueError):
                R.letter_px_from_units(mm, um)
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "img.npy"
            np.save(img, lined_image())
            base = ["letterread", str(img), "--weights", str(w), "--nulls", "1", "--no-orientation", "--json"]
            code, out, err = run_cli(base + ["--letter-mm", "0.16", "--um-per-px", "10"])
            self.assertEqual(code, 0, err)
            res = json.loads(out)
            self.assertEqual((res["letter_px"], res["letter_mm"], res["um_per_px"]), (16.0, 0.16, 10.0))
            self.assertIn("16.00 px", err)                                      # the value used is printed
            self.assertIn("0.16 mm at 10 um per pixel", R.text_summary(res))
            for extra, words in ((["--letter-mm", "3.3"], "--um-per-px"), (["--um-per-px", "10"], "--letter-mm"),
                                 (["--letter-px", "16", "--letter-mm", "3.3", "--um-per-px", "10"], "once")):
                with mock.patch.object(R, "read", side_effect=AssertionError("read without a clear letter size")):
                    code, _, err = run_cli(base + extra)
                self.assertEqual(code, 2)
                self.assertIn(words, err)

    def test_no_letter_size_stops_the_command_line_only(self):
        blank = np.zeros((150, 400), np.float32)            # no line pitch to estimate from
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "blank.npy"
            np.save(img, blank)
            code, out, err = run_cli(["letterread", str(img), "--weights", str(w), "--nulls", "1"])
            self.assertEqual((code, out), (2, ""))
            self.assertIn("--letter-px", err)
            self.assertIn("--letter-mm", err)
            net = R.LineNet(w)
        # Python callers (the benchmark scripts) keep the old fallback unless they ask otherwise.
        self.assertEqual(R.analyze(blank, net, nulls=1, scale_search=False)["letter_px_from"], "image height / 4")
        with self.assertRaisesRegex(ValueError, "no letter size"):
            R.analyze(blank, net, nulls=1, letter_px_fallback=False)

    def test_scale_search_table_in_the_summary(self):
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
        res = R.analyze(lined_image(), net, nulls=2)
        text = R.text_summary(res)
        self.assertIn("scale search around the first guess of", text)
        self.assertEqual(res["letter_px_first_guess"], round(R.estimate_letter_px(R.normalize(lined_image()))[0], 2))
        for t in res["scale_search"]:
            self.assertIn(f"{t['letter_px']:>9} px: {t['letters_kept']:>4} kept", text)
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("  * ")), 1)

    def test_given_letter_size_is_checked_against_the_line_pitch(self):
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
        ok = R.read(lined_image(), net, letter_px=16, nulls=1, orientation=False)
        self.assertNotIn("warning", ok["letter_px_check"])
        self.assertAlmostEqual(ok["letter_px_check"]["ratio"], 16 / R.estimate_letter_px(R.normalize(lined_image()))[0], 2)
        off = R.read(lined_image(), net, letter_px=40, nulls=1, orientation=False)
        self.assertIn("2.5", off["letter_px_check"]["warning"])
        self.assertIn("warning:", R.text_summary(off))
        self.assertNotIn("letter_px_check", R.read(np.zeros((150, 400)), net, letter_px=16, nulls=1, orientation=False))

    def test_read_normalizes_once_and_matches_separate_reads(self):
        img = lined_image()
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
        with mock.patch.object(R, "normalize_info", wraps=R.normalize_info) as spy:
            res = R.read(img, net, letter_px=16, nulls=2)
        self.assertEqual(spy.call_count, 1)
        ref = R.analyze(img, net, letter_px=16, nulls=2)
        self.assertEqual((res["lines"], res["control"]), (ref["lines"], ref["control"]))
        for name, flipped in (("mirrored", img[:, ::-1]), ("rot180", img[::-1, ::-1]),
                              ("rot90", np.rot90(img, -1)), ("rot270", np.rot90(img, 1))):   # turned clockwise
            alone = R.analyze(flipped, net, letter_px=16, nulls=0, p_min=res["p_min"])
            self.assertEqual(res["orientation"]["letters_kept"][name], alone["control"]["letters_kept"])

    def test_cli_progress_and_memory_advice_on_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "img.npy"
            np.save(img, lined_image())
            base = ["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "1", "--json"]
            code, out, err = run_cli(base)
            self.assertEqual(code, 0)
            self.assertIn("reading at letter height 16.0 px", err)
            self.assertIn("orientation read: mirrored", err)
            json.loads(out)                                                     # stdout stays clean JSON
            self.assertEqual(run_cli(base + ["--quiet"])[2], "")
            self.assertEqual(run_cli(base + ["--out", str(Path(d) / "r.json")])[2].splitlines()[-1],
                             f"wrote {Path(d) / 'r.json'}")                     # each file written is named
            self.assertNotIn("wrote", run_cli(base + ["--quiet", "--out", str(Path(d) / "r.json")])[2])
            no_size = [a for a in base if a not in ("--letter-px", "16")]
            with mock.patch.object(R, "load_reduced", side_effect=MemoryError()):
                code, _, err = run_cli(no_size)
                self.assertEqual(code, 2)
                for words in ("out of memory", "--letter-px", "--max-mpx", "--crop"):
                    self.assertIn(words, err)
                # letters too small to block-average: only a window (or a better letter size) helps
                for px, small in (("16", True), ("63", True), ("64", False)):
                    code, _, err = run_cli(no_size + ["--letter-px", px])
                    self.assertEqual(code, 2)
                    self.assertIn("--crop", err)
                    self.assertEqual("too small to block-average" in err, small, px)
                    self.assertEqual("--max-mpx" in err, not small, px)

    def test_command_line_errors_name_the_fix(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            empty = Path(d) / "empty.npy"
            np.save(empty, np.zeros((0, 5), np.float32))
            code, _, err = run_cli(["letterread", str(empty), "--weights", str(w), "--letter-px", "16"])
            self.assertEqual(code, 2)
            self.assertIn("the image is empty (0 x 5 px)", err)
            img = Path(d) / "img.npy"
            np.save(img, lined_image())
            for module in ("numpy", "PIL", "tifffile"):
                missing = ImportError(f"No module named {module!r}", name=module)
                with mock.patch.object(R, "load_reduced", side_effect=missing):
                    code, _, err = run_cli(["letterread", str(img), "--weights", str(w), "--letter-px", "16"])
                self.assertEqual(code, 2)
                self.assertIn(f"No module named {module!r}", err)
                self.assertIn('python -m pip install "scrolls-workbench[reader]"', err)
            with mock.patch.object(R, "load_reduced", side_effect=ImportError("No module named 'zarr'", name="zarr")):
                err = run_cli(["letterread", str(img), "--weights", str(w), "--letter-px", "16"])[2]
            self.assertIn("python -m pip install zarr", err)
            with mock.patch.object(R, "load_reduced", side_effect=ImportError("something else")):
                err = run_cli(["letterread", str(img), "--weights", str(w), "--letter-px", "16"])[2]
            self.assertEqual(err.strip(), "something else")
        with self.assertRaisesRegex(ValueError, r"the image is empty \(3 x 0 px\)"):
            R._window(None, (3, 0), "x")


@unittest.skipIf(np is None, "numpy not installed")
class ControlStatusTest(unittest.TestCase):
    """Status codes, the floor, per-line and per-column counts, the control map and where they are shown."""

    def test_status_codes(self):
        S = R.control_status
        self.assertEqual(S(50, []), "no_control")
        self.assertEqual(S(50, [], control_n=0), "no_control")
        self.assertEqual(S(40, [2, 5]), "strong")
        self.assertEqual(S(15, [2, 5]), "weak")                   # above every null, not three times the largest
        self.assertEqual(S(16, [2, 5]), "strong")
        self.assertEqual(S(5, [2, 5]), "none")                    # a tie with the largest null is not above it
        self.assertEqual(S(4, [0, 1]), "too_few")                 # verdict() called this "well above every null"
        self.assertEqual(S(9, [0, 0]), "too_few")
        self.assertEqual(S(10, [0, 0]), "strong")                 # a null of 0 counts as 1, as in verdict()
        self.assertEqual(S(3, [5, 1]), "none")                    # few letters and below a null: noise, not too_few
        self.assertEqual(S(0, [0, 0]), "none")
        self.assertEqual(S(4, [0, 1], min_letters=4), "strong")
        # the control map: more than three times its letters for strong, more than it at all for weak
        self.assertEqual(S(40, [2, 5], control_n=13), "strong")
        self.assertEqual(S(40, [2, 5], control_n=14), "weak")
        self.assertEqual(S(40, [2, 5], control_n=40), "none")
        self.assertEqual(S(40, [2, 5], control_n=0), "strong")
        self.assertEqual(S(8, [1, 1], control_n=9), "none")
        self.assertEqual(S(8, [1, 1], control_n=2), "too_few")

    def test_status_keeps_the_old_verdicts_meaning(self):
        old = {"confident letters well above every null": "strong",
               "more confident letters than every null, but within a factor of three": "weak",
               "confident letters NOT above the nulls: treat every letter here as noise": "none"}
        for n in range(0, 60):
            for nulls in ([0], [1, 0], [3, 7], [12], [19, 2, 5, 8]):
                st = R.control_status(n, nulls)
                if n >= R.MIN_LETTERS or st == "none":
                    self.assertEqual(old[R.verdict(n, nulls)], st, (n, nulls))
                else:
                    self.assertEqual(st, "too_few")
                    self.assertNotIn("NOT", R.verdict(n, nulls))
        self.assertEqual(R.verdict(10, []), "no control run (nulls=0): nothing here can be trusted")

    def test_report_ratio_and_status_line(self):
        c = R.control_report(122, [43, 33, 27, 28])
        self.assertEqual((c["ratio"], c["status"], c["min_letters"]), (2.84, "weak", 10))
        self.assertNotIn("control_map", c)
        self.assertEqual(R.status_line(c), "weak (122 letters kept; nulls 43, 33, 27, 28, ratio 2.84 to the largest). "
                                           "Confident letters above every control, but not three times above all of "
                                           "them: weak evidence.")
        self.assertEqual(R.status_line(c, sentence=False),
                         "weak (122 letters kept; nulls 43, 33, 27, 28, ratio 2.84 to the largest)")
        c = R.control_report(6, [1, 0], control_n=0, min_letters=8)
        self.assertEqual((c["ratio"], c["control_map"]), (6.0, {"letters_kept": 0, "ratio": 6.0}))
        self.assertEqual(R.status_line(c), "too_few (6 letters kept; nulls 1, 0, ratio 6 to the largest; control map 0, "
                                           "ratio 6). Too few confident letters to judge (fewer than 8).")
        c = R.control_report(30, [])
        self.assertIsNone(c["ratio"])
        self.assertEqual(R.status_line(c), "no_control (30 letters kept). No control run (nulls=0): nothing here can be "
                                           "trusted.")
        for st, text in R.STATUS_TEXT.items():
            self.assertFalse(chr(0x2014) in text or chr(0x2013) in text, st)   # no long dashes
            self.assertEqual(R.control_report(*{"strong": (40, [1]), "weak": (20, [10]), "none": (1, [5]),
                                                "too_few": (5, [0]), "no_control": (5, [])}[st])["status"], st)

    def test_counts_per_line_and_per_column(self):
        img = two_column_image(gap=64)
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
        res = R.analyze(img, net, letter_px=16, nulls=4, p_min=0.6)
        c, cols = res["control"], res["columns"]
        self.assertEqual(len(cols), 2)
        self.assertEqual(sum(col["control"]["letters_kept"] for col in cols), c["letters_kept"])
        self.assertEqual([sum(col["control"]["null_letters_kept"][k] for col in cols) for k in range(4)],
                         c["null_letters_kept"])
        for ci, col in enumerate(cols):
            cc = col["control"]
            self.assertEqual(cc["letters_kept"], sum(r["n_kept"] for r in res["lines"] if r["column"] == ci))
            self.assertAlmostEqual(cc["chance"], float(np.mean(cc["null_letters_kept"])), places=2)
            self.assertEqual(cc["status"], R.control_status(cc["letters_kept"], cc["null_letters_kept"]))
            for r in res["lines"]:
                if r["column"] == ci:   # the nulls scramble positions within the column: one chance rate per column
                    self.assertAlmostEqual(r["chance"], cc["chance"] / col["lines"], places=1)
        self.assertEqual(c["status"], R.control_status(c["letters_kept"], c["null_letters_kept"]))
        self.assertEqual(c["ratio"], round(c["letters_kept"] / max(1, max(c["null_letters_kept"])), 2))
        floor = R.analyze(img, net, letter_px=16, nulls=4, p_min=0.6, min_letters=c["letters_kept"] + 1)
        self.assertIn(floor["control"]["status"], ("too_few", "none"))
        self.assertEqual(floor["lines"], res["lines"])
        none = R.analyze(img, net, letter_px=16, nulls=0, p_min=0.6)
        self.assertEqual(none["control"]["status"], "no_control")
        self.assertTrue(all(r["chance"] is None for r in none["lines"]))
        self.assertTrue(all(col["control"]["chance"] is None for col in none["columns"]))
        text = R.text_summary(res)
        for words in ("status: " + R.status_line(c), "column 1 (x ", "kept, chance"):
            self.assertIn(words, text)

    def test_control_map_is_read_on_the_images_lines(self):
        img = lined_image()
        with tempfile.TemporaryDirectory() as d:
            net = R.LineNet(random_weights(Path(d) / "w.npz"))
        res = R.read(img, net, letter_px=16, nulls=2, p_min=0.0, control=img.copy())
        cm = res["control"]["control_map"]
        self.assertGreater(cm["letters_kept"], 0)
        self.assertEqual(cm["letters_kept"], res["control"]["letters_kept"])    # the same map: the check fails
        self.assertEqual(cm["ratio"], 1.0)
        self.assertEqual(res["control"]["status"], "none")
        self.assertEqual([r["control_map_kept"] for r in res["lines"]], [r["n_kept"] for r in res["lines"]])
        alone = R.read(img, net, letter_px=16, nulls=2, p_min=0.0)
        self.assertEqual(res["lines"][0]["letters"], alone["lines"][0]["letters"])   # the control changes no letter
        self.assertEqual(res["p_min"], alone["p_min"])
        self.assertEqual(res["orientation"], alone["orientation"])
        # A flat control has no lines of its own; it is still read on every line of the image.
        flat = R.read(img, net, letter_px=16, nulls=2, control=np.full_like(img, 0.3))
        self.assertEqual(len([r for r in flat["lines"] if "control_map_kept" in r]), len(flat["lines"]))
        self.assertEqual(sum(r["control_map_kept"] for r in flat["lines"]), flat["control"]["control_map"]["letters_kept"])
        self.assertEqual(flat["control"]["status"], R.control_status(
            flat["control"]["letters_kept"], flat["control"]["null_letters_kept"],
            flat["control"]["control_map"]["letters_kept"]))
        with self.assertRaisesRegex(ValueError, "same surface"):
            R.read(img, net, letter_px=16, nulls=1, control=img[:-1])
        with mock.patch.object(R, "analyze", wraps=R.analyze) as spy:
            R.read(img, net, letter_px=16, nulls=1, control=img)
        self.assertIsNotNone(spy.call_args_list[0].kwargs["control"])
        self.assertTrue(all("control" not in c.kwargs for c in spy.call_args_list[1:]))   # orientation reads: no control
        self.assertIn("control map: ", R.text_summary(res))

    def test_cli_control_map_and_floor(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img, rev, short = Path(d) / "img.npy", Path(d) / "rev.npy", Path(d) / "short.npy"
            np.save(img, lined_image())
            np.save(rev, lined_image(seed=5)[:, ::-1].copy())
            np.save(short, lined_image()[:-10])
            base = ["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "2", "--no-orientation"]
            code, out, err = run_cli(base + ["--json", "--control", str(rev), "--min-letters", "3"])
            self.assertEqual(code, 0, err)
            c = json.loads(out)["control"]
            self.assertEqual((c["control_map"]["file"], c["min_letters"]), (rev.name, 3))   # the name, no folder
            self.assertIn(c["status"], R.STATUS_TEXT)
            code, out, err = run_cli(base + ["--control", str(rev), "--crop", "0", "90", "0", "300"])
            self.assertEqual(code, 0, err)
            self.assertIn(f"control map {rev.name}: ", out)
            self.assertIn("status: ", out)
            for extra, words in ((["--control", str(short)], "same surface"),
                                 (["--control", str(Path(d) / "missing.npy")], "no such file"),
                                 (["--min-letters", "0"], "--min-letters")):
                with mock.patch.object(R, "read", side_effect=AssertionError("read before the checks")):
                    code, _, err = run_cli(base + extra)
                self.assertEqual(code, 2, extra)
                self.assertIn(words, err)
        args = cli.build_parser().parse_args(["letterread", "x.png", "--weights", "w.npz"])
        self.assertEqual(args.min_letters, R.MIN_LETTERS)

    def test_eval_controls_windows_script(self):
        sys.path.insert(0, str(ROOT / "scripts" / "letters"))
        try:
            import eval_controls
        finally:
            sys.path.remove(str(ROOT / "scripts" / "letters"))
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "img.npy"
            np.save(img, lined_image())                                           # 150 x 400
            with contextlib.redirect_stdout(io.StringIO()):
                res = eval_controls.windows(img, w, letter_px=16, size=(75, 200), copies=1, nulls=1)
        self.assertEqual((res["summary"]["as_stored"]["windows"], res["summary"]["shuffled"]["windows"]), (4, 4))
        self.assertTrue(all(r["status"] in R.STATUS_TEXT and r["old"] in ("well above", "above", "NOT above")
                            for r in res["windows"]))

    def test_banner_shows_the_status_and_its_counts(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        res = {"letter_px": 16.0, "input_scale": 1, "lines": [],
               "control": R.control_report(122, [43, 33, 27, 28], control_n=40)}
        text = R.banner_text(res)
        self.assertEqual(text.split("\n"), [R.NOTE, "Controls: " + R.status_line(res["control"])])
        self.assertEqual(R.banner_text({"lines": []}), R.NOTE)
        for width in (60, 400, 4000):
            lines = R.banner_layout(width, text)[1]
            self.assertEqual(" ".join(lines), " ".join(text.split()), width)
            self.assertTrue(any(line.startswith("Controls:") for line in lines), width)   # on a line of its own
        plain = R.overlay_geometry((100, 400), {"letter_px": 16.0, "input_scale": 1, "lines": []})
        self.assertGreater(R.overlay_geometry((100, 400), res)["banner_rows"], plain["banner_rows"])


def unturn(v, rotate, mirror):
    """The input that orient(input, rotate, mirror) turns into v."""
    b = np.rot90(v, k=rotate // 90)
    return np.ascontiguousarray(b[:, ::-1] if mirror else b)


def save_png(path, a, exif_tag=None):
    from PIL import Image
    kw = {}
    if exif_tag is not None:
        ex = Image.Exif()
        ex[R.EXIF_ORIENTATION_TAG] = exif_tag
        kw["exif"] = ex
    Image.fromarray(np.ascontiguousarray(a)).save(path, **kw)
    return path


@unittest.skipIf(np is None, "numpy not installed")
class TurnsAndPhotosTest(unittest.TestCase):
    """Deskew limit and the frame of y, turned reads (rotate, mirror), polarity auto, EXIF orientation, overlay."""

    VIEWS = [(r, m) for r in (0, 90, 180, 270) for m in (False, True)]

    def net(self):
        with tempfile.TemporaryDirectory() as d:
            return R.LineNet(random_weights(Path(d) / "w.npz"))

    def test_orient_and_view_boxes_round_trip(self):
        a = np.random.default_rng(0).random((5, 7))
        self.assertIs(R.orient(a), a)
        with self.assertRaisesRegex(ValueError, "rotate"):
            R.orient(a, 45)
        self.assertTrue(np.array_equal(R.orient(a, 90), np.rot90(a, -1)))           # clockwise
        self.assertTrue(np.array_equal(R.orient(a, 0, True), a[:, ::-1]))
        self.assertTrue(np.array_equal(R.orient(a, 180), a[::-1, ::-1]))           # the old rot180 read
        for r, m in self.VIEWS:
            v = R.orient(a, r, m)
            self.assertTrue(np.array_equal(R.orient(unturn(v, r, m), r, m), v))
            for i in range(v.shape[0]):
                for j in range(v.shape[1]):
                    y0, y1, x0, x1 = R.view_box_to_input([i, i + 1, j, j + 1], r, m, a.shape)
                    self.assertEqual((y1 - y0, x1 - x0), (1, 1))
                    self.assertEqual(a[int(y0), int(x0)], v[i, j], (r, m, i, j))

    def test_compose_view_matches_turning_twice(self):
        a = np.arange(12.0).reshape(3, 4)
        for r, m in self.VIEWS:
            for name, (r2, m2) in R.ORIENTATIONS.items():
                twice = R.orient(R.orient(a, r, m), r2, m2)
                self.assertTrue(np.array_equal(twice, R.orient(a, *R.compose_view(r, m, name))), (r, m, name))
        self.assertEqual(R.view_options(90, True), "--rotate 90 --mirror")
        self.assertEqual(R.view_options(0, False), "")

    def test_turned_read_maps_boxes_to_input_pixels(self):
        img = R.normalize(lined_image())                                  # 150 x 400, lines level
        net = self.net()
        ref = R.read(img, net, letter_px=16, nulls=1, normalized=True)
        letters = lambda res, key: [[(l["glyph"], l["p"], l[key]) for l in L["letters"]] for L in res["lines"]]
        for r, m in ((90, False), (0, True), (270, True), (180, False)):
            given = unturn(img, r, m)                                     # the image stored turned
            res = R.read(given, net, letter_px=16, nulls=1, normalized=True, rotate=r, mirror=m)
            self.assertEqual(letters(res, "view_box"), letters(ref, "box"), (r, m))
            self.assertEqual(res["control"], ref["control"])
            self.assertEqual(res["orientation"]["letters_kept"], ref["orientation"]["letters_kept"])
            self.assertEqual(res["orientation"]["best_view"],
                             dict(zip(("rotate", "mirror"), R.compose_view(r, m, ref["orientation"]["best"]))))
            self.assertEqual((res["view"]["rotate"], res["view"]["mirror"], res["view"]["shape"]), (r, m, [150, 400]))
            self.assertEqual(res["input_shape"], list(given.shape))
            for L in res["lines"]:
                for l in L["letters"]:
                    self.assertEqual(l["box"], R.view_box_to_input(l["view_box"], r, m, given.shape))
        # by hand for a quarter turn: a box [y0, y1, x0, x1] of the upright image lies at rows W - x1 to W - x0 and
        # columns y0 to y1 of the image stored turned a quarter counter-clockwise
        res = R.read(np.rot90(img, 1), net, letter_px=16, nulls=1, normalized=True, rotate=90, orientation=False)
        for L, Lref in zip(res["lines"], ref["lines"]):
            for l, lref in zip(L["letters"], Lref["letters"]):
                y0, y1, x0, x1 = lref["box"]
                self.assertEqual(l["box"], [round(400 - x1, 1), round(400 - x0, 1), y0, y1])
        self.assertIn("read turned (--rotate 90)", R.text_summary(res))
        # a block-averaged read: boxes in input pixels through the block size
        red = R.read(np.rot90(img, 1), net, letter_px=32, nulls=1, normalized=True, rotate=90, orientation=False,
                     input_scale=2)
        self.assertEqual((red["input_shape"], red["reduced_shape"], red["view"]["shape"]), ([800, 300], [400, 150], [300, 800]))
        for L in red["lines"]:
            for l in L["letters"]:
                self.assertEqual(l["box"], R.view_box_to_input(l["view_box"], 90, False, (800, 300)))

    def test_deskew_angles_are_symmetric_and_unchanged_for_whole_steps(self):
        for m in (R.DESKEW_DEG, 3, 0.5, 12):           # the angles np.arange always gave, in the same order
            self.assertEqual(R.deskew_angles(m).tolist(), np.arange(-m, m + 1e-9, R.DESKEW_STEP).tolist())
        odd = R.deskew_angles(5.2).tolist()            # arange gave -5.2 to 4.8: lopsided, and never 5.2
        self.assertEqual((odd[:3], odd[-3:]), ([-5.2, -5.0, -4.5], [4.5, 5.0, 5.2]))
        self.assertEqual(odd, sorted(-a for a in odd))
        self.assertEqual(R.deskew_angles(0.3).tolist(), [-0.3, 0.0, 0.3])

    def test_deskew_limit_warning_and_off(self):
        self.assertTrue(R.deskew_at_limit(6.0) and R.deskew_at_limit(-6.0, 6.0))
        self.assertFalse(R.deskew_at_limit(5.5, 6.0) or R.deskew_at_limit(0.0, 0))
        self.assertTrue(R.deskew_at_limit(5.2, 5.2) and R.deskew_at_limit(-5.2, 5.2))
        self.assertFalse(R.deskew_at_limit(5.0, 5.2))
        tilted = R.shear(R.normalize(lined_image(n_lines=5)), -5.0)
        net = self.net()
        kw = dict(letter_px=16, nulls=1, normalized=True)
        msgs = []
        lim = R.analyze(tilted, net, deskew_deg=3, progress=msgs.append, **kw)
        self.assertEqual((lim["deskew_deg"], lim["deskew_max_deg"], lim["columns"][0]["deskew_at_limit"]), (3.0, 3, True))
        self.assertIn("--deskew 6", lim["deskew_warning"])
        self.assertIn("warning: " + lim["deskew_warning"], msgs)
        self.assertIn("warning: " + lim["deskew_warning"], R.text_summary(lim))
        wide = R.analyze(tilted, net, deskew_deg=8, **kw)
        self.assertEqual((wide["deskew_deg"], wide["columns"][0]["deskew_at_limit"]), (5.0, False))
        self.assertNotIn("deskew_warning", wide)
        off = R.analyze(tilted, net, deskew_deg=0, **kw)
        self.assertEqual((off["deskew_deg"], off["deskew_max_deg"], off["columns"][0]["deskew_at_limit"]), (0.0, 0, False))

    def test_given_lines_are_rows_at_the_middle_and_follow_the_deskew(self):
        a = R.normalize(lined_image(n_lines=4, pitch=30))                 # 150 x 400, lines centred on rows 30 to 120
        tilted = R.shear(a, -3.0)                    # a line centred on row c now lies at row c + (x - 200) tan 3 deg
        ys = [30, 60, 90, 120]                       # the rows of the lines at the middle column, x = 200
        net = self.net()
        kw = dict(letter_px=16, lines=ys, nulls=1, normalized=True, p_min=0.5)
        on = R.analyze(tilted, net, **kw)
        level = R.analyze(a, net, deskew_deg=0, **kw)
        off = R.analyze(tilted, net, deskew_deg=0, **kw)
        letters = lambda res: [[(l["glyph"], l["p"]) for l in L["letters"]] for L in res["lines"]]
        self.assertEqual(on["deskew_deg"], 3.0)
        self.assertEqual([L["y"] for L in on["lines"]], [30.0, 60.0, 90.0, 120.0])
        self.assertEqual(letters(on), letters(level))        # each band follows its tilted line
        self.assertNotEqual(letters(off), letters(level))    # level bands cut across the tilted lines
        t = math.tan(math.radians(3.0))
        for L in on["lines"]:
            for l in L["letters"]:
                y0, y1, x0, x1 = l["box"]
                self.assertAlmostEqual(0.5 * (y0 + y1), L["y"] + (0.5 * (x0 + x1) - 200) * t, delta=0.2)
        for L in off["lines"]:
            for l in L["letters"]:
                self.assertAlmostEqual(0.5 * (l["box"][0] + l["box"][1]), L["y"], delta=0.1)

    @staticmethod
    def fake_trial_reads(right=40, wrong=4):
        """A stand-in for _analyze_at in polarity_trial, for these sparse test images: an array the right way round
        (ink bright on a dark ground, mean under 0.5) keeps `right` letters against nulls of 6 and 2, an inverted one
        `wrong`; records each call."""
        calls = []

        def fake(arr, net, letter_px, **kw):
            calls.append((arr, letter_px, kw))
            kept = right if float(np.mean(arr)) < 0.5 else wrong
            return {"control": {"letters_kept": kept, "null_letters_kept": [6, 2]}}
        return fake, calls

    def test_polarity_trial_reads_both_ways_and_keeps_the_larger_margin(self):
        net = self.net()
        a = R.normalize(1.0 - lined_image())             # a photo normalised as bright ink: the wrong way round
        fake, calls = self.fake_trial_reads()
        with mock.patch.object(R, "_analyze_at", side_effect=fake):
            t = R.polarity_trial(a, net, "bright", letter_px=32, seed=5)
        self.assertEqual(t["choice"], "dark")
        self.assertEqual((t["rule"], t["letter_px"]), (R.AUTO_RULE, 32.0))
        self.assertEqual(t["dark"], {"letters_kept": 40, "null_letters_kept": [6, 2], "margin": 34, "status": "strong"})
        self.assertEqual((t["bright"]["margin"], t["bright"]["status"]), (-2, "none"))
        (first, h1, kw1), (second, h2, kw2) = calls
        self.assertEqual(first.shape, (75, 200))                           # at the working scale, 16 / 32
        self.assertTrue(np.allclose(second, 1.0 - first))                  # the other polarity: the same image inverted
        self.assertEqual((h1, kw1["nulls"], kw1["seed"], kw1["max_lines"], kw1["fill"]), (16.0, 2, 6, 8, 0.0))
        self.assertAlmostEqual(kw2["fill"], float(np.median(second)))       # dark ink: the ground's grey
        fake, calls = self.fake_trial_reads(right=4, wrong=4)
        with mock.patch.object(R, "_analyze_at", side_effect=fake):
            self.assertEqual(R.polarity_trial(a, net, "bright", letter_px=32)["choice"], "bright")   # a tie: bright
            t = R.polarity_trial(1.0 - a, net, "dark", letter_px=32, rotate=90, lines=[40, 80])
        self.assertEqual(calls[-2][0].shape, (200, 75))                    # turned, as the read will be
        self.assertEqual(calls[-2][2]["lines"], [20.0, 40.0])
        with self.assertRaisesRegex(ValueError, "polarity"):
            R.polarity_trial(a, net, "auto")
        with self.assertRaisesRegex(ValueError, "no letter size"):
            R.polarity_trial(np.zeros((40, 40), np.float32), net, letter_px_fallback=False)

    def test_auto_reads_exactly_as_the_chosen_polarity(self):
        net = self.net()
        photo = 1.0 - lined_image()                                       # dark ink on a light ground
        for img, choice in ((photo, "dark"), (lined_image(), "bright")):
            fake, _ = self.fake_trial_reads()
            with mock.patch.object(R, "_analyze_at", side_effect=fake):
                a, info = R.normalize_auto(img, net, letter_px=16)
            self.assertTrue(np.array_equal(a, R.normalize_for_reading(img, choice)))     # exactly, not 1 - a
            self.assertEqual((info["asked"], info["used"], info["trial"]["choice"]), ("auto", choice, choice))
        trial = {"rule": R.AUTO_RULE, "letter_px": 16.0, "choice": "dark",
                 "dark": {"letters_kept": 40, "null_letters_kept": [6, 2], "margin": 34, "status": "strong"},
                 "bright": {"letters_kept": 4, "null_letters_kept": [6, 2], "margin": -2, "status": "none"}}
        msgs = []
        with mock.patch.object(R, "polarity_trial", return_value=trial):
            auto = R.read(photo, net, letter_px=16, nulls=1, polarity="auto", orientation=False, progress=msgs.append)
            ana = R.analyze(photo, net, letter_px=16, nulls=1, polarity="auto")
            norm = R.read(R.normalize(photo, "bright"), net, letter_px=16, nulls=1, polarity="auto", normalized=True,
                          orientation=False)
        dark = R.read(photo, net, letter_px=16, nulls=1, polarity="dark", orientation=False)
        for res in (auto, ana, norm):
            self.assertEqual((res["lines"], res["control"]), (dark["lines"], dark["control"]))
            self.assertEqual((res["polarity"]["asked"], res["polarity"]["used"]), ("auto", "dark"))
            self.assertEqual(res["polarity"]["trial"], trial)
            self.assertEqual(res["shear_fill"], dark["shear_fill"])
        self.assertIn("polarity auto: dark ink (quick read at 16 px: as dark ink 40 letters kept, nulls 6, 2; "
                      "as bright ink 4 letters kept, nulls 6, 2)", msgs)
        self.assertIn("polarity auto: dark ink (quick read at 16 px", R.text_summary(auto))

    def test_normalized_auto_inverts_the_control_map_with_the_image(self):
        """A normalised image that auto inverts to dark ink takes its control map with it, so the map stays a control."""
        net = self.net()
        photo = 1.0 - lined_image()                                       # dark ink on a light ground
        trial = {"rule": R.AUTO_RULE, "letter_px": 16.0, "choice": "dark",
                 "dark": {"letters_kept": 40, "null_letters_kept": [6, 2], "margin": 34, "status": "strong"},
                 "bright": {"letters_kept": 4, "null_letters_kept": [6, 2], "margin": -2, "status": "none"}}
        b = R.normalize(photo, "bright")
        with mock.patch.object(R, "polarity_trial", return_value=trial):
            res = R.read(b, net, letter_px=16, nulls=1, p_min=0.0, polarity="auto", normalized=True,
                         orientation=False, control=b)
        dark = R.read(photo, net, letter_px=16, nulls=1, p_min=0.0, polarity="dark", orientation=False, control=photo)
        wrong = R.read(photo, net, letter_px=16, nulls=1, p_min=0.0, polarity="dark", orientation=False,
                       control=1.0 - photo)                               # the control map the other way round
        self.assertEqual(res["control"], dark["control"])
        c = res["control"]
        self.assertGreater(c["letters_kept"], 0)
        self.assertEqual(c["control_map"]["letters_kept"], c["letters_kept"])   # the image is its own control map
        self.assertNotEqual(wrong["control"]["control_map"]["letters_kept"], c["letters_kept"])  # the check can fail

    def test_polarity_trial_measures_the_letter_size_on_the_turned_image(self):
        net = self.net()
        a = R.normalize(lined_image(n_lines=8, width=600))
        fake, calls = self.fake_trial_reads()
        with mock.patch.object(R, "_analyze_at", side_effect=fake):
            flat = R.polarity_trial(a, net, "bright", letter_px_fallback=False)
            turned = R.polarity_trial(np.rot90(a), net, "bright", rotate=90, letter_px_fallback=False)
            mirrored = R.polarity_trial(np.rot90(a)[:, ::-1], net, "bright", rotate=90, mirror=True,
                                        letter_px_fallback=False)
        self.assertEqual(R.estimate_letter_px(a)[1], "line pitch")
        self.assertAlmostEqual(turned["letter_px"], flat["letter_px"], delta=0.03 * flat["letter_px"])
        self.assertAlmostEqual(mirrored["letter_px"], flat["letter_px"], delta=0.03 * flat["letter_px"])
        self.assertEqual(calls[2][0].shape, calls[0][0].shape)              # read at the same size, the right way up

    def test_a_failed_read_checks_the_other_polarity(self):
        net = self.net()
        photo = 1.0 - lined_image()
        trial = {"rule": R.AUTO_RULE, "letter_px": 16.0, "choice": "dark",
                 "dark": {"letters_kept": 40, "null_letters_kept": [6, 2], "margin": 34, "status": "strong"},
                 "bright": {"letters_kept": 4, "null_letters_kept": [6, 2], "margin": -2, "status": "none"}}
        msgs = []
        with mock.patch.object(R, "polarity_trial", return_value=trial) as spy:
            res = R.read(photo, net, letter_px=16, nulls=1, orientation=False, min_letters=10 ** 6, progress=msgs.append)
            self.assertIn(res["control"]["status"], ("none", "too_few"))
            self.assertEqual(spy.call_count, 1)
            self.assertEqual((spy.call_args.args[2], spy.call_args.kwargs["letter_px"]), ("bright", res["letter_px"]))
            hint = res["polarity"]["hint"]
            self.assertIn("reads better as dark ink on a light ground", hint)
            self.assertIn("--polarity dark", hint)
            self.assertIn("hint: " + hint, msgs)
            text = R.text_summary(res)
            self.assertIn("polarity check, as the controls did not pass: quick read at 16 px", text)
            self.assertIn("hint: this image reads better as dark ink", text)
            res["orientation"] = {"letters_kept": {"as_is": 1, "rot90": 5}, "best": "rot90",
                                  "best_view": {"rotate": 90, "mirror": False}}
            self.assertIn("give --rotate 90 (but first the polarity hint above", R.text_summary(res))
            R.read(photo, net, letter_px=16, nulls=0, orientation=False)          # no_control: nothing to check
            auto = R.read(photo, net, letter_px=16, nulls=1, orientation=False, polarity="auto", min_letters=10 ** 6)
            self.assertEqual(spy.call_count, 2)                                   # auto checked once, before the read
            self.assertNotIn("hint", auto["polarity"])
        # the hint needs the other polarity to win and to be strong on its own
        self.assertIsNone(R.polarity_hint(trial, "dark"))
        weak = dict(trial, dark=dict(trial["dark"], status="weak"))
        self.assertIsNone(R.polarity_hint(weak, "bright"))
        back = dict(trial, choice="bright", bright=dict(trial["dark"]), dark=dict(trial["bright"]))
        self.assertIn("bright ink on a dark ground (an ink map)", R.polarity_hint(back, "dark"))

    def test_normalize_auto_alone_is_a_grey_level_guess(self):
        ink_map = lined_image()                                           # bright ink on a dark ground
        photo = 1.0 - ink_map
        self.assertEqual(R.resolve_polarity(0, 0.8, 1, "auto"), "dark")
        self.assertEqual(R.resolve_polarity(0, 0.2, 1, "auto"), "bright")
        self.assertEqual(R.resolve_polarity(0, 0.8, 1, "bright"), "bright")
        with self.assertRaisesRegex(ValueError, "polarity"):
            R.resolve_polarity(0, 0.5, 1, "light")
        for img, used in ((ink_map, "bright"), (photo, "dark")):
            out, info = R.normalize_info(img, "auto")
            self.assertEqual((info["used"], info["rule"]), (used, R.POLARITY_RULE))
            self.assertTrue(np.array_equal(out, R.normalize(img, used)))
        self.assertLess(R.normalize_info(ink_map)[1]["background"], 0.2)
        self.assertGreater(R.normalize_info(photo)[1]["background"], 0.8)
        # papyrus on a white ground: the median is the papyrus, low in the range, so grey levels say bright
        page = np.full((200, 300), 250.0)
        page[20:170, 30:270] = 110.0 + 5 * np.random.default_rng(0).standard_normal((150, 240))   # 60% papyrus
        page[60:64, 60:240] = 30.0                                        # a dark stroke
        self.assertEqual(R.normalize_info(page, "auto")[1]["used"], "bright")
        self.assertIsNone(R.normalize_info(np.full((9, 9), 3.0), "auto")[1]["background"])

    def test_cli_polarity_auto_and_control_map(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img, ctrl = Path(d) / "img.npy", Path(d) / "ctrl.npy"
            np.save(img, 1.0 - lined_image())
            np.save(ctrl, lined_image(seed=5))
            base = ["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "1", "--json",
                    "--no-orientation"]
            trial = {"rule": R.AUTO_RULE, "letter_px": 16.0, "choice": "dark",
                     "dark": {"letters_kept": 40, "null_letters_kept": [6, 2], "margin": 34, "status": "strong"},
                     "bright": {"letters_kept": 4, "null_letters_kept": [6, 2], "margin": -2, "status": "none"}}
            with mock.patch.object(R, "polarity_trial", return_value=trial) as tr, \
                    mock.patch.object(R, "normalize_info", wraps=R.normalize_info) as spy:
                code, out, err = run_cli(base + ["--polarity", "auto", "--control", str(ctrl), "--seed", "3",
                                                 "--deskew", "4", "--lines", "30", "60"])
            self.assertEqual(tr.call_count, 1)
            self.assertEqual(tr.call_args.args[2], "bright")
            kw = tr.call_args.kwargs
            self.assertEqual((kw["letter_px"], kw["seed"], kw["deskew_deg"], kw["lines"], kw["letter_px_fallback"]),
                             (16.0, 3, 4.0, [30.0, 60.0], False))
            self.assertEqual(code, 0, err)
            res = json.loads(out)
            self.assertEqual((res["polarity"]["asked"], res["polarity"]["used"]), ("auto", "dark"))
            self.assertIn("polarity auto: dark ink (quick read at 16 px: as dark ink 40", err)
            # the options as asked on the command line, and file names without their folder
            o = res["options"]
            self.assertEqual((o["polarity"], o["seed"], o["deskew_deg"], o["lines"], o["letter_px_fallback"]),
                             ("auto", 3, 4.0, [30.0, 60.0], False))
            self.assertEqual((res["source"]["file"], res["control"]["control_map"]["file"]), ("img.npy", "ctrl.npy"))
            self.assertNotIn(str(Path(d).resolve()), out)
            self.assertNotIn(str(d), out)
            # bright for the trial, dark for the read, then the control map in the image's polarity
            self.assertEqual([c.args[1] for c in spy.call_args_list], ["bright", "dark", "dark"])

    def test_cli_rotate_mirror_and_deskew_options(self):
        args = cli.build_parser().parse_args(["letterread", "x.png", "--weights", "w.npz"])
        self.assertEqual((args.deskew, args.rotate, args.mirror), (R.DESKEW_DEG, 0, False))
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            up, turned = Path(d) / "up.npy", Path(d) / "turned.npy"
            np.save(up, lined_image())
            np.save(turned, unturn(lined_image(), 270, True))
            base = ["--weights", str(w), "--letter-px", "16", "--nulls", "1", "--json"]
            code, out, err = run_cli(["letterread", str(up)] + base)
            ref = json.loads(out)
            code, out, err = run_cli(["letterread", str(turned), "--rotate", "270", "--mirror"] + base)
            self.assertEqual(code, 0, err)
            res = json.loads(out)
            self.assertEqual([L["ink_only"] for L in res["lines"]], [L["ink_only"] for L in ref["lines"]])
            self.assertEqual(res["input_shape"], [400, 150])                # the image as stored
            self.assertEqual((res["view"]["rotate"], res["view"]["mirror"]), (270, True))
            self.assertEqual(res["orientation"]["letters_kept"], ref["orientation"]["letters_kept"])
            code, out, err = run_cli(["letterread", str(up), "--deskew", "0", "--no-orientation"] + base)
            self.assertEqual((json.loads(out)["deskew_deg"], json.loads(out)["deskew_max_deg"]), (0.0, 0))
            code, out, err = run_cli(["letterread", str(up), "--deskew", "50"] + base)
            self.assertEqual(code, 2)
            self.assertIn("--deskew 50", err)

    def test_cli_turned_read_draws_boxes_on_the_image_as_stored(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = Path(d) / "turned.npy"
            np.save(img, np.rot90(lined_image(), 1))                     # 400 x 150: lines run up and down
            png = Path(d) / "o.png"
            code, out, err = run_cli(["letterread", str(img), "--weights", str(w), "--letter-px", "16", "--nulls", "1",
                                      "--rotate", "90", "--json", "--no-orientation", "--overlay", str(png),
                                      "--crop", "0", "400", "0", "150"])
            self.assertEqual(code, 0, err)
            res = json.loads(out)
            self.assertEqual((res["input_shape"], res["view"]["shape"], res["crop"]), ([400, 150], [150, 400],
                                                                                       [0, 400, 0, 150]))
            boxes = [l["box"] for L in res["lines"] for l in L["letters"]]
            self.assertTrue(boxes)
            for y0, y1, x0, x1 in boxes:          # centred on the image as stored (a box may reach past its edge)
                self.assertTrue(0 < (y0 + y1) / 2 < 400 and 0 < (x0 + x1) / 2 < 150, (y0, y1, x0, x1))
            for _, _, x0, x1 in boxes:                       # each letter's height runs across the stored image
                self.assertAlmostEqual(x1 - x0, 16.0, places=6)
            with Image.open(png) as px:      # closed before the folder goes (Windows cannot delete an open file)
                size = [px.height, px.width]
            self.assertEqual(size, res["overlay"]["size"])
            self.assertEqual(size[0] - res["overlay"]["banner_rows"], 400)     # drawn the way round it was given

    def test_read_fills_sheared_rows_with_the_ground(self):
        net = self.net()
        photo = 1.0 - lined_image()
        dark = R.read(photo, net, letter_px=16, nulls=1, polarity="dark", orientation=False)
        a = R.normalize(photo, "dark")
        self.assertAlmostEqual(dark["shear_fill"], round(float(np.median(a)), 4), places=4)
        self.assertGreater(dark["shear_fill"], 0)
        bright = R.read(lined_image(), net, letter_px=16, nulls=1, orientation=False)
        self.assertEqual(bright["shear_fill"], 0.0)                       # ink maps: as before
        given = R.read(photo, net, letter_px=16, nulls=1, polarity="dark", orientation=False, shear_fill=0.0)
        self.assertEqual(given["shear_fill"], 0.0)
        tilted = R.shear(a, -4.0, float(np.median(a)))
        out = R.analyze(tilted, net, letter_px=16, nulls=1, normalized=True, shear_fill="median")
        self.assertEqual(out["deskew_deg"], 4.0)

    def test_exif_orientation_is_applied_when_loading(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        a = (np.arange(40 * 64) % 251).astype(np.uint8).reshape(40, 64)
        with tempfile.TemporaryDirectory() as d:
            for tag, shown in ((6, np.rot90(a, -1)), (8, np.rot90(a, 1)), (3, a[::-1, ::-1]), (2, a[:, ::-1])):
                p = save_png(Path(d) / f"t{tag}.png", a, tag)
                self.assertEqual(R.exif_orientation(p), tag)
                self.assertTrue(np.array_equal(R.load_image(p), shown.astype(np.float32)), tag)
                self.assertTrue(np.array_equal(R.load_image(p, crop=(2, 10, 3, 20)), shown[2:10, 3:20].astype(np.float32)))
                img, k, shape = R.load_reduced(p, letter_px=64, max_pixels=100)
                self.assertEqual((k, shape), (2, shown.shape))
                self.assertTrue(np.allclose(img, block_mean(shown, 2)))
            from PIL import Image
            ex = Image.Exif()
            ex[R.EXIF_ORIENTATION_TAG] = 6
            Image.fromarray(a).save(Path(d) / "t.jpg", exif=ex)
            self.assertEqual(R.load_image(Path(d) / "t.jpg").shape, (64, 40))
            plain = save_png(Path(d) / "plain.png", a)
            self.assertEqual(R.exif_orientation(plain), 1)
            self.assertTrue(np.array_equal(R.load_image(plain), a.astype(np.float32)))
            self.assertEqual(R.exif_orientation(Path(d) / "x.npy"), 1)
            # the colour image for the overlay: turned the same way, cropped and averaged like the read image
            rgb = np.zeros((40, 64, 3), np.uint8)
            rgb[..., 0] = 200
            rgb[:10, :, 1] = 250
            p = save_png(Path(d) / "c.png", rgb, 6)
            self.assertTrue(np.array_equal(R.display_image(p), np.rot90(rgb, -1)))
            self.assertEqual(R.display_image(p, crop=(0, 63, 0, 40), k=2).shape, (31, 20, 3))
            self.assertEqual(R.load_reduced(p, crop=(0, 63, 0, 40), letter_px=64, max_pixels=100)[0].shape, (31, 20))
            self.assertIsNone(R.display_image(plain))                                  # grey: drawn from the read image
            self.assertIsNone(R.display_image(Path(d) / "x.npy"))

    def test_overlay_draws_the_image_in_its_own_polarity(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        photo = 1.0 - lined_image()                                       # 150 x 400, dark ink on a light ground
        a = R.normalize(photo, "dark")                                    # what the reader reads: ink bright
        res = {"letter_px": 16.0, "input_scale": 1, "lines": [], "polarity": {"used": "dark"}}
        b = R.overlay_geometry(a.shape, res)["banner_rows"]

        def drawn(path, *args, **kw):
            return np.asarray(Image.open(R.overlay(*args, path, **kw)).convert("RGB")).astype(int)[b:b + 150, :400]

        with tempfile.TemporaryDirectory() as d:
            self.assertGreater(np.median(drawn(Path(d) / "o.png", a, res, normalized=True)), 200)   # light ground
            self.assertGreater(np.median(drawn(Path(d) / "p.png", photo, {k: v for k, v in res.items() if k != "polarity"},
                                               polarity="dark")), 200)
            self.assertLess(np.median(drawn(Path(d) / "q.png", a, dict(res, polarity={"used": "bright"}),
                                            normalized=True)), 60)                                   # an ink map
            base = np.zeros(photo.shape + (3,), np.uint8)
            base[..., 0] = 220
            px = drawn(Path(d) / "c.png", a, res, normalized=True, base=base)
            self.assertTrue((px[..., 0] > 200).all() and (px[..., 1] < 30).all())
            with self.assertRaisesRegex(ValueError, "base"):
                R.overlay(a, res, Path(d) / "x.png", normalized=True, base=np.zeros((5, 5)))

    def test_cli_reads_an_exif_turned_colour_photo(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        up = 1.0 - lined_image()                                          # 150 x 400, dark ink on a light ground
        rgb = np.stack([up * 230, up * 200, up * 150], axis=-1).round().astype(np.uint8)
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            stored = save_png(Path(d) / "stored.png", np.rot90(rgb, 1), 6)   # stored turned; EXIF 6 shows it upright
            upright = save_png(Path(d) / "upright.png", rgb)
            png = Path(d) / "o.png"
            base = ["--weights", str(w), "--letter-px", "16", "--nulls", "1", "--polarity", "auto", "--json",
                    "--no-orientation"]
            code, out, err = run_cli(["letterread", str(stored), "--overlay", str(png)] + base)
            self.assertEqual(code, 0, err)
            res = json.loads(out)
            self.assertIn("EXIF orientation 6", err)
            self.assertEqual((res["exif_orientation"], res["input_shape"], res["polarity"]["used"]), (6, [150, 400], "dark"))
            ref = json.loads(run_cli(["letterread", str(upright)] + base)[1])
            self.assertEqual(res["lines"], ref["lines"])
            self.assertNotIn("exif_orientation", ref)
            px = np.asarray(Image.open(png).convert("RGB")).astype(int)
            self.assertEqual(list(px.shape[:2]), res["overlay"]["size"])
            body = px[res["overlay"]["banner_rows"]:, :400]
            self.assertGreater(np.median(body[..., 0]) - np.median(body[..., 2]), 40)   # drawn in colour, light ground

    def test_summary_names_turns_warnings_and_the_best_turn(self):
        c = R.control_report(0, [0])
        c["verdict"] = R.verdict(0, [0])
        res = {"note": R.NOTE, "letter_px": 16.0, "letter_px_from": "given", "deskew_deg": 6.0, "p_min": 0.5,
               "lines": [], "control": c, "deskew_max_deg": 6.0,
               "columns": [{"x0": 0, "x1": 10, "deskew_deg": 6.0, "deskew_at_limit": True, "lines": 0}],
               "view": {"rotate": 90, "mirror": True}, "exif_orientation": 8,
               "orientation": {"letters_kept": {"as_is": 1, "rot90": 5}, "best": "rot90",
                               "best_view": {"rotate": 180, "mirror": True}}}
        res["deskew_warning"] = R.deskew_warning(res)
        text = R.text_summary(res)
        self.assertIn("warning: the deskew angle is the limit of its search (6 degrees", text)
        self.assertIn("read turned (--rotate 90 --mirror)", text)
        self.assertIn("EXIF orientation 8 applied", text)
        self.assertIn("give --rotate 180 --mirror", text)

    def test_eval_photos_script(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        sys.path.insert(0, str(ROOT / "scripts" / "letters"))
        try:
            import eval_photos
        finally:
            sys.path.remove(str(ROOT / "scripts" / "letters"))
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            with contextlib.redirect_stdout(io.StringIO()):
                res = eval_photos.evaluate(w, pages=1, nulls=1, blanks=2)
        page, summary = res["pages"][0], res["summary"]
        self.assertEqual((page["bright"]["used"], page["dark"]["used"], page["dark_fill0"]["used"]),
                         ("bright", "dark", "dark"))
        self.assertIn(page["auto"]["used"], ("bright", "dark"))
        self.assertEqual(set(page["auto"]["trial"]), {"bright", "dark"})
        self.assertIn(page["quarter_turn"]["best"], R.ORIENTATIONS)
        self.assertEqual(page["deskew_true"], -page["tilt_deg"])
        for mount in ("dark_mount", "white_mount"):
            self.assertIn(page[mount]["auto"], ("bright", "dark"))
        self.assertEqual(page["dark_mount"]["grey_level_guess"], "bright")     # the mount is most of the frame
        self.assertEqual((summary["blank_photo_pages"]["pages"], summary["blank_map_pages"]["pages"]), (2, 2))
        self.assertEqual(set(res["blank_map_pages"][0]), {"auto", "bright"})
        img = eval_photos.photo_page(np.random.default_rng(0), 20.0, 3, 3.0)[0]
        self.assertEqual(img.dtype, np.float32)
        self.assertTrue(np.array_equal(img, np.round(img)) and img.max() <= 255)   # 8-bit grey levels
        mounted = eval_photos.on_mount(img, frac=0.6)
        self.assertAlmostEqual(img.size / mounted.size, 0.4, delta=0.02)


@unittest.skipIf(np is None, "numpy not installed")
class WeightsTest(unittest.TestCase):
    def registry(self, d, src, sha, url=True):
        reg = Path(d) / "reg.json"
        reg.write_text(json.dumps({"models": {"tiny": {"file": "tiny.npz", "sha256": sha,
                                                        "url": src.resolve().as_uri() if url else None}}}))
        return reg

    def test_released_registry_is_well_formed(self):
        models = R.released_weights()
        self.assertTrue({"letters-v2-real", "letters-v2-ccby"} <= set(models))   # the old release stays listed
        guide = (ROOT / "docs" / "letter-reader.md").read_text(encoding="utf-8")
        for name, m in models.items():
            self.assertRegex(m["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(m["file"].endswith(".npz") and m["licence"])
            self.assertEqual(m["url"], f"https://github.com/ChaseHendrick/Scrolls/releases/download/{name}/{m['file']}")
            self.assertEqual((m["params"], m["letter_px"]), (1483241, 16))
            self.assertEqual(m["card"], f"docs/letter-reader.md#model-card-{name}")
            self.assertIn(f"\n## Model card: {name}\n", guide)             # the card's heading makes that anchor
        self.assertEqual(len({m["sha256"] for m in models.values()}), len(models))
        self.assertEqual(len({m["file"] for m in models.values()}), len(models))

    def test_letters_v2_ccby_is_the_default(self):
        from kit import letterdemo as D
        self.assertEqual(R.DEFAULT_WEIGHTS, "letters-v2-ccby")
        m = R.released_weights()[R.DEFAULT_WEIGHTS]
        self.assertEqual((m["file"], m["sha256"]), ("letters-v2-ccby-step026000.npz",
                                                    "b14988852fc721cce71e80a66db0a8ea99a1de914ef2b724ecc6e711baa9ed8c"))
        self.assertTrue(m["licence"].startswith("CC BY 4.0 ") and "NC" not in m["licence"])
        self.assertTrue(R.released_weights()["letters-v2-real"]["licence"].startswith("CC BY-NC 4.0"))
        self.assertEqual(R.released_name(m["sha256"]), "letters-v2-ccby")
        self.assertEqual(cli.build_parser().parse_args(["letterdemo"]).weights, R.DEFAULT_WEIGHTS)
        self.assertEqual(inspect.signature(D.run).parameters["weights"].default, R.DEFAULT_WEIGHTS)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.build_parser().parse_args(["letterread", "x.png"])        # the reader itself names no default

    def test_released_name_is_checked_offline(self):
        """letters-v2-ccby by name, with no network: a missing file is not fetched, a wrong one is refused."""
        m = R.released_weights()["letters-v2-ccby"]
        with tempfile.TemporaryDirectory() as d, mock.patch("urllib.request.urlopen",
                                                            side_effect=AssertionError("network")):
            with self.assertRaisesRegex(ValueError, "not in"):
                R.resolve_weights("letters-v2-ccby", cache=d, download=False)
            fake = random_weights(Path(d) / m["file"])          # the released file name, other bytes
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                R.resolve_weights("letters-v2-ccby", cache=d)    # in the cache, refused
            with self.assertRaisesRegex(ValueError, "letters-v2-ccby"):
                R.resolve_weights(str(fake))                     # by path, refused too
            reg = Path(d) / "reg.json"                           # the same entry, with this file's hash
            reg.write_text(json.dumps({"models": {"letters-v2-ccby": dict(m, sha256=R._sha256(fake))}}))
            self.assertEqual(R.resolve_weights("letters-v2-ccby", cache=d, registry=reg), fake)
            self.assertEqual(R.released_name(R._sha256(fake), registry=reg), "letters-v2-ccby")

    def test_path_passes_through(self):
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            self.assertEqual(R.resolve_weights(str(w)), w)

    def test_name_downloads_once_and_checks_sha256(self):
        with tempfile.TemporaryDirectory() as d:
            src = random_weights(Path(d) / "src.npz")
            reg = self.registry(d, src, R._sha256(src))
            cache = Path(d) / "cache"
            got = R.resolve_weights("tiny", cache=cache, registry=reg)
            self.assertEqual(got, cache / "tiny.npz")
            self.assertEqual(R.LineNet(got).letter_px, 16)
            src.unlink()                                   # the cached copy is used, no second download
            self.assertEqual(R.resolve_weights("tiny", cache=cache, registry=reg), got)
            got.write_bytes(b"swapped")                    # a changed cached file is refused
            with self.assertRaises(ValueError):
                R.resolve_weights("tiny", cache=cache, registry=reg)

    def test_bad_download_is_not_kept(self):
        with tempfile.TemporaryDirectory() as d:
            src = random_weights(Path(d) / "src.npz")
            reg = self.registry(d, src, "0" * 64)
            cache = Path(d) / "cache"
            with self.assertRaises(ValueError):
                R.resolve_weights("tiny", cache=cache, registry=reg)
            self.assertEqual(list(cache.iterdir()), [])

    def test_interrupted_download_leaves_nothing(self):
        from unittest import mock

        class Broken:
            def __init__(self, *a, **kw):
                self.calls, self.kw = 0, kw

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, n):
                self.calls += 1
                if self.calls > 1:
                    raise TimeoutError("stalled")
                return b"x" * 100

        with tempfile.TemporaryDirectory() as d:
            src = random_weights(Path(d) / "src.npz")
            reg = self.registry(d, src, R._sha256(src))
            cache = Path(d) / "cache"
            with mock.patch("urllib.request.urlopen", side_effect=Broken) as opened:
                with self.assertRaises(R.WeightsError) as cm:
                    R.resolve_weights("tiny", cache=cache, registry=reg)
            self.assertEqual(opened.call_args.kwargs["timeout"], R.DOWNLOAD_TIMEOUT)
            self.assertEqual(list(cache.iterdir()), [])
            # an OSError (the command line prints it) that names the model, the URL and the cache folder,
            # and says a file downloaded by hand can go into that folder
            self.assertIsInstance(cm.exception, OSError)
            self.assertIsInstance(cm.exception.__cause__, TimeoutError)
            msg = str(cm.exception)
            for part in ("tiny", src.resolve().as_uri(), str(cache), "by hand", "tiny.npz", "SHA-256"):
                self.assertIn(part, msg)

    def test_unknown_name_and_missing_url(self):
        with tempfile.TemporaryDirectory() as d:
            src = random_weights(Path(d) / "src.npz")
            reg = self.registry(d, src, R._sha256(src), url=False)
            with self.assertRaisesRegex(ValueError, "not a released model"):
                R.resolve_weights("nope", cache=Path(d), registry=reg)
            with self.assertRaisesRegex(ValueError, "no download address"):
                R.resolve_weights("tiny", cache=Path(d) / "c", registry=reg)


@unittest.skipIf(np is None, "numpy not installed")
class WeightsLookupTest(unittest.TestCase):
    """Names before paths, files named like a release, $KIT_LETTER_WEIGHTS, the cache file's mode."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.src = random_weights(self.d / "src.npz")
        self.reg = self.d / "reg.json"
        self.reg.write_text(json.dumps({"models": {"tiny": {"file": "tiny.npz", "sha256": R._sha256(self.src),
                                                            "url": self.src.resolve().as_uri()}}}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_names_come_before_paths(self):
        import os
        other = random_weights(self.d / "x.npz", seed=7).rename(self.d / "tiny")   # called like the model, other weights
        cache = self.d / "cache"
        here = os.getcwd()
        os.chdir(self.d)
        try:
            got = R.resolve_weights("tiny", cache=cache, registry=self.reg)
        finally:
            os.chdir(here)
        self.assertEqual(got, cache / "tiny.npz")
        self.assertEqual(R._sha256(got), R._sha256(self.src))
        self.assertNotEqual(R._sha256(other), R._sha256(self.src))
        self.assertEqual(R.resolve_weights(str(other), registry=self.reg), other)   # a path is still a path

    def test_a_file_named_like_a_release_is_hash_checked(self):
        good = self.d / "good" / "tiny.npz"
        good.parent.mkdir()
        good.write_bytes(self.src.read_bytes())
        self.assertEqual(R.resolve_weights(str(good), registry=self.reg), good)
        bad = random_weights(self.d / "tiny.npz", seed=3)
        with self.assertRaisesRegex(ValueError, "file name of the released model tiny"):
            R.resolve_weights(str(bad), registry=self.reg)
        self.assertEqual(R.resolve_weights(str(self.src), registry=self.reg), self.src)   # another name: no check

    def test_env_names_a_folder_or_a_file(self):
        from unittest import mock
        with mock.patch.dict("os.environ", {"KIT_LETTER_WEIGHTS": "~/letters-folder"}):
            self.assertEqual(R.weights_cache(), Path.home() / "letters-folder")
        mine = self.d / "keep" / "my-copy.npz"
        mine.parent.mkdir()
        mine.write_bytes(self.src.read_bytes())
        with mock.patch.dict("os.environ", {"KIT_LETTER_WEIGHTS": str(mine)}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("no download")):
            self.assertEqual(R.weights_cache(), mine.parent)
            self.assertEqual(R.resolve_weights("tiny", registry=self.reg), mine)   # used as it is, SHA-256 checked
        with mock.patch.dict("os.environ", {"KIT_LETTER_WEIGHTS": str(self.d / "not-yet.npz")}):
            self.assertEqual(R.weights_cache(), self.d)                            # a file to come: its folder

    @unittest.skipIf(sys.platform == "win32", "POSIX file modes")
    def test_downloaded_file_is_readable_by_all(self):
        got = R.resolve_weights("tiny", cache=self.d / "cache", registry=self.reg)
        self.assertEqual(got.stat().st_mode & 0o777, 0o644)

    def test_failed_download_says_where_a_hand_copy_goes(self):
        reg = self.d / "reg2.json"
        reg.write_text(json.dumps({"models": {"tiny": {"file": "tiny.npz", "sha256": R._sha256(self.src),
                                                       "url": (self.d / "gone.npz").resolve().as_uri()}}}))
        cache = self.d / "cache"
        with self.assertRaises(R.WeightsError) as cm:
            R.resolve_weights("tiny", cache=cache, registry=reg)
        msg = str(cm.exception)
        for part in ("tiny", "gone.npz", str(cache), "by hand", "copy it into", "SHA-256"):
            self.assertIn(part, msg)
        self.assertEqual(list(cache.iterdir()), [])
        # copied in by hand, the file is used (and checked)
        (cache / "tiny.npz").write_bytes(self.src.read_bytes())
        self.assertEqual(R.resolve_weights("tiny", cache=cache, registry=reg), cache / "tiny.npz")
        with self.assertRaisesRegex(ValueError, "no download address yet.*by hand"):
            reg.write_text(json.dumps({"models": {"tiny": {"file": "tiny.npz", "sha256": "0" * 64, "url": None}}}))
            R.resolve_weights("tiny", cache=self.d / "other", registry=reg)

    def test_linenet_records_where_its_weights_came_from(self):
        from unittest import mock
        with mock.patch.object(R, "WEIGHTS_REGISTRY", self.reg):
            net = R.LineNet(self.src)
            self.assertEqual(R.weights_info(net), {"name": "tiny", "file": "src.npz", "sha256": R._sha256(self.src),
                                                   "format": R.FORMAT})
            other = R.LineNet(random_weights(self.d / "o.npz", seed=2))
            self.assertIsNone(other.name)
        self.assertIsNone(R.released_name(R._sha256(self.src), registry=self.d / "missing.json"))

    def test_cli_resolves_the_weights_before_loading_the_image(self):
        from unittest import mock
        img = self.d / "img.npy"
        np.save(img, lined_image())
        with mock.patch.object(R, "load_reduced", side_effect=AssertionError("image loaded first")), \
                mock.patch.object(R, "WEIGHTS_REGISTRY", self.reg), \
                mock.patch.dict("os.environ", {"KIT_LETTER_WEIGHTS": str(self.d / "empty-cache")}), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("network is down")):
            code, out, err = run_cli(["letterread", str(img), "--weights", "tiny", "--letter-px", "16"])
        self.assertEqual(code, 2)
        self.assertNotIn("image loaded first", err)
        self.assertIn("could not download the weights tiny", err)
        self.assertIn(str(self.d / "empty-cache"), err)


@unittest.skipIf(np is None, "numpy not installed")
class ApiTest(unittest.TestCase):
    """read() as a Python API: what it takes, what it checks, and the provenance every result carries."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.w = random_weights(self.d / "w.npz")
        self.net = R.LineNet(self.w)
        self.img = lined_image()

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, img, weights=None, **kw):
        kw = dict(dict(letter_px=16, nulls=1, orientation=False), **kw)
        return R.read(img, self.net if weights is None else weights, **kw)

    @staticmethod
    def letters(res):
        return [(L["y"], [(l["glyph"], l["p"], l["box"]) for l in L["letters"]]) for L in res["lines"]]

    def test_weights_as_a_name_a_path_or_a_linenet(self):
        from unittest import mock
        reg = self.d / "reg.json"
        reg.write_text(json.dumps({"models": {"tiny": {"file": "tiny.npz", "sha256": R._sha256(self.w),
                                                       "url": self.w.resolve().as_uri()}}}))
        with mock.patch.object(R, "WEIGHTS_REGISTRY", reg), \
                mock.patch.dict("os.environ", {"KIT_LETTER_WEIGHTS": str(self.d / "cache")}):
            by = {"name": self.read(self.img, "tiny"), "path": self.read(self.img, str(self.w)),
                  "Path": self.read(self.img, self.w), "LineNet": self.read(self.img, R.LineNet(self.w))}
        first = self.letters(by["name"])
        for how, res in by.items():
            self.assertEqual(self.letters(res), first, how)
            self.assertEqual((res["weights"]["name"], res["weights"]["sha256"]), ("tiny", R._sha256(self.w)), how)
        self.assertEqual(by["name"]["weights"]["file"], "tiny.npz")
        self.assertEqual(by["path"]["weights"]["file"], "w.npz")
        with self.assertRaisesRegex(ValueError, "not a released model"):
            self.read(self.img, "no-such-model")
        with self.assertRaisesRegex(TypeError, "released model name"):
            self.read(self.img, 42)

    def test_image_is_squeezed_and_colour_made_grey(self):
        base = self.letters(self.read(self.img))
        for shape in ((1,) + self.img.shape, self.img.shape + (1,), (1, 1) + self.img.shape):
            self.assertEqual(self.letters(self.read(self.img.reshape(shape))), base, shape)
        rgb = np.stack([self.img * 0.5, self.img, self.img * 1.5], axis=-1)
        rgba = np.concatenate([rgb, np.full(self.img.shape + (1,), 7.0, np.float32)], axis=-1)
        grey = R.as_image(rgb)
        self.assertEqual(grey.dtype, np.float32)
        self.assertTrue(np.allclose(grey, self.img, atol=1e-6))      # the mean of the three channels, as load_image
        self.assertTrue(np.array_equal(R.as_image(rgba), grey))      # alpha left out
        self.assertEqual(self.letters(self.read(rgba)), self.letters(self.read(grey)))
        u8 = (np.clip(self.img, 0, 1) * 255).astype(np.uint8)
        self.assertIs(R.as_image(u8), u8)                             # a 2D array is not copied
        with tempfile.TemporaryDirectory() as d:                      # as load_image greys a colour .npy
            np.save(Path(d) / "c.npy", (rgb * 100).astype(np.uint16))
            self.assertTrue(np.array_equal(R.load_image(Path(d) / "c.npy"),
                                           R.as_image((rgb * 100).astype(np.uint16))))

    def test_bad_images_are_refused_clearly(self):
        cases = [(np.stack([self.img] * 3), ValueError, "channels"),          # channels first
                 (np.zeros((4, 5, 6)), ValueError, "2D image"),
                 (np.zeros(50), ValueError, "2D image"),
                 (np.zeros((0, 30)), ValueError, "empty"),
                 (np.array([["a", "b"], ["c", "d"]]), ValueError, "numbers"),
                 ("page.png", TypeError, "load_image")]
        for img, exc, words in cases:
            with self.assertRaisesRegex(exc, words):
                self.read(img)
        with self.assertRaisesRegex(ValueError, "control image: expected a 2D image"):
            self.read(self.img, control=np.zeros((2, 3, 4, 5)))

    def test_options_are_checked_before_any_work(self):
        from unittest import mock
        bad = [dict(letter_px=0), dict(letter_px=-3), dict(letter_px=float("nan")), dict(letter_px="16"),
               dict(polarity="Bright"), dict(polarity="light"), dict(columns="two"), dict(columns=0),
               dict(nulls=-1), dict(nulls=1.5), dict(min_letters=0), dict(deskew_deg=50), dict(rotate=45),
               dict(p_min=2), dict(lm_weight=-1), dict(beam=0), dict(lines=[]), dict(lines=["a"]),
               dict(input_scale=0), dict(seed=0.5)]
        with mock.patch.object(R, "normalize_info", side_effect=AssertionError("work began")), \
                mock.patch.object(R, "_analyze_at", side_effect=AssertionError("work began")):
            for kw in bad:
                name = next(iter(kw))
                with self.assertRaisesRegex(ValueError, f"^{name}") as cm:
                    self.read(self.img, **kw)
                self.assertNotIn("work began", str(cm.exception))
            with self.assertRaisesRegex(TypeError, "unknown option letterpx"):
                self.read(self.img, letterpx=16)
        for kw in (dict(polarity="dark"), dict(polarity="auto"), dict(columns="off"), dict(columns=2),
                   dict(columns="2"), dict(deskew_deg=0), dict(deskew_deg=None), dict(letter_px=np.float32(16))):
            self.read(self.img, **kw)                                  # good values pass
        with self.assertRaisesRegex(ValueError, "^letter_px"):
            R.analyze(self.img, self.net, letter_px=0, nulls=1)        # analyze() checks the same

    def test_language_model_weight_defaults_as_on_the_command_line(self):
        try:
            from kit import greeklm
        except ImportError:
            self.skipTest("kit.greeklm not importable")
        lm = greeklm.KNLetterLM(order=3).fit(["ΚΑΙΤΟΝΘΕΟΝ" * 50])
        args = cli.build_parser().parse_args(["letterread", "x.png", "--weights", "w.npz"])
        self.assertEqual(args.lm_weight, R.LM_WEIGHT)
        res = self.read(self.img, lm=lm)
        self.assertTrue(res["lines"] and all("with_lm" in L for L in res["lines"]))
        self.assertEqual(res["options"]["lm_weight"], R.LM_WEIGHT)
        self.assertEqual(res["options"]["lm"], {"file": None, "sha256": None, "order": 3})
        explicit = self.read(self.img, lm=lm, lm_weight=R.LM_WEIGHT)
        self.assertEqual([L["with_lm"] for L in res["lines"]], [L["with_lm"] for L in explicit["lines"]])
        off = self.read(self.img, lm=lm, lm_weight=0)
        self.assertTrue(all("with_lm" not in L for L in off["lines"]))
        self.assertEqual(self.read(self.img)["options"]["lm_weight"], None)
        a = R.analyze(self.img, self.net, letter_px=16, nulls=1, lm=lm)
        self.assertTrue(all("with_lm" in L for L in a["lines"]))
        with tempfile.TemporaryDirectory() as d:                     # a loaded model records its file name
            lm.save(Path(d) / "greek3.npz")
            loaded = greeklm.KNLetterLM.load(Path(d) / "greek3.npz")
            self.assertEqual(R.lm_info(loaded), {"file": "greek3.npz", "sha256": R._sha256(Path(d) / "greek3.npz"),
                                                 "order": 3})

    def test_every_result_carries_its_provenance(self):
        import kit
        ctrl = lined_image(seed=4)
        res = R.read(self.img, self.w, letter_px=16, nulls=1, seed=5, control=ctrl, rotate=180, mirror=True)
        ana = R.analyze(self.img, self.w, letter_px=16, nulls=1, seed=5)
        for r in (res, ana):
            self.assertEqual(r["schema"], R.SCHEMA)
            self.assertEqual(r["reader"], {"module": "kit.letterread", "version": kit.__version__})
            self.assertEqual(r["weights"], {"name": None, "file": "w.npz", "sha256": R._sha256(self.w),
                                            "format": R.FORMAT})
            self.assertEqual(r["seed"], 5)
            self.assertEqual(list(r)[:2], ["note", "schema"])
            self.assertEqual(list(r)[-1], "options")
            self.assertTrue(set(R.OPTION_NAMES) <= set(r["options"]))
            text = json.dumps(r, ensure_ascii=False)                   # plain JSON
            self.assertNotIn(str(self.d), text)
        o = res["options"]
        self.assertEqual((o["rotate"], o["mirror"], o["orientation"], o["control_map"], o["seed"], o["polarity"]),
                         (180, True, True, True, 5, "bright"))
        self.assertTrue(set(R.OPTION_NAMES) <= set(R.ANALYZE_OPTIONS))
        self.assertIn("weights w.npz, sha256 " + R._sha256(self.w)[:12], R.text_summary(res))
        auto = self.read(1.0 - self.img, polarity="auto")
        self.assertEqual((auto["options"]["polarity"], auto["polarity"]["asked"]), ("auto", "auto"))
        # an orientation read is a read like any other: rerunning with the recorded options gives the same letters
        again = R.read(self.img, self.w, **{k: v for k, v in o.items() if k in R.ANALYZE_OPTIONS and k != "lm"},
                       rotate=o["rotate"], mirror=o["mirror"], control=ctrl)
        self.assertEqual(self.letters(again), self.letters(res))

    def test_cli_result_has_file_names_only(self):
        img, ctrl, out, png = (self.d / n for n in ("img.npy", "ctrl.npy", "res.json", "o.png"))
        np.save(img, self.img)
        np.save(ctrl, lined_image(seed=2))
        extra = []
        try:
            import PIL  # noqa: F401
            extra = ["--overlay", str(png)]
        except ImportError:
            pass
        code, stdout, err = run_cli(["letterread", str(img), "--weights", str(self.w), "--letter-px", "16",
                                     "--nulls", "1", "--no-orientation", "--json", "--out", str(out),
                                     "--control", str(ctrl)] + extra)
        self.assertEqual(code, 0, err)
        res = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(res, json.loads(stdout))
        self.assertEqual(res["source"], {"file": "img.npy", "key": None})
        self.assertEqual(res["weights"]["file"], "w.npz")
        self.assertEqual(res["options"]["max_mpx"], 64)
        if extra:
            self.assertEqual(res["overlay"]["file"], "o.png")
        self.assertNotIn(str(self.d), out.read_text(encoding="utf-8"))

    def test_cli_writes_its_files_before_printing(self):
        from unittest import mock
        img, out, png = self.d / "img.npy", self.d / "res.json", self.d / "o.png"
        np.save(img, self.img)
        args = ["letterread", str(img), "--weights", str(self.w), "--letter-px", "16", "--nulls", "1",
                "--no-orientation", "--out", str(out)]
        try:
            import PIL  # noqa: F401
            args += ["--overlay", str(png)]
        except ImportError:
            png = None
        broken = UnicodeEncodeError("charmap", "Α", 0, 1, "character maps to <undefined>")
        with mock.patch.object(R, "text_summary", side_effect=broken), self.assertRaises(UnicodeEncodeError):
            run_cli(args)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["schema"], R.SCHEMA)
        if png is not None:
            self.assertTrue(png.exists())
        # a file that cannot be written after the read: the other file and the summary still come out
        with mock.patch.object(Path, "write_text", side_effect=PermissionError("read-only")):
            code, stdout, err = run_cli(args)
        self.assertEqual(code, 2)
        self.assertIn("read-only", err)
        self.assertIn("control:", stdout)

    def test_utf8_console(self):
        class Tty(io.TextIOWrapper):
            def isatty(self):
                return True

        pipe = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")   # "\n" stays "\n" on Windows too
        self.assertEqual(R.utf8_console(pipe), [pipe])
        self.assertEqual((pipe.encoding, pipe.errors), ("utf-8", "backslashreplace"))
        pipe.write("ΚΑΙ·Ϲ\n")
        pipe.flush()
        self.assertEqual(pipe.buffer.getvalue().decode("utf-8"), "ΚΑΙ·Ϲ\n")
        greek_tty = Tty(io.BytesIO(), encoding="utf-8")
        ascii_tty = Tty(io.BytesIO(), encoding="ascii")
        self.assertEqual(R.utf8_console(greek_tty, ascii_tty), [ascii_tty])   # a terminal that shows Greek is kept
        self.assertEqual((greek_tty.errors, ascii_tty.encoding), ("strict", "utf-8"))
        self.assertEqual(R.utf8_console(io.StringIO()), [])                   # nothing to reconfigure
        with mock.patch.object(R, "utf8_console") as called:
            run_cli(["letterread", str(self.d / "missing.npy"), "--weights", str(self.w)])
        self.assertEqual(called.call_count, 1)


@unittest.skipIf(np is None, "numpy not installed")
class ScriptsTest(unittest.TestCase):
    """The demo's cached map, and pdftotext read as UTF-8."""

    def load(self, name):
        sys.path.insert(0, str(ROOT / "scripts" / "letters"))
        try:
            return __import__(name)
        finally:
            sys.path.remove(str(ROOT / "scripts" / "letters"))

    def test_demo_uses_a_cached_map_without_listing_the_bucket(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        demo = self.load("demo_p1667")
        with tempfile.TemporaryDirectory() as d:
            Image.fromarray((lined_image() * 255).clip(0, 255).astype(np.uint8)).save(Path(d) / "w013-ds8.jpg")
            with mock.patch.object(demo, "keys", side_effect=AssertionError("listed")), \
                    mock.patch.object(demo, "download", side_effect=AssertionError("downloaded")):
                a, url = demo.small_map("w013", d)
                self.assertIsNone(url)                                   # no note beside it
                (Path(d) / "w013-ds8.json").write_text(json.dumps({"url": "https://example.org/m.jpg"}))
                self.assertEqual(demo.small_map("w013", d)[1], "https://example.org/m.jpg")
        self.assertEqual(a.shape, (lined_image().shape[0] // 2, lined_image().shape[1] // 2))

    def test_demo_reads_with_the_default_weights(self):
        demo = self.load("demo_p1667")

        class Stop(Exception):
            pass

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(demo.R, "load_weights", side_effect=Stop) as load, \
                mock.patch.object(sys, "argv", ["demo_p1667.py", "--out", d]):
            with self.assertRaises(Stop):                       # the weights come first, before any map
                demo.main()
        self.assertEqual(load.call_args.args, (R.DEFAULT_WEIGHTS,))

    def test_pdftotext_is_read_as_utf8(self):
        import types
        p1667_text = self.load("p1667_text")
        with mock.patch.object(p1667_text.subprocess, "run", return_value=types.SimpleNamespace(stdout="")) as run:
            p1667_text.bbox_layout("x.pdf")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        eval_p172 = self.load("eval_p172")
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / eval_p172.PDF_DIR / "t.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF")
            w = random_weights(Path(d) / "w.npz")
            with mock.patch.object(eval_p172.subprocess, "run", return_value=types.SimpleNamespace(stdout="")) as run:
                res = eval_p172.evaluate(d, w)
            self.assertEqual((res["weights"], res["weights_sha256"]), ("w.npz", R._sha256(w)))   # its name, no folder
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")


@unittest.skipIf(np is None, "numpy not installed")
class OverlayTest(unittest.TestCase):
    def test_overlay_png(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            img = lined_image()
            res = R.analyze(img, w, letter_px=16, nulls=1, p_min=0.0)
            out = R.overlay(img, res, Path(d) / "o.png")
            with Image.open(out) as im:
                self.assertEqual(im.size[0], img.shape[1])
                self.assertGreater(im.size[1], img.shape[0])        # the banner sits above the image
                px = np.asarray(im.convert("RGB"))[-img.shape[0]:].astype(int)
            coloured = (np.abs(px[..., 0] - px[..., 1]) > 30).sum()
            self.assertGreater(coloured, 0)                      # letter boxes were drawn
            npy = Path(d) / "img.npy"
            np.save(npy, img)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(["letterread", str(npy), "--weights", str(w), "--letter-px", "16", "--nulls", "1",
                                 "--no-orientation", "--overlay", str(Path(d) / "cli.png")])
            self.assertEqual(code, 0)
            self.assertTrue((Path(d) / "cli.png").exists())


    def test_banner_always_holds_the_whole_note(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Pillow not installed")
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for width in (40, 400, 1851, 4000):
            font, lines, lh, top, canvas_w = R.banner_layout(width)
            self.assertEqual(" ".join(lines), " ".join(R.NOTE.split()), width)
            self.assertGreaterEqual(canvas_w, width)
            self.assertTrue(all(d.textlength(line, font=font) <= canvas_w - 8 for line in lines), width)
            self.assertGreater(lh, 0)
        self.assertGreater(len(R.banner_layout(400)[1]), 1)        # wrapped, not cut off
        self.assertGreater(R.banner_layout(10)[4], 10)             # too narrow for any word at 6 px: the canvas widens

    def test_overlay_outlines_scale_and_reduced_images(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        box = [40.0, 60.0, 100.0, 140.0]
        res = {"letter_px": 16.0, "input_scale": 1, "lines": [{"letters": [
            {"glyph": "Α", "p": 0.9, "kept": True, "box": box},
            {"glyph": "Β", "p": 0.3, "kept": False, "box": [40.0, 60.0, 200.0, 240.0]}]}]}
        img = np.zeros((100, 300), np.float32)
        with tempfile.TemporaryDirectory() as d:
            geo = R.overlay_geometry(img.shape, res)
            px = np.asarray(Image.open(R.overlay(img, res, Path(d) / "o.png")).convert("RGB")).astype(int)
            self.assertEqual(list(px.shape[:2]), geo["size"])
            self.assertEqual(geo["scale"], 1.0)
            b = geo["banner_rows"]
            green = (px[..., 1] > 150) & (px[..., 0] < 100)
            self.assertGreaterEqual(int(green[b + 35:b + 46, 135].sum()), 2)      # top edge of the kept box
            grey = (np.abs(px[..., 0] - 120) < 10) & (np.abs(px[..., 1] - 120) < 10)
            self.assertGreaterEqual(int(grey[b + 35:b + 46, 220].sum()), 2)       # and of the grey one
            self.assertTrue((px[:b, :, 0] < 100).any())                           # banner text
            # a reduced read: the block-averaged image is drawn and boxes come in through input_scale
            reduced = dict(res, input_scale=2, reduced_shape=[50, 150])
            geo2 = R.overlay_geometry((50, 150), reduced, max_side=120)
            self.assertAlmostEqual(geo2["scale"], 0.8 / 2, places=6)
            px2 = np.asarray(Image.open(R.overlay(img[::2, ::2], reduced, Path(d) / "r.png", max_side=120)).convert("RGB"))
            self.assertEqual(list(px2.shape[:2]), geo2["size"])
            self.assertEqual(px2.shape[1], max(120, geo2["size"][1]))
            # the full-size image with the same result: boxes are not divided again
            self.assertEqual(R.overlay_geometry(img.shape, reduced, max_side=300)["scale"], 1.0)

    def test_cli_overlay_max_side_is_recorded(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as d:
            w = random_weights(Path(d) / "w.npz")
            npy = Path(d) / "img.npy"
            np.save(npy, lined_image())                                           # 150 x 400
            png = Path(d) / "o.png"
            code, out, err = run_cli(["letterread", str(npy), "--weights", str(w), "--letter-px", "16", "--nulls", "1",
                                      "--no-orientation", "--json", "--overlay", str(png), "--overlay-max-side", "200"])
            self.assertEqual(code, 0, err)
            geo = json.loads(out)["overlay"]
            self.assertEqual((geo["file"], geo["scale"], geo["max_side"]), (png.name, 0.5, 200))
            with Image.open(png) as im:
                self.assertEqual([im.size[1], im.size[0]], geo["size"])
                self.assertEqual(im.size[0], 200)

if __name__ == "__main__":
    unittest.main()
