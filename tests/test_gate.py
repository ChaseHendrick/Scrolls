import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit import cli, gate

CROPS = {"0841-w00": [0, 640, 0, 640], "0841-ag896": [10, 650, 0, 640], "0841-ag405": [20, 660, 0, 640]}


def bar(reader, seg, fwd, rev):
    return {"segment": seg, "window": "crop", "inner_px": 64, "reader": reader, "auc_as_stored": fwd, "auc_reversed": rev}


def mac_auc(seg, fwd, rev, crop=None, inner=64):
    return {"forward": {"auc": fwd, "inner": inner}, "control": {"auc": rev}, "crop": crop or CROPS[seg]}


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        rows = [bar("d9v2", s, f, 0.55) for s, f in zip(gate.SEGMENTS, (0.90, 0.82, 0.83))]
        rows += [bar("ink_9um seed42", s, f, 0.55) for s, f in zip(gate.SEGMENTS, (0.81, 0.66, 0.78))]
        rows.append(dict(bar("ink_9um seed42", "0841-w00", 0.70, 0.5), inner_px=0))  # other edge: ignored
        self.results = root / "results.json"
        self.results.write_text(json.dumps({"segments": {s: {"crop": c} for s, c in CROPS.items()}, "results": rows}))
        self.work = root / "work"
        for seg in gate.SEGMENTS:
            (self.work / seg / "results").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, seg, name, data):
        (self.work / seg / "results" / f"auc_{name}.json").write_text(json.dumps(data))

    def test_committed_bars_only(self):
        r = gate.run(None, self.results)
        self.assertEqual([x["reader"] for x in r["ranked"]], ["d9v2", "ink_9um seed42"])
        self.assertTrue(r["verdict"]["clear"])
        self.assertEqual(r["verdict"]["winner"], "d9v2")

    def test_mac_reader_within_lead_is_not_a_win(self):
        for seg, f in zip(gate.SEGMENTS, (0.91, 0.83, 0.83)):
            self.put(seg, "v8in", mac_auc(seg, f, 0.5))
        r = gate.run(self.work, self.results)
        self.assertEqual(r["verdict"]["winner"], "v8in")
        self.assertFalse(r["verdict"]["clear"])
        self.assertIn("not a win", r["verdict"]["text"])

    def test_incomplete_and_wrong_crop_are_not_ranked(self):
        self.put("0841-w00", "v8in1447", mac_auc("0841-w00", 0.99, 0.5))
        self.put("0841-ag896", "v8in1447", mac_auc("0841-ag896", 0.99, 0.5, crop=[0, 1, 0, 1]))
        r = gate.run(self.work, self.results)
        self.assertIn("v8in-1447", r["incomplete"])
        self.assertTrue(any("standard crop" in s for s in r["skipped"]))

    def test_weak_control_is_flagged(self):
        for seg in gate.SEGMENTS:
            self.put(seg, "v8in", mac_auc(seg, 0.95, 0.90))
        r = gate.run(self.work, self.results)
        top = r["ranked"][0]
        self.assertEqual(top["reader"], "v8in")
        self.assertFalse(top["control_ok"])
        self.assertEqual(r["verdict"]["winner"], "d9v2")

    def test_mac_ink9um_must_match_the_cpu_bar(self):
        self.put("0841-w00", "ink9um_s42", mac_auc("0841-w00", 0.8130, 0.55))
        self.put("0841-ag896", "ink9um_s42", mac_auc("0841-ag896", 0.66, 0.55))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["gate", str(self.work), "--results", str(self.results)])
        self.assertEqual(code, 1)
        self.assertIn("MISMATCH", out.getvalue())
        self.assertIn("0841-ag896: Mac ink_9um s42 0.6600 vs CPU 0.6600: match", out.getvalue())


if __name__ == "__main__":
    unittest.main()
