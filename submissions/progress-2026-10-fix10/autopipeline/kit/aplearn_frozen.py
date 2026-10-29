"""Reviewable, local-only learner advice. No execution or evaluation of runs.

A digest detects changes; it does not authenticate the observations. Verification
also rebuilds the advice from its frozen request and compact record snapshot.
"""

import json
import math
from pathlib import Path

from . import aplearn as learn

FORMAT = 1
MAX_BYTES = 16 * 1024 * 1024
SOURCES = ("aplearn.py", "aplearn_frozen.py", "autopipe.py", "apbackends.py")
RECORD_KEYS = ("v", "kind", "source", "run", "plan_digest", "sample", "volume", "purpose", "scope",
               "excluded", "started", "decided", "ended", "arm", "arm_key", "planned", "traces", "umbilicus")
TRACE_KEYS = ("sid", "seed_index", "repeat", "outcome", "review")
AXIS_KEYS = ("source", "estimator", "asked", "seconds", "kept", "settings", "grids", "volume",
             "axis_grids", "box_axis", "sha256_source", "sha256", "path", "reuse_refused")
FIELDS = {"format", "request", "sources", "reserve_sha256", "records", "advice", "sha256"}
REQUEST = {"sample", "settings", "volume", "target", "outcome"}


def _keys(obj, keys, name):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise learn.LearnError(f"frozen advice {name}: expected exactly {', '.join(sorted(keys))}")


def _json_value(obj):
    if isinstance(obj, dict):
        if not all(isinstance(k, str) for k in obj):
            raise learn.LearnError("frozen advice needs string object keys")
        for v in obj.values():
            _json_value(v)
    elif isinstance(obj, list):
        for v in obj:
            _json_value(v)
    elif isinstance(obj, float) and not math.isfinite(obj):
        raise learn.LearnError("frozen advice numbers must be finite")
    elif obj is not None and not isinstance(obj, (str, bool, int, float)):
        raise learn.LearnError("frozen advice contains a non-JSON value")


def fingerprints():
    root = Path(__file__).resolve().parent
    sources = {name: learn._sha256(root / name) for name in SOURCES}
    reserve = root / "data" / "autopipe-reserved.json"
    return sources, learn._sha256(reserve) if reserve.exists() else None


def _positive(value, name, upper=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or (upper and value > upper):
        raise learn.LearnError(f"frozen advice {name}: expected a positive whole number" +
                               (f" at most {upper}" if upper else ""))


def _request_impl(req):
    from . import autopipe
    _keys(req, REQUEST, "request")
    _json_value(req)
    if not isinstance(req["sample"], str) or not req["sample"].strip():
        raise learn.LearnError("frozen advice sample must be a nonempty string")
    if not isinstance(req["settings"], dict):
        raise learn.LearnError("frozen advice settings must be an object")
    if not isinstance(req["volume"], str) or not req["volume"]:
        raise learn.LearnError("frozen advice needs the exact scan id in volume (or settings.volume)")
    if isinstance(req["target"], bool) or not isinstance(req["target"], (int, float)) or not 0 < req["target"] < 1:
        raise learn.LearnError("frozen advice target must be between zero and one")
    if req["outcome"] not in ("kept", "qa"):
        raise learn.LearnError("frozen advice outcome must be kept or qa")
    s = learn.merged_settings(req["settings"])
    if s["purpose"] == "target":
        raise learn.LearnError("frozen advice refuses target plans; use their preregistered settings")
    why = learn._scope_why(req["sample"], learn.scope({"settings": s}), set(learn.held_out_samples()))
    if why:
        raise learn.LearnError(f"frozen advice refuses reserved inputs: {why}")
    if req["volume"] and s.get("volume") and req["volume"] != s["volume"]:
        raise learn.LearnError("frozen advice volume disagrees with settings.volume")
    _positive(s["trace"]["generations"], "trace.generations")
    _positive(s["trace"].get("repeats", 1), "trace.repeats", autopipe.MAX_REPEATS)
    if not isinstance(s["umbilicus"]["source"], str) or not s["umbilicus"]["source"].strip():
        raise learn.LearnError("frozen advice umbilicus.source must be a nonempty string")
    autopipe.check_settings(s, req["sample"])
    return s


def _request(req):
    from . import autopipe
    try:
        return _request_impl(req)
    except (TypeError, KeyError, AttributeError, OverflowError, autopipe.AutoError) as exc:
        raise learn.LearnError(f"invalid frozen advice request: {exc}") from exc


def snapshot(records):
    """Only fields used by advice; no map scores, stage payloads, notes or timing evidence."""
    out = []
    for rec in records:
        if not learn.well_formed(rec):
            raise learn.LearnError("frozen advice contains a malformed learner record")
        if rec.get("purpose") == "target" or learn.in_experiment(rec["run"]):
            raise learn.LearnError("frozen advice never includes target run records")
        if learn.excluded_now(rec, set(learn.held_out_samples())):
            continue
        r = {k: rec.get(k) for k in RECORD_KEYS}
        r["planned"] = {k: (rec.get("planned") or {}).get(k) for k in ("generations", "segment")}
        scope = rec.get("scope") or {"segment": r["planned"]["segment"], "transfer": []}
        r["scope"] = {k: scope.get(k) for k in ("segment", "transfer")}
        r["traces"] = [{k: t.get(k) for k in TRACE_KEYS} for t in rec.get("traces") or []]
        r["umbilicus"] = {k: rec["umbilicus"].get(k) for k in AXIS_KEYS} if rec.get("umbilicus") else None
        out.append(r)
    return out


def _records_impl(records):
    from . import autopipe
    if not isinstance(records, list):
        raise learn.LearnError("frozen advice records must be a list")
    if snapshot(records) != records:
        raise learn.LearnError("frozen advice records contain unknown, excluded or noncanonical fields")
    seen = set()
    for r in records:
        if type(r["v"]) is not int or r["v"] != learn.VERSION:
            raise learn.LearnError("frozen advice record version is unsupported")
        if r["purpose"] not in (None, "benchmark", "smoke"):
            raise learn.LearnError("frozen advice record purpose is invalid")
        if not isinstance(r["sample"], str) or not r["sample"].strip():
            raise learn.LearnError("frozen advice record needs a sample")
        key = learn.identity(r) or (r["source"], r["run"])
        if key in seen:
            raise learn.LearnError("frozen advice repeats a run record")
        seen.add(key)
        arm = r["arm"]
        if arm is None and any(t["outcome"] in ("accepted", "rejected") for t in r["traces"]):
            raise learn.LearnError("frozen advice trace outcomes need a trace arm")
        if arm is not None:
            _keys(arm, {"trace", "settings", "seeds", "rule"}, "record arm")
            if not isinstance(arm["settings"], dict) or not isinstance(arm["seeds"], dict):
                raise learn.LearnError("frozen advice record arm settings and seeds must be objects")
            if not isinstance(arm["trace"], str) or not isinstance(arm["rule"], str):
                raise learn.LearnError("frozen advice record arm needs a backend and rule digest")
            if r["arm_key"] != learn.digest(arm)[:16]:
                raise learn.LearnError("frozen advice record arm digest disagrees")
            # params is already a digest in a harvested arm; the other trace settings keep plan shapes.
            autopipe._merge(autopipe.DEFAULTS["trace"], {k: v for k, v in arm["settings"].items()
                                                       if k != "params"}, "trace.")
            _positive(arm["settings"].get("generations"), "record generations")
            if not isinstance(arm["seeds"].get("given"), bool):
                raise learn.LearnError("frozen advice record seeds need given=true or false")
            if set(arm["seeds"]) - {"given", *learn.SEEDS_SAMPLER}:
                raise learn.LearnError("frozen advice record seeds contain unknown fields")
        axis = r["umbilicus"]
        if axis is not None:
            for k in ("path", "sha256", "sha256_source", "settings", "source", "asked", "grids", "volume"):
                if axis[k] is not None and not isinstance(axis[k], str):
                    raise learn.LearnError(f"frozen advice axis {k} must be a string or null")
            if axis["path"] and (not axis["sha256"] or len(axis["sha256"]) != 64 or
                                 any(c not in "0123456789abcdef" for c in axis["sha256"])):
                raise learn.LearnError("frozen advice reusable axis needs a SHA-256 receipt")
        ids, slots = set(), set()
        for t in r["traces"]:
            if not isinstance(t["sid"], str) or not t["sid"] or t["sid"] in ids:
                raise learn.LearnError("frozen advice trace ids must be nonempty and unique within a run")
            ids.add(t["sid"])
            if t["outcome"] not in ("accepted", "rejected", "void") or t["review"] not in (None, "accept", "reject"):
                raise learn.LearnError("frozen advice record has an unknown outcome or review")
            for k in ("seed_index", "repeat"):
                if t[k] is not None and (isinstance(t[k], bool) or not isinstance(t[k], int) or t[k] < 0):
                    raise learn.LearnError(f"frozen advice record {k} must be a nonnegative whole number")
            if t["seed_index"] is not None and t["repeat"] is not None:
                slot = t["seed_index"], t["repeat"]
                if slot in slots:
                    raise learn.LearnError("frozen advice repeats a seed/repeat observation within a run")
                slots.add(slot)


def _records(records):
    from . import autopipe
    try:
        _records_impl(records)
    except (TypeError, KeyError, AttributeError, OverflowError, autopipe.AutoError) as exc:
        raise learn.LearnError(f"invalid frozen advice records: {exc}") from exc


def _advice(req, records):
    sug = learn.suggest(records, req["sample"], req["settings"], req["volume"], req["target"], req["outcome"])
    learn.check_overlay(sug["settings"])
    # The existing API uses integer repeat-count keys; a saved JSON object uses strings.
    return json.loads(json.dumps(sug, allow_nan=False))


def freeze(records, sample, settings=None, volume=None, target=learn.REPEATS_TARGET, outcome="kept"):
    """Build a versioned, self-contained advice artifact from supplied eligible records."""
    if settings is not None and not isinstance(settings, dict):
        raise learn.LearnError("frozen advice settings must be an object")
    if not isinstance(records, list):
        raise learn.LearnError("frozen advice records must be a list")
    req = {"sample": sample, "settings": settings if settings is not None else {},
           "volume": volume if volume is not None else (settings or {}).get("volume"),
           "target": target, "outcome": outcome}
    _json_value(req)
    _request(req)
    compact = snapshot(records)
    _json_value(compact)
    _records(compact)
    sources, reserve = fingerprints()
    obj = {"format": FORMAT, "request": req, "sources": sources, "reserve_sha256": reserve,
           "records": compact, "advice": _advice(req, compact)}
    obj["sha256"] = learn.digest(obj)
    # Check the identical path used for untrusted loaded artifacts before offering it for review.
    verify(obj)
    return obj


def verify(obj):
    """Validate and recompute saved advice, without reading today's ledger or evaluating any outcome."""
    from . import autopipe
    try:
        _keys(obj, FIELDS, "object")
        _json_value(obj)
        if type(obj["format"]) is not int or obj["format"] != FORMAT:
            raise learn.LearnError("unsupported frozen advice format")
        sources, reserve = fingerprints()
        if obj["sources"] != sources or obj["reserve_sha256"] != reserve:
            raise learn.LearnError("frozen advice source or reserve fingerprint changed; freeze a new proposal")
        if obj["sha256"] != learn.digest({k: v for k, v in obj.items() if k != "sha256"}):
            raise learn.LearnError("frozen advice sha256 disagrees with its contents")
        _request(obj["request"])
        _records(obj["records"])
        expected = _advice(obj["request"], obj["records"])
        if learn.digest(expected) != learn.digest(obj["advice"]):
            raise learn.LearnError("frozen advice is not supported by its request and records (or an axis changed)")
        # Check both the allowed keys and the values after combining with the frozen caller settings.
        s = learn.merged_settings(learn._deep(expected["settings"], obj["request"]["settings"]))
        _positive(s["trace"]["generations"], "trace.generations")
        _positive(s["trace"].get("repeats", 1), "trace.repeats", autopipe.MAX_REPEATS)
        autopipe.check_settings(s, obj["request"]["sample"])
        return {"status": "VALID", "sha256": obj["sha256"], "sample": obj["request"]["sample"],
                "changes": expected["changes"], "records": len(obj["records"]),
                "note": "Reproducible advice, not authenticated observations or proof of improvement; no job ran."}
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError, autopipe.AutoError) as exc:
        raise learn.LearnError(f"invalid frozen advice: {exc}") from exc


def read(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise learn.LearnError(f"frozen advice duplicate JSON key: {key}")
            out[key] = value
        return out
    try:
        with Path(path).open("rb") as f:
            raw = f.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise learn.LearnError(f"frozen advice exceeds {MAX_BYTES} bytes")
        obj = json.loads(raw, object_pairs_hook=pairs)
        verify(obj)
        return obj
    except (OSError, ValueError, RecursionError) as exc:
        raise learn.LearnError(f"cannot read frozen advice: {exc}") from exc


def write(path, obj):
    verify(obj)
    raw = json.dumps(obj, indent=1, allow_nan=False) + "\n"
    if len(raw.encode()) > MAX_BYTES:
        raise learn.LearnError(f"frozen advice exceeds {MAX_BYTES} bytes")
    # Exclusive creation also refuses existing and dangling symlinks. Parent must already exist.
    with Path(path).open("x", encoding="utf-8") as f:
        f.write(raw)
    return {"file": str(path), **verify(obj), "request": obj["request"], "advice": obj["advice"]}


def for_plan(obj, sample, settings=None):
    """Replay the frozen request. Only explicit overrides of learnable settings may be added."""
    verify(obj)
    req = obj["request"]
    if sample != req["sample"]:
        raise learn.LearnError("frozen advice belongs to another sample")
    if settings is not None and not isinstance(settings, dict):
        raise learn.LearnError("settings must be an object")
    supplied = settings or {}
    base = learn._flat(learn.merged_settings(req["settings"]))
    base["volume"] = req["volume"]
    for key, value in learn._flat(learn._backends_applied(supplied)).items():
        if key not in learn.LEARNABLE and (key not in base or learn.digest(base[key]) != learn.digest(value)):
            raise learn.LearnError(f"frozen advice context changed at {key}; freeze a new proposal")
    given = learn._deep(req["settings"], supplied)
    given["volume"] = req["volume"]
    _request({**req, "settings": given})
    sug = json.loads(json.dumps(obj["advice"]))
    overridden = learn.given_keys(supplied)
    sug["changes"] = [c for c in sug["changes"] if c["key"] not in overridden]
    sug["overridden"] = sorted(overridden.intersection(learn.LEARNABLE))
    sug["frozen_sha256"] = obj["sha256"]
    return learn._deep(sug["settings"], given), sug


def check_plan(obj, sug, plan):
    """Resolve the catalog before writing a plan, and refuse a changed scan/axis rather than recompute advice."""
    verify(obj)
    req = obj["request"]
    if (plan.get("resolved") or {}).get("sample") != req["sample"]:
        raise learn.LearnError("frozen advice sample differs from the resolved plan")
    if req["volume"] and (plan.get("resolved") or {}).get("volume") != req["volume"]:
        raise learn.LearnError("frozen advice scan differs from the resolved plan")
    why = learn.axis_conflict(sug, plan)
    if why:
        raise learn.LearnError(f"frozen advice axis conflict: {why}; freeze a new proposal")
