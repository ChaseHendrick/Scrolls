"""Second stage: move a coarse center onto the winding center, looking at native level-3 crops.

The first stage (centrenet) sees the whole scroll squeezed into 256 pixels, about 0.3 mm each, too coarse for the
innermost windings. This network sees a 176-pixel window of the level-3 slices (about 70 um per pixel, a 12 to 13 mm
window) around a coarse guess and puts a heatmap peak on the center. Trained on published umbilici, with the coarse
guess replaced by the published center plus a random offset; scored only on scrolls it did not train on.

    python refine.py cv --data DIR --out DIR [--folds 0 1 2 3 --epochs 12 --width 16 --device cpu]
    python refine.py chain fold<k>|all --data DIR --base FIRST_STAGE_RUN --out DIR [--epochs 30 --width 32 --time-s 300]
    python refine.py chain-collect --data DIR --out DIR

cv trains one model per fold of pipeline.FOLDS (saved as refine_cv_fold<k>.pt, apart from chain's refine_fold<k>.pt)
and scores each held-out scroll from coarse guesses that are the
published center plus a smooth random offset along z (median 1.2 mm, like the first stage's held-out error), before
and after refining. A smooth offset is a stand-in for the first stage's real error, which is also smooth along z
but follows the CT's confusing structures; the real test chains the two stages.
"""
import argparse, json, os, sys, time
import numpy as np
import torch, torch.nn.functional as F
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import centrenet, slices

S = 176     # crop side, level-3 pixels: 12.2 mm at 8.64 um, 13.2 mm at 9.362 um
R = 64      # largest training offset, level-3 pixels (4.4 mm at 8.64 um); a training band is S + 2R wide
F3 = 8      # level 3 is 8x level 0

def crop(ct, i, cy, cx, side):
    """Slices i-1, i, i+1 (clamped) in a side x side window whose top-left is round(c) - side // 2; zeros off the
    volume. Returns (3, side, side) uint8 and the window's top-left (y0, x0) in level-3 pixels."""
    n, H, W = ct.shape
    y0, x0 = int(round(cy)) - side // 2, int(round(cx)) - side // 2
    out = np.zeros((3, side, side), np.uint8)
    ys, xs, ye, xe = max(y0, 0), max(x0, 0), min(y0 + side, H), min(x0 + side, W)
    if ye > ys and xe > xs:
        for c, j in enumerate((max(i - 1, 0), i, min(i + 1, n - 1))):
            out[c, ys - y0:ye - y0, xs - x0:xe - x0] = ct[j, ys:ye, xs:xe]
    return out, (y0, x0)

def truth_l3(s, z):
    """Published center at each z in level-3 pixels, NaN outside the annotated range."""
    _, T = slices.truth(s)
    t = np.stack([np.interp(z, T[:, 0], T[:, 1]), np.interp(z, T[:, 0], T[:, 2])], 1) / F3
    t[(z < T[0, 0]) | (z > T[-1, 0])] = np.nan
    return t

def bands(ct, t):
    """Training bands: for each slice with a center, the 3-slice window of side S + 2R centered on it."""
    B = S + 2 * R; keep = np.nonzero(np.isfinite(t[:, 0]))[0]
    out = np.zeros((len(keep), 3, B, B), np.uint8); org = np.zeros((len(keep), 2))
    for k, i in enumerate(keep):
        out[k], org[k] = crop(ct, i, t[i, 0], t[i, 1], B)
    return out, org, t[keep]

def train_offsets(rng, b, um):
    """Training offsets in level-3 pixels: half from a 2-D normal with 1 mm sigma, half uniform over the disk of
    radius R, so the network sees both the usual small error and the far tail."""
    o = rng.normal(0, 1000 / (um * F3), (b, 2))
    r = R * np.sqrt(rng.random(b)); a = 2 * np.pi * rng.random(b)
    u = np.stack([r * np.sin(a), r * np.cos(a)], 1)
    o = np.where((rng.random(b) < 0.5)[:, None], o, u)
    n = np.hypot(*o.T); o *= np.minimum(1, (R - 1) / np.maximum(n, 1e-9))[:, None]
    return o

def smooth_offsets(n, rng, um, med_mm=1.2, corr=8):
    """Coarse-guess error for scoring: a smooth 2-D random track along z (correlation about `corr` slices, 64
    level-0 voxels apart), scaled so its median length is med_mm. Level-3 pixels."""
    from scipy.ndimage import gaussian_filter1d
    o = gaussian_filter1d(rng.normal(size=(n, 2)), corr, axis=0, mode="nearest")
    o *= med_mm * 1000 / (um * F3) / (np.median(np.hypot(*o.T)) + 1e-12)
    return o

def dihedral(x, t, rng):
    """Random flip and rot90 per sample, with contrast jitter. x (b, 3, n, n) tensor, t (b, 2) numpy pixel coords."""
    b, _, n, _ = x.shape; out, tt = [], t.copy()
    for i in range(b):
        xi = x[i]; y, xx = tt[i]
        if rng.random() < 0.5:
            xi = xi.flip(-1); xx = n - 1 - xx
        for _ in range(int(rng.integers(4))):   # rot90 counter-clockwise: (y, x) -> (n - 1 - x, y)
            xi = torch.rot90(xi, 1, (-2, -1)); y, xx = n - 1 - xx, y
        out.append(xi); tt[i] = (y, xx)
    g = torch.from_numpy(rng.uniform(0.8, 1.25, (b, 1, 1, 1)).astype(np.float32)).to(x.device)
    o = torch.from_numpy(rng.uniform(-0.1, 0.1, (b, 1, 1, 1)).astype(np.float32)).to(x.device)
    return torch.stack(out) * g + o, tt

def train(data, epochs, seed, width=16, batch=16, lr=2e-3, time_s=None, device="cpu", log=print):
    """data: {scroll: (bands uint8, band origins, centers in level-3 px, um)}."""
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    items = [(s, k) for s, v in data.items() for k in range(len(v[0]))]
    net = centrenet.Net(width).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr, weight_decay=1e-4)
    steps = max(1, epochs * len(items) // batch)
    def lr_at(frac):
        frac = min(max(frac, 0.0), 1.0)
        if frac < 0.1:
            return lr * (0.04 + 0.96 * frac / 0.1)
        return lr * (0.01 + 0.99 * 0.5 * (1 + np.cos(np.pi * (frac - 0.1) / 0.9)))
    t0 = time.time(); st = 0; net.train(); stopped = "epochs"; amp = device != "cpu"
    while st < steps and stopped == "epochs":
        perm = rng.permutation(len(items)).tolist()
        for b in range(0, len(perm) - batch + 1, batch):
            sel = [items[j] for j in perm[b:b + batch]]
            xs, ts = [], []
            for s, k in sel:
                bd, org, t, um = data[s]
                c = t[k] + train_offsets(rng, 1, um)[0]
                y0, x0 = int(round(c[0])) - S // 2 - org[k, 0], int(round(c[1])) - S // 2 - org[k, 1]
                y0 = int(min(max(y0, 0), 2 * R)); x0 = int(min(max(x0, 0), 2 * R))
                xs.append(bd[k, :, y0:y0 + S, x0:x0 + S]); ts.append(t[k] - org[k] - (y0, x0))
            x = torch.from_numpy(np.stack(xs)).to(device).float() / 255.0
            x, tt = dihedral(x, np.array(ts, np.float32), rng)
            tt = torch.from_numpy(tt).float().to(device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                h = net(x)
            h = h.float(); g = centrenet.heat(tt / 2 - 0.25, h.shape[-1], 1.5)
            loss = F.binary_cross_entropy_with_logits(h, g, pos_weight=torch.tensor(50.0, device=device))
            frac = max(st / steps, (time.time() - t0) / time_s if time_s else 0.0)
            for gp in opt.param_groups:
                gp["lr"] = lr_at(frac)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step(); st += 1
            if st % 100 == 0:
                log(f"step {st}/{steps} loss {loss.item():.4f} {time.time() - t0:.0f}s")
            if st >= steps:
                break
            if time_s and time.time() - t0 > time_s:
                stopped = "time"; break
    return net, dict(steps=st, planned_steps=steps, stopped=stopped, seconds=round(time.time() - t0, 1), items=len(items))

def refine(net, ct, idx, guess, rounds=2, device="cpu"):
    """Move guesses (level-3 px, one per slice index in idx) onto the center; each round re-crops at the last answer."""
    g = np.array(guess, float); peak = None
    for _ in range(rounds):
        crops = [crop(ct, i, *g[k], S) for k, i in enumerate(idx)]
        X = torch.from_numpy(np.stack([c[0] for c in crops]))
        P, peak = centrenet.predict_stacked(net, lambda j: X[j.cpu()].to(device).float() / 255.0, len(crops), device)
        g = P + np.array([c[1] for c in crops], float)
    return g, peak

def _mm(a, b, um):
    return np.hypot(*(a - b).T) * um * F3 / 1000

def cv(data_dir, out, folds=(0, 1, 2, 3), epochs=12, width=16, device="cpu", seed=0, rounds=2, time_s=None, every=1,
       offsets=(0.0, 1.2, 2.5)):
    import pipeline
    from pipeline import FOLDS, _stats
    os.makedirs(out, exist_ok=True)
    cache = {}
    def load(s):
        if s not in cache:
            d = np.load(os.path.join(data_dir, f"{s}.npz")); ct = d["ct"]; z = d["z_l0"]; um = float(d["um"])
            t = truth_l3(s, z); bd, org, tk = bands(ct, t)
            cache[s] = (bd, org, tk, um)
        return cache[s]
    res = {}
    for k in folds:
        test = FOLDS[k]; train_s = [s for s in slices.LABELLED if s not in test]
        log = lambda m: print(f"[fold{k}] {m}", flush=True)
        net, info = train({s: load(s) for s in train_s}, epochs, seed + k, width=width, time_s=time_s, device=device, log=log)
        torch.save(net.state_dict(), os.path.join(out, f"refine_cv_fold{k}.pt"))   # not chain's refine_fold{k}.pt
        res[f"fold{k}"] = dict(train=train_s, test=test, info=info, scrolls={})
        for s in test:
            d = np.load(os.path.join(data_dir, f"{s}.npz")); ct = d["ct"]; z = d["z_l0"]; um = float(d["um"])
            t = truth_l3(s, z); idx = np.nonzero(np.isfinite(t[:, 0]))[0][::every]
            r = {}
            for med in offsets:
                rng = np.random.default_rng([1000 + slices.LABELLED.index(s), int(med * 10)])   # same for every model
                o = smooth_offsets(len(idx), rng, um, med, corr=8 / every) if med else np.zeros((len(idx), 2))
                name = f"med{med:g}" if med else "zero"
                g0 = t[idx] + o
                g1, peak = refine(net, ct, idx, g0, rounds, device)
                before = _mm(centrenet.smooth_z(g0), t[idx], um); after = _mm(centrenet.smooth_z(g1), t[idx], um)
                r[name] = dict(before=_stats(before), after=_stats(after), raw_before=_stats(_mm(g0, t[idx], um)),
                               raw_after=_stats(_mm(g1, t[idx], um)), peak_median=round(float(np.median(peak)), 3))
            res[f"fold{k}"]["scrolls"][s] = r
            log(f"{s}: " + "  ".join(f"{n} raw {v['raw_before']['median_mm']:.2f}->{v['raw_after']['median_mm']:.2f}, smoothed "
                                     f"{v['before']['median_mm']:.2f}->{v['after']['median_mm']:.2f} mm" for n, v in r.items()))
        pipeline.write_json(res, os.path.join(out, "refine_cv.json"), indent=1)
    return res

CHAIN_JOBS = [f"fold{k}" for k in range(4)] + ["all"]   # what a full refine run writes

def _load_band_data(data_dir, scrolls):
    out = {}
    for s in scrolls:
        d = np.load(os.path.join(data_dir, f"{s}.npz")); t = truth_l3(s, d["z_l0"])
        bd, org, tk = bands(d["ct"], t); out[s] = (bd, org, tk, float(d["um"]))
    return out

def chain_job(name, data_dir, base, out, epochs=30, width=32, time_s=300, device="cpu", seed=0, rounds=2):
    """Train one refine model (name fold<k> trains without fold k's scrolls; all trains on all 13) and refine the
    first stage's real answers from run directory `base`: the fold's held-out scrolls from that fold's models
    (mean of seeds, as collect scores them) and any scrolls in slices.UNLABELLED from the median of every first-stage
    model."""
    import pipeline
    k = None if name == "all" else int(name[4:])
    test = pipeline.FOLDS[k] if k is not None else []
    recs = [pipeline.read_json(os.path.join(base, f)) for f in sorted(os.listdir(base)) if f.endswith(".json") and f[:3] in ("fol", "all")]
    log = lambda m: print(f"[refine {name}] {m}", flush=True)
    net, info = train(_load_band_data(data_dir, [s for s in slices.LABELLED if s not in test]), epochs, seed,
                      width=width, time_s=time_s, device=device, log=log)
    os.makedirs(out, exist_ok=True)
    torch.save(net.state_dict(), os.path.join(out, f"refine_{name}.pt"))
    preds = {}
    for s in test + slices.UNLABELLED:
        rs = [r for r in recs if (s in r["test"]) or (s in slices.UNLABELLED and s in r["preds"])]
        Y = np.array([r["preds"][s]["yx"] for r in rs]); p0 = rs[0]["preds"][s]
        g0 = (Y.mean(0) if s in test else np.median(Y, 0)) / F3
        d = np.load(os.path.join(data_dir, f"{s}.npz")); present = np.array(p0["present"])
        idx = np.nonzero(present)[0]
        g1 = np.full_like(g0, np.nan); pk = np.full(len(g0), np.nan)
        g1[idx], pk[idx] = refine(net, d["ct"], idx, g0[idx], rounds, device)
        preds[s] = dict(z=p0["z"], base_yx=(g0 * F3).round(2).tolist(), yx=np.where(np.isfinite(g1), g1 * F3, np.nan).round(2).tolist(),
                        peak=np.nan_to_num(pk).round(4).tolist(), present=p0["present"], held_out=s in test, um=p0["um"], vol=p0["vol"])
    rec = dict(job=f"refine_{name}", test=test, epochs=epochs, width=width, time_s=time_s, side=S, reach=R, rounds=rounds,
               device=device, train_info=info, base=os.path.basename(base.rstrip("/")), preds=preds)
    if str(device).startswith("cuda"):     # mps or cpu: no CUDA name to record
        rec["gpu"] = torch.cuda.get_device_name(torch.device(device))
    pipeline.write_json(rec, os.path.join(out, f"refine_{name}.json"))
    log(f"done {info}")
    return rec

def chain_collect(data_dir, out):
    """Held-out scores of the first stage alone and chained with the refine stage, both smoothed along z the same
    way; and, for each scroll in slices.UNLABELLED, if any, one umbilicus JSON from the median of the refine models
    (both end trims applied) in OUT/umbilicus/."""
    import pipeline
    recs = [pipeline.read_json(os.path.join(out, f)) for f in sorted(os.listdir(out)) if f.startswith("refine_") and f.endswith(".json")]
    res = dict(held_out={}, jobs=[{k: r[k] for k in ("job", "train_info", "test", "base")} | {"gpu": r.get("gpu")} for r in recs])
    A, B, wins = [], [], 0
    for s in slices.LABELLED:
        rs = [r for r in recs if s in r["test"]]
        if not rs:
            continue
        p = rs[0]["preds"][s]; z = np.array(p["z"]); um = p["um"]; present = np.array(p["present"])
        sm = lambda yx: centrenet.smooth_z(np.where(present[:, None], np.array(yx, float), np.nan))
        a = pipeline._err_mm(sm(p["base_yx"]), z, s, um); b = pipeline._err_mm(sm(p["yx"]), z, s, um)
        res["held_out"][s] = dict(first_stage=pipeline._stats(a), chained=pipeline._stats(b))
        A += list(a); B += list(b); wins += int(np.median(b) <= np.median(a))
    res["held_out_all"] = dict(first_stage=pipeline._stats(np.array(A)), chained=pipeline._stats(np.array(B)),
                               chained_not_worse_scrolls=wins) if A else {}
    missing_scrolls = [s for s in slices.LABELLED if s not in res["held_out"]]
    missing_jobs = sorted({f"refine_{n}" for n in CHAIN_JOBS} - {r["job"] for r in recs})
    res["held_out_all"].update(scrolls=len(res["held_out"]), missing_scrolls=missing_scrolls, missing_jobs=missing_jobs,
                               complete=not missing_scrolls and not missing_jobs)
    if slices.UNLABELLED:
        res["unlabelled"] = {}
        os.makedirs(os.path.join(out, "umbilicus"), exist_ok=True)
    for s in slices.UNLABELLED:
        rs = [r for r in recs if s in r["preds"]]
        if not rs:
            continue
        p0 = rs[0]["preds"][s]; z = np.array(p0["z"]); um = p0["um"]; present = np.array(p0["present"])
        Y = np.array([r["preds"][s]["yx"] for r in rs], float); yx = np.nanmedian(Y, 0)
        spread = np.nanmedian(np.hypot(*(Y - yx[None]).transpose(2, 0, 1)), 0) * um / 1000 if len(rs) > 1 else None
        sm = centrenet.smooth_z(np.where(present[:, None], yx, np.nan))
        d = np.load(os.path.join(data_dir, f"{s}.npz"))
        keep = present & pipeline.keep_band(pipeline.papyrus_area(d["ct"]), z, um)
        keep, _, _ = pipeline.end_trimmed_keep(d["ct"], sm, z, um, keep, level=int(d["level"]) if "level" in d.files else 3)
        j = pipeline.umbilicus_json(s, z, sm, keep, um, p0["vol"], spread,
                                    f"automatic: first-stage median refined by {len(rs)} zoomed models, smoothed along z "
                                    f"(scripts/umbilicus); {pipeline._trim_note()}")
        pipeline.write_json(j, os.path.join(out, "umbilicus", f"{s}_umbilicus.json"), indent=1)
        moved = np.hypot(*(sm - centrenet.smooth_z(np.where(present[:, None], np.array(p0["base_yx"], float), np.nan))).T) * um / 1000
        res["unlabelled"][s] = dict(points=j["metadata"]["total_points"], models=len(rs), spread_mm_median=j["metadata"]["spread_mm_median"],
                                 moved_from_first_stage_mm_median=round(float(np.median(moved[keep])), 3) if keep.any() else None)
    pipeline.write_json(res, os.path.join(out, "result.json"), indent=1)
    return res

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cv", "chain", "chain-collect"]); ap.add_argument("name", nargs="?")
    ap.add_argument("--base", help="first-stage run directory (chain)")
    ap.add_argument("--data", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--folds", type=int, nargs="+", default=[0, 1, 2, 3])
    ap.add_argument("--epochs", type=int, default=12); ap.add_argument("--width", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=2); ap.add_argument("--time-s", type=float, default=None)
    ap.add_argument("--device", default="cpu"); ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--side", type=int, default=S); ap.add_argument("--reach", type=int, default=R)
    ap.add_argument("--offsets", type=float, nargs="+", default=[0.0, 1.2, 2.5])
    a = ap.parse_args()
    S, R = a.side, a.reach
    if a.cmd == "cv":
        cv(a.data, a.out, a.folds, a.epochs, a.width, a.device, rounds=a.rounds, time_s=a.time_s, every=a.every,
           offsets=a.offsets)
    elif a.cmd == "chain":
        chain_job(a.name, a.data, a.base, a.out, a.epochs, a.width, a.time_s, a.device, rounds=a.rounds)
    else:
        print(json.dumps(chain_collect(a.data, a.out), indent=1))
