"""scripts/media/: release heroes, clips and captures (docs/tools/media.md).

The label and guard checks run everywhere (standard library). Rendering needs numpy and Pillow, encoding needs ffmpeg
and gifsicle, and capturing needs Playwright with a Chromium; each part skips when its tools are missing.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "scripts" / "media"
sys.path.insert(0, str(MEDIA))

import common  # noqa: E402

HAVE_NUMPY = importlib.util.find_spec("numpy") is not None and importlib.util.find_spec("PIL") is not None
HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("gifsicle") is not None
HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None

GOOD = {"label": "Concept illustration", "alt": "A copper thread through discs.",
        "caption": "Concept illustration: discs on a thread. No scan data.", "license": "Apache-2.0"}
# A Real data render the public media rule allows: PHerc0139 is on no prize list, and it draws no labels.
REAL = {"label": "Real data render", "alt": "A slice.", "license": "CC BY-NC 4.0",
        "caption": "Real data render: PHerc0139, 2.4 um. Data: Vesuvius Challenge open data, CC BY-NC 4.0",
        "data": {"scan": "PHerc0139", "segment": "w035", "voxel_size": "2.399 um", "labels": "none",
                 "credit": "Vesuvius Challenge open data, CC BY-NC 4.0"}}


def real(scan="PHerc0139", segment="w035", labels="none", caption_extra="", **data):
    """REAL with another scan, segment or labels; caption_extra goes before the credit."""
    meta = json.loads(json.dumps(REAL))
    meta["data"].update(scan=scan, segment=segment, labels=labels, **data)
    meta["caption"] = f"Real data render: {scan}{caption_extra}. Data: Vesuvius Challenge open data, CC BY-NC 4.0"
    return meta


def sidecar(meta, width=1920, nbytes=50_000, scripts=("common.py", "hero.py"), commit="0" * 40):
    """A written sidecar record for meta, as write_sidecar() makes it."""
    return dict(meta, schema="scrolls-media/1", command="python scripts/media/hero.py r.json --out-dir OUT",
                outputs=[{"file": "a-hero.webp", "bytes": nbytes, "width": width, "height": 640}],
                tool={"scripts": list(scripts), "scripts_sha256": "0" * 64, "base_commit": commit})


class LabelTest(unittest.TestCase):
    def test_good_records_pass(self):
        common.check_meta(GOOD)
        common.check_meta(REAL)
        common.check_meta(dict(GOOD, label="Synthetic demo", caption="Synthetic demo: a monitor on made-up data."))

    def test_bad_records_fail(self):
        bad = [[], dict(GOOD, label="Concept art"), dict(GOOD, caption="Discs on a thread."),
               dict(GOOD, alt=""), dict(GOOD, license="\n"), dict(GOOD, caption="Concept illustration" + chr(0x2014)),
               {k: v for k, v in GOOD.items() if k != "license"}, dict(REAL, data=None),
               dict(REAL, data=dict(REAL["data"], credit="Data: someone")),
               dict(REAL, caption="Real data render: PHerc0139."), dict(REAL, data=dict(REAL["data"], scan="")),
               dict(REAL, data={k: v for k, v in REAL["data"].items() if k != "labels"}),
               dict(REAL, data=dict(REAL["data"], voxel_size="")),
               dict(REAL, data=dict(REAL["data"], credit="Data: Vesuvius Challenge, CC BY-NC 4.0"),
                    caption="Real data render: PHerc0139. Data: Vesuvius Challenge, CC BY-NC 4.0"),
               dict(REAL, license="Apache-2.0")]
        for meta in bad:
            with self.subTest(meta=meta), self.assertRaises(common.MediaError):
                common.check_meta(meta)
        # segment is optional: a whole-scroll slice has none
        common.check_meta(dict(REAL, data={k: v for k, v in REAL["data"].items() if k != "segment"}))

    def test_the_public_media_rule_at_write_time(self):
        out = ROOT / "docs" / "assets" / "x" / "a-hero.webp"
        common.write_guard("Concept illustration", out)
        common.write_guard("Synthetic demo", ROOT / "docs" / "assets" / "x" / "a.gif")
        common.write_guard("Real data render", out, REAL)
        common.write_guard("Real data render", out, real("PHerc. 172", segment=None))
        common.write_guard("Real data render", out, real("PHerc0841", segment="w00", labels="w00 inklabels"))
        common.write_guard("Real data render", out, real("PHerc0841", segment="ag405"))  # its CT, no labels drawn
        common.write_guard("Model output", Path("/tmp/Scrolls-private/docs/media/x/a-hero.webp"))
        common.write_guard("Real data render", Path("/tmp/Scrolls-private/docs/media/x/a-hero.webp"),
                           real("PHerc0800"))
        refused = {"model output": ("Model output", GOOD), "an unknown label": ("Something else", GOOD),
                   "a Real data render without its record": ("Real data render", None),
                   "a Grand Prize scroll": ("Real data render", real("PHerc0800")),
                   "a First Letters scroll by volume id": ("Real data render", real("PHerc0139", volume="20250821151701")),
                   "a First Letters scroll named without its part": ("Real data render", real("PHerc. 175")),
                   "the title prize's scroll": ("Real data render", real("Scroll 1")),
                   "Paris 4 spelled out": ("Real data render", real("PHerc. Paris 4")),
                   "PHerc1447": ("Real data render", real("PHerc1447")),
                   "an eligible scroll in the caption": ("Real data render", real(caption_extra=" beside PHerc0826")),
                   "an eligible volume id in the caption": ("Real data render", real(caption_extra=", volume 20250521135224")),
                   "held-out ag405 labels": ("Real data render", real("PHerc0841", "ag405", "ag405 inklabels")),
                   "held-out labels in upper case": ("Real data render", real("PHerc0841", "AG405", "ink labels")),
                   "held-out labels in mixed case": ("Real data render", real("PHerc0841", "w00", "Ag405 ink labels")),
                   "the old credit": ("Real data render", dict(REAL, data=dict(REAL["data"], credit="Data: x")))}
        for why, (label, meta) in refused.items():
            with self.subTest(why), self.assertRaises(common.MediaError):
                common.write_guard(label, out, meta)

    def test_prize_list_comes_from_the_snapshot_and_fails_closed(self):
        table, checked = common.prize_scrolls()
        self.assertTrue(checked)
        for name in ("PHerc0800", "PHerc. 826", "PHerc1447", "PHercParis4", "Scroll 1", "PHerc0175A", "PHerc0175"):
            with self.subTest(eligible=name):
                self.assertTrue(common.eligible_prizes(name, table))
        for name in ("PHerc0139", "PHerc. 172", "PHerc0841", "PHerc0332", "Scroll 4", "PHerc0009B", "PHerc017"):
            with self.subTest(not_eligible=name):
                self.assertEqual(common.eligible_prizes(name, table), [])
        self.assertEqual([common.normalize_scroll(n) for n in ("PHerc. 139", "pherc0139", "PHerc. Paris. 4", "scroll-1")],
                         ["PHERC0139", "PHERC0139", "PHERCPARIS4", "PHERCPARIS4"])
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(common.MediaError):
            common.prize_scrolls(tmp)

    def test_a_sidecar_is_checked_against_the_rule(self):
        self.assertEqual(common.public_problems(sidecar(GOOD)), [])
        self.assertEqual(common.public_problems(sidecar(REAL)), [])
        committed = json.loads((ROOT / "docs" / "assets" / "umbilicus" / "umbilicus-hero.json").read_text())
        self.assertEqual(common.public_problems(committed), [])
        bad = {"model output": sidecar(dict(GOOD, label="Model output", caption="Model output: a map.")),
               "too wide": sidecar(GOOD, width=1921), "too large": sidecar(GOOD, nbytes=4_000_001),
               "no commit": sidecar(GOOD, commit=None), "no width": sidecar(GOOD, width=None),
               "real data without its scripts": sidecar(REAL, scripts=()),
               "real data of an eligible scroll": sidecar(real("PHerc1218")),
               "an eligible scroll in a file name": dict(sidecar(REAL), outputs=[
                   {"file": "unroll-pherc0800.webp", "bytes": 1, "width": 1920, "height": 640}]),
               "no command": dict(sidecar(GOOD), command=""), "wrong schema": dict(sidecar(GOOD), schema="x"),
               "not an object": []}
        for why, record in bad.items():
            with self.subTest(why):
                self.assertNotEqual(common.public_problems(record), [])

    def test_an_svg_with_raster_pixels_is_caught(self):
        chart = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="4"/><text>AUC 0.71</text></svg>'
        self.assertFalse(common.svg_embeds_raster(chart))
        for why, svg in {"an image element": '<svg><image href="slice.png" width="10" height="10"/></svg>',
                         "a namespaced image": '<svg:svg><svg:IMAGE xlink:href="a.jpg"/></svg:svg>',
                         "a data URI in CSS": '<svg><style>rect{fill:url(data:image/png;base64,AAAA)}</style></svg>',
                         "a filter image": '<svg><filter><feImage href="b.webp"/></filter></svg>',
                         "an HTML img": '<svg><foreignObject><img src="c.png"/></foreignObject></svg>'}.items():
            with self.subTest(why):
                self.assertTrue(common.svg_embeds_raster(svg))

    def test_size_guard_removes_a_file_over_the_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "docs" / "assets" / "x"
            folder.mkdir(parents=True)
            clip = folder / "a.gif"
            clip.write_bytes(b"GIF89a" + (1920).to_bytes(2, "little") + (540).to_bytes(2, "little") + b"\0" * 8)
            common.size_guard(clip)
            common.size_guard(clip, 1920)
            with self.assertRaises(common.MediaError):
                common.size_guard(clip, 1921)
            self.assertFalse(clip.exists())
            wide = folder / "b.gif"
            wide.write_bytes(b"GIF89a" + (2400).to_bytes(2, "little") + (540).to_bytes(2, "little") + b"\0" * 8)
            with self.assertRaises(common.MediaError):
                common.size_guard(wide)
            big = Path(tmp) / "elsewhere.gif"
            big.write_bytes(b"\0" * 10)
            common.size_guard(big, 4000)
            self.assertTrue(big.exists(), "outside docs/assets/ the limits do not apply")

    def test_public_pictures_are_built_only_from_the_public_tree(self):
        out = ROOT / "docs" / "assets" / "x" / "a-hero.webp"
        common.input_guard(["docs/images/workbench/starter-practice.png", "docs/assets/scrolls-readme-hero.webp"], out)
        common.input_guard(["/tmp/scan-render.png"], Path("/tmp/Scrolls-private/docs/media/x/a-hero.webp"))
        for bad in ("/tmp/scan-render.png", "docs/../../elsewhere/render.png", "kit/data/render.png"):
            with self.subTest(source=bad), self.assertRaises(common.MediaError):
                common.input_guard([bad], out)
        # A Real data render is built from scan data; write_guard's rule checks stand in for the public-tree one.
        common.input_guard(["/tmp/scan-render.png"], out, label="Real data render")

    def test_a_clip_under_docs_assets_needs_a_label(self):
        import encode
        with tempfile.TemporaryDirectory() as tmp:
            target = ROOT / "docs" / "assets" / "never-written" / "clip.gif"
            self.assertEqual(encode.main([tmp, "--gif", str(target)]), 2)
        self.assertFalse(target.parent.exists())

    def test_sidecar_records_what_made_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pic = Path(tmp) / "a-hero.webp"
            pic.write_bytes(b"RIFF0000WEBP")
            rec = common.write_sidecar(Path(tmp) / "a-hero.json", GOOD, [common.output_record(pic, 1920, 640)],
                                       command="python scripts/media/hero.py r.json", scripts=("common.py",))
            on_disk = json.loads((Path(tmp) / "a-hero.json").read_text())
        self.assertEqual(on_disk, rec)
        self.assertEqual((rec["schema"], rec["label"], rec["outputs"][0]["bytes"]), ("scrolls-media/1", GOOD["label"], 12))
        self.assertEqual(len(rec["tool"]["scripts_sha256"]), 64)


class RecipeTest(unittest.TestCase):
    def setUp(self):
        import hero
        self.hero = hero

    def test_committed_recipes_are_valid(self):
        recipes = sorted((MEDIA / "recipes").glob("*.json"))
        self.assertGreaterEqual(len(recipes), 8)
        for path in recipes:
            with self.subTest(recipe=path.name):
                recipe = self.hero.load_recipe(path)
                self.assertTrue(recipe["name"].endswith("-hero"))
                self.assertIn(recipe["label"], ("Concept illustration", "Synthetic demo"))

    def test_bad_recipes_fail(self):
        base = json.loads((MEDIA / "recipes" / "umbilicus.json").read_text())
        bad = [dict(base, name="Bad_Name"), dict(base, extra=1), {k: v for k, v in base.items() if k != "scene"},
               dict(base, scene={"kind": "video"}), dict(base, label="Model output", caption="Model output: x."),
               dict(base, caption="A thread.")]
        with tempfile.TemporaryDirectory() as tmp:
            for i, recipe in enumerate(bad):
                path = Path(tmp) / f"r{i}.json"
                path.write_text(json.dumps(recipe))
                with self.subTest(recipe=i), self.assertRaises(common.MediaError):
                    self.hero.load_recipe(path)

    def test_check_command(self):
        code = self.hero.main(["--check", str(MEDIA / "recipes" / "umbilicus.json"), "--quiet"])
        self.assertEqual(code, 0)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{}")
            self.assertEqual(self.hero.main(["--check", str(bad)]), 2)

    def test_a_panels_scene_is_a_synthetic_demo(self):
        base = json.loads((MEDIA / "recipes" / "starter.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "panels.json"
            path.write_text(json.dumps(dict(base, label="Concept illustration",
                                            caption="Concept illustration: two panels.")))
            with self.assertRaises(common.MediaError):
                self.hero.load_recipe(path)

    def test_a_source_picture_from_outside_the_public_tree_is_refused(self):
        # An honest-looking label on a scan render must not get it into docs/assets/ through an image scene or panel.
        base = json.loads((MEDIA / "recipes" / "starter.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            render = Path(tmp) / "render.png"
            render.write_bytes(b"not a picture")
            image = dict(base, scene={"kind": "image", "path": str(render)})
            panels = json.loads(json.dumps(base))
            panels["scene"]["params"]["panels"][0]["image"] = str(render)
            for i, recipe in enumerate((image, panels)):
                path = Path(tmp) / f"r{i}.json"
                path.write_text(json.dumps(recipe))
                with self.subTest(recipe=i), self.assertRaises(common.MediaError):
                    self.hero.make(path, ROOT / "docs" / "assets" / "never-written")
        self.assertFalse((ROOT / "docs" / "assets" / "never-written").exists())

    def test_an_eligible_scroll_is_refused_under_docs_assets_before_rendering(self):
        recipe = dict(json.loads((MEDIA / "recipes" / "umbilicus.json").read_text()), **real("PHerc0800"),
                      scene={"kind": "image", "path": "missing.png"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "real.json"
            path.write_text(json.dumps(recipe))
            with self.assertRaises(common.MediaError):
                self.hero.make(path, Path(tmp) / "docs" / "assets" / "x")
            self.assertFalse((Path(tmp) / "docs").exists(), "refused before the folder was made")
            # A scan off the prize lists passes the rule and gets as far as Pillow, then reading its picture.
            path.write_text(json.dumps(dict(recipe, **REAL)))
            with self.assertRaises(FileNotFoundError if HAVE_NUMPY else ImportError):
                self.hero.make(path, Path(tmp) / "docs" / "assets" / "x", quiet=True)


@unittest.skipUnless(HAVE_NUMPY, "needs numpy and Pillow")
class RenderTest(unittest.TestCase):
    def setUp(self):
        # Recipes name their input pictures from the repository root, where hero.py is run.
        here = os.getcwd()
        os.chdir(ROOT)
        self.addCleanup(os.chdir, here)

    def test_every_scene_renders_small_and_the_same_twice(self):
        import numpy as np

        import hero
        for path in sorted((MEDIA / "recipes").glob("*.json")):
            recipe = hero.load_recipe(path)
            with self.subTest(recipe=path.name):
                a = np.asarray(hero.render_source(recipe, (120, 40), lambda m: None))
                self.assertEqual(a.shape, (40, 120, 3))
                self.assertGreater(a.std(), 1.0, "a blank picture")
                if path.name == "umbilicus.json":
                    b = np.asarray(hero.render_source(recipe, (120, 40), lambda m: None))
                    self.assertTrue(np.array_equal(a, b), "the same recipe and seed must give the same pixels")

    def test_grade_keeps_the_palette_range(self):
        import numpy as np

        import hero
        from scene import SHADOW
        out = hero.grade(np.zeros((20, 60, 3), np.float32))
        self.assertTrue(np.all(out >= SHADOW * 0.8 - 1e-6), "black lifts toward a warm charcoal, never pure black")
        self.assertTrue(np.all(out[..., 0] >= out[..., 2]), "the field reads warm, as the reference does")
        self.assertTrue(np.all(hero.grade(np.full((20, 60, 3), 50.0, np.float32)) <= 1.0))

    def test_card_is_1200_by_630(self):
        from PIL import Image

        import hero
        if not hero.find_font("Inter*SemiBold.otf") and not hero.find_font("Inter*.ttf"):
            self.skipTest("no Inter font")
        recipe = hero.load_recipe(MEDIA / "recipes" / "umbilicus.json")
        card = hero.make_card(Image.new("RGB", (3840, 1280), (40, 40, 40)), recipe)
        self.assertEqual(card.size, (1200, 630))

    def test_sweep_frames(self):
        import sweep
        self.assertTrue(all(0.2 < sweep.radius_at(z) <= 1.0 for z in (0, 0.5, 1)))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sweep.main(["--out-dir", tmp, "--frames", "2", "--width", "96", "--height", "64"]), 0)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["frame-00000.png", "frame-00001.png"])


@unittest.skipUnless(HAVE_NUMPY and HAVE_FFMPEG, "needs numpy, Pillow, ffmpeg and gifsicle")
class EncodeTest(unittest.TestCase):
    def test_frames_become_an_mp4_and_a_gif_with_one_sidecar(self):
        from PIL import Image

        import encode
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp) / "frames"
            frames.mkdir()
            for i in range(6):
                Image.new("RGB", (64, 48), (20 + 30 * i, 40, 60)).save(frames / f"frame-{i:05d}.png")
            meta = Path(tmp) / "meta.json"
            meta.write_text(json.dumps(dict(GOOD, label="Synthetic demo", caption="Synthetic demo: colors.")))
            out = Path(tmp) / "out"
            code = encode.main([str(frames), "--fps", "6", "--gif-fps", "6", "--gif-width", "64", "--mp4",
                                str(out / "clip.mp4"), "--gif", str(out / "clip.gif"), "--meta", str(meta)])
            self.assertEqual(code, 0)
            rec = json.loads((out / "clip.json").read_text())
            self.assertEqual(sorted(o["file"] for o in rec["outputs"]), ["clip.gif", "clip.mp4"])
            self.assertEqual(rec["label"], "Synthetic demo")
            self.assertNotIn(str(frames), rec["command"], "the sidecar names the frames folder FRAMES, not its path")
            self.assertTrue(rec["command"].startswith("python scripts/media/encode.py FRAMES "))
            code = encode.main([str(frames), "--fps", "6", "--gif-fps", "6", "--gif-width", "64", "--dither", "none",
                                "--gif", str(out / "flat.gif"), "--meta", str(meta),
                                "--made-with", "python scripts/media/sweep.py --out-dir FRAMES --frames 6"])
            self.assertEqual(code, 0)
            rec = json.loads((out / "flat.json").read_text())
            self.assertTrue(rec["command"].startswith("python scripts/media/sweep.py --out-dir FRAMES --frames 6 && "
                                                      "python scripts/media/encode.py FRAMES "))
            self.assertNotIn("--made-with", rec["command"])
            self.assertEqual(rec["tool"]["scripts"], ["common.py", "encode.py", "sweep.py"])
            self.assertEqual(encode.main([str(Path(tmp) / "nothing"), "--gif", str(out / "x.gif")]), 2)

    def test_frame_names_must_be_numbered(self):
        import encode
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "first.png").write_bytes(b"x")
            with self.assertRaises(common.MediaError):
                encode.frames_input(tmp, 12)


class CaptureTest(unittest.TestCase):
    def test_actions_are_checked(self):
        import capture_web
        capture_web.check_actions([{"wait": 10}, {"frames": 2, "every": 50}, {"goto": "http://127.0.0.1:1/"}])
        for bad in ({"wait": 1}, [{"jump": 1}], [{}], [{"every": 50}]):
            with self.subTest(actions=bad), self.assertRaises(capture_web.CaptureError):
                capture_web.check_actions(bad)
        self.assertEqual(capture_web.page_url("about:blank"), "about:blank")
        # real-time frames: each output frame is the last screenshot taken by its time; slow shots repeat frames
        self.assertEqual(capture_web.pick_timed([0.0, 0.1, 0.3, 0.5, 0.75, 0.8], 4, 0.25), [0, 1, 3, 4])
        self.assertEqual(capture_web.pick_timed([0.0, 1.0], 3, 0.25), [0, 0, 0])
        with self.assertRaises(capture_web.CaptureError):
            capture_web.capture("about:blank", ROOT / "docs" / "assets" / "never-written", [{"frame": 1}])
        self.assertFalse((ROOT / "docs" / "assets" / "never-written").exists())
        with self.assertRaises(capture_web.CaptureError):
            capture_web.page_url("/no/such/page.html")

    @unittest.skipUnless(HAVE_PLAYWRIGHT and HAVE_NUMPY, "needs playwright and Pillow")
    def test_a_slider_tween_gives_one_frame_per_step(self):
        import capture_web
        from PIL import Image
        html = ("<!doctype html><body style='margin:0;background:#171A1C'><input id=r type=range min=0 max=10 "
                "value=0 style='width:200px'><div id=b style='width:0;height:20px;background:#B77A54'></div><script>"
                "r.oninput=()=>b.style.width=(r.value*20)+'px'</script>")
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "p.html"
            page.write_text(html)
            try:
                res = capture_web.capture(page, Path(tmp) / "f", [{"tween": {"selector": "#r", "from": 0, "to": 10,
                                                                             "n": 3}}, {"hold": 2}], 240, 60)
            except capture_web.CaptureError as exc:
                self.skipTest(f"no Chromium: {exc}")
            self.assertEqual(res["frames"], 5)
            first, last = (Image.open(Path(tmp) / "f" / f"frame-0000{i}.png") for i in (0, 2))
            self.assertNotEqual(first.tobytes(), last.tobytes(), "the slider moved between frames")
            # the drawn pointer: it moves to a button, taps it (a ring), drags the slider and scrolls smoothly
            steps = [{"cursor": "show"}, {"point": {"selector": "#r", "n": 3}}, {"tap": {"selector": "#r", "n": 2}},
                     {"glide": {"selector": "#r", "from": 0, "to": 10, "n": 3}},
                     {"scrollto": {"selector": "#b", "offset": 0, "n": 2}}, {"cursor": "hide"}, {"frame": 1}]
            res = capture_web.capture(page, Path(tmp) / "g", steps, 240, 60)
            self.assertEqual(res["frames"], 11)
            a, b = (Image.open(Path(tmp) / "g" / f"frame-0000{i}.png").convert("RGB") for i in (0, 2))
            self.assertNotEqual(a.tobytes(), b.tobytes(), "the pointer moved")


if __name__ == "__main__":
    unittest.main()
