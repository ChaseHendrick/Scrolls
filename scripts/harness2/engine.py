"""Harness2 engine for the optional Scrolls adapter. run.py starts it; do not run it directly.

`python -I -S -B engine.py UPSTREAM OUT` loads the pinned Harness2 package from UPSTREAM by
file location (the checkout never enters sys.path), generates fixed synthetic provenance
fixtures under OUT, and calls Harness2's real `core.schedule.run_domain` with this file's
`BenchmarkAdapter` and deterministic local proposer. After selection it judges the adopted
runs against the fixture contract and writes OUT/comparison.json.

The executor is a fixed allowlist: it reads one strict recipe and runs worker.py, which calls
the real `python -m kit provenance check`. An audit hook refuses network use, other process
launches and writes outside OUT. That hook guards this adapter's own code path; it is not a
security sandbox. No model service, benchmark download or scroll data is used.
"""

import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORKER = HERE / "worker.py"
FIXTURE_VERSION = 1
DOMAIN = "provenance"
MODES = ("agg", "seq")
# Neutral task ids: the expected verdicts live only in OUT/judge/expected.json.
CONTROLS = {"record-a": "clean", "record-b": "changed", "record-c": "missing"}
EXPECTED = {"clean": "accept", "changed": "reject", "missing": "reject"}
BASE_RECIPE = {"schema": 1, "recheck_files": False}
RUN_ID = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
LAUNCH = ("os.system", "os.exec", "os.spawn", "os.fork", "os.forkpty", "pty.spawn")
CHANGES = {"os.mkdir": (0,), "os.remove": (0,), "os.rmdir": (0,), "os.rename": (0, 1),
           "os.truncate": (0,), "os.symlink": (0, 1), "os.link": (0, 1), "os.chmod": (0,),
           "os.utime": (0,), "shutil.rmtree": (0,)}
TASK_PROMPT = """A run's provenance record is in source/record.json; it lists the run's input and
output files with their SHA-256 hashes. Decide whether the run's files still match the record.
Answer accept only when the listed files themselves were verified against the record;
otherwise answer reject. Put the answer on one line: `verdict: accept` or `verdict: reject`.
"""
CLAIM = ("Fixture plumbing check only: a deterministic local proposer on three generated "
         "provenance fixtures. Not evidence of learned agent improvement, agent superiority "
         "or ink accuracy.")


class EngineError(RuntimeError):
    """A refusal or broken invariant; run.py reports it from engine.log."""


def load_file(name, path, package_dir=None):
    """Import one module or package by file location, without changing sys.path."""
    kwargs = {"submodule_search_locations": [str(package_dir)]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kwargs)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def install_guard(out):
    """Refuse network use, launches other than the fixed worker, and writes outside OUT."""
    out_s = str(out)
    fixtures = str(out / "fixtures") + os.sep

    def inside(path):
        if isinstance(path, int):
            return True
        try:
            full = os.path.abspath(os.fsdecode(path))
        except TypeError:
            return True
        return full in (out_s, os.devnull) or full.startswith(out_s + os.sep)

    def launch_ok(argv):
        argv = [os.fsdecode(a) for a in argv]
        return (len(argv) == 7 and argv[:5] == [sys.executable, "-I", "-S", "-B", str(WORKER)]
                and argv[5].startswith(fixtures) and argv[5].endswith("/source/record.json")
                and argv[6] in ("true", "false"))

    def hook(event, args):
        if event.startswith("socket.") or event in LAUNCH:
            raise RuntimeError(f"the Harness2 engine refuses network use and other processes ({event})")
        if event in ("subprocess.Popen", "os.posix_spawn") and not launch_ok(args[1]):
            raise RuntimeError("the Harness2 engine launches only the fixed provenance worker")
        if event == "open":
            mode, flags = args[1], args[2]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                (isinstance(flags, int) and bool(flags & WRITE_FLAGS))
            if writing and not inside(args[0]):
                raise RuntimeError(f"the Harness2 engine writes only beneath --out, not {args[0]!r}")
        elif event in CHANGES:
            for i in CHANGES[event]:
                if not inside(args[i]):
                    raise RuntimeError(f"the Harness2 engine writes only beneath --out, not {args[i]!r}")

    sys.addaudithook(hook)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture_files(out, prov):
    """Every fixture file's exact bytes; records use kit's own canonical digest."""
    files = {}
    for task, control in CONTROLS.items():
        src = out / "fixtures" / task / "source"
        inp, outp = src / "input.txt", src / "output.txt"
        data = {inp: f"fixture input for {task}, version 1\n".encode(),
                outp: f"fixture output for {task}, version 1\n".encode()}

        def entry(path):
            return {"path": str(path), "kind": "file", "bytes": len(data[path]), "sha256": sha(data[path])}

        record = {"schema": prov.SCHEMA, "run": f"harness2-fixture-{task}", "code": [], "models": [],
                  "inputs": [entry(inp)], "outputs": [entry(outp)],
                  "note": "synthetic fixture generated by scripts/harness2; no scroll data"}
        record["digest"] = sha(prov.canonical(record))
        files[src / "record.json"] = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
                                      + "\n").encode()
        if control == "changed":
            data[inp] = f"fixture input for {task}, version 2\n".encode()
        if control == "missing":
            del data[outp]
        files.update(data)
    return files


def ensure_fixtures(out, prov):
    """Write the fixtures once, then require the exact bytes and the designed kit behavior."""
    files = fixture_files(out, prov)
    root = out / "fixtures"
    if not root.exists():
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    actual = {p for p in root.rglob("*") if p.is_file()}
    if actual != set(files) or any(p.read_bytes() != d for p, d in files.items()):
        raise EngineError("generated fixtures differ from fixture version 1; use a fresh --out")
    # The controls must be able to fail: kit itself must accept every digest and flag the edits.
    for task, control in CONTROLS.items():
        record = json.loads((root / task / "source" / "record.json").read_text(encoding="utf-8"))
        digest_only, rechecked = prov.verify(record), prov.verify(record, recheck_files=True)
        wanted = {"clean": [], "changed": ["changed"], "missing": ["missing"]}[control]
        if digest_only or [p.rsplit(" ", 1)[-1] for p in rechecked] != wanted:
            raise EngineError(f"fixture controls do not behave as designed in kit provenance ({control})")
    judge = out / "judge" / "expected.json"
    expected = {task: EXPECTED[control] for task, control in CONTROLS.items()}
    if not judge.exists():
        judge.parent.mkdir(parents=True, exist_ok=True)
        judge.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if json.loads(judge.read_text(encoding="utf-8")) != expected:
        raise EngineError("judge expectations differ from fixture version 1; use a fresh --out")
    return expected


def build(h2, out, manifest, run_mod):
    """The adapter and proposer, built on the loaded upstream classes."""
    spec_mod, tree_mod, prop_mod = h2["spec"], h2["tree"], h2["proposer"]
    limits = manifest["limits"]
    candidate = manifest["candidate"]
    json_text = run_mod.json_text

    # Upstream prompt templates exist only for its "opencode" and "codex" surfaces, so this
    # one-file surface borrows the OpenCode prompt family. The deterministic proposer ignores
    # that wording; a model-backed proposer would need prompts written for this surface.
    surface = tree_mod.SurfaceSpec(
        name="opencode", always_on=("recipe.json",), always_on_max=1024,
        always_on_cap_reason="the recipe holds exactly two fixed fields",
        skill_dir="skills", skill_name_rule="must_match",
        trigger_hint="This adapter accepts only recipe.json; remove `{name}`.",
        autotrigger_file="recipe.json", trigger_line="", subagent_requires_mode=False,
        plugin_dir=None, hooks_file=None)

    class RecipeSubstrate:
        name = "recipe"

        def surface(self):
            return surface

    channel = spec_mod.ChannelSpec("opencode", "local/deterministic")

    class ProvenanceAdapter:
        """Harness2 BenchmarkAdapter for three generated provenance fixtures."""

        def __init__(self):
            self.substrate = RecipeSubstrate()
            self.spec = spec_mod.BenchSpec(
                name="scrolls", runs_root=out / "runs", install_mode="workspace_config",
                prompts=spec_mod.BenchPrompts(
                    work="checking whether a run's provenance record still matches its listed files",
                    domain_word="workflow", deliverable_word="verdict"),
                channels={"proposer": channel, "selector": channel}, domain_word="workflow",
                leak_globs=("expected.json",))
            self.expected = {}
            self.lock = threading.Lock()
            self.new_executions = 0
            self.limit_hit = False

        # -- task family
        def tasks(self, split="all"):
            return list(CONTROLS)

        def domain_of(self, task_id):
            return DOMAIN

        def task_prompt(self, task_id):
            return TASK_PROMPT

        def task_files(self, task_id):
            if task_id not in CONTROLS:
                raise EngineError(f"unknown task {task_id!r}")
            return out / "fixtures" / task_id / "source"

        def base_harness(self):
            return out / "base"

        def validate_tree(self, harness):
            extra = sorted(set(harness) - {"recipe.json"})
            problems = [f"only recipe.json is editable; remove {', '.join(extra)}"] if extra else []
            try:
                run_mod.recipe(harness.get("recipe.json", ""))
            except ValueError as exc:
                problems.append(f"recipe.json: {exc}")
            if problems:
                raise ValueError(" | ".join(problems))

        # -- execution
        def run_dir(self, run_id):
            if not RUN_ID.fullmatch(run_id) or ".." in run_id.split("/"):
                raise EngineError(f"unsafe run id {run_id!r}")
            return out / "executions" / run_id

        def read_recipe(self, harness_dir):
            hdir = Path(harness_dir) if harness_dir is not None else self.base_harness()
            names = sorted(p.relative_to(hdir).as_posix() for p in hdir.rglob("*") if p.is_file())
            if names != ["recipe.json"]:
                raise EngineError(f"harness must hold only recipe.json, found {names}")
            return run_mod.recipe((hdir / "recipe.json").read_text(encoding="utf-8"))

        def execute(self, task_id, harness_dir, run_id, *, timeout=None):
            try:
                return self._execute(task_id, harness_dir, run_id)
            except Exception as exc:
                # Harness2 records a failed rollout without its cause; keep the cause in engine.log.
                print(f"execution {run_id} failed: {type(exc).__name__}: {exc}", flush=True)
                raise

        def _execute(self, task_id, harness_dir, run_id):
            run_dir = self.run_dir(run_id)
            recipe = self.read_recipe(harness_dir)
            if self.artifacts_intact(run_dir, recipe):
                return run_dir
            with self.lock:
                if self.new_executions >= limits["executions"]:
                    self.limit_hit = True
                    raise EngineError("execution limit reached")
                self.new_executions += 1
            if run_dir.exists():
                shutil.rmtree(run_dir)
            run_dir.mkdir(parents=True)
            record = self.task_files(task_id) / "record.json"
            flag = "true" if recipe["recheck_files"] else "false"
            proc = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(WORKER), str(record), flag],
                capture_output=True, stdin=subprocess.DEVNULL, cwd=run_dir,
                env={"PATH": os.defpath, "LANG": "C.UTF-8"}, timeout=limits["worker_seconds"])
            output = proc.stdout + proc.stderr
            if len(output) > limits["worker_output_bytes"]:
                raise EngineError("worker output exceeded its byte limit")
            if proc.returncode not in (0, 1):
                raise EngineError(f"worker failed with exit {proc.returncode}: {output[-400:]!r}")
            verdict = "accept" if proc.returncode == 0 else "reject"
            rechecked = "yes" if recipe["recheck_files"] else "no"
            command = "python -m kit provenance check source/record.json" + (" --files" if flag == "true" else "")
            text = output.decode("utf-8", "replace")
            answer = (f"verdict: {verdict}\nfiles rechecked: {rechecked}\ncommand: {command}\n"
                      f"exit status: {proc.returncode}\n")
            trajectory = (f"[ACTION] {command}\n[OBSERVATION]\n{text.rstrip()}\n"
                          f"exit status: {proc.returncode}\nfiles rechecked: {rechecked}\n")
            files = {"answer.txt": answer.encode(), "trajectory.md": trajectory.encode(), "worker.out": output}
            for name, data in files.items():
                (run_dir / name).write_bytes(data)
            meta = {"schema": 1, "run_id": run_id, "task": task_id, "recipe": recipe, "verdict": verdict,
                    "worker_exit": proc.returncode, "fixture_record_sha256": sha(record.read_bytes()),
                    "files_sha256": {name: sha(data) for name, data in files.items()}}
            (run_dir / "run.json").write_text(json_text(meta), encoding="utf-8")
            return run_dir

        def meta(self, run_dir):
            return run_mod.strict_json((Path(run_dir) / "run.json").read_text(encoding="utf-8"))

        def artifacts_intact(self, run_dir, recipe=None):
            """Saved execution files, fixture record and (when given) recipe all still match."""
            try:
                run_dir = Path(run_dir)
                meta = self.meta(run_dir)
                listed = meta["files_sha256"]
                present = {p.name for p in run_dir.iterdir()}
                record = self.task_files(meta["task"]) / "record.json"
                return (present == set(listed) | {"run.json"}
                        and all(sha((run_dir / n).read_bytes()) == h for n, h in listed.items())
                        and meta["fixture_record_sha256"] == sha(record.read_bytes())
                        and (recipe is None or meta["recipe"] == recipe))
            except (OSError, ValueError, KeyError, TypeError, EngineError):
                return False

        def delivered(self, run_dir):
            return self.artifacts_intact(run_dir) and (Path(run_dir) / "answer.txt").is_file()

        def trajectory(self, run_dir, *, obs_trunc):
            return (Path(run_dir) / "trajectory.md").read_text(encoding="utf-8")[:obs_trunc]

        def deliverable_text(self, run_dir):
            return (Path(run_dir) / "answer.txt").read_text(encoding="utf-8")

        def deliverable_files(self, run_dir):
            return {"answer.txt": self.deliverable_text(run_dir)}

        # -- judging, called only after selection
        def score(self, run_dir, task_id):
            if not self.artifacts_intact(run_dir):
                return None
            meta = self.meta(run_dir)
            if meta["task"] != task_id:
                return None
            ok = meta["verdict"] == self.expected[task_id]
            return {"n_passed": int(ok), "n_criteria": 1, "all_pass": ok, "verdict": meta["verdict"],
                    "expected": self.expected[task_id], "recipe": meta["recipe"]}

    def recipe_at(path):
        return run_mod.recipe(Path(path).read_text(encoding="utf-8"))

    class LocalProposer(prop_mod.Proposer):
        """Deterministic, bounded proposals and selection; no model service is called.

        demo: request the file recheck only when the task requires verified files and a base
        trajectory shows they were not rechecked; reuse a library lesson; compose from a pool
        candidate whose rollout shows the recheck. compare: write the supplied candidate
        exactly, never a repaired one.
        """

        def __init__(self):
            super().__init__(channel)
            self.lock = threading.Lock()
            self.new_calls = 0
            self.limit_hit = False

        def call(self, mission, context_dir, label, **kwargs):
            with self.lock:
                if self.new_calls >= limits["proposer_calls"]:
                    self.limit_hit = True
                    raise prop_mod.ProposerError("local proposer call limit reached", attempts=1)
                self.new_calls += 1
            ctx = Path(context_dir)
            workspace = None
            if label.startswith("select."):
                text = self.select(ctx)
            elif label.startswith("experience."):
                text = self.experience(ctx)
            else:
                workspace = ctx / "harness"
                text = f"<notes>{self.propose(ctx, label.split('.')[0])}</notes>"
            reply = prop_mod.Reply(label=label, text=text, ok=True, attempts=1, channel="local",
                                   workspace=workspace)
            with self.lock:
                self._calls.append(reply)
            return reply

        @staticmethod
        def requires_verified(ctx):
            return "verified against the record" in (ctx / "task.md").read_text(encoding="utf-8")

        def propose(self, ctx, stage):
            path = ctx / "harness" / "recipe.json"
            current = recipe_at(path)
            if candidate is not None:
                new, note = dict(candidate), ("Applied the supplied candidate recipe exactly; the local "
                                              "proposer never edits a supplied candidate.")
            elif stage.startswith("inv"):
                unverified = sorted(p.name for p in (ctx / "rollouts").glob("*.md")
                                    if "files rechecked: no" in p.read_text(encoding="utf-8"))
                if self.requires_verified(ctx) and unverified and not current["recheck_files"]:
                    new = dict(current, recheck_files=True)
                    note = (f"The task accepts only files verified against the record, but "
                            f"{', '.join(unverified)} observed `files rechecked: no`; request the recheck.")
                else:
                    new, note = current, "No observed defect that the recipe can address; kept it."
            elif stage.startswith("dom"):
                lessons = sorted(p.parent.name for p in (ctx / "library").rglob("EXPERIENCE.md")
                                 if "recheck_files" in p.read_text(encoding="utf-8"))
                if lessons and not current["recheck_files"]:
                    new = dict(current, recheck_files=True)
                    note = f"Applied the library lesson from {', '.join(lessons)}: recheck the listed files."
                else:
                    new, note = current, "No domain lesson applies yet; kept the current recipe."
            else:
                new, note = current, "No pool candidate observed a file recheck; kept the current recipe."
                for cand in sorted(p for p in (ctx / "pool").glob("*") if p.is_dir()):
                    rollout = cand / "rollout.md"
                    if (self.requires_verified(ctx) and rollout.is_file()
                            and "files rechecked: yes" in rollout.read_text(encoding="utf-8")):
                        new = recipe_at(cand / "harness" / "recipe.json")
                        note = f"Composed from {cand.name}, whose rollout observed `files rechecked: yes`."
                        break
            path.write_text(json_text(new), encoding="utf-8")
            return note

        def select(self, ctx):
            ids = sorted(p.stem for p in (ctx / "candidates").glob("*.md"))
            if not ids:
                return "<why>No candidates were shown.</why>"
            good = [i for i in ids if self.requires_verified(ctx) and "files rechecked: yes"
                    in (ctx / "candidates" / f"{i}.md").read_text(encoding="utf-8")]
            chosen = (good or ids)[0]
            why = ("Its observation shows the listed files were rechecked, as the task requires."
                   if good else "No candidate rechecked the files; chose the first in order.")
            return f"<why>{why}</why>\n```choice\n{chosen}\n```"

        def experience(self, ctx):
            if recipe_at(ctx / "harness" / "recipe.json") == recipe_at(ctx / "base_harness" / "recipe.json"):
                return "NO_ENTRY"
            return ("<edits>\ncomponent: recipe.json\nchange: set recheck_files to true\n"
                    "observed: the adopted rollout reports `files rechecked: yes`\n</edits>\n\n"
                    "<experience>\ncue: When a task accepts only files verified against a provenance record\n"
                    "lesson: Set recheck_files to true so the provenance check rehashes the listed files.\n"
                    "evidence: base rollouts report `files rechecked: no`; the adopted rollout reports yes.\n"
                    "confidence: fixture-only; deterministic local proposer\n</experience>")

    return ProvenanceAdapter(), LocalProposer(), surface


def verify_loaded(upstream, manifest):
    """Every loaded upstream module must match the hashes run.py recorded for the pin."""
    hashes = manifest["upstream"]["files_sha256"]
    for name, module in sorted(sys.modules.items()):
        if name != "harness2" and not name.startswith("harness2."):
            continue
        rel = Path(module.__file__).resolve().relative_to(upstream).as_posix()
        if hashes.get(rel) != sha(Path(module.__file__).read_bytes()):
            raise EngineError(f"loaded upstream module differs from the pin: {rel}")


def judge_runs(h2, adapter, out, k):
    """Independent fixture judgments of the baseline and adopted runs, after selection."""
    schedule, judge = h2["schedule"], h2["judge"]
    rows, selections = [], []
    for task, control in CONTROLS.items():
        ns = schedule.Namespace(adapter.spec.name, adapter.substrate.name, "agg", k)
        try:
            summary = json.loads((ns.task_dir(out / "runs", task) / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = {}
        base = summary.get("base") or []
        scored = [judge.judge_one(adapter, task, "base", k, b["label"], b["run_id"], Path(b["run_dir"]),
                                  chosen_is_base=True) for b in base]
        row = {"task": task, "control": control, "expected": adapter.expected[task],
               "baseline": [{"label": s.label, "verdict": s.raw.get("verdict"), "correct": s.all_pass,
                             "recipe": s.raw.get("recipe"), "error": s.error} for s in scored],
               "adopted": {}}
        for mode in MODES:
            sel = dict((summary.get("selections") or {}).get(mode) or {})
            sel.setdefault("task_id", task)
            sel.setdefault("mode", mode)
            sel.setdefault("k", k)
            selections.append(sel)
        rows.append(row)
    by_task = {row["task"]: row for row in rows}
    for s in judge.judge_selections(adapter, selections):
        by_task[s.task_id]["adopted"][s.mode] = {
            "label": s.label, "verdict": s.raw.get("verdict"), "correct": s.all_pass,
            "recipe": s.raw.get("recipe"), "error": s.error}
    return rows


def main(argv):
    if len(argv) != 3:
        raise SystemExit("usage: engine.py UPSTREAM OUT (run.py starts this)")
    started = time.monotonic()
    upstream, out = Path(argv[1]).resolve(), Path(argv[2]).resolve()
    run_mod = load_file("scrolls_harness2_run", HERE / "run.py")
    prov = load_file("scrolls_harness2_provenance", ROOT / "kit" / "provenance.py")
    manifest = run_mod.strict_json((out / "manifest.json").read_text(encoding="utf-8"))
    install_guard(out)
    load_file("harness2", upstream / "harness2" / "__init__.py", upstream / "harness2")
    import harness2.core.judge as judge
    import harness2.core.proposer as proposer
    import harness2.core.schedule as schedule
    import harness2.core.spec as spec
    import harness2.core.tree as tree
    verify_loaded(upstream, manifest)
    h2 = {"judge": judge, "proposer": proposer, "schedule": schedule, "spec": spec, "tree": tree}

    k, action, candidate = manifest["k"], manifest["action"], manifest["candidate"]
    adapter, prop, surface = build(h2, out, manifest, run_mod)
    if not isinstance(adapter, spec.BenchmarkAdapter):
        raise EngineError("adapter does not satisfy the pinned BenchmarkAdapter protocol")
    adapter.expected = ensure_fixtures(out, prov)
    base = adapter.base_harness()
    if not base.exists():
        tree.write_tree(surface, {"recipe.json": run_mod.json_text(BASE_RECIPE)}, base, stubs=False)
    if adapter.read_recipe(base) != BASE_RECIPE:
        raise EngineError("baseline recipe changed; use a fresh --out")

    result = schedule.run_domain(DOMAIN, adapter.tasks(), k, adapter=adapter, prop=prop,
                                 runs_root=out / "runs", library_root=out / "library" / f"k{k}",
                                 modes=MODES, selector_prop=prop)
    rows = judge_runs(h2, adapter, out, k)

    baseline_correct = sum(all(b["correct"] for b in row["baseline"]) and bool(row["baseline"]) for row in rows)
    adopted = {m: [row["adopted"].get(m) or {} for row in rows] for m in MODES}
    adopted_recipes = {m: sorted({json.dumps(a.get("recipe"), sort_keys=True) for a in adopted[m]}) for m in MODES}
    status = "ok"
    if adapter.limit_hit or prop.limit_hit:
        status = "limit-exceeded"
    elif result["failed"] or any(a.get("error") or a.get("verdict") is None for m in MODES for a in adopted[m]):
        status = "incomplete"
    elif baseline_correct == len(rows):
        status = "controls-invalid"
    elif candidate is not None and any(r != [json.dumps(candidate, sort_keys=True)] for r in adopted_recipes.values()):
        status = "incomplete"
    elif not all(a["correct"] for m in MODES for a in adopted[m]):
        status = "candidate-failed" if candidate is not None else "adopted-failed"

    comparison = {
        "schema": 1, "kind": "synthetic-provenance-workflow", "action": action, "k": k,
        "status": status, "claim": CLAIM, "fixture_version": FIXTURE_VERSION,
        "recipes": {"baseline": BASE_RECIPE, "candidate": candidate,
                    "adopted": {m: [json.loads(r) for r in adopted_recipes[m]] for m in MODES}},
        "summary": {"controls": len(rows), "baseline_correct": baseline_correct,
                    "adopted_correct": {m: sum(bool(a.get("correct")) for a in adopted[m]) for m in MODES}},
        "controls": rows,
        "harness2": {"commit": manifest["upstream"]["commit"], "modes": list(MODES), "domain": DOMAIN,
                     "done": result["done"], "failed": result["failed"], "tasks": result["tasks"]},
        "new_executions": adapter.new_executions, "new_proposer_calls": prop.new_calls,
        "wall_seconds": round(time.monotonic() - started, 2),
    }
    (out / "comparison.json").write_text(run_mod.json_text(comparison), encoding="utf-8")
    print(f"comparison status {status}: {out / 'comparison.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
