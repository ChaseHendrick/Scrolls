"""Greek gap restoration benchmark: hosted text models against a Kneser-Ney letter model (public text only).

Test text: the second half of Philodemus, De Musica (Kemke), First1KGreek tlg1595.tlg221, normalised to 24
Greek capitals with lunate sigma and spaces as word boundaries. 190 items hide 1, 2, 3, 5 or 8 letters inside a
150-symbol window; 40 memorisation probes show 100 symbols and ask for the next letters. The baseline is an
order-8 Kneser-Ney letter model (kit/greekkn.py). Preregistration and result:
docs/prereg/2026-10-22-greek-restoration.md; frozen files: docs/evidence/greek-restoration-20261022/.

    python -m kit.greekfill corpus CORPUS.tsv PERSEUS_DIR FIRST1K_DIR   # normalised corpus from the TEI clones
    python -m kit.greekfill prep CORPUS.tsv OUT_DIR [--cache DIR]       # items, KN fills, manifest (no labels), key
    python -m kit.greekfill run OUT_DIR [--dry-run]                     # hosted models, Hugging Face router
    python -m kit.greekfill score OUT_DIR [--out PATH]                  # score.json from replies.jsonl
    python -m kit.greekfill check OUT_DIR                               # sha256 of each file against the frozen pins
    python -m kit.greekfill chart SCORE.json OUT.svg                    # letter accuracy by gap length

prep writes manifest.json (what the runner sends: prompts only), key.json (answers, never sent) and
baseline.json (the KN fills and continuations, fixed before any reply). run appends replies.jsonl. score reads
it. A fill is model output, not a reading. The benchmark code is ported unchanged from the code that ran the
frozen test on 22 October 2026, apart from comments, the command line, the dry run, score's --out, check and chart.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from . import greekkn as tl

SEED = 20261022
WINDOW = 150            # symbols per window (letters and spaces); the test text has 230 such windows
GAP_LENS = (1, 2, 3, 5, 8)
PER_LEN = 38            # gap items per length -> 190 items
MEMO_N = 40             # memorisation probe items
MEMO_PREFIX = 100
MEMO_LETTERS = 40
KN_ORDER = 8
KN_TRAIN = 16_000_000   # general training symbols: whole documents in corpus order until this many
WEIGHTS = (0.728, 0.272)  # general, Philodemus: fitted earlier by EM on the first half of De Musica
BEAM = 256
RIGHT = 24              # right-context symbols used to rescore a fill

MODELS = {
    "Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra": {"input": 0.09, "output": 0.55},
    "moonshotai/Kimi-K2-Instruct-0905:novita": {"input": 0.6, "output": 2.5},
    "deepseek-ai/DeepSeek-V3-0324:deepinfra": {"input": 0.24, "output": 0.9},
}
MAX_TOKENS = 48
CAP_USD = 1.20
PER_CALL_WORST = 0.0012  # 1,500 input tokens and 48 output tokens at the dearest listed rates

PROMPT_GAP = (
    "Below is a passage of ancient Greek prose by Philodemus, written in capital letters without accents "
    "or breathings; sigma is written Ϲ and spaces mark word boundaries. Exactly {n} consecutive "
    "letter{s} (spaces not counted) {are} missing where the passage shows [{n}]. Reply with only the {n} "
    "missing letter{s} in Greek capitals, no spaces, nothing else.\n\n{text}"
)
PROMPT_MEMO = (
    "Below is the start of a passage of ancient Greek prose by Philodemus, written in capital letters without "
    "accents or breathings; sigma is written Ϲ and spaces mark word boundaries. Continue the passage "
    "exactly as the original text goes on. Reply with only the next {n} letters in Greek capitals, no spaces, "
    "nothing else.\n\n{text}"
)

RULE = {
    "parsed_min": 0.90,         # share of a model's requests with at least one Greek letter
    "margin": 0.05,             # model letter accuracy minus KN letter accuracy
    "alpha": 0.05 / 3,          # one-sided, Bonferroni over three models
    "boot": 20000, "boot_seed": 0,
    "memo_max": 0.50,           # memorisation probe letter accuracy at or above this voids a win
}


# ---------------------------------------------------------------- text
def test_text(corpus):
    for line in open(corpus, encoding="utf-8"):
        d, t = line.rstrip("\n").split("\t", 1)
        if d.startswith("tlg1595") and d.split(".")[1] == "tlg221":
            half = len(t) // 2
            cut = t.rfind(" ", 0, half)
            return t[cut + 1:]
    raise SystemExit("De Musica (tlg1595.tlg221) not in corpus")


def letters(s):
    return "".join(c for c in s if c in tl.ALPHABET)


def normalise_reply(r):
    s = unicodedata.normalize("NFD", r or "").upper()
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("Σ", "Ϲ").replace("ς", "Ϲ").replace("ϲ", "Ϲ")
    return letters(s)


def letter_hits(guess, truth):
    """Position-wise letter matches over the truth's letters (missing or extra letters do not help)."""
    return sum(1 for a, b in zip(guess, truth) if a == b)


# ---------------------------------------------------------------- items
def make_items(text, rng):
    """Non-overlapping windows; a gap window hides L letters starting 60 to 90 symbols in, a memo window
    shows its first MEMO_PREFIX symbols and keeps up to MEMO_LETTERS following letters as truth."""
    n_gap = PER_LEN * len(GAP_LENS)
    span = WINDOW
    starts = np.arange(0, len(text) - span, span)
    pick = rng.choice(len(starts), size=n_gap + MEMO_N, replace=False)
    lens = np.repeat(GAP_LENS, PER_LEN)
    rng.shuffle(lens)
    gaps, memos = [], []
    for j, si in enumerate(pick[:n_gap]):
        w = text[starts[si]:starts[si] + span]
        L = int(lens[j])
        a = int(rng.integers(60, 91))
        while a < len(w) and w[a] == " ":
            a += 1
        # take L letters from a, skipping spaces (spaces inside the gap are hidden too)
        b, got = a, 0
        while got < L:
            if w[b] != " ":
                got += 1
            b += 1
        left, mid, right = w[:a], w[a:b], w[b:]
        gaps.append({"id": "g%03d" % j, "L": L, "left": left, "right": right[:WINDOW - len(left) - L],
                     "truth": letters(mid)})
    for j, si in enumerate(pick[n_gap:]):
        w = text[starts[si]:starts[si] + span]
        nxt = letters(w[MEMO_PREFIX:])[:MEMO_LETTERS]
        memos.append({"id": "m%03d" % j, "prefix": w[:MEMO_PREFIX], "truth": nxt})
    return gaps, memos


# ---------------------------------------------------------------- KN baseline
def build_kn(corpus, cache=None):
    if cache and Path(cache, "general.npz").exists():
        g = tl.KNModel.load(Path(cache, "general.npz"))
        p = tl.KNModel.load(Path(cache, "phil.npz"))
    else:
        gen, ntr = [], 0
        phil_train = None
        for line in open(corpus, encoding="utf-8"):
            d, t = line.rstrip("\n").split("\t", 1)
            if d.startswith("tlg1595"):
                if d.split(".")[1] == "tlg370":
                    phil_train = t
                continue
            b = int(hashlib.sha256(d.encode()).hexdigest(), 16) % 100
            if b >= 6 and ntr < KN_TRAIN:
                gen.append(t)
                ntr += len(t)
        g = tl.KNModel(KN_ORDER).fit_texts(gen)
        p = tl.KNModel(KN_ORDER).fit_texts([phil_train])
        if cache:
            Path(cache).mkdir(parents=True, exist_ok=True)
            g.save(Path(cache, "general.npz"))
            p.save(Path(cache, "phil.npz"))
    return tl.MixtureLM([tl.NgramLM(g), tl.NgramLM(p)], WEIGHTS)


def kn_fill(lm, left, right, L):
    """Best L-letter fill: beam search on the left context, rescored with the right context."""
    pad = tl.BOUND * KN_ORDER
    beams = [("", 0.0)]
    letters_idx = [tl.IDX[c] for c in tl.ALPHABET]
    for _ in range(L):
        hist = [pad + left + s for s, _ in beams]
        lp = lm.next_logprobs(hist)
        cand = []
        for (s, sc), row in zip(beams, lp):
            for i in letters_idx:
                cand.append((s + tl.SYMBOLS[i], sc + float(row[i])))
        cand.sort(key=lambda x: -x[1])
        beams = cand[:BEAM]
    tail = right[:RIGHT]
    scored = [(lm.score(left + s + tail), s) for s, _ in beams]
    best = max(scored)[1]
    return best


def kn_continue(lm, prefix, n):
    pad = tl.BOUND * KN_ORDER
    h, out = pad + prefix, ""
    while len(letters(out)) < n:
        row = lm.next_logprobs([h])[0]
        ch = tl.SYMBOLS[int(np.argmax(row))]
        if ch == tl.BOUND and h.endswith(tl.BOUND):
            ch = tl.SYMBOLS[int(np.argsort(row)[-2])]
        out += ch
        h += ch
    return letters(out)[:n]


# ---------------------------------------------------------------- prep
def gap_prompt(it):
    n = it["L"]
    return PROMPT_GAP.format(n=n, s="" if n == 1 else "s", are="is" if n == 1 else "are",
                             text=it["left"] + "[%d]" % n + it["right"])


def prep(corpus, out, cache=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    text = test_text(corpus)
    gaps, memos = make_items(text, rng)
    lm = build_kn(corpus, cache)
    base = {"gaps": {it["id"]: kn_fill(lm, it["left"], it["right"], it["L"]) for it in gaps},
            "memos": {it["id"]: kn_continue(lm, it["prefix"], len(it["truth"])) for it in memos}}
    reqs = []
    for m in MODELS:
        for it in gaps:
            reqs.append({"id": "%s|%s" % (m, it["id"]), "model": m, "prompt": gap_prompt(it)})
        for it in memos:
            reqs.append({"id": "%s|%s" % (m, it["id"]), "model": m,
                         "prompt": PROMPT_MEMO.format(n=len(it["truth"]), text=it["prefix"])})
    rng.shuffle(reqs)
    manifest = {"models": MODELS, "max_tokens": MAX_TOKENS, "cap_usd": CAP_USD,
                "per_call_worst_usd": PER_CALL_WORST, "requests": reqs}
    key = {"seed": SEED, "text_letters": len(letters(text)), "gaps": gaps, "memos": memos}
    for name, obj in (("manifest.json", manifest), ("key.json", key), ("baseline.json", base)):
        (out / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    pins = {n: hashlib.sha256((out / n).read_bytes()).hexdigest()
            for n in ("manifest.json", "key.json", "baseline.json")}
    acc = sum(letter_hits(base["gaps"][g["id"]], g["truth"]) for g in gaps) / sum(g["L"] for g in gaps)
    print(json.dumps({"requests": len(reqs), "gaps": len(gaps), "memos": len(memos), "pins": pins,
                      "kn_letter_acc": round(acc, 4)}, indent=1))
    return pins


# ---------------------------------------------------------------- score
def boot_lower(diff_by_item, w_by_item, q, n, seed):
    """Lower q-quantile of the letter-weighted mean difference, resampling items."""
    rng = np.random.default_rng(seed)
    d, w = np.asarray(diff_by_item, float), np.asarray(w_by_item, float)
    idx = rng.integers(0, len(d), size=(n, len(d)))
    stats = (d[idx] * w[idx]).sum(1) / w[idx].sum(1)
    return float(np.quantile(stats, q))


def verdict(per_model):
    rows, winners, memorised, parsed_bad = {}, [], [], []
    for m, r in per_model.items():
        ok_parse = r["parsed_share"] >= RULE["parsed_min"]
        win = ok_parse and r["diff"] >= RULE["margin"] and r["diff_lower"] > 0
        mem = r["memo_acc"] >= RULE["memo_max"]
        rows[m] = {"parse_ok": ok_parse, "beats_kn": win, "memorised": mem}
        if not ok_parse:
            parsed_bad.append(m)
        if win and not mem:
            winners.append(m)
        elif win and mem:
            memorised.append(m)
    if len(parsed_bad) == len(per_model):
        v = "VOID"
    elif winners:
        v = "PASS"
    elif memorised:
        v = "INCONCLUSIVE"
    else:
        v = "FAIL"
    return v, rows, winners


def score(out, dest=None):
    """Score replies.jsonl in out against key.json and baseline.json; write dest (default out/score.json)."""
    out = Path(out)
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    base = json.loads((out / "baseline.json").read_text(encoding="utf-8"))
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    rep = {}
    for line in (out / "replies.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        rep[r["id"]] = r
    gaps, memos = key["gaps"], key["memos"]
    kn_hits = [letter_hits(base["gaps"][g["id"]], g["truth"]) for g in gaps]
    Ls = [g["L"] for g in gaps]
    kn_acc = sum(kn_hits) / sum(Ls)
    kn_memo = float(np.mean([letter_hits(base["memos"][m["id"]], m["truth"]) / len(m["truth"]) for m in memos]))
    per_model, usd = {}, 0.0
    for m in man["models"]:
        hits, parsed, n = [], 0, 0
        by_len = {L: [0, 0, 0] for L in GAP_LENS}  # letters hit, letters, exact gaps
        for g in gaps:
            r = rep.get("%s|%s" % (m, g["id"]))
            guess = normalise_reply(r["reply"]) if r else ""
            n += 1
            parsed += bool(guess)
            h = letter_hits(guess, g["truth"])
            hits.append(h)
            bl = by_len[g["L"]]
            bl[0] += h
            bl[1] += g["L"]
            bl[2] += int(guess == g["truth"])
        mm = []
        for it in memos:
            r = rep.get("%s|%s" % (m, it["id"]))
            guess = normalise_reply(r["reply"]) if r else ""
            n += 1
            parsed += bool(guess)
            mm.append(letter_hits(guess, it["truth"]) / len(it["truth"]))
        acc = sum(hits) / sum(Ls)
        diff_item = [(h - k) / L for h, k, L in zip(hits, kn_hits, Ls)]
        per_model[m] = {
            "letter_acc": round(acc, 4), "kn_letter_acc": round(kn_acc, 4), "diff": round(acc - kn_acc, 4),
            "diff_lower": round(boot_lower(diff_item, Ls, RULE["alpha"], RULE["boot"], RULE["boot_seed"]), 4),
            "parsed_share": round(parsed / n, 4), "memo_acc": round(float(np.mean(mm)), 4),
            "by_len": {str(L): {"acc": round(v[0] / v[1], 4), "exact": round(v[2] / (v[1] / L), 4)}
                       for L, v in by_len.items()},
        }
    for r in rep.values():
        usd += r.get("usd", 0.0)
    kn_by_len = {}
    for L in GAP_LENS:
        hl = [(h, g) for h, g in zip(kn_hits, gaps) if g["L"] == L]
        kn_by_len[str(L)] = {"acc": round(sum(h for h, _ in hl) / (L * len(hl)), 4),
                             "exact": round(sum(base["gaps"][g["id"]] == g["truth"] for _, g in hl) / len(hl), 4)}
    v, rows, winners = verdict(per_model)
    res = {"verdict": v, "winners": winners, "checks": rows, "per_model": per_model,
           "kn": {"letter_acc": round(kn_acc, 4), "memo_acc": round(kn_memo, 4), "by_len": kn_by_len},
           "replies": len(rep), "requests": len(man["requests"]), "priced_usd": round(usd, 4), "rule": RULE}
    Path(dest or out / "score.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return res


# ---------------------------------------------------------------- hosted models (standard library only)
URL = "https://router.huggingface.co/v1/chat/completions"

# sha256 of the frozen files (docs/evidence/greek-restoration-20261022/) and of the corpus that made them
PINS = {
    "manifest.json": "ed544db8e3faaf0642217589d0dba44bac5466940145a5846747a82f6f401991",
    "key.json": "177c43b61f77734da5fe88784a75dc268f3404e43af8dbe6e64f97cb93a35405",
    "baseline.json": "99175529f2e39545c8e321aa3c3aa03904bfa9ed0cdaa0cf0ca3d8c5c63b7e0a",
    "replies.jsonl": "5e59715ef56247a06699005d85ed3870454c864ad1c21d9041c6d1819e842c59",
    "score.json": "6a50f13a53af097a5e92e247b5d10faa64e25253126c26c2dffce19e321680a2",
}
PREP_FILES = ("manifest.json", "key.json", "baseline.json")
CORPUS_SHA256 = "5c7c4684b7a4515ebd8840b963757b5a7680cfd2c986375a487b3d66bdb594bf"
SOURCES = {
    "PerseusDL/canonical-greekLit": "0189b9c8d8d1f148133f2f0af309b4ee90ea4332",
    "OpenGreekAndLatin/First1KGreek": "03776b39f4047c5cff06f5296fae4b2bae4b08fb",
}


def token():
    """The Hugging Face token from HF_TOKEN or the huggingface CLI's saved token file; never printed or written."""
    t = os.environ.get("HF_TOKEN")
    if t:
        return t.strip()
    for p in (Path.home() / ".cache/huggingface/token", Path.home() / ".huggingface/token"):
        if p.is_file():
            return p.read_text().strip()
    raise SystemExit("no Hugging Face token: set HF_TOKEN or run `huggingface-cli login`")


def send(payload, tok, tries=3):
    """POST one chat request to the router; (reply JSON, None) or (None, error). 429 waits and retries."""
    for k in range(tries):
        req = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                              "User-Agent": "scrolls-greekfill/1"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read()), None
        except urllib.error.HTTPError as exc:
            err = f"HTTP {exc.code}: {exc.read()[:300]!r}"
            if exc.code == 429 and k + 1 < tries:
                time.sleep(10 * (k + 1))
                continue
            if exc.code < 500 and exc.code != 429:
                return None, err
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            err = repr(exc)
        time.sleep(5 * (k + 1))
    return None, err


def body(m, req):
    """The chat request for one manifest request: its own model and prompt, temperature 0."""
    return {"model": req["model"], "max_tokens": m.get("max_tokens", 48), "temperature": 0,
            "messages": [{"role": "user", "content": req["prompt"]}]}


def priced(m, model, usage):
    """USD of one reply from its reported usage and the manifest's price table; the reserve without usage."""
    if not usage or "prompt_tokens" not in usage:
        return m["per_call_worst_usd"]
    p = m["models"][model]
    return (usage.get("prompt_tokens", 0) * p["input"] + usage.get("completion_tokens", 0) * p["output"]) / 1e6


def run(d, limit=None, per_model=None, dry_run=False):
    """Send the manifest's unanswered requests in order, one at a time, appending d/replies.jsonl.

    Stops before the priced cost could pass the manifest's cap (a request without reported usage counts at
    the worst-case reserve), stops after 3 failed tries of one request, and resumes without re-asking an
    answered request. per_model sends only the first N unanswered requests of each model (smoke and pilot).
    dry_run sends nothing and needs no token: it counts what would be sent and its worst-case cost.
    Returns {"sent", "spent_usd", "answered", "requests", "stopped"}; stopped is None, "cap" or "failed".
    """
    d = Path(d)
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    rp = d / "replies.jsonl"
    done = {}
    if rp.is_file():
        for line in rp.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["id"]] = r
    spent = sum(r.get("usd", 0.0) for r in done.values())
    if dry_run:
        todo, by_model = 0, {}
        for req in m["requests"]:
            if req["id"] in done:
                continue
            if limit is not None and todo >= limit:
                break
            if per_model is not None and by_model.get(req["model"], 0) >= per_model:
                continue
            todo += 1
            by_model[req["model"]] = by_model.get(req["model"], 0) + 1
        worst = todo * m["per_call_worst_usd"]
        res = {"dry_run": True, "would_send": todo, "by_model": by_model, "spent_usd": round(spent, 4),
               "worst_case_usd": round(worst, 4), "cap_usd": m["cap_usd"],
               "fits_cap": spent + worst <= m["cap_usd"], "answered": len(done), "requests": len(m["requests"])}
        print(json.dumps(res, indent=1))
        return res
    tok = token()
    sent, by_model, stopped = 0, {}, None
    with rp.open("a", encoding="utf-8") as f:
        for req in m["requests"]:
            if req["id"] in done:
                continue
            if limit is not None and sent >= limit:
                break
            if per_model is not None and by_model.get(req["model"], 0) >= per_model:
                continue
            if spent + m["per_call_worst_usd"] > m["cap_usd"]:
                print(f"stop: priced cost {spent:.4f} plus worst {m['per_call_worst_usd']} would pass {m['cap_usd']}")
                stopped = "cap"
                break
            out, err = send(body(m, req), tok)
            if out is None:
                spent += m["per_call_worst_usd"]
                print("request failed, stopping:", req["id"], err)
                stopped = "failed"
                break
            u = out.get("usage", {})
            usd = priced(m, req["model"], u)
            reply = (out["choices"][0]["message"].get("content") or "").strip()
            f.write(json.dumps({"id": req["id"], "reply": reply, "usage": u, "usd": usd, "t": time.time()},
                               ensure_ascii=False) + "\n")
            f.flush()
            spent += usd
            sent += 1
            by_model[req["model"]] = by_model.get(req["model"], 0) + 1
            if sent % 50 == 0:
                print(sent, req["id"], f"{spent:.4f}", flush=True)
    print(f"done: sent {sent}, priced cost {spent:.4f} USD; answered {len(done) + sent} of {len(m['requests'])}")
    return {"sent": sent, "spent_usd": round(spent, 4), "answered": len(done) + sent,
            "requests": len(m["requests"]), "stopped": stopped}


# ---------------------------------------------------------------- pins
def sha256_file(path):
    """Hex sha256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_pins(d):
    """Each pinned file in d against PINS. ok needs the three prep files present and every present file equal."""
    d = Path(d)
    files, ok = {}, True
    for name, pin in PINS.items():
        p = d / name
        if not p.is_file():
            files[name] = {"present": False, "pinned": pin, "match": None}
            if name in PREP_FILES:
                ok = False
            continue
        h = sha256_file(p)
        files[name] = {"present": True, "sha256": h, "pinned": pin, "match": h == pin}
        ok = ok and h == pin
    return {"ok": ok, "files": files}


# ---------------------------------------------------------------- chart
CHART_COLORS = {  # validated categorical slots 1 to 4, light and dark surface
    "light": ("#2a78d6", "#eb6834", "#1baf7a", "#eda100"),
    "dark": ("#3987e5", "#d95926", "#199e70", "#c98500"),
}


def _short(model):
    return model.split("/", 1)[-1].split(":", 1)[0]


def chart_svg(res):
    """SVG bar chart of gap letter accuracy by gap length for KN and each model, from a score.json dict."""
    arms = [("Kneser-Ney letter model (ours)", res["kn"]["letter_acc"], res["kn"]["by_len"])]
    for m in sorted(res["per_model"], key=lambda k: -res["per_model"][k]["letter_acc"]):
        arms.append((_short(m), res["per_model"][m]["letter_acc"], res["per_model"][m]["by_len"]))
    W, H = 760, 460
    x0, x1, y0, y1 = 64, W - 24, 136, H - 56
    lens = [str(L) for L in GAP_LENS]
    group = (x1 - x0) / len(lens)
    bw, gap = 22, 2
    css = ["svg{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}",
           ".bg{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.grid{stroke:#e4e3df}.axis{stroke:#9c9a94}"]
    css += [".s%d{fill:%s}" % (i, c) for i, c in enumerate(CHART_COLORS["light"])]
    dark = [".bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.grid{stroke:#33332f}.axis{stroke:#6f6e68}"]
    dark += [".s%d{fill:%s}" % (i, c) for i, c in enumerate(CHART_COLORS["dark"])]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
           'aria-labelledby="t d">' % (W, H, W, H),
           "<title id=\"t\">Gap letter accuracy by gap length</title>",
           "<desc id=\"d\">Greek gap restoration on Philodemus, De Musica: share of hidden letters restored in "
           "place, by number of hidden letters, for a Kneser-Ney letter model and three hosted text models. "
           "Model output. 38 gaps per length.</desc>",
           "<style>%s@media (prefers-color-scheme: dark){%s}</style>" % ("".join(css), "".join(dark)),
           '<rect class="bg" width="%d" height="%d" rx="8"/>' % (W, H),
           '<text class="t1" x="24" y="34" font-size="18" font-weight="600">Gap letter accuracy by gap length</text>',
           '<text class="t2" x="24" y="56" font-size="13">Philodemus, De Musica, second half: 38 gaps per length, '
           'one run, 22 October 2026. Model output.</text>']
    for i, (name, acc, _) in enumerate(arms):  # legend, two columns, with each arm's overall accuracy
        lx, ly = 24 + (i % 2) * 360, 74 + (i // 2) * 22
        out.append('<rect class="s%d" x="%d" y="%d" width="12" height="12" rx="2"/>' % (i, lx, ly))
        out.append('<text class="t2" x="%d" y="%d" font-size="12">%s, all gaps %.3f</text>' % (lx + 17, ly + 11, name, acc))
    for k in range(5):
        v = k / 4
        y = y1 - v * (y1 - y0)
        out.append('<line class="%s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % ("axis" if k == 0 else "grid",
                                                                              x0, x1, y, y))
        out.append('<text class="t2" x="%d" y="%.1f" font-size="12" text-anchor="end">%.2f</text>' % (x0 - 8, y + 4, v))
    for gi, L in enumerate(lens):
        cx = x0 + group * (gi + 0.5)
        left = cx - (len(arms) * bw + (len(arms) - 1) * gap) / 2
        for i, (name, _, by) in enumerate(arms):
            v = by[L]["acc"]
            h = max(v * (y1 - y0), 0.5)
            x, y, r = left + i * (bw + gap), y1 - h, min(4, h / 2)
            out.append('<path class="s%d" d="M%.1f %.1fv%.1fa%.1f %.1f 0 0 1 %.1f %.1fh%.1fa%.1f %.1f 0 0 1 %.1f %.1f'
                       'v%.1fz"><title>%s, %s letter%s: %.3f</title></path>'
                       % (i, x, y1, -(h - r), r, r, r, -r, bw - 2 * r, r, r, r, r, h - r,
                          name, L, "" if L == "1" else "s", v))
        out.append('<text class="t1" x="%.1f" y="%d" font-size="13" text-anchor="middle">%s</text>' % (cx, y1 + 20, L))
    out.append('<text class="t2" x="%.1f" y="%d" font-size="12" text-anchor="middle">letters hidden in the gap</text>'
               % ((x0 + x1) / 2, y1 + 40))
    out.append('<text class="t2" transform="translate(18 %.1f) rotate(-90)" font-size="12" text-anchor="middle">'
               'letter accuracy</text>' % ((y0 + y1) / 2))
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- command line
def build_parser():
    ap = argparse.ArgumentParser(prog="python -m kit.greekfill",
                                 description="Greek gap restoration benchmark: hosted text models against a "
                                             "Kneser-Ney letter model on Philodemus, De Musica.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("corpus", help="build the normalised corpus from TEI clones")
    c.add_argument("out", metavar="CORPUS.tsv", help="output corpus file")
    c.add_argument("roots", metavar="ROOT", nargs="+", help="clone folders, Perseus first, then First1KGreek")
    c.add_argument("--nproc", type=int, default=None, help="worker processes (default: NPROC or 3)")
    p = sub.add_parser("prep", help="items, KN baseline, manifest and key")
    p.add_argument("corpus", metavar="CORPUS.tsv", help="the corpus from the corpus command")
    p.add_argument("out", metavar="OUT_DIR", help="folder for manifest.json, key.json and baseline.json")
    p.add_argument("--cache", default=None, help="folder to save or reuse the fitted KN models")
    r = sub.add_parser("run", help="send the manifest's requests to the hosted models")
    r.add_argument("dir", metavar="OUT_DIR", help="folder with manifest.json; replies.jsonl is appended")
    r.add_argument("--limit", type=int, default=None, help="send at most N requests")
    r.add_argument("--per-model", type=int, default=None, help="send at most N unanswered requests per model")
    r.add_argument("--dry-run", action="store_true", help="count requests and worst-case cost; send nothing")
    s = sub.add_parser("score", help="score replies.jsonl and print the verdict")
    s.add_argument("dir", metavar="OUT_DIR", help="folder with manifest.json, key.json, baseline.json, replies.jsonl")
    s.add_argument("--out", default=None, help="write the score here instead of OUT_DIR/score.json")
    k = sub.add_parser("check", help="sha256 of each file against the frozen pins")
    k.add_argument("dir", metavar="OUT_DIR", help="folder to check")
    h = sub.add_parser("chart", help="SVG chart of letter accuracy by gap length from a score.json")
    h.add_argument("score", metavar="SCORE.json", help="a score.json written by score")
    h.add_argument("out", metavar="OUT.svg", help="the SVG file to write")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "corpus":
        stats = tl.build_corpus(a.out, a.roots, a.nproc)
        stats["matches_frozen"] = stats["sha256"] == CORPUS_SHA256
        print(json.dumps(stats))
        return 0
    if a.cmd == "prep":
        prep(a.corpus, a.out, a.cache)
        return 0
    if a.cmd == "run":
        res = run(a.dir, a.limit, a.per_model, a.dry_run)
        if a.dry_run:
            return 0 if res["fits_cap"] else 3
        return 0 if res["stopped"] is None else 3
    if a.cmd == "score":
        score(a.dir, a.out)
        return 0
    if a.cmd == "chart":
        svg = chart_svg(json.loads(Path(a.score).read_text(encoding="utf-8")))
        Path(a.out).write_text(svg, encoding="utf-8")
        print(json.dumps({"out": a.out, "bytes": len(svg.encode("utf-8"))}))
        return 0
    res = check_pins(a.dir)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
