"""Synthetic demo still for kit run hf-rows: the command in the Scrolls terminal look, on a made-up bill.

    python scripts/media/hfrows_demo.py [--out docs/assets/hf-rows/hf-rows-demo.png]

It writes a scratch ledger, stands a fake Hugging Face Hub in for the billing API (made-up Job ids, flavors and
costs, no network), runs `kit run hf-rows` twice in a pseudo-terminal so kit.termstyle styles it, turns the colour
codes into HTML, and screenshots the page with Node's Playwright and its Chromium. Then it writes the sidecar.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import common  # noqa: E402

IDS = ["6a" + format(0xd00d0 + i, "x").rjust(22, "0") for i in range(5)]
BILL = {"usage": {"jobDetails": [
    {"jobId": IDS[0], "hardwareFlavor": "l4x1", "totalMinutes": 14, "totalCostMicroUsd": 186667,
     "startedAt": "2026-10-27T04:02:10.000Z", "completedAt": "2026-10-27T04:15:40.000Z"},
    {"jobId": IDS[1], "hardwareFlavor": "l4x1", "totalMinutes": 15, "totalCostMicroUsd": 200000,
     "startedAt": "2026-10-27T04:02:12.000Z", "completedAt": "2026-10-27T04:16:31.000Z"},
    {"jobId": IDS[2], "hardwareFlavor": "rtx-pro-6000", "totalMinutes": 9, "totalCostMicroUsd": 412500,
     "startedAt": "2026-10-27T04:20:03.000Z", "completedAt": "2026-10-27T04:28:44.000Z"},
    {"jobId": IDS[3], "hardwareFlavor": "cpu-upgrade", "totalMinutes": 6, "totalCostMicroUsd": 3000,
     "startedAt": "2026-10-27T04:30:00.000Z", "completedAt": "2026-10-27T04:35:20.000Z"},
    {"jobId": IDS[4], "hardwareFlavor": "rtx-pro-6000", "totalMinutes": 3, "totalCostMicroUsd": 137500,
     "startedAt": "2026-10-27T04:40:00.000Z", "completedAt": "1970-01-01T00:00:00.000Z"}]}}
RUNNER = """
import json, sys
sys.path.insert(0, {repo!r})
from kit import hfrows
bill, ids = json.loads({bill!r}), {ids!r}
def get(url, token):
    if url.endswith(hfrows.USAGE):
        return bill, None
    if url.endswith("/api/whoami-v2"):
        return {{"name": "demo"}}, None
    return [{{"id": i}} for i in ids], None
hfrows.http_get = get
from kit import termstyle
termstyle.install()                      # what `python -m kit` does on a terminal (termstyle.auto)
import runpy
sys.argv = ["kit"] + sys.argv[1:]
runpy.run_module("kit", run_name="__main__", alter_sys=True)
"""
SGR = re.compile(r"\x1b\[([0-9;]*)m")
OTHER = re.compile(r"\x1b\[[0-9;?]*[A-Za-ln-z]|\x1b\][^\x07]*\x07|\r")


def xterm256(n):
    base = ["#000000", "#cd3131", "#0dbc79", "#e5e510", "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
            "#666666", "#f14c4c", "#23d18b", "#f5f543", "#3b8eea", "#d670d6", "#29b8db", "#ffffff"]
    if n < 16:
        return base[n]
    if n < 232:
        n -= 16
        v = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (v[n // 36], v[(n // 6) % 6], v[n % 6])
    g = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (g, g, g)


def ansi_html(text):
    """HTML spans for SGR colour, bold and dim codes; other escape codes dropped."""
    out, style = [], {}
    pos = 0
    text = OTHER.sub("", text)
    for m in SGR.finditer(text):
        out.append(_span(html.escape(text[pos:m.start()]), style))
        pos = m.end()
        codes = [int(c) for c in m.group(1).split(";") if c] or [0]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                style = {}
            elif c == 1:
                style["bold"] = True
            elif c == 2:
                style["dim"] = True
            elif c == 38 and i + 2 < len(codes) and codes[i + 1] == 5:
                style["fg"] = xterm256(codes[i + 2])
                i += 2
            elif 30 <= c <= 37 or 90 <= c <= 97:
                style["fg"] = xterm256(c - 30 if c < 90 else c - 82)
            i += 1
    out.append(_span(html.escape(text[pos:]), style))
    return "".join(out)


def _span(s, style):
    if not s or not style:
        return s
    css = []
    if style.get("fg"):
        css.append(f"color:{style['fg']}")
    if style.get("bold"):
        css.append("font-weight:700")
    if style.get("dim"):
        css.append("opacity:.6")
    return f'<span style="{";".join(css)}">{s}</span>'


def pty_run(argv, env):
    cmd = " ".join(_q(a) for a in argv)
    p = subprocess.run(["script", "-q", "-c", cmd, "/dev/null"], capture_output=True, text=True, env=env,
                       cwd=REPO)
    return p.stdout


def _q(a):
    return "'" + a.replace("'", "'\\''") + "'"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "docs/assets/hf-rows/hf-rows-demo.png"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d) / "hf-jobs-costs.csv"
        ledger.write_text("date_time_utc,purpose,flavor,minutes,billed_usd,notes\n", encoding="utf-8")
        runner = Path(d) / "kitdemo.py"
        runner.write_text(RUNNER.format(repo=str(REPO), bill=json.dumps(BILL), ids=IDS), encoding="utf-8")
        env = dict(os.environ, HF_TOKEN="demo", COLUMNS="104", LINES="40", TERM="xterm-256color")
        args = ["run", "hf-rows", "--label", "run=lasagna-previews", "--purpose",
                "lasagna previews on public scans", "--ledger", "hf-jobs-costs.csv", "--public-generic"]
        shown = ["$ python -m kit run hf-rows --label run=lasagna-previews \\",
                 "    --purpose \"lasagna previews on public scans\" --public-generic"]
        first = pty_run([sys.executable, str(runner)] + args[:-2] + [str(ledger), "--public-generic"], env)
        second = pty_run([sys.executable, str(runner)] + args[:-2] + [str(ledger), "--public-generic"], env)
        csv_lines = ledger.read_text(encoding="utf-8").splitlines()
    clean = lambda s: s.replace(str(ledger), "docs/compute/hf-jobs-costs.csv").replace("kitdemo.py run", "kit run")
    body = (html.escape("\n".join(shown)) + "\n" + ansi_html(clean(first)) + "\n"
            + html.escape("$ # the same command again") + "\n" + ansi_html(clean(second))
            + "\n" + html.escape("$ head -4 docs/compute/hf-jobs-costs.csv") + "\n"
            + "\n".join(html.escape(l if len(l) < 118 else l[:115] + "...") for l in csv_lines[:4]))
    page = ("<!doctype html><meta charset=utf-8><style>body{margin:0;background:#0b0f14}"
            "pre{margin:0;padding:28px 32px;font:15px/1.5 'DejaVu Sans Mono',monospace;color:#d6deeb;"
            "white-space:pre}</style><pre>" + body + "</pre>")
    with tempfile.TemporaryDirectory() as d:
        page_path = Path(d) / "demo.html"
        page_path.write_text(page, encoding="utf-8")
        shot = ("const {chromium} = require('playwright'); (async () => { const b = await chromium.launch(); "
                "const p = await b.newPage({viewport: {width: 1100, height: 400}, deviceScaleFactor: 1}); "
                "await p.goto(process.argv[1]); await p.locator('pre').screenshot({path: process.argv[2]}); "
                "await b.close(); })().catch(e => { console.error(e); process.exit(1); });")
        subprocess.run(["node", "-e", shot, page_path.as_uri(), str(out)], check=True)
    common.size_guard(out)
    w, h = common.media_size(out)
    meta = {"label": "Synthetic demo",
            "alt": "A dark terminal running kit run hf-rows: the first run adds four rows and names one Job still "
                   "running, the same command again adds none, and the ledger's first lines show date, purpose, "
                   "flavor, minutes and billed USD.",
            "caption": "Synthetic demo: kit run hf-rows on a made-up Hugging Face bill (invented Job ids and costs, "
                       "no network). Four finished Jobs become rows once; the running one waits. No scan data.",
            "license": "Apache-2.0"}
    common.write_guard(meta["label"], out, meta)
    common.write_sidecar(out.with_suffix(".json"), meta,
                         [common.output_record(out, w, h, kind="still", format="png")],
                         command="python scripts/media/hfrows_demo.py", scripts=["hfrows_demo.py"])
    print(f"{out}: {w} x {h} px, {out.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
