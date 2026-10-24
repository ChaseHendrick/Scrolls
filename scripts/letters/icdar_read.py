#!/usr/bin/env python3
"""Readers on the ICDAR 2023 letter and line sets built by icdar_h2h.py, and their scores.

Every arm writes, per part, one npz of log-probabilities over the 24 capitals for every box in letters.json
order (`post-ARM.npz`: ids, logp). Lines are scored from these posteriors (boxes given) or, for a free line
reader, from its own string per line (`lines-ARM.json`). Reading the test part is guarded: see `test_guard`.

  python scripts/letters/icdar_read.py post --work W --part dev --arm R1 --variant plain --r1 R1.pth --r1-config CFG
  python scripts/letters/icdar_read.py post --work W --part dev --arm O5 --o5 DIR
  python scripts/letters/icdar_read.py acc --work W --part dev --arm R1

Model output: letters named by learned readers for public papyrus photographs; not a reading of any scroll.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
HELLCHAR_CLASSES = ["Alpha", "Beta", "Chi", "Delta", "Epsilon", "Eta", "Gamma", "Iota", "Kappa", "Lambda", "Mu",
                    "Nu", "Omega", "Omicron", "Phi", "Pi", "Psi", "Rho", "Sigma", "Tau", "Theta", "Upsilon", "Xi",
                    "Zeta"]
NAME_TO_CAP = dict(zip(["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa",
                        "lambda", "mu", "nu", "xi", "omicron", "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi",
                        "psi", "omega"], ALPHABET))
R1_SHA = "b30dfd2f22df66683e50ab660bba6673f20c6a1b503fd05dc30d87b818d4bec5"
R1_CONFIG_SHA = "d81d285b37b1f27b54abd1d2f5b08491c1a5631dc4c4bcf6840361ab41c43b60"
O2_SHA = "b14988852fc721cce71e80a66db0a8ea99a1de914ef2b724ecc6e711baa9ed8c"
PREREG = REPO / "docs" / "prereg" / "2026-10-24-letter-reader-icdar-h2h.md"
N_BOOT = 20000


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_part(work, part):
    d = Path(work) / part
    return json.loads((d / "letters.json").read_text()), json.loads((d / "lines.json").read_text())


def crop(work, part, bid):
    from PIL import Image
    return np.asarray(Image.open(Path(work) / part / "crops" / f"{bid}.png").convert("L"))


def tile_shuffle(g, seed, k=4):
    """C2's decoy: the crop cut into a k x k grid (edges trimmed to a multiple of k) and its tiles shuffled."""
    g = np.asarray(g)
    h, w = (g.shape[0] // k) * k, (g.shape[1] // k) * k
    if h < k or w < k:
        return g
    t = g[:h, :w].reshape(k, h // k, k, w // k).swapaxes(1, 2).reshape(k * k, h // k, w // k)
    t = t[np.random.default_rng(seed).permutation(k * k)]
    return t.reshape(k, k, h // k, w // k).swapaxes(1, 2).reshape(h, w)


def log_softmax(z):
    z = np.asarray(z, np.float64)
    return z - np.logaddexp.reduce(z, axis=-1, keepdims=True)


# ------------------------------------------------------------------ R1: Hell-Char ConvNeXt-V2 Tiny, as released

def r1_load(path, config):
    import torch
    import torch.nn as nn
    import timm
    if sha256_file(path) != R1_SHA or sha256_file(config) != R1_CONFIG_SHA:
        raise SystemExit("R1: weights or config are not the pinned files")
    cfg = json.loads(Path(config).read_text())

    class TimmClassifier(nn.Module):           # as the release's demo builds it
        def __init__(self, name, n):
            super().__init__()
            self.model = timm.create_model(name, pretrained=False, num_classes=n, in_chans=1)

        def forward(self, x):
            return self.model(x)
    m = TimmClassifier(cfg.get("model", "convnextv2_tiny"), len(cfg["classes"]))
    state = torch.load(path, map_location="cpu", weights_only=True)
    for k in ("model_state_dict", "state_dict"):
        if isinstance(state, dict) and k in state:
            state = state[k]
    m.load_state_dict(state)
    m.eval()
    perm = [list(cfg["classes"]).index(n) for n in
            sorted(cfg["classes"], key=lambda n: ALPHABET.index(NAME_TO_CAP[n.lower()]))]
    return m, perm


def r1_input(g, variant):
    """One gray crop to R1's 1 x 64 x 64 input: plain is the release's evaluate.py (cv2 INTER_AREA to 64 x 64,
    [0, 1], Normalize(0.5, 0.5)); pad keeps the aspect on a white canvas; demo inverts first."""
    import cv2
    import torch
    from PIL import Image
    g = np.asarray(g, np.uint8)
    if variant in ("plain", "demo"):
        a = 255 - g if variant == "demo" else g
        a = cv2.resize(a, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    elif variant == "pad":
        img = Image.fromarray(g, mode="L")
        w, h = img.size
        s = min(64 / w, 64 / h)
        nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
        canvas = Image.new("L", (64, 64), color=int(np.percentile(g, 80)))
        canvas.paste(img.resize((nw, nh), Image.BILINEAR), ((64 - nw) // 2, (64 - nh) // 2))
        a = np.asarray(canvas, np.float32) / 255.0
    else:
        raise ValueError(variant)
    return (torch.from_numpy(a).unsqueeze(0) - 0.5) / 0.5


def r1_post(model_perm, greys, variant, batch=128):
    import torch
    model, perm = model_perm
    out = []
    with torch.inference_mode():
        for i in range(0, len(greys), batch):
            x = torch.stack([r1_input(g, variant) for g in greys[i:i + batch]])
            out.append(model(x).numpy()[:, perm])
    return log_softmax(np.concatenate(out))


# ------------------------------------------------------------------ O2: letters-v2-ccby, one-letter CTC

def o2_post(weights, greys):
    import ctc_letter as esa
    import realforms
    from kit import letterread as lr
    if sha256_file(weights) != O2_SHA:
        raise SystemExit("O2: not the pinned letters-v2-ccby weights")
    net = lr.LineNet(weights)
    idx = [net.alphabet.index("Ϲ" if c == "Σ" else c) + 1 for c in ALPHABET]   # the reader writes lunate sigma
    out = []
    for g in greys:
        ink = realforms.ink_from_photo(g)
        if ink is None:
            out.append(np.full(24, -np.log(24.0)))
            continue
        band = esa.band_of(ink, net, net.letter_px / max(1, ink.shape[0]))
        lp = net.log_probs(band)
        ol = esa.one_letter_logp(lp)
        out.append(ol[np.array(idx) - 1])
    return log_softmax(np.array(out))


# ------------------------------------------------------------------ O5: our classifier (icdar_train.py)

def o5_post(folder, greys, batch=256):
    import icdar_train as it
    return it.predict_folder(folder, greys, batch=batch)


# ------------------------------------------------------------------ scoring

def unit_counts(ids, units, correct):
    """{unit: (errors, n)}"""
    out = {}
    for u, ok in zip(units, correct):
        e, n = out.get(u, (0, 0))
        out[u] = (e + (0 if ok else 1), n + 1)
    return out


def boot_rate(counts, n=N_BOOT, seed=0):
    keys = sorted(counts)
    e = np.array([counts[k][0] for k in keys], float)
    m = np.array([counts[k][1] for k in keys], float)
    idx = np.random.default_rng(seed).integers(0, len(keys), (n, len(keys)))
    r = e[idx].sum(1) / m[idx].sum(1)
    return float(e.sum() / m.sum()), [float(v) for v in np.percentile(r, [2.5, 97.5])]


def paired(a, b, n=N_BOOT, seed=0):
    """b minus a (error rates), bootstrap over the shared units; 95% and 97.5% intervals from one draw."""
    keys = sorted(set(a) & set(b))
    ea, la = (np.array([a[k][i] for k in keys], float) for i in (0, 1))
    eb, lb = (np.array([b[k][i] for k in keys], float) for i in (0, 1))
    idx = np.random.default_rng(seed).integers(0, len(keys), (n, len(keys)))
    d = eb[idx].sum(1) / lb[idx].sum(1) - ea[idx].sum(1) / la[idx].sum(1)
    return {"d": float(eb.sum() / lb.sum() - ea.sum() / la.sum()),
            "ci95": [float(v) for v in np.percentile(d, [2.5, 97.5])],
            "ci975": [float(v) for v in np.percentile(d, [1.25, 98.75])], "units": len(keys)}


def verdict(lo, hi):
    if hi < 0:
        return "ahead"
    if lo > 0:
        return "behind"
    if lo >= -0.05 and hi <= 0.05:
        return "level"
    return "not resolved"


# ------------------------------------------------------------------ priors and lines

def hellchar_logshare(csv_path):
    """log of Hell-Char's class shares (R1 trained on a letter-stratified 80% of them, so the same shares)."""
    import csv
    from collections import Counter
    c = Counter(r["letter"].strip().lower() for r in csv.DictReader(open(csv_path, newline="", encoding="utf-8")))
    v = np.array([c.get(n, 0) for n in NAME_TO_CAP], float)
    order = [list(NAME_TO_CAP).index(n) for n in sorted(NAME_TO_CAP, key=lambda n: ALPHABET.index(NAME_TO_CAP[n]))]
    v = v[order]
    return np.log(v / v.sum())


def with_prior(lp, weight, lm_unigram, train_logshare):
    """Bayes correction: reader posterior minus its training shares, plus weight times log P(letter) of text."""
    if not weight:
        return lp
    return log_softmax(lp - train_logshare + weight * lm_unigram)


def letter_counts(letters, lp):
    pred = [ALPHABET[i] for i in np.asarray(lp).argmax(1)]
    ok = [p == L["letter"] for p, L in zip(pred, letters)]
    return unit_counts(None, [L["unit"] for L in letters], ok), pred


def line_reads(letters, lines, lp, lm, weight, train_logshare, beam=16):
    """{line id: (read, conf, alts)} for scored lines, boxes given."""
    import greek_lm as g
    pos = {L["id"]: i for i, L in enumerate(letters)}
    out = {}
    for ln in lines:
        if not ln["scored"]:
            continue
        rows = [pos[b] for b in ln["boxes"] if b in pos]
        if len(rows) != len(ln["boxes"]):
            continue
        post = np.asarray(lp)[rows]
        if lm is None or not weight:
            out[ln["id"]] = ("".join(ALPHABET[i] for i in post.argmax(1)), None, None)
        else:
            out[ln["id"]] = g.decode_boxes(post, lm, weight, train_logshare, beam=beam)
    return out


def line_counts(lines, reads):
    import greek_lm as g
    out = {}
    for ln in lines:
        if ln["id"] not in reads:
            continue
        e = g.edit_distance(reads[ln["id"]][0], ln["ref"])
        a, b = out.get(ln["unit"], (0, 0))
        out[ln["unit"]] = (a + e, b + len(ln["ref"]))
    return out


def free_line_reads(work, part, lines, weights):
    """letters-v2-ccby reading each scored line strip with no boxes (greedy CTC)."""
    import ctc_letter as esa
    import realforms
    from kit import letterread as lr
    if sha256_file(weights) != O2_SHA:
        raise SystemExit("O2: not the pinned letters-v2-ccby weights")
    net = lr.LineNet(weights)
    out = {}
    for ln in lines:
        if not ln["scored"]:
            continue
        g = crop(work, part, ln["id"])
        ink = realforms.ink_from_photo(g)
        if ink is None:
            out[ln["id"]] = ("", None, None)
            continue
        band = esa.band_of(ink, net, net.letter_px / max(1.0, ln["box_height"]))
        text = "".join(x[0] for x in lr.ctc_greedy(net.log_probs(band), net.alphabet)).replace("Ϲ", "Σ")
        out[ln["id"]] = (text, None, None)
    return out


# ------------------------------------------------------------------ guard for the test part

def test_guard():
    """A read of the test part must run from a clean, committed tree whose preregistration is filled (no <<...>>
    placeholder left) and whose code hashes match the ones it lists."""
    st = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"],
                        capture_output=True, text=True).stdout.strip()
    if st:
        raise SystemExit("test read refused: the working tree has uncommitted changes")
    import re
    text = PREREG.read_text(encoding="utf-8")
    if re.search(r"<<[A-Z0-9_]+>>", text):
        raise SystemExit("test read refused: the preregistration still has placeholders")
    for path, want in re.findall(r"^- `([^`]+)` sha256 `([0-9a-f]{64})`", text, flags=re.M):
        if sha256_file(REPO / path) != want:
            raise SystemExit(f"test read refused: {path} differs from the preregistration")


# ------------------------------------------------------------------ commands

def cmd_post(a):
    if a.part == "test":
        test_guard()
    letters, _ = load_part(a.work, a.part)
    greys = [crop(a.work, a.part, L["id"]) for L in letters]
    if a.decoy:
        greys = [tile_shuffle(g, i) for i, g in enumerate(greys)]
    if a.arm.startswith("R1"):
        lp = r1_post(r1_load(a.r1, a.r1_config), greys, a.variant)
    elif a.arm == "O2":
        lp = o2_post(a.o2, greys)
    elif a.arm.startswith("O5"):
        lp = o5_post(a.o5, greys)
    else:
        raise SystemExit(a.arm)
    out = Path(a.work) / a.part / f"post-{a.arm}{'-decoy' if a.decoy else ''}.npz"
    np.savez_compressed(out, ids=np.array([L["id"] for L in letters]), logp=lp.astype(np.float32))
    print(out, lp.shape)


def cmd_acc(a):
    letters, _ = load_part(a.work, a.part)
    z = np.load(Path(a.work) / a.part / f"post-{a.arm}.npz")
    lp = z["logp"].astype(np.float64)
    if a.prior:
        lp = lp + a.prior * unigram_logprior()
    pred = [ALPHABET[i] for i in lp.argmax(1)]
    ok = [p == L["letter"] for p, L in zip(pred, letters)]
    c = unit_counts(None, [L["unit"] for L in letters], ok)
    r, ci = boot_rate(c, n=2000)
    print(f"{a.arm} prior {a.prior}: error {r:.4f} ({ci[0]:.4f} to {ci[1]:.4f}) over {len(ok)} boxes, {len(c)} units")


def cmd_freelines(a):
    if a.part == "test":
        test_guard()
    _, lines = load_part(a.work, a.part)
    reads = free_line_reads(a.work, a.part, lines, a.o2)
    out = Path(a.work) / a.part / "lines-O2free.json"
    out.write_text(json.dumps({k: list(v) for k, v in reads.items()}, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out, len(reads))


def cmd_devlines(a):
    import greek_lm as g
    letters, lines = load_part(a.work, "dev")
    z = np.load(Path(a.work) / "dev" / f"post-{a.arm}.npz")
    lp = z["logp"].astype(np.float64)
    lm = g.LM.load(a.lm)
    share = hellchar_logshare(a.hellchar) if a.arm.startswith("R1") else __import__("icdar_train").train_logprior(a.o5)
    if a.prior:
        lp = with_prior(lp, a.prior, lm.unigram(), share)
        share = lm.unigram() * a.prior     # the prior is in lp now; decode with the text model on top of it
    for w in a.weights:
        reads = line_reads(letters, lines, lp, lm, w, share if w else None)
        c = line_counts(lines, reads)
        r, ci = boot_rate(c, n=2000)
        print(f"{a.arm} prior {a.prior} lm weight {w}: CER {r:.4f} ({ci[0]:.4f} to {ci[1]:.4f}) over {len(reads)} lines", flush=True)


def perm_p(letters, pred, n=2000, seed=0):
    """C1: one-sided p of the accuracy against references permuted within units."""
    truth = np.array([L["letter"] for L in letters])
    units = np.array([L["unit"] for L in letters])
    pred = np.array(pred)
    obs = float((pred == truth).mean())
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(units == u) for u in sorted(set(units))]
    ge = 0
    for _ in range(n):
        t = truth.copy()
        for g in groups:
            t[g] = t[g][rng.permutation(len(g))]
        ge += float((pred == t).mean()) >= obs
    return obs, (1 + ge) / (1 + n)


def cmd_score(a):
    """Every preregistered number for one part from the saved posteriors, into one JSON file."""
    import greek_lm as g
    import icdar_train as it
    if a.part == "test":
        test_guard()
    fill = json.loads(Path(a.fill).read_text())          # the fill commit's choices, as a JSON block
    letters, lines = load_part(a.work, a.part)
    d = Path(a.work) / a.part
    lm = g.LM.load(a.lm)
    uni = lm.unigram()
    hc_share = hellchar_logshare(a.hellchar)
    o5_share = it.train_logprior(fill["o5_runs"])

    def post(name):
        return np.load(d / f"post-{name}.npz")["logp"].astype(np.float64)
    arms = {"O5": with_prior(post("O5"), fill["o5_prior"], uni, o5_share),
            "R1": post("R1plain"),
            "R1p": with_prior(post("R1plain"), fill["o5_prior"], uni, hc_share),
            "O2": post("O2")}
    shares = {"O5": o5_share, "R1": hc_share}
    out = {"part": a.part, "fill": fill, "letters": {}, "lines": {}, "controls": {}, "comparisons": {}}
    counts = {}
    for k, lp in arms.items():
        c, pred = letter_counts(letters, lp)
        counts[k] = c
        r, ci = boot_rate(c)
        acc, p = perm_p(letters, pred)
        out["letters"][k] = {"error": r, "ci95": ci, "boxes": len(letters), "units": len(c)}
        out["controls"][f"C1 {k}"] = {"accuracy": acc, "p": p, "pass": p < 0.05}
    # C2 decoys for O5 and R1
    for k, name in (("O5", "O5"), ("R1", "R1plain")):
        dl = post(name + "-decoy")
        if k == "O5":
            dl = with_prior(dl, fill["o5_prior"], uni, o5_share)
        cd, _ = letter_counts(letters, dl)
        real = {u: (n - e, n) for u, (e, n) in counts[k].items()}
        dec = {u: (n - e, n) for u, (e, n) in cd.items()}
        pr = paired(dec, real)                            # real accuracy minus decoy accuracy
        out["controls"][f"C2 {k}"] = dict(pr, **{"pass": pr["ci95"][0] > 0})
    # C6: the prior's commonest letter for every box
    top = ALPHABET[int(np.argmax(uni))]
    c6 = unit_counts(None, [L["unit"] for L in letters], [L["letter"] == top for L in letters])
    pr = paired(counts["O5"], c6)                         # prior-alone error minus O5 error
    out["controls"]["C6 prior alone"] = dict(pr, letter=top, **{"pass": pr["ci95"][0] > 0})
    # lines
    w = fill["lm_weight"]
    reads = {"L5": line_reads(letters, lines, post("O5"), lm, w, o5_share),
             "L-R1": line_reads(letters, lines, post("R1plain"), None, 0, None),
             "L-R1lm": line_reads(letters, lines, post("R1plain"), lm, fill["r1_lm_weight"], hc_share)}
    if (d / "lines-O2free.json").exists():
        reads["L-O2free"] = {k: tuple(v) for k, v in json.loads((d / "lines-O2free.json").read_text()).items()}
    flat = np.zeros((1, 24))
    reads["C7 lm alone"] = {ln["id"]: g.decode_boxes(np.repeat(flat, len(ln["boxes"]), 0), lm, 1.0, None)
                            for ln in lines if ln["scored"]}
    lcounts = {}
    for k, rd in reads.items():
        c = line_counts(lines, rd)
        lcounts[k] = c
        r, ci = boot_rate(c)
        out["lines"][k] = {"cer": r, "ci95": ci, "lines": len(rd), "units": len(c)}
    pr = paired(lcounts["L5"], lcounts["C7 lm alone"])
    out["controls"]["C7 lm alone"] = dict(pr, **{"pass": pr["ci95"][0] > 0})
    for name, (ours, rival, kind) in {"H1": ("O5", "R1", "l"), "H1b": ("O5", "R1p", "l"),
                                      "H2": ("L5", "L-R1", "c"), "H2b": ("L5", "L-R1lm", "c")}.items():
        src = counts if kind == "l" else lcounts
        pr = paired(src[rival], src[ours])                # ours minus rival
        out["comparisons"][name] = dict(pr, ours=ours, rival=rival, verdict=verdict(*pr["ci95"]))
    # per text and a sample of confidences for the record
    out["per_unit"] = {k: {u: list(v) for u, v in c.items()} for k, c in counts.items()}
    out["line_reads"] = {k: {i: v[0] for i, v in rd.items()} for k, rd in reads.items() if k in ("L5", "L-R1lm")}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for k in ("letters", "lines", "comparisons", "controls"):
        for n, v in out[k].items():
            print(k, n, {x: (round(y, 4) if isinstance(y, float) else y) for x, y in v.items()
                         if x in ("error", "cer", "ci95", "d", "verdict", "pass", "p", "accuracy")})


def unigram_logprior():
    from kit import greekglyphs as gg
    uni = gg.ngram_data()["unigram"]
    c = np.array([uni.get(ch, 0) for ch in ALPHABET], float) + 0.5
    return np.log(c / c.sum())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("post")
    s.add_argument("--work", required=True)
    s.add_argument("--part", choices=("dev", "test"), required=True)
    s.add_argument("--arm", required=True)
    s.add_argument("--variant", default="plain")
    s.add_argument("--r1")
    s.add_argument("--r1-config")
    s.add_argument("--o2")
    s.add_argument("--o5")
    s.add_argument("--decoy", action="store_true", help="C2: read tile-shuffled copies of every crop")
    s = sub.add_parser("acc")
    s.add_argument("--work", required=True)
    s.add_argument("--part", choices=("dev",), required=True)
    s.add_argument("--arm", required=True)
    s.add_argument("--prior", type=float, default=0.0)
    s = sub.add_parser("devlines")
    s.add_argument("--work", required=True)
    s.add_argument("--arm", required=True)
    s.add_argument("--lm", required=True)
    s.add_argument("--hellchar")
    s.add_argument("--o5")
    s.add_argument("--prior", type=float, default=0.0)
    s.add_argument("--weights", type=float, nargs="+", default=[0.0, 0.5, 1.0])
    s = sub.add_parser("freelines", help="L-O2free: letters-v2-ccby reads each scored line strip with no boxes")
    s.add_argument("--work", required=True)
    s.add_argument("--part", choices=("dev", "test"), required=True)
    s.add_argument("--o2", required=True)
    s = sub.add_parser("score")
    s.add_argument("--work", required=True)
    s.add_argument("--part", choices=("dev", "test"), required=True)
    s.add_argument("--fill", required=True, help="JSON: o5_runs, o5_prior, lm_weight, r1_lm_weight")
    s.add_argument("--lm", required=True)
    s.add_argument("--hellchar", required=True)
    s.add_argument("--out", required=True)
    a = p.parse_args(argv)
    {"post": cmd_post, "acc": cmd_acc, "devlines": cmd_devlines, "freelines": cmd_freelines,
     "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
