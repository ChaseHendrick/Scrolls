# spaceconnect: the Connect your tool panel on every Space

Writes and checks the Connect your tool panel each of Chase's Hugging Face Spaces carries: the data's URLs and ready snippets for Python, villa's vesuvius package, VC3D, neuroglancer, curl, gradio_client and MCP. It also keeps every Space to one page scroll bar and to American English.

| Field | Value |
| --- | --- |
| Id | `spaceconnect` |
| Status | Current |
| Kind | kit command |
| Area | Viewers and apps |
| Run | `python -m kit spaceconnect render`, `python -m kit spaceconnect check`, `python -m kit spaceconnect run`, `python -m kit spaceconnect new`, `python -m kit spaceconnect scroll`, `python -m kit spaceconnect spelling` |
| Code | `kit/spaceconnect.py`, `kit/cli.py` (`main`) |
| Tests | `tests/test_spaceconnect.py` |
| Needs | Python 3.10 or newer, standard library only. `scroll` needs Python playwright and a Chromium (preinstalled in Claude cloud containers; `pip install playwright`). `run` needs a Python with zarr 3, fsspec, aiohttp, huggingface_hub, datasets, pandas, numpy, tifffile and gradio_client, and a second one with `vesuvius[volume-only]` (villa's package pins zarr 2) |
| Runs on | Any CPU. `render` and `check` take well under a second; `run` took a few minutes for 40 snippets on a 4-core cloud container (2026-10-24), mostly network and one Crackle Check call that runs a reader (141 s) |
| Network | `render`, `check`, `spelling` and `new`: none. `scroll` opens each running Space's page (huggingface.co, or with `--direct` the Space's own `*.hf.space` host, where it sends `HF_TOKEN` so a private Space opens; the token goes to no other host). `check --live` fetches the first byte of every listed URL. `run` reads the open-data bucket (`vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`), `huggingface.co` and the running Spaces, logged out |
| Writes | `render`: `connect.html`, `CONNECT.md` and `onescroll.html` next to each `connect.json`, and the panel and the one-scroll fragment between their markers in that folder's `index.html` when it has them. `scroll --shots DIR`: one PNG per view. `new`: one `connect.json`. `run`: a temporary folder for the snippets' downloads |
| Go-ahead | Not needed to render or check. Deploying a Space follows hard rule 8 |
| Released | Public `main` (this PR) since 2026-10-24 |
| Checked | 2026-10-27 against commit `aa259e8` |

## What it does

Every one of Chase's Spaces, now and future, makes its data easy to use from villa, villa's tools and other people's tools (user decision, 24 October 2026). Each Space keeps a short `connect.json` naming its data sources: an OME-Zarr scan, a public dataset, a tifxyz surface, an open-data folder, a Gradio API or the page's own API. This tool turns that list into one panel, `connect.html`, that a static page splices in and a Gradio app shows with `gr.HTML`, and the same text as `CONNECT.md` for the Space's file browser and for agents.

The panel gives each source its URL with a Copy button and a snippet per tool: Python with zarr, villa's `vesuvius` package, VC3D's File > Attach Remote Zarr, a neuroglancer link, curl, the Hugging Face hub, datasets and pandas, gradio_client, the Gradio call API and the MCP server. A snippet is marked "tested" only when that tool and kind ran against real public data (the `TESTED` table in the code, all on 2026-10-24); the VC3D step is marked "from villa's source" because it was read from villa's code at `6f20245`, not run. Snippets for a paused or undeployed Space say so.

Two rules for every page come with it (user decisions, 27 October 2026).

- **One page scroll bar.** A page scrolls as a whole; nothing inside it keeps a scroll bar of its own. Hugging Face shows a Gradio Space in an iframe it sizes to the app, so only the outer page scrolls, but a guide shown inside the app as an `iframe srcdoc` with a fixed height scrolled on its own, a second bar inside the first. `render` writes `onescroll.html`, a style and a short script that fit every same-origin iframe to its content and refit it when the content changes, so the page scrolls and the frame does not. A Gradio app adds it to its `head`; a static page has it spliced between `<!-- space-onescroll:start -->` and `<!-- space-onescroll:end -->` in its head. An iframe that must keep its own scroll (a map, a 3D view) opts out with `data-scroll="inner"`. One-screen viewers, whose page never scrolls (`"layout": "one-screen"` in `spaces/connect/spaces.json`: Umbilici, Unroll, Segment Lens), keep one scrolling list or panel but never two at once.
- **American English.** Every word a Space shows, its README, its Connect panel, its code and its release entry use American spelling: fiber, color, center, gray, labeled, license, catalog. Names from other people (a repository, a dataset someone else named, a license's own title) keep theirs; `ALLOW_SPELLING` lists each with its reason. `spelling` finds British words, inside identifiers too (`FibreError`, `fibres_box`).

It does not host data. Scans stay in the Vesuvius Challenge open data and are linked, never copied; `validate` refuses a source on huggingface.co that copies a pre-2025 EduceLab-Scrolls scan (Scrolls 1 to 4), whose terms forbid redistribution.

## When to use it

- A new Space: `python -m kit spaceconnect new spaces/NAME --space SharpMeow/NAME`, fill it in, add a row to `spaces/connect/spaces.json`, render, and show `connect.html` on the page.
- A Space's data changed: edit its `connect.json` and render again.
- Before a deploy: `check` (the tests run it) and, with the network, `run`.
- After a deploy: `scroll --shots DIR` on the Space, to see one scroll bar in every view.

Do not use it:

- To publish data: put it in the open data or a public Hugging Face dataset or bucket first, then list it.
- For private Spaces or private data: the panel is public by design.

## Quick start

```bash
python -m kit spaceconnect render spaces/umbilici
python -m kit spaceconnect check
```

On 2026-10-24 this printed:

```
spaces/umbilici: up to date
7 Spaces, 0 problems
```

It worked when `check` exits 0. After editing a `connect.json`, `render` names the files it rewrote.

```bash
python -m kit spaceconnect scroll afv-fibers --shots /tmp/shots
```

prints one line per view, `ok` or the boxes that scroll inside the page and anything cut off at the right, and exits 1 on any problem. Add `--width 390 --height 844` for a phone.

## Checks and controls

`check` fails (exit 1) when a Space under `spaces/` has no row in `spaces/connect/spaces.json`, a spec is invalid, a rendered file is stale, a page in this repository does not show the panel or does not carry the one-scroll fragment, or a British spelling is left in `spaces/` or `docs/releases.json`. `tests/test_spaceconnect.py` runs it, so a new Space without a panel fails the tests. The control for the snippets is `run`: every Python and shell snippet of every running source, executed logged out against the live data. On 2026-10-24 it printed `34 snippets, 0 failed`. A snippet that fails there must not keep its "tested" badge. The control for one scroll bar is `scroll`, run on the live pages: it clicks through every tab and fails on any box that scrolls inside a page that scrolls, or on two scroll bars at once in a one-screen viewer. At phone width it also fails on what a narrow screen cuts off: a table, code block, picture or chart that runs past the right edge of its frame with no box around it that scrolls sideways, and a page that pans sideways (a long link that does not wrap). Sideways scrolling inside a box, such as a wide table in an `overflow-x:auto` wrapper, is allowed. Its own controls are the test pages in `tests/test_spaceconnect.py`: a frame marked `data-scroll="inner"` must still be found scrolling, a bare wide table must be found cut off while the same table in a sideways-scrolling box passes, and a long link must be found panning the page until it may wrap.

Claim label: Sourced fact for the VC3D steps (villa `6f20245`, `MenuActionController.cpp`); the "tested" badges are our own runs of 2026-10-24.

## Commands and options

### `python -m kit spaceconnect render`

```
usage: python -m kit spaceconnect render [-h] dirs [dirs ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dirs` | required | folders that hold a `connect.json`; each gets `connect.html`, `CONNECT.md` and, if its `index.html` has the markers, the panel spliced in |

### `python -m kit spaceconnect check`

```
usage: python -m kit spaceconnect check [-h] [--live]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--live` | off | also fetch every URL (needs the network) |

### `python -m kit spaceconnect run`

```
usage: python -m kit spaceconnect run [-h] [--python PYTHON]
                                      [--vesuvius-python VESUVIUS_PYTHON]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--python PYTHON` | none | the Python for the snippets (default: the one running kit) |
| `--vesuvius-python VESUVIUS_PYTHON` | none | a Python with vesuvius[volume-only] for villa's snippets (vesuvius needs zarr 2, the others zarr 3) |

### `python -m kit spaceconnect scroll`

```
usage: python -m kit spaceconnect scroll [-h] [--direct] [--width WIDTH]
                                         [--height HEIGHT] [--wait WAIT]
                                         [--shots SHOTS] [--json]
                                         [names ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `names` | none | Space names (default: every Space in the registry that is running) |
| `--direct` | off | open the Space's own host (`OWNER-NAME.static.hf.space` for a static Space, else `OWNER-NAME.hf.space`; private Spaces: sends HF_TOKEN to that host only) instead of its huggingface.co page |
| `--width WIDTH` | `1440` | viewport width in CSS pixels |
| `--height HEIGHT` | `900` | viewport height in CSS pixels |
| `--wait WAIT` | `12.0` | seconds to let the page settle |
| `--shots SHOTS` | none | save a screenshot of every view in this folder |
| `--json` | off | one JSON object per Space instead of lines |

### `python -m kit spaceconnect spelling`

```
usage: python -m kit spaceconnect spelling [-h] [paths ...]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `paths` | none | files or folders to check (default: `spaces/` and `docs/releases.json`) |

### `python -m kit spaceconnect new`

```
usage: python -m kit spaceconnect new [-h] --space SPACE dir
```

| Option | Default | Meaning |
| --- | --- | --- |
| `dir` | required | the folder to write a starter `connect.json` into; an existing file is never overwritten |
| `--space SPACE` | required | OWNER/NAME of the Space |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `neuroglancer_link(url: str, name: str)` | str | Nothing | A neuroglancer-demo link that opens an OME-Zarr URL (zarr v2 or v3) as an image layer. |
| `shown_url(src)` | str | KeyError on a source without url | The address a person copies: an open-data folder as s3://bucket/prefix (aws, VC3D and s3fs take it), else url. |
| `validate(spec)` | list of str | Nothing | Every problem with a spec, as sentences; empty when it is fine. |
| `render_html(spec)` | str | KeyError on an invalid spec | The panel as one HTML fragment. |
| `render_md(spec)` | str | KeyError on an invalid spec | The panel as Markdown. |
| `load(d: Path)` | dict | OSError, ValueError | The folder's `connect.json`. |
| `splice(page: str, fragment: str, start=START, end=END)` | str | ValueError without both markers | Put the fragment between the markers of a page; the page must have both. A fragment that starts with the start marker replaces the markers too. |
| `render(d: Path, write=True)` | list of str | ValueError on an invalid spec | Write DIR's outputs (or, with write=False, list the ones that are stale). |
| `registry()` | list of dict | OSError | The rows of `spaces/connect/spaces.json`. |
| `wired(d: Path, sdk: str)` | bool | Nothing | Does the page show the panel? Static pages splice it; Gradio apps read connect.html. |
| `onescroll_html()` | str | Nothing | The head fragment every Space page carries: no iframe keeps a scroll bar of its own. |
| `scroll_wired(d: Path, sdk: str)` | bool | Nothing | Does the page carry the one-scroll fragment? Static pages splice it; Gradio apps add onescroll.html to head. |
| `scan_page(page)` | list of dict | Nothing | Every box scrolling on its own in an open playwright page, across its frames: {frame, box, shown, content}. |
| `scan_cut(page)` | list of dict | Nothing | Every table, code block, picture or chart a narrow screen cuts off, across the page's frames, and the page if it pans sideways: {frame, box, width, room}. |
| `verdict(found: list[dict], one_screen=False)` | list of str | Nothing | Problems with one view: more than one scroll bar, or on a page that scrolls any box scrolling inside it. |
| `space_urls(owner: str, short: str, direct=False, sdk=None)` | list of str | Nothing | The addresses to try for a Space, in order: its huggingface.co page, or with direct its own host (`.static.hf.space` for a static Space; both for an unknown sdk). |
| `scroll_check(names, direct=False, width=1440, height=900, wait=12.0, shots=None, token=None, log=print)` | dict | ImportError without playwright | Open each Space, click through every tab (those behind More tabs too), and report each view's scroll boxes, cut-off content and problems: {name: [{view, found, cut, problems}]}. |
| `spelling(paths=None, root=ROOT)` | list of str | Nothing | `path:line: British word -> American` for every text file under the paths (default `spaces/` and `docs/releases.json`), minus `ALLOW_SPELLING`. |
| `probe_url(src: dict, url: str)` | str | KeyError on a source without kind | The URL `check --live` asks for: a folder (OME-Zarr, tifxyz) has no object of its own, so its metadata file. |
| `check(live=False)` | list of str | Nothing | Problems across every registered Space; empty when all is well. With live, also fetches every source (paused or undeployed Gradio APIs are skipped). |
| `runnable(spec)` | iterator of tuples | Nothing | (source id, tool id, language, code) for every snippet that can run headless, without pip lines or a whole download of a large dataset. |
| `run_snippets(python=sys.executable, vesuvius_python=None, cwd=None)` | list of tuples | Nothing | Run every runnable snippet of every registered Space, logged out; (space, source, tool, ok, seconds, last line). |
| `starter(space: str)` | dict | Nothing | A starter spec for `new`. |
| `add_arguments(p)` | None | Nothing | The command line, for `kit/cli.py`. |
| `run(args)` | int | Nothing | The command line's exit code. |
| `main(argv=None)` | int | SystemExit on bad arguments | `python kit/spaceconnect.py`. |

## Inputs

`connect.json`, schema `space-connect/1`: `space` (OWNER/NAME), `title`, `checked` (a date), optional `intro`, and `sources`. Each source has `id`, `title`, `kind`, `url` (https only) and `license`, an optional `note` and `browse` link, an optional `tools` list to show only some tools, and its kind's fields:

| Kind | Fields | Tools |
| --- | --- | --- |
| `ome-zarr` | `zarr_format` (2 or 3), `example` {`level`, `start` [z, y, x]}, optional `ng_path` | zarr, vesuvius, vc3d, neuroglancer, curl |
| `hf-dataset` | `repo`, `file`, optional `configs`, `table`, `size` | hub, datasets, pandas, cli, curl |
| `file` | `format` (json, csv, image or bytes) | python, curl |
| `tifxyz` | none | python |
| `s3-prefix` | `prefix` (the folder; `url` is the bucket root) | python |
| `gradio-api` | `space`, `host`, `status` (running, paused or not-deployed), `endpoints` [{`api`, `args`}], optional `zerogpu` (true: the Python, curl and MCP snippets pass the caller's own Hugging Face token, so a call spends the caller's ZeroGPU quota) | python, curl, mcp |
| `page-api` | `links` [{`label`, `url`}], optional `embed` | links |

A copy of scan data hosted on huggingface.co gives `scroll` and `scan_year`; one of Scrolls 1 to 4 scanned before 2025 is refused. `spaces/connect/spaces.json` lists every Space: `space`, `dir` (where its `connect.json` is), `sdk` (static or gradio), `source` (here, the Space's own repository, or Scrolls-private, which copies the rendered files) and, for a viewer whose page never scrolls, `"layout": "one-screen"`. `scroll --direct` reads `HF_TOKEN` from the environment and sends it only to the Space's own host.

## Outputs

`connect.html`: one `<section id="connect">` with scoped CSS (class `scc`, accent `--scc-accent`), no script tag, Copy buttons as inline handlers (they work in Gradio 6.28's `gr.HTML`, checked 2026-10-24). `CONNECT.md`: the same content. `run` prints one line per snippet (`ok` or `FAIL`, Space, source, tool, seconds) and a count.

| Exit code | Meaning |
| --- | --- |
| `0` | rendered, no problems, or every snippet ran |
| `1` | a problem, a failed snippet, a missing `connect.json`, or `new` would overwrite a file |
| `2` | bad arguments |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `...exists; not overwritten` | `new` found a `connect.json` already | Edit that file instead |
| `...: no connect.json (python -m kit spaceconnect new...--space OWNER/NAME)` | The folder has no spec | Run `new` first |
| `spaces/NAME: not in spaces/connect/spaces.json` | A new Space without a panel | Add a spec and a row |
| `stale ...; run python -m kit spaceconnect render DIR` | A spec or the renderer changed | Render again and commit the outputs |
| `FAIL ...` from `run` | A URL moved or a package changed | Fix the spec or the snippet; do not keep a "tested" badge on a failing pair |
| `...: the page does not carry the one-scroll fix` | A page without the fragment | Static: add the onescroll markers to its head and render. Gradio: `HEAD += (HERE / "onescroll.html").read_text()` |
| `American spelling: path:line: Word -> word` | A British word in a Space's text | Change it, or add an `ALLOW_SPELLING` entry with a reason if it is someone else's name |
| `tab did not open: not shown` from `scroll` | The tab was not on screen when its turn came: its parent tab closed | Rerun with a wider `--width`; a tab that never opens is a problem with the page |
| `cut off at the right: FRAME BOX W px wide, R px of room` from `scroll` | A table, code block, picture or chart wider than its frame on a narrow screen, with nothing around it that scrolls sideways; `page` means the whole page pans sideways | Wrap a table in a box with `overflow-x:auto`; give grid columns `minmax(min(320px, 100%), 1fr)`; let long links and names wrap (`overflow-wrap:anywhere` on links, `break-word` on text) |
| `did not load: HTTP 404 at URL` from `scroll` | The page answered with an error (a static Space's `OWNER-NAME.hf.space`, a private Space without HF_TOKEN, a Space that is asleep or building) | Check the Space's state; a static Space is opened at `OWNER-NAME.static.hf.space` |
| `scrolls inside the page: ...` from `scroll` | A box with a fixed height and `overflow:auto`, or an iframe the fragment could not fit (another origin, or sized in `vh`) | Let the box grow; give a cross-origin frame its own page or mark it `data-scroll="inner"` only if it must scroll (a map) |

## How it works

`_tools` holds one snippet template per tool and kind, filled from the source's fields. `render_html` writes one block per source (title, license and note, the URL with Copy, then a `<details>` per tool with a badge from `TESTED`, `FROM_VILLA` or the Space's status). `render` compares the new text with the files on disk and rewrites only what changed; `splice` replaces whatever is between `<!-- space-connect:start -->` and `<!-- space-connect:end -->`. The one-scroll script binds every same-origin iframe (and any added later, through a MutationObserver), forces its document to `height:auto` with `overflow:hidden`, and sets the iframe's height to the document's height whenever a ResizeObserver in the frame sees it change; it gives up on a frame whose content grows with its own height (a page sized in `vh`) after 40 changes in 4 seconds and lets it scroll. `scroll` opens each Space at the addresses `space_urls` gives and reports a page that answers 400 or more instead of checking it. It runs a script in each frame that lists the document (scrolling when its content is taller than its own visible height, `clientHeight`, which a sideways scroll bar shortens) and every element with `overflow` auto or scroll whose content is taller than its box, including inside shadow roots; a frame sized from outside (`scrolling="no"`, as Hugging Face sets on a Gradio app and the fragment sets on a guide) has no scroll bar of its own, but the boxes inside it are still checked. It opens every tab level by level (`TABS_JS` gives each shown tab its depth, so a tab group inside a tab is visited once its parent is open), up to 30 views per Space. At phone width Gradio moves the tabs that do not fit into a More tabs menu of plain buttons without `role=tab`; `OVERFLOW_JS` lists those and `OPEN_OVERFLOW_JS` clicks one, so they are visited too. When Playwright's click times out on a tab (a 3D page drawing a few frames a second in headless Chromium without a GPU), `CLICK_TAB_JS` clicks it through the DOM instead. In each view `CUT_JS` lists every table, `pre`, image, svg, canvas and video at least 40 by 12 pixels that starts on screen and ends past the frame's right edge with no ancestor scrolling sideways, skipping hidden copies (`aria-hidden`, `.visually-hidden`), and adds `page` when the document is wider than its frame and neither `html` nor `body` hides the overflow. `spelling` splits camelCase and snake_case words and looks each up in a table built from British stems (`-ise`, `-our`, `-re`, doubled `l`) and single words (grey, licence, catalogue). Neuroglancer links use `zarr://URL/` and the 4-panel layout; for villa's lasagna OME-Zarr, whose root unit is "pixel", point `ng_path` at a level folder (finding of the lasagna fields page, 24 Oct 2026).

## Cost and time

Free. `render` and `check` run in a fraction of a second; `run` took a few minutes for 40 snippets, including a 131 MB checkpoint download and one Crackle Check call that runs a reader (141 s) (2026-10-24, cloud container).

## For agents

- **Command:** `python -m kit spaceconnect check`; for a new Space `python -m kit spaceconnect new spaces/NAME --space SharpMeow/NAME`, then `render`; after a deploy `python -m kit spaceconnect scroll NAME --shots DIR`.
- **Parse:** each problem line names the Space and what to do; the last line counts Spaces and problems. Agents reading a live Space can fetch its `connect.json` or `CONNECT.md`.
- **Rerun:** safe; `render` rewrites only stale outputs.
- **Success:** exit 0 and `0 problems`; for `run`, `0 failed`.
- **Not a pass:** a badge says "tested" only for pairs in `TESTED`; a new kind or tool needs its own run before it gets one.
- **Go-ahead:** Nothing to render or check. Uploading a Space follows hard rule 8.
- **Never:** never list private data or a private bucket in a panel, never rehost a pre-2025 EduceLab-Scrolls scan, never give a page a box that scrolls inside it, and never rename a key or file that published data already uses just to change its spelling (allow it with a reason instead).

## Tests

`python -m unittest tests.test_spaceconnect`: validation (including the EduceLab refusal), every kind's tools, the snippet text, neuroglancer links, escaping and the absence of script tags, splicing, stale detection, `runnable`, `check()` over the real registry, the one-scroll fragment in Chromium (a guide frame grows past its fixed height, a short one shrinks, an opted-out frame keeps its scroll, a `vh`-sized page is given up on), `verdict`, the More tabs menu of a phone-width Gradio page, the cut-off finder (a bare wide table, the same table in a sideways-scrolling box, a long link with and without wrapping), the static host `--direct` opens, a full-height page that a sideways scroll bar makes scroll, and the spelling finder on prose and code. They do not touch the network; `run` and `scroll` are the live checks. The Chromium test skips without playwright.

## History

- 2026-10-24: first version, branched from public `main` at `2ce4d50`: the panel on Umbilici, Unroll, Crackle Check, Scroll Lens, Ink Lens and AutoPipeline ink.
- 2026-10-24: Segment Lens, which merged into `main` while this was open, gets its panel in its Guide; `check` caught it ([PR #170](https://github.com/ChaseHendrick/Scrolls/pull/170)).
- 2026-10-27: one page scroll bar (`onescroll.html`, `scroll`) and American English (`spelling`) on every Space ([PR #253](https://github.com/ChaseHendrick/Scrolls/pull/253)).
- 2026-10-28: `scroll` also opens the tabs a phone folds into More tabs, falls back to a DOM click when a 3D page is too slow for Playwright's, and fails on content cut off at the right and on a page that pans sideways; with `--direct` it opens a static Space at `OWNER-NAME.static.hf.space` (its `OWNER-NAME.hf.space` answers 404, which earlier passed as a page with nothing to scroll) and fails on a page that answers with an error; its first phone run found the AFV Fibers catalog and guide cards, the Fiber Checker guide's table and a dinovol link running past the screen ([PR #254](https://github.com/ChaseHendrick/Scrolls/pull/254)).

## Related

- [umbilici](umbilici.md), [unroll](unroll.md), [scroll-lens](scroll-lens.md), [ink-lens](ink-lens.md): Spaces that carry the panel.
- `spaces/connect/spaces.json`: the list of Spaces.
- villa's [volume-cartographer](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer) (VC3D) and [vesuvius](https://github.com/ScrollPrize/villa/tree/main/vesuvius) package, whose remote readers the snippets use.
