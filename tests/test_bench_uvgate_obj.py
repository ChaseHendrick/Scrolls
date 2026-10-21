"""Tiny text-only fixtures for actual OBJ texture-coordinate benchmarks."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
except ImportError:
    np = None

SOURCE = Path(__file__).resolve().parents[1] / "scripts/bench_uvgate.py"
spec = importlib.util.spec_from_file_location("bench_uvgate_obj", SOURCE)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

_VERTICES = "v 1000 2000 5\nv 1001 2000 5\nv 1000 2001 5\n"
_UVS = "vt 100 -300\nvt 140 -300\nvt 100 -250\n"
_FACE = "f 1/1 2/2 3/3\n"
_BASIC = _VERTICES + _UVS + _FACE


@unittest.skipIf(np is None, "needs numpy")
class TestObjUVLoader(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def obj(self, text, name="fixture.obj"):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def assertHashes(self, path, triangles, report, indices):
        self.assertEqual(report["obj"], str(path.resolve()))
        self.assertEqual(report["files"]["obj"], {
            "bytes": len(path.read_bytes()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
        self.assertEqual(report["triangles_sha256"], hashlib.sha256(
            np.asarray(triangles, dtype="<f8").tobytes(order="C")).hexdigest())
        self.assertEqual(report["face_indices_sha256"], hashlib.sha256(
            np.asarray(indices, dtype="<i8").tobytes()).hexdigest())
        self.assertEqual(report["triangles"], len(triangles))
        self.assertEqual(triangles.dtype, np.dtype("float64"))

    def many_faces(self, count=13):
        lines = [_VERTICES]
        for index in range(count):
            x = index * 10
            lines.append(f"vt {x} 0\nvt {x + 2} 0\nvt {x} 3\n")
        for index in range(count):
            vt = index * 3 + 1
            lines.append(f"f 1/{vt} 2/{vt + 1} 3/{vt + 2}\n")
        return self.obj("".join(lines))

    def test_reads_texture_corners_not_vertex_xy_and_preserves_units(self):
        path = self.obj(_VERTICES + _UVS + "f 3/2 1/3 2/1\n")
        triangles, report = bench.load_obj_uv(path)
        np.testing.assert_array_equal(triangles, [[[140, -300], [100, -250], [100, -300]]])
        self.assertEqual(report["vertices"], 3)
        self.assertEqual(report["uv_vertices"], 3)
        self.assertEqual(report["full_triangles"], 1)
        self.assertEqual(report["selection"], "prefix")
        self.assertEqual(report["seed"], 0)
        self.assertHashes(path, triangles, report, [0])

    def test_vertex_positions_do_not_define_uv_coordinates(self):
        path = self.obj(_BASIC)
        first, report1 = bench.load_obj_uv(path)
        path.write_text(_BASIC.replace("v 1000 2000 5", "v -100 9999 12"))
        second, report2 = bench.load_obj_uv(path)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(report1["triangles_sha256"], report2["triangles_sha256"])
        self.assertNotEqual(report1["files"]["obj"]["sha256"],
                            report2["files"]["obj"]["sha256"])

    def test_slash_normal_form_uses_texture_indices(self):
        path = self.obj(_VERTICES + _UVS + "vn 0 0 1\nf 1/3/1 2/1/1 3/2/1\n")
        triangles, report = bench.load_obj_uv(path)
        np.testing.assert_array_equal(triangles, [[[100, -250], [100, -300], [140, -300]]])
        self.assertHashes(path, triangles, report, [0])

    def test_distinct_texture_indices_preserve_seams(self):
        text = (_VERTICES + _UVS + "vt 500 600\nvt 540 600\nvt 500 650\n"
                + _FACE + "f 1/4 3/6 2/5\n")
        triangles, report = bench.load_obj_uv(self.obj(text))
        np.testing.assert_array_equal(triangles, [
            [[100, -300], [140, -300], [100, -250]],
            [[500, 600], [500, 650], [540, 600]],
        ])
        self.assertEqual(report["vertices"], 3)
        self.assertEqual(report["uv_vertices"], 6)
        self.assertEqual(report["full_triangles"], 2)

    def test_negative_indices_are_relative_to_counts_at_the_face(self):
        text = (_VERTICES + _UVS + "vt 777 888\n"
                "f -3/-1 -2/-4 -1/-2\n"
                "v 0 0 0\nvt 999 111\n")
        triangles, report = bench.load_obj_uv(self.obj(text))
        np.testing.assert_array_equal(triangles, [[[777, 888], [100, -300], [100, -250]]])
        self.assertEqual(report["vertices"], 4)
        self.assertEqual(report["uv_vertices"], 5)

    def test_positive_forward_indices_resolve_at_end_of_file(self):
        path = self.obj("f 1/3 2/1 3/2\n" + _VERTICES + _UVS)
        triangles, report = bench.load_obj_uv(path)
        np.testing.assert_array_equal(triangles, [[[100, -250], [100, -300], [140, -300]]])
        self.assertHashes(path, triangles, report, [0])

    def test_comments_groups_and_material_reference_do_not_load_assets(self):
        # The material file does not exist. Loading it would fail this test.
        text = ("# only synthetic text\nmtllib absent-material.mtl\n"
                "o surface\ng patch\nusemtl painted\ns off\n"
                + _VERTICES + "vt 100 -300 0\nvt 140 -300 0.0\nvt 100 -250\n"
                "\tf 1/1 2/2 3/3 # triangle\n")
        triangles, report = bench.load_obj_uv(self.obj(text))
        np.testing.assert_array_equal(triangles, [[[100, -300], [140, -300], [100, -250]]])
        self.assertEqual(set(report["files"]), {"obj"})
        self.assertEqual(list(self.root.iterdir()), [self.root / "fixture.obj"])

    def test_fractional_and_large_uv_units_are_not_normalized(self):
        text = (_VERTICES + "vt -1.25 25000\nvt 0.125 25000\nvt -1.25 25000.5\n" + _FACE)
        triangles, _ = bench.load_obj_uv(self.obj(text))
        np.testing.assert_array_equal(triangles,
                                      [[[-1.25, 25000], [0.125, 25000], [-1.25, 25000.5]]])

    def test_odd_prefix_limit_keeps_original_face_order_and_hash(self):
        path = self.many_faces()
        full, full_report = bench.load_obj_uv(path)
        for count in (1, 3, 5, 13):
            with self.subTest(count=count):
                triangles, report = bench.load_obj_uv(path, count, selection="prefix", seed=41)
                np.testing.assert_array_equal(triangles, full[:count])
                self.assertEqual(report["full_triangles"], 13)
                self.assertEqual(report["selection"], "prefix")
                self.assertEqual(report["seed"], 41)
                self.assertHashes(path, triangles, report, list(range(count)))
        self.assertEqual(full_report["full_triangles"], 13)

    def test_random_selection_is_seeded_unique_and_sorted_by_face(self):
        path = self.many_faces()
        full, _ = bench.load_obj_uv(path)
        first, report1 = bench.load_obj_uv(path, 5, selection="random", seed=17)
        again, report2 = bench.load_obj_uv(path, 5, selection="random", seed=17)
        other, report3 = bench.load_obj_uv(path, 5, selection="random", seed=23)
        np.testing.assert_array_equal(first, again)
        self.assertEqual(report1, report2)
        self.assertNotEqual(report1["face_indices_sha256"], report3["face_indices_sha256"])
        self.assertFalse(np.array_equal(first, other))
        indices = [int(x / 10) for x in first[:, 0, 0]]
        self.assertEqual(indices, sorted(set(indices)))
        np.testing.assert_array_equal(first, full[indices])
        self.assertEqual(report1["selection"], "random")
        self.assertEqual(report1["seed"], 17)
        self.assertHashes(path, first, report1, indices)

    def test_random_all_faces_retains_original_order(self):
        path = self.many_faces()
        expected, _ = bench.load_obj_uv(path)
        for count in (None, 13):
            with self.subTest(count=count):
                got, report = bench.load_obj_uv(path, count, selection="random", seed=29)
                np.testing.assert_array_equal(got, expected)
                self.assertHashes(path, got, report, list(range(13)))

    def test_source_and_triangle_hashes_track_different_changes(self):
        path = self.obj(_BASIC)
        first, report1 = bench.load_obj_uv(path)
        path.write_text(_BASIC + "# source-only change\n")
        second, report2 = bench.load_obj_uv(path)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(report1["triangles_sha256"], report2["triangles_sha256"])
        self.assertNotEqual(report1["files"]["obj"]["sha256"],
                            report2["files"]["obj"]["sha256"])
        path.write_text(_BASIC.replace("vt 140 -300", "vt 141 -300"))
        third, report3 = bench.load_obj_uv(path)
        self.assertNotEqual(report1["triangles_sha256"], report3["triangles_sha256"])
        self.assertHashes(path, third, report3, [0])

    def test_degenerate_and_duplicate_faces_preserve_face_indices(self):
        path = self.obj(_VERTICES + _UVS + "f 1/1 1/1 1/1\n" + _FACE + _FACE)
        triangles, report = bench.load_obj_uv(path)
        np.testing.assert_array_equal(triangles, [
            [[100, -300], [100, -300], [100, -300]],
            [[100, -300], [140, -300], [100, -250]],
            [[100, -300], [140, -300], [100, -250]],
        ])
        self.assertEqual(report["full_triangles"], 3)
        self.assertHashes(path, triangles, report, [0, 1, 2])
        prefix, prefix_report = bench.load_obj_uv(path, 2)
        np.testing.assert_array_equal(prefix, triangles[:2])
        self.assertHashes(path, prefix, prefix_report, [0, 1])

    def test_same_size_source_change_during_loading_is_refused(self):
        path = self.obj(_BASIC)
        original_hash = bench.file_sha256
        calls = 0

        def mutate_after_first_hash(filename):
            nonlocal calls
            digest = original_hash(filename)
            calls += 1
            if calls == 1:
                changed = _BASIC.replace("vt 140 -300", "vt 141 -300")
                self.assertEqual(len(changed.encode()), len(_BASIC.encode()))
                path.write_text(changed)
            return digest

        with patch.object(bench, "file_sha256", side_effect=mutate_after_first_hash):
            with self.assertRaisesRegex(RuntimeError, "changed while loading"):
                bench.load_obj_uv(path)
        self.assertEqual(calls, 2)

    def test_bad_triangle_limits_and_selection_are_refused(self):
        path = self.many_faces(4)
        for count in (0, -1, 5, True, 1.5, "3"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                bench.load_obj_uv(path, count)
        with self.assertRaises(ValueError):
            bench.load_obj_uv(path, 2, selection="arbitrary")

    def test_missing_texture_corner_forms_are_refused(self):
        for face in ("f 1 2 3", "f 1//1 2//1 3//1", "f 1/1 2/2 3", "f 1/ 2/2 3/3"):
            with self.subTest(face=face), self.assertRaises(ValueError):
                bench.load_obj_uv(self.obj(_VERTICES + _UVS + "vn 0 0 1\n" + face + "\n"))

    def test_zero_out_of_range_and_malformed_corner_indices_are_refused(self):
        for corner in ("0/1", "1/0", "4/1", "1/4", "-4/1", "1/-4", "a/1", "1/a"):
            with self.subTest(corner=corner), self.assertRaises(ValueError):
                bench.load_obj_uv(self.obj(_VERTICES + _UVS + f"f {corner} 2/2 3/3\n"))

    def test_nontriangular_faces_are_refused(self):
        for face in ("f 1/1 2/2", "f 1/1 2/2 3/3 1/1"):
            with self.subTest(face=face), self.assertRaises(ValueError):
                bench.load_obj_uv(self.obj(_VERTICES + _UVS + face + "\n"))

    def test_nonfinite_or_unsupported_texture_coordinates_are_refused(self):
        for uv in ("nan 0", "0 inf", "-inf 1", "1", "1 2 0.5"):
            with self.subTest(uv=uv), self.assertRaises(ValueError):
                bench.load_obj_uv(self.obj(_VERTICES + f"vt {uv}\n" + _UVS + _FACE))
        # Invalid unused UV data must not evade validation through sampling.
        with self.assertRaises(ValueError):
            bench.load_obj_uv(self.obj(_BASIC + "vt nan 0\n"), 1)

    def test_empty_missing_uv_and_missing_faces_are_refused(self):
        fixtures = ("", "# empty\n", _VERTICES + "f 1/1 2/2 3/3\n", _VERTICES + _UVS)
        for text in fixtures:
            with self.subTest(text=text), self.assertRaises(ValueError):
                bench.load_obj_uv(self.obj(text))

    def test_invalid_later_face_cannot_hide_behind_a_prefix_limit(self):
        with self.assertRaises(ValueError):
            bench.load_obj_uv(self.obj(_BASIC + "f 1/1 2/2 99/3\n"), 1)

    def test_reference_full_is_refused_before_loading(self):
        from types import SimpleNamespace
        with self.assertRaisesRegex(ValueError, "quadratic reference"):
            bench.benchmark(SimpleNamespace(method="reference", triangles=None))

    def test_benchmark_receipt_hashes_only_public_code(self):
        from types import SimpleNamespace
        square = (_VERTICES + "v 1001 2001 5\n" + "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
                  + "f 1/1 2/2 4/3\nf 1/1 4/3 3/4\n")
        args = SimpleNamespace(obj_uv=self.obj(square), triangles=None, selection="prefix", seed=0,
                               method="grid", abs_eps=1e-12, collect_pairs=True)
        report = bench.benchmark(args)
        self.assertTrue(report["verdict"]["pass"])
        self.assertEqual(report["verdict"]["overlapping_pairs"], [])
        self.assertEqual(sorted(report["implementation_sha256"]), ["kit/uvgate.py", "scripts/bench_uvgate.py"])
        self.assertEqual(report["source"]["triangles"], 2)
        folded = square + "f 1/1 2/2 4/3\n"
        args.obj_uv = self.obj(folded, "folded.obj")
        report = bench.benchmark(args)
        self.assertFalse(report["verdict"]["pass"])
        self.assertEqual([list(pair) for pair in report["verdict"]["overlapping_pairs"]], [[0, 2]])

    def test_command_writes_the_receipt_from_a_fresh_worker(self):
        import json
        out = self.root / "out" / "receipt.json"
        with patch("sys.stdout"):
            code = bench.main(["--obj-uv", str(self.obj(_BASIC)), "--triangles", "all", "--output", str(out)])
        self.assertEqual(code, 0)
        receipt = json.loads(out.read_text())
        self.assertTrue(receipt["verdict"]["pass"])
        self.assertEqual(receipt["source"]["full_triangles"], 1)
        self.assertIn("whole_process_wall_seconds", receipt)


if __name__ == "__main__":
    unittest.main()
