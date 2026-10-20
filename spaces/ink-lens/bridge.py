"""Ink Lens: a minimal client for the VC3D agent bridge (JSON-RPC 2.0, one JSON message per line, over the local
socket VC3D opens with --agent-bridge). Standard library only.

Protocol and discovery as in villa main 8aa507c12, volume-cartographer/apps/VC3D/agent_bridge/SPEC.md: VC3D writes
~/.vc3d/agent_bridge/<pid>.json with {pid, name, path, startedAt}; clients skip records whose process is gone and take
the newest live one. Methods Ink Lens uses: state.get, segments.list, canvas.get_cursor_volume_point,
points.save_json, points.load_json and viewer.center_on_point (rpc_description.json).
"""

from __future__ import annotations

import itertools
import json
import os
import socket
from pathlib import Path

REGISTRY = Path.home() / ".vc3d" / "agent_bridge"


class BridgeError(RuntimeError):
    """No bridge, or the bridge answered with an error."""


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def discover(name=None, registry=REGISTRY):
    """The socket path of a live bridge: the one called `name`, else the newest. A path given as `name` is used as
    it is."""
    if name and ("/" in name or name.endswith(".sock")):
        return name
    recs = []
    for f in sorted(Path(registry).glob("*.json")) if Path(registry).is_dir() else []:
        try:
            r = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(r, dict) or not r.get("path") or not _alive(r.get("pid")):
            continue
        if name and r.get("name") != name:
            continue
        recs.append(r)
    if not recs:
        raise BridgeError("no live VC3D agent bridge found" + (f" named {name!r}" if name else "") +
                          f" in {registry}; start VC3D with --agent-bridge")
    return max(recs, key=lambda r: r.get("startedAt", 0))["path"]


class Bridge:
    def __init__(self, path, timeout=30.0):
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(path)
        except OSError as exc:
            raise BridgeError(f"cannot connect to the VC3D bridge at {path}: {exc}") from None
        self.file = self.sock.makefile("rb")
        self.ids = itertools.count(1)

    def call(self, method, params=None):
        mid = next(self.ids)
        req = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            req["params"] = params
        self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        while True:
            line = self.file.readline()
            if not line:
                raise BridgeError(f"the bridge closed the connection during {method}")
            msg = json.loads(line)
            if msg.get("id") != mid:          # a notification or another client's deferred answer
                continue
            if "error" in msg:
                e = msg["error"]
                raise BridgeError(f"{method}: [{e.get('code')}] {e.get('message')} {e.get('data') or ''}".strip())
            return msg.get("result")

    def close(self):
        try:
            self.file.close()
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def active_segment(br):
    """{id, path} of VC3D's active segment, or a BridgeError."""
    segs = br.call("segments.list", {"onlyLoaded": True}).get("segments", [])
    act = [s for s in segs if s.get("active")]
    if not act:
        raise BridgeError("VC3D has no active segment; open one first")
    if not act[0].get("path"):
        raise BridgeError(f"VC3D's active segment {act[0].get('id')} has no folder on disk")
    return act[0]


def cursor_point(br, viewer=None):
    res = br.call("canvas.get_cursor_volume_point", {"viewer": viewer} if viewer else {})
    p = res.get("volumePoint") if isinstance(res, dict) else None
    if not isinstance(p, dict):
        raise BridgeError(f"canvas.get_cursor_volume_point returned no volumePoint: {res!r}")
    return [float(p["x"]), float(p["y"]), float(p["z"])]
