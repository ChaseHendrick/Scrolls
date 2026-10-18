# starter: open a local introduction to scroll tools

Scrolls Starter guides newcomers through existing viewers, an offline controls exercise and first official tasks, with a real setup snapshot and an optional Scroll Text Reader command builder.

| Field | Value |
| --- | --- |
| Id | `starter` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Pipeline and agents |
| Run | `python -m kit start`, `scrolls-start`, `from kit import starter` |
| Code | `kit/starter.py`, `kit/data/starter.html`, `kit/data/starter.js`, `kit/cli.py` (`start_main`) |
| Tests | `tests/test_starter.py`, `tests/test_packaging.py` |
| Needs | Python 3.10 or newer, standard library only, and a modern browser. A generated portable HTML page needs only the browser |
| Runs on | Local CPU; no GPU. Import probes have a 15 second timeout and Tesseract probes each have a 10 second timeout |
| Network | None for generation, checking or the embedded exercise. External links open their named sites only when selected; generated install or reader commands can download packages or weights only when the user runs them |
| Writes | One new self-contained HTML file, by default in a new `scrolls-starter-*/index.html` temporary folder; `--check` prints JSON only. No image or model output is generated |
| Go-ahead | Not needed for setup inspection, local practice or command preparation. Linked services and real workflows have their own resource and data requirements |
| Released | Public since workbench 0.4.0; included unchanged in workbench 0.4.1 except the reported package version. The portable HTML and installed command use the same assets |
| Release id | `scrolls-starter` |
| Checked | 2026-10-17 against commit `36d64e2` |

## What it does

The browser tour links the official Vesuvius Challenge introduction and the existing community Unroll and Scroll Lens viewers. A small offline exercise explains known answers and negative controls. The next steps lead to official data access, VC3D and ink-detection tutorials, with a bounded first task and an expected outcome. Community tools are optional, not prerequisites for the official workflow. AutoPipeline's existing guide is available for later automation.

Normal startup checks this Python environment: actual image-package imports, hashes of locally cached released Greek weights, Tesseract's version and installed languages, and the presence of git, Jupyter and Docker on PATH. A missing optional dependency does not block the tour or practice. This is a snapshot of the generating machine, not a complete VC3D or GPU readiness check.

The optional Scroll Text Reader wizard builds a quoted command for an existing local image. It preserves the existing reader's controls and supported backends. Greek LineNet supports measured scale, weights and line centers; Tesseract supports installed recognition languages and JSON output. The browser never reads the image or runs the command. Reader output is model hypotheses, not a verified transcription.

`--portable` skips every local probe and embeds no host executable path, operating system, dependency status or cached-weight state. That file can be shared and opened without Python. Setup is explicitly not checked. Portable commands use `.venv/bin/python` or `.venv\Scripts\python.exe` from the `scrolls-learning` folder described in [Start Here](../start-here.md).

## When to use it

Use it to help someone choose a first task, understand controls, inspect optional local reader requirements or prepare a reader command without memorizing flags. Share the portable edition or the Start Here guide, rather than a machine-specific setup snapshot.

Do not use its teaching exercise to assess scroll accuracy. Use the official tools for tracing and ink inference, and the reader's own evidence and controls for interpreting its hypotheses. The app does not verify file paths, available output space, symlinks or a user's image resolution.

## Quick start

```bash
python -m kit start
```

A normal launch prints `Scrolls Starter: /.../scrolls-starter-.../index.html` and opens that file. On a headless machine use `python -m kit start --no-open`, then open or copy the printed HTML file. Its embedded setup snapshot still describes the original machine.

For a shareable page without machine details:

```bash
python -m kit start --portable --no-open --out Scrolls-Starter.html
```

The file must not already exist, and its parent folder must exist. The page's practice starts at PRACTICE PASS and must change to PRACTICE FAIL when its control is deliberately contaminated. No model is downloaded or run by either command.

## Checks and controls

The exercise draws the known word INK using fixed pixel glyphs and seeded noise, then applies one threshold to the pattern and a noise-only control. The fixed practice rule needs at least 90% precision, 80% recall and a control count at most 10% of the drawn ink count. The default noise strength 35% and threshold 55% pass; thresholds 0 and 100 and adding the same pattern to the control fail. These are teaching checks, not scientific measurements or optical character recognition.

Tests check actual missing imports, corrupted checkpoint hashes, script-element escaping, existing-file and symlink refusals, portable generation without probes, parser-compatible reader commands, hostile shell characters and invalid scale. The existing actual learned-reader demo is linked separately and requires its packages and weights; a synthetic demo pass does not establish scroll accuracy.

Claim label: Interpretation, limited to the teaching exercise and guided progression; setup checks are local software observations.

## Commands and options

### `python -m kit start`

```text
usage: python -m kit start [-h] [--out HTML | --check] [--portable]
                           [--no-open]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--out HTML` | none | Write a new HTML file at this path, never overwrite; otherwise use a new temporary folder |
| `--check` | off | Print a real local setup snapshot as JSON without writing or opening HTML; cannot combine with `--out` or `--portable` |
| `--portable` | off | Skip machine checks and make a shareable page with setup explicitly not checked |
| `--no-open` | off | Write HTML and print its path without trying to open the browser |

The installed `scrolls-start` command takes the same options. Browser commands are labeled for bash/zsh or PowerShell; PowerShell syntax is not Windows Command Prompt syntax. All generated arguments are quoted. The selected shell also updates the install and actual reader-demo commands.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_LETTER_WEIGHTS` | `~/.cache/scrolls-kit/letters` | A folder or `.npz` file to inspect for released model hashes, matching the reader's cache convention; no download is attempted |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `check_setup()` | JSON-compatible dictionary | `OSError`, `ValueError` for unreadable package data | Real local snapshot; missing packages and unavailable Tesseract are reported rather than inferred ready |
| `portable_report()` | JSON-compatible dictionary | None | Generic not-checked report, no probes or machine paths |
| `write_app(out=None, report=None)` | Absolute `Path` | `FileExistsError`, `OSError`, `ValueError` | Creates one new file; omitted report performs the real setup check |
| `add_arguments(parser)` | None | Parser configuration errors | Register the CLI arguments |
| `run(args)` | Exit code | No expected user-input exceptions | Print a report or generate and optionally open the page |

## Inputs

No scroll input is needed. The normal check imports numpy, Pillow, tifffile and imagecodecs in a separate isolated Python process. Tesseract is inspected using its existing backend capability probe. Locally cached released weights are SHA-256 checked up to 64 MiB per file; larger files are explicitly not checked. A custom weights file is not loaded as a model.

The command builder accepts an image path, new output prefix, backend, polarity and optional matching control path. Greek inputs include a released name or local weights path, measured letter height in image pixels (at least 4) or millimeters with image micrometers per pixel, and optional nonnegative line-center rows. Tesseract takes explicit installed recognition codes; no automatic language detection occurs. Blank, non-finite and invalid scale values are rejected. These values stay in this browser session.

## Outputs

The HTML contains its assets and the JSON setup report; it makes no fetch requests. CLI stdout names the generated file and explains how to open it. When a browser cannot open, the file remains available. Generated reader commands can overwrite their own output files, so the wizard requires a new prefix and warns that it cannot check the filesystem. Obvious lexical input/output aliases are refused; symlink and relative/absolute aliases cannot be fully detected in a browser.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema`, `version` | integer, string | Report schema 1 and installed workbench version |
| `portable` | boolean, optional | True only for a generic not-checked report |
| `checked_at` | string or null | UTC snapshot timestamp; null for portable output |
| `python`, `executable`, `system` | string or null | Actual interpreter/version/system, or generic not-checked portable values |
| `virtual_environment` | boolean or null | Whether this Python has a distinct virtual-environment prefix; null when not checked |
| `packages` | list | Name, import availability and version or diagnostic detail |
| `weights` | list | Released name, license and local hash status; no downloads |
| `tesseract` | object | Availability, version and installed languages, or the reason unavailable/not checked |
| `tools` | object | git, Jupyter and Docker presence on PATH; empty when not checked |
| `start_here` | string | Stable public guide URL |

| Exit code | Meaning |
| --- | --- |
| `0` | HTML was written or the JSON snapshot printed; optional dependencies may still be missing |
| `2` | Invalid arguments or a file/data error prevented generation |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | Invalid CLI usage | Check the options above |
| `error: output already exists; choose a new --out path` | Existing file or symlink at the destination | Choose a different name; existing content is preserved |
| `error: could not prepare Scrolls Starter:` | Invalid input, unreadable package data, missing parent folder or write permission | Read the appended detail; use an existing writable parent or reinstall the package |
| `choose --portable or --check, not both` | Portable output and actual inspection requested together | Choose the intended mode |
| `Import check incomplete` | Import subprocess failed or exceeded 15 seconds | Recheck the environment; the app has not claimed those packages work |
| `No browser opened` | Headless machine or browser launcher unavailable | Open the printed file manually, or copy it to another computer |
| `Setup not checked` | Portable edition | Use the installed CLI for a real local check; this is not an error in the practice exercise |
| `An output would replace an input` | An obvious or lexical path alias in the wizard | Use a distinct output prefix and verify the actual paths before running |

## How it works

Python creates an exclusive output file and embeds the packaged HTML and JavaScript. JSON strings escape script delimiters. The page's content security policy disables network connections and form submissions; the UI inserts dynamic text with `textContent`. There is no local HTTP listener, upload endpoint, shell execution or storage of image contents. External links are ordinary user-selected navigation.

A small deterministic browser exercise uses seed 1701, a 23 by 11 pixel field and three drawn glyphs. The command builder delegates all actual reading to the existing `letterread` CLI. It keeps Greek-only flags and exports out of Tesseract commands, preserves built-in controls, and quotes paths for the chosen shell. It never runs that command itself.

## Cost and time

Local CPU only; no billed service. Startup and browser memory use are not measured as a performance benchmark. The import subprocess is bounded to 15 seconds and each of two Tesseract information calls to 10 seconds. Portable generation skips those checks. Practice uses only 253 pixels per image. Linked services and real reader commands have their own download and compute requirements, shown before the user chooses them.

## For agents

- **Command:** `python -m kit start --check` for real JSON; `python -m kit start --portable --no-open --out NEW.html` for a shareable page.
- **Parse:** inspect each package's availability and weight hash status; exit zero alone does not establish reader readiness.
- **Rerun:** use a new output path, or let the command create a new temporary folder.
- **Success:** HTML opens and the exercise changes from pass to fail with its negative controls.
- **Not a pass:** the synthetic practice proves no learned model quality or scroll reading; portable setup is never measured.
- **Go-ahead:** nothing for the local app; external workflows retain their own resource and data rules.
- **Never:** publish a machine-specific snapshot as the portable release, imply OCR output is a reading, execute a prepared command without reviewing its inputs, or weaken controls to produce a pass.

## Tests

`python -m unittest tests.test_starter tests.test_packaging tests.test_cli_parser_cache` covers the app's Python behavior, package entry points and data inclusion. JavaScript command and practice tests use Node.js when available and skip otherwise. Browser layout/keyboard and a fresh installed wheel are checked separately. No target images, trained weights or scientific evaluation is required.

## History

- 2026-10-17: Implemented the local beginner app and portable page on public base `67ced6a`, bridging existing viewers and official tools with explicit teaching-only practice and optional reader command preparation.

## Related

- [Start Here](../start-here.md): install instructions and the route into official tools.
- [Scroll Text Reader guide](../letter-reader.md), [reader backends](reader-backends.md), [actual reader demo](letterdemo.md): optional existing-image workflows.
- [Unroll](unroll.md), [Scroll Lens](scroll-lens.md), [AutoPipeline](autopipeline.md): existing community tools linked from the app.
- [Workbench package](workbench-package.md): installation, entry points and packaged assets.
