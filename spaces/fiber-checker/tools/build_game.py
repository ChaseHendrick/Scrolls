"""Build the pictures for Fiber Checker's "Fiber or not?" game: real surface renders from public scrolls on no prize
list, scanned in 2025 or later, read from the open data with the checker's own renderer.

  python3 tools/build_game.py [--per 24] [--out assets/game.npz]

Writes, for each patch, the render on the surface (the checker's frozen depth rule) and the render 5 voxels off the
traced surface on the far side, as 8-bit grey arrays on the on render's scale, with where each came from. The game
makes its other controls (scrambled, shuffled, blurred, noisy) from the on render as it plays. The file stays on the
Space only, never in git (docs/media/README.md).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
for p in (HERE, HERE.parent.parent / "scripts" / "fibercheck"):
    sys.path.insert(0, str(p))
import fibercat as C  # noqa: E402
import fibercheck as FC  # noqa: E402

# (sample, scan, segment): public scrolls on no prize list, scans from 2025 or later, the tested 2.2 to 2.4 um setting
SOURCES = [("PHerc0500P2", "20250526151718", "20250611171318"),
           ("PHerc0343P", "20260304131111", "20250902170447"),
           ("PHerc0139", "20260102150214", "20250108000005"),
           ("PHerc0009B", "20250820154339", "20250919064353"),
           ("PHerc0814", "20260309142202", "20250925161630")]


def to_u8(on, off):
    """Both renders as 8-bit grey on the on render's 0.5 and 99.5 percentile scale (small enough for the Space)."""
    lo, hi = np.percentile(on, [0.5, 99.5])
    scale = lambda a: np.round(np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8)  # noqa: E731
    return scale(on), scale(off)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--per", type=int, default=24, help="patches per segment")
    ap.add_argument("--out", type=Path, default=HERE / "assets" / "game.npz")
    a = ap.parse_args()
    on, off, src = [], [], []
    for sample, vol, seg in SOURCES:
        row = C.find(sample, seg, vol)
        assert not row["prize"] and row["tested"], row
        mesh = C.fetch_mesh(row)
        ct = FC.CT(row["ct"], row["level"], C.CACHE / "ct")
        pts, _, _ = FC.render_patches(mesh, ct, row["level"], 28, 5, max_patches=a.per, say=print)
        for p in pts:
            i = list(FC.DEPTHS).index(p["t0"])
            j = 0 if i >= len(FC.DEPTHS) // 2 else len(FC.DEPTHS) - 1        # the far end of the depth window
            o, f = to_u8(p["stack"][i], p["stack"][j])
            on.append(o)
            off.append(f)
            src.append(f"{sample} · scan {vol} · segment {seg} · patch r{p['r']} c{p['c']}")
        print(f"{sample}: {len(pts)} patches")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, on=np.stack(on), off=np.stack(off), src=np.array(src))
    print(f"wrote {len(on)} patches to {a.out} ({a.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
