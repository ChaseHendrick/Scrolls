# spaceconnect: the Connect your tool panel on every Space

Writes and checks the Connect your tool panel each of Chase's Hugging Face Spaces carries: the data's URLs and ready snippets for Python, villa's vesuvius package, VC3D, neuroglancer, curl, gradio_client and MCP.

| Field | Value |
| --- | --- |
| Id | `spaceconnect` |
| Status | Current |
| Kind | kit command |
| Area | Viewers and apps |
| Run | `python -m kit spaceconnect render`, `python -m kit spaceconnect check`, `python -m kit spaceconnect run`, `python -m kit spaceconnect new` |
| Code | `kit/spaceconnect.py`, `kit/cli.py` (`main`) |
| Tests | `tests/test_spaceconnect.py` |
| Needs | Python 3.10 or newer, standard library only. `run` needs a Python with zarr 3, fsspec, aiohttp, huggingface_hub, datasets, pandas, numpy, tifffile and gradio_client, and a second one with `vesuvius[volume-only]` (villa's package pins zarr 2) |
| Runs on | Any CPU. `render` and `check` take well under a second; `run` took about 1 minute for 34 snippets on a 4-core cloud container (2026-10-24), most of it network |
| Network | `render`, `check` and `new`: none. `check --live` fetches the first byte of every listed URL. `run` reads the open-data bucket (`vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com`), `huggingface.co` and the running Spaces, logged out |
| Writes | `render`: `connect.html` and `CONNECT.md` next to each `connect.json`, and the panel between the markers of that folder's `index.html` when it has them. `new`: one `connect.json`. `run`: a temporary folder for the snippets' downloads |
| Go-ahead | Not needed to render or check. Deploying a Space follows hard rule 8 |
| Released | Public `main` (this PR) since 2026-10-24 |
| Checked | 2026-10-24 against commit `2ce4d50` |

## What it does

Chase asked on 24 October 2026 for every one of his Spaces, now and future, to make its data easy to use from villa, villa's tools and other people's tools ("gotta make it easy for everyone"). Each Space keeps a short `connect.json` naming its data sources: an OME-Zarr scan, a public dataset, a tifxyz surface, an open-data folder, a Gradio API or the page's own API. This tool turns that list into one panel, `connect.html`, that a static page splices in and a Gradio app shows with `gr.HTML`, and the same text as `CONNECT.md` for the Space's file browser and for agents.

The panel gives each source its URL with a Copy button and a snippet per tool: Python with zarr, villa's `vesuvius` package, VC3D's File > Attach Remote Zarr, a neuroglancer link, curl, the Hugging Face hub, datasets and pandas, gradio_client, the Gradio call API and the MCP server. A snippet is marked "tested" only when that tool and kind ran against real public data (the `TESTED` table in the code, all on 2026-10-24); the VC3D step is marked "from villa's source" because it was read from villa's code at `6f20245`, not run. Snippets for a paused or undeployed Space say so.

It does not host data. Scans stay in the Vesuvius Challenge open data and are linked, never copied; `validate` refuses a source on huggingface.co that copies a pre-2025 EduceLab-Scrolls scan (Scrolls 1 to 4), whose terms forbid redistribution.

## When to use it

- A new Space: `python -m kit spaceconnect new spaces/NAME --space SharpMeow/NAME`, fill it in, add a row to `spaces/connect/spaces.json`, render, and show `connect.html` on the page.
- A Space's data changed: edit its `connect.json` and render again.
- Before a deploy: `check` (the tests run it) and, with the network, `run`.

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
6 Spaces, 0 problems
```

It worked when `check` exits 0. After editing a `connect.json`, `render` names the files it rewrote.

## Checks and controls

`check` fails (exit 1) when a Space under `spaces/` has no row in `spaces/connect/spaces.json`, a spec is invalid, a rendered file is stale, or a page in this repository does not show the panel. `tests/test_spaceconnect.py` runs it, so a new Space without a panel fails the tests. The control for the snippets is `run`: every Python and shell snippet of every running source, executed logged out against the live data. On 2026-10-24 it printed `34 snippets, 0 failed`. A snippet that fails there must not keep its "tested" badge.

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
| `--python PYTHON` | `/usr/bin/python3` | the Python for the snippets (default: this one) |
| `--vesuvius-python VESUVIUS_PYTHON` | none | a Python with vesuvius[volume-only] for villa's snippets (vesuvius needs zarr 2, the others zarr 3) |

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
| `splice(page: str, fragment: str)` | str | ValueError without both markers | Put the fragment between the markers of a page; the page must have both. |
| `render(d: Path, write=True)` | list of str | ValueError on an invalid spec | Write DIR's outputs (or, with write=False, list the ones that are stale). |
| `registry()` | list of dict | OSError | The rows of `spaces/connect/spaces.json`. |
| `wired(d: Path, sdk: str)` | bool | Nothing | Does the page show the panel? Static pages splice it; Gradio apps read connect.html. |
| `check(live=False)` | list of str | Nothing | Problems across every registered Space; empty when all is well. |
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
| `gradio-api` | `space`, `host`, `status` (running, paused or not-deployed), `endpoints` [{`api`, `args`}] | python, curl, mcp |
| `page-api` | `links` [{`label`, `url`}], optional `embed` | links |

A copy of scan data hosted on huggingface.co gives `scroll` and `scan_year`; one of Scrolls 1 to 4 scanned before 2025 is refused. `spaces/connect/spaces.json` lists every Space: `space`, `dir` (where its `connect.json` is), `sdk` (static or gradio) and `source` (here, the Space's own repository, or Scrolls-private, which copies the rendered files).

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

## How it works

`_tools` holds one snippet template per tool and kind, filled from the source's fields. `render_html` writes one block per source (title, license and note, the URL with Copy, then a `<details>` per tool with a badge from `TESTED`, `FROM_VILLA` or the Space's status). `render` compares the new text with the files on disk and rewrites only what changed; `splice` replaces whatever is between `<!-- space-connect:start -->` and `<!-- space-connect:end -->`. Neuroglancer links use `zarr://URL/` and the 4-panel layout; for villa's lasagna OME-Zarr, whose root unit is "pixel", point `ng_path` at a level folder (finding of the lasagna fields page, 24 Oct 2026).

## Cost and time

Free. `render` and `check` run in a fraction of a second; `run` took about 1 minute for 34 snippets, including a 131 MB checkpoint download (2026-10-24, cloud container).

## For agents

- **Command:** `python -m kit spaceconnect check`; for a new Space `python -m kit spaceconnect new spaces/NAME --space SharpMeow/NAME`, then `render`.
- **Parse:** each problem line names the Space and what to do; the last line counts Spaces and problems. Agents reading a live Space can fetch its `connect.json` or `CONNECT.md`.
- **Rerun:** safe; `render` rewrites only stale outputs.
- **Success:** exit 0 and `0 problems`; for `run`, `0 failed`.
- **Not a pass:** a badge says "tested" only for pairs in `TESTED`; a new kind or tool needs its own run before it gets one.
- **Go-ahead:** Nothing to render or check. Uploading a Space follows hard rule 8.
- **Never:** never list private data or a private bucket in a panel, and never rehost a pre-2025 EduceLab-Scrolls scan.

## Tests

`python -m unittest tests.test_spaceconnect`: validation (including the EduceLab refusal), every kind's tools, the snippet text, neuroglancer links, escaping and the absence of script tags, splicing, stale detection, `runnable`, and `check()` over the real registry. They do not touch the network; `run` is the live check.

## History

- 2026-10-24: first version, branched from public `main` at `2ce4d50`: the panel on Umbilici, Unroll, Crackle Check, Scroll Lens, Ink Lens and AutoPipeline ink.

## Related

- [umbilici](umbilici.md), [unroll](unroll.md), [scroll-lens](scroll-lens.md), [ink-lens](ink-lens.md): Spaces that carry the panel.
- `spaces/connect/spaces.json`: the list of Spaces.
- villa's [volume-cartographer](https://github.com/ScrollPrize/villa/tree/main/volume-cartographer) (VC3D) and [vesuvius](https://github.com/ScrollPrize/villa/tree/main/vesuvius) package, whose remote readers the snippets use.
