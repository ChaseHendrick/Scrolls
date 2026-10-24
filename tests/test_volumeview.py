"""Synthetic coordinate and refusal checks; never read remote arrays."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from kit import cli, volumeview as V


def manifest():
    return json.loads((Path(V.__file__).parent / "data" / "volumeview-example.json").read_text())


class TestState(unittest.TestCase):
    def test_downsampled_anisotropic_coordinates_align(self):
        m = manifest()
        state = V.build_state(m)
        self.assertEqual(state["layout"], "4panel")
        self.assertEqual(list(state["dimensions"]), ["x", "y", "z"])
        # One physical point occupies different voxels in the two arrays.
        coords = ([12, 16, 20], [6, 8, 10])
        mapped = []
        for layer, coord in zip(state["layers"], coords):
            t = layer["source"]["transform"]
            self.assertEqual(list(t["inputDimensions"]), ["x", "y", "z"])
            self.assertEqual(list(t["outputDimensions"]), ["x", "y", "z"])
            mapped.append([v * t["inputDimensions"][a][0] / t["outputDimensions"][a][0]
                           for a, v in zip(("z", "y", "x"), coord)])
        self.assertEqual(mapped[0], mapped[1])
        self.assertEqual(mapped[0], [24, 48, 80])
        self.assertEqual(state["layers"][0]["source"]["transform"]["inputDimensions"]["x"], [4e-6, "m"])
        self.assertEqual(state["layers"][1]["blend"], "additive")

    def test_link_roundtrip_and_no_mutation(self):
        m = manifest()
        original = copy.deepcopy(m)
        m["layers"][0]["name"] = 'CT α #?"</script>'
        url = V.viewer_link(m)
        self.assertEqual(urlsplit(url).netloc, "neuroglancer-demo.appspot.com")
        self.assertEqual(json.loads(unquote(url.split("#!", 1)[1])), V.build_state(m))
        self.assertNotIn("</script>", url)
        V.build_state(original)
        self.assertEqual(original, manifest())

    def test_single_ct(self):
        m = manifest()
        m["layers"].pop()
        self.assertEqual(len(V.build_state(m)["layers"]), 1)

    def test_mismatch_missing_axes_units_origin_and_shape_refused(self):
        cases = [
            ("frame", "another-scan"), ("shape_zyx", [20, 30, 41]),
            ("shape_zyx", [20.0, 30, 40]), ("origin_um_zyx", [1, 0, 0]),
            ("origin_um_zyx", [False, 0, 0]), ("voxel_size_um_zyx", [2, 3, 4]),
            ("role", "ct"), ("name", "Synthetic CT (example path only)"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                m = manifest(); m["layers"][1][key] = value
                with self.assertRaises(V.VolumeViewError): V.build_state(m)
        for key, value in [("axes", ["x", "y", "z"]), ("axes", ["z", "y", "y"]),
                           ("scale", [2, 2, 2]), ("scale", [True, 1, 1]),
                           ("units", ["um", "um", "um"]), ("origin", [1, 0, 0])]:
            with self.subTest(grid_key=key, value=value):
                m = manifest(); m["layers"][1]["source_grid"][key] = value
                with self.assertRaises(V.VolumeViewError): V.build_state(m)
        m = manifest(); del m["layers"][0]["source_grid"]
        with self.assertRaises(V.VolumeViewError): V.build_state(m)

    def test_nonfinite_overflow_underflow_and_boolean_refused(self):
        for value in (float("nan"), float("inf"), -1, 0, True, 10**400, 5e-324, "2"):
            with self.subTest(value=str(value)):
                m = manifest(); m["layers"][0]["voxel_size_um_zyx"][0] = value
                with self.assertRaises(V.VolumeViewError): V.build_state(m)

    def test_unapproved_urls_and_components_refused(self):
        host = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
        urls = ["http://localhost/a.zarr", "https://evil.example/a.zarr", "file:///tmp/a.zarr",
                host + "/a.zarr?token=secret", host + "/a.zarr#part", host + "/../a.zarr",
                host + "/a%2Fb.zarr", host + "/a.zarr/0", host + "//a.zarr",
                host + "/a\\b.zarr", host + "/a\nb.zarr", host.replace("https://", "https://u:p@") + "/a.zarr",
                host + ":443/a.zarr", "s3://vesuvius-challenge/private.zarr"]
        for url in urls:
            with self.subTest(url=url):
                m = manifest(); m["layers"][0]["source"] = url
                with self.assertRaises(V.VolumeViewError): V.build_state(m)

    def test_no_network_or_browser_calls(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
             patch("webbrowser.open", side_effect=AssertionError("browser")), \
             patch("socket.socket", side_effect=AssertionError("socket")):
            self.assertTrue(V.viewer_link(manifest()).startswith(V.VIEWER))


class TestCLI(unittest.TestCase):
    def run_cli(self, args, *, workbench=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["volumeview", *args]) if workbench else V.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_receipt_digest_and_workbench_entry(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "input.json"; raw = json.dumps(manifest()).encode(); p.write_bytes(raw)
            code, out, err = self.run_cli([str(p), "--format", "receipt"], workbench=True)
            self.assertEqual((code, err), (0, ""))
            receipt = json.loads(out)
            self.assertEqual(receipt["manifest_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertIn("not verified", receipt["validation"])
            self.assertEqual(receipt["state"], V.build_state(manifest()))

    def test_no_overwrite_including_input_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "input.json"; raw = json.dumps(manifest()); p.write_text(raw)
            alias = Path(td) / "alias.json"; alias.symlink_to(p)
            hard = Path(td) / "hard.json"; os.link(p, hard)
            for out in (p, alias, hard):
                self.assertEqual(self.run_cli([str(p), "--out", str(out)])[0], 2)
                self.assertEqual(p.read_text(), raw)
            dest = Path(td) / "state.json"
            self.assertEqual(self.run_cli([str(p), "--format", "state", "--out", str(dest)])[0], 0)
            self.assertEqual(json.loads(dest.read_text()), V.build_state(manifest()))
            self.assertEqual(self.run_cli([str(p), "--out", str(dest)])[0], 2)

    def test_malformed_or_oversize_creates_no_output(self):
        bad = [b'{"schema":1,"schema":2}', b'NaN', b'{', b'\xff', b'[' * 2000,
               b' ' * (V.MAX_MANIFEST_BYTES + 1), b'{"schema":true,"layers":[]}']
        with tempfile.TemporaryDirectory() as td:
            p, dest = Path(td) / "input.json", Path(td) / "out.json"
            for raw in bad:
                with self.subTest(raw=raw[:30]):
                    p.write_bytes(raw)
                    self.assertEqual(self.run_cli([str(p), "--out", str(dest)])[0], 2)
                    self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
