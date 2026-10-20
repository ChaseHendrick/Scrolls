"""Ink Lens: the control-set threshold and the region status (numpy only).

The rule, frozen in docs/prereg/2026-10-20-ink-lens-gate.md before any map of it existed:

- F and R are the mean ink probabilities (0 to 1) of the region with its layers as stored and reversed, each averaged
  over the same depth windows and readers.
- Papyrus: pixels whose middle CT layer is above the region's 5th percentile of CT and above 0 (so air and the
  masked outside of a segment do not lower the threshold).
- T is the 99th percentile of R over the papyrus pixels: the level that only 1 % of the control's own pixels pass.
- Kept ink: papyrus pixels with F > T. Excess: the fraction of papyrus pixels with F > T, divided by 0.01.
- Status: ink when excess >= 3, weak when 1.5 <= excess < 3, none below 1.5, too_small under 100,000 papyrus pixels
  (about 3 mm square at 9.6 um), unreadable when a map is not finite, constant, or identical to its control.

A region with no text, or where the model reads the reversed volume as well as the stored one, has an excess near 1
and the status none: the check can fail. Everything it keeps is model output, not a reading.
"""

from __future__ import annotations

RULE_ID = "ink-lens-gate-v1"
CT_PERCENTILE = 5.0
CONTROL_PERCENTILE = 99.0
BASE_RATE = 0.01
INK_EXCESS = 3.0
WEAK_EXCESS = 1.5
MIN_PAPYRUS = 100_000
STATUSES = ("ink", "weak", "none", "too_small", "unreadable")
STATUS_TEXT = {
    "ink": "ink above the control: at least 3 times as many pixels pass the control's 99th percentile as the control",
    "weak": "some ink above the control: 1.5 to 3 times the control's share; look before trusting it",
    "none": "no ink above the control: the stored order passes the control's 99th percentile no more than 1.5 times "
            "as often as the control itself",
    "too_small": "too little papyrus in the region to judge (under 100,000 pixels, about 3 mm square)",
    "unreadable": "the maps cannot be judged (not finite, constant, or the same as the control)",
}


class GateError(ValueError):
    """Maps the gate cannot take at all (wrong shapes); the message says why."""


def papyrus(ct_middle, percentile=CT_PERCENTILE):
    """Boolean mask of papyrus pixels in a region: middle CT layer above its own percentile and above 0."""
    import numpy as np
    ct = np.asarray(ct_middle)
    if ct.ndim != 2:
        raise GateError(f"the CT layer is 2-D, not {ct.shape}")
    nz = ct[ct > 0]
    if nz.size == 0:
        return np.zeros(ct.shape, bool)
    floor = max(float(np.percentile(ct, percentile)), 0.0)
    return ct > floor


def _unreadable(F, R, mask):
    import numpy as np
    reasons = []
    for name, m in (("stored-order map", F), ("control map", R)):
        if not np.all(np.isfinite(m)):
            reasons.append(f"the {name} has values that are not finite")
        elif mask.any() and float(m[mask].max()) - float(m[mask].min()) < 1e-6:
            reasons.append(f"the {name} is constant on the papyrus")
    if not reasons and mask.any() and np.array_equal(F[mask], R[mask]):
        reasons.append("the stored-order map is identical to its control (a broken run, or the control was not run)")
    return reasons


def decide(F, R, ct_middle, min_papyrus=MIN_PAPYRUS):
    """The gate on one region: threshold, excess, status and counts, as a JSON-able dict."""
    import numpy as np
    F = np.asarray(F, dtype=np.float32)
    R = np.asarray(R, dtype=np.float32)
    if F.shape != R.shape or F.ndim != 2:
        raise GateError(f"the map {F.shape} and its control {R.shape} must be 2-D and the same shape")
    mask = papyrus(ct_middle)
    if mask.shape != F.shape:
        raise GateError(f"the CT layer {mask.shape} and the maps {F.shape} differ in shape")
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
    out["status_text"] = STATUS_TEXT[out["status"]]
    out["note"] = "Model output, not a reading."
    return out


def kept(F, decision, ct_middle):
    """F where it passes the control's threshold on papyrus, else 0 (float32). Nothing passes unless the status is
    ink or weak."""
    import numpy as np
    F = np.asarray(F, dtype=np.float32)
    out = np.zeros_like(F)
    if decision.get("status") not in ("ink", "weak"):
        return out
    m = papyrus(ct_middle) & (F > float(decision["threshold"]))
    out[m] = F[m]
    return out


def to_u8(kept_map):
    """The kept map as uint8 for an overlay: 0 where nothing is kept (transparent in VC3D), else 1 to 255."""
    import numpy as np
    k = np.asarray(kept_map, dtype=np.float32)
    out = np.zeros(k.shape, np.uint8)
    on = k > 0
    out[on] = np.clip(np.rint(k[on] * 254) + 1, 1, 255).astype(np.uint8)
    return out


def label_shares(kept_map, ink, supervised, inner=64):
    """The preregistered label check: the share of labeled ink pixels kept and the share of labeled background
    pixels kept, inside the supervision mask with an inner edge left out."""
    import numpy as np
    k = np.asarray(kept_map) > 0
    m = np.asarray(supervised, bool).copy()
    if inner:
        m[:inner] = m[-inner:] = False
        m[:, :inner] = m[:, -inner:] = False
    ink = np.asarray(ink, bool)
    ink_px, bg_px = int((m & ink).sum()), int((m & ~ink).sum())
    ink_share = float((k & m & ink).sum()) / ink_px if ink_px else None
    bg_share = float((k & m & ~ink).sum()) / bg_px if bg_px else None
    passes = None if ink_share is None or bg_share is None else ink_share > bg_share
    return {"ink_px": ink_px, "background_px": bg_px, "ink_kept_share": None if ink_share is None else round(ink_share, 5),
            "background_kept_share": None if bg_share is None else round(bg_share, 5), "ink_share_larger": passes,
            "inner": inner}
