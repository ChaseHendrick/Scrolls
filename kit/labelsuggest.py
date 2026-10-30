"""Where to paint ink labels next: tiles where readers' ink maps disagree, written as masks on the maps' grid.
`python -m kit labelsuggest`.

  kit labelsuggest map OUT MAP MAP [MAP ...] [--names A B ...] [--valid MASK] [--tile 64] [--top 20]
                   [--min-valid 0.5] [--seed 0] [--nulls 5] [--measure vote|rank|margin|edge] [--cut 0.5]
        score each pixel's disagreement among the readers (`--measure`, below), average it over a fixed grid of
        tiles, and write the `top` tiles as suggestions: OUT/suggest.json, label-suggestions.png (255 inside a
        suggested tile, 0 elsewhere), disagreement.png (the disagreement, 0 to 255) and the two control arms of the
        same size, random-tiles.png (matched random tiles) and agree-tiles.png (the tiles where the readers agree
        most). No label is read.

Why (Interpretation). Labeling time goes furthest where the current readers are least sure of the answer. Where
every reader agrees, a person's label mostly repeats what the models already say; where they disagree, at least
one of them is wrong, so a label there corrects someone. Whether that saves a person's time is untested: a
suggestion is a place to look, not a claim that the spot is mislabeled or holds ink.

Measures. `vote` (the default): each map is read as an ink probability (divided by its full scale: 1 when its
largest value is at most 1, else 255, else 65535), each reader votes ink where it reaches `cut`, and the
disagreement is 4 p (1 - p) for the share p of readers voting ink (0 when all agree, 1 at an even split): the
query-by-committee vote disagreement. `margin`: 1 - 2 |m - cut| for the readers' mean probability m (uncertainty
sampling on the committee mean). `edge`: 1 on every valid pixel where the committee call (m at or above `cut`)
differs from a valid 4-neighbor's, else 0, so a tile's score is its share of committee ink edge. `rank`: version
1's measure, below, kept for the record; it is drawn to the low-valued background, where each reader's noise
orders pixels differently, so it is not the default.

Rank normalization (`--measure rank`). Readers write maps in different ranges and dtypes (uint8, uint16, float).
Each map is replaced by its mid-rank inside the valid pixels, scaled to 0..1, so a reader's scale or monotone
calibration does not change anything, and tied values (uint8 maps hold many) share one rank instead of being split
at random. With K readers the spread at a pixel is the population standard deviation of its K ranks (0 when all
agree, at most 0.5).

The structure control (it can fail). Disagreement can be high everywhere for uninteresting reasons (independent
noise in each map). The command shuffles the disagreement's valid pixels `nulls` times, which keeps its
distribution and destroys where it lies, and rescores the tiles: the suggestion is `targeted` only when the mean of
the top tiles beats the largest such mean over the shuffles; otherwise it is `flat` and the suggestions are no
better than random spots.

Model output: every map is a reader's output and the disagreement is arithmetic on them. Nothing here is a reading,
and a suggested tile says nothing about whether ink is there.

Standard library plus numpy; tifffile reads TIFF maps; PNG (kit.vc3d_io) and .npy maps need nothing more.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

VERSION = 2
VERSIONS = (1, 2)          # records load_result accepts; version 1 is the rank measure only
DEFAULTS = {"tile": 64, "top": 20, "min_valid": 0.5, "seed": 0, "nulls": 5, "measure": "vote", "cut": 0.5}
MEASURES = ("vote", "rank", "margin", "edge")
NOTE = ("Model output: disagreement among released readers' maps, by the chosen measure (vote by default; rank is "
        "version 1's rank spread). A suggested tile is a place to paint labels, not a reading and not a claim about "
        "ink.")
OUT_FILES = {"suggest": "label-suggestions.png", "disagreement": "disagreement.png", "random": "random-tiles.png",
             "agree": "agree-tiles.png", "json": "suggest.json"}


class SuggestError(ValueError):
    pass


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise SuggestError("kit labelsuggest needs numpy") from exc
    return np


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _digest(obj):
    return hashlib.sha256(_canonical(obj).encode()).hexdigest()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- reading and writing images

def load_map(path):
    """A 2D float32 array from a TIFF, PNG or .npy file (the first page or channel of anything with more)."""
    np = _np()
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".npy":
        a = np.load(p)
    elif suf == ".png":
        from . import vc3d_io
        h, w, ch, data = vc3d_io.read_png_gray(p.read_bytes())
        a = np.frombuffer(data, np.uint8).reshape(h, w, ch)[..., 0]
    elif suf in (".tif", ".tiff"):
        try:
            import tifffile
        except ImportError as exc:  # pragma: no cover
            raise SuggestError("reading TIFF maps needs tifffile") from exc
        a = tifffile.imread(str(p))
    else:
        raise SuggestError(f"{p}: read .tif, .tiff, .png or .npy maps")
    a = np.asarray(a)
    if a.ndim == 3:
        a = a[..., 0] if a.shape[-1] in (3, 4) else a[0]     # RGB(A): the first channel; a stack: its first page
    if a.ndim != 2:
        raise SuggestError(f"{p}: not a 2D map (shape {a.shape})")
    return a.astype(np.float32)


def _write_png(path, a):
    """Write a uint8 grey PNG with kit.vc3d_io (no Pillow needed)."""
    np = _np()
    from . import vc3d_io
    a = np.ascontiguousarray(a, dtype=np.uint8)
    Path(path).write_bytes(vc3d_io.png_bytes(a.shape[0], a.shape[1], a.tobytes(), 1))


# ---------------------------------------------------------------- the spread and the tiles

def _default_valid(maps):
    """Pixels finite in every map and not zero in all of them (a render's empty margin is zero everywhere)."""
    np = _np()
    fin = np.all([np.isfinite(m) for m in maps], axis=0)
    some = np.any([np.nan_to_num(m) != 0 for m in maps], axis=0)
    return fin & some


def midranks(a, valid):
    """Each valid pixel's mid-rank among the valid pixels, scaled to 0..1 (ties share their mean rank); 0 elsewhere."""
    np = _np()
    out = np.zeros(a.shape, np.float32)
    v = a[valid]
    n = v.size
    if n < 2:
        return out
    uniq, inv, counts = np.unique(v, return_inverse=True, return_counts=True)
    before = np.concatenate([[0], np.cumsum(counts)[:-1]])
    mid = (before + (counts - 1) / 2.0) / (n - 1)
    out[valid] = mid[inv.reshape(-1)].astype(np.float32)
    return out


def spread(maps, valid):
    """Per-pixel population standard deviation of the readers' mid-ranks (0 outside valid), and the ranks."""
    np = _np()
    ranks = np.stack([midranks(m, valid) for m in maps])
    s = ranks.std(axis=0).astype(np.float32)
    s[~valid] = 0.0
    return s, ranks


def value_scale(top):
    """The value rule: the full scale implied by a map's largest value (1 when at most 1, else 255, else 65535),
    or None when it reaches past 65535."""
    top = float(top)
    if top <= 1.0:
        return 1.0
    if top <= 255.0:
        return 255.0
    if top <= 65535.0:
        return 65535.0
    return None


def full_scale(a, valid):
    """The map value that means probability 1: 1 when the largest valid value is at most 1, else 255, else 65535."""
    np = _np()
    v = a[valid]
    top = float(np.nanmax(v)) if v.size else 0.0
    s = value_scale(top)
    if s is None:
        raise SuggestError(f"a map's values reach {top}: give probabilities (0..1, uint8 or uint16), or use "
                           "--measure rank")
    return s


def disagreement(maps, valid, measure="vote", cut=0.5):
    """Per-pixel disagreement among the readers (0 outside valid) under `measure`, and each map's full scale
    (None for rank). vote: 4 p (1 - p), p the share of readers whose probability reaches cut; margin: 1 - 2 |m -
    cut| (clipped at 0) for the mean probability m; edge: 1 on the committee call's ink edge; rank: version 1's
    spread of mid-ranks (0 to 0.5)."""
    np = _np()
    if measure not in MEASURES:
        raise SuggestError(f"measure must be one of {', '.join(MEASURES)}")
    if measure == "rank":
        s, _ = spread(maps, valid)
        return s, None
    if not 0 < float(cut) < 1:
        raise SuggestError("cut must lie strictly between 0 and 1")
    scales = [full_scale(m, valid) for m in maps]
    probs = np.stack([np.nan_to_num(m) / f for m, f in zip(maps, scales)]).astype(np.float32)
    if measure == "vote":
        p = (probs >= float(cut)).mean(axis=0)
        s = 4.0 * p * (1.0 - p)
    elif measure == "edge":
        s = ink_edge(probs.mean(axis=0) >= float(cut), valid)
    else:
        s = np.clip(1.0 - 2.0 * np.abs(probs.mean(axis=0) - float(cut)), 0.0, 1.0)
    s = s.astype(np.float32)
    s[~valid] = 0.0
    return s, scales


def ink_edge(call, valid):
    """1 where the call differs from a 4-neighbor, both pixels valid, else 0 (the `edge` measure)."""
    np = _np()
    e = np.zeros(call.shape, bool)
    d = (call[:-1, :] != call[1:, :]) & valid[:-1, :] & valid[1:, :]
    e[:-1, :] |= d
    e[1:, :] |= d
    d = (call[:, :-1] != call[:, 1:]) & valid[:, :-1] & valid[:, 1:]
    e[:, :-1] |= d
    e[:, 1:] |= d
    return e.astype(np.float32)


def tile_scores(s, valid, tile, min_valid):
    """[(y, x, mean spread over its valid pixels, valid share)] for every tile with at least min_valid valid."""
    np = _np()
    H, W = s.shape
    nh, nw = H // tile, W // tile
    if nh == 0 or nw == 0:
        raise SuggestError(f"map {W} x {H} is smaller than one {tile} px tile")
    crop = (slice(0, nh * tile), slice(0, nw * tile))
    vs = valid[crop].reshape(nh, tile, nw, tile).sum(axis=(1, 3))
    ss = s[crop].reshape(nh, tile, nw, tile).sum(axis=(1, 3), dtype=np.float64)
    share = vs / float(tile * tile)
    rows = []
    for i in range(nh):
        for j in range(nw):
            if share[i, j] >= min_valid and vs[i, j] > 0:
                rows.append((i * tile, j * tile, float(ss[i, j] / vs[i, j]), float(share[i, j])))
    return rows


def _pick_top(rows, k):
    """The k tiles with the highest spread; ties go to the earlier tile (row-major), so the pick is deterministic."""
    return sorted(rows, key=lambda r: (-r[2], r[0], r[1]))[:k]


def _pick_agree(rows, k):
    return sorted(rows, key=lambda r: (r[2], r[0], r[1]))[:k]


def _pick_random(rows, k, seed):
    np = _np()
    if not rows:
        return []
    idx = np.random.default_rng(seed).choice(len(rows), size=min(k, len(rows)), replace=False)
    return [rows[i] for i in sorted(int(i) for i in idx)]


def _structure(s, valid, tile, min_valid, k, nulls, seed):
    """The shuffle control: top-k mean spread against the same after shuffling the valid pixels (see the doc)."""
    np = _np()
    rows = tile_scores(s, valid, tile, min_valid)
    top = _pick_top(rows, k)
    observed = float(np.mean([r[2] for r in top])) if top else 0.0
    rng = np.random.default_rng(seed + 1)
    vals = s[valid]
    null = []
    for _ in range(nulls):
        sh = np.zeros_like(s)
        sh[valid] = rng.permutation(vals)
        nt = _pick_top(tile_scores(sh, valid, tile, min_valid), k)
        null.append(float(np.mean([r[2] for r in nt])) if nt else 0.0)
    worst = max(null) if null else None
    targeted = bool(null) and observed > worst
    return {"top_mean_spread": round(observed, 6), "null_top_means": [round(v, 6) for v in null],
            "null_max": None if worst is None else round(worst, 6), "nulls": nulls,
            "verdict": "targeted" if targeted else ("flat" if null else "unchecked"),
            "rule": "targeted when the top tiles' mean spread beats every pixel-shuffled null; otherwise flat"}


def _tiles_json(rows, tile):
    return [{"rank": i + 1, "y": y, "x": x, "h": tile, "w": tile, "spread": round(sc, 6), "valid_share": round(sh, 4)}
            for i, (y, x, sc, sh) in enumerate(rows)]


def _mask_of(shape, tiles):
    np = _np()
    m = np.zeros(shape, np.uint8)
    for t in tiles:
        m[t["y"]:t["y"] + t["h"], t["x"]:t["x"] + t["w"]] = 255
    return m


def suggest(maps, names=None, valid=None, tile=None, top=None, min_valid=None, seed=None, nulls=None,
            measure=None, cut=None):
    """Suggestions from in-memory maps (same shape). Returns (result dict, spread array, valid mask)."""
    np = _np()
    cfg = dict(DEFAULTS)
    for k, v in (("tile", tile), ("top", top), ("min_valid", min_valid), ("seed", seed), ("nulls", nulls),
                 ("measure", measure), ("cut", cut)):
        if v is not None:
            cfg[k] = v
    if len(maps) < 2:
        raise SuggestError("disagreement needs at least two readers' maps")
    shapes = {tuple(m.shape) for m in maps}
    if len(shapes) != 1:
        raise SuggestError(f"maps differ in shape {sorted(shapes)}: put every reader on one grid first")
    if int(cfg["tile"]) < 4 or int(cfg["top"]) < 1 or not 0 < float(cfg["min_valid"]) <= 1 or int(cfg["nulls"]) < 0:
        raise SuggestError("tile >= 4, top >= 1, 0 < min_valid <= 1 and nulls >= 0")
    names = list(names or [f"reader{i + 1}" for i in range(len(maps))])
    if len(names) != len(maps) or len(set(names)) != len(names):
        raise SuggestError("one distinct name per map")
    maps = [np.asarray(m, np.float32) for m in maps]
    valid = _default_valid(maps) if valid is None else (np.asarray(valid) != 0) & _default_valid(maps)
    s, scales = disagreement(maps, valid, cfg["measure"], cfg["cut"])
    tile_, k = int(cfg["tile"]), int(cfg["top"])
    rows = tile_scores(s, valid, tile_, float(cfg["min_valid"]))
    top_rows = _pick_top(rows, k)
    res = {
        "kind": "kit-labelsuggest", "version": VERSION, "readers": names, "shape": list(maps[0].shape),
        "settings": cfg, "settings_digest": _digest({"version": VERSION, **cfg}),
        "full_scales": scales, "valid_pixels": int(valid.sum()), "tiles_eligible": len(rows),
        "top": _tiles_json(top_rows, tile_),
        "controls": {"random": _tiles_json(_pick_random(rows, len(top_rows), int(cfg["seed"])), tile_),
                     "agree": _tiles_json(_pick_agree(rows, len(top_rows)), tile_)},
        "structure": _structure(s, valid, tile_, float(cfg["min_valid"]), k, int(cfg["nulls"]), int(cfg["seed"])),
        "note": NOTE,
    }
    return res, s, valid


def run_map(out, paths, names=None, valid_path=None, **cfg):
    """`kit labelsuggest map`: read the maps, suggest, write OUT's files. Returns the result dict."""
    t0 = time.time()
    out = Path(out)
    paths = [Path(p) for p in paths]
    maps = [load_map(p) for p in paths]
    names = list(names) if names else [p.parent.name + "/" + p.stem if p.stem in ("map", "default", "prediction")
                                       else p.stem for p in paths]
    valid = load_map(valid_path) if valid_path else None
    res, s, valid_m = suggest(maps, names=names, valid=valid, **cfg)
    res["inputs"] = [{"name": n, "path": str(p), "sha256": _sha256(p)} for n, p in zip(names, paths)]
    if valid_path:
        res["valid_mask"] = {"path": str(valid_path), "sha256": _sha256(valid_path)}
    out.mkdir(parents=True, exist_ok=True)
    shape = tuple(res["shape"])
    _write_png(out / OUT_FILES["suggest"], _mask_of(shape, res["top"]))
    _write_png(out / OUT_FILES["random"], _mask_of(shape, res["controls"]["random"]))
    _write_png(out / OUT_FILES["agree"], _mask_of(shape, res["controls"]["agree"]))
    np = _np()
    gain = 510.0 if res["settings"]["measure"] == "rank" else 255.0     # rank spread tops out at 0.5
    _write_png(out / OUT_FILES["disagreement"], np.clip(np.rint(s * gain), 0, 255))
    res["files"] = {k: str(out / v) for k, v in OUT_FILES.items() if k != "json"}
    res["seconds"] = round(time.time() - t0, 2)
    (out / OUT_FILES["json"]).write_text(json.dumps(res, indent=1) + "\n")
    return res


def load_result(path):
    """A suggest.json record, checked for its kind and version."""
    p = Path(path)
    try:
        res = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SuggestError(f"{p}: not a readable suggest.json ({exc})") from exc
    if res.get("kind") != "kit-labelsuggest" or res.get("version") not in VERSIONS:
        raise SuggestError(f"{p}: not a kit labelsuggest record of version {' or '.join(map(str, VERSIONS))}")
    return res


# ---------------------------------------------------------------- command line

def build_parser(p):
    """Add the `map` action to an argparse parser."""
    sub = p.add_subparsers(dest="labelsuggest_cmd", required=True)
    m = sub.add_parser("map", help="suggest tiles where readers disagree; write the masks and suggest.json")
    m.add_argument("out", help="output folder (created): suggest.json and the PNG masks")
    m.add_argument("maps", nargs="+", help="two or more readers' maps on one grid (.tif, .png, .npy)")
    m.add_argument("--names", nargs="+", help="one name per map (default: file stems)")
    m.add_argument("--valid", help="mask of pixels to consider (nonzero = valid)")
    m.add_argument("--tile", type=int, default=DEFAULTS["tile"], help="tile side in map pixels")
    m.add_argument("--top", type=int, default=DEFAULTS["top"], help="tiles to suggest")
    m.add_argument("--min-valid", type=float, default=DEFAULTS["min_valid"],
                   help="least share of valid pixels for a tile to count")
    m.add_argument("--seed", type=int, default=DEFAULTS["seed"], help="seed of the random arm and the shuffles")
    m.add_argument("--nulls", type=int, default=DEFAULTS["nulls"], help="pixel shuffles of the structure control")
    m.add_argument("--measure", choices=MEASURES, default=DEFAULTS["measure"],
                   help="vote: share of readers voting ink, 4p(1-p); margin: committee mean near the cut; edge: share "
                        "of committee ink edge pixels; rank: version 1's rank spread")
    m.add_argument("--cut", type=float, default=DEFAULTS["cut"], help="ink probability cut of vote, margin and edge")
    m.add_argument("--json", action="store_true", help="print the whole record")


def cmd_labelsuggest(a):
    """Run the parsed action; 0 done, 2 an input problem (the message is on stderr)."""
    try:
        res = run_map(a.out, a.maps, names=a.names, valid_path=a.valid, tile=a.tile, top=a.top,
                      min_valid=a.min_valid, seed=a.seed, nulls=a.nulls, measure=a.measure, cut=a.cut)
    except SuggestError as exc:
        print(f"labelsuggest: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        st = res["structure"]
        print(f"{len(res['top'])} tiles of {res['tiles_eligible']} suggested; structure {st['verdict']} "
              f"(top mean spread {st['top_mean_spread']}, shuffled max {st['null_max']}); "
              f"{Path(a.out) / OUT_FILES['json']}")
    return 0


def main(argv=None):
    """`python -m kit.labelsuggest`."""
    p = argparse.ArgumentParser(prog="python -m kit labelsuggest", description=__doc__.split("\n\n")[0])
    build_parser(p)
    return cmd_labelsuggest(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
