"""kit atlas: listing the bucket, measuring meshes (whole and in bands), Lens grids, prize lists, incremental builds."""

import json
import math
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover - the map tests skip without numpy
    np = None

from kit import atlas, find


def _sheet(h=60, w=80, step=20.0):
    r, c = np.mgrid[0:h, 0:w].astype(float)
    xyz = np.stack([1000 + c * step, 2000 + r * step, 500 + 200 * np.sin(c / 15.0)], -1)
    return xyz


def _seg(xyz, step=20.0, um=2.0):
    from kit import tifxyz
    valid = (xyz > -0.5).all(-1)
    return tifxyz.Segment(xyz, valid, {"scale": [1 / step, 1 / step]}, "test", um)


def _listing(prefix, folders=(), keys=()):
    x = "".join(f"<CommonPrefixes><Prefix>{f}</Prefix></CommonPrefixes>" for f in folders)
    x += "".join(f"<Contents><Key>{k}</Key><LastModified>2026-07-15T15:36:05.000Z</LastModified>"
                 f"<ETag>&quot;{e}&quot;</ETag><Size>{s}</Size></Contents>" for k, s, e in keys)
    return f"<ListBucketResult><Prefix>{prefix}</Prefix>{x}</ListBucketResult>".encode()


class FakeBucket:
    """metadata.json and ListObjectsV2 answers for two scrolls: PHerc0139 (on no prize list) and PHerc1447."""

    def __init__(self, etag="aaa"):
        seg = "PHerc0139/segments/w001/"
        mesh = seg + "mesh/w001-on-20260102150214-2.399um.tifxyz/"
        self.pages = {
            "PHerc0139/segments/": _listing("PHerc0139/segments/", [seg]),
            seg + "mesh/": _listing(seg + "mesh/", [mesh, seg + "mesh/intermediate/"]),
            mesh: _listing(mesh, keys=[(mesh + f, 100, etag) for f in ("x.tif", "y.tif", "z.tif", "meta.json")]),
            seg + "mesh/intermediate/": _listing(seg + "mesh/intermediate/", keys=[(seg + "mesh/intermediate/a.obj", 5, "e")]),
            "PHerc1447/segments/": _listing("PHerc1447/segments/", ["PHerc1447/segments/s1/"]),
            "PHerc1447/segments/s1/mesh/": _listing("PHerc1447/segments/s1/mesh/", ["PHerc1447/segments/s1/mesh/tifxyz/"]),
            "PHerc1447/segments/s1/mesh/tifxyz/": _listing(
                "PHerc1447/segments/s1/mesh/tifxyz/",
                keys=[(f"PHerc1447/segments/s1/mesh/tifxyz/{f}", 50, "bbb") for f in ("x.tif", "y.tif", "z.tif")]),
        }
        self.meta = {"samples": {
            "PHerc0139": {"volumes": {"20260102150214": {"id": "20260102150214", "properties": {"pixel_size_um": 2.399}},
                                      "20250728140407": {"id": "20250728140407", "properties": {"pixel_size_um": 9.362}}}},
            "PHerc1447": {"volumes": {"20250521151220": {"id": "20250521151220", "properties": {"pixel_size_um": 8.64}}}}}}

    def __call__(self, url, timeout=60):
        if url.endswith("/metadata.json"):
            return json.dumps(self.meta).encode()
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        prefix = q["prefix"][0]
        return self.pages.get(prefix, _listing(prefix))


@unittest.skipIf(np is None, "needs numpy")
class TestMeasure(unittest.TestCase):
    def test_flat_isometric_sheet_is_clean_and_area_is_exact(self):
        r, c = np.mgrid[0:30, 0:40].astype(float)
        xyz = np.stack([c * 20.0, r * 20.0, np.full((30, 40), 5.0)], -1)
        nums, _ = atlas.measure(_seg(xyz))
        self.assertTrue(nums["clean"])
        self.assertAlmostEqual(nums["edge_p50"], 1.0, places=6)
        self.assertEqual(nums["within_10pct"], 1.0)
        # 29 x 39 cells of 20 x 20 voxels at 2 um: 452400 um2 = 0.004524 cm2
        self.assertAlmostEqual(nums["area_cm2"], round(29 * 39 * 400 * 4e-8, 3))

    def test_planted_hole_and_stretch_are_counted(self):
        xyz = _sheet()
        xyz[20:25, 30:36] = -1                     # a hole of 30 nodes inside the sheet
        xyz[5:10, 60:70, 0] += 2.2 * 20             # a shifted patch: its border edges stretch
        nums, m = atlas.measure(_seg(xyz))
        self.assertEqual(nums["holes_nodes"], 30)
        self.assertGreater(nums["stretched_nodes"], 0)
        self.assertFalse(nums["clean"])
        clean, _ = atlas.measure(_seg(_sheet()))
        self.assertEqual(clean["holes_nodes"], 0)
        self.assertEqual(clean["stretched_nodes"], 0)

    def test_bands_give_the_same_numbers_as_the_whole_grid(self):
        xyz = _sheet(97, 53)
        xyz[40:44, 10:14] = -1
        xyz[60:66, 20:30, 2] += np.arange(6)[:, None] * 25    # a ramp that stretches row edges across a band edge
        whole, mw = atlas.measure(_seg(xyz))
        bands, mb = atlas.measure(_seg(xyz), band_rows=7, band_nodes=10)
        self.assertTrue(bands["banded"])
        for k in whole:
            if k != "banded":
                self.assertEqual(whole[k], bands[k], k)
        for k in mw:
            self.assertTrue((mw[k] == mb[k]).all(), k)
        # the comparison can fail: bands that drop the overlap row lose the cells across each band edge
        part, _ = atlas.measure(_seg(xyz[:7]))
        self.assertLess(part["nodes_filled"], whole["nodes_filled"])

    def test_measure_matches_kit_tifxyz(self):
        from kit import tifxyz
        xyz = _sheet()
        xyz[20:25, 30:36] = -1
        seg = _seg(xyz)
        nums, _ = atlas.measure(seg)
        rep, _ = tifxyz.check(seg)
        self.assertEqual(nums["holes_nodes"], rep["holes"]["nodes"])
        self.assertEqual(nums["folds_nodes"], rep["folds"]["nodes"])
        self.assertEqual(nums["stretched_nodes"], rep["stretched"]["nodes"])
        self.assertEqual(nums["area_cm2"], tifxyz.info(seg)["area_cm2"])

    def test_lens_grid_round_trips_positions_and_flags(self):
        xyz = _sheet(600, 300)
        xyz[100:110, 100:110] = -1
        seg = _seg(xyz)
        _, m = atlas.measure(seg)
        h, w, k, lo, hi, back, flags = atlas.read_lens(atlas.lens_grid(seg, m, side=128))
        self.assertEqual(k, 5)
        self.assertEqual((h, w), (120, 60))
        ok = seg.valid[::k, ::k]
        err = np.nanmax(np.abs(back[ok] - seg.xyz[::k, ::k][ok]))
        self.assertLess(err, (hi - lo).max() / 65534 + 1e-6)
        self.assertTrue(np.isnan(back[~ok]).all())
        self.assertTrue(flags[20:22, 20:22].all())          # the hole's blocks carry flag 1
        self.assertEqual(int(flags[0, 0]), 0)
        with self.assertRaises(Exception):
            atlas.read_lens(b"\x1f\x8b" + b"0" * 10)


class TestPrizeLists(unittest.TestCase):
    def test_eligible_and_not(self):
        table = {"PHERC1447": ["grand-prize-2027"], "PHERC0175A": ["first-letters-2027"],
                 "PHERCPARIS4": ["title-2026"]}
        self.assertEqual(atlas.lists_for("PHerc1447", None, table), ["grand-prize-2027"])
        self.assertEqual(atlas.lists_for("PHerc0139", None, table), [])
        self.assertEqual(atlas.lists_for("PHercParis4", None, table), ["title-2026"])
        self.assertEqual(atlas.lists_for("PHerc0175", None, table), ["first-letters-2027"])   # part letter missing
        self.assertEqual(atlas.lists_for("PHerc0175A", None, table), ["first-letters-2027"])
        self.assertEqual(atlas.lists_for("PHerc1750", None, table), [])                         # not a prefix match

    def test_the_snapshot_marks_a_known_eligible_scroll(self):
        table = atlas.prize_lists()
        self.assertTrue(atlas.lists_for("PHerc1447", None, table))
        self.assertTrue(atlas.lists_for("PHercParis4", None, table))
        self.assertFalse(atlas.lists_for("PHerc0139", None, table))


class TestSurveyAndBuild(unittest.TestCase):
    def test_survey_finds_meshes_voxel_sizes_and_lists(self):
        rows = atlas.survey(get=FakeBucket(), workers=2)
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, ["PHerc0139/w001/w001-on-20260102150214-2.399um.tifxyz", "PHerc1447/s1/tifxyz"])
        a, b = rows
        self.assertEqual((a["voxel_um"], a["voxel_um_from"], a["volume"]), (2.399, "folder name", "20260102150214"))
        self.assertEqual(a["prize_lists"], [])
        self.assertEqual((b["voxel_um"], b["voxel_um_from"]), (8.64, "the scroll's only volume"))
        self.assertTrue(b["prize_lists"])
        self.assertEqual(a["bytes"], 300)
        self.assertTrue(a["url"].startswith(find.BUCKET + "/PHerc0139/"))

    def test_previous_rows_are_reused_only_when_unchanged(self):
        calls = []

        def fake_measure(row, lens_dir=None, workdir=None):
            calls.append(row["id"])
            out = dict(row, grid_h=1, grid_w=1, area_cm2=1.0, clean=True, error=None, seconds=0.0)
            if lens_dir and not row["prize_lists"]:
                Path(lens_dir).mkdir(parents=True, exist_ok=True)
                (Path(lens_dir) / atlas.lens_name(row)).write_bytes(b"x")
                out["lens"] = atlas.lens_name(row)
            return out

        with tempfile.TemporaryDirectory() as d:
            s = atlas.build(d, get=FakeBucket(), workers=1, lens=True, measure_fn=fake_measure, progress=lambda m: None)
            self.assertEqual(len(calls), 2)
            self.assertEqual(s["meshes"], 2)
            rows = atlas.read_atlas(Path(d) / "atlas.jsonl")
            self.assertTrue(rows[0]["lens"] and not rows[1]["lens"])      # no preview for the prize-list scroll
            self.assertIn("Vesuvius Segment Atlas", (Path(d) / "README.md").read_text())
            calls.clear()
            atlas.build(d, previous=Path(d) / "atlas.jsonl", get=FakeBucket(), workers=1, lens=True,
                        measure_fn=fake_measure, progress=lambda m: None)
            self.assertEqual(calls, [])                                  # nothing changed: nothing measured
            atlas.build(d, previous=Path(d) / "atlas.jsonl", get=FakeBucket(etag="new"), workers=1, lens=True,
                        measure_fn=fake_measure, progress=lambda m: None)
            self.assertEqual(calls, ["PHerc0139/w001/w001-on-20260102150214-2.399um.tifxyz"])   # changed ETag
            calls.clear()
            (Path(d) / "lens" / rows[0]["lens"]).unlink()
            atlas.build(d, previous=Path(d) / "atlas.jsonl", get=FakeBucket(etag="new"), workers=1, lens=True,
                        measure_fn=fake_measure, progress=lambda m: None)
            self.assertEqual(len(calls), 1)                              # its preview went missing: made again

    def test_show_sorts_and_filters(self):
        rows = [{"id": "a", "scroll": "S", "segment": "a", "kind": "mesh", "area_cm2": 1.0},
                {"id": "b", "scroll": "S", "segment": "b", "kind": "mesh", "area_cm2": 3.0},
                {"id": "c", "scroll": "T", "segment": "c", "kind": "intermediate", "area_cm2": 9.0},
                {"id": "d", "scroll": "S", "segment": "d", "kind": "mesh", "area_cm2": None}]
        self.assertEqual([r["id"] for r in atlas.show(rows, "s")], ["b", "a", "d"])
        self.assertEqual([r["id"] for r in atlas.show(rows, None, kind=None, top=1)], ["c"])
        self.assertIn("no meshes match", atlas.format_show([], 4))


if __name__ == "__main__":
    unittest.main()
