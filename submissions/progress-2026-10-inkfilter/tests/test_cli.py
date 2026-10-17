import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scrolls_inkfilter import cli, core
from test_core import synthetic


class LocalCommandTest(unittest.TestCase):
    def call(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(args), 0)
        return json.loads(output.getvalue())

    def rejected(self, args, message):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as exc:
            cli.main(args)
        self.assertEqual(exc.exception.code, 2)
        self.assertIn(message, error.getvalue())

    def test_npy_crop_writes_matching_map_control_and_complete_record(self):
        v, _ = synthetic()
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.npy", Path(d)/"out"/"map.npy"
            np.save(source, v)
            result = self.call([str(source), "--output", str(output), "--crop", "8", "88", "9", "89"])
            crop = v[:, 8:88, 9:89]
            np.testing.assert_array_equal(np.load(output), core.ink_map(crop))
            np.testing.assert_array_equal(np.load(result["control"]), core.ink_map(crop, reverse=True))
            self.assertEqual(json.loads(Path(result["record"]).read_text()), result)
            self.assertEqual(result["note"], "filter output, not a reading")
            self.assertEqual(result["crop"], [8, 88, 9, 89])
            self.rejected([str(source), "--output", str(output)], "already exists")

    def test_tiff_io(self):
        import tifffile
        v, _ = synthetic(1)
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.tif", Path(d)/"map.tif"
            tifffile.imwrite(source, v, photometric="minisblack")
            result = self.call([str(source), "--output", str(output)])
            np.testing.assert_array_equal(tifffile.imread(output), core.ink_map(v))
            self.assertEqual(tifffile.imread(result["control"]).shape, v.shape[1:])

    def test_zarr_group_explicit_level_matches_bare_array(self):
        import zarr
        v, _ = synthetic(2)
        with tempfile.TemporaryDirectory() as d:
            source = Path(d)/"input.zarr"
            group = zarr.open_group(str(source), mode="w")
            group.create_array("1", data=v, chunks=(40, 32, 32))
            result = self.call([str(source), "--level", "1", "--output", str(Path(d)/"map.npy")])
            np.testing.assert_array_equal(np.load(result["output"]), core.ink_map(v))
            bare, _, _ = cli.read_window(source/"1", 0)
            np.testing.assert_array_equal(bare, v)

    def test_rejects_bad_crop_before_writing(self):
        v, _ = synthetic()
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.npy", Path(d)/"map.npy"
            np.save(source, v)
            self.rejected([str(source), "--output", str(output), "--crop", "0", "100", "0", "96"], "crop")
            self.assertFalse(output.exists())

    def test_rejects_unsafe_numeric_input(self):
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.npy", Path(d)/"map.npy"
            for bad in (np.ones((4, 4, 4), dtype=np.int32),
                        np.full((4, 4, 4), np.nan), np.full((4, 4, 4), 255.0)):
                np.save(source, bad)
                self.rejected([str(source), "--output", str(output)], "input must")
                self.assertFalse(output.exists())

    def test_rejects_url_and_prevents_input_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d)/"map.npy"
            self.rejected(["https://example.invalid/input.zarr", "--output", str(output)], "local")
            v, _ = synthetic()
            np.save(output, v)
            self.rejected([str(output), "--output", str(output), "--overwrite"], "replace the input")
            np.testing.assert_array_equal(np.load(output), v)

    def test_rejects_outputs_inside_input_even_through_symlinks(self):
        import zarr
        v, _ = synthetic()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "input.zarr"
            group = zarr.open_group(str(source), mode="w")
            group.create_array("0", data=v, chunks=(40, 32, 32))
            before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
            alias = root / "alias"
            alias.symlink_to(source, target_is_directory=True)
            record_output = root / "record-link.npy"
            record_output.with_suffix(".json").symlink_to(source / "zarr.json")
            control_output = root / "control-link.npy"
            (root / "control-link_reverse.npy").symlink_to(source / "unexpected.npy")
            for output in (source / "map.npy", alias / "map.npy", record_output, control_output):
                with self.subTest(output=output):
                    self.rejected([str(source), "--output", str(output), "--overwrite"], "inside the input directory")
                    self.assertFalse(output.exists())
                    after = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
                    self.assertEqual(after, before)

    def test_rejects_zarr_level_subgroup_before_writing(self):
        import zarr
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.zarr", Path(d)/"map.npy"
            zarr.open_group(str(source), mode="w").create_group("0")
            self.rejected([str(source), "--output", str(output)], "level must be an array, not a group")
            self.assertFalse(output.exists())

    def test_rejects_input_hardlink_even_with_overwrite(self):
        v, _ = synthetic()
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.npy", Path(d)/"map.npy"
            np.save(source, v)
            os.link(source, output)
            before = source.read_bytes()
            self.rejected([str(source), "--output", str(output), "--overwrite"], "replace the input")
            self.assertEqual(source.read_bytes(), before)

    def test_rejects_external_hardlink_to_zarr_member(self):
        import zarr
        v, _ = synthetic()
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.zarr", Path(d)/"map.npy"
            group = zarr.open_group(str(source), mode="w")
            group.create_array("0", data=v, chunks=(40, 32, 32))
            before = (source/"zarr.json").read_bytes()
            os.link(source/"zarr.json", output)
            self.rejected([str(source), "--output", str(output), "--overwrite"], "multiply linked files")
            self.assertEqual((source/"zarr.json").read_bytes(), before)

    def test_rejects_dangling_control_alias_to_forward(self):
        v, _ = synthetic()
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"input.npy", Path(d)/"map.npy"
            np.save(source, v)
            (Path(d)/"map_reverse.npy").symlink_to(output)
            self.rejected([str(source), "--output", str(output)], "different files")
            self.assertFalse(output.exists())

    def test_uppercase_npy_uses_exact_output_path_and_preserves_input(self):
        v, _ = synthetic()
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d)/"map.NPY.npy", Path(d)/"map.NPY"
            np.save(source, v)
            before = source.read_bytes()
            result = self.call([str(source), "--output", str(output)])
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(result["output"], str(output))
            self.assertTrue(output.exists())
            self.assertEqual(Path(result["control"]).name, "map_reverse.NPY")
            self.assertTrue(Path(result["control"]).exists())
            np.testing.assert_array_equal(np.load(output), core.ink_map(v))
            self.assertFalse((Path(d)/"map_reverse.NPY.npy").exists())


if __name__ == "__main__":
    unittest.main()
