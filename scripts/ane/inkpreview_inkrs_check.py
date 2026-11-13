"""Check the inkrs backend of the ink preview server (inkpreview.py) against a whole inkrs map of the same layers.

One inkrs engine loads the model. The model's layers of a surface volume (a zarr, a folder of layer TIFFs, or a .npy
of shape (layers, rows, columns)) are read whole: the center crop of --window to the model depth, as a whole map
reads them. inkrs maps the whole canvas, forward and reversed. Then the preview server, in this process and in stack
mode as a viewer uses it (ask, upload the 409's need rectangle, ask again), is asked for views off the patch grid:
inside, on every edge and corner, after pans in four directions and on a diagonal, and reversed. Every view must equal
the whole map's pixels exactly. Two controls must differ from the whole map, so the check can fail: the view cut from
a window without the margin, and from the window shifted half a stride off the grid.

  python3 inkpreview_inkrs_check.py --model EXPORT.safetensors --segment SURFACE [--window FIRST,END]
          [--device auto] [--batch-size N] [--allow SCROLLS] [--view 1200,800] [--json OUT.json]

Prints one JSON report and exits 0 when every view is equal and both controls differ, 1 when not, 3 when the allow
list refuses the segment. It writes nothing but --json. A whole map is model output; here it is only the reference
for the tiling.
"""
import argparse, importlib.util, json, os, sys, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _sibling(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


ip = _sibling("inkpreview")


def read_layers(path, window, depth):
    """The model's layers of the surface volume at path, (depth, rows, columns) in forward order, and their indices."""
    if path.endswith(".npy"):
        arr = np.load(path, mmap_mode="r")
        order = ip.FC.slice_order(window or (0, arr.shape[0]), depth, "f")
        return np.ascontiguousarray(arr[[int(z) for z in order]]), order
    surf = ip.Surface(path)
    order = ip.FC.slice_order(window or (0, surf.shape[0]), depth, "f")
    return surf.window([int(z) for z in order], 0, surf.shape[1], 0, surf.shape[2]), order


def views(H, W, vw, vh, S):
    """(name, x, y, w, h, variant) views of a canvas H rows by W columns, each off the stride grid where it can be."""
    vw, vh = min(vw, W), min(vh, H)

    def cx(v):
        return int(min(max(v, 0), W - vw))

    def cy(v):
        return int(min(max(v, 0), H - vh))
    off = S // 2 + 5
    x0, y0 = cx((W - vw) // 2 + off), cy((H - vh) // 2 + off)
    d = S + S // 2 + 7
    return [("inside", x0, y0, vw, vh, "f"),
            ("pan right", cx(x0 + d), y0, vw, vh, "f"), ("pan down", cx(x0 + d), cy(y0 + d), vw, vh, "f"),
            ("pan left", cx(x0 - d), cy(y0 + d), vw, vh, "f"), ("pan up", cx(x0 - d), y0, vw, vh, "f"),
            ("pan diagonal", cx(x0 + 2 * d), cy(y0 - 2 * d), vw, vh, "f"),
            ("top edge", x0, 0, vw, vh, "f"), ("bottom edge", x0, H - vh, vw, vh, "f"),
            ("left edge", 0, y0, vw, vh, "f"), ("right edge", W - vw, y0, vw, vh, "f"),
            ("top left corner", 0, 0, vw, vh, "f"), ("top right corner", W - vw, 0, vw, vh, "f"),
            ("bottom left corner", 0, H - vh, vw, vh, "f"), ("bottom right corner", W - vw, H - vh, vw, vh, "f"),
            ("inside reversed", x0, y0, vw, vh, "r"), ("bottom right corner reversed", W - vw, H - vh, vw, vh, "r")]


def ask(pv, vol, key, x, y, w, h, variant):
    """What a viewer does: ask; on a 409 upload the need rectangle and ask again. (u8 view, tiles, need or None)."""
    H, W = vol.shape[1:]
    q = {"key": key, "cw": W, "ch": H, "x": x, "y": y, "w": w, "h": h, "variant": variant, "format": "u8"}
    q = {k: str(v) for k, v in q.items()}
    try:
        got, tiles, _ = pv.stack_request(q, b"")
        return got, tiles, None
    except ip.NeedStack as e:
        need = e.need
    nx, ny, nw, nh = need["x"], need["y"], need["w"], need["h"]
    q.update({"sx": str(nx), "sy": str(ny), "sw": str(nw), "sh": str(nh), "dtype": "uint8"})
    got, tiles, _ = pv.stack_request(q, np.ascontiguousarray(vol[:, ny:ny + nh, nx:nx + nw]).tobytes())
    return got, tiles, need


def compare(got, want):
    diff = np.abs(got.astype(np.int16) - want.astype(np.int16))
    return {"pixels": int(diff.size), "differ": int((diff > 0).sum()), "max_abs": int(diff.max()) if diff.size else 0}


def controls(pv, vol, full, x, y, w, h):
    """The view from a window without the margin, and from the right window shifted half a stride: each must differ
    from the whole map somewhere."""
    H, W = vol.shape[1:]
    P, S = pv.P, pv.stride
    out = []

    def bare(lo, hi, L):  # the cells under the view, on the grid, at least one patch long, no margin
        a, e = lo // S * S, min(-(-hi // S) * S, L)
        if e - a < P:
            e = min(a + P, L)
            a = max(0, e - P)
        return a, e
    ya, yb = bare(y, y + h, H)
    xa, xb = bare(x, x + w, W)
    m = pv.b.window(vol[:, ya:yb, xa:xb], False, S)
    out.append(dict(compare(m[y - ya:y - ya + h, x - xa:x - xa + w], full[y:y + h, x:x + w]),
                    name="window without the margin", window=[xa, ya, xb - xa, yb - ya]))
    ya, yb = ip.window_span(y // S * S, min(-(-(y + h) // S) * S, H), H, P, S)
    xa, xb = ip.window_span(x // S * S, min(-(-(x + w) // S) * S, W), W, P, S)
    t = S // 2

    def shift(a, e, L):
        return (a + t, min(e + t, L)) if e + t <= L or a - t < 0 else (a - t, e - t)
    ya, yb = shift(ya, yb, H)
    xa, xb = shift(xa, xb, W)
    m = pv.b.window(vol[:, ya:yb, xa:xb], False, S)
    r0, r1, c0, c1 = max(y, ya), min(y + h, yb), max(x, xa), min(x + w, xb)
    out.append(dict(compare(m[r0 - ya:r1 - ya, c0 - xa:c1 - xa], full[r0:r1, c0:c1]),
                    name="window shifted half a stride", window=[xa, ya, xb - xa, yb - ya]))
    return out


def build_parser():
    ap = argparse.ArgumentParser(description="Check the inkrs preview backend against a whole inkrs map")
    ap.add_argument("--model", required=True, help="inkrs export (.safetensors with its .json sidecar) or villa .pth")
    ap.add_argument("--segment", required=True, help="surface volume: zarr, folder of layer TIFFs, or .npy")
    ap.add_argument("--window", help="FIRST,END layers the center crop comes from (default all)")
    ap.add_argument("--device", choices=("auto", "mps", "cuda"), default="auto")
    ap.add_argument("--batch-size", type=int, metavar="N", help="tiles per forward (default inkrs's)")
    ap.add_argument("--allow", default=ip.DEFAULT_ALLOW, metavar="SCROLLS",
                    help="scroll ids the segment path must name, comma-separated; any: no restriction")
    ap.add_argument("--view", default="1200,800", metavar="W,H", help="view size in pixels (default 1200,800)")
    ap.add_argument("--json", help="also write the report here")
    return ap


def run(a):
    try:
        allow = ip.parse_allow(a.allow)
        ip.guard(ip.path_info(a.segment, allow))
    except ip.Refused as e:
        print("refused: %s" % e)
        return 3
    except ValueError as e:
        raise SystemExit("--allow: %s" % e)
    if allow is None:
        print("inkpreview_inkrs_check: no allow list: any segment may be checked (--allow SCROLLS restricts it)",
              file=sys.stderr, flush=True)
    vw, vh = (int(v) for v in a.view.split(","))
    win = tuple(int(v) for v in a.window.split(",")) if a.window else None
    t0 = time.time()
    b = ip.InkrsBackend(a.model, a.device, a.batch_size)
    pv = ip.Previewer(b, model_name=b.reader)
    load_s = time.time() - t0
    vol, order = read_layers(a.segment, win, b.depth)
    if vol.dtype != np.uint8:
        raise SystemExit("the surface volume is %s; inkrs reads uint8 only" % vol.dtype)
    D, H, W = vol.shape
    t0 = time.time()
    full = {"f": b.window(vol, False, pv.stride), "r": b.window(vol, True, pv.stride)}
    full_s = time.time() - t0
    rep = {"inkrs": b.info(), "patch": pv.P, "stride": pv.stride, "depth": D, "canvas": [H, W],
           "layers": [int(order[0]), int(order[-1])], "engine_load_s": round(load_s, 3),
           "whole_maps_s": round(full_s, 3), "views": [], "controls": []}
    for name, x, y, w, h, variant in views(H, W, vw, vh, pv.stride):
        t0 = time.time()
        got, tiles, need = ask(pv, vol, "check", x, y, w, h, variant)
        rep["views"].append(dict(compare(got, full[variant][y:y + h, x:x + w]), name=name, view=[x, y, w, h],
                                 variant=variant, need=need, cells=list(tiles), s=round(time.time() - t0, 3)))
    vx, vy, vw2, vh2 = rep["views"][0]["view"]
    rep["controls"] = controls(pv, vol, full["f"], vx, vy, vw2, vh2)
    rep["equal"] = all(v["differ"] == 0 for v in rep["views"])
    rep["controls_differ"] = all(c["differ"] > 0 for c in rep["controls"])
    rep["pass"] = rep["equal"] and rep["controls_differ"]
    text = json.dumps(rep, indent=1)
    print(text)
    if a.json:
        with open(a.json, "w") as fh:
            fh.write(text + "\n")
    return 0 if rep["pass"] else 1


def main(argv=None):
    if sys.stdout.isatty():  # styled terminal output where this repository's kit package is present
        try:
            sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))
            from kit import termstyle
            termstyle.script()
        except Exception:
            pass
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
