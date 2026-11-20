"""kit.hubcall: Hub calls back off on the rate limit, share one cool-down per machine, and a local log names the
busiest caller. The MockServer cases repeat the outside check of 20 Nov 2026 against a local HTTP server."""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from kit import hubcall as H


class Resp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}


class HubError(Exception):
    """Shaped like huggingface_hub's HfHubHTTPError: the status on .response."""

    def __init__(self, status, headers=None):
        super().__init__(f"{status} Client Error: Too Many Requests" if status == 429 else f"{status} error")
        self.response = Resp(status, headers)


class Clock:
    def __init__(self):
        self.t, self.slept = 1_000_000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {H.DIR_ENV: self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(H.LOG_ENV, None)
        self.clock = Clock()

    def flaky(self, errors, result="ok"):
        calls = []

        def fn(*a, **kw):
            calls.append((a, kw))
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            return result
        return fn, calls

    def run_call(self, fn, **kw):
        return H.call(fn, who="test", sleep=self.clock.sleep, clock=self.clock, jitter=lambda: 0.0, **kw)


class Detect(Base):
    def test_statuses_from_every_error_shape(self):
        self.assertTrue(H.is_rate_limited(HubError(429)))
        import urllib.error
        self.assertTrue(H.is_rate_limited(urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)))
        self.assertTrue(H.is_rate_limited(Exception("429 Client Error: Too Many Requests for url")))
        self.assertFalse(H.is_rate_limited(HubError(404)))
        self.assertTrue(H.is_transient(HubError(503)))
        self.assertTrue(H.is_transient(ConnectionError("reset")))
        self.assertFalse(H.is_transient(HubError(404)))
        self.assertEqual(H.retry_after(HubError(429, {"Retry-After": "7"})), 7.0)
        self.assertEqual(H.retry_after(HubError(429, {"Retry-After": "9999"})), H.MAX_RETRY_AFTER_S)
        self.assertIsNone(H.retry_after(HubError(429)))


class Call(Base):
    def test_a_429_waits_and_calls_again(self):
        fn, calls = self.flaky([HubError(429), HubError(429, {"Retry-After": "3"})])
        self.assertEqual(self.run_call(fn), "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.clock.slept, [5, 3])             # the backoff, then the server's Retry-After
        outcomes = [r["outcome"] for r in H.read_log()]
        self.assertEqual(outcomes, ["429", "429", "ok"])

    def test_it_gives_up_once_the_waits_pass_the_limit(self):
        fn, calls = self.flaky([HubError(429)] * 20)
        with self.assertRaises(HubError):
            self.run_call(fn, max_wait_s=40)
        self.assertLessEqual(sum(self.clock.slept), 40)
        self.assertIn("gave up after 429", H.read_log()[-1]["outcome"])

    def test_a_5xx_is_retried_twice_and_a_404_never(self):
        fn, calls = self.flaky([HubError(502), ConnectionError("reset")])
        self.assertEqual(self.run_call(fn), "ok")
        self.assertEqual(self.clock.slept, [2, 4])
        fn, calls = self.flaky([HubError(503)] * 3)
        with self.assertRaises(HubError):
            self.run_call(fn)
        fn, calls = self.flaky([HubError(404)])
        with self.assertRaises(HubError):
            self.run_call(fn)
        self.assertEqual(len(calls), 1)
        self.assertEqual(H.read_log()[-1]["outcome"], "error 404")

    def test_a_429_makes_every_process_on_the_machine_wait(self):
        fn, _ = self.flaky([HubError(429, {"Retry-After": "30"})])
        self.assertEqual(self.run_call(fn), "ok")
        self.clock.t -= 20                                     # another process, 10 s into the cool-down
        self.clock.slept.clear()
        other, calls = self.flaky([])
        self.assertEqual(self.run_call(other), "ok")
        self.assertEqual(self.clock.slept, [20])               # it waited out the cool-down before calling
        self.assertEqual(len(calls), 1)

    def test_inside_a_job_the_total_wait_is_shorter(self):
        with mock.patch.dict(os.environ, {"JOB_ID": "j1"}):
            os.environ.pop(H.WAIT_ENV, None)
            self.assertEqual(H.default_max_wait(), H.JOB_MAX_WAIT_S)
            fn, _ = self.flaky([HubError(429)] * 20)
            with self.assertRaises(HubError):
                self.run_call(fn)
            self.assertLessEqual(sum(self.clock.slept), H.JOB_MAX_WAIT_S)
        with mock.patch.dict(os.environ, {H.WAIT_ENV: "30"}):
            self.assertEqual(H.default_max_wait(), 30.0)

    def test_the_log_can_be_turned_off(self):
        os.environ[H.LOG_ENV] = "0"
        fn, _ = self.flaky([])
        self.run_call(fn)
        self.assertEqual(H.read_log(), [])


class Wrap(Base):
    def test_every_method_goes_through_call_and_listings_are_read_inside_it(self):
        class Api:
            token = "x"

            def __init__(self):
                self.n = 0

            def list_repo_tree(self, bid, prefix=""):
                self.n += 1
                if self.n == 1:
                    raise HubError(429)

                def gen():
                    yield "a"
                    yield "b"
                return gen()

        api = Api()
        w = H.wrap(api, "queue")
        self.assertIs(H.wrap(w, "again"), w)
        self.assertEqual(w.token, "x")
        with mock.patch.object(H.time, "sleep", self.clock.sleep), mock.patch.object(H.random, "random", lambda: 0):
            self.assertEqual(w.list_repo_tree("b", prefix="p"), ["a", "b"])
        self.assertEqual([(r["who"], r["method"], r["outcome"]) for r in H.read_log()],
                         [("queue", "list_repo_tree", "429"), ("queue", "list_repo_tree", "ok")])

    def test_a_write_is_retried_on_a_429_but_not_after_a_dropped_answer(self):
        class Api:
            def __init__(self):
                self.calls = []

            def upload_file(self, bid, add=None):
                self.calls.append(bid)
                raise [HubError(429), HubError(502)][len(self.calls) - 1]

        api = Api()
        w = H.wrap(api, "queue")
        with mock.patch.object(H.time, "sleep", self.clock.sleep), mock.patch.object(H.random, "random", lambda: 0):
            with self.assertRaises(HubError):
                w.upload_file("b", add=[])
        self.assertEqual(len(api.calls), 2)                    # the 429 retried once; the 502 raised at once
        self.assertEqual(H.read_log()[-1]["outcome"], "error 502")
        self.assertTrue(H.is_read("list_repo_tree"))
        self.assertFalse(H.is_read("create_commit"))


class Report(Base):
    def test_report_names_the_busiest_caller(self):
        log = Path(self.tmp.name) / "hubcalls.jsonl"
        rows = ([{"t": 1e9, "who": "progress", "method": "list_repo_tree", "outcome": "ok"}] * 5
                + [{"t": 1e9, "who": "queue", "method": "upload_file", "outcome": "429", "waited_s": 5}]
                + [{"t": 1e9, "who": "queue", "method": "upload_file", "outcome": "ok", "waited_s": 5}])
        log.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
        rep = H.report(H.read_log(log))
        self.assertEqual((rep[0]["who"], rep[0]["calls"]), ("progress", 5))
        self.assertEqual((rep[1]["rate_limited"], rep[1]["waited_s"]), (1, 10.0))
        with redirect_stdout(io.StringIO()) as o:
            self.assertEqual(H.main(["report", "--hours", "1e9", "--log", str(log), "--json"]), 0)
        self.assertEqual(json.loads(o.getvalue())["calls"], 7)


ROOT = Path(__file__).resolve().parent.parent


class _Mock(BaseHTTPRequestHandler):
    """A local Hub stand-in: each path answers from its script of actions in turn; the last one repeats."""
    script, seen, lock = {}, [], threading.Lock()
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _go(self):
        path = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        with _Mock.lock:
            _Mock.seen.append((time.time(), self.command, path))
            acts = _Mock.script.get(path) or [("status", 200, {})]
            act = acts.pop(0) if len(acts) > 1 else acts[0]
        if act[0] == "drop":
            self.close_connection = True
            try:
                self.connection.shutdown(2)
            except OSError:
                pass
            return
        _, code, headers = act
        body = b'{"ok": true}'
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = _go


def S(code, retry_after=None):
    return ("status", code, {"Retry-After": str(retry_after)} if retry_after is not None else {})


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url):
    with OPENER.open(url, timeout=5) as r:
        return r.read()


# One process of the shared cool-down case: URL WHO WAITFILE|- (WAITFILE: start after it exists, plus 0.5 s).
PROC = """import os, sys, time, urllib.request
url, who, wait = sys.argv[1:4]
from kit import hubcall
if wait != "-":
    t0 = time.time()
    while not os.path.exists(wait) and time.time() - t0 < 15:
        time.sleep(0.02)
    time.sleep(0.5)
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(u):
    with op.open(u, timeout=5) as r:
        return r.read()
hubcall.call(get, url, who=who, method="get_thing")
"""


class MockServer(Base):
    """Real HTTP 429s, Retry-After headers, 5xx answers and dropped connections from a loopback server."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Mock)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def case(self, acts, method="get_thing", retry_net=True, path="/x", **kw):
        with _Mock.lock:
            _Mock.script, _Mock.seen = {path: list(acts)}, []
        err, out = None, None
        try:
            out = self.run_call(lambda: get(self.base + path), method=method, retry_net=retry_net, **kw)
        except Exception as e:  # noqa: BLE001
            err = H.status_of(e)
        with _Mock.lock:
            n = sum(1 for s in _Mock.seen if s[2] == path)
        return n, list(self.clock.slept), err, out is not None

    def test_429_without_retry_after_backs_off(self):
        self.assertEqual(self.case([S(429), S(429), S(429), S(200)]), (4, [5, 10, 20], None, True))

    def test_retry_after_is_used_and_clipped(self):
        self.assertEqual(self.case([S(429, 3), S(429, 500), S(200)]), (3, [3, 300], None, True))

    def test_503_and_a_dropped_connection_are_retried_for_reads(self):
        self.assertEqual(self.case([S(503), ("drop",), S(200)]), (3, [2, 4], None, True))

    def test_three_503s_raise(self):
        self.assertEqual(self.case([S(503)]), (3, [2, 4], 503, False))

    def test_a_write_is_not_repeated_after_a_502(self):
        self.assertEqual(self.case([S(502), S(200)], method="create_thing", retry_net=False), (1, [], 502, False))

    def test_404_is_not_retried(self):
        self.assertEqual(self.case([S(404)]), (1, [], 404, False))

    def test_it_gives_up_at_the_total_wait(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(H.WAIT_ENV, None)
            os.environ.pop("JOB_ID", None)
            self.assertEqual(self.case([S(429)]), (9, [5, 10, 20, 40, 80, 120, 120, 120], 429, False))
            self.clock.slept.clear()
            os.environ["JOB_ID"] = "test-job"
            self.assertEqual(self.case([S(429)]), (5, [5, 10, 20, 40], 429, False))
        outcomes = [r["outcome"] for r in H.read_log()]
        self.assertIn("gave up after 429", outcomes)

    def test_never_429_is_one_request(self):
        self.assertEqual(self.case([S(200)]), (1, [], None, True))

    def test_the_mutant_that_never_sees_a_429_fails_the_backoff_bar(self):
        with mock.patch.object(H, "is_rate_limited", lambda e: False):
            got = self.case([S(429), S(429), S(429), S(200)])
        self.assertNotEqual(got, (4, [5, 10, 20], None, True))

    def two_processes(self, shared):
        da, db = Path(self.tmp.name) / "A", Path(self.tmp.name) / ("A" if shared else "B")
        da.mkdir(exist_ok=True)
        db.mkdir(exist_ok=True)
        with _Mock.lock:
            _Mock.script, _Mock.seen = {"/a": [S(429, 2), S(200)], "/b": [S(200)]}, []
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        env.pop(H.WAIT_ENV, None)
        pa = subprocess.Popen([sys.executable, "-c", PROC, self.base + "/a", "A", "-"],
                              env=dict(env, **{H.DIR_ENV: str(da)}))
        pb = subprocess.Popen([sys.executable, "-c", PROC, self.base + "/b", "B", str(da / "hub-cooldown.json")],
                              env=dict(env, **{H.DIR_ENV: str(db)}))
        self.assertEqual((pa.wait(30), pb.wait(30)), (0, 0))
        with _Mock.lock:
            a = [s[0] for s in _Mock.seen if s[2] == "/a"]
            b = [s[0] for s in _Mock.seen if s[2] == "/b"]
        return b[0] - a[0], H.read_log(da / "hubcalls.jsonl")

    def test_the_cool_down_is_shared_by_every_process_on_the_machine(self):
        gap, rows = self.two_processes(shared=True)
        self.assertGreaterEqual(gap, 1.9)           # B waited out A's cool-down (Retry-After 2 plus jitter)
        self.assertEqual({r["who"] for r in rows}, {"A", "B"})
        self.assertTrue(all(isinstance(r["pid"], int) for r in rows))

    def test_control_separate_state_folders_do_not_wait(self):
        gap, _ = self.two_processes(shared=False)
        self.assertLess(gap, 1.5)

if __name__ == "__main__":
    unittest.main()
