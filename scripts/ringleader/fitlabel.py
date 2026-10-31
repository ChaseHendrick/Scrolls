"""villa's spiral fit read as a Ringleader labeling: one winding label per m7 skeleton piece of a slice, written
in the per-slice npz layout score.py reads (the community comparator). Model output, never a reading.

    python3 scripts/ringleader/fitlabel.py convert --ckpt FIT/checkpoint_fitted.ckpt --umb FIT/dataset/umbilicus.json \
        --geo work/ringleader/stack3000 --out work/ringleader/fit3000 --villa VILLA_SPIRAL_DIR      (villa's Python)
    python3 scripts/ringleader/score.py work/ringleader/fit3000

The pieces are Ringleader's own: --geo is a Ringleader run folder (its zNNNNN.npz files), and every key score.py
reads (ys, xs, pid, rows, r) is copied unchanged, so both labelings are scored on the same skeleton pixels, pieces,
radial steps and controls. Only the label, the hand and theta' change.

Per skeleton pixel (slice frame: x = xs, y = ys, z = the slice) the fit's own grid coordinates come from an affine
(Frame; on PHerc0139 the catalog matrix from volume 20250728140407 to 20260102150214, divided by 4 for the
fit's L2 grid), then villa's slice-to-spiral transform of the checkpoint (load_fit): u = r / dr (the outward
position in windings) and the fit's angle theta_f. A point's winding in the fit is floor(u - mod(theta_f, 2 pi) /
2 pi), so u - theta_f / 2 pi is constant along a fitted sheet. The integer turn in Ringleader's convention (start
ray theta' = 0 of the slice's own axis, turn + 1 across it) is then

    hand  = +1 when theta_f turns the way the slice's image angle does, else -1 (fit_hand: from the fit alone)
    s     = u - theta_h / 2 pi, theta_h = mod(hand x image angle, 2 pi) (the same start ray as Ringleader's)
    f0    = the circular mean of frac(s) over the slice's skeleton pixels (where the fit puts its sheets; no truth)
    turn  = round(s - f0) per pixel; a piece's label is the most common turn of its pixels

No setting is fitted to the truth: hand, f0 and the labels come from the checkpoint and the m7 skeleton only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
KEEP = ("ys", "xs", "pid", "rows", "r", "path_len")      # copied unchanged from the Ringleader run


class Frame:
    """The map from the slices' frame (x y z voxels) to the fit grid: fit = apply(M, q) / scale. On PHerc0139 M is
    the catalog matrix from volume 20250728140407 (m7) to 20260102150214 and scale 4 (a fit on that scan's L2)."""

    def __init__(self, matrix, scale=4.0):
        self.M = np.asarray(matrix, float)
        self.scale = float(scale)

    def to_fit(self, q):
        q = np.asarray(q, float)
        return (q @ self.M[:, :3].T + self.M[:, 3]) / self.scale


def load_fit(ckpt, umbilicus):
    """villa's spiral fit: (slice-to-spiral map on (N, 3) z y x fit-grid points, dr per winding, iteration, the
    checkpoint's config). Needs villa's spiral-fitting modules (checkpoint_io, flatten_spiral_checkpoint) and torch."""
    import os

    import torch
    from checkpoint_io import load_checkpoint_cpu
    from flatten_spiral_checkpoint import _build_model, _checkpoint_config
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    cp = load_checkpoint_cpu(str(ckpt))
    cfg = _checkpoint_config(cp)
    model = _build_model(cp, cfg, str(umbilicus), torch.device("cpu"))
    transform = model.get_slice_to_spiral_transform()
    step = cp.get("completed_iterations", cp.get("iteration"))

    def to_sp(zyx, batch=20000):
        out = []
        with torch.inference_mode():
            for s in range(0, len(zyx), batch):
                out.append(transform(torch.from_numpy(np.ascontiguousarray(zyx[s:s + batch], np.float32))).cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 3), np.float32)
    return to_sp, float(model.get_dr_per_winding().detach()), step, cfg


def fit_hand(theta_f, image_th) -> int:
    """+1 when the fit's angle turns with the image angle about the slice's axis, -1 when against it: the larger of
    the two circular alignments |mean exp(i(theta_f - th))| and |mean exp(i(theta_f + th))|."""
    ok = np.isfinite(theta_f) & np.isfinite(image_th)
    a, b = theta_f[ok], image_th[ok]
    if not len(a):
        raise ValueError("no finite angles")
    same = abs(np.mean(np.exp(1j * (a - b))))
    other = abs(np.mean(np.exp(1j * (a + b))))
    return 1 if same >= other else -1


def phase(s) -> float:
    """Circular mean of frac(s) in [0, 1): where the fit's sheets sit between its integer turns."""
    s = s[np.isfinite(s)]
    if not len(s):
        return 0.0
    m = np.mean(np.exp(2j * math.pi * s))
    return float(np.mod(np.angle(m) / (2 * math.pi), 1.0))


def piece_mode(lab_px, pid) -> np.ndarray:
    """Per pixel, the most common label of its piece (ties: the lower label); NaN where pid < 0 or no finite label."""
    out = np.full(len(lab_px), np.nan)
    ok = (pid >= 0) & np.isfinite(lab_px)
    if not ok.any():
        return out
    p, v = pid[ok], lab_px[ok].astype(np.int64)
    off = v.min()
    vv = v - off
    nv = int(vv.max()) + 1
    key = p.astype(np.int64) * nv + vv
    uk, cnt = np.unique(key, return_counts=True)
    up, uv = uk // nv, uk % nv
    # for each piece the value of largest count (np.unique sorts by piece then value, so the first max is the lower)
    order = np.lexsort((uv, -cnt, up))
    first = np.ones(len(order), bool)
    first[1:] = up[order][1:] != up[order][:-1]
    best = dict(zip(up[order][first].tolist(), (uv[order][first] + off).tolist()))
    lab_piece = np.full(int(pid.max()) + 1, np.nan)
    lab_piece[list(best)] = list(best.values())
    m = pid >= 0
    out[m] = lab_piece[pid[m]]
    return out


def labels(u, theta_f, theta_p, hand_geo, pid):
    """The fit's labels on one slice's skeleton: (per-piece label, per-pixel turn, hand, theta_h, f0, spread).
    u = r / dr and theta_f are the fit's spiral coordinates per pixel; theta_p and hand_geo are the Ringleader
    geometry's theta' and hand (image angle = hand_geo x theta_p, modulo 2 pi)."""
    image_th = np.mod(hand_geo * theta_p, 2 * math.pi)
    h = fit_hand(theta_f, image_th)
    theta_h = theta_p if h == hand_geo else np.mod(-theta_p, 2 * math.pi)     # slicelab.flip_hand: same start ray
    s = u - theta_h / (2 * math.pi)
    f0 = phase(s)
    t = s - f0
    px = np.where(np.isfinite(t), np.rint(t), np.nan)
    spread = float(np.nanmean(np.abs(t - px))) if np.isfinite(t).any() else None   # 0.25 when the phase is random
    return piece_mode(px, pid), px, h, theta_h, f0, spread


def fit_coords(to_sp, dr, xs, ys, z, frame, batch=400000):
    """u = r / dr and theta_f per pixel of slice z (the slices' frame) through the fit's spiral map."""
    q = np.stack([xs.astype(float), ys.astype(float), np.full(len(xs), float(z))], 1)
    f = frame.to_fit(q)                                       # fit grid x, y, z
    zyx = f[:, ::-1].astype(np.float32)
    u = np.empty(len(xs))
    th = np.empty(len(xs))
    for s in range(0, len(xs), batch):
        sp = np.asarray(to_sp(zyx[s:s + batch]), float)
        u[s:s + batch] = np.hypot(sp[:, 1], sp[:, 2]) / dr
        th[s:s + batch] = np.arctan2(sp[:, 1], sp[:, 2])
    return u, th, f


def _sha(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 24), b""):
            h.update(b)
    return h.hexdigest()


def cmd_convert(a) -> int:
    sys.path.insert(0, str(HERE.parent))
    if a.villa:
        sys.path.insert(0, a.villa)
    import rlcommon
    geo = Path(a.geo)
    files = sorted(geo.glob("z*.npz"))
    zs = [int(f.stem[1:]) for f in files]
    rlcommon.check_z(zs, rlcommon.parse_ranges(a.exclude_z))
    if not files:
        raise SystemExit(f"no zNNNNN.npz in {geo}")
    t0 = time.time()
    to_sp, dr, step, cfg = load_fit(Path(a.ckpt), Path(a.umb))
    if a.matrix:
        M = np.asarray(json.loads(Path(a.matrix).read_text())["matrix"], float)
    else:
        P = rlcommon.P0139
        M = rlcommon.catalog_matrix(P["sample"], P["from"], P["to"], a.catalog)
    frame = Frame(M, a.fit_scale)
    zb, ze = cfg.get("z_begin"), cfg.get("z_end")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pixel").mkdir(exist_ok=True)
    meta = {"checkpoint": str(a.ckpt), "checkpoint_sha256": _sha(a.ckpt), "umbilicus_sha256": _sha(a.umb),
            "step": step, "dr": dr, "z_begin": zb, "z_end": ze, "geometry": str(geo),
            "rule": "turn = round(u - theta_h / 2 pi - f0), label = the piece's most common turn (fitlabel.py)",
            "slices": {}}
    for f, z in zip(files, zs):
        d = np.load(f)
        u, th_f, fx = fit_coords(to_sp, dr, d["xs"], d["ys"], z, frame)
        fz = fx[:, 2]
        inside = (fz >= zb) & (fz < ze) if zb is not None and ze is not None else np.ones(len(fz), bool)
        lab, px, h, theta_h, f0, spread = labels(u, th_f, d["theta_p"], int(d["hand"]), d["pid"])
        keep = {k: d[k] for k in KEEP if k in d.files}
        np.savez_compressed(out / f"z{z:05d}.npz", **keep, label=lab, theta_p=theta_h, hand=np.int64(h),
                            u=u, theta_f=th_f, turn_px=px)
        np.savez_compressed(out / "pixel" / f"z{z:05d}.npz", **keep, label=px, theta_p=theta_h, hand=np.int64(h))
        rec = {"hand": h, "ringleader_hand": int(d["hand"]), "f0": f0, "spread": spread, "pixels": int(len(u)),
               "fit_z": [float(fz.min()), float(fz.max())], "outside_window": int((~inside).sum()),
               "piece_agree": float(np.nanmean(lab == px)) if len(px) else None}
        meta["slices"][str(z)] = rec
        print(f"PROGRESS z{z}: hand {h} (Ringleader {int(d['hand'])}), f0 {f0:.3f}, spread {spread:.3f}, "
              f"fit z {rec['fit_z'][0]:.0f} to {rec['fit_z'][1]:.0f}, outside window {rec['outside_window']}", flush=True)
    meta["seconds"] = round(time.time() - t0, 1)
    (out / "fitlabel.json").write_text(json.dumps(meta, indent=1) + "\n")
    (out / "pixel" / "fitlabel.json").write_text(json.dumps(dict(meta, variant="per pixel, no piece vote"),
                                                            indent=1) + "\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="a fit's checkpoint to per-piece labels on a Ringleader run's skeleton")
    c.add_argument("--ckpt", required=True)
    c.add_argument("--umb", required=True, help="the umbilicus.json the fit used (its dataset folder, fit grid)")
    c.add_argument("--geo", required=True, help="a Ringleader run folder whose zNNNNN.npz give the pieces")
    c.add_argument("--out", required=True)
    c.add_argument("--villa", help="villa's spiral-fitting folder, if not already on sys.path")
    c.add_argument("--matrix", help='JSON {"matrix": 3 x 4} from the slices\' frame to the fit\'s scan voxels '
                   "(default: PHerc0139's catalog transform from 20250728140407 to 20260102150214)")
    c.add_argument("--catalog", help="catalog metadata.json (path or URL) for the default matrix")
    c.add_argument("--fit-scale", type=float, default=4.0, help="scan voxels per fit-grid voxel (default 4, L2)")
    c.add_argument("--exclude-z", default=None, help="z ranges never to convert, lo:hi,lo:hi or a file of them")
    a = ap.parse_args(argv)
    return cmd_convert(a)


if __name__ == "__main__":
    sys.exit(main())
