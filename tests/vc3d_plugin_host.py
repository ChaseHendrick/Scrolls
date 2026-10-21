"""A stand-in for VC3D's plugin host, so plugin manifests can be tested without VC3D.

It follows the manifest rules written for VC3D's Plugins menu (schema vc3d-plugin/1), part of the combined VC3D change
that is not in villa yet: the keys VC3D knows (any other key makes it skip the manifest), the id and input-name
patterns, a program with no placeholders, the placeholders it fills in ({point} as x,y,z with up to 10 significant
digits, {{ and }} as literal braces), the result kinds, and a result path that starts with {output}/ and stays inside
it. A run gets a fresh output folder, the arguments go to the program as a list with no shell, and the declared result
must exist inside that folder afterwards. With VILLA_ROOT set to a villa checkout that has the plugin host,
tests/test_integrations_vc3d.py compares these sets with villa's docs/plugins.md.
"""

import json
import re
import subprocess
from pathlib import Path

SCHEMA = "vc3d-plugin/1"
KEYS = {"schema", "id", "name", "description", "menu", "program", "args", "inputs", "result", "homepage", "license"}
CONTEXT = {"volume", "volume_id", "segment", "segment_id", "project", "ink_overlay", "umbilicus", "point", "point_x",
           "point_y", "point_z", "region", "output", "plugin_dir"}
KINDS = {"none", "file", "segment", "ink_overlay", "points", "umbilicus"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
INPUT = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class ManifestError(ValueError):
    pass


def tokens(text):
    """Literal text and {placeholder} names; {{ and }} are literal braces."""
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
                raise ManifestError(f"unclosed '{{' in {text!r}")
            if lit:
                out.append((False, lit))
                lit = ""
            out.append((True, text[i + 1:close]))
            i = close + 1
            continue
        if c == "}":
            raise ManifestError(f"unmatched '}}' in {text!r}")
        lit, i = lit + c, i + 1
    if lit:
        out.append((False, lit))
    return out


def check_template(text, inputs):
    for is_ph, name in tokens(text):
        if not is_ph:
            continue
        if name.startswith("input:"):
            if name[6:] not in inputs:
                raise ManifestError(f"{{{name}}} names an input the manifest does not declare")
        elif name not in CONTEXT:
            raise ManifestError(f"unknown placeholder {{{name}}}")


def parse(text, path="manifest.json"):
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ManifestError("not a JSON object")
    unknown = set(doc) - KEYS
    if unknown:
        raise ManifestError(f"unknown key {sorted(unknown)[0]!r}")
    if doc.get("schema") != SCHEMA:
        raise ManifestError(f"schema must be {SCHEMA}")
    if not ID.match(str(doc.get("id", ""))):
        raise ManifestError("bad id")
    if not str(doc.get("name", "")).strip():
        raise ManifestError("name is required")
    program = str(doc.get("program", ""))
    if not program.strip():
        raise ManifestError("program is required")
    if "{" in program or "}" in program:
        raise ManifestError("program cannot contain placeholders")
    inputs = []
    for item in doc.get("inputs", []):
        if not isinstance(item, dict) or not INPUT.match(str(item.get("name", ""))):
            raise ManifestError("bad input name")
        if item["name"] in inputs:
            raise ManifestError("input declared twice")
        inputs.append(item["name"])
    args = doc.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ManifestError("args must be an array of strings")
    for a in args:
        check_template(a, inputs)
    result = doc.get("result", {"kind": "none"})
    if result.get("kind") not in KINDS:
        raise ManifestError("bad result kind")
    if result["kind"] != "none":
        rp = str(result.get("path", ""))
        if not rp.startswith("{output}/") or ".." in rp.split("/"):
            raise ManifestError("result.path must start with {output}/ and stay inside it")
        check_template(rp, inputs)
    return dict(doc, plugin_dir=str(Path(path).resolve().parent), input_names=inputs)


def number(v):
    return f"{float(v):.10g}"


def value(name, manifest, ctx):
    if name.startswith("input:"):
        return ctx.get("inputs", {}).get(name[6:], "")
    if name == "plugin_dir":
        return manifest["plugin_dir"]
    point = ctx.get("point")
    if point is not None and name == "point":
        return ",".join(number(v) for v in point)
    if point is not None and name in ("point_x", "point_y", "point_z"):
        return number(point["xyz".index(name[-1])])
    if name == "region" and ctx.get("region") is not None:
        return ",".join(number(v) for v in ctx["region"])
    return str(ctx.get(name) or "")


def expand(text, manifest, ctx):
    out = ""
    for is_ph, name in tokens(text):
        if not is_ph:
            out += name
            continue
        v = value(name, manifest, ctx)
        if not v:
            raise ManifestError(f"{manifest['name']} needs {name}")
        out += v
    return out


def run(manifest, ctx, output, timeout=120):
    """Fill in the placeholders, run the program with no shell, and return (process, result path or None)."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    ctx = dict(ctx, output=str(output))
    inputs = {i["name"]: i.get("default", "") for i in manifest.get("inputs", [])}
    inputs.update(ctx.get("inputs", {}))
    ctx["inputs"] = inputs
    program = manifest["program"]
    if "/" in program and not Path(program).is_absolute():
        program = str(Path(manifest["plugin_dir"]) / program)
    argv = [program] + [expand(a, manifest, ctx) for a in manifest.get("args", [])]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    result = manifest.get("result", {"kind": "none"})
    if result["kind"] == "none" or proc.returncode != 0:
        return proc, None
    path = Path(expand(result["path"], manifest, ctx)).resolve()
    if output.resolve() not in path.parents:
        raise ManifestError("the result left the run folder")
    return proc, path
