"""Connect your tool: one panel per Hugging Face Space that says where its data lives and how other tools read it.

Chase asked on 24 October 2026 for every Space of his, now and future, to connect its data easily to villa, villa's
tools and other people's tools.

Every Space keeps a short connect.json (schema space-connect/1) with the data sources the page shows. This module
turns it into two files that ship with the Space:

  connect.html   a self-contained HTML fragment (scoped CSS, no script tag; copy buttons are inline handlers), which a
                 static page splices in between the markers below and a Gradio app shows with gr.HTML
  CONNECT.md     the same text as Markdown, for the Space's file browser and for agents

  python -m kit spaceconnect render DIR [DIR ...]   write connect.html and CONNECT.md from DIR/connect.json, and splice
                                                    the panel into DIR's page when it has the markers
  python -m kit spaceconnect check [--live]         every Space in spaces/connect/spaces.json: valid spec, outputs up
                                                    to date, page wired; --live also fetches every URL (network)
  python -m kit spaceconnect run [--python PY] [--vesuvius-python PY]   run every Python and shell snippet of every
                                                    running source against the live data (network; logged out); the
                                                    Pythons need zarr, fsspec, aiohttp, huggingface_hub, datasets,
                                                    pandas, numpy, tifffile and gradio_client, and vesuvius[volume-only]
  python -m kit spaceconnect new DIR --space OWNER/NAME   a starter connect.json

A spec:
  {"schema": "space-connect/1", "space": "SharpMeow/umbilici", "title": "Umbilici", "checked": "2026-10-24",
   "intro": "One sentence on what the data is.",                                      (optional)
   "sources": [SOURCE, ...]}
A SOURCE has "id", "title", "kind", "url", "license" and an optional "note"; each kind adds its own fields:
  ome-zarr    an OME-Zarr group read over HTTPS: "zarr_format" (2 or 3), "example": {"level": "2", "start": [z, y, x]},
              optional "ng_path" (a level folder for neuroglancer, which refuses villa's "pixel" unit on lasagna roots)
  hf-dataset  a public Hugging Face dataset: "repo", "file" (one example file), optional "configs", "table", "size"
  file        one file at a URL: "format" (json, csv, image or bytes)
  tifxyz      a tifxyz surface folder (x.tif, y.tif, z.tif, meta.json) at a URL
  s3-prefix   a folder of the open-data bucket: "url" is the HTTPS bucket root, "prefix" the folder, "browse" a page
  gradio-api  a Gradio Space's API: "space", "host", "status" (running or paused), "endpoints": [{"api", "args"}],
              optional "zerogpu": true (a ZeroGPU Space: the snippets pass the caller's own Hugging Face token, so a
              call spends the caller's GPU quota and not the small logged-out one)
  page-api    a static page's own API: "links": [{"label", "url"}], optional "embed"
A source may list "tools" to show only some of its kind's tools.

Only tool and kind pairs that were run against real public data get "tested" (the date in TESTED); pairs taken from
villa's source say so ("from villa's source"). A source hosted on huggingface.co that copies scan data must not come
from an EduceLab-Scrolls scan made before 2025 (Scrolls 1 to 4 and Fragments 1 to 6 are under the EduceLab terms,
which forbid redistribution; villa's vesuvius README): give such a source "scroll" and "scan_year", and check() refuses
it. Link those scans at the open data instead.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SCHEMA = "space-connect/1"
ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "spaces" / "connect" / "spaces.json"
START, END = "<!-- space-connect:start -->", "<!-- space-connect:end -->"
OPEN_DATA = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
VILLA = "ScrollPrize/villa 6f20245"  # the villa commit the VC3D steps were read from (23 Oct 2026)
NEUROGLANCER = "https://neuroglancer-demo.appspot.com/"

# Scrolls 1 to 4 under the EduceLab-Scrolls terms (no redistribution); their pre-2025 scans are never rehosted.
EDUCELAB_SCROLLS = {"PHercParis4", "PHercParis3", "PHerc0332", "PHerc1667"}

# What was run, and with what, before a snippet could say "tested" (24 Oct 2026, cloud container, Python 3.13).
TESTED = {
    ("ome-zarr", "zarr"): "2026-10-24: zarr 3.4.1 read a 64^3 block of PHerc0125 (open data) over HTTPS in 1.1 s",
    ("ome-zarr", "vesuvius"): "2026-10-24: vesuvius 0.2.4 (PyPI) read one pyramid level of PHerc0125 by HTTPS URL",
    ("ome-zarr", "neuroglancer"): "2026-10-24: neuroglancer-demo.appspot.com showed PHerc0125 from this kind of link",
    ("ome-zarr", "curl"): "2026-10-24: the open-data bucket answers with Access-Control-Allow-Origin *",
    ("hf-dataset", "hub"): "2026-10-24: huggingface_hub 1.x, logged out, SharpMeow/vesuvius-center-lines",
    ("hf-dataset", "datasets"): "2026-10-24: datasets 5.1.0, logged out, SharpMeow/vesuvius-center-lines",
    ("hf-dataset", "pandas"): "2026-10-24: pandas with an hf:// path, logged out",
    ("hf-dataset", "cli"): "2026-10-24: hf download, logged out",
    ("hf-dataset", "curl"): "2026-10-24: curl, logged out",
    ("file", "curl"): "2026-10-24: curl",
    ("file", "python"): "2026-10-24: Python standard library",
    ("tifxyz", "python"): "2026-10-24: PHerc0841 w00 mesh (open data), numpy and tifffile",
    ("s3-prefix", "python"): "2026-10-24: open-data bucket listing over HTTPS",
    ("gradio-api", "python"): "2026-10-24: gradio_client 2.7.2 against SharpMeow/crackle-check, logged out",
    ("gradio-api", "curl"): "2026-10-24: Gradio 6.28 call API on SharpMeow/crackle-check",
    ("gradio-api", "mcp"): "2026-10-24: /gradio_api/mcp/sse and /gradio_api/mcp/schema answer on SharpMeow/crackle-check",
    ("page-api", "links"): "2026-10-24: every link answers",
}
FROM_VILLA = {("ome-zarr", "vc3d"): f"{VILLA}: File > Attach Remote Zarr (MenuActionController.cpp)"}

KIND_FIELDS = {
    "ome-zarr": [], "hf-dataset": ["repo", "file"], "file": [], "tifxyz": [], "s3-prefix": ["prefix"],
    "gradio-api": ["space", "host", "endpoints"], "page-api": ["links"],
}


def _q(s: str) -> str:
    return json.dumps(s)


def _zarr(src):
    ex = src.get("example", {})
    level, (z, y, x) = str(ex.get("level", "0")), ex.get("start", [0, 0, 0])
    return level, z, y, x


def neuroglancer_link(url: str, name: str) -> str:
    """A neuroglancer-demo link that opens an OME-Zarr URL (zarr v2 or v3) as an image layer."""
    state = {"layers": [{"type": "image", "source": f"zarr://{url.rstrip('/')}/", "name": name}], "layout": "4panel"}
    return NEUROGLANCER + "#!" + urllib.parse.quote(json.dumps(state, separators=(",", ":")), safe="")


def _tools(src):
    """The (tool id, label, language, code) list for one source."""
    k, url = src["kind"], src["url"]
    out = []
    if k == "ome-zarr":
        level, z, y, x = _zarr(src)
        v = src.get("zarr_format", 2)
        out.append(("zarr", "Python (zarr)", "python",
                    f'# pip install "zarr>=3" fsspec aiohttp\nimport zarr\n\n'
                    f'root = zarr.open_group({_q(url)}, mode="r")  # OME-Zarr, zarr v{v}\n'
                    f'a = root[{_q(level)}]  # level 0 is full resolution; level L is 2**L times coarser\n'
                    f'print(a.shape, a.dtype, a.chunks)\n'
                    f'block = a[{z}:{z + 64}, {y}:{y + 64}, {x}:{x + 64}]  # (z, y, x); reads only the chunks it touches'))
        out.append(("vesuvius", "villa's vesuvius package", "python",
                    f'# pip install "vesuvius[volume-only]"\nfrom vesuvius import Volume\n\n'
                    f'v = Volume(type="zarr", path={_q(url.rstrip("/") + "/" + level)})  # one pyramid level\n'
                    f'block = v[{z}:{z + 64}, {y}:{y + 64}, {x}:{x + 64}]'))
        out.append(("vc3d", "VC3D", "text",
                    f"In VC3D (villa's volume-cartographer), open or create a project, then\n"
                    f"File > Attach Remote Zarr... and paste:\n\n{url}\n\n"
                    f"It accepts http, https and s3 OME-Zarr roots."))
        ng = url.rstrip("/") + ("/" + src["ng_path"].strip("/") if src.get("ng_path") else "")
        out.append(("neuroglancer", "neuroglancer", "link", neuroglancer_link(ng, src["title"])))
        meta = ".zattrs" if v == 2 else "zarr.json"
        arr = ".zarray" if v == 2 else "zarr.json"
        out.append(("curl", "curl", "bash",
                    f"curl -s {url.rstrip('/')}/{meta}            # OME multiscales metadata\n"
                    f"curl -s {url.rstrip('/')}/{level}/{arr}     # one level: shape, chunks, dtype, codec"))
    elif k == "hf-dataset":
        repo, f = src["repo"], src["file"]
        size = f"  # {src['size']}; allow_patterns=[...] fetches part of it" if src.get("size") else ""
        out.append(("hub", "Python (huggingface_hub)", "python",
                    f"# pip install huggingface_hub\nfrom huggingface_hub import hf_hub_download, snapshot_download\n\n"
                    f'path = hf_hub_download({_q(repo)}, {_q(f)}, repo_type="dataset")  # one file, cached\n'
                    f'folder = snapshot_download({_q(repo)}, repo_type="dataset"){size}'))
        if src.get("configs"):
            out.append(("datasets", "Python (datasets)", "python",
                        f"# pip install datasets\nfrom datasets import load_dataset\n\n"
                        + "\n".join(f'{n} = load_dataset({_q(repo)}, {_q(n)}, split="train")'
                                    for n in src["configs"])))
        if src.get("table"):
            out.append(("pandas", "pandas", "python",
                        f"# pip install pandas huggingface_hub\nimport pandas as pd\n\n"
                        f'df = pd.read_json("hf://datasets/{repo}/{src["table"]}", lines=True)'))
        out.append(("cli", "Command line (hf)", "bash",
                    f"pip install -U huggingface_hub\n"
                    f"hf download {repo} {f} --repo-type dataset --local-dir {repo.split('/')[1]}"))
        out.append(("curl", "curl", "bash", f"curl -L -O https://huggingface.co/datasets/{repo}/resolve/main/{f}"))
    elif k == "file":
        fmt = src.get("format", "bytes")
        read = {"json": f"data = json.load(urllib.request.urlopen({_q(url)}))",
                "csv": f"rows = list(csv.DictReader(io.TextIOWrapper(urllib.request.urlopen({_q(url)}), 'utf-8')))",
                "image": f"img = Image.open(io.BytesIO(urllib.request.urlopen({_q(url)}).read()))  # pip install pillow",
                }.get(fmt, f"raw = urllib.request.urlopen({_q(url)}).read()")
        imports = {"json": "import json, urllib.request", "csv": "import csv, io, urllib.request",
                   "image": "import io, urllib.request\nfrom PIL import Image"}.get(fmt, "import urllib.request")
        out.append(("python", "Python", "python", f"{imports}\n\n{read}"))
        out.append(("curl", "curl", "bash", f"curl -L -O {url}"))
    elif k == "tifxyz":
        out.append(("python", "Python (numpy, tifffile)", "python",
                    f"# pip install numpy tifffile\nimport io, json, urllib.request\nimport numpy as np, tifffile\n\n"
                    f"T = {_q(url.rstrip('/'))}\n"
                    f'meta = json.load(urllib.request.urlopen(T + "/meta.json"))  # scale, bbox, format\n'
                    f'get = lambda c: tifffile.imread(io.BytesIO(urllib.request.urlopen(f"{{T}}/{{c}}.tif").read()))\n'
                    f'xyz = np.stack([get(c) for c in "xyz"], -1)  # xyz[i, j] = (x, y, z) in scan voxels; -1 = no surface'))
    elif k == "s3-prefix":
        out.append(("python", "Python (list the folder)", "python",
                    f"import re, urllib.request\n\n"
                    f"B = {_q(url.rstrip('/'))}\n"
                    f'xml = urllib.request.urlopen(B + "/?list-type=2&delimiter=/&prefix={src["prefix"]}").read().decode()\n'
                    f'print(re.findall(r"<Prefix>([^<]+)</Prefix>", xml))  # subfolders; <Key> gives files'))
    elif k == "gradio-api":
        space, host = src["space"], src["host"].rstrip("/")
        gpu = bool(src.get("zerogpu"))
        client = (f"import os\nfrom gradio_client import Client\n\n"
                  f"client = Client({_q(space)}, hf_token=os.environ.get(\"HF_TOKEN\"))  # your token: your own ZeroGPU quota"
                  if gpu else f"from gradio_client import Client\n\nclient = Client({_q(space)})")
        for ep in src["endpoints"]:
            args = ep.get("args", {})
            kw = ", ".join(f"{a}={json.dumps(v)}" for a, v in args.items())
            out.append(("python", f"Python {ep['api']}", "python",
                        f"# pip install gradio_client\n{client}\n"
                        f"result = client.predict({kw + ', ' if kw else ''}api_name={_q(ep['api'])})"))
        ep = src["endpoints"][0]
        body = json.dumps({"data": list(ep.get("args", {}).values())})
        auth = ' ${HF_TOKEN:+-H "Authorization: Bearer $HF_TOKEN"}' if gpu else ""
        out.append(("curl", f"curl {ep['api']}", "bash",
                    (f"# HF_TOKEN, when set, is your own token: the call spends your ZeroGPU quota\n" if gpu else "")
                    + f"URL={host}\n"
                    f"EVENT=$(curl -s -X POST $URL/gradio_api/call{ep['api']} -H 'Content-Type: application/json'{auth} \\\n"
                    f"  -d '{body}' | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"event_id\"])')\n"
                    f"curl -sN{auth} $URL/gradio_api/call{ep['api']}/$EVENT"))
        name = space.split("/")[1]
        server = {"url": f"{host}/gradio_api/mcp/sse"}
        if gpu:
            server["headers"] = {"Authorization": "Bearer YOUR_HF_TOKEN"}
        out.append(("mcp", "MCP (Claude, Cursor and other agents)", "json",
                    json.dumps({"mcpServers": {name: server}}, indent=2)
                    + (f"\n\nYOUR_HF_TOKEN is your own Hugging Face token (huggingface.co/settings/tokens): each call "
                       f"spends your ZeroGPU quota; without it, calls share the small logged-out quota." if gpu else "")
                    + f"\n\nTool list: {host}/gradio_api/mcp/schema"))
    elif k == "page-api":
        lines = [f"{l['label']}: {l['url']}" for l in src["links"]]
        if src.get("embed"):
            lines.append(f'\n<iframe src="{src["embed"]}" width="100%" height="600" '
                         f'allow="fullscreen; clipboard-write"></iframe>')
        out.append(("links", "Links and embed", "text", "\n".join(lines)))
    want = src.get("tools")
    return [t for t in out if not want or t[0] in want]


def shown_url(src) -> str:
    """The address a person copies: an open-data folder as s3://bucket/prefix (aws, VC3D and s3fs take it), else url."""
    if src["kind"] == "s3-prefix":
        bucket = urllib.parse.urlparse(src["url"]).netloc.split(".")[0]
        return f"s3://{bucket}/{src['prefix']}"
    return src["url"]


def _badge(kind, tool, status):
    if status == "paused":
        return "Space paused", "warn"
    if status == "not-deployed":
        return "not deployed yet", "warn"
    if (kind, tool) in TESTED:
        return "tested " + TESTED[(kind, tool)][:10], "ok"
    if (kind, tool) in FROM_VILLA:
        return "from villa's source", "src"
    return "", ""


def validate(spec) -> list[str]:
    """Every problem with a spec, as sentences; empty when it is fine."""
    errs = []
    if spec.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    for f in ("space", "title", "checked", "sources"):
        if not spec.get(f):
            errs.append(f"missing {f}")
    ids = set()
    for s in spec.get("sources", []):
        sid = s.get("id", "?")
        if sid in ids:
            errs.append(f"{sid}: duplicate id")
        ids.add(sid)
        for f in ("id", "title", "kind", "url", "license"):
            if not s.get(f):
                errs.append(f"{sid}: missing {f}")
        k = s.get("kind")
        if k not in KIND_FIELDS:
            errs.append(f"{sid}: unknown kind {k!r}")
            continue
        for f in KIND_FIELDS[k]:
            if not s.get(f):
                errs.append(f"{sid}: kind {k} needs {f}")
        if not str(s.get("url", "")).startswith("https://"):
            errs.append(f"{sid}: url must be https")
        host = urllib.parse.urlparse(s.get("url", "")).netloc
        if host.endswith("huggingface.co") and s.get("scroll") in EDUCELAB_SCROLLS and int(s.get("scan_year", 0)) < 2025:
            errs.append(f"{sid}: {s['scroll']} before 2025 is EduceLab-Scrolls data; link the open data, do not rehost")
        if s.get("tools") and k in KIND_FIELDS and not _tools(s):
            errs.append(f"{sid}: none of its tools exist for kind {k}")
    return errs


def _esc(s):
    return html.escape(str(s), quote=True)


_COPY = ("navigator.clipboard&&navigator.clipboard.writeText(this.parentNode.querySelector('code').innerText)"
         ".then(()=>{this.textContent='Copied';setTimeout(()=>this.textContent='Copy',1200)})")

CSS = """.scc{--a:var(--scc-accent,#4ea8de);color:inherit;font:inherit;line-height:1.5;max-width:60rem}
.scc h2{font-size:1.15em;margin:.2em 0 .3em}.scc h3{font-size:1em;margin:0 0 .2em}
.scc p{margin:.3em 0}.scc a{color:var(--a)}
.scc .scc-src{border:1px solid color-mix(in srgb,currentColor 18%,transparent);border-radius:10px;padding:.7em .9em;margin:.7em 0;background:color-mix(in srgb,currentColor 4%,transparent)}
.scc .scc-meta{font-size:.85em;opacity:.8}
.scc details{border-top:1px solid color-mix(in srgb,currentColor 12%,transparent);padding:.35em 0}
.scc summary{cursor:pointer;font-weight:600;list-style-position:inside}
.scc .scc-b{font-weight:400;font-size:.75em;padding:.05em .5em;border-radius:99px;margin-left:.5em;border:1px solid currentColor;opacity:.75;white-space:nowrap}
.scc .scc-b.ok{color:#3fb37f}.scc .scc-b.src{color:var(--a)}.scc .scc-b.warn{color:#e0a030}
.scc .scc-code{position:relative;margin:.4em 0 .2em}
.scc pre{margin:0;padding:.7em .8em;border-radius:8px;overflow:auto;font-size:.82em;background:color-mix(in srgb,currentColor 9%,transparent);white-space:pre}
.scc code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.scc button.scc-copy{all:unset;box-sizing:border-box;position:absolute;top:.35em;right:.35em;font-size:.75em;line-height:1.4;padding:.1em .6em;border-radius:6px;border:1px solid color-mix(in srgb,currentColor 30%,transparent);background:color-mix(in srgb,currentColor 8%,transparent);color:inherit;cursor:pointer}
.scc button.scc-copy:hover{border-color:var(--a)}
.scc .scc-url{position:relative}.scc .scc-url pre{padding-right:4.5em;white-space:pre-wrap;word-break:break-all}
.scc .scc-go{display:inline-block;margin:.3em 0;padding:.25em .8em;border-radius:6px;border:1px solid var(--a);text-decoration:none}
.scc footer{font-size:.8em;opacity:.75;margin-top:.6em}"""


def render_html(spec) -> str:
    """The panel as one HTML fragment."""
    p = [f'<section class="scc" id="connect" aria-label="Connect your tool"><style>{CSS}</style>',
         "<h2>Connect your tool</h2>",
         f"<p>{_esc(spec.get('intro', 'Everything this page shows can be read straight from these URLs: no account, no download step.'))}</p>"]
    for s in spec["sources"]:
        status = s.get("status", "running") if s["kind"] == "gradio-api" else ""
        meta = [_esc(s["license"])] + ([_esc(s["note"])] if s.get("note") else [])
        if s.get("browse"):
            meta.append(f'<a href="{_esc(s["browse"])}" target="_blank" rel="noopener">browse</a>')
        shown = shown_url(s)
        p += [f'<div class="scc-src" id="connect-{_esc(s["id"])}"><h3>{_esc(s["title"])}</h3>',
              f'<p class="scc-meta">{" · ".join(meta)}</p>',
              f'<div class="scc-url"><button type="button" class="scc-copy" data-testid="connect-copy" onclick="{_COPY}">Copy</button><pre><code>{_esc(shown)}</code></pre></div>']
        for tid, label, lang, code in _tools(s):
            badge, cls = _badge(s["kind"], tid, status)
            b = f'<span class="scc-b {cls}">{_esc(badge)}</span>' if badge else ""
            p.append(f"<details><summary>{_esc(label)}{b}</summary>")
            if lang == "link":
                p.append(f'<a class="scc-go" href="{_esc(code)}" target="_blank" rel="noopener">Open in {_esc(label)}</a>')
            p.append(f'<div class="scc-code"><button type="button" class="scc-copy" data-testid="connect-copy" onclick="{_COPY}">Copy</button>'
                     f'<pre><code>{_esc(code)}</code></pre></div></details>')
        p.append("</div>")
    files = f"https://huggingface.co/spaces/{spec['space']}/blob/main"
    p.append(f'<footer>Machine-readable: <a href="{files}/connect.json" target="_blank" rel="noopener">connect.json</a> and '
             f'<a href="{files}/CONNECT.md" target="_blank" rel="noopener">CONNECT.md</a>. Checked {_esc(spec["checked"])}. '
             f'"Tested" means the snippet ran against this public data on that date. Scan data keeps its own license '
             f'(the Vesuvius Challenge open data is CC BY-NC 4.0).</footer></section>')
    return "\n".join(p) + "\n"


def render_md(spec) -> str:
    """The panel as Markdown."""
    m = [f"# Connect your tool: {spec['title']}", "",
         spec.get("intro", "Everything this page shows can be read straight from these URLs: no account, no download step."),
         "", f"Checked {spec['checked']}. Generated from `connect.json` by `kit spaceconnect` in [ChaseHendrick/Scrolls](https://github.com/ChaseHendrick/Scrolls).", ""]
    for s in spec["sources"]:
        status = s.get("status", "running") if s["kind"] == "gradio-api" else ""
        m += [f"## {s['title']}", "", f"`{shown_url(s)}`", "", f"License: {s['license']}."
              + (f" {s['note']}" if s.get("note") else ""), ""]
        for tid, label, lang, code in _tools(s):
            badge, _ = _badge(s["kind"], tid, status)
            m.append(f"### {label}" + (f" ({badge})" if badge else ""))
            m += ["", f"```{'text' if lang == 'link' else lang}", code, "```", ""]
    return "\n".join(m)


def load(d: Path):
    return json.loads((Path(d) / "connect.json").read_text())


def splice(page: str, fragment: str) -> str:
    """Put the fragment between the markers of a page; the page must have both."""
    a, b = page.index(START) + len(START), page.index(END)
    return page[:a] + "\n" + fragment + page[b:]


def render(d: Path, write=True) -> list[str]:
    """Write DIR's outputs (or, with write=False, list the ones that are stale)."""
    d = Path(d)
    spec = load(d)
    errs = validate(spec)
    if errs:
        raise ValueError(f"{d}/connect.json: " + "; ".join(errs))
    frag = render_html(spec)
    want = {d / "connect.html": frag, d / "CONNECT.md": render_md(spec)}
    for page in ("index.html",):
        f = d / page
        if f.exists() and START in f.read_text():
            want[f] = splice(f.read_text(), frag)
    stale = [str(f) for f, text in want.items() if not f.exists() or f.read_text() != text]
    if write:
        for f in want:
            f.write_text(want[f])
    return stale


def registry():
    return json.loads(REGISTRY.read_text())["spaces"]


def wired(d: Path, sdk: str) -> bool:
    """Does the page show the panel? Static pages splice it; Gradio apps read connect.html."""
    d = Path(d)
    if sdk == "static":
        return any(START in f.read_text() for f in d.glob("*.html") if f.name != "connect.html")
    return any("connect.html" in f.read_text() for f in d.glob("*.py"))


def _live(url: str) -> str:
    req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-0", "User-Agent": "kit-spaceconnect"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return str(r.status)
    except Exception as e:  # noqa: BLE001 - every failure is reported, none is fatal here
        return f"FAIL {e}"


def probe_url(src: dict, url: str) -> str:
    """The URL that answers for a source: a folder has no object of its own, so ask for its metadata file."""
    if src["kind"] == "ome-zarr":
        return url.rstrip("/") + "/" + (".zattrs" if src.get("zarr_format", 2) == 2 else "zarr.json")
    if src["kind"] == "tifxyz":
        return url.rstrip("/") + "/meta.json"
    return url


def check(live=False) -> list[str]:
    """Problems across every registered Space; empty when all is well."""
    probs = []
    listed = set()
    for row in registry():
        d = ROOT / row["dir"]
        listed.add(d.resolve())
        if not (d / "connect.json").exists():
            probs.append(f"{row['space']}: no {row['dir']}/connect.json")
            continue
        spec = load(d)
        probs += [f"{row['space']}: {e}" for e in validate(spec)]
        if spec.get("space") != row["space"]:
            probs.append(f"{row['space']}: connect.json names {spec.get('space')}")
        if not validate(spec):
            probs += [f"{row['space']}: stale {f}; run python -m kit spaceconnect render {row['dir']}"
                      for f in render(d, write=False)]
        if row.get("source") == "here" and not wired(d, row["sdk"]):
            probs.append(f"{row['space']}: the page does not show the panel")
        if live:
            for s in spec.get("sources", []):
                if s["kind"] == "gradio-api" and s.get("status", "running") != "running":
                    continue  # a paused or undeployed Space is labeled so on its panel, not served
                urls = [s["url"]] + [l["url"] for l in s.get("links", [])]
                for u in urls:
                    r = _live(probe_url(s, u))
                    if r.startswith("FAIL") or not r.startswith(("2", "3")):
                        probs.append(f"{row['space']}: {s['id']}: {u}: {r}")
    for d in sorted((ROOT / "spaces").iterdir()):
        if d.is_dir() and d.name != "connect" and d.resolve() not in listed:
            probs.append(f"spaces/{d.name}: not in spaces/connect/spaces.json (every Space gets a connect panel)")
    return probs


def runnable(spec):
    """(source id, tool id, language, code) for every snippet that can run headless: Python and shell of sources whose
    Space is running, without pip lines and without a whole download of a large dataset."""
    for s in spec["sources"]:
        if s.get("status") in ("paused", "not-deployed"):
            continue
        for tid, _, lang, code in _tools(s):
            if lang not in ("python", "bash"):
                continue
            lines = [l for l in code.splitlines() if not l.startswith("pip install")]
            if s.get("size"):
                lines = [l for l in lines if "snapshot_download(" not in l or l.startswith("from ")]
            yield s["id"], tid, lang, "\n".join(lines)


def run_snippets(python=sys.executable, vesuvius_python=None, cwd=None) -> list[tuple]:
    """Run every runnable snippet of every registered Space, logged out; (space, source, tool, ok, seconds, last line)."""
    import subprocess
    import tempfile
    import time
    env = {k: v for k, v in os.environ.items() if k not in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")}
    cwd = cwd or tempfile.mkdtemp(prefix="spaceconnect-")
    out = []
    for row in registry():
        for sid, tid, lang, code in runnable(load(ROOT / row["dir"])):
            py = vesuvius_python if tid == "vesuvius" and vesuvius_python else python
            cmd = [py, "-c", code] if lang == "python" else ["bash", "-c", f"set -o pipefail\n{code} >/dev/null"]
            t = time.time()
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=300)
                ok, last = r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1][:160]
            except subprocess.TimeoutExpired:
                ok, last = False, "timed out after 300 s"
            out.append((row["space"], sid, tid, ok, round(time.time() - t, 1), last))
    return out


def starter(space: str) -> dict:
    name = space.split("/")[1]
    return {"schema": SCHEMA, "space": space, "title": name, "checked": "YYYY-MM-DD",
            "intro": "One sentence: what the data is and that it reads straight from these URLs.",
            "sources": [{"id": "data", "title": "What the data is", "kind": "hf-dataset",
                         "url": f"https://huggingface.co/datasets/{space}", "repo": space, "file": "README.md",
                         "license": "CC BY-NC 4.0"}]}


def add_arguments(p):
    a = p.add_subparsers(dest="action", required=True)
    r = a.add_parser("render", help="write connect.html and CONNECT.md from connect.json")
    r.add_argument("dirs", nargs="+")
    c = a.add_parser("check", help="every Space: valid spec, outputs current, page wired")
    c.add_argument("--live", action="store_true", help="also fetch every URL (needs the network)")
    x = a.add_parser("run", help="run every Python and shell snippet against the live data (network)")
    x.add_argument("--python", help="the Python for the snippets (default: the one running kit)")
    x.add_argument("--vesuvius-python", help="a Python with vesuvius[volume-only] for villa's snippets "
                   "(vesuvius needs zarr 2, the others zarr 3)")
    n = a.add_parser("new", help="write a starter connect.json")
    n.add_argument("dir")
    n.add_argument("--space", required=True, help="OWNER/NAME of the Space")


def run(args) -> int:
    if args.action == "render":
        for d in args.dirs:
            if not (Path(d) / "connect.json").exists():
                print(f"{d}: no connect.json (python -m kit spaceconnect new {d} --space OWNER/NAME)", file=sys.stderr)
                return 1
            changed = render(Path(d))
            print(f"{d}: " + (", ".join(Path(f).name for f in changed) + " written" if changed else "up to date"))
        return 0
    if args.action == "new":
        f = Path(args.dir) / "connect.json"
        if f.exists():
            print(f"{f} exists; not overwritten", file=sys.stderr)
            return 1
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(starter(args.space), indent=1) + "\n")
        print(f"wrote {f}; fill it in, then python -m kit spaceconnect render {args.dir}")
        return 0
    if args.action == "run":
        res = run_snippets(args.python or sys.executable, args.vesuvius_python)
        for space, sid, tid, ok, secs, last in res:
            print(f"{'ok  ' if ok else 'FAIL'} {space} {sid} {tid} {secs} s" + ("" if ok else f": {last}"))
        bad = sum(not r[3] for r in res)
        print(f"{len(res)} snippets, {bad} failed")
        return 1 if bad else 0
    probs = check(live=args.live)
    for line in probs:
        print(line)
    print(f"{len(registry())} Spaces, {len(probs)} problems")
    return 1 if probs else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kit spaceconnect", description=__doc__.splitlines()[0])
    add_arguments(p)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
