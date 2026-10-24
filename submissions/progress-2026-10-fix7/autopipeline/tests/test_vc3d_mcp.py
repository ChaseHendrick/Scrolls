"""Tests for kit.vc3d_mcp, the MCP server behind `python -m kit vc3d mcp`.

The server is driven in process (a fake stdout collects its messages) for the protocol details, then
as a real subprocess over stdio, and, when the official MCP Python SDK is installed, by its client.
Tools run against the stand-in VC3D of tests/vc3d_fakes.py.
"""
import base64
import importlib.util
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vc3d_fakes as fakes  # noqa: E402

from kit import vc3d_agent, vc3d_bridge, vc3d_io, vc3d_mcp  # noqa: E402

ROOT = fakes.ROOT


class Wire:
    """The client's end of the server's stdout: every message, parsed, in order."""

    def __init__(self):
        self.q = queue.Queue()

    def write(self, text):
        for line in text.splitlines():
            if line.strip():
                self.q.put(json.loads(line))

    def flush(self):
        pass


class InProcess(unittest.TestCase):
    version = "2025-11-25"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        fakes.make_bin(self.d / "bin")
        self.env = fakes.env_for(self.d / "bin", self.d / "home")
        self.wire = Wire()
        self.server = vc3d_mcp.Server(self.wire, env=self.env)
        self.addCleanup(self.server.close, grace=5.0)
        self.next_id = 0
        if self.version:
            self.request("initialize", {"protocolVersion": self.version, "capabilities": {},
                                        "clientInfo": {"name": "test", "version": "0"}})
            self.notify("notifications/initialized")

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, msg):
        self.server.feed(json.dumps(msg))

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def request(self, method, params=None, timeout=60):
        self.next_id += 1
        rid = self.next_id
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})})
        return self.until(rid, timeout)[0]

    def until(self, rid, timeout=60):
        """The response to request rid, and the notifications that came before it."""
        notes, deadline = [], time.time() + timeout
        while True:
            msg = self.wire.q.get(timeout=max(0.05, deadline - time.time()))
            if isinstance(msg, dict) and msg.get("id") == rid and "method" not in msg:
                return msg, notes
            notes.append(msg)

    def tool(self, name, arguments=None, **kw):
        res = self.request("tools/call", {"name": name, "arguments": arguments or {}}, **kw)
        self.assertIn("result", res, res)
        return res["result"]


class TestHandshake(InProcess):
    version = None

    def test_versions_are_negotiated(self):
        for asked, expect in [(v, v) for v in vc3d_mcp.SUPPORTED] + [("2099-01-01", vc3d_mcp.LATEST), (None, vc3d_mcp.LATEST)]:
            with self.subTest(asked=asked):
                server = vc3d_mcp.Server(self.wire, env=self.env)
                res = server.initialize({"protocolVersion": asked} if asked else {})
                server.close()
                self.assertEqual(res["protocolVersion"], expect)
                self.assertEqual(set(res["capabilities"]), {"tools", "resources"})
                self.assertEqual(res["serverInfo"]["name"], "kit-vc3d")
                self.assertEqual("title" in res["serverInfo"], expect >= "2025-06-18")
                self.assertIn("preregistered", res["instructions"])

    def test_tool_list_follows_the_version(self):
        for version, annotations, title in (("2024-11-05", False, False), ("2025-03-26", True, False),
                                            ("2025-06-18", True, True)):
            with self.subTest(version=version):
                self.request("initialize", {"protocolVersion": version})
                tools = self.request("tools/list")["result"]["tools"]
                self.assertEqual(len(tools), len(vc3d_agent.TOOLS))
                render = next(t for t in tools if t["name"] == "render")
                self.assertEqual(("annotations" in render, "title" in render), (annotations, title))
                self.assertEqual(render["inputSchema"]["required"], ["surface", "volume"])


class TestProtocol(InProcess):
    def test_errors_and_plain_methods(self):
        self.server.feed("{not json")
        self.assertEqual(self.wire.q.get(timeout=5)["error"]["code"], vc3d_mcp.PARSE_ERROR)
        self.send({"id": 1, "method": "ping"})
        self.assertEqual(self.wire.q.get(timeout=5)["error"]["code"], vc3d_mcp.INVALID_REQUEST)
        self.assertEqual(self.request("server/discover")["error"]["code"], vc3d_mcp.METHOD_NOT_FOUND)
        self.assertEqual(self.request("tools/call", ["render"])["error"]["code"], vc3d_mcp.INVALID_PARAMS)
        self.assertEqual(self.request("tools/call", {"name": "nope"})["error"]["code"], vc3d_mcp.INVALID_PARAMS)
        self.assertEqual(self.request("ping")["result"], {})
        for method, key in (("prompts/list", "prompts"), ("resources/templates/list", "resourceTemplates")):
            self.assertEqual(self.request(method)["result"][key], [])
        self.notify("notifications/roots/list_changed")
        self.send({"jsonrpc": "2.0", "id": 99, "result": {}})  # a response to nothing: ignored
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": "ping"})
        reply, before = self.until(self.next_id)
        self.assertEqual((reply["result"], before), ({}, []))  # nothing was answered in between
        self.assertTrue(self.wire.q.empty())

    def test_batch(self):
        self.server.feed(json.dumps([{"jsonrpc": "2.0", "id": "a", "method": "ping"},
                                     {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                     {"jsonrpc": "2.0", "id": "b", "method": "tools/call",
                                      "params": {"name": "inspect", "arguments": {"path": str(self.d / "missing")}}}]))
        reply = self.wire.q.get(timeout=30)
        self.assertEqual([r["id"] for r in reply], ["a", "b"])
        self.assertTrue(reply[1]["result"]["isError"])

    def test_resources(self):
        listed = {r["uri"]: r for r in self.request("resources/list")["result"]["resources"]}
        self.assertIn("kit-vc3d://AGENTS.md", listed)
        self.assertIn("kit-vc3d://docs/vc3d-headless.md", listed)
        self.assertEqual(listed["kit-vc3d://AGENTS.md"]["mimeType"], "text/markdown")
        text = self.request("resources/read", {"uri": "kit-vc3d://AGENTS.md"})["result"]["contents"][0]["text"]
        self.assertEqual(text, (ROOT / "AGENTS.md").read_text())
        self.assertEqual(self.request("resources/read", {"uri": "file:///etc/passwd"})["error"]["code"],
                         vc3d_mcp.RESOURCE_NOT_FOUND)


class TestToolCalls(InProcess):
    def test_results_errors_and_images(self):
        surf = fakes.write_tifxyz(self.d / "s.tifxyz", fakes.plane(32))
        res = self.tool("inspect", {"path": str(surf)})
        data = json.loads(res["content"][0]["text"])
        self.assertEqual((data["kind"], res["isError"], res["structuredContent"]), ("tifxyz", False, data))
        res = self.tool("inspect", {"path": str(self.d / "missing")})
        self.assertTrue(res["isError"])
        self.assertIn("not found", res["content"][0]["text"])
        res = self.tool("render", {"surface": str(surf)})
        self.assertIn("missing required argument(s) volume", res["content"][0]["text"])
        # AutoPipeline also answers to its earlier name; the VC3D agent package ships without it
        for name in ("autopipeline", "autopipe") if (ROOT / "kit" / "autopipe.py").is_file() else ():
            res = self.tool(name, {"action": "status", "out": str(self.d)})
            self.assertIn("has no plan.json", res["content"][0]["text"])
        res = self.tool("run", {"tool": "vc_sleep", "args": ["0", "--exit", "3"]})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["exit"], 3)
        res = self.tool("preview", {"path": str(surf)})
        image = res["content"][1]
        self.assertEqual((image["type"], image["mimeType"]), ("image", "image/png"))
        self.assertEqual(vc3d_io.read_png_gray(base64.b64decode(image["data"]))[:2], (9, 9))
        self.assertNotIn("_images", res["structuredContent"])

    def test_a_crashing_tool_is_reported_not_fatal(self):
        def boom(ctx, args):
            raise RuntimeError("kaboom")

        broken = vc3d_agent.Tool("boom", "Boom", "Fails.", {}, (), boom, False, True, False, False)
        with mock.patch.dict(vc3d_agent.TOOLS, {"boom": broken}), \
                mock.patch.object(vc3d_mcp.traceback, "print_exc"):
            res = self.tool("boom")
        self.assertTrue(res["isError"])
        self.assertIn("RuntimeError: kaboom", res["content"][0]["text"])
        self.assertEqual(self.request("ping")["result"], {})

    def test_progress_and_cancellation(self):
        pid = self.d / "pid"
        self.next_id += 1
        rid = self.next_id
        self.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                   "params": {"name": "run", "arguments": {"tool": "vc_sleep", "args": ["60", "--pid", str(pid)]},
                              "_meta": {"progressToken": "tok"}}})
        first = self.wire.q.get(timeout=30)
        self.assertEqual((first["method"], first["params"]["progressToken"], first["params"]["progress"]),
                         ("notifications/progress", "tok", 1))
        self.assertIn("vc_sleep", first["params"]["message"])
        self.assertTrue(self.request("ping", timeout=10))  # answered while the tool runs
        self.notify("notifications/cancelled", {"requestId": rid, "reason": "test"})
        deadline = time.time() + 20
        while time.time() < deadline and (rid in self.server.running or vc3d_bridge._alive(int(pid.read_text()))):
            time.sleep(0.1)
        self.assertNotIn(rid, self.server.running)
        self.assertFalse(vc3d_bridge._alive(int(pid.read_text())))
        later = self.request("ping")
        seen = [later]
        while not self.wire.q.empty():
            seen.append(self.wire.q.get())
        self.assertFalse([m for m in seen if m.get("id") == rid])  # a canceled call gets no response

    def test_close_stops_running_tools(self):
        pid = self.d / "pid"
        self.send({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                   "params": {"name": "run", "arguments": {"tool": "vc_sleep", "args": ["60", "--pid", str(pid)]}}})
        deadline = time.time() + 30
        while not pid.exists() and time.time() < deadline:
            time.sleep(0.1)
        started = time.time()
        self.server.close(grace=20)
        self.assertLess(time.time() - started, 15)
        self.assertFalse(vc3d_bridge._alive(int(pid.read_text())))


class TestOverStdio(unittest.TestCase):
    def test_subprocess_speaks_only_protocol_on_stdout(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fakes.make_bin(d / "bin")
            # status probes the ink Python; where that one imports torch (a Mac with the ink stack) the probe
            # takes longer than the 3 s a piped session's calls get after its input ends, so status would go
            # unanswered. A stand-in ink Python answers at once.
            ink = d / "ink-python"
            ink.write_text('#!/bin/sh\necho \'{"python": "stand-in", "version": "3", "torch": false}\'\n')
            ink.chmod(0o755)
            env = fakes.env_for(d / "bin", d / "home", KIT_INK_PYTHON=ink)
            proc = subprocess.Popen([sys.executable, "-m", "kit", "vc3d", "mcp"], cwd=ROOT, env=env, text=True,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "status", "arguments": {}}},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "run", "arguments": {"tool": "vc_sleep", "args": ["0.2"]}}}]
            out, err = proc.communicate("".join(json.dumps(m) + "\n" for m in msgs), timeout=120)
            self.assertEqual(proc.returncode, 0, err)
            replies = {m["id"]: m for m in (json.loads(line) for line in out.splitlines())}  # every line is JSON
            self.assertEqual(sorted(replies), [1, 2, 3, 4])
            self.assertEqual(replies[1]["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual(len(replies[2]["result"]["tools"]), len(vc3d_agent.TOOLS))
            status = replies[3]["result"]["structuredContent"]
            self.assertEqual(status["tools"], f"VC_BIN: {d / 'bin'} (started directly)")
            self.assertEqual(replies[4]["result"]["structuredContent"]["exit"], 0)
            self.assertIn("MCP server on stdio", err)


@unittest.skipUnless(importlib.util.find_spec("mcp") and importlib.util.find_spec("anyio"), "needs the MCP Python SDK")
class TestOfficialClient(unittest.TestCase):
    def test_sdk_client(self):
        import anyio
        from contextlib import asynccontextmanager
        import mcp
        from mcp.client.stdio import StdioServerParameters

        @asynccontextmanager
        async def connect(params):
            if hasattr(mcp, "Client"):       # SDK 2.x, the originally tested API
                async with mcp.Client(params) as client:
                    yield client
            else:                          # SDK 1.x
                from mcp.client.stdio import stdio_client
                async with stdio_client(params) as (read, write), mcp.ClientSession(read, write) as client:
                    await client.initialize()
                    yield client

        def field(result, name):
            if hasattr(result, name):
                return getattr(result, name)
            return getattr(result, {"is_error": "isError", "structured_content": "structuredContent"}[name])

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fakes.make_bin(d / "bin")
            env = fakes.env_for(d / "bin", d / "home")
            surf = fakes.write_tifxyz(d / "s.tifxyz", fakes.plane(32))
            seen = {}

            async def main():
                params = StdioServerParameters(command=sys.executable, args=["-m", "kit", "vc3d", "mcp"],
                                               cwd=str(ROOT), env=env)
                with anyio.fail_after(120):
                    async with connect(params) as c:
                        seen["tools"] = [t.name for t in (await c.list_tools()).tools]
                        seen["inspect"] = await c.call_tool("inspect", {"path": str(surf)})
                        seen["missing"] = await c.call_tool("inspect", {"path": str(d / "missing")})
                        seen["preview"] = await c.call_tool("preview", {"path": str(surf)})
                        seen["resources"] = [str(r.uri) for r in (await c.list_resources()).resources]
                        progress = []

                        async def on_progress(value, total, message):
                            progress.append(message)

                        seen["run"] = await c.call_tool("run", {"tool": "vc_sleep", "args": ["1"]},
                                                        progress_callback=on_progress)
                        seen["progress"] = progress

            anyio.run(main)
        self.assertEqual(len(seen["tools"]), len(vc3d_agent.TOOLS))
        self.assertFalse(field(seen["inspect"], "is_error"))
        self.assertEqual(field(seen["inspect"], "structured_content")["kind"], "tifxyz")
        self.assertTrue(field(seen["missing"], "is_error"))
        self.assertEqual([c.type for c in seen["preview"].content], ["text", "image"])
        self.assertIn("kit-vc3d://AGENTS.md", seen["resources"])
        self.assertFalse(field(seen["run"], "is_error"))
        self.assertTrue(seen["progress"] and "vc_sleep" in seen["progress"][0], seen["progress"])


if __name__ == "__main__":
    unittest.main()
