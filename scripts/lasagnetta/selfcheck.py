"""Lasagnetta's self-check: before a preview is trusted on a new volume, villa's lasagna net runs in process on a few
spots of it and the student is scored against it there; when the agreement is too low, the caller makes villa's own
field instead.

SPOTS crops of 256^3 on the 128 grid are drawn reproducibly inside the region, grown to at least SPAN voxels a side
(at least MIN_PAPYRUS of each crop's context box nonzero in the masked CT). On each, villa's net runs on predict3d's tile lattice (teacher.py) and its
channels are pooled to villa's stored scaledowns, then the student (with the preview's recipe) is scored as the
held-out tests score it (lgcommon.crop_metrics). The decision is "student" when at least MIN_SPOTS
spots scored and their median peak F1 is at least THRESHOLD, else "villa". The threshold sits above the 0.80 bar so a
volume near the bar falls back: on the second and third held-out tests' crops, 12 spots at 0.82 sent PHerc0175B
(median 0.759) to villa every time and PHercMAN5 (0.774) about three times in four, while the volumes at 0.85 or
above stayed with the student 97 % of the time or more. Run on whole volumes (25 Oct 2026, two seeds each, the
released average), it sent PHerc0175B (median 0.64), PHercMAN5 (0.81, 0.82), PHerc0846B (0.81, 0.78) and PHerc0172
(0.79) to villa and kept PHerc0800, 1545, 0814, 0175A, 0306B, 0846A, 0009B and MANB (0.82 to 0.90) with the
student; about 50 s per volume on an RTX Pro 6000, most of it reading CT. It is a check of agreement with villa's
net, not of truth.

  python scripts/lasagnetta/selfcheck.py --checkpoint A.pt[,B.pt,...] --ct CT_LEVEL_DIR [--region Z0 Z1 Y0 Y1 X0 X1]
      [--cos-blur 0.5 0.5 0.5] [--cos-offset 0.04] [--spots 12] [--threshold 0.82] [--out check.json] [--exit-code]

With --exit-code it exits 3 when the decision is "villa". preview.py --self-check runs it first.
"""
import argparse
import functools
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lgcommon as C  # noqa: E402
import lasnet as M  # noqa: E402

SPOTS, MIN_SPOTS, THRESHOLD = 12, 8, 0.82
MIN_PAPYRUS = 0.98
SPAN = 2048                     # spots are drawn from at least this much around the region (voxels a side)
MAX_TRIES = 2000                # cheap with the coarse pre-check; a small volume needs many
COARSE_UP = 3                   # papyrus pre-check on the level 8 times coarser
SEED = 20261025
GRID = 128


@torch.no_grad()
def predict_crop(net, ct_u8, device, flips=((),), cos_blur=(0, 0, 0), cos_offset=0.0):
    """The student on one whole 256^3 crop (bf16 on CUDA), as numpy maps for lgcommon.crop_metrics; flips and
    cos_blur are the inference recipe (lasnet.predict_maps; the defaults are one plain forward)."""
    x = torch.from_numpy(np.ascontiguousarray(ct_u8)).to(device).float()[None, None] / 255.0
    with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
        maps = M.predict_maps(net, x, flips, cos_blur, cos_offset)
    return {k: v[0].float().cpu().numpy() for k, v in maps.items()}


def candidates(region, shape):
    """Every 128-grid crop origin whose crop and teacher context box lie inside the region and the volume."""
    import teacher as TF
    per = []
    for (a, b), n in zip(region, shape):
        lo, hi = max(a, TF.BORDER), min(b, n) - (TF.STRIDE - TF.BORDER + TF.TILE)
        per.append([o for o in range(-(-lo // GRID) * GRID, hi + 1, GRID) if o + C.CROP <= min(b, n)])
    return per


def draw(region, shape, read_ctx, spots=SPOTS, seed=SEED, min_papyrus=MIN_PAPYRUS, tries=MAX_TRIES, coarse=None):
    """Up to spots (origin, context CT) pairs: random grid origins, kept when enough of the context is papyrus.
    coarse(origin), when given, is the crop's papyrus fraction on a coarse level, checked before the full read."""
    per = candidates(region, shape)
    if not all(per):
        return []
    rng = random.Random(seed)
    seen, out = set(), []
    for _ in range(tries):
        if len(out) >= spots:
            break
        o = tuple(rng.choice(c) for c in per)
        if o in seen:
            continue
        seen.add(o)
        if coarse is not None and coarse(o) < min_papyrus:
            continue
        ctx = read_ctx(o)
        if float((ctx > 0).mean()) >= min_papyrus:
            out.append((list(o), ctx))
    return out


def coarse_fraction(source, ct, levels_up=COARSE_UP):
    """A function origin -> the crop's papyrus fraction on the OME-Zarr level levels_up above ct (a path ending in
    /N), or None when that level cannot be opened. source is preview.source."""
    head, _, lvl = str(ct).rstrip("/").rpartition("/")
    if not lvl.isdigit():
        return None
    try:
        meta, get = source(f"{head}/{int(lvl) + levels_up}")
    except Exception:            # noqa: BLE001 - no coarse level: every spot is read in full
        return None
    f = 2 ** levels_up
    get = functools.lru_cache(maxsize=256)(get)

    def frac(o):
        box = tuple((a // f, -(-(a + C.CROP) // f)) for a in o)
        return float((C.read_box_from(meta, get, box)[0] > 0).mean())
    return frac


def widen(region, shape, span=SPAN):
    """The region grown about its middle to at least span voxels a side, kept inside the volume, so a small preview
    region still has room for its spots."""
    out = []
    for (a, b), n in zip(region, shape):
        a, b = max(0, a), min(n, b)
        grow = max(0, span - (b - a))
        a, b = a - grow // 2, b + grow - grow // 2
        if a < 0:
            a, b = 0, b - a
        if b > n:
            a, b = max(0, a - (b - n)), n
        out.append((a, b))
    return tuple(out)


def decide(rows, threshold=THRESHOLD, min_spots=MIN_SPOTS):
    """('student' or 'villa', median peak F1 over the scored spots, scored count)."""
    f1 = [r["peak_f1"] for r in rows if "peak_f1" in r and not np.isnan(r["peak_f1"])]
    med = statistics.median(f1) if f1 else float("nan")
    ok = len(f1) >= min_spots and med >= threshold
    return ("student" if ok else "villa"), med, len(f1)


def check(net, teacher, meta, get, region, device, spots=SPOTS, threshold=THRESHOLD, min_spots=MIN_SPOTS,
          seed=SEED, cos_blur=(0, 0, 0), cos_offset=0.0, log=print, coarse=None):
    """The self-check record for one volume region (see the module note)."""
    import teacher as TF
    t0 = time.time()
    pool = ThreadPoolExecutor(32)
    read_ctx = lambda o: C.read_box_from(meta, get, TF.context_box(o), pool)[0]
    picked = draw(widen(region, meta["shape"]), meta["shape"], read_ctx, spots, seed, coarse=coarse)
    rows = []
    for i, (origin, ctx) in enumerate(picked):
        pooled = C.pooled_from_raw(teacher.raw(ctx, origin), teacher.encode)
        b = TF.BORDER
        ct = np.ascontiguousarray(ctx[b:b + C.CROP, b:b + C.CROP, b:b + C.CROP])
        crop = {"ct": ct, **pooled}
        with torch.no_grad():
            pred = predict_crop(net, ct, device, ((),), cos_blur, cos_offset)
        r = C.crop_metrics(pred, C.targets(crop))
        r["origin"] = origin
        rows.append(r)
        log(f"spot {i + 1}/{len(picked)} at {origin}: peak F1 {r.get('peak_f1', float('nan')):.3f}")
    pool.shutdown()
    decision, med, n = decide(rows, threshold, min_spots)
    return {"what": "Lasagnetta self-check against villa's lasagna net", "decision": decision,
            "median_peak_f1": med, "spots_scored": n, "spots_drawn": len(picked), "threshold": threshold,
            "min_spots": min_spots, "seed": seed, "region": [list(x) for x in region],
            "median_cos_r": statistics.median([r["cos_r"] for r in rows if "cos_r" in r]) if n else float("nan"),
            "seconds": round(time.time() - t0, 1), "rows": rows}


def main(argv=None):
    import preview as P
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--checkpoint", required=True,
                    help="one student, several joined by commas, or release (the released average and its recipe)")
    ap.add_argument("--ct", required=True, help="the CT level the student reads (local zarr v2 folder or s3://...)")
    ap.add_argument("--region", type=int, nargs=6, metavar=("Z0", "Z1", "Y0", "Y1", "X0", "X1"),
                    help="default: the whole level")
    ap.add_argument("--cos-blur", type=float, nargs=3, default=[0.0, 0.0, 0.0], metavar=("SZ", "SY", "SX"))
    ap.add_argument("--cos-offset", type=float, default=0.0)
    ap.add_argument("--spots", type=int, default=SPOTS)
    ap.add_argument("--min-spots", type=int, default=MIN_SPOTS)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--teacher", help="villa's lasagna checkpoint (default: scrollprize/lasagna, downloaded)")
    ap.add_argument("--out", help="write the record here as JSON")
    ap.add_argument("--exit-code", action="store_true", help="exit 3 when the decision is villa")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = P.resolve(ap.parse_args(argv))
    rec = run_cli(a, P)
    if a.out:
        Path(a.out).write_text(json.dumps(rec, indent=1, default=float) + "\n")
    print(json.dumps({k: v for k, v in rec.items() if k != "rows"}, default=float), flush=True)
    if a.exit_code and rec["decision"] != "student":
        sys.exit(3)


def run_cli(a, P):
    """The check from parsed arguments (shared with preview.py --self-check)."""
    import teacher as TF
    device = torch.device(a.device)
    net, config = P.load(a.checkpoint, device)
    meta, get = P.source(a.ct)
    shape = meta["shape"]
    r = a.region or [0, shape[0], 0, shape[1], 0, shape[2]]
    region = ((r[0], r[1]), (r[2], r[3]), (r[4], r[5]))
    ck = a.teacher or C.teacher_checkpoint(Path("/tmp/lasagnetta-teacher"))
    teacher = TF.Teacher(ck, device)
    rec = check(net, teacher, meta, get, region, device, a.spots, a.threshold, a.min_spots, a.seed,
                tuple(a.cos_blur), a.cos_offset, coarse=coarse_fraction(P.source, a.ct))
    rec["config"] = config
    return rec


if __name__ == "__main__":
    main()
