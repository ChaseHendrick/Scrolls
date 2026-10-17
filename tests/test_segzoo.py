"""kit/segzoo.py: the model-zoo registry and the nnU-Net raw dataset to Auto3DSeg datalist converter (stdlib)."""
import argparse
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from kit import segzoo


def raw_dataset(root, cases=("a", "b", "c"), channels=1, labels=None, ending=".nii.gz", num=None):
    root = Path(root)
    (root / "imagesTr").mkdir(parents=True)
    (root / "labelsTr").mkdir()
    for c in cases:
        for ch in range(channels):
            (root / "imagesTr" / f"{c}_{ch:04d}{ending}").write_bytes(b"x")
        (root / "labelsTr" / f"{c}{ending}").write_bytes(b"y")
    meta = {"channel_names": {str(i): "CT" for i in range(channels)},
            "labels": labels or {"background": 0, "surface": 1, "ignore": 2},
            "numTraining": len(cases) if num is None else num, "file_ending": ending, "name": "Dataset999_T"}
    (root / "dataset.json").write_text(json.dumps(meta))
    return root


def run(*argv):
    p = segzoo.build_parser(argparse.ArgumentParser())
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = segzoo.cmd_segzoo(p.parse_args(list(argv)))
    return code, out.getvalue(), err.getvalue()


class RegistryTest(unittest.TestCase):
    def test_every_family_has_every_field_and_a_source(self):
        for f in segzoo.REGISTRY:
            self.assertEqual(set(f), set(segzoo.FIELDS), f["id"])
            self.assertTrue(f["sources"], f["id"])
            for url in f["sources"]:
                self.assertTrue(url.startswith("https://"), url)
            self.assertIsInstance(f["release_ok"], bool)
            self.assertIsInstance(f["gated"], bool)

    def test_ids_are_unique_and_simple(self):
        self.assertEqual(len(segzoo.IDS), len(set(segzoo.IDS)))
        for i in segzoo.IDS:
            self.assertRegex(i, r"^[a-z][a-z0-9]*$")

    def test_every_family_chase_named_is_listed(self):
        for want in ("nnunet", "auto3dseg", "medsam2", "dinov3", "mednext", "swinunetr", "segformer", "ss2d"):
            self.assertIn(want, segzoo.IDS)

    def test_non_permissive_weights_are_never_marked_releasable(self):
        for fid in ("segformer", "dinov3", "medsam2"):
            self.assertFalse(segzoo.family(fid)["release_ok"], fid)
        self.assertTrue(segzoo.family("dinov3")["gated"])

    def test_unknown_family(self):
        with self.assertRaises(KeyError):
            segzoo.family("nope")
        code, _, err = run("show", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown family", err)

    def test_list_and_show(self):
        code, out, _ = run("list")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), len(segzoo.REGISTRY) + 1)
        code, out, _ = run("list", "--json")
        self.assertEqual([f["id"] for f in json.loads(out)], segzoo.IDS)
        code, out, _ = run("show", "mednext")
        self.assertEqual(code, 0)
        self.assertIn("monai==1.6.1", out)
        code, out, _ = run("show", "mednext", "--json")
        self.assertEqual(json.loads(out)["id"], "mednext")
        code, _, err = run("show")
        self.assertEqual(code, 2)
        self.assertIn("needs a family id", err)

    def test_env_never_imports_the_packages(self):
        self.assertIsNone(segzoo.installed("surely_not_a_module_xyz"))
        self.assertIsNotNone(segzoo.installed("json"))
        code, out, _ = run("env", "--json")
        self.assertEqual(code, 0)
        rep = json.loads(out)["families"]
        self.assertEqual(sorted(rep), sorted(segzoo.IDS))
        for r in rep.values():
            self.assertEqual(r["ready"], all(v is not None for v in r["packages"].values()))

    def test_no_long_dashes(self):
        text = Path(segzoo.__file__).read_text()
        self.assertIsNone(re.search("[\u2013\u2014]", text))


class DatalistTest(unittest.TestCase):
    def test_converts_and_splits_by_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = raw_dataset(Path(tmp) / "raw", cases=[f"c{i:03d}" for i in range(20)])
            dl, task, summary = segzoo.build_datalist(raw, folds=5)
            self.assertEqual(summary["cases"], 20)
            self.assertEqual(sum(summary["folds"]), 20)
            first = dl["training"][0]
            self.assertEqual(first["image"], "imagesTr/c000_0000.nii.gz")
            self.assertEqual(first["label"], "labelsTr/c000.nii.gz")
            self.assertEqual(first["fold"], segzoo.fold_of("c000", 5))
            self.assertEqual(task["modality"], "CT")
            self.assertEqual(summary["ignore_label"], 2)
            self.assertTrue(summary["notes"])
            again, _, _ = segzoo.build_datalist(raw, folds=5)
            self.assertEqual(dl, again)

    def test_multichannel_lists_every_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = raw_dataset(Path(tmp) / "raw", channels=2, labels={"background": 0, "ink": 1})
            dl, _, summary = segzoo.build_datalist(raw)
            self.assertEqual(dl["training"][0]["image"], ["imagesTr/a_0000.nii.gz", "imagesTr/a_0001.nii.gz"])
            self.assertIsNone(summary["ignore_label"])
            self.assertEqual(summary["notes"], [])

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = raw_dataset(Path(tmp) / "r1")
            (raw / "labelsTr" / "b.nii.gz").unlink()
            with self.assertRaisesRegex(ValueError, "cases without labels"):
                segzoo.build_datalist(raw)
            raw = raw_dataset(Path(tmp) / "r2", num=7)
            with self.assertRaisesRegex(ValueError, "numTraining 7"):
                segzoo.build_datalist(raw)
            raw = raw_dataset(Path(tmp) / "r3")
            (raw / "imagesTr" / "d.nii.gz").write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "channel suffix"):
                segzoo.build_datalist(raw)
            raw = raw_dataset(Path(tmp) / "r4", channels=2)
            (raw / "imagesTr" / "a_0001.nii.gz").unlink()
            with self.assertRaisesRegex(ValueError, "channels"):
                segzoo.build_datalist(raw)
            with self.assertRaisesRegex(ValueError, "no dataset.json"):
                segzoo.build_datalist(Path(tmp))

    def test_cli_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = raw_dataset(Path(tmp) / "raw")
            out = Path(tmp) / "auto"
            code, text, _ = run("datalist", str(raw), "--out", str(out), "--folds", "3")
            self.assertEqual(code, 0, text)
            self.assertIn("3 cases", text)
            dl = json.loads((out / "datalist.json").read_text())
            self.assertEqual(len(dl["training"]), 3)
            task = (out / "task.yaml").read_text()
            self.assertIn("modality: \"CT\"", task)
            self.assertIn("num_fold: 3", task)
            code, _, err = run("datalist", str(raw))
            self.assertEqual(code, 2)
            self.assertIn("--out", err)
            code, _, err = run("datalist", str(Path(tmp) / "missing"), "--out", str(out))
            self.assertEqual(code, 2)
            self.assertIn("no dataset.json", err)

    def test_invalid_fold_count_preserves_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = raw_dataset(Path(tmp) / "raw")
            out = Path(tmp) / "auto"
            out.mkdir()
            for name in ("datalist.json", "task.yaml"):
                (out / name).write_text("previous result")
            for folds in ("0", "-1", "1"):
                with self.subTest(folds=folds):
                    code, _, err = run("datalist", str(raw), "--out", str(out), "--folds", folds)
                    self.assertEqual(code, 2)
                    self.assertIn("folds must be an integer of at least 2", err)
                    for name in ("datalist.json", "task.yaml"):
                        self.assertEqual((out / name).read_text(), "previous result")
            for folds in (True, 2.5, "5"):
                with self.subTest(folds=folds), self.assertRaisesRegex(ValueError, "folds"):
                    segzoo.build_datalist(raw, folds=folds)

    def test_duplicate_inputs_are_not_silently_replaced(self):
        for folder, name, reason in (("imagesTr", "a_0000.tif", "duplicate image"),
                                     ("labelsTr", "a.tif", "duplicate label")):
            with self.subTest(folder=folder), tempfile.TemporaryDirectory() as tmp:
                raw = raw_dataset(Path(tmp) / "raw")
                meta = json.loads((raw / "dataset.json").read_text())
                del meta["file_ending"]  # Older datasets may omit this; both suffixes are supported.
                (raw / "dataset.json").write_text(json.dumps(meta))
                (raw / folder / name).write_bytes(b"different image")
                out = Path(tmp) / "auto"
                code, _, err = run("datalist", str(raw), "--out", str(out))
                self.assertEqual(code, 2)
                self.assertIn(reason, err)
                self.assertFalse(out.exists())

    def test_label_ending_must_match_the_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = raw_dataset(Path(tmp) / "raw")
            (raw / "labelsTr/a.nii.gz").rename(raw / "labelsTr/a.tif")
            with self.assertRaisesRegex(ValueError, "a.tif does not end with"):
                segzoo.build_datalist(raw)

    def test_malformed_metadata_is_a_cli_error(self):
        changes = ((None, [], "must contain an object"),
                   ("channel_names", {"1": "CT"}, "consecutive integers"),
                   ("channel_names", {"0": "CT", "2": "CT"}, "consecutive integers"),
                   ("labels", [], "labels must be an object"),
                   ("file_ending", [], "unsupported dataset file_ending"),
                   ("file_ending", ".b2nd", "unsupported dataset file_ending"),
                   ("numTraining", True, "numTraining must be a positive integer"),
                   ("numTraining", "3", "numTraining must be a positive integer"))
        for key, value, reason in changes:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as tmp:
                raw = raw_dataset(Path(tmp) / "raw")
                meta = json.loads((raw / "dataset.json").read_text())
                if key is None:
                    meta = value
                else:
                    meta[key] = value
                (raw / "dataset.json").write_text(json.dumps(meta))
                out = Path(tmp) / "auto"
                code, _, err = run("datalist", str(raw), "--out", str(out))
                self.assertEqual(code, 2)
                self.assertIn(reason, err)
                self.assertFalse(out.exists())

    def test_empty_dataset_is_not_a_training_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = raw_dataset(Path(tmp) / "raw", cases=())
            meta = json.loads((raw / "dataset.json").read_text())
            del meta["numTraining"]
            (raw / "dataset.json").write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError, "no training cases"):
                segzoo.build_datalist(raw)


if __name__ == "__main__":
    unittest.main()
