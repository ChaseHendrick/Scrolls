"""Letter language model for Greek written in scriptio continua (24 capitals, no spaces).

Interpolated Kneser-Ney over letter n-grams (default order 5), built from TEI XML texts such as
PerseusDL/canonical-greekLit (https://github.com/PerseusDL/canonical-greekLit, CC BY-SA 4.0). It is
a prior over letter strings for decoding: it never sees an image, and kit/letterread.py always
reports the ink-only decode next to any decode that uses it. Keep texts you evaluate on out of
the training corpus (for Herculaneum work: leave Philodemus out), or the language model will
recite them.

Model files (.npz) hold n-gram counts derived from those editions; keep them out of git and
rebuild them with `python -m kit greeklm build`.
"""

import json
import math
import re
import unicodedata
from pathlib import Path

import numpy as np

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
_IDX = {c: i for i, c in enumerate(ALPHABET)}


def clean_text(s):
    """Accents and breathings dropped, capitals, lunate sigma, letters only (spaces and punctuation removed)."""
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if not unicodedata.combining(c)).upper()
    d = d.replace("Σ", "Ϲ").replace("ς", "Ϲ")
    return "".join(c for c in d if c in _IDX)


def tei_text(xml):
    """Body text of a TEI file with notes, apparatus and headers removed."""
    xml = re.sub(r"<teiHeader.*?</teiHeader>", " ", xml, flags=re.S)
    for tag in ("note", "bibl", "head", "app", "rdg", "del", "speaker", "ref", "foreign"):
        xml = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", xml, flags=re.S)
    xml = re.sub(r"<[^>]+>", " ", xml)
    return re.sub(r"&[a-z]+;", " ", xml)


class KNLetterLM:
    def __init__(self, order=5, discount=0.75):
        self.order = order
        self.D = discount
        self.counts = [dict() for _ in range(order + 1)]     # counts[n][context] -> np.array(24)
        self.cont = [dict() for _ in range(order + 1)]       # continuation counts for lower orders
        self._cache = {}

    def fit(self, texts):
        for t in texts:
            s = [_IDX[c] for c in t if c in _IDX]
            for n in range(1, self.order + 1):
                C = self.counts[n]
                for i in range(n - 1, len(s)):
                    ctx = tuple(s[i - n + 1:i])
                    v = C.get(ctx)
                    if v is None:
                        v = C[ctx] = np.zeros(24, np.float64)
                    v[s[i]] += 1
        # continuation counts: number of distinct left extensions of (ctx, w)
        for n in range(1, self.order):
            K = self.cont[n]
            for ctx, v in self.counts[n + 1].items():
                low = ctx[1:]
                u = K.get(low)
                if u is None:
                    u = K[low] = np.zeros(24, np.float64)
                u += v > 0
        self._cache = {}
        return self

    def _p(self, ctx, n):
        """P(. | last n-1 letters of ctx) as a 24-vector."""
        if n == 0:
            return np.full(24, 1.0 / 24)
        key = (ctx[len(ctx) - (n - 1):] if n > 1 else (), n)
        if key in self._cache:
            return self._cache[key]
        c = key[0]
        table = self.counts[n] if n == self.order else self.cont[n]
        v = table.get(c)
        lower = self._p(ctx, n - 1)
        if v is None or v.sum() == 0:
            p = lower
        else:
            tot = v.sum()
            nz = (v > 0).sum()
            p = np.maximum(v - self.D, 0) / tot + (self.D * nz / tot) * lower
        if len(self._cache) < 2_000_000:
            self._cache[key] = p
        return p

    def logp_next(self, prefix):
        ctx = tuple(_IDX[c] for c in prefix[-(self.order - 1):] if c in _IDX) if self.order > 1 else ()
        n = min(self.order, len(ctx) + 1)
        return np.log(self._p(ctx, n))

    def score(self, text):
        """Total log-probability (nats) of a letter string."""
        tot = 0.0
        for i, c in enumerate(text):
            tot += float(self.logp_next(text[:i])[_IDX[c]])
        return tot

    def bits_per_letter(self, text):
        return -self.score(text) / max(1, len(text)) / math.log(2)

    def sample(self, rng, n, prefix=""):
        s = prefix
        for _ in range(n):
            p = np.exp(self.logp_next(s))
            s += ALPHABET[int(rng.choice(24, p=p / p.sum()))]
        return s[len(prefix):]

    def save(self, path):
        arrs, meta = {}, {"order": self.order, "D": self.D, "tables": []}
        for kind, T in (("counts", self.counts), ("cont", self.cont)):
            for n, d in enumerate(T):
                if not d:
                    continue
                keys = np.array([list(k) + [-1] * (self.order - len(k)) for k in d], np.int8).reshape(len(d), self.order)
                vals = np.stack(list(d.values())).astype(np.float32)
                arrs[f"{kind}{n}_k"], arrs[f"{kind}{n}_v"] = keys, vals
                meta["tables"].append([kind, n])
        np.savez_compressed(path, meta=np.array(json.dumps(meta)), **arrs)

    @classmethod
    def load(cls, path):
        z = np.load(path)
        meta = json.loads(str(z["meta"]))
        lm = cls(meta["order"], meta["D"])
        for kind, n in meta["tables"]:
            keys, vals = z[f"{kind}{n}_k"], z[f"{kind}{n}_v"].astype(np.float64)
            T = getattr(lm, kind)[n]
            for k, v in zip(keys, vals):
                T[tuple(int(x) for x in k if x >= 0)] = v
        return lm


def build(xml_files, order=5, holdout_every=20):
    """Fit on TEI files; every holdout_every-th 2,000-letter chunk is held out for bits-per-letter."""
    train, held = [], []
    for f in xml_files:
        t = clean_text(tei_text(Path(f).read_text(encoding="utf-8", errors="replace")))
        for i in range(0, len(t), 2000):
            (held if (i // 2000) % holdout_every == holdout_every - 1 else train).append(t[i:i + 2000])
    lm = KNLetterLM(order).fit(train)
    sample = "".join(held)[:50000]
    return lm, {"train_letters": sum(map(len, train)), "held_letters": len(sample),
                "bits_per_letter": round(lm.bits_per_letter(sample), 3) if sample else None}
