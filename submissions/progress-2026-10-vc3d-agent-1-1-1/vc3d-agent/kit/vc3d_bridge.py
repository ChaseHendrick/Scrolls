"""Drive the VC3D app with no display over its agent bridge (villa `apps/VC3D/agent_bridge/SPEC.md`).

VC3D started with `--agent-bridge-name NAME` under Qt's offscreen platform listens on a Unix socket
and prints `VC3D-AGENT-BRIDGE: listening name=NAME path=PATH`. The protocol is newline-delimited
JSON-RPC 2.0, one message per line; 120 methods cover projects, the data catalog, segments,
growth, rendering, flattening, points, fibers, screenshots and jobs (`rpc.describe` lists them).

This client is the standard library's AF_UNIX socket (POSIX only). Each call connects, sends one
request, reads lines until the matching response and disconnects, so the app can be driven from a
long-lived MCP server or from one-shot `kit vc3d call` commands alike. The app runs detached; its
pid, name and socket are recorded under KIT_VC3D_HOME/app/ so later calls find it.
"""

import json
import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path

HANDSHAKE = re.compile(r"VC3D-AGENT-BRIDGE: listening name=(\S+) path=(\S+)")
REGISTRY = Path.home() / ".vc3d" / "agent_bridge"
_started = {}  # pid: Popen of apps this process started, so stopping one also reaps it


class BridgeError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(f"[{code}] {message}" + (f" {json.dumps(data)}" if data else ""))
        self.code, self.message, self.data = code, message, data or {}


def parse_handshake(text):
    """(name, socket path) from VC3D's handshake line, or None."""
    m = HANDSHAKE.search(text)
    return (m.group(1), m.group(2)) if m else None


def call(path, method, params=None, timeout=60.0, _id=1):
    """One JSON-RPC request over the bridge socket; returns the result or raises BridgeError."""
    req = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        req["params"] = params
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(min(10.0, timeout))
        s.connect(str(path))
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"bridge call {method} timed out after {timeout:.0f} s")
            s.settimeout(remaining)
            chunk = s.recv(1 << 20)
            if not chunk:
                raise BridgeError(-32010, f"bridge closed the connection during {method}")
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(msg, dict) and msg.get("id") == _id:
                    if "error" in msg:
                        e = msg["error"]
                        raise BridgeError(e.get("code", -1), e.get("message", ""), e.get("data"))
                    return msg.get("result", {})


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    try:
        state = Path(f"/proc/{int(pid)}/stat").read_text().split(")")[-1].split()[0]
        return state != "Z"
    except OSError:
        return True


def discover(registry=REGISTRY):
    """The newest live bridge VC3D published in ~/.vc3d/agent_bridge, or None."""
    best = None
    for f in Path(registry).glob("*.json") if Path(registry).is_dir() else []:
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pid = rec.get("pid")
        path = rec.get("path")
        if not path or not _alive(pid):
            continue
        try:
            started = float(rec.get("startedAt") or 0)  # epoch milliseconds
        except (TypeError, ValueError):
            started = 0.0
        if best is None or started > best[0]:
            best = (started, dict(rec, path=path))
    return best[1] if best else None


class App:
    """A VC3D process with the bridge on, started detached and recorded under `home`."""

    def __init__(self, home):
        self.dir = Path(home) / "app"
        self.record = self.dir / "current.json"

    def current(self):
        try:
            rec = json.loads(self.record.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return rec if _alive(rec.get("pid")) else None

    def socket(self):
        rec = self.current()
        if rec:
            return rec["path"]
        found = discover()
        return found["path"] if found else None

    def start(self, argv, env, name, timeout=90.0):
        """argv: how to start VC3D (from Tools.argv), without the bridge flag."""
        rec = self.current()
        if rec:
            return dict(rec, already_running=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        log = self.dir / f"{name}.log"
        with open(log, "wb") as fh:
            proc = subprocess.Popen([*argv, "--agent-bridge-name", name], stdout=fh, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise BridgeError(-32010, f"VC3D exited with {proc.returncode} before the bridge listened; "
                                          f"log {log}: {log.read_text(errors='replace')[-800:]}")
            found = parse_handshake(log.read_text(errors="replace"))
            if found:
                rec = {"pid": proc.pid, "name": found[0], "path": found[1], "log": str(log),
                       "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
                self.record.write_text(json.dumps(rec, indent=1))
                _started[proc.pid] = proc
                return rec
            time.sleep(0.2)
        proc.kill()
        proc.wait()
        raise BridgeError(-32010, f"no bridge handshake from VC3D within {timeout:.0f} s; log {log}")

    def stop(self, grace=10.0):
        rec = self.current()
        if not rec:
            return {"stopped": False, "detail": "no VC3D started by kit is running"}
        pid = int(rec["pid"])
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and _alive(pid):
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            time.sleep(0.2)
        if _alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        proc = _started.pop(pid, None)
        if proc is not None:
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
        try:
            self.record.unlink()
        except OSError:
            pass
        return {"stopped": True, "pid": pid}
