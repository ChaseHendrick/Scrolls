"""AutoPipeline's trace methods (kit/autopipe.py register_trace_method): a plan that does not name one keeps its
digest, a plan that names one freezes its settings and resolved part, and a plan naming one this kit lacks is
refused rather than traced with the plain tool."""

import unittest

from test_autopipe import catalog

from kit import autopipe


class Doubler:
    name = "testdouble"
    defaults = {"factor": 2}
    traced = []

    @staticmethod
    def check(s):
        if s["trace"]["testdouble"]["factor"] < 1:
            raise autopipe.AutoError("trace.testdouble.factor is at least 1")

    @staticmethod
    def resolved(s):
        return {"testdouble_rule": "r1"}

    @staticmethod
    def trace(run, sid, args):
        Doubler.traced.append(sid)
        return {"exit": 1, "surfaces": [], "testdouble": {"sid": sid}}


class TestTraceMethods(unittest.TestCase):
    def setUp(self):
        self.saved = dict(autopipe.TRACE_METHODS), dict(autopipe.OPTIONAL)

    def tearDown(self):
        autopipe.TRACE_METHODS.clear()
        autopipe.TRACE_METHODS.update(self.saved[0])
        autopipe.OPTIONAL.clear()
        autopipe.OPTIONAL.update(self.saved[1])

    def plan(self, settings=None):
        return autopipe.make_plan("PHercTest", settings, cat=catalog(), created="2026-10-12T00:00:00Z")

    def test_registering_a_method_leaves_other_plans_and_their_digests_alone(self):
        before = self.plan()["digest"]
        autopipe.register_trace_method(Doubler)
        self.assertEqual(self.plan()["digest"], before)
        self.assertEqual(self.plan({"trace": {"testdouble": None}})["digest"], before)
        self.assertNotIn("testdouble", autopipe.DEFAULTS["trace"])

    def test_a_plan_that_asks_for_it_freezes_its_settings_and_resolved_part(self):
        autopipe.register_trace_method(Doubler)
        on = self.plan({"trace": {"testdouble": True}})
        self.assertEqual(on["settings"]["trace"]["testdouble"], {"factor": 2})
        self.assertEqual(on["resolved"]["testdouble_rule"], "r1")
        self.assertNotEqual(on["digest"], self.plan()["digest"])
        self.assertIs(autopipe.trace_method(on["settings"]), Doubler)
        with self.assertRaisesRegex(autopipe.AutoError, "at least 1"):
            self.plan({"trace": {"testdouble": {"factor": 0}}})

    def test_a_method_this_kit_lacks_is_refused(self):
        autopipe.register_trace_method(Doubler)
        s = self.plan({"trace": {"testdouble": True}})["settings"]
        del autopipe.TRACE_METHODS["testdouble"]
        with self.assertRaisesRegex(autopipe.AutoError, "no trace method testdouble"):
            autopipe.trace_method(s)

    def test_without_the_method_its_setting_is_unknown(self):
        with self.assertRaisesRegex(autopipe.AutoError, "unknown plan setting trace.testdouble"):
            self.plan({"trace": {"testdouble": True}})

    def test_repeats_is_not_a_method(self):
        s = self.plan({"trace": {"repeats": 2}})["settings"]
        self.assertIsNone(autopipe.trace_method(s))

    def test_the_run_calls_the_method_and_keeps_its_summary(self):
        autopipe.register_trace_method(Doubler)
        run = autopipe.Run.__new__(autopipe.Run)
        run.s = self.plan({"trace": {"testdouble": True}})["settings"]
        Doubler.traced.clear()
        self.assertEqual(run.trace_call("t00", {})["testdouble"], {"sid": "t00"})
        self.assertEqual(Doubler.traced, ["t00"])


if __name__ == "__main__":
    unittest.main()
