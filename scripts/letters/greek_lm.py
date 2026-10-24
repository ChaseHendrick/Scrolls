#!/usr/bin/env python3
"""A character language model of Greek prose in scriptio continua, and line decoding with it.

The model counts letters of a fixed list of Perseus prose texts (PerseusDL/canonical-greekLit, CC BY-SA 4.0),
written as the 24 capitals with no spaces, accents or marks, as papyri write them. Homer and every verse work
are left out, and so is every <l> (verse line), <quote>, <cit>, <note> and <bibl> element inside the prose, so
quoted hexameters do not enter it. It is an interpolated Kneser-Ney model of order ORDER.

`decode_boxes` reads a line whose letter boxes are given: per box, a reader's log-probabilities over the 24
capitals, turned into likelihoods by subtracting the log of the reader's own training class shares, plus
weight times the language model's log-probability, in a beam search. It also returns each letter's posterior
(its confidence) and ranked alternatives from the final beam.

  python scripts/letters/greek_lm.py build --out lm.json.gz [--cache DIR]
  python scripts/letters/greek_lm.py ppl --lm lm.json.gz --text FILE.xml   # bits per letter on a text

Model output and public text counts only; nothing here is a reading of a scroll.
"""
import argparse
import gzip
import hashlib
import json
import math
import re
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
ORDER = 5
PERSEUS = "https://raw.githubusercontent.com/PerseusDL/canonical-greekLit/{commit}/data/"
PERSEUS_COMMIT = "0189b9c8d8d1f148133f2f0af309b4ee90ea4332"
# Prose only: Herodotus, Thucydides, Xenophon, Plato, Lysias, Isocrates, Demosthenes, Aristotle, Polybius,
# Diogenes Laertius, Plutarch (two Lives). No Homer (tlg0012, tlg0013), no poet.
TEXTS = (
    "tlg0016/tlg001", "tlg0003/tlg001", "tlg0032/tlg001", "tlg0032/tlg006", "tlg0032/tlg007",
    "tlg0059/tlg002", "tlg0059/tlg003", "tlg0059/tlg004", "tlg0059/tlg011", "tlg0059/tlg030", "tlg0059/tlg034",
    "tlg0540/tlg001", "tlg0540/tlg012", "tlg0010/tlg011", "tlg0014/tlg001", "tlg0014/tlg018",
    "tlg0086/tlg010", "tlg0086/tlg035", "tlg0543/tlg001", "tlg0004/tlg001", "tlg0007/tlg001", "tlg0007/tlg049",
)
DROP = ("l", "quote", "cit", "note", "bibl", "head", "teiHeader", "label", "milestone")


def norm(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper().replace("Ϲ", "Σ")
    return "".join(c for c in s if c in ALPHABET)


def prose_of(xml):
    t = xml.split("<body", 1)[-1]
    for tag in DROP:
        t = re.sub(rf"<{tag}\b[^>]*/>", " ", t)
        t = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", t, flags=re.S)
    return norm(re.sub(r"<[^>]+>", " ", t))


def fetch_text(rel, cache=None):
    a, b = rel.split("/")
    for ed in ("perseus-grc2", "perseus-grc1", "perseus-grc3"):
        name = f"{a}.{b}.{ed}.xml"
        if cache and (Path(cache) / name).exists():
            return name, (Path(cache) / name).read_text(encoding="utf-8")
        url = PERSEUS.format(commit=PERSEUS_COMMIT) + f"{rel}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                text = r.read().decode("utf-8")
        except Exception:
            continue
        if cache:
            Path(cache).mkdir(parents=True, exist_ok=True)
            (Path(cache) / name).write_text(text, encoding="utf-8")
        return name, text
    raise SystemExit(f"{rel}: no Perseus Greek edition found")


class LM:
    """Interpolated Kneser-Ney over letters; contexts are strings of up to ORDER-1 capitals; '^' starts a line."""

    def __init__(self, counts, order=ORDER, d=0.75):
        self.order, self.d = order, d
        self.c = counts                         # {n: {context: {letter: count}}}, n = context length
        self.cache = {}

    @classmethod
    def train(cls, stream, order=ORDER):
        counts = {n: defaultdict(lambda: defaultdict(int)) for n in range(order)}
        s = stream
        for i in range(len(s)):
            for n in range(order):
                if i - n < 0:
                    break
                counts[n][s[i - n:i]][s[i]] += 1
        # Kneser-Ney continuation counts for the lower orders: how many distinct left extensions
        kn = {n: defaultdict(lambda: defaultdict(int)) for n in range(order - 1)}
        for n in range(1, order):
            for ctx, nxt in counts[n].items():
                for ch in nxt:
                    kn[n - 1][ctx[1:]][ch] += 1
        out = {order - 1: {k: dict(v) for k, v in counts[order - 1].items()}}
        for n in range(order - 1):
            out[n] = {k: dict(v) for k, v in kn[n].items()}
        return cls(out, order)

    def logp_vec(self, ctx):
        """log P(next | ctx) for the 24 capitals (ctx: the preceding letters, any length)."""
        ctx = ctx[-(self.order - 1):] if self.order > 1 else ""
        if ctx in self.cache:
            return self.cache[ctx]
        p = np.full(24, 1.0 / 24)
        for n in range(0, len(ctx) + 1):
            c = ctx[len(ctx) - n:] if n else ""
            tab = self.c.get(n, {}).get(c)
            if not tab:
                continue
            tot = sum(tab.values())
            cnt = np.array([tab.get(ch, 0) for ch in ALPHABET], float)
            lam = self.d * len(tab) / tot
            p = np.maximum(cnt - self.d, 0) / tot + lam * p
        v = np.log(p / p.sum())
        if len(self.cache) < 500000:
            self.cache[ctx] = v
        return v

    def unigram(self):
        return self.logp_vec("")

    def bits_per_letter(self, s):
        tot = 0.0
        for i in range(len(s)):
            tot -= self.logp_vec(s[max(0, i - self.order + 1):i])[ALPHABET.index(s[i])]
        return tot / max(1, len(s)) / math.log(2)

    def save(self, path, meta):
        obj = {"order": self.order, "d": self.d, "meta": meta,
               "counts": {str(n): v for n, v in self.c.items()}}
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def load(cls, path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            obj = json.load(f)
        return cls({int(n): v for n, v in obj["counts"].items()}, obj["order"], obj["d"])


def decode_boxes(post, lm, weight, train_logprior=None, beam=16, top=3):
    """Best letter string for a line of boxes. post: (n, 24) reader log-probabilities.
    Returns (string, per-letter confidence (max-marginal over the final beam), per-letter top alternatives)."""
    like = np.asarray(post, float) - (train_logprior if train_logprior is not None else 0.0)
    beams = [("", 0.0)]
    for i in range(len(like)):
        cand = []
        for s, sc in beams:
            v = like[i] + weight * lm.logp_vec(s)
            for k in np.argsort(-v)[:beam]:
                cand.append((s + ALPHABET[k], sc + v[k]))
        cand.sort(key=lambda t: -t[1])
        beams = cand[:beam]
    best = beams[0][0]
    sc = np.array([b[1] for b in beams])
    w = np.exp(sc - sc.max())
    w /= w.sum()
    conf, alts = [], []
    for i in range(len(like)):
        m = defaultdict(float)
        for (s, _), wi in zip(beams, w):
            m[s[i]] += wi
        r = sorted(m.items(), key=lambda t: -t[1])
        conf.append(round(float(m[best[i]]), 4))
        alts.append([(ch, round(float(p), 4)) for ch, p in r[:top]])
    return best, conf, alts


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cmd_build(a):
    names, parts = [], []
    for rel in TEXTS:
        name, xml = fetch_text(rel, a.cache)
        s = prose_of(xml)
        names.append({"file": name, "letters": len(s), "sha256": hashlib.sha256(xml.encode()).hexdigest()})
        parts.append(s)
        print(name, len(s), flush=True)
    stream = "".join(parts)
    lm = LM.train(stream, a.order)
    meta = {"texts": names, "letters": len(stream), "perseus_commit": PERSEUS_COMMIT, "dropped_elements": DROP}
    lm.save(a.out, meta)
    print(f"{len(stream)} letters, order {a.order}, saved {a.out}")


def cmd_ppl(a):
    lm = LM.load(a.lm)
    s = prose_of(Path(a.text).read_text(encoding="utf-8")) if a.text.endswith(".xml") else norm(Path(a.text).read_text())
    print(f"{a.text}: {lm.bits_per_letter(s[:a.limit]):.3f} bits per letter over {min(len(s), a.limit)} letters")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True)
    b.add_argument("--cache")
    b.add_argument("--order", type=int, default=ORDER)
    q = sub.add_parser("ppl")
    q.add_argument("--lm", required=True)
    q.add_argument("--text", required=True)
    q.add_argument("--limit", type=int, default=200000)
    a = p.parse_args(argv)
    {"build": cmd_build, "ppl": cmd_ppl}[a.cmd](a)


if __name__ == "__main__":
    main()
