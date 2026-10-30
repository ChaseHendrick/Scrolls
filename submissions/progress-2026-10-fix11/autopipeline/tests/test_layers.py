import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from kit import cli, layers, verify

try:
    import numpy as np
    import tifffile
    import zarr
except ImportError:  # the core kit is standard library only
    np = tifffile = zarr = None


def volume(depth=6, shape=(20, 30)):
    return np.stack([np.full(shape, 10 * (i + 1), dtype=np.uint8) for i in range(depth)])


@unittest.skipIf(zarr is None, "numpy, tifffile and zarr are needed for kit layers")
class LayersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def bare(self, data):
        path = self.root / "bare.zarr"
        zarr.save_array(str(path), data)
        return path

    def group(self, data):
        path = self.root / "ome.zarr"
        g = zarr.open_group(str(path), mode="w")
        g.create_array("0", data=data)
        g.create_array("1", data=data[:, ::2, ::2])
        return path

    def test_bare_array_exports_in_stored_order(self):
        result = layers.export_file(self.bare(volume()), self.root / "out")
        files = sorted((self.root / "out").glob("*.tif"))
        self.assertEqual([f.name for f in files], ["00.tif", "01.tif", "02.tif", "03.tif", "04.tif", "05.tif"])
        self.assertEqual(int(tifffile.imread(files[0])[0, 0]), 10)
        self.assertEqual(int(tifffile.imread(files[-1])[0, 0]), 60)
        self.assertEqual(result["shape"], [6, 20, 30])

    def test_group_uses_full_resolution_level(self):
        layers.export_file(self.group(volume()), self.root / "out")
        self.assertEqual(tifffile.imread(self.root / "out" / "00.tif").shape, (20, 30))

    def test_range_renumbers_from_zero(self):
        layers.export_file(self.bare(volume()), self.root / "out", start=2, count=3)
        files = sorted((self.root / "out").glob("*.tif"))
        self.assertEqual(len(files), 3)
        self.assertEqual(int(tifffile.imread(files[0])[0, 0]), 30)

    def test_crop(self):
        data = volume()
        data[:, 5:10, 7:20] = 255
        src = self.bare(data)
        layers.export_file(src, self.root / "out", crop=(5, 10, 7, 20))
        self.assertTrue((tifffile.imread(self.root / "out" / "00.tif") == 255).all())
        with self.assertRaises(verify.VerifyError):
            layers.export_file(src, self.root / "bad", crop=(0, 21, 0, 5))

    def test_banded_and_per_layer_reads_agree(self):
        rng = np.random.default_rng(0)
        data = rng.integers(0, 256, size=(5, 2100, 40), dtype=np.uint8)   # more rows than one band
        src = self.bare(data)
        layers.export_file(src, self.root / "band", crop=(3, 2050, 1, 39))
        layers.export_file(src, self.root / "single", crop=(3, 2050, 1, 39), max_bytes=0)
        for i in range(5):
            a = tifffile.imread(self.root / "band" / f"{i:02d}.tif")
            np.testing.assert_array_equal(a, data[i, 3:2050, 1:39])
            np.testing.assert_array_equal(a, tifffile.imread(self.root / "single" / f"{i:02d}.tif"))

    def test_non_uint8_volume_is_refused(self):
        with self.assertRaises(verify.VerifyError):
            layers.export_file(self.bare(volume().astype(np.uint16)), self.root / "out")

    def test_out_of_range_is_refused(self):
        with self.assertRaises(verify.VerifyError):
            layers.export_file(self.bare(volume()), self.root / "out", start=4, count=3)

    def test_missing_level_is_refused(self):
        with self.assertRaises(verify.VerifyError):
            layers.export_file(self.group(volume()), self.root / "out", level="5")

    def test_v8in_reads_them_back_in_order(self):
        # Same numeric sort v8in's list_layer_files uses: int(stem).
        layers.export_file(self.bare(volume(depth=12)), self.root / "out")
        stems = sorted((int(p.stem), p) for p in (self.root / "out").glob("*.tif"))
        values = [int(tifffile.imread(p)[0, 0]) for _, p in stems]
        self.assertEqual(values, [10 * (i + 1) for i in range(12)])

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["layers", str(self.bare(volume())), str(self.root / "out"), "--count", "4"])
        self.assertEqual(code, 0)
        self.assertIn("4 layers of [6, 20, 30]", out.getvalue())

    def test_depth_permutation_is_fixed_and_never_trivial(self):
        a = layers.depth_permutation(28, 20261007)
        self.assertEqual(a, layers.depth_permutation(28, 20261007))
        self.assertEqual(sorted(a), list(range(28)))
        for seed in range(50):
            p = layers.depth_permutation(3, seed)
            self.assertNotIn(p, ([0, 1, 2], [2, 1, 0]))
        with self.assertRaises(verify.VerifyError):
            layers.depth_permutation(2, 0)

    def test_shuffled_exports_agree(self):
        src = self.bare(volume())
        result = layers.export_file(src, self.root / "tifs", shuffle_seed=5)
        values = [int(tifffile.imread(self.root / "tifs" / f"{i:02d}.tif")[0, 0]) for i in range(6)]
        self.assertEqual(values, [10 * (j + 1) for j in result["order"]])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["shuffle", str(src), str(self.root / "shuf.zarr"), "--seed", "5", "--crop", "2", "12", "0", "30"])
        self.assertEqual(code, 0)
        z = zarr.open_group(str(self.root / "shuf.zarr"), mode="r")
        self.assertEqual(z["0"].shape, (6, 10, 30))
        self.assertEqual([int(v) for v in z["0"][:, 0, 0]], values)
        self.assertEqual(z.attrs["depth_shuffle"]["order"], result["order"])

    def test_layers_refuses_a_folder_with_earlier_layers(self):
        src = self.bare(volume())
        layers.export_file(src, self.root / "out")
        with self.assertRaises(verify.VerifyError) as ctx:
            layers.export_file(src, self.root / "out", count=3)
        self.assertIn("already holds layer TIFFs", str(ctx.exception))
        self.assertEqual(len(list((self.root / "out").glob("*.tif"))), 6)
        (self.root / "other").mkdir()
        (self.root / "other" / "notes.txt").write_text("kept")
        layers.export_file(src, self.root / "other", count=3)
        self.assertEqual(len(list((self.root / "other").glob("*.tif"))), 3)

    def test_shuffle_refuses_an_existing_out(self):
        src = self.bare(volume())
        dst = self.root / "taken"
        dst.mkdir()
        (dst / "keep.txt").write_text("not ours")
        with self.assertRaises(verify.VerifyError) as ctx:
            layers.shuffle_file(src, dst, 5)
        self.assertIn("already exists", str(ctx.exception))
        self.assertTrue((dst / "keep.txt").is_file())
        with self.assertRaises(verify.VerifyError):
            layers.shuffle_file(src, src, 5)
        self.assertEqual(layers.open_volume(src).shape, (6, 20, 30))


class ShuffleNullWordingTest(unittest.TestCase):
    """The shuffle control is often, not always, a cleaner null than reverse."""

    def test_docstring_says_it_depends_on_the_permutation(self):
        doc = " ".join(layers.__doc__.split())
        self.assertIn("Not always", doc)
        self.assertIn("report the seed", doc)


if __name__ == "__main__":
    unittest.main()
