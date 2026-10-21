"""kit/umbfind.py: the scroll center finder (scripts/umbilicus/predict.py) on the scan VC3D has open, writing only
into its run folder. A stand-in predict.py (KIT_CENTRENET_PREDICT) writes a synthetic line, so nothing reads the
bucket, downloads weights or needs torch."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import umbfind

SCAN = "20250821000000-9.362um-1.2m-113keV-masked.zarr"
KEY = f"PHerc0332/volumes/{SCAN}"
URL = f"https://vesuvius-challenge-open-data.s3.amazonaws.com/{KEY}/"

# predict.py's command line, as the adapter calls it; FAKE_PREDICT picks ok, empty (no point kept), bad (a point VC3D
# cannot read) or fail (exit 1)
FAKE_PREDICT = r'''
import argparse, json, os, sys
from pathlib import Path
ap = argparse.ArgumentParser()
ap.add_argument("scrolls", nargs="+")
ap.add_argument("--first", nargs="+", required=True)
ap.add_argument("--zoom", nargs="*", default=[])
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--volume")
ap.add_argument("--device", default="cpu")
ap.add_argument("--no-end-rule", action="store_true")
a = ap.parse_args()
s = a.scrolls[0]
mode = os.environ.get("FAKE_PREDICT", "ok")
if mode == "fail":
    print("ModuleNotFoundError: No module named 'torch'", file=sys.stderr)
    sys.exit(1)
os.makedirs(a.data, exist_ok=True)
os.makedirs(a.out, exist_ok=True)
Path(a.data, s + ".npz").write_bytes(b"slices")
name = a.volume.rstrip("/").split("/")[-1]
um = float(name.split("-")[1].replace("um", ""))
n = 0 if mode == "empty" else 12
pts = [{"x": 1000 + i, "y": 900 - i, "z": 64 * (i + 1), "score": 100} for i in range(n)]
if mode == "bad":
    pts[3]["x"] = "not a number"
meta = {"source_volume": a.volume, "volume": name, "voxelsize_um": um, "total_points": n, "volume_width": 4000,
        "volume_height": 3600, "volume_slices": 1024, "method": "stand-in", "spread_mm_median": None}
Path(a.out, s + "_umbilicus.json").write_text(json.dumps({"control_points": pts, "metadata": meta}))
Path(a.out, s + "_predict.json").write_text(json.dumps({"scroll": s, "device": a.device, "first": a.first,
                                                        "zoom": a.zoom, "end_rule": not a.no_end_rule}))
print(s, json.dumps({"points": n}))
'''


def write_fake_predict(folder):
    p = Path(folder) / "predict.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(FAKE_PREDICT)
    return p


def write_weights(folder, first=b"first weights", zoom=b"zoom weights"):
    """Two stand-in weight files under the released names; returns pins for umbfind.WEIGHTS."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pins = {}
    for stage, data in (("first", first), ("zoom", zoom)):
        name = umbfind.WEIGHTS[stage][0]
        (folder / name).write_bytes(data)
        pins[stage] = (name, hashlib.sha256(data).hexdigest())
    return pins


def files_under(folder):
    return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob("*") if p.is_file())


class BucketKeyTest(unittest.TestCase):
    def test_urls_keys_and_local_copies_name_one_scan(self):
        for v in (URL, f"s3://vesuvius-challenge-open-data/{KEY}", KEY, f"/data/mirror/{KEY}"):
            self.assertEqual(umbfind.bucket_key(v), ("PHerc0332", KEY, 9.362), v)

    def test_other_locations_and_scans_are_refused(self):
        cases = {"https://example.org/PHerc0332/volumes/" + SCAN: "open-data bucket",
                 "/data/some/folder.zarr": "by key",
                 "ftp://vesuvius-challenge-open-data/" + KEY: "not a bucket URL",
                 "https://vesuvius-challenge-open-data.s3.amazonaws.com/PHerc0332/paths/x.zarr": "not a scan",
                 "PHerc0332/volumes/20231117143551-7.910um-0.2m-77keV-masked.zarr": "8 to 10 um",
                 "PHerc0332/volumes/scan.zarr": "no voxel size"}
        for v, why in cases.items():
            with self.assertRaises(umbfind.UmbfindError) as cm:
                umbfind.bucket_key(v)
            self.assertIn(why, str(cm.exception), v)


class WeightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="umbfind-w-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {umbfind.ENV_WEIGHTS: str(self.tmp / "none")}

    def test_released_files_are_found_by_their_sha256_and_others_skipped(self):
        pins = write_weights(self.tmp / "w")
        with mock.patch.dict(umbfind.WEIGHTS, pins):
            got = umbfind.find_weights(self.tmp / "run", folder=self.tmp / "w", env=self.env)
            self.assertTrue(all(v["pinned"] for v in got.values()))
            self.assertEqual(got["first"]["sha256"], pins["first"][1])
            write_weights(self.tmp / "w", first=b"edited")
            with self.assertRaisesRegex(umbfind.UmbfindError, "skipped .*the release pins"):
                umbfind.find_weights(self.tmp / "run", folder=self.tmp / "w", env=self.env)
        self.assertFalse((self.tmp / "run").exists())

    def test_download_only_when_allowed_and_checked(self):
        data = {"umbilicus-first-all.pt": b"F", "umbilicus-zoom-all.pt": b"Z"}
        pins = {"first": ("umbilicus-first-all.pt", hashlib.sha256(b"F").hexdigest()),
                "zoom": ("umbilicus-zoom-all.pt", hashlib.sha256(b"Z").hexdigest())}

        def opener(url, timeout=None):
            return io.BytesIO(data[url.rsplit("/", 1)[-1]])
        with mock.patch.dict(umbfind.WEIGHTS, pins):
            with self.assertRaisesRegex(umbfind.UmbfindError, "allow --download"):
                umbfind.find_weights(self.tmp / "run", env=self.env, opener=opener)
            got = umbfind.find_weights(self.tmp / "run", download=True, env=self.env, opener=opener)
            self.assertTrue(got["zoom"]["downloaded"])
            self.assertEqual(Path(got["zoom"]["path"]).parent, self.tmp / "run" / "weights")
            data["umbilicus-first-all.pt"] = b"a proxy page"
            shutil.rmtree(self.tmp / "run")
            with self.assertRaisesRegex(umbfind.UmbfindError, "downloaded sha256"):
                umbfind.find_weights(self.tmp / "run", download=True, env=self.env, opener=opener)
            self.assertEqual(files_under(self.tmp / "run"), [])          # nothing half-written is kept

    def test_explicit_files_are_recorded_not_pinned(self):
        write_weights(self.tmp / "fold")
        got = umbfind.find_weights(self.tmp / "run", self.tmp / "fold" / "umbilicus-first-all.pt",
                                   self.tmp / "fold" / "umbilicus-zoom-all.pt", env=self.env)
        self.assertFalse(got["first"]["pinned"])
        with self.assertRaisesRegex(umbfind.UmbfindError, "both --first and --zoom"):
            umbfind.find_weights(self.tmp / "run", first=self.tmp / "fold" / "umbilicus-first-all.pt", env=self.env)


class FindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="umbfind-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.script = write_fake_predict(self.tmp / "bin")
        write_weights(self.tmp / "fold")
        self.w = (str(self.tmp / "fold" / "umbilicus-first-all.pt"), str(self.tmp / "fold" / "umbilicus-zoom-all.pt"))
        self.env = dict(os.environ, KIT_CENTRENET_PREDICT=str(self.script))

    def go(self, mode="ok", **kw):
        env = dict(self.env, FAKE_PREDICT=mode)
        return umbfind.find(URL, self.tmp / "run", *self.w, env=env, **kw)

    def test_the_line_lands_in_the_run_folder_and_nowhere_else(self):
        before = files_under(self.tmp)
        summary, code = self.go()
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["points"], 12)
        self.assertEqual(summary["key"], KEY)
        self.assertEqual(summary["argv"][summary["argv"].index("--device") + 1], "cpu")
        self.assertIn("Model output", summary["claim"])
        line = json.loads((self.tmp / "run" / "umbilicus.json").read_text())
        self.assertEqual(len(line["control_points"]), 12)
        self.assertEqual(json.loads((self.tmp / "run" / "predict.json").read_text())["device"], "cpu")
        new = [f for f in files_under(self.tmp) if f not in before]
        self.assertTrue(all(f.startswith("run/") for f in new), new)

    def test_no_point_and_a_failed_finder_write_no_line(self):
        summary, code = self.go("empty")
        self.assertEqual(code, 1)
        self.assertIn("no point", summary["error"])
        self.assertFalse((self.tmp / "run" / "umbilicus.json").exists())
        shutil.rmtree(self.tmp / "run")
        summary, code = self.go("fail")
        self.assertEqual(code, 1)
        self.assertIn("torch", summary["error"])
        self.assertFalse((self.tmp / "run" / "umbilicus.json").exists())

    def test_the_command_line_refuses_with_exit_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = umbfind.main(["/data/folder.zarr", "--out", str(self.tmp / "run")])
        self.assertEqual(code, 2)
        self.assertIn("by key", err.getvalue())
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"KIT_CENTRENET_PREDICT": str(self.script), "FAKE_PREDICT": "ok"}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = umbfind.main([URL, "--out", str(self.tmp / "run2"), "--first", self.w[0], "--zoom", self.w[1],
                                 "--no-end-rule"])
        self.assertEqual(code, 0)
        self.assertIn("--no-end-rule", json.loads(out.getvalue())["argv"])


if __name__ == "__main__":
    unittest.main()
