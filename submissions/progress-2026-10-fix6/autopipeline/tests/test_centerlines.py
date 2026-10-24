"""Published center lines as AutoPipeline's axis source (kit/centerlines.py, umbilicus.source centerlines): the
pinned snapshot, the source order, the sha256 refusal, the backends shorthand and plan refusals, and a whole
umbilicus stage on the fake scroll. Fakes only: no network."""

import hashlib
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

import test_autopipe as TA

from kit import apbackends, autopipe, centerlines, vc3d_orient


def fake_data(lines):
    return {"dataset": centerlines.DATASET, "rev": centerlines.REV, "lines": lines}


def line(scan, source, sha="0" * 64, kind="person", usable=None):
    return {"scroll": "PHercTest", "scan": scan, "volume": f"{scan}-9.362um.zarr",
            "file": f"lines/PHercTest/PHercTest_{scan}_{source}_umbilicus.json", "source": source, "kind": kind,
            "licence": "MIT", "credit": "test", "sha256": sha, "points": 2, "z_min": 0.0, "z_max": 63.0,
            "usable_ends": usable}


class TestSnapshot(unittest.TestCase):
    def test_the_snapshot_covers_the_22_prize_scans_with_hashes(self):
        d = centerlines.load()
        self.assertEqual(d["rev"], centerlines.REV)
        self.assertEqual(len({l["scroll"] for l in d["lines"]}), 22)
        self.assertTrue(all(len(l["sha256"]) == 64 for l in d["lines"]))
        self.assertTrue({l["source"] for l in d["lines"]} <= set(centerlines.SOURCES))
        # every finder line says which ends to rely on; people's lines carry no end check
        self.assertTrue(all(l["usable_ends"] for l in d["lines"] if l["source"] == "finder"))

    def test_people_come_before_the_finder_and_the_order_is_the_plans(self):
        d = fake_data([line("S1", "finder", kind="model", usable="low"), line("S1", "tauil"), line("S1", "drobkov")])
        self.assertEqual(centerlines.pick("S1-9.362um.zarr", centerlines.DEFAULTS, d)["source"], "drobkov")
        own = {"rev": centerlines.REV, "prefer": ["finder", "drobkov"]}
        self.assertEqual(centerlines.pick("https://x/S1-9.362um.zarr/", own, d)["source"], "finder")
        self.assertIsNone(centerlines.pick("S2", centerlines.DEFAULTS, d))
        self.assertIsNone(centerlines.pick("S1", {"rev": centerlines.REV, "prefer": ["bucket"]}, d))

    def test_real_scans_pick_the_expected_source(self):
        d = centerlines.load()
        self.assertEqual(centerlines.pick("20250821151825", centerlines.DEFAULTS, d)["source"], "bucket")  # PHerc0125
        self.assertEqual(centerlines.pick("20250521120456", centerlines.DEFAULTS, d)["source"], "drobkov")  # PHerc1218
        self.assertEqual(centerlines.pick("20250521115057", centerlines.DEFAULTS, d)["source"], "finder")  # PHerc0175A

    def test_refusals(self):
        for bad, why in (({"rev": "main", "prefer": ["bucket"]}, "holds the dataset at"),
                         ({"rev": centerlines.REV, "prefer": []}, "list of different sources"),
                         ({"rev": centerlines.REV, "prefer": ["bucket", "bucket"]}, "list of different sources"),
                         ({"rev": centerlines.REV, "prefer": ["me"]}, "no source me"),
                         ({"rev": centerlines.REV}, "is {"), (True, "is {")):
            with self.assertRaisesRegex(centerlines.CenterlineError, why):
                centerlines.check(bad)

    def test_a_file_whose_hash_differs_is_refused_and_removed(self):
        tmp = Path(self.id().replace(".", "_"))
        tmp.mkdir(exist_ok=True)
        self.addCleanup(shutil.rmtree, tmp, True)
        body = b'{"control_points": []}'
        good = line("S1", "drobkov", sha=hashlib.sha256(body).hexdigest())

        def dl(url, dest):
            self.assertIn(f"/resolve/{centerlines.REV}/lines/PHercTest/", url)
            Path(dest).write_bytes(body)

        rec = centerlines.fetch(good, tmp / "a.json", dl)
        self.assertEqual((rec["source"], rec["line_source"], rec["line_kind"]), ("centerlines", "drobkov", "person"))
        with self.assertRaisesRegex(centerlines.CenterlineError, "sha256"):
            centerlines.fetch(line("S1", "drobkov", sha="f" * 64), tmp / "b.json", dl)
        self.assertFalse((tmp / "b.json").exists())


class TestPlans(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(centerlines, "load", return_value=fake_data([line("V1", "drobkov")]))
        p.start()
        self.addCleanup(p.stop)

    def plan(self, settings, cat=None):
        return autopipe.make_plan("PHercTest", settings, cat=cat or TA.catalog())

    def test_the_shorthand_names_the_pinned_snapshot(self):
        t = apbackends.translate
        self.assertEqual(t({"umbilicus": "centerlines"}), {"umbilicus": {"source": "centerlines", "centerlines": True}})
        self.assertEqual(t({"umbilicus": ["centerlines", "centrenet", "villa"]}),
                         {"umbilicus": {"source": "centerlines", "centerlines": True,
                                        "estimator": ["centrenet", "villa"]}})
        a = self.plan({"backends": {"umbilicus": "centerlines"}})
        b = self.plan({"umbilicus": {"source": "centerlines", "centerlines": True}})
        self.assertEqual(a["digest"], b["digest"])
        self.assertEqual(a["settings"]["umbilicus"]["centerlines"], centerlines.DEFAULTS)
        other = self.plan({"umbilicus": {"source": "centerlines",
                                         "centerlines": {"prefer": ["finder", "drobkov"]}}})
        self.assertNotEqual(other["digest"], a["digest"])
        # a plan that names no center lines keeps the settings it had
        self.assertNotIn("centerlines", self.plan({})["settings"]["umbilicus"])
        u = apbackends.in_effect("umbilicus", a["settings"])
        self.assertEqual((u["name"], u["kind"]), ("centerlines", "published"))
        rec = apbackends.in_effect("umbilicus", a["settings"], {"source": "centerlines", "line_source": "drobkov",
                                                                "line_kind": "person"})
        self.assertEqual((rec["kind"], rec["line_kind"]), ("published", "person"))

    def test_refusals(self):
        for bad, why in (({"backends": {"umbilicus": ["villa", "centerlines"]}}, "centerlines can only come first"),
                         ({"umbilicus": {"source": "centerlines"}}, "go together"),
                         ({"umbilicus": {"source": "estimate", "centerlines": True}}, "go together"),
                         ({"umbilicus": {"source": "centerlines", "centerlines": {"prefer": ["x"]}}}, "no source x"),
                         ({"umbilicus": {"source": "centerlines", "centerlines": {"rev": "main"}}},
                          "holds the dataset at")):
            with self.assertRaisesRegex(autopipe.AutoError, why):
                self.plan(bad)
        with mock.patch.object(centerlines, "load", return_value=fake_data([line("V9", "drobkov")])):
            with self.assertRaisesRegex(autopipe.AutoError, "has no line for V1"):
                self.plan({"backends": {"umbilicus": "centerlines"}})
            # with a fallback estimator the plan is made, and preflight says the estimate will run
            p = self.plan({"backends": {"umbilicus": ["centerlines", "normals"]}})
            row = apbackends.preflight(p)["rows"][0]
            self.assertEqual((row["stage"], row["line"]), ("umbilicus", None))
            self.assertEqual(row["chain"][0]["backend"], "normals")
        p = self.plan({"backends": {"umbilicus": "centerlines"}})
        row = apbackends.preflight(p)["rows"][0]
        self.assertEqual((row["backend"], row["line"]["source"]), ("centerlines", "drobkov"))


class TestStage(TA.TestRun):
    """umbilicus.source centerlines in a whole run on the fake scroll: the line fetched at the pinned revision, its
    hash checked, the record saying whose line it is."""

    def run_axis(self, sha):
        body = self.axis.read_bytes()
        data = fake_data([line("V1", "drobkov", sha=sha or hashlib.sha256(body).hexdigest())])
        seen = []

        def dl(url, dest, **kw):
            seen.append(url)
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(body)

        with mock.patch.object(centerlines, "load", return_value=data), mock.patch.object(autopipe, "download", dl):
            plan = self.plan(umbilicus={**autopipe.DEFAULTS["umbilicus"], "source": "centerlines",
                                        "centerlines": centerlines.DEFAULTS})
            st, out = self.run_plan(plan, until="umbilicus")
        return st, out, seen

    def test_the_stage_uses_the_scans_line(self):
        st, out, seen = self.run_axis(None)
        self.assertEqual(st["stages"]["umbilicus"]["status"], "done", st["stages"])
        rec = st["stages"]["umbilicus"]["record"]
        self.assertEqual((rec["source"], rec["line_source"], rec["rev"]), ("centerlines", "drobkov", centerlines.REV))
        self.assertEqual(seen, [centerlines.url(line("V1", "drobkov"))])
        self.assertEqual(vc3d_orient.load_umbilicus(str(out / "umbilicus.json"))[0][1:], (TA.AXIS[1], TA.AXIS[0]))

    def test_a_changed_file_fails_the_stage(self):
        st, _, _ = self.run_axis("e" * 64)
        self.assertEqual(st["stages"]["umbilicus"]["status"], "failed", st["stages"])
        self.assertIn("sha256", json.dumps(st["stages"]["umbilicus"]))


for _name in dir(TA.TestRun):      # TestStage borrows TestRun's fixtures, not its tests
    if _name.startswith("test_"):
        setattr(TestStage, _name, None)


if __name__ == "__main__":
    unittest.main()
