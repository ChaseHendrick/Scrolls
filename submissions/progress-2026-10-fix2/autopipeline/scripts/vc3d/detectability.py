"""Would this window have shown ink, if there were any? Plant some and see.

A null result is ambiguous: "the model found nothing here" can mean blank papyrus, or a surface
off the sheet, a misplaced depth window, a coarse scan or a model out of its domain. This probe
settles it per window: add a synthetic ink layer of known contrast where ink would sit (on one
face of the sheet, a few voxels thick, following the measured sheet depth), run the same model
again, and report the smallest planted contrast whose strokes come back as ink (the "ink lift",
the rise in the fraction of stroke pixels above the threshold, clears a margin). None means the
window is blind, and its emptiness says nothing.

    python scripts/vc3d/detectability.py --self-test --out DIR
    python scripts/vc3d/detectability.py --stack RENDER --out DIR --micron-per-pixel 9.362 \\
        --engine villa --checkpoint CKPT.pth [--box y0,y1,x0,x1] [--face both] [--reverse]

Engines are those of scripts/vc3d/ink.py. The stack must be centred on the surface (as
vc_render_tifxyz renders it). Writes DIR/detectability.json.

Ported from axiosdevs/herculaneum-scroll-tools, `ink/detectability.py` (`sheet_depth`,
`script_mask`, `plant_ink`, `probe`) at commit 63a09d4, under the MIT License reproduced below.
Its caveats carry over and are the original author's measurements, not ours:

  * A sensitivity gained by preprocessing is not a sensitivity gained: smoothing a PHerc1451 stack
    made planted ink easier to find while agreement with PHerc0139's published map fell from
    0.858 to 0.448. Check any change that moves this number against a published reference.
  * It does not settle which way to read the layers. The original's `orientation` audit on 44
    published segments said forward on 12, reverse on 16 and nothing on 16, so it is not ported.
  * Ink must be planted on the face the model reads from; `--face both` plants on each in turn.
  * Above a contrast of about 32 the test can invert (a bright layer where the model expects bare
    papyrus reads as no ink), so a lift that falls at high amplitude is not a contradiction.

Changes from the original: `sheet_depth` no longer reads past the last layer of stacks of 25
layers or fewer; `probe` takes the baseline prediction so both faces share one model run.

    MIT License

    Copyright (c) 2026

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

SHEET_BAND = 6          # voxels either side of the sheet centre that count as its face
STROKE_MM = 0.35        # typical Herculaneum stroke width
LINE_MM = 2.0           # typical line spacing
AMPLITUDES = (4, 8, 16, 32)


def sheet_depth(stack, search=12):
    """Per-pixel depth of the sheet centre, from the stack's own brightness, over a band around the
    middle (the neighbouring windings are only a few hundred microns away)."""
    C = stack.shape[0]
    mid = (C - 1) / 2.0
    # the original's upper end, int(min(C, mid + search) + 1), runs one past the last layer when
    # C <= mid + search (25 layers or fewer) and the shapes below stop matching; C - 1 fixes that
    lo, hi = int(max(0, mid - search)), int(min(C - 1, mid + search) + 1)
    band = stack[lo:hi].astype(np.float32)
    depth = np.arange(lo, hi, dtype=np.float32)[:, None, None]
    base = np.percentile(band, 20, axis=0, keepdims=True)
    w = np.clip(band - base, 0, None)
    tot = w.sum(0)
    return np.where(tot > 1e-6, (w * depth).sum(0) / np.maximum(tot, 1e-6), mid)


def script_mask(shape, micron_per_pixel=2.401, seed=0):
    """A plausible page of writing: strokes of the right width, arranged in lines."""
    rng = np.random.default_rng(seed)
    h, w = shape
    stroke = max(2, int(round(STROKE_MM * 1000 / micron_per_pixel)))
    line = max(stroke * 3, int(round(LINE_MM * 1000 / micron_per_pixel)))
    mask = np.zeros(shape, np.float32)
    if h < line * 2 or w < stroke * 8:
        raise ValueError(f"a {h} x {w} px window is too small for the probe: with lines {LINE_MM} mm apart "
                         f"({line} px) not one line of strokes fits; give a larger box")
    for y in range(line, h - line, line):
        x = rng.integers(0, line)
        while x < w - stroke * 4:
            glyph_w = rng.integers(stroke * 2, stroke * 4)
            glyph_h = rng.integers(stroke * 2, stroke * 3)
            y0 = y + int(rng.integers(-stroke, stroke))
            if 0 <= y0 < h - glyph_h:
                # a hollow-ish mark: two verticals and a bar, closer to a letter than a blob
                mask[y0:y0 + glyph_h, x:x + stroke] = 1.0
                mask[y0:y0 + glyph_h, x + glyph_w - stroke:x + glyph_w] = 1.0
                mid = y0 + glyph_h // 2
                mask[mid:mid + stroke, x:x + glyph_w] = 1.0
            x += glyph_w + int(rng.integers(stroke, stroke * 3))
    return mask


def plant_ink(stack, amplitude, micron_per_pixel=2.401, seed=0, band=SHEET_BAND, face="near"):
    """Add a synthetic ink layer of the given contrast on one face of the sheet ('near' toward layer
    0, 'far' toward the last layer), following the measured sheet depth rather than a flat plane."""
    if face not in ("near", "far"):
        raise ValueError(f"face must be 'near' or 'far', not {face!r}")
    out = stack.astype(np.float32).copy()
    C, H, W = out.shape
    centre = sheet_depth(stack)
    mask = script_mask((H, W), micron_per_pixel, seed)
    at = centre - band / 2.0 if face == "near" else centre + band / 2.0
    zz = np.arange(C, dtype=np.float32)[:, None, None]
    profile = np.exp(-0.5 * ((zz - at[None]) / (band / 2.0)) ** 2)
    out += amplitude * profile * mask[None]
    return np.clip(out, 0, 255).astype(stack.dtype), mask


def probe(stack, predict_fn, amplitudes=AMPLITUDES, micron_per_pixel=2.401, seed=0, threshold=0.5, margin=0.05,
          face="near", base=None):
    """Smallest planted contrast this pipeline recovers on this window (`sensitivity`, None when
    blind), with one row per amplitude: the correlation of the change with the planted mask and the
    ink lift inside the strokes. `base`, the unplanted prediction, may be passed in to share it."""
    base = predict_fn(stack) if base is None else base
    rows = []
    sensitivity = None
    for amp in amplitudes:
        planted, mask = plant_ink(stack, amp, micron_per_pixel, seed, face=face)
        got = predict_fn(planted)
        delta = got.astype(np.float32) - base.astype(np.float32)
        m = mask.astype(bool)
        if m.sum() < 16 or (~m).sum() < 16:
            continue
        r = 0.0 if delta.std() < 1e-12 else float(np.corrcoef(delta.ravel(), mask.ravel())[0, 1])
        # the change planting caused, not inside-versus-outside on one map
        lift = float((got[m] > threshold).mean() - (base[m] > threshold).mean())
        rows.append({"amplitude": float(amp), "r_with_planted": round(r, 3), "ink_lift": round(lift, 3)})
        if sensitivity is None and lift >= margin:
            sensitivity = float(amp)
    return {"sensitivity": sensitivity, "baseline_ink_pct": round(float((base > threshold).mean()) * 100, 2),
            "rows": rows}


def probe_faces(stack, predict_fn, faces, **kw):
    """probe on each face, sharing one baseline prediction."""
    base = predict_fn(stack)
    out = {face: probe(stack, predict_fn, face=face, base=base, **kw) for face in faces}
    found = [out[f]["sensitivity"] for f in faces if out[f]["sensitivity"] is not None]
    return {"faces": out, "sensitivity": min(found) if found else None,
            "verdict": "sensitive" if found else "blind"}


# ---------------------------------------------------------------- self-test

def synthetic_stack(layers=21, size=256, seed=1):
    """A sheet centred on the middle layer, bright core and darker voids, with mild noise."""
    rng = np.random.default_rng(seed)
    z = np.arange(layers, dtype=np.float32)[:, None, None]
    sheet = 40 + 80 * np.exp(-0.5 * ((z - (layers - 1) / 2) / 2.5) ** 2)
    noise = rng.normal(0, 1.0, (layers, size, size)).astype(np.float32)
    return np.clip(sheet + noise, 0, 255).astype(np.uint8)


def face_detector(offset, slack):
    """A model that sees ink as extra brightness `offset` layers from the sheet centre, compared with
    the brightness there in the unplanted synthetic stack plus `slack`."""
    def predict(stack):
        c = (stack.shape[0] - 1) // 2
        x = stack[c + offset].astype(np.float32)
        ref = 40 + 80 * np.exp(-0.5 * (offset / 2.5) ** 2)
        return 1.0 / (1.0 + np.exp(-(x - ref - slack)))
    return predict


def self_test(micron_per_pixel=20.0):
    """The probe must find a near-face reader, call a constant model blind, and find a far-face reader
    only when planting on the far face. Each check can fail."""
    stack = synthetic_stack()
    kw = {"micron_per_pixel": micron_per_pixel, "amplitudes": AMPLITUDES}
    near = probe_faces(stack, face_detector(-3, 4.0), ("near",), **kw)
    blind = probe_faces(stack, lambda s: np.full(s.shape[1:], 0.1, np.float32), ("near", "far"), **kw)
    far_near_only = probe_faces(stack, face_detector(+3, 8.0), ("near",), **kw)
    far_both = probe_faces(stack, face_detector(+3, 8.0), ("near", "far"), **kw)
    checks = [
        ("near_reader_found", near["sensitivity"] is not None and near["sensitivity"] <= 16, near),
        ("constant_model_blind", blind["sensitivity"] is None, blind),
        ("far_reader_missed_on_near_face", far_near_only["sensitivity"] is None, far_near_only),
        ("far_reader_found_with_both_faces", far_both["faces"]["far"]["sensitivity"] is not None, far_both),
    ]
    rows = [{"check": name, "pass": bool(ok), "result": res} for name, ok, res in checks]
    return {"self_test": rows, "verdict": "PASS" if all(r["pass"] for r in rows) else "FAIL"}


# ---------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True)
    p.add_argument("--self-test", action="store_true", help="check the probe on synthetic detectors, no model")
    p.add_argument("--stack", help="surface volume (zarr or layer folder), centred on the surface")
    p.add_argument("--micron-per-pixel", type=float, help="pixel size in um")
    p.add_argument("--box", help="window y0,y1,x0,x1 (default: a central 512 px square, or the whole when smaller)")
    p.add_argument("--amplitudes", default=",".join(str(a) for a in AMPLITUDES))
    p.add_argument("--face", default="both", choices=("near", "far", "both"))
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--margin", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--reverse", action="store_true", help="the model reads the layers reversed")
    p.add_argument("--engine", choices=("villa", "torchscript", "v8in", "command"))
    p.add_argument("--checkpoint")
    p.add_argument("--model-dir")
    p.add_argument("--command-json")
    p.add_argument("--device", default="cpu")
    p.add_argument("--batch", type=int)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--stride", type=int)
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    if args.self_test:
        result = self_test()
    else:
        import ink
        if not (args.stack and args.engine and args.micron_per_pixel):
            p.error("--stack, --engine and --micron-per-pixel are needed (or --self-test)")
        try:
            engine = ink.make_engine(args)
            stack = ink.open_stack(args.stack)
            n, h, w = stack.shape
            if args.box:
                y0, y1, x0, x1 = (int(v) for v in args.box.split(","))
            else:
                side = min(512, h, w)
                y0, x0 = (h - side) // 2, (w - side) // 2
                y1, x1 = y0 + side, x0 + side
            a, b, box = ink.window(stack.shape, None, None, (y0, y1, x0, x1))
            data = ink.read_window(stack, a, b, box)
        except ink.InkError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        variant = "r" if args.reverse else "f"
        calls = [0]

        def predict(s):
            calls[0] += 1
            print(f"[detectability] model run {calls[0]}", flush=True)
            return engine.predict(s, variant)

        faces = ("near", "far") if args.face == "both" else (args.face,)
        amps = tuple(float(v) for v in args.amplitudes.split(","))
        try:
            result = probe_faces(data, predict, faces, amplitudes=amps, micron_per_pixel=args.micron_per_pixel,
                                 seed=args.seed, threshold=args.threshold, margin=args.margin)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        result.update(stack=str(args.stack), box=list(box), layers=n, reverse=args.reverse, engine=engine.describe(),
                      amplitudes=list(amps), threshold=args.threshold, margin=args.margin, model_runs=calls[0],
                      note="blind means a null here says nothing; sensitive says the window could show planted "
                           "strokes, not that the model is right about real ones")
    result["seconds"] = round(time.time() - started, 1)
    (out / "detectability.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ("verdict", "sensitivity") if k in result}), flush=True)
    return 0 if result.get("verdict") != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
