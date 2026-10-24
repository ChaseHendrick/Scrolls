"""The Space's download cache and checkpoint load (space/app.py): a private cache, villa last on sys.path, and the
checkpoint loaded weights-only from the bytes whose SHA-256 was checked. No torch, villa or network: stand-ins of
torch and villa's vesuvius are written to a temporary folder."""
import hashlib
import importlib.util
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from optional_deps import without_repo_spaces

ROOT = Path(__file__).resolve().parent.parent
# the release's space/, or in the private repository the Space's source the release builder copies
SPACE = next((p for p in (ROOT / "space", ROOT / "docs" / "submissions" / "progress-2026-10" / "autopipeline" / "space")
              if (p / "inkspace.py").is_file()), ROOT / "space")
COMMIT_FILE = "COMMIT"

TORCH = """
    LOADS = []
    __version__ = "stub"
    class cuda:
        @staticmethod
        def is_available():
            return False
    def load(f, map_location=None, weights_only=False):
        data = f.read() if hasattr(f, "read") else open(f, "rb").read()
        LOADS.append({"type": type(f).__name__, "bytes": data, "weights_only": weights_only})
        if data.startswith(b"PICKLE-CODE") and not weights_only:
            open(PWNED, "w").write("ran")
        return {"state": data}
    """

VILLA = {
    "vesuvius/__init__.py": "",
    "vesuvius/ink_detection/__init__.py": "",
    "vesuvius/ink_detection/models/__init__.py": "",
    "vesuvius/ink_detection/models/checkpoint.py": """
        import torch
        def load_checkpoint(path, *args, **kwargs):     # villa's: a full unpickle of the file at path
            with open(path, "rb") as f:
                return torch.load(f, map_location="cpu", weights_only=False)
        """,
    "vesuvius/ink_detection/inference/__init__.py": "",
    "vesuvius/ink_detection/inference/infer.py": """
        import types
        from vesuvius.ink_detection.models.checkpoint import load_checkpoint
        def configure_model(args):
            ck = load_checkpoint(args.checkpoint)
            model = types.SimpleNamespace(eval=lambda: "model", loaded=ck)
            return types.SimpleNamespace(patch_size=128, input_depth=17, model=model, loaded=ck,
                                         preprocessing="stub", amp_dtype="none")
        def resolve_patch_stride(patch_size, overlap, explicit_stride):
            return 64
        """,
}


def load_app():
    spec = importlib.util.spec_from_file_location("autopipeline_space_app_cache_test", SPACE / "app.py")
    app = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, without_repo_spaces()):
        spec.loader.exec_module(app)
    return app


@unittest.skipUnless((SPACE / "app.py").is_file() and importlib.util.find_spec("numpy"), "needs the Space folder")
class SpaceCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.saved_path, self.saved_mods = list(sys.path), dict(sys.modules)
        stubs = self.d / "stubs" / "torch"
        stubs.mkdir(parents=True)
        (stubs / "__init__.py").write_text(f"PWNED = {str(self.d / 'pwned')!r}\n" + textwrap.dedent(TORCH))
        sys.path.insert(0, str(self.d / "stubs"))
        for name in [m for m in sys.modules if m == "torch" or m.startswith(("torch.", "vesuvius"))]:
            del sys.modules[name]
        self.env = mock.patch.dict(os.environ, {"INK_CACHE": "", "VILLA_SRC": "", "INK_CHECKPOINT": ""})
        self.env.start()
        self.app = load_app()
        self.rows = mock.patch.object(self.app.inkspace, "readers_row", lambda *a: None)   # the stand-in's hash
        self.rows.start()

    def tearDown(self):
        self.rows.stop()
        self.env.stop()
        sys.path[:] = self.saved_path
        for name in [m for m in sys.modules if m not in self.saved_mods]:
            del sys.modules[name]
        os.chmod(self.d, 0o700)
        self.tmp.cleanup()

    def cache(self, mode=0o700):
        cache = self.d / "cache"
        cache.mkdir(mode=mode, exist_ok=True)
        os.chmod(cache, mode)
        dest = cache / f"villa-{self.app.VILLA_COMMIT[:12]}"
        for rel, text in VILLA.items():
            path = dest / "vesuvius" / "src" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text))
        (dest / COMMIT_FILE).write_text(self.app.VILLA_COMMIT + "\n")
        return cache

    def checkpoint(self, cache, body):
        path = cache / "ink_9um" / self.app.CHECKPOINT["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        self.app.CHECKPOINT["sha256"] = hashlib.sha256(body).hexdigest()
        return path

    def test_default_cache_is_per_user_not_tmp(self):
        self.assertEqual(self.app.CACHE.name, "autopipeline-ink")
        self.assertNotEqual(self.app.CACHE.parent, Path(tempfile.gettempdir()))
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.d / "xdg")}):
            self.assertEqual(load_app().CACHE, self.d / "xdg" / "autopipeline-ink")

    def test_new_cache_is_private(self):
        made = self.app.private_cache(self.d / "new" / "cache")
        self.assertEqual(os.stat(made).st_mode & 0o777, 0o700)

    def test_a_cache_others_can_write_is_refused(self):
        for mode in (0o777, 0o775, 0o1777):
            cache = self.cache(mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(RuntimeError) as err:
                self.app.ensure_villa(cache)
            self.assertIn("writable by others", str(err.exception))
        link = self.d / "link"
        link.symlink_to(self.cache(0o700))
        with self.assertRaises(RuntimeError):
            self.app.private_cache(link)

    @unittest.skipUnless(hasattr(os, "getuid") and os.getuid() == 0, "needs root to make a folder of another user")
    def test_a_cache_of_another_user_is_refused(self):
        cache = self.cache(0o700)
        os.chown(cache, 4321, 4321)
        with self.assertRaises(RuntimeError) as err:
            self.app.private_cache(cache)
        self.assertIn("belongs to uid 4321", str(err.exception))

    def test_villa_goes_last_on_sys_path(self):
        cache = self.cache()
        rec = self.app.ensure_villa(cache)
        src = str(cache / f"villa-{self.app.VILLA_COMMIT[:12]}" / "vesuvius" / "src")
        self.assertEqual(sys.path[-1], src)
        self.assertEqual(rec["src"], src)
        self.assertNotIn(src, sys.path[:-1])

    def test_engine_loads_the_checked_bytes_weights_only(self):
        cache = self.cache()
        path = self.checkpoint(cache, b"weights")
        real_read = Path.read_bytes
        swapped = []

        def read_then_swap(p):     # the file changes right after the check: the load must not see it
            data = real_read(p)
            if Path(p) == path and not swapped:
                swapped.append(True)
                path.write_bytes(b"PICKLE-CODE swapped")
            return data
        with mock.patch.object(Path, "read_bytes", read_then_swap):
            engine = self.app.Engine(cache)
        import torch
        self.assertEqual(torch.LOADS, [{"type": "BytesIO", "bytes": b"weights", "weights_only": True}])
        self.assertEqual(engine.cm.loaded, {"state": b"weights"})
        self.assertFalse((self.d / "pwned").exists())
        self.assertNotIn("src", engine.describe()["villa"])

    def test_a_checkpoint_with_other_bytes_is_refused(self):
        cache = self.cache()
        path = self.checkpoint(cache, b"weights")
        path.write_bytes(b"PICKLE-CODE")
        with self.assertRaises(RuntimeError) as err:
            self.app.Engine(cache)
        self.assertIn("refusing it", str(err.exception))
        self.assertFalse((self.d / "pwned").exists())

    def test_the_loader_refuses_another_file(self):
        import torch
        loader = self.app.checked_loader(torch, self.d / "a.pth", b"x")
        with self.assertRaises(RuntimeError):
            loader(self.d / "b.pth")
        self.assertEqual(loader(str(self.d / "a.pth")), {"state": b"x"})

    def test_another_vesuvius_on_the_path_is_refused(self):
        cache = self.cache()
        self.checkpoint(cache, b"weights")
        other = self.d / "site"
        for rel, text in VILLA.items():
            path = other / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text))
        sys.path.insert(1, str(other))
        with self.assertRaises(RuntimeError) as err:
            self.app.Engine(cache)
        self.assertIn("another vesuvius is installed", str(err.exception))


if __name__ == "__main__":
    unittest.main()
