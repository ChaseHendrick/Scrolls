import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from kit import cli

try:
    import numpy as np
    from kit import greeklm
except ImportError:  # the core kit is standard library only
    np = greeklm = None

TEXT = "ΚΑΙΤΟΝΘΕΟΝΚΑΙΤΟΥϹΘΕΟΥϹΚΑΙΤΗΝΑΡΕΤΗΝ" * 30

TEI = """<TEI><teiHeader><title>header text must not count</title></teiHeader>
<text><body><div><p>καὶ τὸν θεὸν <note>ignore this</note> καὶ τοὺς θεούς, ἀρετή.</p></div></body></text></TEI>"""


@unittest.skipIf(np is None, "numpy not installed")
class GreekLMTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(greeklm.clean_text("Καὶ τοὺς θεούς, ἀρετή."), "ΚΑΙΤΟΥϹΘΕΟΥϹΑΡΕΤΗ")
        self.assertEqual(greeklm.clean_text("abc 123"), "")

    def test_tei_drops_header_and_notes(self):
        t = greeklm.clean_text(greeklm.tei_text(TEI))
        self.assertEqual(t, "ΚΑΙΤΟΝΘΕΟΝΚΑΙΤΟΥϹΘΕΟΥϹΑΡΕΤΗ")

    def test_distribution_sums_to_one_in_every_context(self):
        lm = greeklm.KNLetterLM(order=4).fit([TEXT])
        for prefix in ("", "Κ", "ΚΑΙ", "ΞΨΩ", "ΘΕΟΥ"):
            self.assertAlmostEqual(float(np.exp(lm.logp_next(prefix)).sum()), 1.0, places=6)
            self.assertTrue(np.all(np.exp(lm.logp_next(prefix)) > 0))

    def test_learns_and_beats_uniform(self):
        lm = greeklm.KNLetterLM(order=5).fit([TEXT])
        self.assertLess(lm.bits_per_letter("ΚΑΙΤΟΝΘΕΟΝ"), 1.0)
        self.assertGreater(lm.bits_per_letter("ΨΞΖΨΞΖΨΞΖ"), math.log2(24) - 1)
        p = np.exp(lm.logp_next("ΚΑ"))
        self.assertEqual(greeklm.ALPHABET[int(p.argmax())], "Ι")

    def test_save_load_round_trip(self):
        lm = greeklm.KNLetterLM(order=4).fit([TEXT])
        with tempfile.TemporaryDirectory() as d:
            lm.save(Path(d) / "lm.npz")
            lm2 = greeklm.KNLetterLM.load(Path(d) / "lm.npz")
        for prefix in ("", "ΚΑ", "ΘΕΟ"):
            self.assertTrue(np.allclose(lm.logp_next(prefix), lm2.logp_next(prefix), atol=1e-6))

    def test_cli_build_and_score(self):
        with tempfile.TemporaryDirectory() as d:
            tei = Path(d) / "t.xml"
            tei.write_text(TEI.replace("<p>", "<p>" + "καὶ τὸν θεὸν " * 200), encoding="utf-8")
            out = Path(d) / "lm.npz"
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                self.assertEqual(cli.main(["greeklm", "build", str(out), str(tei), "--order", "3"]), 0)
            self.assertGreater(json.loads(buf.getvalue())["train_letters"], 1000)
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                self.assertEqual(cli.main(["greeklm", "score", str(out), "καὶ", "τὸν", "θεόν"]), 0)
            res = json.loads(buf.getvalue())
            self.assertEqual(res["letters"], "ΚΑΙΤΟΝΘΕΟΝ")
            self.assertLess(res["bits_per_letter"], 2.0)


if __name__ == "__main__":
    unittest.main()
