"""Tools that let an AI agent drive VC3D with no display: the layer under `kit vc3d mcp` (an MCP server)
and `kit vc3d call` (the same tools from a shell). See docs/vc3d-agents.md.

Each tool takes a JSON object and returns one. Tools that can run long take `background: true` and
return a job id at once; the job runs the same tool in a detached process, so it outlives the server
and the agent's turn, and `jobs` reads its log and result. Paths may be absolute or relative to the
kit home (KIT_HOME; by default the repository root, kit/kithome.py); volumes may also be http(s) or s3
URLs, which VC3D streams.

Rules the tools enforce (AGENTS.md):
  * Everything a tool writes stays out of git: by default under work/vc3d of the kit home
    (KIT_VC3D_HOME); a path inside the kit home or the repository must be one git ignores.
  * Ink on a target needs an experiment in the ledger whose readout rule was fixed first, writes
    under experiments/<slug>/, and always runs the reverse-depth control next to the forward map.
  * Modal runs rent compute, so they need KIT_ALLOW_MODAL=1, set by the user.
  * Renders default to the team's layer order (--flip-normals; reversed by kit on older binaries).
Standard library only. Ink engines run in KIT_INK_PYTHON (a Python with torch).
"""

import http.client
import json
import math
import os
import platform
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from . import (kithome, ledger, s3relay, vc3d, vc3d_audit, vc3d_bridge, vc3d_cache, vc3d_catalog, vc3d_io,
               vc3d_landmarks, vc3d_orient, vc3d_seat)

# The folder that holds kit/, scripts/vc3d/ and docs/. What tools write goes to the kit home instead (Context.root:
# KIT_HOME, else this folder when it is a source checkout, else the working directory; kit/kithome.py).
ROOT = kithome.SOURCE
SCRIPTS = ROOT / "scripts" / "vc3d"
VERSION = "1"
SAFE_DIRS = ("work", "experiments", "checkpoints", "predictions", "volume-cache", "ink-dataset")
URL = re.compile(r"^(https?|s3)://", re.I)

PRESETS = {
    "9um": {"layers": 28, "slice_step": 1.0, "about": "published 9.362 um renders; ink_9um, Reader v2, v8in"},
    "2um": {"layers": 109, "slice_step": 1.0, "about": "published 2.4 um renders"},
    "1um": {"layers": 116, "slice_step": 1.0, "about": "published 1.129 um renders"},
    "legacy": {"layers": 65, "slice_step": 1.0, "about": "the 2023 papers and the legacy VC pipeline"},
}
FRAME_CANDIDATES = (1.0, 2.0, 4.0, 0.5, 0.25)

INSTRUCTIONS = """\
kit-vc3d drives VC3D (volume-cartographer) and the repository's ink models with no display.
Start with `status`, then `selftest` on a new machine. Typical flow: `catalog` or `fetch_segment` for
data, `trace` to grow a surface, `check_surface` to see that it sits on a sheet in the right frame
(at several windows, with its normal sign), `audit` for missing chunks under it, `render` for a
surface volume (team layer order by default, checked against the umbilicus), `ink` for maps (forward
plus the reverse-depth control), `preview` to look, `jobs` for anything started with background=true.
Rules: outputs stay in ignored folders (work/, experiments/), never in git. An ink map is model
output, not a reading: never say letters were found or read. Ink on a target scroll needs a
preregistered experiment (python -m kit run init) before any map exists. Every check must be able
to fail: keep the reverse and shuffle controls. No posting anywhere; Modal needs KIT_ALLOW_MODAL=1.
`guide` has the details."""


class ToolError(Exception):
    """A problem the agent can fix: reported as a tool error, not a crash."""


class Context:
    """Where tools run: the kit home (root: KIT_HOME, else the repository), the work home, the environment,
    cancellation and progress."""

    def __init__(self, root=None, home=None, env=None, cancel=None, progress=None, in_job=False):
        self.env = dict(os.environ if env is None else env)
        self.root = Path(root or kithome.home(self.env))
        self.home = Path(home or self.env.get("KIT_VC3D_HOME") or self.root / "work" / "vc3d")
        self.cancel = cancel
        self.progress = progress
        self.in_job = in_job
        self.progress_every = float(self.env.get("KIT_VC3D_PROGRESS_SECONDS") or 10)
        self._tools = None
        self.setup_problem = None
        self._relays = {}
        self._relay_lock = threading.Lock()

    def tools(self, required=True):
        if self._tools is None:
            try:
                self._tools = vc3d.find_tools(self.env)
            except vc3d.SetupError as exc:
                self.setup_problem = str(exc)
                if required:
                    raise ToolError(str(exc)) from exc
                return None
        if self._tools is None and required:
            raise ToolError("no VC3D tools found: set VC_APPIMAGE to villa's release AppImage (or the folder it was "
                            "extracted into), VC_BIN to a folder holding vc_render_tifxyz (a villa build's build/bin), "
                            "VC_ROOTFS to an unpacked container root, or put the tools on PATH. "
                            "docs/vc3d-headless.md says how to get them.")
        return self._tools

    def say(self, message):
        if self.progress:
            self.progress(message)

    def cancelled(self):
        return self.cancel is not None and self.cancel.is_set()

    def vc3d_url(self, url):
        """The URL to give VC3D for a remote volume: a local relay's (kit/s3relay.py), started on first use, so
        VC3D never takes a false 404 for a missing chunk; the URL itself with KIT_VC3D_RELAY=0 or when no relay
        can start."""
        url = str(url)
        if self.env.get("KIT_VC3D_RELAY") == "0":
            return url
        try:
            origin, _ = s3relay.origin_of(url)
        except s3relay.RelayError:
            return url
        with self._relay_lock:
            relay = self._relays.get(origin)
            if relay is None:
                try:
                    relay = self._relays[origin] = s3relay.Relay(url).start()
                except OSError as exc:
                    self.say(f"no false-404 relay for {origin} ({exc}); VC3D reads it directly")
                    return url
        return relay.url_for(url)

    def relay_stats(self, url):
        """The running relay's counters for url's origin, or None."""
        try:
            origin, _ = s3relay.origin_of(url)
        except s3relay.RelayError:
            return None
        relay = self._relays.get(origin)
        return dict(relay.stats) if relay else None

    def close(self):
        """Stop the relays this context started."""
        with self._relay_lock:
            for relay in self._relays.values():
                relay.stop()
            self._relays.clear()


# ---------------------------------------------------------------- registry

def _p(kind, desc, **kw):
    out = {"type": kind, "description": desc}
    out.update(kw)
    return out


def STR(desc, **kw):
    return _p("string", desc, **kw)


def INT(desc, **kw):
    return _p("integer", desc, **kw)


def NUM(desc, **kw):
    return _p("number", desc, **kw)


def BOOL(desc, **kw):
    return _p("boolean", desc, **kw)


def ARR(desc, items, **kw):
    return _p("array", desc, items=items, **kw)


def OBJ(desc, **kw):
    return _p("object", desc, **kw)


class Tool:
    def __init__(self, name, title, description, properties, required, handler, background, readonly, destructive,
                 openworld):
        self.name, self.title, self.description = name, title, description
        self.properties, self.required, self.handler = properties, tuple(required), handler
        self.background, self.readonly, self.destructive, self.openworld = background, readonly, destructive, openworld

    def schema(self):
        props = dict(self.properties)
        if self.background:
            props["background"] = BOOL("run as a background job and return its id at once; read it with jobs")
        return {"type": "object", "properties": props, "required": list(self.required), "additionalProperties": False}

    def annotations(self):
        return {"title": self.title, "readOnlyHint": self.readonly, "destructiveHint": self.destructive,
                "idempotentHint": self.readonly, "openWorldHint": self.openworld}


TOOLS = {}
TOOL_ALIASES = {"autopipe": "autopipeline"}   # earlier names that still work (AutoPipeline was autopipe until 9 Oct 2026)


def tool(name, title, description, properties=None, required=(), background=False, readonly=False,
         destructive=False, openworld=False):
    def deco(fn):
        TOOLS[name] = Tool(name, title, description, properties or {}, required, fn, background, readonly,
                           destructive, openworld)
        return fn
    return deco


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def _type_ok(value, kinds):
    for kind in kinds if isinstance(kinds, list) else [kinds]:
        if kind == "null" and value is None:
            return True
        if kind in ("integer", "number") and isinstance(value, bool):
            continue
        if kind == "integer" and isinstance(value, float) and value.is_integer():
            return True
        if kind in _TYPES and isinstance(value, _TYPES[kind]):
            return True
    return False


def validate(t, args):
    if not isinstance(args, dict):
        raise ToolError(f"{t.name} takes a JSON object of arguments")
    schema = t.schema()
    props = schema["properties"]
    unknown = sorted(set(args) - set(props))
    if unknown:
        raise ToolError(f"{t.name}: unknown argument(s) {', '.join(unknown)}; it takes {', '.join(sorted(props))}")
    missing = [r for r in schema["required"] if args.get(r) is None]
    if missing:
        raise ToolError(f"{t.name}: missing required argument(s) {', '.join(missing)}")
    for key, value in args.items():
        spec = props[key]
        if value is None:
            continue
        if not _type_ok(value, spec["type"]):
            raise ToolError(f"{t.name}: {key} should be {spec['type']}, got {type(value).__name__}")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"{t.name}: {key} must be one of {spec['enum']}, got {value!r}")
        if spec.get("type") == "array" and "items" in spec and "type" in spec["items"]:
            for item in value:
                if not _type_ok(item, spec["items"]["type"]):
                    raise ToolError(f"{t.name}: every item of {key} should be {spec['items']['type']}")
                if "enum" in spec["items"] and item not in spec["items"]["enum"]:
                    raise ToolError(f"{t.name}: items of {key} must be in {spec['items']['enum']}")
        for bound, test in (("minimum", lambda v, b: v >= b), ("maximum", lambda v, b: v <= b)):
            if bound in spec and isinstance(value, (int, float)) and not test(value, spec[bound]):
                raise ToolError(f"{t.name}: {key} must be {bound} {spec[bound]}")
        if "minItems" in spec and len(value) < spec["minItems"] or "maxItems" in spec and len(value) > spec["maxItems"]:
            raise ToolError(f"{t.name}: {key} needs {spec.get('minItems')} to {spec.get('maxItems')} items")


def call(name, args=None, ctx=None):
    """Run one tool. Returns its result dict; raises ToolError for problems the caller can fix. A context made
    here is closed afterwards (its relays stop); a context passed in keeps them for the next call."""
    own = ctx is None
    ctx = ctx or Context()
    name = TOOL_ALIASES.get(name, name)
    try:
        t = TOOLS.get(name)
        if t is None:
            raise ToolError(f"no tool {name!r}; tools: {', '.join(sorted(TOOLS))}")
        if args is not None and not isinstance(args, dict):
            raise ToolError(f"{name} takes a JSON object of arguments")
        args = dict(args or {})
        validate(t, args)
        if args.pop("background", False):
            return submit_job(ctx, name, args)
        return t.handler(ctx, args)
    finally:
        if own:
            ctx.close()


# ---------------------------------------------------------------- paths, runs, receipts

def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def slug(text, keep=48):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.")
    return s[-keep:] or "x"


def _is_s3(text):
    """An S3 URL (s3://, or https on amazonaws.com): the kind that answers false 404s."""
    t = str(text)
    if t.lower().startswith("s3://"):
        return True
    return bool(re.match(r"^https?://[^/]*amazonaws\.com(/|$)", t, re.I))


def is_url(text):
    return bool(URL.match(str(text)))


def resolve(ctx, path):
    p = Path(str(path)).expanduser()
    return p if p.is_absolute() else ctx.root / p


def existing(ctx, path, what="path", check=None):
    p = resolve(ctx, path)
    if not p.exists():
        raise ToolError(f"{what} not found: {p}")
    if check == "tifxyz" and not vc3d_io.is_tifxyz(p):
        raise ToolError(f"{p} is not a tifxyz folder (x.tif, y.tif, z.tif)")
    if check == "zarr" and not vc3d_io.is_zarr(p):
        raise ToolError(f"{p} is not a zarr store (.zarray, .zgroup or zarr.json)")
    return p


def _git(ctx, *args, timeout=20, cwd=None):
    env = dict(os.environ, LC_ALL="C", LANGUAGE="C")      # git's messages in English: outside_git() reads one
    try:
        return subprocess.run(["git", "-C", str(cwd or ctx.root), *args], capture_output=True, text=True,
                              timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


def _under(path, base):
    """path relative to base, both through their real paths, or None when it lies outside. A folder reached through
    a symlink (macOS's /tmp and /var lead into /private) is one place, so a path given through either spelling is
    judged where it really is."""
    try:
        return Path(os.path.realpath(path)).relative_to(Path(os.path.realpath(base)))
    except ValueError:
        return None


def in_repo(ctx, path):
    """path relative to the kit home (ctx.root), or None when it lies outside."""
    return _under(path, ctx.root)


def _existing_dir(path):
    p = Path(os.path.abspath(path))
    while not p.is_dir() and p != p.parent:
        p = p.parent
    return p


def outside_git(ctx, folder):
    """True only when no git repository holds folder: git's search found none ("not a git repository (or any
    parent ..."), or, when git cannot run, no .git lies in folder or any folder above it. Any other failure (a
    repository git refuses to read, for dubious ownership say, or a .git file pointing nowhere) counts as inside,
    so the rule 6 guard fails closed."""
    folder = Path(os.path.abspath(folder))
    r = _git(ctx, "rev-parse", "--is-inside-work-tree", cwd=folder)
    if r is None:
        return not any((p / ".git").exists() for p in (folder, *folder.parents))
    return r.returncode != 0 and "not a git repository (or any" in (r.stderr or "")


def ignored(ctx, path):
    """True when a path inside the kit home (ctx.root) is one git ignores, so data written there stays out of git.
    A kit home other than the source folder that lies in no git repository at all (KIT_HOME elsewhere, or the
    working directory of an installed kit) holds nothing git could take. The source folder takes only paths git
    ignores, even when no repository holds it (a copy downloaded without git): the code folder is no place for
    outputs. When the kit home is not the source folder, the source folder is guarded too, so an output path
    cannot land among its tracked files."""
    src, home = Path(os.path.abspath(ROOT)), Path(os.path.abspath(ctx.root))
    for base in [home] + ([src] if src != home else []):
        rel = _under(path, base)
        if rel is None:
            continue
        parts = rel.parts
        if parts and parts[0] in SAFE_DIRS and len(parts) > 1 and not (parts[0] == "experiments"
                                                                       and parts[-1] == "README.md"):
            continue
        if base == src:
            r = _git(ctx, "check-ignore", "-q", "--", str(rel), cwd=base)
            ok = r is not None and r.returncode == 0
        else:
            where = _existing_dir(os.path.realpath(path))
            r = _git(ctx, "check-ignore", "-q", "--", os.path.realpath(path), cwd=where)
            ok = r is not None and r.returncode == 0
            if r is None or r.returncode == 128:  # git could not answer: fine only if no repository holds the path
                ok = outside_git(ctx, where)
        if not ok:
            return False
    return True


def writable(ctx, path):
    p = resolve(ctx, path)
    if not ignored(ctx, p):
        raise ToolError(f"{p} is inside the repository but not ignored by git. Scroll data, renders, maps and weights "
                        "never enter git (AGENTS.md rule 6): write under work/ or experiments/, or outside the "
                        "repository.")
    return p


def fresh(path, create=False):
    """`path`, or path-2, path-3, ... when it exists: two calls in the same second never share an output.
    With create the folder is made here, atomically, so concurrent jobs cannot pick the same name."""
    base = Path(path)
    base.parent.mkdir(parents=True, exist_ok=True)
    p, k = base, 2
    while True:
        if create:
            try:
                p.mkdir()
                return p
            except FileExistsError:
                pass
        elif not p.exists():
            return p
        name = f"{base.stem}-{k}{base.suffix}" if base.suffix in (".png", ".json", ".log") else f"{base.name}-{k}"
        p, k = base.with_name(name), k + 1


def out_dir(ctx, given, *default):
    if given:
        p = writable(ctx, given)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return fresh(ctx.home.joinpath(*default), create=True)


def tail(path, lines=20, max_chars=6000):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 64 * 1024))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])[-max_chars:]


def _kill(proc, group):
    try:
        if group:
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL) if group else proc.kill()
        except OSError:
            pass


def run_logged(ctx, argv, log, env=None, timeout=None, cwd=None):
    """Run argv with its output appended to `log`; honour cancellation and a timeout, report progress.

    Returns (exit code or 'timeout'/'cancelled'/'could not start: ...', seconds)."""
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(a) for a in argv]
    started = time.time()
    group = not ctx.in_job
    with open(log, "ab") as fh:
        fh.write(f"\n$ {shlex.join(argv)}\n".encode())
        fh.flush()
        try:
            proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    env=env, cwd=cwd, start_new_session=group)
        except OSError as exc:
            fh.write(f"could not start: {exc}\n".encode())
            return f"could not start: {exc}", 0.0
        said = time.time()
        try:
            while True:
                try:
                    rc = proc.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if ctx.cancelled():
                    _kill(proc, group)
                    rc = "cancelled"
                    break
                if timeout and time.time() - started > timeout:
                    _kill(proc, group)
                    rc = "timeout"
                    break
                if time.time() - said > ctx.progress_every:
                    said = time.time()
                    last = tail(log, 1)
                    ctx.say(f"{Path(argv[0]).name}: {int(said - started)} s; {last[-200:]}")
        except BaseException:  # Ctrl-C or a job's SIGTERM: never leave the child running on its own
            _kill(proc, group)
            raise
    return rc, round(time.time() - started, 1)


def git_commit(ctx):
    """The commit of the kit that ran (its source folder), or None outside git."""
    r = _git(ctx, "rev-parse", "HEAD", cwd=ROOT)
    return r.stdout.strip() if r is not None and r.returncode == 0 else None


def light_fingerprint(path, max_bytes=512 << 20):
    """Cheap identity for a receipt: sha256 of small files and of tifxyz/zarr metadata, sizes otherwise."""
    import hashlib
    if is_url(path):
        return {"url": str(path)}
    p = Path(path)
    if p.is_file():
        st = p.stat()
        out = {"path": str(p), "bytes": st.st_size}
        if st.st_size <= max_bytes:
            out["sha256"] = _sha(p)
        return out
    if p.is_dir():
        names = [n for n in ("meta.json", "x.tif", "y.tif", "z.tif", ".zarray", ".zattrs", ".zgroup", "zarr.json",
                             "0/.zarray", "0/zarr.json") if (p / n).is_file()]
        h = hashlib.sha256()
        total = 0
        for n in names:
            total += (p / n).stat().st_size
            if total > max_bytes:
                return {"path": str(p), "files": names, "note": "too large to hash"}
            h.update(n.encode() + b"\0" + _sha(p / n).encode())
        return {"path": str(p), "files": names, "sha256": h.hexdigest()}
    return {"path": str(p), "missing": True}


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_receipt(ctx, out, tool_name, args, steps, outputs, started, **extra):
    t = ctx.tools(required=False)
    rec = {"tool": tool_name, "args": args, "started": started, "finished": now(), "kit_commit": git_commit(ctx),
           "host": platform.node(), "machine": f"{platform.system()} {platform.machine()}",
           "python": platform.python_version(), "vc3d": t.describe() if t else None, "steps": steps,
           "outputs": outputs, **extra}
    path = Path(out) / "receipt.json"
    path.write_text(json.dumps(rec, indent=1, default=str))
    return str(path)


# ---------------------------------------------------------------- jobs

def jobs_dir(ctx):
    return ctx.home / "jobs"


def script(name, need):
    """scripts/vc3d/<name> from kit's source folder, or a ToolError saying it ships with the source."""
    try:
        return kithome.source_file(f"scripts/vc3d/{name}", need, source=SCRIPTS.parent.parent)
    except kithome.MissingSource as exc:
        raise ToolError(str(exc)) from exc


_children = []


def _reap():
    for proc in list(_children):
        if proc.poll() is not None:
            _children.remove(proc)


def submit_job(ctx, name, args):
    _reap()
    jid = f"{stamp()}-{name}-{os.urandom(2).hex()}"
    d = jobs_dir(ctx) / jid
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"id": jid, "tool": name, "args": args, "created": now(),
                                            "root": str(ctx.root), "home": str(ctx.home)}, indent=1))
    with open(d / "log.txt", "ab") as log:
        proc = subprocess.Popen([sys.executable, "-m", "kit.vc3d_agent", "job", str(d)], cwd=str(ROOT),
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=ctx.env, start_new_session=True)
    _children.append(proc)
    (d / "pid").write_text(str(proc.pid))
    return {"job": jid, "status": "running", "tool": name, "log": str(d / "log.txt"),
            "next": f"jobs action=wait id={jid} (or action=status to look without waiting)"}


def job_main(jobdir):
    """Entry of a background job's process: run the tool, write result.json and exit.json."""
    d = Path(jobdir)
    spec = json.loads((d / "job.json").read_text())
    ctx = Context(root=spec["root"], home=spec["home"], progress=lambda m: print(m, flush=True), in_job=True)

    def stop(signum, frame):
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, stop)
    print(f"[{now()}] job {spec['id']}: {spec['tool']} {json.dumps(spec['args'])}", flush=True)
    status, error = "failed", None
    try:
        result = call(spec["tool"], spec["args"], ctx)
        (d / "result.json").write_text(json.dumps(result, indent=1, default=str))
        status = "succeeded"
    except ToolError as exc:
        error = str(exc)
    except KeyboardInterrupt as exc:
        status, error = "cancelled", str(exc)
    except Exception as exc:  # a crash is reported, with its traceback in the log
        traceback.print_exc()
        error = f"{type(exc).__name__}: {exc}"
    (d / "exit.json").write_text(json.dumps({"status": status, "error": error, "finished": now()}))
    print(f"[{now()}] job {status}" + (f": {error}" if error else ""), flush=True)
    return 0 if status == "succeeded" else 1


def _pid_alive(pid):
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    except OSError:
        return False
    return vc3d_bridge._alive(pid)


def job_info(ctx, jid, lines=20):
    d = jobs_dir(ctx) / jid
    if not (d / "job.json").is_file():
        raise ToolError(f"no job {jid!r} under {jobs_dir(ctx)}")
    spec = json.loads((d / "job.json").read_text())
    info = {"job": jid, "tool": spec["tool"], "created": spec["created"], "args": spec["args"]}
    if (d / "exit.json").is_file():
        info.update(json.loads((d / "exit.json").read_text()))
    else:
        pid = int((d / "pid").read_text()) if (d / "pid").is_file() else None
        info["status"] = "running" if pid and _pid_alive(pid) else "lost (process ended without a result)"
    if (d / "result.json").is_file():
        info["result"] = json.loads((d / "result.json").read_text())
    info["log"] = str(d / "log.txt")
    info["log_tail"] = tail(d / "log.txt", lines)
    return info


def job_list(ctx, limit=20):
    d = jobs_dir(ctx)
    ids = sorted((p.name for p in d.iterdir() if (p / "job.json").is_file()), reverse=True) if d.is_dir() else []
    out = []
    for jid in ids[:limit]:
        info = job_info(ctx, jid, lines=1)
        out.append({k: info.get(k) for k in ("job", "tool", "status", "created", "finished", "error")})
    return out


def job_cancel(ctx, jid, grace=8.0):
    d = jobs_dir(ctx) / jid
    info = job_info(ctx, jid, 0)
    if info["status"] != "running":
        return {"job": jid, "status": info["status"], "cancelled": False}
    pid = int((d / "pid").read_text())
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.time() + grace
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.2)
    try:  # also when the leader is gone: a child that ignored SIGTERM (a data-loader worker) is still in the group
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    if not (d / "exit.json").is_file():
        (d / "exit.json").write_text(json.dumps({"status": "cancelled", "error": "cancelled", "finished": now()}))
    return {"job": jid, "status": "cancelled", "cancelled": True}


def job_wait(ctx, jid, timeout=60.0, lines=20):
    deadline = time.time() + timeout
    said = 0.0
    while True:
        info = job_info(ctx, jid, lines)
        if info["status"] != "running" or time.time() >= deadline or ctx.cancelled():
            if info["status"] == "running":
                info["waited"] = f"{timeout:.0f} s; still running, wait again"
            return info
        if time.time() - said > ctx.progress_every:
            said = time.time()
            ctx.say(f"{jid}: {tail(jobs_dir(ctx) / jid / 'log.txt', 1)[-200:]}")
        time.sleep(min(1.0, max(0.1, deadline - time.time())))


# ---------------------------------------------------------------- capabilities and environments

def accepts_url_volume(help_text):
    """True when the renderer takes a remote URL as --volume itself: villa since ba2bf75 (#1863, 12 Oct 2026).
    Those builds mark --remote-url deprecated and exit 1 when --volume and --remote-url name different
    sources, so kit must not pass its cache folder as --volume there."""
    text = " ".join(str(help_text).split())
    if "[DEPRECATED] Same as passing the remote" in text or "or a remote OME-Zarr URL" in text:
        return True
    # a build whose help names --volume but no --remote-url cannot take the old pair at all; should villa reword
    # the help or drop the deprecated flag, the URL as --volume is the only form left
    return "--volume" in text and "--remote-url" not in text


def capabilities(ctx, tools, refresh=False):
    """What this build's renderer supports, read from its --help; cached per binary. A probe that failed (a
    timeout, no binary, help without --volume) is recorded but never reused: the next call probes again, so one
    bad start cannot leave the renderer marked without the URL form for good."""
    probe = tools.path(vc3d.PROBE)
    try:
        key = f"{tools.kind}:{tools.bindir}:{probe.stat().st_mtime_ns}"
    except OSError:
        key = f"{tools.kind}:{tools.bindir}:missing"
    cache = ctx.home / "cache" / "capabilities.json"
    try:
        data = json.loads(cache.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    if not refresh and data.get("key") == key and "volume_url" in data and data.get("starts"):
        return data
    try:
        r = subprocess.run(tools.argv(vc3d.PROBE, "--help"), capture_output=True, text=True, timeout=60,
                           env=vc3d.headless_env(ctx.env))
        text = r.stdout + r.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        text = str(exc)
    keep = data.get("selftest") if data.get("key") == key else None
    data = {"key": key, "starts": "--volume" in text, "flip_normals": "--flip-normals" in text,
            "zarr_compressor": "--zarr-compressor" in text, "surface_interpolation": "--surface-interpolation" in text,
            "remote_url": "--remote-url" in text, "volume_url": accepts_url_volume(text), "selftest": keep}
    _write_capabilities(cache, data)
    return data


def _write_capabilities(cache, data):
    """Write the probe cache whole: a reader sees the old file or the new one, never a half-written one (which it
    would read as empty, probe again and write back without the self-test record)."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f".{cache.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, cache)


def _save_selftest(ctx, tools, report):
    caps = capabilities(ctx, tools, refresh=True)    # a self-test reads the build's help afresh too
    caps["selftest"] = {"verdict": report["verdict"], "at": now(), "conventions": report.get("conventions"),
                        "work": report.get("work")}
    _write_capabilities(ctx.home / "cache" / "capabilities.json", caps)


_INK_ENV = {}
INK_PROBE = r"""
import importlib.util as u, json, sys
out = {"python": sys.executable, "version": sys.version.split()[0]}
for m in ("numpy", "tifffile", "zarr", "numcodecs", "imagecodecs", "torch", "vesuvius", "huggingface_hub"):
    out[m] = bool(u.find_spec(m))
if out["torch"]:
    try:
        import torch
        out["torch_version"] = torch.__version__
        out["cuda"] = torch.cuda.is_available()
        out["mps"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except Exception as exc:
        out["torch_error"] = str(exc)
print(json.dumps(out))
"""


def ink_python(ctx):
    return ctx.env.get("KIT_INK_PYTHON") or sys.executable


def ink_env(ctx, refresh=False):
    py = ink_python(ctx)
    if refresh or py not in _INK_ENV:
        try:
            r = subprocess.run([py, "-c", INK_PROBE], capture_output=True, text=True, timeout=120, env=ctx.env)
            _INK_ENV[py] = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else \
                {"python": py, "error": (r.stderr or r.stdout)[-500:]}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError) as exc:
            _INK_ENV[py] = {"python": py, "error": str(exc)}
    return _INK_ENV[py]


def numpy_stack():
    try:
        import numpy  # noqa: F401
        import tifffile  # noqa: F401
        import zarr  # noqa: F401
        return True
    except ImportError:
        return False


def threads_for(ctx, a, cap=None):
    n = a.get("threads") or int(vc3d.headless_env(ctx.env)["OMP_NUM_THREADS"])
    return max(1, min(n, cap)) if cap else max(1, n)


# ---------------------------------------------------------------- surfaces

def tifxyz_stats(path, voxel_um=None, max_vertices=2_000_000):
    """Grid, validity, extent, step regularity and area of a tifxyz surface (standard library). A grid of more
    than max_vertices is read at every step-th row and column (`sampled_every`); there each valid vertex read
    stands for the block of vertices it starts, so valid_vertices of a fully valid grid is rows x cols (and an
    estimate where a block is partly valid)."""
    p = Path(path)
    meta = {}
    if (p / "meta.json").is_file():
        try:
            meta = json.loads((p / "meta.json").read_text())
        except json.JSONDecodeError:
            meta = {}
    x, y, z = (vc3d_io.read_tiff(p / f"{a}.tif") for a in "xyz")
    if not (x.h == y.h == z.h and x.w == y.w == z.w):
        raise ToolError(f"{p}: x, y and z grids differ in size")
    rows, cols = x.h, x.w
    step = max(1, int(math.ceil(math.sqrt(rows * cols / max_vertices))))
    X, Y, Z = x.data, y.data, z.data

    def ok(i):
        a, b, c = X[i], Y[i], Z[i]
        return not (a == -1 and b == -1 and c == -1) and a == a and b == b and c == c and (a or b or c)

    valid = n = covered = 0
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    edges, area = [], 0.0
    for r in range(0, rows, step):
        for c in range(0, cols, step):
            i = r * cols + c
            n += 1
            if not ok(i):
                continue
            valid += 1
            # the block this vertex stands for, cut short at the last row and column: these sum to rows x cols
            covered += min(step, rows - r) * min(step, cols - c)
            for k, v in enumerate((X[i], Y[i], Z[i])):
                lo[k], hi[k] = min(lo[k], v), max(hi[k], v)
            if c + step < cols and ok(i + step):
                edges.append(math.dist((X[i], Y[i], Z[i]), (X[i + step], Y[i + step], Z[i + step])) / step)
            if r + step < rows and ok(i + step * cols):
                j = i + step * cols
                edges.append(math.dist((X[i], Y[i], Z[i]), (X[j], Y[j], Z[j])) / step)
                k2 = j + step
                if c + step < cols and ok(i + step) and ok(k2):
                    u = (X[i + step] - X[i], Y[i + step] - Y[i], Z[i + step] - Z[i])
                    v = (X[j] - X[i], Y[j] - Y[i], Z[j] - Z[i])
                    area += math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2
                                      + (u[0] * v[1] - u[1] * v[0]) ** 2)
    edges.sort()
    scale = meta.get("scale") or [None, None]
    # a malformed scale (one element, a dict, a string) is reported, not raised: the stats are still good
    two = isinstance(scale, (list, tuple)) and len(scale) == 2
    steps = [round(1 / s, 3) if isinstance(s, (int, float)) and s > 0 else None for s in scale] if two else None
    out = {"path": str(p), "grid_rows_cols": [rows, cols], "sampled_every": step,
           "valid_vertices": covered,
           "valid_fraction": round(valid / max(1, n), 4),
           "bbox_xyz": [[round(v, 2) for v in lo], [round(v, 2) for v in hi]] if valid else None,
           "meta_scale": scale, "grid_step_voxels": steps}
    if not two:
        out["meta_scale_problem"] = f"scale {scale!r} is not two numbers"
    if edges:
        med = vc3d_io.percentile(edges, 50)
        out["edge_voxels"] = {"median": round(med, 3), "p95": round(vc3d_io.percentile(edges, 95), 3),
                              "max": round(edges[-1], 3)}
        out["long_edges"] = sum(1 for e in edges if e > 4 * med)
    # each sampled quad already spans step x step cells, so the sum is the area as it is (until 9 Oct 2026 it was
    # multiplied by step squared again, overstating grids over max_vertices). A sampled grid leaves out two partial
    # strips of cells, the last (rows - 1) % step rows of cells and the last (cols - 1) % step columns. Together
    # they are at most step / rows + step / cols of the grid's cells, because (step - 1) / (n - 1) <= step / n
    # for n >= step, and step / n is over 1 otherwise. On an evenly spaced grid that is also the share of the area
    out["area_voxels2"] = round(area, 1)
    if meta.get("area_vx2") is not None:
        out["meta_area_vx2"], out["meta_area_cm2"] = meta.get("area_vx2"), meta.get("area_cm2")
    vu = voxel_um or meta.get("voxelsize")
    if vu:
        out["voxel_um"] = vu
        out["area_cm2"] = round(out["area_voxels2"] * (vu * 1e-4) ** 2, 4)
    if steps and all(steps):
        out["render_px_at_scale_1"] = [int(round(rows / scale[1])), int(round(cols / scale[0]))]
    for k in ("uuid", "type", "format", "source", "target_volume", "max_gen", "vc_gsfs_mode", "seed"):
        if k in meta:
            out[k] = meta[k]
    return out


def central_vertex(path):
    """(row, col) of the valid vertex nearest the grid centre."""
    x = vc3d_io.read_tiff(Path(path) / "x.tif")
    z = vc3d_io.read_tiff(Path(path) / "z.tif")
    rows, cols = x.h, x.w
    best = None
    step = max(1, int(math.sqrt(rows * cols / 250_000)))
    for r in range(0, rows, step):
        for c in range(0, cols, step):
            i = r * cols + c
            if x.data[i] == -1 or z.data[i] <= 0:
                continue
            d = (r - rows / 2) ** 2 + (c - cols / 2) ** 2
            if best is None or d < best[0]:
                best = (d, r, c)
    if best is None:
        raise ToolError(f"{path} has no valid vertex")
    return best[1], best[2], rows, cols


def window_centres(path, k):
    """Up to k valid vertices [(row, col, (x, y, z))] spread over a tifxyz: the one nearest the grid centre
    first, then the cells of a lattice over the valid area, farthest from those already chosen first."""
    p = Path(path)
    row, col, rows, cols = central_vertex(p)
    gx, gy, gz = (vc3d_io.read_tiff(p / f"{a}.tif") for a in "xyz")

    def ok(r, c):
        i = r * cols + c
        return gx.data[i] != -1 and gz.data[i] > 0

    def xyz(r, c):
        i = r * cols + c
        return (round(gx.data[i], 2), round(gy.data[i], 2), round(gz.data[i], 2))

    chosen = [(row, col)]
    if k > 1:
        step = max(1, int(math.sqrt(rows * cols / 250_000)))
        rmin = cmin = math.inf
        rmax = cmax = -math.inf
        for r in range(0, rows, step):
            for c in range(0, cols, step):
                if ok(r, c):
                    rmin, rmax, cmin, cmax = min(rmin, r), max(rmax, r), min(cmin, c), max(cmax, c)
        m = math.ceil(math.sqrt(k)) + 1
        cands = []
        for i in range(m):
            for j in range(m):
                r0, r1 = rmin + (rmax - rmin) * i / m, rmin + (rmax - rmin) * (i + 1) / m
                c0, c1 = cmin + (cmax - cmin) * j / m, cmin + (cmax - cmin) * (j + 1) / m
                tr, tc = (r0 + r1) / 2, (c0 + c1) / 2
                sub = max(1, int(max(r1 - r0, c1 - c0) / 50))
                best = None
                for r in range(int(r0), int(r1) + 1, sub):
                    for c in range(int(c0), int(c1) + 1, sub):
                        if r < rows and c < cols and ok(r, c):
                            d = (r - tr) ** 2 + (c - tc) ** 2
                            if best is None or d < best[0]:
                                best = (d, r, c)
                if best:
                    cands.append((best[1], best[2]))
        while len(chosen) < k and cands:
            def spread(q):   # nearest chosen first, then all of them: ties go to the cell that spreads widest
                d = [(q[0] - a) ** 2 + (q[1] - b) ** 2 for a, b in chosen]
                return min(d), sum(d)
            far = max(cands, key=spread)
            cands.remove(far)
            if spread(far)[0] > 0:
                chosen.append(far)
    return [(r, c, xyz(r, c)) for r, c in chosen], rows, cols


def _voxel_for(ctx, volume, given=None):
    """Voxel size in um: given; else the catalog's (an open-data URL, or the volume id that starts the name);
    else the size an open-data style name carries (20260411134726-2.400um-...)."""
    if given:
        return float(given)
    if is_url(volume):
        found = _catalog_voxel(ctx, volume)
        if found:
            return float(found)
    name = str(volume).rstrip("/").split("/")[-1]
    cat = _catalog(ctx)
    hit = vc3d_catalog.volume_by_id(cat, name.split("-")[0]) if cat else None
    if hit and hit[1].get("voxel_um"):
        return float(hit[1]["voxel_um"])
    m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)um", name)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------- tools: discovery

@tool("status", "Status", "Where the VC3D tools are, what this build supports, the last self-test, the ink "
      "Python, running jobs and the app bridge. Call this first.", readonly=True)
def h_status(ctx, a):
    tools = ctx.tools(required=False)
    env = vc3d.headless_env(ctx.env)
    out = {"server": f"kit-vc3d {VERSION}", "repo": str(ctx.root), "home": str(ctx.home),
           "display": "none needed (QT_QPA_PLATFORM=offscreen)", "cpu_limit": vc3d.cpu_limit(),
           "threads_default": int(env["OMP_NUM_THREADS"]), "modal_allowed": ctx.env.get("KIT_ALLOW_MODAL") == "1"}
    if tools is None:
        out["tools"] = None
        out["fix"] = ctx.setup_problem or ("set VC_APPIMAGE to villa's release AppImage, or VC_BIN to a villa "
                                           "build's bin folder (docs/vc3d-headless.md), then call selftest")
    else:
        caps = capabilities(ctx, tools)
        out["tools"] = tools.describe()
        out["has"] = {n: tools.has(n) for n in [t[0] for t in vc3d.PIPELINE_TOOLS] + ["VC3D"]}
        missing = [r for r in vc3d.pipeline_tools(tools) if not r["found"]]
        if missing:
            out["autopipeline_missing"] = {r["tool"]: vc3d.missing_text(r) for r in missing}
        out["renderer"] = {k: caps.get(k) for k in ("starts", "flip_normals", "zarr_compressor",
                                                     "surface_interpolation", "remote_url", "volume_url")}
        out["last_selftest"] = caps.get("selftest") or "never run on this build: call selftest"
        if not caps.get("flip_normals"):
            out["note"] = "this renderer lacks --flip-normals; render reverses the layers itself for team order"
    out["ink_python"] = ink_env(ctx)
    out["jobs_running"] = [j for j in job_list(ctx, 50) if j["status"] == "running"]
    out["app"] = vc3d_bridge.App(ctx.home).current()
    out["models"] = sorted(load_models(ctx))
    return out


@tool("selftest", "Self-test", "Render and trace synthetic volumes with no display and check every value: the "
      "build starts, samples trilinearly, registers pixels, orders layers (and --flip-normals reverses them), "
      "and the tracer follows normal grids onto a sheet tilted out of its seed plane while a grow with grids for "
      "the mirror sheet misses it (otherwise the check is VOID). With default weights the tracer reads nothing from "
      "the volume, so this covers its normal-grid reader, not its use of a surface prediction. Records the result "
      "for status.",
      {"threads": INT("OpenMP threads", minimum=1), "timeout": INT("seconds per tool call", minimum=10)})
def h_selftest(ctx, a):
    tools = ctx.tools()
    work = out_dir(ctx, None, "selftest", stamp())
    report = vc3d.selftest(tools, work, threads=a.get("threads", 1), timeout=a.get("timeout", 300))
    _save_selftest(ctx, tools, report)
    report["summary"] = vc3d.format_report(report)
    return report


@tool("list_tools", "List VC3D tools", "Every vc_* command line tool of this build with the first line of its "
      "help. Any of them runs through `run`.", readonly=True)
def h_list_tools(ctx, a):
    tools = ctx.tools()
    cache = ctx.home / "cache" / "tool-list.json"
    key = str(tools.bindir) + str(tools.path(vc3d.PROBE).stat().st_mtime_ns if tools.has(vc3d.PROBE) else "")
    try:
        data = json.loads(cache.read_text())
        if data.get("key") == key:
            return data["result"]
    except (OSError, json.JSONDecodeError):
        pass
    names = sorted(p.name for p in tools.bindir.iterdir() if p.name.startswith("vc_") or p.name == "VC3D") \
        if tools.bindir.is_dir() else []
    env = vc3d.headless_env(ctx.env)
    ctx.home.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in names:
        if name == "VC3D":
            rows.append({"tool": name, "summary": "the VC3D app; drive it with app_start and app_call"})
            continue
        try:
            r = subprocess.run(tools.argv(name, "--help"), capture_output=True, text=True, timeout=20, env=env,
                               cwd=str(ctx.home))
            lines = [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
            first = next((ln for ln in lines if not ln.lower().startswith(("allowed options", "usage"))), lines[0] if lines else "")
        except (OSError, subprocess.SubprocessError) as exc:
            first = f"(no help: {exc})"
        rows.append({"tool": name, "summary": first[:200]})
    result = {"bindir": str(tools.bindir), "tools": rows}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"key": key, "result": result}))
    return result


@tool("tool_help", "Tool help", "The full --help text of one VC3D tool.",
      {"tool": STR("tool name, e.g. vc_render_tifxyz")}, required=["tool"], readonly=True)
def h_tool_help(ctx, a):
    tools = ctx.tools()
    name = a["tool"]
    if not re.fullmatch(r"vc_[A-Za-z0-9_]+|VC3D", name) or not tools.has(name):
        raise ToolError(f"{name} is not a tool of {tools.bindir}; see list_tools")
    ctx.home.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(tools.argv(name, "--help"), capture_output=True, text=True, timeout=30,
                       env=vc3d.headless_env(ctx.env), cwd=str(ctx.home))
    return {"tool": name, "exit": r.returncode, "help": (r.stdout + r.stderr)[:20000]}


GUIDE = ROOT / "docs" / "vc3d-agents.md"


@tool("guide", "Guide", "How to use these tools well: the workflow, VC3D's rendering conventions, the "
      "repository's rules for ink work, tracing, troubleshooting. Without a topic: the list of topics.",
      {"topic": STR("a section heading of docs/vc3d-agents.md, or part of one")}, readonly=True)
def h_guide(ctx, a):
    text = GUIDE.read_text() if GUIDE.is_file() else INSTRUCTIONS
    sections = re.split(r"(?m)^## ", text)
    heads = {s.splitlines()[0].strip(): s for s in sections[1:]}
    topic = (a.get("topic") or "").strip().lower()
    missing = None if GUIDE.is_file() else (f"docs/vc3d-agents.md is not beside the kit package in {ROOT}: it "
                                            "ships with the source folder (pip install -e . from a copy of it)")
    if not topic:
        return {"instructions": INSTRUCTIONS, "topics": list(heads), **({"note": missing} if missing else {})}
    hits = sorted((h for h in heads if topic in h.lower()),  # an exact heading, then a prefix, then any match
                  key=lambda h: (h.lower() != topic, not h.lower().startswith(topic)))
    if not hits:
        raise ToolError(missing or f"no section matches {topic!r}; topics: {', '.join(heads)}")
    return {"topic": hits[0], "text": "## " + heads[hits[0]]}


# ---------------------------------------------------------------- tools: running VC3D

@tool("run", "Run a VC3D tool", "Run any vc_* tool with no display and capped thread pools; output goes to a "
      "log. S3 URLs among the arguments are given to the tool through kit's false-404 relay, and the empty-chunk "
      "markers of every URL are checked after the run. For the common steps prefer trace, render, flatten and "
      "check_surface, which also record receipts.",
      {"tool": STR("vc_* tool name"), "args": ARR("arguments, one per item", {"type": "string"}),
       "threads": INT("OpenMP threads (default: the CPU quota)", minimum=1),
       "timeout": INT("seconds before the run is stopped (default 3600)", minimum=1),
       "cwd": STR("working directory (default: the work home)")},
      required=["tool"], background=True)
def h_run(ctx, a):
    tools = ctx.tools()
    name = a["tool"]
    if not re.fullmatch(r"vc_[A-Za-z0-9_]+", name) or not tools.has(name):
        raise ToolError(f"{name} is not a vc_* tool of {tools.bindir} (the app runs through app_start)")
    cwd = resolve(ctx, a["cwd"]) if a.get("cwd") else ctx.home
    cwd.mkdir(parents=True, exist_ok=True)
    log = fresh(ctx.home / "runs" / f"{stamp()}-{name}.log")
    env = vc3d.headless_env(ctx.env, threads=a.get("threads"))
    args = [ctx.vc3d_url(x) if _is_s3(x) else x for x in a.get("args", [])]
    urls = dict.fromkeys(x for x in a.get("args", []) if is_url(x))
    guards = [g for g in (_cache_guard(ctx, u, ctx.vc3d_url(u) if _is_s3(u) else u) for u in urls) if g]
    for g in guards:
        g.before()
    rc, seconds = run_logged(ctx, tools.argv(name, *args), log, env=env,
                             timeout=a.get("timeout", 3600), cwd=str(cwd))
    out = {"tool": name, "exit": rc, "seconds": seconds, "log": str(log), "log_tail": tail(log, 30)}
    for g in guards:
        affected = g.after().get("affected") or []
        rep = g.summary()
        if affected:
            rep["read_as_empty"] = affected[:20]
            rep["warning"] = (f"this run may have read {len(affected)} chunks of {g.url} that exist as zeros (S3 "
                              "answered 404 for them); the cache is fixed now, so running it again reads them")
        out.setdefault("cache", []).append(rep)
    return out


def _segments_in(folder):
    return {p.name for p in Path(folder).iterdir() if p.is_dir() and (p / "meta.json").is_file()} \
        if Path(folder).is_dir() else set()


GRID_MARKER = "normal-grids-remote.json"   # villa NormalGridVolume.hpp: a grid folder holding it streams its files
GRID_MISSING_CHECKS = 400                  # missing-grid markers checked against the bucket after a run


def normal_grids_dir(ctx, grids):
    """(folder for the tracer's normal_grid_path, record). A local vc_gen_normalgrids folder is used as it is. A
    URL (a published .normal-grids/ folder) gets a cache folder under the kit home, named after the URL and shared
    by every trace of that grid set, and each run a view of it (open_grid_view) holding villa's streaming marker:
    VC3D then fetches only the grid files the trace touches, into the cache, for the next trace too. The record
    names the cache; close_grid_view removes the view after the run."""
    import hashlib
    if not is_url(grids):
        folder = existing(ctx, grids, "normal grids")
        if not (folder / "metadata.json").is_file() and not (folder / GRID_MARKER).is_file():
            raise ToolError(f"{folder} has no metadata.json: not a normal-grid folder (vc_gen_normalgrids writes one)")
        return folder, {"source": str(folder), "remote": False}
    url = str(grids).rstrip("/")
    name = slug(url.split("/")[-1] or "grids") + "-" + hashlib.sha256(url.encode()).hexdigest()[:8]
    cache = ctx.home / "normal-grids" / name
    cache.mkdir(parents=True, exist_ok=True)
    (cache / GRID_MARKER).unlink(missing_ok=True)   # older kit wrote it here; a view holds it now
    served = ctx.vc3d_url(url)
    view = open_grid_view(cache, served)
    return view, {"source": url, "remote": True, "served_from": served, "cache": str(cache)}


GRID_PLANES = ("xy", "xz", "yz")   # villa NormalGridVolume's plane folders


def open_grid_view(cache, served):
    """A folder of its own for one VC3D run over a streamed grid set: the marker naming this process's relay, and
    links to the cache's metadata and plane folders, so every grid file VC3D fetches lands in the cache. VC3D reads
    the marker once, when the trace starts. With one marker in the shared cache, each process rewrote it with its
    own relay's port, a trace that started a moment later took the other's relay, and lost its grids when that
    process ended: two traces run side by side on 9 Oct 2026 had 25 grid files of the second fail with HTTP 0
    after the first finished (inferred from the two relays' request counts and the times).

    The view is a temporary folder on local disk (the links point into the cache, wherever it is). Where links
    cannot be made, the cache itself gets the marker, as before."""
    import tempfile
    for plane in GRID_PLANES:
        (cache / plane).mkdir(parents=True, exist_ok=True)
    view = Path(tempfile.mkdtemp(prefix="kit-grids-"))
    try:
        for entry in sorted(cache.iterdir()):
            if entry.name != GRID_MARKER and not entry.name.endswith(".part"):
                (view / entry.name).symlink_to(entry.resolve(), target_is_directory=entry.is_dir())
    except OSError:
        shutil.rmtree(view, ignore_errors=True)
        view = cache
    tmp = view / (GRID_MARKER + ".tmp")
    tmp.write_text(json.dumps({"url": served}))
    tmp.replace(view / GRID_MARKER)
    return view


def close_grid_view(view, cache):
    """After the run: what VC3D wrote into the view itself rather than through its links (a level folder of a
    multiscale store, metadata it fetched) moves into the cache unless the cache has it, then the view goes."""
    view, cache = Path(view), Path(cache)
    if not view.is_dir() or view.resolve() == cache.resolve():
        return
    for top in sorted(view.iterdir()):
        if top.is_symlink() or top.name == GRID_MARKER:
            continue
        files = [top] if top.is_file() else [Path(d) / f for d, _, fs in os.walk(top) for f in fs]
        for f in files:
            dest = cache / f.relative_to(view)
            if ".tmp-" in f.name or dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
    shutil.rmtree(view, ignore_errors=True)


GRID_FETCH_FAILED = re.compile(r"normal-grid fetch (?:for (\S+) returned HTTP (\d+)|failed for (\S+?): (.*))")
GRID_REFETCH_TRIES = 4


def grid_fetch_failures(text):
    """{relative path: what VC3D said} for the grid files it could not fetch, from its log. VC3D leaves no marker
    for these (only a 404 gets one) and keeps a null grid for that slice for the rest of the run, so the trace grew
    there without that plane's normals; a later run asks again."""
    out = {}
    for m in GRID_FETCH_FAILED.finditer(text):
        rel = m.group(1) or m.group(3)
        out[rel] = f"HTTP {m.group(2)}" if m.group(1) else m.group(4).strip()
    return out


def refetch_grids(info, rels, opener=None, sleep=time.sleep, give_up=5):
    """Fetch grid files a run failed to fetch into the cache, with S3's false 404s and network failures retried.
    After `give_up` failures with nothing fetched it stops asking (the network is likely down) and counts the rest
    as failing. Returns (fetched, still failing as {rel: why})."""
    import urllib.error
    import urllib.request
    from . import s3retry
    cache, fetched, failed = Path(info["cache"]), [], {}
    for rel in rels:
        if len(failed) >= give_up and not fetched:
            failed[rel] = "not asked: the ones before it all failed"
            continue
        dest = cache / rel
        if dest.is_file() and dest.stat().st_size:
            fetched.append(rel)
            continue
        why = None
        for attempt in range(GRID_REFETCH_TRIES):
            req = urllib.request.Request(f"{info['source']}/{rel}", headers={"User-Agent": "kit-vc3d"})
            try:
                with s3retry.open_url(req, opener, timeout=120) as resp:
                    data = resp.read()
            except urllib.error.HTTPError as exc:
                why = f"HTTP {exc.code}"
                if exc.code < 500 and exc.code != 429:
                    break
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:   # cut-off reads too
                why = str(getattr(exc, "reason", exc)) or type(exc).__name__
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
                fetched.append(rel)
                why = None
                break
            if attempt + 1 < GRID_REFETCH_TRIES:
                sleep(min(8.0, 0.5 * 2 ** attempt))
        if why is not None:
            failed[rel] = why
    return fetched, failed


def grid_files(folder):
    """The grid files in a normal-grid folder or cache (partial downloads and markers are not counted)."""
    return sum(1 for _ in Path(folder).rglob("*.grid"))


def grid_missing(folder):
    """The grid files VC3D marked missing in a streaming folder (it writes <file>.missing on a 404 and never asks
    again), as paths relative to the folder."""
    return sorted(str(p.relative_to(folder))[:-len(".missing")] for p in Path(folder).rglob("*.missing"))


def check_grid_missing(info, before, opener=None):
    """After a run that streamed grids: the markers it added, each asked of the bucket again. A marker for a file
    the bucket holds came from a false 404 (S3 answers them from this cloud, kit/s3retry.py) and would hide that
    slice's normals from every later trace, so it is deleted; the record says how many there were, since this run
    went without them."""
    from . import s3retry
    folder = Path(info["cache"])
    new = [r for r in grid_missing(folder) if r not in before]
    false, unknown = [], []
    for rel in new[:GRID_MISSING_CHECKS]:
        state, _ = s3retry.key_state(f"{info['source']}/{rel}", opener=opener)
        if state == s3retry.PRESENT:
            (folder / (rel + ".missing")).unlink(missing_ok=True)
            false.append(rel)
        elif state != s3retry.MISSING:
            unknown.append(rel)
    out = {"missing": len(new), "missing_sample": new[:10], "false_missing": len(false),
           "unchecked": max(0, len(new) - GRID_MISSING_CHECKS) + len(unknown)}
    if false:
        out["warning"] = (f"{len(false)} grid files answered 404 during the run but are in the bucket; this trace "
                          "went without their normals, and the markers are removed so the next run reads them")
    return out


def check_grid_fetches(info, log, offset=0, opener=None):
    """After a run that streamed grids: the grid files VC3D failed to fetch, from its log since `offset`, fetched
    again into the cache so the next run has them. The record says how many failed, since this run went without
    their normals."""
    try:
        with open(log, "rb") as fh:
            fh.seek(offset)
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return {}
    failed = grid_fetch_failures(text)
    if not failed:
        return {"fetch_failed": 0}
    fetched, still = refetch_grids(info, sorted(failed)[:GRID_MISSING_CHECKS], opener)
    still.update({r: "not asked (over the limit)" for r in sorted(failed)[GRID_MISSING_CHECKS:]})
    out = {"fetch_failed": len(failed), "fetch_failed_sample": [f"{r}: {failed[r]}" for r in sorted(failed)[:10]],
           "refetched": len(fetched), "refetch_failed": len(still)}
    out["fetch_warning"] = (
        f"VC3D could not fetch {len(failed)} grid files during the run (HTTP 0 means no answer at all, after its "
        "retries); it went without those slices' normals for the rest of the run, so the trace grew near them "
        "without that plane's data term. " + (f"All {len(fetched)} are in the cache now; run the trace again for a "
                                               "result with them." if not still else
                                               f"{len(still)} still fail: {sorted(still)[:5]}"))
    return out


@tool("trace", "Trace a surface", "Grow a tifxyz surface with vc_grow_seg_from_seed on a surface-prediction "
      "volume (local zarr or URL): from a seed point, by resuming a surface for more generations, as the "
      "neighbouring sheet of a surface (gen_neighbor, rays along the normals), or by expansion over a folder of "
      "segments. Give normal_grids: without them no loss of the tracer reads the scan. Returns the new surfaces "
      "with their size and area.",
      {"volume": STR("surface prediction zarr (path or http/s3 URL); VC3D reads only the chunks it touches"),
       "mode": STR("seed (default), resume, gen_neighbor or expansion", enum=["seed", "resume", "gen_neighbor", "expansion"]),
       "seed": ARR("seed point x, y, z in level-0 voxels (seed mode; omit for a random seed)", {"type": "number"},
                   minItems=3, maxItems=3),
       "seed_check": BOOL("check an explicit seed first with seed_check and refuse one off the prediction or on "
                          "air (default true)"),
       "snap_seed": BOOL("move a seed that is off the prediction to the nearest voxel on it within 8 voxels "
                         "(default false: refuse)"),
       "ct": STR("CT volume in the same frame (path or URL), for the seed's papyrus or air check"),
       "resume": STR("tifxyz to resume (resume) or to start from (gen_neighbor)"),
       "generations": INT("total generation count to stop at (resume: must exceed the surface's)", minimum=1),
       "neighbor_dir": STR("gen_neighbor: in or out along the normals", enum=["in", "out"]),
       "voxel_um": NUM("voxel size in um (needed for min_area_cm when the volume has no metadata)"),
       "params": OBJ("extra JSON parameters for the tracer, merged last (see villa's vc_grow_seg_from_seed)"),
       "normal_grids": STR("the prediction's normal grids: a local vc_gen_normalgrids folder, or the URL of a "
                           "published .normal-grids/ folder, streamed into a local cache as the trace needs them. "
                           "They feed the tracer's normal and snap losses, its only terms that read the scan; "
                           "without them a surface is the seed extrapolated by smoothness. The grids set the step "
                           "(their spiral-step), so do not pass step_size with them"),
       "out": STR("folder the tracer writes segments into (default work/vc3d/traces/<time>)"),
       "name": STR("segment name: write into out/name instead of a timestamped subfolder"),
       "threads": INT("tracer threads (default min(4, CPUs): it does not scale past a few)", minimum=1),
       "cache_reruns": INT("URL volumes: trace again from scratch when VC3D cached a chunk that exists as empty "
                           "during the run (default 0: the result says so, and the cache is fixed for the next run)",
                           minimum=0),
       "timeout": INT("seconds (default 6 h)", minimum=1)},
      required=["volume"], background=True, openworld=True)
def h_trace(ctx, a):
    views = []   # (view, cache) of streamed normal grids, removed whatever happens
    try:
        return _trace(ctx, a, views)
    finally:
        for view, cache in views:
            close_grid_view(view, cache)


def _trace(ctx, a, views):
    tools = ctx.tools()
    if not tools.has(vc3d.TRACER):
        raise ToolError(f"{vc3d.TRACER} is not in {tools.bindir}")
    mode = a.get("mode", "seed")
    volume = a["volume"] if is_url(a["volume"]) else str(existing(ctx, a["volume"], "volume", "zarr"))
    started = now()
    seed_info = None
    out = out_dir(ctx, a.get("out"), "traces", stamp())
    threads = threads_for(ctx, a, cap=None) if a.get("threads") else min(4, vc3d.cpu_limit())
    params = {"mode": "seed" if mode in ("seed", "resume") else mode, "thread_limit": threads}
    if a.get("generations"):
        params["generations"] = a["generations"]
    if a.get("voxel_um"):
        params["voxelsize"] = a["voxel_um"]
    if mode == "gen_neighbor":
        params["neighbor_dir"] = a.get("neighbor_dir", "out")
    grid_info = grid_before = files_before = None
    if a.get("normal_grids"):
        folder, grid_info = normal_grids_dir(ctx, a["normal_grids"])
        params["normal_grid_path"] = str(folder)
        if grid_info["remote"]:
            views.append((folder, grid_info["cache"]))
            grid_before = set(grid_missing(grid_info["cache"]))
            files_before = grid_files(grid_info["cache"])
    params.update(a.get("params") or {})
    pfile = out / f"params-{stamp()}.json"
    pfile.write_text(json.dumps(params, indent=1))
    target = out / a["name"] if a.get("name") else out
    argv = ["-v", ctx.vc3d_url(volume) if is_url(volume) else volume, "-t", target, "-p", pfile]
    if mode in ("resume", "gen_neighbor"):
        if not a.get("resume"):
            raise ToolError(f"mode {mode} needs resume=<tifxyz folder>")
        argv += ["--resume", existing(ctx, a["resume"], "surface", "tifxyz")]
    elif a.get("seed"):
        seed = list(a["seed"])
        if a.get("seed_check", True):
            check = vc3d_prep_tools.check_seed(sys.modules[__name__], ctx, volume, seed, ct=a.get("ct"))
            if not check["on_prediction"] and a.get("snap_seed") and check.get("nearest_on"):
                before_snap, moved_from = check, seed
                seed = list(check["nearest_on"])
                # Both checks and the recorded verdict must describe the seed passed to the tracer.
                check = vc3d_prep_tools.check_seed(sys.modules[__name__], ctx, volume, seed, ct=a.get("ct"))
                check["moved_from"], check["before_snap"] = moved_from, before_snap
            if not check["on_prediction"]:
                near = (f"; the nearest voxel on it is {check['nearest_on']}, {check['nearest_distance']} voxels "
                        "away (snap_seed moves there)") if check.get("nearest_on") else \
                    f"; nothing within {check['radius']} voxels is"
                raise ToolError(f"seed {seed} is off the surface prediction (value {check['value']}, the tracer "
                                f"needs {check['threshold']}){near}. seed_check false skips this check")
            if check.get("ct", {}).get("verdict") == "air":
                why = check["ct"].get("why") or "below the papyrus and air midpoint"
                raise ToolError(f"seed {seed} is on air in the CT ({why}); pick a seed on a sheet, "
                                "or seed_check false")
            seed_info = check
        argv += ["-s", *[str(v) for v in seed]]
    if a.get("name"):
        target.mkdir(parents=True, exist_ok=True)
        argv += ["--segment-name", a["name"]]
    before = _segments_in(out)
    log = out / "trace.log"
    log_from = log.stat().st_size if log.is_file() else 0
    env = vc3d.headless_env(ctx.env, threads=threads)

    def reset():   # a trace run again starts clean: the surfaces of the run before are removed
        for n in sorted(_segments_in(out) - before):
            shutil.rmtree(out / n, ignore_errors=True)
        if a.get("name"):
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)

    rc, seconds, cache = _guarded(
        ctx, _cache_guard(ctx, volume),
        lambda: run_logged(ctx, tools.argv(vc3d.TRACER, *argv), log, env=env, timeout=a.get("timeout", 6 * 3600),
                           cwd=str(out)),
        reset, a.get("cache_reruns", 0))
    new = [target] if a.get("name") and (target / "meta.json").is_file() else \
        [out / n for n in sorted(_segments_in(out) - before)]
    surfaces = []
    for s in new:
        try:
            surfaces.append(tifxyz_stats(s, a.get("voxel_um")))
        except (vc3d_io.IOFormatError, OSError, KeyError) as exc:
            surfaces.append({"path": str(s), "error": str(exc)})
    result = {"exit": rc, "seconds": seconds, "mode": mode, "volume": volume, "out": str(out), "surfaces": surfaces,
              "log": str(log), "log_tail": tail(log, 15)}
    if cache is not None:
        result["cache"] = cache
    if seed_info is not None:
        result["seed_check"] = seed_info
    if grid_info is not None:
        if grid_info["remote"]:
            for view, cache_dir in views:
                close_grid_view(view, cache_dir)
        folder = Path(grid_info.get("cache") or params["normal_grid_path"])
        # files: the grid files in the folder after the run; for streamed grids that is the shared cache, so the
        # total over every trace of that grid set so far, not this run's. files_fetched is what the cache gained
        # during this run (files minus files_before), which includes what a trace of the same grid set running at
        # the same time fetched, and not the files refetched below
        grid_info["files"] = grid_files(folder)
        if grid_info["remote"]:
            grid_info["files_before"] = files_before
            grid_info["files_fetched"] = grid_info["files"] - files_before
            grid_info.update(check_grid_missing(grid_info, grid_before))
            grid_info.update(check_grid_fetches(grid_info, log, log_from))
        result["normal_grids"] = grid_info
    elif "normal_grid_path" not in params:
        result["data_term"] = ("none: no normal grids, so no loss of the tracer read the scan and the surface is the "
                               "seed extrapolated by smoothness; give normal_grids")
    if rc == 0 and not surfaces:
        result["note"] = "the tracer exited 0 but wrote no surface; read the log (no seed found, or area below min_area_cm)"
    elif any(s.get("valid_vertices") == 0 for s in surfaces):
        result["note"] = ("a new surface has no valid vertex" + (
            ": no ray met the neighbouring sheet; try the other neighbor_dir, or set params neighbor_max_distance, "
            "neighbor_threshold (default 1) or neighbor_min_clearance" if mode == "gen_neighbor" else ""))
    result["receipt"] = write_receipt(ctx, out, "trace", a, [{"argv": argv, "exit": rc, "seconds": seconds}],
                                      [s.get("path") for s in surfaces], started, params=params,
                                      inputs={"volume": light_fingerprint(volume)}, cache=cache)
    return result


def _remote_args(ctx, volume, caps=None):
    """Renderer arguments for a remote volume. Builds that take a URL as --volume (accepts_url_volume) get the
    URL there; older builds get a local cache folder as --volume and the URL as --remote-url. Either way the
    fetched chunks go to VC3D's shared remote cache, as the tracer's do."""
    if caps and caps.get("volume_url"):
        return ["--volume", ctx.vc3d_url(volume)]
    cache = ctx.home / "volume-cache" / slug(volume.rstrip("/").split("/")[-1] or "remote")
    cache.mkdir(parents=True, exist_ok=True)
    return ["--volume", cache, "--remote-url", ctx.vc3d_url(volume)]


CACHE_RERUNS = 2   # runs again after a run that read a chunk VC3D cached as empty by mistake


def _cache_guard(ctx, volume, vc_url=None):
    """A vc3d_cache.Guard for a remote volume: VC3D caches a chunk that answered 404 as empty for good, and S3
    sometimes answers 404 for chunks that exist. vc_url is the URL VC3D is given (default: the relay's, as
    render and trace give it), which names the cache folder. None for a local volume or with
    KIT_VC3D_CACHE_CHECK=0."""
    if not volume or not is_url(str(volume)) or ctx.env.get("KIT_VC3D_CACHE_CHECK") == "0":
        return None
    return vc3d_cache.Guard(str(volume), env=ctx.env, ledger_dir=ctx.home / "cache" / "vc3d-empty",
                            cache_url=vc_url or ctx.vc3d_url(volume))


def _guarded(ctx, guard, run, reset=None, reruns=CACHE_RERUNS):
    """run() -> (rc, seconds) with a remote volume's empty-chunk markers checked before and after (false ones are
    deleted). A run that exits 0 but may have read a chunk that exists as zeros is repeated after reset(), up to
    `reruns` times. Returns (rc, seconds over all runs, cache report or None)."""
    if guard is None:
        rc, seconds = run()
        return rc, seconds, None
    guard.before()
    relay0 = ctx.relay_stats(guard.url) or {}
    total, runs = 0.0, 0
    while True:
        rc, seconds = run()
        total += seconds
        runs += 1
        affected = guard.after().get("affected") or []
        if rc != 0 or not affected or runs > reruns:
            break
        ctx.say(f"{len(affected)} chunks VC3D cached as empty exist in the bucket (false 404s); fixed in the "
                "cache, running again")
        if reset:
            reset()
    info = {**guard.summary(), "runs": runs}
    relay = ctx.relay_stats(guard.url)
    if relay:
        info["relay"] = {"vc3d_url": guard.cache_url, **{k: v - relay0.get(k, 0) for k, v in relay.items()}}
    if rc == 0 and affected:
        info["read_as_empty"] = affected[:20]
        info["warning"] = (f"this run may have read {len(affected)} chunks that exist as zeros (S3 answered 404 "
                           "for them); the cache is fixed now, so running it again reads them")
    return rc, total, info


def _catalog(ctx, fetch=False):
    """The open-data catalog from the cache (fetched first when fetch is true and it is missing or a day
    old), or None. Tools that only want a hint from it never wait on the network for it."""
    cache = ctx.home / "cache"
    try:
        if fetch:
            return vc3d_catalog.load(cache)
        if (cache / "open-data-metadata.json").is_file():
            return vc3d_catalog.load(cache, max_age=10 ** 9)
    except (vc3d_catalog.CatalogError, OSError, ValueError):
        return None
    return None


def _catalog_voxel(ctx, url):
    cat = _catalog(ctx)
    hit = vc3d_catalog.volume_for_url(cat, url) if cat else None
    return hit[1].get("voxel_um") if hit else None


def _umbilicus(ctx, a, volume=None):
    """(control points, where they came from) for a's umbilicus (a file or URL) or the catalog's for the
    volume; (None, why not) when there is none. The catalog is fetched only for open-data URLs."""
    src, scale, origin = a.get("umbilicus"), a.get("umbilicus_scale", 1.0), "given"
    if not src and volume:
        cat = _catalog(ctx, fetch=is_url(volume) and "vesuvius-challenge-open-data" in str(volume))
        src, origin = (vc3d_catalog.umbilicus_for(cat, str(volume)) if cat else None), "catalog"
        if not src:
            return None, "no umbilicus given and none in the catalog for this volume" + \
                ("" if cat else " (no catalog cached here; the catalog tool fetches it)")
    if not src:
        return None, "no umbilicus given"
    if is_url(src):
        path = ctx.home / "cache" / "umbilicus" / slug(src.rstrip("/").split("/")[-1], 120)
        if not path.is_file():
            try:
                vc3d_catalog.download(src, path, timeout=60)
            except (OSError, vc3d_catalog.CatalogError) as exc:
                raise ToolError(f"cannot fetch the umbilicus {src}: {exc}") from exc
    else:
        path = existing(ctx, src, "umbilicus")
    try:
        pts = vc3d_orient.load_umbilicus(path, scale)
    except (vc3d_orient.OrientError, ValueError) as exc:
        raise ToolError(f"umbilicus {src}: {exc}") from exc
    info = {"source": str(src), "from": origin, "points": len(pts), "z_range": [pts[0][0], pts[-1][0]]}
    if scale != 1:
        info["scale"] = scale
    return pts, info


def _render_orientation(ctx, surface, a, volume):
    """Decide the team order's flag from the surface's own geometry when an umbilicus is known (one sign per
    patch, by an area-weighted vote); otherwise VC3D's usual flag. A surface with no clear sign is refused."""
    if not a.get("orientation_check", True):
        return {"checked": False, "why": "orientation_check is false"}
    if a.get("flatten"):
        return {"checked": False, "why": "flatten re-parametrises the surface inside the renderer; check the "
                                         "flattened tifxyz with the orientation tool"}
    try:
        umb, info = _umbilicus(ctx, a, volume)
    except ToolError as exc:
        if a.get("umbilicus"):
            raise
        return {"checked": False, "why": str(exc)}
    if umb is None:
        return {"checked": False, "why": info}
    box = crop_grid_box(surface, a)
    try:
        res = vc3d_orient.orientation(surface, umbilicus=umb, scale_segmentation=a.get("scale_segmentation", 1.0),
                                      affine=a.get("affine"), grid_box=box)
    except (vc3d_orient.OrientError, vc3d_io.IOFormatError) as exc:
        return {"checked": False, "why": str(exc)}
    n = res["normal"]
    where = "the cropped part of this surface" if box else "this surface"
    if n["confidence"] == "ambiguous":
        raise ToolError(f"team order needs one clear normal sign, and {where} has none against the umbilicus "
                        f"(outward share {n['outward_share']}): {res['advice']}. Split the surface, check the "
                        "umbilicus, render order=normal on purpose, or pass orientation_check=false to use VC3D's "
                        "usual --flip-normals anyway.")
    out = {"checked": True, "vote": n["vote"], "outward_share": n["outward_share"], "confidence": n["confidence"],
           "layout": res["layout"], "umbilicus": info, "advice": res["advice"]}
    if box:
        out["grid_box"] = res["grid_box"]
    return out


def crop_grid_box(surface, a):
    """The grid rows and columns [row0, row1, col0, col1) that a render's crop covers, one vertex wider on each
    side, or None without a crop. A grid step is scale_segmentation x scale / (meta scale x 2^level) output pixels,
    times the cube root of an affine's determinant (the pixel registration the self-test measures)."""
    if not a.get("crop"):
        return None
    meta = json.loads((surface / "meta.json").read_text()) if (surface / "meta.json").is_file() else {}
    sx, sy = (meta.get("scale") or [1.0, 1.0])[:2]
    k = a.get("scale_segmentation", 1.0) * a.get("scale", 1) / 2 ** a.get("level", 0)
    if a.get("affine"):
        m = a["affine"]
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        k *= abs(det) ** (1 / 3)
    x, y, w, h = a["crop"]
    kx, ky = k / sx, k / sy   # output pixels per grid column, per grid row
    return [max(0, math.floor(y / ky) - 1), math.ceil((y + h) / ky) + 1,
            max(0, math.floor(x / kx) - 1), math.ceil((x + w) / kx) + 1]


def reverse_tif_layers(folder):
    """Reverse the layer order of a --tif-output folder in place (what --flip-normals would have given)."""
    files = vc3d_io.layer_files(folder)
    n = len(files)
    tmp = [Path(folder) / f".kit-reverse-{k}.tif" for k in range(n)]
    for f, t in zip(files, tmp):
        f.rename(t)
    for k, t in enumerate(tmp):
        t.rename(files[n - 1 - k])
    return n


def tif_to_zarr(folder, dest, compressor="blosc"):
    """Stack a layer folder into an OME-Zarr group (level "0"), the layout villa's ink inference reads."""
    import numpy as np
    import tifffile
    import zarr
    files = vc3d_io.layer_files(folder)
    first = tifffile.imread(files[0])
    data = np.empty((len(files), *first.shape), dtype=first.dtype)
    for k, f in enumerate(files):
        data[k] = tifffile.imread(f)
    group = zarr.open_group(str(dest), mode="w")
    chunks = (len(files), min(128, data.shape[1]), min(128, data.shape[2]))
    if hasattr(group, "create_array"):
        group.create_array("0", data=data, chunks=chunks)
    else:
        group.create_dataset("0", data=data, chunks=chunks)
    group.attrs["multiscales"] = [{"version": "0.4", "axes": [{"name": a, "type": "space"} for a in "zyx"],
                                   "datasets": [{"path": "0"}]}]
    return list(data.shape)


@tool("render", "Render a surface volume", "Render the layer stack along a tifxyz surface with "
      "vc_render_tifxyz: num-slices layers along the normal, trilinear, in the team's layer order by default "
      "(--flip-normals; on older binaries kit reverses the layers itself). Presets match published products "
      "(9um: 28 layers, 2um: 109, 1um: 116, legacy: 65). Volume may be a local zarr or a URL (streamed, "
      "retried on network drops). Writes a receipt next to the output.",
      {"surface": STR("tifxyz folder"), "volume": STR("CT volume: OME-Zarr path or http/s3 URL"),
       "preset": STR("layer preset (default 9um)", enum=sorted(PRESETS)),
       "layers": INT("number of layers (overrides the preset)", minimum=1),
       "slice_step": NUM("voxels between layers (default 1)"),
       "order": STR("team (default; layer index grows toward the scroll centre, as published renders and "
                    "training labels) or normal (VC3D's default, toward d/dcol x d/drow)", enum=["team", "normal"]),
       "scale": NUM("output pixels per voxel of the chosen level (default 1)"),
       "level": INT("OME-Zarr pyramid level to sample (default 0)", minimum=0),
       "scale_segmentation": NUM("multiply the surface coordinates first (e.g. 0.25 for a level-0 mesh on a 4x binned volume)"),
       "format": STR("zarr (default), tif (00.tif, 01.tif, ...: v8in's input) or both", enum=["zarr", "tif", "both"]),
       "compressor": STR("zarr compressor (default blosc when numcodecs is installed here, else gzip, which the "
                         "standard library reads)", enum=["blosc", "zstd", "gzip", "lz4", "none"]),
       "crop": ARR("output window x, y, width, height in pixels", {"type": "integer"}, minItems=4, maxItems=4),
       "auto_crop": BOOL("crop to the valid surface bounding box"),
       "voxel_um": NUM("voxel size in um, written to the output metadata (looked up in the catalog for open-data URLs)"),
       "interpolation": STR("surface resampling: linear (VC3D default) or smooth", enum=["linear", "smooth"]),
       "affine": ARR("3x4 affine (rows of x, y, z) applied to the surface, e.g. from catalog transforms",
                     {"type": "array"}, minItems=3, maxItems=4),
       "flatten": BOOL("ABF++ flatten before rendering"),
       "composite": OBJ("one composite image instead of layers: {start, end, reducer: max|mean|median|alpha|beerlambert}"),
       "out": STR("output folder (default work/vc3d/renders/<surface>-<time>)"),
       "cache_gb": INT("chunk cache size (default 4)", minimum=1),
       "retries": INT("extra attempts after a failure (default 2 for URLs, 0 for local volumes)", minimum=0),
       "cache_reruns": INT("URL volumes: runs again when VC3D cached a chunk that exists as empty (S3 sometimes "
                           "answers 404 for chunks it holds; the markers are checked and fixed after every run). "
                           "Default 2", minimum=0),
       "threads": INT("OpenMP threads", minimum=1), "timeout": INT("seconds per attempt (default 12 h)", minimum=1),
       "umbilicus": STR("umbilicus file or URL (villa formats) for the team order check; default: the catalog's "
                        "for open-data volumes"),
       "orientation_check": BOOL("team order: decide the flag from the surface's normal against the umbilicus when "
                                 "one is known (default true); false always uses --flip-normals"),
       "extra_args": ARR("further vc_render_tifxyz arguments", {"type": "string"}),
       "allow_lossy": BOOL("render from a lossy volcomp copy anyway (default false: refused). Geometry checks and "
                           "previews only: the receipt marks the render, and the ink tool warns on it")},
      required=["surface", "volume"], background=True, openworld=True)
def h_render(ctx, a):
    tools = ctx.tools()
    caps = capabilities(ctx, tools)
    surface = existing(ctx, a["surface"], "surface", "tifxyz")
    volume = a["volume"]
    remote = is_url(volume)
    if not remote:
        volume = str(existing(ctx, volume, "volume", "zarr"))
    lossy = vc3d_io.volcomp_source(volume)
    if lossy and not a.get("allow_lossy"):
        raise ToolError(f"{lossy}. Pass allow_lossy=true only for geometry checks or previews, never for an ink input.")
    preset = PRESETS[a.get("preset", "9um")]
    layers = a.get("layers", preset["layers"])
    step = a.get("slice_step", preset["slice_step"])
    order = a.get("order", "team")
    fmt = a.get("format", "zarr")
    started = now()
    out = out_dir(ctx, a.get("out"), "renders", f"{slug(surface.name)}-{stamp()}")
    argv = ["--segmentation", surface, "--scale", a.get("scale", 1), "--group-idx", a.get("level", 0)]
    argv += _remote_args(ctx, volume, caps) if remote else ["--volume", volume]
    composite = a.get("composite")
    if composite:
        argv += ["--composite-start", composite.get("start", -layers // 2), "--composite-end",
                 composite.get("end", layers // 2), "--composite-collapse", "--accum-type", composite.get("reducer", "max")]
    else:
        argv += ["--num-slices", layers, "--slice-step", step]
    argv += ["--cache-gb", a.get("cache_gb", 4)]
    voxel = a.get("voxel_um") or (_catalog_voxel(ctx, volume) if remote else None)
    if voxel:
        argv += ["--voxel-size", voxel, "--voxel-unit", "micrometer"]
    if a.get("scale_segmentation"):
        argv += ["--scale-segmentation", a["scale_segmentation"]]
    if a.get("crop"):
        x, y, w, h = a["crop"]
        argv += ["--crop-x", x, "--crop-y", y, "--crop-width", w, "--crop-height", h]
    if a.get("auto_crop"):
        argv += ["--auto-crop"]
    if a.get("interpolation"):
        if not caps.get("surface_interpolation"):
            raise ToolError("this renderer has no --surface-interpolation; build villa main")
        argv += ["--surface-interpolation", a["interpolation"]]
    if a.get("affine"):
        (out / "affine.json").write_text(json.dumps({"transformation_matrix": a["affine"]}))
        argv += ["--affine", out / "affine.json"]
    if a.get("flatten"):
        argv += ["--flatten"]
    orient = _render_orientation(ctx, surface, a, volume) if order == "team" and not composite else None
    flip = order == "team" and not composite and (orient or {}).get("vote", "outward") == "outward"
    emulate = flip and not caps.get("flip_normals")
    if flip and caps.get("flip_normals"):
        argv += ["--flip-normals"]
    zarr_out = out / "layers.zarr" if fmt in ("zarr", "both") else None
    tif_out = out / "layers" if fmt in ("tif", "both") else None
    if emulate and zarr_out is not None:
        if not numpy_stack():
            raise ToolError("this renderer lacks --flip-normals, and putting a zarr render in team order then needs "
                            "numpy, tifffile and zarr here. Use format=tif (kit reverses the files), order=normal, "
                            "or a current villa build.")
        tif_out = tif_out or out / ".layers-normal-order"
    if zarr_out is not None and not emulate:
        argv += ["--zarr-output", zarr_out]
        if caps.get("zarr_compressor"):
            comp = a.get("compressor") or ("blosc" if _have("numcodecs") else "gzip")
            argv += ["--zarr-compressor", comp]
    if tif_out is not None:
        argv += ["--tif-output", tif_out]
    argv += a.get("extra_args", [])
    retries = a.get("retries", 2 if remote else 0)
    env = vc3d.headless_env(ctx.env, threads=a.get("threads"))
    log = out / "render.log"
    steps = []

    def run_all():
        for attempt in range(retries + 1):
            args_now = argv + (["--resume"] if attempt and zarr_out is not None and not emulate else [])
            rc, seconds = run_logged(ctx, tools.argv(vc3d.PROBE, *args_now), log, env=env,
                                     timeout=a.get("timeout", 12 * 3600), cwd=str(out))
            steps.append({"argv": [str(v) for v in args_now], "exit": rc, "seconds": seconds})
            if rc == 0 or rc in ("cancelled", "timeout") or str(rc).startswith("could not start"):
                break
            ctx.say(f"render attempt {attempt + 1} exited {rc}; retrying")
        return rc, 0.0

    def reset():
        for path in (zarr_out, tif_out):
            if path is not None and Path(path).exists():
                shutil.rmtree(path)

    rc, _, cache = _guarded(ctx, _cache_guard(ctx, volume) if remote else None, run_all, reset,
                            a.get("cache_reruns", CACHE_RERUNS))
    result = {"exit": rc, "out": str(out), "attempts": len(steps), "seconds": sum(s["seconds"] for s in steps),
              "log": str(log)}
    if cache is not None:
        result["cache"] = cache
    if orient is not None:
        result["orientation"] = orient
    if rc != 0:
        result["log_tail"] = tail(log, 25)
        result["receipt"] = write_receipt(ctx, out, "render", a, steps, [], started, orientation=orient, cache=cache)
        return result
    if emulate:
        n = reverse_tif_layers(tif_out)
        result["order"] = f"team: {n} layers reversed by kit (this binary lacks --flip-normals)"
        if zarr_out is not None:
            result["zarr_shape"] = tif_to_zarr(tif_out, zarr_out)
            if fmt == "zarr":
                shutil.rmtree(tif_out)
                tif_out = None
    elif composite:
        result["order"] = "composite"
    elif order == "team":
        result["order"] = "team (--flip-normals)" if flip else \
            "team (no flag: this surface's +N already points toward the centre)"
    else:
        result["order"] = "VC3D default (+N, toward d/dcol x d/drow)"
    if zarr_out is not None:
        result["zarr"] = str(zarr_out)
        try:
            result["levels"] = vc3d_io.zarr_levels(zarr_out)
            result["shape"] = result["levels"][0][1]
        except vc3d_io.IOFormatError as exc:
            result["zarr_error"] = str(exc)
    if tif_out is not None:
        files = vc3d_io.layer_files(tif_out)
        result["tif_dir"] = str(tif_out)
        if files:
            info = vc3d_io.tiff_info(files[0])
            result.setdefault("shape", [len(files), info["height"], info["width"]])
    outputs = [p for p in (result.get("zarr"), result.get("tif_dir")) if p]
    result["receipt"] = write_receipt(ctx, out, "render", a, steps, outputs, started, order=result["order"],
                                      layers=layers, slice_step=step, preset=a.get("preset", "9um"),
                                      inputs={"surface": light_fingerprint(surface), "volume": light_fingerprint(volume)},
                                      conventions=(caps.get("selftest") or {}).get("conventions"), orientation=orient,
                                      cache=cache, **({"lossy_source": lossy} if lossy else {}))
    if lossy:
        result["warnings"] = result.get("warnings", []) + [lossy]
    return result


def _have(module):
    import importlib.util
    return importlib.util.find_spec(module) is not None


@tool("flatten", "Flatten a surface", "ABF++ (or LSCM) flattening of a tifxyz surface with vc_flatten, giving a "
      "new tifxyz whose grid is the flattened layout (render it like any surface).",
      {"surface": STR("tifxyz folder"), "out": STR("output tifxyz folder (default work/vc3d/flat/<name>-<time>)"),
       "iterations": INT("ABF++ iterations (default 10)", minimum=1),
       "downsample": INT("compute on every n-th vertex (1, 2 or 4)", minimum=1),
       "lscm_only": BOOL("LSCM only, skip ABF++"), "no_scale": BOOL("do not rescale to the 3D area"),
       "timeout": INT("seconds (default 4 h)", minimum=1)},
      required=["surface"], background=True)
def h_flatten(ctx, a):
    tools = ctx.tools()
    if not tools.has("vc_flatten"):
        raise ToolError(f"vc_flatten is not in {tools.bindir}")
    surface = existing(ctx, a["surface"], "surface", "tifxyz")
    started = now()
    out = writable(ctx, a["out"]) if a.get("out") else fresh(ctx.home / "flat" / f"{slug(surface.name)}-{stamp()}")
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = ["-i", surface, "-o", out, "--iterations", a.get("iterations", 10), "--downsample", a.get("downsample", 1)]
    argv += ["--lscm-only"] if a.get("lscm_only") else []
    argv += ["--no-scale"] if a.get("no_scale") else []
    log = out.parent / f"{out.name}.log"
    rc, seconds = run_logged(ctx, tools.argv("vc_flatten", *argv), log, env=vc3d.headless_env(ctx.env),
                             timeout=a.get("timeout", 4 * 3600))
    result = {"exit": rc, "seconds": seconds, "out": str(out), "log": str(log)}
    if rc == 0 and vc3d_io.is_tifxyz(out):
        result["surface"] = tifxyz_stats(out)
        result["receipt"] = write_receipt(ctx, out, "flatten", a, [{"argv": [str(v) for v in argv], "exit": rc}],
                                          [str(out)], started, inputs={"surface": light_fingerprint(surface)})
    else:
        result["log_tail"] = tail(log, 25)
    return result


# ---------------------------------------------------------------- tools: inspecting and checking

@tool("inspect", "Inspect a path", "Describe a tifxyz surface (grid, valid fraction, extent, edge lengths, area, "
      "render size), a zarr (levels, shapes, chunks, compressor), a layer folder, a TIFF, an .npy or a receipt.",
      {"path": STR("file or folder"), "voxel_um": NUM("voxel size in um, for areas in cm2")},
      required=["path"], readonly=True)
def h_inspect(ctx, a):
    p = existing(ctx, a["path"])
    if vc3d_io.is_tifxyz(p):
        return {"kind": "tifxyz", **tifxyz_stats(p, a.get("voxel_um"))}
    if vc3d_io.is_zarr(p):
        levels = vc3d_io.zarr_levels(p)
        z = vc3d_io.open_zarr(p)
        attrs = {}
        for f in (".zattrs", "zarr.json"):
            if (p / f).is_file():
                attrs = json.loads((p / f).read_text())
                break
        return {"kind": "zarr", "levels": levels, "dtype": z.kind, "chunks": z.chunks, "compressor": z.compressor,
                "zarr_format": z.version, "attrs": {k: attrs[k] for k in list(attrs)[:12]}}
    if p.is_dir():
        files = vc3d_io.layer_files(p)
        if files:
            info = vc3d_io.tiff_info(files[0])
            return {"kind": "layer folder", "layers": len(files), "first": files[0].name, "last": files[-1].name,
                    "dtype": info["kind"], **{k: info[k] for k in ("height", "width", "compression")}}
        return {"kind": "folder", "entries": sorted(x.name for x in p.iterdir())[:200]}
    suffix = p.suffix.lower()
    if suffix in (".tif", ".tiff"):
        info = vc3d_io.tiff_info(p)
        info["dtype"] = info.pop("kind")
        return {"kind": "tiff", **info}
    if suffix == ".npy":
        with open(p, "rb") as fh:
            head = vc3d_io.npy_header(fh.read(4096))
        return {"kind": "npy", "shape": list(head["shape"]), "dtype": head["kind"]}
    if suffix == ".json":
        return {"kind": "json", "content": json.loads(p.read_text()[:200000])}
    return {"kind": "file", "bytes": p.stat().st_size}


def guard_preview(ctx, path):
    """A map under experiments/<slug>/ may be looked at only once its experiment exists (readout fixed)."""
    rel = in_repo(ctx, path)
    if rel is not None and len(rel.parts) > 1 and rel.parts[0] == "experiments":
        try:
            ledger.load(rel.parts[1], root=ctx.root / "experiments")
        except ledger.LedgerError as exc:
            raise ToolError(f"{path} belongs to experiment {rel.parts[1]!r}, which has no ledger record: "
                            f"preregister before looking ({exc})") from exc


def _load_plane(ctx, p, a):
    """A 2-D view of p for preview: (Raster float32, info). Reads the least it can."""
    mode = a.get("mode", "auto")
    max_side = a.get("max_side", 1024)
    box = a.get("box")
    info = {}
    if vc3d_io.is_tifxyz(p):
        ch = a.get("channel", "z")
        r = vc3d_io.read_tiff(p / f"{ch}.tif")
        vals = vc3d_io.array.array("f", (0.0 if v == -1 else float(v) for v in r.data))
        raster = vc3d_io.Raster(r.h, r.w, "f32", vals)
        info["view"] = f"tifxyz {ch} coordinate per grid vertex (invalid vertices black)"
        return _fit(raster, box, max_side, "mean", info)
    if vc3d_io.is_zarr(p):
        levels = vc3d_io.zarr_levels(p)
        name, shape = levels[0]
        full = shape
        if a.get("level") is not None:
            name, shape = next(((n, s) for n, s in levels if n == str(a["level"])), (None, None))
            if name is None:
                raise ToolError(f"{p} has no level {a['level']}; levels {[n for n, _ in levels]}")
        elif box is None:
            for n, s in levels:
                if max(s[-2:]) >= max_side:
                    name, shape = n, s
        z = vc3d_io.open_zarr(p, name or None)
        f = full[-1] / shape[-1]
        yx = [(0, shape[-2]), (0, shape[-1])]
        if box:
            yx = [(int(box[0] / f), int(math.ceil(box[1] / f))), (int(box[2] / f), int(math.ceil(box[3] / f)))]
        info.update(level=name or "array", level_shape=shape, full_shape=full)
        if len(shape) == 2:
            buf, sh = z.read(yx)
            return _fit(vc3d_io.Raster(sh[0], sh[1], z.kind, buf), None, max_side, "mean", info)
        n = shape[0]
        if mode in ("max", "mean", "min"):
            lo, hi = a.get("layers") or [0, n]
            buf, sh = z.read([(lo, hi), *yx])
            plane = sh[1] * sh[2]
            red = {"max": max, "min": min, "mean": lambda v: sum(v) / len(v)}[mode]
            vals = vc3d_io.array.array("f", (red([buf[k * plane + i] for k in range(sh[0])]) for i in range(plane)))
            info["view"] = f"{mode} over layers {lo}..{hi - 1}"
            return _fit(vc3d_io.Raster(sh[1], sh[2], "f32", vals), None, max_side, "mean", info)
        k = n // 2 if a.get("layer") is None else a["layer"]
        if not 0 <= k < n:
            raise ToolError(f"layer {k} outside 0..{n - 1}")
        buf, sh = z.read([(k, k + 1), *yx])
        info["view"] = f"layer {k} of {n}"
        return _fit(vc3d_io.Raster(sh[1], sh[2], z.kind, buf), None, max_side, "mean", info)
    if p.is_dir():
        files = vc3d_io.layer_files(p)
        if not files:
            images = sorted(x.name for x in p.iterdir() if x.suffix.lower() in (".tif", ".tiff", ".npy", ".png"))
            raise ToolError(f"{p} holds no numbered layer TIFFs" +
                            (f"; preview one of its files: {', '.join(images[:12])}" if images else ""))
        if mode in ("max", "mean", "min"):
            lo, hi = a.get("layers") or [0, len(files)]
            planes = [_read_image(f) for f in files[lo:hi]]
            red = {"max": max, "min": min, "mean": lambda v: sum(v) / len(v)}[mode]
            h, w = planes[0].h, planes[0].w
            vals = vc3d_io.array.array("f", (red([pl.data[i] for pl in planes]) for i in range(h * w)))
            info["view"] = f"{mode} over layers {lo}..{hi - 1} of {len(files)}"
            return _fit(vc3d_io.Raster(h, w, "f32", vals), box, max_side, "mean", info)
        k = len(files) // 2 if a.get("layer") is None else a["layer"]
        if not 0 <= k < len(files):
            raise ToolError(f"layer {k} outside 0..{len(files) - 1}")
        info["view"] = f"layer {k} of {len(files)} ({files[k].name})"
        return _fit(_read_image(files[k]), box, max_side, "mean", info)
    if p.suffix.lower() == ".npy":
        r = vc3d_io.read_npy(p, a.get("layer"))
        info["view"] = "array"
        return _fit(r, box, max_side, "mean", info)
    info["view"] = "image"
    return _fit(_read_image(p), box, max_side, "mean", info)


def _read_image(path):
    try:
        import numpy as np
        import tifffile
        arr = np.squeeze(tifffile.imread(str(path)))
        if arr.ndim == 2:
            return vc3d_io.Raster(arr.shape[0], arr.shape[1], "f32",
                                  vc3d_io.array.array("f", arr.astype(np.float32).tobytes()))
    except Exception:  # fall back to the standard-library reader (e.g. LZW without imagecodecs)
        pass
    return vc3d_io.read_tiff(path)


def _fit(raster, box, max_side, how, info):
    if box:
        y0, y1, x0, x1 = (int(v) for v in box)
        y0, x0 = max(0, y0), max(0, x0)
        y1, x1 = min(raster.h, y1), min(raster.w, x1)
        if y1 <= y0 or x1 <= x0:
            raise ToolError(f"box {box} is outside the {raster.h} x {raster.w} image")
        rows = [raster.data[r * raster.w + x0:r * raster.w + x1] for r in range(y0, y1)]
        data = vc3d_io.array.array("f")
        for row in rows:
            data.extend(vc3d_io.as_floats(row))
        raster = vc3d_io.Raster(y1 - y0, x1 - x0, "f32", data)
    factor = max(1, int(math.ceil(max(raster.h, raster.w) / max_side)))
    info["downsample"] = factor
    info["shown_shape"] = [raster.h // factor or 1, raster.w // factor or 1]
    return vc3d_io.downsample(raster, factor, how), info


@tool("preview", "Preview as PNG", "Look at a render, a layer stack, an ink map or a surface: one layer (default "
      "the middle), a max/mean/min over layers, a 2-D map, or a tifxyz coordinate grid, contrast-stretched to a PNG "
      "that is returned as an image and saved. Previews stay in ignored folders like everything else.",
      {"path": STR("zarr, layer folder, TIFF, .npy or tifxyz"),
       "mode": STR("auto (default), layer, max, mean or min", enum=["auto", "layer", "max", "mean", "min"]),
       "layer": INT("layer index (default the middle)", minimum=0),
       "layers": ARR("layer range [start, stop) for max/mean/min", {"type": "integer"}, minItems=2, maxItems=2),
       "level": STR("zarr pyramid level (default: the coarsest that still fills max_side)"),
       "box": ARR("window y0, y1, x0, x1 in full-resolution pixels", {"type": "integer"}, minItems=4, maxItems=4),
       "channel": STR("tifxyz coordinate to show (default z)", enum=["x", "y", "z"]),
       "max_side": INT("longest side of the PNG (default 1024)", minimum=16, maximum=4096),
       "percentiles": ARR("contrast stretch low, high (default 1, 99)", {"type": "number"}, minItems=2, maxItems=2),
       "range": ARR("fixed values for black and white instead of percentiles, e.g. [0, 255] for a uint8 ink map "
                    "or [0, 1] for a float one, so maps compare by eye", {"type": "number"}, minItems=2, maxItems=2),
       "invert": BOOL("dark ink on light papyrus"), "out": STR("PNG path (default under work/vc3d/previews)")},
      required=["path"], readonly=True)
def h_preview(ctx, a):
    p = existing(ctx, a["path"])
    guard_preview(ctx, p)
    raster, info = _load_plane(ctx, p, a)
    lo, hi = a.get("percentiles") or [1, 99]
    fixed = a.get("range") or [None, None]
    data, (vlo, vhi) = vc3d_io.to_u8(raster, lo, hi, skip_zero=True, invert=a.get("invert", False),
                                     lo=fixed[0], hi=fixed[1])
    png = vc3d_io.png_bytes(raster.h, raster.w, data)
    dest = writable(ctx, a["out"]) if a.get("out") else \
        fresh(ctx.home / "previews" / f"{slug(p.name)}-{a.get('mode', 'auto')}-{stamp()}.png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)
    st = vc3d_io.stats(raster)
    return {"png": str(dest), "path": str(p), **info, "stretch": [vlo, vhi],
            "values": {k: st[k] for k in ("min", "max", "mean", "nonzero_fraction")}, "_images": [str(dest)]}


@tool("check_surface", "Check a surface", "Can this surface be trusted? Grid sanity (valid fraction, spikes), "
      "self-intersections (vc_tifxyz_selfcross), the normal's sign against the umbilicus when one is known (as "
      "the orientation tool), and, given its volume, whether it sits on a papyrus sheet: a short stack is rendered "
      "across a window of the surface and the centre layer must be brighter than the layers a gap away on both "
      "sides (seating score, ported from axiosdevs/herculaneum-scroll-tools). windows spreads that over the "
      "surface, so a trace that leaves its sheet part way shows up; s_local adds the community's S_local "
      "sheet-profile score (exploratory). With frame_search the central window is also scored at other "
      "scale_segmentation values, so a mesh in the wrong frame (another scan or binning) shows up as a better "
      "score elsewhere. Stack depth scales with the voxel size (about 280 um either side).",
      {"surface": STR("tifxyz folder"), "volume": STR("CT volume the surface should sit in (path or URL)"),
       "level": INT("pyramid level to sample (default 0)", minimum=0),
       "scale_segmentation": NUM("coordinate scale to test (default 1)"),
       "frame_search": BOOL("also score scale_segmentation 2, 4, 0.5 and 0.25 on the central window"),
       "windows": INT("windows spread over the surface, the central one first (default 1, or 9 with s_local)",
                      minimum=1, maximum=25),
       "s_local": BOOL("also S_local: median over 40 random 0.3 mm columns of (max - median) / median of the "
                       "depth profile within +-131 um (community notes; needs the voxel size)"),
       "seed": INT("seed for S_local's columns (default 0)", minimum=0),
       "half_layers": INT("layers either side of the surface (default about 280 um of them: 30 at 9.362 um, "
                          "117 at 2.4 um; 30 when the voxel size is unknown)", minimum=3, maximum=200),
       "window": INT("square window in output pixels (default 192, or room for two S_local columns)",
                     minimum=16, maximum=2048),
       "material": INT("centre intensity above which a pixel is in material (default 40)", minimum=0, maximum=255),
       "selfcross": BOOL("run vc_tifxyz_selfcross (default true)"),
       "umbilicus": STR("umbilicus file or URL for the orientation check (default: the catalog's for the volume)"),
       "voxel_um": NUM("voxel size in um (default: the catalog's, or the size in an open-data volume's name)"),
       "cache_reruns": INT("URL volumes: renders a window again when VC3D cached a chunk that exists as empty "
                           "(default 2)", minimum=0),
       "threads": INT("threads", minimum=1), "timeout": INT("seconds per render (default 1800)", minimum=1)},
      required=["surface"], background=True, openworld=True)
def h_check_surface(ctx, a):
    tools = ctx.tools()
    surface = existing(ctx, a["surface"], "surface", "tifxyz")
    out = out_dir(ctx, None, "checks", f"{slug(surface.name)}-{stamp()}")
    result = {"surface": str(surface), "out": str(out)}
    grid = tifxyz_stats(surface, a.get("voxel_um"))
    result["grid"] = grid
    findings = []
    if grid["valid_fraction"] < 0.05:
        findings.append(f"only {grid['valid_fraction']:.1%} of the grid is valid")
    if grid.get("long_edges"):
        findings.append(f"{grid['long_edges']} grid edges are over 4x the median length (spikes or jumps)")
    env = vc3d.headless_env(ctx.env, threads=a.get("threads"))
    if a.get("selfcross", True) and tools.has("vc_tifxyz_selfcross"):
        rep = out / "selfcross.json"
        rc, _ = run_logged(ctx, tools.argv("vc_tifxyz_selfcross", "--surface", surface, "-o", rep, "--threads",
                                           threads_for(ctx, a)), out / "selfcross.log", env=env, timeout=3600)
        try:
            sc = json.loads(rep.read_text())
            transverse = sum(c.get("transverse", 0) for c in sc.get("census", []))
            result["selfcross"] = {"clean": sc.get("clean_of_transverse_self_intersection"), "transverse": transverse,
                                   "report": str(rep)}
            if transverse:
                findings.append(f"{transverse} transverse self-intersections (the trace passes through itself)")
        except (OSError, json.JSONDecodeError) as exc:
            result["selfcross"] = {"exit": rc, "error": str(exc), "log_tail": tail(out / "selfcross.log", 10)}
    if a.get("umbilicus") or a.get("volume"):
        result["orientation"] = orient = _surface_orientation(ctx, surface, a)
        if orient.get("checked") and orient["normal"]["confidence"] == "ambiguous":
            findings.append(f"orientation: no clear normal sign against the umbilicus ({orient['advice']})")
        elif orient.get("checked") and orient["normal"]["vote"] == "inward":
            findings.append("orientation: +N points toward the centre (" + orient["layout"] + "); render's team "
                            "order leaves out --flip-normals for it, and a stack rendered with that flag is reversed")
    if a.get("volume"):
        result["seating"] = _seating(ctx, tools, surface, a, out, env)
        seat = result["seating"]
        if seat.get("verdict") not in ("seated",):
            findings.append(f"seating: {seat.get('verdict')}" + (f" ({seat['seated_windows']} windows seated)"
                                                                if seat.get("seated_windows") else ""))
        if seat.get("better_frame"):
            findings.append(f"scores higher at scale_segmentation {seat['better_frame']}: the mesh may be in another frame")
    result["findings"] = findings
    result["verdict"] = "ok" if not findings else "look closer"
    return result


def _surface_orientation(ctx, surface, a):
    try:
        umb, info = _umbilicus(ctx, a, a.get("volume"))
    except ToolError as exc:
        if a.get("umbilicus"):
            raise
        return {"checked": False, "why": str(exc)}
    if umb is None:
        return {"checked": False, "why": info}
    try:
        o = vc3d_orient.orientation(surface, umbilicus=umb, scale_segmentation=a.get("scale_segmentation", 1.0))
    except (vc3d_orient.OrientError, vc3d_io.IOFormatError) as exc:
        return {"checked": False, "why": str(exc)}
    keep = ("normal", "team_order", "advice", "layout", "rows", "columns", "folds", "disagreeing_tiles")
    return {"checked": True, **{k: o.get(k) for k in keep}, "umbilicus": info}


def _seating(ctx, tools, surface, a, out, env):
    meta = json.loads((surface / "meta.json").read_text()) if (surface / "meta.json").is_file() else {}
    sx, sy = (meta.get("scale") or [1.0, 1.0])[:2]
    level = a.get("level", 0)
    volume = a["volume"]
    voxel = _voxel_for(ctx, volume, a.get("voxel_um"))
    eff = voxel * 2 ** level if voxel else None   # um between layers at this level
    want_s = a.get("s_local", False)
    if want_s and not eff:
        raise ToolError("s_local needs the voxel size: pass voxel_um (open-data volumes are looked up in the catalog)")
    half = a.get("half_layers") or (min(200, max(3, math.ceil(280 / eff))) if eff else 30)
    window = a.get("window") or (min(2048, max(192, 2 * vc3d_seat.s_local_params(eff)["column_px"] + 64))
                                 if want_s else 192)
    centres, rows, cols = window_centres(surface, a.get("windows") or (9 if want_s else 1))
    remote = is_url(volume)
    vol_args = (_remote_args(ctx, volume, capabilities(ctx, tools)) if remote
                else ["--volume", existing(ctx, volume, "volume", "zarr")])
    guard = _cache_guard(ctx, volume) if remote else None
    cache_warnings = []
    base = a.get("scale_segmentation", 1.0)
    candidates = [base] + ([s for s in FRAME_CANDIDATES if s != base] if a.get("frame_search") else [])

    def render(s, row, col, tag):
        f = s / (2 ** level)
        cx, cy = int(col / sx * f), int(row / sy * f)
        full_w, full_h = int(cols / sx * f), int(rows / sy * f)
        w, h = min(window, full_w), min(window, full_h)
        x0, y0 = max(0, min(cx - w // 2, full_w - w)), max(0, min(cy - h // 2, full_h - h))
        dest = out / f"profile-{tag}"
        argv = ["--segmentation", surface, *vol_args, "--scale", 1, "--group-idx", level,
                "--num-slices", 2 * half + 1, "--slice-step", 1, "--cache-gb", 2,
                "--crop-x", x0, "--crop-y", y0, "--crop-width", w, "--crop-height", h, "--tif-output", dest]
        if s != 1.0:
            argv += ["--scale-segmentation", s]
        rc, seconds, cache = _guarded(
            ctx, guard, lambda: run_logged(ctx, tools.argv(vc3d.PROBE, *argv), out / "seating.log", env=env,
                                           timeout=a.get("timeout", 1800)),
            lambda: shutil.rmtree(dest, ignore_errors=True), a.get("cache_reruns", CACHE_RERUNS))
        row_out = {"scale_segmentation": s, "exit": rc, "seconds": seconds, "window_xywh": [x0, y0, w, h]}
        if cache and cache.get("warning"):
            cache_warnings.append(f"window {tag}: {cache['warning']}")
        stack = None
        if rc == 0:
            try:
                stack = vc3d.read_layers(dest)
                row_out.update(vc3d_seat.seating(*stack, material=a.get("material", vc3d_seat.MATERIAL)))
            except (OSError, ValueError) as exc:
                row_out.update(score=-1.0, error=str(exc))
        else:
            row_out.update(score=-1.0, log_tail=tail(out / "seating.log", 8))
        return row_out, stack

    seed, columns, values = a.get("seed", 0), vc3d_seat.S_LOCAL_COLUMNS, []

    def s_local_of(k, stack):
        if want_s and stack is not None:
            quota = columns // len(centres) + (1 if k < columns % len(centres) else 0)
            values.extend(vc3d_seat.s_local_columns(*stack, eff, quota, random.Random(f"{seed}:{k}")))

    rows_out = []
    for s in candidates:
        ctx.say(f"seating: scale_segmentation {s:g}, central window")
        row_out, stack = render(s, centres[0][0], centres[0][1], f"s{s:g}")
        rows_out.append(row_out)
        if s == base:
            s_local_of(0, stack)
    wins = [rows_out[0]]
    for k, (r, c, _) in enumerate(centres[1:], 1):
        ctx.say(f"seating: window {k + 1} of {len(centres)}")
        row_out, stack = render(base, r, c, f"w{k}")
        wins.append(row_out)
        s_local_of(k, stack)
    first = rows_out[0]
    res = {"volume": volume, "level": level, "scale_segmentation": base, "verdict": vc3d_seat.verdict(first),
           "score": first.get("score"), "contrast": first.get("contrast"), "coverage": first.get("coverage"),
           "gap_layers": first.get("gap"), "sheet_contrast": first.get("sheet_contrast"),
           "half_layers": half, "window": window, "voxel_um": voxel,
           "thresholds": {"seated_contrast": vc3d_seat.SEATED_CONTRAST, "unseated_contrast": vc3d_seat.UNSEATED_CONTRAST,
                          "note": "an interpretation; compare frames rather than trusting one number"},
           "candidates": [{k: r.get(k) for k in ("scale_segmentation", "score", "contrast", "coverage", "gap",
                                                  "sheet_contrast", "valid_pixels", "exit")} for r in rows_out],
           "profile": first.get("profile")}
    if len(wins) > 1:
        res["windows"] = [{"grid_row_col": [r, c], "xyz": list(p), "window_xywh": w["window_xywh"],
                           "verdict": vc3d_seat.verdict(w), **{k: w.get(k) for k in ("score", "contrast", "coverage",
                                                                                      "gap", "exit")}}
                          for (r, c, p), w in zip(centres, wins)]
        verdicts = [w["verdict"] for w in res["windows"]]
        seated = verdicts.count("seated")
        res["seated_windows"] = f"{seated} of {len(wins)}"
        res["verdict"] = "seated" if seated == len(wins) else "partly seated" if seated else \
            "not seated" if verdicts.count("not seated") == len(wins) else "unclear"
    if want_s:
        res["s_local"] = vc3d_seat.s_local_summary(values, eff, layers=2 * half + 1, seed=seed)
    if len(rows_out) > 1:
        ranked, margin = vc3d_seat.best_frame(rows_out)
        res["best_frame"] = ranked[0]["scale_segmentation"]
        res["margin_over_next"] = round(margin, 2) if margin is not None else None
        if ranked[0]["scale_segmentation"] != base and ranked[0]["score"] > max(first.get("score", -1), 0) + 1:
            res["better_frame"] = ranked[0]["scale_segmentation"]
    if guard is not None:
        res["cache"] = guard.summary()
        if cache_warnings:
            res["cache"]["warnings"] = cache_warnings
    return res


@tool("orientation", "Normal orientation", "Which way does a surface's normal point, toward the scroll's centre "
      "or away? VC3D stacks layers along N = d/dcol x d/drow (along -N with --flip-normals, the team order for "
      "villa's standard segments, whose N points outward). A grid with its rows or columns the other way round has "
      "N pointing inward, and the same flag then stacks its layers away from the centre (HANDOFF zone B checks 1 "
      "and 3). The sign is decided once per patch by an area-weighted vote against the umbilicus (given, or the "
      "catalog's for the volume), a fixed axis, or a circle fitted to the surface (an estimate). Also reports which "
      "way rows and columns run, sharp folds, and the tiles that vote the other way. render's team order uses the "
      "same vote whenever an umbilicus is known.",
      {"surface": STR("tifxyz folder"),
       "volume": STR("the volume the surface is in (path or URL): the catalog's umbilicus for it is used"),
       "umbilicus": STR("umbilicus file or URL: text lines z, y, x or villa's JSON forms"),
       "umbilicus_scale": NUM("multiply the umbilicus coordinates first (default 1), for one annotated in another binning"),
       "centre_xy": ARR("a fixed axis x, y instead of an umbilicus", {"type": "number"}, minItems=2, maxItems=2),
       "scale_segmentation": NUM("multiply the surface coordinates first, as render does (default 1)"),
       "affine": ARR("3x4 affine (rows of x, y, z) applied to the surface, as render does", {"type": "array"},
                     minItems=3, maxItems=4),
       "grid_box": ARR("only this patch of the grid: rows and columns [row0, row1, col0, col1)",
                       {"type": "integer", "minimum": 0}, minItems=4, maxItems=4),
       "max_vertices": INT("vertices sampled at most (default 200000)", minimum=100, maximum=5000000),
       "tiles": INT("tiles per side for the map of disagreeing regions (default 6)", minimum=1, maximum=32)},
      required=["surface"], readonly=True, openworld=True)
def h_orientation(ctx, a):
    surface = existing(ctx, a["surface"], "surface", "tifxyz")
    umb, info = (None, None) if a.get("centre_xy") and not a.get("umbilicus") else _umbilicus(ctx, a, a.get("volume"))
    try:
        res = vc3d_orient.orientation(surface, umbilicus=umb, centre_xy=a.get("centre_xy"),
                                      scale_segmentation=a.get("scale_segmentation", 1.0), affine=a.get("affine"),
                                      max_vertices=a.get("max_vertices", 200_000), tiles=a.get("tiles", 6),
                                      grid_box=a.get("grid_box"))
    except (vc3d_orient.OrientError, vc3d_io.IOFormatError) as exc:
        raise ToolError(str(exc)) from exc
    if umb is not None:
        res["umbilicus"] = info
    elif info:
        res["umbilicus"] = {"used": False, "why": info}
    return res


@tool("audit", "Audit a zarr volume", "Is a zarr volume whole where a surface needs it? A missing chunk reads as "
      "fill_value (usually 0) with no error, so a blank map over it means nothing (HANDOFF zone B check 5). Checks "
      "that every pyramid level has a header, that the shapes agree with the scale transforms and that no level is "
      "empty, and decodes a few chunks; with a surface, checks that every chunk a render along it reads exists at "
      "the levels asked (masked volumes omit empty chunks on purpose, so only chunks under the surface count, and "
      "a gap only in the margin is a warning); with render, counts zero samples inside a rendered stack. Paths or "
      "URLs (anonymous, paced). Each chunk is present, missing or unknown; unknown makes the verdict incomplete, "
      "never clean. Writes audit.json.",
      {"volume": STR("OME-Zarr group or zarr array: path or http/s3 URL"),
       "surface": STR("tifxyz folder whose footprint to check chunk by chunk"),
       "grid_box": ARR("only this part of the surface: grid rows and columns [row0, row1, col0, col1) (zone B "
                       "of a larger trace, say)", {"type": "integer", "minimum": 0}, minItems=4, maxItems=4),
       "levels": ARR("levels to check under the surface (default the finest)", {"type": "integer", "minimum": 0}),
       "scale_segmentation": NUM("multiply the surface coordinates first, as render does (default 1)"),
       "margin": INT("voxels of each checked level either side of the surface (default 60; a 2um render's 109 "
                     "layers span +-54)", minimum=0, maximum=4096),
       "max_points": INT("surface vertices sampled at most (default 250000)", minimum=100, maximum=5000000),
       "max_requests": INT("chunk requests to a remote store at most (default 4000); chunks past it stay unknown",
                           minimum=1),
       "rate": NUM("requests per second to a remote store (default 20)", minimum=0.1, maximum=1000),
       "decode": INT("chunks per level to download and decode (default 2)", minimum=0, maximum=50),
       "render": STR("a rendered stack (zarr or folder of layer TIFFs) whose zero samples to count"),
       "out": STR("folder for audit.json (default work/vc3d/audits/<volume>-<time>)")},
      background=True, readonly=True, openworld=True)
def h_audit(ctx, a):
    if not a.get("volume") and not a.get("render"):
        raise ToolError("audit needs volume, render or both")
    if a.get("surface") and not a.get("volume"):
        raise ToolError("a surface footprint is checked against a volume: give volume too")
    started = now()
    volume = a.get("volume")
    if volume and not is_url(volume):
        volume = str(existing(ctx, volume, "volume", "zarr"))
    surface = str(existing(ctx, a["surface"], "surface", "tifxyz")) if a.get("surface") else None
    render = str(existing(ctx, a["render"], "render")) if a.get("render") else None
    out = out_dir(ctx, a.get("out"), "audits", f"{slug(str(volume or render).rstrip('/').split('/')[-1])}-{stamp()}")
    kw = {"rate": a.get("rate", vc3d_audit.DEFAULT_RATE)} if volume and is_url(volume) else {}
    try:
        report = vc3d_audit.audit(volume, surface=surface, check_levels=a.get("levels"),
                                  scale_segmentation=a.get("scale_segmentation", 1.0),
                                  margin=a.get("margin", vc3d_audit.DEFAULT_MARGIN),
                                  max_points=a.get("max_points", vc3d_audit.DEFAULT_MAX_POINTS),
                                  max_requests=a.get("max_requests", vc3d_audit.DEFAULT_MAX_REQUESTS),
                                  decode_n=a.get("decode", 2), render=render, progress=ctx.say,
                                  grid_box=a.get("grid_box"), **kw)
    except (vc3d_audit.AuditError, vc3d_io.IOFormatError) as exc:
        raise ToolError(str(exc)) from exc
    path = out / "audit.json"
    path.write_text(json.dumps(report, indent=1))
    report["report"] = str(path)
    report["receipt"] = write_receipt(ctx, out, "audit", a, [], [str(path)], started, verdict=report["verdict"],
                                      inputs={"volume": light_fingerprint(volume) if volume else None,
                                              "surface": light_fingerprint(surface) if surface else None})
    return report


def _known_volume_urls(ctx):
    """{cache folder name: (URL to check, URL VC3D was given)} for the volumes the kit can name: its cache
    ledgers, and every volume of the cached catalog in the forms VC3D may have been given (us-east-1, global,
    s3://, and through the relay on any of its preferred ports)."""
    found = {}
    for led in sorted((ctx.home / "cache" / "vc3d-empty").glob("*.json")):
        data = vc3d_cache.Ledger(led).read()
        if data.get("url"):
            found[led.stem] = (data["url"], data["cache_url"])
    cat = _catalog(ctx)
    for sample in (cat or {}).get("samples", {}).values():
        for vol in sample.get("volumes", {}).values():
            for d in vol.get("data", []):
                path = (d.get("origins") or [{}])[0].get("path") if d.get("type") == "ome-zarr" else None
                if not path:
                    continue
                url = vc3d_catalog.data_url(d).rstrip("/")
                given = [url]
                if url.startswith(vc3d_catalog.BUCKET_URL):
                    given += [f"https://vesuvius-challenge-open-data.s3.amazonaws.com/{path.strip('/')}",
                              f"s3://vesuvius-challenge-open-data/{path.strip('/')}"]
                given += [r for g in given[:2] for r in s3relay.candidate_urls(g)]
                for g in given:
                    found.setdefault(vc3d_cache.volume_dir(g, root="/").name, (url, g))
    return found


@tool("cache_check", "Check VC3D's chunk cache", "VC3D caches a remote chunk that answered 404 as empty, for good, "
      "and S3 sometimes answers 404 for chunks it holds, so a render or trace can read holes with no error (a "
      "2.4 um crop render here had 28% of its samples blank from 4 such chunks). This checks the empty-chunk "
      "markers in a remote volume's cache against the bucket (a 404 is missing only when S3 says NoSuchKey) and "
      "deletes the false ones, so the next read fetches the chunk. render, check_surface, trace and run already "
      "do it around every run on a URL; use this after VC3D ran outside the kit (the app, a script).",
      {"volume": STR("volume URL exactly as VC3D was given it (s3:// and https:// forms have separate caches)"),
       "all": BOOL("every volume folder in VC3D's cache whose URL is known (from the kit's checks or the catalog)"),
       "via_relay": BOOL("with volume: also check the folders of the relay URLs kit gave VC3D for it (default "
                         "true)"),
       "delete": BOOL("delete false markers (default true); false only reports them"),
       "recheck": BOOL("ask again about markers already found true")},
      background=True, openworld=True)
def h_cache_check(ctx, a):
    root = vc3d_cache.cache_root(ctx.env)
    ledgers = ctx.home / "cache" / "vc3d-empty"
    if a.get("volume"):
        if not is_url(a["volume"]):
            raise ToolError("volume must be the URL VC3D streamed (a local volume has no remote cache)")
        url = a["volume"]
        given = [url] + (s3relay.candidate_urls(url) if a.get("via_relay", True) else [])
        targets = [(vc3d_cache.volume_dir(g, root=root).name, (url, g)) for g in given
                   if g == url or (root / vc3d_cache.volume_dir(g, root=root).name).is_dir()]
    elif a.get("all"):
        known = _known_volume_urls(ctx)
        folders = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        targets = [(f, known.get(f)) for f in folders]
    else:
        raise ToolError("give volume (a URL) or all=true")
    out = {"cache_root": str(root), "volumes": []}
    for folder, urls in targets:
        if urls is None:
            n = len(vc3d_cache.markers(root / folder))
            out["volumes"].append({"folder": folder, "markers": n, "url": None,
                                   "note": "URL not known here; check it with volume=<the URL VC3D was given>"
                                   if n else "no empty-chunk markers"})
            continue
        ctx.say(f"checking {folder}")
        rep = vc3d_cache.check(urls[0], ctx.env, ledgers, delete=a.get("delete", True),
                               recheck=a.get("recheck", False), progress=ctx.say, root=root, cache_url=urls[1])
        out["volumes"].append({"folder": folder, **rep})
    out["false_deleted"] = sum(v.get("deleted", 0) for v in out["volumes"])
    out["false_found"] = sum(len(v.get("false", [])) for v in out["volumes"])
    out["unknown"] = sum(len(v.get("unknown", [])) for v in out["volumes"])
    return out


def _volume_id(text):
    """The volume id (the timestamp that starts a volume's name) in an id, folder name or URL."""
    if not text:
        return None
    name = str(text).rstrip("/").split("/")[-1]
    return (name[:-5] if name.endswith(".zarr") else name).split("-")[0]


def _landmark_image_check(ctx, a, cat, sample, src, dst, points, tol):
    """The CT check of one transform at its landmarks (spread out to image_points) and at the given points."""
    if not (src and dst):
        raise ToolError("image needs from_volume and to_volume")
    try:
        from . import vc3d_region
    except ImportError as exc:
        raise ToolError(f"the image check needs numpy ({exc})") from exc
    rows = {r["volume"]: r for r in vc3d_catalog.volumes(cat, sample)}
    for vid in (src, dst):
        if not (rows.get(vid) or {}).get("url"):
            raise ToolError(f"no zarr URL in the catalog for volume {vid}")
    stored = {(vid, t.get("to_volume_id")): t for _, vid, t in vc3d_landmarks.stored_transforms(cat, sample)}
    t = stored.get((src, dst))
    if t is not None:
        matrix, lm_from, lm_to = t["transformation_matrix"], t.get("from_landmarks") or [], t.get("to_landmarks") or []
    else:
        path = vc3d_landmarks.path_between(cat, sample, src, dst)
        if path is None:
            raise ToolError(f"{sample} has no transform from {src} to {dst}")
        matrix = next(x.get("matrix") for g in ((cat["samples"][sample].get("sample") or {}).get("properties") or {})
                      .get("volume_transforms", []) if g.get("from_volume_id") == src
                      for x in g.get("transforms", []) if x.get("to_volume_id") == dst)
        lm_from, lm_to = [], []
        if not points:
            raise ToolError(f"{src} to {dst} is derived ({path}): it has no landmarks of its own, so give at points")
    k = a.get("image_points")
    if k and len(lm_from) > k:
        pick = sorted({round(i * (len(lm_from) - 1) / max(1, k - 1)) for i in range(k)})
        lm_from, lm_to = [lm_from[i] for i in pick], [lm_to[i] for i in pick]
    try:
        vf = vc3d_region.Volume(rows[src]["url"], voxel_um=rows[src]["voxel_um"])
        vt = vc3d_region.Volume(rows[dst]["url"], voxel_um=rows[dst]["voxel_um"])
    except (vc3d_region.RegionError, vc3d_audit.AuditError) as exc:
        raise ToolError(f"cannot open the volumes: {exc}") from exc
    kw = {key: a[key] for key in ("work_um", "patch", "search", "margin", "exclude") if a.get(key) is not None}
    if kw.get("exclude", vc3d_landmarks.IMAGE_DEFAULTS["exclude"]) * 2 > kw.get("search",
                                                                             vc3d_landmarks.IMAGE_DEFAULTS["search"]):
        raise ToolError("exclude must be at most half of search, or nothing is left to compare the peak with")
    out = {}
    if lm_from:
        ctx.say(f"image check at {len(lm_from)} landmarks")
        out["landmarks"] = vc3d_landmarks.image_check(matrix, vf, vt, lm_from, rows[src]["voxel_um"],
                                                      rows[dst]["voxel_um"], to_points=lm_to, tolerance_um=tol,
                                                      progress=ctx.say, **kw)
    if points:
        ctx.say(f"image check at {len(points)} points")
        out["at"] = vc3d_landmarks.image_check(matrix, vf, vt, points, rows[src]["voxel_um"],
                                               rows[dst]["voxel_um"], tolerance_um=tol, progress=ctx.say, **kw)
    out["note"] = ("offset_um: where the CT puts a point relative to the matrix, in the target frame. A match counts "
                   "only when its peak stands margin above the best correlation farther away, and only when the "
                   "swapped pairs (the control) do not match")
    return out


@tool("landmarks", "Check cross-scan transforms", "The open-data catalog maps each scan of a sample to the others "
      "with affine matrices fitted to landmark pairs; VC3D and render's affine use them to carry a surface between "
      "scans' frames, and a wrong one puts the surface beside its sheet with no error. Checks every stored matrix "
      "against its own landmarks (residuals; is it their least-squares fit), predicts each landmark from the others "
      "(leave-one-out: the error between landmarks), compares a similarity fit, measures how flat the landmark set "
      "is, the matrix's scale against the voxel sizes and its handedness (a mirror flips a surface's normal between "
      "frames), and checks each sample's derived table (inverses and chains) against the stored matrices. With at "
      "or surface (and from_volume and to_volume, any pair the sample's table connects) it estimates how firmly the "
      "landmarks pin the mapping down there. Verdicts (consistent, weak, inconsistent, unchecked) follow fixed rules "
      "with tolerance_um. With image (one stored transform, or any pair with at), it also checks the CT itself: "
      "around each landmark (and at point) it correlates the finer scan, carried through the matrix, with the "
      "coarser scan at every nearby shift, reports where the CT puts the point relative to the matrix, and counts a "
      "peak only when it stands clear of the best correlation elsewhere; swapped pairs are the control. Writes "
      "landmarks.json.",
      {"sample": STR("sample id (default every sample; found from the volumes when they are given)"),
       "from_volume": STR("only transforms from this volume: its id (the timestamp that starts its name), folder "
                          "name or URL"),
       "to_volume": STR("only transforms to this volume (id, folder name or URL)"),
       "tolerance_um": NUM("error that matters, in micrometres (default 75, half the 0.15 mm thickness of a "
                           "carbonized sheet)", minimum=0.1),
       "at": ARR("points [x, y, z] in from_volume's voxels where to estimate the mapping's error",
                 {"type": "array"}, maxItems=10000),
       "surface": STR("tifxyz in from_volume's frame: estimate the mapping's error over its vertices"),
       "scale_segmentation": NUM("multiply the surface coordinates first, as render does (default 1)"),
       "max_points": INT("surface vertices used at most (default 400)", minimum=1, maximum=20000),
       "image": BOOL("also check the CT at each landmark (and at point): downloads a few chunks per point"),
       "image_points": INT("image check: at most this many landmarks, spread over the set (default all)",
                           minimum=1, maximum=1000),
       "work_um": NUM("image check: voxel size of the grid compared on (default 4, or the coarser scan's voxel "
                      "when larger)", minimum=0.1),
       "patch": INT("image check: side of the compared cube in work voxels (default 64)", minimum=8, maximum=256),
       "search": INT("image check: shifts tried, in work voxels either way (default 32)", minimum=1, maximum=128),
       "margin": NUM("image check: how far the peak must stand above the best correlation elsewhere (default "
                     "0.1)", minimum=0, maximum=2),
       "exclude": NUM("image check: work voxels around the peak left out when finding the best correlation "
                      "elsewhere (default 6; keep it well under search)", minimum=0.5, maximum=64),
       "refresh": BOOL("download the catalog again (it is cached for a day)"),
       "out": STR("folder for landmarks.json (default work/vc3d/checks/landmarks-<time>)")},
      background=True, readonly=True, openworld=True)
def h_landmarks(ctx, a):
    started = now()
    try:
        cat = vc3d_catalog.load(ctx.home / "cache", refresh=a.get("refresh", False))
    except vc3d_catalog.CatalogError as exc:
        raise ToolError(str(exc)) from exc
    src, dst = _volume_id(a.get("from_volume")), _volume_id(a.get("to_volume"))
    sample = a.get("sample")
    if not sample and (src or dst):
        hit = vc3d_catalog.volume_by_id(cat, src or dst)
        if hit is None:
            raise ToolError(f"no volume {src or dst} in the catalog")
        sample = hit[0]
    tol = a.get("tolerance_um", vc3d_landmarks.TOLERANCE_UM)
    points = None
    if a.get("surface"):
        surface = existing(ctx, a["surface"], "surface", "tifxyz")
        try:
            samples, _, _ = vc3d_audit.surface_samples(surface, a.get("scale_segmentation", 1.0),
                                                       max_points=a.get("max_points", 400))
        except (vc3d_audit.AuditError, vc3d_io.IOFormatError) as exc:
            raise ToolError(str(exc)) from exc
        points = [p[:3] for p in samples]
        if not points:
            raise ToolError(f"{surface} has no valid vertex")
    if a.get("at"):
        points = (points or []) + [list(p) for p in a["at"]]
    try:
        if points is not None:
            if not (src and dst):
                raise ToolError("at and surface need from_volume and to_volume (the frame the points are in, and "
                                "the one they are carried to)")
            report = {"sample": sample, "from": src, "to": dst, "tolerance_um": tol,
                      **vc3d_landmarks.error_along(cat, sample, src, dst, points)}
            worst = report.get("jackknife_affine_max_um")
            report["note"] = ("jackknife spread: how far the mapping of a point moves when one landmark is left out "
                              "(hops add in quadrature). It does not see bends between landmarks; the "
                              "leave-one-out errors of each hop's landmarks (landmarks without at) do.")
            if worst is not None and worst > tol:
                report["warning"] = (f"the mapping here moves up to {worst} um when one landmark is left out, more "
                                     f"than {tol:g} um")
        else:
            report = vc3d_landmarks.check_catalog(cat, sample, src, dst, tol)
        if a.get("image"):
            report["image_check"] = _landmark_image_check(ctx, a, cat, sample, src, dst, points, tol)
    except vc3d_landmarks.LandmarkError as exc:
        raise ToolError(str(exc)) from exc
    out = out_dir(ctx, a.get("out"), "checks", f"landmarks-{stamp()}")
    path = out / "landmarks.json"
    path.write_text(json.dumps(report, indent=1))
    image = report.get("image_check")
    if image:   # the rows stay in the report file
        image = {k: ({kk: vv for kk, vv in v.items() if kk != "rows"} if isinstance(v, dict) else v)
                 for k, v in image.items()}
        report["image_check"] = image if points is not None else report["image_check"]
    if points is None:
        report = {"tolerance_um": tol, "counts": report["counts"], "mirrored": report["mirrored"],
                  "derived_problems": {s: d["problems"] for s, d in report["derived"].items() if d["problems"]},
                  "derived_entries": sum(d["entries"] for d in report["derived"].values()),
                  "transforms": [vc3d_landmarks.summary_row(r) for r in report["transforms"]],
                  "flags": "details of each flag are in the report file"}
    if image:
        report["image_check"] = image
    report["report"] = str(path)
    report["receipt"] = write_receipt(ctx, out, "landmarks", a, [], [str(path)], started)
    return report


# ---------------------------------------------------------------- tools: jobs and passthroughs

@tool("jobs", "Background jobs", "List, inspect, wait for or cancel background jobs (anything started with "
      "background=true). wait returns when the job ends or after timeout seconds; call again to keep waiting.",
      {"action": STR("list (default), status, log, wait or cancel", enum=["list", "status", "log", "wait", "cancel"]),
       "id": STR("job id"), "timeout": NUM("wait: seconds (default 30, at most 600)", minimum=0, maximum=600),
       "lines": INT("log lines to return (default 20)", minimum=0, maximum=2000)})
def h_jobs(ctx, a):
    action = a.get("action", "list")
    if action == "list":
        return {"jobs": job_list(ctx)}
    if not a.get("id"):
        raise ToolError(f"jobs action={action} needs id")
    if action == "status":
        return job_info(ctx, a["id"], a.get("lines", 20))
    if action == "log":
        return {"job": a["id"], "log_tail": tail(jobs_dir(ctx) / a["id"] / "log.txt", a.get("lines", 200), 100000)}
    if action == "wait":
        return job_wait(ctx, a["id"], a.get("timeout", 30), a.get("lines", 20))
    return job_cancel(ctx, a["id"])


@tool("kit", "Run a kit command", "Any `python -m kit` command of this repository: auc, verify, rowscore, "
      "layers, shuffle, overlap, collate, provenance, run (the experiment ledger), compute, prizes, doctor and more. "
      "Pass the words after `python -m kit` as args.",
      {"args": ARR("arguments after `python -m kit`, e.g. [\"run\", \"list\"]", {"type": "string"}, minItems=1),
       "timeout": INT("seconds (default 1800)", minimum=1)},
      required=["args"], background=True)
def h_kit(ctx, a):
    args = a["args"]
    if args[0] == "vc3d" and len(args) > 1 and args[1] in ("mcp", "app-mcp"):
        raise ToolError("the MCP servers are not started from inside the server")
    log = fresh(ctx.home / "runs" / f"{stamp()}-kit-{slug(args[0])}.log")
    # run in the kit home, with this kit importable from there and the same home for the command
    env = dict(kithome.python_env(ctx.env), **{kithome.ENV: str(ctx.root)})
    rc, seconds = run_logged(ctx, [sys.executable, "-m", "kit", *args], log, env=env,
                             timeout=a.get("timeout", 1800), cwd=str(ctx.root))
    return {"args": args, "exit": rc, "seconds": seconds, "output": tail(log, 200, 30000), "log": str(log)}


@tool("modal", "Run on Modal", "Run the headless VC3D Modal app (scripts/vc3d/modal_vc3d.py): the self-test, or one "
      "vc_* tool on the Modal Volume vc3d-data. This rents compute, so it runs only when the user has set "
      "KIT_ALLOW_MODAL=1 for this server. Always a background job.",
      {"entrypoint": STR("selftest or tool", enum=["selftest", "tool"]),
       "tool": STR("vc_* tool name (entrypoint tool)"), "args": STR("tool arguments as one string, paths under /data"),
       "image": STR("source (villa built at the pinned revision; has --flip-normals) or container (published image)",
                    enum=["source", "container"]),
       "threads": INT("threads", minimum=1)},
      required=["entrypoint"], openworld=True)
def h_modal(ctx, a):
    if ctx.env.get("KIT_ALLOW_MODAL") != "1":
        raise ToolError("Modal runs rent compute, which needs the user's go-ahead (AGENTS.md rule 8). The user "
                        "enables them by starting this server with KIT_ALLOW_MODAL=1.")
    if not ctx.in_job:
        return submit_job(ctx, "modal", a)
    target = f"{script('modal_vc3d.py', 'the modal tool')}::{a['entrypoint']}"
    argv = ["modal", "run", target]
    if a["entrypoint"] == "tool":
        if not a.get("tool"):
            raise ToolError("entrypoint tool needs tool=<vc_* name>")
        argv += ["--name", a["tool"], "--args", a.get("args", "")]
    if a.get("threads"):
        argv += ["--threads", a["threads"]]
    env = dict(kithome.python_env(ctx.env), VC3D_IMAGE=a.get("image", "source"))
    env.pop("MODAL_TOKEN_ID", None)
    env.pop("MODAL_TOKEN_SECRET", None)
    log = fresh(ctx.home / "runs" / f"{stamp()}-modal-{a['entrypoint']}.log")
    rc, seconds = run_logged(ctx, argv, log, env=env, timeout=8 * 3600, cwd=str(ctx.root))
    return {"exit": rc, "seconds": seconds, "log": str(log), "output": tail(log, 60)}


# ---------------------------------------------------------------- tools: data

@tool("catalog", "Open-data catalog", "Find data in the Vesuvius Challenge open-data bucket: samples; a sample's "
      "volumes (URL, voxel size, shape, surface predictions); its segments (frames they are published in, surface "
      "volumes, ink maps, labels); one segment in full; affine transforms between a sample's volumes; models.",
      {"action": STR("samples, volumes, segments, segment, transforms or models",
                     enum=["samples", "volumes", "segments", "segment", "transforms", "models"]),
       "sample": STR("sample id, e.g. PHerc0139 or PHercParis4"), "segment": STR("segment id, long id or suffix"),
       "query": STR("segments: substring of the long id"), "limit": INT("segments: rows (default 100)", minimum=1),
       "refresh": BOOL("download the catalog again (it is cached for a day)")},
      required=["action"], readonly=True, openworld=True)
def h_catalog(ctx, a):
    try:
        cat = vc3d_catalog.load(ctx.home / "cache", refresh=a.get("refresh", False))
        action = a["action"]
        if action == "samples":
            return {"samples": vc3d_catalog.samples(cat)}
        if action == "models":
            return {"models": vc3d_catalog.models(cat)}
        if not a.get("sample"):
            raise ToolError(f"catalog action={action} needs sample")
        if action == "volumes":
            return {"sample": a["sample"], "volumes": vc3d_catalog.volumes(cat, a["sample"])}
        if action == "segments":
            rows, total = vc3d_catalog.segments(cat, a["sample"], a.get("query"), a.get("limit", 100))
            return {"sample": a["sample"], "total": total, "segments": rows}
        if action == "transforms":
            return {"sample": a["sample"], "transforms": vc3d_catalog.transforms(cat, a["sample"])}
        if not a.get("segment"):
            raise ToolError("catalog action=segment needs segment")
        return vc3d_catalog.segment(cat, a["sample"], a["segment"])
    except vc3d_catalog.CatalogError as exc:
        raise ToolError(str(exc)) from exc


@tool("fetch_segment", "Fetch a segment", "Download a published segment's tifxyz (small: the x, y, z grids and "
      "meta.json), in the frame of a given volume or as traced, from the open-data bucket.",
      {"sample": STR("sample id"), "segment": STR("segment id, long id or suffix"),
       "frame": STR("volume id whose frame to fetch (see catalog segment: frames); omit for the original"),
       "dest": STR("folder (default work/vc3d/segments/<sample>/<long id>[-on-<frame>].tifxyz)")},
      required=["sample", "segment"], openworld=True)
def h_fetch_segment(ctx, a):
    from . import fetch
    try:
        cat = vc3d_catalog.load(ctx.home / "cache")
        long_id, prefix = vc3d_catalog.tifxyz_prefix(cat, a["sample"], a["segment"], a.get("frame"))
    except vc3d_catalog.CatalogError as exc:
        raise ToolError(str(exc)) from exc
    name = f"{long_id}-on-{a['frame']}.tifxyz" if a.get("frame") else f"{long_id}.tifxyz"
    dest = writable(ctx, a["dest"]) if a.get("dest") else ctx.home / "segments" / a["sample"] / name
    try:
        objects, fetched, total = fetch.fetch_prefix(prefix.rstrip("/"), dest, workers=8)
    except (fetch.FetchError, OSError) as exc:
        raise ToolError(f"download failed: {exc}") from exc
    surface = dest
    if not vc3d_io.is_tifxyz(surface):
        found = [p.parent for p in dest.rglob("x.tif")]
        surface = found[0] if found else dest
    out = {"surface": str(surface), "objects": objects, "bytes": total, "downloaded": fetched,
           "source": vc3d_catalog.url_of(prefix)}
    if vc3d_io.is_tifxyz(surface):
        out["stats"] = tifxyz_stats(surface)
    return out


def models_file(ctx):
    return ctx.home / "models.json"


def load_models(ctx):
    try:
        return json.loads(models_file(ctx).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


@tool("models", "Ink models", "The ink models this machine knows: list them, register a checkpoint you have "
      "(engine villa, torchscript or v8in), remove one, or list the known downloadable ones (fetch_model).",
      {"action": STR("list (default), add, remove or known", enum=["list", "add", "remove", "known"]),
       "name": STR("model name"), "engine": STR("villa, torchscript or v8in", enum=["villa", "torchscript", "v8in"]),
       "checkpoint": STR("checkpoint file (.pth, or .pt for torchscript)"), "model_dir": STR("v8in repository snapshot"),
       "notes": STR("free text: where it came from, what it was trained on")})
def h_models(ctx, a):
    action = a.get("action", "list")
    models = load_models(ctx)
    if action == "known":
        return {"known": {k: {"engine": v["engine"], "repo": v["repo"], "revision": v["revision"], "about": v["about"]}
                          for k, v in vc3d_catalog.KNOWN_MODELS.items()}}
    if action == "list":
        return {"models": models}
    if not a.get("name"):
        raise ToolError(f"models action={action} needs name")
    if action == "remove":
        removed = models.pop(a["name"], None)
    else:
        if not a.get("engine"):
            raise ToolError("models action=add needs engine")
        entry = {"engine": a["engine"], "notes": a.get("notes")}
        key = "model_dir" if a["engine"] == "v8in" else "checkpoint"
        if not a.get(key):
            raise ToolError(f"models action=add with engine {a['engine']} needs {key}")
        entry[key] = str(existing(ctx, a[key], key))
        entry["added"] = now()
        models[a["name"]] = entry
        removed = None
    models_file(ctx).parent.mkdir(parents=True, exist_ok=True)
    models_file(ctx).write_text(json.dumps(models, indent=1))
    return {"models": models, **({"removed": removed} if action == "remove" else {})}


@tool("fetch_model", "Download an ink model", "Download a known ink checkpoint from Hugging Face or a GitHub release "
      "(download only; pinned files are checked against their sha256) into checkpoints/ (ignored by git) and "
      "register it: " + ", ".join(sorted(vc3d_catalog.KNOWN_MODELS)) + ".",
      {"name": STR("model", enum=sorted(vc3d_catalog.KNOWN_MODELS)),
       "dest": STR("folder (default checkpoints/<name>)")},
      required=["name"], background=True, openworld=True)
def h_fetch_model(ctx, a):
    dest = writable(ctx, a["dest"]) if a.get("dest") else ctx.root / "checkpoints" / a["name"]
    try:
        receipt = vc3d_catalog.fetch_model(a["name"], dest, log=ctx.say)
    except (OSError, vc3d_catalog.CatalogError, ValueError) as exc:
        host = "github.com" if vc3d_catalog.KNOWN_MODELS[a["name"]].get("host") == "github-release" else "huggingface.co"
        raise ToolError(f"download of {a['name']} failed: {exc} (is {host} reachable from here?)") from exc
    (dest / "kit-download.json").write_text(json.dumps(dict(receipt, at=now()), indent=1))
    models = load_models(ctx)
    models[a["name"]] = {k: receipt[k] for k in ("engine", "checkpoint", "model_dir") if receipt.get(k)}
    models[a["name"]].update(notes=vc3d_catalog.KNOWN_MODELS[a["name"]]["about"], source=receipt["repo"],
                             revision=receipt["resolved_commit"] or receipt["revision"], added=now())
    models_file(ctx).parent.mkdir(parents=True, exist_ok=True)
    models_file(ctx).write_text(json.dumps(models, indent=1))
    return receipt


# ---------------------------------------------------------------- tools: ink

INK_PURPOSES = ["target", "benchmark", "smoke"]
ENGINE_ARGS = {
    "engine": STR("villa (villa's flat inference on a .pth), torchscript (a TorchScript export taking "
                  "the layer stack), v8in (a v8in snapshot) or command (your own)",
                  enum=["villa", "torchscript", "v8in", "command"]),
    "model": STR("a registered model name (see models); sets engine and checkpoint"),
    "checkpoint": STR("checkpoint file"), "model_dir": STR("v8in snapshot folder"),
    "command": ARR("command engine: argv with placeholders {input} (a zarr group; write {layers} instead for a "
                   "folder of layer TIFFs), {output} (where the map goes, .tif or .npy), {reverse} (1 or 0), {device}",
                   {"type": "string"}),
    "device": STR("cpu (default), cuda, cuda:0 or mps"),
    "batch": INT("batch size", minimum=1), "threads": INT("CPU threads", minimum=1),
}


def _engine(ctx, a):
    spec = {}
    if a.get("model"):
        models = load_models(ctx)
        if a["model"] not in models:
            raise ToolError(f"no registered model {a['model']!r}; models: {', '.join(models) or 'none'} "
                            "(models action=add, or fetch_model)")
        spec.update(models[a["model"]])
    for k in ("engine", "checkpoint", "model_dir", "command"):
        if a.get(k):
            spec[k] = a[k]
    engine = spec.get("engine")
    if engine is None:
        raise ToolError("say which model: model=<registered name>, or engine with checkpoint/model_dir/command")
    if engine in ("villa", "torchscript") and not spec.get("checkpoint"):
        raise ToolError(f"engine {engine} needs checkpoint")
    if engine == "v8in" and not spec.get("model_dir"):
        raise ToolError("engine v8in needs model_dir")
    if engine == "command" and not spec.get("command"):
        raise ToolError("engine command needs command")
    argv = ["--engine", engine]
    if spec.get("checkpoint"):
        argv += ["--checkpoint", str(existing(ctx, spec["checkpoint"], "checkpoint"))]
    if spec.get("model_dir"):
        argv += ["--model-dir", str(existing(ctx, spec["model_dir"], "model_dir"))]
    if spec.get("command"):
        argv += ["--command-json", json.dumps(spec["command"])]
    argv += ["--device", a.get("device", "cpu")]
    if a.get("batch"):
        argv += ["--batch", str(a["batch"])]
    argv += ["--threads", str(threads_for(ctx, a))]
    return engine, argv, spec


def _ink_out(ctx, a, kind, engine):
    """Where ink output goes, after the repository's preregistration and control rules."""
    purpose = a["purpose"]
    if purpose == "target":
        slug_ = a.get("experiment")
        if not slug_:
            raise ToolError("ink on a target needs experiment=<slug>: fix the readout rule before any map exists "
                            "(python -m kit run init SLUG --scroll S --question Q --readout R, or the kit tool)")
        root = ctx.root / "experiments"
        try:
            rec = ledger.load(slug_, root=root)
            problems = ledger.check(slug_, root=root)
        except ledger.LedgerError as exc:
            raise ToolError(f"experiment {slug_!r}: {exc}. Preregister it first with kit run init.") from exc
        if problems:
            raise ToolError(f"experiment {slug_!r} fails its ledger check: {'; '.join(problems)}")
        if rec["status"] not in ("planned", "running"):
            raise ToolError(f"experiment {slug_!r} is {rec['status']}; ink runs belong to planned or running experiments")
        base = root / slug_ / kind
        if a.get("out"):
            given = resolve(ctx, a["out"])
            if in_repo(ctx, given) is None or not str(given).startswith(str(base)):
                raise ToolError(f"target output stays under {base}")
            base = given
        if a.get("out"):
            base.mkdir(parents=True, exist_ok=True)
            return base, slug_
        return fresh(base / f"{stamp()}-{engine}", create=True), slug_
    out = out_dir(ctx, a.get("out"), kind, f"{stamp()}-{engine}")
    return out, None


def render_provenance(inp):
    """What the render receipt beside an ink input says (level, scale, voxel size, layer order and how it was
    decided), with warnings for the zone B rules: full resolution (HANDOFF check 2) and the team order."""
    for cand in (Path(inp) / "receipt.json", Path(inp).parent / "receipt.json"):
        try:
            rec = json.loads(cand.read_text()) if cand.is_file() else None
        except (OSError, ValueError):
            rec = None
        if not rec or rec.get("tool") != "render":
            continue
        args = rec.get("args") or {}
        argv = ((rec.get("steps") or [{}])[0].get("argv") or [])
        voxel = argv[argv.index("--voxel-size") + 1] if "--voxel-size" in argv[:-1] else args.get("voxel_um")
        orient = rec.get("orientation") if isinstance(rec.get("orientation"), dict) else None
        info = {"receipt": str(cand), "level": args.get("level", 0), "scale": args.get("scale", 1),
                "voxel_um": float(voxel) if voxel else None, "order": rec.get("order"),
                "order_checked": None if orient is None else orient.get("checked", False)}
        warnings = []
        lossy = rec.get("lossy_source") or vc3d_io.volcomp_source(str(args.get("volume", "")))
        if lossy:
            info["lossy_source"] = True
            warnings.append(f"rendered from a lossy source: {lossy}")
        if info["level"]:
            warnings.append(f"rendered from pyramid level {info['level']} ({2 ** info['level']}x downsampled); zone B "
                            "reads stay at full resolution (HANDOFF check 2)")
        if info["scale"] and info["scale"] < 1:
            warnings.append(f"rendered at scale {info['scale']}, below one pixel per voxel")
        if info["order"] and not str(info["order"]).startswith("team"):
            warnings.append(f"layer order is {info['order']}, not the team order the released models were trained on")
        elif orient is not None and not orient.get("checked"):
            warnings.append("team order taken from VC3D's usual flag, not checked against an umbilicus ("
                            f"{orient.get('why')}); the orientation tool checks it")
        return info, warnings
    return None, []


@tool("ink", "Ink detection", "Run an ink model on a rendered surface volume with no display: forward and the "
      "reverse-depth control always, optionally the depth-shuffle control. Engines: villa's flat inference "
      "(ink_9um and its fine-tunes), a TorchScript export, v8in, or your own command. An ink map is model "
      "output, not a reading. purpose=target needs a preregistered experiment and writes under "
      "experiments/<slug>/; benchmark is for labelled public segments; smoke for pipeline checks.",
      {"input": STR("surface volume: zarr (from render) or a layer folder"),
       "purpose": STR("target, benchmark or smoke", enum=INK_PURPOSES),
       "experiment": STR("ledger slug (required for target)"),
       **ENGINE_ARGS,
       "variants": ARR("maps to make: f forward, r reverse (control), s depth-shuffled (control); default f, r",
                       {"type": "string", "enum": ["f", "r", "s"]}, minItems=1),
       "layers": ARR("source layer window [start, stop) (default all; the model centre-crops its depth)",
                     {"type": "integer"}, minItems=2, maxItems=2),
       "box": ARR("torchscript: window r0, r1, c0, c1 in pixels (default whole)", {"type": "integer"},
                  minItems=4, maxItems=4),
       "stride": INT("patch stride in pixels", minimum=1), "seed": INT("shuffle seed (default 20261007)"),
       "out": STR("output folder (default work/vc3d/ink/<time>-<engine>, or under the experiment)"),
       "timeout": INT("seconds (default 24 h)", minimum=1)},
      required=["input", "purpose"], background=True)
def h_ink(ctx, a):
    variants = a.get("variants") or ["f", "r"]
    if a["purpose"] in ("target", "benchmark") and not {"f", "r"} <= set(variants):
        raise ToolError("the reverse-depth control is required next to the forward map (AGENTS.md rule 4): "
                        "variants must include f and r")
    inp = existing(ctx, a["input"], "input")
    engine, eargv, spec = _engine(ctx, a)
    out, slug_ = _ink_out(ctx, a, "ink", engine)
    started = now()
    argv = [ink_python(ctx), str(script("ink.py", "the ink tool")), "--input", str(inp), "--out", str(out),
            "--variants", ",".join(variants), *eargv]
    if a.get("layers"):
        argv += ["--layer-start", str(a["layers"][0]), "--layer-end", str(a["layers"][1])]
    if a.get("box"):
        argv += ["--box", ",".join(str(v) for v in a["box"])]
    if a.get("stride"):
        argv += ["--stride", str(a["stride"])]
    argv += ["--seed", str(a.get("seed", 20261007))]
    log = out / "ink.log"
    rc, seconds = run_logged(ctx, argv, log, env=dict(ctx.env, PYTHONPATH=str(ROOT)),
                             timeout=a.get("timeout", 24 * 3600), cwd=str(ROOT))
    summary = {}
    if (out / "ink.json").is_file():
        summary = json.loads((out / "ink.json").read_text())
    # the device asked for and the one the engine's output named: villa's inference can take MPS on a Mac when
    # asked for cpu (KIT_AUTOPIPE_DEVICE in autopipe)
    used = summary.get("engine") if isinstance(summary.get("engine"), dict) else {}
    device = {"asked": a.get("device", "cpu"), "reported": used.get("device_reported")}
    result = {"exit": rc, "seconds": seconds, "out": str(out), "purpose": a["purpose"], "engine": engine,
              "device": device, "maps": summary.get("maps"), "comparison": summary.get("comparison"),
              "log": str(log),
              "note": "model output, not a reading; compare forward with the controls before saying anything"}
    render, warnings = render_provenance(inp)
    lossy = vc3d_io.volcomp_source(inp)
    if lossy:
        warnings = warnings + [f"the ink input itself is lossy: {lossy}"]
    if render:
        result["render"] = render
    if warnings:
        result["warnings"] = warnings
    if rc != 0:
        result["log_tail"] = tail(log, 30)
    maps = [m["path"] for m in (summary.get("maps") or {}).values() if m.get("path")]
    result["receipt"] = write_receipt(ctx, out, "ink", a, [{"argv": argv, "exit": rc, "seconds": seconds}], maps,
                                      started, engine=spec, device=device,
                                      inputs={"input": light_fingerprint(inp)})
    if slug_ and rc == 0 and maps:
        try:
            ledger.add_provenance(slug_, shlex.join(argv), files=maps, root=ctx.root / "experiments")
            result["ledger"] = f"provenance added to experiments/{slug_}/run.json"
        except ledger.LedgerError as exc:
            result["ledger"] = f"not recorded: {exc}"
    return result


@tool("detectability", "Detectability probe", "Would this window have shown ink if there were any? Plants "
      "synthetic strokes of known contrast on the sheet face of a rendered stack and runs the same ink model again; "
      "reports the faintest contrast whose strokes come back (ink lift). A window that recovers nothing is blind, "
      "and a null there says nothing. Ported from axiosdevs/herculaneum-scroll-tools. self_test checks the probe "
      "itself on synthetic detectors without any model.",
      {"stack": STR("surface volume: zarr or layer folder"),
       "purpose": STR("target, benchmark or smoke", enum=INK_PURPOSES), "experiment": STR("ledger slug (target)"),
       **ENGINE_ARGS,
       "box": ARR("window y0, y1, x0, x1 in pixels (default a central 512 square)", {"type": "integer"},
                  minItems=4, maxItems=4),
       "amplitudes": ARR("planted contrasts in CT units (default 4, 8, 16, 32; above about 32 the test inverts)",
                         {"type": "number"}, minItems=1),
       "micron_per_pixel": NUM("pixel size in um (sets stroke width and line spacing)"),
       "face": STR("near (toward layer 0), far, or both (default both)", enum=["near", "far", "both"]),
       "reverse": BOOL("read the stack depth-reversed"), "threshold": NUM("probability threshold (default 0.5)"),
       "margin": NUM("ink lift that counts as recovered (default 0.05)"), "seed": INT("stroke layout seed"),
       "stride": INT("patch stride in pixels (v8in defaults to 21: nine runs of about 80 min each on four CPUs)",
                     minimum=1),
       "self_test": BOOL("only check the probe on synthetic detectors (needs numpy, no model)"),
       "out": STR("output folder"), "timeout": INT("seconds (default 12 h)", minimum=1)},
      background=True)
def h_detectability(ctx, a):
    started = now()
    argv = [ink_python(ctx), str(script("detectability.py", "the detectability tool"))]
    if a.get("self_test"):
        out = out_dir(ctx, a.get("out"), "detectability", f"{stamp()}-selftest")
        argv += ["--self-test", "--out", str(out)]
        engine_spec = None
    else:
        for k in ("stack", "purpose", "micron_per_pixel"):
            if a.get(k) is None:
                raise ToolError(f"detectability needs {k} (or self_test=true)")
        stack = existing(ctx, a["stack"], "stack")
        engine, eargv, engine_spec = _engine(ctx, a)
        out, slug_ = _ink_out(ctx, a, "detectability", engine)
        argv += ["--stack", str(stack), "--out", str(out), "--micron-per-pixel", str(a["micron_per_pixel"]), *eargv]
        if a.get("box"):
            argv += ["--box", ",".join(str(v) for v in a["box"])]
        if a.get("amplitudes"):
            argv += ["--amplitudes", ",".join(str(v) for v in a["amplitudes"])]
        for k in ("face", "threshold", "margin", "seed", "stride"):
            if a.get(k) is not None:
                argv += [f"--{k}", str(a[k])]
        if a.get("reverse"):
            argv += ["--reverse"]
    log = out / "detectability.log"
    rc, seconds = run_logged(ctx, argv, log, env=dict(ctx.env, PYTHONPATH=str(ROOT)),
                             timeout=a.get("timeout", 12 * 3600), cwd=str(ROOT))
    result = {"exit": rc, "seconds": seconds, "out": str(out), "log": str(log)}
    if (out / "detectability.json").is_file():
        result.update(json.loads((out / "detectability.json").read_text()))
    if rc != 0:
        result["log_tail"] = tail(log, 30)
    result["receipt"] = write_receipt(ctx, out, "detectability", a, [{"argv": argv, "exit": rc}], [], started,
                                      engine=engine_spec)
    return result


# ---------------------------------------------------------------- tools: the VC3D app

def _app(ctx):
    return vc3d_bridge.App(ctx.home)


def _bridge_socket(ctx):
    path = _app(ctx).socket()
    if not path:
        raise ToolError("no VC3D app is running with its agent bridge: call app_start")
    return path


@tool("app_start", "Start the VC3D app", "Start the VC3D app itself with no display (Qt offscreen) and its agent "
      "bridge on, detached, so app_call can drive it: open projects and catalog samples, grow and edit segments, "
      "place points, render, flatten, take screenshots. One app at a time.",
      {"name": STR("bridge name (default kit-vc3d)"), "args": ARR("extra VC3D arguments", {"type": "string"}),
       "open": STR("volume package (.volpkg, .volpkg.json or zarr project) to open once it is up"),
       "threads": INT("OpenMP threads", minimum=1), "timeout": INT("seconds to wait for the bridge (default 90)", minimum=5)},
      openworld=True)
def h_app_start(ctx, a):
    tools = ctx.tools()
    if not tools.has("VC3D"):
        raise ToolError(f"VC3D (the app) is not in {tools.bindir}; the command line tools work without it")
    env = vc3d.headless_env(ctx.env, threads=a.get("threads"))
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    try:
        rec = _app(ctx).start(tools.argv("VC3D", *a.get("args", [])), env, a.get("name", "kit-vc3d"),
                              timeout=a.get("timeout", 90))
        rec["ping"] = vc3d_bridge.call(rec["path"], "ping", timeout=30)
        if a.get("open"):
            rec["opened"] = vc3d_bridge.call(rec["path"], "volume.open",
                                             {"path": str(existing(ctx, a["open"], "project"))}, timeout=120)
    except (vc3d_bridge.BridgeError, OSError, TimeoutError) as exc:
        raise ToolError(f"VC3D app: {exc}") from exc
    rec["next"] = "app_call method=state.get, then app_methods to see the 120 bridge methods"
    return rec


@tool("app_methods", "List app methods", "The VC3D app's bridge methods with their parameters (rpc.describe), "
      "optionally only those starting with a prefix such as segmentation., render., flatten., catalog.",
      {"prefix": STR("method name prefix")}, readonly=True)
def h_app_methods(ctx, a):
    try:
        res = vc3d_bridge.call(_bridge_socket(ctx), "rpc.describe",
                               {"prefix": a["prefix"]} if a.get("prefix") else {}, timeout=30)
    except (vc3d_bridge.BridgeError, OSError, TimeoutError) as exc:
        raise ToolError(f"rpc.describe: {exc}") from exc
    methods = res.get("methods", {})
    items = methods.items() if isinstance(methods, dict) else ((m.get("name"), m) for m in methods)
    rows = []
    for name, m in sorted(items):
        params = (m.get("params") or {})
        props = params.get("properties", {})
        req = set(params.get("required", []))
        rows.append({"method": name, "params": {k: (v.get("type") if isinstance(v, dict) else v) for k, v in props.items()},
                     "required": sorted(req), "mcp_tool": (m.get("mcp") or {}).get("tool")})
    return {"count": len(rows), "methods": rows, "coverage": res.get("coverage")}


@tool("app_call", "Call an app method", "Call one VC3D bridge method with its JSON params, e.g. state.get, "
      "catalog.list_samples, volume.open, segments.list, segmentation.grow_patch_from_seed, render.tifxyz, "
      "job.status, screenshot.capture (returned as an image). Bridge errors come back with their code.",
      {"method": STR("bridge method name"), "params": OBJ("method parameters"),
       "timeout": NUM("seconds (default 60)", minimum=1, maximum=3600)},
      required=["method"], openworld=True)
def h_app_call(ctx, a):
    try:
        res = vc3d_bridge.call(_bridge_socket(ctx), a["method"], a.get("params"), timeout=a.get("timeout", 60))
    except vc3d_bridge.BridgeError as exc:
        raise ToolError(f"{a['method']} failed: {exc}") from exc
    except (OSError, TimeoutError) as exc:
        raise ToolError(f"{a['method']}: {exc}") from exc
    if isinstance(res, dict) and isinstance(res.get("base64"), str) and res.get("format") == "png":
        import base64
        dest = fresh(ctx.home / "previews" / f"app-{slug(a['method'])}-{stamp()}.png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(res["base64"]))
        res = dict(res, base64=f"(saved to {dest})", png=str(dest), _images=[str(dest)])
    return res if isinstance(res, dict) else {"result": res}


@tool("app_screenshot", "Screenshot the app", "A PNG of the VC3D window or one viewer, returned as an image.",
      {"target": STR("window (default) or a viewer id/name"), "max_dim": INT("longest side in pixels", minimum=16)},
      readonly=True)
def h_app_screenshot(ctx, a):
    params = {"target": a.get("target", "window")}
    if a.get("max_dim"):
        params["maxDim"] = a["max_dim"]
    return h_app_call(ctx, {"method": "screenshot.capture", "params": params, "timeout": 60})


@tool("app_stop", "Stop the app", "Stop the VC3D app started by app_start.", destructive=True)
def h_app_stop(ctx, a):
    return _app(ctx).stop()


# ---------------------------------------------------------------- shell entry and background jobs

def cli(args):
    """`kit vc3d tools` and `kit vc3d call`: the MCP server's tools for agents that have a shell instead."""
    if args.action == "tools":
        if args.json:
            print(json.dumps([{"name": t.name, "title": t.title, "description": t.description,
                               "inputSchema": t.schema(), "annotations": t.annotations()} for t in TOOLS.values()],
                             indent=1))
            return 0
        for t in TOOLS.values():
            print(f"{t.name:15s} {re.split(r'(?<=[a-z0-9)])[.:] (?=[A-Z])', t.description)[0].rstrip('.')}")
        print("\npython -m kit vc3d call TOOL '{...}'  runs one; python -m kit vc3d tools --json gives the arguments")
        return 0
    text = args.arguments
    try:
        if text.startswith("@"):
            text = Path(text[1:]).read_text()
        params = json.loads(text) if text.strip() else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"arguments must be a JSON object: {exc}"}))
        return 2
    if args.background:
        params["background"] = True
    ctx = Context(progress=lambda m: print(m, file=sys.stderr, flush=True))
    try:
        result = call(args.tool, params, ctx)
    except ToolError as exc:
        print(json.dumps({"error": str(exc)}, indent=1))
        return 2
    result.pop("_images", None)
    print(json.dumps(result, indent=1, default=str))
    return 0 if result.get("exit") in (None, 0) else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "job":
        return job_main(argv[1])
    print("usage: python -m kit.vc3d_agent job JOBDIR  (started by the server; use python -m kit vc3d call)",
          file=sys.stderr)
    return 2


def _load_extensions():
    """Optional tool sets: every kit/vc3d_ext_*.py beside this module, in name order, registered on this module.
    A kit without them still serves every other tool."""
    import importlib
    import pkgutil
    for info in sorted(pkgutil.iter_modules([str(Path(__file__).resolve().parent)]), key=lambda i: i.name):
        if info.name.startswith("vc3d_ext_"):
            importlib.import_module(f"{__package__}.{info.name}").register(sys.modules[__name__])


_load_extensions()
from . import vc3d_prep_tools  # noqa: E402  (registers seed_check, trim, volume_meta and merge_patch; see kit/vc3d_prep_tools.py)
vc3d_prep_tools.register(sys.modules[__name__])
from . import autopipe  # noqa: E402  (registers umbilicus, seeds, distortion and autopipe; see kit/autopipe.py)
autopipe.register(sys.modules[__name__])


if __name__ == "__main__":
    sys.exit(main())
