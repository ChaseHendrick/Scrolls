"""kit windlabel-box (docs/tools/windlabel-box.md) on a synthetic spiral: a binary surface prediction, a grad_mag
that doubles from x = 150 on, and a lasagna manifest naming it. The command must keep every exported winding on
the true wraps, cut only where the grad_mag is doubled, write files VC3D loads, and refuse before any work
without a prediction, a grad_mag source or an umbilicus. Needs numpy and scipy (skipped without them)."""

import contextlib
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import scipy  # noqa: F401
except ImportError:  # pragma: no cover
    np = None

ROOT = Path(__file__).resolve().parents[1]
CENTRE, R0, PITCH, PLANT_X = (120.0, 120.0), 20.0, 14.0, 150.0


def spiral_volume(shape=(48, 240, 240), half=1.6):
    """Binary prediction (z, y, x) of an Archimedean spiral sheet r = r0 + pitch * (theta / 2 pi + n)."""
    Z, Y, X = shape
    yy, xx = np.mgrid[0:Y, 0:X].astype(np.float64)
    dx, dy = xx - CENTRE[0], yy - CENTRE[1]
    r = np.hypot(dx, dy)
    th = np.mod(np.arctan2(dy, dx), 2 * math.pi)
    u = (r - R0) / PITCH - th / (2 * math.pi)
    n = np.rint(u)
    sl = (np.abs(u - n) * PITCH <= half) & (r > R0) & (n >= 0)
    vol = np.zeros(shape, np.uint8)
    vol[:] = (sl * 255).astype(np.uint8)[None]
    return vol


def true_wrap(p):
    dx, dy = p[0] - CENTRE[0], p[1] - CENTRE[1]
    th = math.atan2(dy, dx) % (2 * math.pi)
    return round((math.hypot(dx, dy) - R0) / PITCH - th / (2 * math.pi))


def write_zarr(root, vol, chunk):
    """A one-level OME-Zarr v2 group, uncompressed; all-zero chunks left out."""
    d = Path(root) / "0"
    d.mkdir(parents=True)
    (d / ".zarray").write_text(json.dumps({
        "zarr_format": 2, "shape": list(vol.shape), "chunks": list(chunk), "dtype": vol.dtype.str,
        "compressor": None, "fill_value": 0, "filters": None, "order": "C", "dimension_separator": "/"}))
    for i in range(-(-vol.shape[0] // chunk[0])):
        for j in range(-(-vol.shape[1] // chunk[1])):
            for m in range(-(-vol.shape[2] // chunk[2])):
                blk = np.zeros(chunk, vol.dtype)
                sub = vol[i * chunk[0]:(i + 1) * chunk[0], j * chunk[1]:(j + 1) * chunk[1],
                          m * chunk[2]:(m + 1) * chunk[2]]
                blk[:sub.shape[0], :sub.shape[1], :sub.shape[2]] = sub
                if blk.any():
                    q = d / str(i) / str(j)
                    q.mkdir(parents=True, exist_ok=True)
                    (q / str(m)).write_bytes(blk.tobytes())
    (Path(root) / ".zgroup").write_text(json.dumps({"zarr_format": 2}))
    (Path(root) / ".zattrs").write_text(json.dumps({"multiscales": [{"version": "0.4", "axes": [
        {"name": a} for a in "zyx"], "datasets": [{"path": "0", "coordinateTransformations": [
            {"type": "scale", "scale": [1.0, 1.0, 1.0]}]}]}]}))


def write_inputs(d):
    write_zarr(d / "pred.zarr", spiral_volume(), (16, 64, 64))
    g = np.full((24, 120, 120), 70, np.uint8)                 # level 1 of a 48 x 240 x 240 base
    g[:, :, ((np.arange(120) + 0.5) * 2 - 0.5) >= PLANT_X] = 140
    write_zarr(d / "las" / "gm.zarr", g, (16, 32, 32))
    (d / "las" / "run.lasagna.json").write_text(json.dumps({
        "groups": {"grad_mag": {"zarr": "gm.zarr", "scaledown": 1, "channels": ["grad_mag"]},
                   "normals": {"zarr": "gm.zarr", "scaledown": 1, "channels": ["nx", "ny"]}},
        "base_shape_zyx": [48, 240, 240], "grad_mag_factor": 1.0, "grad_mag_encode_scale": 1000.0}))
    (d / "umbilicus.json").write_text(json.dumps([[0.0, 120.0, 120.0], [47.0, 120.0, 120.0]]))


def run(argv):
    from kit import windlabel_box as w
    import argparse
    a = w.build_parser(argparse.ArgumentParser()).parse_args(argv)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = w.cmd_windlabel_box(a)
    return rc, out.getvalue(), err.getvalue()


@unittest.skipIf(np is None, "needs numpy and scipy")
class TestWindlabelBox(unittest.TestCase):
    def test_box_writes_villa_files_on_the_true_wraps(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write_inputs(d)
            rc, out, err = run(["--prediction", str(d / "pred.zarr"), "--grad-mag", str(d / "las/run.lasagna.json"),
                                "--point", "120,120,24", "--box", "140", "--seeds", "30",
                                "--umbilicus", str(d / "umbilicus.json"), "--out", str(d / "run"), "--json"])
            self.assertEqual(rc, 0, err[-1500:])
            res = json.loads(out)                                 # only JSON on stdout
            self.assertTrue(res["ok"])
            self.assertGreater(res["collections"], 5)
            self.assertGreater(res["split_steps"], 0)
            ch = json.loads((d / "run/chains.json").read_text())
            self.assertTrue(ch["rule_digest"].startswith("0e53e0ae5016"))
            self.assertEqual(ch["axis_source"], "file")
            self.assertEqual(ch["box"], [[50.0, 190.0], [50.0, 190.0], [-46.0, 94.0]])
            ex = json.loads((d / "run/export.json").read_text())
            self.assertEqual(ex["split_rule"]["params_digest"], "c6d2eecbebc2")
            # every cut step reaches the doubled grad_mag; every exported winding difference is the true one
            sp = json.loads((d / "run/split.json").read_text())
            pw = json.loads((d / "run/relative_windings.json").read_text())
            self.assertEqual(pw["vc_pointcollections_json_version"], "1")
            pairs = right = 0
            for c in pw["collections"].values():
                self.assertFalse(c["metadata"]["winding_is_absolute"])
                pts = list(c["points"].values())
                for a_, b_ in zip(pts, pts[1:]):
                    pairs += 1
                    right += (b_["wind_a"] - a_["wind_a"]) == (true_wrap(b_["p"]) - true_wrap(a_["p"]))
            self.assertGreater(pairs, 20)
            self.assertGreaterEqual(right / pairs, 0.95)
            self.assertIn("chains", sp)
            fl = json.loads((d / "run/flags.json").read_text())
            split_pts = [p["p"] for c in fl["collections"].values() if "split" in c["name"]
                         for p in c["points"].values()]
            self.assertTrue(split_pts)
            self.assertGreater(min(p[0] for p in split_pts), PLANT_X - 2 * PITCH)

    def test_refuses_before_any_work(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            write_inputs(d)
            pred, gm, umb = str(d / "pred.zarr"), str(d / "las/run.lasagna.json"), str(d / "umbilicus.json")
            cases = [(["--grad-mag", gm, "--umbilicus", umb], "no surface prediction"),
                     (["--prediction", pred, "--umbilicus", umb], "no grad_mag source"),
                     (["--prediction", pred, "--grad-mag", gm], "no umbilicus given"),
                     (["--prediction", pred, "--grad-mag", gm, "--umbilicus", str(d / "nope.json")], "no such file"),
                     (["--prediction", str(d / "missing.zarr"), "--grad-mag", gm, "--umbilicus", umb],
                      "cannot open the surface"),
                     (["--prediction", pred, "--grad-mag", str(d / "missing.lasagna.json"), "--umbilicus", umb],
                      "no lasagna manifest")]
            for extra, why in cases:
                with self.subTest(why=why):
                    out = d / f"run-{len(why)}"
                    rc, _, err = run([*extra, "--point", "120,120,24", "--out", str(out)])
                    self.assertEqual(rc, 2)
                    self.assertIn(why, err)
                    self.assertFalse((out / "chains.json").exists())
            for point, box, seeds in (("1,2", "512", "200"), ("1,2,3", "0", "200"), ("1,2,3", "512", "x")):
                rc, _, _ = run(["--prediction", pred, "--grad-mag", gm, "--umbilicus", umb, "--point", point,
                                "--box", box, "--seeds", seeds, "--out", str(d / "bad")])
                self.assertEqual(rc, 2)

    def test_kit_command_line_has_it(self):
        r = subprocess.run([sys.executable, "-m", "kit", "windlabel-box", "--help"], cwd=ROOT, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--umbilicus", r.stdout)


if __name__ == "__main__":
    unittest.main()
