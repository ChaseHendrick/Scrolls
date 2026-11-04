"""Villa ports: which references in your Python scripts break at a villa commit, and what to use instead.

villa PR #2440 (the vc_reader takeover, merged 4 Nov 2026 as baf5e605b) removed `vesuvius.tifxyz` and
`vesuvius.image_proc` from villa's `vesuvius` package, moved several modules, and dropped zarr and tifffile from the
package's dependencies. A script that imports villa's package can break at any later villa commit without anyone
noticing until it runs. This tool finds every reference to villa's Python packages in a folder of yours and
resolves it against villa's tree at a commit. It only reads:

  python3 -m kit villaports scan [--root PATH ...] [--villa REF] [--exclude GLOB ...] [--json]
  python3 -m kit villaports diff --from OLD [--to NEW] [--root PATH ...] [--json]

What counts as a reference (the packages are listed in kit/data/villaports-map.json, `packages`):

  - in .py files, parsed with ast: `import vesuvius.x`, `from vesuvius.x import a, b`, calls of
    importlib.import_module, runpy.run_module, importlib.util.find_spec and __import__ with a constant name, a list
    or tuple holding "-m" then "vesuvius.x", and string constants (not docstrings) holding `-m vesuvius.x` or a
    `from vesuvius.x import a` / `import vesuvius.x` statement (code for `python -c`); a file ast cannot parse is
    read line by line instead;
  - in shell scripts, YAML, JSON, TOML, .cfg files and Dockerfiles, line by line: `python -m vesuvius.x` (any
    python, any flags before -m), the "-m", "vesuvius.x" list form, and import statements (heredocs, `python -c`);
    lines starting with `#` are comments and skipped.

Where it looks: every such file under each --root (default the current folder). Left out by default
(DEFAULT_EXCLUDES; --no-default-excludes scans them): files git ignores when the root is in a git work tree, version
control, virtual environment, cache, build and dependency folders, and vendored copies of villa's packages (a
folder named like a scanned package that holds an __init__.py), which are villa's code rather than yours. Each
--exclude GLOB leaves out more: a file whose path from the root, or any of its folders, matches GLOB. This tool's
own files are never scanned, since its map and tests name villa modules on purpose.

Each reference resolves to one status: ok; ok-via-shim (villa's import breaks, but it sits in a try block whose
`except ImportError` imports the same names from a module of yours that is in the scanned folder and defines
them); missing-module (a module in the dotted path is not in villa's tree at REF, or `-m` names a package without
__main__.py); missing-name (the module is there but defines no such top-level name: functions, classes,
assignments, imports and re-exports, including those under top-level if, try and with blocks, and submodules of a
package); unknown (the module has `from x import *` or a module-level __getattr__, or does not parse, so a name
cannot be ruled out). When the importing file's own folder holds a copy of the package, Python imports that copy
first, so the reference is resolved against the copy instead of villa. Attribute use after an import
(`vesuvius.a.b.func(...)`), villa's console scripts and third-party dependencies (zarr, tifffile) are not checked.

A suggested replacement for a break comes from the curated map kit/data/villaports-map.json (entries read from the
#2440 diff, each naming the villa file at baf5e605b that holds the replacement), checked against villa's tree at
REF; without a map entry, a missing name is looked up among the top-level definitions of the package at REF.

Villa access: a blobless partial clone cached at default_cache() ($XDG_CACHE_HOME/scrolls-villaports/villa.git,
or under ~/.cache), or at --cache PATH, made and updated with anonymous git (`git clone --filter=blob:none --bare`); the blobs it needs are fetched in one batch and
read with `git cat-file --batch`. `--villa-git PATH` reads an existing clone instead (never fetched, except missing
blobs of a partial clone). `--offline` uses the cache as it is. The GitHub REST API is never used.

Exit codes: 0 nothing breaks, 3 a reference breaks (scan) or a module or name your code uses was removed (diff), 1
an error, 75 villa could not be reached and no cached clone exists. Standard library only.
"""

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXIT_OK, EXIT_FAIL, EXIT_ATTENTION, EXIT_UNREACHABLE = 0, 1, 3, 75
VILLA_URL = "https://github.com/ScrollPrize/villa"
MAP_FILE = ROOT / "kit" / "data" / "villaports-map.json"
TAKEOVER = "baf5e605bb42a3d55a62b7c5c728e0908137225c"  # villa #2440, the vc_reader takeover
DEFAULT_PACKAGES = OrderedDict([("vesuvius", ["vesuvius/src/vesuvius"])])

OK, MISSING_MODULE, MISSING_NAME, UNKNOWN = "ok", "missing-module", "missing-name", "unknown"
SHIM = "ok-via-shim"  # villa's import fails, and the ImportError fallback to a module of yours resolves
BREAKS = (MISSING_MODULE, MISSING_NAME)
STATUSES = (OK, SHIM, MISSING_MODULE, MISSING_NAME, UNKNOWN)

# Folder names left out unless --no-default-excludes: version control, environments, caches, builds, dependencies.
DEFAULT_EXCLUDES = (".git", ".hg", ".svn", ".venv", "venv", "env", ".env", ".tox", ".nox", "__pycache__",
                    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".ipynb_checkpoints", "node_modules",
                    "site-packages", "build", "dist", ".eggs", "*.egg-info")
SELF = (Path(__file__).resolve(), MAP_FILE.resolve(), (ROOT / "tests" / "test_villaports.py").resolve())
TEXT_SUFFIXES = (".sh", ".bash", ".zsh", ".yml", ".yaml", ".json", ".toml", ".cfg")
MAX_BYTES = 8 * 1024 * 1024

LOCAL_GIT_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR",
                       "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")
GIT_CONFIG = ("-c", "core.hooksPath=" + os.devnull, "-c", "credential.helper=", "-c", "gc.auto=0",
              "-c", "maintenance.auto=false", "-c", "fetch.writeCommitGraph=false")


def default_cache(environ=None):
    """Where the villa clone is cached: $XDG_CACHE_HOME/scrolls-villaports/villa.git, else under ~/.cache."""
    environ = os.environ if environ is None else environ
    base = environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "scrolls-villaports" / "villa.git"


class VillaError(RuntimeError):
    """Villa's tree could not be read (a bad ref, a failed fetch): exit 1."""


class Unreachable(VillaError):
    """Villa could not be reached and there is no cached clone: exit 75."""


# Your references -----------------------------------------------------------------------------------------------

class Ref:
    """One reference to a villa module in a scanned file."""

    __slots__ = ("path", "line", "module", "names", "kind", "fallbacks", "file")

    def __init__(self, path, line, module, names=(), kind="import", fallbacks=(), file=None):
        self.path, self.line, self.module, self.names = path, line, module, tuple(names)
        self.kind = kind
        # Shims: [(module, names)] the code imports instead when this import raises ImportError.
        self.fallbacks = tuple(fallbacks)
        self.file = Path(file) if file else None  # the absolute path of the scanned file

    def key(self):
        return (self.path, self.line, self.module, self.names, self.kind)

    def as_dict(self):
        out = {"path": self.path, "line": self.line, "module": self.module, "names": list(self.names),
               "kind": self.kind}
        if self.fallbacks:
            out["fallbacks"] = [{"module": m, "names": list(n)} for m, n in self.fallbacks]
        return out


def _kind_of_file(rel):
    name = rel.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        return "py"
    if name.startswith("Dockerfile") or name.endswith(".dockerfile") or name.endswith(TEXT_SUFFIXES):
        return "text"
    return None


def _pkg_pattern(packages):
    alt = "|".join(re.escape(p) for p in packages)
    return r"(?:%s)(?:\.[A-Za-z_]\w*)*" % alt


class Patterns:
    """The regular expressions for one set of package names."""

    def __init__(self, packages):
        mod = _pkg_pattern(packages)
        self.packages = tuple(packages)
        self.dash_m = re.compile(r"(?<![\w-])-m\s+(%s)\b(?!\.)" % mod)
        self.list_m = re.compile(r"""["']-m["']\s*,\s*["'](%s)["']""" % mod)
        self.from_import = re.compile(r"(?:^|[\s;(\"'])from\s+(%s)\s+import\s+(\(?[\w\s,*]+)" % mod)
        self.plain_import = re.compile(r"(?:^|[\s;\"'])import\s+(%s)\b(?!\.)" % mod)
        self.exact = re.compile(r"^(%s)$" % mod)
        self._name = re.compile(r"(?<![\w.])(?:%s)\b" % "|".join(re.escape(p) for p in packages))
        self._before = re.compile(r"(?:\bimport|\bfrom|-m)\s+$")

    def hint(self, text):
        """True when text may hold a reference: every form puts a package name after a quote, `import`,
        `from` or `-m`, so a file without one is not parsed."""
        if not any(p in text for p in self.packages):
            return False
        for m in self._name.finditer(text):
            i = m.start()
            if i and text[i - 1] in "\"'" or self._before.search(text, max(0, i - 12), i):
                return True
        return False

    def in_text(self, text):
        """[(module, names, kind)] found in one line or string."""
        found = []
        for m in self.dash_m.finditer(text):
            found.append((m.group(1), (), "-m"))
        for m in self.list_m.finditer(text):
            found.append((m.group(1), (), "-m"))
        for m in self.from_import.finditer(text):
            found.append((m.group(1), _split_names(m.group(2)), "string-import"))
        for m in self.plain_import.finditer(text):
            found.append((m.group(1), (), "string-import"))
        return found


def _split_names(text):
    names = []
    for part in text.replace("(", " ").replace(")", " ").split(","):
        words = part.split()
        if not words:
            continue
        first = re.match(r"\*|[A-Za-z_]\w*", words[0])
        if first:
            names.append(first.group(0))
        if (first and first.end() < len(words[0])) or (len(words) > 1 and words[1] != "as"):
            break  # the statement ended; what follows is other code
    return tuple(names)


IMPORT_CALLS = {"import_module", "run_module", "find_spec", "__import__"}


def _belongs(module, packages):
    return module.split(".", 1)[0] in packages


def refs_in_python(text, rel, pats):
    """References in one Python source; falls back to line reading when ast cannot parse it."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return refs_in_text(text, rel, pats)
    out, docs, shims = [], set(), shim_fallbacks(tree, pats)
    for node in ast.walk(tree):  # breadth first: a docstring's owner comes before the docstring
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _belongs(alias.name, pats.packages):
                    out.append(Ref(rel, node.lineno, alias.name, (), "import", shims.get(id(node), ())))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and _belongs(node.module, pats.packages):
                out.append(Ref(rel, node.lineno, node.module, tuple(a.name for a in node.names), "from",
                               shims.get(id(node), ())))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in IMPORT_CALLS and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) and pats.exact.match(node.args[0].value):
                out.append(Ref(rel, node.lineno, node.args[0].value, (), name))
        elif isinstance(node, (ast.List, ast.Tuple)):
            elts = node.elts
            for a, b in zip(elts, elts[1:]):
                if isinstance(a, ast.Constant) and a.value == "-m" and isinstance(b, ast.Constant) \
                        and isinstance(b.value, str) and pats.exact.match(b.value):
                    out.append(Ref(rel, b.lineno, b.value, (), "-m"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            if not pats.hint(node.value):
                continue
            for module, names, kind in pats.in_text(node.value):
                out.append(Ref(rel, node.lineno, module, names, kind))
    return out


IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _catches_import_error(handler):
    kinds = handler.type
    if kinds is None:
        return True
    names = kinds.elts if isinstance(kinds, ast.Tuple) else [kinds]
    return any(getattr(n, "id", getattr(n, "attr", None)) in IMPORT_ERRORS for n in names)


def shim_fallbacks(tree, pats):
    """{id(import node): [(module, names)]} for villa imports in a try body whose ImportError handler imports
    from a module that is not villa's instead:

        try:
            from vesuvius.tifxyz import read_tifxyz
        except ImportError:
            from mytools.compat import read_tifxyz
    """
    out = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Try) or type(node).__name__ == "TryStar"):
            continue
        fallbacks = []
        for handler in node.handlers:
            if not _catches_import_error(handler):
                continue
            for sub in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
                if isinstance(sub, ast.ImportFrom) and sub.level == 0 and sub.module \
                        and not _belongs(sub.module, pats.packages):
                    fallbacks.append((sub.module, tuple(a.name for a in sub.names)))
        if not fallbacks:
            continue
        for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(sub, (ast.Import, ast.ImportFrom)):
                out[id(sub)] = fallbacks
    return out


def refs_in_text(text, rel, pats):
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if not any(p in line for p in pats.packages) or line.lstrip().startswith("#"):
            continue
        for module, names, kind in pats.in_text(line):
            out.append(Ref(rel, number, module, names, kind))
    return out


def _env():
    env = {k: v for k, v in os.environ.items() if k not in LOCAL_GIT_VARIABLES}
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "LC_ALL": "C"})
    return env


def _git_files(root):
    """Tracked and untracked, not ignored, files under root when it is in a git work tree, else None."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "-co", "--exclude-standard"],
                              capture_output=True, env=_env(), check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk_files(root, prune):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git" and not prune(d)]
        for name in filenames:
            yield os.path.relpath(os.path.join(dirpath, name), root)


def excluded(rel, globs):
    """True when the path (from the root, with /) or any of its folders matches one of globs. A glob matches a
    folder by its path from the root or by its name alone."""
    parts = rel.split("/")
    for glob in globs:
        if fnmatch.fnmatchcase(rel, glob):
            return True
        for i in range(1, len(parts)):
            if fnmatch.fnmatchcase(parts[i - 1], glob) or fnmatch.fnmatchcase("/".join(parts[:i]), glob):
                return True
    return False


def vendored_copy(root, rel, packages):
    """True when a folder on the path is named like a scanned package and holds an __init__.py: a vendored copy of
    villa's code, not the user's."""
    parts = rel.split("/")[:-1]
    for i, part in enumerate(parts):
        if part in packages and (Path(root).joinpath(*parts[:i + 1]) / "__init__.py").is_file():
            return True
    return False


def iter_files(roots, excludes=(), defaults=True, packages=None, skipped=None):
    """(absolute path, path shown, root) for every candidate file under roots, exclusions applied. Paths show
    relative to their root, prefixed with the root as given when there is more than one. skipped, a Counter when
    given, counts the files left out as vendored copies."""
    packages = tuple(packages or DEFAULT_PACKAGES)
    globs = tuple(excludes) + (DEFAULT_EXCLUDES if defaults else ())
    seen = set()
    roots = list(roots)
    for given in roots:
        root = Path(given).resolve()
        if not root.is_dir():
            raise ValueError("no folder %s to scan" % given)
        files = _git_files(root) if defaults else None
        if files is None:
            files = list(_walk_files(root, lambda d: any(fnmatch.fnmatchcase(d, g) for g in globs)))
        for rel in sorted(files):
            rel = rel.replace(os.sep, "/")
            path = root / rel
            if path in seen or _kind_of_file(rel) is None or path.resolve() in SELF:
                continue
            seen.add(path)
            if excluded(rel, globs):
                continue
            if defaults and vendored_copy(root, rel, packages):
                if skipped is not None:
                    skipped["vendored"] += 1
                continue
            shown = rel if len(roots) == 1 else "%s/%s" % (str(given).rstrip("/"), rel)
            yield path, shown, root


def find_refs(roots=None, packages=None, excludes=(), defaults=True, skipped=None):
    """Every reference to the villa packages in the files under roots (default the current folder),
    deduplicated, sorted by path and line."""
    packages = list(packages or DEFAULT_PACKAGES)
    pats = Patterns(packages)
    out, keys, parsed = [], set(), {}
    for path, shown, root in iter_files(roots or [Path.cwd()], excludes, defaults, packages, skipped):
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not pats.hint(text):
            continue
        kind = _kind_of_file(shown)
        digest = (kind, hashlib.sha1(text.encode("utf-8", "replace")).hexdigest())
        if digest not in parsed:  # copies of one file are parsed once
            parsed[digest] = refs_in_python(text, "", pats) if kind == "py" else refs_in_text(text, "", pats)
        for found in parsed[digest]:
            ref = Ref(shown, found.line, found.module, found.names, found.kind, found.fallbacks, path)
            if ref.key() not in keys:
                keys.add(ref.key())
                out.append(ref)
    out.sort(key=lambda r: (r.path, r.line, r.module, r.names))
    return out


# Villa's tree ------------------------------------------------------------------------------------------------

def _git(repo, args, data=None, check=True, timeout=600):
    command = ["git", *GIT_CONFIG, "-C", str(repo), *args]
    try:
        proc = subprocess.run(command, input=data, capture_output=True, env=_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise VillaError("git %s timed out after %d s" % (args[0], timeout)) from None
    except OSError as error:
        raise VillaError("cannot run git: %s" % error) from None
    if check and proc.returncode != 0:
        raise VillaError("git %s failed: %s" % (" ".join(args[:2]), _first_line(proc.stderr)))
    return proc


def _first_line(err):
    text = err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err)
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith(("warning:", "hint:"))]
    return lines[-1] if lines else "no message"


def ensure_clone(cache, url=VILLA_URL, offline=False):
    """The cached blobless bare clone of villa, made or updated with anonymous git. Returns (path, note)."""
    cache = Path(cache)
    if not (cache / "HEAD").exists():
        if offline:
            raise Unreachable("no cached villa clone at %s and --offline was given; run once online or pass "
                              "--villa-git PATH" % cache)
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(["git", *GIT_CONFIG, "clone", "-q", "--filter=blob:none", "--bare", url,
                                   str(cache)], capture_output=True, env=_env(), timeout=900)
        except OSError as error:
            raise VillaError("cannot run git: %s" % error) from None
        if proc.returncode != 0:
            raise Unreachable("cannot clone villa from %s (offline?): %s; pass --villa-git PATH to read an "
                              "existing clone" % (url, _first_line(proc.stderr)))
        return cache, "cloned " + url
    if offline:
        return cache, "cached clone, not fetched (--offline)"
    proc = _git(cache, ["fetch", "-q", "--prune", "--filter=blob:none", "origin", "+refs/heads/*:refs/heads/*"],
                check=False, timeout=600)
    if proc.returncode != 0:
        return cache, "fetch failed (%s); using the cached clone as it is" % _first_line(proc.stderr)
    return cache, "fetched " + url


class Villa:
    """Read-only access to one villa clone: commits, trees and blobs (fetched in batches when missing)."""

    def __init__(self, path, packages=None):
        self.path = Path(path)
        if _git(self.path, ["rev-parse", "--git-dir"], check=False).returncode != 0:
            raise VillaError("%s is not a git repository" % self.path)
        self.packages = OrderedDict(packages or DEFAULT_PACKAGES)
        self._present = None
        self._blobs = {}
        self._trees = {}

    def resolve(self, ref):
        """Full sha of a commit name (a branch, tag, short or full sha); VillaError when villa has no such commit."""
        for name in (ref, "origin/" + ref, "refs/remotes/origin/" + ref, "refs/heads/" + ref):
            proc = _git(self.path, ["rev-parse", "--verify", "--quiet", name + "^{commit}"], check=False)
            if proc.returncode == 0:
                return proc.stdout.decode().strip()
        raise VillaError("villa has no commit %r in %s" % (ref, self.path))

    def describe(self, sha):
        proc = _git(self.path, ["show", "-s", "--format=%h %cs %s", sha], check=False)
        return proc.stdout.decode("utf-8", "replace").strip()

    def _scan_objects(self):
        proc = _git(self.path, ["cat-file", "--batch-all-objects", "--batch-check=%(objectname)"])
        self._present = set(proc.stdout.decode().split())

    def _promisor(self):
        proc = _git(self.path, ["config", "--get-regexp", r"^remote\..*\.promisor$"], check=False)
        for line in proc.stdout.decode().splitlines():
            key, _, value = line.partition(" ")
            if value.strip() == "true":
                return key[len("remote."):-len(".promisor")]
        return None

    def prefetch(self, oids):
        """Fetch, in one batch, the blobs among oids that a partial clone does not hold yet."""
        if self._present is None:
            self._scan_objects()
        missing = sorted({o for o in oids if o not in self._present})
        if not missing:
            return 0
        remote = self._promisor()
        if remote is None:
            raise VillaError("%d blobs missing from %s and it has no promisor remote" % (len(missing), self.path))
        for i in range(0, len(missing), 2000):
            chunk = missing[i:i + 2000]
            proc = _git(self.path, ["-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "--no-tags",
                                    "--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none",
                                    "--stdin", remote], data=("\n".join(chunk) + "\n").encode(), check=False)
            if proc.returncode != 0:
                raise VillaError("cannot fetch %d villa blobs (offline?): %s" % (len(chunk),
                                                                                 _first_line(proc.stderr)))
            self._present.update(chunk)
        return len(missing)

    def blobs(self, oids):
        """{oid: text} for blob oids, fetching missing ones first."""
        need = [o for o in dict.fromkeys(oids) if o not in self._blobs]
        if need:
            self.prefetch(need)
            proc = _git(self.path, ["cat-file", "--batch"], data=("\n".join(need) + "\n").encode())
            data, pos = proc.stdout, 0
            while pos < len(data):
                end = data.index(b"\n", pos)
                header = data[pos:end].decode().split()
                pos = end + 1
                if len(header) < 3 or header[1] == "missing":
                    continue
                size = int(header[2])
                self._blobs[header[0]] = data[pos:pos + size].decode("utf-8", "replace")
                pos += size + 1
        return {o: self._blobs.get(o) for o in oids}

    def tree(self, commit, prefix):
        """{path: oid} of every file under prefix (a folder) at commit; trees only, no blobs needed."""
        key = (commit, prefix)
        if key not in self._trees:
            proc = _git(self.path, ["ls-tree", "-r", "-z", "--full-tree", commit, "--", prefix.rstrip("/") + "/"])
            files = {}
            for entry in proc.stdout.decode("utf-8", "replace").split("\0"):
                if not entry:
                    continue
                meta, _, path = entry.partition("\t")
                parts = meta.split()
                if len(parts) == 3 and parts[1] == "blob":
                    files[path] = parts[2]
            self._trees[key] = files
        return self._trees[key]

    def package_root(self, commit, package):
        """Where a package lives in villa's tree at commit: the first candidate folder holding __init__.py, else
        the shallowest `<x>/src/<package>` or `<package>` folder with one, else None."""
        for cand in self.packages.get(package, []):
            if cand + "/__init__.py" in self.tree(commit, cand):
                return cand
        proc = _git(self.path, ["ls-tree", "-r", "--name-only", "--full-tree", commit])
        hits = [p[:-len("/__init__.py")] for p in proc.stdout.decode("utf-8", "replace").splitlines()
                if p.endswith("/" + package + "/__init__.py") or p == package + "/__init__.py"]
        hits = [h for h in hits if h == package or h.endswith("/src/" + package) or h.count("/") == 1]
        hits = [h for h in hits if not h.startswith(("deprecated/", "archive/"))]
        return sorted(hits, key=lambda h: (h.count("/"), h))[0] if hits else None

    def snapshot(self, ref):
        return Snapshot(self, self.resolve(ref))


class Shims:
    """Modules of yours that ImportError fallbacks name, and local copies of a villa package, found in the scanned
    folders (never in villa)."""

    def __init__(self, roots=()):
        self.roots = [Path(r).resolve() for r in roots]
        self._cache = {}

    def _shown(self, path):
        for root in self.roots:
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            return rel if len(self.roots) == 1 else "%s/%s" % (root, rel)
        return str(path)

    def find(self, module, near=None):
        """(shown path, names, open) of module, looked up next to the importing file (near), then under each
        scanned root; None when it is in none of them."""
        rel = module.replace(".", "/")
        bases = ([Path(near).parent] if near else []) + self.roots
        for base in bases:
            for cand in (base / (rel + ".py"), base / rel / "__init__.py"):
                key = str(cand)
                if key not in self._cache:
                    self._cache[key] = None
                    if cand.is_file():
                        try:
                            text = cand.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            continue
                        names, open_ = top_level_names(text)
                        if cand.name == "__init__.py":  # a package: its submodules are names too
                            names = names | {p.stem for p in cand.parent.glob("*.py")} | \
                                {p.name for p in cand.parent.iterdir() if p.is_dir()}
                        self._cache[key] = (self._shown(cand), names, open_)
                if self._cache[key]:
                    return self._cache[key]
        return None

    def local_copy(self, ref):
        """(status, detail) when the importing file's own folder holds the package (a copy that wins on
        sys.path), else None."""
        if ref.file is None:
            return None
        top = ref.module.split(".")[0]
        folder = ref.file.parent
        if not ((folder / top).is_dir() or (folder / (top + ".py")).is_file()):
            return None
        rel = ref.module.replace(".", "/")
        found = None
        for cand in (folder / (rel + ".py"), folder / rel / "__init__.py"):
            if cand.is_file():
                found = self.find(ref.module, ref.file)
                break
        copy = self._shown(folder / top)
        if not found:
            return MISSING_MODULE, "no module %s in the local copy %s" % (ref.module, copy)
        shown, names, open_ = found
        lost = [n for n in ref.names if n != "*" and n not in names and not open_]
        if lost:
            return MISSING_NAME, "no name %s in the local copy %s" % (", ".join(lost), shown)
        return OK, "local copy " + shown

    def check(self, ref, status, detail):
        needed = set(n for n in ref.names if n != "*")
        covered, paths, notes = set(), [], []
        for module, names in ref.fallbacks:
            found = self.find(module, ref.file)
            if not found:
                notes.append("shim %s is not in the scanned folder" % module)
                continue
            shown, defined, open_ = found
            have = {n for n in names if n in defined or open_}
            if needed - have and set(names) - have:
                notes.append("shim %s defines no %s" % (module, ", ".join(sorted(set(names) - have))))
            covered |= have
            paths.append(shown)
        if paths and needed <= covered:
            return SHIM, "via shim " + ", ".join(dict.fromkeys(paths))
        return status, detail + ("; " + "; ".join(notes) if notes else "")


class Snapshot:
    """Villa's packages at one commit: modules, their top-level names, and reference resolution."""

    def __init__(self, villa, commit):
        self.villa, self.commit = villa, commit
        self.roots, self.files = {}, {}
        for package in villa.packages:
            root = villa.package_root(commit, package)
            self.roots[package] = root
            if root:
                for path, oid in villa.tree(commit, root).items():
                    self.files[package + path[len(root):]] = oid
        self._names = {}

    def module_kind(self, module):
        """'module', 'package', 'namespace' or None."""
        rel = module.replace(".", "/")
        if rel + ".py" in self.files:
            return "module"
        if rel + "/__init__.py" in self.files:
            return "package"
        if any(f.startswith(rel + "/") for f in self.files) and self.roots.get(module.split(".")[0]):
            return "namespace"
        return None

    def module_file(self, module, suffix=".py"):
        rel = module.replace(".", "/")
        for path in (rel + suffix, rel + "/__init__" + suffix):
            if path in self.files:
                return path
        return None

    def first_missing(self, module):
        """The shortest prefix of module that is not a module at this commit, or None when all are."""
        parts = module.split(".")
        for i in range(1, len(parts) + 1):
            prefix = ".".join(parts[:i])
            kind = self.module_kind(prefix)
            if kind is None:
                return prefix
            if kind == "module" and i < len(parts):
                return ".".join(parts[:i + 1])
        return None

    def submodules(self, module):
        rel = module.replace(".", "/") + "/"
        subs = set()
        for f in self.files:
            if f.startswith(rel):
                head = f[len(rel):].split("/", 1)
                if len(head) == 2 or head[0].endswith(".py"):
                    name = head[0][:-3] if len(head) == 1 else head[0]
                    if name != "__init__" and name.isidentifier():
                        subs.add(name)
        return subs

    def prefetch_modules(self, modules):
        paths = [self.module_file(m, x) for m in modules for x in (".py", ".pyi")]
        self.villa.blobs([self.files[f] for f in paths if f])

    def names(self, module):
        """(set of top-level names, open) for a module; open is True when names cannot be ruled out."""
        if module not in self._names:
            path = self.module_file(module)
            names, open_ = set(), False
            if path:
                text = self.villa.blobs([self.files[path]])[self.files[path]]
                names, open_ = top_level_names(text)
            elif self.module_kind(module) != "namespace":
                open_ = True
            stub = self.module_file(module, ".pyi")
            if stub:  # a type stub names what a module builds at run time (vc_reader.transforms does)
                names |= top_level_names(self.villa.blobs([self.files[stub]])[self.files[stub]])[0]
            names |= self.submodules(module)
            self._names[module] = (names, open_)
        return self._names[module]

    def resolve(self, ref):
        """(status, detail) of one reference at this commit."""
        package = ref.module.split(".")[0]
        if not self.roots.get(package):
            return MISSING_MODULE, "villa has no %s package at %s" % (package, self.commit[:9])
        gone = self.first_missing(ref.module)
        if gone:
            return MISSING_MODULE, "no module " + gone
        if ref.kind == "-m" and self.module_kind(ref.module) in ("package", "namespace") \
                and "__main__" not in self.submodules(ref.module):
            return MISSING_MODULE, "package %s has no __main__.py for -m" % ref.module
        names = [n for n in ref.names if n != "*"]
        if not names:
            return OK, ""
        defined, open_ = self.names(ref.module)
        lost = [n for n in names if n not in defined]
        if not lost:
            return OK, ""
        if open_:
            return UNKNOWN, "%s not found, but %s has a star import or __getattr__" % (", ".join(lost), ref.module)
        return MISSING_NAME, "no name %s in %s" % (", ".join(lost), ref.module)

    def resolve_all(self, refs, shims=None):
        """resolve() for each reference. With shims (a Shims), a reference whose own folder holds a copy of the
        package resolves against that copy, and a break with an ImportError fallback is checked against the
        scanned folders: (SHIM, "via shim PATH") when the fallback module is there and defines every name."""
        self.prefetch_modules({r.module for r in refs if r.names})
        out = []
        for ref in refs:
            local = shims.local_copy(ref) if shims else None
            if local:  # the importing file's folder comes first on sys.path, so the copy wins
                out.append(local)
                continue
            status, detail = self.resolve(ref)
            if shims and status in BREAKS and ref.fallbacks:
                status, detail = shims.check(ref, status, detail)
            out.append((status, detail))
        return out

    def definitions(self):
        """{name: [modules]} of top-level functions, classes and assignments in every package module."""
        if not hasattr(self, "_defs"):
            mods = {}
            for f in self.files:
                if f.endswith(".py"):
                    mod = f[:-3].replace("/", ".")
                    mods[mod[:-len(".__init__")] if mod.endswith(".__init__") else mod] = self.files[f]
            texts = self.villa.blobs(list(mods.values()))
            defs = defaultdict(list)
            for mod, oid in sorted(mods.items()):
                for name in defined_names(texts.get(oid) or ""):
                    defs[name].append(mod)
            self._defs = defs
        return self._defs


def _top_statements(body):
    for node in body:
        yield node
        if isinstance(node, ast.If):
            yield from _top_statements(node.body)
            yield from _top_statements(node.orelse)
        elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            yield from _top_statements(node.body)
            for handler in node.handlers:
                yield from _top_statements(handler.body)
            yield from _top_statements(node.orelse)
            yield from _top_statements(node.finalbody)
        elif isinstance(node, (ast.With, ast.For, ast.While)):
            yield from _top_statements(node.body)
            yield from _top_statements(getattr(node, "orelse", []))


def _targets(target):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _targets(elt)
    elif isinstance(target, ast.Starred):
        yield from _targets(target.value)


def _is_globals(node):
    return isinstance(node, ast.Call) and getattr(node.func, "id", None) == "globals"


def _binds_globals(stmt):
    """True when a statement calls globals().update or setdefault, or assigns to globals()[...]."""
    for n in ast.walk(stmt):
        if isinstance(n, ast.Attribute) and n.attr in ("update", "setdefault") and _is_globals(n.value):
            return True
        if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and _is_globals(n.value):
            return True
    return False


def top_level_names(text):
    """(names, open) bound at a module's top level; open when it has `import *`, a __getattr__, a top-level
    globals().update or does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set(), True
    names, open_ = set(), False
    for node in _top_statements(tree.body):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and _binds_globals(node):
            open_ = True  # globals().update(...) binds names ast cannot see
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if node.name == "__getattr__":
                open_ = True
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                names.update(_targets(t))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            names.update(_targets(node.target))
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "*":
                    open_ = True
                else:
                    names.add(a.asname or a.name)
    return names, open_


def defined_names(text):
    """Names a module defines itself (functions, classes, assignments), not ones it imports."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                names.update(_targets(t))
    return {n for n in names if not n.startswith("__")}


# The replacement map -------------------------------------------------------------------------------------------

def load_map(path=None):
    """The curated map: {'packages': OrderedDict, 'entries': [...], ...}; ValueError on a bad file."""
    path = Path(path) if path else MAP_FILE
    if not path.exists():
        return {"packages": OrderedDict(DEFAULT_PACKAGES), "entries": []}
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    problems = []
    packages = data.get("packages") or DEFAULT_PACKAGES
    if not isinstance(packages, dict) or not all(isinstance(v, list) for v in packages.values()):
        problems.append("packages must map a package name to a list of villa folders")
    for i, e in enumerate(data.get("entries", [])):
        for field in ("old", "new_module", "use", "villa", "commit"):
            if not isinstance(e.get(field), str) or not e.get(field):
                problems.append("entry %d (%s) has no %s" % (i, e.get("old"), field))
    if problems:
        raise ValueError("bad map %s: %s" % (path, "; ".join(problems)))
    data["packages"] = OrderedDict(packages)
    data.setdefault("entries", [])
    return data


def map_lookup(entries, module, name=None):
    """The map entry for module (and name): an entry for this exact name first, then the module entry with the
    longest matching prefix; None when nothing matches."""
    best, best_len = None, -1
    for e in entries:
        old, ename = e["old"], e.get("name")
        if not (module == old or module.startswith(old + ".")):
            continue
        if ename and ename != name:
            continue
        score = len(old) + (1000 if ename else 0)
        if score > best_len:
            best, best_len = e, score
    return best


def suggestion(snap, entries, ref, detail):
    """A replacement text for a broken reference, or ''."""
    lost = []
    if detail.startswith("no name "):
        lost = [n.strip() for n in detail[len("no name "):].rsplit(" in ", 1)[0].split(",")]
    targets = lost or [n for n in ref.names if n != "*"] or [None]
    out = []
    for name in targets:
        e = map_lookup(entries, ref.module, name)
        if e:
            check = ""
            if snap is not None:
                probe = Ref("", 0, e["new_module"], (e["new_name"],) if e.get("new_name") else ())
                status, _ = snap.resolve(probe)
                if status in BREAKS:
                    check = " [map target not found at %s]" % snap.commit[:9]
            out.append("%s%s (map: villa %s at %s)%s" % ((name + ": ") if name and len(targets) > 1 else "",
                                                        e["use"], e["villa"], e["commit"][:9], check))
        elif name and snap is not None and lost:
            homes = snap.definitions().get(name, [])
            if homes:
                out.append("%s is defined at %s in %s" % (name, snap.commit[:9], ", ".join(homes[:3])))
    return "; ".join(dict.fromkeys(out))


# Commands ------------------------------------------------------------------------------------------------------

def _open_villa(args, data):
    """Villa object for the command's options and the map's packages, and a note on how it was reached."""
    if getattr(args, "villa_git", None):
        path, note = args.villa_git, "existing clone " + str(args.villa_git)
    else:
        cache = getattr(args, "cache", None) or default_cache()
        path, note = ensure_clone(cache, offline=getattr(args, "offline", False))
    return Villa(path, data["packages"]), note


def _roots(args):
    return list(getattr(args, "root", None) or [Path.cwd()])


def _find(args, data, skipped=None):
    return find_refs(_roots(args), list(data["packages"]), getattr(args, "exclude", None) or (),
                     not getattr(args, "no_default_excludes", False), skipped)


def _group_key(ref, status, detail):
    if status == MISSING_MODULE:
        return detail[len("no module "):].split()[0].rstrip(";") if detail.startswith("no module ") else ref.module
    return "%s.%s" % (ref.module, detail.split()[2].rstrip(",")) if detail.startswith("no name ") else ref.module


def scan(refs, snap, entries, shims=None):
    """Rows for every reference at one snapshot: dict(ref fields, status, detail, and for a break suggestion and
    group)."""
    results = snap.resolve_all(refs, shims)
    rows = []
    for ref, (status, detail) in zip(refs, results):
        row = ref.as_dict()
        row.update(status=status, detail=detail)
        if status in BREAKS:
            row["suggestion"] = suggestion(snap, entries, ref, detail)
            row["group"] = _group_key(ref, status, detail)
        rows.append(row)
    return rows


def summarize(rows):
    counts = Counter(r["status"] for r in rows)
    broken = [r for r in rows if r["status"] in BREAKS]
    return {"references": len(rows), "files": len({r["path"] for r in rows}),
            "statuses": {s: counts.get(s, 0) for s in STATUSES},
            "breaking_files": len({r["path"] for r in broken}),
            "groups": OrderedDict(sorted(Counter(r["group"] for r in broken).items(),
                                         key=lambda kv: (-kv[1], kv[0])))}


def _head(snap, label, note):
    roots = ", ".join("%s at %s" % (p, r or "(absent)") for p, r in snap.roots.items())
    return "kit villaports %s: villa %s (%s); %s; %s" % (label, snap.villa.describe(snap.commit)[:80],
                                                         snap.commit[:9], roots, note)


def _cmd_scan(args, data):
    villa, note = _open_villa(args, data)
    snap = villa.snapshot(args.villa)
    skipped = Counter()
    refs = _find(args, data, skipped)
    rows = scan(refs, snap, data["entries"], Shims(_roots(args)))
    summary = summarize(rows)
    summary["skipped_vendored_files"] = skipped["vendored"]
    code = EXIT_ATTENTION if summary["breaking_files"] else EXIT_OK
    roots = [str(Path(r).resolve()) for r in _roots(args)]
    if args.json:
        print(json.dumps({"villa": snap.commit, "ref": args.villa, "roots": snap.roots, "scanned": roots,
                          "note": note, "summary": summary, "references": rows, "exit": code}, indent=1))
        return code
    print(_head(snap, "scan", note))
    s = summary["statuses"]
    print("scanned %s: %d references in %d files: %d ok, %d ok via shim, %d missing module, %d missing name, "
          "%d unknown; %d files break" % (", ".join(roots), summary["references"], summary["files"], s[OK], s[SHIM],
                                         s[MISSING_MODULE], s[MISSING_NAME], s[UNKNOWN], summary["breaking_files"]))
    if skipped["vendored"]:
        print("skipped %d files in vendored copies of villa packages (--no-default-excludes scans them)"
              % skipped["vendored"])
    shimmed = Counter(r["detail"] for r in rows if r["status"] == SHIM)
    for detail, n in sorted(shimmed.items()):
        print("ok via shim: %d references %s (--all lists them)" % (n, detail))
    shown = [r for r in rows if args.all or r["status"] in BREAKS or r["status"] == UNKNOWN]
    if shown:
        print()
    for r in shown:
        names = (" (%s)" % ", ".join(r["names"])) if r["names"] else ""
        print("%-14s %s:%d  %s%s%s" % (r["status"], r["path"], r["line"], r["module"], names,
                                       ("  " + r["detail"]) if r["detail"] else ""))
        if r.get("suggestion"):
            print("%-14s -> %s" % ("", r["suggestion"]))
    if summary["groups"]:
        print("\nbreaks by removed module or name:")
        for group, n in summary["groups"].items():
            files = sorted({r["path"] for r in rows if r.get("group") == group})
            print("  %4d  %s  (%d files)" % (n, group, len(files)))
    return code


def _cmd_diff(args, data):
    villa, note = _open_villa(args, data)
    old, new = villa.snapshot(args.from_ref), villa.snapshot(args.to_ref)
    refs = _find(args, data)
    shims = Shims(_roots(args))
    before, after = old.resolve_all(refs, shims), new.resolve_all(refs, shims)
    renames = module_renames(villa, old, new)
    changes = OrderedDict()
    for ref, (s0, d0), (s1, d1) in zip(refs, before, after):
        if s0 in BREAKS + (SHIM,) or s1 not in BREAKS + (SHIM,):  # SHIM at OLD: villa lacked it already
            continue
        raw1, rawd1 = (s1, d1) if s1 != SHIM else new.resolve(ref)
        key = _group_key(ref, raw1, rawd1)
        item = changes.setdefault(key, {"what": "module" if raw1 == MISSING_MODULE else "name", "removed": key,
                                        "renamed_to": None, "suggestion": "", "references": []})
        item["references"].append({"path": ref.path, "line": ref.line, "module": ref.module,
                                   "names": list(ref.names), "shim": d1[len("via shim "):] if s1 == SHIM else None})
        if item["what"] == "module" and key in renames:
            item["renamed_to"] = renames[key]
        if not item["suggestion"]:
            item["suggestion"] = suggestion(new, data["entries"], ref, rawd1)
    unshimmed = sum(1 for c in changes.values() for r in c["references"] if not r["shim"])
    code = EXIT_ATTENTION if unshimmed else EXIT_OK
    if args.json:
        print(json.dumps({"from": old.commit, "to": new.commit, "note": note, "changes": list(changes.values()),
                          "unshimmed": unshimmed, "exit": code}, indent=1))
        return code
    print("kit villaports diff: villa %s -> %s; %s" % (villa.describe(old.commit)[:60], villa.describe(new.commit)[:60],
                                                        note))
    nmod = sum(1 for c in changes.values() if c["what"] == "module")
    total = sum(len(c["references"]) for c in changes.values())
    print("%d modules and %d names your code uses (%d references) were removed or moved; %d references still "
          "break, %d resolve through a shim" % (nmod, len(changes) - nmod, total, unshimmed, total - unshimmed))
    for c in changes.values():
        files = sorted({r["path"] for r in c["references"]})
        moved = (" -> renamed to %s (git rename)" % c["renamed_to"]) if c["renamed_to"] else ""
        print("\n%-6s %s: %d references in %d files%s" % (c["what"], c["removed"], len(c["references"]), len(files),
                                                          moved))
        if c["suggestion"]:
            print("       -> " + c["suggestion"])
        for r in c["references"]:
            print("       %s:%d%s" % (r["path"], r["line"], ("  ok via shim " + r["shim"]) if r["shim"] else ""))
    return code


def module_renames(villa, old, new):
    """{old module: new module} for package files git sees as renamed between two snapshots."""
    out = {}
    for package, root0 in old.roots.items():
        root1 = new.roots.get(package)
        if not root0 or not root1:
            continue
        proc = _git(villa.path, ["diff", "--name-status", "-z", "-M", "--diff-filter=R", old.commit, new.commit,
                                 "--", root0 + "/", root1 + "/"], check=False)
        fields = proc.stdout.decode("utf-8", "replace").split("\0")
        i = 0
        while i + 2 < len(fields):
            if fields[i].startswith("R"):
                a, b = fields[i + 1], fields[i + 2]
                if a.startswith(root0 + "/") and b.startswith(root1 + "/") and a.endswith(".py") \
                        and b.endswith(".py"):
                    out[_path_module(package, a[len(root0):])] = _path_module(package, b[len(root1):])
                i += 3
            else:
                i += 1
    return out


def _path_module(package, rel):
    mod = (package + rel[:-3]).replace("/", ".")
    return mod[:-len(".__init__")] if mod.endswith(".__init__") else mod


def add_arguments(p):
    sub = p.add_subparsers(dest="action", required=True)

    def common(q):
        q.add_argument("--root", action="append", type=Path, help="folder to scan (repeatable; default the "
                                                                  "current folder)")
        q.add_argument("--exclude", action="append", metavar="GLOB", help="leave out files whose path from the "
                                                                          "root, or any of whose folders, matches "
                                                                          "GLOB (repeatable)")
        q.add_argument("--no-default-excludes", action="store_true", help="also scan git-ignored files, "
                                                                          "environment, cache and build folders "
                                                                          "and vendored copies of villa packages")
        q.add_argument("--villa-git", type=Path, help="read this existing villa clone instead of the cache")
        q.add_argument("--cache", type=Path, help="where to keep the villa clone (default "
                                                  "~/.cache/scrolls-villaports/villa.git)")
        q.add_argument("--offline", action="store_true", help="use the cached clone without fetching")
        q.add_argument("--map", type=Path, help="replacement map (default kit/data/villaports-map.json)")
        q.add_argument("--json", action="store_true", help="print JSON instead of text")

    q = sub.add_parser("scan", help="every reference to villa's Python packages in a folder, resolved at a commit")
    q.add_argument("--villa", default="main", help="villa commit, branch or tag to resolve against (default main)")
    q.add_argument("--all", action="store_true", help="also list references that resolve")
    common(q)
    q.set_defaults(handler=_cmd_scan)

    q = sub.add_parser("diff", help="villa modules and names your code uses that NEW removed or renamed relative "
                                    "to OLD")
    q.add_argument("--from", dest="from_ref", required=True, help="the older villa commit")
    q.add_argument("--to", dest="to_ref", default="main", help="the newer villa commit (default main)")
    common(q)
    q.set_defaults(handler=_cmd_diff)


def run(args):
    try:
        data = load_map(args.map)
        return args.handler(args, data)
    except Unreachable as error:
        print("kit villaports: villa unreachable: %s" % error, file=sys.stderr)
        return EXIT_UNREACHABLE
    except (VillaError, ValueError, OSError) as error:
        print("kit villaports failed: %s" % error, file=sys.stderr)
        return EXIT_FAIL


def main(argv=None):
    if argv is None and sys.stdout.isatty():  # the Scrolls look (AGENTS.md rule 17)
        from kit import termstyle
        termstyle.script()
    parser = argparse.ArgumentParser(prog="python -m kit.villaports", description=__doc__.split("\n\n")[0])
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
