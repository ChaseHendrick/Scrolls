"""The planted-hop benchmark: does a surface prediction keep touching sheets apart? `kit hopbench`.

Where two sheets of a scroll touch, a traced surface can step from one onto the next without crossing any gap. A
surface prediction that draws the two touching sheets as one thick run hides that step; one that keeps a thin
dark line between them shows it. This benchmark plants such hops into copies of PHerc0139's published hand-traced
windings, at places where two neighboring windings really come within 4 voxels of each other, and asks whether the
one-sheet check of kit/sheetgap.py, reading the prediction along the mesh normal, still joins the two sides. It
also measures, on clean 20 mm windows of single windings, the largest square the check calls one sheet. Run it
on m7 (the default), recto-090, or your own prediction in m7's frame.

  refs   download the windings w023 to w040 and build their manifest (kit/sheetrefs.py)
  run    calibrate the check's run thickness on the clean windows, score the clean windows and the planted hops,
         and write OUT/hopbench.json

Arms. none: plain 8-connected regions of every valid point (a plant counts only when this joins its two sides).
seated: the per-point on-sheet test (a run of the prediction within 2 voxels), 8-connected. gap: the one-sheet
check. truth (clean windows only): points with no other hand-traced winding within 8 voxels, an upper bound that
needs hand traces. A good prediction makes the gap arm join few plants and keep large squares.

Public data only (the open-data bucket); CPU only; about 37 minutes on 4 cores with an empty cache and about 6 GB of
memory; m7's chunks for these windings take 0.75 GB. Model output about geometry; nothing here is a reading.
"""

import concurrent.futures
import json
import math
import sys
import time
from pathlib import Path

from . import sheetgap as sg
from . import sheetrefs as sr

SEED = 20261016
CLEAN_MM = 20.0
WINDOWS_PER_WINDING = 1
PLANT_MM = 6.0
SITES_PER_PAIR = 4
CONTACT_VOX = 4.0
COPY_VOX = 8.0
FAR_VOX = 6.0
MIN_SIDE_VOX2 = 1600.0
THICK_QUANTILE = 0.95
THICK_CAP = 10
BAR_MM = 12.5          # about the area that held the 10 letters of the PHerc. 343 First Letters award
DEFAULT_OUT = sr.DEFAULT_ROOT / "runs"
SETTINGS = {"seed": SEED, "clean_mm": CLEAN_MM, "windows_per_winding": WINDOWS_PER_WINDING, "plant_mm": PLANT_MM,
            "sites_per_pair": SITES_PER_PAIR, "contact_vox": CONTACT_VOX, "copy_vox": COPY_VOX,
            "far_vox": FAR_VOX, "min_side_vox2": MIN_SIDE_VOX2, "thick_quantile": THICK_QUANTILE,
            "thick_cap": THICK_CAP}


def _say(log, msg):
    if log:
        log(msg)


def _prefetch(reader, P, N, half, threads=8):
    """Download every chunk a window's profiles will touch, in parallel, before the (single-threaded) check."""
    np = sr._np()
    C = np.array(reader.chunks)
    keys = set()
    for t in (-half, 0, half):
        q = np.floor((P + t * N) / C).astype(np.int64)
        keys.update(map(tuple, np.unique(q, axis=0)))
    keys = sorted(k for k in keys if min(k) >= 0)
    with concurrent.futures.ThreadPoolExecutor(threads) as pool:
        list(pool.map(reader.read, keys))
    return len(keys)


def _window(ref, centre_rc, mm, voxel_um):
    np = sr._np()
    side = int(math.ceil(mm * 1000.0 / voxel_um / ref.step))
    H, W = ref.valid.shape
    r0 = int(np.clip(centre_rc[0] - side // 2, 0, max(H - side, 0)))
    c0 = int(np.clip(centre_rc[1] - side // 2, 0, max(W - side, 0)))
    return slice(r0, r0 + side), slice(c0, c0 + side)


def _dense(ref, win, rule):
    xyz, valid = ref.xyz[win], ref.valid[win] & (ref.label[win] == ref.gid)
    _, _, _, step = sr.grid_geometry(xyz, valid)
    k = max(1, int(math.ceil(step / rule["step_vox"])))
    up, uv, src = sr.upsample(xyz, valid, k)
    nrm, _, ok, ustep = sr.grid_geometry(up, uv)
    return up, nrm, ok, ustep, src


def _recalc(cert, runs, rule):
    """Classify a window's stored runs under a max_thick_vox (runs do not depend on it)."""
    np = sr._np()
    found, a, b, glo, ghi, miss, L = runs
    st = np.full(len(a), sg.OK, np.int8)
    g = int(rule["gap_vox"])
    st[(glo < g) | (ghi < g)] = sg.GAP
    st[((b - a + 1) > int(rule["max_thick_vox"])) | (a == 0) | (b == L - 1)] = sg.THICK
    st[~found] = sg.OFF
    st[miss] = sg.MISSING
    status = np.full(cert.ok.shape, sg.INVALID, np.int8)
    status[cert.ok] = st
    centre = np.full(cert.ok.shape, np.nan)
    centre[cert.ok] = np.where(found, (a + b) / 2.0 - L // 2, np.nan)
    cert.status, cert.centre = status, centre
    return cert


def _runs_of(field, cert, rule):
    P, N = cert.xyz[cert.ok][:, ::-1], cert.normals[cert.ok][:, ::-1]
    B, miss = sg.profiles(field, P, N, int(rule["half_vox"]))
    found, a, b, glo, ghi = sg.runs(B, rule["on_run_vox"])
    return found, a, b, glo, ghi, miss, B.shape[1]


def _clean_windows(refs, names, rule, field, reader, rng, log=None):
    """One CLEAN_MM square per winding, at least 90 % valid, its center drawn with the seed; the profile runs of
    every dense point are stored so that the calibrated rule can classify them without reading again."""
    stored = []
    for ref in refs:
        if ref.name not in names:
            continue
        cand = sr._np().argwhere(ref.labelled())
        rng.shuffle(cand)
        done = 0
        for rc in cand[:400]:
            if done >= WINDOWS_PER_WINDING:
                break
            win = _window(ref, rc, CLEAN_MM, rule["voxel_um"])
            v = ref.valid[win] & (ref.label[win] == ref.gid)
            if v.size == 0 or v.mean() < 0.9:
                continue
            t0 = time.time()
            up, nrm, ok, ustep, src = _dense(ref, win, rule)
            if ok.any():
                _prefetch(reader, up[ok][:, ::-1], nrm[ok][:, ::-1], rule["half_vox"])
            cert = sg.Cert(None, None, None, up, nrm, ok, ustep)
            runs = _runs_of(field, cert, rule)
            contact = ref.attrs["contact"][win].reshape(-1)
            truth_free = ok & ~contact[src]
            stored.append((ref.name, [win[0].start, win[1].start], cert, runs, truth_free))
            done += 1
            _say(log, f"clean {ref.name} at {win[0].start},{win[1].start}: {int(ok.sum())} points, "
                      f"{time.time() - t0:.0f} s")
    return stored


def calibrate(stored, rule):
    """max_thick_vox: the THICK_QUANTILE of run thickness at clean points with no other winding within 8 voxels
    whose run has both gaps, rounded up and capped at THICK_CAP."""
    np = sr._np()
    th = []
    for _, _, cert, runs, truth_free in stored:
        found, a, b, glo, ghi, miss, L = runs
        tf = truth_free[cert.ok]
        g = int(rule["gap_vox"])
        sel = found & ~miss & tf & (glo >= g) & (ghi >= g) & (a > 0) & (b < L - 1)
        th.append((b - a + 1)[sel])
    th = np.concatenate(th) if th else np.zeros(0)
    q = float(np.quantile(th, THICK_QUANTILE)) if th.size else float("nan")
    return {"points": int(th.size), "quantile": THICK_QUANTILE, "value": sr._r(q),
            "max_thick_vox": int(min(math.ceil(q), THICK_CAP)) if math.isfinite(q) else None,
            "hist": {int(k): int(v) for k, v in zip(*np.unique(th, return_counts=True))}}


def _score_clean(stored, rule, log=None):
    np = sr._np()
    rows = []
    for name, at, cert, runs, truth_free in stored:
        _recalc(cert, runs, rule)
        out = {"gap": sg.summary(cert, sg.components(cert, rule), rule)}
        on = np.isin(cert.status, (sg.OK, sg.GAP, sg.THICK))
        out["seated"] = sg.summary(cert, sg.components(cert, rule, mask=on, linked=False), rule)
        out["truth"] = sg.summary(cert, sg.components(cert, rule, mask=truth_free, linked=False), rule)
        okc = cert.status == sg.OK
        out["gap"]["ok_in_true_contact"] = sr._r(float((okc & ~truth_free & cert.ok).sum()) / max(okc.sum(), 1))
        _say(log, f"clean {name}: gap {out['gap']['square_mm']} mm, seated {out['seated']['square_mm']} mm, "
                  f"truth {out['truth']['square_mm']} mm")
        rows.append({"winding": name, "window_at": at, **out})
    return rows


def _plants(refs, man, names, rule, field, reader, rng, log=None):
    """Planted hops at real contacts between chain neighbors (kit.sheetgap.plant, band and ramp modes)."""
    np = sr._np()
    rows = []
    seen = set()
    for A in refs:
        if A.name not in names:
            continue
        for B in sr._neighbours_of(A, refs, man):
            if B.name not in names or (B.name, A.name) in seen:
                continue
            seen.add((A.name, B.name))
            sel = np.argwhere(A.labelled())
            s, ins, _, _ = sr.match(A.xyz[A.labelled()], B)
            ok = ins & np.isfinite(s)
            if ok.sum() < 500:
                continue
            med = float(np.median(np.abs(s[ok])))
            if med < COPY_VOX:
                _say(log, f"pair {A.name}/{B.name}: median offset {med:.1f} vox, a copy of one sheet; skipped")
                continue
            sites = sel[ok & (np.abs(s) <= CONTACT_VOX)]
            rng.shuffle(sites)
            min_cells = PLANT_MM * 1000.0 / rule["voxel_um"] / A.step
            picked = []
            for rc in sites:
                if len(picked) >= SITES_PER_PAIR:
                    break
                if all(np.hypot(*(rc - p)) >= min_cells for p in picked):
                    picked.append(rc)
            for rc in picked:
                win = _window(A, rc, PLANT_MM, rule["voxel_um"])
                up, nrm, okd, ustep, _ = _dense(A, win, rule)
                for mode in ("band", "ramp"):
                    out = sg.plant(up, okd, B, mode=mode, contact_vox=CONTACT_VOX, min_part_vox2=MIN_SIDE_VOX2,
                                   step=ustep)
                    row = {"A": A.name, "B": B.name, "at": [win[0].start, win[1].start], "mode": mode}
                    if out is None:
                        rows.append({**row, "status": "no split"})
                        continue
                    P, valid, w, s2 = out
                    pn, _, pok, pstep = sr.grid_geometry(P, valid)
                    if pok.any():
                        _prefetch(reader, P[pok][:, ::-1], pn[pok][:, ::-1], rule["half_vox"])
                    cert = sg.check_dense(P, pn, pok, pstep, field, rule)
                    miss = float((cert.status == sg.MISSING).sum()) / max(pok.sum(), 1)
                    m_side = max(1, int(MIN_SIDE_VOX2 / pstep ** 2))
                    res = {"none": sg.bridges(sg.components(cert, rule, mask=pok, linked=False), w, s2, valid,
                                              FAR_VOX, m_side)[0]}
                    on = np.isin(cert.status, (sg.OK, sg.GAP, sg.THICK))
                    res["seated"] = sg.bridges(sg.components(cert, rule, mask=on, linked=False), w, s2, valid,
                                               FAR_VOX, m_side)[0]
                    b_gap, nA, nB = sg.bridges(sg.components(cert, rule), w, s2, valid, FAR_VOX, m_side)
                    res["gap"] = b_gap
                    counted = res["none"] and miss < 0.05
                    rows.append({**row, "status": "counted" if counted else "not counted",
                                 "missing_share": sr._r(miss), "side_cells": [nA, nB], "joined": res,
                                 "status_counts": cert.counts()})
                    _say(log, f"plant {A.name}->{B.name} {mode} at {row['at']}: "
                              + ", ".join(f"{k} {'joined' if v else 'apart'}" for k, v in res.items()))
    return rows


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [sr._r(max(0.0, c - h)), sr._r(min(1.0, c + h))]


def tally(prow):
    out = {}
    for mode in ("band", "ramp", "all"):
        rows = [r for r in prow if r["status"] == "counted" and (mode == "all" or r["mode"] == mode)]
        n = len(rows)
        out[mode] = {"n": n}
        for arm in ("none", "seated", "gap"):
            k = sum(bool(r["joined"][arm]) for r in rows)
            out[mode][arm] = {"joined": k, "share": sr._r(k / n) if n else None, "wilson95": wilson(k, n)}
    out["not_counted"] = sum(r["status"] != "counted" for r in prow)
    return out


def _clean_tally(crow, bar_mm=BAR_MM):
    np = sr._np()
    out = {}
    for arm in ("gap", "seated", "truth"):
        mm = [r[arm]["square_mm"] for r in crow]
        out[arm] = {"median_square_mm": sr._r(float(np.median(mm))) if mm else None,
                    f"share_ge_{bar_mm}mm": sr._r(float(np.mean([m >= bar_mm for m in mm]))) if mm else None,
                    "squares_mm": mm}
    return out


def headline(rep):
    """The numbers a comparison quotes: the gap arm's joined plants and the clean windows' squares."""
    p, c = rep["plants"]["all"], rep["clean"]["gap"]
    return {"prediction": rep["rule"]["prediction"], "max_thick_vox": rep["rule"]["max_thick_vox"],
            "plants_counted": p["n"], "gap_joined": p["gap"]["joined"], "gap_joined_share": p["gap"]["share"],
            "seated_joined_share": p["seated"]["share"],
            "clean_windows": len(c["squares_mm"]), "gap_median_square_mm": c["median_square_mm"],
            f"gap_share_ge_{BAR_MM}mm": c[f"share_ge_{BAR_MM}mm"]}


def run(refs_dir=sr.DEFAULT_REFS, pred="m7", threshold=None, cache_dir=sr.DEFAULT_CACHE, rule=None, log=None):
    """The whole benchmark; returns the report (also what `kit hopbench run` writes)."""
    np = sr._np()
    rule = dict(sg.GAP_RULE, **(rule or {}))
    local = None
    if pred in sr.PRED_SOURCES:
        rule["prediction"] = sr.PRED_SOURCES[pred]
    elif Path(pred).exists():
        local = sr.LocalZarr(pred)
        rule["prediction"] = "local:" + Path(pred).resolve().name
    else:
        raise sr.BenchError(f"--pred {pred}: not one of {sorted(sr.PRED_SOURCES)} and not a local zarr")
    if threshold is not None:
        rule["threshold"] = int(threshold)
    t0 = time.time()
    names = set(sr.RULE["split"]["tune"])
    man, refs = sr.load_refs(refs_dir)
    reader = local if local is not None else sr.ChunkReader(rule["prediction"], cache_dir)
    field = sg.Field(reader, rule["threshold"], cache_chunks=96)
    stored = _clean_windows(refs, names, rule, field, reader, np.random.default_rng(SEED), log)
    calib = calibrate(stored, rule)
    if calib["max_thick_vox"] is None:
        raise sr.BenchError("no clean point had an isolated run: the prediction does not see these sheets")
    rule["max_thick_vox"] = calib["max_thick_vox"]
    _say(log, f"calibrated max_thick_vox = {rule['max_thick_vox']} (p95 {calib['value']} on {calib['points']} points)")
    crow = _score_clean(stored, rule, log)
    prow = _plants(refs, man, names, rule, field, reader, np.random.default_rng(SEED + 1), log)
    rep = {"kind": "kit-hopbench", "version": 1, "windings": sorted(names), "manifest_digest": man["digest"],
           "rule": rule, "rule_digest": sg.rule_digest(rule), "settings": SETTINGS, "calibration": calib,
           "plants": tally(prow), "clean": _clean_tally(crow), "clean_rows": crow, "plant_rows": prow,
           "missing_chunks": len(field.missing_chunks),
           "reader": {k: getattr(reader, k, None) for k in ("fetched", "cached", "missing", "absent")},
           "seconds": round(time.time() - t0)}
    rep["headline"] = headline(rep)
    return rep


def build_parser(p):
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("refs", help="download PHerc0139 windings w023 to w040 and build their manifest")
    a.add_argument("--refs", default=str(sr.DEFAULT_REFS), help="where the references go (default %(default)s)")
    a.add_argument("--workers", type=int, default=2)
    a = actions.add_parser("run", help="the planted-hop benchmark on a surface prediction")
    a.add_argument("--pred", default="m7", help="m7 (default), recto090, or a local zarr v2 array in m7's frame "
                   "(uint8, level-0 shape 20974 x 6621 x 6621; the folder or its multiscale root)")
    a.add_argument("--threshold", type=int, help="on-threshold for the prediction (default 128)")
    a.add_argument("--refs", default=str(sr.DEFAULT_REFS))
    a.add_argument("--cache", default=str(sr.DEFAULT_CACHE), help="chunk cache (default %(default)s)")
    a.add_argument("--out", help="report folder (default work/hopbench/runs/<pred>)")
    a.add_argument("--json", action="store_true", help="print the headline as JSON")


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def cmd_hopbench(args):
    try:
        if args.action == "refs":
            man = sr.build_refs(args.refs, log=_log, workers=args.workers)
            print(f"hopbench refs: {len(man['references'])} windings, manifest {man['digest'][:12]} in {args.refs}")
            return 0
        rep = run(args.refs, args.pred, args.threshold, args.cache, log=_log)
    except sr.BenchError as exc:
        print(f"hopbench: {exc}", file=sys.stderr)
        return 2
    tag = args.pred if args.pred in sr.PRED_SOURCES else Path(args.pred).name
    out = Path(args.out) if args.out else DEFAULT_OUT / tag
    out.mkdir(parents=True, exist_ok=True)
    path = out / "hopbench.json"
    path.write_text(json.dumps(rep, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
    h = rep["headline"]
    if args.json:
        print(json.dumps(h, indent=1))
        return 0
    print(f"hopbench {tag}: max_thick_vox {h['max_thick_vox']}")
    print(f"  planted hops joined by the one-sheet check: {h['gap_joined']} of {h['plants_counted']} "
          f"({h['gap_joined_share']}); per-point test: {h['seated_joined_share']}")
    print(f"  clean 20 mm windows: median one-sheet square {h['gap_median_square_mm']} mm, "
          f"{h[f'gap_share_ge_{BAR_MM}mm']} of {h['clean_windows']} at {BAR_MM} mm or more")
    print(f"  report: {path}")
    return 0
