"""Trace budgets, partial surfaces and readable tracer logs, for AutoPipeline (AP) and the trace tool.

AP traced fresh scrolls into its own timeouts and kept nothing (a note of the source repository): villa's
`vc_grow_seg_from_seed` writes its surface only at the end, AP stopped it with SIGTERM then SIGKILL at a timeout
fixed per plan (2.4 to 7 times too low for 60 generations on villa e0bbb8b, whose 512-entry normal-grid cache
thrashes), and the log was 95 percent GridStore cache warnings, so no record said which generation a trace reached.
This module holds the pieces the fix needs, standard library only:

  TraceLog, LogWatch   read the tracer's log as it grows: the generation in progress, generations done, area,
                       seconds per generation (from its "-> done" lines), and the GridStore warnings counted and
                       left out of every tail and progress line
  read_snapshot        check the surface a trace left in its folder (x, y, z and meta.json) and read its
                       generation, area, elapsed time and stop reason; villa's "snapshot-interval" writes one every
                       N generations by an atomic folder swap, so a trace killed after its first snapshot leaves its
                       last complete one (before the first snapshot there is nothing to keep)
  recover_snapshot     move a complete surface villa's save left in its temporary folder into place, for a kill
                       between the two steps of the save's fallback on a filesystem without RENAME_EXCHANGE
  stop_record          what stopped a trace and whether its surface is a partial result (PARTIAL_KINDS), a whole
                       one (a kill after the final save), or none
  budget               a trace's time budget from a cost model fitted to measured seconds per vertex, with
                       headroom, a cold-cache factor, a cap, and a share of a work deadline (seeds before repeats)
  grid_cache_bytes     VC_GRID_CACHE_BYTES from the machine's memory and the trace's generations (villa main since
                       PR #2007)
  grid_settings        the normal-grid cache variables a trace gets on this build (VC_GRID_CACHE_BYTES on villa
                       main, VC_NORMAL_GRID_CACHE on villa e0bbb8b with a villa patch of the source repository) and its cost class

Numbers are Model output from public development data (PHerc0841 w00, PHerc0139), measured on Modal CPUs at 4
tracer threads; the cost model is an Interpretation of them, and AP calibrates it against each run's own traces.
"""

import json
import math
import re
import shutil
from collections import deque
from pathlib import Path

GRIDSTORE = "[GridStore Cache] Hitrate Warning"     # villa NormalGridVolume.cpp: printed under 99 % hits
GEN_RE = re.compile(r"^gen (\d+) processing (\d+) fringe cands")
DONE_RE = re.compile(r"^-> done (\d+) \| fringe (\d+) \| area ([0-9.]+) mm\^2.*?\| avg speed ([0-9.]+) mm\^2/s"
                     r"(?: \(([0-9.eE+-]+) m\^2/day\))?.*?\| current speed ([0-9.]+) mm\^2/s")
HIT_RE = re.compile(r"Hit Rate: ([0-9.]+)%")
STOP_RE = re.compile(r"^stopping before generation (\d+)")     # a villa patch of the source repository
TAIL_KEEP = 40                       # non-warning lines a TraceLog keeps for the tail
RECENT_GENERATIONS = 4               # one slow and one fast pair: late generations alternate (GrowPatch.cpp)
SNAPSHOT_FILES = ("x.tif", "y.tif", "z.tif", "meta.json")
STOP_REASONS = ("generations", "time_limit", "fringe_empty", "running")    # meta.json stop_reason (the patch)
# The stop reasons of a final save that ended the trace as planned: every generation placed, or nothing left to grow
WHOLE_STOP_REASONS = ("generations", "fringe_empty")
# A surface that is a partial result, by what stopped it: the patched tracer's own time limit (it saved as usual),
# AP's hard timeout or a cancel kit sent, after which the folder held a complete snapshot, or a container lost
# mid-trace whose snapshot a restart found (AP records it rather than tracing the same seed from generation 1 again).
# A signal kit did not send (the kernel's out-of-memory killer, an operator) is not one: the trace failed for a reason
# outside the plan, the snapshot stays on disk, and AP records an infrastructure failure, which a rerun retries
PARTIAL_KINDS = ("partial_time_limit", "partial_timeout", "partial_cancelled", "partial_preempted")
KILL_SIGNALS = (-9, -15)             # SIGKILL, SIGTERM: Popen's return code for a child they ended
MIN_BUDGET_S = 120                   # a trace is never given less, whatever share of a deadline is left
MODEL_THREADS = 4                    # the tracer threads the cost model's seconds per vertex were measured at
GIB = 2 ** 30
VILLA_GRID_CACHE_BYTES = 2 * GIB     # villa main's normal-grid cache budget when VC_GRID_CACHE_BYTES is unset
VILLA_GRID_CACHE_ENTRIES = 512       # villa e0bbb8b's fixed normal-grid cache, and the grid-cache bundle's default
# a villa patch of the source repository (12 Oct 2026, a 4-core Xeon, PHerc0139): 8192 grids took a 30-generation trace
# from 123.0 s to 39.6 s at 4 threads; at 60 generations the original took 384.1 s at 2 threads and the patched build
# with jemalloc 124.4 s at 4; peak memory 1.83 GB against 0.33 GB at 60 generations (much of it mapped grid files)
GRID_CACHE_ENTRIES = 8192
GRID_CACHE_ENTRIES_MIN_MEMORY = 8 * GIB

# The settings of AP's trace.budget (a module of AutoPipeline OPTIONAL), each one in the plan digest.
DEFAULTS = {
    # villa's "snapshot-interval" (hyphenated: GrowPatch.cpp reads that name; snapshot_interval is ignored): the
    # whole surface is written over the trace's folder every N generations. 81 snapshots added about 2 s to a 41 s
    # trace in the tracer study and did not change its output (TIFF hashes identical). That was one small synthetic
    # trace at one thread on local disk; the cost of a save at G200 size on a Modal Volume is not measured
    "snapshot_interval": 2,
    # a trace stopped by its time limit, AP's timeout or a cancel keeps its last complete surface as a partial
    # result, which qa checks like any other; false records it as a failure, as before
    "keep_partial": True,
    # a target plan (purpose "target") that keeps partial surfaces names where its preregistration says how they
    # count (AGENTS.md rule 3), for example "docs/prereg/2026-10-20-x.md, Readout"; make_plan refuses it otherwise
    "partial_rule": None,
    # pass "time_limit_s" when the tracer has it (a villa patch of the source repository, found by vc3d.tracer_features):
    # "auto", or "off" to rely on snapshots and the hard timeout alone
    "time_limit": "auto",
    # time_limit_s = budget - max(safety_s, twice the slowest generation measured on this run's traces), at most half
    # the budget, so the final save fits (the patch already stops before a generation it predicts would overrun);
    # the hard timeout, AP's backstop, is budget + grace_s when time_limit_s is passed, else the budget itself
    "safety_s": 120,
    "grace_s": 300,
    # budget = max(trace.timeout, estimate x headroom), at most max(max_s, trace.timeout). Under a work deadline
    # (KIT_AUTOPIPE_DEADLINE, the runner's) the time left less the reserve (reserve_s + reserve_per_surface_s for
    # each planned trace, for the stages after trace) goes to the first repeat of every seed first, then to the
    # second repeats, and so on: the traces of one round share what is left, each at least an equal share. A trace
    # whose share is under min_share_s is deferred (not run; a rerun with more time runs it)
    "headroom": 1.5,
    "max_s": 8 * 3600,
    "reserve_s": 900,
    "reserve_per_surface_s": 150,
    "min_share_s": 600,
    # a later repeat of a seed whose earlier repeat stopped short at its budget (partial_time_limit or
    # partial_timeout): "defer" it when its budget does not cover the estimate for a whole trace either (calibrated by
    # this run's measured speed), since it would stop short as the first did and a partial repeat says nothing about
    # agreement; "run" runs it anyway
    "short_repeats": "defer",
    # the run's first trace reads normal grids this machine has not cached (Model output: generation 45 at 4414 s
    # cold against 2729 to 3019 s warm on PHerc0841 w00, +46 to +62 %)
    "cold_factor": 1.5,
    # seconds per vertex placed at MODEL_THREADS threads, by the tracer's normal-grid cache. thrash: villa's
    # 512-entry cache (e0bbb8b without a villa patch of the source repository), fitted to PHerc0841 w00 t00-r1 (5417 s at 12992
    # vertices, gen 57) and t00-r0 (4943 s at 11660, gen 54). sized: a cache that holds the trace's grids (villa main
    # with enough VC_GRID_CACHE_BYTES for the generations, or the grid-cache bundle with 8192 grids or more): 129 s
    # for a G60 on PHerc0139 (0.0093 s a vertex) times 4, the unexplained factor between the two scans on the
    # unpatched build. Fewer threads cost proportionally more (thread_factor)
    "model": {"thrash_s_per_vertex": 0.42, "sized_s_per_vertex": 0.04},
    # a trace found after a lost container with a complete snapshot: kept as a partial result ("keep"), or
    # traced again from generation 1 ("retrace"). Growth is never resumed from it (a note of the source repository)
    "preempted": "keep",
    # VC_GRID_CACHE_BYTES for byte-budget builds (villa main since PR #2007; 2 GiB unset, villa measured its knee
    # near 4 GiB): "auto" is min(max(grid_cache_max_gib, 1.5 x what the trace's grids take), grid_cache_fraction x
    # the machine's memory), what they take scaling as the square of the generations from grid_cache_g200_gib (a
    # G200 trace needs about 8 GiB, villa PR #2007; a G60 trace ran with 0 warnings and 1.17 GB peak at villa's
    # 2 GiB default, 18 Oct 2026); a whole number is taken as given, null leaves villa's default
    "grid_cache_bytes": "auto",
    "grid_cache_fraction": 0.6,
    "grid_cache_max_gib": 8,
    "grid_cache_g200_gib": 8,
    # VC_NORMAL_GRID_CACHE for villa e0bbb8b built with a villa patch of the source repository (a grid count; unset, the bundle
    # keeps villa's 512): "auto" sets GRID_CACHE_ENTRIES when the environment does not already set it and the
    # machine has at least GRID_CACHE_ENTRIES_MIN_MEMORY, a whole number is taken as given, null leaves it alone.
    # An environment that sets it (the Modal runner's grid image: 32768) always wins
    "grid_cache_entries": "auto",
}
TIME_LIMIT_MODES = ("auto", "off")
PREEMPTED_MODES = ("keep", "retrace")
SHORT_REPEAT_MODES = ("defer", "run")


class BudgetError(ValueError):
    """A trace.budget setting out of range (make_plan refuses the plan)."""


# ---------------------------------------------------------------- the tracer's log

class TraceLog:
    """The tracer's log read line by line: feed() takes text as it comes (a line cut in two is kept until its
    end arrives). Each "$ " line (kit's command line, written before every run) starts a new run's record; the
    tail and the warning count run on across them."""

    def __init__(self):
        self.tail = deque(maxlen=TAIL_KEEP)
        self.gridstore = 0
        self.hit_rate = None
        self._part = ""
        self._reset()

    def _reset(self):
        self.gen_in_progress = None
        self.last_gen_line = None
        self.generations_done = None
        self.vertices_done = None
        self.area_mm2 = None
        self.elapsed_s = None
        self.gen_seconds = []           # [generation, seconds] for each generation done
        self.stopping = None

    def feed(self, text):
        lines = (self._part + text).split("\n")
        self._part = lines.pop()
        for line in lines:
            self.line(line.rstrip("\r"))
        return self

    def close(self):
        if self._part:
            self.line(self._part)
            self._part = ""
        return self

    def line(self, line):
        if GRIDSTORE in line:
            self.gridstore += 1
            m = HIT_RE.search(line)
            if m:
                self.hit_rate = float(m.group(1))
            return
        if not line.strip():
            return
        self.tail.append(line)
        if line.startswith("$ "):
            self._reset()
            return
        m = GEN_RE.match(line)
        if m:
            self.gen_in_progress = int(m.group(1))
            self.last_gen_line = line
            return
        m = DONE_RE.match(line)
        if m:
            done, area, avg = int(m.group(1)), float(m.group(3)), float(m.group(4))
            per_day = float(m.group(5)) if m.group(5) else None
            # elapsed growth time = area / average speed; m^2/day has more digits than mm^2/s (2 decimals)
            rate = per_day * 1e6 / 86400.0 if per_day else avg
            elapsed = area / rate if rate > 0 else None
            if elapsed is not None:
                prev = self.elapsed_s or 0.0
                if self.gen_in_progress is not None:
                    self.gen_seconds.append([self.gen_in_progress, round(max(0.0, elapsed - prev), 2)])
                self.elapsed_s = elapsed
            self.generations_done = self.gen_in_progress
            self.vertices_done, self.area_mm2 = done, area
            return
        m = STOP_RE.match(line)
        if m:
            self.stopping = line

    def recent_seconds(self):
        """Mean seconds per generation over the last RECENT_GENERATIONS generations done, or None."""
        last = [s for _, s in self.gen_seconds[-RECENT_GENERATIONS:]]
        return round(sum(last) / len(last), 2) if last else None

    def summary(self):
        """What the record keeps: the last "gen N" line, generations done, vertices, area, elapsed growth seconds,
        seconds of the last generation and per generation recently, and the GridStore warnings left out."""
        return {"last_gen_line": self.last_gen_line, "generation_in_progress": self.gen_in_progress,
                "generations_done": self.generations_done, "vertices_done": self.vertices_done,
                "area_mm2": self.area_mm2,
                "growth_seconds": round(self.elapsed_s, 1) if self.elapsed_s is not None else None,
                "seconds_last_generation": self.gen_seconds[-1][1] if self.gen_seconds else None,
                "seconds_per_generation_recent": self.recent_seconds(),
                "seconds_per_generation": self.gen_seconds[-12:],
                "gridstore_warnings_left_out": self.gridstore, "gridstore_hit_rate_last": self.hit_rate,
                **({"stopping": self.stopping} if self.stopping else {})}

    def tail_text(self, lines=15):
        return "\n".join(list(self.tail)[-lines:])

    def message(self, of=None):
        """One progress line, never a GridStore warning: the generation in progress (of `of`, the last generation
        the plan places), area and seconds per generation; before the first generation, the last line."""
        if self.gen_in_progress is None:
            last = self.tail[-1] if self.tail else ""
            text = last[-200:]
        else:
            text = f"gen {self.gen_in_progress}" + (f" of {of}" if of else "") + " in progress"
            if self.generations_done is not None:
                text += f", {self.generations_done} done, {self.area_mm2:.2f} mm2"
            if self.gen_seconds:
                text += f", last generation {self.gen_seconds[-1][1]:.0f} s"
        if self.gridstore:
            text += f"; {self.gridstore} GridStore cache warnings left out"
        return text


class LogWatch:
    """A TraceLog fed from a log file from `offset` on: poll() reads only what was appended since the last call
    (run_logged calls it for each progress line), so a log of millions of warning lines is read once."""

    def __init__(self, path, offset=0, of=None):
        self.path, self.offset, self.of = Path(path), int(offset), of
        self.log = TraceLog()

    def poll(self):
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return self.log.message(self.of)
        self.offset += len(data)
        self.log.feed(data.decode("utf-8", "replace"))
        return self.log.message(self.of)

    def finish(self):
        self.poll()
        self.log.close()
        return self.log


def read_log(path, offset=0):
    """A TraceLog of `path` from `offset` to its end (the trace tool reads its own run's part of trace.log)."""
    return LogWatch(path, offset).finish()


def filtered_tail(text, lines=15):
    """The last `lines` lines of `text` that are not GridStore warnings."""
    return TraceLog().feed(text).close().tail_text(lines)


# ---------------------------------------------------------------- snapshots and what stopped a trace

def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def generations_done(meta):
    """The last generation a surface holds, from its meta.json: villa writes max_gen = the generation counter,
    which on a "generations" or "time_limit" stop is one past the last placed generation (it is raised before the
    check), and in a snapshot or after an empty fringe is the last placed one."""
    g = meta.get("max_gen")
    if not isinstance(g, int) or isinstance(g, bool):
        return None
    return g - 1 if meta.get("stop_reason") in ("generations", "time_limit") else g


def read_snapshot(folder, since=None):
    """The surface in a trace's folder, checked: {"ok", "why", "path", "max_gen", "generations_done", "area_cm2",
    "elapsed_time_s", "stop_reason"}. ok needs x.tif, y.tif, z.tif and meta.json, none empty, a meta.json that
    parses with a whole max_gen of 1 or more and an area, and with `since` (epoch seconds) a meta.json written
    then or later, so a folder an earlier trace left is not taken for this one's."""
    p = Path(folder)
    out = {"ok": False, "path": str(p)}
    missing = [f for f in SNAPSHOT_FILES if not (p / f).is_file() or (p / f).stat().st_size == 0]
    if missing:
        out["why"] = f"no complete surface: {', '.join(missing)} missing or empty"
        return out
    try:
        meta = json.loads((p / "meta.json").read_text())
    except (OSError, ValueError) as exc:
        out["why"] = f"meta.json does not parse: {exc}"
        return out
    if not isinstance(meta, dict):
        out["why"] = "meta.json is not an object"
        return out
    if since is not None and (p / "meta.json").stat().st_mtime < since - 2:
        out["why"] = "the surface is older than this trace (an earlier run left it)"
        return out
    out.update({k: meta.get(k) for k in ("max_gen", "area_cm2", "elapsed_time_s", "stop_reason")})
    out["generations_done"] = generations_done(meta)
    if not isinstance(out["max_gen"], int) or isinstance(out["max_gen"], bool) or out["max_gen"] < 1:
        out["why"] = f"meta.json has no generation (max_gen {out['max_gen']!r})"
        return out
    if not _number(out["area_cm2"]) or out["area_cm2"] < 0:
        out["why"] = f"meta.json has no area (area_cm2 {out['area_cm2']!r})"
        return out
    out["ok"] = True
    return out


def recover_snapshot(target, since=None):
    """Put back a complete surface that villa's save left beside a trace's folder, when the folder itself holds
    none: {"recovered_from": path, **read_snapshot(target)}, or None when there is nothing to recover.

    villa's QuadSurface::save writes into target.parent/.tmp_<thread>/<name> and then swaps that folder in with
    renameat2(RENAME_EXCHANGE). Where the filesystem lacks RENAME_EXCHANGE (ENOSYS or EINVAL) it removes the old
    folder first and renames after, so a kill between the two leaves the only complete copy in the temporary
    folder. A temporary copy counts when read_snapshot passes it (x, y, z and meta.json, which villa writes last),
    with `since` as there; the one with the highest max_gen is moved into place."""
    target = Path(target)
    if read_snapshot(target, since=since)["ok"]:
        return None
    best = None
    for cand in sorted(target.parent.glob(f".tmp_*/{target.name}")):
        snap = read_snapshot(cand, since=since)
        if snap["ok"] and (best is None or snap["max_gen"] > best[1]["max_gen"]):
            best = (cand, snap)
    if best is None:
        return None
    try:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)       # empty (made before the run) or incomplete: this run would replace it
        elif target.exists() or target.is_symlink():
            target.unlink()
        best[0].rename(target)
    except OSError:
        return None
    out = read_snapshot(target, since=since)
    out["recovered_from"] = str(best[0])
    return out


def holds_whole_trace(snap, generations=None):
    """True when a checked surface (read_snapshot) is the trace's final save, every planned generation placed or
    nothing left to grow, rather than a snapshot taken on the way: its meta.json stop_reason is "generations" or
    "fringe_empty" (the patched tracer), or, from a tracer without the patch, its max_gen reaches `generations`
    (villa's final save writes the generation counter, one past the last placed generation; a snapshot writes the
    last placed one), or it holds the last planned generation (generations - 1). An unpatched tracer's final save
    after an empty fringe cannot be told from a snapshot by its meta.json: it counts as partial when the trace did
    not exit 0."""
    snap = snap or {}
    if not snap.get("ok"):
        return False
    sr = snap.get("stop_reason")
    if sr in WHOLE_STOP_REASONS:
        return True
    if sr == "time_limit":
        return False
    g, done = snap.get("max_gen"), snap.get("generations_done")
    if not isinstance(generations, int) or isinstance(generations, bool) or generations < 2:
        return False
    return (isinstance(g, int) and g >= generations) or (isinstance(done, int) and done >= generations - 1)


def whole_generations(snap, generations):
    """The last generation a whole surface holds: the last planned one when the tracer placed them all (its max_gen
    is the counter, one past it), else what read_snapshot read (an empty fringe)."""
    if snap.get("stop_reason") == "fringe_empty":
        return snap.get("generations_done")
    return generations - 1 if isinstance(generations, int) else snap.get("generations_done")


def partial_kind(rc, snap, generations=None):
    """The partial result a trace's end makes (PARTIAL_KINDS), or None for a whole one or none at all: rc is the
    trace tool's exit (0, a code, "timeout", "cancelled", ...), snap read_snapshot of its folder after the run,
    generations the planned count. A surface holding the whole trace (holds_whole_trace: a kill that came after the
    final save) is not partial, and neither is one left by a signal kit did not send (KILL_SIGNALS)."""
    if not (snap or {}).get("ok"):
        return None
    if rc == 0:
        return "partial_time_limit" if snap.get("stop_reason") == "time_limit" else None
    if holds_whole_trace(snap, generations):
        return None
    if rc == "timeout":
        return "partial_timeout"
    if rc == "cancelled":
        return "partial_cancelled"
    return None


def preempted_kind(snap, generations=None):
    """What a surface found after a lost process or container is (keep_preempted): None when it holds the whole
    trace (the tracer finished and saved before the loss), "partial_time_limit" when the patched tracer stopped at
    its own limit and saved, else "partial_preempted" (its last snapshot)."""
    if holds_whole_trace(snap, generations):
        return None
    return "partial_time_limit" if (snap or {}).get("stop_reason") == "time_limit" else "partial_preempted"


def stop_record(rc, snap, log_summary=None, generations=None):
    """What stopped a trace: {"exit", "reason", "partial", "whole", "snapshot", "max_gen", "generations_done",
    "generations_planned", "area_cm2", "elapsed_time_s"} plus the log's progress (TraceLog.summary). whole: the
    surface is the trace's final save although the tracer did not exit 0 (a timeout or signal that came after it).
    A signal kit did not send gives "external_signal" and, when a snapshot was left, "snapshot_left" (its path)."""
    snap = snap or {}
    kind = partial_kind(rc, snap, generations)
    done = snap.get("generations_done")
    whole = rc != 0 and holds_whole_trace(snap, generations) and rc not in KILL_SIGNALS
    if whole:
        done = whole_generations(snap, generations)
    if rc == 0:
        sr = snap.get("stop_reason")
        if sr and sr != "running":
            reason = sr
        elif not snap.get("ok"):
            reason = snap.get("why") or "no surface"
        else:
            # a tracer without the patch writes no stop reason, and its max_gen is one past the last generation
            # after a "generations" stop but the last one after an empty fringe: the log says which
            logged = (log_summary or {}).get("generations_done")
            if logged is not None:
                done = logged
            elif isinstance(snap.get("max_gen"), int) and isinstance(generations, int) and \
                    snap["max_gen"] >= generations:
                done = generations - 1
            last = generations - 1 if isinstance(generations, int) and generations > 1 else None
            reason = "generations" if last is None or (isinstance(done, int) and done >= last) else \
                "ended before its last generation (an empty fringe or the tracer's limits)"
    elif rc in ("timeout", "cancelled"):
        reason = rc + (", after the tracer saved its whole surface" if whole else "")
    elif rc in KILL_SIGNALS:
        reason = f"killed by signal {-rc}, not sent by kit (the out-of-memory killer or an operator)"
    else:
        reason = str(rc)
    rec = {"exit": rc, "reason": reason, "partial": kind, "whole": whole,
           "snapshot": bool(snap.get("ok")) and rc != 0 and not whole,
           "generations_planned": generations, "generations_done": done,
           **{k: snap.get(k) for k in ("max_gen", "area_cm2", "elapsed_time_s")}}
    if rc in KILL_SIGNALS:
        rec["external_signal"] = -rc
        if snap.get("ok"):
            rec["snapshot_left"] = snap.get("path")
    if snap and not snap.get("ok") and rc != 0:
        rec["no_snapshot"] = snap.get("why")
    if log_summary:
        rec["progress"] = log_summary
    return rec


# ---------------------------------------------------------------- the cost model and the budget

def check_settings(cfg):
    """Refusals for a trace.budget object (make_plan's): every key known, every value in range."""
    if not isinstance(cfg, dict):
        raise BudgetError("trace.budget is an object (or true for its defaults)")
    unknown = sorted(set(cfg) - set(DEFAULTS))
    if unknown:
        raise BudgetError(f"trace.budget has no setting {', '.join(unknown)}")
    si = cfg["snapshot_interval"]
    if isinstance(si, bool) or not isinstance(si, int) or not 0 <= si <= 1000:
        raise BudgetError("trace.budget.snapshot_interval is a whole number of generations from 0 to 1000 (0: none)")
    if not isinstance(cfg["keep_partial"], bool):
        raise BudgetError("trace.budget.keep_partial is true or false")
    pr = cfg["partial_rule"]
    if pr is not None and (not isinstance(pr, str) or not pr.strip() or len(pr) > 300):
        raise BudgetError("trace.budget.partial_rule is null or where the preregistration says how partial surfaces "
                          "count (a short text, at most 300 characters)")
    if cfg["time_limit"] not in TIME_LIMIT_MODES:
        raise BudgetError(f"trace.budget.time_limit is one of {TIME_LIMIT_MODES}")
    if cfg["preempted"] not in PREEMPTED_MODES:
        raise BudgetError(f"trace.budget.preempted is one of {PREEMPTED_MODES}")
    if cfg["short_repeats"] not in SHORT_REPEAT_MODES:
        raise BudgetError(f"trace.budget.short_repeats is one of {SHORT_REPEAT_MODES}")
    for k, lo, hi in (("safety_s", 0, 7200), ("grace_s", 0, 7200), ("reserve_s", 0, 86400),
                      ("reserve_per_surface_s", 0, 7200), ("min_share_s", MIN_BUDGET_S, 86400),
                      ("max_s", MIN_BUDGET_S, 7 * 86400), ("headroom", 1, 10), ("cold_factor", 1, 10),
                      ("grid_cache_fraction", 0.01, 0.95), ("grid_cache_max_gib", 0.25, 1024),
                      ("grid_cache_g200_gib", 0.25, 1024)):
        if not _number(cfg[k]) or not lo <= cfg[k] <= hi:
            raise BudgetError(f"trace.budget.{k} is a number from {lo} to {hi}")
    model = cfg["model"]
    if not isinstance(model, dict) or set(model) != set(DEFAULTS["model"]) or not all(
            _number(v) and 0 < v <= 60 for v in model.values()):
        raise BudgetError(f"trace.budget.model holds {sorted(DEFAULTS['model'])}, each a number of seconds above 0 "
                          "and at most 60")
    g = cfg["grid_cache_bytes"]
    if g is not None and g != "auto" and (isinstance(g, bool) or not isinstance(g, int) or g < 64 * 2 ** 20):
        raise BudgetError("trace.budget.grid_cache_bytes is auto, null or a whole number of bytes of 64 MiB or more")
    e = cfg["grid_cache_entries"]
    if e is not None and e != "auto" and (isinstance(e, bool) or not isinstance(e, int) or not 16 <= e <= 10 ** 7):
        raise BudgetError("trace.budget.grid_cache_entries is auto, null or a whole number of grids from 16 to "
                          "10000000")


def vertices(generations):
    """The vertex count of a fresh, unbounded trace run to `generations`: villa places generations 2 to G - 1,
    and every candidate of an unbounded fresh trace is placed, so after generation n it holds 4 n^2 - 4 vertices
    (12 after generation 2; 13920 after generation 59, the last of a G60 trace). A bounded trace holds fewer."""
    n = max(int(generations) - 1, 2)
    return 4 * n * n - 4


def grid_bytes_needed(cfg, generations):
    """Bytes of normal grids a trace of `generations` keeps in use, scaled as the square of the generations (the
    area it covers) from grid_cache_g200_gib at 200, never under villa's own default (VILLA_GRID_CACHE_BYTES, which
    a G60 trace ran within with no warning). An Interpretation of two points (a note of the source repository)."""
    g = generations if isinstance(generations, int) and not isinstance(generations, bool) and generations > 0 else 60
    return max(VILLA_GRID_CACHE_BYTES, int(cfg.get("grid_cache_g200_gib", 8) * GIB * (g / 200.0) ** 2))


def grid_cache_bytes(cfg, memory, generations=None):
    """VC_GRID_CACHE_BYTES for this machine under trace.budget, or None to leave villa's default: a whole number
    as given; "auto" as min(max(grid_cache_max_gib, 1.5 x grid_bytes_needed), grid_cache_fraction x memory), None
    when memory is unknown or when that comes out under villa's own default (VILLA_GRID_CACHE_BYTES): villa keeps at
    least 512 grids under its default budget but takes an explicit VC_GRID_CACHE_BYTES at its word
    (NormalGridVolume.cpp at 1db9cd9), so a smaller value set by kit could hold fewer grids than leaving it unset."""
    v = (cfg or {}).get("grid_cache_bytes", "auto")
    if v is None:
        return None
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if not memory:
        return None
    cap = max(cfg["grid_cache_max_gib"] * GIB, 1.5 * grid_bytes_needed(cfg, generations))
    n = int(min(cap, cfg["grid_cache_fraction"] * memory))
    return n if n > VILLA_GRID_CACHE_BYTES else None


def grid_cache_entries(cfg, env=None, memory=None):
    """(VC_NORMAL_GRID_CACHE kit sets, or None, and where the trace's value comes from): for villa e0bbb8b with
    a villa patch of the source repository. An environment that sets the variable keeps it ("environment"); null leaves it unset
    ("unset"); a whole number is taken as given ("plan"); "auto" sets GRID_CACHE_ENTRIES when the machine has
    GRID_CACHE_ENTRIES_MIN_MEMORY or more ("plan"), else leaves villa's 512 ("unset")."""
    if str((env or {}).get("VC_NORMAL_GRID_CACHE") or "").strip():
        return None, "environment"
    v = (cfg or {}).get("grid_cache_entries", "auto")
    if v is None:
        return None, "unset"
    if isinstance(v, int) and not isinstance(v, bool):
        return v, "plan"
    if memory and memory >= GRID_CACHE_ENTRIES_MIN_MEMORY:
        return GRID_CACHE_ENTRIES, "plan"
    return None, "unset"


def cache_class(features, cache_bytes=None, env=None, entries=None, generations=None, cfg=None):
    """"sized" when the tracer's normal-grid cache holds a trace's grids, else "thrash": a byte-budget build
    (villa main) whose budget (cache_bytes, else villa's 2 GiB default) is at least 4 GiB, villa's own sweep's knee,
    and at least what the trace's generations need (grid_bytes_needed, with cfg's grid_cache_g200_gib), or the
    grid-cache bundle with 8192 grids or more (entries, the value kit sets, else VC_NORMAL_GRID_CACHE in env).
    Anything else, an unknown build included, is costed as the 512-entry cache."""
    kind = (features or {}).get("grid_cache")
    if kind == "bytes":
        have = cache_bytes or VILLA_GRID_CACHE_BYTES
        need = max(4 * GIB, grid_bytes_needed(cfg or DEFAULTS, generations))
        return "sized" if have >= need else "thrash"
    if kind == "entries":
        n = entries
        if not n:
            try:
                n = int((env or {}).get("VC_NORMAL_GRID_CACHE") or VILLA_GRID_CACHE_ENTRIES)
            except ValueError:
                n = VILLA_GRID_CACHE_ENTRIES
        return "sized" if n >= GRID_CACHE_ENTRIES else "thrash"
    return "thrash"


def _env_int(env, name):
    try:
        v = int(str((env or {}).get(name) or "").strip())
    except ValueError:
        return None
    return v if v >= 0 else None


def grid_settings(cfg, features, memory=None, env=None, generations=None):
    """The normal-grid cache settings a trace gets under trace.budget on this build: {"kind", "grid_cache_bytes",
    "grid_cache_entries", "bytes_from", "entries_from", "class"}. grid_cache_bytes and grid_cache_entries are what
    kit sets (VC_GRID_CACHE_BYTES and VC_NORMAL_GRID_CACHE), or None; the *_from fields say where the tracer's
    value comes from ("plan", "environment", "unset" or "not this build"); class is the cost model's (cache_class).

    By the build's kind (features["grid_cache"], kit.vc3d.tracer_features): "bytes" (villa main since PR #2007)
    gets VC_GRID_CACHE_BYTES from grid_cache_bytes; "entries" (villa e0bbb8b with a villa patch of the source repository) gets
    VC_NORMAL_GRID_CACHE from grid_cache_entries; "fixed" (plain e0bbb8b, a 512-entry cache no variable changes)
    gets neither; "unknown" (no tracer file could be read) gets both, since each build ignores the other's
    variable. A variable the environment already sets is never changed (the Modal grid image sets 32768 grids)."""
    kind = (features or {}).get("grid_cache") or "unknown"
    rec = {"kind": kind, "grid_cache_bytes": None, "grid_cache_entries": None, "bytes_from": "not this build",
           "entries_from": "not this build"}
    env_bytes = _env_int(env, "VC_GRID_CACHE_BYTES")
    if kind in ("bytes", "unknown"):
        if env_bytes is not None:
            rec["bytes_from"] = "environment"
        else:
            rec["grid_cache_bytes"] = grid_cache_bytes(cfg, memory, generations)
            rec["bytes_from"] = "plan" if rec["grid_cache_bytes"] else "unset"
    if kind in ("entries", "unknown"):
        rec["grid_cache_entries"], rec["entries_from"] = grid_cache_entries(cfg, env, memory)
    effective_bytes = env_bytes if rec["bytes_from"] == "environment" else rec["grid_cache_bytes"]
    if kind == "bytes" and effective_bytes == 0:
        # VC_GRID_CACHE_BYTES=0 turns villa main's byte budget off: the old 512-entry cache
        rec["class"] = "thrash"
    else:
        rec["class"] = cache_class(features, effective_bytes, env, rec["grid_cache_entries"], generations, cfg)
    return rec


def measured_rate(speeds, min_vertices=1000):
    """The highest seconds per vertex among this run's traces that placed at least min_vertices (late
    generations cost more a vertex, so a short trace says little), or None."""
    rates = [s["s_per_vertex"] for s in (speeds or {}).values()
             if _number(s.get("s_per_vertex")) and (s.get("vertices") or 0) >= min_vertices]
    return max(rates) if rates else None


def slowest_generation(speeds):
    """The longest single generation in seconds among this run's traces (their recent seconds per generation), or
    None: the time limit's safety margin is twice it."""
    secs = []
    for s in (speeds or {}).values():
        for pair in s.get("seconds_per_generation") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and _number(pair[1]):
                secs.append(float(pair[1]))
        if _number(s.get("seconds_per_generation_recent")):
            secs.append(float(s["seconds_per_generation_recent"]))
    return max(secs) if secs else None


def speed_record(summary, seconds=None):
    """A trace's measured speed for calibration, from its log summary: generations and vertices done, growth
    seconds, seconds per vertex, and seconds per generation recently. None when it placed nothing."""
    s = summary or {}
    v, t = s.get("vertices_done"), s.get("growth_seconds") or seconds
    if not v or not _number(t) or t <= 0:
        return None
    return {"generations_done": s.get("generations_done"), "vertices": v, "growth_seconds": round(t, 1),
            "s_per_vertex": round(t / v, 5), "seconds_per_generation_recent": s.get("seconds_per_generation_recent"),
            "seconds_per_generation": (s.get("seconds_per_generation") or [])[-RECENT_GENERATIONS:]}


def thread_factor(threads):
    """How much slower than at MODEL_THREADS a trace at `threads` tracer threads is costed: MODEL_THREADS / threads
    below it (linear, the cautious guess), 1 at or above it, since no speed-up past 4 threads was measured (the same
    G60 on Modal: 179 s on 2 cores, 129 s on 4, 171 s on 8, 127 s on 16; a script of the source repository cpu_grid)."""
    if not isinstance(threads, int) or isinstance(threads, bool) or threads < 1:
        return 1.0
    return max(1.0, MODEL_THREADS / threads)


def estimate_s(cfg, generations, cls="thrash", cold=False, measured=None, threads=None):
    """Seconds a whole trace of `generations` is expected to take: vertices(generations) x the class's seconds
    per vertex x thread_factor (x cold_factor when cold), raised to what `measured` (seconds per vertex of this run's
    earlier traces, at this run's threads) gives."""
    v = vertices(generations)
    est = v * cfg["model"][f"{cls}_s_per_vertex"] * thread_factor(threads) * (cfg["cold_factor"] if cold else 1.0)
    if _number(measured) and measured > 0:
        est = max(est, v * measured)
    return est


def budget(cfg, generations, plan_timeout, cls="thrash", cold=False, measured=None, deadline=None, now=None,
           traces_left=1, time_limit=False, threads=None, after_short=False, surfaces=None,
           slowest_generation_s=None, ceiling_s=None):
    """One trace's budget under trace.budget `cfg`: {"estimate_s", "wanted_s", "budget_s", "time_limit_s",
    "hard_timeout_s", "defer", ...}.

    estimate = estimate_s(...); wanted = estimate x headroom; budget = max(plan_timeout, wanted), at most
    max(max_s, plan_timeout), and with ceiling_s at most max(plan_timeout, ceiling_s). With `deadline` (epoch
    seconds) and `now`, the window is deadline - now - (reserve_s + reserve_per_surface_s x surfaces), and the traces
    of this trace's round (traces_left: the round's traces not yet traced, this one included; the first repeats of
    every seed are the first round) share it: this one gets the larger of an equal share and what the window leaves
    after the others' warm estimates, and the budget is at most that. A share under min_share_s defers the trace
    ("defer" says why), and so does a later repeat of a seed whose earlier repeat stopped short at its budget
    (after_short) when this budget does not cover a warm estimate either, under short_repeats "defer". time_limit: whether the tracer takes time_limit_s;
    then it is the budget less the safety margin (max(safety_s, 2 x slowest_generation_s), at most half the
    budget), and the hard timeout is budget + grace_s."""
    v = vertices(generations)
    rate = cfg["model"][f"{cls}_s_per_vertex"]
    est = estimate_s(cfg, generations, cls, cold, measured, threads)
    warm = estimate_s(cfg, generations, cls, False, measured, threads)
    wanted = est * cfg["headroom"]
    floor = float(plan_timeout or 0)
    cap = max(float(cfg["max_s"]), floor)
    rec = {"generations": generations, "vertices": v, "class": cls, "cold": bool(cold), "threads": threads,
           "thread_factor": thread_factor(threads), "s_per_vertex": rate, "measured_s_per_vertex": measured,
           "estimate_s": round(est), "warm_estimate_s": round(warm), "wanted_s": round(wanted),
           "plan_timeout_s": plan_timeout, "after_short": bool(after_short)}
    if _number(ceiling_s) and ceiling_s < cap:
        cap = max(floor, float(ceiling_s))
        rec["ceiling_s"] = round(cap)
    b = min(max(floor, wanted), cap)
    if wanted > cap:
        rec["capped_at_s"] = round(cap)
    defer = None
    if deadline is not None and now is not None:
        reserve = float(cfg["reserve_s"]) + float(cfg["reserve_per_surface_s"]) * int(surfaces or 0)
        window = float(deadline) - float(now) - reserve
        n = max(1, int(traces_left))
        share = max(window / n, window - (n - 1) * warm)
        rec.update(window_s=round(window), reserve_s=round(reserve), traces_left=n, deadline_share_s=round(share))
        if share < b:
            b = max(float(MIN_BUDGET_S), share)
            rec["cut_by_deadline"] = True
        if share < cfg["min_share_s"]:
            defer = (f"the work deadline leaves this trace {max(0, round(share))} s, under min_share_s "
                     f"{cfg['min_share_s']}")
    if defer is None and after_short and cfg["short_repeats"] == "defer" and b < warm:
        defer = (f"an earlier repeat of this seed stopped short at its budget, and this one's budget ({round(b)} s) "
                 f"does not cover a whole trace's estimate ({round(warm)} s) either: it would stop short too and say "
                 "nothing about agreement")
    rec["budget_s"] = round(b)
    rec["short_of_wanted"] = b < wanted
    rec["defer"] = defer
    if time_limit:
        slow = 2.0 * slowest_generation_s if _number(slowest_generation_s) else 0.0
        safety = min(max(float(cfg["safety_s"]), slow), 0.5 * b)
        rec["safety_s"] = round(safety)
        rec["time_limit_s"] = round(b - safety)
        rec["hard_timeout_s"] = round(b + cfg["grace_s"])
    else:
        rec["time_limit_s"] = None
        rec["hard_timeout_s"] = round(b)
    return rec
