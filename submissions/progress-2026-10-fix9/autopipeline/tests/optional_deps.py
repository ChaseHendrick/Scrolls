"""Skip a test when an optional package is missing, the way the map tools' tests skip without numpy.

The core kit is standard library only, and a cloud container or a fresh clone often lacks scipy, tifffile, zarr,
numcodecs, torch or huggingface_hub. A test that needs one says so with @needs(...) and skips with the reason
instead of failing with ModuleNotFoundError, so a run's real failures stand out. On a machine with the package
the test runs as before.
"""
import importlib.util
import unittest


def missing(*names):
    """The packages among names (top-level module names) that cannot be imported here."""
    return [n for n in names if importlib.util.find_spec(n.split(".")[0]) is None]


def needs(*names):
    """unittest.skipIf decorator for a test method or class that needs these packages."""
    gone = missing(*names)
    return unittest.skipIf(bool(gone), "needs " + ", ".join(gone) + " (not installed)")


def without_repo_spaces():
    """sys.modules entries that make `import spaces` fail when the only `spaces` is this repository's spaces/ folder.

    app.py does `try: import spaces except ImportError: spaces = None`. Run from the repository root, Python finds
    the spaces/ folder as a namespace package with no GPU attribute, so the app's GPU wrapper breaks. On the
    Space the real package is installed and nothing changes."""
    try:
        import spaces
    except ImportError:
        return {}
    return {} if hasattr(spaces, "GPU") else {"spaces": None}
