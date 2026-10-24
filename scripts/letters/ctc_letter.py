#!/usr/bin/env python3
"""The CTC line reader (kit.letterread.LineNet) on one letter or one line strip: the band it reads and the
one-letter label probability. Copied unchanged from the set A study script of 16 October (eval_set_a.py, not
published here), so the ICDAR head-to-head and the agent interface need no part of that study.

Model output: letter hypotheses, not a reading of any scroll.
"""
import numpy as np


def one_letter_logp(lp):
    """(K-1,) log P(label = that one letter) under CTC, blank index 0, every alignment blank* c+ blank*."""
    T, K = lp.shape
    c = lp[:, 1:]                                        # T x L
    b = lp[:, 0]
    s0 = b[0]                                            # blanks so far (scalar)
    s1 = c[0].copy()                                     # in the letter
    s2 = np.full(K - 1, -np.inf)                         # blanks after the letter
    for t in range(1, T):
        n2 = np.logaddexp(s2, s1) + b[t]
        n1 = np.logaddexp(s1, s0) + c[t]
        s0 = s0 + b[t]
        s1, s2 = n1, n2
    return np.logaddexp(s1, s2)


def band_of(ink, net, scale):
    from PIL import Image
    h = net.letter_px
    gh = max(2, int(round(ink.shape[0] * scale)))
    gw = max(1, int(round(ink.shape[1] * scale)))
    g = np.asarray(Image.fromarray(ink.astype(np.float32), mode="F").resize((gw, gh), Image.BILINEAR),
                   np.float32).clip(0, 1)
    rows = net.band_rows
    if gh > rows:                                        # taller than the band: keep its middle rows
        g = g[(gh - rows) // 2:(gh - rows) // 2 + rows]
        gh = rows
    band = np.zeros((rows, gw + 2 * h), np.float32)
    top = int(round(net.band[0] * h - gh / 2))
    top = min(max(top, 0), rows - gh)
    band[top:top + gh, h:h + gw] = g
    return band
