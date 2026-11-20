"""Executed-files guard helpers for runners whose Python children start inside their own helpers, and the static
import closure a freeze lists. Library only, no command line.

kit/freeze.py keeps the registry and the guard every runner uses (executed_files, executed_check, run_script,
launch_check). This module adds, on top of executed_check, what a runner needs when its children are started by
other code (kept out of kit/freeze.py, which live freezes pin, so adding these does not change a pinned file):

- recording_argv(argv, record): the argv that runs a `python [FLAGS] -m MODULE ARGS` or `python [FLAGS] SCRIPT.py
  ARGS` child through CHILD_RUNNER, so the child writes the files of every module it loaded to `record`;
- recording_check(files, root, records): executed_check on what those children recorded;
- guard_record(files, root, when, records=None) and guard_void(marker_doc, records=()): a runner's check that
  records a refusal instead of raising it, and the void reasons read back from those records;
- import_closure(root, entries, top_only=(), search=("",), discover=(), always=()): the repository files a set of
  entry files can import, read from their source (inside functions too), so a freeze can list a module a function
  loads late.

None of them sees a file a process opens or executes without importing it (a data file, a shell script, a binary).
A runner that imports this module inside its container lists kit/__init__.py, kit/freezeguard.py, kit/freeze.py and
kit/preregsets.py among its files: this module imports nothing from the repository beyond kit/freeze.py (and through
it kit/preregsets.py). Standard library only.
"""

import json
import os
from pathlib import Path

from .freeze import FreezeError, FreezeRefused, _listed, executed_check

__all__ = ["CHILD_RUNNER", "PYTHON_FLAGS", "recording_argv", "recording_check", "guard_record", "guard_void",
           "import_closure"]


# python [-I] -c CHILD_RUNNER RECORD m MODULE ARGS... runs `python [-I] -m MODULE ARGS...`, and
# python [-I] -c CHILD_RUNNER RECORD s SCRIPT ARGS... runs `python [-I] SCRIPT ARGS...`, each as __main__ with
# sys.path as that command would have it (no script folder first under -I or -P, whose safe_path leaves sys.path
# alone), then writes the files of every module the child loaded to RECORD, also when it exits with an error or a
# code. A child ended by SIGKILL writes nothing (recording_check counts it as missing).
CHILD_RUNNER = """import json, os, runpy, sys
record, how, target = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [target] + sys.argv[4:]
try:
    if how == "m":
        if not sys.flags.safe_path:
            sys.path[0] = os.getcwd()
        runpy.run_module(target, run_name="__main__", alter_sys=True)
    else:
        if not sys.flags.safe_path:
            sys.path[0] = os.path.dirname(os.path.abspath(target))
        runpy.run_path(target, run_name="__main__")
finally:
    files = [m.__file__ for m in list(sys.modules.values()) if getattr(m, "__file__", None)]
    if how != "m":
        files.append(target)
    else:   # run_module puts the old __main__ back when it returns: name the file it ran
        import importlib.util
        try:
            spec = importlib.util.find_spec(target)
            if spec is not None and spec.submodule_search_locations is not None:
                spec = importlib.util.find_spec(target + ".__main__")
            if spec is not None and spec.origin and os.path.isfile(spec.origin):
                files.append(spec.origin)
        except (ImportError, ValueError):
            pass
    files = {g(f) for f in files for g in (os.path.abspath, os.path.realpath)}
    with open(record, "w") as fh:
        json.dump(sorted(files), fh)
"""
PYTHON_FLAGS = ("-I", "-E", "-s", "-S", "-P", "-u", "-B", "-O", "-OO")


def recording_argv(argv, record):
    """The argv that runs this Python child through CHILD_RUNNER, so it also writes the files of every module it
    loaded to `record`: `python [FLAGS] -m MODULE ARGS` and `python [FLAGS] SCRIPT.py ARGS` (FLAGS from
    PYTHON_FLAGS, kept). None for anything else (a binary, a shell, `python -c`), which the caller runs as it is and
    whose loaded files nobody records. Use it for every Python child a frozen run starts, then recording_check on
    the records."""
    argv = [str(a) for a in argv]
    if not argv or not os.path.basename(argv[0]).startswith("python"):
        return None
    i = 1
    while i < len(argv) and argv[i] in PYTHON_FLAGS:
        i += 1
    flags = argv[1:i]
    if i + 1 < len(argv) and argv[i] == "-m":
        return [argv[0], *flags, "-c", CHILD_RUNNER, str(record), "m", argv[i + 1], *argv[i + 2:]]
    if i < len(argv) and argv[i].endswith(".py") and not argv[i].startswith("-"):
        return [argv[0], *flags, "-c", CHILD_RUNNER, str(record), "s", argv[i], *argv[i + 1:]]
    return None


def recording_check(files, root, records, when="children"):
    """executed_check on what Python children recorded (CHILD_RUNNER records, a list of file paths each): refuse
    (FreezeRefused) when any of them loaded a repository file under root that files does not list. records are the
    record paths the children were given; one that is missing or does not parse (a child killed before it could
    write) is counted, not guessed. Returns {"records", "written", "missing", "files"}."""
    loaded, written, missing = set(), 0, []
    for rec in records:
        try:
            with open(rec, encoding="utf-8") as fh:
                got = json.load(fh)
        except (OSError, ValueError):
            missing.append(str(rec))
            continue
        if not isinstance(got, list):
            missing.append(str(rec))
            continue
        written += 1
        loaded.update(str(p) for p in got)
    n = executed_check(files, root, when=when, loaded=sorted(loaded)) if loaded else 0
    return {"records": len(list(records)), "written": written, "missing": missing, "files": n}


def guard_record(files, root, when, records=None):
    """A runner's executed-files check that never raises for a refusal: {"when", "listed", "own", "children",
    "refused"}. own is executed_check of this process; with records (CHILD_RUNNER record paths), children is
    recording_check of them; refused holds the FreezeRefused message when a repository file outside files was
    loaded, so the caller can record it where a resume will see it before it stops the run."""
    rec = {"when": when, "listed": len(_listed(files))}
    try:
        rec["own"] = executed_check(files, root, when=when)
        if records is not None:
            rec["children"] = recording_check(files, root, records, when=f"{when}, a child process")
    except FreezeRefused as exc:
        rec["refused"] = str(exc)[:1200]
    return rec


def guard_void(marker_doc, records=()):
    """Reasons a run's executed-files guard voids it: each refusal in marker_doc["refused"] (the refusals its
    functions recorded, kept where a resume reads them) and in the given guard_record results."""
    why = []
    for r in list((marker_doc or {}).get("refused") or []) + [r for r in records if isinstance(r, dict)]:
        if isinstance(r, dict) and r.get("refused"):
            why.append(f"the executed-files guard refused {r.get('when')}: {r['refused']}"[:600])
    return why


def import_closure(root, entries, top_only=(), search=("",), discover=(), always=()):
    """The repository files a set of entry files can import, read from their source without running it: every
    import statement at any depth (inside functions too), __import__("NAME") and importlib.import_module("NAME")
    with a literal name, resolved against root/<each of search> as `python` would find a module or package
    (packages' __init__.py included), followed transitively. Files named in top_only have only the imports that run
    when they are imported followed: module level, inside if, try, with and class bodies, but not inside a function
    or lambda (a command-line dispatcher such as kit/cli.py, which names every subcommand's module but loads one).
    always holds (FILE, FUNCTION) pairs for functions of a top_only file that every use of it runs (kit/cli.py's
    build_parser builds the whole parser on each `python -m kit` and imports a few subcommands' modules to do it): the
    imports in their own bodies are followed too, but not those inside a lambda or a nested function there, which run
    only when called; a name in always that is not a module-level function of its file is an error (FreezeError).
    discover holds (FILE, GLOB) pairs for modules a file finds by listing its folder (a plugin loader that imports every
    plugins/ext_*.py): once FILE is in the closure, every file GLOB matches under root is too. The static
    complement of executed_files: a freeze that lists this closure covers a module a function loads late, on a path
    no test ran. Returns a sorted list of repository paths, entries included."""
    import ast
    root = Path(root)

    def own(node):
        """node's subtree without the bodies that run only when called (functions and lambdas; a class body runs
        where it is defined, its methods do not)."""
        stop = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
        todo = list(ast.iter_child_nodes(node))
        while todo:
            n = todo.pop()
            yield n
            if not isinstance(n, stop):
                todo.extend(ast.iter_child_nodes(n))

    def top_nodes(tree, rel):
        nodes = list(own(tree))
        wanted = {f for owner, f in always if owner == rel}
        for fn in tree.body:
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in wanted:
                nodes.extend(own(fn))
                wanted.discard(fn.name)
        if wanted:
            raise FreezeError(f"import_closure: {rel} has no module-level function {', '.join(sorted(wanted))} "
                              "named in always")
        return nodes

    def resolve(name):
        parts = [p for p in str(name).split(".") if p]
        if not parts:
            return None
        for base in search:
            p = root.joinpath(base, *parts) if base else root.joinpath(*parts)
            if p.with_suffix(".py").is_file():
                return p.with_suffix(".py").relative_to(root).as_posix()
            if (p / "__init__.py").is_file():
                return (p / "__init__.py").relative_to(root).as_posix()
        return None

    def names(rel):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
        pkg = rel.split("/")[:-1]          # a module's package; an __init__.py's is its own folder
        out = set()
        nodes = top_nodes(tree, rel) if rel in top_only else ast.walk(tree)
        for n in nodes:
            if isinstance(n, ast.Import):
                out.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    base = pkg[:len(pkg) - (n.level - 1)] if n.level > 1 else pkg
                    mod = ".".join(base + ([n.module] if n.module else []))
                else:
                    mod = n.module or ""
                out.add(mod)
                out.update(f"{mod}.{a.name}" for a in n.names if a.name != "*")
            elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and \
                    isinstance(n.args[0].value, str) and \
                    (getattr(n.func, "id", None) == "__import__" or getattr(n.func, "attr", None) == "import_module"):
                out.add(n.args[0].value)
        found = set()
        for m in out:
            parts = m.split(".")
            for k in range(1, len(parts) + 1):
                r = resolve(".".join(parts[:k]))
                if r:
                    found.add(r)
        for owner, pattern in discover:
            if rel == owner:
                found.update(q.relative_to(root).as_posix() for q in sorted(root.glob(pattern)) if q.is_file())
        return found

    seen = {Path(e).as_posix() for e in entries}
    todo = sorted(seen)
    while todo:
        rel = todo.pop()
        for g in names(rel):
            if g not in seen:
                seen.add(g)
                todo.append(g)
    return sorted(seen)
