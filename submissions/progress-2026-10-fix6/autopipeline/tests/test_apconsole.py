"""The AutoPipeline monitor's console (kit/apconsole.py) and its token-guarded routes on the monitor server."""

import http.client
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_autopipe_monitor import plan_doc
from kit import apconsole, vc3d_agent
from kit import autopipe_monitor as mon


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / "runs" / "r1"
        self.run.mkdir(parents=True)
        plan = plan_doc(purpose="smoke")
        (self.run / "plan.json").write_text(json.dumps(plan))
        self.surface = self.root / "t00"
        self.surface.mkdir()
        (self.run / "state.json").write_text(json.dumps({"plan_digest": plan["digest"], "stages": {},
                                                         "surfaces": {"t00": {"surface": str(self.surface)},
                                                                      "t01": {"surface": "traces/t01"}}}))
        self.ctx = vc3d_agent.Context(root=self.root / "kit")
        self.addCleanup(self.ctx.close)


class TestParse(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(apconsole.parse("kit doctor --json"), ("kit", {"args": ["doctor", "--json"]}))
        self.assertEqual(apconsole.parse("python3 -m kit prizes"), ("kit", {"args": ["prizes"]}))
        self.assertEqual(apconsole.parse("ap status 'my run'"), ("kit", {"args": ["autopipeline", "status", "my run"]}))
        self.assertEqual(apconsole.parse("autopipeline run R"),
                         ("kit", {"args": ["autopipeline", "run", "R"], "timeout": apconsole.RUN_TIMEOUT}))
        self.assertEqual(apconsole.parse('app_open surfaces=["/a b"] display=true background=true'),
                         ("app_open", {"surfaces": ["/a b"], "display": True}))
        self.assertEqual(apconsole.parse('inspect {"path": "/x"}'), ("inspect", {"path": "/x"}))
        self.assertEqual(apconsole.parse("inspect path=/x level=2"), ("inspect", {"path": "/x", "level": 2}))
        self.assertEqual(apconsole.parse("inspect path={surface}"), ("inspect", {"path": "{surface}"}))
        self.assertEqual(apconsole.parse("check_surface surface='/a b' volume=\"v 1\" frame_search=false"),
                         ("check_surface", {"surface": "/a b", "volume": "v 1", "frame_search": False}))

    def test_refusals(self):
        for line in ("", "   ", "kit", "ap", "nosuch x=1", "inspect {bad json", "inspect [1]", "inspect path",
                     "kit 'unclosed", "inspect path='/x", 'inspect a=[1]b', "x" * 9000):
            with self.subTest(line=line[:20]), self.assertRaises(apconsole.ConsoleError):
                apconsole.parse(line)

    def test_fill(self):
        got = apconsole.fill({"surfaces": ["{surface}"], "args": ["status", "{run}/x"]}, {"run": "/r", "surface": "/s"})
        self.assertEqual(got, {"surfaces": ["/s"], "args": ["status", "/r/x"]})
        with self.assertRaises(apconsole.ConsoleError):
            apconsole.fill(["{surface}"], {"run": "/r", "surface": None})


class TestNotesAndJobs(Base):
    def test_notes(self):
        self.assertEqual(apconsole.read_notes(self.ctx, self.run)["text"], "")
        rec = apconsole.save_notes(self.ctx, self.run, "first look: t00 fine")
        self.assertEqual(rec["text"], "first look: t00 fine")
        path = apconsole.notes_path(self.ctx, self.run)
        self.assertTrue(path.is_file())
        self.assertFalse(path.is_relative_to(self.run))
        # another folder with the same name keeps its own notes
        other = self.root / "elsewhere" / "r1"
        other.mkdir(parents=True)
        self.assertNotEqual(apconsole.notes_path(self.ctx, other), path)
        with self.assertRaises(apconsole.ConsoleError):
            apconsole.save_notes(self.ctx, self.run, "x" * (apconsole.NOTES_MAX + 1))
        with self.assertRaises(apconsole.ConsoleError):
            apconsole.save_notes(self.ctx, self.run, 7)
        self.assertEqual(apconsole.read_notes(self.ctx, self.run)["text"], "first look: t00 fine")
        apconsole.save_notes(self.ctx, self.run, "  \n")
        self.assertFalse(path.exists())

    def test_run_list_and_refuse_foreign_jobs(self):
        for line in ("kit run local -- ls", "kit vc3d mcp", "inspect level=x"):
            with self.subTest(line=line), self.assertRaises(apconsole.ConsoleError):
                apconsole.run(self.ctx, self.run, line)
        rec = apconsole.run(self.ctx, self.run, "inspect path={surface}", surface=self.surface)
        self.assertEqual((rec["tool"], rec["command"]), ("inspect", "inspect path={surface}"))
        spec = json.loads((vc3d_agent.job_dir(self.ctx, rec["job"]) / "job.json").read_text())
        self.assertEqual(spec["args"], {"path": str(self.surface)})
        info = vc3d_agent.job_wait(self.ctx, rec["job"], timeout=60)
        self.assertEqual(info["status"], "succeeded", info.get("log_tail"))
        rows = apconsole.jobs(self.ctx, self.run)
        self.assertEqual([(r["job"], r["command"]) for r in rows], [(rec["job"], "inspect path={surface}")])
        detail = apconsole.job(self.ctx, self.run, rec["job"])
        self.assertIsInstance(detail["result"], str)
        # a job of the same kit home that this run's console did not start is not shown or cancelled through it
        other = vc3d_agent.submit_job(self.ctx, "guide", {})
        for fn in (apconsole.job, apconsole.cancel):
            with self.subTest(fn=fn.__name__), self.assertRaises(apconsole.ConsoleError):
                fn(self.ctx, self.run, other["job"])
        vc3d_agent.job_wait(self.ctx, other["job"], timeout=60)

    def test_cancel(self):
        # a monitor of the run serves until it is stopped: a command that runs until cancelled
        rec = apconsole.run(self.ctx, self.run, "ap monitor {run} --port 0 --read-only")
        time.sleep(1.0)
        self.assertEqual(vc3d_agent.job_info(self.ctx, rec["job"])["status"], "running")
        self.assertEqual(apconsole.cancel(self.ctx, self.run, rec["job"]), {"job": rec["job"], "status": "cancelled",
                                                                           "cancelled": True})
        self.assertEqual(apconsole.jobs(self.ctx, self.run)[0]["status"], "cancelled")


class TestServer(Base):
    def setUp(self):
        super().setUp()
        self.mon = mon.serve(self.run, port=0, ctx=self.ctx).start()
        self.addCleanup(self.mon.stop, 0)

    def req(self, method, path, body=None, token=True, ctype="application/json", origin=None, server=None):
        server = server or self.mon
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
        headers = {}
        if token:
            headers["X-AP-Token"] = server.token if token is True else token
        if ctype and body is not None:
            headers["Content-Type"] = ctype
        if origin:
            headers["Origin"] = origin
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        try:
            return r.status, json.loads(data)
        except json.JSONDecodeError:
            return r.status, data

    def test_page_carries_the_token_and_snapshot_does_not(self):
        status, html = self.req("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.mon.token.encode(), html)
        out = self.root / "snap.html"
        apconsole.save_notes(self.ctx, self.run, "private thought")
        mon.snapshot(self.run, out, ctx=self.ctx)
        text = out.read_text()
        self.assertNotIn(self.mon.token, text)
        self.assertNotIn("private thought", text)
        mon.snapshot(self.run, out, ctx=self.ctx, notes=True)
        self.assertIn("private thought", out.read_text())

    def test_token_origin_and_content_type(self):
        self.assertEqual(self.req("GET", "/api/console", token=False)[0], 403)
        self.assertEqual(self.req("GET", "/api/console", token="wrong")[0], 403)
        self.assertEqual(self.req("POST", "/api/notes", {"text": "x"}, token=False)[0], 403)
        self.assertEqual(self.req("POST", "/api/notes", {"text": "x"}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.req("POST", "/api/notes", {"text": "x"}, ctype="text/plain")[0], 415)
        self.assertEqual(self.req("POST", "/", {"text": "x"})[0], 405)
        self.assertEqual(apconsole.read_notes(self.ctx, self.run)["text"], "")
        status, rec = self.req("POST", "/api/notes", {"text": "seen"}, origin=f"http://127.0.0.1:{self.mon.port}")
        self.assertEqual((status, rec["text"]), (200, "seen"))
        status, got = self.req("GET", "/api/console")
        self.assertEqual((status, got["notes"]["text"], got["jobs"]), (200, "seen", []))

    def test_run_with_a_surface(self):
        status, rec = self.req("POST", "/api/run", {"command": "inspect path={surface}", "surface": "t00"})
        self.assertEqual(status, 200, rec)
        vc3d_agent.job_wait(self.ctx, rec["job"], timeout=60)
        status, job = self.req("GET", "/api/job?id=" + rec["job"])
        self.assertEqual((status, job["status"]), (200, "succeeded"))
        self.assertEqual(self.req("POST", "/api/run", {"command": "inspect path={surface}", "surface": "zz"})[0], 400)
        self.assertEqual(self.req("POST", "/api/run", {"command": "inspect path={surface}"})[0], 400)
        self.assertEqual(self.req("GET", "/api/job?id=../../etc")[0], 400)
        self.assertEqual(self.mon.surface_path("t01"), self.run / "traces" / "t01")

    def test_read_only_server(self):
        ro = mon.serve(self.run, port=0, console=False, ctx=self.ctx).start()
        self.addCleanup(ro.stop, 0)
        self.assertEqual(self.req("POST", "/api/notes", {"text": "x"}, server=ro)[0], 405)
        self.assertEqual(self.req("GET", "/api/console", server=ro)[0], 403)
        status, html = self.req("GET", "/", token=False, server=ro)
        self.assertNotIn(ro.token.encode(), html)
        wide = mon.Monitor(self.run, host="0.0.0.0", port=0)       # not a loopback address: off unless asked
        self.addCleanup(wide.httpd.server_close)
        self.assertFalse(wide.console)
        self.assertFalse(wide.console_page()["on"])


if __name__ == "__main__":
    unittest.main()
