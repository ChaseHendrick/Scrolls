"""slicechains.py: the synthetic self-test (both senses vote their own way, closed rings abstain) and its CLI."""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "spiralsense" / "slicechains.py"
HAVE = all(importlib.util.find_spec(m) for m in ("numpy", "scipy", "skimage", "numcodecs"))


@unittest.skipUnless(HAVE, "needs numpy, scipy, scikit-image and numcodecs")
class SliceChains(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location("slicechains", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def votes(self, mod, sense, rings=False, mirror=False):
        img, cx, cy, pitch = mod.synthetic(sense, rings)
        img = img.astype("uint8")
        if mirror:
            img, cx = img[:, ::-1], img.shape[1] - 1 - cx
        vs = [q["vote"] for q in mod.plane_chains(img, cx, cy, pitch, r_px=img.shape[0])]
        return vs.count("CW"), vs.count("ACW")

    def test_each_sense_votes_its_own_way(self):
        mod = self.load()
        cw, acw = self.votes(mod, "CW")
        self.assertGreater(cw, 0)
        self.assertEqual(acw, 0)
        cw, acw = self.votes(mod, "ACW")
        self.assertGreater(acw, 0)
        self.assertEqual(cw, 0)

    def test_mirror_flips_the_vote(self):
        mod = self.load()
        cw, acw = self.votes(mod, "CW", mirror=True)
        self.assertGreater(acw, 0)
        self.assertEqual(cw, 0)

    def test_closed_rings_do_not_vote(self):
        mod = self.load()
        self.assertEqual(self.votes(mod, "CW", rings=True), (0, 0))

    def test_selftest_cli_passes_and_prints_json(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1])["selftest"], "PASS")


if __name__ == "__main__":
    unittest.main()
