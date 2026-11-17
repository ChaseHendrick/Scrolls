#!/usr/bin/env python3
"""slicechains: winding sense from 2D sheet chains in single z planes of the m7 surface prediction.

Rule (frozen 16 Nov 2026 before its blind test): m7 level 1, core disk r < 1500 level-0 voxels around the center line at
each plane's z; skeletonize, remove 3x3 around junction pixels, pieces >= 8 px; greedy end linking with gap <= 1.0
pitch, ends antiparallel within 35 deg, forward progress >= -1.5 px, lateral offset <= 0.25 pitch, no cycles; a chain
winding >= 1 turn votes by r(theta + 2 pi) - r(theta) (median; positive = CW, radius grows with atan2(y, x),
x = zarr axis 2, y = axis 1) when the median's sign holds on >= 0.6 of the overlap. Votes pool over planes at
linspace(z0, z1, N + 2)[1:-1]; decide when >= min_votes votes and share >= min_share, else abstain.
--mirror flips each plane in x and mirrors the center line (the call must flip).
--symmetric also tracks each plane mirrored and adds its votes, flipped, to the stored ones, so pixel-order effects of
the thinning and walking cancel and the mirrored call is the exact opposite by construction.
--selftest runs the rule on synthetic spirals of both senses (and a set of closed rings, which must abstain).
Developed 16 Nov 2026 on six scrolls whose catalog direction was known; tested blind on 12 others (docs/tools/slicechains.md).
Needs only numpy, scipy, numcodecs, skimage.
"""
import argparse, json, math, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np, numcodecs
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage.morphology import skeletonize

LEV, R_L0, MINLEN, GAP_F, LAT_F, COS_MIN, MIN_CONS = 1, 1500.0, 8, 1.0, 0.25, math.cos(math.radians(35)), 0.6
SAMPLES_PER_TURN, MIN_TURNS = 64, 1.0
K8 = np.ones((3, 3), int)
BL = numcodecs.Blosc()

# ------------------------------------------------------------------ center line
def load_line(path):
    txt = open(path).read().strip()
    if txt[:1] in '[{':
        d = json.loads(txt)
        if isinstance(d, dict):
            d = d.get('points', d.get('control_points'))
        pts = [(float(e['z']), float(e['y']), float(e['x'])) if isinstance(e, dict) else tuple(map(float, e[:3])) for e in d]
    else:
        pts = [tuple(float(v) for v in l.split(',') if v.strip()) for l in txt.splitlines()
               if l.strip() and not l.strip().startswith('#')]
    return sorted(pts)

def centre_at(pts, z):
    if z <= pts[0][0]: return pts[0][2], pts[0][1]
    if z >= pts[-1][0]: return pts[-1][2], pts[-1][1]
    lo, hi = 0, len(pts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pts[mid][0] <= z: lo = mid
        else: hi = mid
    (z0, y0, x0), (z1, y1, x1) = pts[lo], pts[hi]
    t = (z - z0) / (z1 - z0) if z1 != z0 else 0.0
    return x0 + t * (x1 - x0), y0 + t * (y1 - y0)

# ------------------------------------------------------------------ data
_META = {}
def _meta(url):
    for k in range(5):
        try:
            if url not in _META: _META[url] = json.load(urllib.request.urlopen(f"{url}/{LEV}/.zarray", timeout=60))
            return _META[url]
        except Exception:
            if k == 4: raise
            time.sleep(3 * (k + 1))

def fetch_plane(url, line, z):
    """Binary m7 plane at level LEV covering the core box; returns img, origin (level px), centre (L0)."""
    meta = _meta(url)
    sh, ch = meta['shape'], meta['chunks'][0]; s = 2 ** LEV
    cz, oz = (z // s) // ch, (z // s) % ch
    cx, cy = centre_at(line, z)
    x0 = max(0, int((cx - R_L0) / s) // ch); x1 = min((sh[2] - 1) // ch, int((cx + R_L0) / s) // ch)
    y0 = max(0, int((cy - R_L0) / s) // ch); y1 = min((sh[1] - 1) // ch, int((cy + R_L0) / s) // ch)
    cl = [(j, i) for j in range(y0, y1 + 1) for i in range(x0, x1 + 1)]
    def get(c):
        for _ in range(5):
            try:
                b = urllib.request.urlopen(f"{url}/{LEV}/{cz}/{c[0]}/{c[1]}", timeout=90).read()
                return np.frombuffer(BL.decode(b), np.uint8).reshape(ch, ch, ch)[oz].copy()
            except urllib.error.HTTPError as e:
                if e.code in (403, 404): return None
            except Exception:
                time.sleep(2)
        raise RuntimeError(f'chunk {cz}/{c} failed')
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(get, cl))
    img = np.zeros(((y1 - y0 + 1) * ch, (x1 - x0 + 1) * ch), np.uint8)
    for (j, i), a in zip(cl, res):
        if a is not None: img[(j - y0) * ch:(j - y0 + 1) * ch, (i - x0) * ch:(i - x0 + 1) * ch] = a
    return img, (x0 * ch, y0 * ch), (cx, cy)

# ------------------------------------------------------------------ tracking
def pieces(b):
    sk = skeletonize(b)
    nb = ndi.convolve(sk.astype(int), K8, mode='constant') - 1
    sk = sk & ~ndi.binary_dilation(sk & (nb >= 3), structure=np.ones((3, 3), bool))
    lab, n = ndi.label(sk, structure=np.ones((3, 3)))
    nb = (ndi.convolve(sk.astype(int), K8, mode='constant') - 1) * sk
    out = []
    for i, sl in enumerate(ndi.find_objects(lab)):
        if sl is None: continue
        ys, xs = np.nonzero(lab[sl] == i + 1)
        if len(ys) < MINLEN: continue
        ys = ys + sl[0].start; xs = xs + sl[1].start
        idx = {(y, x): k for k, (y, x) in enumerate(zip(ys, xs))}
        ends = np.nonzero(nb[ys, xs] == 1)[0]
        cur = ends[0] if len(ends) else 0; order = [cur]; seen = {cur}
        while True:
            y, x = ys[cur], xs[cur]; nxt = None
            for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                k = idx.get((y + dy, x + dx))
                if k is not None and k not in seen: nxt = k; break
            if nxt is None: break
            order.append(nxt); seen.add(nxt); cur = nxt
        if len(order) >= MINLEN: out.append(np.stack([xs[order], ys[order]], 1).astype(float))
    return out

def link(ps, gap, lat_max):
    ends = []
    for i, p in enumerate(ps):
        k = min(6, len(p) - 1)
        for e, (pos, d) in enumerate(((p[0], p[0] - p[k]), (p[-1], p[-1] - p[-1 - k]))):
            ends.append((i, e, pos, d / (np.linalg.norm(d) + 1e-9)))
    P = np.array([e[2] for e in ends]); D = np.array([e[3] for e in ends]); cands = []
    for a, b in cKDTree(P).query_pairs(gap):
        if ends[a][0] == ends[b][0]: continue
        da, db = D[a], D[b]
        if np.linalg.norm(P[b] - P[a]) > gap or -(da @ db) < COS_MIN: continue
        v = P[b] - P[a]
        if np.linalg.norm(v) > 1e-9:
            if v @ da < -1.5 or -v @ db < -1.5: continue
            lat = max(abs(da[0] * v[1] - da[1] * v[0]), abs(db[0] * v[1] - db[1] * v[0]))
        else: lat = 0.0
        if lat <= lat_max: cands.append((np.linalg.norm(v) + 3 * lat, a, b))
    cands.sort(); parent = list(range(len(ps))); used = set(); nxt = {}
    def f(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for c, a, b in cands:
        if a in used or b in used: continue
        ra, rb = f(ends[a][0]), f(ends[b][0])
        if ra == rb: continue
        parent[ra] = rb; used |= {a, b}
        ea, eb = ends[a][:2], ends[b][:2]; nxt[ea] = eb; nxt[eb] = ea
    chains, done = [], set()
    for i in range(len(ps)):
        if i in done: continue
        cur, ce = i, 0
        while (cur, ce) in nxt: j, je = nxt[(cur, ce)]; cur, ce = j, 1 - je
        seq, e_in = [], ce
        while True:
            done.add(cur); seq.append(ps[cur] if e_in == 0 else ps[cur][::-1])
            if (cur, 1 - e_in) not in nxt: break
            cur, e_in = nxt[(cur, 1 - e_in)]
        chains.append(np.concatenate(seq))
    return chains

def turn_gain(xy, cx, cy):
    """Same measurement as kit.spiralsense.turn_gain for a curve at one z."""
    r = np.hypot(xy[:, 0] - cx, xy[:, 1] - cy); th = np.unwrap(np.arctan2(xy[:, 1] - cy, xy[:, 0] - cx))
    if th[-1] < th[0]: th, r = th[::-1], r[::-1]
    run = np.maximum.accumulate(th); keep = np.r_[True, np.diff(run) > 0]; th, r = run[keep], r[keep]
    turns = float((th[-1] - th[0]) / (2 * math.pi)) if len(th) > 1 else 0.0
    if turns < MIN_TURNS: return turns, None, None
    span = th[-1] - th[0] - 2 * math.pi
    n = max(2, int(SAMPLES_PER_TURN * max(span, 1e-9) / (2 * math.pi)) + 1)
    t = np.linspace(th[0], th[-1] - 2 * math.pi, n)
    dr = np.interp(t + 2 * math.pi, th, r) - np.interp(t, th, r); med = float(np.median(dr))
    return turns, med, float(np.mean(np.sign(dr) == np.sign(med)))

def plane_chains(img, cx, cy, pitch_px, r_px=None):
    H, W = img.shape; yy, xx = np.ogrid[:H, :W]
    rr = R_L0 / 2 ** LEV if r_px is None else r_px
    b = (img > 0) & ((xx - cx) ** 2 + (yy - cy) ** 2 < rr ** 2)
    out = []
    for c in link(pieces(b), GAP_F * pitch_px, LAT_F * pitch_px):
        th = np.unwrap(np.arctan2(c[:, 1] - cy, c[:, 0] - cx))
        if abs(th[-1] - th[0]) < 2 * math.pi * 0.95 and np.ptp(th) < 2 * math.pi: continue
        turns, g, cons = turn_gain(c, cx, cy)
        if g is None: continue
        vote = ('CW' if g > 0 else 'ACW') if (cons >= MIN_CONS and g != 0) else None
        out.append({'turns': round(turns, 3), 'gain_l0': round(g * 2 ** LEV, 2), 'consistency': round(cons, 3),
                    'r_median_l0': round(float(np.median(np.hypot(c[:, 0] - cx, c[:, 1] - cy))) * 2 ** LEV, 1),
                    'vote': vote})
    return out

def synthetic(sense, rings=False, n=700, pitch=9.0, seed=0):
    """Binary plane of an Archimedean spiral (sense 'CW': radius grows with atan2(y, x)) squashed 0.6 in y, rotated,
    with breaks, or of closed rings when rings is True; center (n/2, n/2)."""
    rng = np.random.default_rng(seed); img = np.zeros((n, n), bool); c = n / 2
    th = np.linspace(0, 2 * math.pi * 30, 400000)
    r = 40 + pitch * (th / (2 * math.pi)) if not rings else 40 + pitch * np.floor(th / (2 * math.pi))
    sg = 1 if sense == 'CW' else -1
    x, y = r * np.cos(sg * th), r * np.sin(sg * th) * 0.6
    a = 0.4; x, y = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
    keep = rng.random(len(th)) > 0.0
    for k in rng.integers(0, len(th), 60):
        keep[k:k + 300] = False
    xi, yi = np.round(c + x[keep]).astype(int), np.round(c + y[keep]).astype(int)
    ok = (xi >= 0) & (xi < n) & (yi >= 0) & (yi < n)
    img[yi[ok], xi[ok]] = True
    return ndi.binary_dilation(img), c, c, pitch * 0.6

def selftest():
    out = {}
    for name, sense, rings in (('spiral_CW', 'CW', False), ('spiral_ACW', 'ACW', False), ('rings', 'CW', True)):
        img, cx, cy, pitch = synthetic(sense, rings)
        votes = [q['vote'] for q in plane_chains(img.astype(np.uint8), cx, cy, pitch, r_px=img.shape[0])]
        out[name] = {'CW': votes.count('CW'), 'ACW': votes.count('ACW')}
    ok = (out['spiral_CW']['CW'] > 0 and out['spiral_CW']['ACW'] == 0 and out['spiral_ACW']['ACW'] > 0
          and out['spiral_ACW']['CW'] == 0 and out['rings']['CW'] + out['rings']['ACW'] == 0)
    print(json.dumps({'selftest': 'PASS' if ok else 'FAIL', **out}))
    return 0 if ok else 1

def main():
    if sys.stdout.isatty():  # the Scrolls look (AGENTS.md, terminal look rule); plain when piped
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
            from kit import termstyle
            termstyle.script()
        except ImportError:
            pass
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--m7', required=True); ap.add_argument('--line', required=True)
    ap.add_argument('--voxel-um', type=float, required=True); ap.add_argument('--pitch', type=float, required=True)
    ap.add_argument('--z-edges', required=True, help='z0,z1 (level 0); extra values are ignored except first and last')
    ap.add_argument('--planes', type=int, default=104); ap.add_argument('--mirror', action='store_true')
    ap.add_argument('--symmetric', action='store_true', help='add each plane\'s mirrored votes, flipped')
    ap.add_argument('--skip-z', default='', help='Z0-Z1[,Z0-Z1...] level-0 windows whose planes are dropped (reserved sites)')
    ap.add_argument('--quiet', action='store_true', help='print no per-plane votes and no call (sense-blind logs)')
    ap.add_argument('--min-votes', type=int, default=5); ap.add_argument('--min-share', type=float, default=0.8)
    ap.add_argument('--cache', help='directory for fetched planes (reused by z)'); ap.add_argument('--cache-tag', default='m7')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    ze = [float(v) for v in a.z_edges.split(',')]; line = load_line(a.line); s = 2 ** LEV
    zs = [int(z) for z in np.linspace(ze[0], ze[-1], a.planes + 2)[1:-1]]
    skip = [tuple(int(v) for v in w.split('-')) for w in a.skip_z.split(',') if w]
    dropped = [z for z in zs if any(lo <= z < hi for lo, hi in skip)]
    zs = [z for z in zs if z not in dropped]
    rows, t0 = [], time.time()
    for k, z in enumerate(zs):
        f = os.path.join(a.cache, f'{a.cache_tag}_L{LEV}_z{z}.npz') if a.cache else None
        if f and os.path.exists(f):
            d = np.load(f); img, o, c = d['img'], d['origin'], d['centre']
        else:
            img, o, c = fetch_plane(a.m7, line, z)
            if f: np.savez_compressed(f, img=img, origin=o, centre=c, lev=LEV)
        cx, cy = c[0] / s - o[0], c[1] / s - o[1]
        if a.mirror: img, cx = img[:, ::-1], img.shape[1] - 1 - cx
        ch = plane_chains(img, cx, cy, a.pitch / s)
        vs = [q['vote'] for q in ch]
        row = {'z': z, 'CW': vs.count('CW'), 'ACW': vs.count('ACW'), 'chains': ch}
        if a.symmetric:
            mch = plane_chains(img[:, ::-1], img.shape[1] - 1 - cx, cy, a.pitch / s)
            mv = [q['vote'] for q in mch]
            row.update(mirror_CW=mv.count('CW'), mirror_ACW=mv.count('ACW'), mirror_chains=mch)
            row['CW'], row['ACW'] = row['CW'] + row['mirror_ACW'], row['ACW'] + row['mirror_CW']
        rows.append(row)
        if rows[-1]['CW'] + rows[-1]['ACW'] and not a.quiet:
            print(f"{k + 1}/{len(zs)} z={z} CW={rows[-1]['CW']} ACW={rows[-1]['ACW']} {time.time() - t0:.0f}s", flush=True)
    cw, acw = sum(r['CW'] for r in rows), sum(r['ACW'] for r in rows); n = cw + acw
    call = 'abstain' if n < a.min_votes or max(cw, acw) / n < a.min_share else ('CW' if cw > acw else 'ACW')
    res = {'tool': 'slicechains', 'm7': a.m7, 'line': a.line, 'mirror': a.mirror, 'symmetric': a.symmetric,
           'planes': len(zs), 'skip_z': skip, 'planes_dropped': len(dropped),
           'rule': {'level': LEV, 'r_l0': R_L0, 'minlen': MINLEN, 'gap_pitch': GAP_F, 'lat_pitch': LAT_F,
                    'cos_min': COS_MIN, 'min_consistency': MIN_CONS, 'min_turns': MIN_TURNS,
                    'min_votes': a.min_votes, 'min_share': a.min_share, 'pitch': a.pitch, 'voxel_um': a.voxel_um},
           'totals': {'CW': cw, 'ACW': acw, 'planes_voting': sum(1 for r in rows if r['CW'] + r['ACW']),
                      'unvoting_wound_chains': sum(1 for r in rows for q in r['chains'] if q['vote'] is None)},
           'call': call, 'secs': round(time.time() - t0, 1), 'rows': rows}
    json.dump(res, open(a.out, 'w'))
    if a.quiet:
        print(json.dumps({'planes': len(zs), 'secs': res['secs'], 'out': a.out}))
    else:
        print(json.dumps({k: res[k] for k in ('mirror', 'planes', 'totals', 'call', 'secs')}))

if __name__ == '__main__':
    main()
