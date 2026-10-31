#!/usr/bin/env python3
"""Paired acquisition-recipe fidelity (kit/sqrecipe.py, kit/sqfid.py).

  python3 scripts/sqrecipe/sqrecipe.py pool --scroll S --boxes BOXES.json --out POOL.json     # geometry, no CT
  python3 scripts/sqrecipe/sqrecipe.py measure --pool POOL.json --out ROWS.json [--workers W]
  python3 scripts/sqrecipe/sqrecipe.py dev --rows ROWS.json [--rows ROWS2.json] --out DEV.json
  python3 scripts/sqrecipe/sqrecipe.py test-pool --scroll S --bands BANDS.json --out POOL.json  # geometry, no CT
  python3 scripts/sqrecipe/sqrecipe.py test --pool POOL.json --out-dir DIR [--workers W]        # once per pool

CT chunks are streamed from the public hosts into memory and dropped; no scan data is written. Every number is a
Measurement of the CT, never a reading.
"""

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kit import sqfid  # noqa: E402
from kit import sqrecipe as rc  # noqa: E402

R = 128
DLS = "https://data.aws.ash2txt.org/samples/PHerc0332/volumes/"
OPEN = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/"

# Catalog matrices (xyz, level-0 voxels, 9 decimals for PHerc0332): the open data bucket's metadata.json
# volume_transforms (copy of 20 Oct 2026). PHerc0332: 7.910 um frame to each target volume. PHerc0500P2: 2.215 to
# 9.362 um (4 landmarks) and 4.317 to 2.215 um (6 landmarks).
M_791_TO_324 = [[2.408817362, -0.002810362, 0.001083935, 163.026385491],
                [0.000281404, 2.410870574, -0.000322019, 614.268374061],
                [-0.002784371, -0.001968511, 2.419841799, -142.979650711]]
M_791_TO_324_70 = [[2.408650285, -0.003214638, 0.00140162, 163.810813313],
                   [0.000634788, 2.411609513, -0.000650995, 614.062486522],
                   [-0.002361201, -0.001447263, 2.41969167, -151.933333144]]
M_791_TO_2399 = [[-1.666065421, -2.825463965, -0.105405084, 16641.404059653],
                 [-2.808917279, 1.656522169, 0.062729261, 9450.940370219],
                 [-0.000223611, 0.126693241, -3.274859424, 33649.005234924]]
A_2215_TO_9362 = [[-0.22668740143479876, 0.06829000653424222, -0.01838088604499233, 3654.690187878843],
                  [-0.07094406316509316, -0.21952731717684904, 0.05474403624931551, 3571.0835279760922],
                  [-0.0012371029641354003, 0.05737681441756459, 0.23042731975594216, 159.17139938311448]]
A_4317_TO_2215 = [[1.9486746429309512, -0.013410979609796314, 0.0015152387239145138, -18.021757798529507],
                  [-0.0004203013392913846, 1.942159665865403, 0.0009120176877807085, -47.228696134530765],
                  [0.001143396562488519, -0.004794755644779158, 1.9471178613953597, -828.6184266617311]]

M_0500_REF = rc.invert(A_2215_TO_9362).tolist()
M_0500_B = rc.compose(rc.invert(A_4317_TO_2215), M_0500_REF).tolist()

# native: the coarse acquisition, read at level 0, whose grid every arm is put on. arms: finer acquisitions, read at
# `level` and resampled onto that grid. ref: the independent finer reference. null_pair: the arms differ so little
# in recipe that no difference is expected (PHerc0500P2's "9.362 um" scan is a 4.681 um acquisition binned by 2).
SCROLLS = {
    "PHerc0332": {
        "native": DLS + "20231117143551-7.910um-53keV-masked.zarr",
        "arms": {"B": {"url": DLS + "20231027191953-3.240um-53keV-masked.zarr", "level": 1, "M": M_791_TO_324},
                 "B70": {"url": DLS + "20231201141544-3.240um-70keV-masked.zarr", "level": 1,
                         "M": M_791_TO_324_70}},
        "ref": {"url": OPEN + "PHerc0332/volumes/20251211183505-2.399um-0.2m-78keV-masked.zarr", "level": 1,
                "M": M_791_TO_2399},
        "null_pair": False,
    },
    "PHerc0500P2": {
        "native": OPEN + "PHerc0500P2/volumes/20250820143440-9.362um-1.2m-113keV-masked.zarr",
        "arms": {"B": {"url": OPEN + "PHerc0500P2/volumes/20250528085330-4.317um-1.2m-111keV-masked.zarr",
                       "level": 1, "M": M_0500_B}},
        "ref": {"url": OPEN + "PHerc0500P2/volumes/20250526151718-2.215um-0.4m-111keV-masked.zarr", "level": 1,
                "M": M_0500_REF},
        "null_pair": True,
    },
}

DEV = {"n": 100, "max_candidates": 600}
TEST = {"n": 120, "max_candidates": 1500, "seed": 33}
MINIMUM = {"regions": 60, "clusters": 10}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


def shape0(url):
    raw = rc.Store(url).get("0/.zarray")
    if raw is None:
        raise rc.RecipeError(f"no 0/.zarray at {url}")
    return tuple(json.loads(raw)["shape"])


def read_json(path, what):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise rc.RecipeError(f"cannot read {what} {path}: {exc}") from exc


def check_boxes(boxes, what):
    """A list of {'name', 'z': [lo, hi], 'y': [lo, hi], 'x': [lo, hi]} (region indices, inclusive)."""
    if not isinstance(boxes, list) or not boxes:
        raise rc.RecipeError(f"{what} must be a non-empty JSON list of boxes")
    for b in boxes:
        if not isinstance(b, dict) or "name" not in b or any(
                not (isinstance(b.get(k), list) and len(b[k]) == 2 and 0 <= b[k][0] <= b[k][1] < 1024)
                for k in "zyx"):
            raise rc.RecipeError(f"{what}: each box needs a name and z, y, x as [lo, hi] region indices, 0 to 1023")
    return boxes


def excluded(S, origin, exclude):
    """The first exclusion box the region touches, or None. Each box names a volume ('native', 'ref' or an arm) and
    its z, y, x ranges in that volume's level-0 voxels (hi exclusive)."""
    for e in exclude or ():
        vol = e.get("volume", "native")
        if vol == "native":
            M = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0]]
        elif vol == "ref":
            M = S["ref"]["M"]
        elif vol in S["arms"]:
            M = S["arms"][vol]["M"]
        else:
            raise rc.RecipeError(f"exclusion box names unknown volume {vol!r}")
        if rc.touches(M, origin, R, e):
            return e.get("name", vol)
    return None


def candidates(S, shapes, box, exclude, dropped):
    """Region codes of one box whose 128-voxel cube lies inside the native volume, whose corners map inside the
    reference and every arm, and that touch no exclusion box."""
    codes = []
    for z in range(box["z"][0], box["z"][1] + 1):
        for y in range(box["y"][0], box["y"][1] + 1):
            for x in range(box["x"][0], box["x"][1] + 1):
                o = [z * R, y * R, x * R]
                if any(o[i] + R > shapes["native"][i] for i in range(3)):
                    why = "native_extent"
                elif not rc.corners_inside(S["ref"]["M"], o, R, shapes["ref"]):
                    why = "ref_extent"
                elif any(not rc.corners_inside(a["M"], o, R, shapes[k]) for k, a in S["arms"].items()):
                    why = "arm_extent"
                elif excluded(S, o, exclude):
                    why = "excluded"
                else:
                    codes.append(sqfid.region_code((z, y, x)))
                    continue
                dropped[why] = dropped.get(why, 0) + 1
    return codes


def _shapes(S):
    shapes = {"native": shape0(S["native"]), "ref": shape0(S["ref"]["url"])}
    for k, a in S["arms"].items():
        shapes[k] = shape0(a["url"])
    return shapes


def cmd_pool(args):
    """Development pool: each box's candidates in its own seeded order (box 'seed', default 0), boxes in file
    order."""
    import numpy as np
    S = SCROLLS[args.scroll]
    boxes = check_boxes(read_json(args.boxes, "boxes file"), "boxes file")
    exclude = read_json(args.exclude, "exclusion file") if args.exclude else []
    shapes = _shapes(S)
    order, dropped = [], {}
    for box in boxes:
        codes = candidates(S, shapes, box, exclude, dropped)
        rng = np.random.default_rng(int(box.get("seed", 0)))
        order += [{"code": codes[i], "box": box["name"]} for i in rng.permutation(len(codes))]
    out = {"scroll": args.scroll, "candidates": order, "n_candidates": len(order), "dropped": dropped,
           "shapes0": shapes, "boxes": boxes, "exclude": exclude}
    Path(args.out).write_text(json.dumps(out, indent=1))
    log(f"pool {args.scroll}: {len(order)} candidates, dropped {dropped}")


def cmd_test_pool(args):
    """Test pool: every candidate of every band in one seeded order."""
    import numpy as np
    S = SCROLLS[args.scroll]
    bands = check_boxes(read_json(args.bands, "bands file"), "bands file")
    exclude = read_json(args.exclude, "exclusion file") if args.exclude else []
    shapes = _shapes(S)
    codes, dropped = [], {}
    for b in bands:
        codes += [{"code": c, "box": b["name"]} for c in candidates(S, shapes, b, exclude, dropped)]
    rng = np.random.default_rng(args.seed)
    order = [codes[i] for i in rng.permutation(len(codes))]
    Path(args.out).write_text(json.dumps({"scroll": args.scroll, "candidates": order, "n_candidates": len(order),
                                          "dropped": dropped, "bands": bands, "exclude": exclude,
                                          "seed": args.seed}, indent=1))
    log(f"test pool {args.scroll}: {len(order)} candidates, dropped {dropped}")


_ST = {}


def _init(scroll):
    import numpy as np
    S = SCROLLS[scroll]
    _ST["S"] = S
    _ST["native"] = rc.ParallelZArray(rc.Store(S["native"]), "0", threads=4, cache=64)
    _ST["ref"] = rc.ParallelZArray(rc.Store(S["ref"]["url"]), str(S["ref"]["level"]), threads=8, cache=64)
    _ST["arms"] = {k: rc.ParallelZArray(rc.Store(a["url"]), str(a["level"]), threads=8, cache=64)
                   for k, a in S["arms"].items()}
    _ST["M"] = {k: np.asarray(a["M"], float) for k, a in S["arms"].items()}
    _ST["Mref"] = np.asarray(S["ref"]["M"], float)


def _measure_one(item, tries=5):
    import http.client
    for k in range(tries):
        try:
            return _measure_once(item)
        except (http.client.HTTPException, OSError, ConnectionError) as exc:
            if k == tries - 1:
                raise
            log(f"retry {item['code']}: {type(exc).__name__}")
            time.sleep(3 * (k + 1))


def _measure_once(item):
    S, rule = _ST["S"], rc.RULE
    code = item["code"]
    zyx = sqfid.region_index(code)
    origin = [int(i) * R for i in zyx]
    share = {}
    N, _ = _ST["native"].block(origin, R)
    share["N"] = float((N > 0).mean())
    if share["N"] < rule["min_mask_share"]:
        return item, None, None, share
    ref = sqfid.fine_on_coarse(_ST["ref"], S["ref"]["level"], _ST["Mref"], origin, R)
    share["ref"] = float((ref > 0).mean())
    if share["ref"] < rule["min_mask_share"]:
        return item, None, None, share
    cubes = {"N": N}
    for k, a in S["arms"].items():
        cubes[k] = sqfid.fine_on_coarse(_ST["arms"][k], a["level"], _ST["M"][k], origin, R)
        share[k] = float((cubes[k] > 0).mean())
        if share[k] < rule["min_mask_share"]:
            return item, None, None, share
    t0 = time.time()
    cubes["Np"] = rc.round_trip(_ST["native"], _ST["M"]["B"], S["arms"]["B"]["level"], origin, R)
    hfN = rc.hf_noise(N)
    cubes["Bdeg"], added = rc.degrade_to(cubes["B"], hfN, seed=int(code) % (2 ** 31))
    row = {"code": int(code), "box": item["box"], "region": "_".join(str(i) for i in zyx),
           "cluster": sqfid.cluster_of(code), "mask_share": {k: round(v, 4) for k, v in share.items()},
           "hf": {k: round(rc.hf_noise(cubes[k]), 4) for k in cubes}, "deg_noise_sd": round(added, 4),
           "ref_mean": round(float(ref[ref > 0].mean()), 4)}
    for k, c in cubes.items():
        o = sqfid.outcome(c, ref, rule)
        row[f"F_{k}"], row[f"shift_{k}"], row[f"border_{k}"] = o["fidelity"], o["shift"], o["at_border"]
    row["cpu_s"] = round(time.time() - t0, 1)
    keep = {k: cubes[k] for k in ["N"] + list(S["arms"])}
    return item, row, (keep, ref), share


def _mismatch(args_):
    cube, ref = args_
    return sqfid.outcome(cube, ref, rc.RULE)["fidelity"]


def cmd_measure(args):
    pool = read_json(args.pool, "pool file")
    scroll = pool.get("scroll")
    if scroll not in SCROLLS:
        raise rc.RecipeError(f"pool names unknown scroll {scroll!r}")
    S = SCROLLS[scroll]
    if Path(args.out).exists():
        raise rc.RecipeError(f"{args.out} exists")
    n, cap = args.n, args.max_candidates
    order = pool["candidates"][:cap]
    rows, kept, seen, skipped, read = [], [], 0, [], []
    read_log = Path(args.out).with_name(Path(args.out).stem + "-read.json")   # kept current, also if the run dies
    t0 = time.time()
    arms = ["N"] + list(S["arms"])
    with concurrent.futures.ProcessPoolExecutor(args.workers, initializer=_init, initargs=(scroll,)) as ex:
        i = 0
        while len(rows) < n and i < len(order):
            batch = order[i:i + args.workers * 2]
            i += len(batch)
            # every candidate opened, usable or not, the overrun after the n-th usable one included: these are the
            # regions a verdict spends
            read += [{"code": int(it["code"]), "box": it["box"],
                      "region": "_".join(str(v) for v in sqfid.region_index(it["code"]))} for it in batch]
            read_log.write_text(json.dumps({"scroll": scroll, "n_read": len(read), "read": read}))
            for item, row, cubes, share in ex.map(_measure_one, batch):
                seen += 1
                if row is None:
                    skipped.append({"code": item["code"], "box": item["box"], "mask_share": share})
                    continue
                if len(rows) >= n:
                    continue
                rows.append(row)
                kept.append(cubes)
            log(f"measure {scroll}: {len(rows)}/{n} regions, {seen} seen, {time.time() - t0:.0f} s")
        jobs = [(kept[k][0][a], kept[k - 1][1]) for k in range(len(kept)) for a in arms] if len(kept) >= 2 else []
        mis = list(ex.map(_mismatch, jobs))
    for k, r in enumerate(rows):
        for j, a in enumerate(arms):
            r[f"Fmis_{a}"] = round(mis[k * len(arms) + j], 6) if mis else float("nan")
    res = {"scroll": scroll, "n": len(rows), "seen": seen, "skipped_mask": len(skipped), "skipped": skipped,
           "n_read": len(read), "read": read, "rows": rows, "rule": rc.RULE, "rule_digest": sqfid.digest(rc.RULE),
           "ref_level": S["ref"]["level"], "wall_s": round(time.time() - t0, 1), "pool": str(args.pool)}
    Path(args.out).write_text(json.dumps(res, indent=1))
    log(f"wrote {args.out}: {len(rows)} regions in {res['wall_s']} s")


def readout(d):
    """The readout of one scroll's rows: outcome control and border share per arm, the primary bar on
    d = F(B) - F(N), the processing, degradation and sign-flip controls, and B against B70 when B70 was measured."""
    import numpy as np
    rows = d["rows"]
    if len(rows) < 2:
        raise rc.RecipeError("the rows file holds fewer than 2 regions")
    cl = [r["cluster"] for r in rows]
    arms = [a for a in ("N", "B", "B70") if f"F_{a}" in rows[0]]
    F = {k: np.array([r[f"F_{k}"] for r in rows], float) for k in arms + ["Np", "Bdeg"]}
    out = {"scroll": d["scroll"], "n": len(rows), "clusters": len(set(cl)), "seen": d["seen"],
           "skipped_mask": d["skipped_mask"], "median_F": {k: float(np.median(v)) for k, v in F.items()}}
    out["outcome_control"] = {a: sqfid.outcome_control(F[a], [r[f"Fmis_{a}"] for r in rows], cl, rc.RULE)
                              for a in arms}
    out["border"] = {a: rc.border_share([r[f"border_{a}"] for r in rows]) for a in arms + ["Np", "Bdeg"]}
    dB = F["B"] - F["N"]
    out["primary"] = rc.paired(dB, cl)
    out["processing"] = rc.processing_holds(F["B"], F["Np"], cl)
    gain = float(np.median(F["Np"] - F["N"]))
    out["processing"]["gain_median"] = gain
    out["processing"]["gain_fraction_of_primary"] = gain / out["primary"]["median"] if out["primary"]["median"] else None
    out["degradation"] = rc.degradation_holds(F["Bdeg"], F["N"], out["primary"]["median"])
    out["degradation"]["Bdeg_vs_B"] = rc.paired(F["Bdeg"] - F["B"], cl)
    out["signflip"] = rc.signflip(dB, cl)
    if "B70" in arms:
        out["energy_B_minus_B70"] = rc.paired(F["B"] - F["B70"], cl)
        out["native_vs_B70"] = rc.paired(F["B70"] - F["N"], cl)
    out["hf_median"] = {k: float(np.median([r["hf"][k] for r in rows])) for k in rows[0]["hf"]}
    return out


def dev_verdict(o):
    """The development decision: VOID under the minimum; GO when every arm's outcome control and border check, the
    primary bar, the processing, degradation and sign-flip controls all hold; else NO-GO with the failed items."""
    arms = sorted(o["outcome_control"])
    items = {
        "1_minimum": o["n"] >= MINIMUM["regions"] and o["clusters"] >= MINIMUM["clusters"],
        "2_outcome_control": all(o["outcome_control"][a]["holds"] for a in arms),
        "3_border": all(o["border"][a]["holds"] for a in arms),
        "4_primary": o["primary"]["passes"],
        "5_processing": o["processing"]["holds"],
        "6_degradation": bool(o["degradation"]["holds"]),
        "7_signflip": o["signflip"]["holds"],
    }
    if not items["1_minimum"]:
        dec = "VOID"
    else:
        dec = "GO" if all(items.values()) else "NO-GO"
    return {"items": items, "decision": dec, "failed": [k for k, v in items.items() if not v]}


def test_verdict(o):
    """The test's reading: VOID under the minimum or when an instrument control (outcome control of N or B, border
    of N or B, sign-flip) fails; PASS when the primary bar, the processing control and the degradation control all
    hold; FAIL otherwise."""
    v = dev_verdict(o)
    it = v["items"]
    inst = {"outcome_control": all(o["outcome_control"][a]["holds"] for a in ("N", "B")),
            "border": all(o["border"][a]["holds"] for a in ("N", "B")), "signflip": it["7_signflip"]}
    if not it["1_minimum"] or not all(inst.values()):
        return {"verdict": "VOID", "instrument": inst, "items": it}
    ok = it["4_primary"] and it["5_processing"] and it["6_degradation"]
    return {"verdict": "PASS" if ok else "FAIL", "instrument": inst, "items": it}


def cmd_test(args):
    """A test, once: refuses an existing output folder, measures the pool, reads out and writes the verdict."""
    out = Path(args.out_dir)
    if out.exists():
        raise rc.RecipeError(f"{out} exists: the test runs once")
    read_json(args.pool, "pool file")
    out.mkdir(parents=True)
    ns = argparse.Namespace(pool=args.pool, out=str(out / "rows.json"), workers=args.workers, n=args.n,
                            max_candidates=args.max_candidates)
    cmd_measure(ns)
    d = json.loads((out / "rows.json").read_text())
    o = readout(d)
    o.update(test_verdict(o))
    o["n_read"], o["read"] = d["n_read"], d["read"]
    (out / "result.json").write_text(json.dumps(o, indent=1))
    print(json.dumps({k: o[k] for k in ("verdict", "n", "clusters", "n_read", "primary")}, indent=1))


def cmd_dev(args):
    res = {"sets": {}}
    for path in args.rows:
        d = read_json(path, "rows file")
        o = readout(d)
        o["rows_file"] = str(path)
        o["rows_digest"] = sqfid.digest(d["rows"])
        o["rule_digest"] = sqfid.digest(rc.RULE)
        if SCROLLS.get(d["scroll"], {}).get("null_pair"):
            o["null_pair_usable"] = bool(all(o["outcome_control"][a]["holds"] for a in o["outcome_control"])
                                         and all(o["border"][a]["holds"] for a in ("N", "B")))
        else:
            o["verdict"] = dev_verdict(o)
        key = d["scroll"]
        if key in res["sets"]:
            key = f"{key}:{len(res['sets'])}"
        res["sets"][key] = o
    Path(args.out).write_text(json.dumps(res, indent=1))
    show = {}
    for s, o in res["sets"].items():
        show[s] = {"n": o["n"], "median_F": {k: round(v, 4) for k, v in o["median_F"].items()},
                   "primary": {k: o["primary"][k] for k in ("share", "share_ci", "median", "median_ci", "passes")},
                   "verdict": o.get("verdict"), "null_pair_usable": o.get("null_pair_usable")}
    print(json.dumps(show, indent=1))


def main(argv=None):
    if argv is None and sys.stdout.isatty():          # the Scrolls look (AGENTS.md, terminal look rule)
        from kit import termstyle
        termstyle.script()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    scroll = {"required": True, "choices": sorted(SCROLLS), "help": "the scroll whose volumes SCROLLS names"}
    excl = {"help": "JSON list of exclusion boxes: volume, z, y, x (level-0 voxels, hi exclusive)"}
    a = sub.add_parser("pool", help="development candidates from boxes, geometry only")
    a.add_argument("--scroll", **scroll)
    a.add_argument("--boxes", required=True, help="JSON list of boxes: name, z, y, x (region indices), seed")
    a.add_argument("--exclude", **excl)
    a.add_argument("--out", required=True, help="pool file to write")
    a.set_defaults(fn=cmd_pool)
    a = sub.add_parser("measure", help="stream the CT and measure every arm's fidelity per region")
    a.add_argument("--pool", required=True, help="a pool file from pool or test-pool")
    a.add_argument("--workers", type=int, default=3, help="processes")
    a.add_argument("--n", type=int, default=DEV["n"], help="usable regions to measure")
    a.add_argument("--max-candidates", type=int, default=DEV["max_candidates"],
                   help="read at most this many candidates of the pool, in its order")
    a.add_argument("--out", required=True, help="rows file to write (refused if it exists)")
    a.set_defaults(fn=cmd_measure)
    a = sub.add_parser("dev", help="read out rows files")
    a.add_argument("--rows", required=True, action="append", help="a rows file from measure (repeatable)")
    a.add_argument("--out", required=True, help="readout file to write")
    a.set_defaults(fn=cmd_dev)
    a = sub.add_parser("test-pool", help="test candidates from bands in one seeded order, geometry only")
    a.add_argument("--scroll", **scroll)
    a.add_argument("--bands", required=True, help="JSON list of bands: name, z, y, x (region indices)")
    a.add_argument("--exclude", **excl)
    a.add_argument("--seed", type=int, default=TEST["seed"], help="seed of the candidate order")
    a.add_argument("--out", required=True, help="pool file to write")
    a.set_defaults(fn=cmd_test_pool)
    a = sub.add_parser("test", help="measure a test pool once and write its verdict")
    a.add_argument("--pool", required=True, help="a pool file from test-pool")
    a.add_argument("--workers", type=int, default=3, help="processes")
    a.add_argument("--n", type=int, default=TEST["n"], help="usable regions to measure")
    a.add_argument("--max-candidates", type=int, default=TEST["max_candidates"],
                   help="read at most this many candidates of the pool, in its order")
    a.add_argument("--out-dir", required=True, help="new folder for rows.json, rows-read.json and result.json")
    a.set_defaults(fn=cmd_test)
    args = p.parse_args(argv)
    try:
        args.fn(args)
    except rc.RecipeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
