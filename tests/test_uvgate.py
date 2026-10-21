import unittest

from kit.uvgate import UvGateError, coverage_verdict, load_uv_csv, sheet_verdict, triangle_area, uv_overlap_gate


class UvOverlapGateTest(unittest.TestCase):
    def test_triangle_inside_another_fails(self):
        tris = [((0, 0), (4, 0), (0, 4)), ((1, 1), (2, 1), (1, 2))]
        got = uv_overlap_gate(tris)
        self.assertFalse(got["pass"])
        self.assertEqual(got["pairs"], 1)
        self.assertEqual(got["witness"][0], 0)
        self.assertEqual(got["witness"][1], 1)
        self.assertGreater(got["witness"][2], 0)

    def test_shared_edge_passes(self):
        tris = [((0, 0), (1, 0), (0, 1)), ((1, 0), (1, 1), (0, 1))]
        got = uv_overlap_gate(tris)
        self.assertTrue(got["pass"])
        self.assertEqual(got["pairs"], 0)
        self.assertIsNone(got["witness"])

    def test_inner_third_fails(self):
        tris = [
            ((0, 0), (1, 0), (0, 1)),
            ((1, 0), (1, 1), (0, 1)),
            ((0.2, 0.2), (0.8, 0.2), (0.2, 0.8)),
        ]
        got = uv_overlap_gate(tris)
        self.assertFalse(got["pass"])
        self.assertEqual(got["pairs"], 1)

    def test_degenerate_only_fails(self):
        got = uv_overlap_gate([((0, 0), (1, 0), (2, 0))])
        self.assertFalse(got["pass"])
        self.assertEqual(got["pairs"], 0)
        self.assertEqual(got["degenerate"], 1)

    def test_crossing_pair_fails(self):
        tris = [((0, 0), (2, 0), (1, 2)), ((0, 1), (2, 1), (1, -1))]
        self.assertFalse(uv_overlap_gate(tris)["pass"])


class CoverageVerdictTest(unittest.TestCase):
    def test_full_cover_passes_and_short_cover_fails(self):
        box = [((0, 0), (2, 0), (0, 2)), ((2, 0), (2, 2), (0, 2))]
        full = coverage_verdict(box, source_area=4.0, min_fraction=0.90)
        self.assertTrue(full["pass"])
        self.assertAlmostEqual(full["fraction"], 1.0)
        short = coverage_verdict(box, source_area=12.0, min_fraction=0.90)
        self.assertFalse(short["pass"])
        self.assertAlmostEqual(short["fraction"], 1.0 / 3.0)

    def test_zero_source_area_is_refused(self):
        with self.assertRaises(UvGateError):
            coverage_verdict([((0, 0), (1, 0), (0, 1))], source_area=0)

    def test_published_short_sheet_fails_the_bar(self):
        # 47.4 percent of the source, no overlap. The bar is 0.90.
        tri = [((0, 0), (1, 0), (0, 0.948))]
        got = coverage_verdict(tri, source_area=1.0, min_fraction=0.90)
        self.assertAlmostEqual(got["fraction"], 0.474)
        self.assertFalse(got["pass"])


class SheetVerdictTest(unittest.TestCase):
    def test_clean_cover_passes_and_overlap_blocks_it(self):
        clean = [((0, 0), (2, 0), (0, 2)), ((2, 0), (2, 2), (0, 2))]
        self.assertTrue(sheet_verdict(clean, source_area=4.0)["pass"])
        crossed = clean + [((0.2, 0.2), (1.2, 0.2), (0.2, 1.2))]
        blocked = sheet_verdict(crossed, source_area=4.0)
        self.assertFalse(blocked["pass"])
        self.assertFalse(blocked["overlap"]["pass"])


class LoadUvCsvTest(unittest.TestCase):
    def test_shared_edge_sheet_loads_and_passes(self):
        text = (
            "tri,u,v\n"
            "a,0,0\n"
            "a,1,0\n"
            "a,0,1\n"
            "b,1,0\n"
            "b,1,1\n"
            "b,0,1\n"
        )
        tris = load_uv_csv(text)
        self.assertEqual(
            tris,
            [
                ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
                ((1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            ],
        )
        summed = sum(triangle_area(tri) for tri in tris)
        self.assertTrue(sheet_verdict(tris, source_area=summed)["pass"])

    def test_duplicate_third_point_raises(self):
        text = (
            "tri,u,v\n"
            "a,0,0\n"
            "a,1,0\n"
            "a,0,1\n"
            "a,0,1\n"
        )
        with self.assertRaises(UvGateError):
            load_uv_csv(text)

    def test_bad_header_raises(self):
        with self.assertRaises(UvGateError):
            load_uv_csv("id,u,v\na,0,0\na,1,0\na,0,1\n")


if __name__ == "__main__":
    unittest.main()
