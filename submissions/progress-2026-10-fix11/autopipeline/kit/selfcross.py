"""Does a tifxyz surface pass through itself? villa's self-intersection census, with two backends.

villa's vc_tifxyz_selfcross counted a surface's non-adjacent transverse self-intersections under both quad
triangulations. AutoPipeline's qa stage rejects a trace that has any (qa.max_selfcross 0). villa main removed the
tool, its census kernel and their tests in e1aa625a6 (29 Oct 2026, villa #2358), and nothing on main replaces it, so
a villa build made after that has no self-intersection check. This module keeps the check as a swappable backend:

  villa    villa's vc_tifxyz_selfcross binary, when the VC3D build kit uses has it (an AppImage or build made before
           e1aa625a6). Its report is used as it writes it.
  kernel   villa's census kernel, vc_tifxyz_selfcross_impl.hpp at villa 7154682e1 (the last commit with it),
           compiled on this machine by `python -m kit selfcross build` with our driver
           (scripts/selfcross/selfcross_kernel.cpp) and a stand-in for the two OpenCV types it uses
           (scripts/selfcross/shim). The header is fetched from villa at that commit and checked by sha256 (or read
           from KIT_SELFCROSS_HEADER); it is never copied into this repository. villa's code is GPL-3.0, so the
           built binary is too and stays where it was built. The grid is loaded here the way VC3D's
           load_quad_from_tifxyz loads it: a cell with z <= 0 is invalid, and mask.tif applies (channel 0 under 255
           invalidates; a mask an integer multiple of the grid invalidates a cell when any pixel of its block
           does). Nothing else invalidates: a cell with x = -1 and z > 0 stays, as in VC3D.
  auto     villa when the build has it, else kernel (the default).

The kernel backend writes the report vc_tifxyz_selfcross writes (the same keys, census rows and contact fields, so
every reader of that report reads it), with its own `tool` and a `kernel` block naming the villa commit and the
header's and driver's sha256. It has no --collection.

  python -m kit selfcross build [--header FILE] [--cxx g++] [--force]   compile the kernel backend
  python -m kit selfcross status [--json]                               which backends this machine has
  python -m kit selfcross run --surface S -o REPORT.json [--backend auto|villa|kernel] [--threads N]
                              [--exclude 1] [--maxedge 60] [--cell 40] [--fail-on-crossing]

Exit codes of run: 0 the census ran (whatever it found), 1 an error, 2 no backend, 3 --fail-on-crossing and a
transverse contact was found (as vc_tifxyz_selfcross). Parity: on 51 synthetic tifxyz surfaces the kernel backend's
report matched villa's vc_tifxyz_selfcross at 7154682e1 in every count, contact and site (tests/test_selfcross.py
holds the fixtures; docs/tools/selfcross.md the record). Standard library, with numpy for the grid.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from . import kithome

VILLA_COMMIT = "7154682e174205bcaafe06a4962668becd85bb56"
HEADER_NAME = "vc_tifxyz_selfcross_impl.hpp"
HEADER_PATH = f"volume-cartographer/apps/src/{HEADER_NAME}"
HEADER_SHA256 = "307e3d33ee672c84d6a683aeae40fc8d80801a16785ced843d4520bbdb7ae64b"
HEADER_URL = f"https://raw.githubusercontent.com/ScrollPrize/villa/{VILLA_COMMIT}/{HEADER_PATH}"
DRIVER = "scripts/selfcross/selfcross_kernel.cpp"
SHIM = "scripts/selfcross/shim"
SHIM_FILE = "opencv2/core/mat.hpp"
VILLA_TOOL = "vc_tifxyz_selfcross"
BINARY = "selfcross_kernel"
ENV_HEADER = "KIT_SELFCROSS_HEADER"     # a local copy of the header (checked by sha256 like a fetched one)
ENV_BIN = "KIT_SELFCROSS_BIN"           # a kernel binary built elsewhere
BACKENDS = ("villa", "kernel")
CHOICES = ("auto",) + BACKENDS
DEFAULTS = {"exclude": 1, "maxedge": 60.0, "cell": 40.0}
NOTE = ("clean means no non-adjacent transverse contact under either quad triangulation, on the surface as VC3D "
        "loads it (z <= 0 cells invalid, mask.tif applied); coplanar and grazing contacts are counted but are not "
        "crossings (two sheets pressed flat against each other are coplanar)")


class SelfcrossError(RuntimeError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _numpy():
    try:
        import numpy as np
    except ImportError as exc:     # pragma: no cover - numpy is a dependency of the package
        raise SelfcrossError("the kernel backend needs numpy to read the tifxyz grid") from exc
    return np


# ------------------------------------------------------------------------------------------------------ building

def build_root(env=None):
    return kithome.path("work", "selfcross", env=env)


def source_bytes():
    """(driver bytes, shim bytes): the two files of ours the kernel binary is built from."""
    try:
        driver = kithome.source_file(DRIVER, "the kernel self-intersection backend").read_bytes()
        shim = (kithome.source_file(SHIM, "the kernel self-intersection backend") / SHIM_FILE).read_bytes()
    except kithome.MissingSource as exc:
        raise SelfcrossError(str(exc)) from exc
    return driver, shim


def build_key(driver, shim):
    """What a kernel binary is built from, as one digest: the header's sha256 and our two files."""
    return _sha(HEADER_SHA256.encode() + b"\0" + _sha(driver).encode() + b"\0" + _sha(shim).encode())


def build_dir(env=None):
    driver, shim = source_bytes()
    return build_root(env) / f"kernel-{build_key(driver, shim)[:16]}"


def header(given=None, env=None, fetch=True, timeout=60):
    """The census header's bytes, checked against HEADER_SHA256: from `given` or KIT_SELFCROSS_HEADER, else the
    copy a build cached, else fetched from villa at VILLA_COMMIT (and cached)."""
    env = os.environ if env is None else env
    src = given or (env.get(ENV_HEADER) or "").strip() or None
    cache = build_root(env) / f"villa-{VILLA_COMMIT[:9]}" / HEADER_NAME
    if src:
        try:
            data = Path(src).expanduser().read_bytes()
        except OSError as exc:
            raise SelfcrossError(f"cannot read the census header {src}: {exc}") from exc
        where = str(src)
    elif cache.is_file():
        data, where = cache.read_bytes(), str(cache)
    elif not fetch:
        raise SelfcrossError(f"the census header is not cached in {cache.parent}; run `python -m kit selfcross "
                             f"build` (it fetches {HEADER_URL}) or set {ENV_HEADER}")
    else:
        try:
            with urllib.request.urlopen(HEADER_URL, timeout=timeout) as r:
                data = r.read()
        except OSError as exc:
            raise SelfcrossError(f"could not fetch the census header {HEADER_URL}: {exc}. Without network, set "
                                 f"{ENV_HEADER} to a copy of {HEADER_PATH} from villa {VILLA_COMMIT[:9]}") from exc
        where = HEADER_URL
    got = _sha(data)
    if got != HEADER_SHA256:
        raise SelfcrossError(f"the census header from {where} has sha256 {got}, not {HEADER_SHA256} (villa "
                             f"{VILLA_COMMIT[:9]}'s {HEADER_PATH}): refused")
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cache)
    return data, where


def find_compiler(cxx=None, env=None):
    env = os.environ if env is None else env
    for name in ([cxx] if cxx else [env.get("CXX") or None, "c++", "g++", "clang++"]):
        if name and shutil.which(name):
            return shutil.which(name)
    return None


def build(cxx=None, given_header=None, force=False, env=None, timeout=600):
    """Compile the kernel backend into the kit home (work/selfcross/kernel-<key>/). Returns its build record."""
    driver, shim = source_bytes()
    out = build_dir(env)
    binary = out / BINARY
    rec_path = out / "build.json"
    if binary.is_file() and rec_path.is_file() and not force:
        rec = json.loads(rec_path.read_text())
        rec["reused"] = True
        return rec
    compiler = find_compiler(cxx, env)
    if compiler is None:
        raise SelfcrossError("no C++17 compiler found (set CXX, or install g++ or clang++; on a Mac, "
                             "`xcode-select --install`)")
    data, where = header(given_header, env)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = Path(tmp)
        (tmp / "inc").mkdir()
        (tmp / "inc" / HEADER_NAME).write_bytes(data)
        (tmp / "shim" / "opencv2" / "core").mkdir(parents=True)
        (tmp / "shim" / SHIM_FILE).write_bytes(shim)
        (tmp / "selfcross_kernel.cpp").write_bytes(driver)
        argv = [compiler, "-O2", "-std=c++17", "-I", str(tmp / "shim"), "-I", str(tmp / "inc"),
                str(tmp / "selfcross_kernel.cpp"), "-o", str(tmp / BINARY), "-pthread"]
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SelfcrossError(f"the kernel build did not finish: {exc}") from exc
        if p.returncode != 0:
            raise SelfcrossError(f"the kernel build failed (exit {p.returncode}):\n{(p.stderr or p.stdout)[-3000:]}")
        os.replace(tmp / BINARY, binary)
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True).stdout.splitlines()[:1]
    rec = {"backend": "kernel", "binary": str(binary), "villa_commit": VILLA_COMMIT, "header": HEADER_PATH,
           "header_sha256": HEADER_SHA256, "header_from": where, "driver_sha256": _sha(driver),
           "shim_sha256": _sha(shim), "build_key": build_key(driver, shim), "compiler": compiler,
           "compiler_version": version[0] if version else None, "built": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                                         time.gmtime()),
           "licence": "the binary holds villa's GPL-3.0 census kernel: it is a GPL-3.0 work; keep it on this machine"}
    tmp = rec_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1) + "\n")
    os.replace(tmp, rec_path)
    return rec


def kernel_binary(env=None):
    """(path, build record) of the kernel backend this machine has, or (None, why not)."""
    env = os.environ if env is None else env
    given = (env.get(ENV_BIN) or "").strip()
    if given:
        p = Path(given).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p, {"backend": "kernel", "binary": str(p), "given": ENV_BIN}
        return None, (f"{ENV_BIN}={given} is not an executable file (unset it to use the kernel built by "
                      "`python -m kit selfcross build`)")
    try:
        out = build_dir(env)
    except SelfcrossError as exc:
        return None, str(exc)
    p, rec = out / BINARY, out / "build.json"
    if p.is_file() and os.access(p, os.X_OK) and rec.is_file():
        try:
            return p, json.loads(rec.read_text())
        except (OSError, ValueError) as exc:
            return None, f"the kernel build record {rec} is unreadable ({exc}); rebuild with --force"
    return None, "the kernel backend is not built (run `python -m kit selfcross build`)"


def villa_has(tools):
    return tools is not None and tools.has(VILLA_TOOL)


def resolve(backend="auto", tools=None, env=None):
    """(backend name, None) for the backend that runs, or (None, why none can)."""
    if backend not in CHOICES:
        raise SelfcrossError(f"selfcross backend {backend!r}: choices are {', '.join(CHOICES)}")
    if backend in ("auto", "villa") and villa_has(tools):
        return "villa", None
    why = [f"{VILLA_TOOL} is not in the VC3D build (villa removed it in e1aa625a6)"] \
        if backend in ("auto", "villa") else []
    if backend in ("auto", "kernel"):
        p, rec = kernel_binary(env)
        if p is not None:
            return "kernel", None
        why.append(rec)
    return None, "; ".join(why)


def argv(backend, surface, report, tools=None, threads=None, params=None):
    """The command that writes `report` for `surface` with this backend (resolve() picked it)."""
    p = {**DEFAULTS, **(params or {})}
    extra = []
    for k in ("exclude", "maxedge", "cell"):
        if p[k] != DEFAULTS[k]:
            extra += [f"--{k}", p[k]]
    th = [] if threads is None else ["--threads", threads]
    if backend == "villa":
        return tools.argv(VILLA_TOOL, "--surface", surface, "-o", report, *th, *extra)
    if backend == "kernel":
        return [sys.executable, "-m", "kit", "selfcross", "run", "--backend", "kernel", "--surface", str(surface),
                "-o", str(report), *map(str, th), *map(str, extra)]
    raise SelfcrossError(f"no backend {backend!r}")


def unavailable_text(why):
    return f"no self-intersection backend ({why})"


# ------------------------------------------------------------------------------------------------------ the census

def load_grid(surface):
    """The (rows, cols, 3) float32 grid VC3D's load_quad_from_tifxyz gives for a tifxyz folder: z <= 0 cells and the
    cells mask.tif rejects set to (-1, -1, -1). NaN cells stay NaN (the kernel skips any quad with one)."""
    from . import meshqa
    np = _numpy()
    p = meshqa.load_patch(surface)
    if p.read_errors:
        raise SelfcrossError(f"cannot read {surface}: " + "; ".join(f"{k}: {v}" for k, v in p.read_errors.items()))
    if not p.shapes_agree():
        raise SelfcrossError(f"{surface}: x, y and z grids differ in shape ({p.x.shape}, {p.y.shape}, {p.z.shape})")
    xyz = np.stack([p.x, p.y, p.z], axis=-1).astype(np.float32)
    with np.errstate(invalid="ignore"):
        bad = p.z <= 0
    mask, _how = p.mask_valid()
    if mask is not None:
        bad |= ~mask
    xyz[bad] = -1.0
    return np.ascontiguousarray(xyz)


def _threads(threads):
    n = int(threads or 0)
    return n if n > 0 else (os.cpu_count() or 4)


def run_kernel(surface, report, threads=None, binary=None, env=None, timeout=None, echo=False, **params):
    """The kernel backend on one tifxyz: writes `report` as vc_tifxyz_selfcross would. Returns the report. echo: pass
    the kernel's per-diagonal counts on to stderr (the command line does)."""
    p = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    if not (isinstance(p["cell"], (int, float)) and p["cell"] > 0 and p["cell"] < float("inf")):
        raise SelfcrossError(f"--cell must be a finite positive number of voxels (got {p['cell']})")
    if int(p["exclude"]) != p["exclude"] or p["exclude"] < 0:
        raise SelfcrossError(f"--exclude must be a whole number, 0 or more (got {p['exclude']})")
    if not (p["maxedge"] >= 0 and p["maxedge"] < float("inf")):
        raise SelfcrossError(f"--maxedge must be a finite number, 0 or more; 0 disables it (got {p['maxedge']})")
    rec = None
    if binary is None:
        binary, rec = kernel_binary(env)
        if binary is None:
            raise SelfcrossError(rec)
    grid = load_grid(surface)
    rows, cols = grid.shape[:2]
    report = Path(report)
    with tempfile.TemporaryDirectory() as tmp:
        raw, part = Path(tmp) / "grid.f32", Path(tmp) / "census.json"
        grid.tofile(raw)
        cmd = [str(binary), str(raw), str(rows), str(cols), str(part), "--exclude", str(int(p["exclude"])),
               "--maxedge", repr(float(p["maxedge"])), "--cell", repr(float(p["cell"])),
               "--threads", str(_threads(threads))]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SelfcrossError(f"the kernel did not finish: {exc}") from exc
        if proc.stderr and echo:
            sys.stderr.write(proc.stderr)
        if proc.returncode != 0 or not part.is_file():
            raise SelfcrossError(f"the kernel exited {proc.returncode}: {proc.stderr.strip()[-2000:]}")
        census = json.loads(part.read_text())
    total = sum(int(d["transverse"]) for d in census["census"])
    rec = rec if isinstance(rec, dict) else {}
    out = {"tool": "kit selfcross (villa's vc_tifxyz_selfcross census kernel)", "backend": "kernel",
           "kernel": {"villa_commit": VILLA_COMMIT, "header": HEADER_PATH, "header_sha256": HEADER_SHA256,
                      **{k: rec.get(k) for k in ("driver_sha256", "shim_sha256", "compiler_version") if rec.get(k)},
                      # a binary named by KIT_SELFCROSS_BIN was not built here, so nothing checked what it came from
                      **({"given": rec["given"], "unverified": True} if rec.get("given") else {})},
           "report_only": True, "surface": str(surface), "clean_of_transverse_self_intersection": total == 0,
           "note": NOTE,
           "parameters": {"exclude": int(p["exclude"]), "maxedge": float(p["maxedge"]), "cell": float(p["cell"]),
                          "touch_tolerance": census.get("touch_tolerance"), "diagonals": [0, 1]},
           "grid_rows": rows, "grid_cols": cols, "census": census["census"]}
    report.parent.mkdir(parents=True, exist_ok=True)
    tmp = report.with_name(report.name + ".tmp")
    tmp.write_text(json.dumps(out, indent=4))
    os.replace(tmp, report)
    return out


def transverse(report):
    """Transverse contacts over both diagonals of a report (either backend's)."""
    return sum(int(d.get("transverse", 0)) for d in report.get("census", []))


def census(surface, report, backend="auto", tools=None, threads=None, timeout=3600, env=None, log=None, **params):
    """Run the chosen backend on one surface, in a child process, and read its report. Returns {"backend", "exit",
    "report": path, "parsed": report dict} or, when nothing could run or the report is unreadable, the same with
    "error" (and no "parsed"). The callers that log through their own runner use resolve() and argv() instead."""
    name, why = resolve(backend, tools, env)
    if name is None:
        return {"backend": None, "exit": None, "error": unavailable_text(why)}
    cmd = argv(name, surface, report, tools, threads, params)
    run_env = dict(os.environ if env is None else env)
    try:
        p = subprocess.run([str(a) for a in cmd], capture_output=True, text=True, timeout=timeout, env=run_env)
        rc, text = p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        rc, text = f"{type(exc).__name__}", str(exc)
    if log is not None:
        with open(log, "a") as fh:
            fh.write("$ " + " ".join(map(str, cmd)) + "\n" + text)
    out = {"backend": name, "exit": rc, "report": str(report)}
    try:
        out["parsed"] = json.loads(Path(report).read_text())
    except (OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}" + (f"; {text.strip()[-500:]}" if text.strip() else "")
    return out


def report_json(surface, tools=None, threads=2, timeout=3600, env=None, backend="auto"):
    """(backend, report dict, exit code) for one surface in a scratch folder: the callers that read the report and
    keep no file (kit regioncrop, kit gscore). Raises SelfcrossError when no backend can run or no
    report was written."""
    with tempfile.TemporaryDirectory() as tmp:
        got = census(surface, Path(tmp) / "selfcross.json", backend, tools, threads, timeout, env)
    if got["backend"] is None:
        raise SelfcrossError(got["error"])
    if "parsed" not in got:
        raise SelfcrossError(f"{got['backend']} self-intersection backend failed on {surface} (exit {got['exit']}): "
                             f"{got.get('error')}")
    return got["backend"], got["parsed"], got["exit"]


def status(tools=None, env=None):
    """What this machine has for each backend, and which `auto` picks."""
    if tools is None:
        from . import vc3d
        try:
            tools = vc3d.find_tools(env)
        except Exception:      # noqa: BLE001 - status reports, never fails
            tools = None
    kb, krec = kernel_binary(env)
    picked, why = resolve("auto", tools, env)
    return {"villa": {"found": villa_has(tools), "tool": VILLA_TOOL,
                      "where": str(tools.path(VILLA_TOOL)) if tools is not None else None},
            "kernel": {"found": kb is not None, "binary": str(kb) if kb else None,
                       **({"build": krec} if kb is not None else {"why": krec}),
                       "compiler": find_compiler(env=env), "villa_commit": VILLA_COMMIT,
                       "header_sha256": HEADER_SHA256},
            "auto": picked, **({"why": why} if picked is None else {})}


# ------------------------------------------------------------------------------------------------------ command line

def build_parser(p=None):
    p = p or argparse.ArgumentParser(prog="kit selfcross", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="selfcross_cmd", required=True)
    b = sub.add_parser("build", help="compile the kernel backend (fetches villa's census header at 7154682e1)")
    b.add_argument("--header", help=f"a local copy of {HEADER_PATH} (else {ENV_HEADER}, the cache, or fetched)")
    b.add_argument("--cxx", help="the C++17 compiler (default $CXX, c++, g++ or clang++)")
    b.add_argument("--force", action="store_true", help="rebuild even when a build exists")
    b.add_argument("--json", action="store_true")
    s = sub.add_parser("status", help="which backends this machine has, and which auto picks")
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("run", help="census one tifxyz surface")
    r.add_argument("--surface", required=True, help="tifxyz folder")
    r.add_argument("-o", "--output", required=True, help="report file (.json)")
    r.add_argument("--backend", choices=CHOICES, default="auto")
    r.add_argument("--threads", type=int, default=0, help="worker threads; 0 = all cores")
    r.add_argument("--exclude", type=int, default=DEFAULTS["exclude"],
                   help="grid-index adjacency left out (default 1: quads that share a vertex)")
    r.add_argument("--maxedge", type=float, default=DEFAULTS["maxedge"],
                   help="drop quads with an edge longer than this many voxels (default 60; 0 disables)")
    r.add_argument("--cell", type=float, default=DEFAULTS["cell"],
                   help="broad-phase cell in voxels (default 40; changes speed, never the counts)")
    r.add_argument("--fail-on-crossing", action="store_true", help="exit 3 when a transverse contact is found")
    return p


def main(argv_=None, args=None):
    args = args or build_parser().parse_args(argv_)
    cmd = args.selfcross_cmd
    if cmd == "build":
        try:
            rec = build(args.cxx, args.header, args.force)
        except SelfcrossError as exc:
            print(f"selfcross build: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(rec, indent=1))
        else:
            print(("reused " if rec.get("reused") else "built ") + rec["binary"])
            print(f"villa {VILLA_COMMIT[:9]} {HEADER_PATH} sha256 {HEADER_SHA256[:16]}...")
            print(rec["licence"])
        return 0
    if cmd == "status":
        st = status()
        if args.json:
            print(json.dumps(st, indent=1))
        else:
            print(f"villa   {'found' if st['villa']['found'] else 'missing'}  {st['villa']['where'] or VILLA_TOOL}")
            print(f"kernel  {'found' if st['kernel']['found'] else 'missing'}  "
                  f"{st['kernel']['binary'] or st['kernel'].get('why')}")
            print(f"auto    {st['auto'] or 'none: ' + st.get('why', '')}")
        return 0
    from . import vc3d
    try:
        tools = vc3d.find_tools()
    except Exception:      # noqa: BLE001 - a broken VC_APPIMAGE leaves the kernel
        tools = None
    name, why = resolve(args.backend, tools)
    if name is None:
        print(f"selfcross: {unavailable_text(why)}", file=sys.stderr)
        return 2
    params = {"exclude": args.exclude, "maxedge": args.maxedge, "cell": args.cell}
    if name == "villa":
        cmd_ = argv("villa", args.surface, args.output, tools, args.threads or None, params)
        if args.fail_on_crossing:
            cmd_.append("--fail-on-crossing")
        return subprocess.run([str(a) for a in cmd_]).returncode
    try:
        rep = run_kernel(args.surface, args.output, threads=args.threads, echo=True, **params)
    except SelfcrossError as exc:
        print(f"selfcross: {exc}", file=sys.stderr)
        return 1
    n = transverse(rep)
    print(f"Report written to {args.output}")
    print("No non-adjacent transverse self-intersection found." if n == 0 else
          f"Surface has non-adjacent transverse self-intersections: {rep['census'][0]['transverse']} contacts on "
          f"diagonal 0, {rep['census'][1]['transverse']} on diagonal 1.")
    return 3 if n and args.fail_on_crossing else 0


if __name__ == "__main__":
    sys.exit(main())
