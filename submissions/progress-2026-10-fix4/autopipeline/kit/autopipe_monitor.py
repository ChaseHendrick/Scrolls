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
shared: thumbnails are on by default only for smoke runs and published labelled segments. Standard library;
numpy and tifffile, when present, make thumbnails of large maps, decoding at most THUMB_MAX_DECODED bytes at a
time (an uncompressed map is read through a memory map instead).
"""

import array
import base64
import calendar
import hashlib
import ipaddress
import json
import math
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import autopipe, vc3d_io

SCHEMA = 1
STALE_S = 1800                 # no update to state.json or events.jsonl for this long: the run looks stopped
EVENTS = "events.jsonl"
EVENTS_OLD = "events.1.jsonl"  # the previous part, once events.jsonl passed EVENTS_MAX
EVENTS_MAX = 256 * 1024
TAIL = 60                      # log lines the page shows
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
    """(on, why): thumbnails are on by default only for a smoke run or a published labelled segment, whose maps
    may be shown; any other run's maps may be of a scroll whose ink is not published."""
    if thumbs == "off":
        return False, "thumbnails are turned off"
    if thumbs != "on" and plan_part.get("purpose") == "target":
        return False, ("a target run: no thumbnails unless asked for (--thumbs on); maps of target scrolls must "
                       "not be shared")
    if thumbs != "on" and plan_part.get("purpose") != "smoke" and not plan_part.get("labelled_segment"):
        return False, ("this run is not a smoke run and names no published labelled segment, so its maps may be of "
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
                  "grid_rows_cols": tr.get("grid_rows_cols")} if tr else None,
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
            "mtime": st.st_mtime if st else None, "timing": timing}


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
            fh.seek(max(0, size - 4096))
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = [_cut(x, LINE_KEEP) for x in raw.replace("\r", "\n").split("\n") if x.strip()]
    if size > 4096 and lines:
        lines = lines[1:]
    return {"path": os.path.relpath(best[0], folder), "mtime": best[1], "lines": lines[-20:]}


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
                          "(scripts/vc3d/modal_autopipe.py, which starts from the first stage on its own copy). This "
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
                "trace_failures": [], "report": None, "scores_file": None,
                "events": {"present": False, "lines": [], "truncated": False}, "tool_log": None,
                "thumbs": {"enabled": False, "why": None}}


def _summary(folder, now, host, alive, stale_s, tail, thumbs, share):
    host = socket.gethostname() if host is None else host
    alive = alive or pid_alive
    out = {"monitor": SCHEMA, "generated": _iso(now), "generated_epoch": round(now, 3),
           "folder": folder.name if share else str(folder), "name": folder.name, "local_only": True, "note": NOTE,
           "plan": None, "state": {"present": False, "mtime": None, "age_s": None, "error": None}, "phase": "error",
           "banner": None, "current": None, "stats": {}, "stages": [], "surfaces": [], "surfaces_truncated": False,
           "trace_failures": [], "report": None, "scores_file": None,
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
    out["events"] = {k: ev[k] for k in ("present", "lines", "truncated")}
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
                              "reason": _cut(f.get("reason"), 400)}
                             for sid, f in list(failures.items())[:MAX_SURFACES] if isinstance(f, dict)]

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
                a = a[..., 0]          # samples (grey and alpha, or colour): the first
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


def thumb_png(path, scale=None):
    """(PNG bytes, (lo, hi)) of an ink map: the first plane at most THUMB_SIDE pixels a side, grey, zeros black.
    Without scale it is stretched between the 1st and 99th percentile of its non-zero values; a control map is
    drawn on its forward map's scale so it is never stretched to look like ink. Cached by file and scale."""
    path = Path(path)
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size, tuple(scale) if scale else None)
    with _THUMBS_LOCK:
        hit = _THUMBS.get(key)
    if hit is not None:
        return hit
    r = _plane(path)
    lo, hi = scale if scale else (None, None)
    data, used = vc3d_io.to_u8(r, lo=lo, hi=hi)
    got = (vc3d_io.png_bytes(r.h, r.w, data), tuple(used))
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
WIRE_Q = 16000              # coordinates as int16 in [-WIRE_Q, WIRE_Q] about the mesh's centre
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
    centred on the valid points and scaled so the longest side of their box spans 2 * WIRE_Q, as little-endian
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
            t = (tot / n - lo) / span if span else 0.5   # a uniform map shows mid grey, as its thumbnail does
            line.append(min(1.0, max(0.0, t)))
        out.append(line)
    return out


def _grey(t):
    return 232 + int(t * 23 + 0.5)   # the 24 greys of the 256-colour palette


def ascii_map(raster, width=40, scale=None, dither=False, color=False, ramp=RAMP):
    """(lines, (lo, hi)): an ink map drawn in characters, at most `width` wide, each a block mean stretched between
    the 1st and 99th percentile of the map's non-zero values, or on `scale` (a control on its forward map's scale,
    so it is never stretched to look like ink). Off-surface blocks are blank. Plain: one character per cell from
    `ramp`, a cell about twice as tall as wide; dither adds the 4 x 4 ordered (Bayer) threshold before rounding.
    color: two pixels per cell, the upper and lower half block in the 256-colour palette's greys (ANSI escapes)."""
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
    and scores, and, when thumbnails are on (the page's rule: smoke runs and published labelled segments, or
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

_DARK = {"bg": "#0e1215", "card": "#171c20", "inset": "#0f1417", "stroke": "rgba(255,255,255,.09)",
         "text": "rgba(255,255,255,.94)", "text2": "#a3b2b8", "mint": "#a8f0b8", "amber": "#ffc26b",
         "blue": "#91c2fa", "violet": "#cfb5fa", "grid": "rgba(255,255,255,.07)", "idle": "rgba(255,255,255,.06)",
         "mint-rgb": "168,240,184", "amber-rgb": "255,194,107", "blue-rgb": "145,194,250",
         "grey-rgb": "163,178,184", "violet-rgb": "207,181,250", "scheme": "dark"}
_LIGHT = {"bg": "#f3f5f6", "card": "#ffffff", "inset": "#eef1f3", "stroke": "rgba(14,18,21,.10)",
          "text": "#12171b", "text2": "#55646a", "mint": "#1d8a4a", "amber": "#9a5a00", "blue": "#2160a8",
          "violet": "#6a46c2", "grid": "rgba(14,18,21,.08)", "idle": "rgba(14,18,21,.07)",
          "mint-rgb": "29,138,74", "amber-rgb": "154,90,0", "blue-rgb": "33,96,168", "grey-rgb": "85,100,106",
          "violet-rgb": "106,70,194", "scheme": "light"}


def _tokens(t):
    return "color-scheme:" + t["scheme"] + ";" + "".join(f"--{k}:{v};" for k, v in t.items() if k != "scheme")


_CSS = """
:root{%DARK%}
@media (prefers-color-scheme: light){:root:not([data-theme=dark]){%LIGHT%}}
:root[data-theme=light]{%LIGHT%}
:root[data-theme=dark]{%DARK%}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text)}
body{font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
 -webkit-text-size-adjust:100%;overflow-x:hidden}
.wrap{max-width:1440px;margin:0 auto;padding:28px;display:flex;flex-direction:column;gap:24px}
.num{font-family:ui-rounded,"SF Pro Rounded",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.label{font-size:11.5px;font-weight:600;letter-spacing:.01em;color:var(--text2)}
.sec{color:var(--text2)}
.wrapany{overflow-wrap:anywhere;word-break:break-word}
.row{display:flex;align-items:center;gap:12px;min-width:0}
.spacer{flex:1 1 auto}
.tile{flex:0 0 auto;width:45px;height:45px;border-radius:13px;display:grid;place-items:center;
 color:var(--mint);background:rgba(var(--mint-rgb),.10);border:1px solid rgba(var(--mint-rgb),.18)}
header.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.brand{font-size:16px;font-weight:700;letter-spacing:.01em}
.brand .short{display:none}
.capsule{display:flex;align-items:center;gap:7px;flex-wrap:wrap;padding:8px 10px 8px 13px;border-radius:999px;
 background:var(--card);border:1px solid var(--stroke);min-width:0;max-width:100%}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;padding:4px 8px;
 border-radius:999px;background:var(--idle);white-space:nowrap}
.pill.mint{color:var(--mint);background:rgba(var(--mint-rgb),.10)}
.pill.amber{color:var(--amber);background:rgba(var(--amber-rgb),.10)}
.pill.blue{color:var(--blue);background:rgba(var(--blue-rgb),.10)}
.pill.grey{color:var(--text2);background:rgba(var(--grey-rgb),.10)}
.pill.tag{font-size:10.5px;font-weight:700;letter-spacing:.01em}
button.ghost{font:inherit;font-size:11px;font-weight:600;color:var(--text2);background:var(--idle);border:0;
 border-radius:999px;padding:4px 9px;cursor:pointer}
button.ghost:focus-visible,button.icon:focus-visible{outline:2px solid var(--mint);outline-offset:2px}
.intro{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap}
.intro h1{margin:0;font-size:30px;line-height:1.15;font-weight:600;letter-spacing:-.01em}
.intro .sub{margin-top:7px;color:var(--text2)}
.live{display:flex;flex-direction:column;align-items:flex-end;gap:4px;margin-left:auto}
.dot{width:6px;height:6px;border-radius:50%;background:var(--text2);display:inline-block}
.dot.mint{background:var(--mint)}.dot.amber{background:var(--amber)}.dot.blue{background:var(--blue)}
.livelab{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:600;letter-spacing:.01em;
 color:var(--text2)}
.banner{display:flex;align-items:center;gap:13px;padding:16px;border-radius:13px;
 background:rgba(var(--tone-rgb),.07);border:1px solid rgba(var(--tone-rgb),.25);min-width:0}
.banner .btile{flex:0 0 auto;width:43px;height:43px;border-radius:11px;display:grid;place-items:center;
 color:var(--tone);background:rgba(var(--tone-rgb),.12)}
.banner h2{margin:0 0 4px;font-size:16px;font-weight:600}
.banner p{margin:0;font-size:12.5px;color:var(--text2)}
.banner .badge{flex:0 0 auto;font-size:10.5px;font-weight:700;letter-spacing:.01em;color:var(--tone);
 padding:6px 9px;border-radius:999px;background:rgba(var(--tone-rgb),.10)}
.t-mint{--tone:var(--mint);--tone-rgb:var(--mint-rgb)}.t-amber{--tone:var(--amber);--tone-rgb:var(--amber-rgb)}
.t-blue{--tone:var(--blue);--tone-rgb:var(--blue-rgb)}.t-grey{--tone:var(--text2);--tone-rgb:var(--grey-rgb)}
.notices{display:flex;flex-direction:column;gap:10px}
.notices:empty{display:none}
.notice{display:flex;gap:10px;align-items:flex-start;padding:12px 14px;border-radius:11px;
 background:rgba(var(--tone-rgb),.06);border:1px solid rgba(var(--tone-rgb),.20);min-width:0}
.notice b{display:block;font-size:12.5px;margin-bottom:2px}
.notice span{font-size:12px;color:var(--text2)}
.notice .ic{color:var(--tone);flex:0 0 auto;margin-top:1px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.stat{background:var(--card);border:1px solid var(--stroke);border-radius:14px;padding:18px;min-width:0}
.stat .v{display:flex;align-items:baseline;gap:4px;margin:12px 0 10px}
.stat .v b{font-size:34px;font-weight:500;line-height:1}
.stat .v span{font-size:13px;font-weight:500;color:var(--text2);margin-right:5px}
.stat .d{font-size:11px;color:var(--text2)}
.stat .ic{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:7px;background:var(--tone)}
.card{background:var(--card);border:1px solid var(--stroke);border-radius:16px;padding:21px;min-width:0}
.card h3{margin:0;font-size:16px;font-weight:600}
.card .hd{display:flex;align-items:flex-start;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.card .hd .sec{font-size:12px;margin-top:4px}
button.icon{width:32px;height:32px;border-radius:8px;border:0;background:var(--idle);color:var(--text2);
 display:grid;place-items:center;cursor:pointer}
.strip{display:grid;grid-template-columns:repeat(11,1fr);gap:5px;margin-bottom:6px}
.seg{height:12px;border-radius:3px;background:var(--idle)}
.s-done{background:rgba(var(--mint-rgb),.78)}.s-failed,.s-stopped{background:rgba(var(--amber-rgb),.85)}
.s-quiet,.s-unknown{background:rgba(var(--amber-rgb),.55)}
.s-handoff,.s-waiting_runner{background:rgba(var(--blue-rgb),.70)}.s-skipped{background:rgba(var(--grey-rgb),.35)}
.s-running{background:var(--mint);animation:pulse 1.6s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
@media (prefers-reduced-motion: reduce){.s-running{animation:none}}
.striplab{display:grid;grid-template-columns:repeat(11,1fr);gap:5px;font-size:9px;color:var(--text2);
 text-align:center;margin-bottom:16px}
.striplab span{overflow:hidden;text-overflow:clip;white-space:nowrap}
.gantt{display:flex;flex-direction:column;gap:7px}
.grow{display:grid;grid-template-columns:96px 112px 74px minmax(0,1fr);align-items:center;gap:10px;min-width:0}
.grow .nm{font-weight:600;font-size:13px}
.grow .du{font-size:12px;color:var(--text2);text-align:right}
.track{position:relative;height:16px;border-radius:5px;background:var(--inset);overflow:hidden}
.track .q{position:absolute;top:0;bottom:0;border-left:1px dashed var(--grid)}
.track .bar{position:absolute;top:3px;bottom:3px;border-radius:3px;min-width:3px}
.grow .sm{grid-column:2 / -1;font-size:11.5px;color:var(--text2);margin-top:-3px;overflow-wrap:anywhere}
.axis{display:grid;grid-template-columns:96px 112px 74px minmax(0,1fr);gap:10px;font-size:10px;color:var(--text2);
 margin-top:6px}
.axis .ticks{display:flex;justify-content:space-between}
.chip{display:inline-flex;align-items:center;justify-content:center;font-size:10.5px;font-weight:600;
 padding:3px 9px;border-radius:999px;color:var(--tone);background:rgba(var(--tone-rgb),.10);
 border:1px solid rgba(var(--tone-rgb),.20);white-space:nowrap}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:14px;font-size:10px;color:var(--text2)}
.legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.surfaces{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr));gap:16px}
.sc{display:flex;flex-direction:column;gap:14px}
.sc .shd{display:flex;align-items:center;gap:12px;min-width:0}
.sc .stile{flex:0 0 auto;width:38px;height:38px;border-radius:11px;display:grid;place-items:center;
 color:var(--tone);background:rgba(var(--tone-rgb),.10);font-weight:700;font-size:12px}
.sc .sid{font-weight:600;font-size:15px}
.sc .orig{font-size:11.5px;color:var(--text2);overflow-wrap:anywhere}
dl.kv{display:grid;grid-template-columns:minmax(90px,max-content) minmax(0,1fr);gap:6px 14px;margin:0;font-size:12.5px}
dl.kv dt{color:var(--text2)}
dl.kv dd{margin:0;overflow-wrap:anywhere}
.part{border-top:1px solid var(--stroke);padding-top:12px;display:flex;flex-direction:column;gap:8px}
.subhd{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.fine{font-size:11px;color:var(--text2)}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.cmp>div{background:var(--inset);border-radius:10px;padding:10px;min-width:0}
.cmp b{font-size:22px;font-weight:500;display:block;margin-top:4px}
.thumbs{display:grid;grid-template-columns:1fr 1fr;gap:10px}
figure{margin:0;min-width:0}
figure img{display:block;width:100%;height:auto;max-height:220px;object-fit:contain;border-radius:8px;
 background:var(--inset);image-rendering:pixelated;transition:opacity .25s ease}
figure img.pre{opacity:0}
figure img.broken{opacity:0;min-height:60px}
.frame{border-radius:8px}
.sk{position:relative;overflow:hidden;background:var(--inset)}
.sk::after{content:"";position:absolute;inset:0;transform:translateX(-100%);
 background:linear-gradient(90deg,transparent,rgba(var(--grey-rgb),.18),transparent);animation:shimmer 1.4s ease-in-out infinite}
@keyframes shimmer{to{transform:translateX(100%)}}
.frame.sk{aspect-ratio:3/2;max-height:220px}
.frame.sk img{position:absolute;inset:0}
.skel{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.skel .sk{aspect-ratio:3/2;border-radius:8px}
.wirebox{position:relative;height:220px;border-radius:10px;background:var(--inset)}
.wirebox canvas{display:block;width:100%;height:100%;border-radius:10px;cursor:grab;touch-action:pan-y}
.wirebox canvas:active{cursor:grabbing}
.wirebox canvas:focus-visible{outline:2px solid var(--mint);outline-offset:2px}
@media (prefers-reduced-motion: reduce){.sk::after{animation:none;opacity:0}figure img{transition:none}}
figcaption{font-size:10.5px;color:var(--text2);margin-top:4px}
.scorerow{background:var(--inset);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:4px;min-width:0}
.scorerow .cmp>div{background:var(--card)}
.log{background:var(--inset);border-radius:10px;padding:12px;max-height:420px;overflow-y:auto;overflow-x:hidden;
 white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5}
.log .ts{color:var(--text2)}
.log .ev{color:var(--mint)}
.log .bad{color:var(--amber)}
footer{display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--text2);padding:0 2px 4px}
footer span{flex:1 1 300px}
.hidden{display:none !important}
@media (max-width:760px){
 .grow{grid-template-columns:minmax(0,1fr) auto auto}
 .grow .du{min-width:72px;white-space:nowrap}
 .grow .track{grid-column:1 / -1}
 .grow .sm{grid-column:1 / -1;margin-top:0}
 .grow.notime .track{display:none}
 .axis{grid-template-columns:minmax(0,1fr)}
 .axis>span:not(.ticks){display:none}
}
@media (max-width:600px){
 .wrap{padding:16px;gap:18px}
 .brand .full{display:none}.brand .short{display:inline}
 .intro h1{font-size:24px}
 .capsule{border-radius:14px}
 .live{align-items:flex-start;margin-left:0}
 .stat{padding:14px}.stat .v b{font-size:28px}
 .card{padding:16px}
 .banner{flex-wrap:wrap}
 .banner .btext{flex:1 1 calc(100% - 60px) !important}
 .banner .badge{margin-left:56px}
 dl.kv{grid-template-columns:minmax(0,1fr)}
 dl.kv dt{margin-top:4px}
 .striplab{display:none}
}
"""

_JS = r"""
(function(){
"use strict";
var LIVE = %LIVE%;
var S = JSON.parse(document.getElementById("summary").textContent);
var lastOk = Date.now(), lost = false, misses = 0, timer = null, fetchedAt = Date.now();
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
function tonecls(t){return "t-"+(t||"grey");}
function chip(status){return el("span","chip "+tonecls(STAGE_TONE[status]||"grey"),STAGE_LABEL[status]||status);}
function pill(text, tone, tag){return el("span","pill "+(tone||"")+(tag?" tag":""),text);}
function kv(dl, k, v){if(v===null||v===undefined||v==="") return; dl.appendChild(el("dt",null,k));
  var dd=el("dd",null,v); dl.appendChild(dd); return dd;}
function isRunning(){return !!(S.current&&(S.phase==="running"||S.phase==="quiet"));}
function ended(){return ENDED.indexOf(S.phase)>=0;}
function noNews(){return LIVE&&lost&&isRunning();}       // the server stopped answering while a stage ran
function elapsedNow(){var e=S.current?S.current.elapsed_s:null; if(e===null||e===undefined) return null;
  return e+(LIVE&&!lost&&isRunning()?(Date.now()-fetchedAt)/1000:0);}
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
  $("subtitle").textContent=bits.join("  |  ");
  $("folder").textContent=S.folder?("<run> = "+S.folder):"";
  $("target").classList.toggle("hidden", p.purpose!=="target");
  document.title=(S.name||"run")+" | AP Monitor";}

function liveLabel(){var d=$("livedot"), t=$("livetext"), u=$("updated");
  if(!LIVE){d.className="dot"; t.textContent="Snapshot "+(S.generated||""); u.textContent="Taken "+new Date((S.generated_epoch||0)*1000).toLocaleString(); return;}
  var ago=Math.max(0,Math.round((Date.now()-lastOk)/1000));
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
  tickElapsed();}

function notices(){var box=clear($("notices"));
  function add(tone, title, msg){var n=el("div","notice "+tonecls(tone)); var ic=el("span","ic"); ic.appendChild(svg(tone==="amber"?"amber":"blue"));
    n.appendChild(ic); var t=el("div"); t.appendChild(el("b",null,title)); t.appendChild(el("span",null,msg)); n.appendChild(t); box.appendChild(n);}
  if(lost&&LIVE&&!noNews()){if(ended()) add("grey","The monitor has closed","As it does when its run ends, or when it was stopped; the last state read is shown.");
    else add("amber","No connection","The monitor is not answering; the last state read is shown, and the page keeps trying.");}
  if(S.state&&S.state.error&&S.phase!=="state_error") add("amber","state.json",S.state.error);
  if(S.plan&&S.plan.purpose==="target") add("amber","A target run","Its maps and scores stay private: maps of target scrolls must not be shared. Thumbnails are off unless asked for.");
  var tf=S.trace_failures||[];
  if(tf.length) add("amber",tf.length+" trace"+(tf.length>1?"s":"")+" gave no surface",
    tf.slice(0,6).map(function(f){return f.id+" ("+(f.kind||"unknown")+"): "+(f.reason||"");}).join("; ")+(tf.length>6?"; ...":""));
  if(S.report&&S.report.present&&S.report.matches===false) add("amber","report.json changed","Its sha256 is not the digest the run recorded when it wrote it.");}

function stats(){var st=S.stats||{}, box=clear($("stats"));
  function card(tone, label, val, unit, detail){var c=el("div","stat "+tonecls(tone)); var l=el("div","label"); var i=el("span","ic"); l.appendChild(i); l.appendChild(document.createTextNode(label)); c.appendChild(l);
    var v=el("div","v num"); if(val!==null){v.appendChild(el("b",null,val)); if(unit) v.appendChild(el("span",null,unit));} c.appendChild(v); c.appendChild(el("div","d",detail)); box.appendChild(c); return v;}
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
  if(S.phase==="running"&&LIVE) $("b-title").textContent="Running "+stageName(S.current.stage)+" for "+dur(e);}

function timeline(){var rows=S.stages||[], strip=clear($("strip")), lab=clear($("striplab")), g=clear($("gantt"));
  rows.forEach(function(r){var st=rowStatus(r); var s=el("div","seg s-"+st); s.title=stageName(r.name)+": "+(STAGE_LABEL[st]||st); strip.appendChild(s); lab.appendChild(el("span",null,stageName(r.name)));});
  var now=LIVE&&!lost?(S.generated_epoch+(Date.now()-fetchedAt)/1000):S.generated_epoch;
  function endOf(r){return r.ended_epoch!=null?r.ended_epoch:((r.status==="running"||r.status==="quiet")?now:r.started_epoch);}
  var t0=null,t1=null; rows.forEach(function(r){if(r.started_epoch!=null){t0=t0==null?r.started_epoch:Math.min(t0,r.started_epoch);
    var e=endOf(r); t1=t1==null?e:Math.max(t1,e);}});
  if(t0!=null&&t1!=null&&t1-t0<1) t1=t0+1;
  rows.forEach(function(r){var st=rowStatus(r); var row=el("div","grow"+(r.started_epoch==null?" notime":"")); row.appendChild(el("span","nm",stageName(r.name))); var c=el("span"); c.appendChild(chip(st)); row.appendChild(c);
    var live=isRunning()&&S.current.stage===r.name&&!noNews();
    var du=el("span","du num",live?dur(elapsedNow()):(r.seconds!=null?dur(r.seconds):"")); if(live) du.id="du-running"; row.appendChild(du);
    var tr=el("div","track"); [25,50,75].forEach(function(q){var l=el("div","q"); l.style.left=q+"%"; tr.appendChild(l);});
    if(t0!=null&&r.started_epoch!=null){var e=endOf(r);
      var b=el("div","bar s-"+st); b.style.left=(100*(r.started_epoch-t0)/(t1-t0)).toFixed(2)+"%";
      b.style.width=Math.max(0.6,100*(e-r.started_epoch)/(t1-t0)).toFixed(2)+"%"; tr.appendChild(b);}
    row.appendChild(tr);
    var sm=r.error||r.why||r.summary; if(st==="unknown"&&r.status!=="unknown") sm="last seen running; the monitor stopped answering";
    if(sm){row.appendChild(el("div","sm"+(r.error?" wrapany":""),r.error?("Error ("+(r.kind||"unknown")+"): "+sm):cap(sm)));}
    g.appendChild(row);});
  var ax=$("axis"); ax.classList.toggle("hidden", t0==null);
  if(t0!=null){$("ax0").textContent="Start "+clock(t0); $("ax1").textContent=clock(t0+(t1-t0)/2);
    $("ax2").textContent=isRunning()&&LIVE&&!lost?"Now":("End "+clock(t1));}}

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
  g.globalAlpha=1;}
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
    w.cap.textContent=d.rows+" x "+d.cols+" grid points"+(Array.isArray(d.extent)?(" in a box of "+d.extent.map(function(v){return Math.round(v);}).join(" x ")+" voxels (x, y, z)"):"")+"; nearer lines are brighter. Arrow keys turn it too, 0 resets.";
    wireSoon(w);}
  catch(e){w.box.classList.remove("sk"); w.cap.textContent="No wireframe: the mesh could not be read.";}}
function wireFigure(s, used){var key=typeof s.wire==="string"?s.wire:("inline:"+s.id); used["wire:"+key]=1; var w=WIRES[key];
  if(w) return w.fig;
  w={key:key, yaw:VIEW.yaw, pitch:VIEW.pitch, pts:null, raf:0}; WIRES[key]=w;
  var fig=el("figure","wire"), box=el("div","wirebox sk"), cv=el("canvas"); cv.tabIndex=0; cv.setAttribute("role","img");
  cv.setAttribute("aria-label","3D wireframe of the traced surface "+s.id+": drag or use the arrow keys to turn it, 0 resets");
  box.appendChild(cv); fig.appendChild(box); var cap=el("figcaption",null,"Traced mesh: loading"); fig.appendChild(cap);
  w.fig=fig; w.box=box; w.cv=cv; w.cap=cap;
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

function surfaceCard(s, used){var tone={rendered:"mint",accepted:"mint",published:"blue",rejected:"amber",trace_failed:"amber",not_rendered:"amber",unreadable:"amber"}[s.status]||"grey";
  var label={rendered:"Accepted",accepted:"Accepted",published:"Published, checked not gated",rejected:"Rejected",trace_failed:"Trace failed",not_rendered:"Accepted, not rendered",unreadable:"Unreadable"}[s.status];
  if(!label&&s.status&&s.status.indexOf("waiting:")===0) label="Waiting for "+stageName(s.status.slice(8));
  var c=el("div","card sc "+tonecls(tone)); var hd=el("div","shd"); hd.appendChild(el("div","stile",s.published?"PUB":(s.id||"").slice(0,3).toUpperCase()));
  var t=el("div"); t.style.minWidth="0"; t.appendChild(el("div","sid",s.id)); if(s.origin) t.appendChild(el("div","orig",cap(s.origin))); hd.appendChild(t);
  hd.appendChild(el("span","spacer")); hd.appendChild(el("span","chip "+tonecls(tone),label||s.status)); c.appendChild(hd);
  if(s.failure&&s.failure.reason){var n=el("div","notice t-amber"); n.appendChild(el("span",null,"Stopped at "+(s.failure.stage?stageName(s.failure.stage):"?")+" ("+(s.failure.kind||"unknown")+"): "+s.failure.reason)); c.appendChild(n);}
  (s.reasons||[]).forEach(function(r){if(s.failure&&s.failure.reason&&s.failure.reason.indexOf(r)>=0) return; var n=el("div","notice t-amber"); n.appendChild(el("span",null,"QA: "+r)); c.appendChild(n);});
  (s.warnings||[]).forEach(function(w){var n=el("div","notice t-amber"); n.appendChild(el("span",null,"Warning: "+w)); c.appendChild(n);});
  var dl=el("dl","kv");
  if(s.trace) kv(dl,"Trace",[s.trace.area_cm2!=null?fmt(s.trace.area_cm2,3)+" cm²":null, s.trace.valid_fraction!=null?pct(s.trace.valid_fraction)+" valid":null, Array.isArray(s.trace.grid_rows_cols)?("grid "+s.trace.grid_rows_cols.join(" x ")):null].filter(Boolean).join(", "));
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
  if(s.wire&&(typeof s.wire!=="string"||s.wire.indexOf("wire/")===0)){var wp=el("div","part"); var wh=el("div","subhd");
    wh.appendChild(el("span","label","Traced mesh")); wh.appendChild(pill("3D, drag to turn","grey",true)); wp.appendChild(wh);
    wp.appendChild(wireFigure(s, used)); c.appendChild(wp);}
  if(!(s.ink||[]).length&&s.status==="rendered"&&(S.thumbs||{}).enabled&&isRunning()&&!noNews()&&S.current.stage==="ink"){
    var wi=el("div","part"); var wih=el("div","subhd"); wih.appendChild(el("span","label","Ink maps")); wih.appendChild(pill("Waiting for the Ink stage","grey",true)); wi.appendChild(wih);
    var sk=el("div","skel"); sk.setAttribute("aria-hidden","true"); sk.appendChild(el("div","sk")); sk.appendChild(el("div","sk")); wi.appendChild(sk); c.appendChild(wi);}
  if((s.ink||[]).length){var sub=el("div","part"); var h=el("div","subhd"); h.appendChild(el("span","label","Ink maps")); h.appendChild(pill("Model output","amber",true)); sub.appendChild(h);
    s.ink.forEach(function(m){var cr=(m.comparison||{}).r, th=m.threshold!=null?m.threshold:0.5;
      var line=m.model+": exit "+(m.exit==null?"N/A":m.exit)+"; maps: "+((m.variants||[]).map(function(v){return VARIANT[v]||v;}).join(", ")||"none");
      if(cr) line+="; share of pixels above "+th+" (how much each map marks, not a score): forward "+pct(cr.forward_share_above)+", reversed "+pct(cr.control_share_above);
      sub.appendChild(el("div","fine",line));
      if(m.thumbs&&m.thumbs.f){var tg=el("div","thumbs"); [["f","Forward"],["r","Reversed control, same scale"]].forEach(function(v){var src=m.thumbs[v[0]]; if(!src||!(src.indexOf("thumb/")===0||src.indexOf("data:image/png;base64,")===0)) return;
        var f=el("figure"); f.appendChild(thumbFrame(thumbImg(src, s.id+" "+m.model+" "+v[1]+" map, model output", used))); f.appendChild(el("figcaption",null,v[1])); tg.appendChild(f);}); sub.appendChild(tg);}
      (m.warnings||[]).forEach(function(w){sub.appendChild(el("div","fine","Warning: "+w));});});
    sub.appendChild(el("div","fine","Model output, not a reading."));
    c.appendChild(sub);}
  if((s.scores||[]).length){var sb=el("div","part"); var h2=el("div","subhd"); h2.appendChild(el("span","label","Scores")); h2.appendChild(pill("Model output","amber",true)); sb.appendChild(h2);
    s.scores.forEach(function(r){var box=el("div","scorerow"); box.appendChild(el("div","fine",(r.model||"All models")+(r.scope?(" | "+r.scope):"")));
      if(r.error){box.appendChild(el("div",null,"Error: "+r.error));}
      else if(r.scorable===false){box.appendChild(el("div",null,"Not scored: "+(r.why||"")));}
      else {var g=el("div","cmp"); [["Forward AUC",r.forward_auc],["Reversed control AUC",r.control_auc]].forEach(function(x){var d=el("div"); d.appendChild(el("div","label",x[0])); d.appendChild(el("b","num",fmt(x[1],3))); g.appendChild(d);}); box.appendChild(g);
        var xs=[]; if(r.shuffled_auc!=null) xs.push("Shuffled "+fmt(r.shuffled_auc,3)); if(r.displaced_auc!=null) xs.push("Displaced labels "+fmt(r.displaced_auc,3)); if(r.reference_auc!=null) xs.push("Published map on the same pixels "+fmt(r.reference_auc,3));
        if(xs.length) box.appendChild(el("div","fine num",xs.join("  |  ")));}
      sb.appendChild(box);});
    sb.appendChild(el("div","fine","Model output, not a reading: pixel AUC against published labels; the reversed control should sit near or below 0.5."));
    c.appendChild(sb);}
  else if((s.ink||[]).length||s.published){var nsc=S.scores_file||{}; if(nsc.skipped) c.appendChild(el("div","fine","Not scored: "+nsc.skipped));}
  return c;}

function surfaces(){var box=clear($("surfaces")), list=S.surfaces||[], used={};
  $("surf-count").textContent=list.length?(list.length+" surface"+(list.length>1?"s":"")+(S.surfaces_truncated?" (first 300)":"")):"";
  if(!list.length){var e=el("div","card sec");
    e.textContent=S.phase==="not_started"?"No surface yet: the run has not started.":"No surface yet: the trace stage has not recorded one."; box.appendChild(e);}
  list.forEach(function(s){box.appendChild(surfaceCard(s, used));});
  Object.keys(IMGS).forEach(function(k){if(!used[k]) delete IMGS[k];});
  Object.keys(WIRES).forEach(function(k){if(!used["wire:"+k]) delete WIRES[k];});
  wireAll();
  var t=S.thumbs||{};
  var anyMaps=list.some(function(x){return (x.ink||[]).some(function(m){return (m.variants||[]).length;});});
  var anyThumb=list.some(function(x){return (x.ink||[]).some(function(m){return m.thumbs&&m.thumbs.f;});});
  $("thumbnote").textContent=anyThumb?(t.why||"Thumbnails: forward and reversed control drawn on the forward map's scale.")
    :!anyMaps?"":!t.enabled?("No thumbnails: "+(t.why||"turned off")):"No thumbnails: the map files are not in this folder.";}

function stuck(box){return !box.dataset.seen||box.scrollHeight-box.scrollTop-box.clientHeight<60;}
function logs(){var box=$("log"), ev=S.events||{}, stick=stuck(box); clear(box);
  if(!ev.present){box.appendChild(el("span","ts",S.phase==="not_started"?"No events yet: the run has not started.\n":"This run keeps no event log (made before the monitor existed); stage records come from state.json.\n"));}
  else{ if(ev.truncated) box.appendChild(el("span","ts","... earlier lines in events.jsonl\n"));
    (ev.lines||[]).forEach(function(l){box.appendChild(el("span","ts",clock(l.t)+"  ")); var cls=l.kind==="event"?((l.event==="failed"||l.event==="crashed"||l.event==="interrupted")?"bad":"ev"):null;
      box.appendChild(el("span",cls,(l.msg||"")+"\n"));});}
  if(stick) box.scrollTop=box.scrollHeight; box.dataset.seen="1";
  var tl=S.tool_log, tb=$("toollog"), tstick=stuck(tb); $("toolhd").classList.toggle("hidden",!tl); clear(tb);
  if(tl){$("toolpath").textContent=tl.path+" (newest tool log, last lines)"; tb.textContent=(tl.lines||[]).join("\n"); tb.classList.remove("hidden");
    if(tstick) tb.scrollTop=tb.scrollHeight; tb.dataset.seen="1";} else tb.classList.add("hidden");}

function render(){header(); liveLabel(); banner(); notices(); stats(); timeline(); surfaces(); logs();}

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

function poll(){if(!LIVE) return; if(document.hidden){schedule(4000); return;}
  fetch("summary.json",{cache:"no-store",credentials:"same-origin"}).then(function(r){if(!r.ok) throw new Error(r.status); return r.json();})
  .then(function(j){S=j; lost=false; misses=0; lastOk=Date.now(); fetchedAt=Date.now(); render(); schedule(["running","quiet","not_started"].indexOf(S.phase)>=0?2000:10000);})
  .catch(function(){var was=lost; lost=true; misses++; if(!was) render(); else {liveLabel(); banner(); notices();}
    schedule(ended()?Math.min(60000,5000*misses):5000);});}
function schedule(ms){if(timer) clearTimeout(timer); timer=setTimeout(poll,ms);}

theme(); $("export").addEventListener("click",exportJson); render();
window.addEventListener("resize",wireAll);
try{window.matchMedia("(prefers-color-scheme: light)").addEventListener("change",wireAll);}catch(e){}
setInterval(function(){liveLabel(); tickElapsed();},1000);
document.addEventListener("visibilitychange",function(){if(!document.hidden) schedule(50);});
if(LIVE) schedule(2000);
})();
"""

_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="referrer" content="no-referrer">
%CSPMETA%<title>AP Monitor</title>
<style>%CSS%</style>
</head>
<body>
<div class="wrap">
<header class="top">
 <div class="row" style="flex:1 1 300px"><div class="tile" aria-hidden="true">%LOGO%</div>
 <div style="min-width:0"><div class="brand"><span class="full">AutoPipeline Monitor</span><span class="short">AP Monitor</span></div><div class="sec" style="font-size:12px">A live view of one run folder. Nothing leaves this machine.</div></div></div>
 <div class="capsule"><span id="h-sample">sample</span><span class="pill" id="h-volume">volume</span><span class="pill mono" id="h-digest">plan</span><button class="ghost" id="theme" type="button" aria-label="Colour theme">Theme: auto</button></div>
</header>
<section class="intro">
 <div style="min-width:0;flex:1 1 420px"><h1 id="title" class="wrapany">run</h1><div class="sub" id="subtitle"></div><div class="mono sec wrapany" id="folder" style="margin-top:4px"></div>
 <div id="target" class="hidden" style="margin-top:8px"><span class="pill amber tag">Target run: maps stay private</span></div></div>
 <div class="live"><div class="livelab"><span class="dot" id="livedot"></span><span id="livetext">Loading</span></div><div class="fine" id="updated"></div></div>
</section>
<div id="banner" class="banner t-grey" role="status" aria-live="polite">
 <div class="btile" id="b-icon" aria-hidden="true"></div>
 <div class="btext" style="min-width:0;flex:1 1 200px"><h2 id="b-title">Reading the run folder</h2><p id="b-detail" class="wrapany"></p></div>
 <span class="badge" id="b-badge"></span>
</div>
<div class="notices" id="notices"></div>
<section class="stats" id="stats" aria-label="Run numbers"></section>
<section class="card" aria-label="Stage timeline">
 <div class="hd"><div><h3>Stage timeline</h3><div class="sec">Each stage's latest attempt, on the wall clock, from state.json and events.jsonl</div></div>
 <span class="spacer"></span><span class="pill mint tag">Measured</span>
 <button class="icon" id="export" type="button" title="Export the summary as JSON: the run's records and log lines, without the folder's path, the host or the process id" aria-label="Export the summary as JSON">%EXPORT%</button></div>
 <div class="strip" id="strip" aria-hidden="true"></div><div class="striplab" id="striplab" aria-hidden="true"></div>
 <div class="gantt" id="gantt"></div>
 <div class="axis" id="axis"><span></span><span></span><span></span><span class="ticks"><span id="ax0"></span><span id="ax1"></span><span id="ax2"></span></span></div>
 <div class="legend"><span><i style="background:rgba(var(--mint-rgb),.78)"></i>Done or running</span><span><i style="background:rgba(var(--amber-rgb),.85)"></i>Failed or stopped</span><span><i style="background:rgba(var(--blue-rgb),.7)"></i>Handed off</span><span><i style="background:rgba(var(--grey-rgb),.35)"></i>Skipped</span><span><i style="background:var(--idle)"></i>Not run</span></div>
</section>
<section aria-label="Surfaces">
 <div class="row" style="margin:0 2px 12px;flex-wrap:wrap"><h3 style="margin:0;font-size:16px;font-weight:600">Surfaces</h3><span class="fine" id="surf-count"></span><span class="spacer"></span><span class="pill amber tag">Model output, not a reading</span></div>
 <div class="surfaces" id="surfaces"></div>
 <div class="fine" id="thumbnote" style="margin:10px 2px 0"></div>
</section>
<section class="card" aria-label="Log">
 <div class="hd"><div><h3>Log tail</h3><div class="sec">Progress lines and stage events from events.jsonl, in this viewer's local time; &lt;run&gt; is this run folder, &lt;kit&gt; the kit home, ~ the home folder</div></div></div>
 <div class="log mono" id="log"></div>
 <div id="toolhd" class="hidden" style="margin-top:14px"><div class="label" id="toolpath"></div></div>
 <div class="log mono hidden" id="toollog" style="margin-top:8px;max-height:260px"></div>
</section>
<footer><span>Local only: this page reads one folder on this machine and sends nothing anywhere.</span><span style="text-align:right">Every map and score is model output, not a reading. Maps of target scrolls must not be shared.</span></footer>
</div>
%TEMPLATES%
<script type="application/json" id="summary">%SUMMARY%</script>
<script>%JS%</script>
</body>
</html>
"""


def _embed(summary):
    """The summary as JSON safe inside a <script> element: <, > and & as \\u escapes."""
    return (json.dumps(summary, default=str, separators=(",", ":")).replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("&", "\\u0026"))


def page(summary, live=True):
    """The monitor page: one self-contained HTML document with the summary embedded; live pages poll
    summary.json on the server they came from, a snapshot (live=False) makes no request at all."""
    css = _CSS.replace("%DARK%", _tokens(_DARK)).replace("%LIGHT%", _tokens(_LIGHT))
    js = _JS.replace("%LIVE%", "true" if live else "false")
    meta = "" if live else ('<meta http-equiv="Content-Security-Policy" content="'
                            + CSP.replace("connect-src 'self'", "connect-src 'none'") + '">\n')
    templates = "".join(f'<template id="ic-{k}">{v}</template>' for k, v in _ICONS.items())
    return (_HTML.replace("%CSPMETA%", meta).replace("%CSS%", css).replace("%LOGO%", _ICONS["logo"])
            .replace("%EXPORT%", _ICONS["export"]).replace("%TEMPLATES%", templates).replace("%JS%", js)
            .replace("%SUMMARY%", _embed(summary)))


# ---------------------------------------------------------------- snapshot

def snapshot(folder, out_file, ctx=None, **kw):
    """Write one self-contained HTML page of the run folder (summary and thumbnails embedded) to out_file, which
    must lie outside the run folder and, inside a repository, in a folder git ignores (AGENTS.md rule 6). A
    relative out_file is taken from the current directory. Returns its path."""
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
    tmp.write_text(page(summary, live=False), encoding="utf-8")
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

    def _refuse(self):
        self.server.monitor.send(self, 405, b"read-only: GET only\n", "text/plain; charset=utf-8",
                                 extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse


class Monitor:
    """A read-only HTTP server of one run folder: the page at /, the summary at /summary.json, ink map thumbnails at
    /thumb/<surface>/<model>/<f|r>.png and traced meshes' wireframes at /wire/<surface>.json (both found through
    state.json, under the thumbnails' rule). Nothing else is served."""

    def __init__(self, folder, host=LOCAL, port=DEFAULT_PORT, **kw):
        self.folder = Path(folder).resolve()
        self.kw = kw
        self.host = host
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
                body = page(summarize(self.folder, **self.kw), live=True).encode("utf-8")
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
    """A Monitor bound to host:port (port 0: any free one), not yet serving; .start() serves it in a thread."""
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
    a.add_argument("--thumbs", choices=("auto", "on", "off"), default="auto",
                   help="ink map thumbnails (auto: on for smoke runs and published labelled segments only)")
    a.add_argument("--stale-minutes", type=float, default=STALE_S / 60,
                   help="no update for this long and a running stage looks stopped (default 30)")
    a.add_argument("--text", action="store_true",
                   help="print the run as text in this terminal, ink maps drawn in characters, and exit (no server)")
    a.add_argument("--width", type=int, default=40, help="--text: a map's width in characters (default 40)")
    a.add_argument("--color", choices=("auto", "on", "off"), default="auto",
                   help="--text: maps in grey half blocks, two pixels a character (auto: on in a terminal "
                        "unless NO_COLOR is set)")
    a.add_argument("--dither", action="store_true", help="--text, without colour: ordered (Bayer) dithering")
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
                path = snapshot(folder, args.snapshot, ctx=ctx, **kw)
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
            mon = serve(folder, args.host, args.port, **kw)
        except OSError as exc:
            print(f"error: cannot listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
            return 2
        print(f"monitor: {mon.url} (read-only; Ctrl-C stops it)", file=sys.stderr, flush=True)
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
