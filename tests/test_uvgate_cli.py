import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kit.uvgate_cli import build_parser, cmd_uvgate


_SHARED_EDGE_CSV = (
    "tri,u,v\n"
    "0,0,0\n"
    "0,2,0\n"
    "0,0,2\n"
    "1,2,0\n"
    "1,2,2\n"
    "1,0,2\n"
)


class UvGateCliTest(unittest.TestCase):
    def _write(self, directory, text):
        path = Path(directory) / "tris.json"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _run(self, path, *extra):
        args = build_parser().parse_args([path, *extra])
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cmd_uvgate(args)
        return code, out.getvalue(), err.getvalue()

    def test_shared_edge_pair_covering_the_source_box_exits_0(self):
        tris = [[[0, 0], [2, 0], [0, 2]], [[2, 0], [2, 2], [0, 2]]]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, json.dumps(tris))
            code, out, _err = self._run(path, "--source-area", "4")
        self.assertEqual(code, 0)
        got = json.loads(out)
        self.assertTrue(got["pass"])
        self.assertIn("overlap", got)
        self.assertIn("coverage", got)

    def test_triangle_inside_another_exits_1(self):
        tris = [[[0, 0], [4, 0], [0, 4]], [[1, 1], [2, 1], [1, 2]]]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, json.dumps(tris))
            code, out, _err = self._run(path, "--source-area", "8")
        self.assertEqual(code, 1)
        got = json.loads(out)
        self.assertFalse(got["pass"])
        self.assertFalse(got["overlap"]["pass"])

    def test_missing_source_area_is_an_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                build_parser().parse_args(["triangles.json"])
        self.assertEqual(caught.exception.code, 2)

    def test_garbage_json_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "{not json")
            code, out, err = self._run(path, "--source-area", "1")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err)

    def test_csv_shared_edge_pair_covering_the_source_area_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tris.csv"
            path.write_text(_SHARED_EDGE_CSV, encoding="utf-8")
            code, out, err = self._run(str(path), "--source-area", "4")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        got = json.loads(out)
        self.assertTrue(got["pass"])

    def test_csv_shared_edge_pair_with_mesh_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tris.csv"
            path.write_text(_SHARED_EDGE_CSV, encoding="utf-8")
            code, out, err = self._run(str(path), "--source-area", "4", "--mesh")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        got = json.loads(out)
        self.assertTrue(got["pass"])
        self.assertTrue(got["mesh"]["pass"])

    def test_disjoint_triangles_with_mesh_exit_1(self):
        tris = [[[0, 0], [1, 0], [0, 1]], [[3, 0], [4, 0], [3, 1]]]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, json.dumps(tris))
            code, out, err = self._run(path, "--source-area", "1", "--mesh")
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        got = json.loads(out)
        self.assertFalse(got["pass"])
        self.assertFalse(got["mesh"]["pass"])


if __name__ == "__main__":
    unittest.main()
