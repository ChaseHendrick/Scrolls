"""Scroll centre (umbilicus) line for any scroll from trained weights: no training, no labels needed.

    python predict.py SCROLL [SCROLL ...] --first W.pt [W.pt ...] [--zoom Z.pt ...] --data DIR --out DIR
                      [--volume PATH] [--device cpu] [--no-end-rule]

For each scroll: the slices the models were trained on (every 8th level-3 plane of the scan, read from the
open-data bucket with range requests into DIR/<scroll>.npz unless that file exists; an existing file is used only
when it holds the scan asked for, --volume or by default slices.volume(), and holds some CT), the first-stage centre of each
--first model (median over models), then each --zoom model moves that guess onto the centre (median over models),
then the line is smoothed along z and the ends are trimmed (mount and caps by pipeline.keep_band, then the
end-point rule unless --no-end-rule). Writes OUT/<scroll>_umbilicus.json in the format of the published umbilicus
files (control points x, y, z in level-0 voxels) and OUT/<scroll>_predict.json with per-slice details.
The same steps as pipeline.collect and refine.chain_collect, without the training. Takes 8 to 10 um scans only
(UM_RANGE): the 1.2 m scans, like the 8.64 and 9.362 um scans the models trained on. Model output, not a
measurement: check the line on CT before using it.
"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slices, pipeline

FRAME = 256     # first-stage frame side, as trained (pipeline.run_job size)
UM_RANGE = (8.0, 10.0)   # voxel sizes taken: the 1.2 m scans (about 9 um); the models trained on 8.64 and 9.362 um


def check_um(um, what):
    """Refuse a scan outside UM_RANGE: untested, and on a finer scan every 8th level-3 plane is many times the download."""
    if not UM_RANGE[0] <= um <= UM_RANGE[1]:
        raise SystemExit(f"{what}: {um:g} um voxels; this finder takes {UM_RANGE[0]:g} to {UM_RANGE[1]:g} um scans "
                         "(the models trained on 8.64 and 9.362 um scans only)")


def _json_list(a, nd):
    """Rounded values for JSON; NaN (a slice without papyrus) becomes null."""
    a = np.round(np.asarray(a, float), nd)
    return np.where(np.isfinite(a), a, None).tolist()


def load_net(path, device):
    import torch, centrenet
    sd = torch.load(path, map_location=device, weights_only=True)
    net = centrenet.Net(int(sd["e1.0.weight"].shape[0])).to(device)
    net.load_state_dict(sd); net.eval()
    return net


def first_stage(npz, weights, device):
    """Each model's centre per slice in level-0 voxels: (models, slices, 2), and the slices with any papyrus."""
    import centrenet
    imgs, fr = centrenet.frame(npz, FRAME, device=device)
    Y = []
    for w in weights:
        P, _ = centrenet.predict(load_net(w, device), imgs, device=device)
        Y.append(centrenet.Frame.net_to_l0(P.astype(float), fr))
    return np.array(Y), np.asarray(fr["present"], bool)


def zoom_stage(ct, guess_l0, present, weights, device, level=3):
    """Each zoom model's refined centre (level-0 voxels) from the same guess; NaN on slices without papyrus."""
    import refine
    f = 2 ** level; idx = np.nonzero(present)[0]; Y = []
    for w in weights:
        g = np.full(guess_l0.shape, np.nan)
        g[idx] = refine.refine(load_net(w, device), ct, idx, guess_l0[idx] / f, device=device)[0] * f
        Y.append(g)
    return np.array(Y)


def predict(s, first, zoom, data, out, device="cpu", end_rule=True, vol=None):
    os.makedirs(data, exist_ok=True); os.makedirs(out, exist_ok=True)
    npz = os.path.join(data, f"{s}.npz")
    if vol:                       # before any download
        try:
            vum = float(vol.rstrip("/").split("/")[-1].split("-")[1].replace("um", ""))
        except (IndexError, ValueError):
            raise SystemExit(f"{vol}: no voxel size in the scan name (<timestamp>-<size>um-...)")
        check_um(vum, vol)
    want = (vol or slices.volume(s)).rstrip("/")    # the scan to use; a slice file of another scan is never reused
    if not os.path.exists(npz):
        slices.extract_ranged(s, npz + ".tmp.npz", vol=want); os.replace(npz + ".tmp.npz", npz)
    d = np.load(npz); ct = d["ct"]; z = np.asarray(d["z_l0"]); um = float(d["um"])
    level = int(d["level"]) if "level" in d.files else 3
    held = str(d["vol"]).rstrip("/") if "vol" in d.files else None
    if held != want:
        raise SystemExit(f"{npz} holds slices of {held}, not {'--volume ' if vol else 'the default scan '}{want}: "
                         "use another --data folder or remove the file")
    if not ct.any() or ("missing" in d.files and "chunks" in d.files and int(d["missing"]) >= int(d["chunks"])):
        raise SystemExit(f"{npz} holds no CT (every chunk read was absent or zero): remove the file and check the scan path")
    check_um(um, npz)
    Y1, present = first_stage(npz, first, device)
    yx = np.median(Y1, 0); Y = Y1
    if zoom:
        Y = zoom_stage(ct, yx, present, zoom, device, level)
        yx = np.nanmedian(Y, 0)
    spread = np.nanmedian(np.hypot(*(Y - yx[None]).transpose(2, 0, 1)), 0) * um / 1000 if len(Y) > 1 else None
    sm = slices.smooth_z(np.where(present[:, None], yx, np.nan))
    keep = present & pipeline.keep_band(pipeline.papyrus_area(ct), z, um)
    band = keep.copy(); support = None; thr = None
    if end_rule:
        keep, support, thr = pipeline.end_trimmed_keep(ct, sm, z, um, keep, level=level)
    stages = f"median of {len(first)} first-stage models" + (f", refined by the median of {len(zoom)} zoom models" if zoom else "")
    j = pipeline.umbilicus_json(s, z, sm, keep, um, str(d["vol"]), spread,
                                f"automatic: {stages}, smoothed along z (scripts/umbilicus/predict.py); {pipeline._trim_note(end_rule)}")
    with open(os.path.join(out, f"{s}_umbilicus.json"), "w") as fh:
        json.dump(j, fh, indent=1)
    detail = dict(scroll=s, volume=str(d["vol"]), voxelsize_um=um, z=z.tolist(), yx=_json_list(sm, 2),
                  present=present.tolist(), keep_band=band.tolist(), kept=keep.tolist(), papyrus_level=thr,
                  support=None if support is None else np.round(support, 3).tolist(),
                  spread_mm=None if spread is None else _json_list(spread, 3),
                  first=[os.path.basename(w) for w in first], zoom=[os.path.basename(w) for w in zoom], rule=dict(
                      cap_mm=pipeline.CAP_MM, area_frac=pipeline.AREA_FRAC, end_rule=end_rule, radius_mm=pipeline.END_RADIUS_MM,
                      min_support=pipeline.END_SUPPORT, run_mm=pipeline.END_RUN_MM, rays=pipeline.END_RAYS))
    with open(os.path.join(out, f"{s}_predict.json"), "w") as fh:
        json.dump(detail, fh)
    return dict(points=j["metadata"]["total_points"], keep_band=int(band.sum()), spread_mm_median=j["metadata"]["spread_mm_median"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scrolls", nargs="+")
    ap.add_argument("--first", nargs="+", required=True, help="first-stage weights (centrenet.Net state_dict)")
    ap.add_argument("--zoom", nargs="*", default=[], help="zoom-stage weights (refine.py)")
    ap.add_argument("--data", required=True, help="slice files <scroll>.npz (made here if missing)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--volume", help="bucket path of the scan to use (one scroll only, 8 to 10 um); default slices.volume()")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--no-end-rule", action="store_true")
    a = ap.parse_args()
    if a.volume and len(a.scrolls) > 1:
        raise SystemExit("--volume needs exactly one scroll")
    for s in a.scrolls:
        print(s, json.dumps(predict(s, a.first, a.zoom, a.data, a.out, a.device, not a.no_end_rule, a.volume)), flush=True)
