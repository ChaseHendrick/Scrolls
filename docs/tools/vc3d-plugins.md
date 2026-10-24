# vc3d-plugins: run Scrolls and community tools from VC3D's Plugins menu

Eight VC3D plugin manifests (the Center Finder, StrokeNet, the Scroll Text Reader, Ink Lens, three villa commands and the v8in ink model) for the Plugins menu proposed on villa branch `vc3d-plugins`, with a kit launcher and tests.

| Field | Value |
| --- | --- |
| Id | `vc3d-plugins` |
| Status | Experimental |
| Kind | data, patch |
| Area | Viewers and apps |
| Run | VC3D built from villa branch `vc3d-plugins`, started with `VC3D_PLUGIN_PATH=plugins`; `python3 plugins/run_kit.py COMMAND ...` runs the kit from a plain clone |
| Code | `plugins/` |
| Tests | `tests/test_plugins.py` |
| Needs | VC3D built from villa branch `vc3d-plugins` (commit `a0c8b9e6d`, on villa `main` `d1b95150e`); each tool's own needs, on its page; Python 3.10 or newer for `plugins/run_kit.py` |
| Runs on | Wherever VC3D runs; each tool takes the time its page gives. The manifest checks take about 1.2 s (measured 2026-10-20, 4-core cloud container) |
| Network | Only what each tool contacts, on its page (the Center Finder reads the open-data bucket; StrokeNet and the Scroll Text Reader download their released weights once from this repository's GitHub releases) |
| Writes | VC3D writes each run into `~/.vc3d/plugin-runs/ID/TIME/` with `plugin-run.json`; by result kind it also attaches a segment or an umbilicus to the open project, appends a record to the active segment's `ink-detections.json`, or adds point collections. Ink Lens writes its overlay, pins and a merged `ink-detections.json` into the segment folder itself (its result kind is `none`) |
| Go-ahead | Not needed to run on public data. Opening the villa PR needs Chase's yes (rule 8); output from prize-eligible scrolls stays private (rule 1) |
| Released | Not released; the villa side is a local branch, not pushed |
| Checked | 2026-10-21 against commit `249096b` |
| License | Manifests and launcher: Apache 2.0 ([LICENSE](../../LICENSE)); each tool keeps its own license, named in its manifest's `license` field |

## What it does

Community members use VC3D, villa's viewer, every day, and a VC3D maintainer said the team prefers VC3D extensions over new viewers. Our tools already write formats VC3D reads (the Center Finder writes `umbilicus.json`, ink models write PNG predictions), but using them meant leaving VC3D, running a command and attaching the file by hand.

The villa branch `vc3d-plugins` adds a **Plugins** menu to VC3D. A plugin is one JSON manifest: one program, its arguments with placeholders such as `{segment}`, `{volume}`, `{ink_overlay}` and `{output}`, and a result kind that says how VC3D loads what the program writes (`none`, `file`, `segment`, `ink_overlay`, `points` or `umbilicus`). VC3D shows the exact command and asks before each run, runs it through its existing command-line tool runner with an argument list (no shell), and loads only the declared result from the run's own folder with its existing loaders. No plugin code is loaded into VC3D.

This folder holds manifests for four of Chase's public tools that write or read community formats (the Center Finder, StrokeNet, the Scroll Text Reader and Ink Lens) and for four community tools: villa's `vc_gen_umbilicus`, `vc_render_tifxyz` and `vc_tifxyz2obj`, and Youssef Nader's v8in ink model. `plugins/run_kit.py` runs `python -m kit` from this checkout so the kit manifests work without an install.

It adds no model, no weights and no accuracy result. Everything a plugin produces is what the underlying tool produces: an ink detection or a StrokeNet score is model output, not a reading, and an umbilicus is model output to be checked on CT.

## When to use it

- You work in VC3D and want the Center Finder's line attached to the project, an ink model's prediction shown on the active segment, or a StrokeNet or Scroll Text Reader result on the selected ink detection, without leaving VC3D.
- You maintain a tool and want a manifest others can drop into `~/.vc3d/plugins/`.

Do not use it:

- For scored runs that need a control. The Scroll Text Reader manifest runs without `--control`, so its status is `no_control`; use [letterread](letterread.md) from the command line with the reverse-depth map.
- For a batch over many segments or scrolls; use [AutoPipeline](autopipeline.md) or the tool's own command.
- For a stack of segments: [stackcheck](stackcheck.md) needs an ordered list, which plugins cannot pass yet.
- With a VC3D build that lacks the Plugins menu (any villa `main` as of 2026-10-20).

## Quick start

```bash
git clone https://github.com/ChaseHendrick/Scrolls && cd Scrolls
python -m unittest tests.test_plugins          # every manifest loads under VC3D's rules
export VC3D_PLUGIN_PATH="$PWD/plugins"
VC3D                                           # a VC3D built from villa branch vc3d-plugins
```

Output of the test run on 2026-10-20 (4-core cloud container):

```text
Ran 6 tests in 1.221s

OK
```

In VC3D, **Plugins** lists the three submenus Scrolls, Volume Cartographer and Ink detection. **Plugins > Plugin Folders...** shows the folder above and no skipped manifests when it worked. A run opens the console, then a message saying what was loaded. VC3D itself was not run against these manifests in this session (no local VC3D build); the C++ parser from the villa branch, compiled alone against Qt 6.4.2, loaded all eight manifests and filled every placeholder (2026-10-21).

## Checks and controls

`tests/test_plugins.py` checks each manifest against a Python mirror of VC3D's parser rules (schema, keys, id, placeholders, declared inputs, result path inside `{output}/`), and its `test_the_checker_can_fail` case feeds nine broken manifests that must each be refused. It also parses the kit manifests' arguments with the kit's own parser and checks that every `--option` passed to a script appears in that script, so a renamed option fails the test. On the villa side, `test_plugin_manifest` (nine test functions) and a new case in `test_open_data_manifest` cover parsing, refusal of unsafe manifests, placeholder expansion, folder scanning, program lookup and the `ink-detections.json` append; they passed locally for the manifest part (compiled alone) and still need the full VC3D build and test run on Modal.

The results a plugin loads keep their own controls: StrokeNet reports its rotation and IAAFT controls; the Scroll Text Reader run here has none (`no_control`).

Claim label: None for the manifests and launcher (they make no claim); Model output for anything a plugin's tool writes.

## Commands and options

Not applicable: the manifests are data VC3D reads; `plugins/run_kit.py` passes every argument to `python -m kit` unchanged. The manifest format is under Inputs.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `VC3D_PLUGIN_PATH` | unset | Folders VC3D searches after `~/.vc3d/plugins/`, separated by `:` (`;` on Windows); set it to this repository's `plugins/` |
| `VC3D_PLUGIN_RUNS` | `~/.vc3d/plugin-runs` | Where VC3D puts each run's folder |

## Python API

Not applicable: no importable functions; `tests/test_plugins.py` has its own helpers.

## Inputs

A manifest (`vc3d-plugin/1`) has these keys:

| Key | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `vc3d-plugin/1` |
| `id` | yes | 1 to 64 letters, digits, `.`, `_`, `-`; unique |
| `name` | yes | Menu text |
| `program` | yes | Bare name (next to VC3D, then `PATH`), absolute path, or path relative to the manifest; no placeholders |
| `args` | no | Strings; each stays one argument after placeholders are filled |
| `inputs` | no | Values asked before each run, used as `{input:NAME}` |
| `result` | no | `{"kind": ..., "path": "{output}/..."}` |
| `menu`, `description`, `homepage`, `license` | no | Submenu and reference text |

Placeholders: `{volume}`, `{volume_id}`, `{segment}`, `{segment_id}`, `{point}` (`x,y,z`), `{point_x}`, `{point_y}`, `{point_z}`, `{region}` (`x0,y0,z0,x1,y1,z1`), `{ink_overlay}`, `{umbilicus}`, `{project}`, `{output}`, `{plugin_dir}`, `{input:NAME}`. Coordinates are full-resolution voxels of the current volume. A placeholder with no value (no active segment, say) stops the run with a message naming what is missing.

Per manifest, see the table in [`plugins/README.md`](../../plugins/README.md). The Center Finder expects its released weights in `work/umbilicus/weights/` of this checkout; v8in asks for a local snapshot of `YoussefMoNader/ink-8um-v8in`.

## Outputs

Each run folder `~/.vc3d/plugin-runs/ID/TIME/` holds what the tool wrote and `plugin-run.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | string | `vc3d-plugin-run/1` |
| `plugin_id` | string | The manifest's `id` |
| `manifest` | string | Absolute path of the manifest |
| `manifest_sha256` | string | SHA-256 of the manifest bytes as read |
| `program` | string | The resolved program path |
| `args` | list of strings | The exact arguments |
| `result_kind`, `result_path` | string | What VC3D loads, and from where |
| `state` | string | `started`, `finished`, `failed` or `load_failed` |
| `updated_utc` | string | ISO time of the last update |
| `message` | string | The summary or error, when there is one |

| Exit code | Meaning |
| --- | --- |
| `0` | The plugin's program succeeded; VC3D loads the declared result |
| `1` | Any nonzero exit of the program: VC3D shows the error and the run folder and loads nothing |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `No plugins installed` in the menu | No readable manifest in `~/.vc3d/plugins/` or `VC3D_PLUGIN_PATH` | Set `VC3D_PLUGIN_PATH` to this `plugins/` folder and use **Reload Plugins** |
| `Plugin Folders (N skipped)...` | A manifest broke a rule; the dialog names the file and the rule | Fix the manifest; `python -m unittest tests.test_plugins` reports the same rules |
| `Cannot find the program "python3" next to VC3D or on PATH.` | VC3D's `PATH` lacks the program | Put the full path of the right Python in `program` |
| `... needs an active segment` (or `an open volume`, `a selected ink detection overlay`) | The placeholder has no value | Select what it names, then run again |
| `Another tool is still running.` | VC3D runs one command-line tool at a time | Wait for it, or cancel it in the console |
| `The program finished, but its result was not loaded:` | The declared file is missing or not in the expected format | Read the console and the run folder |
| `no segment was active when the plugin started` | An `ink_overlay` result with no active segment | Activate the segment first |

## How it works

1. VC3D reads every `*.json` in `~/.vc3d/plugins/` and the `VC3D_PLUGIN_PATH` folders, sorted by name, and skips any manifest that breaks a rule.
2. On a menu click it asks for the manifest's inputs, fills the placeholders from what is open, makes a fresh run folder and shows the command.
3. It runs the program through `CommandLineToolRunner`, the runner behind Render segment and the other `vc_*` tools, with the console open.
4. On exit 0 it loads the result by kind: `umbilicus` through the same check as **File > Attach Umbilicus**; `ink_overlay` by appending a record to the active segment's `ink-detections.json` (keeping catalog records) and selecting it; `points` by adding collections, never replacing; `segment` by attaching the folder; `file` by offering to open it.
5. `plugins/run_kit.py` puts this checkout first on `sys.path` and calls `kit.cli.main`, so `python3 plugins/run_kit.py strokenet ...` equals `python -m kit strokenet ...`.

## Cost and time

Not measured inside VC3D. Each tool's time is on its page; the Center Finder took about 13 minutes on 4 CPU cores for PHerc1203 ([guide](../../scripts/umbilicus/README.md)). A villa build and test run on Modal's 64-core runner costs at most 2.69 USD worst case (the runner's plan, 2026-10-20). Nothing here rents compute.

## For agents

- **Command:** `python -m unittest tests.test_plugins` to check the manifests; in VC3D, the Plugins menu (no headless entry yet: the agent bridge has no plugin method, so agents run the underlying tool's own command instead, as its page says).
- **Parse:** each run's `plugin-run.json`: `state` (`finished` means the result was loaded), `result_path`, `args`, `manifest_sha256`.
- **Rerun:** Safe; every run gets a new folder. Results that attach (umbilicus, segment) replace or add project entries, and VC3D asks before replacing an attached umbilicus; ink detections and point collections are added each time.
- **Success:** The tests pass; in VC3D, `state` is `finished` and the message names what was loaded.
- **Not a pass:** A Scroll Text Reader result with `no_control`; a StrokeNet score on a downsampled JPEG preview; an umbilicus on one of the 13 published scrolls from the `-all` weights; a manifest test pass taken as proof that a live VC3D loads the result (not yet run in VC3D).
- **Go-ahead:** Nothing to run on public data. Opening the villa PR, posting media, or publishing outputs needs Chase's yes.
- **Never:** Put a manifest from an untrusted source in a plugin folder; call an ink detection or a score a reading; share output from prize-eligible scrolls before the announcement; put target-scroll results in this repository.

## Tests

`python -m unittest tests.test_plugins` (six tests): manifest rules and a failing case, files named in this checkout exist, kit commands accept the arguments, script options exist, and the launcher runs from another working directory. Not covered here: VC3D itself (villa's `test_plugin_manifest` and `test_open_data_manifest`, which still need the Modal build), and whether each tool's output is right (each tool's own tests).

## History

- 2026-10-20: first version: seven manifests, `plugins/run_kit.py`, `tests/test_plugins.py`; villa branch `vc3d-plugins` at `25d616e16` adds the Plugins menu.
- 2026-10-21: `ink-lens.json` in the `vc3d-plugin/1` format (Ink Lens had only a draft manifest); the script-option test also reads `spaces/`; villa branch rebased onto villa `main` `d1b95150e` as `a0c8b9e6d`.

## Related

- [umbilicus](umbilicus.md), [strokenet](strokenet.md), [letterread](letterread.md), [ink-lens](ink-lens.md), [v8in-run](v8in-run.md): the tools the Scrolls and Ink detection manifests run.
- [stackcheck](stackcheck.md), [inkfilter](inkfilter.md): not wired yet, and why, in [`plugins/README.md`](../../plugins/README.md).
- [autopipeline](autopipeline.md): batch runs over many volumes, which plugins do not replace.
