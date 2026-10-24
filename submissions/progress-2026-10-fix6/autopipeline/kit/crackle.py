"""crackle: Crackle Check's control-set gate (ink-lens-gate-v1) for kit and AutoPipeline (numpy only).

The same rule as the Crackle Check Space (a script of the source repository, released at
https://huggingface.co/spaces/SharpMeow/crackle-check), frozen in public Scrolls'
docs/prereg/2026-10-20-ink-lens-gate.md before any map of it existed:

- F and R are an ink map of a region with its layers as stored and reversed (the reverse-depth control).
- Papyrus: pixels whose middle CT layer is above the region's 5th percentile of CT and above 0.
- T is the 99th percentile of R over the papyrus. Excess: the share of papyrus pixels with F > T, divided by 0.01.
- Status: ink (the Space's answer Yes) at excess 3 or more, weak (Maybe) from 1.5 to 3, none (No signal found)
  below 1.5, too_small under 100,000 papyrus pixels, unreadable when a map is not finite, constant or identical to
  its control.

A region with no text, or where the model reads the reversed volume as well as the stored one, has an excess near 1:
the check can fail. The gate was checked on 640 px regions (the prereg's three PHerc0841 crops), so surface() judges a
whole surface in tiles of that size and reports the tiles beside the whole-surface gate. Everything it keeps is model
output, not a reading. A parity test in the source repository holds this module to the Space's gate.py.
"""

from __future__ import annotations

RULE_ID = "ink-lens-gate-v1"
CT_PERCENTILE = 5.0
CONTROL_PERCENTILE = 99.0
BASE_RATE = 0.01
INK_EXCESS = 3.0
WEAK_EXCESS = 1.5
MIN_PAPYRUS = 100_000
TILE_PX = 640                 # the region size the rule was checked at (the prereg's 640 px crops)
STATUSES = ("ink", "weak", "none", "too_small", "unreadable")
ANSWERS = {"ink": "Yes", "weak": "Maybe", "none": "No signal found", "too_small": "Too small",
           "unreadable": "Could not judge"}
SPACE = "https://huggingface.co/spaces/SharpMeow/crackle-check"
PREREG = "https://github.com/ChaseHendrick/Scrolls/blob/main/docs/prereg/2026-10-20-ink-lens-gate.md"
NOTE = ("Crackle Check's answer: is the model's ink signal stronger than the same model run on the layers reversed? "
        "A Yes is a place to look, not text; a No does not prove there is no ink. Model output, not a reading.")


class CrackleError(ValueError):
    """Maps the gate cannot take at all (wrong shapes, numpy missing); the message says why."""


def _np():
    try:
        import numpy as np
    except ImportError as exc:  # the core kit is standard library only
        raise CrackleError("numpy is required for kit crackle") from exc
    return np


def papyrus(ct_middle, percentile=CT_PERCENTILE):
    """Boolean mask of papyrus pixels: middle CT layer above its own percentile of the nonzero CT and above 0."""
    np = _np()
    ct = np.asarray(ct_middle)
    if ct.ndim != 2:
        raise CrackleError(f"the CT layer is 2-D, not {ct.shape}")
    nz = ct[ct > 0]
    if nz.size == 0:
        return np.zeros(ct.shape, bool)
    floor = max(float(np.percentile(ct, percentile)), 0.0)
    return ct > floor


def _unreadable(F, R, mask):
    np = _np()
    reasons = []
    for name, m in (("stored-order map", F), ("control map", R)):
        if not np.all(np.isfinite(m)):
            reasons.append(f"the {name} has values that are not finite")
        elif mask.any() and float(m[mask].max()) - float(m[mask].min()) < 1e-6:
            reasons.append(f"the {name} is constant on the papyrus")
    if not reasons and mask.any() and np.array_equal(F[mask], R[mask]):
        reasons.append("the stored-order map is identical to its control (a broken run, or the control was not run)")
    return reasons


def decide_mask(F, R, mask, min_papyrus=MIN_PAPYRUS):
    """The gate on one region given its papyrus mask: threshold, excess, status and counts, as a JSON-able dict."""
    np = _np()
    F = np.asarray(F, dtype=np.float32)
    R = np.asarray(R, dtype=np.float32)
    if F.shape != R.shape or F.ndim != 2:
        raise CrackleError(f"the map {F.shape} and its control {R.shape} must be 2-D and the same shape")
    if mask.shape != F.shape:
        raise CrackleError(f"the CT layer {mask.shape} and the maps {F.shape} differ in shape")
    n = int(mask.sum())
    out = {"rule": RULE_ID, "papyrus_px": n, "region_px": int(mask.size), "threshold": None, "excess": None,
           "forward_above": None, "control_above": None, "status": None}
    reasons = _unreadable(F, R, mask)
    if reasons:
        out.update(status="unreadable", reasons=reasons)
    elif n < min_papyrus:
        out.update(status="too_small")
    else:
        T = float(np.percentile(R[mask], CONTROL_PERCENTILE))
        f_above = float((F[mask] > T).mean())
        r_above = float((R[mask] > T).mean())
        excess = f_above / BASE_RATE
        status = "ink" if excess >= INK_EXCESS else "weak" if excess >= WEAK_EXCESS else "none"
        out.update(threshold=round(T, 6), excess=round(excess, 4), forward_above=round(f_above, 6),
                   control_above=round(r_above, 6), status=status)
    out["answer"] = ANSWERS[out["status"]]
    return out


def decide(F, R, ct_middle, min_papyrus=MIN_PAPYRUS):
    """The gate on one region (the Space's gate.decide, with its answer word added)."""
    return decide_mask(F, R, papyrus(ct_middle), min_papyrus)


def kept(F, decision, mask):
    """F where it passes the region's threshold on papyrus, else 0 (float32). Nothing passes unless the status is
    ink or weak."""
    np = _np()
    F = np.asarray(F, dtype=np.float32)
    out = np.zeros_like(F)
    if decision.get("status") not in ("ink", "weak"):
        return out
    m = mask & (F > float(decision["threshold"]))
    out[m] = F[m]
    return out


def to_u8(kept_map):
    """A kept map as uint8 for an overlay: 0 where nothing is kept (transparent in VC3D), else 1 to 255."""
    np = _np()
    k = np.asarray(kept_map, dtype=np.float32)
    out = np.zeros(k.shape, np.uint8)
    on = k > 0
    out[on] = np.clip(np.rint(k[on] * 254) + 1, 1, 255).astype(np.uint8)
    return out


def surface(F, R, ct_middle, tile=TILE_PX, min_papyrus=MIN_PAPYRUS):
    """A whole surface: the gate on all of it, and on each tile of `tile` px (row-major from the top left; the last
    row and column of tiles may be smaller). Returns (record, kept): kept is the uint8 overlay of every tile that
    passes (ink or weak), each by its own threshold. The papyrus mask is the surface's own, as one region."""
    np = _np()
    F = np.asarray(F, dtype=np.float32)
    R = np.asarray(R, dtype=np.float32)
    mask = papyrus(ct_middle)
    whole = decide_mask(F, R, mask, min_papyrus)
    k = np.zeros(F.shape, np.float32)
    rows, counts = [], {s: 0 for s in STATUSES}
    if whole["status"] != "unreadable":
        h, w = F.shape
        for y in range(0, h, tile):
            for x in range(0, w, tile):
                sl = (slice(y, y + tile), slice(x, x + tile))
                m = mask[sl]
                if not m.any():
                    continue                          # off the surface: not a tile
                d = decide_mask(F[sl], R[sl], m, min_papyrus)
                counts[d["status"]] += 1
                rows.append([y, x, d["status"], d["excess"]])
                if d["status"] in ("ink", "weak"):
                    k[sl] = kept(F[sl], d, m)
    judged = counts["ink"] + counts["weak"] + counts["none"]
    rec = {"whole": whole, "tile_px": tile, "tiles": counts, "tiles_judged": judged,
           "yes_share": round(counts["ink"] / judged, 4) if judged else None, "tile_list": rows}
    return rec, to_u8(k)
