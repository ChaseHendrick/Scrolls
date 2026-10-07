import unittest
from fractions import Fraction as F

from kit.titlecheck import Iv, check

# Synthetic numbers only, not sourced letter sizes.
PRIORS = {
    "letter_width_mm": [2, 3],
    "letter_spacing_mm": [F(1, 2), 1],
    "letter_height_mm": [3, 4],
    "word_gap_mm": [1, 2],
    "candidates": [
        {"id": "true", "lines": ["ABCDEF", "GHIJ"]},
        {"id": "long", "lines": ["ABCDEFGHIJKLMNOPQRST", "UV"]},
        {"id": "short", "lines": ["AB", "CD"]},
        {"id": "threelines", "lines": ["ABCDEF", "GHI", "J"]},
    ],
}


def synthetic_region():
    # Truth "ABCDEF" / "GHIJ" drawn with width 2.5 mm, spacing 0.75 mm, height 3.5 mm:
    # longest line 6*2.5 + 5*0.75 = 18.75 mm; at 0.01 mm/px that is 1875 px.
    return {"id": "synthetic", "pixel_mm": {"center": "0.01", "radius": "0.0001"},
            "distortion": {"center": 0, "radius": "0.02"},
            "threshold_px": {"center": 0, "radius": 20},
            "width_px": 1875, "letter_height_px": 350, "lines": 2, "letters": [9, 11]}


class T(unittest.TestCase):
    def test_interval_exact(self):
        a = Iv.ball("0.1", "0.1")
        self.assertEqual(a.lo, 0)
        self.assertEqual((a * a).hi, F(1, 25))
        self.assertEqual((Iv(1, 2) - Iv(1, 2)).lo, -1)

    def test_known_title_survives_and_others_certified(self):
        r = check(PRIORS, synthetic_region())
        self.assertEqual([s["id"] for s in r["survivors"]], ["true"])
        el = {e["id"]: e["certificates"] for e in r["eliminated"]}
        self.assertEqual(set(el), {"long", "short", "threelines"})
        self.assertTrue(any(c["quantity"] == "lines" for c in el["threelines"]))
        for certs in el.values():
            for c in certs:
                self.assertRegex(c["inequality"], r"^pred\.(hi .* < meas\.lo|lo .* > meas\.hi)")

    def test_wide_uncertainty_eliminates_nothing(self):
        reg = synthetic_region()
        reg.pop("lines"); reg.pop("letters")
        reg["distortion"] = {"center": 0, "radius": "0.9"}
        reg["threshold_px"] = {"center": 0, "radius": 5000}
        r = check(PRIORS, reg)
        self.assertEqual(r["eliminated"], [])


if __name__ == "__main__":
    unittest.main()
