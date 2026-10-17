"""AutoPipeline over every released scan: per-scan config, priced plan, resumable queue, watcher. Launches nothing.

  python -m kit run all --dry-run [--state DIR] [--refresh] [--only SAMPLE[/VOLUME]] [--include-superseded]
      catalog every volume in the open-data bucket (kit/scancatalog.py), make each one's config, price it, write
      the batch plan (DIR/plan.json, DIR/plan.md, one DIR/scans/<sample>/<volume>/status.json each) and a dry-run
      row per scan in DIR/batch-ledger.csv. Prints the plan digest the owner approves.
  python -m kit run all --status [--state DIR]      per-scan status table and totals
  python -m kit run all --approve DIGEST            record the owner's approval of exactly that priced plan; still
                                                     launches nothing (scans move to "approved")
  python -m kit run watch [--state DIR] [--json] [--exit-code]
      for a scheduled routine: rebuild the catalog, diff it against the last one seen (DIR/catalog.json), queue every
      new or changed volume as "planned", priced, in dry-run, print the new scans, and save the catalog. Exit 0; with
      --exit-code, exit 3 when something new was queued.

Idempotent and resumable: a scan's status file is keyed by its config digest. Rerunning with nothing changed rewrites
nothing; a scan whose status is "done" (or "running") is skipped; a scan whose config changed goes back to "planned".
Statuses: planned, approved, running, done, failed, skipped (with a reason), blocked (with a reason).

Launch: this module never starts Modal. After the owner approves a priced plan, each approved scan's Modal launch is the
existing per-run path (scrolls-kit autopipeline plan in the released package, then its Modal runner with its own budget checks and ledger
row; docs/autopipeline/README.md section 11). plan.json lists the command for each scan.

Privacy: batch runs are purpose "benchmark" or "smoke" on public scans. The batch never takes title settings and
writes nothing public (state lives in the git-ignored work/ folder); a config naming title work is refused.

Prices are Modal list rates (kit/data/modal-rates.json through kit/cloudcost.py) times stage hours from the
assumptions in COST_MODEL, calibrated on the billed PHerc0841 w00 run (0.27 USD: 249 L4 seconds, 4892 CPU seconds).
They are estimates (low, typical, high), not quotes. Standard library only.
"""

import csv
import hashlib
import json
import math
import shlex
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import cloudcost, prizes, scancatalog

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "work" / "autobatch"
STATUSES = ("planned", "approved", "running", "done", "failed", "skipped", "blocked")
FINISHED = ("done", "running")
LEDGER_COLUMNS = ("date_time_et", "key", "sample", "volume", "voxel_um", "status", "ink_readers",
                  "est_low_usd", "est_typical_usd", "est_high_usd", "plan_digest", "note")

# Ink reader by level-0 voxel size (owner, 16 Oct 2026; measured on PHerc0139 w043: Hecate 2.4 um AUC 0.940,
# canonical 2um 0.887, Hecate 9.6 um 0.922; model output on one segment, which is not held out: w043 is ink_9um
# training data, docs/logs/2026-10-08-w045-not-held-out.md). Fine scans read with
# Hecate 2.4 um; coarse scans with the team's ink_9um and Hecate 9.6 um (after kit hecateprep's resample to 9.6 um).
READERS = (
    (3.5, ["hecate-2.4um"], "fine scan: Hecate 2.4 um (best on w043, which is not held out)"),
    (6.5, ["hecate-2.4um", "hecate-9.6um"], "middle: Hecate 2.4 um and Hecate 9.6 um (resampled), compared"),
    (20.0, ["ink_9um-seed42", "hecate-9.6um"], "coarse scan: ink_9um and Hecate 9.6 um (resampled)"),
)
READER_SPEC = {
    "hecate-2.4um": {"repo": "scrollprize/hecate", "file": "hecate_2.4um.pth",
                     "revision": "9cb86e500e944b11a06a7020403cde5dffb5bcb2", "cost_factor": 2.0},
    "hecate-9.6um": {"repo": "scrollprize/hecate", "file": "hecate_9.6um.pth",
                     "revision": "9cb86e500e944b11a06a7020403cde5dffb5bcb2", "cost_factor": 1.0,
                     "prep": "kit hecateprep prep --target-um 9.6"},
    "ink_9um-seed42": {"repo": "scrollprize/ink_9um", "file": "hybrid_3d2d-seed42/step-075000.pth",
                       "revision": "main", "cost_factor": 1.0},
}

# Stage hours (typical) and the machines they run on, matching scripts/vc3d/modal_autopipe.py's decorators.
COST_MODEL = {
    "surfaces_per_scan": 4,            # seeds traced, rendered and read per scan
    "spread": {"low": 0.5, "typical": 1.0, "high": 2.5},
    "plan_h": 0.1,                     # headers, axis estimate, plan: cpu_long 8 cores 32 GiB
    "grid_h_per_tvox": 0.6,            # normal-grid cache per 1e12 level-0 voxels: cpu_grid 4 cores 32 GiB
    "grid_h_min": 0.25, "grid_h_max": 3.0,
    "trace_render_h": 0.4,             # per surface: cpu_arm 8 cores 32 GiB
    "ink_h_at_9um": 0.07,              # per surface per reader at 9 um, f r s variants: L4 8 cores 32 GiB
    "ink_h_max": 1.0,                  # the GPU step's work limit (GPU_WORK_S 3600 s)
    "surfacepred_h_per_tvox": 2.0,     # scans with no published surface prediction: H100 8 cores 64 GiB
    "surfacepred_h_min": 0.5, "surfacepred_h_max": 8.0,
    "driver_usd_per_h": 0.016,
}
# Ink models AutoPipeline itself registers (kit/vc3d_catalog.py KNOWN_MODELS). The Hecate readers run through
# their own runner until they are registered; the plan lists them per scan.
AUTOPIPE_MODELS = ("ink_9um-seed42", "ink_9um-seed43", "reader-v2", "d9v2", "v8in")
MACHINES = {"plan": (None, 8, 32), "grid": (None, 4, 32), "trace_render": (None, 8, 32), "ink": ("L4", 8, 32),
            "surfacepred": ("H100", 8, 64)}


class BatchError(Exception):
    pass


def _now_et():
    """Now in US Eastern time, whatever the machine's own zone (cloud and Modal machines run on UTC)."""
    try:
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    except ZoneInfoNotFoundError:   # no time zone database (Windows without tzdata): say UTC, not ET
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def readers_for(voxel_um):
    if not isinstance(voxel_um, (int, float)) or voxel_um <= 0:
        return [], "no voxel size"
    for top, names, why in READERS:
        if voxel_um <= top:
            return list(names), why
    return [], f"{voxel_um} um is coarser than any released ink reader (20 um limit)"


def zarr_levels(zattrs):
    """[(level path, scale zyx)] from an OME-Zarr .zattrs document."""
    out = []
    for ms in (zattrs or {}).get("multiscales", [])[:1]:
        for d in ms.get("datasets", []):
            scale = next((t.get("scale") for t in d.get("coordinateTransformations", []) if t.get("type") == "scale"),
                         None)
            out.append({"path": str(d.get("path")), "scale": scale})
    return out


def _inside(state, path):
    """path, after checking that it resolves inside the state folder (ids come from the bucket and metadata.json)."""
    path = Path(path)
    if not path.resolve().is_relative_to(Path(state).resolve()):
        raise BatchError(f"{path} is outside the batch folder {state}")
    return path


def _check_ids(row):
    for k in ("sample", "volume"):
        if not scancatalog.safe_id(row.get(k)):
            raise BatchError(f"{k} id {str(row.get(k))[:80]!r} is not a safe name")


def fetch_levels(row, cache_dir, get=scancatalog.http_get):
    """The volume's zarr levels, read once from its .zattrs and cached under cache_dir.

    A failed read raises BatchError, so the scan is rejected and retried on the next run instead of being
    planned and priced at level 0."""
    if not row.get("zarr_url"):
        return None
    _check_ids(row)
    cache = _inside(cache_dir, Path(cache_dir) / "zattrs" / f"{row['sample']}_{row['volume']}.json")
    if cache.is_file():
        return json.loads(cache.read_text())
    try:
        doc = json.loads(get(row["zarr_url"] + ".zattrs"))
    except (OSError, ValueError) as exc:
        raise BatchError(f"cannot read {row['zarr_url']}.zattrs ({str(exc)[:120]}), so the scan's levels and price "
                         "are unknown; the next run tries again") from exc
    levels = zarr_levels(doc)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(levels))
    return levels


def fetch_shape(row, cache_dir, get=scancatalog.http_get):
    """Level-0 shape (z, y, x) from the zarr's 0/.zarray when metadata.json gives none; cached."""
    if not row.get("zarr_url"):
        return None
    _check_ids(row)
    cache = _inside(cache_dir, Path(cache_dir) / "zattrs" / f"{row['sample']}_{row['volume']}.shape.json")
    if cache.is_file():
        return json.loads(cache.read_text())
    try:
        shape = json.loads(get(row["zarr_url"] + "0/.zarray"))["shape"]
    except (OSError, ValueError, KeyError):
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(shape))
    return shape


def with_shape(row, state, get):
    if row.get("shape_zyx") or not row.get("in_bucket") or not row.get("in_metadata"):
        return row
    shape = fetch_shape(row, state, get)
    return {**row, "shape_zyx": shape, "shape_source": "zarr 0/.zarray"} if shape else row


def pick_level(levels, voxel_um, want_um):
    """The coarsest level whose voxel is at most want_um (level 0 when none is coarser)."""
    best = 0
    for i in range(len(levels or [])):
        if voxel_um * (2 ** i) <= want_um + 1e-9:
            best = i
    return best


def scan_config(row, levels=None, model=None):
    """The automatic per-scan config: voxel, levels, readers, the AutoPipeline settings, and why a scan is skipped."""
    model = model or COST_MODEL
    um = row.get("voxel_um")
    names, why = readers_for(um)
    skip = block = None
    if not row.get("in_bucket"):
        block = "not in the open-data bucket (catalog points to another host; the bucket is the only source)"
    elif row.get("superseded_by"):
        sb = row["superseded_by"]
        skip = f"superseded by {sb.get('volume_id') if isinstance(sb, dict) else sb}"
    elif not row.get("in_metadata"):
        block = "in the bucket listing but not in metadata.json: no headers yet (watch picks it up when it appears)"
    elif not row.get("shape_zyx"):
        block = "no shape in metadata.json"
    elif not scancatalog.valid_shape(row["shape_zyx"]):
        block = f"shape {str(row['shape_zyx'])[:80]} is not three positive integers"
    elif not names:
        block = why
    preds = row.get("surface_predictions") or []
    cfg = {
        "sample": row["sample"], "volume": row["volume"], "long_id": row.get("long_id"),
        "zarr_url": row.get("zarr_url"), "voxel_um": um, "shape_zyx": row.get("shape_zyx"),
        "levels": [l["path"] for l in levels] if levels else None,
        "trace_level": pick_level(levels, um, 9.6) if (levels and um) else None,
        "ink_level": pick_level(levels, um, 2.4 if names[:1] == ["hecate-2.4um"] else 9.6) if (levels and um) else None,
        "readers": names, "reader_rule": why,
        "readers_spec": {n: READER_SPEC[n] for n in names},
        "needs_surface_prediction": not preds,
        "autopipe_settings": {"purpose": "benchmark" if row.get("ink_labels") else "smoke",
                              "volume": row["volume"],
                              "ink": {"where": "modal", "variants": ["f", "r", "s"],
                                      "models": [n for n in names if n in AUTOPIPE_MODELS] or ["ink_9um-seed42"]},
                              "trace": {"normal_grids": "auto" if row.get("normal_grids") else "off"}},
        "readers_outside_autopipe": [n for n in names if n not in AUTOPIPE_MODELS],
        "surfaces": model["surfaces_per_scan"],
    }
    try:
        # Ids and names come from the bucket (a volume folder may well say "subtitle"); the check is on the rest.
        refuse_title({k: v for k, v in cfg.items() if k not in ID_FIELDS})
        refuse_title({k: v for k, v in cfg["autopipe_settings"].items() if k != "volume"}, "config.autopipe_settings")
    except BatchError as exc:
        block = block or f"refused: {exc}"
    cfg["digest"] = digest(cfg)
    cfg["skip"], cfg["block"] = skip, block
    return cfg


ID_FIELDS = ("sample", "volume", "long_id", "zarr_url", "autopipe_settings")


def refuse_title(obj, path="config"):
    """Batch configs carry only the generic AutoPipeline settings; title settings are refused."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "title" in str(k).lower():
                raise BatchError(f"{path}.{k}: title settings are not allowed in a batch config")
            refuse_title(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            refuse_title(v, f"{path}[{i}]")
    elif isinstance(obj, str) and "title" in obj.lower():
        raise BatchError(f"{path}: title work is not allowed in a batch config")


def _hours(cfg, model):
    z, y, x = cfg["shape_zyx"]
    tvox = z * y * x / 1e12
    um = cfg["voxel_um"] * 2 ** (cfg.get("ink_level") or 0)   # the reader sees the ink level's voxels
    n = cfg["surfaces"]
    clamp = lambda v, lo, hi: max(lo, min(hi, v))
    h = {"plan": model["plan_h"],
         "grid": clamp(model["grid_h_per_tvox"] * tvox, model["grid_h_min"], model["grid_h_max"]),
         "trace_render": model["trace_render_h"] * n,
         "ink": sum(min(model["ink_h_max"], model["ink_h_at_9um"] * (9.0 / um) ** 2 *
                        READER_SPEC[r]["cost_factor"]) for r in sorted(
                            set(cfg["readers"]) | set(cfg["autopipe_settings"]["ink"]["models"]))) * n}
    if cfg["needs_surface_prediction"]:
        h["surfacepred"] = clamp(model["surfacepred_h_per_tvox"] * tvox, model["surfacepred_h_min"],
                                 model["surfacepred_h_max"])
    return h


def price(cfg, rates=None, model=None):
    """{"hours": {stage: h}, "usd": {low, typical, high}, "stages_usd": {...}} for one scan's config."""
    model = model or COST_MODEL
    if cfg.get("skip") or cfg.get("block"):
        return {"hours": {}, "stages_usd": {}, "usd": {k: 0.0 for k in model["spread"]}}
    rates = rates or cloudcost.load_rates()
    hours = _hours(cfg, model)
    stages = {}
    for stage, h in hours.items():
        gpu, cpu, mem = MACHINES[stage]
        stages[stage] = round(cloudcost.container_cost(rates, h, gpu=gpu, cpu=cpu, mem_gib=mem)["total"], 4)
    typical = sum(stages.values()) + model["driver_usd_per_h"] * sum(hours.values())
    usd = {k: round(typical * f, 2) for k, f in model["spread"].items()}
    return {"hours": {k: round(v, 3) for k, v in hours.items()}, "stages_usd": stages, "usd": usd}


def _status_path(state, cfg):
    _check_ids(cfg)
    return _inside(state, Path(state) / "scans" / cfg["sample"] / cfg["volume"] / "status.json")


def read_status(state, cfg):
    p = _status_path(state, cfg)
    return json.loads(p.read_text()) if p.is_file() else None


def _write_if_changed(path, doc):
    path = Path(path)
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if path.is_file() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return True


def queue_scan(state, cfg, cost):
    """Create or refresh a scan's status; never moves a finished scan back. Returns (status, changed)."""
    old = read_status(state, cfg)
    if old and old.get("status") in FINISHED and old.get("digest") == cfg["digest"]:
        return old["status"], False
    if cfg.get("block"):
        status, reason = "blocked", cfg["block"]
    elif cfg.get("skip"):
        status, reason = "skipped", cfg["skip"]
    elif (old and old.get("digest") == cfg["digest"] and old.get("status") in ("approved", "failed")
          and old.get("cost") == cost):   # an approval holds only for the price the owner saw
        status, reason = old["status"], old.get("reason")
    else:
        status, reason = "planned", None
    doc = {"key": f"{cfg['sample']}/{cfg['volume']}", "digest": cfg["digest"], "status": status, "reason": reason,
           "config": cfg, "cost": cost, "history": (old or {}).get("history", [])}
    if not old or old.get("status") != status or old.get("digest") != cfg["digest"]:
        doc["history"] = doc["history"] + [{"at": _now_et(), "status": status, "digest": cfg["digest"]}]
    _write_if_changed(_status_path(state, cfg).with_name("settings.json"), cfg["autopipe_settings"])
    return status, _write_if_changed(_status_path(state, cfg), doc)


def ledger_row(state, cfg, status, cost, plan_digest, note=""):
    """Append one dry-run row per (scan, config digest, plan digest); a rerun adds nothing."""
    path = Path(state) / "batch-ledger.csv"
    k = f"{cfg['sample']}/{cfg['volume']}@{cfg['digest']}#{plan_digest}"
    if path.is_file():
        with open(path, newline="") as fh:
            if any(r.get("key") == k for r in csv.DictReader(fh)):
                return False
    new = not path.is_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, LEDGER_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({"date_time_et": _now_et(), "key": k, "sample": cfg["sample"], "volume": cfg["volume"],
                    "voxel_um": cfg["voxel_um"], "status": f"dry-run {status}", "ink_readers": " ".join(cfg["readers"]),
                    "est_low_usd": cost["usd"]["low"], "est_typical_usd": cost["usd"]["typical"],
                    "est_high_usd": cost["usd"]["high"], "plan_digest": plan_digest, "note": note})
    return True


def launch_command(cfg):
    q, s, v = shlex.quote, cfg["sample"], cfg["volume"]
    return (f"scrolls-kit autopipeline plan {q(s)} --settings {q(f'@work/autobatch/scans/{s}/{v}/settings.json')} "
            f"--out {q(f'work/autobatch/runs/{s}-{v}')}")


def load_catalog(state, refresh=False, fetch=None):
    path = Path(state) / "catalog.json"
    if path.is_file() and not refresh:
        return json.loads(path.read_text())
    doc = (fetch or (lambda: scancatalog.fetch(prizes.load())))()
    scancatalog.write(doc, path)
    return doc


ROW_ERRORS = (BatchError, TypeError, ValueError, KeyError, AttributeError, IndexError, ZeroDivisionError, OverflowError)


def _prepare(r, state, get, rates, include_superseded=False):
    """(row, config, cost) for one catalog row; a malformed row raises one of ROW_ERRORS."""
    _check_ids(r)
    r = with_shape(r, state, get)
    lv = fetch_levels(r, state, get) if r.get("in_bucket") else None
    cfg = scan_config(r, lv)
    if include_superseded and cfg["skip"] and cfg["skip"].startswith("superseded"):
        cfg["skip"] = None
    return r, cfg, price(cfg, rates)


def _rejected(r, exc):
    key = f"{str(r.get('sample'))[:80]}/{str(r.get('volume'))[:80]}" if isinstance(r, dict) else str(r)[:160]
    return {"key": key, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def plan_all(state=STATE, catalog=None, only=None, include_superseded=False, levels_get=None, rates=None):
    """Plan, price and queue every volume; write plan.json, plan.md and the dry-run ledger rows.

    A malformed catalog row (unsafe id, repeated key, wrong types) is listed under "rejected" and planned no further;
    it never stops the rest of the batch."""
    state = Path(state)
    catalog = catalog if catalog is not None else load_catalog(state)
    rows = [r for r in catalog["volumes"]
            if not only or (isinstance(r, dict) and (scancatalog.key(r) == only or r.get("sample") == only))]
    entries, rejected, keys = [], [], set()
    for r in rows:
        try:
            r, cfg, cost = _prepare(r, state, levels_get or scancatalog.http_get, rates, include_superseded)
            if scancatalog.key(r) in keys:
                raise BatchError(f"duplicate key {scancatalog.key(r)}")
            if "prize_eligible" not in r or "era" not in r:
                raise BatchError("row has no prize_eligible or era: rebuild the catalog with --refresh")
        except ROW_ERRORS as exc:
            rejected.append(_rejected(r, exc))
            continue
        keys.add(scancatalog.key(r))
        entries.append((r, cfg, cost))
    plan = {"schema": 1, "catalog_checked": catalog.get("checked"), "cost_model": COST_MODEL,
            "scans": [{"key": scancatalog.key(r), "digest": c["digest"], "voxel_um": c["voxel_um"],
                       "readers": c["readers"], "trace_level": c["trace_level"], "ink_level": c["ink_level"], "levels": c["levels"],
                       "needs_surface_prediction": c["needs_surface_prediction"], "skip": c["skip"],
                       "block": c["block"], "usd": p["usd"], "hours": p["hours"],
                       "prize_eligible": r["prize_eligible"], "era": r["era"],
                       "command": None if (c["skip"] or c["block"]) else launch_command(c)}
                      for r, c, p in entries]}
    plan["total_usd"] = {k: round(sum(s["usd"][k] for s in plan["scans"]), 2) for k in COST_MODEL["spread"]}
    plan["counts"] = {}
    plan["rejected"] = rejected
    plan_digest = _plan_digest(plan)
    plan["digest"] = plan_digest
    for r, c, p in entries:
        status, _ = queue_scan(state, c, p)
        plan["counts"][status] = plan["counts"].get(status, 0) + 1
        ledger_row(state, c, status, p, plan_digest, c["skip"] or c["block"] or "")
    if not only:
        _write_if_changed(state / "plan.json", plan)
        (state / "plan.md").write_text(plan_markdown(plan))
    return plan


def plan_markdown(plan):
    lines = [f"# AutoPipeline batch plan {plan['digest']} (dry run; nothing launched)", "",
             f"Catalog checked {plan['catalog_checked']}. Estimates at Modal list rates, not quotes.", "",
             "| scan | um | readers | level | surf pred | low | typical | high | status |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in plan["scans"]:
        st = "skip: " + s["skip"] if s["skip"] else ("blocked: " + s["block"] if s["block"] else "planned")
        lines.append(f"| {s['key']} | {s['voxel_um']} | {' '.join(s['readers'])} | {s['trace_level']} | "
                     f"{'needed' if s['needs_surface_prediction'] else 'published'} | {s['usd']['low']} | "
                     f"{s['usd']['typical']} | {s['usd']['high']} | {st} |")
    t = plan["total_usd"]
    lines += ["", f"Total: low {t['low']} USD, typical {t['typical']} USD, high {t['high']} USD.", ""]
    return "\n".join(lines)


def _plan_digest(plan):
    return digest({"scans": plan["scans"], "total": plan["total_usd"]})


def _approvable(state, s):
    """(status path, status doc) of a planned scan whose files still match what plan.json priced, or None.

    Raises BatchError when the status, its config or settings.json were changed after pricing."""
    sample, _, volume = str(s.get("key", "")).partition("/")
    p = _status_path(state, {"sample": sample, "volume": volume})
    if not p.is_file():
        return None
    doc = json.loads(p.read_text())
    if doc.get("status") != "planned" or doc.get("digest") != s["digest"]:
        return None
    cfg = doc.get("config") or {}
    settings = p.with_name("settings.json")
    if (digest({k: v for k, v in cfg.items() if k not in ("digest", "skip", "block")}) != doc["digest"]
            or (doc.get("cost") or {}).get("usd") != s["usd"]
            or not settings.is_file() or json.loads(settings.read_text()) != cfg.get("autopipe_settings")):
        raise BatchError(f"{s['key']}: status, config, cost or settings.json changed after pricing: run --dry-run again")
    return p, doc


def approve(state, plan_digest):
    state = Path(state)
    plan = json.loads((state / "plan.json").read_text())
    try:
        actual = _plan_digest(plan)
    except (KeyError, TypeError) as exc:
        raise BatchError(f"plan.json is malformed ({exc}): run --dry-run again") from exc
    if plan.get("digest") != actual:
        raise BatchError(f"plan.json was edited after it was priced (contents hash to {actual}): run --dry-run again")
    if actual != plan_digest:
        raise BatchError(f"plan digest is {actual}, not {plan_digest}: approve the plan you priced")
    todo = [x for x in (_approvable(state, s) for s in plan["scans"]) if x]   # check every scan before writing any
    n = 0
    for p, doc in todo:
        doc["status"] = "approved"
        doc["history"].append({"at": _now_et(), "status": "approved", "plan": plan_digest})
        _write_if_changed(p, doc)
        n += 1
    _write_if_changed(state / "approval.json", {"plan": plan_digest, "at": _now_et(), "approved_scans": n,
                                                "total_usd": plan["total_usd"]})
    return n


def status_table(state):
    out = []
    for p in sorted(Path(state).glob("scans/*/*/status.json")):
        d = json.loads(p.read_text())
        out.append({"key": d["key"], "status": d["status"], "reason": d.get("reason"),
                    "typical_usd": d["cost"]["usd"]["typical"]})
    return out


def watch(state=STATE, fetch=None, levels_get=None, rates=None):
    """Diff a fresh catalog against the last one seen, queue new or changed volumes (dry run), save the catalog."""
    state = Path(state)
    path = state / "catalog.json"
    old = json.loads(path.read_text()) if path.is_file() else None
    new = (fetch or (lambda: scancatalog.fetch(prizes.load())))()
    d = scancatalog.diff(old, new)
    queued, rejected = [], []
    for change, r in [("new", r) for r in d["new"]] + [("changed", r) for r in d["changed"]]:
        try:
            r, cfg, cost = _prepare(r, state, levels_get or scancatalog.http_get, rates)
        except ROW_ERRORS as exc:   # one bad row is reported, never fails every scheduled run
            rejected.append({**_rejected(r, exc), "change": change})
            continue
        status, _ = queue_scan(state, cfg, cost)
        ledger_row(state, cfg, status, cost, "watch", change)
        queued.append({"key": scancatalog.key(r), "change": change,
                       "status": status, "voxel_um": cfg["voxel_um"], "readers": cfg["readers"],
                       "usd": cost["usd"], "reason": cfg["skip"] or cfg["block"]})
    if rejected:   # a row that failed is saved as last seen (or not at all), so the next run tries it again
        failed = {r["key"] for r in rejected}
        before = {scancatalog.key(r): r for r in (old or {}).get("volumes", [])}
        kept = []
        for r in new["volumes"]:
            k = scancatalog.key(r)
            if k not in failed:
                kept.append(r)
            elif k in before:
                kept.append(before[k])
        new = {**new, "volumes": kept}
    scancatalog.write(new, path)
    unsafe = [{**e, "key": f"{str(e.get('sample'))[:80]}/{str(e.get('volume') or e.get('name'))[:80]}"}
              for e in new.get("rejected", [])]   # names build() left out: they carry no "key" of their own
    return {"first_run": old is None, "queued": queued, "gone": d["gone"], "catalog_volumes": len(new["volumes"]),
            "rejected": rejected + unsafe, "failed": len(rejected)}
