"""Kneser-Ney letter model over Greek capitals, and the TEI corpus builder it is trained on.

What this is: an interpolated modified Kneser-Ney letter n-gram model (Chen and Goodman 1999) over the 24
Greek capitals with lunate sigma plus " " as the word boundary, and the normaliser that turns public TEI
editions (PerseusDL/canonical-greekLit, OpenGreekAndLatin/First1KGreek) into one line of capitals per
document. It is the baseline of the Greek gap restoration benchmark (kit/greekfill.py, docs/tools/greekfill.md).
It is a statistical prior over letter strings; it never reads a scroll, and a string it fills in is
model output, not a reading.

Pieces (numpy only):

* KNModel: interpolated modified Kneser-Ney letter n-gram model, orders up to 13, fitted in chunks with
  base-25 integer keys and sorted arrays, so scoring is vectorised with searchsorted.
* NgramLM, MixtureLM: a fitted model as a language model, and a linear interpolation of several.
* build_corpus(): the normalised corpus, "DOCID<TAB>TEXT" per document (TEXT uses single spaces).

Symbols: the 24 majuscules ALPHABET (lunate sigma) plus " " as the word boundary; documents are padded
with boundaries.

Ported from the code that made the benchmark's frozen baseline on 22 October 2026: the model and mixture code
are unchanged, functions this benchmark does not use were removed, and the corpus builder is packaged as a
function, so the baseline reproduces byte for byte.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϹΤΥΦΧΨΩ"
BOUND = " "
SYMBOLS = ALPHABET + BOUND
V = len(SYMBOLS)                 # 25
B = V - 1                        # boundary index
IDX = {c: i for i, c in enumerate(SYMBOLS)}
MAX_ORDER = 13                   # 25**13 < 2**63


# ---------------------------------------------------------------- text helpers
def clean(text: str) -> str:
    """Uppercase base letters (lunate sigma), non-letters as single boundaries."""
    import unicodedata
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.combining(ch):
            continue
        up = ch.upper()
        if up in ("Σ", "ς", "Ϲ", "ϲ"):
            up = "Ϲ"
        out.append(up if up in ALPHABET else " ")
    return " ".join("".join(out).split())


def encode(text: str, pad: int = 1) -> np.ndarray:
    """int8 symbol ids with `pad` leading and one trailing boundary."""
    t = clean(text)
    ids = np.fromiter((IDX[c] for c in t), dtype=np.int8, count=len(t))
    return np.concatenate([np.full(pad, B, np.int8), ids, np.full(1, B, np.int8)])




# ---------------------------------------------------------------- Kneser-Ney
def _keys(seq: np.ndarray, k: int) -> np.ndarray:
    """Base-V integer keys of all k-grams of an int8 sequence (int64)."""
    n = len(seq) - k + 1
    if n <= 0:
        return np.zeros(0, np.int64)
    key = np.zeros(n, np.int64)
    s = seq.astype(np.int64)
    for j in range(k):
        key = key * V + s[j:j + n]
    return key


def _merge(keys_list, counts_list):
    keys = np.concatenate(keys_list)
    counts = np.concatenate(counts_list)
    order = np.argsort(keys, kind="stable")
    keys, counts = keys[order], counts[order]
    uk, start = np.unique(keys, return_index=True)
    return uk, np.add.reduceat(counts, start).astype(np.int64)


class KNModel:
    """Interpolated modified Kneser-Ney letter model."""

    def __init__(self, order=7, discount="modified", min_count=1):
        if not 1 <= order <= MAX_ORDER:
            raise ValueError("order must be 1..%d" % MAX_ORDER)
        self.order = order
        self.discount = discount
        self.min_count = min_count
        self.tables = {}     # k -> dict(keys, counts, ctx_keys, ctx_total, ctx_n1, ctx_n2, ctx_n3, D)
        self.n_train = 0

    # ---- fitting
    def fit_sequences(self, seqs, chunk_letters=20_000_000):
        """Fit on an iterable of int8 sequences (each already padded with order-1 boundaries)."""
        N = self.order
        acc_k, acc_c = [], []
        buf, size = [], 0

        def flush():
            nonlocal buf, size
            if not buf:
                return
            s = np.concatenate(buf)
            k = _keys(s, N)
            # drop n-grams that straddle two documents' padding is harmless (boundary context)
            uk, cnt = np.unique(k, return_counts=True)
            acc_k.append(uk)
            acc_c.append(cnt.astype(np.int64))
            if len(acc_k) >= 4:
                mk, mc = _merge(acc_k, acc_c)
                acc_k[:], acc_c[:] = [mk], [mc]
            buf, size = [], 0

        for s in seqs:
            s = np.asarray(s, np.int8)
            if len(s) < N:
                s = np.concatenate([np.full(N - len(s), B, np.int8), s])
            buf.append(s)
            # keep n-grams inside each document: separate docs with N-1 boundaries
            buf.append(np.full(N - 1, B, np.int8))
            size += len(s)
            self.n_train += int((s != B).sum())
            if size >= chunk_letters:
                flush()
        flush()
        top_k, top_c = _merge(acc_k, acc_c) if len(acc_k) > 1 else (acc_k[0], acc_c[0])
        if self.min_count > 1:
            keep = top_c >= self.min_count
            top_k, top_c = top_k[keep], top_c[keep]
        self._build(top_k, top_c)
        return self

    def fit_texts(self, texts, **kw):
        pad = self.order - 1
        return self.fit_sequences((encode(t, pad=max(pad, 1)) for t in texts), **kw)

    def _build(self, top_keys, top_counts):
        N = self.order
        keys, counts = top_keys, top_counts
        for k in range(N, 0, -1):
            ctx = keys // V
            uctx, start, inv = np.unique(ctx, return_index=True, return_inverse=True)
            tot = np.add.reduceat(counts, start)
            n1 = np.bincount(inv, weights=(counts == 1), minlength=len(uctx)).astype(np.int64)
            n2 = np.bincount(inv, weights=(counts == 2), minlength=len(uctx)).astype(np.int64)
            n3 = np.bincount(inv, weights=(counts >= 3), minlength=len(uctx)).astype(np.int64)
            D = self._discounts(counts)
            self.tables[k] = dict(keys=keys, counts=counts, ctx_keys=uctx, ctx_total=tot,
                                  ctx_n1=n1, ctx_n2=n2, ctx_n3=n3, D=D)
            if k > 1:
                # continuation counts for order k-1: distinct left extensions
                suffix = keys % (V ** (k - 1))
                uk, cc = np.unique(suffix, return_counts=True)
                keys, counts = uk, cc.astype(np.int64)

    def _discounts(self, counts):
        n = [int((counts == i).sum()) for i in (1, 2, 3, 4)]
        if n[0] == 0 or n[1] == 0:
            return (0.5, 0.75, 0.9)
        Y = n[0] / (n[0] + 2 * n[1])
        if self.discount == "single":
            return (Y, Y, Y)
        D1 = 1 - 2 * Y * n[1] / n[0]
        D2 = 2 - 3 * Y * n[2] / n[1] if n[1] else 1.0
        D3 = 3 - 4 * Y * n[3] / n[2] if n[2] else 1.5
        return (max(D1, 0.05), max(D2, 0.05), max(D3, 0.05))

    # ---- scoring
    def _lookup(self, table_keys, values, q):
        idx = np.searchsorted(table_keys, q)
        idx = np.minimum(idx, len(table_keys) - 1)
        hit = table_keys[idx] == q if len(table_keys) else np.zeros(len(q), bool)
        out = np.zeros(len(q), values.dtype)
        out[hit] = values[idx[hit]]
        return out, hit, idx

    def prob_next(self, ctx_keys_by_k, w):
        """P(w | context) for vectors: ctx_keys_by_k[k] is the (k-1)-symbol context key per query."""
        p = np.full(len(w), 1.0 / V)
        for k in range(1, self.order + 1):
            t = self.tables[k]
            ck = ctx_keys_by_k[k]
            q = ck * V + w
            c, _, _ = self._lookup(t["keys"], t["counts"], q)
            tot, hit, idx = self._lookup(t["ctx_keys"], t["ctx_total"], ck)
            n1 = np.where(hit, t["ctx_n1"][idx], 0)
            n2 = np.where(hit, t["ctx_n2"][idx], 0)
            n3 = np.where(hit, t["ctx_n3"][idx], 0)
            D1, D2, D3 = t["D"]
            d = np.where(c == 0, 0.0, np.where(c == 1, D1, np.where(c == 2, D2, D3)))
            safe = np.maximum(tot, 1)
            gamma = (D1 * n1 + D2 * n2 + D3 * n3) / safe
            pk = np.maximum(c - d, 0.0) / safe + gamma * p
            p = np.where(hit, pk, p)
        return p

    def _ctx_keys(self, seq, pos):
        """Context keys (k-1 symbols before each position) for k = 1..order."""
        out = {1: np.zeros(len(pos), np.int64)}
        s = seq.astype(np.int64)
        key = np.zeros(len(pos), np.int64)
        for k in range(2, self.order + 1):
            j = pos - (k - 1)
            sym = np.where(j >= 0, s[np.maximum(j, 0)], B)
            key = key + sym * (V ** (k - 2))
            out[k] = key.copy()
        return out

    def seq_logprobs(self, seq):
        """Natural log prob of every symbol after the first in an int8 sequence."""
        pos = np.arange(1, len(seq))
        return np.log(self.prob_next(self._ctx_keys(seq, pos), seq[1:].astype(np.int64)))

    def next_logprobs(self, histories):
        """(len(histories), V) log P(next | history) for string histories (boundary-padded)."""
        n = len(histories)
        L = self.order - 1
        ctx = np.full((n, max(L, 1)), B, np.int64)
        for i, h in enumerate(histories):
            tail = h[-L:] if L else ""
            for j, ch in enumerate(reversed(tail)):
                ctx[i, j] = IDX[ch]
        keys = {1: np.zeros(n, np.int64)}
        key = np.zeros(n, np.int64)
        for k in range(2, self.order + 1):
            key = key + ctx[:, k - 2] * (V ** (k - 2))
            keys[k] = key.copy()
        rep = {k: np.repeat(v, V) for k, v in keys.items()}
        w = np.tile(np.arange(V, dtype=np.int64), n)
        return np.log(self.prob_next(rep, w)).reshape(n, V)

    # ---- persistence
    def save(self, path):
        path = Path(path)
        arrs = {}
        for k, t in self.tables.items():
            for name, a in t.items():
                if name != "D":
                    arrs["%d_%s" % (k, name)] = a
            arrs["%d_D" % k] = np.asarray(t["D"])
        meta = {"order": self.order, "discount": self.discount, "min_count": self.min_count,
                "n_train": self.n_train}
        np.savez_compressed(path, meta=json.dumps(meta), **arrs)

    @classmethod
    def load(cls, path):
        d = np.load(path, allow_pickle=False)
        meta = json.loads(str(d["meta"]))
        m = cls(meta["order"], meta["discount"], meta["min_count"])
        m.n_train = meta["n_train"]
        for k in range(1, m.order + 1):
            t = {n: d["%d_%s" % (k, n)] for n in ("keys", "counts", "ctx_keys", "ctx_total",
                                                   "ctx_n1", "ctx_n2", "ctx_n3")}
            t["D"] = tuple(float(x) for x in d["%d_D" % k])
            m.tables[k] = t
        return m


# ---------------------------------------------------------------- shared API
class _LMBase:
    def text_logprobs(self, text):
        raise NotImplementedError

    def score(self, text):
        """Total natural log prob of a string (with final boundary)."""
        return float(self.text_logprobs(text).sum())

    def bits_per_symbol(self, texts):
        tot, n = 0.0, 0
        for t in texts:
            lp = self.text_logprobs(t)
            tot += float(lp.sum())
            n += len(lp)
        return -tot / max(n, 1) / math.log(2)

    def per_letter(self, text):
        n = sum(1 for c in clean(text) if c != " ")
        return self.score(text) / max(n, 1)


class NgramLM(_LMBase):
    def __init__(self, model: KNModel):
        self.model = model
        self.order = model.order

    def text_logprobs(self, text):
        seq = encode(text, pad=1)
        return self.model.seq_logprobs(seq)

    def next_logprobs(self, histories):
        return self.model.next_logprobs(histories)


class MixtureLM(_LMBase):
    """p = sum_i w_i p_i over component LMs exposing text_logprobs / next_logprobs."""

    def __init__(self, components, weights=None):
        self.components = list(components)
        k = len(self.components)
        self.weights = np.full(k, 1.0 / k) if weights is None else np.asarray(weights, float)

    def _mix(self, lps):
        stack = np.stack(lps)
        shape = (-1,) + (1,) * (stack.ndim - 1)
        stack = stack + np.log(np.maximum(self.weights, 1e-12)).reshape(shape)
        m = stack.max(0)
        return m + np.log(np.exp(stack - m).sum(0))

    def text_logprobs(self, text):
        return self._mix([c.text_logprobs(text) for c in self.components])

    def next_logprobs(self, histories):
        return self._mix([c.next_logprobs(histories) for c in self.components])

    def fit_weights(self, texts, iters=50):
        """EM for mixture weights on held-out texts (component predictions fixed)."""
        lps = [np.concatenate([c.text_logprobs(t) for t in texts]) for c in self.components]
        P = np.exp(np.stack(lps))
        w = self.weights.copy()
        for _ in range(iters):
            r = w[:, None] * P
            r /= r.sum(0, keepdims=True)
            w = r.mean(1)
        self.weights = w
        return w


def em_weights(component_logprobs, iters=100):
    """EM mixture weights from precomputed per-symbol log probs (list of equal-length arrays)."""
    P = np.exp(np.stack(component_logprobs))
    w = np.full(len(component_logprobs), 1.0 / len(component_logprobs))
    for _ in range(iters):
        r = w[:, None] * P
        r /= r.sum(0, keepdims=True)
        w = r.mean(1)
    return w


# ---------------------------------------------------------------- TEI corpus
DROP = {"teiHeader", "note", "head", "bibl", "ref", "label", "figDesc", "del", "sic", "orig", "abbr"}
_MAP = {"Σ": "Ϲ", "ς": "Ϲ", "σ": "Ϲ", "ϲ": "Ϲ", "Ϲ": "Ϲ", "ϛ": "", "Ϛ": ""}


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(elem, out):
    tag = _local(elem.tag)
    if tag in DROP:
        if elem.tail:
            out.append(elem.tail)
        return
    lang = elem.get("{http://www.w3.org/XML/1998/namespace}lang")
    if tag == "foreign" and lang and lang != "grc":
        if elem.tail:
            out.append(elem.tail)
        return
    if tag in ("l", "p", "lb", "div", "lg", "sp", "speaker"):
        out.append("\n")
    if elem.text:
        out.append(elem.text)
    for ch in elem:
        _text(ch, out)
    if elem.tail:
        out.append(elem.tail)


def normalise(raw: str) -> str:
    """TEI body text to capitals: brackets dropped (letters kept), hyphenation joined, lacuna dots a boundary."""
    raw = re.sub(r"[\[\]⟦⟧⟨⟩{}<>()|†*]", "", raw)  # editorial brackets join letters
    raw = re.sub(r"-\s*\n\s*", "", raw)               # hyphenation across lines
    raw = re.sub(r"(\.\s*){2,}", " ", raw)            # lacuna dots
    s = unicodedata.normalize("NFD", raw)
    out = []
    for ch in s:
        if unicodedata.combining(ch):
            continue
        ch = _MAP.get(ch, ch)
        if not ch:
            continue
        up = ch.upper()
        up = _MAP.get(up, up)
        out.append(up if up in ALPHABET else " ")
    return " ".join("".join(out).split())


def doc_text(path: str):
    """(path, normalised text of the TEI <body>) or (path, None) when the file does not parse or has no body."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return path, None
    body = None
    for el in root.iter():
        if _local(el.tag) == "body":
            body = el
            break
    if body is None:
        return path, None
    out = []
    _text(body, out)
    return path, normalise("".join(out))


def build_corpus(out_path, roots, nproc=None):
    """Write the normalised corpus to out_path from every *grc*.xml under each root, in order.

    Files are sorted by path within each root; a document shorter than 200 symbols is left out. Returns
    {"files", "kept", "letters", "sha256"}. nproc defaults to the NPROC environment variable, else 3.
    """
    out_path = Path(out_path)
    files = []
    for root in roots:
        files += sorted(str(p) for p in Path(root).rglob("*grc*.xml"))
    stats = {"files": len(files), "kept": 0, "letters": 0}
    workers = nproc or int(os.environ.get("NPROC", "3"))
    with ProcessPoolExecutor(max_workers=workers) as ex, \
            open(out_path, "w", encoding="utf-8") as fo:
        for path, text in ex.map(doc_text, files, chunksize=8):
            if not text or len(text) < 200:
                continue
            docid = Path(path).name.replace(".xml", "")
            fo.write(docid + "\t" + text + "\n")
            stats["kept"] += 1
            stats["letters"] += sum(1 for c in text if c != " ")
    h = hashlib.sha256(out_path.read_bytes()).hexdigest()
    stats["sha256"] = h
    return stats
