"""AutoPipeline's live monitor: one page that shows what a run folder is doing, served on this machine only.

  python -m kit autopipeline monitor RUN_FOLDER [--port N] [--host H] [--open]   serve it live on 127.0.0.1
  python -m kit autopipeline monitor RUN_FOLDER --snapshot FILE.html               write it once, with no server
  python -m kit autopipeline run RUN_FOLDER --monitor [PORT]                       serve it while the run lasts
  python -m kit autopipeline monitor RUN_FOLDER --text [--width N] [--watch S]    the same run as text, here

summarize() reads one run folder (plan.json, state.json, report.json, scores.json, events.jsonl and the newest tool
log) and returns one JSON summary, which the page draws: what the run is doing now, each of the 11 stages with
its status and time, each surface with its checks, a 3D wireframe of its traced mesh, ink maps and scores beside
their reversed-map controls, and the tail of the run's log. Thumbnails and wireframes wait under a skeleton
shimmer until they load. text_view() prints the same run in a terminal, the maps drawn in characters. It reads only files that resolve inside the folder (a symlink out of it is not
followed), and shows paths inside the folder as <run> and the home folder as ~, pieces of them that a cut line
leaves included. The server answers GET only, for
the page, the summary and thumbnails of the ink maps state.json names; no URL maps to a file, and nothing is ever
written into the run folder. The page is one self-contained HTML document (inline CSS and JavaScript, no fonts,
scripts or images from elsewhere) and makes no request beyond its own server; a snapshot embeds the summary,
without the folder's path, the host or the process id, with any other absolute path shown by its last name, and
needs none.

EventLog is the run's side: Run.run (kit/autopipe.py) marks the stage it is in under state.json's "running" key
(with the process id and host, so the page can tell a live run from a stopped one; a stage that raises something
Run does not record as a failure, a bug or Ctrl-C, leaves the mark as crashed or interrupted) and appends
progress lines and stage events to events.jsonl, which is kept to about 512 KiB.

Every surface, map and score the page shows is model output, not a reading. Maps of target scrolls must not be
shared: thumbnails are on by default only for smoke runs and published labeled segments. Standard library;
numpy and tifffile, when present, make thumbnails of large maps, decoding at most THUMB_MAX_DECODED bytes at a
time (an uncompressed map is read through a memory map instead).
"""

import array
import base64
import calendar
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import struct
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import autopipe, tracebudget, vc3d_io

SCHEMA = 1
STALE_S = 1800                 # no update to state.json or events.jsonl for this long: the run looks stopped
EVENTS = "events.jsonl"
EVENTS_OLD = "events.1.jsonl"  # the previous part, once events.jsonl passed EVENTS_MAX
EVENTS_MAX = 256 * 1024
TAIL = 60                      # log lines the page shows
TOOL_LOG_READ = 64 * 1024      # bytes of the newest tool log read for its last lines (GridStore warnings left out)
THUMB_SIDE = 192               # a thumbnail's longest side, in pixels
THUMB_MAX_DECODED = 256 << 20  # a compressed map that decodes to more than this gets no thumbnail
THUMB_MAX_PLAIN = 4 << 20      # without numpy and tifffile, only TIFFs this small
MAX_SURFACES = 300
MAX_REASONS = 20
MAX_TEXT = 600
LINE_KEEP = 2000               # a log line as kept; the page shows LINE_SHOW of it, once paths are shortened
LINE_SHOW = 500
DEFAULT_PORT = 8765
LOCAL = "127.0.0.1"
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
FINISHED = ("done", "skipped", "handoff")
STAGE_LABELS = {"qa": "QA"}   # stage names the page writes other than with a capital first letter
ENDED_MARKS = ("crashed", "interrupted")   # a running mark the run left when a stage raised (EventLog.ended)
NOTE = ("Every surface, map and score here is model output, not a reading. Maps of target scrolls must not be "
        "shared.")
CSP = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'")


class MonitorError(ValueError):
    """A folder or output the monitor refuses."""


# ---------------------------------------------------------------- the run's side: running mark and events.jsonl

class EventLog:
    """events.jsonl in a run folder: one JSON object per line, a progress line ({"t", "stage", "msg"}) or a stage
    event ({"t", "stage", "event", "seconds", "error"}). When the file passes max_bytes it becomes events.1.jsonl
    (replacing the older part), so a run keeps at most about twice max_bytes. Writing never fails a run."""

    def __init__(self, out, max_bytes=EVENTS_MAX):
        self.path = Path(out) / EVENTS
        self.max_bytes = max_bytes
        self.stage_now = None
        self._lock = threading.Lock()

    @staticmethod
    def _mark(stage, t):
        return {"stage": stage, "status": "running", "started": time.strftime(TIME_FMT, time.gmtime(t)),
                "started_epoch": round(t, 3), "pid": os.getpid(), "host": socket.gethostname()}

    def running(self, stage, t=None):
        """The record Run keeps under state["running"] while `stage` runs; the event goes to the log."""
        t = time.time() if t is None else t
        self.stage_now = stage
        self._write({"t": round(t, 1), "stage": stage, "event": "running"})
        return self._mark(stage, t)

    def ended(self, mark, stage, exc, seconds):
        """The running mark of a stage that raised something Run does not record as a stage failure (a bug, or
        Ctrl-C): status crashed or interrupted, with when and why. Run keeps it outside "stages", so the stage is
        not done and a resume reruns it, and the page says the run stopped even while the process lives on (an MCP
        server that caught the error). The event goes to the log."""
        t = time.time()
        how = ENDED_MARKS[1] if isinstance(exc, (KeyboardInterrupt, SystemExit)) else ENDED_MARKS[0]
        error = _cut(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__, MAX_TEXT)
        rec = dict(mark) if isinstance(mark, dict) and mark.get("stage") == stage else self._mark(stage, t - seconds)
        rec.update(status=how, ended=_iso(t), ended_epoch=round(t, 3), error=error)
        self.stage(stage, how, {"seconds": round(seconds, 1), "error": error})
        return rec

    def tee(self, then):
        """A progress callback that logs each message, then passes it on to `then` (may be None)."""
        def say(message):
            self.line(message)
            if then is not None:
                then(message)
        return say

    def line(self, message):
        self._write({"t": round(time.time(), 1), "stage": self.stage_now, "msg": _cut(message, LINE_KEEP)})

    def stage(self, stage, status, extra=None):
        extra = extra or {}
        rec = {"t": round(time.time(), 1), "stage": stage, "event": status}
        if extra.get("seconds") is not None:
            rec["seconds"] = extra["seconds"]
        if extra.get("error"):
            rec["error"] = _cut(extra["error"], MAX_TEXT)
        self._write(rec)
        if self.stage_now == stage:
            self.stage_now = None

    def _write(self, rec):
        text = json.dumps(rec, default=str) + "\n"
        with self._lock:
            try:
                if self.path.is_file() and self.path.stat().st_size + len(text) > self.max_bytes:
                    os.replace(self.path, self.path.with_name(EVENTS_OLD))
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError:
                pass


# ---------------------------------------------------------------- small helpers

def _cut(text, n=MAX_TEXT):
    text = "" if text is None else str(text)
    return text if len(text) <= n else text[:n - 1] + "\u2026"


def _sentence(text):
    text = str(text or "").strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _iso(t):
    return time.strftime(TIME_FMT, time.gmtime(t))


def _epoch(stamp):
    try:
        return float(calendar.timegm(time.strptime(str(stamp), TIME_FMT)))
    except (TypeError, ValueError):
        return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _d(v):
    """v when it is a dict, else {}: a record of an unexpected shape reads as empty and never breaks the page."""
    return v if isinstance(v, dict) else {}


def _dur(seconds):
    """Plain words for a span, as the page's dur() writes it: 4.5 s, 45 s, 12 min 5 s, 2 h 5 min."""
    if seconds is None:
        return "an unknown time"
    s = max(0.0, float(seconds))
    if s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{min(59, int(s + 0.5))} s"
    s = int(s)
    if s < 3600:
        m, r = divmod(s, 60)
        return f"{m} min {r} s" if r else f"{m} min"
    h, m = s // 3600, (s % 3600) // 60
    return f"{h} h {m} min" if m else f"{h} h"


def _cap(text):
    text = str(text or "")
    return text[:1].upper() + text[1:]


def _label(stage):
    """A stage's name as the page shows it: Acquire, Umbilicus, ..., QA, ..., Report (the page's stageName())."""
    stage = str(stage or "")
    return STAGE_LABELS.get(stage, _cap(stage))


def _first_clause(text, n=240):
    """An error's words before its first dict or list (the full error is on the stage's row)."""
    text = str(text or "")
    cuts = [i for i in (text.find(sep) for sep in (": {", ": [", " {'", ' {"')) if i > 0]
    return _cut(text[:min(cuts)] if cuts else text, n)


def pid_alive(pid):
    """True when a process with this id runs on this machine, False when none does, None when it cannot tell."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if os.name != "posix":
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _inside(folder, path):
    """path resolved, when it lies inside folder (resolved), else None."""
    try:
        p = Path(str(path))
        if not p.is_absolute():
            p = folder / p
        p = p.resolve()
        p.relative_to(Path(folder).resolve())
        return p
    except (ValueError, OSError, RuntimeError):
        return None


# Parsed files, read again only when their mtime or size changes, so polling a large state.json every 2 s is cheap
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _stat(path):
    try:
        st = os.stat(path)
        return st
    except OSError:
        return None


def _cached(path, kind, read):
    st = _stat(path)
    if st is None:
        return None, None
    key = (str(path), kind)
    sig = (st.st_mtime_ns, st.st_size)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit and hit[0] == sig:
        return hit[1], st
    value = read(path)
    with _CACHE_LOCK:
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[key] = (sig, value)
    return value, st


def _json_file(folder, name):
    """(value, stat, error) of the JSON file folder/name. A file that resolves outside the folder (a symlink out
    of it) is present but not read. Read twice before it counts as unreadable (a writer may be mid-way)."""
    path = folder / name
    if not os.path.lexists(path):
        return None, None, "missing"
    real = _inside(folder, path)
    if real is None:
        try:
            st = os.lstat(path)
        except OSError:
            return None, None, "missing"
        return None, st, f"{name} points outside the run folder, so the monitor does not read it"

    def read(p):
        err = None
        for attempt in range(2):
            try:
                return {"value": json.loads(Path(p).read_text(encoding="utf-8")), "error": None}
            except (OSError, ValueError) as exc:
                err = f"{type(exc).__name__}: {_cut(exc, 200)}"
                if attempt == 0:
                    time.sleep(0.05)
        return {"value": None, "error": err}
    got, st = _cached(real, "json", read)
    if got is None:
        return None, None, "missing"
    return got["value"], st, got["error"]


def _sha256(folder, name):
    real = _inside(folder, folder / name)
    if real is None:
        return None
    got, _ = _cached(real, "sha256", lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest())
    return got


def _kit_home():
    try:
        from . import kithome
        return Path(kithome.home()).resolve()
    except Exception:  # noqa: BLE001 - no kit home known: paths in it are shown in full
        return None


def _subs(folder):
    """Display substitutions: the run folder's path as <run>, the kit home's as <kit>, the home folder as ~ (log
    lines and errors repeat them; the page names the folder once, and a snapshot does not name it)."""
    paths = []
    kit = _kit_home()
    for p, short in ((folder, "<run>"), (Path(os.path.abspath(str(folder))), "<run>"), (kit, "<kit>"),
                     (Path.home(), "~")):
        if p is None:
            continue
        try:
            p = str(p)
        except (RuntimeError, OSError):
            continue
        if len(p) > 1 and (p, short) not in paths:
            paths.append((p, short))
    try:
        real_home = str(Path.home().resolve())
        if len(real_home) > 1 and (real_home, "~") not in paths:
            paths.append((real_home, "~"))
    except (RuntimeError, OSError):
        pass
    whole = [(re.compile(re.escape(p) + r"(?![\w.\-])"), short) for p, short in paths]
    return whole + [x for p, short in paths for x in _piece_subs(p, short)]


_PATH_CHAR = r"[\w.\-/~]"


def _piece_subs(p, short):
    """The pieces of path p that a cut line leaves, as short: a tail (a progress line keeps a tool log line's last
    characters, kit/vc3d_agent.py) and a head before an ellipsis (a line cut at LINE_KEEP). A piece counts when it
    holds a separator after its first character, so it names at least one folder above its last; a piece that
    starts or ends inside a word is not one. Tried after the whole paths, so a whole path is never a piece."""
    tails = [p[k:] for k in range(1, len(p)) if p.find("/", k + 1) != -1]
    heads = [p[:k] for k in range(2, len(p)) if p.find("/", 1, k) != -1]
    out = []
    if tails:
        alt = "|".join(re.escape(t) for t in sorted(tails, key=len, reverse=True))
        out.append((re.compile(rf"(?<!{_PATH_CHAR})(?:{alt})(?![\w.\-])"), short))
    if heads:
        alt = "|".join(re.escape(h) for h in sorted(heads, key=len, reverse=True))
        out.append((re.compile(rf"(?<!{_PATH_CHAR})(?:{alt})(?=…)"), short))
    return out


# a snapshot or an export shows any other absolute path (at least two names deep) by its last name only, since
# a path outside the run folder and the kit home can still name the folders around them (a tool or model given
# by its path, a volume beside the run folder). Not after a scheme (s3://, https://) or one of the short names.
_ELSEWHERE = re.compile(r"(?<![\w.\-/~:>])/(?:[\w.\-~]+/)+[\w.\-~]*")


def _by_name(m):
    name = [x for x in m.group(0).split("/") if x][-1]
    return f"\u2026/{name}" + ("/" if m.group(0).endswith("/") else "")


# and a path piece at the start of a progress line's tail (kit/vc3d_agent.py keeps a tool log line's last 200
# characters, so the tail can start inside any path, such as a Python under the home folder) by its last name too
_CUT_START = re.compile(r"^([^\s:]+: \d+ s; )(?![<~/\u2026])(\S*/\S*)")


def _cut_start(m):
    name = [x for x in m.group(2).split("/") if x][-1:] or [""]
    return f"{m.group(1)}\u2026/{name[0]}"


def _redact(obj, subs, skip=()):
    if isinstance(obj, str):
        for rx, short in subs:
            obj = rx.sub(short, obj)
        return obj
    if isinstance(obj, list):
        return [_redact(x, subs) for x in obj]
    if isinstance(obj, dict):
        return {k: (v if k in skip else _redact(v, subs)) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------- the summary

def _trace_stop(rec):
    """What stopped a trace (trace.budget's record, kit/tracebudget.py stop_record), for a surface or a failure:
    its partial kind, reason, generations done of planned, the last "gen N" line, recent seconds per generation and
    the GridStore cache warnings left out of its log; {} for a record without one (a plan without trace.budget)."""
    stop = _d(_d(rec).get("stop"))
    if not stop:
        return {}
    prog = _d(stop.get("progress"))
    return {"partial": stop.get("partial"), "stop_reason": _cut(stop.get("reason"), 200),
            "generations_done": stop.get("generations_done"), "generations_planned": stop.get("generations_planned"),
            "last_gen_line": _cut(prog.get("last_gen_line"), 200),
            "seconds_per_generation": _num(prog.get("seconds_per_generation_recent")),
            "gridstore_warnings_left_out": prog.get("gridstore_warnings_left_out")}


def _trace_progress(lines):
    """The newest progress line of the tracer in the trace stage's events (the trace tool writes "gen N of M in
    progress, D done, A mm2, last generation S s" there, kit/tracebudget.py TraceLog.message), or None."""
    for e in reversed(lines or []):
        msg = e.get("msg")
        if e.get("stage") == "trace" and isinstance(msg, str) and msg.startswith("vc_grow_seg_from_seed:"):
            return _cut(msg, 300)
    return None


def _trace_method(settings):
    """The plan's trace method by its own name (an optional trace.<name> setting this module does not know), or
    None. Found the way kit/autopipe.py finds it, without knowing any method."""
    trace = _d(settings.get("trace"))
    names = [k for k, v in trace.items() if v is not None and k not in autopipe.DEFAULTS["trace"]
             and f"trace.{k}" not in autopipe.PLAIN_OPTIONAL]
    return names[0] if names else None


def _plan_part(plan):
    s, r = _d(plan.get("settings")), _d(plan.get("resolved"))
    ink = _d(s.get("ink"))
    d = str(plan.get("digest") or "")
    return {"digest": d or None, "short": d[:12] or None, "version": plan.get("version"),
            "created": plan.get("created"), "sample": r.get("sample"), "volume": r.get("volume"),
            "voxel_um": r.get("voxel_um"), "purpose": s.get("purpose"), "experiment": s.get("experiment"),
            "segment": s.get("segment"),
            # a published segment with published labels (make_plan resolves it from BENCHMARKS)
            "labelled_segment": bool(s.get("segment") and _d(r.get("benchmark"))),
            "prediction_model": r.get("prediction_model"),
            "models": [str(m) for m in ink["models"]] if isinstance(ink.get("models"), list) else [],
            "ink_where": ink.get("where"), "trace_method": _trace_method(s)}


def _count(values):
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def _stage_summary(name, rec):
    """One plain line from a stage's record."""
    status, r = rec.get("status"), rec.get("record")
    if status == "failed":
        return _cut(rec.get("error"), 300)
    if not isinstance(r, dict):
        return None
    if set(r) == {"skipped"}:
        return _cut(r["skipped"], 300)
    if status == "handoff":
        return f"handed off to the {r.get('handoff') or 'other'} runner"
    if name == "acquire":
        bits = [f"{r['voxel_um']} um voxels" if _num(r.get("voxel_um")) else None,
                f"volume {len(r['volume_levels'])} levels" if isinstance(r.get("volume_levels"), list) else None,
                f"prediction {len(r['prediction_levels'])} levels" if isinstance(r.get("prediction_levels"), list)
                else None]
        return ", ".join(b for b in bits if b) or "inputs resolved"
    if name == "umbilicus":
        return f"axis from {r.get('source', 'unknown source')}" + (f", {r['points']} points" if _num(r.get("points"))
                                                                   else "")
    if name == "seeds":
        st = r.get("stats") or {}
        bits = [f"{len(r.get('seeds') or [])} seeds"]
        bits += [f"{st[k]} {k.replace('_', ' ')}" for k in ("candidates", "refused", "too_close") if st.get(k)]
        return ", ".join(bits)
    if name == "trace":
        return f"{len(r.get('surfaces') or [])} traced, {len(r.get('failed') or [])} failed"
    if name == "qa":
        w = r.get("warnings") or {}
        return (f"accepted {len(r.get('accepted') or [])}, rejected {len(r.get('rejected') or [])}"
                + (f", warnings on {len(w)}" if w else ""))
    if name == "flatten":
        c = _count(v for v in r.values() if isinstance(v, str))
        return ", ".join(f"{n} {k}" for k, n in sorted(c.items())) or None
    if name == "render":
        vals = [v for k, v in r.items() if k != "label_transfer" and isinstance(v, str)]
        refused = sum(v.startswith("refused") for v in vals)
        failed = sum(v.startswith("failed") for v in vals)
        bits = [f"{len(vals) - refused - failed} rendered"]
        bits += [f"{refused} refused"] if refused else []
        bits += [f"{failed} failed"] if failed else []
        return ", ".join(bits)
    if name == "ink":
        runs = [e for v in r.values() if isinstance(v, dict) for e in v.values()]
        bad = [e for e in runs if e != 0]
        return f"{len(r)} surfaces, {len(runs)} model runs" + (f", {len(bad)} not exit 0" if bad else ", all exit 0")
    if name == "score":
        if "rule" in r and "surfaces" in r:
            return f"own traces on carried labels: {len(r.get('surfaces') or {})} surfaces"
        return f"{len(r)} models scored"
    if name == "report":
        return f"report digest {str(r.get('digest') or '')[:12]}" if r.get("digest") else "report written"
    return None


def _auc(d, key="forward"):
    return _num(_d(_d(d).get(key)).get("auc"))


def _bench_rows(model, m):
    """Score rows of one model from a benchmark's score_maps record ({whole, crop, shuffled_whole})."""
    if not isinstance(m, dict):
        return []
    if m.get("error"):
        return [{"model": model, "scope": None, "error": _cut(m["error"], 300)}]
    rows = []
    for scope in ("whole", "crop"):
        d = m.get(scope)
        if not isinstance(d, dict):
            continue
        row = {"model": model, "scope": scope, "forward_auc": _auc(d), "control_auc": _auc(d, "control"),
               "control_name": "reversed", "shuffled_auc": _auc(m.get("shuffled_whole")) if scope == "whole" else None,
               "displaced_auc": None, "reference_auc": None, "scorable": True, "why": None, "error": None}
        if d.get("skipped"):
            row.update(scorable=False, why=_cut(d["skipped"], 300))
        elif d.get("exit") not in (None, 0) or "stderr" in d:
            row["error"] = _cut(f"kit auc exited {d.get('exit')}: {d.get('stderr') or ''}", 300)
        rows.append(row)
    return rows


def _scores(folder, state):
    """{surface id: [score rows]} from scores.json (or the score stage's record), both shapes AutoPipeline writes:
    a benchmark's ({model: {whole, crop, shuffled_whole}}, on surface seg) and score.transfer's."""
    data, st, err = _json_file(folder, "scores.json")
    present = st is not None
    if data is None:
        data = _d(_d(state.get("stages")).get("score")).get("record")
    out = {}
    if not isinstance(data, dict) or set(data) == {"skipped"}:
        return out, {"present": present, "skipped": _cut(data["skipped"], 300) if isinstance(data, dict) else None,
                     "error": err if present else None}
    if "rule" in data and isinstance(data.get("surfaces"), dict):
        for key, ref in _d(data.get("references")).items():
            if isinstance(ref, dict) and isinstance(ref.get("models"), dict):
                out[str(ref.get("surface") or f"ref-{key}")] = [row for model, m in ref["models"].items()
                                                                for row in _bench_rows(model, m)]
        for sid, e in data["surfaces"].items():
            rows = out.setdefault(sid, [])
            if not isinstance(e, dict):
                continue
            if e.get("scorable") is False and not e.get("segments"):
                rows.append({"model": None, "scope": None, "scorable": False, "why": _cut(e.get("why"), 300)})
                continue
            for key, g in _d(e.get("segments")).items():
                if not isinstance(g, dict):
                    continue
                if not g.get("scorable"):
                    rows.append({"model": None, "scope": key, "scorable": False, "why": _cut(g.get("why"), 300)})
                    continue
                for model, m in _d(g.get("models")).items():
                    m = _d(m)
                    rows.append({"model": model, "scope": f"carried from {key}", "forward_auc": _auc(m),
                                 "control_auc": _auc(m, "reverse"), "control_name": "reversed",
                                 "shuffled_auc": _auc(m, "shuffled"),
                                 "displaced_auc": _num(_d(m.get("displaced")).get("mean_auc")),
                                 "reference_auc": _num(_d(_d(m.get("reference")).get("on_carried_pixels"))
                                                       .get("auc")),
                                 "scorable": True, "why": None,
                                 "error": _cut(m["error"], 300) if m.get("error") else None})
    else:
        out["seg"] = [row for model, m in data.items() for row in _bench_rows(model, m)]
    return out, {"present": present, "skipped": None, "error": err if present else None}


def _map_file(folder, sid, model, path):
    """An ink map's file inside the run folder: the path state.json records, or, for a folder copied from the
    machine that ran it (a Modal volume, say), the same file at ink/<sid>/<model>/ in this folder."""
    if not path:
        return None
    p = _inside(folder, path)
    if p is None and "/" not in sid + model and ".." not in (sid, model) and sid and model:
        p = _inside(folder, folder / "ink" / sid / model / Path(str(path)).name)
    return p if p is not None and p.is_file() else None


def _thumbs_mode(plan_part, thumbs):
    """(on, why): thumbnails are on by default only for a smoke run or a published labeled segment, whose maps
    may be shown; any other run's maps may be of a scroll whose ink is not published."""
    if thumbs == "off":
        return False, "thumbnails are turned off"
    if thumbs != "on" and plan_part.get("purpose") == "target":
        return False, ("a target run: no thumbnails unless asked for (--thumbs on); maps of target scrolls must "
                       "not be shared")
    if thumbs != "on" and plan_part.get("purpose") != "smoke" and not plan_part.get("labelled_segment"):
        return False, ("this run is not a smoke run and names no published labeled segment, so its maps may be of "
                       "a scroll whose ink is not published: no thumbnails unless asked for (--thumbs on); such maps "
                       "must not be shared")
    plain = vc3d_io.numpy_or_none() is None
    try:
        import tifffile  # noqa: F401
    except ImportError:
        plain = True
    return True, ("Without numpy and tifffile, thumbnails only of TIFFs of 4 MB or less" if plain else None)


def _surface(sid, s, entry, stages, running_stage, method, scores, folder, thumbs_on, seed=None):
    published = autopipe.Run.published(sid)
    qa = s.get("qa") or {}
    failure = (entry or {}).get("failure")
    status = None
    if published:
        status = "published"
    elif failure:
        st = (stages.get(failure["stage"]) or {}).get("status")
        if running_stage == failure["stage"] or st not in ("done", "skipped", "failed", "handoff"):
            status, failure = f"waiting:{failure['stage']}", None
        else:
            status = {"trace": "trace_failed", "qa": "rejected"}.get(failure["stage"], "not_rendered")
    elif s.get("accepted"):
        status = "rendered" if (s.get("render") or {}).get("zarr") else "accepted"
    else:
        status = "waiting:qa"
    tr = s.get("trace") or {}
    fl = s.get("flatten") or {}
    used = fl.get("used")
    side = fl.get("after") if used == "flattened" and isinstance(fl.get("after"), dict) else fl.get("before")
    side = side if isinstance(side, dict) else {}
    rd = s.get("render") or {}
    audit = rd.get("audit") or {}
    pc = rd.get("published_check")
    snap = rd.get("snap") if isinstance(rd.get("snap"), dict) else None
    trim = rd.get("trim") if isinstance(rd.get("trim"), dict) else None
    m = s.get(method) if method else None
    out = {
        "id": sid, "origin": _cut(s.get("origin"), 300), "published": published,
        "seed_index": (entry or {}).get("seed_index", s.get("seed_index")),
        "seed": seed if isinstance(seed, list) and len(seed) == 3 else None,
        "repeat": (entry or {}).get("repeat", s.get("repeat")),
        "status": status, "accepted": s.get("accepted"),
        "reasons": [_cut(x, 300) for x in (qa.get("reasons") or [])[:MAX_REASONS]],
        "warnings": [_cut(x, 300) for x in _warnings(s)[:MAX_REASONS]],
        "failure": {k: _cut(failure.get(k), 400) for k in ("stage", "kind", "reason")} if failure else None,
        "rule_verdict": qa.get("rule_verdict"),
        "trace": {"area_cm2": _num(tr.get("area_cm2")), "valid_fraction": _num(tr.get("valid_fraction")),
                  "grid_rows_cols": tr.get("grid_rows_cols"), **_trace_stop(tr)} if tr else None,
        "method": {"name": method, "summary": {k: (_cut(v, 120) if isinstance(v, str) else v)
                                               for k, v in list(m.items())[:40]
                                               if v is None or isinstance(v, (str, int, float, bool))}}
        if isinstance(m, dict) else None,
        "bench": {k: (s.get("bench") or {}).get(k) for k in ("verdict", "valid")} if s.get("bench") else None,
        "flatten": {"used": used, "passes": fl.get("passes"),
                    "p95_stretch": _num((side.get("abs_log_stretch") or {}).get("p95")),
                    "shear_p95": _num((side.get("shear_deg") or {}).get("p95")),
                    "render_distortion": _cut((fl.get("render_distortion") or {}).get("warning"), 300) or None}
        if fl else None,
        "render": {"exit": rd.get("exit"), "rendered": bool(rd.get("zarr")),
                   "audit_verdict": audit.get("verdict"), "missing_fraction": _num(audit.get("missing_fraction")),
                   "order": rd.get("order"),
                   "published_check": (pc.get("passes") if isinstance(pc, dict) else pc),
                   "published_check_note": _cut((pc or {}).get("skipped") or (pc or {}).get("error"), 300)
                   if isinstance(pc, dict) else None,
                   "trim": {"used": trim.get("used"), "area_share": _num(trim.get("area_share")),
                            "why": _cut(trim.get("why"), 300)} if trim else None,
                   # autopipe writes the snap check's verdict as "passed" (the other checks say "passes")
                   "snap_check": snap["check"].get("passed") if snap and isinstance(snap.get("check"), dict)
                   else None,
                   "refused": _cut(rd.get("refused"), 400) if rd.get("refused") else None,
                   "failure": _cut((rd.get("failure") or {}).get("reason"), 400) if rd.get("failure") else None,
                   "warning": _cut(rd.get("warning"), 300) if rd.get("warning") else None}
        if rd else None,
        "ink": [], "scores": scores.get(sid, [])[:40], "wire": None}
    mesh = _mesh(folder, s) if thumbs_on else None
    if mesh is not None:
        # drawn under the thumbnails' rule; ?m= changes when the mesh is rewritten, as a thumbnail's does
        out["wire"] = (f"wire/{quote(sid, safe='')}.json?m="
                       + ".".join(str(_stat(mesh / f"{a}.tif").st_mtime_ns) for a in "xyz"))
    if out["method"] is not None:
        out["method"]["summary"] = dict(list(out["method"]["summary"].items())[:12])
    for model, mm in list((s.get("ink") or {}).items())[:12]:
        if not isinstance(mm, dict):
            continue
        maps = mm.get("maps") if isinstance(mm.get("maps"), dict) else {}
        comp = {}
        for v, c in (mm.get("comparison") or {}).items():
            if isinstance(c, dict):
                above, mean = c.get("above_threshold") or {}, c.get("mean") or {}
                comp[v] = {"forward_share_above": _num(above.get("forward")),
                           "control_share_above": _num(above.get("control")),
                           "forward_mean": _num(mean.get("forward")), "control_mean": _num(mean.get("control")),
                           "pearson_r": _num(c.get("pearson_r"))}
        thresh = next((_num((x.get("stats") or {}).get("threshold")) for x in maps.values()
                       if isinstance(x, dict) and _num((x.get("stats") or {}).get("threshold")) is not None), None)
        thumbs = None
        if thumbs_on and isinstance(maps.get("f"), dict):
            # ?m= changes when a map is rewritten, so a browser may cache a thumbnail and still see a new map
            fwd = _stat(_map_file(folder, sid, model, maps["f"].get("path")) or "")
            if fwd is not None:
                url = f"thumb/{quote(sid, safe='')}/{quote(model, safe='')}"
                thumbs = {"f": f"{url}/f.png?m={fwd.st_mtime_ns}"}
                rev = _stat(_map_file(folder, sid, model, maps["r"].get("path")) or "") \
                    if isinstance(maps.get("r"), dict) else None
                if rev is not None:
                    thumbs["r"] = f"{url}/r.png?m={fwd.st_mtime_ns}.{rev.st_mtime_ns}"
        out["ink"].append({"model": model, "exit": mm.get("exit"), "variants": sorted(maps),
                           "threshold": thresh, "comparison": comp,
                           "warnings": [_cut(w, 300) for w in (mm.get("warnings") or [])[:MAX_REASONS]]
                           if isinstance(mm.get("warnings"), list) else [],
                           "thumbs": thumbs})
    return out


def _warnings(s):
    try:
        return [w for w in autopipe.Run.warnings(s) if w]
    except Exception:  # noqa: BLE001 - a record of an unexpected shape has no warnings to show
        return []


def _events(folder, tail):
    """The last `tail` lines of events.jsonl (and of events.1.jsonl when that is needed), as {t, stage, msg}."""
    def read(path):
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 96 * 1024))
                raw = fh.read()
        except OSError:
            return []
        lines = raw.decode("utf-8", "replace").split("\n")
        if size > 96 * 1024:
            lines = lines[1:]           # the first line read may be cut
        out = []
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if "event" in e:
                msg = f"Stage {_label(e.get('stage'))}: {e.get('event')}"
                if _num(e.get("seconds")) is not None:
                    msg += f" after {e['seconds']} s"
                if e.get("error"):
                    msg += f": {e['error']}"
                kind = "event"
            else:
                msg, kind = e.get("msg"), "log"
                if e.get("stage") and msg == f"stage {e['stage']}":
                    continue        # Run's own line for the stage event just above it
                if isinstance(msg, str) and tracebudget.GRIDSTORE in msg:
                    # villa's normal-grid cache warning, which runs before 18 Oct 2026 wrote as progress lines
                    # (on villa e0bbb8b, 11998 of a trace log's 12684 lines): counted, not shown
                    out.append({"gridstore": True})
                    continue
            out.append({"t": _num(e.get("t")), "stage": e.get("stage"), "msg": _cut(msg, LINE_KEEP), "kind": kind,
                        "event": e.get("event")})
        return out
    def tail_of(name):
        real = _inside(folder, folder / name)       # a symlink out of the folder is not read
        return _cached(real, "events", read) if real is not None else (None, None)
    lines, st = tail_of(EVENTS)
    present = st is not None
    older, _ = tail_of(EVENTS_OLD)
    allines = list(older or []) + list(lines or [])
    gridstore = sum(1 for e in allines if e.get("gridstore"))
    allines = [e for e in allines if not e.get("gridstore")]
    # each stage's latest attempt to a tenth of a second (state.json keeps its end to the second)
    timing = {}
    for e in allines:
        if e["kind"] != "event" or e["t"] is None or not isinstance(e["stage"], str):
            continue
        if e["event"] == "running":
            timing[e["stage"]] = {"start": e["t"], "end": None}
        elif e["stage"] in timing and timing[e["stage"]]["end"] is None:
            timing[e["stage"]]["end"] = e["t"]
    return {"present": present or bool(older), "lines": allines[-tail:], "truncated": len(allines) > tail,
            "mtime": st.st_mtime if st else None, "timing": timing, "gridstore_left_out": gridstore}


_LOGS = {}


def _tool_log(folder, now):
    """The newest *.log in the run folder (zarr stores left out; the walk is redone at most every 5 s), with its
    last 20 lines."""
    hit = _LOGS.get(str(folder))
    if hit is None or now - hit[0] > 5:
        best = None
        base = len(folder.parts)
        try:
            for root, dirs, files in os.walk(folder):
                depth = len(Path(root).parts) - base
                dirs[:] = [d for d in dirs if not d.endswith(".zarr") and depth < 4]
                for f in files:
                    if f.endswith(".log"):
                        real = _inside(folder, os.path.join(root, f))    # a symlink out of the folder is not read
                        st = _stat(real) if real is not None else None
                        if st is not None and (best is None or st.st_mtime > best[1]):
                            best = (os.path.join(root, f), st.st_mtime, real)
        except OSError:
            best = None
        _LOGS[str(folder)] = hit = (now, best)
    best = hit[1]
    if best is None:
        return None
    try:
        with open(best[2], "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TOOL_LOG_READ))
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = [x for x in raw.replace("\r", "\n").split("\n") if x.strip()]
    if size > TOOL_LOG_READ and lines:
        lines = lines[1:]
    # villa e0bbb8b's tracer log is mostly normal-grid cache warnings: they are counted and left out
    kept = [_cut(x, LINE_KEEP) for x in lines if tracebudget.GRIDSTORE not in x]
    return {"path": os.path.relpath(best[0], folder), "mtime": best[1], "lines": kept[-20:],
            "gridstore_left_out": len(lines) - len(kept)}


def _run_cmd(folder, share):
    """The command that resumes this run: the folder as the kit home sees it (work/autopipe/...), else its path;
    a snapshot names no path outside the kit home."""
    kit = _kit_home()
    try:
        rel = folder.relative_to(kit).as_posix() if kit is not None else None
    except ValueError:
        rel = None
    return f"python -m kit autopipeline run {rel or ('<run folder>' if share else folder)}"


def _banner(phase, cur, plan_part, stages, report, run_cmd, failed_row, handoff_row, share, state_error):
    if phase == "state_error":
        title = ("state.json belongs to another plan" if "another plan" in str(state_error)
                 else "Cannot read state.json")
        return {"tone": "amber", "title": title,
                "detail": f"{_sentence(state_error)} The stages below are not known while it stays so; the monitor "
                          "never changes the file.", "badge": "Error"}
    if phase == "not_started":
        return {"tone": "blue", "title": "Not started",
                "detail": f"The plan is frozen (digest {plan_part.get('short')}...). Start it with {run_cmd}.",
                "badge": "Waiting"}
    if phase in ("running", "quiet", "stopped", "looks_stopped"):
        stage, el, idx = _label(cur["stage"]), cur.get("elapsed_s"), cur.get("index")
        since = cur.get("last_activity_s")
        who = "The run's process" if share else f"Process {cur.get('pid')} on {cur.get('host')}"
        if phase == "running":
            alive = " is alive" if cur.get("alive") else (" (this page cannot check a process on another machine)"
                                                         if not cur.get("same_host") else "")
            return {"tone": "mint", "title": f"Running {stage} for {_dur(el)}",
                    "detail": f"Stage {idx} of {len(autopipe.STAGES)}. {who}{alive}; last update {_dur(since)} ago.",
                    "badge": "Live"}
        if phase == "quiet":
            return {"tone": "amber", "title": f"Running {stage}, quiet for {_dur(since)}",
                    "detail": f"{who} is alive but has written nothing since. A long step can be quiet; see the "
                              "log tail.", "badge": "Quiet"}
        resume = f"Run {run_cmd} to resume: {stage} runs again and finished stages are kept."
        if phase == "stopped":
            how = cur.get("how")
            if how == "crashed":
                return {"tone": "amber", "title": f"Stopped at {stage}: crashed",
                        "detail": f"After about {_dur(el)} the stage raised {_sentence(_first_clause(cur.get('error')))}"
                                  f" That is a fault in the code or the machine, not a stage result. {resume}",
                        "badge": "Stopped"}
            if how == "interrupted":
                return {"tone": "amber", "title": f"Interrupted at {stage}",
                        "detail": f"The run was interrupted ({_first_clause(cur.get('error'), 80)}) after about "
                                  f"{_dur(el)} in {stage}. {resume}", "badge": "Stopped"}
            pid = "" if share else f" (pid {cur.get('pid')})"
            return {"tone": "amber", "title": f"Stopped at {stage}",
                    "detail": f"The process that ran it{pid} is gone and recorded no error. It ran about {_dur(el)} "
                              f"in {stage}; its last sign of life was {_dur(since)} ago. {resume}",
                    "badge": "Stopped"}
        host = "the run's host" if share else f"host {cur.get('host')}"
        return {"tone": "amber", "title": f"Looks stopped at {stage}",
                "detail": f"No update for {_dur(since)} from {host}; this page cannot check a process on another "
                          "machine.", "badge": "No news"}
    if phase == "failed":
        name, kind = _label(failed_row["name"]), failed_row.get("kind")
        first = _cap(_sentence(_first_clause(failed_row.get("error"))))
        if kind == "ours":
            nxt = (f"Decided by AutoPipeline's own rule (ours). Next: check the inputs, or change the plan's settings for "
                   f"{name}, which makes a new plan in a new folder. The full error is on the {name} row below.")
        else:
            nxt = ("A fetch, tool or machine problem (infrastructure). Next: running again may pass, and finished "
                   f"stages are kept: {run_cmd}.")
        return {"tone": "amber", "title": f"Stopped at {name} with an error", "detail": f"{first} {nxt}",
                "badge": "Failed"}
    if phase == "handoff":
        name = _label(handoff_row["name"])
        why = _first_clause(handoff_row.get("why"), 200).split(";")[0].strip() or "this machine cannot run it"
        job = f" and wrote {handoff_row['job']}" if handoff_row.get("job") else ""
        return {"tone": "blue", "title": f"Handed off at {name}",
                "detail": f"{_cap(_sentence(why))} The run stopped here{job}. {name} runs where a registered "
                          "model and a GPU are: on such a machine, set KIT_INK_PYTHON and run this folder again, or "
                          "give the job file to a GPU runner such as this repository's Modal runner "
                          "(a script of the source repository, which starts from the first stage on its own copy). This "
                          "page reads this folder only and contacts no runner.", "badge": "Handed off"}
    if phase == "finished":
        skipped = sum(r["status"] == "skipped" for r in stages)
        ended = sum(r["status"] in FINISHED for r in stages)
        detail = f"{ended} stages ended ({skipped} skipped)."
        tone = "mint"
        if report and report.get("present"):
            if report.get("matches") is True:
                detail += f" Report digest {str(report.get('digest_file'))[:12]}... matches report.json."
            elif report.get("matches") is False:
                detail += " report.json changed after the run wrote it: its digest no longer matches the record."
                tone = "amber"
        return {"tone": tone, "title": "Finished", "detail": detail, "badge": "Finished"}
    if phase == "paused":
        last = next((_label(r["name"]) for r in reversed(stages) if r["status"] in FINISHED), None)
        return {"tone": "blue", "title": f"Paused after {last}" if last else "Paused",
                "detail": f"No stage is marked as running; later stages have not run. {run_cmd} goes on from here.",
                "badge": "Paused"}
    return {"tone": "amber", "title": "Cannot read this run", "detail": "", "badge": "Error"}


def summarize(folder, now=None, host=None, alive=None, stale_s=STALE_S, tail=TAIL, thumbs="auto", share=False):
    """One JSON summary of a run folder for the page (schema SCHEMA). Read-only, and never raises: a folder it
    cannot make sense of gives a summary that says so. now, host and alive (pid -> True, False or None) can be
    given for tests; alive defaults to pid_alive. share (a snapshot or an export): the folder by its name only, and
    no host or process id."""
    folder = Path(folder).resolve()
    now = time.time() if now is None else float(now)
    try:
        return _summary(folder, now, host, alive, stale_s, tail, thumbs, share)
    except Exception as exc:  # noqa: BLE001 - a page that cannot read the run says so instead of failing
        why = f"the monitor could not read this folder's records ({type(exc).__name__})"
        return {"monitor": SCHEMA, "generated": _iso(now), "generated_epoch": round(now, 3),
                "folder": folder.name if share else str(folder), "name": folder.name, "local_only": True,
                "note": NOTE, "plan": {"error": why},
                "state": {"present": False, "mtime": None, "age_s": None, "error": why}, "phase": "error",
                "banner": {"tone": "amber", "title": "Cannot read this run", "detail": _sentence(why),
                           "badge": "Error"},
                "current": None, "stats": {}, "stages": [], "surfaces": [], "surfaces_truncated": False,
                "trace_failures": [], "partial_traces": [], "trace_inflight": None, "trace_runtime": None,
                "trace_preempted": [], "report": None, "scores_file": None,
                "events": {"present": False, "lines": [], "truncated": False}, "tool_log": None,
                "thumbs": {"enabled": False, "why": None}}


def _summary(folder, now, host, alive, stale_s, tail, thumbs, share):
    host = socket.gethostname() if host is None else host
    alive = alive or pid_alive
    out = {"monitor": SCHEMA, "generated": _iso(now), "generated_epoch": round(now, 3),
           "folder": folder.name if share else str(folder), "name": folder.name, "local_only": True, "note": NOTE,
           "plan": None, "state": {"present": False, "mtime": None, "age_s": None, "error": None}, "phase": "error",
           "banner": None, "current": None, "stats": {}, "stages": [], "surfaces": [], "surfaces_truncated": False,
           "trace_failures": [], "partial_traces": [], "trace_inflight": None, "trace_runtime": None,
                "trace_preempted": [], "report": None, "scores_file": None,
           "events": {"present": False, "lines": [], "truncated": False}, "tool_log": None,
           "thumbs": {"enabled": False, "why": None}}
    subs = _subs(folder) + ([(_ELSEWHERE, _by_name), (_CUT_START, _cut_start)] if share else [])
    plan, _, perr = _json_file(folder, "plan.json")
    if not isinstance(plan, dict):
        why = (f"no plan.json in {'this folder' if share else folder}" if perr == "missing"
               else f"plan.json is unreadable: {perr}" if perr else "plan.json is not a JSON object")
        out["plan"] = {"error": why}
        out["banner"] = {"tone": "amber", "title": "Not a run folder", "detail": why, "badge": "Error"}
        return out
    pp = out["plan"] = _plan_part(plan)
    state, sst, serr = _json_file(folder, "state.json")
    state_error = None
    if sst is not None and (serr or not isinstance(state, dict)):
        state_error = serr if serr and "points outside" in serr else \
            f"state.json cannot be read ({serr or 'it is not a JSON object'})"
        state = {}
    elif sst is not None and state.get("plan_digest") not in (None, pp["digest"]):
        state_error = (f"state.json belongs to another plan ({str(state.get('plan_digest'))[:12]}), not this "
                       f"folder's {pp['short']}")
        state = {}
    state = _d(state)
    if sst is not None:
        out["state"] = {"present": True, "mtime": sst.st_mtime, "age_s": round(max(0.0, now - sst.st_mtime), 1),
                        "error": state_error}
    stages = _d(state.get("stages"))

    def status_of(name):
        return _d(stages.get(name)).get("status")
    ev = _events(folder, tail)
    out["events"] = {k: ev[k] for k in ("present", "lines", "truncated", "gridstore_left_out")}
    activity = max([t for t in (sst.st_mtime if sst else None, ev.get("mtime")) if t is not None], default=None)

    running = _d(state.get("running"))
    cur = None
    if state_error:
        phase = "state_error"
    elif running.get("stage") in autopipe.STAGES:
        how = running.get("status")
        ended_mark = how in ENDED_MARKS
        same = running.get("host") == host
        pid = running.get("pid")
        is_alive = alive(pid) if same and not ended_mark else None
        started = _num(running.get("started_epoch")) or _epoch(running.get("started"))
        since = None if activity is None else max(0.0, now - activity)
        if ended_mark or (same and is_alive is False):
            phase = "stopped"
        elif since is not None and since > stale_s:
            phase = "quiet" if is_alive else "looks_stopped"
        else:
            phase = "running"
        # a stage that stopped ends at its mark's end, or at the run's last sign of life: never at "now"
        end = None
        if phase in ("stopped", "looks_stopped") and started is not None:
            end = _num(running.get("ended_epoch")) if ended_mark else None
            if end is None and activity is not None:
                end = max(started, activity)
        elapsed = None
        if started is not None and (end is not None or phase in ("running", "quiet")):
            elapsed = round(max(0.0, (end if end is not None else now) - started), 1)
        cur = {"stage": running["stage"], "index": autopipe.STAGES.index(running["stage"]) + 1,
               "started": running.get("started"), "started_epoch": started, "ended_epoch": end,
               "elapsed_s": elapsed, "how": how if ended_mark else ("gone" if phase == "stopped" else None),
               "error": _cut(running.get("error"), MAX_TEXT) if ended_mark and running.get("error") else None,
               "pid": None if share else pid, "host": None if share else running.get("host"), "same_host": same,
               "alive": is_alive, "last_activity_s": round(since, 1) if since is not None else None}
    elif sst is None:
        phase = "not_started"
    elif any(status_of(n) == "failed" for n in autopipe.STAGES):
        phase = "failed"
    elif any(status_of(n) == "handoff" for n in autopipe.STAGES):
        phase = "handoff"
    elif status_of("report") == "done":
        phase = "finished"
    else:
        phase = "paused"
    out["phase"], out["current"] = phase, cur

    # the stage timeline
    rows = []
    failed_at = next((i for i, n in enumerate(autopipe.STAGES) if status_of(n) == "failed"), None)
    ink_handoff = status_of("ink") == "handoff"
    for i, name in enumerate(autopipe.STAGES):
        rec = _d(stages.get(name))
        row = {"name": name, "index": i + 1, "status": "waiting", "started": None, "ended": None,
               "started_epoch": None, "ended_epoch": None, "seconds": None, "summary": None, "error": None,
               "kind": None, "why": None}
        if cur and cur["stage"] == name:
            if phase in ("running", "quiet"):
                summary = "running now"
            elif phase == "stopped":
                verb = cur["how"] if cur["how"] in ENDED_MARKS else "stopped"
                summary = (f"{verb} after about {_dur(cur['elapsed_s'])}"
                           + (f": {cur['error']}" if cur["error"] else
                              f"; no process is running it, last sign of life {_dur(cur['last_activity_s'])} ago"))
            else:
                summary = (f"no news for {_dur(cur['last_activity_s'])}, after at least {_dur(cur['elapsed_s'])} "
                           "in this stage")
            row.update(status={"running": "running", "quiet": "quiet", "stopped": "stopped",
                               "looks_stopped": "unknown"}[phase], started=cur["started"],
                       started_epoch=cur["started_epoch"], ended_epoch=cur["ended_epoch"],
                       ended=_iso(cur["ended_epoch"]) if cur["ended_epoch"] is not None else None,
                       seconds=cur["elapsed_s"], summary=summary)
        elif isinstance(rec.get("status"), str) and rec.get("status"):
            end = _epoch(rec.get("at"))
            secs = _num(rec.get("seconds"))
            start = end - secs if end is not None and secs is not None else end
            tm = ev["timing"].get(name) or {}
            if end is not None and tm.get("end") is not None and -0.5 <= tm["end"] - end < 1.5:
                start, end = tm["start"], tm["end"]       # the same attempt, timed to 0.1 s by events.jsonl
            r = _d(rec.get("record"))
            row.update(status=rec["status"], ended=rec.get("at"), ended_epoch=end, seconds=secs,
                       started_epoch=start,
                       error=_cut(rec.get("error"), MAX_TEXT) if rec.get("error") else None, kind=rec.get("kind"),
                       why=_cut(r.get("why"), MAX_TEXT) if r.get("why") else None)
            if rec["status"] == "handoff" and r.get("job"):
                row["job"] = _cut(Path(str(r["job"])).name, 120)
            row["started"] = _iso(row["started_epoch"]) if row["started_epoch"] is not None else None
            try:
                row["summary"] = _stage_summary(name, rec)
            except Exception:  # noqa: BLE001 - a record of an unexpected shape gives no summary, not a broken page
                row["summary"] = None
        elif phase == "failed" and failed_at is not None and i > failed_at:
            row["status"] = "not_reached"
        elif name == "score" and ink_handoff:
            row.update(status="waiting_runner", summary="the runner the Ink stage was handed to scores it")
        rows.append(row)
    out["stages"] = rows

    # surfaces
    surfaces = _d(state.get("surfaces"))
    try:
        entries = {e["sid"]: e for e in autopipe.trace_entries(state)}
    except Exception:  # noqa: BLE001 - an older or partial state: surfaces are still listed by name
        entries = {}
    order = list(entries) + sorted(k for k in surfaces if k not in entries)
    out["surfaces_truncated"] = len(order) > MAX_SURFACES
    order = order[:MAX_SURFACES]
    pp_thumbs, why = _thumbs_mode(pp, thumbs)
    out["thumbs"] = {"enabled": pp_thumbs, "why": why}
    scores, out["scores_file"] = _scores(folder, state)
    method = pp.get("trace_method")
    running_stage = cur["stage"] if cur and phase in ("running", "quiet") else None
    planned = state.get("planned_traces") if isinstance(state.get("planned_traces"), list) else []
    seeds = {p.get("sid"): p.get("seed") for p in planned if isinstance(p, dict) and isinstance(p.get("sid"), str)}
    for sid in order:
        s = _d(surfaces.get(sid))
        try:
            out["surfaces"].append(_surface(sid, s, entries.get(sid), stages, running_stage, method, scores,
                                            folder, pp_thumbs, seeds.get(sid)))
        except Exception as exc:  # noqa: BLE001
            out["surfaces"].append({"id": sid, "status": "unreadable", "origin": None, "published": False,
                                    "reasons": [], "warnings": [], "ink": [], "scores": [],
                                    "failure": {"stage": None, "kind": None,
                                                "reason": f"record not readable here: {type(exc).__name__}"}})
    failures = _d(state.get("trace_failures"))
    out["trace_failures"] = [{"id": sid, "seed": f.get("seed"), "kind": f.get("kind"),
                              "reason": _cut(f.get("reason"), 400), **_trace_stop(f)}
                             for sid, f in list(failures.items())[:MAX_SURFACES] if isinstance(f, dict)]
    # trace.budget (kit/tracebudget.py): partial surfaces, the trace in flight with its budget, and the runtime
    partials = _d(state.get("partial_traces"))
    out["partial_traces"] = [{"id": sid, "kind": p.get("kind"), "reason": _cut(p.get("reason"), 200),
                              "generations_done": p.get("generations_done"),
                              "generations_planned": p.get("generations_planned"),
                              "area_cm2": _num(p.get("area_cm2")), "budget_s": _num(p.get("budget_s"))}
                             for sid, p in list(partials.items())[:MAX_SURFACES] if isinstance(p, dict)]
    inflight = _d(state.get("trace_inflight"))
    out["trace_inflight"] = {"id": inflight.get("sid"), "started": inflight.get("started"),
                             "budget_s": _num(_d(inflight.get("budget")).get("budget_s")),
                             "time_limit_s": _num(_d(inflight.get("budget")).get("time_limit_s")),
                             "hard_timeout_s": _num(_d(inflight.get("budget")).get("hard_timeout_s")),
                             "progress": _trace_progress(out["events"]["lines"])} \
        if inflight.get("sid") else None
    rt = _d(state.get("trace_runtime"))
    out["trace_runtime"] = {"class": rt.get("class"), "grid_cache_bytes": _num(rt.get("grid_cache_bytes")),
                            "grid_cache_entries": _num(rt.get("grid_cache_entries")),
                            "grid_cache_from": _d(rt.get("grid_cache_from")) or None,
                            "memory_bytes": _num(rt.get("memory_bytes")), "time_limit": rt.get("time_limit"),
                            "villa_rev": _cut(_d(rt.get("villa")).get("rev"), 64),
                            "villa_patches": _cut(_d(rt.get("villa")).get("patches"), 200),
                            "attempts": len(state.get("trace_runtimes") or []) or None,
                            "warning": _cut(rt.get("warning"), 400)} if rt else None
    pre = _d(state.get("trace_preempted"))
    out["trace_preempted"] = [{"id": sid, "kept": p.get("kept"), "whole": p.get("whole"), "kind": p.get("kind"),
                               "generations_done": p.get("generations_done"), "why": _cut(p.get("why"), 200)}
                              for sid, p in list(pre.items())[:MAX_SURFACES] if isinstance(p, dict)]

    # report
    rep, rst, rerr = _json_file(folder, "report.json")
    if rst is not None:
        recorded = _d(_d(stages.get("report")).get("record")).get("digest")
        dfile = _sha256(folder, "report.json") if not rerr or "points outside" not in rerr else None
        out["report"] = {"present": True, "stages": rep.get("stages") if isinstance(rep, dict) else None,
                         "digest_recorded": recorded, "digest_file": dfile,
                         "matches": (dfile == recorded) if recorded else None, "error": rerr}
    else:
        out["report"] = {"present": False}

    # numbers for the cards
    surfaces = {k: v for k, v in surfaces.items() if isinstance(v, dict)}
    traced = [k for k in surfaces if not autopipe.Run.published(k)]
    finished_rows = [r for r in rows if r["status"] in FINISHED]
    out["stats"] = {
        "stages_total": len(autopipe.STAGES), "stages_finished": len(finished_rows),
        "stages_skipped": sum(r["status"] == "skipped" for r in rows),
        "surfaces_planned": len(planned) if isinstance(state.get("planned_traces"), list) else None,
        "surfaces_traced": len(traced),
        "surfaces_accepted": sum(1 for k in traced if surfaces[k].get("accepted")),
        "surfaces_rejected": sum(1 for k in traced if "qa" in surfaces[k] and not surfaces[k].get("accepted")),
        "published_segments": sum(1 for k in surfaces if autopipe.Run.published(k)),
        "trace_failures": len(failures),
        "surfaces_partial": len(partials),
        "warnings": sum(len(_warnings(s)) for s in surfaces.values()),
        "run_seconds": round(sum(r["seconds"] or 0 for r in rows), 1) if rows else None}
    out["tool_log"] = _tool_log(folder, now)
    # paths in records and log lines as <run> and ~ (the page names the folder once; a snapshot not at all)
    out = _redact(out, subs, skip=("folder",))
    for line in out["events"]["lines"]:
        line["msg"] = _cut(line["msg"], LINE_SHOW)
    if out["tool_log"]:
        out["tool_log"]["lines"] = [_cut(x, LINE_SHOW) for x in out["tool_log"]["lines"]]
    out["kit_home"] = "<kit>" if any(short == "<kit>" for _, short in subs) else None
    rows, cur = out["stages"], out["current"]
    failed_row = next((r for r in rows if r["status"] == "failed"), None)
    handoff_row = next((r for r in rows if r["status"] == "handoff"), None)
    out["banner"] = _banner(phase, cur, pp, rows, out["report"], _run_cmd(folder, share), failed_row, handoff_row,
                            share, out["state"].get("error"))
    return out


# ---------------------------------------------------------------- thumbnails

_THUMBS = {}
_THUMBS_LOCK = threading.Lock()
_DECODE_LOCK = threading.Lock()   # one map decodes at a time, so a page full of thumbnails cannot stack them up


def _plane(path, side=THUMB_SIDE):
    """A map's first plane, strided down to at most `side` pixels a side, as a vc3d_io Raster. With numpy and
    tifffile a map that decodes to at most THUMB_MAX_DECODED bytes is decoded, a larger uncompressed one is read
    through a memory map (only the rows the thumbnail takes), and a larger compressed one gets none."""
    size = path.stat().st_size
    np = vc3d_io.numpy_or_none()
    try:
        import tifffile
    except ImportError:
        tifffile = None
    if np is not None and tifffile is not None:
        with _DECODE_LOCK:
            with tifffile.TiffFile(str(path)) as tf:
                page = tf.pages[0]
                nbytes = int(np.prod([int(x) for x in page.shape], dtype=np.int64)) * np.dtype(page.dtype).itemsize
                if nbytes <= THUMB_MAX_DECODED:
                    a = page.asarray()
                elif page.is_memmappable:
                    a = None
                else:
                    raise MonitorError(f"the map decodes to {nbytes >> 20} MB, more than the "
                                       f"{THUMB_MAX_DECODED >> 20} MB a thumbnail may use, and is compressed")
            if a is None:
                a = tifffile.memmap(str(path), page=0, mode="r")
            a = np.squeeze(a)
            if a.ndim == 3 and a.shape[-1] <= 4:
                a = a[..., 0]          # samples (gray and alpha, or color): the first
            while a.ndim > 2:
                a = a[0]
            if a.ndim != 2:
                raise MonitorError("not an image")
            step = max(1, -(-max(a.shape) // side))
            small = np.array(a[::step, ::step], dtype=np.float32)
            del a
        return vc3d_io.raster_from_numpy(small)
    if size > THUMB_MAX_PLAIN:
        raise MonitorError("the map is over 4 MB and numpy or tifffile is missing")
    r = vc3d_io.read_tiff(path)
    step = max(1, -(-max(r.h, r.w) // side))
    return vc3d_io.downsample(r, step, "nearest")


# Ink maps' colors: dark umber through copper to pale papyrus. Each stop sits at its own CIE L* between the two ends,
# so lightness rises evenly with the score and a brighter pixel is a higher score in either theme.
INK_STOPS = ((0.0, (22, 17, 15)), (0.133, (62, 36, 22)), (0.335, (124, 68, 32)), (0.581, (190, 120, 56)),
             (0.812, (232, 182, 112)), (1.0, (250, 236, 206)))


def _ink_color(t):
    """The (r, g, b) of INK_STOPS at t in 0 to 1."""
    t = min(1.0, max(0.0, t))
    for (t0, c0), (t1, c1) in zip(INK_STOPS, INK_STOPS[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(int(a + (b - a) * f + 0.5) for a, b in zip(c0, c1))
    return INK_STOPS[-1][1]


INK_LUT = tuple(_ink_color(i / 255) for i in range(256))


def ink_rgba(raster, lo=None, hi=None, side=None, lo_pct=1.0, hi_pct=99.0):
    """(h, w, RGBA bytes, (lo, hi)) of an ink map as a picture. It is cropped to its on-surface pixels (non-zero and
    finite; VC3D marks off-surface 0), which are stretched between lo and hi (by default their 1st and 99th
    percentile; a uniform map shows the middle color) and colored with INK_LUT; off-surface pixels are clear. A
    map whose longer side is under `side` is enlarged to it bilinearly, among on-surface pixels only, so a small map
    reads as a smooth picture rather than blocks; its edge fades out with the share of on-surface neighbors."""
    h, w, vals = raster.h, raster.w, raster.data
    ok = [v == v and v != 0 and abs(v) != float("inf") for v in vals]
    rows = [r for r in range(h) if any(ok[r * w:(r + 1) * w])]
    if not rows:
        return h, w, bytes(4 * h * w), (0.0, 0.0)
    cols = [c for c in range(w) if any(ok[r * w + c] for r in rows)]
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    if lo is None or hi is None:
        sample = sorted(v for v, k in zip(vals, ok) if k)
        lo = vc3d_io.percentile(sample, lo_pct) if lo is None else lo
        hi = vc3d_io.percentile(sample, hi_pct) if hi is None else hi
    span = hi - lo
    ch, cw = r1 - r0, c1 - c0
    t = [[((vals[r * w + c] - lo) / span if span else 0.5) if ok[r * w + c] else None for c in range(c0, c1)]
         for r in range(r0, r1)]
    f = max(1.0, (side or 0) / max(ch, cw))
    oh, ow = max(1, round(ch * f)), max(1, round(cw * f))
    out = bytearray(4 * oh * ow)
    i = 0
    for y in range(oh):
        sy = min(max((y + 0.5) * ch / oh - 0.5, 0.0), ch - 1.0)
        ya = int(sy)
        yb, fy = min(ya + 1, ch - 1), sy - ya
        for x in range(ow):
            sx = min(max((x + 0.5) * cw / ow - 0.5, 0.0), cw - 1.0)
            xa = int(sx)
            xb, fx = min(xa + 1, cw - 1), sx - xa
            tot = wsum = 0.0
            for yy, wy in ((ya, 1 - fy), (yb, fy)):
                for xx, wx in ((xa, 1 - fx), (xb, fx)):
                    v = t[yy][xx]
                    if v is not None and wy * wx:
                        tot += v * wy * wx
                        wsum += wy * wx
            if wsum:
                r, g, b = INK_LUT[min(255, max(0, int(tot / wsum * 255 + 0.5)))]
                out[i:i + 4] = bytes((r, g, b, min(255, int(wsum * 255 + 0.5))))
            i += 4
    return oh, ow, bytes(out), (lo, hi)


def _png_rgba(h, w, data):
    """An 8-bit RGBA PNG of row-major samples (vc3d_io.png_bytes writes gray and RGB)."""
    raw = b"".join(b"\x00" + bytes(data[r * 4 * w:(r + 1) * 4 * w]) for r in range(h))

    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def thumb_png(path, scale=None):
    """(PNG bytes, (lo, hi)) of an ink map: the first plane, cropped to its on-surface pixels, in the ink colors
    with off-surface clear, at most THUMB_SIDE pixels a side and a small map enlarged smoothly to it (ink_rgba). Without scale it is stretched between the 1st and 99th percentile of its non-zero values; a
    control map is drawn on its forward map's scale so it is never stretched to look like ink. Cached by file and
    scale."""
    path = Path(path)
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size, tuple(scale) if scale else None)
    with _THUMBS_LOCK:
        hit = _THUMBS.get(key)
    if hit is not None:
        return hit
    r = _plane(path)
    lo, hi = scale if scale else (None, None)
    h, w, data, used = ink_rgba(r, lo=lo, hi=hi, side=THUMB_SIDE)
    got = (_png_rgba(h, w, data), tuple(used))
    with _THUMBS_LOCK:
        if len(_THUMBS) >= 64:
            _THUMBS.pop(next(iter(_THUMBS)))
        _THUMBS[key] = got
    return got


def _thumb_for(folder, state, sid, model, variant):
    """The PNG of surface sid's map `variant` (f or r) from `model`, found only through state.json and only inside
    the folder, or None."""
    if variant not in ("f", "r"):
        return None
    s = _d(state.get("surfaces")).get(sid)
    if not isinstance(s, dict):
        return None
    m = _d(s.get("ink")).get(model)
    maps = (m or {}).get("maps") if isinstance(m, dict) else None
    if not isinstance(maps, dict) or not isinstance(maps.get("f"), dict) or not isinstance(maps.get(variant), dict):
        return None
    fwd = _map_file(folder, sid, model, maps["f"].get("path"))
    path = fwd if variant == "f" else _map_file(folder, sid, model, maps[variant].get("path"))
    if fwd is None or path is None:
        return None
    try:
        png, scale = thumb_png(fwd)
        if variant != "f":
            png, _ = thumb_png(path, scale=scale)
        return png
    except Exception:  # noqa: BLE001 - an unreadable map has no thumbnail
        return None



# ---------------------------------------------------------------- wireframes

WIRE_SIDE = 64              # a wireframe's grid: at most this many rows and columns of the traced mesh
WIRE_Q = 16000              # coordinates as int16 in [-WIRE_Q, WIRE_Q] about the mesh's center
WIRE_HOLE = -32768          # a point VC3D's loader would not load (x == -1, z <= 0, or not finite)
WIRE_SNAPSHOT_MAX = 24      # a snapshot embeds the wireframes of at most this many surfaces
_WIRES = {}


def _mesh(folder, s):
    """The traced tifxyz folder state.json names for a surface, when it and its x, y and z grids lie inside the run
    folder, else None. A published segment's mesh in the kit home's cache is not read."""
    path = s.get("surface") if isinstance(s, dict) else None
    p = _inside(folder, path) if isinstance(path, str) and path else None
    if p is None or not vc3d_io.is_tifxyz(p) or any(_inside(folder, p / f"{a}.tif") is None for a in "xyz"):
        return None
    return p


def wire_data(mesh):
    """A tifxyz surface as the page's wireframe: its x, y and z grids strided to at most WIRE_SIDE rows and columns,
    centered on the valid points and scaled so the longest side of their box spans 2 * WIRE_Q, as little-endian
    int16 (x, y, z) triples in base64, row by row, with holes as WIRE_HOLE. Also the grid's size, the number of
    valid points and the box's extent in voxels. Cached by the grids' mtimes and sizes."""
    mesh = Path(mesh)
    sts = [(mesh / f"{a}.tif").stat() for a in "xyz"]
    key = (str(mesh), tuple((st.st_mtime_ns, st.st_size) for st in sts))
    with _THUMBS_LOCK:
        hit = _WIRES.get(key)
    if hit is not None:
        return hit
    grids = [_plane(mesh / f"{a}.tif", WIRE_SIDE) for a in "xyz"]
    if len({(g.h, g.w) for g in grids}) != 1:
        raise MonitorError("the mesh's x, y and z grids differ in size")
    rows, cols = grids[0].h, grids[0].w
    X, Y, Z = (g.floats() for g in grids)
    ok = [x != -1 and z > 0 and math.isfinite(x) and math.isfinite(y) and math.isfinite(z)
          for x, y, z in zip(X, Y, Z)]
    if not any(ok):
        raise MonitorError("the mesh has no valid point")
    lo = [min(v for v, k in zip(axis, ok) if k) for axis in (X, Y, Z)]
    hi = [max(v for v, k in zip(axis, ok) if k) for axis in (X, Y, Z)]
    centre = [(a + b) / 2 for a, b in zip(lo, hi)]
    span = max(b - a for a, b in zip(lo, hi)) or 1.0
    q = array.array("h", [WIRE_HOLE]) * (3 * rows * cols)
    for i, k in enumerate(ok):
        if k:
            for j, axis in enumerate((X, Y, Z)):
                q[3 * i + j] = int(round((axis[i] - centre[j]) / span * 2 * WIRE_Q))
    if sys.byteorder != "little":
        q.byteswap()
    got = {"rows": rows, "cols": cols, "unit": WIRE_Q, "hole": WIRE_HOLE,
           "q": base64.b64encode(q.tobytes()).decode("ascii"), "valid": sum(ok),
           "extent": [round(b - a, 1) for a, b in zip(lo, hi)]}
    with _THUMBS_LOCK:
        if len(_WIRES) >= 64:
            _WIRES.pop(next(iter(_WIRES)))
        _WIRES[key] = got
    return got


def _wire_for(folder, state, sid):
    """The wireframe of surface sid's traced mesh, found only through state.json and only inside the folder, or
    None."""
    mesh = _mesh(folder, _d(_d(state.get("surfaces")).get(sid)))
    if mesh is None:
        return None
    try:
        return wire_data(mesh)
    except Exception:  # noqa: BLE001 - an unreadable mesh has no wireframe
        return None


# ---------------------------------------------------------------- terminal view

RAMP = " .:-=+*#%@"     # Paul Bourke's ten-level character ramp, dark to bright
BAYER4 = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)   # the 4 x 4 ordered-dither matrix, row by row
UPPER, LOWER = "\u2580", "\u2584"   # half blocks: two pixels in one character cell
TEXT_SURFACES = 8       # the text view draws the maps of this many surfaces at most
STATUS_TEXT = {"done": "Done", "running": "Running", "skipped": "Skipped", "handoff": "Handed off",
               "waiting_runner": "On the runner", "failed": "Failed", "stopped": "Stopped", "quiet": "Quiet",
               "unknown": "No news", "waiting": "Not run yet", "not_reached": "Not reached"}
SURFACE_TEXT = {"rendered": "Accepted", "accepted": "Accepted", "published": "Published, checked not gated",
                "rejected": "Rejected", "trace_failed": "Trace failed", "not_rendered": "Accepted, not rendered",
                "unreadable": "Unreadable"}


def _stretch(raster):
    """(lo, hi): the 1st and 99th percentile of a map's non-zero samples, the thumbnails' stretch."""
    sample = sorted(v for v in vc3d_io.sample_values(raster.data) if v == v and v != 0)
    if not sample:
        return 0.0, 0.0
    return vc3d_io.percentile(sample, 1.0), vc3d_io.percentile(sample, 99.0)


def _cells(raster, rows, cols, lo, hi):
    """rows x cols block means of a map, stretched to 0 to 1 between lo and hi over its non-zero samples; None for a
    block of zeros only (VC3D's off-surface)."""
    data, h, w = raster.data, raster.h, raster.w
    span = hi - lo
    out = []
    for r in range(rows):
        r0 = r * h // rows
        r1 = max(r0 + 1, (r + 1) * h // rows)
        line = []
        for c in range(cols):
            c0 = c * w // cols
            c1 = max(c0 + 1, (c + 1) * w // cols)
            tot, n = 0.0, 0
            for rr in range(r0, r1):
                for v in data[rr * w + c0:rr * w + c1]:
                    if v != 0 and v == v:
                        tot += v
                        n += 1
            if not n:
                line.append(None)
                continue
            t = (tot / n - lo) / span if span else 0.5   # a uniform map shows mid gray, as its thumbnail does
            line.append(min(1.0, max(0.0, t)))
        out.append(line)
    return out


def _grey(t):
    return 232 + int(t * 23 + 0.5)   # the 24 grays of the 256-color palette


def ascii_map(raster, width=40, scale=None, dither=False, color=False, ramp=RAMP):
    """(lines, (lo, hi)): an ink map drawn in characters, at most `width` wide, each a block mean stretched between
    the 1st and 99th percentile of the map's non-zero values, or on `scale` (a control on its forward map's scale,
    so it is never stretched to look like ink). Off-surface blocks are blank. Plain: one character per cell from
    `ramp`, a cell about twice as tall as wide; dither adds the 4 x 4 ordered (Bayer) threshold before rounding.
    color: two pixels per cell, the upper and lower half block in the 256-color palette's grays (ANSI escapes)."""
    lo, hi = scale if scale else _stretch(raster)
    cols = max(1, min(int(width), raster.w))
    if color:
        rows = max(2, round(raster.h / raster.w * cols))
        rows += rows % 2
        cells = _cells(raster, rows, cols, lo, hi)
        lines = []
        for top, bottom in zip(cells[0::2], cells[1::2]):
            parts = []
            for a, b in zip(top, bottom):
                if a is None and b is None:
                    parts.append("\x1b[0m ")
                elif b is None:
                    parts.append(f"\x1b[0m\x1b[38;5;{_grey(a)}m{UPPER}")
                elif a is None:
                    parts.append(f"\x1b[0m\x1b[38;5;{_grey(b)}m{LOWER}")
                else:
                    parts.append(f"\x1b[38;5;{_grey(a)};48;5;{_grey(b)}m{UPPER}")
            lines.append("".join(parts) + "\x1b[0m")
        return lines, (lo, hi)
    rows = max(1, round(raster.h / raster.w * cols / 2))
    top = len(ramp) - 1
    lines = []
    for r, line in enumerate(_cells(raster, rows, cols, lo, hi)):
        chars = []
        for c, t in enumerate(line):
            if t is None:
                chars.append(" ")
                continue
            bias = (BAYER4[(r % 4) * 4 + c % 4] + 0.5) / 16 if dither else 0.5
            chars.append(ramp[min(top, max(0, int(math.floor(t * top + bias))))])
        lines.append("".join(chars))
    return lines, (lo, hi)


def _map_rasters(folder, state, sid, model):
    """(forward, reversed or None) of surface sid's maps from `model` as rasters, found only through state.json and
    only inside the folder, or None."""
    m = _d(_d(_d(state.get("surfaces")).get(sid)).get("ink")).get(model)
    maps = m.get("maps") if isinstance(m, dict) else None
    if not isinstance(maps, dict) or not isinstance(maps.get("f"), dict):
        return None
    fwd = _map_file(folder, sid, model, maps["f"].get("path"))
    rev = _map_file(folder, sid, model, maps["r"].get("path")) if isinstance(maps.get("r"), dict) else None
    if fwd is None:
        return None
    try:
        f = _plane(fwd)
    except Exception:  # noqa: BLE001 - an unreadable map is not drawn
        return None
    try:
        r = _plane(rev) if rev is not None else None
    except Exception:  # noqa: BLE001
        r = None
    return f, r


def _fmt(v, d=3):
    return "N/A" if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) else f"{v:.{d}f}"


def text_view(folder, width=40, color=False, dither=False, **kw):
    """The run as text for a terminal: the banner, each stage with its status and time, each surface with its checks
    and scores, and, when thumbnails are on (the page's rule: smoke runs and published labeled segments, or
    --thumbs on), each ink map beside its reversed control on the forward map's scale, drawn by ascii_map. Reads
    what summarize() reads and writes nothing. Every map and score is model output, not a reading."""
    folder = Path(folder).resolve()
    S = summarize(folder, **kw)
    state, _, _ = _json_file(folder, "state.json")
    state = _d(state)
    pp = S.get("plan") or {}
    out = []
    head = ["AP Monitor", S.get("name") or "run"]
    head += [x for x in (pp.get("short") and f"Plan {pp['short']}", pp.get("sample"),
                         pp.get("volume") and f"Volume {pp['volume']}") if x]
    out.append(" | ".join(head))
    b = S.get("banner") or {}
    if b.get("title"):
        out.append(b["title"] + (f" ({b['badge']})" if b.get("badge") else ""))
    if b.get("detail"):
        out.append("  " + b["detail"])
    rows = S.get("stages") or []
    if rows:
        out += ["", "Stages"]
        for r in rows:
            secs = "" if r.get("seconds") is None else _dur(r["seconds"])
            line = f"  {_label(r['name']):<10} {STATUS_TEXT.get(r['status'], r['status']):<13} {secs:>14}"
            note = r.get("error") or r.get("why")
            out.append(line.rstrip() + (f"  {_cut(note, 160)}" if note else ""))
    surfs = S.get("surfaces") or []
    out += ["", f"Surfaces: {len(surfs)}" + (" (first 300)" if S.get("surfaces_truncated") else "")]
    drawn = skipped = 0
    for s in surfs:
        label = SURFACE_TEXT.get(s.get("status")) or (f"Waiting for {_label(s['status'][8:])}"
                                                      if str(s.get("status")).startswith("waiting:") else s.get("status"))
        tr = s.get("trace") or {}
        bits = [x for x in (tr.get("area_cm2") is not None and f"{_fmt(tr['area_cm2'])} cm²",
                            tr.get("valid_fraction") is not None and f"{100 * tr['valid_fraction']:.1f}% valid") if x]
        out.append(f"  {s.get('id')}  {label}" + (f"  trace {', '.join(bits)}" if bits else ""))
        for why in (s.get("reasons") or [])[:3]:
            out.append(f"    QA: {why}")
        for sc in s.get("scores") or []:
            if sc.get("error") or sc.get("scorable") is False:
                continue
            out.append(f"    {sc.get('model') or 'All models'}{' | ' + sc['scope'] if sc.get('scope') else ''}: "
                       f"forward AUC {_fmt(sc.get('forward_auc'))}, reversed control {_fmt(sc.get('control_auc'))}")
        for m in s.get("ink") or []:
            if not m.get("thumbs"):
                continue
            if drawn >= TEXT_SURFACES:
                skipped += 1
                continue
            got = _map_rasters(folder, state, s["id"], m["model"])
            if got is None:
                continue
            f_lines, scale = ascii_map(got[0], width, dither=dither, color=color)
            r_lines = ascii_map(got[1], width, scale=scale, dither=dither, color=color)[0] if got[1] else []
            cols = max(1, min(int(width), got[0].w))
            out.append(f"    {m['model']}: forward" + " " * max(1, cols - len(m["model"]) - 7)
                       + ("reversed control, same scale" if r_lines else ""))
            for i, fl in enumerate(f_lines):
                out.append("    " + fl + ("  " + r_lines[i] if i < len(r_lines) else ""))
            drawn += 1
    if skipped:
        out.append(f"  The maps of {skipped} more are not drawn here; the page shows them.")
    t = S.get("thumbs") or {}
    if any(s.get("ink") for s in surfs) and not t.get("enabled"):
        out.append(f"  No maps drawn: {t.get('why') or 'turned off'}")
    out += ["", NOTE]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- the page

_ICONS = {
    "logo": '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round"><path d="M12 12c0-1 .9-1.6 1.8-1.3 1.4.4 1.7 2.3.8 3.4-1.4 1.6-4 1.3-5.1-.4-1.5-2.3'
            '-.3-5.3 2.2-6.2 3.3-1.2 6.7 1 7.2 4.4.6 4.1-2.6 7.7-6.7 7.6-4.8-.1-8.2-4.6-7.4-9.3"/></svg>',
    "mint": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/>'
            '<path d="M12 7v5l3 2"/></svg>',
    "amber": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4"/>'
             '<path d="M12 17h.01"/></svg>',
    "blue": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01"/>'
            '<path d="M11 12h1v5h1"/></svg>',
    "done": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3z"/>'
            '<path d="m8.5 12 2.5 2.5 4.5-5"/></svg>',
    "export": '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/>'
              '<path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/></svg>',
}

_DARK = {"bg": "#0b0c0c", "card": "#101211", "inset": "#080909", "stroke": "rgba(232,230,223,.16)",
         "text": "#e8e6df", "text2": "#8f8d86", "mint": "#e8e6df", "amber": "#ff6a2b", "blue": "#7ea6ff",
         "violet": "#c3a6ff", "grid": "rgba(232,230,223,.07)", "idle": "rgba(232,230,223,.06)",
         "mint-rgb": "232,230,223", "amber-rgb": "255,106,43", "blue-rgb": "126,166,255",
         "grey-rgb": "143,141,134", "violet-rgb": "195,166,255", "scheme": "dark"}
_LIGHT = {"bg": "#e7e6e0", "card": "#efeee9", "inset": "#e1e0d9", "stroke": "rgba(17,17,17,.20)",
          "text": "#111111", "text2": "#5f5e58", "mint": "#111111", "amber": "#d9480f", "blue": "#2552c9",
          "violet": "#6a46c2", "grid": "rgba(17,17,17,.08)", "idle": "rgba(17,17,17,.06)",
          "mint-rgb": "17,17,17", "amber-rgb": "217,72,15", "blue-rgb": "37,82,201", "grey-rgb": "95,94,88",
          "violet-rgb": "106,70,194", "scheme": "light"}


def _tokens(t):
    return "color-scheme:" + t["scheme"] + ";" + "".join(f"--{k}:{v};" for k, v in t.items() if k != "scheme")


# One screen (decided 23 Oct 2026: everything on one screen with no page scroll, futuristic but not cluttered): on a
# laptop the page is a fixed grid of panels the height of the window, and only a panel's own list scrolls; below
# 1000 px wide or 600 px tall it falls back to one column that scrolls. Monochrome ink on paper (or paper on ink),
# hairlines and monospace, with one signal color for what needs a person: --mint is the ink, --amber the signal.
_CSS = """
:root{%LIGHT%}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){%DARK%}}
:root[data-theme=light]{%LIGHT%}
:root[data-theme=dark]{%DARK%}
*{box-sizing:border-box}
/* --fz scales every font size; smaller screens than a 14 inch MacBook step it down */
:root{--fz:1}     /* stepped down for small screens at the end of this sheet */
html,body{margin:0;padding:0;background:var(--bg);color:var(--text)}
body{font:calc(13px*var(--fz))/1.45 ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
 -webkit-text-size-adjust:100%;overflow-x:hidden}
.wrap{height:100vh;height:100dvh;display:grid;gap:10px;padding:12px 16px;
 grid-template-columns:minmax(0,1fr);grid-template-rows:auto auto minmax(0,1.7fr) minmax(0,1fr) auto}
.num{font-variant-numeric:tabular-nums}
.mono{font-family:inherit}
.label{font-size:calc(11.5px*var(--fz));letter-spacing:.06em;color:var(--text2)}
.sec{color:var(--text2)}
.fine{font-size:calc(11.5px*var(--fz));color:var(--text2)}
.wrapany{overflow-wrap:anywhere;word-break:break-word}
.row{display:flex;align-items:center;gap:10px;min-width:0}
.spacer{flex:1 1 auto}
.hidden{display:none !important}
.ell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
/* header: brand and run on the left, the run's numbers on the right */
header.top{display:flex;align-items:stretch;gap:14px;min-width:0;border-bottom:1px solid var(--text);padding-bottom:8px}
.brand{font-size:calc(16px*var(--fz));font-weight:700;letter-spacing:.04em;white-space:nowrap}
.brand .short{display:none}
.brand .sl{color:var(--text2);font-weight:400;margin:0 .35em}
.idblock{display:flex;flex-direction:column;justify-content:space-between;min-width:0;flex:1 1 auto}
.meta{display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-width:0;font-size:calc(11.5px*var(--fz));color:var(--text2)}
.meta h1{margin:0;font-size:inherit;font-weight:600;color:var(--text);max-width:28ch}
.capsule{display:contents}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:calc(11.5px*var(--fz));padding:1px 6px;border:1px solid var(--stroke);
 white-space:nowrap;color:var(--text2)}
.pill.mint{color:var(--mint)}.pill.amber{color:var(--amber);border-color:rgba(var(--amber-rgb),.5)}
.pill.blue{color:var(--blue);border-color:rgba(var(--blue-rgb),.5)}.pill.grey{color:var(--text2)}
.pill.tag{letter-spacing:.04em}
.pill.inv{background:var(--mint);color:var(--bg);border-color:var(--mint)}
.stats{display:flex;align-items:stretch;flex:0 0 auto}
.stat{display:flex;flex-direction:column;justify-content:space-between;padding:0 14px;border-left:1px solid var(--stroke);min-width:96px}
.stat .v{display:flex;align-items:baseline;gap:4px;line-height:1}
.stat .v b{font-size:calc(24px*var(--fz));font-weight:400;letter-spacing:-.02em}
.stat .v span{font-size:calc(12px*var(--fz));color:var(--text2)}
.stat .d{display:none}
.stat .ic{display:inline-block;width:6px;height:6px;margin-right:6px;background:var(--tone);vertical-align:1px}
.stat.t-amber .v b{color:var(--amber)}
/* status row: the run's state, then the eleven stages as a rail, then the viewer's controls */
.statusrow{display:grid;grid-template-columns:minmax(250px,1fr) minmax(0,2fr) auto;gap:14px;align-items:center;min-width:0}
.banner{display:flex;align-items:center;gap:10px;min-width:0;padding:6px 10px;border:1px solid rgba(var(--tone-rgb),.45);
 background:rgba(var(--tone-rgb),.05);height:100%}
.banner .btile{flex:0 0 auto;width:24px;height:24px;display:grid;place-items:center;color:var(--tone)}
.banner .btile svg{width:20px;height:20px}
.banner h2{margin:0;font-size:calc(13.5px*var(--fz));font-weight:600;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.banner p{margin:1px 0 0;font-size:calc(11.5px*var(--fz));color:var(--text2);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.banner .badge{flex:0 0 auto;font-size:calc(11.5px*var(--fz));padding:2px 7px;color:var(--bg);background:var(--tone);white-space:nowrap}
.banner .badge:empty{display:none}
.t-mint{--tone:var(--mint);--tone-rgb:var(--mint-rgb)}.t-amber{--tone:var(--amber);--tone-rgb:var(--amber-rgb)}
.t-blue{--tone:var(--blue);--tone-rgb:var(--blue-rgb)}.t-grey{--tone:var(--text2);--tone-rgb:var(--grey-rgb)}
.strip{position:relative;display:grid;grid-template-columns:repeat(11,minmax(0,1fr));align-items:start;min-width:0;padding-top:2px}
.strip::before{content:"";position:absolute;left:4.5%;right:4.5%;top:9px;border-top:1px solid var(--stroke)}
.node{position:relative;display:flex;flex-direction:column;align-items:center;gap:3px;min-width:0;font:inherit;color:var(--text2);
 background:none;border:0;padding:0;cursor:pointer}
.node .pt{position:relative;width:13px;height:13px;border-radius:50%;border:1px solid var(--text2);background:var(--bg);z-index:1}
.node .nl{padding:0 3px;font-size:calc(11.5px*var(--fz));color:var(--text);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.node .nd{padding:0 3px;font-size:calc(10.5px*var(--fz));color:var(--text2);white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}
.node.n-done .pt{background:var(--mint);border-color:var(--mint)}
.node.n-running .pt,.node.n-quiet .pt{border:2px solid var(--mint);background:var(--bg);box-shadow:0 0 0 3px rgba(var(--mint-rgb),.15)}
.node.n-running .pt::after{content:"";position:absolute;inset:2px;border-radius:50%;background:var(--mint);animation:pulse 1.6s ease-in-out infinite}
.node.n-failed .pt,.node.n-stopped .pt,.node.n-unknown .pt{background:var(--amber);border-color:var(--amber)}
.node.n-quiet .pt{border-color:var(--amber)}
.node.n-handoff .pt,.node.n-waiting_runner .pt{background:var(--blue);border-color:var(--blue)}
.node.n-skipped .pt{border-style:dashed}
.node[aria-pressed="true"] .nl{background:var(--mint);color:var(--bg);padding:0 4px}
.node:focus-visible{outline:1px solid var(--mint);outline-offset:2px}
.live{display:flex;flex-direction:column;align-items:flex-end;gap:5px}
.livelab{display:flex;align-items:center;gap:6px;font-size:calc(11.5px*var(--fz));color:var(--text2);white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--text2);display:inline-block}
.dot.mint{background:var(--mint);animation:pulse 1.6s ease-in-out infinite}.dot.amber{background:var(--amber)}.dot.blue{background:var(--blue)}
.tools{display:flex;gap:6px;align-items:center}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
/* panels */
.main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr) minmax(0,1fr);gap:10px;min-height:0}
.bottom{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:10px;min-height:0}
.card{position:relative;display:flex;flex-direction:column;min-width:0;min-height:0;background:var(--card);border:1px solid var(--stroke)}
.card::before,.card::after{content:"";position:absolute;width:7px;height:7px;border-color:var(--text);border-style:solid;pointer-events:none}
.card::before{top:-1px;left:-1px;border-width:1px 0 0 1px}.card::after{bottom:-1px;right:-1px;border-width:0 1px 1px 0}
.hd{display:flex;align-items:center;gap:10px;padding:7px 12px;border-bottom:1px solid var(--stroke);min-width:0;flex:0 0 auto}
.hd h3{margin:0;font-size:calc(12px*var(--fz));font-weight:600;letter-spacing:.06em;white-space:nowrap}
.hd h3 .ix{color:var(--text2);font-weight:400;margin-right:8px}
.hd .sec{font-size:calc(11.5px*var(--fz));white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.body{padding:10px 12px;min-height:0;flex:1 1 auto;overflow:auto;display:flex;flex-direction:column;gap:8px}
.body.flush{padding:0;overflow:hidden}
button.ghost,button.action,button.icon{font:inherit;font-size:calc(12px*var(--fz));line-height:1.2;color:var(--text);background:transparent;
 border:1px solid var(--stroke);padding:5px 11px;cursor:pointer;white-space:nowrap;min-height:30px;
 display:inline-flex;align-items:center;justify-content:center;gap:6px}
button.icon{width:30px;padding:0;color:var(--text2)}
button.ghost:hover,button.action:hover,button.icon:hover{border-color:var(--text)}
button.action[aria-pressed="true"]{background:var(--mint);color:var(--bg);border-color:var(--mint)}
button:disabled{opacity:.4;cursor:default}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,a:focus-visible{outline:1px solid var(--mint);outline-offset:2px}
/* stages */
.gantt{display:flex;flex-direction:column;flex:1 1 auto;min-height:0}
.grow{flex:1 1 auto;min-height:24px;max-height:40px;display:grid;grid-template-columns:84px 92px 80px minmax(0,1fr);align-items:center;gap:8px;min-width:0;
 padding:0;border-bottom:1px dashed var(--grid)}
.grow .sm{display:none}
button.stage-pick{font:inherit;text-align:left;color:var(--text);background:none;border:0;padding:3px 0;cursor:pointer;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:2px 0}
button.stage-pick[aria-pressed="true"]{background:var(--mint);color:var(--bg);padding-left:4px}
.grow .du{font-size:calc(11.5px*var(--fz));color:var(--text2);text-align:right;white-space:nowrap}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:calc(11.5px*var(--fz));color:var(--tone);white-space:nowrap}
.chip::before{content:"";width:6px;height:6px;background:var(--tone);flex:0 0 auto}
.track{position:relative;height:10px;background:repeating-linear-gradient(90deg,var(--grid) 0 1px,transparent 1px 10%)}
.track .q{display:none}
.track .bar{position:absolute;top:1px;bottom:1px;min-width:2px}
.s-done{background:var(--mint)}.s-failed,.s-stopped{background:var(--amber)}
.s-quiet,.s-unknown{background:rgba(var(--amber-rgb),.6)}
.s-handoff,.s-waiting_runner{background:var(--blue)}
.s-skipped{background:repeating-linear-gradient(45deg,var(--text2) 0 1px,transparent 1px 4px)}
.bar.s-running{background:repeating-linear-gradient(-45deg,var(--mint) 0 3px,transparent 3px 6px);background-size:12px 12px;
 animation:march 0.8s linear infinite}
@keyframes march{to{background-position:12px 0}}
.axis{display:grid;grid-template-columns:84px 92px 80px minmax(0,1fr);gap:8px;font-size:calc(10.5px*var(--fz));color:var(--text2);margin-top:4px;white-space:nowrap}
.axis .ticks{display:flex;justify-content:space-between;gap:8px}
.inspect{flex:0 1 auto;max-height:48%;overflow:auto;border-top:1px solid var(--text);padding:8px 10px;background:var(--inset);font-size:calc(12px*var(--fz))}
.inspect h4{font-size:calc(12px*var(--fz));margin:0 0 6px;letter-spacing:.04em}
.inspect:focus{outline:1px solid var(--mint)}
dl.kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:3px 12px;margin:0;font-size:calc(12px*var(--fz))}
dl.kv dt{color:var(--text2);white-space:nowrap}
dl.kv dd{margin:0;overflow-wrap:anywhere}
/* notices: a count in the status row that opens over the panels */
.notices-wrap{position:relative}
.notices-wrap>summary{list-style:none;cursor:pointer}
.notices-wrap>summary::-webkit-details-marker{display:none}
.notices{position:absolute;right:0;top:calc(100% + 6px);z-index:20;width:min(560px,92vw);max-height:60vh;overflow:auto;
 display:flex;flex-direction:column;gap:6px;padding:8px;background:var(--card);border:1px solid var(--text);
 box-shadow:0 12px 40px rgba(0,0,0,.25)}
.notice{display:flex;gap:8px;align-items:flex-start;padding:6px 8px;border-left:2px solid var(--tone);background:rgba(var(--tone-rgb),.06);min-width:0}
.notice b{display:block;font-size:calc(12px*var(--fz));margin-bottom:1px}
.notice span{font-size:calc(11.5px*var(--fz));color:var(--text2);overflow-wrap:anywhere}
.notice .ic{color:var(--tone);flex:0 0 auto}
.notice .ic svg{width:14px;height:14px}
/* surfaces: a picker, then one surface large */
.picker{display:flex;gap:4px;overflow-x:auto;overflow-y:hidden;padding:6px 10px;border-bottom:1px solid var(--stroke);
 flex:0 0 auto;scrollbar-width:thin}
.spick{font:inherit;font-size:calc(11.5px*var(--fz));display:inline-flex;align-items:center;gap:5px;padding:2px 7px;cursor:pointer;
 color:var(--text);background:none;border:1px solid var(--stroke);white-space:nowrap}
.spick i{width:6px;height:6px;background:var(--tone);flex:0 0 auto}
.spick[aria-pressed="true"]{background:var(--mint);color:var(--bg);border-color:var(--mint)}
.spick[aria-pressed="true"] i{outline:1px solid var(--bg)}
.surface{display:flex;flex-direction:column;min-height:0;flex:1 1 auto}
.shd{display:flex;align-items:center;gap:8px;padding:6px 10px;min-width:0;flex:0 0 auto}
.shd .sid{font-weight:600;font-size:calc(14px*var(--fz))}
.shd .orig{font-size:calc(11.5px*var(--fz));color:var(--text2)}
.stage3d{position:relative;flex:1 1 auto;min-height:120px;margin:0 10px;
 background-image:radial-gradient(var(--grid) 1px,transparent 1.2px);background-size:14px 14px;border:1px solid var(--grid)}
.stage3d::before,.stage3d::after{content:"";position:absolute;background:var(--grid);pointer-events:none}
.stage3d::before{left:50%;top:0;bottom:0;width:1px}.stage3d::after{top:50%;left:0;right:0;height:1px}
.stage3d .wire{position:absolute;inset:0;display:flex;flex-direction:column}
.stage3d .wirebox{flex:1 1 auto;height:auto;min-height:0;background:transparent}
.stage3d figcaption{position:absolute;left:8px;top:6px;right:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:calc(10.5px*var(--fz));color:var(--text2);pointer-events:none}
.stage3d .empty{position:absolute;inset:0;display:grid;place-items:center;text-align:center;padding:16px;color:var(--text2)}
.ro{position:absolute;right:8px;top:6px;font-size:calc(10.5px*var(--fz));color:var(--text2);pointer-events:none;z-index:1}
.checks{flex:0 1 auto;max-height:42%;overflow:auto;padding:8px 10px;display:flex;flex-direction:column;gap:6px}
.wirebox{position:relative;height:220px}
.wirebox canvas{display:block;width:100%;height:100%;cursor:grab;touch-action:pan-y}
.wirebox canvas:active{cursor:grabbing}
.wirebox canvas:focus-visible{outline:1px solid var(--mint);outline-offset:-2px}
/* ink */
.part{display:flex;flex-direction:column;gap:6px;padding-bottom:8px;border-bottom:1px dashed var(--grid)}
.part:last-child{border-bottom:0}
.subhd{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.thumbs,.skel{display:grid;grid-template-columns:1fr 1fr;gap:8px}
figure{margin:0;min-width:0}
figure img{display:block;width:100%;height:auto;max-height:min(24vh,220px);object-fit:contain;background:var(--inset);
 transition:opacity .25s ease;border:1px solid var(--stroke)}
.inkscale{display:inline-flex;align-items:center;gap:5px;vertical-align:middle}
.inkscale i{display:inline-block;width:56px;height:7px;border:1px solid var(--stroke);
 background:linear-gradient(90deg,#16110f,#3e2416 13.3%,#7c4420 33.5%,#be7838 58.1%,#e8b670 81.2%,#faecce)}
figure img.pre{opacity:0}
figure img.broken{opacity:0;min-height:40px}
figcaption{font-size:calc(10.5px*var(--fz));color:var(--text2);margin-top:3px}
.frame{position:relative}
.sk{position:relative;overflow:hidden;background:var(--inset)}
.sk::after{content:"";position:absolute;inset:0;transform:translateX(-100%);
 background:linear-gradient(90deg,transparent,rgba(var(--grey-rgb),.18),transparent);animation:shimmer 1.4s ease-in-out infinite}
@keyframes shimmer{to{transform:translateX(100%)}}
.frame.sk{aspect-ratio:3/2;max-height:min(24vh,220px)}
.frame.sk img{position:absolute;inset:0}
.skel .sk{aspect-ratio:3/2}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.cmp>div{border:1px solid var(--stroke);padding:5px 7px;min-width:0}
.cmp b{font-size:calc(20px*var(--fz));font-weight:400;display:block;margin-top:2px}
.scorerow{display:flex;flex-direction:column;gap:4px;min-width:0}
/* log and commands */
.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}
.controls label{display:flex;align-items:center;gap:5px;min-width:0;color:var(--text2);font-size:calc(11.5px*var(--fz))}
.controls input,.controls select,.command{font:inherit;font-size:calc(12px*var(--fz));color:var(--text);background:var(--inset);
 border:1px solid var(--stroke);padding:4px 8px;min-width:0;max-width:100%;border-radius:0;min-height:30px}
.controls .search{flex:1 1 140px}
.controls .search input{flex:1 1 auto;width:100%}
.tabs{display:flex;gap:0;margin-left:auto}
.tabs button{border-right-width:0;min-height:26px;padding:3px 11px}.tabs button:last-child{border-right-width:1px}
.log{flex:1 1 auto;min-height:0;background:var(--inset);border:1px solid var(--stroke);padding:6px 8px;overflow-y:auto;
 overflow-x:hidden;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.45;font-size:calc(12px*var(--fz))}
.log .ts{color:var(--text2)}
.log .ev{color:var(--text);font-weight:600}
.log .bad{color:var(--amber);font-weight:600}
.files{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:2px 10px}
.file-row{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;font-size:calc(11.5px*var(--fz));padding:1px 0}
.file-row code{font:inherit;color:var(--text)}
.command{width:100%;min-height:28px;resize:vertical;flex:1 1 auto}
/* console */
.pane{display:flex;flex-direction:column;gap:8px;min-height:0;flex:1 1 auto}
.quick{display:flex;gap:6px;flex-wrap:wrap;flex:0 0 auto}
.quick button{padding:4px 9px}
#con-msg:empty{display:none}
.cmdline{display:flex;align-items:stretch;gap:0;min-width:0;margin:0}
.cmdline .prompt{display:grid;place-items:center;padding:0 9px;border:1px solid var(--stroke);border-right:0;color:var(--amber);background:var(--inset)}
.cmdline input{flex:1 1 auto;min-width:0;font:inherit;font-size:calc(12px*var(--fz));color:var(--text);background:var(--inset);border:1px solid var(--stroke);padding:4px 8px;border-radius:0;min-height:30px}
.cmdline button{border-left:0}
.toolref{display:flex;flex-direction:column;gap:6px;flex:0 0 auto;min-width:0;border-top:1px dashed var(--grid);padding-top:8px}
/* one row that scrolls sideways, so a chip is never cut in half */
.toolchips{display:flex;flex-wrap:nowrap;gap:5px;overflow-x:auto;overflow-y:hidden;scrollbar-width:thin;padding-bottom:2px;min-width:0}
.toolchips button{flex:0 0 auto}
.toolchips button{font:inherit;font-size:calc(11.5px*var(--fz));line-height:1.2;padding:3px 8px;border:1px solid var(--grid);background:none;color:var(--text2);cursor:pointer}
.toolchips button:hover{color:var(--text);border-color:var(--text)}
textarea.notes{flex:1 1 auto;min-height:60px;width:100%;resize:none;font:inherit;font-size:calc(12px*var(--fz));line-height:1.45;color:var(--text);
 background:var(--inset);border:1px solid var(--stroke);padding:6px 8px;border-radius:0}
.jobs{display:flex;flex-direction:column;flex:0 0 auto;max-height:42%;overflow-y:auto;border:1px solid var(--stroke)}
.jobrow{display:grid;grid-template-columns:108px minmax(0,1fr) 72px auto;gap:10px;align-items:center;padding:3px 8px;font-size:calc(11.5px*var(--fz));
 border:0;border-bottom:1px dashed var(--grid);background:none;color:var(--text);font-family:inherit;text-align:left;cursor:pointer;min-height:26px}
.jobrow:last-child{border-bottom:0}
.jobrow[aria-pressed="true"]{background:var(--inset);box-shadow:inset 2px 0 0 var(--amber)}
.jobrow .tm{color:var(--text2);text-align:right}
.jobrow .x{font-size:calc(11px*var(--fz));color:var(--text2);border:1px solid var(--stroke);padding:0 5px}
.jobrow .x:hover{color:var(--text);border-color:var(--text)}
footer{display:flex;gap:16px;font-size:calc(10.5px*var(--fz));color:var(--text2);border-top:1px solid var(--stroke);padding-top:5px}
footer span{flex:1 1 300px}
footer span:last-child{text-align:right}
@media (prefers-reduced-motion: reduce){.sk::after{animation:none;opacity:0}figure img{transition:none}
 .node.n-running .pt::after,.dot.mint,.bar.s-running{animation:none}}
/* a window too small for one screen: one column that scrolls */
@media (max-width:1000px),(max-height:600px){
 .wrap{height:auto;min-height:100vh;grid-template-rows:none}
 .main,.bottom{grid-template-columns:minmax(0,1fr)}
 .card{min-height:0}
 .stage3d{min-height:260px;flex:0 0 auto}
 .checks{max-height:none}
 .log{max-height:360px}
 .pane{min-height:0}
 textarea.notes{min-height:160px}
 .statusrow{grid-template-columns:minmax(0,1fr)}
 .live{flex-direction:row;align-items:center;justify-content:space-between;flex-wrap:wrap}
 .livelab{flex-wrap:wrap;white-space:normal}
 .tools{flex-wrap:wrap}
 header.top{flex-wrap:wrap}
 .stats{flex-wrap:wrap;width:100%}
 .stat{border-left:0;border-top:1px solid var(--stroke);padding:6px 10px 6px 0;flex:1 1 90px}
}
@media (max-width:600px){
 .wrap{padding:12px}
 .brand .full{display:none}.brand .short{display:inline}
 .strip{grid-template-columns:repeat(6,minmax(0,1fr));row-gap:6px}
 .strip::before{display:none}
 .grow{grid-template-columns:minmax(0,1fr) auto auto}
 .grow .track{grid-column:1 / -1}
 .grow.notime .track{display:none}
 .axis{grid-template-columns:minmax(0,1fr)}
 .axis>span:not(.ticks){display:none}
 dl.kv{grid-template-columns:minmax(0,1fr)}
 dl.kv dt{margin-top:3px}
 footer{flex-direction:column}
 footer span:last-child{text-align:left}
}
/* small screens, under a 14 inch MacBook's window: smaller text, one-row button strips, fewer extras */
@media (max-width:1440px),(max-height:820px){:root{--fz:.9}.gantt .grow{min-height:21px}#ax1{display:none}.toolref .fine{display:none}
 .quick{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:thin}.quick button{flex:0 0 auto}}
@media (max-height:760px){.toolref{display:none}figure img{max-height:20vh}}
"""

_JS = r"""
(function(){
"use strict";
var LIVE = %LIVE%;
var S = JSON.parse(document.getElementById("summary").textContent);
var lastOk = Date.now(), lost = false, misses = 0, timer = null, fetchedAt = Date.now();
var pausedAt = null, polling = false, selectedStage = "";
var IMGS = {};   // thumbnail nodes kept across renders, so a poll never reloads or blanks a loaded image
var STAGE_TONE = {done:"mint", running:"mint", skipped:"grey", handoff:"blue", waiting_runner:"blue",
  failed:"amber", stopped:"amber", quiet:"amber", unknown:"amber", waiting:"grey", not_reached:"grey"};
var STAGE_LABEL = {done:"Done", running:"Running", skipped:"Skipped", handoff:"Handed off",
  waiting_runner:"On the runner", failed:"Failed", stopped:"Stopped", quiet:"Quiet", unknown:"No news",
  waiting:"Not run yet", not_reached:"Not reached"};
var STAGE_NAME = {qa:"QA"};   // the server's STAGE_LABELS: names written other than with a capital first letter
var VARIANT = {f:"forward", r:"reversed", s:"shuffled"};
var ENDED = ["finished","failed","handoff","paused","stopped","state_error","error"];
function $(id){return document.getElementById(id);}
function el(tag, cls, text){var e=document.createElement(tag); if(cls) e.className=cls;
  if(text!==undefined && text!==null) e.textContent=String(text); return e;}
function clear(e){while(e.firstChild) e.removeChild(e.firstChild); return e;}
function cap(t){t=String(t||""); return t.charAt(0).toUpperCase()+t.slice(1);}
function stageName(n){return STAGE_NAME[n]||cap(n);}   // Acquire, Umbilicus, ..., QA, ..., Report
function svg(name){var t=$("ic-"+name); var n=t&&t.content&&t.content.firstElementChild; return n?n.cloneNode(true):el("span");}
function fmt(v, d){if(v===null||v===undefined||typeof v!=="number"||!isFinite(v)) return "N/A";
  return v.toFixed(d===undefined?3:d);}
function pct(v){return (typeof v==="number"&&isFinite(v)) ? (v*100).toFixed(1)+"%" : "N/A";}
// one way to write a span everywhere (the server's _dur writes the same): 4.5 s, 45 s, 12 min 5 s, 2 h 5 min
function durParts(s){if(s===null||s===undefined||typeof s!=="number"||!isFinite(s)) return [["N/A",""]]; s=Math.max(0,s);
  if(s<10) return [[s.toFixed(1),"s"]]; if(s<60) return [[String(Math.min(59,Math.round(s))),"s"]];
  s=Math.floor(s); if(s<3600){var m=Math.floor(s/60), r=s%60; return r?[[String(m),"min"],[String(r),"s"]]:[[String(m),"min"]];}
  var h=Math.floor(s/3600), mm=Math.floor((s%3600)/60); return mm?[[String(h),"h"],[String(mm),"min"]]:[[String(h),"h"]];}
function dur(s){var p=durParts(s); if(p[0][0]==="N/A") return "N/A"; return p.map(function(x){return x[0]+" "+x[1];}).join(" ");}
function fillDur(v, s){clear(v); v.setAttribute("aria-label",dur(s)); durParts(s).forEach(function(p){v.appendChild(el("b",null,p[0])); if(p[1]) v.appendChild(el("span",null,p[1]));});}
function clock(t){if(!t) return "N/A"; var d=new Date(t*1000);
  return d.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"});}
function hm(t){return t?new Date(t*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",hourCycle:"h23"}):"N/A";}
function durShort(s){if(s===null||s===undefined||typeof s!=="number"||!isFinite(s)) return "N/A"; s=Math.max(0,Math.round(s));   // the rail's: 14s, 1m 3s, 2h 5m
  return s<60?s+"s":s<3600?Math.floor(s/60)+"m "+(s%60)+"s":Math.floor(s/3600)+"h "+Math.floor(s%3600/60)+"m";}
function tonecls(t){return "t-"+(t||"grey");}
function chip(status){return el("span","chip "+tonecls(STAGE_TONE[status]||"grey"),STAGE_LABEL[status]||status);}
function pill(text, tone, tag){return el("span","pill "+(tone||"")+(tag?" tag":""),text);}
function kv(dl, k, v){if(v===null||v===undefined||v==="") return; dl.appendChild(el("dt",null,k));
  var dd=el("dd",null,v); dl.appendChild(dd); return dd;}
function isRunning(){return !!(S.current&&(S.phase==="running"||S.phase==="quiet"));}
function ended(){return ENDED.indexOf(S.phase)>=0;}
function noNews(){return LIVE&&lost&&isRunning();}       // the server stopped answering while a stage ran
function elapsedNow(){var e=S.current?S.current.elapsed_s:null; if(e===null||e===undefined) return null;
  return e+(LIVE&&!lost&&isRunning()?((pausedAt||Date.now())-fetchedAt)/1000:0);}
function rowStatus(r){return noNews()&&(r.status==="running"||r.status==="quiet")?"unknown":r.status;}

function theme(){var b=$("theme"), modes=["auto","dark","light"], cur="auto";
  try{cur=localStorage.getItem("autopipeline-monitor-theme")||"auto";}catch(e){}
  function apply(m){if(m==="auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme",m); b.textContent="Theme: "+m; wireAll();}
  apply(cur);
  b.addEventListener("click",function(){cur=modes[(modes.indexOf(cur)+1)%3]; apply(cur);
    try{localStorage.setItem("autopipeline-monitor-theme",cur);}catch(e){}});}

function header(){var p=S.plan||{};
  $("h-sample").textContent=p.sample||"No sample";
  $("h-volume").textContent=p.volume?("Volume "+p.volume):"No volume";
  $("h-digest").textContent=p.short?("Plan "+p.short):"No plan";
  $("title").textContent=S.name||"run";
  var bits=[]; if(p.purpose) bits.push(cap(p.purpose)+" run"); if(p.created) bits.push("Planned "+p.created);
  if(p.models&&p.models.length) bits.push("Ink: "+p.models.join(", "));
  $("subtitle").textContent=bits.join("  |  "); $("subtitle").title=bits.join("  |  ");
  $("folder").textContent=S.folder?("<run> = "+S.folder):""; $("folder").title=S.folder||"";
  $("target").classList.toggle("hidden", p.purpose!=="target");
  document.title=(S.name||"run")+" | AP Monitor";}

function liveLabel(){var d=$("livedot"), t=$("livetext"), u=$("updated");
  if(!LIVE){d.className="dot"; t.textContent="Snapshot "+(S.generated||""); u.textContent="Taken "+new Date((S.generated_epoch||0)*1000).toLocaleString(); return;}
  var ago=Math.max(0,Math.round((Date.now()-lastOk)/1000));
  if(pausedAt){d.className="dot amber"; t.textContent="Viewer paused"; u.textContent="Last update "+dur(ago)+" ago; the run is not paused"; return;}
  if(lost){d.className=ended()?"dot":"dot amber"; t.textContent=ended()?"Monitor closed":"No connection, retrying"; u.textContent="Last update "+(ago<60?ago+" s":dur(ago))+" ago"; return;}
  if(S.phase==="running"){d.className="dot mint"; t.textContent="Live";}
  else {d.className="dot blue"; t.textContent="Watching";}
  u.textContent="Updated "+(ago<60?ago+" s":dur(ago))+" ago";}

function banner(){var b=S.banner||{tone:"grey",title:"",detail:"",badge:""}, box=$("banner");
  if(noNews()) b={tone:"amber",title:"No news since "+stageName(S.current.stage)+" was running",
    detail:"The monitor stopped answering: the run ended, was interrupted or crashed, or the monitor was closed. Run python -m kit autopipeline monitor on this folder to see where it stopped.",badge:"No news"};
  box.className="banner "+tonecls(b.tone);
  var tile=clear($("b-icon")); var ic=b.tone==="amber"?"amber":(S.phase==="finished"&&b.tone==="mint")?"done":b.tone==="blue"?"blue":"mint";
  tile.appendChild(svg(ic));
  $("b-title").textContent=b.title||""; $("b-detail").textContent=b.detail||""; $("b-badge").textContent=b.badge||"";
  box.title=(b.title||"")+(b.detail?"\n"+b.detail:"");
  tickElapsed();}

// notices sit behind a count in the status row, so they never push the panels down; one that needs a person
// (amber) names itself on the count
function notices(){var box=clear($("notices")), list=[];
  function add(tone, title, msg){var n=el("div","notice "+tonecls(tone)); var ic=el("span","ic"); ic.appendChild(svg(tone==="amber"?"amber":"blue"));
    n.appendChild(ic); var t=el("div"); t.appendChild(el("b",null,title)); t.appendChild(el("span",null,msg)); n.appendChild(t); box.appendChild(n); list.push([tone,title]);}
  noticeList(add);
  var wrap=$("notice-box"), sum=$("notice-sum"); wrap.classList.toggle("hidden",!list.length);
  var amber=list.filter(function(x){return x[0]==="amber";});
  sum.className="pill tag "+(amber.length?"amber":"blue");
  sum.textContent=amber.length?(amber[0][1]+(list.length>1?" +"+(list.length-1):"")):(list.length+" note"+(list.length>1?"s":""));
  sum.title=list.map(function(x){return x[1];}).join("\n");}
function noticeList(add){
  if(lost&&LIVE&&!noNews()){if(ended()) add("grey","The monitor has closed","As it does when its run ends, or when it was stopped; the last state read is shown.");
    else add("amber","No connection","The monitor is not answering; the last state read is shown, and the page keeps trying.");}
  if(S.state&&S.state.error&&S.phase!=="state_error") add("amber","state.json",S.state.error);
  if(S.plan&&S.plan.purpose==="target") add("amber","A target run","Its maps and scores stay private: maps of target scrolls must not be shared. Thumbnails are off unless asked for.");
  var tf=S.trace_failures||[];
  if(tf.length) add("amber",tf.length+" trace"+(tf.length>1?"s":"")+" gave no surface",
    tf.slice(0,6).map(function(f){return f.id+" ("+(f.kind||"unknown")+"): "+(f.reason||"");}).join("; ")+(tf.length>6?"; ...":""));
  var pt=S.partial_traces||[];
  if(pt.length) add("blue",pt.length+" partial surface"+(pt.length>1?"s":"")+", checked by qa like any other",
    pt.slice(0,6).map(function(p){return p.id+" ("+(p.kind||"partial")+"): stopped after generation "+(p.generations_done!=null?p.generations_done:"?")+
      (p.generations_planned!=null?" of "+(p.generations_planned-1):"")+(p.area_cm2!=null?", "+fmt(p.area_cm2,3)+" cm²":"");}).join("; ")+(pt.length>6?"; ...":""));
  var fl=S.trace_inflight;
  if(fl&&fl.id) add("blue","Tracing "+fl.id,"Budget "+(fl.budget_s!=null?dur(fl.budget_s):"not set")+(fl.time_limit_s!=null?", the tracer stops itself at "+dur(fl.time_limit_s):"")+
    (fl.hard_timeout_s!=null?", stopped at "+dur(fl.hard_timeout_s)+" at the latest":"")+(fl.started?"; started "+fl.started:"")+"."+(fl.progress?" Latest: "+fl.progress:""));
  var rt=S.trace_runtime;
  if(rt&&rt.warning) add("amber","The tracer's grid cache thrashes",rt.warning);
  if(rt&&!rt.warning&&rt.class) add("blue","Trace runtime","Cost class "+rt.class+(rt.grid_cache_bytes!=null?", VC_GRID_CACHE_BYTES "+fmt(rt.grid_cache_bytes/1073741824,1)+" GiB":"")+
    (rt.grid_cache_entries!=null?", VC_NORMAL_GRID_CACHE "+rt.grid_cache_entries:"")+(rt.memory_bytes!=null?", memory "+fmt(rt.memory_bytes/1073741824,1)+" GiB":"")+
    (rt.time_limit?", time limit passed to the tracer":", no tracer time limit")+(rt.villa_rev?", villa "+String(rt.villa_rev).slice(0,10):"")+(rt.villa_patches?" with "+rt.villa_patches:"")+".");
  var pr=S.trace_preempted||[];
  if(pr.length) add("blue","After a lost container",pr.slice(0,6).map(function(p){return p.id+": "+(p.kept?("kept"+(p.whole?" whole":" as "+(p.kind||"partial"))+
    (p.generations_done!=null?" at generation "+p.generations_done:"")):("traced again ("+(p.why||"no snapshot")+")"));}).join("; ")+(pr.length>6?"; ...":""));
  if(S.report&&S.report.present&&S.report.matches===false) add("amber","report.json changed","Its sha256 is not the digest the run recorded when it wrote it.");}

function stats(){var st=S.stats||{}, box=clear($("stats"));
  function card(tone, label, val, unit, detail){var c=el("div","stat "+tonecls(tone)); var l=el("div","label"); var i=el("span","ic"); l.appendChild(i); l.appendChild(document.createTextNode(label)); c.appendChild(l);
    var v=el("div","v num"); if(val!==null){v.appendChild(el("b",null,val)); if(unit) v.appendChild(el("span",null,unit));} c.appendChild(v); c.appendChild(el("div","d",detail)); c.title=label+": "+detail; box.appendChild(c); return v;}
  card("mint","Stages", st.stages_finished==null?"N/A":String(st.stages_finished), "/ "+(st.stages_total||11), "Done, skipped or handed off");
  var traced=st.surfaces_traced||0, known=traced||st.surfaces_planned!=null;
  card(st.surfaces_rejected?"amber":"blue","Surfaces", known?String(st.surfaces_accepted||0):"N/A", known?("/ "+traced):"",
    "Accepted of traced"+(st.surfaces_planned!=null?("; "+st.surfaces_planned+" planned"):"")+"; "+(st.trace_failures||0)+" trace failures"+(st.published_segments?("; "+st.published_segments+" published"):""));
  var run=isRunning();
  var v=card(run&&!noNews()?"mint":(run?"amber":"blue"), run?((noNews()?"Last seen in ":"Elapsed in ")+stageName(S.current.stage)):"Run time", null, null,
    run?(noNews()?"Until the monitor stopped answering":"Measured from the run's own start record"):"Sum of stage times in state.json");
  v.id="elapsed"; fillDur(v, run?elapsedNow():st.run_seconds);
  card(st.warnings?"amber":"mint","Warnings", st.warnings==null?"N/A":String(st.warnings), "", "QA and render distortion, not stopping the run");}

// the banner title, the card and the running stage's row show one elapsed time, ticking together
function tickElapsed(){if(!isRunning()||noNews()) return; var e=elapsedNow(); if(e===null) return;
  var v=$("elapsed"); if(v) fillDur(v, e);
  var du=$("du-running"); if(du) du.textContent=dur(e);
  var nd=$("nd-running"); if(nd) nd.textContent=durShort(e);
  if(S.phase==="running"&&LIVE) $("b-title").textContent="Running "+stageName(S.current.stage)+" for "+dur(e);}

// the stages twice: as a rail of eleven points in the status row (a glance), and as rows with a wall-clock bar
// each in the stages panel; either one chooses a stage
function timeline(){var act=document.activeElement, focus=act&&act.dataset&&act.dataset.stage, focusRail=act&&act.dataset&&act.dataset.rail;
  var rows=S.stages||[], strip=clear($("strip")), g=clear($("gantt"));
  rows.forEach(function(r){var st=rowStatus(r); var n=el("button","node n-"+st); n.type="button"; n.dataset.rail=r.name;
    n.setAttribute("aria-pressed",String(selectedStage===r.name)); n.title=stageName(r.name)+": "+(STAGE_LABEL[st]||st)+((r.error||r.why||r.summary)?"\n"+cap(r.error||r.why||r.summary):"");
    n.setAttribute("aria-label",stageName(r.name)+", "+(STAGE_LABEL[st]||st)); n.onclick=function(){chooseStage(selectedStage===r.name?"":r.name);};
    n.appendChild(el("span","pt")); n.appendChild(el("span","nl",stageName(r.name)));
    var live=isRunning()&&S.current.stage===r.name&&!noNews();
    var nd=el("span","nd num",live?durShort(elapsedNow()):(r.seconds!=null&&st!=="waiting"&&st!=="not_reached"?durShort(r.seconds):"\u00a0")); if(live) nd.id="nd-running"; n.appendChild(nd);
    strip.appendChild(n); if(focusRail===r.name) n.focus({preventScroll:true});});
  var now=LIVE&&!lost?(S.generated_epoch+((pausedAt||Date.now())-fetchedAt)/1000):S.generated_epoch;
  function endOf(r){return r.ended_epoch!=null?r.ended_epoch:((r.status==="running"||r.status==="quiet")?now:r.started_epoch);}
  var t0=null,t1=null; rows.forEach(function(r){if(r.started_epoch!=null){t0=t0==null?r.started_epoch:Math.min(t0,r.started_epoch);
    var e=endOf(r); t1=t1==null?e:Math.max(t1,e);}});
  if(t0!=null&&t1!=null&&t1-t0<1) t1=t0+1;
  rows.forEach(function(r){var st=rowStatus(r); var row=el("div","grow"+(r.started_epoch==null?" notime":""));
    var pick=el("button","nm stage-pick",stageName(r.name)); pick.type="button"; pick.dataset.stage=r.name;
    pick.setAttribute("aria-pressed",String(selectedStage===r.name)); pick.setAttribute("aria-controls","stage-detail");
    pick.title="Inspect "+stageName(r.name)+" and filter its log"; pick.onclick=function(){chooseStage(r.name);}; row.appendChild(pick);
    var c=el("span"); c.appendChild(chip(st)); row.appendChild(c);
    var live=isRunning()&&S.current.stage===r.name&&!noNews();
    var du=el("span","du num",live?dur(elapsedNow()):(r.seconds!=null?dur(r.seconds):"")); if(live) du.id="du-running"; row.appendChild(du);
    var tr=el("div","track"); [25,50,75].forEach(function(q){var l=el("div","q"); l.style.left=q+"%"; tr.appendChild(l);});
    if(t0!=null&&r.started_epoch!=null){var e=endOf(r);
      var b=el("div","bar s-"+st); b.style.left=(100*(r.started_epoch-t0)/(t1-t0)).toFixed(2)+"%";
      b.style.width=Math.max(0.6,100*(e-r.started_epoch)/(t1-t0)).toFixed(2)+"%"; tr.appendChild(b);}
    row.appendChild(tr);
    var sm=r.error||r.why||r.summary; if(st==="unknown"&&r.status!=="unknown") sm="last seen running; the monitor stopped answering";
    if(sm){row.appendChild(el("div","sm"+(r.error?" wrapany":""),r.error?("Error ("+(r.kind||"unknown")+"): "+sm):cap(sm))); row.title=r.error?("Error ("+(r.kind||"unknown")+"): "+sm):cap(sm);}
    g.appendChild(row); if(focus===r.name) pick.focus({preventScroll:true});});
  var ax=$("axis"); ax.classList.toggle("hidden", t0==null);
  if(t0!=null){$("ax0").textContent=hm(t0); $("ax1").textContent=hm(t0+(t1-t0)/2);
    $("ax2").textContent=isRunning()&&LIVE&&!lost?"Now":hm(t1);}}

function thumbImg(src, alt, used){used[src]=1; var im=IMGS[src];
  if(!im){im=el("img","pre"); im.alt=alt; im.decoding="async";
    im.addEventListener("load",function(){im.classList.remove("pre"); if(im.parentNode) im.parentNode.classList.remove("sk");});
    im.addEventListener("error",function(){im.classList.add("broken"); if(im.parentNode) im.parentNode.classList.remove("sk");
      delete IMGS[src];});   // tried again next poll
    im.src=src; IMGS[src]=im;} return im;}
// a thumbnail waits under a shimmer until it has loaded, then fades in
function thumbFrame(im){var f=el("div","frame"+(im.complete&&(im.naturalWidth||im.classList.contains("broken"))?"":" sk"));
  f.appendChild(im); return f;}

// The traced mesh as a wireframe on a canvas: rows and columns of the strided grid as polylines, broken at holes,
// turned by dragging (or the arrow keys; 0 resets) and drawn orthographically, nearer lines brighter. Canvases are
// kept across polls with their turn, like thumbnails.
var WIRES = {};
var VIEW = {yaw:-0.6, pitch:0.35};
function clampPitch(p){return Math.max(-1.5,Math.min(1.5,p));}
function wireDraw(w){var box=w.box, cv=w.cv, W=box.clientWidth, H=box.clientHeight; if(!w.pts||!W||!H) return;
  var dpr=window.devicePixelRatio||1, pw=Math.round(W*dpr), ph=Math.round(H*dpr);
  if(cv.width!==pw||cv.height!==ph){cv.width=pw; cv.height=ph;}
  var g=cv.getContext("2d"); if(!g) return; g.setTransform(dpr,0,0,dpr,0,0); g.clearRect(0,0,W,H);
  var n=w.rows*w.cols, P=w.pts, ok=w.ok, X=new Float32Array(n), Y=new Float32Array(n), D=new Float32Array(n);
  var cy=Math.cos(w.yaw), sy=Math.sin(w.yaw), cp=Math.cos(w.pitch), sp=Math.sin(w.pitch), k=0.46*Math.min(W,H)/w.radius;
  for(var i=0;i<n;i++){if(!ok[i]) continue; var x=P[3*i], y=P[3*i+1], z=P[3*i+2];
    var x1=cy*x-sy*y, y1=sy*x+cy*y, up=cp*z-sp*y1;      // z, the scroll's axis, points up the screen
    X[i]=W/2+k*x1; Y[i]=H/2-k*up; D[i]=(sp*z+cp*y1)/w.radius;}   // D: -1 nearest to 1 farthest
  var B=4, buckets=[[],[],[],[]];
  function seg(a,b){if(!ok[a]||!ok[b]) return; var t=((D[a]+D[b])/2+1)/2; buckets[Math.min(B-1,Math.max(0,Math.floor(t*B)))].push(a,b);}
  for(var r=0;r<w.rows;r++) for(var c=0;c<w.cols;c++){var i2=r*w.cols+c; if(c+1<w.cols) seg(i2,i2+1); if(r+1<w.rows) seg(i2,i2+w.cols);}
  g.lineWidth=1; g.lineCap="round"; g.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue("--mint").trim()||"#1d8a4a";
  for(var b=B-1;b>=0;b--){var L=buckets[b]; if(!L.length) continue; g.globalAlpha=0.95-0.22*b; g.beginPath();
    for(var j=0;j<L.length;j+=2){g.moveTo(X[L[j]],Y[L[j]]); g.lineTo(X[L[j+1]],Y[L[j+1]]);} g.stroke();}
  g.globalAlpha=1;
  if(w.ro) w.ro.textContent="yaw "+Math.round(w.yaw*57.2958)+"°  pitch "+Math.round(w.pitch*57.2958)+"°";}
function wireSoon(w){if(w.raf) return; w.raf=requestAnimationFrame(function(){w.raf=0; wireDraw(w);});}
function wireAll(){Object.keys(WIRES).forEach(function(k){wireSoon(WIRES[k]);});}
function wireLoad(w, d){try{var bin=atob(d.q), n=d.rows*d.cols, unit=d.unit||16000, hole=d.hole===undefined?-32768:d.hole;
    if(bin.length!==6*n) throw new Error("size");
    var dv=new DataView(new ArrayBuffer(bin.length)); for(var i=0;i<bin.length;i++) dv.setUint8(i,bin.charCodeAt(i));
    var P=new Float32Array(3*n), ok=new Uint8Array(n), rad=0;
    for(var j=0;j<n;j++){var x=dv.getInt16(6*j,true); if(x===hole) continue; ok[j]=1;
      P[3*j]=x/unit; P[3*j+1]=dv.getInt16(6*j+2,true)/unit; P[3*j+2]=dv.getInt16(6*j+4,true)/unit;
      rad=Math.max(rad,Math.sqrt(P[3*j]*P[3*j]+P[3*j+1]*P[3*j+1]+P[3*j+2]*P[3*j+2]));}
    w.pts=P; w.ok=ok; w.rows=d.rows; w.cols=d.cols; w.radius=rad||1; w.box.classList.remove("sk");
    w.cap.textContent=d.rows+" x "+d.cols+" grid points"+(Array.isArray(d.extent)?(" in a box of "+d.extent.map(function(v){return Math.round(v);}).join(" x ")+" voxels (x, y, z)"):"")+"; nearer lines are brighter. Drag or use the arrow keys to turn it, 0 resets.";
    w.cap.title=w.cap.textContent; wireSoon(w);}
  catch(e){w.box.classList.remove("sk"); w.cap.textContent="No wireframe: the mesh could not be read.";}}
function wireFigure(s, used){var key=typeof s.wire==="string"?s.wire:("inline:"+s.id); used["wire:"+key]=1; var w=WIRES[key];
  if(w) return w.fig;
  w={key:key, yaw:VIEW.yaw, pitch:VIEW.pitch, pts:null, raf:0}; WIRES[key]=w;
  var fig=el("figure","wire"), box=el("div","wirebox sk"), cv=el("canvas"); cv.tabIndex=0; cv.setAttribute("role","img");
  cv.setAttribute("aria-label","3D wireframe of the traced surface "+s.id+": drag or use the arrow keys to turn it, 0 resets");
  box.appendChild(cv); fig.appendChild(box); var cap=el("figcaption",null,"Traced mesh: loading"); fig.appendChild(cap);
  w.fig=fig; w.box=box; w.cv=cv; w.cap=cap; w.ro=el("span","ro"); w.ro.style.top="auto"; w.ro.style.bottom="6px"; box.appendChild(w.ro);
  var drag=null;
  cv.addEventListener("pointerdown",function(e){drag={x:e.clientX,y:e.clientY,yaw:w.yaw,pitch:w.pitch}; try{cv.setPointerCapture(e.pointerId);}catch(_){}});
  cv.addEventListener("pointermove",function(e){if(!drag) return; w.yaw=drag.yaw+(e.clientX-drag.x)*0.01; w.pitch=clampPitch(drag.pitch+(e.clientY-drag.y)*0.01); wireSoon(w);});
  function end(){drag=null;} cv.addEventListener("pointerup",end); cv.addEventListener("pointercancel",end);
  cv.addEventListener("dblclick",function(){w.yaw=VIEW.yaw; w.pitch=VIEW.pitch; wireSoon(w);});
  cv.addEventListener("keydown",function(e){var a=0.12, k=e.key;
    if(k==="ArrowLeft") w.yaw-=a; else if(k==="ArrowRight") w.yaw+=a; else if(k==="ArrowUp") w.pitch=clampPitch(w.pitch-a);
    else if(k==="ArrowDown") w.pitch=clampPitch(w.pitch+a); else if(k==="0"||k==="Home"){w.yaw=VIEW.yaw; w.pitch=VIEW.pitch;} else return;
    e.preventDefault(); wireSoon(w);});
  if(typeof s.wire!=="string") wireLoad(w, s.wire);
  else if(s.wire.indexOf("wire/")===0) fetch(s.wire,{credentials:"same-origin"}).then(function(r){if(!r.ok) throw new Error(r.status); return r.json();})
    .then(function(d){wireLoad(w,d);}).catch(function(){box.classList.remove("sk"); cap.textContent="No wireframe: the mesh could not be read."; delete WIRES[key];});
  return fig;}

// One surface at a time, large: the picker lists every surface with its verdict's tone; the chosen one shows its
// traced mesh in 3D and its checks in the surfaces panel, and its ink maps beside their controls and its scores
// in the ink panel. The choice holds through polls while that surface is still listed.
var selectedSurface = "";
var SURF_TONE = {rendered:"mint",accepted:"mint",published:"blue",rejected:"amber",trace_failed:"amber",not_rendered:"amber",unreadable:"amber"};
var SURF_LABEL = {rendered:"Accepted",accepted:"Accepted",published:"Published, checked not gated",rejected:"Rejected",trace_failed:"Trace failed",not_rendered:"Accepted, not rendered",unreadable:"Unreadable"};
function surfTone(s){return SURF_TONE[s.status]||"grey";}
function surfLabel(s){var l=SURF_LABEL[s.status]; if(!l&&s.status&&s.status.indexOf("waiting:")===0) l="Waiting for "+stageName(s.status.slice(8)); return l||s.status;}
function keepScroll(id, fn){var b=$(id), top=b?b.scrollTop:0; fn(); b=$(id); if(b) b.scrollTop=top;}

function surfaceChecks(s){var c=el("div","checks"); c.id="surface-checks";
  if(s.failure&&s.failure.reason){var n=el("div","notice t-amber"); n.appendChild(el("span",null,"Stopped at "+(s.failure.stage?stageName(s.failure.stage):"?")+" ("+(s.failure.kind||"unknown")+"): "+s.failure.reason)); c.appendChild(n);}
  (s.reasons||[]).forEach(function(r){if(s.failure&&s.failure.reason&&s.failure.reason.indexOf(r)>=0) return; var n=el("div","notice t-amber"); n.appendChild(el("span",null,"QA: "+r)); c.appendChild(n);});
  (s.warnings||[]).forEach(function(w){var n=el("div","notice t-amber"); n.appendChild(el("span",null,"Warning: "+w)); c.appendChild(n);});
  var dl=el("dl","kv");
  if(s.trace) kv(dl,"Trace",[s.trace.area_cm2!=null?fmt(s.trace.area_cm2,3)+" cm²":null, s.trace.valid_fraction!=null?pct(s.trace.valid_fraction)+" valid":null, Array.isArray(s.trace.grid_rows_cols)?("grid "+s.trace.grid_rows_cols.join(" x ")):null,
    s.trace.partial?("partial ("+s.trace.partial+"), generation "+(s.trace.generations_done!=null?s.trace.generations_done:"?")+(s.trace.generations_planned!=null?" of "+(s.trace.generations_planned-1):"")):null,
    s.trace.seconds_per_generation!=null?(fmt(s.trace.seconds_per_generation,0)+" s a generation lately"):null].filter(Boolean).join(", "));
  if(s.seed_index!=null) kv(dl,"Seed","#"+s.seed_index+(s.seed?(" at ["+s.seed.map(function(v){return Math.round(v);}).join(", ")+"]"):"")+(s.repeat?(", repeat "+s.repeat):""));
  if(s.rule_verdict) kv(dl,"Trace rule",s.rule_verdict+" (recorded, not gated)");
  if(s.method){kv(dl,"Trace method",s.method.name); Object.keys(s.method.summary||{}).forEach(function(k){kv(dl,"  "+k,String(s.method.summary[k]));});}
  if(s.bench) kv(dl,"Winding bench",(s.bench.verdict||"N/A")+(s.bench.valid===false?" (not valid)":""));
  if(s.flatten) kv(dl,"Flatten",cap([s.flatten.used, s.flatten.passes===true?"limits pass":s.flatten.passes===false?"limits fail":null, s.flatten.p95_stretch!=null?"p95 stretch "+fmt(s.flatten.p95_stretch,3):null, s.flatten.shear_p95!=null?"p95 shear "+fmt(s.flatten.shear_p95,1)+" deg":null].filter(Boolean).join(", ")));
  if(s.render){var r=s.render; kv(dl,"Render",[r.rendered?"Rendered":"Not rendered", r.exit!=null?"exit "+r.exit:null, r.audit_verdict?"chunk audit "+r.audit_verdict:null, r.missing_fraction!=null?pct(r.missing_fraction)+" chunks missing":null].filter(Boolean).join(", "));
    if(r.order) kv(dl,"Layer order",cap(r.order));
    if(r.published_check!==undefined&&r.published_check!==null) kv(dl,"Against published",r.published_check===true?"Matches":r.published_check===false?"Differs":String(r.published_check));
    else if(r.published_check_note) kv(dl,"Against published",cap(r.published_check_note));
    if(r.trim) kv(dl,"Trim",(r.trim.used?"Trimmed":"Not trimmed")+(r.trim.area_share!=null?", keeps "+pct(r.trim.area_share):"")+(r.trim.why?": "+r.trim.why:""));
    if(r.snap_check!==null&&r.snap_check!==undefined) kv(dl,"Snap check",r.snap_check===true?"Passed":r.snap_check===false?"Failed":String(r.snap_check));
    if(r.refused) kv(dl,"Refused",cap(r.refused)); if(r.failure) kv(dl,"Render failure",cap(r.failure)); if(r.warning) kv(dl,"Audit",cap(r.warning));}
  if(dl.childNodes.length) c.appendChild(dl);
  return c;}

function surfaceHero(s, used, box){var tone=surfTone(s);
  var hd=el("div","shd "+tonecls(tone)); hd.appendChild(el("span","sid",s.id));
  if(s.origin){var o=el("span","orig ell",cap(s.origin)); o.title=cap(s.origin); hd.appendChild(o);}
  hd.appendChild(el("span","spacer")); hd.appendChild(el("span","chip "+tonecls(tone),surfLabel(s))); box.appendChild(hd);
  var st=el("div","stage3d");
  if(s.wire&&(typeof s.wire!=="string"||s.wire.indexOf("wire/")===0)) st.appendChild(wireFigure(s, used));
  else st.appendChild(el("div","empty",(S.thumbs||{}).enabled===false?"No 3D view: "+((S.thumbs||{}).why||"thumbnails are off for this run")+".":"No 3D view yet: the traced mesh is not in this folder."));
  box.appendChild(st);
  box.appendChild(surfaceChecks(s));}

function inkPanel(s, box){var used=inkPanel.used;
  $("ink-for").textContent=s?("surface "+s.id):"";
  if(!s){box.appendChild(el("div","sec","No surface yet.")); return;}
  if(!(s.ink||[]).length&&s.status==="rendered"&&(S.thumbs||{}).enabled&&isRunning()&&!noNews()&&S.current.stage==="ink"){
    var wi=el("div","part"); var wih=el("div","subhd"); wih.appendChild(el("span","label","Ink maps")); wih.appendChild(pill("Waiting for the Ink stage","grey",true)); wi.appendChild(wih);
    var sk=el("div","skel"); sk.setAttribute("aria-hidden","true"); sk.appendChild(el("div","sk")); sk.appendChild(el("div","sk")); wi.appendChild(sk); box.appendChild(wi);}
  (s.ink||[]).forEach(function(m){var sub=el("div","part"); var h=el("div","subhd"); h.appendChild(el("span","label",m.model)); h.appendChild(pill("Model output","amber",true)); sub.appendChild(h);
    var cr=(m.comparison||{}).r, th=m.threshold!=null?m.threshold:0.5;
    var line="Exit "+(m.exit==null?"N/A":m.exit)+"; maps: "+((m.variants||[]).map(function(v){return VARIANT[v]||v;}).join(", ")||"none");
    if(m.thumbs&&m.thumbs.f){var tg=el("div","thumbs"); [["f","Forward"],["r","Reversed control, same scale"]].forEach(function(v){var src=m.thumbs[v[0]]; if(!src||!(src.indexOf("thumb/")===0||src.indexOf("data:image/png;base64,")===0)) return;
      var f=el("figure"); f.appendChild(thumbFrame(thumbImg(src, s.id+" "+m.model+" "+v[1]+" map, model output", used))); f.appendChild(el("figcaption",null,v[1])); tg.appendChild(f);}); sub.appendChild(tg);}
    if(cr) line+="; share of pixels above "+th+" (how much each map marks, not a score): forward "+pct(cr.forward_share_above)+", reversed "+pct(cr.control_share_above);
    sub.appendChild(el("div","fine",line));
    (m.warnings||[]).forEach(function(w){sub.appendChild(el("div","fine","Warning: "+w));});
    box.appendChild(sub);});
  if((s.scores||[]).length){var sb=el("div","part"); var h2=el("div","subhd"); h2.appendChild(el("span","label","Scores")); h2.appendChild(pill("Model output","amber",true)); sb.appendChild(h2);
    s.scores.forEach(function(r){var row=el("div","scorerow"); row.appendChild(el("div","fine",(r.model||"All models")+(r.scope?(" | "+r.scope):"")));
      if(r.error){row.appendChild(el("div",null,"Error: "+r.error));}
      else if(r.scorable===false){row.appendChild(el("div",null,"Not scored: "+(r.why||"")));}
      else {var g=el("div","cmp"); [["Forward AUC",r.forward_auc],["Reversed control AUC",r.control_auc]].forEach(function(x){var d=el("div"); d.appendChild(el("div","label",x[0])); d.appendChild(el("b","num",fmt(x[1],3))); g.appendChild(d);}); row.appendChild(g);
        var xs=[]; if(r.shuffled_auc!=null) xs.push("Shuffled "+fmt(r.shuffled_auc,3)); if(r.displaced_auc!=null) xs.push("Displaced labels "+fmt(r.displaced_auc,3)); if(r.reference_auc!=null) xs.push("Published map on the same pixels "+fmt(r.reference_auc,3));
        if(xs.length) row.appendChild(el("div","fine num",xs.join("  |  ")));}
      sb.appendChild(row);});
    sb.appendChild(el("div","fine","Pixel AUC against published labels; the reversed control should sit near or below 0.5."));
    box.appendChild(sb);}
  else if((s.ink||[]).length||s.published){var nsc=S.scores_file||{}; if(nsc.skipped) box.appendChild(el("div","fine","Not scored: "+nsc.skipped));}
  if((s.ink||[]).length) box.appendChild(el("div","fine","Model output, not a reading."));
  else if(!box.childNodes.length) box.appendChild(el("div","sec",s.status==="rendered"?"No ink maps yet for "+s.id+".":"No ink maps for "+s.id+": "+cap(surfLabel(s))+"."));}

function surfaces(){var list=S.surfaces||[], used={}, pick=$("surf-pick"), act=document.activeElement;
  var focusId=act&&act.dataset&&act.dataset.surface, left=pick.scrollLeft;
  $("surf-count").textContent=list.length?(list.length+(S.surfaces_truncated?" (first 300)":"")):"";
  if(!list.some(function(x){return x.id===selectedSurface;})) selectedSurface=list.length?list[0].id:"";
  clear(pick); pick.classList.toggle("hidden",list.length<2);
  list.forEach(function(s){var b=el("button","spick "+tonecls(surfTone(s))); b.type="button"; b.dataset.surface=s.id;
    b.setAttribute("aria-pressed",String(s.id===selectedSurface)); b.title=s.id+": "+surfLabel(s); b.appendChild(el("i")); b.appendChild(document.createTextNode(s.id));
    b.onclick=function(){selectedSurface=s.id; surfaces(); var c=pick.querySelector('[aria-pressed="true"]'); if(c) c.scrollIntoView({block:"nearest",inline:"nearest"});};
    pick.appendChild(b); if(focusId===s.id) b.focus({preventScroll:true});});
  pick.scrollLeft=left;
  var s=list.find(function(x){return x.id===selectedSurface;});
  keepScroll("surface-checks",function(){var box=clear($("surfaces"));
    if(!s){var st=el("div","stage3d"); st.appendChild(el("div","empty",S.phase==="not_started"?"No surface yet: the run has not started.":"No surface yet: the trace stage has not recorded one.")); box.appendChild(st);}
    else surfaceHero(s, used, box);});
  inkPanel.used=used; keepScroll("ink",function(){inkPanel(s, clear($("ink")));});
  Object.keys(IMGS).forEach(function(k){if(!used[k]) delete IMGS[k];});
  Object.keys(WIRES).forEach(function(k){if(!used["wire:"+k]) delete WIRES[k];});
  wireAll();
  var t=S.thumbs||{};
  var anyMaps=list.some(function(x){return (x.ink||[]).some(function(m){return (m.variants||[]).length;});});
  var anyThumb=list.some(function(x){return (x.ink||[]).some(function(m){return m.thumbs&&m.thumbs.f;});});
  var tn=$("thumbnote");
  tn.textContent=anyThumb?(t.why||" high model score. Thumbnails: forward and reversed control drawn on the forward map's scale.")
    :!anyMaps?"":!t.enabled?("No thumbnails: "+(t.why||"turned off")):"No thumbnails: the map files are not in this folder.";
  if(anyThumb&&!t.why){var ks=el("span","inkscale"); ks.appendChild(el("span",null,"Low")); ks.appendChild(el("i")); tn.insertBefore(ks,tn.firstChild);}
  quick();}

var logTab = "events";   // the log panel shows the run's events (filterable), the newest tool log or the console's jobs
function setTab(t){logTab=t; ["events","tool","jobs"].forEach(function(k){$("tab-"+k).setAttribute("aria-pressed",String(t===k));}); logs(); if(t==="jobs") jobsView(true);}
function stuck(box){return !box.dataset.seen||box.scrollHeight-box.scrollTop-box.clientHeight<60;}
function logs(){var box=$("log"), ev=S.events||{}, stick=stuck(box); clear(box);
  var query=$("log-search").value.toLowerCase(), kind=$("log-kind").value, all=ev.lines||[];
  var lines=all.filter(function(l){return (!selectedStage||l.stage===selectedStage)&&
    (kind!=="events"||l.kind==="event")&&(kind!=="failures"||["failed","crashed","interrupted"].indexOf(l.event)>=0)&&
    (!query||String(l.msg||"").toLowerCase().indexOf(query)>=0);});
  $("log-count").textContent=lines.length+" of "+all.length+" loaded lines"+(ev.truncated?"; earlier lines are not loaded":"")+(ev.gridstore_left_out?"; "+ev.gridstore_left_out+" GridStore cache warnings left out":"");
  if(!ev.present){box.appendChild(el("span","ts",S.phase==="not_started"?"No events yet: the run has not started.\n":"This run keeps no event log (made before the monitor existed); stage records come from state.json.\n"));}
  else{ if(ev.truncated) box.appendChild(el("span","ts","... earlier lines in events.jsonl\n"));
    if(!lines.length) box.appendChild(el("span","ts","No loaded log lines match these filters. Clear filters to see the full tail.\n"));
    lines.forEach(function(l){box.appendChild(el("span","ts",clock(l.t)+"  ")); var cls=l.kind==="event"?((l.event==="failed"||l.event==="crashed"||l.event==="interrupted")?"bad":"ev"):null;
      box.appendChild(el("span",cls,(l.msg||"")+"\n"));});}
  if(stick) box.scrollTop=box.scrollHeight; box.dataset.seen="1";
  var tl=S.tool_log, tb=$("toollog"), tstick=stuck(tb); clear(tb);
  $("tab-tool").disabled=!tl; if(!tl&&logTab==="tool"){logTab="events"; $("tab-events").setAttribute("aria-pressed","true"); $("tab-tool").setAttribute("aria-pressed","false");}
  var onTool=logTab==="tool"; box.classList.toggle("hidden",logTab!=="events"); $("log-controls").classList.toggle("hidden",logTab!=="events");
  $("jobs-pane").classList.toggle("hidden",logTab!=="jobs");
  $("toolhd").classList.toggle("hidden",!tl||!onTool);
  if(tl){$("toolpath").textContent=tl.path+" (newest tool log"+(tl.gridstore_left_out?", "+tl.gridstore_left_out+" GridStore cache warnings left out":", unfiltered")+"; it may belong to another stage)"; tb.textContent=(tl.lines||[]).join("\n"); tb.classList.toggle("hidden",!onTool);
    if(tstick) tb.scrollTop=tb.scrollHeight; tb.dataset.seen="1";} else tb.classList.add("hidden");}

// ---------------------------------------------------------------- console: tools, notes, files (kit/apconsole.py)
var CON = JSON.parse(document.getElementById("console").textContent||"{}");
var conTab = "tools", JOBS = [], jobSel = "", jobBusy = false, conBusy = false, notesDirty = false, notesTimer = null, resumeOk = false;
var QUICK = [["VC3D window",'app_open surfaces=["{surface}"] display=true',"surface","Open the chosen surface in the VC3D app's window on this machine"],
  ["VC3D headless",'app_open surfaces=["{surface}"]',"surface","Open the chosen surface in VC3D offscreen and take a screenshot"],
  ["Check surface","check_surface surface={surface}","surface","Grid sanity and self-intersections of the chosen surface (nothing is changed)"],
  ["Inspect","inspect path={surface}","surface","Grid, valid fraction, extent and area of the chosen surface"],
  ["AP status","ap status {run}","run","AutoPipeline's status of this run"],
  ["AP resume","ap run {run}","resume","Resume this run where it stopped (a background job; cancel it in Log, Jobs)"]];
function conOn(){return LIVE&&CON.on===true;}
function api(method, path, body){var h={"X-AP-Token":CON.token||""}, o={method:method,headers:h,cache:"no-store",credentials:"same-origin"};
  if(body!==undefined){h["Content-Type"]="application/json"; o.body=JSON.stringify(body);}
  return fetch(path,o).then(function(r){return r.json().catch(function(){return {error:"HTTP "+r.status};})
    .then(function(j){if(!r.ok) throw new Error(j.error||("HTTP "+r.status)); return j;});});}
function setConTab(t){conTab=t; ["tools","notes","files"].forEach(function(k){$("tab-con-"+k).setAttribute("aria-pressed",String(t===k)); $("con-"+k).classList.toggle("hidden",t!==k);});}
function quick(){var box=clear($("quick")), surf=(S.surfaces||[]).find(function(x){return x.id===selectedSurface;});
  QUICK.forEach(function(q){var b=el("button","action",q[0]); b.type="button"; b.title=q[3]+": "+q[1]; b.dataset.command=q[1];
    b.disabled=!conOn()||(q[2]==="surface"&&!surf)||(q[2]==="resume"&&!resumeOk);
    if(q[2]==="resume"&&!resumeOk&&conOn()) b.title="Resume unavailable now: Files says why";
    b.onclick=function(){$("con-input").value=q[1]; runCommand(q[1]);}; box.appendChild(b);});
  $("con-help").textContent=!LIVE?"A snapshot runs nothing. Open the live monitor (python -m kit autopipeline monitor RUN) to use the console.":
    !conOn()?"Console off: "+(CON.why||"this server is read only")+".":
    "{run} is this run folder, {surface} "+(surf?surf.id+" (chosen in 02)":"the surface chosen in 02")+". Each command runs in the background on this machine; its output is in Log, Jobs.";}
function runCommand(cmd){if(!conOn()) return; var msg=$("con-msg"); cmd=String(cmd||"").trim(); if(!cmd){msg.textContent="Type a command first."; return;}
  var body={command:cmd}; if(cmd.indexOf("{surface}")>=0) body.surface=selectedSurface;
  $("con-run").disabled=true; msg.textContent="Starting: "+cmd;
  api("POST","api/run",body).then(function(j){STARTED[j.job]={job:j.job,tool:j.tool,status:"running",command:j.command,created:j.job.replace(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d).*/,"$1-$2-$3T$4:$5:$6")}; mergeJobs(JOBS);
    msg.textContent="Started job "+j.job+" ("+j.tool+"). Its output is in Log, Jobs."; jobSel=j.job; setTab("jobs"); consolePoll(true);})
  .catch(function(e){msg.textContent="Not started: "+e.message;}).finally(function(){$("con-run").disabled=false;});}
var STARTED = {};   // jobs this page started that a poll in flight may not list yet
function mergeJobs(list){JOBS=list.slice(); Object.keys(STARTED).forEach(function(k){
  if(JOBS.some(function(x){return x.job===k;})) delete STARTED[k]; else JOBS.unshift(STARTED[k]);});}
function hhmm(t){var m=/T(\d\d:\d\d:\d\d)/.exec(String(t||"")); return m?m[1]:"";}
function jobsView(fetchNow){var box=clear($("jobs"));
  if(!conOn()){box.appendChild(el("div","empty",!LIVE?"A snapshot has no jobs.":"Console off: no jobs.")); $("jobhd").textContent=""; clear($("joblog")); return;}
  if(!JOBS.length) box.appendChild(el("div","empty","No jobs yet. Run a command in 05 Console, Tools."));
  if(!JOBS.some(function(j){return j.job===jobSel;})) jobSel=JOBS.length?JOBS[0].job:"";
  JOBS.forEach(function(j){var b=el("button","jobrow"); b.type="button"; b.dataset.job=j.job; b.setAttribute("aria-pressed",String(j.job===jobSel));
    var tone=j.status==="succeeded"?"mint":j.status==="running"?"blue":j.status==="cancelled"?"grey":"amber";
    b.appendChild(el("span","chip "+tonecls(tone),cap(j.status||"")));
    b.appendChild(el("span","ell",j.command||j.tool)); b.appendChild(el("span","tm",hhmm(j.created)));
    var x=el("span","x","Cancel"); if(j.status!=="running") x.style.visibility="hidden";
    x.onclick=function(ev){ev.stopPropagation(); api("POST","api/cancel",{job:j.job}).then(function(){consolePoll(true);}).catch(function(e){$("jobhd").textContent="Not cancelled: "+e.message;});};
    b.appendChild(x); b.onclick=function(){jobSel=j.job; jobsView(true);}; box.appendChild(b);});
  if(!jobSel){$("jobhd").textContent=""; clear($("joblog"));}
  if(fetchNow) jobDetail();}
function jobDetail(){if(!conOn()||!jobSel||jobBusy) return; jobBusy=true; var want=jobSel;
  api("GET","api/job?id="+encodeURIComponent(want)).then(function(j){if(want!==jobSel) return; var lg=$("joblog"), stick=stuck(lg);
    $("jobhd").textContent=(j.command||j.tool)+"  |  "+cap(j.status||"")+(j.finished?" at "+hhmm(j.finished):"")+(j.error?"  |  "+j.error:"")+"  |  "+j.log;
    lg.textContent=(j.log_tail||"")+(j.output?"\n\noutput:\n"+j.output:"")+(j.result?"\n\nresult:\n"+j.result:"");
    if(lg.dataset.job!==j.job){lg.dataset.job=j.job; lg.scrollTop=j.status==="running"?lg.scrollHeight:0;} else if(stick&&j.status==="running") lg.scrollTop=lg.scrollHeight; lg.dataset.seen="1";
    var row=JOBS.find(function(x){return x.job===j.job;}); if(row&&row.status!==j.status){row.status=j.status; row.finished=j.finished; jobsView(false);}
    if(j.status==="running") setTimeout(function(){if(logTab==="jobs"&&jobSel===want) jobDetail();},1500);})
  .catch(function(e){$("jobhd").textContent="Job unreadable: "+e.message;}).finally(function(){jobBusy=false;});}
function notesMsg(t){$("notes-msg").textContent=t;}
function saveNotes(){if(!conOn()||!notesDirty) return; var text=$("notes").value; notesDirty=false;
  api("POST","api/notes",{text:text}).then(function(j){notesMsg(j.saved?"Saved "+new Date(j.saved*1000).toLocaleTimeString():"Empty: nothing kept");})
  .catch(function(e){notesDirty=true; notesMsg("Not saved: "+e.message);});}
function consolePoll(force){if(!conOn()||conBusy) return; conBusy=true;
  api("GET","api/console").then(function(j){mergeJobs(j.jobs||[]);
    var n=$("notes"); if(!notesDirty&&document.activeElement!==n&&n.value!==(j.notes.text||"")) n.value=j.notes.text||"";
    if(!notesDirty&&j.notes.saved&&!$("notes-msg").textContent) notesMsg("Saved "+new Date(j.notes.saved*1000).toLocaleTimeString());
    $("tab-jobs").textContent=JOBS.some(function(x){return x.status==="running";})?"Jobs *":"Jobs";
    if(logTab==="jobs") jobsView(true);})
  .catch(function(){}).finally(function(){conBusy=false;});}
function consoleInit(){var dl=$("con-list"), chips=$("toolchips"); (CON.tools||[]).forEach(function(t){var o=el("option"); o.value=t.name+" "; o.label=t.title; dl.appendChild(o);
    var c=el("button",null,t.name); c.type="button"; c.title=t.title; c.onclick=function(){var f=$("con-input"); f.value=t.name+" "; f.focus();}; chips.appendChild(c);});
  if(!conOn()) $("toolchips").closest(".toolref").classList.add("hidden");
  $("tab-con-tools").onclick=function(){setConTab("tools");}; $("tab-con-notes").onclick=function(){setConTab("notes");}; $("tab-con-files").onclick=function(){setConTab("files");};
  $("tab-jobs").onclick=function(){setTab("jobs");};
  $("con-form").addEventListener("submit",function(ev){ev.preventDefault(); runCommand($("con-input").value);});
  var n=$("notes");
  if(conOn()){$("brand-sec").textContent="one run folder; console on this machine";
    $("foot-local").textContent="Local only: reads one run folder and runs console commands on this machine; sends nothing elsewhere.";
    n.addEventListener("input",function(){notesDirty=true; notesMsg("Editing"); if(notesTimer) clearTimeout(notesTimer); notesTimer=setTimeout(saveNotes,1200);});
    n.addEventListener("blur",saveNotes); window.addEventListener("pagehide",saveNotes);
    consolePoll(true); setInterval(function(){consolePoll(false);},3000);
    }
  else{n.readOnly=true; $("con-input").disabled=true; $("con-run").disabled=true;
    if(CON.snapshot){n.value=CON.notes||""; $("notes-label").textContent=CON.notes?"Notes on this run as they were when the snapshot was made (read only)":"Notes are not in this snapshot (make one with --with-notes)";}
    else $("notes-label").textContent="Console off: "+(CON.why||"this server is read only");
    $("con-sec").textContent=LIVE?"off on this server":"snapshot: runs nothing";}
  setConTab("tools");}

function chooseStage(name){selectedStage=name; $("stage-filter").value=name; timeline(); stageDetail(); logs();}
function stageDetail(){var row=(S.stages||[]).find(function(r){return r.name===selectedStage;});
  var box=clear($("stage-detail"));
  box.classList.toggle("hidden",!row);
  if(!row){box.appendChild(el("span","sec","Choose a stage, here or on the rail above, to inspect it and filter the log. Nothing in the run is changed.")); return;}
  box.appendChild(el("h4",null,stageName(row.name))); var dl=el("dl","kv"); box.appendChild(dl);
  kv(dl,"Status",STAGE_LABEL[rowStatus(row)]||rowStatus(row)); kv(dl,"Started",row.started); kv(dl,"Ended",row.ended);
  kv(dl,"Duration",row.seconds==null?"Not recorded":dur(row.seconds)); kv(dl,"Details",row.error||row.why||row.summary||"No result recorded yet.");
  if(row.kind) kv(dl,"Failure type",row.kind==="ours"?"The plan's acceptance rule refused this result. Inspect inputs or make a new plan; do not erase the failure.":"Infrastructure: fix the tool, input or machine problem before resuming.");
  var failures=(S.surfaces||[]).filter(function(s){return s.failure&&s.failure.stage===row.name;});
  failures.slice(0,6).forEach(function(s){kv(dl,"Surface "+s.id,s.failure.reason||(s.reasons||[]).join("; ")||"See this surface's checks below.");});
  if(failures.length>6) kv(dl,"More surfaces",String(failures.length-6)+" additional failures in the surface cards below.");
  if(row.name==="qa"&&(row.status==="failed"||failures.length)) kv(dl,"Geometry review","Inspect the flagged surface in VC3D against neighboring CT slices. Check that it follows the same papyrus sheet before editing or tracing again. These records do not identify which region needs repair.");
  if(row.job) kv(dl,"Runner job",row.job);}
function fileList(){var list=clear($("run-files"));
  [["plan.json",!!(S.plan&&!S.plan.error),S.plan&&S.plan.error], ["state.json",S.state&&S.state.present,S.state&&S.state.error],
   ["report.json",S.report&&S.report.present,S.report&&S.report.error], ["scores.json",S.scores_file&&S.scores_file.present,S.scores_file&&S.scores_file.error],
   ["events.jsonl (and .1)",S.events&&S.events.present,null]].forEach(function(f){var row=el("div","file-row");
     row.appendChild(el("code",null,f[0])); row.appendChild(el("span","fine",f[2]?"Unreadable / refused":f[1]?"Recorded":"Not recorded"));
     if(f[2]) row.appendChild(el("span","fine wrapany",f[2])); list.appendChild(row);});}
function shellQuote(s){return "'"+String(s).replace(/'/g,"'\\''")+"'";}
function commands(){var failed=(S.stages||[]).find(function(r){return r.status==="failed";});
  var usable=LIVE&&S.folder&&S.plan&&!S.plan.error&&!(S.state&&S.state.error);
  var stale=Date.now()-lastOk>=30000;
  var resume=usable&&!lost&&!pausedAt&&!stale&&["not_started","paused","stopped","handoff","failed"].indexOf(S.phase)>=0&&!(failed&&failed.kind==="ours");
  var why=!usable?"The run's records are incomplete or unreadable.":pausedAt?"Resume viewer updates to check the current run state first.":
    lost||stale?"Reconnect and refresh the run state first.":failed&&failed.kind==="ours"?"The plan's acceptance rule refused this result; inspect inputs or make a new plan.":
    S.phase==="finished"?"This run has finished.":"This run may still be active. Inspect its stage and process before resuming.";
  $("status-command").disabled=!usable; $("resume-command").disabled=!resume; if(resumeOk!==!!resume){resumeOk=!!resume; quick();}
  $("command-note").textContent=!LIVE?"Snapshots omit the run path. Open the local live monitor to prepare a command.":
    "For bash or zsh with AutoPipeline installed; copying runs nothing. Resume needs the original inputs and tools, and handed-off ink its GPU setup."+
    (!resume?" Resume unavailable: "+why:"");
  if(!resume&&$("command-text").dataset.action==="run"){$("command-text").value=""; $("copy-command").disabled=true;}}
function prepareCommand(action){$("command-text").value="scrolls-kit autopipeline "+action+" "+shellQuote(S.folder);
  $("command-text").dataset.action=action; $("copy-command").disabled=false; $("copy-message").textContent="Review the command, then copy it into your terminal.";}
function copyCommand(){var field=$("command-text"), value=field.value;
  function manual(){field.focus(); field.select(); $("copy-message").textContent="Clipboard unavailable. The command is selected; press Ctrl+C or Command+C to copy.";}
  if(!value) return; if(!navigator.clipboard||!navigator.clipboard.writeText){manual(); return;}
  navigator.clipboard.writeText(value).then(function(){$("copy-message").textContent="Command copied. Paste it into your terminal when ready.";},manual);}
function render(){var rows=S.stages||[], select=$("stage-filter");
  if(Array.from(select.options).slice(1).map(function(o){return o.value;}).join(",")!==rows.map(function(r){return r.name;}).join(",")){
    clear(select); var all=el("option",null,"All stages"); all.value=""; select.appendChild(all);
    rows.forEach(function(r){var option=el("option",null,stageName(r.name)); option.value=r.name; select.appendChild(option);});
    if(!rows.some(function(r){return r.name===selectedStage;})) selectedStage=""; select.value=selectedStage;}
  $("inspect-problem").disabled=!rows.some(function(r){return ["failed","stopped","unknown","handoff","running","quiet"].indexOf(rowStatus(r))>=0;});
  header(); liveLabel(); banner(); notices(); stats(); timeline(); stageDetail(); surfaces(); logs(); fileList(); commands();}

// the export leaves out the folder's path, the host and the process id (the server's share view, or the same
// fields cleared here when the server is gone); log lines and records stay as the page shows them
function exportJson(){
  function save(obj){try{var o=JSON.parse(JSON.stringify(obj)); o.folder=o.name; if(o.current){o.current.pid=null; o.current.host=null;}
    var blob=new Blob([JSON.stringify(o,null,1)],{type:"application/json"}); var a=document.createElement("a");
    a.href=URL.createObjectURL(blob); a.download="autopipeline-"+((o.plan&&o.plan.short)||"run")+"-summary.json"; document.body.appendChild(a); a.click();
    setTimeout(function(){URL.revokeObjectURL(a.href); a.remove();},1000);}catch(e){}}
  if(!LIVE||lost){save(S); return;}
  fetch("summary.json?share=1",{cache:"no-store",credentials:"same-origin"}).then(function(r){if(!r.ok) throw new Error(r.status); return r.json();})
  .then(save).catch(function(){save(S);});}

function poll(force){if(!LIVE||polling||(pausedAt&&!force)) return; if(document.hidden&&!force){schedule(4000); return;}
  polling=true; $("refresh-now").disabled=true;
  var controller=new AbortController(), deadline=setTimeout(function(){controller.abort();},10000);
  fetch("summary.json",{cache:"no-store",credentials:"same-origin",signal:controller.signal}).then(function(r){if(!r.ok) throw new Error(r.status); return r.json();})
  .then(function(j){if(pausedAt&&!force) return; S=j; lost=false; misses=0; lastOk=Date.now(); fetchedAt=Date.now(); if(pausedAt) pausedAt=Date.now(); render(); schedule(["running","quiet","not_started"].indexOf(S.phase)>=0?2000:10000);})
  .catch(function(){var was=lost; lost=true; misses++; if(!was) render(); else {liveLabel(); banner(); notices();}
    schedule(ended()?Math.min(60000,5000*misses):5000);})
  .finally(function(){clearTimeout(deadline); polling=false; $("refresh-now").disabled=false;});}
function schedule(ms){if(timer) clearTimeout(timer); if(!pausedAt) timer=setTimeout(function(){poll(false);},ms);}

theme(); $("export").addEventListener("click",exportJson);
$("stage-filter").onchange=function(){chooseStage(this.value);}; $("log-search").oninput=logs; $("log-kind").onchange=logs;
$("clear-filters").onclick=function(){$("log-search").value=""; $("log-kind").value="all"; chooseStage("");};
$("inspect-problem").onclick=function(){var row=(S.stages||[]).find(function(r){return ["failed","stopped","unknown","handoff","running","quiet"].indexOf(rowStatus(r))>=0;});
  if(row){chooseStage(row.name); $("stage-detail").scrollIntoView({block:"nearest"}); $("stage-detail").focus({preventScroll:true});}
  else{$("copy-message").textContent="No failed, stopped, handed-off or running stage in the loaded state.";}};
$("status-command").onclick=function(){prepareCommand("status");}; $("resume-command").onclick=function(){prepareCommand("run");};
$("copy-command").onclick=copyCommand;
$("tab-events").onclick=function(){setTab("events");}; $("tab-tool").onclick=function(){setTab("tool");};
consoleInit();
$("pause-view").disabled=!LIVE; $("refresh-now").disabled=!LIVE;
$("pause-view").onclick=function(){pausedAt=pausedAt?null:Date.now(); if(timer) clearTimeout(timer);
  this.textContent=pausedAt?"Resume view":"Pause view"; this.title=pausedAt?"Resume viewer updates":"Pause viewer updates (the run goes on)"; this.setAttribute("aria-pressed",String(!!pausedAt));
  render(); if(!pausedAt) poll(true);}; $("refresh-now").onclick=function(){poll(true);};
render();
window.addEventListener("resize",wireAll);
try{window.matchMedia("(prefers-color-scheme: light)").addEventListener("change",wireAll);}catch(e){}
setInterval(function(){liveLabel(); tickElapsed(); commands();},1000);
document.addEventListener("visibilitychange",function(){if(!document.hidden) schedule(50);});
if(LIVE) schedule(2000);
})();
"""

_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="referrer" content="no-referrer">
%CSPMETA%<title>AP Monitor</title>
<style>%CSS%</style>
</head>
<body>
<div class="wrap">
<header class="top">
 <div class="idblock">
  <div class="brand"><span class="full">AutoPipeline Monitor</span><span class="short">AP Monitor</span><span class="sl">/</span><span class="sec" style="font-weight:400;font-size:calc(12px*var(--fz))" id="brand-sec">one run folder, read only</span></div>
  <div class="meta"><h1 id="title" class="ell">run</h1><span class="capsule"><span class="pill" id="h-sample">sample</span><span class="pill" id="h-volume">volume</span><span class="pill" id="h-digest">plan</span></span>
   <span id="target" class="hidden"><span class="pill amber tag">Target run: maps stay private</span></span>
   <span class="ell" id="subtitle"></span></div>
  <div class="meta"><span class="ell" id="folder"></span></div>
 </div>
 <section class="stats" id="stats" aria-label="Run numbers"></section>
</header>
<section class="statusrow" aria-label="Run state">
 <div id="banner" class="banner t-grey" role="status" aria-live="polite">
  <div class="btile" id="b-icon" aria-hidden="true"></div>
  <div class="btext" style="min-width:0;flex:1 1 auto"><h2 id="b-title">Reading the run folder</h2><p id="b-detail" class="wrapany"></p></div>
  <span class="badge" id="b-badge"></span>
 </div>
 <nav class="strip" id="strip" aria-label="Stages: choose one to inspect it"></nav>
 <div class="live">
  <div class="livelab"><span class="dot" id="livedot"></span><span id="livetext">Loading</span><span id="updated"></span></div>
  <div class="tools">
   <details class="notices-wrap hidden" id="notice-box"><summary class="pill" id="notice-sum"></summary><div class="notices" id="notices"></div></details>
   <button class="action" id="inspect-problem" type="button" title="Inspect the current or stopped stage">Inspect</button>
   <button class="action" id="pause-view" type="button" aria-pressed="false" title="Pause viewer updates (the run goes on)">Pause view</button>
   <button class="action" id="refresh-now" type="button">Refresh</button>
   <button class="icon" id="export" type="button" title="Export the summary as JSON: the run's records and log lines, without the folder's path, the host or the process id" aria-label="Export the summary as JSON">%EXPORT%</button>
   <button class="ghost" id="theme" type="button" aria-label="Color theme">Theme: auto</button>
  </div>
 </div>
</section>
<section class="main">
 <section class="card" aria-label="Stage timeline">
  <div class="hd"><h3><span class="ix">01</span>Stages</h3><span class="sec">latest attempt of each; choose one to inspect it</span></div>
  <div class="body">
   <div class="gantt" id="gantt"></div>
   <div class="axis" id="axis"><span></span><span></span><span></span><span class="ticks"><span id="ax0"></span><span id="ax1"></span><span id="ax2"></span></span></div>
  </div>
  <div id="stage-detail" class="inspect" tabindex="-1" aria-label="Selected stage details"></div>
 </section>
 <section class="card" aria-label="Surfaces">
  <div class="hd"><h3><span class="ix">02</span>Surfaces</h3><span class="fine" id="surf-count"></span><span class="spacer"></span><span class="pill amber tag">Model output, not a reading</span></div>
  <div class="picker" id="surf-pick" aria-label="Choose a surface"></div>
  <div class="surface" id="surfaces"></div>
 </section>
 <section class="card" aria-label="Ink maps and scores">
  <div class="hd"><h3><span class="ix">03</span>Ink and control</h3><span class="sec" id="ink-for"></span></div>
  <div class="body" id="ink" style="flex:0 1 auto"></div>
  <div class="fine" id="thumbnote" style="padding:0 10px 6px"></div>
 </section>
</section>
<section class="bottom">
 <section class="card" id="log-section" aria-label="Log">
  <div class="hd"><h3><span class="ix">04</span>Log</h3><span class="sec">local time; &lt;run&gt; is this run folder, &lt;kit&gt; the kit home, ~ the home folder</span>
   <span class="tabs"><button class="action" id="tab-events" type="button" aria-pressed="true">Events</button><button class="action" id="tab-tool" type="button" aria-pressed="false">Tool log</button><button class="action" id="tab-jobs" type="button" aria-pressed="false">Jobs</button></span></div>
  <div class="body">
   <div class="controls" id="log-controls">
    <label>Stage<select id="stage-filter"><option value="">All stages</option></select></label>
    <label>Lines<select id="log-kind"><option value="all">All lines</option><option value="events">Stage events</option><option value="failures">Failure events</option></select></label>
    <label class="search">Search<input id="log-search" type="search" placeholder="tool, error, file"></label>
    <button class="action" id="clear-filters" type="button">Clear filters</button>
    <span class="fine" id="log-count" role="status"></span>
   </div>
   <div class="log" id="log"></div>
   <div id="toolhd" class="hidden"><div class="fine wrapany" id="toolpath"></div></div>
   <div class="log hidden" id="toollog"></div>
   <div class="pane hidden" id="jobs-pane"><div class="jobs" id="jobs"></div><div class="fine wrapany" id="jobhd"></div><div class="log" id="joblog"></div></div>
  </div>
 </section>
 <section class="card" id="files-section" aria-label="Console: tools, notes and files">
  <div class="hd"><h3><span class="ix">05</span>Console</h3><span class="sec" id="con-sec">runs on this machine</span>
   <span class="tabs"><button class="action" id="tab-con-tools" type="button" aria-pressed="true">Tools</button><button class="action" id="tab-con-notes" type="button" aria-pressed="false">Notes</button><button class="action" id="tab-con-files" type="button" aria-pressed="false">Files</button></span></div>
  <div class="body">
   <div class="pane" id="con-tools">
    <div class="quick" id="quick" aria-label="Quick actions on the chosen surface and the run"></div>
    <form class="cmdline" id="con-form" autocomplete="off"><span class="prompt" aria-hidden="true">&gt;</span><label for="con-input" class="hidden">Command</label><input id="con-input" list="con-list" spellcheck="false" placeholder="ap status {run}   kit doctor   inspect path={surface}"><button class="action" id="con-run" type="submit">Run</button></form>
    <datalist id="con-list"></datalist>
    <p class="fine wrapany" id="con-msg" role="status" aria-live="polite" style="margin:0"></p>
    <p class="fine" id="con-help" style="margin:0"></p>
    <div class="toolref"><span class="fine">Every command the box takes; choose one to start a line</span><div class="toolchips" id="toolchips"></div></div>
   </div>
   <div class="pane hidden" id="con-notes">
    <label for="notes" class="fine" id="notes-label">Notes on this run, kept on this machine outside the run folder</label>
    <textarea class="notes" id="notes" spellcheck="true" placeholder="What you saw, what to try next, which surface to open in VC3D"></textarea>
    <span class="fine" id="notes-msg" role="status" aria-live="polite"></span>
   </div>
   <div class="pane hidden" id="con-files">
   <div class="files" id="run-files"></div>
   <div class="controls">
    <button class="action" id="status-command" type="button">Prepare status command</button>
    <button class="action" id="resume-command" type="button">Prepare resume command</button>
   </div>
   <p class="fine" id="command-note" style="margin:0"></p>
   <label for="command-text" class="fine">Terminal command to review</label>
   <div class="controls" style="flex-wrap:nowrap"><textarea class="command" id="command-text" readonly spellcheck="false" rows="1"></textarea><button class="action" id="copy-command" type="button" disabled>Copy command</button></div>
   <span class="fine" id="copy-message" role="status" aria-live="polite"></span>
   </div>
  </div>
 </section>
</section>
<footer><span id="foot-local">Local only: this page reads one folder on this machine and sends nothing anywhere.</span><span>Every map and score is model output, not a reading. Maps of target scrolls must not be shared.</span></footer>
</div>
%TEMPLATES%
<script type="application/json" id="summary">%SUMMARY%</script>
<script type="application/json" id="console">%CONSOLE%</script>
<script>%JS%</script>
</body>
</html>
"""


def _embed(summary):
    """The summary as JSON safe inside a <script> element: <, > and & as \\u escapes."""
    return (json.dumps(summary, default=str, separators=(",", ":")).replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("&", "\\u0026"))


def page(summary, live=True, console=None):
    """The monitor page: one self-contained HTML document with the summary embedded; live pages poll
    summary.json on the server they came from, a snapshot (live=False) makes no request at all. console is what
    Monitor.console_page gives a live page (its token included), or for a snapshot {"on": False, "notes": text}."""
    console = console or {"on": False}
    if not live:
        console = {"on": False, "snapshot": True, "notes": console.get("notes")}
    css = _CSS.replace("%DARK%", _tokens(_DARK)).replace("%LIGHT%", _tokens(_LIGHT))
    js = _JS.replace("%LIVE%", "true" if live else "false")
    meta = "" if live else ('<meta http-equiv="Content-Security-Policy" content="'
                            + CSP.replace("connect-src 'self'", "connect-src 'none'") + '">\n')
    templates = "".join(f'<template id="ic-{k}">{v}</template>' for k, v in _ICONS.items())
    return (_HTML.replace("%CSPMETA%", meta).replace("%CSS%", css).replace("%LOGO%", _ICONS["logo"])
            .replace("%EXPORT%", _ICONS["export"]).replace("%TEMPLATES%", templates).replace("%JS%", js)
            .replace("%SUMMARY%", _embed(summary)).replace("%CONSOLE%", _embed(console)))


# ---------------------------------------------------------------- snapshot

def snapshot(folder, out_file, ctx=None, notes=False, **kw):
    """Write one self-contained HTML page of the run folder (summary and thumbnails embedded) to out_file, which
    must lie outside the run folder and, inside a repository, in a folder git ignores (AGENTS.md rule 6). A
    relative out_file is taken from the current directory. With notes, the run's console notes go in, read only.
    Returns its path."""
    from . import vc3d_agent
    folder = Path(folder).resolve()
    if not (folder / "plan.json").is_file():
        raise MonitorError(f"{folder} has no plan.json; make one with: python -m kit autopipeline plan")
    out = Path(out_file).expanduser()
    out = (Path.cwd() / out if not out.is_absolute() else out).resolve()
    if out == folder or folder in out.parents:
        raise MonitorError(f"{out} is inside the run folder; the monitor never writes there")
    ctx = ctx or vc3d_agent.Context()
    out = vc3d_agent.writable(ctx, out)
    summary = summarize(folder, share=True, **kw)
    state, _, _ = _json_file(folder, "state.json")
    state = _d(state)
    for s in summary.get("surfaces") or []:
        for m in s.get("ink") or []:
            if not m.get("thumbs"):
                continue
            got = {}
            for v in m["thumbs"]:
                png = _thumb_for(folder, state, s["id"], m["model"], v)
                if png:
                    got[v] = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
            m["thumbs"] = got if "f" in got else None
    wired = 0
    for s in summary.get("surfaces") or []:
        if s.get("wire"):
            s["wire"] = _wire_for(folder, state, s["id"]) if wired < WIRE_SNAPSHOT_MAX else None
            wired += s["wire"] is not None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    shown = None
    if notes:
        from . import apconsole
        shown = apconsole.read_notes(ctx, folder)["text"]
    tmp.write_text(page(summary, live=False, console={"notes": shown}), encoding="utf-8")
    os.replace(tmp, out)
    return out


# ---------------------------------------------------------------- server

class _Handler(BaseHTTPRequestHandler):
    server_version = "AutoPipelineMonitor/1"
    sys_version = ""

    def log_message(self, *args):     # the page polls every 2 s: keep the terminal quiet
        pass

    def do_GET(self):
        self.server.monitor.handle(self, head=False)

    def do_HEAD(self):
        self.server.monitor.handle(self, head=True)

    def do_POST(self):
        self.server.monitor.handle_post(self)

    def _refuse(self):
        self.server.monitor.send(self, 405, b"read-only: GET only\n", "text/plain; charset=utf-8",
                                 extra={"Allow": "GET, HEAD"})

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse


class Monitor:
    """An HTTP server of one run folder, which it only reads: the page at /, the summary at /summary.json, ink map
    thumbnails at /thumb/<surface>/<model>/<f|r>.png and traced meshes' wireframes at /wire/<surface>.json (both found
    through state.json, under the thumbnails' rule). With the console on (the default on a loopback address), the
    page's notes and commands go through /api/ (kit/apconsole.py), each request carrying this server's token, which
    only its own live page holds; with it off every POST is refused."""

    def __init__(self, folder, host=LOCAL, port=DEFAULT_PORT, console=None, ctx=None, **kw):
        self.folder = Path(folder).resolve()
        self.kw = kw
        self.host = host
        self.console = _loopback(host) if console is None else bool(console)
        self.token = secrets.token_urlsafe(24)
        self._ctx, self._own_ctx = ctx, ctx is None   # the console's vc3d_agent.Context (made on first use)
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.monitor = self
        self.port = self.httpd.server_address[1]
        shown = "127.0.0.1" if host in ("", "0.0.0.0") else (f"[{host}]" if ":" in host else host)
        self.url = f"http://{shown}:{self.port}/"
        self.thread = None
        self.last_summary = 0.0
        self.last_request = 0.0
        self.served_after_stop = threading.Event()
        self.stopping = False

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.25},
                                       name="autopipeline-monitor", daemon=True)
        self.thread.start()
        return self

    def stop(self, final_wait=3.0, grace=2.0):
        """Stop serving. When a page polled in the last 30 s, wait up to final_wait seconds for its next poll, so it
        shows how the run ended, then until its requests (thumbnails that poll first showed) have been quiet for
        half a second, at most grace seconds more."""
        self.stopping = True
        if final_wait and time.time() - self.last_summary < 30 and self.served_after_stop.wait(final_wait):
            end = time.time() + grace
            while time.time() < end and time.time() - self.last_request < 0.5:
                time.sleep(0.05)
        try:
            self.httpd.shutdown()
        finally:
            self.httpd.server_close()
            if self._ctx is not None and self._own_ctx:
                self._ctx.close()

    def host_ok(self, value):
        """The Host header names this server by an IP address, localhost, the bound host or this machine's name
        (a DNS-rebinding page names it by its own domain and is refused)."""
        if not value:
            return False
        h = value.strip()
        if h.startswith("["):
            h = h[1:h.find("]")] if "]" in h else h
        elif h.count(":") == 1:
            h = h.split(":")[0]
        h = h.lower().rstrip(".")
        try:
            ipaddress.ip_address(h)
            return True
        except ValueError:
            pass
        names = {"localhost", str(self.host).lower()}
        try:
            names |= {socket.gethostname().lower(), socket.getfqdn().lower()}
        except OSError:
            pass
        return h in names

    def send(self, req, code, body, ctype, extra=None, head=False, cache="no-store"):
        req.send_response(code)
        req.send_header("Content-Type", ctype)
        req.send_header("Content-Length", str(len(body)))
        req.send_header("Cache-Control", cache)
        req.send_header("Content-Security-Policy", CSP)
        req.send_header("X-Content-Type-Options", "nosniff")
        req.send_header("Referrer-Policy", "no-referrer")
        req.send_header("Cross-Origin-Resource-Policy", "same-origin")
        req.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            req.send_header(k, v)
        req.end_headers()
        if not head:
            req.wfile.write(body)

    def handle(self, req, head=False):
        try:
            if not self.host_ok(req.headers.get("Host")):
                return self.send(req, 403, b"forbidden: unknown Host\n", "text/plain; charset=utf-8", head=head)
            self.last_request = time.time()
            url = urlsplit(req.path)
            path = url.path
            if path in ("/", "/index.html"):
                body = page(summarize(self.folder, **self.kw), live=True, console=self.console_page()).encode("utf-8")
                return self.send(req, 200, body, "text/html; charset=utf-8", head=head)
            if path == "/summary.json":
                # ?share=1: the page's export, without the folder's path, the host or the process id
                share = parse_qs(url.query).get("share") == ["1"]
                body = json.dumps(summarize(self.folder, share=share, **self.kw), default=str).encode("utf-8")
                if not share:
                    self.last_summary = time.time()
                    if self.stopping:
                        self.served_after_stop.set()
                return self.send(req, 200, body, "application/json; charset=utf-8", head=head)
            if path == "/favicon.ico":
                return self.send(req, 204, b"", "image/x-icon", head=head)
            if path.startswith("/api/"):
                return self.api(req, "GET", path, parse_qs(url.query), None, head=head)
            m = re.fullmatch(r"/thumb/([^/]+)/([^/]+)/([fr])\.png", path)
            if m:
                png = self.thumb(unquote(m.group(1)), unquote(m.group(2)), m.group(3))
                if png:      # the URL carries the maps' mtimes, so a cached thumbnail is never a stale one
                    return self.send(req, 200, png, "image/png", head=head, cache="private, max-age=3600")
            m = re.fullmatch(r"/wire/([^/]+)\.json", path)
            if m:
                wire = self.wire(unquote(m.group(1)))
                if wire:     # the URL carries the grids' mtimes
                    return self.send(req, 200, json.dumps(wire).encode("utf-8"), "application/json; charset=utf-8",
                                     head=head, cache="private, max-age=3600")
            return self.send(req, 404, b"not found\n", "text/plain; charset=utf-8", head=head)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as exc:  # noqa: BLE001 - a page that fails to draw says why, the server stays up
            try:
                return self.send(req, 500, f"monitor error: {type(exc).__name__}\n".encode(),
                                 "text/plain; charset=utf-8", head=head)
            except OSError:
                return None

    # ------------------------------------------------------------ console (kit/apconsole.py)

    def ctx(self):
        if self._ctx is None:
            from . import vc3d_agent
            self._ctx = vc3d_agent.Context()
        return self._ctx

    def console_page(self):
        """What the live page needs to show the console: whether it is on, the token, the commands it takes."""
        if not self.console:
            return {"on": False, "why": "the console is off on this server (--read-only, or not on a loopback address)"}
        from . import apconsole
        return {"on": True, "token": self.token, "tools": apconsole.tools()}

    def api_ok(self, req):
        """A console request: the console is on, it carries this server's token, and any Origin is this server."""
        if not self.console:
            return False
        if not hmac.compare_digest(str(req.headers.get("X-AP-Token") or ""), self.token):
            return False
        origin = req.headers.get("Origin")
        return origin is None or origin == f"http://{req.headers.get('Host')}"

    def surface_path(self, sid):
        """A surface's tifxyz folder from state.json (relative paths from the run folder), or None."""
        state, _, _ = _json_file(self.folder, "state.json")
        rec = ((_d(state).get("surfaces") or {}).get(sid) or {}) if isinstance(sid, str) else {}
        p = rec.get("surface") if isinstance(rec, dict) else None
        if not isinstance(p, str) or not p:
            return None
        p = Path(p).expanduser()
        return p if p.is_absolute() else self.folder / p

    def handle_post(self, req):
        try:
            if not self.host_ok(req.headers.get("Host")):
                return self.send(req, 403, b"forbidden: unknown Host\n", "text/plain; charset=utf-8")
            path = urlsplit(req.path).path
            if not self.console or not path.startswith("/api/"):
                return self.send(req, 405, b"read-only: GET only\n", "text/plain; charset=utf-8",
                                 extra={"Allow": "GET, HEAD"})
            if (req.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._json(req, 415, {"error": "send application/json"})
            try:
                n = int(req.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > 256 * 1024:
                return self._json(req, 413, {"error": "a console request is at most 256 KB"})
            try:
                body = json.loads(req.rfile.read(n) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._json(req, 400, {"error": "the body is not JSON"})
            return self.api(req, "POST", path, {}, body if isinstance(body, dict) else {})
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as exc:  # noqa: BLE001 - the server stays up
            try:
                return self._json(req, 500, {"error": f"monitor error: {type(exc).__name__}"})
            except OSError:
                return None

    def _json(self, req, code, obj, head=False):
        return self.send(req, code, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8",
                         head=head)

    def api(self, req, method, path, query, body, head=False):
        from . import apconsole, vc3d_agent
        if not self.api_ok(req):
            return self._json(req, 403, {"error": "the console is off, or this request does not come from its page"},
                              head=head)
        self.last_request = time.time()
        ctx = self.ctx()
        try:
            if method == "GET" and path == "/api/console":
                return self._json(req, 200, {"notes": apconsole.read_notes(ctx, self.folder),
                                             "jobs": apconsole.jobs(ctx, self.folder)}, head=head)
            if method == "GET" and path == "/api/job":
                jid = (query.get("id") or [""])[0]
                return self._json(req, 200, apconsole.job(ctx, self.folder, jid), head=head)
            if method == "POST" and path == "/api/notes":
                return self._json(req, 200, apconsole.save_notes(ctx, self.folder, body.get("text")))
            if method == "POST" and path == "/api/run":
                sid = body.get("surface")
                surf = self.surface_path(sid) if sid else None
                if sid and surf is None:
                    raise apconsole.ConsoleError(f"surface {sid!r} has no tifxyz path in state.json")
                return self._json(req, 200, apconsole.run(ctx, self.folder, str(body.get("command") or ""), surf))
            if method == "POST" and path == "/api/cancel":
                return self._json(req, 200, apconsole.cancel(ctx, self.folder, str(body.get("job") or "")))
        except (apconsole.ConsoleError, vc3d_agent.ToolError, OSError) as exc:
            return self._json(req, 400, {"error": str(exc)}, head=head)
        return self._json(req, 404, {"error": "no such console request"}, head=head)

    def _shown(self):
        """state.json, when it belongs to this folder's plan and the thumbnails' rule lets its maps be shown."""
        state, _, _ = _json_file(self.folder, "state.json")
        plan, _, _ = _json_file(self.folder, "plan.json")
        if not isinstance(state, dict) or not isinstance(plan, dict) or \
                state.get("plan_digest") not in (None, plan.get("digest")):
            return None
        on, _ = _thumbs_mode(_plan_part(plan), self.kw.get("thumbs", "auto"))
        return state if on else None

    def thumb(self, sid, model, variant):
        state = self._shown()
        return _thumb_for(self.folder, state, sid, model, variant) if state is not None else None

    def wire(self, sid):
        state = self._shown()
        return _wire_for(self.folder, state, sid) if state is not None else None


def serve(folder, host=LOCAL, port=DEFAULT_PORT, **kw):
    """A Monitor bound to host:port (port 0: any free one), not yet serving; .start() serves it in a thread.
    console=False turns the notes and command console off (default: on for a loopback address)."""
    return Monitor(folder, host, port, **kw)


def _loopback(host):
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def start(folder, port=DEFAULT_PORT, host=LOCAL, out=None, **kw):
    """Serve the monitor in a daemon thread for a run in this process; a busy port falls back to a free one. Never
    raises: a monitor that cannot start prints why and the run goes on. Returns the Monitor or None."""
    out = out or sys.stderr
    try:
        try:
            mon = serve(folder, host, port, **kw)
        except OSError:
            mon = serve(folder, host, 0, **kw)
        mon.start()
        print(f"monitor: {mon.url} (local only, stops when the run ends)", file=out, flush=True)
        return mon
    except Exception as exc:  # noqa: BLE001 - the run must not fail for its monitor
        print(f"monitor: not started ({type(exc).__name__}: {exc}); the run goes on", file=out, flush=True)
        return None


# ---------------------------------------------------------------- command line

def add_parser(actions):
    """`autopipeline monitor` on kit/autopipe.py's subparsers."""
    a = actions.add_parser("monitor", help="a live, read-only page of one run folder on this machine, or a snapshot")
    a.add_argument("out", help="run folder (a relative one is read from the kit home, as status reads it)")
    a.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT}; 0: any free one)")
    a.add_argument("--host", default=LOCAL, help="address to listen on (default 127.0.0.1, this machine only)")
    a.add_argument("--snapshot", metavar="FILE.html",
                   help="write one self-contained page and exit, no server (relative to the current directory)")
    a.add_argument("--open", action="store_true", help="open the page in the default browser")
    a.add_argument("--read-only", action="store_true",
                   help="no console: the page cannot save notes or run commands (it is off anyway when --host is "
                        "not a loopback address)")
    a.add_argument("--with-notes", action="store_true", help="--snapshot: put the run's notes in, read only")
    a.add_argument("--thumbs", choices=("auto", "on", "off"), default="auto",
                   help="ink map thumbnails (auto: on for smoke runs and published labeled segments only)")
    a.add_argument("--stale-minutes", type=float, default=STALE_S / 60,
                   help="no update for this long and a running stage looks stopped (default 30)")
    a.add_argument("--text", action="store_true",
                   help="print the run as text in this terminal, ink maps drawn in characters, and exit (no server)")
    a.add_argument("--width", type=int, default=40, help="--text: a map's width in characters (default 40)")
    a.add_argument("--color", choices=("auto", "on", "off"), default="auto",
                   help="--text: maps in gray half blocks, two pixels a character (auto: on in a terminal "
                        "unless NO_COLOR is set)")
    a.add_argument("--dither", action="store_true", help="--text, without color: ordered (Bayer) dithering")
    a.add_argument("--watch", type=float, metavar="SECONDS",
                   help="--text: print it again every SECONDS (at least 1) until Ctrl-C")
    return a


def _text_cli(folder, args, kw, out=None, sleep=time.sleep):
    out = out or sys.stdout
    if args.snapshot:
        print("error: --text and --snapshot do not go together", file=sys.stderr)
        return 2
    if args.width < 8:
        print("error: --width is at least 8", file=sys.stderr)
        return 2
    if args.watch is not None and args.watch < 1:
        print("error: --watch is at least 1 second", file=sys.stderr)
        return 2
    tty = hasattr(out, "isatty") and out.isatty()
    color = args.color == "on" or (args.color == "auto" and tty and not os.environ.get("NO_COLOR"))
    try:
        while True:
            text = text_view(folder, width=args.width, color=color, dither=args.dither, **kw)
            out.write(("\x1b[H\x1b[2J" if args.watch and tty else "") + text)
            out.flush()
            if not args.watch:
                return 0
            sleep(args.watch)
    except KeyboardInterrupt:
        return 0


def cli(args):
    from . import vc3d_agent
    ctx = vc3d_agent.Context()
    try:
        folder = vc3d_agent.resolve(ctx, args.out)
        if not (folder / "plan.json").is_file():
            print(f"error: {folder} has no plan.json; make one with action plan", file=sys.stderr)
            return 2
        kw = {"stale_s": args.stale_minutes * 60, "thumbs": args.thumbs}
        if getattr(args, "text", False):
            return _text_cli(folder, args, kw)
        if args.snapshot:
            try:
                path = snapshot(folder, args.snapshot, ctx=ctx, notes=getattr(args, "with_notes", False), **kw)
            except (MonitorError, vc3d_agent.ToolError, OSError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            print(json.dumps({"snapshot": str(path), "folder": str(folder)}, indent=1))
            print("note: the snapshot holds this run's records, log lines and any thumbnails (not the folder's path, "
                  "the host or the process id); a snapshot of a target run must not be shared", file=sys.stderr)
            if args.open:
                import webbrowser
                webbrowser.open(path.as_uri())
            return 0
        try:
            mon = serve(folder, args.host, args.port, console=False if getattr(args, "read_only", False) else None, **kw)
        except OSError as exc:
            print(f"error: cannot listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
            return 2
        print(f"monitor: {mon.url} (" + ("console on: notes and commands run on this machine" if mon.console
              else "read-only") + "; Ctrl-C stops it)", file=sys.stderr, flush=True)
        if not _loopback(args.host):
            print(f"warning: listening on {args.host}: anyone who can reach this machine can read this run's "
                  "records, paths and log lines", file=sys.stderr, flush=True)
        if args.open:
            import webbrowser
            webbrowser.open(mon.url)
        try:
            mon.httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            mon.httpd.server_close()
        return 0
    finally:
        ctx.close()
