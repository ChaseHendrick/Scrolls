import contextlib
import io
import json
import math
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from kit import auc, cli, ensemble, vc3d_io, verify

try:
    import numpy as np
    import tifffile
except ImportError:  # the core kit is standard library only
    np = tifffile = None
try:
    import zarr
except ImportError:
    zarr = None
try:  # only to cross-check the PNG reader against libpng's encoder
    import imagecodecs
except ImportError:
    imagecodecs = None


@unittest.skipIf(tifffile is None, "numpy and tifffile are needed for kit ensemble")
class EnsembleTest(unittest.TestCase):
    def test_mean_scales_each_dtype_and_keeps_no_prediction_pixels_out(self):
        a = np.array([[255, 0], [51, 102]], np.uint8)
        b = np.array([[65535, 65535], [0, 13107]], np.uint16)
        out, valid = ensemble.combine([a, b])
        self.assertEqual(valid.tolist(), [[True, False], [False, True]])
        self.assertAlmostEqual(out[0, 0], 1.0)
        self.assertAlmostEqual(out[1, 1], (0.4 + 0.2) / 2)
        self.assertEqual(out[0, 1], 0.0)

    def test_weights(self):
        a = np.full((2, 2), 255, np.uint8)
        b = np.full((2, 2), 51, np.uint8)
        out, _ = ensemble.combine([a, b], weights=[3, 1])
        self.assertAlmostEqual(out[0, 0], (3 * 1.0 + 0.2) / 4)

    def test_rank_ignores_each_map_s_scale(self):
        rng = np.random.default_rng(0)
        x = rng.integers(1, 256, (16, 16)).astype(np.uint8)
        squeezed = (30000 + x.astype(np.uint16))  # same order, a narrow band of the uint16 range
        out, _ = ensemble.combine([x, squeezed], method="rank")
        alone, _ = ensemble.combine([x, x], method="rank")
        np.testing.assert_allclose(out, alone)

    def test_rank_ties_share_a_rank(self):
        a = np.array([[5, 5, 9]], np.uint8)
        out, _ = ensemble.combine([a, a], method="rank")
        self.assertEqual(out[0, 0], out[0, 1])
        self.assertEqual(out[0, 2], 1.0)

    def test_refuses_bad_input(self):
        a = np.ones((2, 2), np.uint8)
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a])
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a, np.ones((2, 3), np.uint8)])
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a, a], weights=[1])
        with self.assertRaises(verify.VerifyError):
            ensemble.combine([a, a], method="median")

    def test_files_round_trip_keeps_valid_pixels_above_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = np.array([[1, 0], [200, 255]], np.uint8)
            b = np.array([[1, 7], [100, 255]], np.uint8)
            tifffile.imwrite(root / "a.tif", a)
            tifffile.imwrite(root / "b.tif", b)
            for name in ("e.tif", "e.npy"):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main(["ensemble", str(root / name), str(root / "a.tif"), str(root / "b.tif")])
                self.assertEqual(code, 0)
                self.assertIn("3 valid px", out.getvalue())
                got = np.load(root / name) if name.endswith(".npy") else tifffile.imread(root / name)
                self.assertEqual(got[0, 1], 0)
                self.assertTrue((got[np.array([[1, 0], [1, 1]], bool)] > 0).all())
                self.assertGreater(got[1, 1], got[1, 0])

    def test_mean_output_is_unchanged(self):
        """The uint16 values the mean wrote before zscore, decode and validity options existed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tifffile.imwrite(root / "a.tif", np.array([[1, 0], [200, 255]], np.uint8))
            tifffile.imwrite(root / "b.tif", np.array([[1, 7], [100, 255]], np.uint8))
            ensemble.ensemble_files(root / "e.tif", [root / "a.tif", root / "b.tif"])
            self.assertEqual(tifffile.imread(root / "e.tif").tolist(), [[258, 0], [38550, 65535]])
            ensemble.ensemble_files(root / "r.tif", [root / "a.tif", root / "b.tif"], "rank")
            self.assertEqual(tifffile.imread(root / "r.tif").tolist(), [[1, 0], [32768, 65535]])

    def test_nan_and_inf_are_never_valid(self):
        """kit writes NaN where a map has no value (--raw-out); one NaN must not spoil a model's statistics."""
        rng = np.random.default_rng(21)
        a = rng.integers(1, 256, (12, 14)).astype(np.uint8)
        f = (rng.random((12, 14)) * 200 + 2).astype(np.float32)   # above 1: mean and rank divide it by 255
        g = f.copy()
        g[2, 3], g[5, 6] = np.nan, np.inf
        holes = np.ones(f.shape, bool)
        holes[2, 3] = holes[5, 6] = False
        f0 = np.where(holes, f, 0).astype(np.float32)   # the same pixels marked "no prediction" the usual way
        for method in ("mean", "rank", "zscore"):
            for keep_zero in (False, True):
                out, valid = ensemble.combine([a, g], method, keep_zero=keep_zero)
                self.assertEqual(valid.tolist(), holes.tolist(), (method, keep_zero))
                self.assertTrue(np.isfinite(out).all(), method)
            # elsewhere nothing changes: the same as a map with 0 at those two pixels
            ref, _ = ensemble.combine([a, f0], method)
            np.testing.assert_array_equal(ensemble.combine([a, g], method)[0], ref, err_msg=method)
        stats = ensemble.zscore_stats([("a", a), ("g", g)])
        self.assertTrue(math.isfinite(stats["models"]["g"]["mean"]) and math.isfinite(stats["models"]["g"]["sd"]))
        self.assertEqual(stats["models"]["g"]["n_px"], f.size - 2)

    def test_unreadable_and_unwritable_files_are_clear_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Path(tmp)
            tifffile.imwrite(r / "a.tif", np.arange(1, 21, dtype=np.uint8).reshape(4, 5))
            tifffile.imwrite(r / "b.tif", np.arange(21, 41, dtype=np.uint8).reshape(4, 5))
            (r / "empty.npy").write_bytes(b"")
            a, b = str(r / "a.tif"), str(r / "b.tif")
            cases = [
                (["ensemble", str(r / "o.tif"), a, str(r / "missing.npy")], "cannot read"),
                (["ensemble", str(r / "o.tif"), a, str(r / "empty.npy"), "--method", "rank"], "cannot read"),
                (["ensemble", str(r / "o.tif"), f"x={a}", f"y={r / 'missing.npy'}", "--method", "zscore"], "cannot read"),
                (["ensemble", str(r / "no" / "o.tif"), a, b], "cannot write"),
                (["ensemble", str(r), a, b], "cannot write"),
                (["ensemble", str(r / "no" / "o.npy"), a, b, "--method", "zscore"], "cannot write"),
                (["ensemble", str(r / "o.tif"), a, b, "--raw-out", str(r / "no" / "r.npy")], "cannot write"),
                (["ensemble", "--method", "zscore", "--pool", f"x={a}", "--stats-out", str(r / "no" / "s.json")],
                 "cannot write"),
            ]
            for argv, needle in cases:
                code, _, err = run_cli(argv)
                self.assertEqual(code, 2, argv)
                self.assertIn(needle, err, argv)
            code, out, _ = run_cli(["ensemble", str(r / "o.tif"), a, b])   # the same call with good paths works
            self.assertEqual(code, 0)
            with self.assertRaises(verify.VerifyError):   # the API refuses weights for zscore, as the CLI does
                ensemble.ensemble_files(r / "w.tif", [a, b], "zscore", [5.0, 1.0])


# ---------------------------------------------------------------- helpers for the zscore tests

def png_blob(a, filters=(0, 1, 2, 3, 4), channels=1):
    """Grey (or grey-valued RGB) PNG of a uint8 or uint16 array, rows filtered in turn by `filters`."""
    depth = 16 if a.dtype == np.uint16 else 8
    h, w = a.shape
    px = np.repeat(a[..., None], channels, axis=2) if channels > 1 else a[..., None]
    raw = px.astype(">u2").tobytes() if depth == 16 else px.astype(np.uint8).tobytes()
    bpp = channels * depth // 8
    stride = w * bpp
    out, prev = b"", [0] * stride
    for r in range(h):
        line = list(raw[r * stride:(r + 1) * stride])
        f = filters[r % len(filters)]
        enc = []
        for i, x in enumerate(line):
            left = line[i - bpp] if i >= bpp else 0
            up, ul = prev[i], prev[i - bpp] if i >= bpp else 0
            p = left + up - ul
            pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
            pred = {0: 0, 1: left, 2: up, 3: (left + up) // 2,
                    4: left if pa <= pb and pa <= pc else up if pb <= pc else ul}[f]
            enc.append((x - pred) % 256)
        out += bytes([f] + enc)
        prev = line

    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, depth, 0 if channels == 1 else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(out)) + chunk(b"IEND", b"")


def exact_auc(scores, ink):
    """Mann-Whitney AUC with ties counted half, from average ranks (no quantization)."""
    uniq, inv, counts = np.unique(scores, return_inverse=True, return_counts=True)
    start = np.concatenate(([0], np.cumsum(counts)[:-1]))
    ranks = (start + (counts + 1) / 2.0)[inv]
    n1, n0 = int(ink.sum()), int((~ink).sum())
    return (ranks[ink].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def his_read(a, kind):
    """Nieuwlaar's read_map on an array: villa uint8 TIFF -> (v - 64) / 128 clipped; Hecate PNG -> v / 255."""
    if kind == "hecate":
        return a.astype(np.float32) / 255.
    return np.clip((a.astype(np.float32) - 64.) / 128., 0, 1)


def his_reference(ct, reading, blind, kinds, order, write_k):
    """His ensemble_maps.py arithmetic, written out again from its formulas, on in-memory arrays."""
    valid = (ct > 0).all(0)
    sub = np.zeros_like(valid)
    sub[8 // 2::8, 8 // 2::8] = True
    sub &= valid
    stats, subs = {}, {}
    for sn in order:
        s1 = s2 = 0.0
        n = 0
        sv, vals = [], []
        for a in reading[sn]:
            M = his_read(a, kinds[sn])
            v = M[valid]
            s1 += float(v.sum(dtype=np.float64))
            s2 += float(np.square(v, dtype=np.float64).sum())
            n += v.size
            sv.append(M[sub].astype(np.float32))
            vals.append(v)
        mu = s1 / n
        sd = math.sqrt(max(s2 / n - mu * mu, 0.0)) + 1e-6
        v = np.concatenate(vals)
        q = np.rint(v * 128) / 128.0 if kinds[sn] != "hecate" else np.minimum((v * 65536).astype(np.int64), 65535) / 65536
        stats[sn] = dict(mean=mu, sd=sd, n_px=n, p1=float(np.percentile(q, 1.0)), p99_5=float(np.percentile(q, 99.5)))
        subs[sn] = np.stack(sv)
    E = None
    for sn in order:
        z = (subs[sn] - stats[sn]["mean"]) / stats[sn]["sd"]
        E = z if E is None else E + z
    E /= len(order)
    ens = dict(zip(("p1", "p99_5"), (float(x) for x in np.percentile(E.ravel(), [1.0, 99.5]))), n_grid=int(E.size))
    images = {}
    for side, maps in (("reading", reading), ("blind", blind)):
        acc = None
        for sn in order:
            zc = (his_read(maps[sn][write_k], kinds[sn]) - stats[sn]["mean"]) / stats[sn]["sd"]
            acc = zc if acc is None else acc + zc
        images[side] = acc / len(order)
    return valid, stats, ens, images


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


@unittest.skipIf(tifffile is None, "numpy and tifffile are needed for kit ensemble")
class DecodeAndPngTest(unittest.TestCase):
    def test_ls_decode_clips_at_the_label_smoothing_floor(self):
        u8 = np.array([0, 1, 64, 65, 128, 192, 255], np.uint8)
        np.testing.assert_array_equal(ensemble.decode_values(u8, "ls"), [0, 0, 0, 1 / 128, 0.5, 1, 1])
        np.testing.assert_allclose(ensemble.decode_values(u8, "none"), u8 / 255.0, rtol=1e-6)
        u16 = np.array([0, 16384, 32768, 49151, 65535], np.uint16)
        np.testing.assert_allclose(ensemble.decode_values(u16, "ls"), np.clip((u16 / 65535 - 0.25) / 0.5, 0, 1), atol=1e-6)
        f = np.array([0.1, 0.25, 0.5, 0.75, 0.9], np.float64)
        got = ensemble.decode_values(f, "ls")
        self.assertEqual(got.dtype, np.float32)
        np.testing.assert_allclose(got, [0, 0, 0.5, 1, 1], atol=1e-7)
        with self.assertRaises(verify.VerifyError):
            ensemble.decode_values(u8, "sigmoid")

    def test_validity_comes_from_raw_values_before_decoding(self):
        a = np.array([[0, 30, 64, 200]], np.uint8)     # 30 and 64 decode to 0 with ls but are predictions
        b = np.array([[90, 90, 0, 100]], np.uint8)
        for method in ("mean", "rank", "zscore"):
            out, valid = ensemble.combine([a, b], method, decode="ls")
            self.assertEqual(valid.tolist(), [[False, True, False, True]], method)
            out, valid = ensemble.combine([a, b], method, decode="ls", keep_zero=True)
            self.assertTrue(valid.all(), method)
        mean, _ = ensemble.combine([a, b], decode="ls")
        self.assertAlmostEqual(mean[0, 1], (0 + 26 / 128) / 2, places=6)
        mask = np.array([[True, True, True, False]])
        _, valid = ensemble.combine([a, b], decode="ls", valid=mask)
        self.assertEqual(valid.tolist(), [[False, True, False, False]])

    def test_png_8_and_16_bit_grey_every_filter(self):
        rng = np.random.default_rng(3)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dtype, top in ((np.uint8, 255), (np.uint16, 65535)):
                a = rng.integers(0, top + 1, (11, 13)).astype(dtype)
                for filters in ((0,), (1,), (2,), (0, 1, 2), (3,), (4,), (0, 1, 2, 3, 4)):
                    path = root / f"m{top}.png"
                    path.write_bytes(png_blob(a, filters))
                    got = verify.load_map(path)
                    self.assertEqual(got.dtype, dtype)
                    np.testing.assert_array_equal(got, a, err_msg=f"{dtype} filters {filters}")
                rgb = root / "rgb.png"
                rgb.write_bytes(png_blob(a, channels=3))
                np.testing.assert_array_equal(verify.load_map(rgb), a)
            grey = rng.integers(0, 256, (9, 7)).astype(np.uint8)
            blob = png_blob(grey, (4, 3, 1))
            self.assertEqual(vc3d_io.read_png_gray(blob)[3], grey.tobytes())   # the standard-library reader agrees
            colour = np.stack([grey, grey, 255 - grey], -1)
            path = root / "colour.png"
            path.write_bytes(vc3d_io.png_bytes(9, 7, colour.tobytes(), channels=3))
            with self.assertRaises(verify.VerifyError):
                verify.load_map(path)
            for cut in (40, 20, 25):   # 20 and 25 end inside the 13-byte IHDR
                (root / "bad.png").write_bytes(png_blob(grey)[:cut])
                with self.assertRaises(verify.VerifyError, msg=f"cut at {cut}"):
                    verify.load_map(root / "bad.png")
            (root / "empty.png").write_bytes(png_blob(np.zeros((3, 0), np.uint8)))
            with self.assertRaises(verify.VerifyError):
                verify.load_map(root / "empty.png")

    @unittest.skipIf(imagecodecs is None, "imagecodecs (libpng) not installed")
    def test_png_reader_matches_libpng(self):
        rng = np.random.default_rng(4)
        with tempfile.TemporaryDirectory() as tmp:
            for dtype, top in ((np.uint8, 255), (np.uint16, 65535)):
                a = (np.cumsum(rng.integers(0, 9, (64, 80)), 1) * (top // 600)).astype(dtype)
                path = Path(tmp) / "lib.png"
                path.write_bytes(imagecodecs.png_encode(a))
                np.testing.assert_array_equal(verify.load_map(path), a)

    def test_png_maps_go_through_verify_auc_and_ensemble(self):
        rng = np.random.default_rng(5)
        a = rng.integers(1, 256, (20, 24)).astype(np.uint8)
        b = (255 - a).astype(np.uint8)
        b[b == 0] = 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.png").write_bytes(png_blob(a))
            (root / "a2.png").write_bytes(png_blob(a, (4,)))
            (root / "b.png").write_bytes(png_blob(b))
            self.assertEqual(verify.verify_files(root / "a.png", root / "a2.png", root / "b.png")["verdict"], verify.PASS)
            np.testing.assert_array_equal(auc._load(root / "a.png"), a)
            code, out, _ = run_cli(["ensemble", str(root / "e.tif"), str(root / "a.png"), str(root / "b.png")])
            self.assertEqual(code, 0)
            self.assertIn(f"{a.size} valid px", out)
            (root / "small.png").write_bytes(png_blob(a[:10]))
            code, _, err = run_cli(["ensemble", str(root / "e.tif"), str(root / "a.png"), str(root / "small.png")])
            self.assertEqual(code, 2)
            self.assertIn("differ in shape", err)


@unittest.skipIf(zarr is None, "numpy, tifffile and zarr are needed for kit ensemble --method zscore")
class ZscoreTest(unittest.TestCase):
    ORDER = ("dnative", "hecate", "ink9-42")
    KINDS = {"dnative": "villa", "hecate": "hecate", "ink9-42": "villa"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        rng = np.random.default_rng(7)
        self.shape = (41, 50)
        ct = rng.integers(1, 256, (6,) + self.shape).astype(np.uint8)
        ct[:, :6, :] = 0              # off the papyrus in every layer
        ct[3, 20:25, 30:40] = 0        # one empty layer is enough to drop a pixel
        self.ct = ct
        g = zarr.open_group(str(self.root / "surface.zarr"), mode="w")
        g.create_array("0", data=ct, chunks=(6, 16, 16))
        self.reading, self.blind = {}, {}
        for sn in self.ORDER:
            for side, store in (("reading", self.reading), ("blind", self.blind)):
                store[sn] = []
                for k in range(3):
                    base = rng.normal(0.4 if sn == "hecate" else 120, 0.15 if sn == "hecate" else 40, self.shape)
                    if sn == "hecate":
                        a = np.clip(np.round(base * 255), 0, 255).astype(np.uint8)
                    else:
                        a = np.clip(np.round(base), 0, 255).astype(np.uint8)
                    a[rng.random(self.shape) < 0.01] = 0   # raw zeros inside the surface: his rule keeps them
                    store[sn].append(a)
                    path = self.path(sn, side, k)
                    if sn == "hecate":
                        path.write_bytes(png_blob(a))
                    else:
                        tifffile.imwrite(path, a)

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, sn, side, k):
        return self.root / f"{side}__{sn}__d{10 + k}.{'png' if sn == 'hecate' else 'tif'}"

    def his_flags(self):
        return ["--decode", "ls", "--decode", "hecate=none", "--valid-from", str(self.root / "surface.zarr"), "--keep-zero"]

    def test_matches_his_arithmetic_reading_and_blind_side(self):
        r = self.root
        pool = []
        for sn in self.ORDER:
            ext = "png" if sn == "hecate" else "tif"
            pool += ["--pool", f"{sn}={r}/reading__{sn}__d*.{ext}"]   # a glob, as the shell would pass it quoted
        code, out, err = run_cli(["ensemble", "--method", "zscore", *pool, *self.his_flags(),
                                  "--stats-out", str(r / "stats.json")])
        self.assertEqual(code, 0, err)
        self.assertIn("statistics of 3 models", out)
        valid, his_stats, his_ens, images = his_reference(self.ct, self.reading, self.blind, self.KINDS, self.ORDER, 1)
        stats = json.loads((r / "stats.json").read_text())
        self.assertEqual(stats["model_order"], list(self.ORDER))
        for sn in self.ORDER:
            m = stats["models"][sn]
            self.assertEqual(m["decode"], "none" if sn == "hecate" else "ls")
            self.assertEqual(len(m["maps"]), 3)
            self.assertEqual(m["n_px"], his_stats[sn]["n_px"])
            self.assertEqual(m["mean"], his_stats[sn]["mean"])
            self.assertEqual(m["sd"], his_stats[sn]["sd"])
            self.assertAlmostEqual(m["p1"], his_stats[sn]["p1"], places=12)
            self.assertAlmostEqual(m["p99_5"], his_stats[sn]["p99_5"], places=12)
        self.assertEqual(stats["ensemble"]["n_grid"], his_ens["n_grid"])
        self.assertEqual(stats["ensemble"]["p1"], his_ens["p1"])
        self.assertEqual(stats["ensemble"]["p99_5"], his_ens["p99_5"])
        self.assertEqual(stats["ensemble"]["grid"], {"start": 4, "step": 8})
        for side in ("reading", "blind"):
            maps = [f"{sn}={self.path(sn, side, 1)}" for sn in self.ORDER]
            code, out, err = run_cli(["ensemble", str(r / f"{side}.tif"), *maps, "--method", "zscore",
                                      "--stats", str(r / "stats.json"), "--raw-out", str(r / f"{side}.npy"),
                                      *self.his_flags(), "--json"])
            self.assertEqual(code, 0, err)
            res = json.loads(out)
            raw = np.load(r / f"{side}.npy")
            self.assertEqual(raw.dtype, np.float32)
            np.testing.assert_array_equal(raw[valid], images[side][valid])   # bit for bit
            self.assertTrue(np.isnan(raw[~valid]).all())
            self.assertEqual(res["valid_px"], int(valid.sum()))
            self.assertEqual(res["statistics_from"], str(r / "stats.json"))
            self.assertEqual(res["stretch"]["p1"], his_ens["p1"])   # the reading side's stretch, on both sides
            tif = tifffile.imread(r / f"{side}.tif")
            self.assertEqual(tif.dtype, np.uint16)
            self.assertTrue((tif[~valid] == 0).all())
            self.assertEqual((int(tif[valid].min()), int(tif[valid].max())), (1, 65535))
            lo, hi = res["mean_z_min"], res["mean_z_max"]
            expect = 1 + np.round((raw[valid].astype(np.float64) - lo) / (hi - lo) * 65534)
            np.testing.assert_array_equal(tif[valid], expect)
            p1 = res["stretch_out_units"]["p1"]
            self.assertAlmostEqual(p1, 1 + (his_ens["p1"] - lo) / (hi - lo) * 65534)

    def test_stats_pooled_over_one_set_applied_to_another(self):
        r = self.root
        a = {sn: [self.path(sn, "reading", k) for k in range(3)] for sn in ("dnative", "ink9-42")}
        pool = [x for sn in a for p in a[sn] for x in ("--pool", f"{sn}={p}")]
        code, _, err = run_cli(["ensemble", "--method", "zscore", *pool, "--decode", "ls", "--stats-out", str(r / "s.json")])
        self.assertEqual(code, 0, err)
        stats = ensemble.load_stats(r / "s.json")
        b = {sn: self.blind[sn][2] for sn in a}
        code, _, err = run_cli(["ensemble", str(r / "b.npy"), *[f"{sn}={self.path(sn, 'blind', 2)}" for sn in a],
                                "--method", "zscore", "--stats", str(r / "s.json"), "--raw-out", str(r / "braw.npy")])
        self.assertEqual(code, 0, err)
        raw = np.load(r / "braw.npy")
        ok = (b["dnative"] != 0) & (b["ink9-42"] != 0)
        want = None
        for sn in a:   # set B with set A's statistics
            z = (his_read(b[sn], "villa") - stats["models"][sn]["mean"]) / stats["models"][sn]["sd"]
            want = z if want is None else want + z
        want = want / 2
        np.testing.assert_array_equal(raw[ok], want[ok])
        for sn in a:   # they are set A's own statistics, not set B's
            ok_a = np.concatenate([self.reading[sn][k].ravel() != 0 for k in range(3)])
            vals = np.concatenate([his_read(self.reading[sn][k], "villa").ravel() for k in range(3)])[ok_a]
            self.assertAlmostEqual(stats["models"][sn]["mean"], float(vals.astype(np.float64).mean()), places=10)
            self.assertAlmostEqual(stats["models"][sn]["sd"], float(vals.astype(np.float64).std()) + 1e-6, places=8)
        own = ensemble.zscore_stats([(sn, b[sn]) for sn in a], "ls")   # set B's own statistics differ
        self.assertNotEqual(own["models"]["dnative"]["mean"], stats["models"]["dnative"]["mean"])
        npy = np.load(r / "b.npy")
        self.assertTrue((npy[ok] > 0).all() and (npy[~ok] == 0).all())
        # misuse is refused
        for extra, needle in ((["--decode", "none"], "computed with decode"),
                              (["--pool", f"dnative={a['dnative'][0]}"], "does not go with"),):
            code, _, err = run_cli(["ensemble", str(r / "x.tif"), *[f"{sn}={self.path(sn, 'blind', 2)}" for sn in a],
                                    "--method", "zscore", "--stats", str(r / "s.json"), *extra])
            self.assertEqual(code, 2)
            self.assertIn(needle, err)
        code, _, err = run_cli(["ensemble", str(r / "x.tif"), f"dnative={self.path('dnative', 'blind', 2)}",
                                f"hecate={self.path('hecate', 'blind', 2)}", "--method", "zscore", "--stats", str(r / "s.json")])
        self.assertEqual(code, 2)
        self.assertIn("give one map for each", err)

    def test_invariant_to_an_affine_rescale_of_one_model(self):
        rng = np.random.default_rng(11)
        pool_a = [rng.random(self.shape).astype(np.float32) + 0.01 for _ in range(2)]
        pool_b = [rng.random(self.shape).astype(np.float32) ** 2 + 0.01 for _ in range(2)]
        apply_a, apply_b = rng.random(self.shape).astype(np.float32) + 0.01, rng.random(self.shape).astype(np.float32) + 0.01

        def mean_z(scale, shift):
            pool = [("a", m * scale + shift) for m in pool_a] + [("b", m) for m in pool_b]
            stats = ensemble.zscore_stats(pool)
            return ensemble.apply_zscore([("a", apply_a * scale + shift), ("b", apply_b)], stats)

        z0, ok0 = mean_z(1.0, 0.0)
        z1, ok1 = mean_z(np.float32(37.5), np.float32(4.25))
        np.testing.assert_array_equal(ok0, ok1)
        np.testing.assert_allclose(z1, z0, rtol=1e-4, atol=1e-4)
        self.assertGreater(float(np.abs(z0).max()), 1.0)
        # so the scored output ranks the pixels the same way
        s0, s1 = ensemble.affine01(z0, ok0)[0], ensemble.affine01(z1, ok1)[0]
        self.assertGreater(np.corrcoef(s0.ravel(), s1.ravel())[0, 1], 0.99999)

    def test_monotone_output_keeps_auc(self):
        rng = np.random.default_rng(13)
        h, w = self.shape
        ink = np.zeros(self.shape, bool)
        ink[10:20] = True
        mask = np.ones(self.shape, bool)
        mask[:, :3] = False
        r = self.root
        paths = {}
        for name, levels in (("m1", 12), ("m2", 9)):   # few distinct values: no two scores share a uint16 level
            a = (rng.integers(1, levels + 1, self.shape) * 17 + np.where(ink, 20, 0)).astype(np.uint8)
            paths[name] = r / f"{name}.tif"
            tifffile.imwrite(paths[name], a)
        code, out, err = run_cli(["ensemble", str(r / "z.tif"), *[f"{n}={p}" for n, p in paths.items()],
                                  "--method", "zscore", "--raw-out", str(r / "z.npy")])
        self.assertEqual(code, 0, err)
        self.assertIn("statistics from maps", out)
        tif, raw = tifffile.imread(r / "z.tif"), np.load(r / "z.npy")
        valid = tif > 0
        got = auc.score_array(tif, ink, mask)["auc"]
        self.assertEqual(got, round(exact_auc(raw[mask & valid], ink[mask & valid]), 4))
        # continuous scores: the order is kept (ties allowed by rounding), and the AUC within rounding
        a = rng.random(self.shape).astype(np.float32) + np.where(ink, 0.3, 0.0) + 0.01
        b = rng.random(self.shape).astype(np.float32) + 0.01
        tifffile.imwrite(r / "a.tif", a)
        tifffile.imwrite(r / "b.tif", b)
        code, _, err = run_cli(["ensemble", str(r / "c.tif"), f"a={r / 'a.tif'}", f"b={r / 'b.tif'}", "--method", "zscore",
                                "--raw-out", str(r / "c.npy")])
        self.assertEqual(code, 0, err)
        tif, raw = tifffile.imread(r / "c.tif"), np.load(r / "c.npy")
        order = np.argsort(raw.ravel(), kind="stable")
        self.assertTrue((np.diff(tif.ravel()[order].astype(np.int64)) >= 0).all())
        self.assertAlmostEqual(auc.score_array(tif, ink, mask)["auc"], exact_auc(raw[mask], ink[mask]), places=3)

    def test_valid_from_surface_volume_and_mask(self):
        r = self.root
        want = (self.ct > 0).all(0)
        np.testing.assert_array_equal(ensemble.valid_from(r / "surface.zarr"), want)
        np.testing.assert_array_equal(ensemble.valid_from(r / "surface.zarr", self.shape, rows=5), want)
        tifffile.imwrite(r / "mask.tif", want.astype(np.uint8) * 255)
        np.testing.assert_array_equal(ensemble.valid_from(r / "mask.tif"), want)
        with self.assertRaises(verify.VerifyError):
            ensemble.valid_from(r / "surface.zarr", (10, 10))
        a, b = self.path("dnative", "reading", 0), self.path("ink9-42", "reading", 0)
        code, out, err = run_cli(["ensemble", str(r / "m.tif"), str(a), str(b), "--valid-from", str(r / "surface.zarr")])
        self.assertEqual(code, 0, err)
        both = want & (self.reading["dnative"][0] != 0) & (self.reading["ink9-42"][0] != 0)
        self.assertIn(f"{int(both.sum())} valid px", out)
        np.testing.assert_array_equal(tifffile.imread(r / "m.tif") > 0, both)
        code, out, err = run_cli(["ensemble", str(r / "m.tif"), str(a), str(b), "--valid-from", str(r / "surface.zarr"),
                                  "--keep-zero"])
        self.assertEqual(code, 0, err)
        self.assertIn(f"{int(want.sum())} valid px", out)

    def test_stretch_histogram_of_mixed_maps(self):
        """A model with a uint8 map decoded with ls and a float map: his 65,536-bin rule over both."""
        u8 = self.reading["dnative"][0]
        f = np.random.default_rng(17).random(self.shape).astype(np.float32)
        stats = ensemble.zscore_stats([("a", u8), ("a", f)], "ls")
        m = stats["models"]["a"]
        self.assertEqual(m["stretch_bins"], "65536 bins")
        v = np.concatenate([his_read(u8, "villa")[u8 != 0], np.clip((f - 0.25) / 0.5, 0, 1).ravel()])
        q = np.minimum((v * 65536).astype(np.int64), 65535) / 65536
        self.assertAlmostEqual(m["p1"], float(np.percentile(q, 1.0)), places=12)
        self.assertAlmostEqual(m["p99_5"], float(np.percentile(q, 99.5)), places=12)
        self.assertEqual(m["n_px"], int((u8 != 0).sum()) + f.size)

    def test_stretch_needs_paired_depths(self):
        pool = [("a", self.reading["dnative"][0]), ("a", self.reading["dnative"][1]), ("b", self.reading["ink9-42"][0])]
        stats = ensemble.zscore_stats(pool, "ls")
        self.assertNotIn("p1", stats["ensemble"])
        self.assertIn("cannot be paired", stats["ensemble"]["note"])
        self.assertEqual(stats["models"]["a"]["stretch_bins"], "129 levels")
        self.assertEqual(stats["models"]["a"]["maps"], ["<array 0>", "<array 1>"])

    def test_cli_refusals(self):
        r = self.root
        a, b = self.path("dnative", "reading", 0), self.path("ink9-42", "reading", 0)
        cases = [
            (["ensemble", str(r / "o.tif"), f"x={a}", f"y={b}", "--method", "zscore", "--weights", "1", "2"], "unweighted"),
            (["ensemble", str(r / "o.tif"), str(a), str(b), "--pool", f"x={a}"], "belong to --method zscore"),
            (["ensemble", str(r / "o.tif"), str(a), str(b), "--decode", "x=ls"], "needs --method zscore"),
            (["ensemble", "--method", "zscore", f"x={a}", f"y={b}"], "output map comes first"),
            (["ensemble", "--method", "zscore", "--pool", f"x={a}"], "--stats-out"),
            (["ensemble", str(r / "o.tif"), f"x={a}", f"x={b}", "--method", "zscore"], "one map per model"),
            (["ensemble", str(r / "o.tif"), f"x={a}", f"y={b}", "--method", "zscore", "--pool", f"x={a}"], "no pooled maps"),
            (["ensemble", "--method", "zscore", "--pool", f"x={r}/nothing*.tif", "--stats-out", str(r / "s.json")], "no file"),
            (["ensemble", str(r / "o.tif"), f"x={a}", f"y={b}", "--method", "zscore", "--decode", "z=ls"], "not given"),
            (["ensemble", str(r / "o.tif"), f"x={a}", f"y={b}", "--method", "zscore", "--decode", "x=ls",
              "--decode", "x=none"], "two decodes"),
            (["ensemble", str(r / "o.tif"), f"x={a}", f"y={b}", "--method", "zscore", "--raw-out", str(r / "raw.tif")], ".npy"),
            (["ensemble", str(r / "o.tif"), str(a)], "at least two"),
        ]
        for argv, needle in cases:
            code, _, err = run_cli(argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(needle, err, argv)
        (r / "bad.json").write_text("{}")
        code, _, err = run_cli(["ensemble", str(r / "o.tif"), f"x={a}", f"y={b}", "--method", "zscore", "--stats", str(r / "bad.json")])
        self.assertEqual((code, "not a kit ensemble statistics file" in err), (2, True))

    def test_malformed_statistics_are_refused(self):
        r = self.root
        a, b = self.path("dnative", "reading", 0), self.path("ink9-42", "reading", 0)
        good = ensemble.zscore_stats([("x", a), ("y", b)], "ls")
        (r / "good.json").write_text(json.dumps(good))
        self.assertEqual(ensemble.load_stats(r / "good.json")["models"]["x"]["mean"], good["models"]["x"]["mean"])
        for change in ({"mean": None}, {"mean": "0.3"}, {"sd": 0}, {"sd": -1.0}, {"sd": float("nan")},
                       {"decode": "sigmoid"}, "not a model"):
            bad = json.loads(json.dumps(good))
            if isinstance(change, dict):
                bad["models"]["x"].update(change)
            else:
                bad["models"]["x"] = change
            (r / "bad.json").write_text(json.dumps(bad))
            with self.assertRaises(verify.VerifyError, msg=str(change)):
                ensemble.load_stats(r / "bad.json")
            code, _, err = run_cli(["ensemble", str(r / "o.tif"), f"x={a}", f"y={b}", "--method", "zscore",
                                    "--stats", str(r / "bad.json")])
            self.assertEqual(code, 2, change)
            self.assertIn("model x needs", err)

    def test_plain_paths_zscore_on_their_own_statistics(self):
        r = self.root
        a, b = self.path("dnative", "reading", 0), self.path("ink9-42", "reading", 0)
        code, out, err = run_cli(["ensemble", str(r / "o.npy"), str(a), str(b), "--method", "zscore", "--decode", "ls",
                                  "--stats-out", str(r / "self.json"), "--json"])
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertEqual(res["model_order"], ["map1", "map2"])
        self.assertEqual(sorted(json.loads((r / "self.json").read_text())["models"]), ["map1", "map2"])
        got = np.load(r / "o.npy")
        self.assertEqual(got.dtype, np.float32)
        api, valid = ensemble.combine([self.reading["dnative"][0], self.reading["ink9-42"][0]], "zscore", decode="ls")
        np.testing.assert_allclose(got[valid], (1 + api[valid] * 65534) / 65535, rtol=1e-6)
        self.assertTrue((got[~valid] == 0).all())


if __name__ == "__main__":
    unittest.main()
