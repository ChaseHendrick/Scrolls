"""Actual browser controls on synthetic run records; optional Playwright + Chromium, no downloads."""

import importlib.util
import json
import shlex
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_autopipe_monitor import Folder, T0, stage, surface
from kit import apconsole, vc3d_agent
from kit import autopipe_monitor as mon


CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser")
HAVE_BROWSER = CHROMIUM and importlib.util.find_spec("playwright") is not None


@unittest.skipUnless(HAVE_BROWSER, "optional Playwright and system Chromium are required")
class TestMonitorControls(Folder):
    def setUp(self):
        super().setUp()
        # A real shell argument containing spaces, a quote and command substitutions, never executed.
        self.d = self.d.rename(self.d.with_name("run ' $(touch NO) `echo NO`"))
        self.write_plan()
        self.stages = self.stages_through("seeds")
        self.stages["trace"] = stage("failed", T0, 12, error="missing <tool> & input", kind="infrastructure")
        self.write_state(self.stages)
        events = [dict(t=T0, stage="seeds", event="done"),
                  dict(t=T0 + 1, stage="trace", msg="Looking for normal grids"),
                  dict(t=T0 + 2, stage="trace", event="failed", error="missing <tool> & input")]
        (self.d / mon.EVENTS).write_text("".join(json.dumps(e) + "\n" for e in events))
        self.before = {p.name: p.read_bytes() for p in self.d.iterdir() if p.is_file()}
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.chromium.launch(executable_path=CHROMIUM, headless=True,
                                             args=["--no-sandbox"])
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={"width": 1200, "height": 900})
        self.errors = []
        self.page.on("pageerror", lambda err: self.errors.append(str(err)))
        self.requests = []
        self.page.on("request", lambda req: self.requests.append((req.method, req.url)))
        self.ctx = vc3d_agent.Context(root=self.d.parent / "kit")
        self.addCleanup(self.ctx.close)
        self.monitor = mon.serve(self.d, port=0, ctx=self.ctx).start()
        self.addCleanup(self.monitor.stop, 0)
        self.page.goto(self.monitor.url)
        self.page.wait_for_function("() => document.querySelector('#log-count').textContent.includes('3 of 3')")

    def tearDown(self):
        self.assertEqual(self.errors, [])
        # only this server, and nothing but GET outside the console's own requests
        self.assertTrue(all(url.startswith(self.monitor.url) and
                            (method == "GET" or url.startswith(self.monitor.url + "api/"))
                            for method, url in self.requests), self.requests)
        super().tearDown()

    def refresh(self):
        self.page.locator("#refresh-now").click()
        self.page.wait_for_function("() => !document.querySelector('#refresh-now').disabled")

    def test_keyboard_stage_search_failure_filter_and_clear_preserve_records(self):
        self.page.locator('[data-stage="trace"]').focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(self.page.locator("#stage-filter").input_value(), "trace")
        self.assertIn("missing <tool> & input", self.page.locator("#stage-detail").inner_text())
        self.assertIn("2 of 3", self.page.locator("#log-count").inner_text())
        self.page.locator('[data-stage="trace"]').focus()
        self.page.locator("#refresh-now").evaluate("e => e.click()")
        self.page.wait_for_function("() => !document.querySelector('#refresh-now').disabled")
        self.assertEqual(self.page.evaluate("document.activeElement.dataset.stage"), "trace")
        self.page.locator("#log-kind").select_option("failures")
        self.assertIn("1 of 3", self.page.locator("#log-count").inner_text())
        self.page.locator("#log-search").fill("does not exist")
        self.assertIn("No loaded log lines match", self.page.locator("#log").inner_text())
        self.page.locator("#clear-filters").click()
        self.assertIn("3 of 3", self.page.locator("#log-count").inner_text())
        self.assertEqual(self.before, {p.name: p.read_bytes() for p in self.d.iterdir() if p.is_file()})

    def test_pause_manual_refresh_and_resume_keep_filters(self):
        self.page.locator("#pause-view").click()
        self.assertIn("Viewer paused", self.page.locator("#livetext").inner_text())
        self.page.locator("#stage-filter").select_option("trace")
        self.page.locator("#log-search").fill("tool")
        self.stages["trace"]["error"] = "updated tool failure"
        self.write_state(self.stages)
        self.page.wait_for_timeout(2300)
        self.assertNotIn("updated tool failure", self.page.locator("#stage-detail").inner_text())
        self.refresh()
        self.assertIn("updated tool failure", self.page.locator("#stage-detail").inner_text())
        self.assertIn("Viewer paused", self.page.locator("#livetext").inner_text())
        self.assertEqual(self.page.locator("#stage-filter").input_value(), "trace")
        self.assertEqual(self.page.locator("#log-search").input_value(), "tool")
        self.page.locator("#pause-view").click()
        self.page.wait_for_function("() => !document.querySelector('#refresh-now').disabled")
        self.assertNotIn("Viewer paused", self.page.locator("#livetext").inner_text())

    def files_tab(self):
        self.page.locator("#tab-con-files").click()

    def test_commands_round_trip_hostile_path_and_clipboard_failure(self):
        self.files_tab()
        self.page.locator("#status-command").click()
        args = shlex.split(self.page.locator("#command-text").input_value())
        self.assertEqual(args, ["scrolls-kit", "autopipeline", "status", str(self.d)])
        self.page.locator("#resume-command").click()
        args = shlex.split(self.page.locator("#command-text").input_value())
        self.assertEqual(args, ["scrolls-kit", "autopipeline", "run", str(self.d)])
        self.page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('denied'))}})")
        self.page.locator("#copy-command").click()
        self.page.wait_for_function("() => document.querySelector('#copy-message').textContent.includes('selected')")
        self.assertEqual(self.page.locator("#command-text").evaluate("e => e.selectionEnd - e.selectionStart"),
                         len(self.page.locator("#command-text").input_value()))
        self.write_state(self.stages_through("seeds"), running=self.running("trace", started=T0))
        self.refresh()
        self.assertTrue(self.page.locator("#resume-command").is_disabled())
        self.assertEqual(self.page.locator("#command-text").input_value(), "")
        self.assertTrue(self.page.locator("#copy-command").is_disabled())

    def test_hanging_refresh_expires_resume_command_and_allows_manual_recovery(self):
        self.page.clock.install()
        self.page.reload()
        self.page.wait_for_function("() => document.querySelector('#log-count').textContent.includes('3 of 3')")
        held = []
        self.page.route("**/summary.json", lambda route: held.append(route))
        self.files_tab()
        self.page.locator("#resume-command").click()
        self.page.locator("#refresh-now").click()
        self.page.wait_for_function("() => document.querySelector('#refresh-now').disabled")
        self.page.clock.fast_forward(31000)
        self.page.wait_for_function("() => !document.querySelector('#refresh-now').disabled")
        self.assertTrue(self.page.locator("#resume-command").is_disabled())
        self.assertTrue(self.page.locator("#copy-command").is_disabled())
        self.assertEqual(self.page.locator("#command-text").input_value(), "")
        for route in held:
            route.abort()
        self.page.unroute("**/summary.json")
        self.refresh()
        self.assertFalse(self.page.locator("#resume-command").is_disabled())

    def test_snapshot_privacy_mobile_and_no_network(self):
        self.page.close()
        self.page = self.browser.new_page(viewport={"width": 375, "height": 812})
        self.page.on("pageerror", lambda err: self.errors.append(str(err)))
        requests = []
        self.page.on("request", lambda req: requests.append(req.url))
        out = self.d.parent / "snapshot.html"
        mon.snapshot(self.d, out)
        html = out.read_text()
        self.assertNotIn(str(self.d), html)
        self.page.set_content(html)
        for name in ("pause-view", "refresh-now", "status-command", "resume-command", "copy-command"):
            self.assertTrue(self.page.locator("#" + name).is_disabled(), name)
        self.page.locator("#inspect-problem").click()
        self.assertIn("missing <tool>", self.page.locator("#stage-detail").inner_text())
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 375)
        self.assertEqual(requests, [])

    def test_own_rule_failure_and_unreadable_files_are_not_recoverable_success(self):
        self.stages["trace"]["kind"] = "ours"
        self.write_state(self.stages)
        (self.d / "report.json").write_text("not json")
        self.refresh()
        self.page.locator("#inspect-problem").click()
        self.assertIn("do not erase the failure", self.page.locator("#stage-detail").inner_text())
        self.files_tab()
        self.assertTrue(self.page.locator("#resume-command").is_disabled())
        self.assertIn("Unreadable / refused", self.page.locator("#run-files").inner_text())
        self.assertIn("Not recorded", self.page.locator("#run-files").inner_text())

    def test_console_notes_and_a_job(self):
        self.assertIn("console on this machine", self.page.locator("#brand-sec").inner_text())
        self.page.locator("#tab-con-notes").click()
        self.page.locator("#notes").fill("check t00 in VC3D\nsheet switch near the hole?")
        self.page.locator("#tab-con-tools").click()     # leaving the box saves at once
        self.page.wait_for_function("() => document.querySelector('#notes-msg').textContent.startsWith('Saved')")
        self.assertEqual(apconsole.read_notes(self.ctx, self.d)["text"], "check t00 in VC3D\nsheet switch near the hole?")
        self.assertFalse(apconsole.notes_path(self.ctx, self.d).is_relative_to(self.d))
        # quick actions on a surface stay off with no surface; AP status runs as a job and shows in Log, Jobs
        self.assertTrue(self.page.locator('#quick [data-command^="app_open"]').first.is_disabled())
        self.page.locator("#con-input").fill("no_such_tool x=1")
        self.page.locator("#con-run").click()
        self.page.wait_for_function("() => document.querySelector('#con-msg').textContent.startsWith('Not started')")
        self.page.locator("#con-input").fill("guide topic=Troubleshooting")
        self.page.locator("#con-run").click()
        self.page.wait_for_function("() => document.querySelector('#con-msg').textContent.startsWith('Started job')")
        self.assertEqual(self.page.locator("#tab-jobs").get_attribute("aria-pressed"), "true")
        self.page.wait_for_function("() => document.querySelector('#jobs .jobrow .chip').textContent === 'Succeeded'",
                                    timeout=60000)
        self.page.wait_for_function("() => document.querySelector('#joblog').textContent.includes('result:')")
        self.assertIn("guide topic=Troubleshooting", self.page.locator("#jobs").inner_text())
        self.assertEqual(len(apconsole.jobs(self.ctx, self.d)), 1)
        self.page.reload()                               # notes come back from the server
        self.page.wait_for_function("() => document.querySelector('#notes').value.includes('sheet switch')")
        self.assertEqual(self.before, {p.name: p.read_bytes() for p in self.d.iterdir() if p.is_file()})

    def test_qa_inspector_uses_recorded_surface_failure_without_claiming_localization(self):
        stages = self.stages_through("trace")
        stages["qa"] = stage("failed", T0, 1, error="no surface passed", kind="ours")
        self.write_state(stages, {"t00": surface("t00", accepted=False, reasons=["self-intersection"], ink=False)})
        self.refresh()
        self.page.locator("#inspect-problem").click()
        text = self.page.locator("#stage-detail").inner_text()
        self.assertIn("self-intersection", text)
        self.assertIn("VC3D", text)
        self.assertIn("do not identify which region needs repair", text)
