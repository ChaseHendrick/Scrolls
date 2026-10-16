"""Tests for scripts/heldout/hecate_split.py, the port of the published Hecate trainer's split rule
(villa distilled_3d_ink 5ff00ca0, data/multiteacher.py). Synthetic masks only; no label file is read."""
import sys
import unittest
from pathlib import Path

try:
    import numpy as np
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "heldout"))
    import hecate_split as H
except ImportError:  # pragma: no cover
    np = None


def brute_dilate(mask, size):
    """scipy.ndimage.maximum_filter(mode="constant", cval=0) written out by hand."""
    r = size // 2
    h, w = mask.shape
    out = np.zeros_like(mask)
    for y in range(h):
        for x in range(w):
            out[y, x] = mask[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].any()
    return out


@unittest.skipIf(np is None, "needs numpy")
class HecateSplitTest(unittest.TestCase):
    def test_box_any_is_a_constant_mode_max_filter(self):
        rng = np.random.default_rng(0)
        for shape, size in (((9, 13), 3), ((20, 7), 5), ((15, 15), 33)):
            m = rng.random(shape) < 0.08
            np.testing.assert_array_equal(H.box_any(m, size), brute_dilate(m, size))

    def test_max_pool_keeps_a_single_marked_pixel(self):
        m = np.zeros((40, 50), np.uint8)
        m[33, 49] = 1
        pooled = H.max_pool_mask(m)
        self.assertEqual(pooled.shape, (3, 4))
        self.assertTrue(pooled[2, 3])
        self.assertEqual(int(pooled.sum()), 1)

    def test_validation_mask_over_all_supervision_leaves_no_training_patch(self):
        # PHerc0841's case: every supervised pixel is inside the validation mask.
        sup = np.zeros((2048, 2048), np.uint8)
        sup[200:1800, 300:1700] = 255
        val = np.zeros_like(sup)
        val[100:1900, 200:1900] = 255
        ink = np.zeros_like(sup)
        ink[500:600, 500:900] = 255
        r = H.split(sup, val, ink, identity="841/x")
        self.assertEqual(r["train_patches"], 0)
        self.assertTrue(r["validation_only"])
        self.assertGreater(r["val_patches"], 0)
        self.assertEqual(r["share_supervised_in_validation"], 1.0)
        self.assertEqual(r["supervised_px_in_training_patches"], 0)
        self.assertEqual(r["supervised_ink_px_in_training_patches"], 0)

    def test_small_validation_mask_keeps_training_patches_outside_the_guard(self):
        # This check can fail: a training-segment layout must give training patches, all clear of the guard.
        sup = np.zeros((2048, 4096), np.uint8)
        sup[:, :] = 1
        val = np.zeros_like(sup)
        val[0:512, 0:512] = 1
        r = H.split(sup, val, None, identity="0139/x")
        self.assertFalse(r["validation_only"])
        self.assertGreater(r["train_patches"], 0)
        self.assertLess(r["share_supervised_in_training_patches"], 1.0)
        support, heldout = H.max_pool_mask(sup), H.max_pool_mask(val)
        train, _ = H.patch_coordinates(support | heldout, heldout, sup.shape)
        for y, x in train:  # every footprint at least 256 px from the validation square
            self.assertTrue(y >= 512 + 256 or x >= 512 + 256, (y, x))

    def test_generated_holdout_is_seeded_and_ten_percent_of_blocks(self):
        sup = np.ones((4096, 5120), np.uint8)  # 4 x 5 blocks of 1024 px
        support = H.max_pool_mask(sup)
        a, blocks_a = H.spatial_holdout(support, 27, "0139/w043_2026011217")
        b, blocks_b = H.spatial_holdout(support, 27, "0139/w043_2026011217")
        c, blocks_c = H.spatial_holdout(support, 27, "0139/another")
        self.assertEqual(blocks_a, blocks_b)
        self.assertEqual(len(blocks_a), 2)  # round(20 * 0.1)
        self.assertEqual(int(a.sum()), 2 * 64 * 64)
        self.assertEqual(len(blocks_c), 2)
        r = H.split(sup, None, None, identity="0139/w043_2026011217")
        self.assertEqual(r["holdout"], "generated blocks (no validation mask)")
        self.assertEqual(r["generated_blocks"], 2)
        self.assertGreater(r["train_patches"], 0)

    def test_an_empty_validation_mask_falls_back_to_generated_blocks(self):
        sup = np.ones((4096, 4096), np.uint8)
        r = H.split(sup, np.zeros_like(sup), None, identity="814/x")
        self.assertEqual(r["holdout"], "generated blocks (no validation mask)")
        self.assertNotIn("share_supervised_in_validation", r)

    # Hand-counted cases for the three rules that set the M1 percentages. Grid: 16 px cells, so a
    # 256 px patch is 16 x 16 cells; training scan every 8 cells, validation scan every 16.

    def test_training_patch_needs_five_percent_of_its_cells_supervised(self):
        # One patch position on a 256 px canvas; 5 % of 256 cells is 12.8, so 12 cells fail and 13 pass.
        held = np.zeros((16, 16), bool)
        for n, want in ((12, 0), (13, 1)):
            support = np.zeros((16, 16), bool)
            support.flat[:n] = True
            train, _ = H.patch_coordinates(support, held, (256, 256))
            self.assertEqual(len(train), want, n)

    def test_training_scan_steps_half_a_patch(self):
        # 512 px canvas, all supervised, no holdout: rows and columns 0, 128, 256 px, so 9 patches.
        support = np.ones((32, 32), bool)
        train, val = H.patch_coordinates(support, np.zeros_like(support), (512, 512))
        self.assertEqual(sorted(map(tuple, train.tolist())),
                         [(y, x) for y in (0, 128, 256) for x in (0, 128, 256)])
        self.assertEqual(len(val), 0)

    def test_validation_patch_needs_held_out_and_supervised_cells_and_steps_a_whole_patch(self):
        # Supervision in the top half only. Holdout cells in window (0, 0), supervised, and in
        # window (16, 16), unsupervised. Only window (0, 0) qualifies; a half-patch validation stride,
        # or a rule using support or holdout alone, would add windows.
        support = np.zeros((32, 32), bool)
        support[:16, :] = True
        held = np.zeros_like(support)
        held[10:12, 10:12] = True
        held[20:22, 20:22] = True
        _, val = H.patch_coordinates(support, held, (512, 512))
        self.assertEqual(val.tolist(), [[0, 0]])

    def test_split_shares_on_a_hand_counted_segment(self):
        # 512 x 2048 px, all supervised; validation mask on the first 256 px columns (cells 0-15).
        # Guard 16 cells, so training windows start at column cell 32 or later: 11 columns
        # (32, 40, ..., 112) x 3 rows (0, 8, 16) = 33 patches covering cells 32-127 of 128: 75 %.
        # Validation windows: rows 0 and 16 at column 0 only: 2.
        sup = np.ones((512, 2048), np.uint8)
        val = np.zeros_like(sup)
        val[:, :256] = 1
        r = H.split(sup, val, None, identity="814/x")
        self.assertEqual(r["train_patches"], 33)
        self.assertEqual(r["val_patches"], 2)
        self.assertEqual(r["share_supervised_in_training_patches"], 0.75)
        self.assertEqual(r["share_supervised_in_validation"], 0.125)

    def test_stable_seed_matches_the_trainers_formula(self):
        import hashlib
        want = int.from_bytes(hashlib.sha256(b"27:841/w00:3:4").digest()[:8], "big")
        self.assertEqual(H.stable_seed(27, "841/w00", np.int64(3), np.int64(4)), want)


class HeldOutEntriesTest(unittest.TestCase):
    """`held_out` in docs/results.json says, per labelled segment, which released reader trained on it."""

    def setUp(self):
        import json
        root = Path(__file__).resolve().parents[1]
        self.root = root
        self.held = json.loads((root / "docs" / "results.json").read_text(encoding="utf-8"))["held_out"]

    def test_every_entry_cites_a_log_that_exists(self):
        import re
        for key, text in self.held.items():
            logs = re.findall(r"docs/logs/[\w.-]+\.md", text)
            self.assertTrue(logs, f"held_out.{key} cites no log")
            for log in logs:
                self.assertTrue((self.root / log.rstrip(".")).exists(), f"held_out.{key} cites missing {log}")

    def test_pherc0841_names_both_hecate_channels(self):
        text = self.held["PHerc0841"]
        self.assertIn("Not held out from Hecate", text)
        self.assertIn("validation-only", text)      # its own published split
        self.assertIn("ink_canonical_2um", text)    # its starting weights

    def test_w043_is_not_called_held_out_from_its_trainers(self):
        text = self.held["w043"]
        self.assertTrue(text.split(":", 1)[1].lstrip().startswith("not held out from ink_9um"), text)
        self.assertIn("Hecate", text)

    def test_kit_caveats_say_not_held_out_from_hecate(self):
        # kit auc's and kit ensemble's docstrings and kit plan's printed First Letters plan carry the
        # Hecate caveat; since 2026-10-16 it reads "not held out", no longer "possibly" or "may not be".
        import ast
        texts = {}
        for name in ("auc", "ensemble", "plan"):
            tree = ast.parse((self.root / "kit" / f"{name}.py").read_text(encoding="utf-8"))
            texts[name] = ast.get_docstring(tree)
            for node in tree.body:
                if name == "plan" and isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "HELD_OUT":
                    texts[name] = node.value.value
        for name, text in texts.items():
            with self.subTest(name):
                flat = " ".join(text.replace("#", " ").split())
                self.assertRegex(flat, r"not (?:held out )?(?:for|from) Hecate")
                self.assertNotRegex(flat, r"possibly (?:not )?(?:for |from )?Hecate|may not be held out")


if __name__ == "__main__":
    unittest.main()
