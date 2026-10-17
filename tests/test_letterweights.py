"""Released reader selection preserves task scope, explicit choices and hash pins."""

import json
from pathlib import Path
import tempfile
import unittest

from kit import letterweights as W


class SelectionTests(unittest.TestCase):
    def test_given_lines_choose_noncommercial_ink_line_checkpoint(self):
        self.assertEqual(W.select_weights(lines_given=True), "letters-v2-real")
        info = W.profile_info(lines_given=True)
        self.assertEqual((info["name"], info["license"]), ("ink-lines", "CC-BY-NC-4.0"))
        self.assertIn("line positions", info["scope"])

    def test_automatic_page_read_keeps_permissive_weights(self):
        self.assertEqual(W.select_weights(), "letters-v2-ccby")
        info = W.profile_info()
        self.assertEqual((info["name"], info["license"]), ("permissive", "CC-BY-4.0"))
        self.assertIn("unresolved", info["scope"])

    def test_explicit_profile_overrides_task_default(self):
        self.assertEqual(W.select_weights(profile="permissive", lines_given=True), "letters-v2-ccby")
        self.assertEqual(W.select_weights(profile="ink-lines", lines_given=False), "letters-v2-real")

    def test_explicit_model_and_local_path_are_never_substituted(self):
        path = Path("my-reader.npz")
        for chosen in ("letters-v2-real", "letters-v2-ccby", path):
            for lines_given in (False, True):
                with self.subTest(chosen=chosen, lines_given=lines_given):
                    self.assertEqual(W.select_weights(chosen, lines_given=lines_given), chosen)
        self.assertIs(W.select_weights(path), path)

    def test_ambiguous_selection_is_refused(self):
        with self.assertRaisesRegex(ValueError, "choose --weights or --weight-profile"):
            W.select_weights("my-reader.npz", "ink-lines")

    def test_unknown_profile_does_not_fall_back_to_another_model(self):
        for profile in ("best", "", "ink-lines-typo"):
            with self.subTest(profile=profile):
                with self.assertRaisesRegex(ValueError, "unknown weight profile"):
                    W.select_weights(profile=profile)

    def test_profile_cannot_point_at_unreleased_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({"profiles": {"ink-lines": {"weights": "not-released"}},
                                        "models": {}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unregistered weights"):
                W.select_weights(profile="ink-lines", registry=path)

    def test_choices_keep_existing_release_files_hashes_and_urls(self):
        models = json.loads(W.REGISTRY.read_text(encoding="utf-8"))["models"]
        pins = {
            "letters-v2-real": ("letters-v2-real-step030000.npz",
                                "44946dadf0195ddb565f097acec0dd1d777af9b6c66d83995c1f4497aa587477"),
            "letters-v2-ccby": ("letters-v2-ccby-step026000.npz",
                                "b14988852fc721cce71e80a66db0a8ea99a1de914ef2b724ecc6e711baa9ed8c"),
        }
        for profile in W.PROFILE_NAMES:
            name = W.select_weights(profile=profile)
            with self.subTest(profile=profile):
                filename, sha = pins[name]
                self.assertEqual((models[name]["file"], models[name]["sha256"]), (filename, sha))
                self.assertEqual(models[name]["url"],
                                 f"https://github.com/ChaseHendrick/Scrolls/releases/download/{name}/{filename}")


if __name__ == "__main__":
    unittest.main()
