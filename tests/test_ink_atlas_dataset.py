"""Tests for spaces/ink-atlas/dataset: the index builder and the upload guard, on a fake atlas (no network)."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "spaces" / "ink-atlas" / "dataset"
sys.path.insert(0, str(HERE))
import build_index  # noqa: E402
import publish  # noqa: E402

MODELS = ("ink_9um-s42", "hecate-9.6")


def fake_atlas(root):
    sid, path = "kbh-PHerc0000_1_2_3", "surfaces/PHerc0000/kbh-PHerc0000_1_2_3"
    files = ["ensemble/forward.png", "ensemble/reverse.png", "ensemble-rev/forward.png", "ensemble-rev/reverse.png",
             "maps/ink_9um-s42/c-4_s1_forward.png", "maps/ink_9um-s42/c+4_s1_reverse.png",
             "maps/hecate-9.6/c+0_s1_forward.png", "ct_mid.png", "preview.jpg"]
    live = {"verdict": "ALIVE", "metrics": {"p50": 0.3, "p99": 0.7, "spread_p99_p50": 0.4, "std": 0.1,
                                            "fraction_near_half": 0.05, "valid_pixels": 10}}
    meta = {"id": sid, "scroll": "PHerc0000", "role": "eligible", "source": "test", "scan": "1", "voxel_um": 8.64,
            "canvas_um": 9.6, "mesh": {"base": "https://example.org/mesh"}, "ct": "https://example.org/ct",
            "render": {"canvas_hw": [100, 200], "layers": 65, "rendered_px": 10000, "sha256": "ab"},
            "ensemble_png_z_range": [-2.0, 4.0], "files": files,
            "models": {"ink_9um-s42": {"alive": True, "liveness": {"c-4_s1": {"forward": live},
                                                                   "c+4_s1": {"reverse": dict(live, verdict="DEAD")}}},
                       "hecate-9.6": {"alive": False, "liveness": {}}}}
    (root / path).mkdir(parents=True)
    (root / path / "meta.json").write_text(json.dumps(meta))
    (root / path / "preview.jpg").write_bytes(b"jpg")
    (root / "atlas.json").write_text(json.dumps({"surfaces": [{"id": sid, "scroll": "PHerc0000",
                                                               "role": "eligible", "path": path}]}))
    return path


class BuildIndex(unittest.TestCase):
    def test_rows(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            path = fake_atlas(root)
            counts = build_index.build(root, root)
            self.assertEqual(counts, {"pictures": 9, "surfaces": 1, "maps": 3, "scrolls": 1})
            rows = [json.loads(x) for x in (root / "metadata.jsonl").read_text().splitlines()]
            self.assertEqual({r["file_name"] for r in rows}, {f"{path}/{f}" for f in json.loads(
                (root / path / "meta.json").read_text())["files"]})
            m = next(r for r in rows if r["file_name"].endswith("c-4_s1_forward.png"))
            self.assertEqual((m["model"], m["window"], m["window_offset_layers"], m["order"], m["alive"], m["p99"]),
                             ("ink_9um-s42", "c-4", -4, "forward", True, 0.7))
            dead = next(r for r in rows if r["file_name"].endswith("c+4_s1_reverse.png"))
            self.assertEqual((dead["window_offset_layers"], dead["alive"]), (4, False))
            hec = next(r for r in rows if r["model"] == "hecate-9.6")
            self.assertIsNone(hec["alive"])              # no liveness record: unknown, not alive
            ens = [r for r in rows if r["kind"] in ("ensemble", "ensemble-rev")]
            self.assertEqual({(r["kind"], r["stats_from"]) for r in ens},
                             {("ensemble", "forward"), ("ensemble-rev", "reverse")})
            self.assertTrue(all((r["value_min"], r["value_max"]) == (-2.0, 4.0) for r in ens))
            self.assertIn("c%2B4_s1_reverse.png", dead["url"])
            s = [json.loads(x) for x in (root / "surfaces/metadata.jsonl").read_text().splitlines()]
            self.assertEqual(s[0]["file_name"], "PHerc0000/kbh-PHerc0000_1_2_3/preview.jpg")
            self.assertEqual((s[0]["models_alive"], s[0]["area_cm2"]), (1, round(10000 * 9.6e-4 ** 2, 2)))
            with open(root / "index/maps.csv") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 9)

    def test_id_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            path = fake_atlas(root)
            meta = json.loads((root / path / "meta.json").read_text())
            meta["id"] = "other"
            (root / path / "meta.json").write_text(json.dumps(meta))
            with self.assertRaises(SystemExit):
                build_index.build(root, root)


class PublishGuard(unittest.TestCase):
    def stage(self, t, rels):
        for rel in rels:
            p = Path(t) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        return t

    def test_allows_index_and_card(self):
        with tempfile.TemporaryDirectory() as t:
            self.stage(t, ["README.md", "metadata.jsonl", "surfaces/metadata.jsonl", "index/maps.csv",
                           "assets/hero.jpg"])
            got = [r for r, _, _ in publish.plan(t, {"README.md", "assets/gallery.jpg"})]
            self.assertEqual(len(got), 5)

    def test_allows_card_standard_files_and_replacing_them(self):
        with tempfile.TemporaryDirectory() as t:
            self.stage(t, ["provenance.json", "SHA256SUMS"])
            got = [r for r, _, _ in publish.plan(t, {"provenance.json", "SHA256SUMS"})]
            self.assertEqual(got, ["SHA256SUMS", "provenance.json"])

    def test_refuses_maps_and_overwrites(self):
        for rels, existing in ((["surfaces/PHerc0000/x/maps/m/c+0_s1_forward.png"], set()),
                               (["atlas.json"], {"atlas.json"}),
                               (["assets/gallery.jpg"], {"assets/gallery.jpg"})):
            with tempfile.TemporaryDirectory() as t:
                self.stage(t, rels)
                with self.assertRaises(SystemExit):
                    publish.plan(t, existing)


if __name__ == "__main__":
    unittest.main()
