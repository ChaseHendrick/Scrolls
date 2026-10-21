"""Tool registry: one manifest per tool, read by three front doors (the command line, VC3D and AutoPipeline).

  python -m kit tools list [--door D] [--accepts FROM] [SELECTION] [--json]   every tool with its doors; with a
                                             selection, only the tools it can start (VC3D's enabled menu items)
  python -m kit tools show ID [--json]       one manifest, its doors, its digest and its page's agent rules
  python -m kit tools check [--json]         every manifest against its page and the code (tooldocs check runs it)
  python -m kit tools availability ID [--json]   what the tool needs on this machine, and what is missing
  python -m kit tools selection [SELECTION] [--out FILE]   what VC3D has selected, as a vc3d-selection/1 document
  python -m kit tools plan ID [SELECTION] [--input NAME=PATH] [--param K=V] [--write FILE] [--json]   the dry
                                             run: the bound inputs, the command, the outputs, time, disk and every
                                             gate's verdict; writes nothing (exit 4), or, with --write, the plan with
                                             its digest (exit 0, so VC3D's "Plan:" entry shows it)
  python -m kit tools confirm DIGEST [--plan FILE] [--out RUN] [--json]   run a written plan: the inputs are bound
                                             again from its frozen selection and must give the same digest
  python -m kit tools run ID [SELECTION] [--input ...] [--param ...] [--out RUN] [--json]   bind, gate, run through
                                             the local cost ledger, audit the writes, write VC3D's handoff files
  python -m kit tools open RUN [--live [NAME]] [--apply] [--replace-points] [--json]   a finished run's handoff:
                                             print the allow-listed VC3D calls, or send them to a running VC3D
  python -m kit tools take KIND [--run RUN] [--output NAME] --out DIR   one checked output of a finished run,
                                             copied into DIR for VC3D's plugin host to load as KIND (segment,
                                             ink_overlay, points, umbilicus or file)
  python -m kit tools exec ID -- INPUT OUTPUT REVERSE   the command AutoPipeline's ink command engine calls for a
                                             registry ink backend (reg:ID)
  python -m kit tools export-vc3d DIR [--check] [--include-private]   VC3D plugin manifests (vc3d-plugin/1, villa's
                                             apps/VC3D/plugins) and a launcher, one manifest per tool VC3D can start

SELECTION is --selection FILE (vc3d-selection/1), --from-app [NAME] (read once from a running VC3D's agent bridge,
read-only calls), or the flags VC3D's plugin host fills from its placeholders: --volume {volume}, --segment
{segment}, --ink-overlay {ink_overlay}, --point {point}, --region {region}, --umbilicus {umbilicus}, --project
{project}; plus --crop Y0,Y1,X0,X1 (a box on the segment's canvas), --points FILE and --segments PATH (repeatable,
in order). A point is x,y,z and a region low x,y,z then high x,y,z, in the volume's level-0 voxels. --bridge-path
SOCKET adds what only that VC3D's agent bridge knows (its loaded segments by id, the voxel size), read once with
read-only calls; VC3D's launcher (bin/scrolls-tool) passes its own parent VC3D's bridge, found by its parent pid in
~/.vc3d/agent_bridge/PID.json or VC3D_AGENT_BRIDGE_SOCKET, never the newest bridge. An input with "bind": "bridge"
names segments by id or an ink detection by label, resolved from that frozen selection.

A manifest is kit/data/registry/ID.json (schema scrolls-tool/1), one per tool, so it ships with kit. Its authored part
says what the tool takes (inputs, each with where it binds from), its parameters, its command (an argument list whose
words may name only {in.NAME}, {in.NAME.FIELD}, {param.NAME}, {run} and {python}), its outputs (every path under
{run}/), its compute, its safety rules, an optional AutoPipeline stage and how VC3D shows it. Its `facts` block is
copied from the tool's page by `python -m kit.tooldocs index` (title, status, go-ahead, network, licence and the
page's Success, Not a pass and Never rules); nobody edits it. More manifests come from each folder in KIT_TOOL_PATH
and from ~/.vc3d/tools/ (community tools); the first id wins and a clash is a check problem.

The doors are worked out from each manifest, never typed: cli always; mcp when every input can be given as a path;
vc3d when every required input binds from what VC3D can select and nothing needs a yes, writes outside the run
folder, spends money or downloads; ap when the manifest names an AutoPipeline stage it can fill.

Safety, enforced before any command runs (a refusal is exit 3 and a result with the rule's name): no paid compute from
any door (KIT_ALLOW_MODAL and MODAL_* are removed from the child's environment; Modal and GPU work is planned only); the
local time and disk rule (AGENTS.md rule 11); writes only inside the run folder (cwd and TMPDIR are inside it, every
input, segment folder and project file is stat'ed before and after, and a change marks the run violated, exit 5); a
model-output or readout tool on a prize-eligible scroll is refused in public Scrolls and needs a preregistered
experiment in Scrolls-private; downloads need --yes-download; a tool whose page says it needs a yes, or that spends
quota (a ZeroGPU Space, the Anthropic API), never runs from here. After the run, the format gate checks each declared
output with its format's checker (tifxyz, umbilicus JSON, VC3D project, point collection, an overlay on the segment's
canvas, OME-Zarr; kit/villafmt.py's rules when that module is present) before anything is opened or handed on; a failure
is exit 3 and nothing opens. An output may name one converter manifest (convert), run in the same run folder and
recorded as its own stage. Every local run goes through kit.localcost (AGENTS.md rule 9; the ledger record is --slug,
else tools-YYYYMMDD made once, under KIT_TOOLS_LEDGER or kit's ledger root) and writes provenance.json and graph.json.
An ink map is model output, not a reading.

Exit codes: 0 done; 1 the tool or one of its checks failed; 2 bad arguments or an input that cannot be bound; 3 refused
by a safety gate before anything ran, or by the format gate after it; 4 planned only (a dry run, or work that belongs on
Modal or past the local time rule); 5 violated (the tool changed something outside its run folder; its results are not
opened).

Extensions: every kit/toolreg_ext_*.py beside this module is imported and its register(module) called, so a kit can
add openers (how an output kind is handed to VC3D), run-folder handlers and stage checks without changing this file.
Standard library only (numpy and tifffile, when present, write the 8-bit views of float maps). Scrolls-private
carries a copy of this module; keep the two the same.
"""

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import pkgutil
import platform
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["SCHEMA", "SELECTION_SCHEMA", "RESULT_SCHEMA", "PLUGIN_SCHEMA", "Tool", "Registry", "RegistryError",
           "BindError", "load", "validate_manifest", "doors", "selection_from", "selection_from_app", "bind",
           "plan", "run", "open_run", "exec_ink", "exec_repair", "stage_choices", "existing_backends", "ink_models", "plugin_manifests", "export_vc3d",
           "check", "facts_for", "write_facts", "load_cached", "register_opener", "register_run_folder",
           "register_stage_check", "vc3d_reasons", "vc3d_plan_reasons", "vc3d_entries", "parent_bridge",
           "enrich_from_bridge", "format_gate", "write_plan", "find_plan", "confirm", "take", "launch",
           "add_arguments", "main", "cli"]

KIT_ROOT = Path(__file__).resolve().parent.parent
ROOT = KIT_ROOT
REGISTRY_REL = Path("kit") / "data" / "registry"
PLUGINS_REL = Path("integrations") / "vc3d" / "plugins"
SCHEMA = "scrolls-tool/1"
SELECTION_SCHEMA = "vc3d-selection/1"
RESULT_SCHEMA = "vc3d-result/1"
PLAN_SCHEMA = "scrolls-tool-plan/1"
# villa's VC3D plugin host: apps/VC3D/plugins/PluginManifest.cpp on the vc3d-plugins lane of the combined VC3D suite
# (not merged into villa yet); read 20 Oct 2026.
PLUGIN_SCHEMA = "vc3d-plugin/1"
PLUGIN_PLACEHOLDERS = ("volume", "volume_id", "segment", "segment_id", "project", "ink_overlay", "umbilicus", "point",
                       "point_x", "point_y", "point_z", "region", "output", "plugin_dir")
PLUGIN_RESULTS = ("none", "file", "segment", "ink_overlay", "points", "umbilicus")
LAUNCHER = "scrolls-tool"
ENV_PATH = "KIT_TOOL_PATH"
ENV_LEDGER = "KIT_TOOLS_LEDGER"
SKIP_FILE = "skip.json"

EXIT_OK, EXIT_FAILED, EXIT_BAD, EXIT_REFUSED, EXIT_PLANNED, EXIT_VIOLATED = 0, 1, 2, 3, 4, 5
STATUS_EXIT = {"ok": EXIT_OK, "failed": EXIT_FAILED, "bad": EXIT_BAD, "refused": EXIT_REFUSED,
               "planned": EXIT_PLANNED, "violated": EXIT_VIOLATED}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
PROGRAM_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
PLACEHOLDER_NAME = re.compile(r"^(?:in\.[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)?|param\.[a-z][a-z0-9_]*|run|python)$")
ROLE_RE = re.compile(r"^(?:forward|control:[a-z0-9-]+)$")

# page: the id of the tool page a manifest belongs to, when it is not the manifest's own id (one page documents several
# entry points, such as an agent's tools: each gets its own manifest and shares the page's facts)
TOP_KEYS = ("schema", "id", "repo", "kind", "title", "notes", "page", "inputs", "params", "run", "outputs", "compute",
            "safety", "pipeline", "vc3d", "native", "facts")
REPOS = ("public", "private", "community")
KINDS = ("tool", "native", "pipeline", "converter")
INPUT_KEYS = ("from", "format", "required", "space", "pair_of", "label", "role", "axis_order", "bind")
AXIS_ORDERS = ("xyz", "zyx")
# host: from VC3D's plugin placeholders or explicit flags; bridge: a segment id or ink detection label that only the
# parent VC3D's agent bridge can turn into a path (VC3D_AGENT_BRIDGE_SOCKET or ~/.vc3d/agent_bridge/PID.json)
BINDS = ("host", "bridge")
# where an input binds from: what VC3D has selected (its plugin placeholders and its agent bridge's state), or an
# explicit path (--input NAME=PATH)
INPUT_FROM = ("volume", "segment", "segment.render", "segment.overlay", "segment.overlay.reverse", "segment.labels",
              "segment.mask", "segments", "point", "points", "region", "umbilicus", "project", "path")
VC3D_FROM = ("volume", "segment", "segment.render", "segment.overlay", "segment.overlay.reverse", "segment.labels",
             "segment.mask", "point", "region", "umbilicus", "project")
FROM_PLACEHOLDER = {"volume": "volume", "segment": "segment", "segment.render": "segment",
                    "segment.overlay": "ink_overlay", "segment.overlay.reverse": None, "segment.labels": "segment",
                    "segment.mask": "segment", "point": "point", "region": "region", "umbilicus": "umbilicus",
                    "project": "project"}
# a box on the segment's canvas carries the canvas size it is on (canvas_h, canvas_w; 0 when no segment is known), so
# a tool reading a map of another resolution can scale the box to it
FIELDS = {"point": ("x", "y", "z"), "region:segment_canvas": ("y0", "y1", "x0", "x1", "canvas_h", "canvas_w"),
          "region:volume": ("x0", "y0", "z0", "x1", "y1", "z1")}
SPACES = ("volume", "segment_canvas")
FORMATS = ("tifxyz", "ome-zarr", "zarr", "zarr-v2", "tif-stack", "volpkg-json", "vc3d-point-collection",
           "json-points", "ink-detections-json", "tiff", "tiff-uint8", "tiff-uint16", "tiff-float32", "npy", "npz",
           "png", "umbilicus-json", "villa-explicit-seed", "html", "json", "text", "url", "villa-label",
           "catalog-id")
PARAM_KEYS = ("type", "default", "enum", "help", "from", "required")
PARAM_TYPES = {"integer": int, "number": (int, float), "string": str, "boolean": bool}
PARAM_FROM = ("volume.voxel_um",)
RUN_KEYS = ("argv", "optional_args", "stdout", "timeout_s")
OUTPUT_KEYS = ("kind", "format", "path", "role", "on", "required", "label", "check", "axis_order", "convert")
OUTPUT_KINDS = ("surface", "overlay", "volume", "overlay_volume", "points", "umbilicus", "project", "labels",
                "report", "file", "link")
COMPUTE_KEYS = ("where", "typical_s", "disk_mb", "ram_gb", "scales_with", "note")
WHERE = ("local-cpu", "local-gpu", "modal-cpu", "modal-gpu", "none")
SAFETY_KEYS = ("model_output", "readout", "controls", "paid_compute", "writes_outside", "destructive", "network",
               "downloads_mb", "quota", "eligible_scrolls")
QUOTAS = ("zerogpu", "anthropic-api")
ELIGIBLE = ("refuse-public", "private-prereg")
PAID = ("never", "plan-only")
NETWORKS = ("none", "public-read", "download")
OUTSIDE_KINDS = ("volume-folder", "vc3d-cache-delete", "mirror", "kit-home", "segment-folder", "destructive")
PIPELINE_KEYS = ("stage", "contract", "input", "prediction", "seed", "output", "reverse", "flag", "pair_output",
                 "existing", "built_in")
# AutoPipeline's swappable stages (kit/apbackends.py STAGES in the kit that has it) and the contract each one passes
AP_STAGES = ("umbilicus", "trace", "flatten", "snap", "repair", "ink", "triage")
CONTRACTS = {"umbilicus": "umbilicus", "trace": "trace", "flatten": "flatten", "snap": "snap", "repair": "repair",
             "ink": "ink-command", "triage": "triage"}
REVERSE_MODES = ("flag", "pair")
VC3D_KEYS = ("menu", "label", "result", "confirm")
MENUS = ("segment", "segments", "viewer", "region", "tools")
NATIVE_KEYS = ("program", "vc3d_action", "source")
FACT_KEYS = ("title", "tagline", "status", "kind", "area", "page", "go_ahead", "network", "license", "checked",
             "success", "not_a_pass", "never")
# a VC3D bridge call a result may ask for: it opens or shows, never edits, saves, deletes, grows or launches
ALLOWED_OPEN = ("segments.attach", "segments.activate", "volume.attach", "volume.select", "points.load_json",
                "viewer.set_overlay", "viewer.center_on_point", "workspace.switch")
REPLACES = {"points.load_json": "every point collection in that VC3D"}
# the bridge calls a selection may read: they change nothing in the app
READ_CALLS = ("state.get", "segments.list", "points.list", "viewer.get_overlay")
ENV_BRIDGE = "VC3D_AGENT_BRIDGE_SOCKET"
ENV_PLUGIN_RUNS = "VC3D_PLUGIN_RUNS"
# what VC3D's plugin host writes into the fresh run folder before the program starts (PluginController::writeRecord)
HOST_FILES = ("plugin-run.json",)
TAKE_KINDS = ("segment", "ink_overlay", "points", "umbilicus", "file")
TAKE_PATHS = {"segment": "{output}/segment", "ink_overlay": "{output}/ink_overlay.tif",
              "points": "{output}/points.json", "umbilicus": "{output}/umbilicus.json", "file": "{output}/take.json"}
ASPECT_TOL = 0.02
LOCAL_LIMIT_S = {"mac": 600, "cloud": 1800}    # AGENTS.md rule 11
DISK_FLOOR_MB = 1024
AUDIT_LIMIT = 20000
HASH_MAX = 4 << 20
CLAIM = "Model output, not a reading"
NO_CONTROL = "no control: not a pass"
SCROLL_RE = re.compile(r"(?i)pherc[\s._-]*(paris[\s._-]*\d+|\d+[a-z]?)")

OPENERS = {}            # output kind -> fn(job, name, spec, path) -> {"files", "open", "plugin", "warnings"} or None
RUN_FOLDERS = []        # fn(run, live, apply, call) -> dict or None, for run folders another tool made (AutoPipeline's)
STAGE_CHECKS = []       # fn(manifest) -> list of problems with its pipeline block
HOOKS = {"ap_available": lambda: False}


class RegistryError(ValueError):
    """A bad manifest, argument or selection (exit 2)."""


class BindError(RegistryError):
    """An input that cannot be bound from the selection (exit 2); the message names what is missing."""


def register_opener(kind, fn):
    OPENERS[kind] = fn


def register_run_folder(fn):
    RUN_FOLDERS.append(fn)


def register_stage_check(fn):
    STAGE_CHECKS.append(fn)


# ---------------------------------------------------------------- small helpers


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(obj):
    return hashlib.sha256(_canonical(obj)).hexdigest()


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        os.chmod(tmp, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _dump(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n"


def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique)


def is_remote(location):
    return bool(re.match(r"^[a-z][a-z0-9+.-]*://", str(location)))


def _sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _repo_kind(root):
    try:
        from . import tooldocs
        return tooldocs.repo_kind(root)
    except Exception:  # noqa: BLE001 - no git or no tooldocs: treated as public, the stricter side
        return None


def _load_extensions():
    for info in sorted(pkgutil.iter_modules([str(Path(__file__).resolve().parent)]), key=lambda i: i.name):
        if info.name.startswith("toolreg_ext_"):
            importlib.import_module(f"{__package__}.{info.name}").register(sys.modules[__name__])


# ---------------------------------------------------------------- manifests


class Tool:
    """One manifest, where it came from, and its digest (the authored part only: facts change with the page)."""

    def __init__(self, manifest, path, source):
        self.m = manifest
        self.path = Path(path)
        self.source = source
        self.id = manifest["id"]
        self.digest = _digest({k: v for k, v in manifest.items() if k != "facts"})

    def __getitem__(self, key):
        return self.m.get(key)

    @property
    def kind(self):
        return self.m.get("kind", "tool")

    @property
    def facts(self):
        return self.m.get("facts") or {}

    @property
    def title(self):
        # a manifest that shares another tool's page (page) is one entry point of it: its own title names that entry
        own = self.m.get("title") if self.m.get("page") else None
        return own or self.facts.get("title") or self.m.get("title") or self.id

    @property
    def inputs(self):
        return self.m.get("inputs") or {}

    @property
    def params(self):
        return self.m.get("params") or {}

    @property
    def outputs(self):
        return self.m.get("outputs") or {}

    @property
    def safety(self):
        return self.m.get("safety") or {}

    @property
    def compute(self):
        return self.m.get("compute") or {}

    def required_inputs(self):
        return {n: s for n, s in self.inputs.items() if s.get("required", True)}


class Registry:
    def __init__(self, tools=None, skip=None, problems=None):
        self.tools = dict(tools or {})
        self.skip = dict(skip or {})
        self.problems = list(problems or [])

    def __iter__(self):
        return iter(sorted(self.tools.values(), key=lambda t: t.id))

    def __contains__(self, tool_id):
        return tool_id in self.tools

    def get(self, tool_id):
        if tool_id not in self.tools:
            near = [t for t in sorted(self.tools) if tool_id in t or t in tool_id]
            why = f" ({self.skip[tool_id]})" if tool_id in self.skip else ""
            raise RegistryError(f"no tool {tool_id!r} in the registry{why}" +
                                (f"; did you mean {', '.join(near)}?" if near else "; python -m kit tools list"))
        return self.tools[tool_id]


def manifest_dirs(root=ROOT, env=None):
    """(folder, source) in the order ids are taken: the repository's kit/data/registry, KIT_TOOL_PATH, ~/.vc3d/tools."""
    env = os.environ if env is None else env
    dirs = [(Path(root) / REGISTRY_REL, "kit")]
    for part in str(env.get(ENV_PATH, "")).split(os.pathsep):
        if part.strip():
            dirs.append((Path(part.strip()).expanduser(), "path"))
    home = env.get("HOME")
    if home:
        dirs.append((Path(home) / ".vc3d" / "tools", "community"))
    return dirs


def load(root=ROOT, env=None):
    """Every manifest the registry can see; bad ones become problems, never tools."""
    tools, problems, skip = {}, [], {}
    for folder, source in manifest_dirs(root, env):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name == SKIP_FILE:
                if source == "kit":
                    try:
                        skip = dict(_read_json(path).get("tools") or {})
                    except (OSError, ValueError, AttributeError) as exc:
                        problems.append(f"{path}: does not parse: {exc}")
                continue
            try:
                m = _read_json(path)
            except (OSError, ValueError) as exc:
                problems.append(f"{path}: does not parse: {exc}")
                continue
            bad = validate_manifest(m)
            if isinstance(m, dict) and m.get("id") and path.stem != m.get("id"):
                bad.append(f"the file is named {path.name} but the id is {m.get('id')!r}")
            if bad:
                problems += [f"{path}: {p}" for p in bad]
                continue
            if m["id"] in tools:
                problems.append(f"{path}: id {m['id']!r} is already taken by {tools[m['id']].path}")
                continue
            tools[m["id"]] = Tool(m, path, source)
    return Registry(tools, skip, problems)


_CACHE = {}


def load_cached(root=ROOT):
    """load(root) with the person's environment, kept until a manifest file changes (AutoPipeline asks often)."""
    dirs = manifest_dirs(root)
    key = (str(root), tuple(sorted((str(f), f.stat().st_mtime_ns) for d, _ in dirs if d.is_dir()
                                  for f in d.glob("*.json"))))
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = load(root)
    return _CACHE[key]


def _placeholders(text):
    return PLACEHOLDER.findall(text)


def _check_words(words, where, inputs, params, problems, allow_program=False):
    if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
        problems.append(f"{where} must be a list of strings")
        return
    for i, w in enumerate(words):
        if w.count("{") != w.count("}"):
            problems.append(f"{where}[{i}] {w!r} has an unbalanced brace")
            continue
        for name in _placeholders(w):
            if not PLACEHOLDER_NAME.match(name):
                problems.append(f"{where}[{i}] names {{{name}}}; a command may name only {{in.NAME}}, "
                                "{in.NAME.FIELD}, {param.NAME}, {run} and {python}")
                continue
            parts = name.split(".")
            if parts[0] == "in":
                spec = inputs.get(parts[1])
                if spec is None:
                    problems.append(f"{where}[{i}] names input {parts[1]!r}, which inputs does not declare")
                elif len(parts) == 3 and parts[2] not in _fields(spec):
                    problems.append(f"{where}[{i}] names field {parts[2]!r} of {parts[1]!r}; it has "
                                    f"{', '.join(_fields(spec)) or 'no fields'}")
            elif parts[0] == "param" and parts[1] not in params:
                problems.append(f"{where}[{i}] names param {parts[1]!r}, which params does not declare")
        literal = PLACEHOLDER.sub("X", w)
        if literal.startswith(("/", "~")) or ".." in Path(literal).parts or re.match(r"^[A-Za-z]:\\", literal):
            problems.append(f"{where}[{i}] {w!r} names a fixed path; a command names files only through placeholders "
                            "(outputs under {run}/)")
        if i == 0 and allow_program and w != "{python}" and not PROGRAM_RE.match(w):
            problems.append(f"{where}[0] must be {{python}} or a bare program name found on PATH, not {w!r}")


def _fields(spec):
    if spec.get("from") == "point":
        return FIELDS["point"]
    if spec.get("from") == "region":
        return FIELDS[f"region:{spec.get('space', 'volume')}"]
    return ()


def validate_manifest(m):
    """Problems with one manifest's shape, each a short sentence (empty when it is valid)."""
    p = []
    if not isinstance(m, dict):
        return ["a manifest is a JSON object"]
    unknown = sorted(set(m) - set(TOP_KEYS))
    if unknown:
        p.append(f"unknown key(s) {', '.join(unknown)}; a manifest has {', '.join(TOP_KEYS)}")
    if m.get("schema") != SCHEMA:
        p.append(f"schema must be {SCHEMA!r}")
    if not isinstance(m.get("id"), str) or not ID_RE.match(m["id"]):
        p.append("id must be 1 to 64 lowercase letters, digits or '-', starting with a letter or digit")
    if m.get("repo") not in REPOS:
        p.append(f"repo must be one of {', '.join(REPOS)}")
    kind = m.get("kind", "tool")
    if kind not in KINDS:
        p.append(f"kind must be one of {', '.join(KINDS)}")
    if m.get("repo") == "community" and not m.get("title"):
        p.append("a community manifest needs a title (it has no tool page)")
    for key in ("title", "notes"):
        if key in m and not isinstance(m[key], str):
            p.append(f"{key} must be a string")
    if "page" in m and (not isinstance(m["page"], str) or not ID_RE.match(m["page"])):
        p.append("page names a tool page by its id (docs/tools/ID.md)")
    if kind == "native":
        nat = m.get("native")
        if not isinstance(nat, dict) or not isinstance(nat.get("program"), str) or not PROGRAM_RE.match(
                nat.get("program", "")):
            p.append("a native manifest needs native.program, a bare program name")
        elif set(nat) - set(NATIVE_KEYS):
            p.append(f"native has unknown key(s) {', '.join(sorted(set(nat) - set(NATIVE_KEYS)))}")
        for key in ("run", "inputs", "outputs", "pipeline", "vc3d"):
            if key in m:
                p.append(f"a native manifest has no {key}: VC3D and villa run it themselves")
        return p
    inputs = m.get("inputs", {})
    if not isinstance(inputs, dict):
        p.append("inputs must be an object of name: spec")
        inputs = {}
    for name, spec in inputs.items():
        w = f"inputs.{name}"
        if not NAME_RE.match(name):
            p.append(f"{w}: an input name is lowercase letters, digits or '_'")
        if not isinstance(spec, dict):
            p.append(f"{w} must be an object")
            continue
        if set(spec) - set(INPUT_KEYS):
            p.append(f"{w} has unknown key(s) {', '.join(sorted(set(spec) - set(INPUT_KEYS)))}")
        if spec.get("from") not in INPUT_FROM:
            p.append(f"{w}.from must be one of {', '.join(INPUT_FROM)}")
        fmt = spec.get("format", [])
        if not isinstance(fmt, list) or set(fmt) - set(FORMATS):
            p.append(f"{w}.format must be a list of {', '.join(FORMATS)}")
        if "required" in spec and not isinstance(spec["required"], bool):
            p.append(f"{w}.required must be true or false")
        if spec.get("from") == "region" and spec.get("space", "volume") not in SPACES:
            p.append(f"{w}.space must be one of {', '.join(SPACES)}")
        if spec.get("from") == "segment.overlay.reverse":
            twin = spec.get("pair_of")
            if twin not in inputs or inputs.get(twin, {}).get("from") != "segment.overlay":
                p.append(f"{w}: a reverse twin names pair_of, an input bound from segment.overlay")
        if "role" in spec and not ROLE_RE.match(str(spec["role"])):
            p.append(f"{w}.role must be forward or control:NAME")
        if spec.get("axis_order", "xyz") not in AXIS_ORDERS:
            p.append(f"{w}.axis_order must be one of {', '.join(AXIS_ORDERS)} (the binder converts x,y,z for a "
                     "zyx tool)")
        if spec.get("bind", "host") not in BINDS:
            p.append(f"{w}.bind must be one of {', '.join(BINDS)}")
        elif spec.get("bind") == "bridge" and spec.get("from") not in ("path", "segments"):
            p.append(f"{w}: bind bridge is for a path or segments input (a segment id or an ink detection label)")
    params = m.get("params", {})
    if not isinstance(params, dict):
        p.append("params must be an object of name: spec")
        params = {}
    for name, spec in params.items():
        w = f"params.{name}"
        if not NAME_RE.match(name):
            p.append(f"{w}: a param name is lowercase letters, digits or '_'")
        if not isinstance(spec, dict):
            p.append(f"{w} must be an object")
            continue
        if set(spec) - set(PARAM_KEYS):
            p.append(f"{w} has unknown key(s) {', '.join(sorted(set(spec) - set(PARAM_KEYS)))}")
        if spec.get("type") not in PARAM_TYPES:
            p.append(f"{w}.type must be one of {', '.join(PARAM_TYPES)}")
        elif spec.get("default") is not None and not _typed_ok(spec["default"], spec["type"]):
            p.append(f"{w}.default is not a {spec['type']}")
        if "enum" in spec and (not isinstance(spec["enum"], list) or not spec["enum"]):
            p.append(f"{w}.enum must be a nonempty list")
        if "from" in spec and spec["from"] not in PARAM_FROM:
            p.append(f"{w}.from must be one of {', '.join(PARAM_FROM)}")
    run = m.get("run")
    if not isinstance(run, dict):
        p.append("run must be an object with argv")
        run = {}
    if set(run) - set(RUN_KEYS):
        p.append(f"run has unknown key(s) {', '.join(sorted(set(run) - set(RUN_KEYS)))}")
    if not run.get("argv"):
        p.append("run.argv must be a nonempty list of strings")
    else:
        _check_words(run["argv"], "run.argv", inputs, params, p, allow_program=True)
    opt = run.get("optional_args", {})
    if not isinstance(opt, dict):
        p.append("run.optional_args must be an object of input or param name: words")
        opt = {}
    for name, words in opt.items():
        if name not in inputs and name not in params:
            p.append(f"run.optional_args.{name} is neither an input nor a param")
        _check_words(words, f"run.optional_args.{name}", inputs, params, p)
    if "stdout" in run and not _under_run(run["stdout"]):
        p.append("run.stdout must be a path under {run}/")
    if "timeout_s" in run and (not isinstance(run["timeout_s"], int) or isinstance(run["timeout_s"], bool)
                               or run["timeout_s"] <= 0):
        p.append("run.timeout_s must be a positive integer")
    outputs = m.get("outputs", {})
    if not isinstance(outputs, dict) or not outputs:
        p.append("outputs must be a nonempty object of name: spec")
        outputs = {}
    for name, spec in outputs.items():
        w = f"outputs.{name}"
        if not NAME_RE.match(name):
            p.append(f"{w}: an output name is lowercase letters, digits or '_'")
        if not isinstance(spec, dict):
            p.append(f"{w} must be an object")
            continue
        if set(spec) - set(OUTPUT_KEYS):
            p.append(f"{w} has unknown key(s) {', '.join(sorted(set(spec) - set(OUTPUT_KEYS)))}")
        if spec.get("kind") not in OUTPUT_KINDS:
            p.append(f"{w}.kind must be one of {', '.join(OUTPUT_KINDS)}")
        if spec.get("format") not in FORMATS:
            p.append(f"{w}.format must be one of {', '.join(FORMATS)}")
        if not _under_run(spec.get("path", "")):
            p.append(f"{w}.path must start with {{run}}/ and stay inside it")
        else:
            for name2 in _placeholders(spec["path"]):
                if name2 != "run":
                    p.append(f"{w}.path may name only {{run}}")
        if "role" in spec and not ROLE_RE.match(str(spec["role"])):
            p.append(f"{w}.role must be forward or control:NAME")
        if "on" in spec and spec["on"] not in inputs:
            p.append(f"{w}.on names {spec['on']!r}, which inputs does not declare")
        if "check" in spec and not isinstance(spec["check"], bool):
            p.append(f"{w}.check must be true or false (true, the default, turns on the format gate)")
        if spec.get("axis_order", "xyz") not in AXIS_ORDERS:
            p.append(f"{w}.axis_order must be one of {', '.join(AXIS_ORDERS)}")
        if "convert" in spec and (not isinstance(spec["convert"], str) or not ID_RE.match(spec["convert"])):
            p.append(f"{w}.convert names one converter manifest by its id")
    comp = m.get("compute", {})
    if not isinstance(comp, dict) or set(comp) - set(COMPUTE_KEYS):
        p.append(f"compute must be an object with {', '.join(COMPUTE_KEYS)}")
        comp = {}
    if comp.get("where", "local-cpu") not in WHERE:
        p.append(f"compute.where must be one of {', '.join(WHERE)}")
    for key in ("typical_s", "disk_mb", "ram_gb"):
        if key in comp and (not isinstance(comp[key], (int, float)) or isinstance(comp[key], bool) or comp[key] < 0):
            p.append(f"compute.{key} must be a number of at least 0")
    saf = m.get("safety")
    if not isinstance(saf, dict):
        p.append("safety must be an object (model_output, paid_compute, network at least)")
        saf = {}
    if set(saf) - set(SAFETY_KEYS):
        p.append(f"safety has unknown key(s) {', '.join(sorted(set(saf) - set(SAFETY_KEYS)))}")
    for key in ("model_output", "readout", "destructive"):
        if key in saf and not isinstance(saf[key], bool):
            p.append(f"safety.{key} must be true or false")
    if not isinstance(saf.get("model_output"), bool):
        p.append("safety.model_output must say true or false")
    if saf.get("paid_compute") not in PAID:
        p.append(f"safety.paid_compute must be one of {', '.join(PAID)}")
    if saf.get("network") not in NETWORKS:
        p.append(f"safety.network must be one of {', '.join(NETWORKS)}")
    wo = saf.get("writes_outside", [])
    if not isinstance(wo, list) or set(wo) - set(OUTSIDE_KINDS):
        p.append(f"safety.writes_outside must be a list of {', '.join(OUTSIDE_KINDS)}")
    if "downloads_mb" in saf and (not isinstance(saf["downloads_mb"], (int, float)) or saf["downloads_mb"] < 0):
        p.append("safety.downloads_mb must be a number of at least 0")
    if saf.get("quota") is not None and saf.get("quota") not in QUOTAS:
        p.append(f"safety.quota must be null or one of {', '.join(QUOTAS)}")
    elif saf.get("quota") and isinstance(m.get("facts"), dict) and not m["facts"].get("go_ahead"):
        p.append(f"safety.quota {saf['quota']}: a tool that spends quota says on its page that it needs a yes "
                 "(Go-ahead: Needed)")
    if "eligible_scrolls" in saf and saf["eligible_scrolls"] not in ELIGIBLE:
        p.append(f"safety.eligible_scrolls must be one of {', '.join(ELIGIBLE)}")
    controls = saf.get("controls", [])
    if not isinstance(controls, list):
        p.append("safety.controls must be a list of input or output names")
        controls = []
    for c in controls:
        if c not in inputs and c not in outputs:
            p.append(f"safety.controls names {c!r}, which is neither an input nor an output")
    if saf.get("model_output"):
        forward_maps = [n for n, s in outputs.items() if isinstance(s, dict) and s.get("kind") == "overlay"
                        and s.get("role", "forward") == "forward"]
        if forward_maps and not any(isinstance(outputs.get(c), dict) and str(outputs[c].get("role", "")).startswith(
                "control:") for c in controls):
            p.append("a model-output tool that makes maps declares at least one control output (role control:NAME) "
                     "in safety.controls")
    pipe = m.get("pipeline")
    if pipe is not None:
        p += _check_pipeline(pipe, inputs, outputs, kind, m.get("params") if isinstance(m.get("params"), dict) else None)
    vc = m.get("vc3d")
    if vc is not None:
        if not isinstance(vc, dict) or set(vc) - set(VC3D_KEYS):
            p.append(f"vc3d must be an object with {', '.join(VC3D_KEYS)}")
        else:
            if vc.get("menu") not in MENUS:
                p.append(f"vc3d.menu must be one of {', '.join(MENUS)}")
            if "result" in vc and vc["result"] not in outputs:
                p.append(f"vc3d.result names {vc['result']!r}, which outputs does not declare")
            if "confirm" in vc and not isinstance(vc["confirm"], bool):
                p.append("vc3d.confirm must be true or false (true makes Plan: and Run planned: entries)")
    if kind == "converter":
        if vc is not None or pipe is not None:
            p.append("a converter manifest never reaches a menu or a stage: it runs as an output's convert step")
        if not any(isinstance(s, dict) and s.get("required", True) for s in inputs.values()):
            p.append("a converter takes one required input, the output it converts")
    facts = m.get("facts")
    if facts is not None and (not isinstance(facts, dict) or set(facts) - set(FACT_KEYS)):
        p.append(f"facts is generated by python -m kit.tooldocs index and has only {', '.join(FACT_KEYS)}")
    return p


def _check_pipeline(pipe, inputs, outputs, kind, params=None):
    p = []
    if not isinstance(pipe, dict) or set(pipe) - set(PIPELINE_KEYS):
        return [f"pipeline must be an object with {', '.join(PIPELINE_KEYS)}"]
    if "built_in" in pipe:
        if set(pipe) - {"built_in"}:
            p.append("pipeline.built_in marks a tool AutoPipeline already calls inside a stage; it takes no other key")
        return p
    stage = pipe.get("stage")
    if stage not in AP_STAGES:
        return [f"pipeline.stage must be one of {', '.join(AP_STAGES)}"]
    if "existing" in pipe:
        if not isinstance(pipe["existing"], str) or set(pipe) - {"stage", "existing"}:
            p.append("pipeline.existing names the stage's backend this tool already is; it takes only stage")
        elif PLACEHOLDER.fullmatch(pipe["existing"]):
            ref = pipe["existing"][1:-1]
            spec = (params or {}).get(ref[6:]) if ref.startswith("param.") else None
            if not isinstance(spec, dict) or not isinstance(spec.get("enum"), list) or not spec["enum"]:
                p.append("pipeline.existing as {param.NAME} names a declared param with an enum: each value is one "
                         "of the stage's backends")
        return p
    if pipe.get("contract") != CONTRACTS[stage]:
        p.append(f"pipeline.contract for stage {stage} is {CONTRACTS[stage]!r}")
    if stage == "ink":
        if pipe.get("input") not in inputs:
            p.append("pipeline.input names the input the ink engine's {input} binds to")
        if pipe.get("reverse") not in REVERSE_MODES:
            p.append(f"pipeline.reverse must be one of {', '.join(REVERSE_MODES)} (AutoPipeline's ink engine calls the "
                     "command once with reverse 0 and once with 1 on the same input)")
        elif pipe["reverse"] == "pair":
            if pipe.get("pair_output") not in outputs or not str(outputs[pipe["pair_output"]].get("role", "")).startswith(
                    "control:"):
                p.append("pipeline.pair_output names the output that holds the reverse-depth map (role control:NAME)")
        elif pipe["reverse"] == "flag" and not (isinstance(pipe.get("flag"), list) and pipe["flag"]):
            p.append("pipeline.flag is the argument list that makes the tool read the depth order reversed")
    elif stage == "repair":
        p += _check_repair(pipe, inputs, outputs, params or {})
    else:
        p.append(f"stage {stage} has no generic registry runner in AutoPipeline yet: name the stage's existing backend "
                 "with pipeline.existing, or mark the tool built_in")
    return p


def _check_repair(pipe, inputs, outputs, params):
    """The repair contract: AutoPipeline's qa stage hands a trace it rejected for a sheet switch (input, a tifxyz
    bound from the segment), the surface prediction the trace was made on (prediction, the plan's prediction_url)
    and, when the manifest takes one, the trace's planned seed (seed, a point); the tool writes a repaired tifxyz
    copy (output) inside its run folder, and qa checks the copy again by its own rule (exec_repair)."""
    p = []
    if set(pipe) - {"stage", "contract", "input", "prediction", "seed", "output"}:
        p.append("pipeline for stage repair takes stage, contract, input, prediction, seed and output only")
    trace = inputs.get(pipe.get("input")) if isinstance(pipe.get("input"), str) else None
    if not isinstance(trace, dict) or trace.get("from") != "segment" or "tifxyz" not in (trace.get("format") or []):
        p.append("pipeline.input names the input that takes the trace: from segment, format tifxyz")
    pred = inputs.get(pipe.get("prediction")) if isinstance(pipe.get("prediction"), str) else None
    if not isinstance(pred, dict) or pred.get("from") not in ("volume", "path"):
        p.append("pipeline.prediction names the input that takes the surface prediction (from volume or path)")
    if "seed" in pipe:
        seed = inputs.get(pipe["seed"]) if isinstance(pipe["seed"], str) else None
        if not isinstance(seed, dict) or seed.get("from") != "point" or seed.get("required", True):
            p.append("pipeline.seed names an optional input from point that takes the trace's planned seed")
    out = outputs.get(pipe.get("output")) if isinstance(pipe.get("output"), str) else None
    if not isinstance(out, dict) or out.get("kind") != "surface" or out.get("format") != "tifxyz":
        p.append("pipeline.output names the output that holds the repaired copy: kind surface, format tifxyz")
    filled = {pipe.get(k) for k in ("input", "prediction", "seed")}
    extra = sorted(n for n, s in inputs.items() if isinstance(s, dict) and s.get("required", True) and n not in filled)
    if extra:
        p.append(f"AutoPipeline's repair stage fills only the trace, the prediction and the seed; required input(s) "
                 f"{', '.join(extra)} would be left unbound")
    loose = sorted(n for n, s in params.items() if isinstance(s, dict) and s.get("default") is None
                   and s.get("from") != "volume.voxel_um")
    if loose:
        p.append(f"AutoPipeline's repair stage sets only the voxel size; param(s) {', '.join(loose)} need a default")
    return p


def _under_run(path):
    return isinstance(path, str) and path.startswith("{run}/") and ".." not in path.split("/")


def _typed_ok(value, typ):
    if typ in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, PARAM_TYPES[typ])


# ---------------------------------------------------------------- doors


def doors(tool):
    """The doors a manifest opens, worked out from it: cli, mcp, vc3d, ap (or native for villa's own tools)."""
    if tool.kind == "native":
        return ["native"]
    out = ["cli", "mcp"]
    if vc3d_reasons(tool) == []:
        out.append("vc3d")
    pipe = tool["pipeline"] or {}
    if pipe.get("stage") and HOOKS["ap_available"]():
        out.append("ap")
    return out


def vc3d_reasons(tool):
    """Why VC3D gets no entry at all for this tool (empty when it gets one): the page needs a yes, it spends quota,
    writes outside its run folder, is destructive, or has a required input VC3D cannot supply."""
    why = []
    if tool.kind != "tool":
        why.append(f"a {tool.kind} manifest")
    for name, spec in tool.required_inputs().items():
        if spec.get("from") not in VC3D_FROM and spec.get("bind") != "bridge":
            why.append(f"input {name} binds from {spec.get('from')}, which VC3D's plugin host does not pass")
    saf = tool.safety
    if tool.facts.get("go_ahead"):
        why.append("its page says it needs a yes")
    if saf.get("quota"):
        why.append(f"it spends {saf['quota']} quota, which needs Chase's yes for each use")
    if saf.get("writes_outside"):
        why.append("it writes outside its run folder")
    if saf.get("destructive"):
        why.append("it is destructive")
    return why


def vc3d_plan_reasons(tool):
    """Why VC3D gets only a "Plan:" entry for this tool (a priced dry run, nothing runs): GPU or Modal work, a
    first-use download, or a typical time over the local rule on Chase's Mac (AGENTS.md rule 11)."""
    why = []
    saf, comp = tool.safety, tool.compute
    if saf.get("paid_compute") != "never" or comp.get("where", "local-cpu") in ("modal-cpu", "modal-gpu", "local-gpu"):
        why.append("GPU or Modal work is planned only")
    if saf.get("downloads_mb"):
        why.append(f"it downloads about {saf['downloads_mb']:g} MB on first use, which needs --yes-download")
    typical = comp.get("typical_s")
    if isinstance(typical, (int, float)) and typical > LOCAL_LIMIT_S["mac"]:
        why.append(f"about {typical:g} s, over the {LOCAL_LIMIT_S['mac']} s local rule on Chase's Mac")
    return why


def vc3d_entries(tool):
    """The VC3D menu entries a tool gets: [] (none), ["plan"], ["plan", "confirm"] (vc3d.confirm) or ["run"]."""
    if vc3d_reasons(tool):
        return []
    if vc3d_plan_reasons(tool):
        return ["plan"]
    return ["plan", "confirm"] if (tool["vc3d"] or {}).get("confirm") else ["run"]


# ---------------------------------------------------------------- selection


def _floats(text, n, what):
    try:
        vals = [float(v) for v in str(text).replace(" ", "").split(",")]
    except ValueError:
        raise RegistryError(f"{what} {text!r} is not {n} numbers separated by commas") from None
    if len(vals) != n or any(v != v or v in (float("inf"), float("-inf")) for v in vals):
        raise RegistryError(f"{what} {text!r} is not {n} finite numbers separated by commas")
    return vals


def _volume_info(location, voxel_um=None):
    info = {"location": str(location), "remote": is_remote(location)}
    if not info["remote"]:
        p = Path(location).expanduser()
        info["location"] = str(p.resolve()) if p.exists() else str(p)
        info["id"] = p.name
        meta = p / "meta.json"
        if voxel_um is None and meta.is_file():
            try:
                v = _read_json(meta).get("voxelsize")
                voxel_um = float(v) if isinstance(v, (int, float)) and v > 0 else None
            except (OSError, ValueError, AttributeError):
                pass
    else:
        info["id"] = str(location).rstrip("/").rsplit("/", 1)[-1]
    if voxel_um is not None:
        info["voxel_um"] = float(voxel_um)
    return info


LABEL_TYPES = {"labels": ("ink-labels", "inklabels", "ink labels", "labels"),
               "mask": ("supervision", "supervision-mask", "supervision mask", "supervision_mask", "mask")}


def _record_role(r, label):
    """A record's role: kit_role when given, else labels or mask from its artifact_type, else from its label text
    (reverse and shuffle mark controls, as AutoPipeline's records name them), else forward."""
    if r.get("kit_role"):
        return str(r["kit_role"])
    kind = str(r.get("artifact_type") or "").strip().lower()
    for role, names in LABEL_TYPES.items():
        if kind in names:
            return role
    low = label.lower()
    return "control:reverse" if "reverse" in low else "control:shuffle" if "shuffle" in low else "forward"


def _ink_records(segdir):
    """SEGDIR's ink detection records as VC3D reads them: ink-detections.json, else, when that file is missing or
    empty, catalog-origin.json's ink_detections (OpenDataSegmentCache.cpp). Each is {path, label, role, pair}; pair
    is the model a record's maps share (AutoPipeline's kit_villafmt.model), so a forward map finds its own controls."""
    recs = []
    for path, key in ((Path(segdir) / "ink-detections.json", None), (Path(segdir) / "catalog-origin.json",
                                                                       "ink_detections")):
        if recs or not path.is_file():
            continue
        try:
            doc = _read_json(path)
        except (OSError, ValueError):
            continue
        doc = doc.get(key) if key and isinstance(doc, dict) else doc
        recs = doc if isinstance(doc, list) else []
    out = []
    for r in recs:
        if isinstance(r, dict) and isinstance(r.get("local_file"), str) and r["local_file"]:
            f = Path(r["local_file"])
            f = f if f.is_absolute() else Path(segdir) / f
            label = str(r.get("label") or f.name)
            rec = {"path": str(f), "label": label, "role": _record_role(r, label)}
            meta = r.get("kit_villafmt") if isinstance(r.get("kit_villafmt"), dict) else {}
            if meta.get("model"):
                rec["pair"] = str(meta["model"])
            out.append(rec)
    return out


def _find_render(segdir):
    seg = Path(segdir)
    for cand in (seg / "layers", seg / "surface_volume"):
        if cand.is_dir() and any(cand.glob("*.tif")):
            return str(cand)
    zarrs = sorted(d for d in seg.glob("*.zarr") if d.is_dir() and not re.search(r"(inklabels|supervision|mask|"
                                                                                  r"validation)", d.name))
    return str(zarrs[0]) if zarrs else None


def _segment_info(path, render=None):
    seg = Path(path).expanduser()
    info = {"path": str(seg.resolve()) if seg.exists() else str(seg), "id": seg.name}
    meta = seg / "meta.json"
    if meta.is_file():
        try:
            m = _read_json(meta)
            if isinstance(m, dict):
                if m.get("uuid"):
                    info["uuid"] = str(m["uuid"])
                cat = {k: m[k] for k in sorted(m) if str(k).startswith("vc_open_data_") and isinstance(m[k], str)}
                if cat:
                    info["catalog"] = cat
        except (OSError, ValueError):
            pass
    info["render"] = str(render) if render else (_find_render(seg) if seg.is_dir() else None)
    info["overlays"] = _ink_records(seg) if seg.is_dir() else []
    return info


def selection_from(volume=None, segment=None, ink_overlay=None, point=None, region=None, crop=None, umbilicus=None,
                   project=None, points=None, segments=None, render=None, voxel_um=None, source="flags", app=None):
    """A vc3d-selection/1 document from explicit values (what VC3D's plugin host passes, or a person types)."""
    doc = {"schema": SELECTION_SCHEMA, "source": source, "frame": "x, y, z in the volume's level-0 voxels"}
    if app:
        doc["app"] = app
    if project:
        doc["project"] = str(Path(project).expanduser())
    if volume:
        doc["volume"] = _volume_info(volume, voxel_um)
    elif voxel_um is not None:
        doc["volume"] = {"voxel_um": float(voxel_um)}
    if segment:
        doc["segment"] = _segment_info(segment, render)
    if ink_overlay:
        doc["ink_overlay"] = str(Path(ink_overlay).expanduser())
    if segments:
        doc["segments"] = [_segment_info(s) for s in segments]
    if point is not None:
        doc["point"] = point if isinstance(point, list) else _floats(point, 3, "--point")
    if region is not None:
        r = region if isinstance(region, list) else _floats(region, 6, "--region")
        doc["region"] = {"space": "volume", "low": [min(r[i], r[i + 3]) for i in range(3)],
                         "high": [max(r[i], r[i + 3]) for i in range(3)]}
    if crop is not None:
        c = crop if isinstance(crop, list) else [int(v) for v in _floats(crop, 4, "--crop")]
        if c[1] <= c[0] or c[3] <= c[2]:
            raise RegistryError(f"--crop {crop!r}: Y1 must exceed Y0 and X1 must exceed X0")
        doc["crop"] = {"space": "segment_canvas", "y0": int(c[0]), "y1": int(c[1]), "x0": int(c[2]), "x1": int(c[3])}
    if umbilicus:
        doc["umbilicus"] = str(Path(umbilicus).expanduser())
    if points:
        doc["points"] = {"path": str(Path(points).expanduser())}
    doc["digest"] = _digest({k: v for k, v in doc.items() if k != "digest"})
    return doc


def read_selection(path):
    doc = _read_json(path)
    if not isinstance(doc, dict) or doc.get("schema") != SELECTION_SCHEMA:
        raise RegistryError(f"{path}: not a {SELECTION_SCHEMA} document")
    return doc


def _bridge():
    try:
        return importlib.import_module(f"{__package__}.vc3d_bridge")
    except ImportError:
        return None


def resolve_bridge(name=None):
    """The socket path of a running VC3D's agent bridge: name (a socket path, or a bridge name in VC3D's registry),
    else the newest live bridge. Needs kit.vc3d_bridge (Scrolls-private and the AutoPipeline package)."""
    br = _bridge()
    if br is None:
        raise RegistryError("reading a running VC3D needs kit/vc3d_bridge.py (in the AutoPipeline package and "
                            "Scrolls-private); pass the selection as flags or --selection FILE instead")
    if name and Path(name).expanduser().exists():
        return str(Path(name).expanduser())
    reg = Path(br.REGISTRY)
    for f in sorted(reg.glob("*.json")) if reg.is_dir() else []:
        try:
            rec = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if name and rec.get("name") == name and rec.get("path"):
            return rec["path"]
    if name:
        raise RegistryError(f"no running VC3D with an agent bridge named {name!r}")
    rec = br.discover()
    if not rec:
        raise RegistryError("no running VC3D with its agent bridge on (start it with --agent-bridge-name NAME)")
    return rec["path"]


def _rpc(path, method, params=None, timeout=30.0):
    """One JSON-RPC 2.0 request over a VC3D agent bridge socket (one JSON line each way); kit.vc3d_bridge's client
    when this kit has it."""
    br = _bridge()
    if br is not None:
        return br.call(path, method, params, timeout=timeout)
    import socket
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sk:
        sk.settimeout(timeout)
        sk.connect(str(path))
        sk.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while True:
            chunk = sk.recv(1 << 20)
            if not chunk:
                raise RegistryError(f"VC3D's agent bridge closed the connection during {method}")
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("id") == 1:
                    if "error" in msg:
                        raise RegistryError(f"VC3D's agent bridge refused {method}: "
                                            f"{(msg.get('error') or {}).get('message')}")
                    return msg.get("result") or {}


def parent_bridge(ppid=None, env=None):
    """{path, how} of the agent bridge of the VC3D that started this process, or None: VC3D_AGENT_BRIDGE_SOCKET when
    the host exports it, else ~/.vc3d/agent_bridge/PPID.json (AgentBridgeServer::writeRegistryFile names the file by
    VC3D's pid). Never the newest bridge: another person's or another window's VC3D is not this one."""
    env = os.environ if env is None else env
    sock = env.get(ENV_BRIDGE)
    if sock and Path(sock).exists():
        return {"path": str(sock), "how": ENV_BRIDGE}
    home = env.get("HOME")
    if not home:
        return None
    pid = os.getppid() if ppid is None else int(ppid)
    rec_path = Path(home) / ".vc3d" / "agent_bridge" / f"{pid}.json"
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    path = rec.get("path") if isinstance(rec, dict) else None
    if not path or not Path(path).exists() or str(rec.get("pid", pid)) != str(pid):
        return None
    return {"path": str(path), "name": rec.get("name"), "how": f"{rec_path} (VC3D pid {pid}, the launcher's parent)"}


def enrich_from_bridge(sel, sock, call=None):
    """The selection plus what only that VC3D's bridge knows, read once with read-only calls (state.get,
    segments.list): the volume's id and voxel size and every loaded segment by id, for bridge-bound inputs. A volume
    that differs from the one the plugin host passed is refused. Returns a new, re-digested selection; a bridge that
    does not answer is recorded and the selection is otherwise unchanged."""
    call = call or _rpc
    doc = {k: v for k, v in sel.items() if k != "digest"}
    app = dict(doc.get("app") or {})
    app["bridge"] = str(sock)
    try:
        state = call(sock, "state.get", None) or {}
        listed = (call(sock, "segments.list", {}) or {}).get("segments") or []
    except Exception as exc:  # noqa: BLE001 - a silent bridge only loses the bridge-bound inputs
        app.pop("bridge")
        app["bridge_error"] = f"{sock}: {exc}"
        doc["app"] = app
        doc["digest"] = _digest(doc)
        return doc
    vol = state.get("volume") or {}
    v = dict(doc.get("volume") or {})
    if vol.get("path") and v.get("location") and not v.get("remote") and not is_remote(vol["path"]):
        if Path(vol["path"]).expanduser().resolve() != Path(v["location"]).resolve():
            raise RegistryError(f"VC3D's bridge has volume {vol['path']} open, not {v['location']}: the selection "
                                "changed; start the entry again")
    if not v.get("location") and vol.get("path"):
        v.update(_volume_info(vol["path"], v.get("voxel_um")))
    if "voxel_um" not in v and isinstance(vol.get("voxelSize"), (int, float)) and vol["voxelSize"] > 0:
        v["voxel_um"] = float(vol["voxelSize"])
    if v:
        doc["volume"] = v
    segs = {str(x["id"]): str(x["path"]) for x in listed if x.get("id") and x.get("path")}
    active = (state.get("activeSurface") or {}).get("id")
    app.update(volume_id=vol.get("id"), active_segment=active, segments=segs)
    if not doc.get("segment") and active and str(active) in segs:
        doc["segment"] = _segment_info(segs[str(active)])     # its ink detections, for labels and twins
    doc["app"] = app
    doc["source"] = str(doc.get("source", "flags")).split("+")[0] + "+bridge"
    doc["digest"] = _digest(doc)
    return doc


def selection_from_app(name=None, call=None):
    """Read what a running VC3D has selected, with read-only bridge calls (state.get, segments.list); nothing is sent
    that changes the app."""
    sock = resolve_bridge(name) if call is None else (name or "fake")
    call = call or _rpc
    state = call(sock, "state.get", None) or {}
    vol = state.get("volume") or {}
    active = (state.get("activeSurface") or {}).get("id")
    segs = {str(s["id"]): str(s["path"]) for s in (call(sock, "segments.list", {}) or {}).get("segments") or []
            if s.get("id") and s.get("path")}
    seg_path = segs.get(str(active)) if active else None
    poi = ((state.get("focusPoi") or {}).get("position")) or None
    point = [float(poi[k]) for k in "xyz"] if isinstance(poi, dict) and all(k in poi for k in "xyz") else None
    return selection_from(volume=vol.get("path") or None, segment=seg_path, point=point,
                          project=(state.get("vpkg") or {}).get("path"),
                          voxel_um=vol.get("voxelSize") if isinstance(vol.get("voxelSize"), (int, float)) else None,
                          source="bridge", app={"bridge": str(sock), "volume_id": vol.get("id"),
                                                "active_segment": active, "segments": segs})


# ---------------------------------------------------------------- binding


def _segment(sel, need):
    seg = sel.get("segment")
    if not seg or not seg.get("path"):
        raise BindError(f"needs an active segment ({need})")
    return seg


def _labels_in_records(seg, role, formats):
    """A label or mask file the segment's ink detection records name (artifact_type or kit_role), when it exists in
    one of the formats asked for; records come before villa's file names."""
    exts = {"zarr": ".zarr", "zarr-v2": ".zarr", "ome-zarr": ".zarr", "tiff": (".tif", ".tiff"), "png": ".png"}
    allowed = [e for f in (formats or ["zarr", "tiff", "png"]) for e in
               (exts.get(f) if isinstance(exts.get(f), tuple) else (exts.get(f),)) if e]
    for o in seg.get("overlays") or []:
        p = Path(o["path"])
        if o.get("role") == role and p.exists() and p.suffix.lower() in allowed:
            return str(p)
    return None


def _labels_in(segdir, segid, stems, formats):
    exts = {"zarr": (".zarr",), "zarr-v2": (".zarr",), "ome-zarr": (".zarr",), "tiff": (".tif", ".tiff"),
            "png": (".png",)}
    allowed = [e for f in (formats or ["zarr", "tiff", "png"]) for e in exts.get(f, ())]
    for stem in stems:
        for name in (f"{segid}_{stem}", stem):
            for ext in allowed:
                cand = Path(segdir) / f"{name}{ext}"
                if cand.exists():
                    return str(cand)
    return None


def _twin_stems(stem):
    """The stems a reverse-depth twin of a forward map's stem may have: STEM_reverse or STEM-reverse, and for a map
    named with a forward variant letter (ink.py's ink_f, AutoPipeline's MODEL-f) the same name with r."""
    out = [f"{stem}_reverse", f"{stem}-reverse"]
    m = re.match(r"^(.*[_-])f$", stem)
    if m:
        out.append(m.group(1) + "r")
    return out


def _twin(forward, sel):
    """The reverse-depth control of a forward map: the segment's ink detection record with role control:reverse that
    shares its model (pair) or its stem rule, else a file beside it by the stem rule (_twin_stems)."""
    fwd = Path(forward)
    stems = _twin_stems(fwd.stem)
    recs = (sel.get("segment") or {}).get("overlays") or []
    mine = next((o for o in recs if Path(o["path"]) == fwd), None)
    for o in recs:
        if o.get("role") != "control:reverse":
            continue
        if Path(o["path"]).stem in stems or (mine and mine.get("pair") and o.get("pair") == mine["pair"]):
            return o["path"]
    for stem in stems:
        cand = fwd.with_name(stem + fwd.suffix)
        if cand.exists():
            return str(cand)
    return None


def _voxel(sel):
    v = (sel.get("volume") or {}).get("voxel_um")
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def _canvas_crop(sel, segdir):
    """A volume-space focus region as a box on the segment's canvas: the grid cells whose vertex lies inside it,
    scaled by meta.json's scale. Needs numpy and tifffile."""
    try:
        import numpy as np
        import tifffile
    except ImportError:
        raise BindError("turning VC3D's focus region into a box on the segment's canvas needs numpy and tifffile; "
                        "pass --crop Y0,Y1,X0,X1 instead") from None
    r = sel["region"]
    seg = Path(segdir)
    try:
        xyz = [np.asarray(tifffile.imread(seg / f"{a}.tif"), dtype=np.float64) for a in "xyz"]
        meta = _read_json(seg / "meta.json")
    except (OSError, ValueError) as exc:
        raise BindError(f"cannot read the segment's tifxyz grid in {seg}: {exc}") from exc
    inside = np.ones(xyz[0].shape, dtype=bool)
    for k in range(3):
        inside &= (xyz[k] >= r["low"][k]) & (xyz[k] <= r["high"][k]) & (xyz[k] != -1)
    if not inside.any():
        raise BindError("VC3D's focus region holds no vertex of the active segment")
    rows, cols = np.nonzero(inside)
    sc = meta.get("scale") if isinstance(meta, dict) else None
    sx, sy = (float(sc[0]), float(sc[1])) if isinstance(sc, list) and len(sc) >= 2 and sc[0] and sc[1] else (1.0, 1.0)
    return {"space": "segment_canvas", "y0": int(rows.min() / sy), "y1": int((rows.max() + 1) / sy),
            "x0": int(cols.min() / sx), "x1": int((cols.max() + 1) / sx)}


def _check_format(name, path, spec):
    fmt = spec.get("format") or []
    if not fmt or is_remote(path):
        return
    p = Path(path)
    suffix_ok = {"zarr": p.suffix == ".zarr" or (p / ".zarray").exists() or (p / ".zgroup").exists()
                 or (p / "zarr.json").exists(),
                 "tifxyz": (p / "x.tif").exists(), "tiff": p.suffix in (".tif", ".tiff"),
                 "tiff-float32": p.suffix in (".tif", ".tiff"), "tiff-uint8": p.suffix in (".tif", ".tiff"),
                 "tiff-uint16": p.suffix in (".tif", ".tiff"), "npy": p.suffix == ".npy", "npz": p.suffix == ".npz",
                 "png": p.suffix == ".png", "json": p.suffix == ".json", "umbilicus-json": p.suffix == ".json",
                 "vc3d-point-collection": p.suffix == ".json", "volpkg-json": p.name.endswith(".volpkg.json"),
                 "tif-stack": p.is_dir() and any(p.glob("*.tif"))}
    suffix_ok["ome-zarr"] = suffix_ok["zarr-v2"] = suffix_ok["zarr"]
    if not any(suffix_ok.get(f, True) for f in fmt):
        raise BindError(f"input {name}: {path} is not {' or '.join(fmt)}")


def bind(tool, sel, explicit=None):
    """{placeholder: value} for the tool's inputs, and a record of what bound each one. Raises BindError naming the
    selection kind that is missing."""
    explicit = dict(explicit or {})
    unknown = sorted(set(explicit) - set(tool.inputs))
    if unknown:
        raise BindError(f"{tool.id} has no input {', '.join(unknown)}; its inputs: {', '.join(tool.inputs) or 'none'}")
    values, record = {}, {}
    order = sorted(tool.inputs.items(), key=lambda kv: kv[1].get("from") == "segment.overlay.reverse")
    for name, spec in order:
        src = spec.get("from")
        req = spec.get("required", True)
        val = explicit.get(name)
        if val == "":                       # VC3D passes an empty {input:NAME} as an empty argument
            val = None
        how = "explicit" if val is not None else src
        try:
            if val is None:
                val = _bind_one(name, spec, sel, values)
            elif spec.get("bind") == "bridge":
                val = _from_bridge(name, spec, sel, val)
                how = "bridge"
        except BindError:
            if req or how == "bridge":
                raise
            val = None
        if val is None:
            if req:
                raise BindError(f"input {name} ({src}) could not be bound: give --input {name}=PATH")
            continue
        if src == "point" and not isinstance(val, list):
            val = _floats(val, 3, f"input {name}")
        if src == "region" and isinstance(val, str):
            nums = [int(v) for v in _floats(val, 4, f"input {name}")] if spec.get("space") == "segment_canvas" \
                else _floats(val, 6, f"input {name}")
            val = dict(zip(_fields(spec), nums))
        if src == "segments" and isinstance(val, str):
            val = [v for v in val.split(",") if v]
        if isinstance(val, str):
            if not is_remote(val):
                path = Path(val).expanduser()
                if not path.exists():
                    raise BindError(f"input {name}: {val} does not exist")
                val = str(path.resolve())
            _check_format(name, val, spec)
        _store(values, name, spec, val)
        record[name] = {"from": how, "value": val}
    return values, record


def _from_bridge(name, spec, sel, val):
    """A bridge-bound input's value: an existing path as it is; else segment ids (from VC3D's segments.list) or an
    ink detection label on the active segment, both read once into the frozen selection by enrich_from_bridge."""
    if isinstance(val, str) and not is_remote(val) and Path(val).expanduser().exists():
        return val
    app = sel.get("app") or {}
    if not app.get("bridge"):
        raise BindError(f"input {name} names {val!r}, which needs VC3D started with --agent-bridge (the launcher "
                        "reads its parent VC3D's bridge" + (f"; {app['bridge_error']}" if app.get("bridge_error")
                                                            else "") + "), or give a path")
    words = [w.strip() for w in (val if isinstance(val, list) else str(val).split(",")) if w.strip()]
    segs = app.get("segments") or {}
    if spec.get("from") == "segments" or "tifxyz" in (spec.get("format") or []):
        missing = [w for w in words if w not in segs]
        if missing:
            raise BindError(f"input {name}: VC3D has no loaded segment {', '.join(missing)}")
        if spec.get("from") == "segments":
            return [segs[w] for w in words]
        if len(words) != 1:
            raise BindError(f"input {name} takes one segment id, not {len(words)}")
        return segs[words[0]]
    for o in (sel.get("segment") or {}).get("overlays") or []:
        if str(val) in (o.get("label"), Path(o["path"]).name, Path(o["path"]).stem):
            return o["path"]
    raise BindError(f"input {name}: the active segment has no ink detection labelled {val!r}")


def _store(values, name, spec, val):
    key = f"in.{name}"
    if isinstance(val, dict):
        fields = _fields(spec)
        for f in fields:
            values[f"{key}.{f}"] = str(val[f])
        values[key] = ",".join(str(val[f]) for f in fields)
    elif spec.get("from") == "point":
        for f, v in zip("xyz", val):
            values[f"{key}.{f}"] = repr(float(v))
        # VC3D's frame is x, y, z; a tool that reads z, y, x declares axis_order zyx and gets the point reversed
        ordered = list(val)[::-1] if spec.get("axis_order") == "zyx" else list(val)
        values[key] = ",".join(repr(float(v)) for v in ordered)
    elif isinstance(val, list):
        values[key] = [str(v) for v in val]
    else:
        values[key] = str(val)


def _bind_one(name, spec, sel, values):
    src = spec["from"]
    fmt = spec.get("format") or []
    if src == "path":
        return None
    if src == "volume":
        vol = sel.get("volume") or {}
        if not vol.get("location"):
            raise BindError(f"input {name} needs an open volume")
        return vol["location"]
    if src == "segment":
        return _segment(sel, f"input {name}")["path"]
    if src == "segment.render":
        seg = _segment(sel, f"input {name}")
        if not seg.get("render"):
            raise BindError(f"input {name} needs the active segment's surface volume (a render: layers/ or a .zarr "
                            f"beside {seg['path']}); render one first with villa's vc_render_tifxyz into a folder "
                            "you choose (about 1 to 1.7 GB for a whole segment), then pass --input "
                            f"{name}=PATH")
        return seg["render"]
    if src == "segment.overlay":
        if sel.get("ink_overlay"):
            return sel["ink_overlay"]
        seg = sel.get("segment") or {}
        fwd = [o for o in seg.get("overlays") or [] if o.get("role") == "forward"]
        if not fwd:
            raise BindError(f"input {name} needs a selected ink detection overlay (or a forward map listed in the "
                            "segment's ink-detections.json)")
        return fwd[0]["path"]
    if src == "segment.overlay.reverse":
        forward = values.get(f"in.{spec['pair_of']}")
        twin = _twin(forward, sel) if forward else None
        if not twin:
            raise BindError(f"input {name} needs the reverse-depth control of {forward or 'the forward map'} "
                            "(FILE_reverse beside it, or a control:reverse record in ink-detections.json)")
        return twin
    if src in ("segment.labels", "segment.mask"):
        seg = _segment(sel, f"input {name}")
        stems = ("inklabels",) if src == "segment.labels" else ("supervision_mask", "supervision", "mask")
        found = _labels_in_records(seg, "labels" if src == "segment.labels" else "mask", fmt) or \
            _labels_in(seg["path"], seg["id"], stems, fmt)
        if not found:
            what = "ink labels" if src == "segment.labels" else "supervision mask"
            raise BindError(f"input {name} needs the segment's {what} ({seg['id']}_{stems[0]} in villa's naming, "
                            f"format {' or '.join(fmt) or 'any'}) in {seg['path']}")
        return found
    if src == "segments":
        segs = sel.get("segments") or []
        if not segs:
            raise BindError(f"input {name} needs several segments in order (--segments PATH, repeated)")
        return [s["path"] for s in segs]
    if src == "point":
        if sel.get("point") is None:
            raise BindError(f"input {name} needs a focus point")
        return list(sel["point"])
    if src == "points":
        pts = sel.get("points") or {}
        if not pts.get("path"):
            raise BindError(f"input {name} needs a point collection file (--points FILE)")
        return pts["path"]
    if src == "region":
        if spec.get("space") == "segment_canvas":
            if sel.get("crop"):
                box = {k: sel["crop"][k] for k in ("y0", "y1", "x0", "x1")}
            elif sel.get("region"):
                box = _canvas_crop(sel, _segment(sel, f"input {name}")["path"])
            else:
                raise BindError(f"input {name} needs a box on the segment's canvas (--crop Y0,Y1,X0,X1) or a focus "
                                "region")
            seg = (sel.get("segment") or {}).get("path")
            canvas = _canvas_shape(seg) if seg else None
            box["canvas_h"], box["canvas_w"] = (int(round(canvas[0])), int(round(canvas[1]))) if canvas else (0, 0)
            return box
        if not sel.get("region"):
            raise BindError(f"input {name} needs an enabled focus region")
        r = sel["region"]
        return dict(zip(FIELDS["region:volume"], r["low"] + r["high"]))
    if src == "umbilicus":
        if not sel.get("umbilicus"):
            raise BindError(f"input {name} needs an attached umbilicus")
        return sel["umbilicus"]
    if src == "project":
        if not sel.get("project"):
            raise BindError(f"input {name} needs a project saved on disk")
        return sel["project"]
    raise BindError(f"input {name}: cannot bind from {src}")


def bind_params(tool, given, sel):
    """{param.NAME: text} with defaults, types, enums and values looked up from the selection ("auto")."""
    given = dict(given or {})
    unknown = sorted(set(given) - set(tool.params))
    if unknown:
        raise BindError(f"{tool.id} has no param {', '.join(unknown)}; its params: {', '.join(tool.params) or 'none'}")
    out, record = {}, {}
    for name, spec in tool.params.items():
        raw = given.get(name)
        if raw in (None, "", "auto") and spec.get("from") == "volume.voxel_um":
            v = _voxel(sel)
            if v is not None:
                raw = v
        if raw in (None, "", "auto"):
            raw = spec.get("default")
        if raw is None:
            if spec.get("required", True) and spec.get("default", None) is None and "default" not in spec:
                hint = " (or open a volume whose meta.json gives voxelsize)" if spec.get("from") else ""
                raise BindError(f"param {name} is needed: --param {name}=VALUE{hint}")
            continue
        value = _coerce(name, raw, spec)
        if "enum" in spec and value not in spec["enum"]:
            raise BindError(f"param {name} must be one of {', '.join(map(str, spec['enum']))}, not {value!r}")
        out[f"param.{name}"] = str(value).lower() if isinstance(value, bool) else str(value)
        record[name] = value
    return out, record


def _coerce(name, raw, spec):
    typ = spec["type"]
    try:
        if typ == "integer":
            v = int(raw) if not isinstance(raw, bool) else None
            if v is None or (isinstance(raw, float) and raw != v):
                raise ValueError
            return v
        if typ == "number":
            v = float(raw)
            if v != v or v in (float("inf"), float("-inf")):
                raise ValueError
            return v
        if typ == "boolean":
            if isinstance(raw, bool):
                return raw
            if str(raw).lower() in ("true", "1", "yes"):
                return True
            if str(raw).lower() in ("false", "0", "no"):
                return False
            raise ValueError
        return str(raw)
    except (TypeError, ValueError):
        raise BindError(f"param {name}: {raw!r} is not a {typ}") from None


def _expand(word, values):
    names = _placeholders(word)
    if len(names) == 1 and word == "{" + names[0] + "}" and isinstance(values.get(names[0]), list):
        return list(values[names[0]])

    def sub(m):
        v = values.get(m.group(1))
        if v is None:
            raise RegistryError(f"{{{m.group(1)}}} has no value")
        if isinstance(v, list):
            raise RegistryError(f"{{{m.group(1)}}} is a list; it must be a whole argument")
        return v
    return [PLACEHOLDER.sub(sub, word)]


def command(tool, values):
    run = tool["run"] or {}
    argv = []
    for w in run.get("argv", []):
        argv += _expand(w, values)
    for name, words in (run.get("optional_args") or {}).items():
        if f"in.{name}" in values or f"param.{name}" in values:
            for w in words:
                argv += _expand(w, values)
    return argv


# ---------------------------------------------------------------- gates


def eligible_scrolls():
    """Every scroll the dated prize snapshot names as eligible for any prize (normalized)."""
    from . import prizes
    snap = prizes.load()
    return {prizes.normalize_scroll(e["scroll"]) for p in snap.get("prizes", []) for e in p.get("eligible") or []
            if isinstance(e, dict) and e.get("scroll")}


def scrolls_named(*texts):
    from . import prizes
    found = set()
    for t in texts:
        for m in SCROLL_RE.finditer(str(t)):
            found.add(prizes.normalize_scroll("PHerc" + re.sub(r"[\s._-]", "", m.group(1))))
    return found


def _strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def _platform_limit():
    return LOCAL_LIMIT_S["mac"] if platform.system() == "Darwin" else LOCAL_LIMIT_S["cloud"]


def gates(tool, sel, record, purpose="benchmark", experiment=None, allow_outside=(), yes_download=False,
          root=ROOT, disk_at=None, kind=None):
    """[{rule, verdict: pass|refused|planned|warn, detail}] in the order checked."""
    out = []

    def g(rule, verdict, detail):
        out.append({"rule": rule, "verdict": verdict, "detail": detail})

    saf, comp = tool.safety, tool.compute
    if tool.kind == "native":
        g("native", "refused", "villa's own tool: VC3D runs it from its own menu; agents run it with villa's binary")
        return out
    if tool.facts.get("go_ahead"):
        g("go-ahead", "refused", "its page says it needs Chase's yes, so it never runs from here (hard rule 8)")
    else:
        g("go-ahead", "pass", "not needed")
    if saf.get("quota"):
        g("quota", "refused", f"it spends {saf['quota']} quota, which needs Chase's yes for each use; it never runs "
          "from here (hard rule 8)")
    where = comp.get("where", "local-cpu")
    if saf.get("paid_compute") == "plan-only" or where in ("modal-cpu", "modal-gpu", "local-gpu"):
        g("paid-compute", "planned", "GPU and Modal work is planned only (AGENTS.md rules 8 and 11): write a spec in "
          "docs/compute/modal-specs/ and launch it through its own approval")
    else:
        g("paid-compute", "pass", "none: KIT_ALLOW_MODAL and MODAL_* are removed from the child's environment")
    limit = _platform_limit()
    typical = comp.get("typical_s")
    if isinstance(typical, (int, float)) and typical > limit:
        g("local-time", "planned", f"about {typical:g} s here, over the {limit} s local rule (AGENTS.md rule 11)")
    else:
        g("local-time", "pass", f"typical {typical if typical is not None else 'unknown'} s, rule {limit} s")
    need = float(comp.get("disk_mb", 0)) + DISK_FLOOR_MB
    try:
        free = shutil.disk_usage(disk_at or root).free / 1e6
    except OSError:
        free = None
    if free is not None and free < need:
        g("disk", "refused", f"{free:.0f} MB free, {need:.0f} MB needed with the {DISK_FLOOR_MB} MB floor")
    else:
        g("disk", "pass", f"{'unknown' if free is None else f'{free:.0f} MB'} free, {need:.0f} MB needed")
    wo = [k for k in saf.get("writes_outside", []) if k not in allow_outside]
    if wo:
        g("writes-outside", "refused", f"it writes outside its run folder ({', '.join(wo)}); pass --allow-outside "
          "KIND for this run once you have read what it writes")
    else:
        g("writes-outside", "pass", "every output under the run folder")
    if saf.get("destructive") and "destructive" not in allow_outside:
        g("destructive", "refused", "a destructive tool runs only with --allow-outside destructive")
    mb = saf.get("downloads_mb") or 0
    if mb and not yes_download:
        g("downloads", "refused", f"it downloads about {mb:g} MB on first use; pass --yes-download to allow it")
    elif mb:
        g("downloads", "pass", f"about {mb:g} MB allowed by --yes-download")
    if saf.get("model_output") or saf.get("readout") or saf.get("eligible_scrolls"):
        named = scrolls_named(*_strings(sel), *_strings(record))
        hits = sorted(named & eligible_scrolls())
        kind = kind if kind is not None else _repo_kind(root)
        if not hits:
            g("target", "pass" if named else "warn",
              f"inputs name {', '.join(sorted(named))}, none prize-eligible" if named else
              "no scroll is named in the inputs; if this is a prize-eligible scroll, run it in Scrolls-private")
        elif kind != "private":
            g("target", "refused", f"{', '.join(hits)} is prize-eligible: model output and readouts of it belong in "
              "Scrolls-private, under a preregistered experiment (hard rules 1 and 3)")
        else:
            g("target", *_target_check(hits, purpose, experiment))
    return out


def _target_check(hits, purpose, experiment):
    from . import ledger
    if purpose != "target" or not experiment:
        return ("refused", f"{', '.join(hits)} is prize-eligible: pass --purpose target --experiment SLUG, a "
                "preregistered experiment whose readout was fixed before any map exists (hard rule 3)")
    root = _ledger_root()
    try:
        rec = ledger.load(experiment, root)
        problems = ledger.check(experiment, root)
    except Exception as exc:  # noqa: BLE001 - a missing or bad record is a refusal, with its reason
        return ("refused", f"experiment {experiment}: {exc}")
    if problems:
        return ("refused", f"experiment {experiment}: {'; '.join(problems)}")
    if rec.get("status") not in ("planned", "running"):
        return ("refused", f"experiment {experiment} is {rec.get('status')}, not planned or running")
    from . import prizes
    if prizes.normalize_scroll(str(rec.get("scroll", ""))) not in hits:
        return ("refused", f"experiment {experiment} is for {rec.get('scroll')}, not {', '.join(hits)}")
    return ("pass", f"experiment {experiment} ({rec.get('scroll')}, readout fixed)")


def _verdict(gate_list):
    if any(x["verdict"] == "refused" for x in gate_list):
        return "refused"
    if any(x["verdict"] == "planned" for x in gate_list):
        return "planned"
    return "pass"


# ---------------------------------------------------------------- runs


def _ledger_root():
    """Where registry runs record their cost: KIT_TOOLS_LEDGER, else kit's ledger root (a relative one is taken
    from the checkout, since VC3D's plugin host starts tools from any folder)."""
    from . import ledger
    if os.environ.get(ENV_LEDGER):
        return Path(os.environ[ENV_LEDGER]).expanduser()
    root = Path(ledger.DEFAULT_ROOT)
    return root if root.is_absolute() else ROOT / root


def ensure_slug(slug=None, root=None, today=None):
    """The ledger record a registry run's cost goes to: --slug, else a plumbing record tools-YYYYMMDD made once."""
    from . import ledger
    root = Path(root) if root else _ledger_root()
    if slug:
        ledger.load(slug, root)
        return slug
    slug = f"tools-{(today or datetime.now(timezone.utc)).strftime('%Y%m%d')}"
    if not ledger.path_for(slug, root).exists():
        try:
            ledger.init(slug, "none", "tool registry runs (python -m kit tools run): plumbing, public data",
                        "none: tool runs on public data; no readout", root=root)
        except ledger.LedgerError:
            if not ledger.path_for(slug, root).exists():
                raise
    return slug


def _identity(val):
    """What a run's digest covers for one bound value: a URL, or a local path with its size and mtime."""
    out = []
    for v in val if isinstance(val, list) else [val]:
        if isinstance(v, str) and not is_remote(v) and os.path.exists(v):
            st = os.stat(v)
            out.append([v, st.st_size, st.st_mtime_ns])
        else:
            out.append(v)
    return out


def _local_paths(record, sel):
    paths = []
    for rec in record.values():
        for v in rec["value"] if isinstance(rec["value"], list) else [rec["value"]]:
            if isinstance(v, str) and not is_remote(v) and os.path.exists(v):
                paths.append(v)
    for key in ("project", "umbilicus", "ink_overlay"):
        if isinstance(sel.get(key), str) and os.path.exists(sel[key]):
            paths.append(sel[key])
    seg = (sel.get("segment") or {}).get("path")
    if seg and os.path.exists(seg):
        paths.append(seg)
    for s in sel.get("segments") or []:
        if s.get("path") and os.path.exists(s["path"]):
            paths.append(s["path"])
    return sorted(set(paths))


def snapshot(paths, limit=AUDIT_LIMIT):
    """{path: [size, mtime_ns, inode] or None} of each path and, for a folder, of up to limit entries inside it."""
    out, count = {}, 0
    for p in paths:
        for path in _walk(p):
            if count >= limit:
                out["__truncated__"] = True
                return out
            try:
                st = os.lstat(path)
                out[path] = [st.st_size, st.st_mtime_ns, st.st_ino]
            except OSError:
                out[path] = None
            count += 1
    return out


def _walk(p):
    yield str(p)
    if os.path.isdir(p) and not os.path.islink(p):
        for root, dirs, files in os.walk(p):
            dirs.sort()
            for name in sorted(dirs) + sorted(files):
                yield os.path.join(root, name)


def audit(before, after):
    """Paths whose size, mtime or inode changed, or that appeared or vanished, between two snapshots."""
    changed = [p for p in sorted(set(before) | set(after)) if p != "__truncated__" and before.get(p) != after.get(p)]
    return changed


def _inside(path, run):
    try:
        Path(path).resolve().relative_to(Path(run).resolve())
        return True
    except ValueError:
        return False


class Job:
    """One prepared run: the tool, the selection, the bound inputs and params, the command and the gates."""

    def __init__(self, tool, sel, values, record, params, param_record, gate_list, purpose, experiment):
        self.tool, self.sel, self.values, self.record = tool, sel, values, record
        self.params, self.param_record, self.gates = params, param_record, gate_list
        self.purpose, self.experiment = purpose, experiment
        self.digest = _digest({"manifest": tool.digest, "inputs": {k: _identity(v["value"]) for k, v in
                                                                   sorted(record.items())},
                               "params": param_record, "purpose": purpose, "experiment": experiment})
        self.run = None
        self.registry = None
        self.converted = {}             # output name -> its format after the convert step

    def outputs(self):
        return {n: Path(s["path"].replace("{run}", str(self.run))) for n, s in self.tool.outputs.items()}

    def argv(self):
        vals = dict(self.values, **self.params, run=str(self.run), python=sys.executable)
        return command(self.tool, vals)


def prepare(tool, sel, explicit=None, given=None, purpose="benchmark", experiment=None, allow_outside=(),
            yes_download=False, root=ROOT, kind=None):
    values, record = bind(tool, sel, explicit)
    params, param_record = bind_params(tool, given, sel)
    gate_list = gates(tool, sel, record, purpose, experiment, allow_outside, yes_download, root, kind=kind)
    return Job(tool, sel, values, record, params, param_record, gate_list, purpose, experiment)


def _default_run_dir(job, root=ROOT, fresh=False):
    if job.purpose == "target" and job.experiment:
        base = _ledger_root() / job.experiment / "tools"
    else:
        base = Path(root) / "work" / "tools"
    name = f"{job.tool.id}-{job.digest[:10]}"
    if fresh:
        name += "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / name


def plan(tool, job, run_dir=None):
    """The dry run's document: nothing is written."""
    job.run = Path(run_dir) if run_dir else _default_run_dir(job)
    verdict = _verdict(job.gates)
    comp = tool.compute
    return {"schema": RESULT_SCHEMA, "tool": tool.id, "title": tool.title, "manifest_sha256": tool.digest,
            "selection_sha256": job.sel.get("digest"), "run": str(job.run), "status": "planned",
            "exit": EXIT_PLANNED, "would": "refuse" if verdict == "refused" else "plan only" if verdict == "planned"
            else "run", "inputs": job.record, "params": job.param_record, "argv": job.argv(),
            "outputs": {n: str(p) for n, p in job.outputs().items()}, "gates": job.gates,
            "compute": {k: comp.get(k) for k in ("where", "typical_s", "disk_mb", "ram_gb", "scales_with")},
            "doors": doors(tool), "claim": _claim(tool)}


def _claim(tool):
    saf = tool.safety
    if saf.get("model_output"):
        return CLAIM
    if saf.get("readout"):
        return "Score: a measurement against published labels or a control, not a reading"
    return "Check or report: no ink map, no reading"


def _result_base(tool, job, status, code, run_dir):
    return {"schema": RESULT_SCHEMA, "tool": tool.id, "title": tool.title, "manifest_sha256": tool.digest,
            "selection_sha256": job.sel.get("digest") if job else None, "run": str(run_dir) if run_dir else None,
            "status": status, "exit": code, "claim": _claim(tool), "finished_utc": utc_now(),
            "gates": job.gates if job else [], "outputs": [], "open": [], "warnings": [], "next_steps": [],
            "applied": [], "report": {k: tool.facts.get(k) for k in ("success", "not_a_pass", "never")}}


def _write_result(run_dir, result):
    if run_dir:
        _atomic_write(Path(run_dir) / "vc3d-result.json", _dump(result))
    return result


def run(tool, job, run_dir=None, fresh=False, slug=None, root=ROOT, ledger_root=None, env=None,
        registry=None):
    """Run a prepared job: refuse or plan when a gate says so, else run the command through the local cost ledger,
    audit its writes, check its outputs, write provenance.json, graph.json, VC3D's handoff files and, last,
    vc3d-result.json. Returns (result, exit code)."""
    explicit_out = run_dir is not None
    run_dir = Path(run_dir) if run_dir else _default_run_dir(job, root, fresh)
    verdict = _verdict(job.gates)
    if not explicit_out and not fresh and (run_dir / "vc3d-result.json").is_file():
        try:
            prev = _read_json(run_dir / "vc3d-result.json")
        except (OSError, ValueError):
            prev = {}
        if prev.get("status") == "ok" and prev.get("manifest_sha256") == tool.digest:
            prev["reused"] = True
            return prev, EXIT_OK
        run_dir = _default_run_dir(job, root, fresh=True)
    if explicit_out and run_dir.exists() and any(q.name not in HOST_FILES for q in run_dir.iterdir()):
        raise RegistryError(f"--out {run_dir} is not empty; give a new or empty folder")
    job.run = run_dir
    if verdict != "pass":
        status = "refused" if verdict == "refused" else "planned"
        res = _result_base(tool, job, status, STATUS_EXIT[status], run_dir)
        res["argv"] = job.argv()
        res["refused_by" if status == "refused" else "planned_by"] = [x["rule"] for x in job.gates
                                                                      if x["verdict"] == verdict]
        run_dir.mkdir(parents=True, exist_ok=True)
        return _write_result(run_dir, res), res["exit"]
    from . import localcost
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "tmp").mkdir(exist_ok=True)
    argv = job.argv()
    started = utc_now()
    _atomic_write(run_dir / "selection.json", _dump(job.sel))
    watched = _local_paths(job.record, job.sel)
    watched = [p for p in watched if not _inside(p, run_dir)]
    before = snapshot(watched)
    child = dict(os.environ if env is None else env)
    for k in list(child):
        if k == "KIT_ALLOW_MODAL" or k.startswith("MODAL_"):
            del child[k]
    child["PYTHONPATH"] = str(KIT_ROOT) + (os.pathsep + child["PYTHONPATH"] if child.get("PYTHONPATH") else "")
    child["TMPDIR"] = str(run_dir / "tmp")
    child["KIT_TOOL_RUN"] = str(run_dir)
    run_rec = {"tool": tool.id, "manifest": str(tool.path), "manifest_sha256": tool.digest, "argv": argv,
               "cwd": str(run_dir), "env_removed": sorted(set(os.environ if env is None else env) - set(child)),
               "env_set": ["PYTHONPATH", "TMPDIR", "KIT_TOOL_RUN"], "started_utc": started, "inputs": job.record,
               "params": job.param_record, "purpose": job.purpose, "experiment": job.experiment,
               "watched": len(watched), "audit_truncated": bool(before.get("__truncated__"))}
    _atomic_write(run_dir / "registry-run.json", _dump(run_rec))
    timeout = (tool["run"] or {}).get("timeout_s")
    stdout_t = (tool["run"] or {}).get("stdout")
    stdout_p = Path(stdout_t.replace("{run}", str(run_dir))) if stdout_t else run_dir / "stdout.txt"
    stdout_p.parent.mkdir(parents=True, exist_ok=True)
    res = _result_base(tool, job, "ok", EXIT_OK, run_dir)
    res["argv"] = argv
    try:
        ledger_root = Path(ledger_root) if ledger_root else _ledger_root()
        slug = ensure_slug(slug if slug else (job.experiment if job.purpose == "target" else None), ledger_root)
        with open(stdout_p, "w", encoding="utf-8") as so, open(run_dir / "stderr.txt", "w", encoding="utf-8") as se:
            code, item = localcost.run(slug, argv, root=ledger_root, cwd=str(run_dir), env=child,
                                       timeout=timeout, stdout=so, stderr=se)
    except localcost.CostError as exc:
        res.update(status="bad", exit=EXIT_BAD, error=f"the local cost ledger refused the run: {exc} (AGENTS.md "
                   "rule 9 logs every local run; set SCROLLS_ELECTRICITY_USD_PER_KWH once)")
        return _write_result(run_dir, res), EXIT_BAD
    res["cost"] = {"slug": slug, **{k: item.get(k) for k in ("wall_s", "cpu_s", "kwh", "usd_exact", "exit_code")}}
    if item.get("timed_out"):
        res["warnings"].append(f"stopped after the manifest's timeout of {timeout} s")
    after = snapshot(watched)
    changed = audit(before, after)
    outs = job.outputs()
    escaped = [n for n, p in outs.items() if p.exists() and not _inside(p, run_dir)]
    if changed or escaped:
        res.update(status="violated", exit=EXIT_VIOLATED,
                   violations={"changed_outside": changed[:50], "outputs_outside": escaped})
        res["warnings"].append("the tool changed files outside its run folder: nothing is opened")
        return _write_result(run_dir, res), EXIT_VIOLATED
    missing = [n for n, p in outs.items() if tool.outputs[n].get("required", True) and not p.exists()]
    if code != 0 or missing:
        res.update(status="failed", exit=EXIT_FAILED, tool_exit=code)
        if missing:
            res["warnings"].append(f"missing output(s): {', '.join(missing)}")
        res["stderr_tail"] = _tail(run_dir / "stderr.txt")
    job.registry = registry
    if res["status"] == "ok" and any(s.get("convert") for s in tool.outputs.values()):
        job.registry = registry if registry is not None else load_cached(root)
        _convert(tool, job, outs, res, job.registry, root, ledger_root)
    if res["status"] == "ok":
        res["format_gate"] = format_gate(tool, job, outs)
        failed = [g["output"] for g in res["format_gate"] if g["verdict"] == "fail"]
        if failed:
            res.update(status="refused", exit=EXIT_REFUSED, refused_by=["format-gate"])
            res["warnings"].append(f"the format gate failed for {', '.join(failed)}: nothing is opened or handed on")
    res["outputs"] = _describe_outputs(tool, outs, job)
    res["controls"] = _controls(tool, job, outs)
    if res["status"] == "ok":
        _views(tool, job, outs, res)
        _open(tool, job, outs, res)
    res["provenance"] = _provenance(tool, job, outs, run_dir, started)
    res["graph"] = str(_graph(tool, job, outs, run_dir, res.get("conversions")))
    res["summary"] = _summary(tool, res, outs)
    return _write_result(run_dir, res), res["exit"]


def _tail(path, n=20):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def _describe_outputs(tool, outs, job):
    rows = []
    for name, p in outs.items():
        spec = tool.outputs[name]
        row = {"name": name, "kind": spec["kind"], "format": job.converted.get(name, spec["format"]), "path": str(p),
               "role": spec.get("role"), "exists": p.exists()}
        if spec.get("on"):
            row["on_input"] = spec["on"]
        if p.is_file():
            row["bytes"] = p.stat().st_size
            if row["bytes"] <= HASH_MAX:
                row["sha256"] = _sha256_file(p)
        rows.append(row)
    return rows


def _controls(tool, job, outs):
    req = list(tool.safety.get("controls") or [])
    present = [c for c in req if (c in outs and outs[c].exists()) or f"in.{c}" in job.values]
    if not req:
        verdict = "no control declared" if (tool.safety.get("model_output") or tool.safety.get("readout")) else \
            "not applicable"
    else:
        verdict = "present" if len(present) == len(req) else NO_CONTROL
    return {"required": req, "present": present, "verdict": verdict}


def _summary(tool, res, outs):
    lines = [f"{tool.title}: {res['status']}", res["claim"]]
    if res.get("controls", {}).get("verdict") not in (None, "not applicable", "present"):
        lines.append(f"Controls: {res['controls']['verdict']}")
    for name, p in outs.items():
        if tool.outputs[name]["kind"] == "report" and p.is_file() and p.suffix == ".json" and p.stat().st_size < 1 << 20:
            try:
                data = _read_json(p)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                keep = {k: v for k, v in data.items() if isinstance(v, (int, float, str, bool)) and len(str(v)) < 120}
                lines.append(f"{name}: " + ", ".join(f"{k}={v}" for k, v in list(keep.items())[:8]))
    return lines


# ---------------------------------------------------------------- format gate and conversions


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"),
                                                                                         float("-inf"))


def _villafmt():
    """AutoPipeline's format layer (kit/villafmt.py, rules cited to villa source lines), when this kit has it."""
    try:
        return importlib.import_module(f"{__package__}.villafmt")
    except ImportError:
        return None


def _messages(items):
    return [e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in items or []]


def _gate_tifxyz(path, ctx):
    seg = Path(path)
    errors = []
    vf = _villafmt()
    if vf is not None:
        try:
            errors += _messages(vf.check_tifxyz(seg, pixels=True).get("errors"))
        except Exception as exc:  # noqa: BLE001 - a checker that cannot read it is a failure, with its reason
            errors.append(f"kit.villafmt cannot check it: {exc}")
    elif not seg.is_dir():
        return "fail", f"{seg} is not a folder"
    else:
        try:
            if not isinstance(_read_json(seg / "meta.json"), dict):
                errors.append("meta.json is not an object")
        except (OSError, ValueError) as exc:
            errors.append(f"meta.json: {exc}")
        errors += [f"{a}.tif is missing" for a in "xyz" if not (seg / f"{a}.tif").is_file()]
    if errors:
        return "fail", "; ".join(errors[:3])
    try:
        import numpy as np
        import tifffile
    except ImportError:
        return "pass", "files present; vertices unmeasured (no numpy or tifffile here)"
    try:
        x, y, z = (np.asarray(tifffile.imread(seg / f"{a}.tif"), dtype=np.float64) for a in "xyz")
    except (OSError, ValueError) as exc:
        return "fail", f"cannot read the grid: {exc}"
    if not (x.ndim == 2 and x.shape == y.shape == z.shape):
        return "fail", f"x, y and z are not one 2-D grid ({x.shape}, {y.shape}, {z.shape})"
    valid = x != -1                     # villa marks a missing vertex with x = -1 (QuadSurface's invalid point)
    if not valid.any():
        return "fail", "no valid vertex (every x is -1)"
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    bad, holes = int((valid & ~finite).sum()), int((valid & finite & (z <= 0)).sum())
    if bad:
        return "fail", f"{bad} vertices are not finite"
    if holes:
        return "fail", f"{holes} vertices have z <= 0 without villa's missing-vertex mark (x = -1)"
    return "pass", f"{x.shape[0]} x {x.shape[1]} grid, {int(valid.sum())} valid vertices"


def _check_umbilicus(path):
    """(points, errors) as VC3D's umbilicus reader takes the file (Umbilicus.cpp LoadJsonFile), minimally;
    kit/villafmt.py has the full rules and is used when present."""
    vf = _villafmt()
    if vf is not None:
        return vf.check_umbilicus(path)
    try:
        doc = _read_json(path)
    except (OSError, ValueError) as exc:
        return 0, [f"cannot read it: {exc}"]
    arr = doc if isinstance(doc, list) else (doc.get("points", doc.get("control_points"))
                                             if isinstance(doc, dict) else None)
    if not isinstance(arr, list) or not arr:
        return 0, ["no points: the root must be an array or hold a points or control_points array"]
    for i, e in enumerate(arr):
        vals = e[:3] if isinstance(e, list) else [e.get(k) for k in ("z", "y", "x")] if isinstance(e, dict) else []
        if len(vals) < 3 or not all(_finite(v) for v in vals):
            return len(arr), [f"entry {i} is not [z, y, x] or an object with numeric z, y, x"]
    return len(arr), []


def _gate_umbilicus(path, ctx):
    n, errors = _check_umbilicus(path)
    return ("fail", "; ".join(errors[:3])) if errors else ("pass", f"{n} points")


def _gate_points(path, ctx):
    try:
        doc = _read_json(path)
    except (OSError, ValueError) as exc:
        return "fail", f"cannot read it: {exc}"
    if ctx["format"] == "vc3d-point-collection":
        if not isinstance(doc, dict) or doc.get("vc_pointcollections_json_version") != "1" or not isinstance(
                doc.get("collections"), dict):
            return "fail", "not a VC3D point collection, version 1 (vc_pointcollections_json_version and collections)"
        pts = [q.get("p") for c in doc["collections"].values() if isinstance(c, dict)
               for q in (c.get("points") or {}).values() if isinstance(q, dict)]
    elif isinstance(doc, list):
        pts = [q.get("xyz", q.get("p")) if isinstance(q, dict) else q for q in doc]
    else:
        return "fail", "not a list of x, y, z points"
    bad = sum(1 for q in pts if not (isinstance(q, list) and len(q) == 3 and all(_finite(v) for v in q)))
    if bad:
        return "fail", f"{bad} of {len(pts)} points are not three finite numbers"
    return "pass", f"{len(pts)} points"


def _gate_project(path, ctx):
    try:
        doc = _read_json(path)
    except (OSError, ValueError) as exc:
        return "fail", f"cannot read it: {exc}"
    base = Path(path).parent
    vf = _villafmt()
    if vf is not None:
        errors = _messages(vf.check_project(doc, base).get("errors"))
    elif not isinstance(doc, dict):
        errors = ["the project is not a JSON object"]
    else:
        errors = []
        for key in ("volumes", "segments"):
            for e in doc.get(key) or []:
                loc = e if isinstance(e, str) else e.get("location") if isinstance(e, dict) else None
                if not isinstance(loc, str) or not loc:
                    errors.append(f"{key}: an entry is neither a path nor {{location, tags}}")
                elif not is_remote(loc) and not (base / loc).exists():
                    errors.append(f"{key}: {loc} does not exist")
    return ("fail", "; ".join(errors[:3])) if errors else ("pass", "VC3D project")


def _gate_ome_zarr(path, ctx):
    p = Path(path)
    attrs = None
    for name, pick in ((".zattrs", lambda d: d), ("zarr.json", lambda d: d.get("attributes") or {})):
        f = p / name
        if f.is_file():
            try:
                attrs = pick(_read_json(f))
            except (OSError, ValueError, AttributeError) as exc:
                return "fail", f"{name}: {exc}"
            break
    if not ((p / ".zgroup").is_file() or (p / "zarr.json").is_file()):
        return "fail", "not a zarr group (no .zgroup or zarr.json)"
    ms = (attrs or {}).get("multiscales") or ((attrs or {}).get("ome") or {}).get("multiscales")
    levels = [d.get("path") for d in (ms[0].get("datasets") or [])] if isinstance(ms, list) and ms and isinstance(
        ms[0], dict) else []
    if not levels:
        return "fail", "no multiscales levels in its attributes (OME-Zarr)"
    missing = [lv for lv in levels if not (p / str(lv)).exists()]
    if missing:
        return "fail", f"level(s) {', '.join(map(str, missing))} are listed but missing"
    try:
        voxel = _read_json(p / "meta.json").get("voxelsize")
    except (OSError, ValueError, AttributeError):
        voxel = None
    if not (_finite(voxel) and voxel > 0):
        return "fail", "meta.json gives no positive voxelsize (VC3D reads the voxel size there)"
    return "pass", f"{len(levels)} levels, {voxel:g} um voxels"


def _png_shape(path):
    import struct
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    w, h = struct.unpack(">II", head[16:24])
    return (h, w)


def _image_shape(path):
    p = Path(path)
    if p.suffix == ".png":
        return _png_shape(p)
    try:
        import numpy as np
        if p.suffix == ".npy":
            return tuple(np.load(p, mmap_mode="r").shape)
        import tifffile
    except ImportError:
        return None
    if p.suffix in (".tif", ".tiff"):
        with tifffile.TiffFile(p) as t:
            return tuple(t.series[0].shape)
    return None


def _canvas_shape(segdir):
    """(height, width) of a tifxyz segment's canvas: its grid divided by meta.json's scale; None when unreadable."""
    try:
        import tifffile
        with tifffile.TiffFile(Path(segdir) / "x.tif") as t:
            rows, cols = t.series[0].shape[:2]
        meta = _read_json(Path(segdir) / "meta.json")
    except (ImportError, OSError, ValueError, IndexError):
        return None
    sc = meta.get("scale") if isinstance(meta, dict) else None
    sx, sy = (float(sc[0]), float(sc[1])) if isinstance(sc, list) and len(sc) >= 2 and sc[0] and sc[1] else (1.0, 1.0)
    return rows / sy, cols / sx


def _gate_overlay(path, ctx):
    try:
        shape = _image_shape(path)
    except (OSError, ValueError) as exc:
        return "fail", f"cannot read it as an image: {exc}"
    if shape is None:
        return "unmeasured", "no numpy or tifffile here to read its size"
    dims = [d for d in shape if d != 1]
    if len(dims) != 2:
        return "fail", f"not one 2-D image (shape {shape})"
    job = ctx["job"]
    if job.sel.get("crop") or any(s.get("from") == "region" and f"in.{n}" in job.values
                                  for n, s in job.tool.inputs.items()):
        return "pass", f"{dims[0]} x {dims[1]}, a crop (not compared with the segment's canvas)"
    seg = (job.sel.get("segment") or {}).get("path")
    canvas = _canvas_shape(seg) if seg else None
    if canvas is None:
        return "pass", f"{dims[0]} x {dims[1]}; no segment grid to compare with"
    want, got = canvas[1] / canvas[0], dims[1] / dims[0]
    if abs(got / want - 1.0) > ASPECT_TOL:
        return "fail", (f"{dims[0]} x {dims[1]} has aspect {got:.4f}, the segment's canvas {want:.4f}; VC3D would "
                        "stretch it over the wrong place (more than 2 percent apart)")
    return "pass", f"{dims[0]} x {dims[1]}, on the segment's canvas (aspect within 2 percent)"


FORMAT_CHECKS = {"tifxyz": _gate_tifxyz, "umbilicus-json": _gate_umbilicus, "volpkg-json": _gate_project,
                 "vc3d-point-collection": _gate_points, "json-points": _gate_points, "ome-zarr": _gate_ome_zarr}
OVERLAY_FORMATS = ("tiff", "tiff-uint8", "tiff-uint16", "tiff-float32", "npy", "png")


def format_gate(tool, job, outs):
    """[{output, format, verdict: pass|fail|unmeasured, detail}] for every declared output that exists and keeps its
    check on: each format's checker, and for an overlay its size against the segment's canvas. A fail means nothing
    is opened or handed to AutoPipeline."""
    rows = []
    for name, p in outs.items():
        spec = tool.outputs[name]
        if not spec.get("check", True) or not p.exists():
            continue
        fmt = job.converted.get(name, spec["format"])
        fn = FORMAT_CHECKS.get(fmt)
        if fn is None and spec["kind"] in ("overlay", "overlay_volume") and fmt in OVERLAY_FORMATS:
            fn = _gate_overlay
        if fn is None:
            continue
        try:
            verdict, detail = fn(p, {"job": job, "spec": spec, "format": fmt, "name": name})
        except Exception as exc:  # noqa: BLE001 - a checker that breaks is a failure, never a pass
            verdict, detail = "fail", f"the {fmt} check could not run: {exc}"
        rows.append({"output": name, "format": fmt, "verdict": verdict, "detail": detail})
    return rows


def _convert(tool, job, outs, res, registry, root, ledger_root):
    """Run each output's declared converter (one step, a converter manifest) in RUN/convert/NAME and put its
    result in that output's place; recorded in res["conversions"] and as a stage in graph.json."""
    for name, spec in tool.outputs.items():
        cid = spec.get("convert")
        if not cid or not outs[name].exists():
            continue
        try:
            conv = registry.get(cid)
        except RegistryError as exc:
            res.update(status="failed", exit=EXIT_FAILED)
            res["warnings"].append(f"{name}: its converter {cid} is not in the registry: {exc}")
            return
        if conv.kind != "converter":
            res.update(status="failed", exit=EXIT_FAILED)
            res["warnings"].append(f"{name}: {cid} is a {conv.kind} manifest, not a converter")
            return
        src = next(iter(conv.required_inputs()))
        cdir = job.run / "convert" / name
        cjob = prepare(conv, job.sel, {src: str(outs[name])}, None, job.purpose, job.experiment, root=root)
        cres, code = run(conv, cjob, run_dir=cdir, root=root, ledger_root=ledger_root, registry=registry)
        made = [Path(s["path"].replace("{run}", str(cdir))) for s in conv.outputs.values()
                if s.get("role", "forward") == "forward"]
        res.setdefault("conversions", []).append({"output": name, "converter": cid, "manifest_sha256": conv.digest,
                                                  "status": cres.get("status"), "run": str(cdir),
                                                  "from": str(outs[name]), "to": str(made[0]) if made else None})
        if code != EXIT_OK or not made or not made[0].exists():
            res.update(status="failed", exit=EXIT_FAILED)
            res["warnings"].append(f"{name}: its converter {cid} ended {cres.get('status')}")
            return
        outs[name] = made[0]
        job.converted[name] = next(s["format"] for s in conv.outputs.values() if s.get("role", "forward") == "forward")


# ---------------------------------------------------------------- VC3D handoff (opener)


def _crop_box(job):
    """(y0, y1, x0, x1) of the box on the segment's canvas this run was cropped to, or None."""
    for n, spec in job.tool.inputs.items():
        if spec.get("from") == "region" and spec.get("space") == "segment_canvas" and f"in.{n}.y0" in job.values:
            try:
                return tuple(int(float(job.values[f"in.{n}.{k}"])) for k in ("y0", "y1", "x0", "x1"))
            except (TypeError, ValueError):
                return None
    return None


def _views(tool, job, outs, res):
    """8-bit views of the maps on one shared scale, which is what VC3D loads: it stretches a non-8-bit image to its
    own minimum and maximum (InkDetectionOverlayController.cpp, toU8Scalar) and shows an 8-bit image as it is, so a
    forward map and a flat control would both look full-contrast. The scale comes from the forward map (0.5 and 99.5
    percentiles of its finite pixels) and is applied unchanged to its controls; an 8-bit forward map keeps its values,
    and so does one stored as floats whose values are all whole numbers from 0 to 255 with a maximum above 1 (a 0 or
    255 mask such as geomfix's approval.tif, which a percentile stretch would make flat when every pixel is 255).
    VC3D stretches an ink detection over the whole segment grid, so a map of a crop is placed at its box on a canvas of
    the segment's size, 0 (transparent) elsewhere. The float originals stay for scoring."""
    maps = {n: p for n, p in outs.items() if tool.outputs[n]["kind"] == "overlay" and p.is_file()
            and p.suffix in (".tif", ".tiff", ".npy")}
    fwd = [n for n in maps if tool.outputs[n].get("role", "forward") == "forward"]
    if not fwd:
        return
    try:
        import numpy as np
        import tifffile
    except ImportError:
        res["warnings"].append("no numpy or tifffile here: 8-bit views of the maps were not written, so VC3D has "
                               "nothing to load")
        return

    def read(p):
        return np.load(p) if p.suffix == ".npy" else tifffile.imread(p)
    try:
        raw = np.asarray(read(maps[fwd[0]]))
    except (OSError, ValueError) as exc:
        res["warnings"].append(f"cannot read {maps[fwd[0]]} for its 8-bit view: {exc}")
        return
    keep = raw.dtype == np.uint8
    ref = raw.astype(np.float64)
    finite = ref[np.isfinite(ref)]
    if finite.size == 0:
        return
    if not keep and finite.min() >= 0 and 1 < finite.max() <= 255 and bool(np.all(finite == np.round(finite))):
        keep = True     # an 8-bit map or mask stored as floats (kit's own TIFF writer writes float32): kept as it is
    lo, hi = (0.0, 255.0) if keep else (float(v) for v in np.percentile(finite, [0.5, 99.5]))
    hi = hi if hi > lo else lo + 1.0
    box = _crop_box(job)
    seg = (job.sel.get("segment") or {}).get("path")
    canvas = _canvas_shape(seg) if box and seg else None
    placed = None
    vdir = job.run / "vc3d" / "views"
    vdir.mkdir(parents=True, exist_ok=True)
    views, shas = {}, {}
    for name, p in maps.items():
        a = np.squeeze(np.asarray(read(p), dtype=np.float64))
        u8 = np.clip(np.nan_to_num((a - lo) / (hi - lo), nan=0.0) * 255.0, 0, 255).round().astype(np.uint8)
        if canvas and u8.ndim == 2:
            y0, y1, x0, x1 = box
            H, W = int(round(canvas[0])), int(round(canvas[1]))
            if abs(u8.shape[0] - (y1 - y0)) <= 1 and abs(u8.shape[1] - (x1 - x0)) <= 1 and (u8.shape != (H, W)):
                full = np.zeros((H, W), np.uint8)
                h, w = min(u8.shape[0], H - y0), min(u8.shape[1], W - x0)
                full[y0:y0 + h, x0:x0 + w] = u8[:h, :w]
                u8, placed = full, {"box": [y0, y1, x0, x1], "canvas": [H, W]}
            elif u8.shape != (H, W):
                res["warnings"].append(f"{name}: {u8.shape[0]} x {u8.shape[1]} is neither the crop "
                                       f"{y1 - y0} x {x1 - x0} nor the canvas {H} x {W}; its view is not placed")
        out = vdir / f"{name}_u8.tif"
        tifffile.imwrite(out, u8)
        views[name] = str(out)
        shas[name] = _sha256_file(out)
    doc = {"from": fwd[0], "low": lo, "high": hi, "percentiles": None if keep else [0.5, 99.5],
           "applied_to": sorted(views), "sha256": shas,
           "note": "one scale for the forward map and its controls; " + CLAIM}
    if placed:
        doc["placed"] = placed
    _atomic_write(job.run / "vc3d" / "scale.json", _dump(doc))
    res["views"] = views
    res["views_sha256"] = shas


def _open(tool, job, outs, res):
    opens, plugin = [], None
    for name, p in outs.items():
        spec = tool.outputs[name]
        fn = OPENERS.get(spec["kind"]) or DEFAULT_OPENERS.get(spec["kind"])
        if fn is None or not p.exists():
            continue
        got = fn(job, name, spec, p, res) or {}
        opens += got.get("open", [])
        res["warnings"] += got.get("warnings", [])
        res["next_steps"] += got.get("next_steps", [])
    for c in opens:
        if c["method"] not in ALLOWED_OPEN:
            raise RegistryError(f"opener asked for {c['method']}, which is not on the allow-list")
    res["open"] = opens
    vc = tool["vc3d"] or {}
    plugin = plugin_result(tool, job.registry)
    if vc.get("result") or plugin:
        res["vc3d"] = {"plugin_result": plugin}


def _open_points(job, name, spec, path, res):
    if spec["format"] == "vc3d-point-collection":
        doc_path = path
    elif spec["format"] == "json-points":
        try:
            pts = _read_json(path)
            pts = [[float(c) for c in (q.get("xyz", q.get("p")) if isinstance(q, dict) else q)] for q in pts]
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            return {"warnings": [f"{name}: not a list of x, y, z points: {exc}"]}
        doc_path = job.run / "vc3d" / "points" / f"{name}.json"
        _atomic_write(doc_path, _dump(points_document(pts, f"{job.tool.id} {name} {job.digest[:10]}")))
    else:
        return {}
    return {"open": [{"method": "points.load_json", "params": {"path": str(doc_path)},
                      "why": f"{name} as a point collection", "replaces": REPLACES["points.load_json"]}]}


def points_document(points, name, color=(1.0, 0.5, 0.0)):
    """A VC3D point collection, version 1 (villa core/src/PointCollections.cpp), with one collection."""
    pts = {str(i + 1): {"p": [float(c) for c in p], "creation_time": 0, "wind_a": None} for i, p in enumerate(points)}
    return {"vc_pointcollections_json_version": "1",
            "collections": {"1": {"name": name, "points": pts, "metadata": {"winding_is_absolute": False},
                                  "color": list(color)}}}


def _open_listed(job, name, spec, path, res):
    return {"next_steps": [f"{name}: {path} ({spec['kind']}, {spec['format']})"]}


DEFAULT_OPENERS = {"points": _open_points, "report": _open_listed, "link": _open_listed, "overlay": _open_listed,
                   "surface": _open_listed, "umbilicus": _open_listed, "volume": _open_listed,
                   "overlay_volume": _open_listed, "labels": _open_listed, "project": _open_listed}


def plugin_result(tool, registry=None):
    """{kind, path} VC3D's plugin host loads after the run: the manifest's vc3d.result when the host can load it on
    its own (a forward map on the segment's grid as an ink detection, a surface as a segment, points, an umbilicus, a
    report as a file), else the run's vc3d-result.json as a file. An output with a convert step is loaded from the
    converter's folder. Controls and second outputs come back through the "Open run output" entries (take)."""
    vc = tool["vc3d"] or {}
    name = vc.get("result")
    spec = tool.outputs.get(name) if name else None
    if spec:
        rel = spec["path"].replace("{run}", "{output}")
        kind, fmt = spec["kind"], spec["format"]
        if spec.get("convert"):
            conv = None
            try:
                conv = (registry or load_cached()).get(spec["convert"])
            except RegistryError:
                pass
            made = [s for s in (conv.outputs.values() if conv else []) if s.get("role", "forward") == "forward"]
            if not made:
                return {"kind": "file", "path": "{output}/vc3d-result.json"}
            rel = made[0]["path"].replace("{run}", "{output}/convert/" + name)
            fmt = made[0]["format"]
        if kind == "points" and fmt == "vc3d-point-collection":
            return {"kind": "points", "path": rel}
        if kind == "points" and fmt == "json-points":
            return {"kind": "points", "path": "{output}/vc3d/points/" + name + ".json"}
        if kind == "umbilicus" and fmt == "umbilicus-json":
            return {"kind": "umbilicus", "path": rel}
        if kind == "overlay" and spec.get("role", "forward") == "forward" and not spec.get("convert"):
            if fmt in ("tiff", "tiff-uint8", "tiff-uint16", "tiff-float32", "npy"):
                return {"kind": "ink_overlay", "path": "{output}/vc3d/views/" + name + "_u8.tif"}
            if fmt == "png":
                return {"kind": "ink_overlay", "path": rel}
        if kind == "overlay" and fmt in ("tiff", "tiff-uint8", "tiff-uint16", "tiff-float32", "png") and \
                spec.get("role", "forward") == "forward":
            return {"kind": "ink_overlay", "path": rel}
        if kind == "surface" and fmt == "tifxyz":
            return {"kind": "segment", "path": rel}
        if kind in ("report", "link", "file"):
            return {"kind": "file", "path": rel}
    return {"kind": "file", "path": "{output}/vc3d-result.json"}


def open_run(run_dir, live=None, apply=False, replace_points=False, call=None):
    """A finished run's VC3D handoff: the result's allow-listed calls, printed, or (live and apply) sent one by one
    to a running VC3D, each reply recorded in RUN/vc3d/open-log.json. A run folder another tool made (AutoPipeline's)
    goes to its own handler."""
    run_dir = Path(run_dir)
    for fn in RUN_FOLDERS:
        got = fn(run_dir, live=live, apply=apply, call=call)
        if got is not None:
            return got
    path = run_dir / "vc3d-result.json"
    if not path.is_file():
        raise RegistryError(f"{run_dir} has no vc3d-result.json: not a registry run folder")
    res = _read_json(path)
    if res.get("status") != "ok":
        raise RegistryError(f"{run_dir}: the run is {res.get('status')}, so nothing is opened")
    calls = res.get("open") or []
    for c in calls:
        if c.get("method") not in ALLOWED_OPEN:
            raise RegistryError(f"{path}: {c.get('method')} is not on the allow-list; refusing the whole result")
        for v in _strings(c.get("params") or {}):
            if os.path.isabs(v) and not _inside(v, run_dir):
                raise RegistryError(f"{path}: {c['method']} names {v}, outside the run folder; refusing")
    out = {"run": str(run_dir), "tool": res.get("tool"), "calls": calls, "applied": [], "live": live is not None}
    if live is None or not apply:
        out["note"] = ("the calls a VC3D would get; add --live [NAME] --apply to send them to a running VC3D"
                       if calls else "nothing for the bridge to open: see the result's outputs and next_steps")
        return out
    if call is not None:
        sock = live or "fake"
    elif live:
        sock = resolve_bridge(live)
    else:
        found = parent_bridge()
        if not found:
            raise RegistryError("--live with no name sends only to the VC3D that started this command (its parent); "
                                "name a bridge or socket path to send elsewhere; the newest bridge is never used")
        sock = found["path"]
    call = call or _rpc
    sel_path = run_dir / "selection.json"
    want = ((_read_json(sel_path).get("volume") or {}).get("location") if sel_path.is_file() else None)
    if want and not is_remote(want):
        have = ((call(sock, "state.get", None) or {}).get("volume") or {}).get("path")
        if have and not is_remote(have) and Path(have).expanduser().resolve() != Path(want).resolve():
            raise RegistryError(f"that VC3D has volume {have} open, not the run's {want}: nothing is sent")
    for c in calls:
        if c.get("replaces") and not replace_points:
            out["applied"].append({"method": c["method"], "ok": False, "skipped": f"it replaces {c['replaces']}; "
                                   "pass --replace-points to allow it"})
            continue
        try:
            call(sock, c["method"], c.get("params"))
            out["applied"].append({"method": c["method"], "params": c.get("params"), "ok": True})
        except Exception as exc:  # noqa: BLE001 - a failed call is recorded; the others still run
            out["applied"].append({"method": c["method"], "params": c.get("params"), "ok": False, "error": str(exc)})
    log = run_dir / "vc3d" / "open-log.json"
    _atomic_write(log, _dump({"at": utc_now(), "bridge": str(sock), "applied": out["applied"]}))
    res["applied"] = out["applied"]
    _atomic_write(path, _dump(res))
    return out


# ---------------------------------------------------------------- plan, confirm and take


def write_plan(tool, job, path, explicit=None, given=None, yes_download=False):
    """Write the dry run with its digest to path (VC3D's "Plan:" entry writes {output}/plan.json): what would run,
    the gates, the time and disk, the frozen selection and how to confirm it. Nothing runs."""
    doc = plan(tool, job)
    out = {"schema": PLAN_SCHEMA, "tool": tool.id, "title": tool.title, "plan_digest": job.digest,
           "manifest_sha256": tool.digest, "written_utc": utc_now(), "would": doc["would"],
           "confirm": f"python -m kit tools confirm {job.digest[:16]}", "selection": job.sel,
           "explicit": dict(explicit or {}), "given": dict(given or {}), "purpose": job.purpose,
           "experiment": job.experiment, "yes_download": bool(yes_download), "plan": doc,
           "note": ("a plan only: nothing ran. Confirm binds the inputs again from this frozen selection; any change "
                    "to an input, a param or the manifest gives another digest and is refused. "
                    + ("Planned only here (" + ", ".join(x["rule"] for x in job.gates if x["verdict"] == "planned")
                       + "): confirm gives the same plan, never a launch." if doc["would"] == "plan only" else ""))}
    _atomic_write(path, _dump(out))
    return out


def _plan_dirs(root=ROOT, env=None):
    env = os.environ if env is None else env
    runs = Path(env[ENV_PLUGIN_RUNS]) if env.get(ENV_PLUGIN_RUNS) else (
        Path(env["HOME"]) / ".vc3d" / "plugin-runs" if env.get("HOME") else None)
    return [d for d in (runs, Path(root) / "work" / "tools" / "plans") if d is not None]


def find_plan(digest, plan_path=None, root=ROOT, env=None):
    """(path, plan) of the written plan whose digest starts with digest: plan_path, else VC3D's plugin run folders
    (VC3D_PLUGIN_RUNS or ~/.vc3d/plugin-runs) and work/tools/plans/."""
    if not re.match(r"^[0-9a-f]{10,64}$", str(digest or "")):
        raise RegistryError("a plan digest is 10 to 64 lowercase hex characters (the plan's confirm line)")
    if plan_path:
        cands = [Path(plan_path).expanduser()]
    else:
        cands = []
        for d in _plan_dirs(root, env):
            if d.is_dir():
                cands += sorted(d.glob("*/*/plan.json")) + sorted(d.glob("*.json"))
    hits = {}
    for c in cands:
        try:
            doc = _read_json(c)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("schema") == PLAN_SCHEMA and str(doc.get("plan_digest", "")).startswith(
                digest):
            hits.setdefault(doc["plan_digest"], (c, doc))
    if not hits:
        raise RegistryError(f"no written plan with digest {digest}: make one with python -m kit tools plan ID ... "
                            "--write FILE, or VC3D's Plan: entry")
    if len(hits) > 1:
        raise RegistryError(f"digest {digest} matches {len(hits)} plans; give more of it")
    return next(iter(hits.values()))


def confirm(reg, digest, plan_path=None, tool_id=None, run_dir=None, root=ROOT, ledger_root=None, slug=None,
            kind=None):
    """Run a written plan: the same manifest, the inputs bound again from its frozen selection, the same digest.
    Returns (result, exit code); a changed manifest or input is refused (exit 3) and nothing runs."""
    path, doc = find_plan(digest, plan_path, root)
    tool = reg.get(doc["tool"])

    def refuse(why):
        res = _result_base(tool, None, "refused", EXIT_REFUSED, run_dir)
        res.update(refused_by=["confirm"], error=why, plan=str(path))
        if run_dir:
            Path(run_dir).mkdir(parents=True, exist_ok=True)
            _write_result(run_dir, res)
        return res, EXIT_REFUSED
    if tool_id and tool_id != tool.id:
        return refuse(f"the plan is for {tool.id}, not {tool_id}")
    if tool.digest != doc.get("manifest_sha256"):
        return refuse(f"{tool.id}'s manifest changed after the plan (now {tool.digest[:16]}, the plan pinned "
                      f"{str(doc.get('manifest_sha256'))[:16]}): make a new plan")
    try:
        job = prepare(tool, doc["selection"], doc.get("explicit"), doc.get("given"), doc.get("purpose", "benchmark"),
                      doc.get("experiment"), (), bool(doc.get("yes_download")), root, kind=kind)
    except RegistryError as exc:
        return refuse(f"the inputs cannot be bound again: {exc}")
    if job.digest != doc["plan_digest"]:
        return refuse(f"an input or param changed since the plan (digest now {job.digest[:16]}, the plan "
                      f"{doc['plan_digest'][:16]}): make a new plan")
    res, code = run(tool, job, run_dir=run_dir, slug=slug, root=root, ledger_root=ledger_root, registry=reg)
    res["confirmed_plan"] = {"path": str(path), "digest": doc["plan_digest"]}
    if res.get("run"):
        _write_result(res["run"], res)
    return res, code


def _newest_run(env=None):
    runs = [d for d in _plan_dirs(ROOT, env)[:1] if d.is_dir()]
    found = []
    for d in runs:
        for f in d.glob("*/*/vc3d-result.json"):
            try:
                if _read_json(f).get("status") == "ok":
                    found.append((f.stat().st_mtime_ns, f.parent))
            except (OSError, ValueError, AttributeError):
                continue
    if not found:
        raise RegistryError("no finished run under VC3D's plugin run folders; name one with --run")
    return max(found)[1]


TAKE_FITS = {"segment": (("surface",), ("tifxyz",)), "ink_overlay": (("overlay",), OVERLAY_FORMATS),
             "points": (("points",), ("vc3d-point-collection", "json-points")),
             "umbilicus": (("umbilicus",), ("umbilicus-json",)), "file": (OUTPUT_KINDS, FORMATS)}


def take(kind, dest, run=None, output=None, env=None):
    """Copy one checked output of a finished registry run into dest (VC3D's fresh run folder) as KIND, so the plugin
    host loads it from its own folder: the run must be ok with its format gate passed, and a hashed output must still
    match its sha256. Writes dest/take.json; returns it."""
    if kind not in TAKE_KINDS:
        raise RegistryError(f"take KIND is one of {', '.join(TAKE_KINDS)}")
    src_run = Path(run).expanduser() if run else _newest_run(env)
    res_path = src_run / "vc3d-result.json"
    if not res_path.is_file():
        raise RegistryError(f"{src_run} has no vc3d-result.json: not a finished registry run")
    res = _read_json(res_path)
    if res.get("status") != "ok":
        raise RegistryError(f"{src_run}: the run is {res.get('status')}, so nothing is taken from it")
    if any(g.get("verdict") == "fail" for g in res.get("format_gate") or []):
        raise RegistryError(f"{src_run}: its format gate failed, so nothing is taken from it")
    kinds, fmts = TAKE_FITS[kind]
    rows = [r for r in res.get("outputs") or [] if r.get("exists") and (output and r.get("name") == output or not
                                                                         output and r.get("kind") in kinds
                                                                         and r.get("format") in fmts)]
    if not rows:
        raise RegistryError(f"{src_run}: no output {output or ''} that VC3D can load as {kind}".replace("  ", " "))
    row = rows[0]
    if row.get("kind") not in kinds or row.get("format") not in fmts:
        raise RegistryError(f"{src_run}: output {row['name']} is {row.get('kind')} ({row.get('format')}), not "
                            f"something VC3D loads as {kind}")
    src = Path(row["path"])
    if not _inside(src, src_run):
        raise RegistryError(f"{src} is outside its run folder; refusing")
    if row.get("sha256") and _sha256_file(src) != row["sha256"]:
        raise RegistryError(f"{src} changed after its run (sha256 differs); refusing")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    target = Path(TAKE_PATHS[kind].replace("{output}", str(dest)))
    if kind == "file":
        target = dest / src.name
    if kind == "segment":
        shutil.copytree(src, target)
        meta = target / "meta.json"
        try:
            m = _read_json(meta)
            if isinstance(m, dict):
                m["uuid"] = f"{m.get('uuid') or src.name}-take-{_sha256_file(res_path)[:10]}"
                _atomic_write(meta, _dump(m))
        except (OSError, ValueError):
            pass
    elif kind == "points" and row["format"] == "json-points":
        pts = [[float(c) for c in (q.get("xyz", q.get("p")) if isinstance(q, dict) else q)] for q in _read_json(src)]
        _atomic_write(target, _dump(points_document(pts, f"{res.get('tool')} {row['name']}")))
    elif kind == "ink_overlay" and (res.get("views") or {}).get(row["name"]):
        view = Path(res["views"][row["name"]])     # the 8-bit view: the run's shared scale, placed on the canvas
        if not _inside(view, src_run) or not view.is_file():
            raise RegistryError(f"{view}: the 8-bit view of {row['name']} is missing or outside its run folder")
        want = (res.get("views_sha256") or {}).get(row["name"])
        if not want or _sha256_file(view) != want:
            raise RegistryError(f"{view} changed after its run (sha256 differs or was not recorded); refusing")
        shutil.copyfile(view, target)
        src = view
    elif kind == "ink_overlay" and src.suffix == ".npy":
        import numpy as np
        import tifffile
        tifffile.imwrite(target, np.load(src))
    elif kind == "ink_overlay" and src.suffix == ".png":
        raise RegistryError(f"{src} is a PNG; VC3D's ink detection loader here takes a TIFF")
    else:
        shutil.copyfile(src, target)
    doc = {"schema": "scrolls-take/1", "kind": kind, "from_run": str(src_run), "tool": res.get("tool"),
           "output": row["name"], "role": row.get("role"), "source": str(src), "source_sha256": row.get("sha256"),
           "path": str(target), "claim": res.get("claim"), "at": utc_now()}
    _atomic_write(dest / "take.json", _dump(doc))
    return doc


def launch(argv, env=None, ppid=None):
    """What VC3D's launcher (bin/scrolls-tool) runs: python -m kit tools ARGV, with the agent bridge of the VC3D that
    started it (parent_bridge: VC3D_AGENT_BRIDGE_SOCKET, else ~/.vc3d/agent_bridge/PPID.json; never the newest)
    passed as --bridge-path to the actions that read a selection."""
    argv = list(argv)
    if argv and argv[0] in ("plan", "run", "list", "selection") and not {"--bridge-path", "--from-app",
                                                                         "--selection"} & set(argv):
        found = parent_bridge(ppid, env)
        if found:
            argv += ["--bridge-path", found["path"]]
    return main(argv)


# ---------------------------------------------------------------- provenance and causal links


def _provenance(tool, job, outs, run_dir, started):
    from . import provenance
    budget = 256 << 20
    inputs, skipped = [], []
    for rec in job.record.values():
        for v in rec["value"] if isinstance(rec["value"], list) else [rec["value"]]:
            if not isinstance(v, str) or is_remote(v) or not os.path.exists(v):
                if isinstance(v, str):
                    skipped.append(v)
                continue
            size = _size(v, budget + 1)
            if size > budget:
                skipped.append(v)
                continue
            budget -= size
            inputs.append(v)
    outputs = [str(p) for p in outs.values() if p.exists()]
    try:
        rec = provenance.build(f"tools:{tool.id}:{job.digest[:10]}", KIT_ROOT, started=started, inputs=inputs,
                               outputs=outputs, note=f"{tool.title}; manifest sha256 {tool.digest}",
                               notes=[f"not hashed (remote or over the size budget): {s}" for s in skipped] or None)
        path = Path(run_dir) / "provenance.json"
        provenance.write(rec, path)
        return {"path": str(path), "digest": rec["digest"]}
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}


def _size(path, stop):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            if total >= stop:
                return total
    return total


def _ap_run_of(path):
    """The AutoPipeline run folder (plan.json and state.json) holding path, or None."""
    p = Path(path).resolve()
    for parent in [p] + list(p.parents)[:6]:
        if (parent / "plan.json").is_file() and (parent / "state.json").is_file():
            return parent
    return None


def _graph(tool, job, outs, run_dir, conversions=None):
    """RUN/graph.json in AutoPipeline's causal-link vocabulary (graph version 1: input, stage and file nodes; read,
    made and derived_from edges), so a trace can be followed from an AutoPipeline run into a registry run."""
    nodes, edges = {}, []
    stage = f"stage:tool:{tool.id}"
    nodes[stage] = {"id": stage, "kind": "stage", "stage": f"tool:{tool.id}", "backend": tool.id,
                    "manifest_sha256": tool.digest, "repo": tool["repo"], "license": tool.facts.get("license"),
                    "status": "done"}
    for name, rec in sorted(job.record.items()):
        for v in rec["value"] if isinstance(rec["value"], list) else [rec["value"]]:
            if not isinstance(v, str):
                nid = f"input:{name}"
                nodes[nid] = {"id": nid, "kind": "input", "key": name, "value": v}
            else:
                nid = f"file:{v}"
                info = {"id": nid, "kind": "file", "path": v, "outside_run": True, "input": name}
                if not is_remote(v) and os.path.isfile(v) and os.path.getsize(v) <= HASH_MAX:
                    info["sha256"] = _sha256_file(v)
                nodes[nid] = info
                ap = _ap_run_of(v) if not is_remote(v) else None
                if ap is not None:
                    rel = Path(v).resolve().relative_to(ap).as_posix()
                    edges.append({"from": nid, "to": f"run:{ap}#file:{rel}", "rel": "derived_from"})
            edges.append({"from": nid, "to": stage, "rel": "read"})
    for name, p in outs.items():
        if not p.exists():
            continue
        rel = p.resolve().relative_to(Path(run_dir).resolve()).as_posix()
        nid = f"file:{rel}"
        nodes[nid] = {"id": nid, "kind": "file", "path": rel, "made_by": f"tool:{tool.id}", "output": name,
                      **({"sha256": _sha256_file(p)} if p.is_file() and p.stat().st_size <= HASH_MAX else {})}
        edges.append({"from": stage, "to": nid, "rel": "made"})
    for conv in conversions or []:
        cstage = f"stage:convert:{conv['output']}"
        nodes[cstage] = {"id": cstage, "kind": "stage", "stage": f"convert:{conv['converter']}",
                         "backend": conv["converter"], "manifest_sha256": conv["manifest_sha256"],
                         "status": "done" if conv.get("status") == "ok" else conv.get("status")}
        src = Path(conv["from"]).resolve().relative_to(Path(run_dir).resolve()).as_posix()
        nodes.setdefault(f"file:{src}", {"id": f"file:{src}", "kind": "file", "path": src,
                                         "made_by": f"tool:{tool.id}", "output": conv["output"]})
        edges.append({"from": stage, "to": f"file:{src}", "rel": "made"})
        edges.append({"from": f"file:{src}", "to": cstage, "rel": "read"})
        if conv.get("to"):
            dst = Path(conv["to"]).resolve().relative_to(Path(run_dir).resolve()).as_posix()
            if f"file:{dst}" in nodes:
                nodes[f"file:{dst}"]["made_by"] = f"convert:{conv['converter']}"
                edges = [e for e in edges if not (e["to"] == f"file:{dst}" and e["from"] == stage)]
            edges.append({"from": cstage, "to": f"file:{dst}", "rel": "made"})
    graph = {"version": 1, "run": str(run_dir), "tool": tool.id, "nodes": list(nodes.values()), "edges": edges,
             "note": "A registry run: one stage (the tool) read its inputs and made its outputs. " + CLAIM + " when "
                     "the tool makes ink maps."}
    graph["digest"] = _digest({"nodes": graph["nodes"], "edges": edges})
    path = Path(run_dir) / "graph.json"
    _atomic_write(path, _dump(graph))
    return path


# ---------------------------------------------------------------- AutoPipeline door


def existing_backends(tool):
    """The stage backends a tool already is: pipeline.existing, or every enum value of the param it names as
    {param.NAME} (one tool that runs any of the stage's models, such as AutoPipeline's ink script)."""
    ex = (tool["pipeline"] or {}).get("existing")
    if not isinstance(ex, str) or not ex:
        return []
    if PLACEHOLDER.fullmatch(ex) and ex[1:-1].startswith("param."):
        return [str(v) for v in (tool.params.get(ex[7:-1]) or {}).get("enum") or []]
    return [ex]


def stage_choices(stage, registry=None):
    """{backend name: entry} the registry adds to one AutoPipeline stage: an ink-command tool becomes reg:ID; a tool
    that is already a stage's backend annotates that entry (existing). Each entry carries the manifest digest."""
    reg = registry or load_cached()
    out = {}
    for tool in reg:
        pipe = tool["pipeline"] or {}
        if pipe.get("stage") != stage or tool.kind != "tool":
            continue
        block = {"id": tool.id, "manifest_sha256": tool.digest, "manifest": str(tool.path)}
        if pipe.get("existing"):
            for name in existing_backends(tool):
                out[name] = {"registry": block}
            continue
        if stage == "repair" and pipe.get("contract") == "repair":
            out[f"reg:{tool.id}"] = {
                "origin": "ours" if tool["repo"] in ("public", "private") else "community",
                "by": f"{tool.title} (tool registry, kit/data/registry/{tool.id}.json, through toolreg.exec_repair)",
                "kind": "classical" if not tool.safety.get("model_output") else "learned",
                "licence": tool.facts.get("license") or "this repository", "needs": [],
                "compute": "gpu" if "gpu" in tool.compute.get("where", "local-cpu") else "cpu",
                "settings": {"qa": {"repair": {"method": f"reg:{tool.id}"}}}, "registry": block}
            continue
        if stage == "ink" and pipe.get("contract") == "ink-command":
            comp = tool.compute.get("where", "local-cpu")
            out[f"reg:{tool.id}"] = {
                "origin": "ours" if tool["repo"] in ("public", "private") else "community",
                "by": f"{tool.title} (tool registry, kit/data/registry/{tool.id}.json, through python -m kit tools "
                      "exec)", "kind": "classical" if not tool.safety.get("model_output") else "learned",
                "licence": tool.facts.get("license") or "this repository", "needs": [],
                "compute": "gpu" if "gpu" in comp else "cpu", "settings": {"ink": {"models": [f"reg:{tool.id}"]}},
                "registry": block}
    return out


def ink_models(registry=None):
    """In-memory command-engine registrations for AutoPipeline's ink stage, one per ink-command manifest, named
    reg:ID; nothing is written to the model registry file. The command pins the manifest digest, so a manifest that
    changed after planning is refused at run time."""
    reg = registry or load_cached()
    out = {}
    for tool in reg:
        pipe = tool["pipeline"] or {}
        if tool.kind == "tool" and pipe.get("stage") == "ink" and pipe.get("contract") == "ink-command":
            out[f"reg:{tool.id}"] = {
                "engine": "command",
                "command": [sys.executable, "-m", "kit", "tools", "exec", tool.id, "--sha256", tool.digest[:16], "--",
                            "{input}", "{output}", "{reverse}"],
                "notes": f"tool registry: {tool.title}; {CLAIM}", "registry": {"id": tool.id,
                                                                               "manifest_sha256": tool.digest}}
    return out


def exec_ink(tool, input_path, output, reverse, sha=None, root=ROOT, ledger_root=None):
    """AutoPipeline's ink command engine calls this once with reverse 0 and once with 1 on the same input. Mode pair:
    the tool runs once per input (cached beside the output) and the forward or the control map is copied to output;
    mode flag: the tool runs with its reverse flag. Returns an exit code."""
    pipe = tool["pipeline"] or {}
    if pipe.get("stage") != "ink" or pipe.get("contract") != "ink-command":
        raise RegistryError(f"{tool.id} is not an ink-command backend")
    if sha and not tool.digest.startswith(sha):
        raise RegistryError(f"{tool.id}'s manifest changed after the plan was made (digest {tool.digest[:16]}, the "
                            f"plan pinned {sha}): make a new plan")
    if str(reverse) not in ("0", "1"):
        raise RegistryError(f"reverse must be 0 or 1, not {reverse!r}")
    out = Path(output)
    sel = selection_from(source="autopipeline")
    explicit = {pipe["input"]: input_path}
    job = prepare(tool, sel, explicit)
    if pipe["reverse"] == "flag" and str(reverse) == "1":
        tool = Tool(json.loads(json.dumps(tool.m)), tool.path, tool.source)
        tool.m["run"]["argv"] = list(tool.m["run"]["argv"]) + list(pipe["flag"])
        job = prepare(tool, sel, explicit)
    cache = out.parent / ".toolreg" / f"{tool.id}-{job.digest[:10]}{'-r' if pipe['reverse'] == 'flag' and str(reverse) == '1' else ''}"
    if (cache / "vc3d-result.json").is_file() and _read_json(cache / "vc3d-result.json").get("status") == "ok":
        res, code = _read_json(cache / "vc3d-result.json"), EXIT_OK
    else:
        if cache.exists():
            shutil.rmtree(cache)
        res, code = run(tool, job, run_dir=cache, root=root, ledger_root=ledger_root)
    if code != EXIT_OK:
        print(json.dumps({"tool": tool.id, "status": res.get("status"), "exit": code, "run": str(cache)}),
              file=sys.stderr)
        return code
    outs = {n: Path(s["path"].replace("{run}", str(cache))) for n, s in tool.outputs.items()}
    if pipe["reverse"] == "pair" and str(reverse) == "1":
        src = outs[pipe["pair_output"]]
    else:
        src = next(outs[n] for n, s in tool.outputs.items() if s["kind"] == "overlay"
                   and s.get("role", "forward") == "forward")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix == ".npy" and src.suffix != ".npy":
        import numpy as np
        import tifffile
        np.save(out, np.asarray(tifffile.imread(src)))
    elif out.suffix in (".tif", ".tiff") and src.suffix == ".npy":
        import numpy as np
        import tifffile
        tifffile.imwrite(out, np.load(src))
    else:
        shutil.copyfile(src, out)
    return EXIT_OK


def exec_repair(tool, surface, run_dir, prediction, seed=None, voxel_um=None, sha=None, root=ROOT, ledger_root=None):
    """AutoPipeline's qa stage calls this for a repair backend reg:ID (the repair contract, pipeline.input,
    prediction, seed and output): the tool runs on the rejected trace and the plan's surface prediction in run_dir
    (made fresh; it writes nothing else), through every gate, the local cost ledger, the write audit and the format
    gate. Returns (result, exit code, the repaired tifxyz folder or None); qa then checks the copy by its own rule.
    sha, the digest the plan froze, refuses a manifest edited since."""
    pipe = tool["pipeline"] or {}
    if pipe.get("stage") != "repair" or pipe.get("contract") != "repair":
        raise RegistryError(f"{tool.id} is not a repair backend")
    if sha and not tool.digest.startswith(sha):
        raise RegistryError(f"{tool.id}'s manifest changed after the plan was made (digest {tool.digest[:16]}, the "
                            f"plan froze {sha[:16]}): make a new plan")
    explicit = {pipe["input"]: str(surface), pipe["prediction"]: str(prediction)}
    if seed is not None and pipe.get("seed"):
        explicit[pipe["seed"]] = ",".join(repr(float(v)) for v in seed)
    sel = selection_from(source="autopipeline", voxel_um=voxel_um)
    job = prepare(tool, sel, explicit)
    run_dir = Path(run_dir)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    res, code = run(tool, job, run_dir=run_dir, root=root, ledger_root=ledger_root)
    out = Path(tool.outputs[pipe["output"]]["path"].replace("{run}", str(run_dir)))
    return res, code, (out if code == EXIT_OK and out.is_dir() else None)


# ---------------------------------------------------------------- VC3D plugin manifests


def _plugin_args(tool):
    """The plugin host's argument list for one tool: one flag per selection kind its required inputs bind from, so
    VC3D refuses to start it (saying what is missing) when that is not selected; a bridge-bound input becomes an
    {input:NAME} the person fills (segment ids, or an ink detection label)."""
    flags, seen = [], set()
    inputs = []
    for name, spec in tool.inputs.items():
        if spec.get("bind") == "bridge":
            what = "segment ids, inner to outer, separated by commas" if spec.get("from") == "segments" else \
                "a segment id" if "tifxyz" in (spec.get("format") or []) else "an ink detection label"
            inputs.append({"name": name, "label": f"{spec.get('label') or name} ({what})", "default": ""})
            flags += ["--input", f"{name}={{input:{name}}}"]
            continue
        if not spec.get("required", True):
            continue
        ph = FROM_PLACEHOLDER.get(spec["from"])
        if ph and ph not in seen:
            seen.add(ph)
            flags += [f"--{ph.replace('_', '-')}", "{" + ph + "}"]
    for name, spec in tool.params.items():
        uses_volume = spec.get("from") == "volume.voxel_um"
        if uses_volume and "volume" not in seen:
            seen.add("volume")
            flags += ["--volume", "{volume}"]
        if spec.get("default") is not None and not uses_volume:
            continue
        default = "auto" if uses_volume else ""
        inputs.append({"name": name, "label": spec.get("help") or name.replace("_", " "), "default": default})
        flags += ["--param", f"{name}={{input:{name}}}"]
    return flags, inputs


def _optional_region(tool):
    return any(not spec.get("required", True) and spec.get("from") == "region" and spec.get("bind") != "bridge"
               for spec in tool.inputs.values())


def plugin_manifests(registry=None, include_private=False):
    """{entry key: vc3d-plugin/1 manifest} for every tool whose doors include vc3d (vc3d_entries: a run entry, or a
    "Plan:" entry and, for vc3d.confirm, a "Run planned:" entry), plus the generic "Open run output as KIND"
    entries that bring any checked output of a finished run back into VC3D (take)."""
    reg = registry or load()
    out = {}
    for tool in reg:
        if tool["repo"] == "private" and not include_private:
            continue
        modes = vc3d_entries(tool)
        if not modes:
            continue
        flags, inputs = _plugin_args(tool)
        vc = tool["vc3d"] or {}
        label = vc.get("label") or tool.title
        desc = tool.facts.get("tagline") or tool.title
        if tool.safety.get("model_output"):
            desc += f". {CLAIM}."
        base = {"schema": PLUGIN_SCHEMA, "menu": f"Scrolls/{vc.get('menu', 'tools')}", "program": f"bin/{LAUNCHER}"}
        extra = {}
        if tool.facts.get("license"):
            extra["license"] = tool.facts["license"]
        if tool.facts.get("page"):
            extra["homepage"] = "https://github.com/ChaseHendrick/Scrolls/blob/main/" + tool.facts["page"]
        if "run" in modes:
            m = dict(base, id=f"scrolls.{tool.id}", name=label, description=desc,
                     args=["run", tool.id] + flags + ["--out", "{output}", "--json"])
            if inputs:
                m["inputs"] = inputs
            m["result"] = plugin_result(tool, reg)
            out[tool.id] = dict(m, **extra)
            if _optional_region(tool) and "{region}" not in flags:
                # the host refuses a start when a placeholder has no value, so an optional focus region gets its own
                # entry, which VC3D enables only while a focus region is set
                out[f"{tool.id}.region"] = dict(m, id=f"scrolls.{tool.id}.region", name=f"{label} (focus region)",
                                                description=f"{desc}. Only the focus region, as a box on the "
                                                            "segment's canvas.",
                                                args=["run", tool.id] + flags + ["--region", "{region}", "--out",
                                                                                 "{output}", "--json"], **extra)
        if "plan" in modes:
            why = vc3d_plan_reasons(tool)
            m = dict(base, id=f"scrolls.{tool.id}.plan", name=f"Plan: {label}",
                     description=f"{desc}. A priced dry run: nothing runs" + (f" ({'; '.join(why)})" if why else "")
                     + ".", args=["plan", tool.id] + flags + ["--write", "{output}/plan.json", "--json"])
            if inputs:
                m["inputs"] = inputs
            m["result"] = {"kind": "file", "path": "{output}/plan.json"}
            out[f"{tool.id}.plan"] = dict(m, **extra)
        if "confirm" in modes:
            m = dict(base, id=f"scrolls.{tool.id}.confirm", name=f"Run planned: {label}",
                     description=f"{desc}. Runs a plan from its Plan: entry; the inputs must give the same digest.",
                     args=["confirm", "{input:digest}", "--tool", tool.id, "--out", "{output}", "--json"],
                     inputs=[{"name": "digest", "label": "the plan's digest (from its plan.json)", "default": ""}])
            m["result"] = plugin_result(tool, reg)
            out[f"{tool.id}.confirm"] = dict(m, **extra)
    for kind in TAKE_KINDS:
        out[f"take-{kind}"] = {
            "schema": PLUGIN_SCHEMA, "id": f"scrolls.take-{kind.replace('_', '-')}",
            "name": f"Open run output as {kind.replace('_', ' ')}",
            "description": "One checked output of a finished Scrolls tool run (status ok, format gate passed, sha256 "
                           "unchanged), copied into this run's folder so VC3D loads it: controls, second outputs and "
                           "AutoPipeline surfaces.",
            "menu": "Scrolls/Open run output", "program": f"bin/{LAUNCHER}",
            "args": ["take", kind, "--run", "{input:run}", "--output", "{input:output}", "--out", "{output}",
                     "--json"],
            "inputs": [{"name": "run", "label": "run folder (empty: the newest finished run)", "default": ""},
                       {"name": "output", "label": "output name (empty: the first that fits)", "default": ""}],
            "result": {"kind": kind, "path": TAKE_PATHS[kind]}}
    return out


def launcher_text(kit_root=None, up=None):
    """The launcher VC3D's plugin host starts (bin/scrolls-tool): python -m kit tools from a Scrolls checkout, found
    `up` folders above the launcher (inside the checkout) or at kit_root (an absolute path, for a folder outside)."""
    root = f"Path(__file__).resolve().parents[{up}]" if up is not None else f"Path({str(kit_root or KIT_ROOT)!r})"
    return ("#!/usr/bin/env python3\n"
            '"""Launcher for VC3D\'s plugin host: runs `python -m kit tools ARGS` from a Scrolls checkout (written by\n'
            'python -m kit tools export-vc3d; SCROLLS_KIT_ROOT overrides where kit is)."""\n'
            "import os\nimport sys\nfrom pathlib import Path\n\n"
            f"ROOT = Path(os.environ['SCROLLS_KIT_ROOT']) if os.environ.get('SCROLLS_KIT_ROOT') else {root}\n"
            "sys.path.insert(0, str(ROOT))\n"
            "from kit import toolreg  # noqa: E402\n\n"
            "sys.exit(toolreg.launch(sys.argv[1:]))\n")


def export_vc3d(dest, registry=None, include_private=False, root=ROOT, check_only=False):
    """Write DEST/scrolls.ID.json (vc3d-plugin/1) for each tool VC3D can start and DEST/bin/scrolls-tool; with
    check_only, return the files that differ instead. Stale scrolls.*.json manifests are removed. A launcher inside
    the checkout finds kit relative to itself; one outside names this kit's folder."""
    dest = Path(dest)
    order = ("schema", "id", "name", "description", "menu", "program", "args", "inputs", "result", "license",
             "homepage")
    files = {f"{m['id']}.json": json.dumps({k: m[k] for k in order if k in m}, indent=1, ensure_ascii=False) + "\n"
             for m in plugin_manifests(registry, include_private).values()}
    try:
        up = len((dest / "bin").resolve().relative_to(Path(root).resolve()).parts)
    except ValueError:
        up = None
    files[f"bin/{LAUNCHER}"] = launcher_text(None, up)
    stale = sorted(p.name for p in dest.glob("scrolls.*.json") if p.name not in files) if dest.is_dir() else []
    if check_only:
        diff = [rel for rel, text in files.items() if not (dest / rel).is_file()
                or (dest / rel).read_text(encoding="utf-8") != text]
        return diff + stale
    for rel, text in files.items():
        _atomic_write(dest / rel, text)
    os.chmod(dest / "bin" / LAUNCHER, 0o755)
    for name in stale:
        (dest / name).unlink()
    return sorted(files)


# ---------------------------------------------------------------- facts and checks


def facts_for(page, root):
    """The facts block of a manifest, copied from its tool page (kit.tooldocs.Page)."""
    name, _, tagline = page.title.partition(": ")
    go = page.field("Go-ahead")
    checked = re.match(r"^(\d{4}-\d{2}-\d{2}) against commit `([0-9a-f]{7,40})`", page.field("Checked"))
    agent = {}
    for line in page.body("For agents").splitlines():
        m = re.match(r"^- \*\*([^*]+?):\*\*\s*(.*)$", line)
        if m:
            agent[m.group(1).strip()] = m.group(2).strip()
    facts = {"title": name, "tagline": tagline or page.summary, "status": page.field("Status"),
             "kind": [k.strip() for k in page.field("Kind").split(",") if k.strip()], "area": page.field("Area"),
             "page": page.path.relative_to(root).as_posix(), "go_ahead": go.startswith("Needed"),
             "network": page.field("Network"), "license": page.field("License") or None,
             "checked": f"{checked.group(1)} {checked.group(2)}" if checked else page.field("Checked"),
             "success": agent.get("Success"), "not_a_pass": agent.get("Not a pass"), "never": agent.get("Never")}
    return facts


def _pages(root):
    from . import tooldocs
    return {p.id: p for p in tooldocs.load_pages(Path(root) / "docs" / "tools")}


def write_facts(root=ROOT):
    """Rewrite each kit manifest's facts block from its page; returns the manifests changed."""
    root = Path(root)
    folder = root / REGISTRY_REL
    if not folder.is_dir():
        return []
    pages = _pages(root)
    changed = []
    for path in sorted(folder.glob("*.json")):
        if path.name == SKIP_FILE:
            continue
        try:
            m = _read_json(path)
        except (OSError, ValueError):
            continue
        page = pages.get(m.get("page") or m.get("id")) if isinstance(m, dict) else None
        if page is None:
            continue
        new = dict(m, facts=facts_for(page, root))
        text = json.dumps(new, indent=1, ensure_ascii=False) + "\n"
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            changed.append(path.name)
    return changed


def _kit_commands():
    from . import tooldocs
    return tooldocs.kit_commands()


def check(root=ROOT, commands=None, pages=None, env=None):
    """Every problem with the repository's tool registry; empty when it is consistent. tooldocs check runs it."""
    root = Path(root)
    folder = root / REGISTRY_REL
    if not folder.is_dir():
        return []
    env = {} if env is None else env       # the repository's own manifests only, never the person's folders
    reg = load(root, env)
    problems = [f"{Path(p).relative_to(root) if str(p).startswith(str(root)) else p}" for p in reg.problems]
    pages = pages if pages is not None else _pages(root)
    kind = _repo_kind(root)
    try:
        commands = commands if commands is not None else (_kit_commands() if root == ROOT else None)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"cannot build kit's parser for the registry check: {exc}")
        commands = None
    rel = lambda t: t.path.relative_to(root).as_posix() if str(t.path).startswith(str(root)) else str(t.path)  # noqa: E731
    for tool in reg:
        where = rel(tool)
        pid = tool["page"] or tool.id
        page = pages.get(pid)
        if tool["repo"] == "community" or tool.kind == "native":
            if page is not None:
                problems.append(f"{where}: {pid} has a tool page, so its repo is public or private")
            continue
        if page is None:
            problems.append(f"{where}: no tool page docs/tools/{pid}.md; a manifest belongs to a tool with a page")
            continue
        if kind == "public" and tool["repo"] != "public":
            problems.append(f"{where}: repo {tool['repo']} in public Scrolls; private manifests live in Scrolls-private")
        status = page.field("Status")
        if status == "Retired":
            problems.append(f"{where}: {tool.id} is Retired; a retired tool carries no manifest")
        want = facts_for(page, root)
        if tool.facts != want:
            problems.append(f"{where}: facts are out of date with docs/tools/{pid}.md: run python -m kit.tooldocs "
                            "index")
        net = page.field("Network")
        net_none = net.startswith("None")
        # "None for local inputs. With a URL, ...": a page whose tool reads the network only when given a remote input
        # fits a manifest that never does (none) and one whose inputs may be URLs (public-read)
        conditional = net_none and re.match(r"None (?:for|with|when|unless|except)\b", net) is not None
        if net_none != (tool.safety.get("network") == "none") and not (
                conditional and tool.safety.get("network") == "public-read"):
            problems.append(f"{where}: the page's Network field ({page.field('Network')[:40]!r}) and safety.network "
                            f"({tool.safety.get('network')}) disagree")
        problems += [f"{where}: {m}" for m in _check_program(tool, page, root, commands, status)]
        for fn in STAGE_CHECKS:
            problems += [f"{where}: {m}" for m in fn(tool.m)]
    for tid, why in sorted(reg.skip.items()):
        if tid in reg.tools:
            problems.append(f"{REGISTRY_REL / SKIP_FILE}: {tid} has a manifest; remove it from skip.json")
        elif tid not in pages:
            problems.append(f"{REGISTRY_REL / SKIP_FILE}: {tid} has no tool page; remove it")
        elif not isinstance(why, str) or len(why.strip()) < 12:
            problems.append(f"{REGISTRY_REL / SKIP_FILE}: {tid} needs a reason of a few words")
    runnable = ("kit command", "kit entry point", "script", "script folder", "kit module")
    covered = {t["page"] or t.id for t in reg}
    # every runnable tool has a manifest or a reason: public Scrolls' rule; Scrolls-private's folder holds only the
    # manifests of its private tools so far (its open-items row), so there the rule is not applied
    for pid, page in sorted(pages.items()) if kind != "private" else ():
        kinds = [k.strip() for k in page.field("Kind").split(",")]
        if page.field("Status") in ("Current", "Experimental") and any(k in runnable for k in kinds):
            if pid not in covered and pid not in reg.skip:
                problems.append(f"docs/tools/{pid}.md: no manifest in {REGISTRY_REL}/ and no reason in "
                                f"{REGISTRY_REL / SKIP_FILE}; every runnable tool has one or the other")
    plugins = root / PLUGINS_REL
    if plugins.is_dir():
        stale = export_vc3d(plugins, reg, root=root, check_only=True)
        if stale:
            problems.append(f"{PLUGINS_REL}/ is out of date ({', '.join(stale[:5])}): run python -m kit tools "
                            f"export-vc3d {PLUGINS_REL}")
    return problems


def _check_program(tool, page, root, commands, status):
    argv = (tool["run"] or {}).get("argv") or []
    if not argv:
        return []
    run_field = " ".join(page.spans("Run")) + " " + page.field("Run")
    if argv[0] == "{python}" and len(argv) >= 3 and argv[1] == "-m":
        mod = argv[2]
        if mod == "kit":
            cmd = argv[3] if len(argv) > 3 else None
            if commands is not None and cmd not in commands.parsers:
                return [f"run.argv names python -m kit {cmd}, which is not a kit command"]
            if f"python -m kit {cmd}" not in run_field:
                return [f"run.argv runs python -m kit {cmd}, which the page's Run field does not name"]
            return []
        if mod.startswith("kit."):
            if not (Path(root) / "kit" / f"{mod[4:]}.py").is_file():
                return [f"run.argv names {mod}, which is not a module of this kit"]
            return []
        return [f"run.argv runs python -m {mod}; a kit manifest runs kit or a program its page names"]
    if argv[0] == "{python}":
        return ["run.argv must run a module (python -m ...)"]
    if argv[0] not in page.text:
        return [f"run.argv runs {argv[0]}, which its page does not name"]
    return []


# ---------------------------------------------------------------- availability


def availability(tool):
    """[{need, status: ready|missing|fetch, detail}] for what the tool needs here."""
    rows = []
    argv = (tool["run"] or {}).get("argv") or []
    if tool.kind == "native":
        prog = tool["native"]["program"]
        found = shutil.which(prog)
        rows.append({"need": f"binary:{prog}", "status": "ready" if found else "missing",
                     "detail": found or f"{prog} not on PATH (build villa, or use VC3D's own menu)"})
        return rows
    if argv and argv[0] != "{python}":
        found = shutil.which(argv[0])
        rows.append({"need": f"program:{argv[0]}", "status": "ready" if found else "missing",
                     "detail": found or f"{argv[0]} not on PATH"})
    if argv[:3] == ["{python}", "-m", "kit"] and len(argv) > 3:
        rows.append({"need": f"kit command {argv[3]}", "status": "ready", "detail": str(KIT_ROOT)})
    for mod in ("numpy", "tifffile", "zarr"):
        if mod in str(tool.facts) or mod in json.dumps(tool.m.get("notes", "")):
            ok = importlib.util.find_spec(mod) is not None
            rows.append({"need": mod, "status": "ready" if ok else "missing",
                         "detail": "in kit's Python" if ok else f"python3 -m pip install {mod}"})
    if tool.safety.get("downloads_mb"):
        rows.append({"need": "download", "status": "fetch",
                     "detail": f"about {tool.safety['downloads_mb']:g} MB on first use (--yes-download)"})
    return rows


# ---------------------------------------------------------------- command line


def _pairs(items, what):
    out = {}
    for item in items or []:
        k, sep, v = str(item).partition("=")
        if not sep or not k:
            raise RegistryError(f"{what} {item!r} is not NAME=VALUE")
        out[k] = v
    return out


def _selection_args(p):
    p.add_argument("--selection", help="a vc3d-selection/1 file")
    p.add_argument("--from-app", nargs="?", const="", default=None, metavar="NAME",
                   help="read the selection from a running VC3D's agent bridge (read-only calls); NAME or a socket "
                        "path picks one, else the newest")
    p.add_argument("--volume", help="the open volume: a local zarr folder or a URL ({volume})")
    p.add_argument("--segment", help="the active segment's tifxyz folder ({segment})")
    p.add_argument("--ink-overlay", help="the selected ink detection overlay image ({ink_overlay})")
    p.add_argument("--point", help="the focus point x,y,z in level-0 voxels ({point})")
    p.add_argument("--region", help="the focus region x0,y0,z0,x1,y1,z1 in level-0 voxels ({region})")
    p.add_argument("--crop", help="a box Y0,Y1,X0,X1 on the segment's canvas")
    p.add_argument("--umbilicus", help="the attached umbilicus JSON ({umbilicus})")
    p.add_argument("--project", help="the open project, a .volpkg.json ({project})")
    p.add_argument("--points", help="a point collection file")
    p.add_argument("--segments", action="append", default=[], help="a tifxyz folder; repeat in order (inner to outer)")
    p.add_argument("--voxel-um", type=float, help="the volume's voxel size, when it cannot be read from it")
    p.add_argument("--bridge-path", metavar="SOCKET", help="read segment ids and the voxel size once from this "
                   "VC3D's agent bridge (read-only); VC3D's launcher passes its parent VC3D's bridge")


def add_arguments(parser):
    """The `python -m kit tools` actions."""
    acts = parser.add_subparsers(dest="action", required=True)
    a = acts.add_parser("list", help="every tool in the registry, with its doors")
    a.add_argument("--door", choices=["cli", "mcp", "vc3d", "ap", "native"], help="only tools with this door")
    a.add_argument("--accepts", choices=INPUT_FROM, help="only tools with an input bound from this")
    _selection_args(a)
    a.add_argument("--json", action="store_true")
    a = acts.add_parser("show", help="one manifest, its doors, digest and agent rules")
    a.add_argument("id")
    a.add_argument("--json", action="store_true")
    a = acts.add_parser("check", help="every manifest against its page and the code")
    a.add_argument("--json", action="store_true")
    a = acts.add_parser("availability", help="what the tool needs on this machine")
    a.add_argument("id")
    a.add_argument("--json", action="store_true")
    a = acts.add_parser("selection", help="what VC3D has selected, as a vc3d-selection/1 document")
    _selection_args(a)
    a.add_argument("--out", help="write it here instead of printing it")
    for name, text in (("plan", "the dry run: bound inputs, command, outputs and gates; writes nothing"),
                       ("run", "bind, gate, run, audit and hand the outputs to VC3D")):
        a = acts.add_parser(name, help=text)
        a.add_argument("id")
        _selection_args(a)
        a.add_argument("--input", action="append", default=[], metavar="NAME=PATH", help="bind an input explicitly")
        a.add_argument("--param", action="append", default=[], metavar="NAME=VALUE", help="set a param")
        a.add_argument("--purpose", choices=["benchmark", "smoke", "target"], default="benchmark",
                       help="target needs --experiment, a preregistered ledger record (Scrolls-private)")
        a.add_argument("--experiment", help="the ledger slug of a target run")
        a.add_argument("--allow-outside", action="append", default=[], choices=OUTSIDE_KINDS,
                       help="allow one declared write outside the run folder, for this run")
        a.add_argument("--yes-download", action="store_true", help="allow the tool's declared first-use download")
        a.add_argument("--json", action="store_true")
        if name == "run":
            a.add_argument("--out", help="the run folder (new or empty); default work/tools/ID-DIGEST10")
            a.add_argument("--fresh", action="store_true", help="a new run folder even when an identical run is done")
            a.add_argument("--slug", help="the ledger record for the cost entry (default tools-YYYYMMDD)")
        else:
            a.add_argument("--write", metavar="FILE", help="write the plan with its digest here and exit 0 (VC3D's "
                           "Plan: entry); confirm runs it")
    a = acts.add_parser("confirm", help="run a written plan; the inputs must give the same digest")
    a.add_argument("digest", help="the plan's digest (10 or more hex characters)")
    a.add_argument("--plan", help="the plan file (default: search VC3D's plugin run folders and work/tools/plans/)")
    a.add_argument("--tool", help="refuse unless the plan is for this tool")
    a.add_argument("--out", help="the run folder (new or empty)")
    a.add_argument("--slug", help="the ledger record for the cost entry")
    a.add_argument("--json", action="store_true")
    a = acts.add_parser("take", help="copy one checked output of a finished run into a folder for VC3D to load")
    a.add_argument("kind", choices=TAKE_KINDS)
    a.add_argument("--run", default="", help="the run folder (empty: the newest finished run VC3D started)")
    a.add_argument("--output", default="", help="the output's name (empty: the first that fits KIND)")
    a.add_argument("--out", required=True, help="where to copy it (VC3D's {output})")
    a.add_argument("--json", action="store_true")
    a = acts.add_parser("open", help="a finished run's VC3D handoff")
    a.add_argument("run_dir", metavar="RUN")
    a.add_argument("--live", nargs="?", const="", default=None, metavar="NAME",
                   help="a running VC3D: a bridge name or socket path; with none, only the VC3D that started this "
                        "command")
    a.add_argument("--apply", action="store_true", help="send the allow-listed calls (with --live)")
    a.add_argument("--replace-points", action="store_true",
                   help="also send points.load_json, which replaces every point collection in that VC3D")
    a.add_argument("--json", action="store_true")
    a = acts.add_parser("exec", help="AutoPipeline's ink command engine: ID -- INPUT OUTPUT REVERSE")
    a.add_argument("id")
    a.add_argument("--sha256", help="the manifest digest prefix the plan pinned")
    a.add_argument("words", nargs="*", metavar="WORD", help="three words after --: INPUT OUTPUT REVERSE")
    a = acts.add_parser("export-vc3d", help="VC3D plugin manifests (vc3d-plugin/1) and their launcher")
    a.add_argument("dest", metavar="DIR", help="a folder VC3D reads: ~/.vc3d/plugins or one in VC3D_PLUGIN_PATH")
    a.add_argument("--check", action="store_true", help="only say which files differ (exit 1 when any)")
    a.add_argument("--include-private", action="store_true", help="also private tools (only into a folder outside "
                                                                  "both repositories)")
    return parser


def _selection(args):
    if getattr(args, "selection", None):
        return read_selection(args.selection)
    if getattr(args, "from_app", None) is not None:
        return selection_from_app(args.from_app or None)
    sel = selection_from(volume=args.volume, segment=args.segment, ink_overlay=args.ink_overlay, point=args.point,
                         region=args.region, crop=args.crop, umbilicus=args.umbilicus, project=args.project,
                         points=args.points, segments=args.segments or None, voxel_um=args.voxel_um,
                         source="plugin" if args.volume or args.segment or args.point else "flags")
    if getattr(args, "bridge_path", None):
        sel = enrich_from_bridge(sel, args.bridge_path)
    return sel


def _has_selection(args):
    return any(getattr(args, k, None) for k in ("selection", "volume", "segment", "ink_overlay", "point", "region",
                                                "crop", "umbilicus", "project", "points", "segments")) or \
        getattr(args, "from_app", None) is not None


def _print(obj, as_json, lines=None):
    if as_json or lines is None:
        print(json.dumps(obj, indent=1, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


def _list(args, reg):
    sel = _selection(args) if _has_selection(args) else None
    rows = []
    for tool in reg:
        d = doors(tool)
        if args.door and args.door not in d:
            continue
        if args.accepts and args.accepts not in [s.get("from") for s in tool.inputs.values()]:
            continue
        row = {"id": tool.id, "title": tool.title, "kind": tool.kind, "repo": tool["repo"], "doors": d,
               "status": tool.facts.get("status"), "inputs": {n: s.get("from") for n, s in tool.inputs.items()},
               "outputs": {n: s.get("kind") for n, s in tool.outputs.items()}}
        if sel is not None:
            if tool.kind != "tool":
                continue
            try:
                bind(tool, sel)
                row["enabled"] = True
            except RegistryError as exc:
                row["enabled"], row["missing"] = False, str(exc)
        rows.append(row)
    lines = [f"{r['id']:<28} {','.join(r['doors']):<22} {r['title']}" + (
        "" if r.get("enabled", True) else f"   (disabled: {r['missing']})") for r in rows]
    if reg.problems:
        lines.append(f"{len(reg.problems)} manifest problem(s): python -m kit tools check")
    _print({"tools": rows, "skipped": reg.skip, "problems": reg.problems}, args.json, lines)
    return EXIT_OK


def cli(args, root=ROOT, env=None):
    """Run one parsed `python -m kit tools` action; returns the exit code."""
    try:
        _load_extensions()
        reg = load(root, env)
        act = args.action
        if act == "list":
            return _list(args, reg)
        if act == "check":
            problems = check(root)
            _print({"ok": not problems, "problems": problems}, args.json,
                   problems or [f"tool registry: {len(reg.tools)} manifests, no problems"])
            return EXIT_FAILED if problems else EXIT_OK
        if act == "show":
            tool = reg.get(args.id)
            doc = {"id": tool.id, "title": tool.title, "doors": doors(tool), "manifest": str(tool.path),
                   "manifest_sha256": tool.digest, "vc3d_blocked_by": vc3d_reasons(tool), **tool.m}
            _print(doc, True)
            return EXIT_OK
        if act == "availability":
            tool = reg.get(args.id)
            rows = availability(tool)
            missing = [r for r in rows if r["status"] == "missing"]
            _print({"id": tool.id, "needs": rows, "ready": not missing}, args.json,
                   [f"{r['status']:<8} {r['need']}: {r['detail']}" for r in rows] or ["nothing to check"])
            return EXIT_FAILED if missing else EXIT_OK
        if act == "selection":
            doc = _selection(args)
            if args.out:
                _atomic_write(args.out, _dump(doc))
                print(args.out)
            else:
                _print(doc, True)
            return EXIT_OK
        if act in ("plan", "run"):
            tool = reg.get(args.id)
            sel = _selection(args)
            job = prepare(tool, sel, _pairs(args.input, "--input"), _pairs(args.param, "--param"), args.purpose,
                          args.experiment, tuple(args.allow_outside), args.yes_download, root)
            if act == "plan" and args.write:
                doc = write_plan(tool, job, Path(args.write).expanduser(), _pairs(args.input, "--input"),
                                 _pairs(args.param, "--param"), args.yes_download)
                _print(doc, args.json, [f"{tool.id}: would {doc['would']}; plan written to {args.write}",
                                        f"  confirm with: {doc['confirm']}"])
                return EXIT_OK
            if act == "plan":
                doc = plan(tool, job)
                _print(doc, args.json, [f"{tool.id}: would {doc['would']}", "  " + " ".join(doc["argv"])] +
                       [f"  {x['verdict']:<8} {x['rule']}: {x['detail']}" for x in doc["gates"]])
                return EXIT_PLANNED
            res, code = run(tool, job, run_dir=args.out, fresh=args.fresh, slug=args.slug, root=root)
            _print(res, args.json, (res.get("summary") or [f"{tool.id}: {res['status']}"]) +
                   [f"  run folder: {res['run']}"] + [f"  {w}" for w in res.get("warnings", [])])
            return code
        if act == "confirm":
            res, code = confirm(reg, args.digest, args.plan, args.tool, args.out, root, slug=args.slug)
            _print(res, args.json, (res.get("summary") or [f"{res.get('tool')}: {res['status']}"]) +
                   ([f"  {res['error']}"] if res.get("error") else []) +
                   ([f"  run folder: {res['run']}"] if res.get("run") else []))
            return code
        if act == "take":
            doc = take(args.kind, Path(args.out).expanduser(), args.run or None, args.output or None)
            _print(doc, args.json, [f"{doc['kind']}: {doc['path']} (from {doc['from_run']}, output {doc['output']})"])
            return EXIT_OK
        if act == "open":
            out = open_run(args.run_dir, args.live, args.apply, args.replace_points)
            _print(out, args.json, None)
            return EXIT_FAILED if any(not a.get("ok") and not a.get("skipped") for a in out.get("applied", [])) \
                else EXIT_OK
        if act == "exec":
            words = list(args.words)
            if len(words) != 3:
                raise RegistryError("exec takes ID -- INPUT OUTPUT REVERSE (the ink command engine's {input}, "
                                    "{output} and {reverse})")
            return exec_ink(reg.get(args.id), *words, sha=args.sha256, root=root)
        if act == "export-vc3d":
            dest = Path(args.dest).expanduser()
            if args.include_private and _inside(dest, root):
                raise RegistryError("--include-private writes only to a folder outside the repositories")
            if args.check:
                diff = export_vc3d(dest, reg, args.include_private, root=root, check_only=True)
                print("\n".join(diff) if diff else f"{dest}: current")
                return EXIT_FAILED if diff else EXIT_OK
            files = export_vc3d(dest, reg, args.include_private, root=root)
            print(f"wrote {len(files)} files to {dest}; VC3D reads ~/.vc3d/plugins and each folder in "
                  "VC3D_PLUGIN_PATH")
            return EXIT_OK
        raise RegistryError(f"unknown action {act}")
    except RegistryError as exc:
        print(json.dumps({"error": str(exc), "exit": EXIT_BAD}) if getattr(args, "json", False) else
              f"tools: {exc}", file=sys.stderr)
        _refusal_record(args, exc)
        return EXIT_BAD


def _refusal_record(args, exc):
    """A run or confirm refused before it started (an input that does not bind, a bad --param) leaves its reason in
    vc3d-result.json when --out is the fresh folder VC3D's plugin host made (holding only its own plugin-run.json),
    so the person sees why in the run folder VC3D names. Any other folder is left untouched."""
    out = getattr(args, "out", None) if getattr(args, "action", None) in ("run", "confirm") else None
    if not out:
        return
    out = Path(out).expanduser()
    try:
        if not out.is_dir() or (out / "vc3d-result.json").exists() or \
                any(q.name not in HOST_FILES for q in out.iterdir()):
            return
        _write_result(out, {"schema": RESULT_SCHEMA, "tool": getattr(args, "id", None) or getattr(args, "tool", None),
                            "status": "bad", "exit": EXIT_BAD, "error": str(exc), "finished_utc": utc_now(),
                            "outputs": [], "open": [], "warnings": [], "next_steps": [], "applied": []})
    except OSError:
        pass


def main(argv=None):
    """`python -m kit tools ARGS` without the rest of kit's parser (the VC3D launcher calls this)."""
    parser = argparse.ArgumentParser(prog="python -m kit tools")
    add_arguments(parser)
    return cli(parser.parse_args(sys.argv[1:] if argv is None else argv))
