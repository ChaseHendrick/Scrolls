"""Tests for kit/expatlas.py: the geometry on synthetic sheets, the calls, the registry and the matrix logic."""

import json
import math
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    import scipy  # noqa: F401
    import tifffile  # noqa: F401
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False

from kit import expatlas

ROOT = Path(__file__).resolve().parent.parent


def cylinder(radius, h=40, w=60, step=20.0, z0=100.0, theta0=0.0):
    """A tifxyz-like grid on a cylinder about the z axis (voxels), rows along z, columns along the arc."""
    rows = np.arange(h) * step + z0
    dth = step / radius
    cols = theta0 + np.arange(w) * dth
    th, z = np.meshgrid(cols, rows)
    x = 2000 + radius * np.cos(th)
    y = 2000 + radius * np.sin(th)
    return np.stack([x, y, z], -1).astype(np.float64)


def plane(h=40, w=40, step=20.0, z=500.0, tilt=0.0):
    r, c = np.meshgrid(np.arange(h) * step, np.arange(w) * step, indexing="ij")
    return np.stack([c + 100, r + 100, z + tilt * c], -1).astype(np.float64)


@unittest.skipUnless(HAVE, "needs numpy, scipy and tifffile")
class Geometry(unittest.TestCase):
    PX = 9.4

    def test_same_sheet_is_exposed(self):
        a = cylinder(1500)
        r = expatlas.pair(a, a, self.PX)
        self.assertEqual(r["call"], "exposed")
        self.assertGreater(r["f_same"], 0.99)
        self.assertAlmostEqual(r["z_overlap"], 1.0)

    def test_retrace_on_another_grid_is_exposed(self):
        # the same sheet sampled on a grid shifted by half a cell and coarser: an independent trace
        a = cylinder(1500)
        b = cylinder(1500 + 2.0, h=30, w=45, step=27.0, z0=113.0, theta0=0.004)
        r = expatlas.pair(a, b, self.PX)
        self.assertEqual(r["call"], "exposed")
        self.assertGreater(r["f_same"], 0.6)

    def test_adjacent_winding_is_clear(self):
        a = cylinder(1500)
        shift = 140.0 / self.PX           # one nominal winding
        b = cylinder(1500 + shift)
        r = expatlas.pair(a, b, self.PX)
        self.assertEqual(r["call"], "clear")
        self.assertEqual(r["f_same"], 0.0)
        self.assertGreater(r["f_reach"], 0.9)   # it is there, just one winding out

    def test_threshold_edges(self):
        a = plane()
        inside = plane(z=500.0 + 55.0 / self.PX)
        outside = plane(z=500.0 + 65.0 / self.PX)
        self.assertEqual(expatlas.pair(a, inside, self.PX)["call"], "exposed")
        self.assertEqual(expatlas.pair(a, outside, self.PX)["call"], "clear")
        band = expatlas.pair(a, outside, self.PX)
        self.assertGreater(band["f_band"], 0.9)   # within the 100 um render band

    def test_no_cover_past_the_edge(self):
        # a training sheet beside the evaluation sheet in the same plane covers nothing
        a = plane()
        b = plane() + np.array([40 * 20.0 + 200, 0, 0])
        r = expatlas.pair(a, b, self.PX)
        self.assertEqual(r["f_same"], 0.0)
        self.assertEqual(r["f_reach"], 0.0)

    def test_partial_cover_and_trace(self):
        a = plane(h=100, w=100)
        b = plane(h=100, w=3)               # a 3-column strip: 3 % of the vertices
        r = expatlas.pair(a, b, self.PX)
        self.assertEqual(r["call"], "trace")
        self.assertTrue(0.02 <= r["f_same"] <= 0.04)

    def test_holes_are_not_cover(self):
        a = plane()
        b = plane()
        b[:, :20] = np.nan
        r = expatlas.pair(a, b, self.PX)
        self.assertTrue(0.45 <= r["f_same"] <= 0.55)

    def test_crossing_sheet_is_not_exposed(self):
        # a sheet that crosses the evaluation sheet at 45 degrees touches it along one line only
        a = plane(h=60, w=60)
        b = plane(h=60, w=60, z=500.0 - 300, tilt=0.5)
        r = expatlas.pair(a, b, self.PX)
        self.assertLess(r["f_same"], expatlas.EXPOSED_FRAC)

    def test_displaced_moves_along_normal(self):
        a = plane()
        b = expatlas.displaced(a, 3.0)
        d = np.nanmedian(np.abs(b[..., 2] - a[..., 2]))
        self.assertAlmostEqual(d, 3.0, places=5)

    def test_decimate_caps_points(self):
        a = plane(h=200, w=200)
        sub, k = expatlas.decimate(a, 1000)
        self.assertLessEqual(int(np.isfinite(sub).all(-1).sum()), 1000)
        self.assertGreater(k, 1)

    def test_write_and_read_tifxyz(self):
        a = plane()
        a[0, 0] = np.nan
        with tempfile.TemporaryDirectory() as d:
            expatlas.write_tifxyz(Path(d) / "m", a)
            b = expatlas.Fetcher(Path(d) / "cache").read(str(Path(d) / "m"))
        self.assertTrue(np.isnan(b[0, 0]).all())
        self.assertTrue(np.allclose(a[1:], b[1:], atol=1e-3))


class Calls(unittest.TestCase):
    def test_call_bands(self):
        self.assertEqual(expatlas.call(0.05), "exposed")
        self.assertEqual(expatlas.call(0.0499), "trace")
        self.assertEqual(expatlas.call(0.005), "trace")
        self.assertEqual(expatlas.call(0.0049), "clear")
        self.assertEqual(expatlas.call(None), "unknown")

    def test_skip_patterns_match_any_spelling(self):
        rec = {"scroll": "PHercX", "suffix": "w031_2026"}
        self.assertTrue(expatlas.skipped("20260101000000", rec, ["PHercX/*w03[0-9]*"]))
        self.assertTrue(expatlas.skipped("20260101000000", rec, ["PHercX/2026010100*"]))
        self.assertFalse(expatlas.skipped("20260101000000", rec, ["PHercY/*"]))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "skip.txt"
            p.write_text("# comment\nPHercX/*w03*\n\n")
            self.assertEqual(expatlas.read_skip(p), ["PHercX/*w03*"])
            p.write_text("nopattern\n")
            with self.assertRaises(expatlas.AtlasError):
                expatlas.read_skip(p)


class Registry(unittest.TestCase):
    def setUp(self):
        self.reg = expatlas.load_registry()

    def test_models_present(self):
        ids = {m["id"] for m in self.reg["models"]}
        for need in ("ink_9um", "v8in", "v8in-1447", "d9v2", "reader-v2", "reader-v3", "canonical-2um", "hecate",
                     "trace-v3b", "a-hn"):
            self.assertIn(need, ids)

    def test_every_entry_well_formed(self):
        roles = {"train", "train_split", "validation", "validation_only", "selected", "test"}
        for m in self.reg["models"]:
            self.assertIn(m["label"], ("Sourced fact", "Community report"))
            for e in m["entries"]:
                self.assertIn(e["role"], roles)
                if e["segment"] not in (None, "*"):
                    self.assertRegex(e["segment"], r"^\d{14}$")
                self.assertIn(e["source"], self.reg["sources"])
        for s in self.reg["sources"].values():
            self.assertTrue(s["url"].startswith("https://"))

    def test_inheritance(self):
        c = [mid for mid, _ in expatlas.chain(self.reg, "v8in-1447")]
        self.assertEqual(c, ["v8in-1447", "v8in"])
        c = [mid for mid, _ in expatlas.chain(self.reg, "reader-v3")]
        self.assertEqual(c, ["reader-v3", "reader-v2", "ink_9um"])

    def test_known_names_resolve(self):
        by = {m["id"]: m for m in self.reg["models"]}
        seg = {e["name"]: e["segment"] for e in by["ink_9um"]["entries"]}
        self.assertEqual(seg["phercparis4-w05"], "20231012184424")
        self.assertEqual(seg["pherc1667-w018"], "20240304144031")
        v8 = {e["name"]: e["segment"] for e in by["v8in"]["entries"]}
        self.assertIsNone(v8["20231012184423"])     # listed by v8in, not in the catalog
        self.assertEqual(v8["0009B_ag132115"], "20250919132115")
        roles = {e["role"] for e in by["hecate"]["entries"] if e["scroll"] == "PHerc0841"}
        self.assertEqual(roles, {"validation_only"})

    def test_no_dashes(self):
        text = (ROOT / "kit" / "data" / "expatlas-models.json").read_text(encoding="utf-8")
        self.assertNotIn("—", text)
        self.assertNotIn("–", text)


def tiny_catalog():
    """Two scrolls; scroll A has an evaluation segment E on volume V1 and training segments on V1 and V2."""
    m = [[2.0, 0, 0, 10.0], [0, 2.0, 0, 0], [0, 0, 2.0, 0]]
    inv = [[0.5, 0, 0, -5.0], [0, 0.5, 0, 0], [0, 0, 0.5, 0]]

    def seg(gid, vol, labeled=False):
        data = [{"type": "tifxyz", "origins": [{"path": f"A/{gid}/tifxyz/"}]}]
        if labeled:
            data.append({"type": "ink-labels", "origins": [{"path": f"A/{gid}/ink-labels/"}]})
        return {"suffix": f"s{gid[-1]}", "original_volume_id": vol, "data": data}

    return {"samples": {
        "A": {"sample": {"properties": {"volume_transforms": [
            {"from_volume_id": "11111111111111", "transforms": [{"to_volume_id": "22222222222222", "matrix": m,
                                                                 "derivation_path": "11111111111111-22222222222222"}]},
            {"from_volume_id": "22222222222222", "transforms": [{"to_volume_id": "11111111111111", "matrix": inv,
                                                                 "derivation_path": "11111111111111-22222222222222⁻¹"}]}]}},
              "volumes": {"11111111111111": {"properties": {"pixel_size_um": 9.0}},
                          "22222222222222": {"properties": {"pixel_size_um": 4.5}}},
              "segments": {"30000000000001": seg("30000000000001", "11111111111111", True),
                           "30000000000002": seg("30000000000002", "22222222222222"),
                           "30000000000003": seg("30000000000003", "11111111111111")}},
        "B": {"volumes": {}, "segments": {}}}}


class FakeFetch:
    def __init__(self, meshes):
        self.meshes = meshes

    def read(self, path):
        return self.meshes[path].copy()


@unittest.skipUnless(HAVE, "needs numpy, scipy and tifffile")
class Matrix(unittest.TestCase):
    def setUp(self):
        e = cylinder(1500)
        same_on_v2 = e * 2.0 + np.array([10.0, 0, 0])      # E itself, moved to V2's frame by the matrix
        far = cylinder(1500 + 300.0)                       # another winding, on V1
        self.fetch = FakeFetch({"A/30000000000001/tifxyz": e, "A/30000000000002/tifxyz": same_on_v2,
                                "A/30000000000003/tifxyz": far})
        self.cat = tiny_catalog()

    def reg(self, entries, inherits=(), lst="published"):
        src = {"s": {"url": "https://example.org/x", "rev": "1", "read": "2026-11-04"}}
        models = [{"id": "m", "title": "m", "by": "x", "label": "Sourced fact", "list": lst,
                   "inherits": list(inherits), "entries": entries},
                  {"id": "p", "title": "p", "by": "x", "label": "Sourced fact", "list": "published",
                   "inherits": [], "entries": [{"role": "train", "scroll": "A", "name": "E", "segment": "30000000000001",
                                                "match": "id", "source": "s"}]}]
        return {"schema": "expatlas-models/1", "sources": src, "models": models}

    def cell(self, reg, model="m", skip=()):
        m = expatlas.build_matrix(self.cat, reg, self.fetch, models=[model], skip=skip)
        return m, m["cells"][0]

    def test_cross_scan_copy_is_exposed(self):
        reg = self.reg([{"role": "train", "scroll": "A", "name": "t2", "segment": "30000000000002", "match": "id",
                         "source": "s"}])
        _, c = self.cell(reg)
        self.assertEqual(c["status"], "exposed")
        self.assertGreater(c["f_same"], 0.95)

    def test_other_winding_is_clear(self):
        reg = self.reg([{"role": "train", "scroll": "A", "name": "t3", "segment": "30000000000003", "match": "id",
                         "source": "s"}])
        _, c = self.cell(reg)
        self.assertEqual(c["status"], "clear")

    def test_named_and_inherited(self):
        reg = self.reg([], inherits=["p"])
        _, c = self.cell(reg)
        self.assertEqual(c["status"], "trained")
        self.assertIn("m < p", c["why"])

    def test_no_training_on_scroll_is_clear(self):
        reg = self.reg([{"role": "train", "scroll": "B", "name": "x", "segment": None, "match": "none",
                         "source": "s"}])
        _, c = self.cell(reg)
        self.assertEqual(c["status"], "clear")

    def test_unresolved_name_on_scroll_is_unknown(self):
        reg = self.reg([{"role": "train", "scroll": "A", "name": "mystery", "segment": None, "match": "none",
                         "source": "s"}])
        _, c = self.cell(reg)
        self.assertEqual(c["status"], "unknown")

    def test_unpublished_list_is_unknown(self):
        _, c = self.cell(self.reg([], lst="not published"))
        self.assertEqual(c["status"], "unknown")

    def test_validation_cover_is_selected(self):
        reg = self.reg([{"role": "validation", "scroll": "A", "name": "t2", "segment": "30000000000002",
                         "match": "id", "source": "s"}])
        _, c = self.cell(reg)
        self.assertEqual(c["status"], "selected")

    def test_skip_reads_nothing(self):
        reg = self.reg([{"role": "train", "scroll": "A", "name": "t2", "segment": "30000000000002", "match": "id",
                         "source": "s"}])
        self.fetch.meshes = {}
        m, c = self.cell(reg, skip=["A/*"])
        self.assertEqual(c["status"], "not-run")
        self.assertEqual(m["duplicates"], [])

    def test_text_render(self):
        reg = self.reg([{"role": "train", "scroll": "A", "name": "t2", "segment": "30000000000002", "match": "id",
                         "source": "s"}])
        m, _ = self.cell(reg)
        text = expatlas.format_matrix(m)
        self.assertIn("E100", text.replace(" ", ""))


class Cli(unittest.TestCase):
    def test_models_json(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = expatlas.main(["models", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())["schema"], "expatlas-models/1")

    def test_registered_in_kit_cli(self):
        from kit import cli
        names = [n for _, group in cli.GROUPS for n in group]
        self.assertIn("expatlas", names)


if __name__ == "__main__":
    unittest.main()
