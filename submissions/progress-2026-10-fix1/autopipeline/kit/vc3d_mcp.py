"""MCP server for the headless VC3D tools: `python -m kit vc3d mcp` (stdio). See docs/vc3d-agents.md.

An MCP client (Claude Code, Claude Desktop, or any other) starts this process and talks to it over
stdin and stdout with newline-delimited JSON-RPC 2.0. It serves the tools of kit/vc3d_agent.py:
`tools/list` gives their schemas, `tools/call` runs one in a worker thread, so pings and
cancellations are answered while a long render runs. A result is the tool's JSON as text (and as
structuredContent from protocol 2025-06-18), plus any preview PNG as an image. Progress messages go
out as notifications/progress when the client asked for them; notifications/cancelled stops the
tool's subprocess. The docs are served as resources.

Protocol versions 2024-11-05 to 2025-11-25 (the initialize handshake). A client that first probes
`server/discover` (2026-07-28) gets "method not found" and falls back to the handshake, as the
specification asks. Standard library only: nothing to install beyond Python and the VC3D tools.

Stray output would corrupt the protocol, so the server keeps its own copy of stdout and points file
descriptor 1 at stderr: anything printed by a library or a child process lands in the client's log.
"""

import base64
import json
import os
import signal
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import vc3d_agent

SUPPORTED = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LATEST = SUPPORTED[0]
NAME = "kit-vc3d"
MAX_IMAGE = 4 << 20  # bytes of PNG inlined per image; larger previews are referred to by path
DOCS = {  # resource uri: (path under the repository, title)
    "kit-vc3d://docs/vc3d-agents.md": ("docs/vc3d-agents.md", "Driving headless VC3D as an agent: workflow, conventions, rules"),
    "kit-vc3d://docs/vc3d-headless.md": ("docs/vc3d-headless.md", "Headless VC3D: building, running, rendering conventions, Modal"),
    "kit-vc3d://AGENTS.md": ("AGENTS.md", "The repository's rules for agents"),
}
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
RESOURCE_NOT_FOUND = -32002


def at_least(version, minimum):
    """Protocol versions are dates, so they compare as strings."""
    return (version or LATEST) >= minimum


class Server:
    def __init__(self, out, env=None, root=None, workers=8):
        self.out = out
        self.env = dict(os.environ if env is None else env)
        # root: the kit home the tools run in (None: KIT_HOME, else the default, kit/kithome.py); the guides it
        # serves as resources come from the source folder, or from root when one is given
        self.root = Path(root) if root else None
        self.docs = Path(root) if root else vc3d_agent.ROOT
        self.version = None
        self.client = {}
        self._write = threading.Lock()
        self._calls = threading.Lock()
        self.running = {}  # request id: cancel event
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kit-vc3d-tool")

    # ------------------------------------------------------------ wire

    def send(self, msg):
        line = json.dumps(msg, default=str, ensure_ascii=False)
        with self._write:
            self.out.write(line + "\n")
            self.out.flush()

    @staticmethod
    def response(rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result if result is not None else {}
        return msg

    @staticmethod
    def error(code, message, data=None):
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return err

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def feed(self, line):
        """One line from the client: a message or a batch. Replies are sent from here or from a worker."""
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            self.send(self.response(None, error=self.error(PARSE_ERROR, f"parse error: {exc}")))
            return
        if isinstance(msg, list):  # a JSON-RPC batch (protocol 2025-03-26): answered as one array
            replies = [r for r in (self.dispatch(m, sync=True) for m in msg) if r is not None]
            if replies:
                with self._write:
                    self.out.write(json.dumps(replies, default=str, ensure_ascii=False) + "\n")
                    self.out.flush()
            return
        reply = self.dispatch(msg)
        if reply is not None:
            self.send(reply)

    def dispatch(self, msg, sync=False):
        """Handle one message; returns the response to send now, or None (a notification, or a tool call
        that a worker answers later)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self.response(msg.get("id") if isinstance(msg, dict) else None,
                                 error=self.error(INVALID_REQUEST, "not a JSON-RPC 2.0 message"))
        method = msg.get("method")
        rid = msg.get("id")
        if method is None:
            return None  # a response to something we sent (we send no requests): nothing to do
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return self.response(rid, error=self.error(INVALID_PARAMS, "params must be an object")) if "id" in msg else None
        if "id" not in msg:
            self.on_notification(method, params)
            return None
        try:
            if method == "tools/call":
                return self.tools_call(rid, params, sync)
            handler = self.HANDLERS.get(method)
            if handler is None:
                return self.response(rid, error=self.error(METHOD_NOT_FOUND, f"method not found: {method}"))
            return self.response(rid, handler(self, params))
        except RequestError as exc:
            return self.response(rid, error=self.error(exc.code, exc.message))
        except Exception as exc:  # a bug here must not kill the server
            traceback.print_exc(file=sys.stderr)
            return self.response(rid, error=self.error(INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"))

    def on_notification(self, method, params):
        if method == "notifications/cancelled":
            with self._calls:
                event = self.running.get(params.get("requestId"))
            if event is not None:
                event.set()
        # notifications/initialized, notifications/roots/list_changed and others need no action

    # ------------------------------------------------------------ methods

    def initialize(self, params):
        asked = params.get("protocolVersion")
        self.version = asked if asked in SUPPORTED else LATEST
        self.client = params.get("clientInfo") or {}
        info = {"name": NAME, "version": vc3d_agent.VERSION}
        if at_least(self.version, "2025-06-18"):
            info["title"] = "Headless VC3D for agents (kit)"
        return {"protocolVersion": self.version,
                "capabilities": {"tools": {"listChanged": False},
                                 "resources": {"listChanged": False, "subscribe": False}},
                "serverInfo": info, "instructions": vc3d_agent.INSTRUCTIONS}

    def ping(self, params):
        return {}

    def tool_list(self):
        tools = []
        for t in vc3d_agent.TOOLS.values():
            d = {"name": t.name, "description": t.description, "inputSchema": t.schema()}
            if at_least(self.version, "2025-03-26"):
                d["annotations"] = t.annotations()
            if at_least(self.version, "2025-06-18"):
                d["title"] = t.title
            tools.append(d)
        return tools

    def tools_list(self, params):
        return {"tools": self.tool_list()}

    def resources_list(self, params):
        out = []
        for uri, (rel, title) in DOCS.items():
            path = self.docs / rel
            if path.is_file():
                d = {"uri": uri, "name": Path(rel).name, "description": title, "mimeType": "text/markdown",
                     "size": path.stat().st_size}
                if at_least(self.version, "2025-06-18"):
                    d["title"] = title
                out.append(d)
        return {"resources": out}

    def resources_read(self, params):
        uri = params.get("uri")
        if uri not in DOCS or not (self.docs / DOCS[uri][0]).is_file():
            raise RequestError(RESOURCE_NOT_FOUND, f"resource not found: {uri}")
        text = (self.docs / DOCS[uri][0]).read_text(encoding="utf-8")
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}

    HANDLERS = {}

    # ------------------------------------------------------------ tool calls

    def tools_call(self, rid, params, sync=False):
        name = vc3d_agent.TOOL_ALIASES.get(params.get("name"), params.get("name"))
        if name not in vc3d_agent.TOOLS:
            return self.response(rid, error=self.error(INVALID_PARAMS, f"unknown tool: {name}"))
        args = params.get("arguments") or {}
        token = (params.get("_meta") or {}).get("progressToken")
        cancel = threading.Event()
        with self._calls:
            self.running[rid] = cancel
        if sync:
            return self.run_tool(rid, name, args, token, cancel)
        self.pool.submit(self._run_and_send, rid, name, args, token, cancel)
        return None

    def _run_and_send(self, rid, name, args, token, cancel):
        reply = self.run_tool(rid, name, args, token, cancel)
        if reply is not None:
            self.send(reply)

    def run_tool(self, rid, name, args, token, cancel):
        count = [0]

        def progress(message):
            if token is None:
                return
            count[0] += 1
            note = {"progressToken": token, "progress": count[0]}
            if at_least(self.version, "2025-03-26"):
                note["message"] = str(message)[:500]
            try:
                self.notify("notifications/progress", note)
            except (OSError, ValueError):
                pass

        ctx = vc3d_agent.Context(root=self.root, env=self.env, cancel=cancel, progress=progress)
        try:
            result = self.tool_result(vc3d_agent.call(name, args, ctx))
        except vc3d_agent.ToolError as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:  # a crash in a tool is reported to the agent, with the traceback on stderr
            traceback.print_exc(file=sys.stderr)
            result = {"content": [{"type": "text", "text": f"{name} failed inside the server: "
                                                           f"{type(exc).__name__}: {exc}"}], "isError": True}
        finally:
            with self._calls:
                self.running.pop(rid, None)
        if cancel.is_set():
            return None  # the client cancelled: it expects no response
        return self.response(rid, result)

    def tool_result(self, result):
        if not isinstance(result, dict):
            result = {"result": result}
        images = result.pop("_images", None) or []
        text = json.dumps(result, indent=1, default=str, ensure_ascii=False)
        content = [{"type": "text", "text": text}]
        for path in images:
            try:
                data = Path(path).read_bytes()
            except OSError as exc:
                content.append({"type": "text", "text": f"image {path} unreadable: {exc}"})
                continue
            if len(data) > MAX_IMAGE:
                content.append({"type": "text", "text": f"image {path} is {len(data)} bytes, too large to inline; "
                                                        "ask preview for a smaller max_side"})
                continue
            content.append({"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": "image/png"})
        exit_code = result.get("exit")
        out = {"content": content, "isError": exit_code is not None and exit_code != 0}
        if at_least(self.version, "2025-06-18"):
            out["structuredContent"] = json.loads(text)
        return out

    # ------------------------------------------------------------ lifetime

    def close(self, settle=0.0, grace=15.0):
        """Input ended: give running tools `settle` seconds to finish and answer, then cancel the rest,
        which kills their subprocesses, and wait up to `grace` for them. Background jobs are separate
        processes and carry on."""
        deadline = time.monotonic() + settle
        while time.monotonic() < deadline:
            with self._calls:
                if not self.running:
                    break
            time.sleep(0.05)
        with self._calls:
            events = list(self.running.values())
        for event in events:
            event.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        for t in [t for t in threading.enumerate() if t.name.startswith("kit-vc3d-tool")]:
            t.join(timeout=grace)


class RequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


Server.HANDLERS = {
    "initialize": Server.initialize,
    "ping": Server.ping,
    "tools/list": Server.tools_list,
    "resources/list": Server.resources_list,
    "resources/read": Server.resources_read,
    "resources/templates/list": lambda self, params: {"resourceTemplates": []},
    "prompts/list": lambda self, params: {"prompts": []},
    "logging/setLevel": lambda self, params: {},
    "completion/complete": lambda self, params: {"completion": {"values": [], "total": 0, "hasMore": False}},
}


def serve(inp, out, env=None, root=None, settle=3.0):
    """Run until `inp` ends. inp yields lines (bytes or str); out is a text stream. Calls still running
    when the input ends get `settle` seconds to answer (requests piped in from a shell); an interrupt
    or SIGTERM cancels them at once."""
    server = Server(out, env=env, root=root)
    try:
        for raw in inp:
            server.feed(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
    except KeyboardInterrupt:
        settle = 0.0
        raise
    finally:
        server.close(settle=settle)
    return 0


def _interrupt(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def main():
    """Entry for `python -m kit vc3d mcp`: protocol on the real stdout, everything else on stderr."""
    proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    print(f"{NAME} {vc3d_agent.VERSION}: MCP server on stdio, {len(vc3d_agent.TOOLS)} tools, kit "
          f"{vc3d_agent.ROOT}, kit home {vc3d_agent.kithome.home()}", file=sys.stderr)
    signal.signal(signal.SIGTERM, _interrupt)  # a client stopping the server also stops its running tools
    try:
        return serve(sys.stdin.buffer, proto)
    except KeyboardInterrupt:
        return 0
