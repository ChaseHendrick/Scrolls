"""Checks of the VC3D plugin manifests in plugins/ (docs/tools/vc3d-plugins.md).

The rules mirror VC3D's own parser (villa branch vc3d-plugins,
volume-cartographer/apps/VC3D/plugins/PluginManifest.cpp): a manifest that fails here
would be skipped by VC3D. The kit commands the manifests call are parsed with kit's
own parser, so a renamed option fails here first.
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"

SCHEMA = "vc3d-plugin/1"
KEYS = {"schema", "id", "name", "description", "menu", "program", "args", "inputs", "result", "homepage", "license"}
CONTEXT = {"volume", "volume_id", "segment", "segment_id", "project", "ink_overlay", "umbilicus", "point",
           "point_x", "point_y", "point_z", "region", "output", "plugin_dir"}
KINDS = {"none", "file", "segment", "ink_overlay", "points", "umbilicus"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
INPUT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def placeholders(template):
    """Placeholder names in a template, with VC3D's brace rules ({{ and }} are literal)."""
    names, i = [], 0
    while i < len(template):
        c = template[i]
        if c == "{":
            if template[i + 1:i + 2] == "{":
                i += 2
                continue
            close = template.find("}", i + 1)
            if close < 0:
                raise ValueError(f"unclosed '{{' in {template!r}")
            names.append(template[i + 1:close])
            i = close + 1
        elif c == "}":
            if template[i + 1:i + 2] == "}":
                i += 2
                continue
            raise ValueError(f"unmatched '}}' in {template!r}")
        else:
            i += 1
    return names


def problems(manifest):
    """Why VC3D would skip this manifest, as a list of strings (empty: it loads)."""
    out = []
    unknown = set(manifest) - KEYS
    if unknown:
        out.append(f"unknown keys {sorted(unknown)}")
    if manifest.get("schema") != SCHEMA:
        out.append("schema")
    if not ID_RE.match(str(manifest.get("id", ""))):
        out.append("id")
    if not str(manifest.get("name", "")).strip():
        out.append("name")
    program = str(manifest.get("program", ""))
    if not program.strip() or "{" in program or "}" in program:
        out.append("program")
    inputs = manifest.get("inputs", [])
    names = [i.get("name", "") for i in inputs if isinstance(i, dict)]
    if len(names) != len(inputs) or len(set(names)) != len(names) or not all(INPUT_RE.match(n) for n in names):
        out.append("inputs")
    templates = list(manifest.get("args", []))
    if not all(isinstance(a, str) for a in templates):
        out.append("args")
        templates = []
    result = manifest.get("result", {"kind": "none"})
    kind = result.get("kind")
    if kind not in KINDS:
        out.append("result.kind")
    elif kind != "none":
        path = str(result.get("path", ""))
        if not path.startswith("{output}/") or ".." in path.split("/"):
            out.append("result.path")
        templates.append(path)
    for template in templates:
        try:
            used = placeholders(template)
        except ValueError as e:
            out.append(str(e))
            continue
        for name in used:
            if name.startswith("input:"):
                if name[len("input:"):] not in names:
                    out.append(f"undeclared {{{name}}}")
            elif name not in CONTEXT:
                out.append(f"unknown {{{name}}}")
    return out


def load_all():
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(PLUGINS.glob("*.json"))}


class TestPluginManifests(unittest.TestCase):
    def test_every_manifest_loads_in_vc3d(self):
        manifests = load_all()
        self.assertGreaterEqual(len(manifests), 7)
        for name, manifest in manifests.items():
            with self.subTest(manifest=name):
                self.assertEqual(problems(manifest), [])
        ids = [m["id"] for m in manifests.values()]
        self.assertEqual(len(ids), len(set(ids)), "plugin ids must be unique")

    def test_the_checker_can_fail(self):
        good = {"schema": SCHEMA, "id": "a", "name": "A", "program": "p",
                "args": ["{segment}"], "result": {"kind": "points", "path": "{output}/p.json"}}
        self.assertEqual(problems(good), [])
        for bad, why in [
            ({**good, "schema": "vc3d-plugin/2"}, "schema"),
            ({**good, "run": "x"}, "unknown keys"),
            ({**good, "program": "{volume}/bin"}, "program"),
            ({**good, "args": ["{segments}"]}, "unknown {segments}"),
            ({**good, "args": ["{input:x}"]}, "undeclared {input:x}"),
            ({**good, "args": ["{volume"]}, "unclosed"),
            ({**good, "result": {"kind": "points", "path": "/tmp/p.json"}}, "result.path"),
            ({**good, "result": {"kind": "points", "path": "{output}/../p.json"}}, "result.path"),
            ({**good, "result": {"kind": "script", "path": "{output}/p"}}, "result.kind"),
        ]:
            with self.subTest(why=why):
                self.assertTrue(any(why in p for p in problems(bad)), problems(bad))

    def test_files_in_this_checkout_exist(self):
        # {plugin_dir}/... paths that point into the repository must exist; work/ holds the
        # user's downloaded weights and slices (ignored by git), so it is left out.
        for name, manifest in load_all().items():
            for arg in manifest.get("args", []):
                if not arg.startswith("{plugin_dir}/") or "{" in arg[len("{plugin_dir}/"):]:
                    continue
                rel = arg[len("{plugin_dir}/"):]
                target = (PLUGINS / rel).resolve()
                if (ROOT / "work") in target.parents:
                    continue
                with self.subTest(manifest=name, arg=arg):
                    self.assertTrue(target.is_file(), target)

    def test_kit_commands_accept_the_manifest_arguments(self):
        from kit.cli import _parser
        parser = _parser("python -m kit", None)
        values = {"ink_overlay": "map.png", "output": "/tmp/run", "plugin_dir": str(PLUGINS)}
        checked = 0
        for name, manifest in load_all().items():
            args = manifest.get("args", [])
            if not args or args[0] != "{plugin_dir}/run_kit.py":
                continue
            filled = []
            for arg in args[1:]:
                for key in placeholders(arg):
                    arg = arg.replace("{" + key + "}", values.get(key, "1"))
                filled.append(arg)
            with self.subTest(manifest=name):
                parsed = parser.parse_args(filled)
                self.assertEqual(parsed.command, filled[0])
                checked += 1
        self.assertGreaterEqual(checked, 2)

    def test_script_options_exist(self):
        # Scripts are not imported (they need torch); their argparse lines are read instead.
        for name, manifest in load_all().items():
            args = manifest.get("args", [])
            if not args or not args[0].startswith("{plugin_dir}/../scripts/"):
                continue
            source = (PLUGINS / args[0][len("{plugin_dir}/"):]).resolve().read_text(encoding="utf-8")
            for flag in (a for a in args[1:] if a.startswith("--")):
                with self.subTest(manifest=name, flag=flag):
                    self.assertIn(f'"{flag}"', source)

    def test_launcher_runs_kit_from_a_plain_clone(self):
        out = subprocess.run([sys.executable, "-I", str(PLUGINS / "run_kit.py"), "--help"],
                             capture_output=True, text=True, timeout=120, cwd="/")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("strokenet", out.stdout)


if __name__ == "__main__":
    unittest.main()
