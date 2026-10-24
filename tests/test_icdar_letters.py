import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LETTERS = str(ROOT / "scripts" / "letters")

try:
    import numpy as np
    sys.path.insert(0, LETTERS)
    import greek_lm as G
    import icdar_h2h as H
    import icdar_read as R
    import reader_api as A
except ImportError:  # these scripts need numpy; the core kit does not
    np = G = H = R = A = None
finally:
    while LETTERS in sys.path:
        sys.path.remove(LETTERS)


@unittest.skipIf(np is None, "needs numpy")
class IcdarBuildTest(unittest.TestCase):
    def test_to_capital(self):
        self.assertEqual(H.to_capital("ϲ"), "Σ")
        self.assertEqual(H.to_capital("ά"), "Α")
        self.assertIsNone(H.to_capital("."))
        self.assertIsNone(H.to_capital("?"))

    def test_group_lines(self):
        line1 = [[10 + 30 * i, 100, 25, 30] for i in range(6)]
        line2 = [[10 + 30 * i, 200, 25, 30] for i in range(6)]
        out = H.group_lines(line1 + line2)
        self.assertEqual([sorted(m) for m, _ in out], [list(range(6)), list(range(6, 12))])
        self.assertFalse(any(a for _, a in out))
        stacked = [[10, 100, 25, 30], [12, 112, 25, 30], [40, 104, 25, 30]]
        self.assertTrue(H.group_lines(stacked)[0][1])

    def test_ink_gate_can_fail(self):
        g = np.full((400, 400), 200.0)
        boxes = [[20 + 40 * i, 100 + 80 * r, 30, 30] for i in range(8) for r in range(3)]
        for x, y, w, h in boxes:
            g[y:y + h, x:x + w] = 60.0 + (x % 7)
        self.assertTrue(H.ink_gate(g, boxes)["pass"])
        moved = [[x, y + 40, w, h] for x, y, w, h in boxes]   # boxes on the bare gaps
        self.assertFalse(H.ink_gate(g, moved)["pass"])


@unittest.skipIf(np is None, "needs numpy")
class IcdarScoreTest(unittest.TestCase):
    def test_verdict(self):
        self.assertEqual(R.verdict(-0.1, -0.01), "ahead")
        self.assertEqual(R.verdict(0.01, 0.1), "behind")
        self.assertEqual(R.verdict(-0.04, 0.04), "level")
        self.assertEqual(R.verdict(-0.2, 0.04), "not resolved")

    def test_paired_sign(self):
        a = {f"u{i}": (5, 10) for i in range(10)}
        b = {f"u{i}": (2, 10) for i in range(10)}
        p = R.paired(a, b, n=500)
        self.assertAlmostEqual(p["d"], -0.3)
        self.assertLess(p["ci95"][1], 0)

    def test_tile_shuffle_keeps_pixels(self):
        g = np.arange(64 * 48, dtype=float).reshape(64, 48)
        s = R.tile_shuffle(g, 3)
        self.assertEqual(s.shape, g.shape)
        self.assertFalse(np.array_equal(s, g))


@unittest.skipIf(np is None, "needs numpy")
class GreekLMTest(unittest.TestCase):
    def setUp(self):
        self.lm = G.LM.train("ΜΗΝΙΝΑΕΙΔΕΘΕΑ" * 50 + "ΚΑΙΤΟΝΚΑΙΤΗΝ" * 50, order=4)

    def test_probabilities_sum_to_one(self):
        for ctx in ("", "ΜΗ", "ΞΞΞ"):
            self.assertAlmostEqual(float(np.exp(self.lm.logp_vec(ctx)).sum()), 1.0, places=6)

    def test_prose_of_drops_verse_and_quotes(self):
        xml = '<TEI><teiHeader>ΑΑΑ</teiHeader><body><p>λόγος <quote>μῆνιν</quote> <l>ἄειδε</l> ἐστί</p></body></TEI>'
        self.assertEqual(G.prose_of(xml), "ΛΟΓΟΣΕΣΤΙ")

    def test_decode_prefers_the_language_model_on_a_tie(self):
        idx = G.ALPHABET.index
        post = np.full((4, 24), np.log(1e-4))
        for i, ch in enumerate("ΜΗΝΙ"):
            post[i, idx(ch)] = np.log(0.6)
        post[1, idx("Η")] = post[1, idx("Ν")] = np.log(0.45)   # box 2 is Η or Ν, even odds
        text, conf, alts = G.decode_boxes(post, self.lm, 1.0)
        self.assertEqual(text, "ΜΗΝΙ")
        self.assertEqual(len(conf), 4)
        self.assertEqual(alts[1][0][0], "Η")
        text0, _, _ = G.decode_boxes(post, self.lm, 0.0)
        self.assertEqual(len(text0), 4)

    def test_edit_distance(self):
        self.assertEqual(G.edit_distance("ΚΑΙ", "ΚΑΙ"), 0)
        self.assertEqual(G.edit_distance("ΚΑΙ", "ΚΙ"), 1)
        self.assertEqual(G.edit_distance("", "ΑΒ"), 2)


class _FakeReader:
    def letter(self, image, box=None, top=5):
        return {"letter": "Α", "image": image, "box": box, "top": top}

    def line(self, image, boxes, lm_weight=1.0):
        return {"text": "Α" * len(boxes), "lm_weight": lm_weight}

    def line_free(self, image, box=None, letter_height=None):
        raise FileNotFoundError(image)


@unittest.skipIf(np is None, "needs numpy")
class ReaderMcpTest(unittest.TestCase):
    def rpc(self, msgs):
        out = io.StringIO()
        A.serve(_FakeReader(), io.StringIO("\n".join(json.dumps(m) for m in msgs) + "\nnot json\n"), out)
        return [json.loads(x) for x in out.getvalue().splitlines()]

    def test_session(self):
        r = self.rpc([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "read_line", "arguments": {"image": "x.png", "boxes": [[0, 0, 1, 1]] * 3}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_letter", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "read_line_free",
                                                                          "arguments": {"image": "gone.png"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "nope"},
        ])
        self.assertEqual([m.get("id") for m in r], [1, 2, 3, 4, 5, 6, None])   # no reply to the notification
        self.assertEqual(r[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual({t["name"] for t in r[1]["result"]["tools"]}, {"read_letter", "read_line", "read_line_free"})
        self.assertEqual(r[2]["result"]["structuredContent"]["text"], "ΑΑΑ")
        self.assertEqual(r[3]["error"]["code"], -32602)
        self.assertTrue(r[4]["result"]["isError"])
        self.assertEqual(r[5]["error"]["code"], -32601)
        self.assertEqual(r[6]["error"]["code"], -32700)

    def test_unknown_version_falls_back(self):
        r = self.rpc([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999"}}])
        self.assertEqual(r[0]["result"]["protocolVersion"], A.SUPPORTED[0])


@unittest.skipIf(np is None, "needs numpy")
class ReaderFetchTest(unittest.TestCase):
    def test_fetch_checks_every_hash(self):
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "src").mkdir()
            files = {"r-model.pt": b"weights", "r-config.json": b"{}", "lm.json.gz": b"counts"}
            for n, b in files.items():
                (t / "src" / n).write_bytes(b)
            sha = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
            man = {"base_url": (t / "src").as_uri() + "/",
                   "runs": {"r": {"model": {"file": "r-model.pt", "sha256": sha["r-model.pt"], "bytes": 7},
                                  "config": {"file": "r-config.json", "sha256": sha["r-config.json"], "bytes": 2}}},
                   "lm": {"file": "lm.json.gz", "sha256": sha["lm.json.gz"], "bytes": 6}}
            (t / "m.json").write_text(json.dumps(man))
            old = A.MANIFEST
            A.MANIFEST = t / "m.json"
            try:
                self.assertEqual(A.released(t / "home"), (None, None))
                runs, lm = A.fetch(t / "home", log=lambda m: None)
                self.assertEqual(runs, str(t / "home" / "r"))
                self.assertTrue((t / "home" / "r" / "model.pt").exists())
                self.assertEqual(lm, str(t / "home" / "lm.json.gz"))
                (t / "home" / "r" / "model.pt").write_bytes(b"tampered")
                self.assertEqual(A.released(t / "home"), (None, None))
                (t / "src" / "r-model.pt").write_bytes(b"other")
                with self.assertRaises(ValueError):
                    A.fetch(t / "home", log=lambda m: None)
            finally:
                A.MANIFEST = old


if __name__ == "__main__":
    unittest.main()
