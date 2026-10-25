"""The Hugging Face Space of AutoPipeline's ink step: space/ in the release.

Covers the sample list and the segments the Space may read, the reserved and prize-target data it must never touch
(a scan of every file the Space is made of, which must catch a planted name), crop sizing and the GPU call's
duration, uploads, the checks on the maps, scoring, the README's metadata and the page. Nothing here downloads
anything or starts a server. Parts that need numpy, gradio or villa skip without them.
"""

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from optional_deps import without_repo_spaces

ROOT = Path(__file__).resolve().parent.parent
SPACE = next((p for p in (ROOT / "space", ROOT / "docs" / "submissions" / "progress-2026-10" / "autopipeline" / "space")
              if (p / "inkspace.py").is_file()), None)
BUILDER = ROOT / "scripts" / "release" / "autopipeline.py"


def have(module):
    return importlib.util.find_spec(module) is not None


def inkspace():
    if str(SPACE) not in sys.path:
        sys.path.insert(0, str(SPACE))
    import inkspace as mod
    return mod


def prize_targets():
    """Every scroll a prize in the newest snapshot names, eligible or awarded, with its scan volume ids."""
    snap = sorted((ROOT / "kit" / "data").glob("prizes-*.json"))[-1]
    names, volumes = set(), set()
    for prize in json.loads(snap.read_text())["prizes"]:
        for entry in prize.get("eligible", []) + prize.get("awarded", []):
            names.add(entry["scroll"])
            if str(entry.get("volume", "")).isdigit():
                volumes.add(entry["volume"])
    return sorted(names), sorted(volumes)


def scroll_pattern(name):
    """PHerc0172 as PHerc. 172 or P.Herc. 172; PHercParis4 also as PHerc. Paris 4, PHerc Paris 4 or Paris 4. (The
    release exporter, which this file ships without, has the same rule in a module of the source repository.)"""
    m = re.fullmatch(r"PHerc(\d+)([A-Z]?)", name)
    if m:
        return rf"\bp\.?\s*herc\.?\s*0*{int(m.group(1))}(?!\d)"
    m = re.fullmatch(r"PHerc([A-Za-z]+)(\d+)", name)
    if m:
        return rf"(?:\bp\.?\s*herc\.?\s*|\b){m.group(1)}[\s._-]*0*{int(m.group(2))}(?!\d)"
    return re.escape(name)


def forbidden_patterns():
    """What must appear nowhere in the Space: PHerc0841 ag405 and every PHerc1447 segment (reserved one-time tests),
    and every prize target scroll and scan volume."""
    pats = [r"(?i)\bag[ _-]?405\b", r"(?i)\b(?:ag|auto[ _-]?grown)[ _-]?\d*405\b", r"(?<![\d.])405(?!\d)",
            r"174252405", r"20260221022814",
            r"(?i)\bp\.?\s*herc\.?\s*0*1447(?!\d)", r"(?<![\d.])1447(?!\d)"]
    names, volumes = prize_targets()
    for name in names:
        pats.append("(?i)" + scroll_pattern(name))   # PHercParis4 also as PHerc. Paris 4 and Paris 4
    pats += [rf"(?<!\d){v}(?!\d)" for v in volumes]
    if BUILDER.is_file():   # the release's own list of private names, where this checkout has the builder
        spec = importlib.util.spec_from_file_location("release_autopipeline_for_space_test", BUILDER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pats += list(mod.BLOCK)
    return pats


def scan(root, patterns):
    hits = []
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        text = rel + "\n" + path.read_text(errors="replace")
        hits += [(rel, p, m.group(0)) for p in patterns for m in re.finditer(p, text)]
    return hits


@unittest.skipIf(SPACE is None, "no Space folder in this checkout")
class SamplesAndGuard(unittest.TestCase):
    def setUp(self):
        self.S = inkspace()
        self.data = self.S.load_samples()

    def sample(self, **change):
        s = dict(self.data["samples"][0])
        s.update(change)
        return s

    def test_the_samples_are_the_allowed_segments_with_their_roles(self):
        got = {(s["scroll"], s["segment"]): s["role"] for s in self.data["samples"]}
        self.assertEqual(got, self.S.ALLOWED)
        self.assertEqual(self.data["bucket"], self.S.BUCKET)
        for s in self.data["samples"]:
            y0, y1, x0, x1 = s["crop"]
            self.assertEqual((y1 - y0, x1 - x0), (640, 640), s["id"])
        notes = {s["id"]: s["note"] for s in self.data["samples"]}
        self.assertIn("Training data", notes["0139-w035"])
        self.assertIn("Not held out", notes["0139-w045"])
        self.assertTrue(all("not a blind test" in notes[k] for k in ("0841-w00", "0841-ag896")))

    def test_segments_off_the_allow_list_are_refused(self):
        for change in ({"segment": "20260221022814-auto_grown_20260220174252405"},
                       {"scroll": "PHerc1447", "segment": "20250521151220-w01"},
                       {"scroll": "PHerc0826"},
                       {"role": "test"},
                       {"surface_volume": "../../PHerc1447/x.zarr"},
                       {"labels": "https://example.org/labels"},
                       {"crop": [0, 640, 0, 9999]},
                       {"crop": [0, 64, 0, 640]},
                       {"note": ""}):
            with self.assertRaises(self.S.SpaceError, msg=str(change)):
                self.S.check_sample(self.sample(**change))
        with self.assertRaises(self.S.SpaceError):
            self.S.check_sample(self.sample(), bucket="https://example.org")

    def test_no_allowed_segment_is_reserved_or_a_prize_target(self):
        names, _ = prize_targets()
        self.assertTrue(names)
        for scroll, segment in self.S.ALLOWED:
            self.assertNotIn(scroll, names)
            self.assertEqual(scan_text(f"{scroll} {segment}", forbidden_patterns()), [])

    def test_reserved_and_target_data_appear_nowhere_in_the_space(self):
        pats = forbidden_patterns()
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "space"
            files = self.S.stage(staged)
            self.assertIn("app.py", files)
            self.assertEqual(scan(staged, pats), [])
            self.assertEqual(scan(SPACE, pats), [])
            # the scan must be able to fail
            for planted in ("PHerc0841 ag405", "PHerc0841 auto-grown 405", "auto_grown 405", "PHerc0841 segment 405",
                            "20260220000000-auto_grown_20260220000000405", "PHerc. 1447", "segment 1447",
                            "PHerc0826", "PHerc0175B", "20250821151723"):
                (staged / "planted.txt").write_text(planted + "\n")
                self.assertTrue(scan(staged, pats), planted)

    def test_window_and_lookup(self):
        s = self.S.sample_by("0841-w00", self.data)
        self.assertEqual(self.S.window(s), tuple(s["crop"]))
        y0, y1, x0, x1 = self.S.window(s, 384)
        self.assertEqual((y1 - y0, x1 - x0), (384, 384))
        self.assertEqual(((y0 + y1) // 2, (x0 + x1) // 2), ((s["crop"][0] + s["crop"][1]) // 2,
                                                            (s["crop"][2] + s["crop"][3]) // 2))
        for bad in (256, 641):     # under one 384 px patch, or past the crop
            with self.assertRaises(self.S.SpaceError):
                self.S.window(s, bad)
        with self.assertRaises(self.S.SpaceError):
            self.S.sample_by("0841-ag405", self.data)
        self.assertTrue(self.S.segment_url(s).startswith(self.S.BUCKET + "/PHerc0841/segments/20260220213127-w00/"))


def scan_text(text, patterns):
    return [p for p in patterns if re.search(p, text)]


@unittest.skipIf(SPACE is None, "no Space folder in this checkout")
class Sizing(unittest.TestCase):
    def setUp(self):
        self.S = inkspace()

    def test_patch_schedule_matches_villa(self):
        # Reader V3's 384 px patches at villa's overlap 0.5 (stride 192)
        self.assertEqual((self.S.PATCH, self.S.STRIDE, self.S.MIN_SIDE), (384, 192, 384))
        self.assertEqual(self.S.positions(640), [0, 192, 256])
        self.assertEqual(self.S.positions(700), [0, 192, 316])
        self.assertEqual(self.S.positions(768), [0, 192, 384])
        self.assertEqual(self.S.positions(384), [0])
        self.assertEqual(self.S.patches(640, 640), 9)

    def test_gpu_call_duration(self):
        self.assertEqual(self.S.gpu_seconds(640, 640), 28)
        self.assertEqual(self.S.gpu_seconds(768, 768), 28)
        self.assertEqual(self.S.gpu_seconds(384, 384), self.S.MIN_GPU_S)
        self.assertLessEqual(self.S.gpu_seconds(self.S.MAX_SIDE, self.S.MAX_SIDE), self.S.MAX_GPU_S)
        with self.assertRaises(self.S.SpaceError):
            self.S.gpu_seconds(4000, 4000)

    def test_volume_limits(self):
        S = self.S
        self.assertEqual(S.check_volume((28, 640, 640), "uint8"), (28, 640, 640))
        S.check_volume((17, 384, 768), "uint16")
        for shape, dtype in (((640, 640), "uint8"), ((28, 640, 640), "float32"), ((16, 640, 640), "uint8"),
                             ((66, 640, 640), "uint8"), ((28, 800, 640), "uint8"), ((28, 640, 100), "uint8"),
                             ((28, 640, 383), "uint8")):
            with self.assertRaises(S.SpaceError, msg=f"{shape} {dtype}"):
                S.check_volume(shape, dtype)


@unittest.skipIf(SPACE is None or not have("numpy"), "needs the Space folder and numpy")
class MapsAndScores(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.np = np
        self.S = inkspace()

    def test_upload_is_read_into_memory_and_its_file_deleted(self):
        np, S = self.np, self.S
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "v.npy"
            np.save(good, np.ones((20, 384, 400), np.uint8))
            arr = S.read_upload(good)
            self.assertEqual(arr.shape, (20, 384, 400))
            self.assertFalse(good.exists())
            for name, data in (("flat.npy", np.ones((160, 200), np.uint8)),
                               ("objects.npy", np.array([{"a": 1}], dtype=object)),
                               ("v.zarr", b"x")):
                path = Path(tmp) / name
                if isinstance(data, bytes):
                    path.write_bytes(data)
                else:
                    np.save(path, data, allow_pickle=True)
                with self.assertRaises(S.SpaceError, msg=name):
                    S.read_upload(path)
                self.assertFalse(path.exists(), name)

    def test_an_upload_too_big_inside_is_refused_from_its_header(self):
        np, S = self.np, self.S
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            # a .npy whose header claims 24 x 8192 x 8192: refused before np.load allocates anything
            path = Path(tmp) / "huge.npy"
            with open(path, "wb") as fh:
                np.lib.format.write_array_header_1_0(fh, {"descr": "|u1", "fortran_order": False,
                                                          "shape": (24, 8192, 8192)})
                fh.write(b"\0" * 64)
            with mock.patch.object(np, "load", side_effect=AssertionError("np.load ran")):
                with self.assertRaisesRegex(S.SpaceError, "height 8192"):
                    S.read_upload(path)
            self.assertFalse(path.exists())
            # a .npy that is a zip, or has no .npy header at all
            for name, data in (("zip.npy", b"PK\x03\x04" + b"\0" * 60), ("text.npy", b"hello\n")):
                (Path(tmp) / name).write_bytes(data)
                with self.assertRaises(S.SpaceError, msg=name):
                    S.read_upload(Path(tmp) / name)

    @unittest.skipUnless(have("tifffile"), "tifffile is not installed")
    def test_a_compressed_tif_too_big_inside_is_refused_before_it_is_decoded(self):
        np, S = self.np, self.S
        import tifffile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            bomb = Path(tmp) / "bomb.tif"
            tifffile.imwrite(bomb, np.zeros((24, 1024, 1024), np.uint8), compression="zlib")
            self.assertLess(bomb.stat().st_size, 2 ** 20)
            with mock.patch.object(tifffile.TiffPageSeries, "asarray", side_effect=AssertionError("decoded")), \
                    mock.patch.object(tifffile.TiffFile, "asarray", side_effect=AssertionError("decoded")):
                with self.assertRaisesRegex(S.SpaceError, "height 1024"):
                    S.read_upload(bomb)
            self.assertFalse(bomb.exists())
            good = Path(tmp) / "good.tif"
            vol = (np.arange(20 * 384 * 400) % 65536).astype(np.uint16).reshape(20, 384, 400)
            tifffile.imwrite(good, vol, compression="zlib")
            self.assertTrue(np.array_equal(S.read_upload(good), vol))
            self.assertFalse(good.exists())
            broken = Path(tmp) / "broken.tif"
            broken.write_bytes(b"II*\0" + b"\xff" * 60)
            with self.assertRaises(S.SpaceError):
                S.read_upload(broken)

    def test_upload_over_the_size_limit_is_refused_and_deleted(self):
        S = self.S
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.npy"
            with open(big, "wb") as fh:
                fh.truncate(S.MAX_UPLOAD_BYTES + 1)
            with self.assertRaises(S.SpaceError):
                S.read_upload(big)
            self.assertFalse(big.exists())

    def test_an_upload_deleted_before_it_ran_is_asked_for_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(self.S.SpaceError, "upload it again"):
                self.S.read_upload(Path(tmp) / "gone.npy")

    def test_page_images_are_png_data_made_in_memory(self):
        np, S = self.np, self.S
        import base64
        import struct
        import zlib
        img = np.arange(130 * 141, dtype=np.uint32).reshape(130, 141).astype(np.uint8)
        png = S.png_bytes(img)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        pos, chunks = 8, {}
        while pos < len(png):
            n, tag = struct.unpack(">I4s", png[pos:pos + 8])
            data = png[pos + 8:pos + 8 + n]
            self.assertEqual(struct.unpack(">I", png[pos + 8 + n:pos + 12 + n])[0], zlib.crc32(tag + data))
            chunks[tag] = chunks.get(tag, b"") + data
            pos += 12 + n
        self.assertEqual(struct.unpack(">IIBBBBB", chunks[b"IHDR"]), (141, 130, 8, 0, 0, 0, 0))
        rows = np.frombuffer(zlib.decompress(chunks[b"IDAT"]), np.uint8).reshape(130, 142)
        self.assertTrue((rows[:, 0] == 0).all())
        self.assertTrue(np.array_equal(rows[:, 1:], img))
        for bad in (np.zeros((4, 4, 4), np.uint8), np.zeros((4, 4), np.float32), np.zeros((0, 4), np.uint8)):
            with self.assertRaises(S.SpaceError):
                S.png_bytes(bad)
        page = S.figures_html([("CT <middle>", np.zeros((4, 4), np.uint16) + 7), ("Map", img)])
        uris = re.findall(r'src="data:image/png;base64,([A-Za-z0-9+/=]+)"', page)
        self.assertEqual(len(uris), 2)
        self.assertEqual(base64.b64decode(uris[1]), S.png_bytes(S.ink_rgb(img)))   # the ink map in color
        self.assertEqual(base64.b64decode(uris[1])[25], 2)                           # RGB
        self.assertEqual(base64.b64decode(uris[0])[25], 0)                           # the CT stays gray
        self.assertIn("CT &lt;middle&gt;", page)
        self.assertNotIn("<middle>", page)

    def test_ink_colors_match_the_monitor_and_share_the_forward_scale(self):
        np, S = self.np, self.S
        from kit import autopipe_monitor as mon
        self.assertEqual(S.INK_STOPS, mon.INK_STOPS)
        self.assertEqual([tuple(c) for c in S.ink_rgb(np.arange(256, dtype=np.uint8)[None])[0]],
                         list(mon.INK_LUT))
        fwd = np.linspace(0, 1, 100, dtype=np.float32).reshape(10, 10)
        page = S.figures_html([("CT", fwd), ("Map", fwd), ("Control", fwd * 0.5)])
        import base64
        import zlib
        raw = [zlib.decompress(base64.b64decode(u)[41:-12])
               for u in re.findall(r'src="data:image/png;base64,([A-Za-z0-9+/=]+)"', page)]
        self.assertLess(sum(raw[2]), sum(raw[1]))      # the control on the forward map's scale stays darker

    def test_no_forward_map_without_its_control(self):
        np, S = self.np, self.S
        f = np.zeros((4, 4), np.uint8)
        for result in ({"forward": f}, {"reverse": f}, {"forward": f, "reverse": np.zeros((4, 5), np.uint8)}):
            with self.assertRaises(S.SpaceError):
                S.require_pair(result)
        self.assertEqual(len(S.require_pair({"forward": f, "reverse": f})), 2)

    def maps(self):
        np = self.np
        rng = np.random.default_rng(0)
        ink = np.zeros((256, 256), bool)
        ink[100:150, 60:200] = True
        forward = np.clip(80 + 120 * ink + rng.normal(0, 20, ink.shape), 1, 255).astype(np.uint8)
        reverse = np.clip(80 + rng.normal(0, 20, ink.shape), 1, 255).astype(np.uint8)
        return ink, forward, reverse

    def test_broken_maps_are_refused(self):
        np, S = self.np, self.S
        ink, forward, reverse = self.maps()
        surface = np.ones(forward.shape, bool)
        comparison = S.check_maps(forward, reverse, surface)
        self.assertGreater(comparison["forward_minus_control"], 0)
        for f, r in ((np.zeros_like(forward), reverse), (forward, forward.copy())):
            with self.assertRaises(S.SpaceError):
                S.check_maps(f, r, surface)

    def test_scores_put_a_real_signal_above_its_control(self):
        np, S = self.np, self.S
        ink, forward, reverse = self.maps()
        res = S.score_pair(forward, reverse, ink, np.ones(ink.shape, bool))
        self.assertGreater(res["forward"]["auc"], 0.95)
        self.assertLess(abs(res["reverse"]["auc"] - 0.5), 0.05)
        self.assertGreater(res["difference"], 0.4)
        self.assertEqual(res["forward"]["inner"], S.INNER)
        self.assertEqual(res["forward"]["ink_px"] + res["forward"]["background_px"], (256 - 128) ** 2)
        text = S.summary({"sample": S.sample_by("0841-w00"), "box": [0, 256, 0, 256], "scores": res})
        self.assertIn("model output, not a reading", text)
        self.assertIn("Control, layers reversed", text)


@unittest.skipIf(SPACE is None, "no Space folder in this checkout")
class FilesAndWording(unittest.TestCase):
    def setUp(self):
        self.S = inkspace()

    def test_checkpoint_is_the_one_in_readers_tsv(self):
        ck = self.S.load_samples()["checkpoint"]
        row = self.S.readers_row("readerv3", ROOT)
        self.assertIsNotNone(row, "scripts/firstletters/readers.tsv has no readerv3")
        self.assertEqual((ck["url"], ck["sha256"]), (row["url"], row["sha256"]))
        self.assertTrue(ck["url"].endswith("/" + ck["file"]))
        self.assertEqual((ck["repo"], ck["file"], ck["license"]), ("domenicor046/reader-v3", "reader-v3.pth", "MIT"))

    @unittest.skipUnless((ROOT / "scripts" / "vc3d" / "modal_autopipe.py").is_file(),
                         "no Modal runner in this copy (AutoPipeline's public cut leaves it out)")
    def test_villa_commit_is_the_one_autopipeline_runs(self):
        src = (ROOT / "scripts" / "vc3d" / "modal_autopipe.py").read_text()
        pinned = re.search(r'^VILLA_REV = "([0-9a-f]{40})"', src, flags=re.M).group(1)
        self.assertEqual(self.S.load_samples()["villa_commit"], pinned)

    def test_staged_kit_modules_are_closed_under_their_imports(self):
        S = self.S
        root = S.find_root(SPACE)
        for m in S.KIT_MODULES:
            for dep in S.kit_imports(root / "kit" / f"{m}.py"):
                self.assertIn(dep, S.KIT_MODULES, f"kit/{m}.py imports {dep}, which the Space does not carry")
        with tempfile.TemporaryDirectory() as tmp:
            files = S.stage(Path(tmp) / "s")
            self.assertEqual(sorted(files), sorted(list(S.SPACE_FILES) + [f"kit/{m}.py" for m in S.KIT_MODULES] +
                                                   list(S.EXTRA_FILES)))
            with self.assertRaises(S.SpaceError):
                S.stage(Path(tmp) / "s")

    def test_readme_metadata_and_requirements(self):
        text = (SPACE / "README.md").read_text()
        head = text.split("---")[1]
        lines = [line for line in head.strip().splitlines() if ":" in line and not line.startswith(" ")]
        meta = {k.strip(): v.strip().strip('"') for k, v in (line.split(":", 1) for line in lines)}
        self.assertEqual(meta["sdk"], "gradio")
        self.assertEqual(meta["app_file"], "app.py")
        self.assertEqual(meta["suggested_hardware"], "zero-a10g")
        self.assertEqual(meta["python_version"], "3.12")
        self.assertLessEqual(len(meta["short_description"]), 60)
        req = (SPACE / "requirements.txt").read_text()
        for line in req.splitlines():   # every package at the exact version the local run used
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[\w.]+$")
        torch = re.search(r"^torch==([\d.]+)$", req, flags=re.M).group(1)
        self.assertIn(torch, ("2.8.0", "2.9.1", "2.10.0", "2.11.0", "2.12.1", "2.13.0"))
        self.assertNotRegex(req, r"(?m)^(gradio|spaces)\b")

    def test_the_page_says_what_happens_to_an_upload(self):
        S = self.S
        minutes = S.UNRUN_UPLOAD_MINUTES
        self.assertEqual(minutes * 60, S.CACHE_SWEEP_S + S.UPLOAD_MAX_AGE_S)
        for text in (S.UPLOAD_TEXT, (SPACE / "README.md").read_text()):
            text = " ".join(text.split())
            self.assertIn(f"a file you upload but do not run is deleted within {minutes} minutes", text)
            self.assertIn("sent inside the page and never written to the Space's disk", text)
            self.assertNotIn("othing is kept", text)

    def test_wording(self):
        S = self.S
        readme = (SPACE / "README.md").read_text()
        for text in (readme, S.INTRO):
            self.assertIn("model output, not a reading", text)
            self.assertIn("AutoPipeline runs villa's pipeline from a released scan to a scored ink map, with checks "
                          "that can fail at every step.", " ".join(text.split()))
        for path in SPACE.iterdir():
            if path.is_file() and path.suffix in (".py", ".md", ".json", ".txt"):
                body = path.read_text()
                for ch in (chr(0x2014), chr(0x2013)):
                    self.assertNotIn(ch, body, path.name)


@unittest.skipIf(SPACE is None or not have("numpy"), "needs the Space folder and numpy")
class App(unittest.TestCase):
    """app.py with a stand-in engine: the job flow, and the page where gradio is installed. No model, no network."""

    def setUp(self):
        import numpy as np
        self.np = np
        self.S = inkspace()
        spec = importlib.util.spec_from_file_location("autopipeline_space_app_under_test", SPACE / "app.py")
        self.app = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, without_repo_spaces()):
            spec.loader.exec_module(self.app)

    def fake(self, broken=False):
        np = self.np

        class Engine:
            def describe(self):
                return {"checkpoint": "stand-in"}

            def run_pair(self, volume):
                mid = volume[volume.shape[0] // 2].astype(np.float32)
                forward = np.clip(mid, 1, 255).astype(np.uint8)
                reverse = forward.copy() if broken else np.clip(255 - mid, 1, 255).astype(np.uint8)
                return {"forward": forward, "reverse": reverse, "layers": {}, "patches": 9, "device": "cpu",
                        "device_name": "stand-in", "seconds": 0.0}
        return Engine()

    def volume(self):
        np = self.np
        rng = np.random.default_rng(1)
        v = rng.integers(60, 120, size=(20, 384, 384), dtype=np.uint8)
        v[:, 150:220, 90:300] += 100
        return v

    def test_sample_flow_scores_both_maps(self):
        np, app, S = self.np, self.app, self.S
        vol = self.volume()
        ink = np.zeros((384, 384), bool)
        ink[150:220, 90:300] = True
        app.ENGINE = self.fake()
        orig = (S.read_crop, S.labels_for)
        S.read_crop = lambda sample, box: (vol, {"url": "stand-in", "box": list(box)})
        S.labels_for = lambda sample, box, shape: (ink, np.ones(shape, bool))
        try:
            res = app.run_sample("0841-w00", 384)
        finally:
            S.read_crop, S.labels_for = orig
        self.assertEqual(res["forward"].shape, res["reverse"].shape)
        self.assertGreater(res["scores"]["forward"]["auc"], 0.9)
        self.assertLess(res["scores"]["reverse"]["auc"], 0.1)
        self.assertEqual(res["receipt"]["gpu_seconds_requested"], 20)
        self.assertEqual(res["receipt"]["note"], "model output, not a reading")
        self.assertIn("Layers in stored order", res["summary"])

    def test_upload_flow_has_no_auc_and_refuses_a_broken_run(self):
        np, app, S = self.np, self.app, self.S
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "up.npy"
            np.save(path, self.volume())
            app.ENGINE = self.fake()
            res = app.run_upload(str(path))
            self.assertIsNone(res["scores"])
            self.assertFalse(path.exists())
            self.assertIn("No labels", res["summary"])
            np.save(path, self.volume())
            app.ENGINE = self.fake(broken=True)
            with self.assertRaises(S.SpaceError):
                app.run_upload(str(path))

    def test_the_page_shows_the_three_images_inside_it(self):
        np = self.np
        a = np.full((128, 128), 9, np.uint8)
        page = self.app.figures(a, a, a)
        self.assertEqual(page.count("data:image/png;base64,"), 3)
        for caption in ("CT, middle layer", "Ink map, layers in stored order", "Control, layers reversed"):
            self.assertIn(caption, page)

    def test_result_strip_keeps_a_control_that_outscores_the_forward_map(self):
        result = {"sample": {"title": "Sample <script>alert(1)</script>"},
                  "receipt": {"shape": [28, 640, 640], "inference_seconds": 3.25},
                  "scores": {"forward": {"auc": 0.3, "ink_px": 200, "background_px": 800},
                             "reverse": {"auc": 0.8, "ink_px": 200, "background_px": 800},
                             "difference": -0.5}}
        markup = self.S.metrics_html(result)
        self.assertIn("Stored-order AUC", markup)
        self.assertIn("0.3000", markup)
        self.assertIn("0.8000", markup)
        self.assertIn("-0.5000", markup)
        self.assertIn("1,000", markup)
        self.assertIn("small area is noisy", markup)
        self.assertIn("640 × 640", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertNotIn("<script>", markup)

    def test_unscored_result_and_empty_workspace_do_not_make_up_measurements(self):
        markup = self.S.metrics_html({"sample": None, "scores": None,
                                      "receipt": {"shape": [20, 256, 256], "inference_seconds": 0}})
        self.assertIn("No labels", markup)
        self.assertNotIn("Stored-order AUC", markup)
        self.assertNotIn("0.0000", markup)
        empty = self.S.empty_figures_html()
        self.assertNotIn("data:image", empty)
        self.assertNotIn("ap-metric", empty)
        self.assertIn("Both maps will appear together", empty)

    @unittest.skipUnless(have("gradio"), "gradio is not installed")
    def test_page_builds_without_serving(self):
        demo = self.app.build_demo()
        self.assertEqual(type(demo).__name__, "Blocks")
        self.assertEqual(tuple(demo.delete_cache), (self.S.CACHE_SWEEP_S, self.S.UPLOAD_MAX_AGE_S))
        # no component that makes Gradio write an output file: the images go out as HTML
        kinds = {type(b).__name__ for b in demo.blocks.values()}
        self.assertIn("HTML", kinds)
        self.assertFalse(kinds & {"Image", "Gallery", "AnnotatedImage", "ImageEditor", "Video", "Audio"}, kinds)
        self.assertEqual([type(b).__name__ for b in demo.blocks.values() if type(b).__name__ == "File"], ["File"])

    @unittest.skipUnless(have("gradio"), "gradio is not installed")
    def test_source_actions_share_one_inference_queue(self):
        demo = self.app.build_demo()
        actions = [fn for fn in demo.fns.values() if fn.fn and fn.fn.__name__ in ("on_sample", "on_upload")]
        self.assertEqual(len(actions), 2)
        self.assertEqual({fn.concurrency_id for fn in actions}, {"ink-analysis"})
        self.assertTrue(all(fn.concurrency_limit == 1 for fn in actions))
        theme = self.app.theme()
        self.assertEqual(theme.body_text_color, "#182633")
        # The page stays light in a dark-mode browser, so inline code keeps its light chip there too (14 Oct 2026:
        # Gradio's dark chip behind the page's dark text hid `ink_9um` in "About this workflow").
        self.assertEqual(theme.code_background_fill_dark, theme.code_background_fill)
        self.assertEqual(theme.body_text_color_dark, theme.body_text_color)

    def test_gradio_refuses_a_big_upload_while_it_streams_in(self):
        self.assertEqual(self.app.LAUNCH["max_file_size"], self.S.MAX_UPLOAD_BYTES)


if __name__ == "__main__":
    unittest.main()
