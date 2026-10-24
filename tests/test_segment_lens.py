"""Segment Lens (spaces/segment-lens): its preview reader matches kit.atlas's writer, and the page keeps its promises."""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from kit import atlas

ROOT = Path(__file__).resolve().parents[1]
SPACE = ROOT / "spaces" / "segment-lens"
APP = (SPACE / "app.js").read_text(encoding="utf-8")

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def _parse_lens_source():
    """The page's parseLens function, as text."""
    m = re.search(r"function parseLens\(raw\) \{.*?\n\}\n", APP, re.S)
    assert m, "parseLens not found in app.js"
    return m.group(0)


class TestPage(unittest.TestCase):
    def test_header_offsets_match_the_python_format(self):
        self.assertIn(f"'{atlas.LENS_MAGIC.decode()}'", APP)
        # magic (4) + three uint16 (6) + six float32 (24) = 34 bytes before the planes
        self.assertEqual(4 + 6 + 24, 34)
        src = _parse_lens_source()
        for needle in ("getUint16(4, true)", "getUint16(6, true)", "getUint16(8, true)", "getFloat32(10 + 4 * i",
                       "getFloat32(22 + 4 * i", "34 + 2 * n * i", "34 + 6 * n"):
            self.assertIn(needle, src)

    def test_card_links_the_dataset_and_page_reads_only_it(self):
        card = (SPACE / "README.md").read_text(encoding="utf-8")
        self.assertIn(atlas.DATASET, card)
        self.assertIn(f"https://huggingface.co/datasets/{atlas.DATASET}/resolve/main/", APP)
        # meshes are drawn only from the atlas's lens files, never fetched from the bucket
        self.assertNotRegex(APP, r"fetch\([^)]*(S3|amazonaws)")
        self.assertIn("if (!row.lens)", APP)

    def test_no_long_dashes(self):
        for f in SPACE.iterdir():
            if f.suffix in (".js", ".html", ".css", ".md") or f.name == "NOTICE":
                text = f.read_text(encoding="utf-8")
                self.assertNotIn("\u2014", text, f.name)
                self.assertNotIn("\u2013", text, f.name)

    def test_agent_calls_are_documented(self):
        page = (ROOT / "docs" / "tools" / "segment-lens.md").read_text(encoding="utf-8")
        block = re.search(r"window\.segmentLens = \{(.*?)\n\};", APP, re.S).group(1)
        calls = re.findall(r"^\s{2}(\w+):", block, re.M)
        self.assertTrue(calls)
        for c in calls:
            self.assertIn(f"`{c}", page, c)


@unittest.skipIf(np is None or not shutil.which("node"), "needs numpy and Node.js")
class TestReaderRoundTrip(unittest.TestCase):
    def test_page_reads_what_the_atlas_writes(self):
        from kit import tifxyz
        r, c = np.mgrid[0:300, 0:140].astype(float)
        xyz = np.stack([1000 + c * 20, 2000 + r * 20, 500 + 300 * np.sin(c / 20)], -1)
        xyz[100:110, 50:60] = -1
        seg = tifxyz.Segment(xyz, (xyz > -0.5).all(-1), {"scale": [0.05, 0.05]}, "t", 2.0)
        _, m = atlas.measure(seg)
        blob = atlas.lens_grid(seg, m, side=64)
        h, w, k, lo, hi, back, flags = atlas.read_lens(blob)
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw.bin"
            import gzip
            raw.write_bytes(gzip.decompress(blob))
            js = Path(d) / "t.mjs"
            js.write_text(_parse_lens_source() + f"""
import {{ readFileSync }} from 'fs';
const g = parseLens(new Uint8Array(readFileSync({json.dumps(str(raw))})));
let fl = 0; for (const f of g.flags) if (f & 1) fl++;
let miss = 0; for (const v of g.q[0]) if (v === 65535) miss++;
console.log(JSON.stringify({{h: g.h, w: g.w, k: g.k, lo: g.lo, hi: g.hi, holes: fl, missing: miss, q0: g.q[2][5 * g.w + 7]}}));
""")
            out = json.loads(subprocess.run(["node", str(js)], capture_output=True, text=True, check=True).stdout)
        self.assertEqual((out["h"], out["w"], out["k"]), (h, w, k))
        np.testing.assert_allclose(out["lo"], lo, rtol=1e-6)
        np.testing.assert_allclose(out["hi"], hi, rtol=1e-6)
        self.assertEqual(out["holes"], int((flags & 1).astype(bool).sum()))
        self.assertGreater(out["holes"], 0)
        self.assertEqual(out["missing"], int(np.isnan(back[..., 0]).sum()))
        z = lo[2] + out["q0"] / 65534 * (hi[2] - lo[2])
        self.assertAlmostEqual(z, back[5, 7, 2], places=3)


if __name__ == "__main__":
    unittest.main()
