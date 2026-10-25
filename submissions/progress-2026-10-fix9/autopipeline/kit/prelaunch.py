"""Pre-launch guard for Modal runners (python -m kit.prelaunch): a launch contract check and a freeze check.

Two checks run before a Modal runner starts anything (21 Oct 2026, ideas 7 and 8 of a list of twenty agent process fixes):

Contract (idea 7). What a runner needs, read from its source with ast (it is never imported) and, when it declares
one, from its launch contract (a CONTRACT literal in the runner, a RUNNER.contract.json beside it, or --contract):

- packages: every non-standard module the runner imports at module level, inside a Modal function or under
  `with image.imports()` must be installed by its image for the default interpreter (pip_install, uv_pip_install,
  or a `pip install` in run_commands). An image this cannot see into (a registry image other than a plain OS, CUDA
  or Python one, a Dockerfile, a requirements or pyproject install, an install it cannot render) turns a gap into
  attention, never a pass; a contract's packages list, or {venv: [names]} for an install with --python, is checked
  the same way;
- inputs: each declared input exists and has its format (file, dir, json with keys, tif, npy, csv with columns,
  zarr, zarr2, zarr3), with optional sha256, min_bytes and dtype (tif, npy and Zarr headers are read, nothing else);
  an input under a declared Volume mount is checked inside the container with check_inputs(contract, where="volume");
- Volume paths: each declared Volume is opened by the runner (modal.Volume.from_name) and mounted where the contract
  says; each declared Volume path sits under a mount; every local file or folder the image adds exists;
- outputs: names are unique and each has a dtype; when the contract names a consumer (a dtypes and names dict, or
  {"runner": PATH} whose contract's accepts says what it reads), each output's dtype and name are ones it accepts.
  check_outputs (python -m kit.prelaunch outputs) reads the written files' headers after the run.

This generalizes an earlier contract check of one benchmark's runner (venv packages, map dtype, map names and
Zarr format are these checks for any runner).

No runner calls guard() or declares a contract yet (python -m kit.prelaunch audit, 21 Oct 2026): runners gain one
when next edited, never a runner a live freeze lists. Only the VC3D agent's Modal tool runs check() today.

Freeze (idea 8). The files a launch will execute are the runner and the repository modules it imports at module
level, in a Modal function or in a function one names, followed through what importing each module runs (import,
from-import, relative and sibling imports, sys.path entries the runner adds, importlib.import_module of a constant),
plus the contract's executes list (scripts it starts as subprocesses). It is a static lower bound: the in-container
check (kit.freeze.executed_check) still sees the rest. When the launch belongs to a freeze (--freeze ID, KIT_FREEZE, or
the contract's freeze), kit.freeze.launch_check must pass (every listed file unchanged; a spent freeze only from a
checkout of its freezing commit) and every executed file must be listed. A runner listed in a live freeze with no
freeze named is refused too: name the freeze, or say why this launch is not its run. A contract with freeze_required
and no freeze is refused. Code that never runs a preregistered experiment (the VC3D agent's Modal tool) passes
freeze=False. Override: --override-freeze REASON (or KIT_FREEZE_OVERRIDE) lets a refused freeze check pass only
after a line with the reason, the problems, the runner, the freeze and HEAD is appended to
docs/compute/freeze-overrides.jsonl, which is committed with the launch's ledger row. A reason needs at least 20
characters and 4 words. Contract problems have no override: fix the runner or the contract.

  python -m kit.prelaunch check RUNNER [--contract FILE] [--freeze ID|none] [--override-freeze REASON]
                                [--dry-run] [--json]                 # exit 0 pass, 1 refused, 2 bad input, 3 attention
  python -m kit.prelaunch launch RUNNER [same options] [--exec] [-- MODAL_ARGS ...]
                                                       # check, then modal run --detach (needs KIT_ALLOW_MODAL=1)
  python -m kit.prelaunch infer RUNNER [--json]        # what the guard reads from a runner
  python -m kit.prelaunch outputs RUNNER --dir DIR [--contract FILE] [--json]    # after a run: names and dtypes
  python -m kit.prelaunch audit [--json]               # every Modal runner in the repository

In a runner, call guard(__file__, CONTRACT) first in the local entrypoint; it raises LaunchRefused (a SystemExit)
with the reasons. Standard library only; kit/freeze.py (and kit/preregsets.py) are imported only for a freeze check.
"""

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "prelaunch/1"
OVERRIDE_SCHEMA = "freeze-override/1"
OVERRIDES = "docs/compute/freeze-overrides.jsonl"
DEFAULT_BRANCH = "origin/grok/laneJ-title"
EXIT_OK, EXIT_FAIL, EXIT_INPUT, EXIT_ATTENTION = 0, 1, 2, 3
DEFAULT_VENV = "default"
REASON_MIN_CHARS, REASON_MIN_WORDS = 20, 4

CONTRACT_KEYS = {"schema", "runner", "note", "inputs", "packages", "volumes", "volume_paths", "outputs", "consumer",
                 "accepts", "freeze", "freeze_required", "executes"}
INPUT_KINDS = {"file", "dir", "json", "tif", "npy", "csv", "zarr", "zarr2", "zarr3"}
INPUT_KEYS = {"path", "kind", "sha256", "min_bytes", "keys", "columns", "dtype", "note"}
DTYPES = {"bool", "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float16", "float32",
          "float64"}

# import name -> the pip names that provide it, where they differ
PROVIDERS = {
    "PIL": ("pillow",), "cv2": ("opencv-python", "opencv-python-headless", "opencv-contrib-python",
                                "opencv-contrib-python-headless"),
    "skimage": ("scikit-image",), "sklearn": ("scikit-learn",), "yaml": ("pyyaml",), "dateutil": ("python-dateutil",),
    "attr": ("attrs",), "pkg_resources": ("setuptools",), "jwt": ("pyjwt",), "OpenGL": ("pyopengl",),
    "google": ("protobuf", "google-cloud-storage", "google-auth"), "magic": ("python-magic",),
    "pytorch_lightning": ("pytorch-lightning", "lightning"), "fitz": ("pymupdf",), "SimpleITK": ("simpleitk",),
    "segmentation_models_pytorch": ("segmentation-models-pytorch",), "Bio": ("biopython",), "zmq": ("pyzmq",),
    "pydantic_core": ("pydantic",), "typing_extensions": ("typing-extensions",), "imageio_ffmpeg": ("imageio-ffmpeg",),
    "huggingface_hub": ("huggingface-hub",), "nnunetv2": ("nnunetv2",), "vesuvius": ("vesuvius",),
}
# what installing a pip name also brings (enough to keep the common stacks from reading as gaps)
BRINGS = {
    "tifffile": ("numpy",), "scipy": ("numpy",), "zarr": ("numpy", "numcodecs"), "numcodecs": ("numpy",),
    "imagecodecs": ("numpy",), "h5py": ("numpy",), "pandas": ("numpy", "python-dateutil"),
    "matplotlib": ("numpy", "pillow"), "scikit-image": ("numpy", "scipy", "pillow", "imageio", "tifffile",
                                                         "networkx"),
    "scikit-learn": ("numpy", "scipy", "joblib"), "torchvision": ("torch", "numpy", "pillow"),
    "opencv-python": ("numpy",), "opencv-python-headless": ("numpy",), "trimesh": ("numpy",),
    "numba": ("numpy", "llvmlite"), "boto3": ("botocore", "s3transfer", "jmespath"),
    "awscli": ("botocore", "pyyaml", "s3transfer"), "requests": ("urllib3", "idna", "certifi", "charset-normalizer"),
    "huggingface-hub": ("requests", "tqdm", "pyyaml", "fsspec", "filelock", "packaging"),
    "safetensors": (), "s3fs": ("fsspec", "aiobotocore", "aiohttp"), "imageio": ("numpy", "pillow"),
    "torch": ("filelock", "jinja2", "networkx", "sympy", "fsspec", "typing-extensions"),
    "einops": (), "timm": ("torch", "torchvision", "huggingface-hub", "safetensors", "pyyaml"),
    "lightning": ("torch", "pytorch-lightning", "pyyaml"), "pytorch-lightning": ("torch", "pyyaml"),
    "tensorstore": ("numpy",), "blosc2": ("numpy",), "open3d": ("numpy",), "torch-tensorrt": ("torch",),
    "nvidia-modelopt": ("torch",), "vesuvius": ("torch", "numpy", "zarr"),
}
# registry images that bring no Python packages of their own; any other registry image is opaque
PLAIN_BASES = re.compile(r"^(docker\.io/)?(library/)?(ubuntu|debian|python|alpine|nvidia/cuda|nvcr\.io/nvidia/cuda)"
                         r"([:@/]|$)", re.I)
OPAQUE_METHODS = {"pip_install_from_requirements", "pip_install_from_pyproject", "uv_sync", "from_dockerfile",
                  "dockerfile_commands", "micromamba_install", "conda_install", "from_aws_ecr", "from_gcp_artifact_registry",
                  "micromamba", "conda"}
PIP_FLAGS_WITH_VALUE = {"--python", "--index-strategy", "--extra-index-url", "--index-url", "-i", "-r", "--requirement",
                        "-c", "--constraint", "--find-links", "-f", "--target", "-t", "--prefix", "--root",
                        "--trusted-host", "--platform", "--python-version", "--only-binary", "--no-binary"}


class PrelaunchError(Exception):
    """A malformed contract, runner, freeze name or override reason (exit 2)."""


class LaunchRefused(SystemExit):
    """guard() refused a launch; the message lists every problem."""


def _norm(name):
    return re.split(r"[<>=!~\[;@ ]", name.strip().strip("'\""), maxsplit=1)[0].lower().replace("_", "-")


def _norm_dtype(text):
    """A numpy-style dtype string ("<f4", "|u1", "uint8", "float32") as a plain name, or None."""
    if text is None:
        return None
    t = str(text).strip().lower().lstrip("<>|=")
    if t in DTYPES:
        return t
    m = re.fullmatch(r"([uifb])(\d+)", t)
    if not m:
        return None
    kind, size = m.group(1), int(m.group(2))
    if kind == "b":
        return "bool" if size == 1 else None
    name = {"u": "uint", "i": "int", "f": "float"}[kind] + str(size * 8)
    return name if name in DTYPES else None


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _find_root(path):
    """The repository root above path: the first folder holding kit/ and a .git entry; ROOT otherwise."""
    p = Path(path).resolve()
    for d in [p] + list(p.parents):
        if (d / "kit" / "__init__.py").is_file() and (d / ".git").exists():
            return d
    return ROOT


def _rel(path, root):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- reading a runner (ast, never imported)

class _Eval:
    """Evaluate the simple expressions runners build paths, package lists and commands from; None when it cannot."""

    UNKNOWN = object()

    def __init__(self, runner):
        self.env = {"__file__": str(Path(runner).resolve())}

    def assign(self, tree):
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    self._bind(t, node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                self._bind(node.target, node.value)

    def _bind(self, target, value):
        if isinstance(target, ast.Name):
            v = self.value(value)
            if v is not None:
                self.env[target.id] = v
        elif isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple) and len(target.elts) == len(value.elts):
            for t, v in zip(target.elts, value.elts):
                self._bind(t, v)

    def value(self, node):  # noqa: C901 - one small interpreter
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
            return node.value
        if isinstance(node, ast.Name):
            return self.env.get(node.id)
        if isinstance(node, (ast.List, ast.Tuple)):
            out = []
            for e in node.elts:
                if isinstance(e, ast.Starred):
                    v = self.value(e.value)
                    if not isinstance(v, (list, tuple)):
                        return None
                    out += list(v)
                    continue
                v = self.value(e)
                if v is None:
                    return None
                out.append(v)
            return out
        if isinstance(node, ast.Dict):
            out = {}
            for k, v in zip(node.keys, node.values):
                kk, vv = (self.value(k) if k is not None else None), self.value(v)
                if kk is None or vv is None:
                    return None
                out[kk] = vv
            return out
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                    continue
                x = self.value(v.value)
                parts.append(str(x) if isinstance(x, (str, int, float, Path)) else "{?}")
            return "".join(parts)
        if isinstance(node, ast.BinOp):
            a, b = self.value(node.left), self.value(node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Div) and isinstance(a, Path) and isinstance(b, (str, Path)):
                return a / b
            if isinstance(node.op, ast.Add) and isinstance(a, str) and isinstance(b, str):
                return a + b
            if isinstance(node.op, ast.Add) and isinstance(a, list) and isinstance(b, list):
                return a + b
            if isinstance(node.op, ast.Mod) and isinstance(a, str):
                try:
                    return a % (tuple(b) if isinstance(b, list) else b)
                except (TypeError, ValueError):
                    return None
            return None
        if isinstance(node, ast.Subscript):
            base = self.value(node.value)
            idx = self.value(node.slice)
            if isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
                p = self.value(node.value.value)
                if isinstance(p, Path) and isinstance(idx, int) and idx < len(p.parents):
                    return p.parents[idx]
                return None
            if isinstance(base, (dict, list, tuple)) and idx is not None:
                try:
                    return base[idx]
                except (KeyError, IndexError, TypeError):
                    return None
            return None
        if isinstance(node, ast.Attribute):
            base = self.value(node.value)
            if isinstance(base, Path) and node.attr in ("parent", "name", "stem"):
                return getattr(base, node.attr)
            return None
        if isinstance(node, ast.Call):
            return self._call(node)
        return None

    def _call(self, node):
        f = node.func
        args = [self.value(a) for a in node.args]
        name = f.id if isinstance(f, ast.Name) else (
            f"{f.value.id}.{f.attr}" if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None)
        if name in ("Path", "pathlib.Path", "PurePosixPath", "pathlib.PurePosixPath") and len(args) == 1 \
                and isinstance(args[0], (str, Path)):
            return Path(args[0])
        if name == "str" and len(args) == 1 and isinstance(args[0], (str, Path, int, float)):
            return str(args[0])
        if name in ("os.fspath",) and len(args) == 1 and isinstance(args[0], (str, Path)):
            return str(args[0])
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) and isinstance(f.value.value, ast.Name) \
                and f.value.value.id == "os" and f.value.attr == "path" and all(isinstance(a, (str, Path)) for a in args):
            fn = {"dirname": os.path.dirname, "abspath": os.path.abspath, "realpath": os.path.abspath,
                  "join": os.path.join, "basename": os.path.basename}.get(f.attr)
            if fn and args:
                return fn(*[str(a) for a in args])
            return None
        if isinstance(f, ast.Attribute):
            base = self.value(f.value)
            if isinstance(base, Path) and f.attr in ("resolve", "absolute", "expanduser") and not args:
                return base
            if isinstance(base, Path) and f.attr == "joinpath" and all(isinstance(a, (str, Path)) for a in args):
                return base.joinpath(*args)
            if isinstance(base, str) and f.attr == "join" and len(args) == 1 and isinstance(args[0], (list, tuple)) \
                    and all(isinstance(a, str) for a in args[0]):
                return base.join(args[0])
            if isinstance(base, str) and f.attr == "format":
                try:
                    return base.format(*args, **{k.arg: self.value(k.value) for k in node.keywords if k.arg})
                except (IndexError, KeyError, ValueError):
                    return None
        return None


def _decorator_text(fn):
    return " ".join(ast.unparse(d) for d in fn.decorator_list) if hasattr(ast, "unparse") else ""


def _is_remote(fn):
    text = _decorator_text(fn)
    return bool(re.search(r"\.(function|cls|method|enter|exit|asgi_app|wsgi_app|web_endpoint|fastapi_endpoint|"
                          r"batched|concurrent)\b", text))


def _catches_import_error(try_node):
    for h in try_node.handlers:
        names = [] if h.type is None else [ast.unparse(e) for e in (h.type.elts if isinstance(h.type, ast.Tuple)
                                                                     else [h.type])]
        if h.type is None or any(n.split(".")[-1] in ("ImportError", "ModuleNotFoundError", "Exception",
                                                      "BaseException") for n in names):
            return True
    return False


def _remote_reachable(tree):
    """Names of the functions a Modal function can reach in this file: those named (called or passed on) inside a
    remote function's body, and so on transitively. Their imports run in the container."""
    funcs, roots = {}, []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(n.name, []).append(n)
            if _is_remote(n):
                roots.append(n)
        elif isinstance(n, ast.ClassDef) and _is_remote(n):
            roots += [b for b in n.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))]
    seen, todo = set(), list(roots)
    while todo:
        fn = todo.pop()
        for x in ast.walk(fn):
            if isinstance(x, ast.Name) and x.id in funcs and x.id not in seen:
                seen.add(x.id)
                todo += funcs[x.id]
    return seen


def _imports(tree, text="", reach=()):
    """(module, scope, lineno, level, names) for every import statement, and importlib.import_module of a constant:
    scope module, remote (a Modal function or class, a function one can reach (reach), or `with image.imports()`),
    local (any other function) or optional (inside a try that catches ImportError). Only statements are walked, so
    a large module stays cheap."""
    out = []

    def stmts(nodes, scope, optional):
        for n in nodes:
            sc = "optional" if optional else scope
            if isinstance(n, ast.Import):
                out.extend((a.name, sc, n.lineno, 0, ()) for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                out.append((n.module or "", sc, n.lineno, n.level, tuple(a.name for a in n.names)))
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stmts(n.body, "remote" if scope == "remote" or n.name in reach or _is_remote(n) else "local", False)
            elif isinstance(n, ast.ClassDef):
                stmts(n.body, "remote" if _is_remote(n) else scope, optional)
            elif isinstance(n, ast.Try) or type(n).__name__ == "TryStar":
                stmts(n.body, scope, optional or _catches_import_error(n))
                for h in n.handlers:
                    stmts(h.body, scope, optional)
                stmts(n.orelse, scope, optional)
                stmts(n.finalbody, scope, optional)
            elif isinstance(n, ast.If):
                if any(getattr(x, "id", getattr(x, "attr", None)) == "TYPE_CHECKING" for x in ast.walk(n.test)):
                    continue
                stmts(n.body, scope, optional)
                stmts(n.orelse, scope, optional)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                remote = any(isinstance(i.context_expr, ast.Call) and isinstance(i.context_expr.func, ast.Attribute)
                             and i.context_expr.func.attr == "imports" for i in n.items)
                stmts(n.body, "remote" if remote else scope, optional)
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.While)):
                stmts(n.body, scope, optional)
                stmts(n.orelse, scope, optional)
            elif type(n).__name__ == "Match":
                for case in n.cases:
                    stmts(case.body, scope, optional)

    stmts(tree.body, "module", False)
    for m in re.finditer(r"import_module\(\s*[\"']([A-Za-z_][\w.]*)[\"']", text):
        out.append((m.group(1), "local", text.count("\n", 0, m.start()) + 1, 0, ()))
    return out


def _pip_tokens(command):
    """Each `pip install` in a shell command as (venv, [packages], opaque)."""
    out = []
    for m in re.finditer(r"(?:^|[\s;&|(])(?:uv\s+pip|pip3?|python3?(?:\.\d+)?\s+-m\s+pip|\S*/pip3?|\S*/python3?\S*\s+-m"
                         r"\s+pip)\s+install\b(.*?)(?=&&|\|\||;|$)", command, flags=re.S):
        toks = m.group(1).split()
        venv, pkgs, opaque, i = DEFAULT_VENV, [], False, 0
        while i < len(toks):
            t = toks[i]
            if t in PIP_FLAGS_WITH_VALUE:
                if t == "--python" and i + 1 < len(toks):
                    v = toks[i + 1]
                    venv = str(Path(v).parent.parent) if "/bin/" in v else v
                if t in ("-r", "--requirement", "--target", "-t", "--prefix"):
                    opaque = True
                i += 2
                continue
            if t in ("--system",):
                i += 1
                continue
            if t in ("-e", "--editable"):
                opaque = True
                i += 2
                continue
            if t.startswith("-"):
                i += 1
                continue
            if "{?}" in t or "/" in t or t.startswith(".") or t.startswith("git+") or "://" in t:
                opaque = True
            else:
                pkgs.append(_norm(t))
            i += 1
        out.append((venv, [p for p in pkgs if p], opaque))
    return out


def infer(runner, root=None):
    """What a launch of this runner needs, read from its source: images (packages per interpreter, opaque or not),
    Volumes and mounts, local files the image adds, imports by scope, the repository files it executes, its contract
    (a CONTRACT literal, or RUNNER.contract.json beside it) and whether it calls guard()."""
    runner = Path(runner)
    root = Path(root) if root else _find_root(runner)
    try:
        text = runner.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(runner))
    except (OSError, SyntaxError, UnicodeDecodeError) as e:
        raise PrelaunchError(f"{runner}: cannot read the runner ({e})")
    ev = _Eval(runner)
    ev.assign(tree)
    nodes = list(ast.walk(tree))
    venvs, opaque, bases, adds, volumes, mounts, unresolved = {}, [], [], [], {}, {}, 0
    var_volume = {}
    for node in nodes:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            vname = _volume_name(node.value, ev)
            if vname:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        var_volume[t.id] = vname
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        vname = _volume_name(node, ev)
        if vname:
            volumes.setdefault(vname, node.lineno)
        for kw in node.keywords:
            if kw.arg == "volumes" and isinstance(kw.value, ast.Dict):
                for k, v in zip(kw.value.keys, kw.value.values):
                    mount = ev.value(k) if k is not None else None
                    name = var_volume.get(v.id) if isinstance(v, ast.Name) else _volume_name(v, ev)
                    if isinstance(mount, (str, Path)) and name:
                        mounts[str(mount)] = name
        f = node.func
        if not isinstance(f, ast.Attribute):
            continue
        meth = f.attr
        if meth in ("pip_install", "uv_pip_install"):
            names, opq = [], False
            for a in node.args:
                v = ev.value(a.value if isinstance(a, ast.Starred) else a)
                if isinstance(v, str):
                    names.append(v)
                elif isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v):
                    names += list(v)
                else:
                    opq = True
            for n in names:
                if "/" in n or n.startswith("git+") or "://" in n or n.startswith("."):
                    opq = True
                else:
                    venvs.setdefault(DEFAULT_VENV, set()).add(_norm(n))
            if opq:
                opaque.append(f"line {node.lineno}: {meth} with a package this cannot read")
        elif meth == "run_commands":
            for a in node.args:
                v = ev.value(a.value if isinstance(a, ast.Starred) else a)
                cmds = [v] if isinstance(v, str) else (list(v) if isinstance(v, (list, tuple)) else None)
                if cmds is None or not all(isinstance(c, str) for c in cmds):
                    opaque.append(f"line {node.lineno}: run_commands with a command this cannot render")
                    continue
                for c in cmds:
                    for venv, pkgs, opq in _pip_tokens(c):
                        venvs.setdefault(venv, set()).update(pkgs)
                        if opq:
                            opaque.append(f"line {node.lineno}: a pip install this cannot read in full ({venv})")
        elif meth == "apt_install":
            for a in node.args:
                v = ev.value(a.value if isinstance(a, ast.Starred) else a)
                for n in ([v] if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []):
                    if isinstance(n, str) and n.startswith("python3-"):
                        venvs.setdefault(DEFAULT_VENV, set()).add(_norm(n[len("python3-"):]))
        elif meth in OPAQUE_METHODS:
            opaque.append(f"line {node.lineno}: {meth}")
        elif meth == "from_registry":
            tag = ev.value(node.args[0]) if node.args else None
            bases.append(tag or "?")
            if not (isinstance(tag, str) and PLAIN_BASES.match(tag)):
                opaque.append(f"line {node.lineno}: registry image {tag or '(unrendered)'} may bring its own packages")
        elif meth in ("add_local_file", "add_local_dir", "copy_local_file", "copy_local_dir"):
            src = ev.value(node.args[0]) if node.args else None
            dst = ev.value(node.args[1]) if len(node.args) > 1 else None
            if isinstance(src, (str, Path)):
                p = Path(src)
                if not p.is_absolute():
                    p = (runner.parent / p) if not (root / p).exists() else root / p
                adds.append({"kind": "dir" if meth.endswith("dir") else "file", "src": _rel(p, root),
                             "abs": str(p), "dst": str(dst) if dst is not None else None, "line": node.lineno})
            else:
                unresolved += 1
        elif meth == "add_local_python_source":
            for a in node.args:
                v = ev.value(a)
                if isinstance(v, str):
                    adds.append({"kind": "python_source", "src": v, "abs": None, "dst": None, "line": node.lineno})
    imports = _imports(tree, text, _remote_reachable(tree))
    contract, contract_from = _declared_contract(tree, runner)
    entries, path_unknown = _sys_path_entries(nodes, ev)
    path_bases, provided, runtime_paths = [], set(), []
    root_r = root.resolve()
    for e in entries + ["/root"]:
        pe = Path(e)
        if pe.is_absolute() and str(pe.resolve()).startswith(str(root_r) + os.sep) and pe.is_dir():
            path_bases.append(pe.resolve())
            continue
        mapped = False
        for a in adds:
            dst = (a.get("dst") or "").rstrip("/")
            if not dst or "{?}" in dst:
                continue
            if a["kind"] == "dir" and a["abs"] and (e == dst or e.startswith(dst + "/")):
                local = Path(a["abs"]) / e[len(dst):].lstrip("/")
                if local.is_dir():
                    path_bases.append(local.resolve())
                    mapped = True
            elif a["kind"] == "file" and str(Path(dst).parent) == e.rstrip("/"):
                provided.add(Path(dst).stem)
                mapped = True
        if not mapped and e != "/root" and not (pe.is_absolute() and str(pe).startswith(str(root_r))):
            runtime_paths.append(e)   # filled at run time (a download, a clone, a Volume): cannot be seen here
    for a in adds:
        if a["kind"] == "dir" and a.get("dst") and "{?}" not in a["dst"]:
            provided.add(Path(a["dst"].rstrip("/")).name)   # a folder added as /x/pkg is importable as pkg from /x
        if a["kind"] == "python_source":
            provided.add(a["src"].split(".")[0])
    closure = executed_files(runner, root, bases=path_bases)
    return {"runner": _rel(runner, root), "root": str(root),
            "venvs": {k: sorted(v) for k, v in sorted(venvs.items())}, "opaque": opaque, "bases": bases,
            "volumes": sorted(volumes), "mounts": dict(sorted(mounts.items())), "adds": adds,
            "unresolved_adds": unresolved, "path_bases": sorted({_rel(b, root) for b in path_bases}),
            "path_entries": entries, "path_unknown": path_unknown + len(runtime_paths), "provided": sorted(provided),
            "git_clone": bool(re.search(r"\bgit\s+clone\b", text)),
            "imports": [{"module": m, "scope": s, "line": ln, "level": lv} for m, s, ln, lv, _ in imports],
            "executes": closure, "contract": contract, "contract_from": contract_from,
            "calls_guard": bool(re.search(r"\bprelaunch\b.*\bguard\b|\bfrom\s+kit\.prelaunch\s+import\b.*\bguard\b",
                                          text))}


def _sys_path_entries(nodes, ev):
    """Values given to sys.path.insert or sys.path.append anywhere in the runner, as strings (a loop variable over a
    literal list gives each item), and how many could not be read."""
    loops = {}
    for n in nodes:
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name):
            v = ev.value(n.iter)
            if isinstance(v, (list, tuple)):
                loops[n.target.id] = list(v)
    out, unknown = [], 0
    for n in nodes:
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("insert", "append")
                and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "path"
                and isinstance(n.func.value.value, ast.Name) and n.func.value.value.id == "sys" and n.args):
            continue
        arg = n.args[-1]
        v = ev.value(arg)
        if isinstance(v, (str, Path)):
            out.append(str(v))
            continue
        inner = arg.args[0] if isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "str" and arg.args else arg
        if isinstance(inner, ast.Name) and inner.id in loops:
            out += [str(x) for x in loops[inner.id] if isinstance(x, (str, Path))]
        else:
            unknown += 1
    return out, unknown


def _volume_name(call, ev):
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != "from_name":
        return None
    owner = call.func.value
    owner_name = owner.attr if isinstance(owner, ast.Attribute) else owner.id if isinstance(owner, ast.Name) else ""
    if owner_name not in ("Volume", "NetworkFileSystem", "CloudBucketMount"):
        return None
    v = ev.value(call.args[0]) if call.args else None
    return v if isinstance(v, str) else None


def _declared_contract(tree, runner):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CONTRACT" for t in node.targets):
            try:
                return ast.literal_eval(node.value), f"{Path(runner).name}: CONTRACT (line {node.lineno})"
            except (ValueError, SyntaxError) as e:
                raise PrelaunchError(f"{runner}: CONTRACT must be a literal ({e})")
    side = Path(runner).with_suffix(".contract.json")
    if side.is_file():
        try:
            return json.loads(side.read_text(encoding="utf-8")), side.name
        except json.JSONDecodeError as e:
            raise PrelaunchError(f"{side}: not JSON ({e})")
    return None, None


# ---------------------------------------------------------------- the files a launch executes (static import closure)

def _module_file(root, dotted):
    """root/a/b.py or root/a/b/__init__.py for a dotted name, with the package __init__ files on the way."""
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return None, []
    inits = [root.joinpath(*parts[:i], "__init__.py") for i in range(1, len(parts))]
    inits = [p for p in inits if p.is_file()]
    for cand in (root.joinpath(*parts).with_suffix(".py"), root.joinpath(*parts, "__init__.py")):
        if cand.is_file():
            return cand, inits
    return None, inits


_IMPORTS_CACHE = {}


def _runner_imports(path):
    text = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    return _imports(tree, text, _remote_reachable(tree))


def _file_imports(path):
    try:
        key = (str(path), Path(path).stat().st_mtime_ns)
        if key not in _IMPORTS_CACHE:
            text = Path(path).read_text(encoding="utf-8")
            _IMPORTS_CACHE[key] = _imports(ast.parse(text, filename=str(path)), text)
        return _IMPORTS_CACHE[key]
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []


def executed_files(runner, root=None, extra=(), bases=()):
    """The repository files a launch of runner executes in its container as far as its imports show, as sorted
    repository paths: the runner; the repository modules it imports at module level, in a Modal function or in a
    function one names; and, through each imported module, what importing it runs (its module-level imports). An
    import inside a function of an imported module runs only if that function is called, and a script started as a
    subprocess is not an import, so both are left to the in-container check (kit.freeze.executed_check and
    run_script) and the contract's executes list; the runner's launch-side functions run on the laptop. Imports resolve against
    the root, the runner's folder (first on sys.path when Modal runs the script), the sys.path entries the runner
    adds (bases) and, for relative imports, each module's package. Dynamic loading this cannot see belongs in the
    contract's executes list (extra)."""
    runner = Path(runner).resolve()
    root = Path(root).resolve() if root else _find_root(runner)
    seen, todo = set(), [runner] + [root / e for e in extra]
    script_dir = runner.parent
    more = [Path(b) for b in bases]
    while todo:
        f = todo.pop()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        if f.suffix != ".py":
            continue
        pkg_dir = f.parent
        found = _runner_imports(f) if f == runner else _file_imports(f)
        for module, scope, _ln, level, names in found:
            if scope == "local" or (f != runner and scope == "remote"):
                continue
            bases = []
            if level:
                base = pkg_dir
                for _ in range(level - 1):
                    base = base.parent
                bases = [(base, module)]
            else:
                bases = [(root, module), (script_dir, module)] + [(b, module) for b in more]
                if pkg_dir != script_dir and not (pkg_dir / "__init__.py").is_file():
                    bases.append((pkg_dir, module))
            for base, mod in bases:
                hit, inits = _module_file(base, mod) if mod else (None, [])
                if mod and hit is None and not inits:
                    continue
                todo += inits
                if hit is not None:
                    todo.append(hit)
                for n in names:   # from a.b import c, where c is a submodule
                    sub, _ = _module_file(base, f"{mod}.{n}" if mod else n)
                    if sub is not None:
                        todo.append(sub)
                if hit is not None or inits:
                    break
    return sorted(_rel(p, root) for p in seen if str(p).startswith(str(root) + os.sep))


# ---------------------------------------------------------------- contracts

def validate_contract(c, where="contract"):
    """Raise PrelaunchError unless c is a well-formed prelaunch/1 contract; returns it."""
    if not isinstance(c, dict):
        raise PrelaunchError(f"{where}: a contract is a JSON object")
    if c.get("schema") != SCHEMA:
        raise PrelaunchError(f"{where}: schema must be {SCHEMA!r}")
    unknown = set(c) - CONTRACT_KEYS
    if unknown:
        raise PrelaunchError(f"{where}: unknown keys {sorted(unknown)} (known: {sorted(CONTRACT_KEYS)})")
    for i, inp in enumerate(c.get("inputs") or []):
        if not isinstance(inp, dict) or not isinstance(inp.get("path"), str) or inp.get("kind") not in INPUT_KINDS:
            raise PrelaunchError(f"{where}: inputs[{i}] needs a path and a kind in {sorted(INPUT_KINDS)}")
        if set(inp) - INPUT_KEYS:
            raise PrelaunchError(f"{where}: inputs[{i}] has unknown keys {sorted(set(inp) - INPUT_KEYS)}")
        if inp.get("dtype") is not None and _norm_dtype(inp["dtype"]) is None:
            raise PrelaunchError(f"{where}: inputs[{i}] dtype {inp['dtype']!r} is not one of {sorted(DTYPES)}")
    pk = c.get("packages")
    if pk is not None and not (isinstance(pk, list) and all(isinstance(x, str) for x in pk)) and not (
            isinstance(pk, dict) and all(isinstance(v, list) for v in pk.values())):
        raise PrelaunchError(f"{where}: packages is a list of pip names, or {{venv: [names]}}")
    vols = c.get("volumes")
    if vols is not None and not (isinstance(vols, dict) and all(isinstance(v, str) for v in vols.values())):
        raise PrelaunchError(f"{where}: volumes is {{volume name: mount path}}")
    for i, o in enumerate(c.get("outputs") or []):
        if not isinstance(o, dict) or not isinstance(o.get("name"), str):
            raise PrelaunchError(f"{where}: outputs[{i}] needs a name")
    for key in ("consumer", "accepts"):
        if c.get(key) is not None and not isinstance(c[key], dict):
            raise PrelaunchError(f"{where}: {key} is an object")
    if c.get("freeze") is not None and not isinstance(c["freeze"], str):
        raise PrelaunchError(f"{where}: freeze is a freeze id (python -m kit freeze list)")
    for key in ("executes", "volume_paths"):
        if c.get(key) is not None and not (isinstance(c[key], list) and all(isinstance(x, str) for x in c[key])):
            raise PrelaunchError(f"{where}: {key} is a list of paths")
    return c


def _installed(venvs, venv=DEFAULT_VENV):
    have = set(venvs.get(venv, ()))
    todo = list(have)
    while todo:
        for b in BRINGS.get(todo.pop(), ()):
            if b not in have:
                have.add(b)
                todo.append(b)
    return have


def _stdlib():
    names = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    return names | {"__future__", "modal", "_typeshed"}


def _provided(module, have):
    top = module.split(".")[0]
    cands = PROVIDERS.get(top, ()) + (_norm(top),)
    return any(c in have for c in cands)


def _repo_module(root, runner, module, bases=()):
    top = module.split(".")[0]
    for base in [Path(root), Path(runner).resolve().parent] + [Path(root) / b for b in bases]:
        if (base / f"{top}.py").is_file() or (base / top / "__init__.py").is_file() or (
                (base / top).is_dir() and any((base / top).glob("*.py"))):   # a namespace package
            return True
    return False


def _problem(check, detail):
    return {"check": check, "detail": detail}


def check_static(info, contract=None):
    """Contract problems and attention a launch would meet, from the runner's source and its contract (no files
    are read except the local sources the image adds and a consumer runner's contract)."""
    problems, attention, notes = [], [], []
    root, runner = Path(info["root"]), Path(info["root"]) / info["runner"]
    stdlib = _stdlib()
    have = _installed(info["venvs"])
    opaque = bool(info["opaque"])
    for imp in info["imports"]:
        mod = imp["module"]
        if imp["level"] or imp["scope"] not in ("module", "remote") or not mod:
            continue
        top = mod.split(".")[0]
        if top in stdlib or top in info.get("provided", ()) or _provided(mod, have) or _repo_module(
                root, runner, mod, info.get("path_bases", ())):
            continue
        what = (f"line {imp['line']}: imports {top} ({imp['scope']} scope), which the image does not install for "
                "its default interpreter")
        if opaque:
            attention.append(_problem("package-unverified", what + f"; the image is opaque here "
                                      f"({info['opaque'][0]}), so this cannot be confirmed"))
        elif info.get("git_clone") or info.get("path_unknown"):
            attention.append(_problem("package-unverified", what + "; the image clones a git repository, or the "
                                      "runner adds a sys.path entry this cannot read or one filled at run time, any of "
                                      "which may provide it"))
        else:
            problems.append(_problem("missing-package", what))
    for a in info["adds"]:
        if a["abs"] and not Path(a["abs"]).exists():
            problems.append(_problem("missing-local-source", f"line {a['line']}: the image adds {a['src']}, which "
                                     "does not exist"))
    if info.get("unresolved_adds"):
        notes.append(f"{info['unresolved_adds']} local add(s) whose source path this cannot render were not checked")
    if contract is None:
        notes.append("no launch contract declared: packages and local sources were checked from the source only")
        return problems, attention, notes
    pk = contract.get("packages") or []
    want = {DEFAULT_VENV: pk} if isinstance(pk, list) else pk
    for venv, names in want.items():
        got = _installed(info["venvs"], venv)
        missing = [n for n in names if _norm(n) not in got]
        if missing:
            what = f"the contract needs {missing} in {venv}; the image installs {sorted(info['venvs'].get(venv, []))}"
            (attention if opaque else problems).append(_problem("contract-package" if not opaque
                                                                else "package-unverified", what))
    for name, mount in (contract.get("volumes") or {}).items():
        if name not in info["volumes"]:
            problems.append(_problem("volume", f"the contract names Volume {name!r}; the runner opens "
                                     f"{info['volumes'] or 'none'}"))
        elif info["mounts"].get(mount) != name:
            where = [m for m, n in info["mounts"].items() if n == name]
            problems.append(_problem("volume-mount", f"the contract mounts {name!r} at {mount}; the runner mounts it "
                                     f"at {where or 'no path this can read'}"))
    mounts = set((contract.get("volumes") or {}).values()) | set(info["mounts"])
    for p in contract.get("volume_paths") or []:
        if not any(p == m or p.startswith(m.rstrip("/") + "/") for m in mounts):
            problems.append(_problem("volume-path", f"{p} is under no Volume mount ({sorted(mounts) or 'none'})"))
    for inp in contract.get("inputs") or []:
        if inp["path"].startswith("/") and not any(inp["path"].startswith(m.rstrip("/") + "/") for m in mounts):
            problems.append(_problem("input-path", f"input {inp['path']} is absolute but under no Volume mount"))
    names = [o["name"] for o in contract.get("outputs") or []]
    for n in sorted({n for n in names if names.count(n) > 1}):
        problems.append(_problem("output-name", f"output {n} is declared twice"))
    for o in contract.get("outputs") or []:
        if o.get("dtype") is not None and _norm_dtype(o["dtype"]) is None:
            problems.append(_problem("output-dtype", f"output {o['name']}: dtype {o['dtype']!r} is not a dtype"))
    consumer = contract.get("consumer")
    if consumer:
        acc, label = _accepts(consumer, root)
        for o in contract.get("outputs") or []:
            dt = _norm_dtype(o.get("dtype"))
            if acc.get("dtypes") and dt not in {_norm_dtype(x) for x in acc["dtypes"]}:
                problems.append(_problem("consumer-dtype", f"output {o['name']} is {dt}; {label} accepts "
                                         f"{acc['dtypes']}"))
            if acc.get("names") and not any(fnmatch.fnmatch(o["name"], pat) for pat in acc["names"]):
                problems.append(_problem("consumer-name", f"output {o['name']}; {label} reads {acc['names']}"))
    return problems, attention, notes


def _accepts(consumer, root):
    if "runner" in consumer:
        path = Path(root) / consumer["runner"]
        c, _ = _declared_contract(ast.parse(path.read_text(encoding="utf-8")), path)
        if not c or not isinstance(c.get("accepts"), dict):
            raise PrelaunchError(f"consumer {consumer['runner']} declares no accepts in its contract")
        return c["accepts"], consumer["runner"]
    return consumer, "the consumer"


# ---------------------------------------------------------------- file headers (inputs before, outputs after)

def _tif_dtype(path):
    """The first image's dtype from a TIFF header (classic or BigTIFF), or None when it is not a TIFF."""
    with open(path, "rb") as fh:
        head = fh.read(16)
        if len(head) < 8 or head[:2] not in (b"II", b"MM"):
            return None
        e = "<" if head[:2] == b"II" else ">"
        magic = struct.unpack(e + "H", head[2:4])[0]
        if magic == 42:
            off, cnt_fmt, ent, val_size = struct.unpack(e + "I", head[4:8])[0], "H", 12, 4
        elif magic == 43:
            off, cnt_fmt, ent, val_size = struct.unpack(e + "Q", head[8:16])[0], "Q", 20, 8
        else:
            return None
        fh.seek(off)
        n = struct.unpack(e + cnt_fmt, fh.read(struct.calcsize(cnt_fmt)))[0]
        tags = {}
        for _ in range(min(n, 4096)):
            raw = fh.read(ent)
            if len(raw) < ent:
                break
            tag, typ = struct.unpack(e + "HH", raw[:4])
            if tag in (258, 339):
                size = {3: 2, 4: 4, 1: 1}.get(typ, 2)
                fmt = {3: "H", 4: "I", 1: "B"}.get(typ, "H")
                count = struct.unpack(e + ("I" if ent == 12 else "Q"), raw[4:4 + (4 if ent == 12 else 8)])[0]
                val = raw[4 + (4 if ent == 12 else 8):]
                if count * size > val_size:
                    pos = fh.tell()
                    fh.seek(struct.unpack(e + ("I" if ent == 12 else "Q"), val)[0])
                    val = fh.read(size)
                    fh.seek(pos)
                tags[tag] = struct.unpack(e + fmt, val[:size])[0]
    bits, fmt = tags.get(258, 1), tags.get(339, 1)
    if bits == 1:
        return "bool"
    return _norm_dtype({1: "uint", 2: "int", 3: "float"}.get(fmt, "uint") + str(bits))


def _npy_dtype(path):
    with open(path, "rb") as fh:
        head = fh.read(10)
        if head[:6] != b"\x93NUMPY":
            return None
        major = head[6]
        if major == 1:
            n = struct.unpack("<H", head[8:10])[0]
        else:
            n = struct.unpack("<I", head[8:10] + fh.read(2))[0]
        text = fh.read(n).decode("latin1")
    m = re.search(r"'descr':\s*'([^']+)'", text)
    return _norm_dtype(m.group(1)) if m else None


def _zarr_info(path):
    """(format, dtype) of a Zarr store or array: 2 with .zarray or .zgroup, 3 with zarr.json; dtype from the array's
    metadata (or its first array child, for a group)."""
    p = Path(path)
    if (p / ".zarray").is_file():
        return 2, _norm_dtype(json.loads((p / ".zarray").read_text()).get("dtype"))
    if (p / ".zgroup").is_file():
        for child in sorted(p.iterdir()):
            if (child / ".zarray").is_file():
                return 2, _zarr_info(child)[1]
        return 2, None
    if (p / "zarr.json").is_file():
        meta = json.loads((p / "zarr.json").read_text())
        if meta.get("node_type") == "array":
            return 3, _norm_dtype(meta.get("data_type"))
        for child in sorted(x for x in p.iterdir() if x.is_dir()):
            if (child / "zarr.json").is_file():
                return 3, _zarr_info(child)[1]
        return 3, None
    return None, None


def _file_dtype(path):
    p = Path(path)
    if p.is_dir():
        return _zarr_info(p)[1]
    if p.suffix.lower() in (".tif", ".tiff"):
        return _tif_dtype(p)
    if p.suffix.lower() == ".npy":
        return _npy_dtype(p)
    return None


def check_inputs(contract, base=None, where="local"):
    """Problems with a contract's inputs: where local, the relative paths (against base, the repository root by
    default); where volume, the absolute paths (inside the container, after the Volume is mounted). Returns
    (problems, notes)."""
    base = Path(base) if base else ROOT
    problems, notes = [], []
    for inp in contract.get("inputs") or []:
        path, kind = inp["path"], inp["kind"]
        on_volume = path.startswith("/")
        if (where == "local") == on_volume:
            if where == "local":
                notes.append(f"{path}: a Volume input, checked in the container (check_inputs(contract, "
                             "where='volume'))")
            continue
        p = Path(path) if on_volume else base / path
        bad = lambda d: problems.append(_problem(f"input-{kind}", f"{path}: {d}"))  # noqa: E731
        if not p.exists():
            bad("missing")
            continue
        if kind in ("dir", "zarr", "zarr2", "zarr3") and not p.is_dir():
            bad("is not a folder")
            continue
        if kind not in ("dir", "zarr", "zarr2", "zarr3") and not p.is_file():
            bad("is not a file")
            continue
        if inp.get("min_bytes") and p.is_file() and p.stat().st_size < inp["min_bytes"]:
            bad(f"{p.stat().st_size} bytes, under min_bytes {inp['min_bytes']}")
        if inp.get("sha256") and p.is_file() and _sha256_file(p) != inp["sha256"]:
            bad(f"sha256 {_sha256_file(p)[:12]} is not the contract's {inp['sha256'][:12]}")
        got_dtype = None
        if kind == "json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                bad(f"not JSON ({e})")
                continue
            missing = [k for k in inp.get("keys") or [] if not isinstance(data, dict) or k not in data]
            if missing:
                bad(f"has no key(s) {missing}")
        elif kind == "csv":
            with open(p, encoding="utf-8", errors="replace") as fh:
                header = [h.strip() for h in fh.readline().rstrip("\n").split(",")]
            missing = [c for c in inp.get("columns") or [] if c not in header]
            if missing:
                bad(f"has no column(s) {missing}")
        elif kind == "tif":
            got_dtype = _tif_dtype(p)
            if got_dtype is None:
                bad("is not a TIFF")
        elif kind == "npy":
            got_dtype = _npy_dtype(p)
            if got_dtype is None:
                bad("is not a .npy file")
        elif kind.startswith("zarr"):
            fmt, got_dtype = _zarr_info(p)
            if fmt is None:
                bad("is not a Zarr store (no .zarray, .zgroup or zarr.json)")
            elif kind in ("zarr2", "zarr3") and fmt != int(kind[-1]):
                bad(f"is Zarr format {fmt}; the contract says format {kind[-1]}")
        if inp.get("dtype") and got_dtype is not None and got_dtype != _norm_dtype(inp["dtype"]):
            bad(f"dtype {got_dtype}; the contract says {_norm_dtype(inp['dtype'])}")
    return problems, notes


def check_outputs(contract, folder):
    """After a run: each declared output is present under folder (a name may be a glob) with its declared dtype,
    read from the file's header (tif, npy, Zarr). Returns (problems, rows)."""
    problems, rows = [], []
    folder = Path(folder)
    for o in contract.get("outputs") or []:
        hits = sorted(folder.glob(o["name"])) if any(ch in o["name"] for ch in "*?[") else (
            [folder / o["name"]] if (folder / o["name"]).exists() else [])
        if not hits:
            problems.append(_problem("output-missing", f"{o['name']} is not under {folder}"))
            rows.append({"name": o["name"], "path": None, "dtype": None, "status": "missing"})
            continue
        for h in hits:
            got = _file_dtype(h)
            want = _norm_dtype(o.get("dtype"))
            status = "ok"
            if want and got is None:
                status = "unreadable"
                problems.append(_problem("output-dtype", f"{_rel(h, folder)}: its dtype cannot be read from the "
                                         "header (tif, npy or Zarr only)"))
            elif want and got != want:
                status = "dtype"
                problems.append(_problem("output-dtype", f"{_rel(h, folder)} is {got}; the contract says {want}"))
            rows.append({"name": o["name"], "path": _rel(h, folder), "dtype": got, "status": status})
    return problems, rows


# ---------------------------------------------------------------- freeze check

def _git_head(root):
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _find_entry(fz, data, root, fid):
    try:
        return fz.find(data, fid)
    except fz.FreezeError:
        pass
    try:   # a rerun of a spent freeze launches from git worktree add DIR COMMIT, whose registry predates the entry
        return fz.find(fz.load(root, rev=DEFAULT_BRANCH), fid)
    except Exception:  # noqa: BLE001 - the branch may be absent from this clone
        raise PrelaunchError(f"freeze {fid!r} is not in a note of the source repository (python -m kit freeze list)")


def freeze_check(runner, root=None, freeze=None, contract=None, data=None):
    """The freeze half of the guard, without overrides: a dict with problems, notes, the freeze id (or None) and
    the executed files. freeze is an id, "none" or False (no freeze applies), or None (the contract's freeze, else
    whatever live freeze lists the runner)."""
    runner = Path(runner)
    root = Path(root) if root else _find_root(runner)
    contract = contract or {}
    rel = _rel(runner, root)
    executes = executed_files(runner, root, extra=contract.get("executes") or ())
    out = {"freeze": None, "problems": [], "notes": [], "executes": executes, "listed_in": []}
    if freeze is False:
        out["notes"].append("freeze check off: this launch path never runs a preregistered experiment")
        return out
    from . import freeze as fz

    data = fz.load(root) if data is None else data
    live = [e for e in data["freezes"] if e["state"] == "live" and rel in (e.get("files") or {})]
    out["listed_in"] = [e["id"] for e in live]
    fid = freeze if freeze not in (None, "") else contract.get("freeze")
    if fid in ("none", None):
        if live:   # --freeze none alone would let a frozen run launch unchecked, so it needs a recorded reason too
            out["problems"].append(_problem("freeze-unnamed", f"{rel} is listed in live freeze(s) "
                                            f"{out['listed_in']}: name the freeze (--freeze ID) when this launch is "
                                            "its run, or give --override-freeze REASON saying why it is not"))
        elif contract.get("freeze_required"):
            out["problems"].append(_problem("freeze-required", "the contract says freeze_required, and no freeze is "
                                            "named"))
        else:
            out["notes"].append("no freeze applies to this launch" + (" (--freeze none)" if fid == "none" else ""))
        return out
    entry = _find_entry(fz, data, root, fid)
    out["freeze"] = fid
    try:
        n = fz.launch_check(entry, root)
        out["notes"].append(f"freeze {fid}: {n} listed file(s) match {entry['freezing_commit'][:12]}")
    except fz.FreezeRefused as e:
        out["problems"].append(_problem("freeze-files", str(e)))
    listed = set(entry.get("files") or {})
    if listed:
        unlisted = [p for p in executes if p not in listed]
        if unlisted:
            out["problems"].append(_problem("freeze-unlisted", f"the launch would execute {unlisted}, which freeze "
                                            f"{fid} does not list: list them, amend the preregistration and freeze "
                                            "again (docs/AI-AGENTS.md rule 14)"))
    return out


def _valid_reason(reason):
    r = (reason or "").strip()
    if len(r) < REASON_MIN_CHARS or len(r.split()) < REASON_MIN_WORDS:
        raise PrelaunchError(f"an override reason needs at least {REASON_MIN_CHARS} characters and "
                             f"{REASON_MIN_WORDS} words saying why the freeze does not bind this launch; got {r!r}")
    return r


def record_override(root, runner, freeze, problems, reason, now=None):
    """Append one freeze-override/1 line to docs/compute/freeze-overrides.jsonl; returns the record."""
    rec = {"schema": OVERRIDE_SCHEMA, "at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "runner": runner, "freeze": freeze, "head": _git_head(root), "reason": reason,
           "problems": [p["detail"] for p in problems],
           "by": os.environ.get("KIT_AGENT") or os.environ.get("USER") or "unknown"}
    path = Path(root) / OVERRIDES
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def load_overrides(root=ROOT):
    """Every recorded override, validated: PrelaunchError for a malformed line."""
    path = Path(root) / OVERRIDES
    if not path.is_file():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise PrelaunchError(f"{OVERRIDES} line {i}: not JSON ({e})")
        if rec.get("schema") != OVERRIDE_SCHEMA or not rec.get("runner") or not rec.get("at"):
            raise PrelaunchError(f"{OVERRIDES} line {i}: not a {OVERRIDE_SCHEMA} record")
        _valid_reason(rec.get("reason"))
        out.append(rec)
    return out


# ---------------------------------------------------------------- the guard

def check(runner, contract=None, freeze=None, override=None, root=None, contract_path=None, dry_run=False,
          now=None):
    """The whole pre-launch check of one runner: a report with ok, exit, problems (contract and freeze), attention,
    notes and, when an override was used, its record. contract: a dict, else contract_path, else what the runner
    declares. Writes only the override record (not with dry_run)."""
    runner = Path(runner)
    if not runner.is_file():
        raise PrelaunchError(f"{runner}: no such runner")
    root = Path(root) if root else _find_root(runner)
    info = infer(runner, root)
    source = info["contract_from"]
    if contract is None and contract_path:
        try:
            contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise PrelaunchError(f"{contract_path}: cannot read the contract ({e})")
        source = str(contract_path)
    elif contract is not None:
        source = "given"
    else:
        contract = info["contract"]
    if contract is not None:
        validate_contract(contract, source or "contract")
    problems, attention, notes = check_static(info, contract)
    if contract is not None:
        p2, n2 = check_inputs(contract, root)
        problems += p2
        notes += n2
    fr = freeze_check(runner, root, freeze=freeze, contract=contract)
    notes += fr["notes"]
    report = {"runner": info["runner"], "contract": source, "freeze": fr["freeze"], "listed_in": fr["listed_in"],
              "executes": fr["executes"], "problems": problems, "freeze_problems": fr["problems"],
              "attention": attention, "notes": notes, "override": None}
    if fr["problems"] and override:
        reason = _valid_reason(override)
        if dry_run:
            report["override"] = {"reason": reason, "recorded": False, "would_record": OVERRIDES}
        else:
            report["override"] = dict(record_override(root, info["runner"], fr["freeze"], fr["problems"], reason, now),
                                      recorded=OVERRIDES)
    elif override and not fr["problems"]:
        notes.append("an override reason was given, but the freeze check passed, so nothing was recorded")
    freeze_blocks = bool(fr["problems"]) and report["override"] is None
    report["ok"] = not problems and not freeze_blocks
    report["exit"] = EXIT_FAIL if not report["ok"] else EXIT_ATTENTION if attention else EXIT_OK
    return report


def guard(runner_file, contract=None, freeze=None, override=None, root=None, quiet=False):
    """Call first in a runner's local entrypoint: guard(__file__, CONTRACT). Raises LaunchRefused (a SystemExit)
    with every problem; returns the report. freeze and override default to KIT_FREEZE and KIT_FREEZE_OVERRIDE."""
    if freeze is None:
        freeze = os.environ.get("KIT_FREEZE") or None
    if override is None:
        override = os.environ.get("KIT_FREEZE_OVERRIDE") or None
    try:
        report = check(runner_file, contract=contract, freeze=freeze, override=override, root=root)
    except PrelaunchError as e:
        raise LaunchRefused(f"prelaunch: {e}")
    if not report["ok"]:
        raise LaunchRefused(format_report(report))
    if not quiet:
        print(f"prelaunch: {report['runner']} passed" + (f" (freeze {report['freeze']})" if report["freeze"] else "")
              + (f", {len(report['attention'])} unverified" if report["attention"] else "")
              + (", freeze override recorded" if report["override"] else ""), file=sys.stderr)
    return report


def format_report(r):
    head = "PASS" if r["ok"] and not r["attention"] else "PASS, with attention" if r["ok"] else "REFUSED"
    lines = [f"prelaunch {head}: {r['runner']}" + (f" (contract: {r['contract']})" if r["contract"] else
                                                    " (no contract)")
             + (f", freeze {r['freeze']}" if r["freeze"] else "")]
    for p in r["problems"]:
        lines.append(f"  problem  {p['check']}: {p['detail']}")
    for p in r["freeze_problems"]:
        tag = "overridden" if r["override"] else "problem "
        lines.append(f"  {tag} {p['check']}: {p['detail']}")
    for p in r["attention"]:
        lines.append(f"  attention {p['check']}: {p['detail']}")
    for n in r["notes"]:
        lines.append(f"  note     {n}")
    if r["override"]:
        o = r["override"]
        lines.append(f"  override reason: {o['reason']} ({'recorded in ' + o['recorded'] if o.get('recorded') else 'dry run, not recorded'})")
    return "\n".join(lines)


# ---------------------------------------------------------------- audit and launch

def runners(root=ROOT):
    """Every Modal runner in the repository: a .py under scripts/ or codec/ that imports modal and builds an App."""
    out = []
    for top in ("scripts", "codec", "work"):
        base = Path(root) / top
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts or "/archive/" in p.as_posix():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if re.search(r"^\s*import modal\b|^\s*from modal import", text, re.M) and re.search(
                    r"modal\.App\(|\bApp\(", text):
                out.append(p)
    return out


def audit(root=ROOT):
    """One row per Modal runner: contract problems from its source, attention, whether it declares a contract and
    calls guard(), and the live freezes that list it."""
    try:
        from . import freeze as fz

        data = fz.load(root)
        live = {}
        for e in data["freezes"]:
            if e["state"] == "live":
                for f in e.get("files") or {}:
                    live.setdefault(f, []).append(e["id"])
    except Exception:  # noqa: BLE001 - the audit still reads the runners without a registry
        live = {}
    rows = []
    for p in runners(root):
        rel = _rel(p, root)
        try:
            info = infer(p, root)
            c = info["contract"]
            if c is not None:
                validate_contract(c, rel)
            problems, attention, _ = check_static(info, c)
            rows.append({"runner": rel, "problems": [x["detail"] for x in problems],
                         "attention": len(attention), "opaque": bool(info["opaque"]), "contract": c is not None,
                         "calls_guard": info["calls_guard"], "live_freezes": live.get(rel, []),
                         "executes": len(info["executes"])})
        except PrelaunchError as e:
            rows.append({"runner": rel, "problems": [str(e)], "attention": 0, "opaque": None, "contract": None,
                         "calls_guard": None, "live_freezes": live.get(rel, []), "executes": 0})
    return rows


def _launch_argv(runner, modal_args=(), modal_bin=None):
    """The modal command a passing launch runs: modal run --detach RUNNER ARGS (KIT_PRELAUNCH_MODAL overrides the
    modal binary, for tests)."""
    return [modal_bin or os.environ.get("KIT_PRELAUNCH_MODAL") or "modal", "run", "--detach", str(runner),
            *modal_args]


# ---------------------------------------------------------------- command line

def add_arguments(p):
    sub = p.add_subparsers(dest="action", required=True)

    def common(sp):
        sp.add_argument("runner", help="the Modal runner (a .py file)")
        sp.add_argument("--contract", help="a prelaunch/1 contract JSON (default: the runner's CONTRACT or "
                        "RUNNER.contract.json)")
        sp.add_argument("--freeze", help="the freeze this launch belongs to (python -m kit freeze list), or none")
        sp.add_argument("--override-freeze", metavar="REASON", help="let a refused freeze check pass, recording this "
                        f"reason in {OVERRIDES}")
        sp.add_argument("--dry-run", action="store_true", help="record nothing")
        sp.add_argument("--json", action="store_true", help="print the report as JSON")

    common(sub.add_parser("check", help="contract and freeze check of one runner; exit 0 pass, 1 refused, 3 attention"))
    la = sub.add_parser("launch", help="check, then modal run --detach (only with --exec and KIT_ALLOW_MODAL=1)")
    common(la)
    la.add_argument("--exec", action="store_true", help="run modal after a pass (needs KIT_ALLOW_MODAL=1)")
    la.add_argument("modal_args", nargs="*", help="after --: the runner's own arguments")
    inf = sub.add_parser("infer", help="what the guard reads from a runner")
    inf.add_argument("runner", help="the Modal runner (a .py file)")
    inf.add_argument("--json", action="store_true", help="print everything read as JSON")
    out = sub.add_parser("outputs", help="after a run: declared outputs present with their dtypes")
    out.add_argument("runner", help="the Modal runner whose contract declares the outputs")
    out.add_argument("--dir", required=True, help="the folder the run wrote (copied back from the Volume)")
    out.add_argument("--contract", help="a prelaunch/1 contract JSON instead of the runner's own")
    out.add_argument("--json", action="store_true", help="print the rows and problems as JSON")
    au = sub.add_parser("audit", help="every Modal runner in the repository")
    au.add_argument("--json", action="store_true", help="print one JSON row per runner")


def _emit(obj, as_json, text):
    print(json.dumps(obj, indent=1, default=str) if as_json else text)


def run(args, root=None):
    try:
        if args.action in ("check", "launch"):
            freeze = args.freeze
            r = check(args.runner, freeze=freeze, override=args.override_freeze, root=root,
                      contract_path=args.contract, dry_run=args.dry_run)
            if args.action == "check":
                _emit(r, args.json, format_report(r))
                return r["exit"]
            argv = _launch_argv(args.runner, list(args.modal_args or []))
            r["command"] = argv
            _emit(r, args.json, format_report(r) + "\n  command  " + " ".join(argv))
            if not r["ok"]:
                return EXIT_FAIL
            if not args.exec:
                return r["exit"]
            if os.environ.get("KIT_ALLOW_MODAL") != "1":
                print("prelaunch: refusing to run modal: Modal rents compute, which needs the user's go-ahead; set "
                      "KIT_ALLOW_MODAL=1 for an approved launch (AGENTS.md rules 8 and 10)", file=sys.stderr)
                return EXIT_INPUT
            env = dict(os.environ, KIT_PRELAUNCH_PASSED=r["runner"])
            if r["freeze"]:
                env["KIT_FREEZE"] = r["freeze"]
            return subprocess.run(argv, env=env).returncode
        if args.action == "infer":
            info = infer(args.runner, root)
            text = "\n".join([f"runner   {info['runner']}", f"packages {info['venvs']}",
                              f"opaque   {info['opaque'] or 'no'}", f"volumes  {info['volumes']} mounts "
                              f"{info['mounts']}", f"adds     {[a['src'] for a in info['adds']]}",
                              f"executes {info['executes']}", f"contract {info['contract_from'] or 'none'}",
                              f"guard    {'called' if info['calls_guard'] else 'not called'}"])
            _emit(info, args.json, text)
            return EXIT_OK
        if args.action == "outputs":
            r = Path(root) if root else _find_root(args.runner)
            c = json.loads(Path(args.contract).read_text()) if args.contract else infer(args.runner, r)["contract"]
            if c is None:
                raise PrelaunchError(f"{args.runner} declares no contract, so there are no outputs to check")
            validate_contract(c)
            problems, rows = check_outputs(c, args.dir)
            text = "\n".join([f"{x['status']:10s} {x['name']} {x['path'] or ''} {x['dtype'] or ''}" for x in rows]
                             + [f"problem {p['detail']}" for p in problems])
            _emit({"problems": problems, "outputs": rows}, args.json, text or "no outputs declared")
            return EXIT_FAIL if problems else EXIT_OK
        if args.action == "audit":
            rows = audit(Path(root) if root else ROOT)
            bad = [x for x in rows if x["problems"]]
            text = "\n".join([f"{len(rows)} Modal runners; {len(bad)} with contract problems from their source; "
                              f"{sum(1 for x in rows if x['contract'])} declare a contract; "
                              f"{sum(1 for x in rows if x['calls_guard'])} call guard()"]
                             + [f"  {x['runner']}: {'; '.join(x['problems'])}" for x in bad])
            _emit(rows, args.json, text)
            return EXIT_OK
    except PrelaunchError as e:
        print(f"prelaunch: {e}", file=sys.stderr)
        return EXIT_INPUT
    return EXIT_INPUT


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m kit.prelaunch", description=__doc__.split("\n")[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
