"""Kollesis finder: candidate scores from tracked full-height patch features, and dev AUC tables.

    python fh_scores.py OUTDIR [OUTDIR ...]      # prints AUCs of every candidate against each negative kind

Each score is one number per query, larger = more kollesis-like. Missing (too few valid samples) is NaN.
"""
import glob
import json
import os
import sys

import numpy as np

FEATS = ('thick', 'peaks', 'mass', 'ridge', 'bright')
NEAR = (300.0, 1500.0, 3000.0)      # near window upper ends (lower end 0)
FAR = (4000.0, 8000.0)
BEY = (-1800.0, -200.0)
MIN_VALID = 0.5                    # fraction of a window's samples that must be valid


def win(f, valid, s, lo, hi, rows=None):
    """Per-row mean of f over columns lo <= s < hi; NaN where under MIN_VALID valid."""
    m = (s >= lo) & (s < hi)
    if rows is not None:
        f, valid = f[rows], valid[rows]
    v = valid[:, m]
    x = np.where(v, f[:, m], np.nan)
    with np.errstate(all='ignore'):
        out = np.nanmean(x, 1)
    out[v.mean(1) < MIN_VALID] = np.nan
    return out


def kfh1(d):
    """The score frozen for the PHerc0139 test (chosen on PHerc0332 dev, 28 Oct 2026): density above the sheet level
    ('mass') in the first 600 voxels behind the point minus 4,000 to 8,000 voxels behind, per row, averaged over
    the five rows within 256 voxels of the point's height; NaN unless at least 3 of the 5 rows are valid."""
    s, valid = d['s'], d['valid']
    f = d['mass'].astype(np.float32)
    R = valid.shape[0]
    mid = R // 2
    near = win(f, valid, s, 0.0, 600.0)
    far = win(f, valid, s, 4000.0, 8000.0)
    dd = (near - far)[mid - 2:mid + 3]
    ok = np.isfinite(dd)
    return float(dd[ok].mean()) if ok.sum() >= 3 else np.nan


def candidates(d):
    """dict name -> score for one query's features d (npz-like)."""
    s, valid = d['s'], d['valid']
    out = {'kfh1': kfh1(d)}
    R = valid.shape[0]
    mid = R // 2
    for F in FEATS:
        f = d[F].astype(np.float32)
        far = win(f, valid, s, *FAR)
        bey = win(f, valid, s, *BEY)
        for W in NEAR:
            near = win(f, valid, s, 0.0, W)
            with np.errstate(all='ignore'):
                dnf = near - far
                dnb = near - bey
                out[f'{F}_near{int(W)}-far_mean'] = np.nanmean(dnf) if np.isfinite(dnf).sum() >= 5 else np.nan
                out[f'{F}_near{int(W)}-far_median'] = np.nanmedian(dnf) if np.isfinite(dnf).sum() >= 5 else np.nan
                ok = np.isfinite(dnf)
                out[f'{F}_near{int(W)}-far_frac'] = (dnf[ok] > 0).mean() if ok.sum() >= 5 else np.nan
                out[f'{F}_near{int(W)}-bey_mean'] = np.nanmean(dnb) if np.isfinite(dnb).sum() >= 5 else np.nan
                out[f'{F}_near{int(W)}_row0-far'] = (near[mid] - far[mid])
                out[f'{F}_near{int(W)}_abs'] = np.nanmean(near) if np.isfinite(near).sum() >= 5 else np.nan
    return out


def auc(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if not len(a) or not len(b):
        return np.nan
    allv = np.r_[a, b]
    order = np.argsort(allv, kind='mergesort')
    ranks = np.empty(len(allv))
    sv = allv[order]
    # average ranks for ties
    i = 0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    ra = ranks[:len(a)].sum()
    return (ra - len(a) * (len(a) + 1) / 2) / (len(a) * len(b))


def load(dirs, keys=FEATS + ('valid', 's')):
    rows = []
    for dd in dirs:
        for p in sorted(glob.glob(os.path.join(dd, 'q*.npz'))):
            if p.endswith('.tmp.npz'):
                continue
            z = np.load(p)
            rows.append(dict(qid=int(os.path.basename(p)[1:6]), kind=str(z['kind']), file=str(z['fname']),
                             **{k: z[k] for k in keys}))
    return rows


def table(rows, neg=('break', 'plain', 'interior', 'shifted')):
    C = [candidates(r) for r in rows]
    kinds = np.array([r['kind'] for r in rows])
    names = list(C[0])
    res = {}
    for nm in names:
        v = np.array([c[nm] for c in C], float)
        res[nm] = {k: auc(v[kinds == 'kollesis'], v[kinds == k]) for k in neg}
        res[nm]['missing_kollesis'] = int(np.isnan(v[kinds == 'kollesis']).sum())
    return res, kinds


if __name__ == '__main__':
    rows = load(sys.argv[1:])
    from collections import Counter
    print(Counter(r['kind'] for r in rows))
    res, kinds = table(rows)
    neg = ('break', 'plain', 'interior', 'shifted')
    print(f"{'candidate':34s} " + ' '.join(f'{k:>9s}' for k in neg) + '  miss')
    for nm, r in sorted(res.items(), key=lambda kv: -np.nan_to_num(kv[1]['interior'])):
        print(f"{nm:34s} " + ' '.join(f"{r[k]:9.3f}" for k in neg) + f"  {r['missing_kollesis']}")
    json.dump(res, open('fh_dev_table.json', 'w'), indent=1)
