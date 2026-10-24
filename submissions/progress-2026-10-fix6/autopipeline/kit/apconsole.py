"""The AutoPipeline monitor's console: notes on a run, and a command box that runs VC3D agent tools and kit commands.

Notes are a Markdown file per run folder under the kit home (work/autopipe-notes/, which git ignores), never in the
run folder itself, which the monitor only reads. A command is one line:

    kit ARGS...            any `python -m kit` command through the VC3D agent's kit tool (not `run local`)
    ap ARGS...             the same as `kit autopipeline ARGS...` (also `autopipeline ARGS...`)
    TOOL KEY=VALUE...      a VC3D agent tool (`python -m kit vc3d tools` lists them); VALUE is JSON when it
                           parses as JSON, else a string, as `kit vc3d call --arg` takes it
    TOOL {JSON}            the same, with the arguments as one JSON object

{run} anywhere in an argument is the run folder and {surface} the surface chosen on the page.

Every command runs as a VC3D agent background job (`kit vc3d call jobs`), so the page never waits on it; the jobs
started from one run's monitor are listed with that run's notes. `app_open surfaces=[...] display=true` opens
surfaces in the VC3D app's window; without display it runs offscreen, as the other tools do.
"""

import hashlib
import json
import os
import re
import shlex
from pathlib import Path

from . import vc3d_agent

NOTES_MAX = 64 * 1024
JOBS_KEPT = 50
RUN_TIMEOUT = 7 * 24 * 3600    # `ap run` resumes a whole run: the kit tool's 30 minute default would cut it off
KIT_WORDS = ("kit", "python -m kit", "python3 -m kit")
AP_WORDS = ("ap", "autopipeline")


class ConsoleError(ValueError):
    """A command or note the console refuses; the message says why."""


def _key(folder):
    folder = Path(folder).resolve()
    digest = hashlib.sha256(str(folder).encode("utf-8")).hexdigest()[:12]
    return f"{vc3d_agent.slug(folder.name, 40)}-{digest}"


def notes_dir(ctx):
    return ctx.root / "work" / "autopipe-notes"


def notes_path(ctx, folder):
    """Where the notes of run folder `folder` live: one file per resolved folder path, outside the folder."""
    return notes_dir(ctx) / f"{_key(folder)}.md"


def read_notes(ctx, folder):
    p = notes_path(ctx, folder)
    try:
        st = p.stat()
        return {"text": p.read_text(encoding="utf-8", errors="replace")[:NOTES_MAX], "saved": st.st_mtime,
                "path": str(p)}
    except FileNotFoundError:
        return {"text": "", "saved": None, "path": str(p)}


def _atomic(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def save_notes(ctx, folder, text):
    """Replace the run's notes with text (at most 64 KB as UTF-8). Empty text removes the file."""
    if not isinstance(text, str):
        raise ConsoleError("notes are text")
    if len(text.encode("utf-8")) > NOTES_MAX:
        raise ConsoleError(f"notes are at most {NOTES_MAX // 1024} KB")
    p = vc3d_agent.writable(ctx, notes_path(ctx, folder))
    if not text.strip():
        p.unlink(missing_ok=True)
        return {"text": "", "saved": None, "path": str(p)}
    _atomic(p, text)
    return read_notes(ctx, folder)


def parse(command):
    """(tool name, arguments) for one console line; ConsoleError when it is not one."""
    line = (command or "").strip()
    if not line:
        raise ConsoleError("type a command, e.g. ap status RUN, kit doctor, or app_open surfaces=[\"...\"]")
    if len(line) > 8000:
        raise ConsoleError("a command is at most 8000 characters")
    for word in KIT_WORDS:
        if line == word or line.startswith(word + " "):
            words = _split(line[len(word):])
            if not words:
                raise ConsoleError("kit needs a command, e.g. kit doctor")
            return "kit", {"args": words}
    head, _, rest = line.partition(" ")
    if head in AP_WORDS:
        words = _split(rest)
        if not words:
            raise ConsoleError("ap needs an action, e.g. ap status RUN")
        args = {"args": ["autopipeline", *words]}
        if words[0] == "run":
            args["timeout"] = RUN_TIMEOUT
        return "kit", args
    name = vc3d_agent.TOOL_ALIASES.get(head, head)
    if name not in vc3d_agent.TOOLS:
        raise ConsoleError(f"no tool {head!r}: start with kit, ap, or one of {', '.join(sorted(vc3d_agent.TOOLS))}")
    rest = rest.strip()
    if rest.startswith("{"):
        try:
            args = json.loads(rest)
        except json.JSONDecodeError as exc:
            raise ConsoleError(f"{name}: the arguments are not one JSON object ({exc.msg})") from exc
        if not isinstance(args, dict):
            raise ConsoleError(f"{name}: the arguments are not one JSON object")
    else:
        args = pairs(rest, name)
    args.pop("background", None)
    return name, args


_KEY = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)=")


def pairs(text, name="tool"):
    """KEY=VALUE words as a dict. A VALUE starting with [ or { is read as JSON up to its matching bracket, so
    surfaces=["/a b"] keeps its quotes and spaces (one that is not JSON, such as {surface}, is a plain word); a
    quoted VALUE is that string; any other VALUE runs to the next space and is JSON when it parses as JSON (2,
    true, null), else the string, as `kit vc3d call --arg` reads it."""
    out, i, dec = {}, 0, json.JSONDecoder()
    while i < len(text):
        if text[i:].strip() == "":
            break
        m = _KEY.match(text, i)
        if not m:
            word = text[i:].split(None, 1)[0]
            raise ConsoleError(f"{name}: {word!r} is not KEY=VALUE")
        key, i = m.group(1), m.end()
        ch, done = text[i:i + 1], False
        if ch in ("[", "{"):
            try:
                value, i = dec.raw_decode(text, i)
                done = True
            except json.JSONDecodeError:   # not JSON, such as {surface}: a plain word below
                pass
        if done:
            pass
        elif ch in ("'", '"'):
            end = text.find(ch, i + 1)
            if end < 0:
                raise ConsoleError(f"{name}: {key} has no closing {ch}")
            value, i = text[i + 1:end], end + 1
        else:
            m2 = re.compile(r"\S*").match(text, i)
            raw, i = m2.group(0), m2.end()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
        if i < len(text) and not text[i].isspace():
            raise ConsoleError(f"{name}: put a space after {key}'s value")
        out[key] = value
    return out


def _split(text):
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise ConsoleError(f"cannot split the command: {exc}") from exc


def _jobs_file(ctx, folder):
    return notes_dir(ctx) / f"{_key(folder)}.jobs.json"


def _job_list(ctx, folder):
    """This run's console jobs, newest first, as {"job": id, "command": the line typed}."""
    try:
        rows = json.loads(_jobs_file(ctx, folder).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("job"), str)]


def _job_ids(ctx, folder):
    return [r["job"] for r in _job_list(ctx, folder)]


def fill(value, names):
    """value with each {run} and {surface} in its strings replaced by that path (after parsing, so a path needs no
    quoting); a placeholder with no path given is refused."""
    if isinstance(value, str):
        for key in ("run", "surface"):
            mark = "{" + key + "}"
            if mark in value:
                if not names.get(key):
                    raise ConsoleError(f"{mark} needs a {'chosen surface' if key == 'surface' else 'run folder'}")
                value = value.replace(mark, str(names[key]))
        return value
    if isinstance(value, list):
        return [fill(v, names) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, names) for k, v in value.items()}
    return value


def run(ctx, folder, command, surface=None):
    """Check and start one console command as a background job; returns the job's record (id, tool, log). {run} in
    the command is the run folder and {surface} the path of the given surface (a tifxyz folder)."""
    name, args = parse(command)
    args = fill(args, {"run": str(Path(folder).resolve()), "surface": str(surface) if surface else None})
    tool = vc3d_agent.TOOLS[name]
    try:
        vc3d_agent.validate(tool, args)
    except vc3d_agent.ToolError as exc:
        raise ConsoleError(str(exc)) from exc
    if name == "kit":     # the kit tool's own refusals, said before a job starts
        words = [str(x) for x in args["args"]]
        if words[:2] == ["run", "local"] or (words[:1] == ["vc3d"] and words[1:2] in (["mcp"], ["app-mcp"])):
            raise ConsoleError("that kit command is not offered here; run it in a terminal")
    p = vc3d_agent.writable(ctx, _jobs_file(ctx, folder))
    rec = vc3d_agent.submit_job(ctx, name, args)
    rec["command"] = command.strip()
    _atomic(p, json.dumps(([{"job": rec["job"], "command": rec["command"]}] + _job_list(ctx, folder))[:JOBS_KEPT]))
    return rec


def jobs(ctx, folder, limit=12):
    """The jobs started from this run's console, newest first: id, tool, status, created, finished, error and the
    command typed."""
    out = []
    for row in _job_list(ctx, folder)[:limit]:
        try:
            info = vc3d_agent.job_info(ctx, row["job"], lines=1)
        except vc3d_agent.ToolError:
            continue
        out.append(dict({k: info.get(k) for k in ("job", "tool", "status", "created", "finished", "error")},
                        command=row.get("command")))
    return out


def job(ctx, folder, jid, lines=40):
    """One of this run's console jobs, with its log tail and result; a job this run did not start is refused."""
    if jid not in _job_ids(ctx, folder):
        raise ConsoleError(f"{jid!r} was not started from this run's console")
    try:
        info = vc3d_agent.job_info(ctx, jid, lines=lines)
    except vc3d_agent.ToolError as exc:
        raise ConsoleError(str(exc)) from exc
    info["command"] = next((r.get("command") for r in _job_list(ctx, folder) if r["job"] == jid), None)
    res = info.get("result")
    if isinstance(res, dict) and isinstance(res.get("output"), str):     # the kit tool: its printed output
        info["output"] = res["output"]
        res = {k: v for k, v in res.items() if k != "output"}
    if res is not None:
        text = json.dumps(res, indent=1, default=str)
        info["result"] = text if len(text) <= 20000 else text[:20000] + "\n... (cut; the whole result is in the job)"
    return info


def cancel(ctx, folder, jid):
    if jid not in _job_ids(ctx, folder):
        raise ConsoleError(f"{jid!r} was not started from this run's console")
    return vc3d_agent.job_cancel(ctx, jid)


def tools():
    """Name and title of every command the console takes, for the page's suggestions."""
    out = [{"name": "ap", "title": "AutoPipeline (kit autopipeline ...)"},
           {"name": "kit", "title": "Any kit command"}]
    out += [{"name": t.name, "title": t.title} for t in vc3d_agent.TOOLS.values() if t.name != "kit"]
    return out
