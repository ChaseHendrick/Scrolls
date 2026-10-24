#!/usr/bin/env python3
"""The Scroll Text Reader for agents: a command line with JSON output and an MCP server (stdio).

Three reads, each Model output (letter hypotheses for a person to check, never a reading of a scroll):

  letter      one letter box of a gray image: the 24 capitals ranked with probabilities (our classifier,
              scripts/letters/icdar_train.py, an ensemble of its run folders)
  line        a line whose letter boxes are given: the best string under the classifier and the Greek prose
              language model (scripts/letters/greek_lm.py), each letter's confidence and ranked alternatives
  line_free   a line strip with no boxes: letters-v2-ccby's CTC read (kit.letterread), greedy

  python scripts/letters/reader_api.py letter IMAGE [--box X0 Y0 X1 Y1] [--top 5]
  python scripts/letters/reader_api.py line IMAGE --boxes BOXES.json [--lm-weight W]
  python scripts/letters/reader_api.py line-free IMAGE [--box X0 Y0 X1 Y1] --letter-height H
  python scripts/letters/reader_api.py mcp                      # MCP over stdio (JSON-RPC 2.0, one message a line)
  python scripts/letters/reader_api.py fetch                    # download the released weights once

Models come from READER_RUNS (comma-separated run folders), READER_LM (the language model file) and READER_O2
(letters-v2-ccby weights), or the --runs, --lm and --o2 options; without them, from the released weights that
`fetch` put in READER_HOME (default ~/.cache/scrolls-kit/letterclass), listed with their SHA-256 in
letterclass-weights.json beside this script. Needs torch, timm, opencv-python-headless,
numpy and Pillow for `letter` and `line`; numpy and Pillow only for `line-free`.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

ALPHABET = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
NOTE = "Model output: letter hypotheses for a person to check, not a reading or transcription."
SUPPORTED = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MANIFEST = HERE / "letterclass-weights.json"


def home():
    return Path(os.environ.get("READER_HOME") or Path.home() / ".cache" / "scrolls-kit" / "letterclass")


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def released(root=None):
    """(comma-separated run folders, language model path) of the released weights under root, or (None, None)
    when any file is missing or differs from the manifest."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    root = Path(root or home())
    runs = []
    for name, files in m["runs"].items():
        for kind, f in files.items():
            p = root / name / ("model.pt" if kind == "model" else "config.json")
            if not p.exists() or _sha256(p) != f["sha256"]:
                return None, None
        runs.append(str(root / name))
    lm = root / m["lm"]["file"]
    return ",".join(runs), (str(lm) if lm.exists() and _sha256(lm) == m["lm"]["sha256"] else None)


def fetch(root=None, base_url=None, log=print):
    """Download every released file once into root, checking each SHA-256; returns released(root)."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    root = Path(root or home())
    base = base_url or m["base_url"]
    jobs = [(f, root / name / ("model.pt" if kind == "model" else "config.json"))
            for name, files in m["runs"].items() for kind, f in files.items()]
    jobs.append((m["lm"], root / m["lm"]["file"]))
    for f, dest in jobs:
        if dest.exists() and _sha256(dest) == f["sha256"]:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        log(f"fetch {f['file']} ({f['bytes'] / 1e6:.1f} MB)")
        with urllib.request.urlopen(base + f["file"], timeout=600) as r, open(part, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        if _sha256(part) != f["sha256"]:
            part.unlink()
            raise ValueError(f"{f['file']}: sha256 differs from letterclass-weights.json")
        part.replace(dest)
    return released(root)


def load_gray(path, box=None):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    a = np.asarray(Image.open(path).convert("L"))
    if box:
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        a = a[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
    if a.size == 0:
        raise ValueError("empty crop")
    return a


class Reader:
    def __init__(self, runs=None, lm=None, o2=None):
        self.runs = runs or os.environ.get("READER_RUNS")
        self.lm_path = lm or os.environ.get("READER_LM")
        if not self.runs or not self.lm_path:
            r, m = released()
            self.runs, self.lm_path = self.runs or r, self.lm_path or m
        self.o2 = o2 or os.environ.get("READER_O2")
        self._lm = None

    def posteriors(self, greys):
        import icdar_train as it
        if not self.runs:
            raise ValueError("no classifier: run reader_api.py fetch, or set READER_RUNS or --runs")
        return it.predict_folder(self.runs, greys)

    def lm(self):
        import greek_lm as g
        if self._lm is None:
            if not self.lm_path:
                raise ValueError("no language model: run reader_api.py fetch, or set READER_LM or --lm")
            self._lm = g.LM.load(self.lm_path)
        return self._lm

    def letter(self, image, box=None, top=5):
        lp = self.posteriors([load_gray(image, box)])[0]
        order = np.argsort(-lp)[:top]
        return {"letter": ALPHABET[order[0]], "probability": round(float(np.exp(lp[order[0]])), 4),
                "ranked": [{"letter": ALPHABET[k], "probability": round(float(np.exp(lp[k])), 4)} for k in order],
                "note": NOTE}

    def line(self, image, boxes, lm_weight=0.5, top=3):
        import greek_lm as g
        import icdar_train as it
        if not boxes:
            raise ValueError("line needs at least one box")
        full = load_gray(image)
        greys = [full[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)] for x0, y0, x1, y1 in boxes]
        lp = self.posteriors(greys)
        share = it.train_logprior(self.runs)
        text, conf, alts = g.decode_boxes(lp, self.lm(), lm_weight, share if lm_weight else None, top=top)
        ink = "".join(ALPHABET[k] for k in lp.argmax(1))
        return {"text": text, "ink_only": ink, "lm_weight": lm_weight,
                "letters": [{"letter": ch, "confidence": c, "alternatives": [{"letter": a, "probability": p}
                                                                              for a, p in al], "box": list(b)}
                            for ch, c, al, b in zip(text, conf, alts, boxes)], "note": NOTE}

    def line_free(self, image, box=None, letter_height=None):
        import ctc_letter as esa
        import realforms
        from kit import letterread as lr
        if not self.o2:
            raise ValueError("no line reader weights: set READER_O2 or --o2")
        g = load_gray(image, box)
        h = float(letter_height or max(8, g.shape[0] / 1.3))
        net = lr.LineNet(self.o2)
        ink = realforms.ink_from_photo(g)
        if ink is None:
            return {"text": "", "note": NOTE, "flat": True}
        band = esa.band_of(ink, net, net.letter_px / h)
        text = "".join(x[0] for x in lr.ctc_greedy(net.log_probs(band), net.alphabet)).replace("Ϲ", "Σ")
        return {"text": text, "letter_height": h, "note": NOTE}


TOOLS = [
    {"name": "read_letter", "description": "Rank the 24 Greek capitals for one letter box of a gray image "
     "(papyrus photograph or ink map). Model output, not a reading.",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string", "description": "path to a PNG, JPEG or TIFF"},
         "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
                 "description": "x0, y0, x1, y1 in pixels; omit for the whole image"},
         "top": {"type": "integer", "default": 5}}, "required": ["image"]}},
    {"name": "read_line", "description": "Read a line whose letter boxes are given: best string under the "
     "classifier and a Greek prose language model, with each letter's confidence and alternatives.",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string"},
         "boxes": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
         "lm_weight": {"type": "number", "default": 0.5}}, "required": ["image", "boxes"]}},
    {"name": "read_line_free", "description": "Read a line strip with no letter boxes (CTC line reader).",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string"}, "box": {"type": "array", "items": {"type": "number"}},
         "letter_height": {"type": "number"}}, "required": ["image"]}},
]


class ArgError(ValueError):
    pass


def call_tool(reader, name, args):
    spec = {t["name"]: t for t in TOOLS}.get(name)
    if spec is None:
        raise ArgError(f"unknown tool {name!r}")
    missing = [k for k in spec["inputSchema"].get("required", []) if k not in args]
    if missing:
        raise ArgError(f"{name}: missing {', '.join(missing)}")
    if name == "read_letter":
        return reader.letter(args["image"], args.get("box"), int(args.get("top", 5)))
    if name == "read_line":
        return reader.line(args["image"], args["boxes"], float(args.get("lm_weight", 0.5)))
    if name == "read_line_free":
        return reader.line_free(args["image"], args.get("box"), args.get("letter_height"))


def handle(reader, msg, state):
    """One JSON-RPC message to its response (None for a notification)."""
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:
        return None
    if method == "initialize":
        v = params.get("protocolVersion")
        state["version"] = v if v in SUPPORTED else SUPPORTED[0]
        res = {"protocolVersion": state["version"], "capabilities": {"tools": {}},
               "serverInfo": {"name": "scroll-text-reader", "version": "0.1.0"},
               "instructions": "Greek letter reader for papyrus photographs and ink maps. " + NOTE}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            out = call_tool(reader, params.get("name"), params.get("arguments") or {})
            res = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}], "isError": False}
            if (state.get("version") or "") >= "2025-06-18":
                res["structuredContent"] = out
        except ArgError as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": str(e)}}
        except Exception as e:                       # a tool error is a result the agent can read
            res = {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": res}


def serve(reader, inp=sys.stdin, out=sys.stdout):
    state = {}
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            out.flush()
            continue
        r = handle(reader, msg, state)
        if r is not None:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs")
    p.add_argument("--lm")
    p.add_argument("--o2")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("letter")
    s.add_argument("image")
    s.add_argument("--box", type=float, nargs=4)
    s.add_argument("--top", type=int, default=5)
    s = sub.add_parser("line")
    s.add_argument("image")
    s.add_argument("--boxes", required=True, help="JSON file: [[x0, y0, x1, y1], ...] left to right")
    s.add_argument("--lm-weight", type=float, default=0.5)
    s = sub.add_parser("line-free")
    s.add_argument("image")
    s.add_argument("--box", type=float, nargs=4)
    s.add_argument("--letter-height", type=float)
    sub.add_parser("mcp")
    s = sub.add_parser("fetch")
    s.add_argument("--into", help="folder (default READER_HOME or ~/.cache/scrolls-kit/letterclass)")
    a = p.parse_args(argv)
    if a.cmd == "fetch":
        runs, lm = fetch(a.into, log=lambda m: print(m, file=sys.stderr))
        print(json.dumps({"runs": runs, "lm": lm}, indent=1))
        return
    r = Reader(a.runs, a.lm, a.o2)
    if a.cmd == "mcp":
        real = sys.stdout
        sys.stdout = sys.stderr                     # stray prints must not corrupt the protocol
        serve(r, sys.stdin, real)
        return
    if a.cmd == "letter":
        out = r.letter(a.image, a.box, a.top)
    elif a.cmd == "line":
        out = r.line(a.image, json.loads(Path(a.boxes).read_text()), a.lm_weight)
    else:
        out = r.line_free(a.image, a.box, a.letter_height)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
