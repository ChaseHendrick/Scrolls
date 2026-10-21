"""A stand-in for VC3D's plugin host, for the tool registry's tests: no VC3D build, no Qt, no downloads.

It follows villa's apps/VC3D/plugins/PluginManifest.cpp (the vc3d-plugins lane of the combined VC3D suite, read
20 Oct 2026) closely enough to test the layer above it: a manifest is schema vc3d-plugin/1 with only the known keys;
"program" holds no placeholder; every argument is a template that expands to exactly one argument, naming only the
host's placeholders ({volume}, {segment}, {ink_overlay}, {point}, {region}, {output}, ...) or {input:NAME} for a
declared input; a placeholder with no value refuses the start and says what is missing; the result path starts with
{output}/ and may not leave it after expansion; a relative program with a separator resolves against the manifest's
folder. The program runs as a separate process with an argument list, never through a shell.

After a run the host loads the declared result the way VC3D would (a file must exist; points must be a point
collection, version 1; a segment needs meta.json; an umbilicus needs control points) and, as the registry's
results applier, plays the run's vc3d-result.json open list against a recording stand-in app. Standard library only.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCHEMA = "vc3d-plugin/1"
KNOWN_KEYS = {"schema", "id", "name", "description", "menu", "program", "args", "inputs", "result", "homepage",
              "license"}
PLACEHOLDERS = {"volume", "volume_id", "segment", "segment_id", "project", "ink_overlay", "umbilicus", "point",
                "point_x", "point_y", "point_z", "region", "output", "plugin_dir"}
RESULT_KINDS = {"none", "file", "segment", "ink_overlay", "points", "umbilicus"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
INPUT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
NEEDS = {"volume": "an open volume", "volume_id": "an open volume", "segment": "an active segment",
         "segment_id": "an active segment", "project": "a project saved on disk",
         "ink_overlay": "a selected ink detection overlay", "umbilicus": "an attached umbilicus",
         "region": "an enabled focus region"}


class HostError(Exception):
    pass


def _tokens(text):
    """Literal and placeholder pieces of a template; '{{' and '}}' are literal braces."""
    out, lit, i = [], "", 0
    while i < len(text):
        c = text[i]
        if c == "{" and text[i + 1:i + 2] == "{":
            lit, i = lit + "{", i + 2
            continue
        if c == "}" and text[i + 1:i + 2] == "}":
            lit, i = lit + "}", i + 2
            continue
        if c == "{":
            close = text.find("}", i + 1)
            if close < 0:
                raise HostError(f"unclosed '{{' in {text!r}")
            if lit:
                out.append((False, lit))
                lit = ""
            out.append((True, text[i + 1:close]))
            i = close + 1
            continue
        if c == "}":
            raise HostError(f"unmatched '}}' in {text!r}")
        lit, i = lit + c, i + 1
    if lit:
        out.append((False, lit))
    return out


def _check_template(text, inputs):
    for is_ph, name in _tokens(text):
        if not is_ph:
            continue
        if name.startswith("input:"):
            if name[6:] not in inputs:
                raise HostError(f"{{{name}}} names an input the manifest does not declare")
        elif name not in PLACEHOLDERS:
            raise HostError(f"unknown placeholder {{{name}}}")


def parse(path):
    """One manifest file, validated as PluginManifest.cpp's parseManifest does; raises HostError."""
    path = Path(path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise HostError("not a JSON object")
    unknown = set(doc) - KNOWN_KEYS
    if unknown:
        raise HostError(f"unknown key {sorted(unknown)[0]!r}")
    if doc.get("schema") != SCHEMA:
        raise HostError(f'"schema" must be "{SCHEMA}"')
    if not ID_RE.match(str(doc.get("id", ""))):
        raise HostError('"id" must be 1 to 64 letters, digits, ".", "_" or "-"')
    if not str(doc.get("name", "")).strip():
        raise HostError('"name" is required')
    prog = str(doc.get("program", ""))
    if not prog.strip():
        raise HostError('"program" is required')
    if "{" in prog or "}" in prog:
        raise HostError('"program" cannot contain placeholders')
    inputs = {}
    for item in doc.get("inputs", []):
        if not isinstance(item, dict) or not INPUT_RE.match(str(item.get("name", ""))):
            raise HostError('each input needs a "name" of lowercase letters, digits or "_"')
        if item["name"] in inputs:
            raise HostError(f'input "{item["name"]}" is declared twice')
        inputs[item["name"]] = str(item.get("default", ""))
    args = doc.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise HostError('"args" must be an array of strings')
    for a in args:
        _check_template(a, inputs)
    result = doc.get("result", {"kind": "none"})
    if result.get("kind") not in RESULT_KINDS:
        raise HostError('"result.kind" must be none, file, segment, ink_overlay, points or umbilicus')
    if result["kind"] != "none":
        rp = str(result.get("path", ""))
        if not rp.startswith("{output}/") or ".." in rp.split("/"):
            raise HostError('"result.path" must start with {output}/ and stay inside it')
        _check_template(rp, inputs)
    return {"doc": doc, "inputs": inputs, "dir": path.parent.resolve(), "path": path}


def scan(dirs):
    """(plugins by id, problems): every *.json in each folder, in name order; a repeated id is a problem."""
    plugins, problems = {}, []
    for d in dirs:
        for f in sorted(Path(d).glob("*.json")) if Path(d).is_dir() else []:
            try:
                p = parse(f)
            except (HostError, ValueError) as exc:
                problems.append(f"{f}: {exc}")
                continue
            if p["doc"]["id"] in plugins:
                problems.append(f"{f}: id {p['doc']['id']!r} is already used by an earlier plugin")
                continue
            plugins[p["doc"]["id"]] = p
    return plugins, problems


def _num(v):
    return format(float(v), ".10g")


def _value(name, plugin, ctx):
    if name.startswith("input:"):
        return ctx.get("inputs", {}).get(name[6:], plugin["inputs"].get(name[6:], ""))
    if name == "plugin_dir":
        return str(plugin["dir"])
    if name in ("point", "point_x", "point_y", "point_z") and ctx.get("point"):
        p = ctx["point"]
        return {"point": ",".join(_num(v) for v in p), "point_x": _num(p[0]), "point_y": _num(p[1]),
                "point_z": _num(p[2])}[name]
    if name == "region" and ctx.get("region"):
        return ",".join(_num(v) for v in ctx["region"])
    return str(ctx.get(name) or "")


def _expand_one(text, plugin, ctx):
    out = ""
    for is_ph, piece in _tokens(text):
        if not is_ph:
            out += piece
            continue
        v = _value(piece, plugin, ctx)
        if not v:
            need = NEEDS.get(piece) or ("a focus point" if piece.startswith("point") else
                                        f'a value for "{piece[6:]}"' if piece.startswith("input:") else piece)
            raise HostError(f"{plugin['doc']['name']} needs {need}")
        out += v
    return out


def expand(plugin, ctx):
    """(argv after the program, result path); each template stays exactly one argument."""
    args = [_expand_one(a, plugin, ctx) for a in plugin["doc"].get("args", [])]
    result = plugin["doc"].get("result", {"kind": "none"})
    rpath = None
    if result["kind"] != "none":
        rpath = os.path.normpath(_expand_one(result["path"], plugin, ctx))
        if not rpath.startswith(os.path.normpath(ctx["output"]) + os.sep):
            raise HostError(f"{plugin['doc']['name']}: the result path leaves the run folder")
    return args, rpath


def resolve_program(plugin):
    prog = plugin["doc"]["program"].strip()
    if os.path.isabs(prog):
        return prog if os.access(prog, os.X_OK) else None
    if "/" in prog:
        cand = plugin["dir"] / prog
        return str(cand) if cand.is_file() and os.access(cand, os.X_OK) else None
    from shutil import which
    return which(prog)


def enabled(plugin, ctx):
    """(True, None), or (False, the host's refusal) for a context, as the menu would show it."""
    try:
        expand(plugin, dict(ctx, output=ctx.get("output") or "/run/x"))
        return True, None
    except HostError as exc:
        return False, str(exc)


def load_result(kind, path):
    """What VC3D does with the declared result, as far as a test can see it."""
    p = Path(path)
    if kind == "file":
        if not p.is_file():
            raise HostError(f"result file {p} is missing")
        return {"kind": kind, "path": str(p)}
    if kind == "points":
        doc = json.loads(p.read_text())
        if doc.get("vc_pointcollections_json_version") != "1" or not isinstance(doc.get("collections"), dict):
            raise HostError(f"{p} is not a VC3D point collection, version 1")
        return {"kind": kind, "collections": [c.get("name") for c in doc["collections"].values()]}
    if kind == "segment":
        if not (p / "meta.json").is_file():
            raise HostError(f"{p} is not a segment folder (no meta.json)")
        return {"kind": kind, "path": str(p)}
    if kind == "umbilicus":
        doc = json.loads(p.read_text())
        if not doc.get("control_points"):
            raise HostError(f"{p} has no control_points")
        return {"kind": kind, "path": str(p)}
    return {"kind": kind}


class App:
    """A recording stand-in for a running VC3D: answers the read calls and records every call it is sent."""

    def __init__(self, state=None, segments=None):
        self.state = state or {}
        self.segments = segments or []
        self.calls = []

    def call(self, sock, method, params=None, timeout=60):
        self.calls.append((method, params))
        if method == "state.get":
            return self.state
        if method == "segments.list":
            return {"segments": self.segments}
        return {"ok": True}


def run(plugin, ctx, env=None, timeout=300):
    """Start one plugin as VC3D would: expand, resolve, run with an argument list, load the result."""
    Path(ctx["output"]).mkdir(parents=True, exist_ok=True)
    args, rpath = expand(plugin, ctx)
    # VC3D writes plugin-run.json (state started) into the fresh folder before the program runs
    # (PluginController::writeRecord), so a tool sees one file there
    (Path(ctx["output"]) / "plugin-run.json").write_text(json.dumps({"schema": "vc3d-plugin-run/1",
                                                                    "state": "started"}))
    prog = resolve_program(plugin)
    if prog is None:
        raise HostError(f"{plugin['doc']['program']} was not found")
    proc = subprocess.run([prog, *args], capture_output=True, text=True, env=env, timeout=timeout)
    out = {"exit": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "argv": [prog, *args],
           "result_path": rpath}
    kind = plugin["doc"].get("result", {}).get("kind", "none")
    if rpath and Path(rpath).exists():
        out["loaded"] = load_result(kind, rpath)
    return out


if __name__ == "__main__":
    found, bad = scan(sys.argv[1:])
    print(json.dumps({"plugins": sorted(found), "problems": bad}, indent=1))
