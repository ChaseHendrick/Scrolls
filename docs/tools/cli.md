# cli: the kit command line (python -m kit) and its list of commands

`python -m kit` is the one command line of the workbench: `kit/cli.py` builds the command parser, hands each to its handler, and gives the installed package its console scripts.

| Field | Value |
| --- | --- |
| Id | `cli` |
| Status | Current |
| Kind | kit module |
| Area | Releases and repository |
| Run | `python -m kit`, `scrolls-workbench`, `scrolls-letterread`, `scrolls-letterlines`, `scrolls-letterdemo`, `scrolls-start` (the installed package's console scripts), `from kit import cli` |
| Code | `kit/cli.py` (`build_parser`, `_parser`, `_parse`, `main`, `_console`, `workbench_main`, `letterread_main`, `letterlines_main`, `letterdemo_main`, `start_main`, `import_advice`, `_shape`, `CONSOLE_SCRIPTS`, `READER_INSTALL`, `_PARSERS`), `kit/__main__.py`, `kit/__init__.py` |
| Tests | `tests/test_cli_parser_cache.py`, `tests/test_packaging.py`, `tests/test_localcost_regressions.py`, `tests/test_repo.py`, `tests/test_letterdemo.py`, `tests/test_letter_scripts.py` |
| Needs | Python 3.10 or newer (`requires-python` in `pyproject.toml`). The entry point and every module it imports at start are standard library only; a command that needs numpy, tifffile, zarr, Pillow or scipy imports them when it runs (see its page) |
| Runs on | Any machine. `python -m kit prizes --json` took 0.19 s wall (measured 2026-10-16, cloud container, Python 3.13.16); building the parser once and reusing it brought a repeated `main()` from 13 ms to 2 ms per call (commit `88fbee4`'s message; machine not recorded) |
| Network | None of its own. Some commands contact hosts (such as `fetch` and `run all --refresh`); each command's page says which |
| Writes | Nothing of its own. Each command's writes are on its page |
| Go-ahead | Not needed to run the entry point. A command that posts, uploads or rents compute needs Chase's yes first (the go-ahead rule, hard rule 8); its page says so |
| Released | Public `main` since 2026-10-06 (`2daee8e`); the console scripts since 2026-10-14 (`2582ab7`). Since 2026-10-20 the README's "Released tools" lists the command-line tools as one entry, Scrolls kit (`scrolls-kit` in `docs/releases.json`), with one line per tool |
| Release id | `scrolls-kit` |
| Guide | [CHANGELOG.md](../../CHANGELOG.md) (what each package version holds and how to install it) |
| Checked | 2026-10-16 against commit `63ee638` |

## What it does

Every `python -m kit` command, from `prizes` to `run all`, starts here. `kit/__main__.py` calls `main()` in `kit/cli.py` and exits with what it returns. `main()` takes the command line, picks the command (and its action, for the eight commands that have actions, such as `run init` or `provenance check`), and calls that command's handler: a `cmd_` function in `kit/cli.py`, or `releases.run` in `kit/releases.py`. The handler's return value is the exit code.

This page covers the entry point itself: the parser, the command list, the console scripts of the installed package `scrolls-workbench`, the parser cache and the package version. Each command's options, outputs and errors are on that command's page, linked from the table under Commands and options. The `cmd_` functions belong to those pages too.

`kit/__init__.py` holds the package's docstring and `__version__` (`"0.2.0"` at this commit), which `pyproject.toml` reads as the package version and which the letter reader writes into its provenance (`kit.letterread`, `kit.letterlines` and `kit.letterexport` import it as `KIT_VERSION`). The package wraps the official pipeline in ScrollPrize/villa; it does not reimplement it.

The entry point makes no claim of its own. Nothing it prints is a result about ink: each command's page says what its output may and may not be called.

## When to use it

- To find which commands exist and what each does: `python -m kit --help`, or the table below.
- To run any workbench command from a clone of the repository (`python -m kit COMMAND`), or from an installed package (`scrolls-workbench COMMAND`).
- To call a command from Python with its exact command-line behavior: `cli.main([...])`.

Do not use it:

- To learn one command's options: read that command's page (`python -m kit.tooldocs show ID`), or run `python -m kit COMMAND --help`.
- For a `python -m kit.MODULE` entry point such as [`tooldocs`](tooldocs.md): those have their own parsers and pages and are not commands of `python -m kit`.
- For the scripts under `scripts/`: they run on their own (`bash scripts/X.sh`, `python scripts/X.py`), each with its own page.

## Quick start

```bash
cd SCROLLS
python -m kit --help
python -m kit prizes --json
```

- `SCROLLS`: the root of a clone of the repository. `python -m kit` finds the package only from there (or when the package is installed).

Run on 2026-10-16 in the checkout, `--help` printed the usage line and one line per command, starting:

```
usage: python -m kit [-h]
                     {prizes,doctor,plan,cost,fetch,verify,rowscore,auc,fibertensor,hpscore,overlap,collate,stackcheck,meshaudit,surfacefix,provenance,compute,ensemble,gate,layers,shuffle,phantom,view,strokenet,letterread,letterlines,letterdemo,greeklm,releases,run} ...
```

and `prizes --json` printed the dated prize snapshot, starting `{ "checked": "2026-10-11", "source": "https://scrollprize.org/prizes", ...`, with exit code 0. It worked when the exit code is 0. An unknown command prints `python -m kit: error: argument command: invalid choice: ...` and exits with 2.

## Checks and controls

The entry point has no result to control. These checks keep it honest:

- **The cached parser gives the same answer as a fresh one.** `tests/test_cli_parser_cache.py` compares the namespace from `_parse(_parser(), argv)` with `build_parser().parse_args(argv)`, and checks that a handler that changes a list default (such as `rowscore --reverse`) does not leak it into the next call.
- **Every documented command exists.** `tests/test_repo.py` (`test_documented_kit_commands_exist`) fails when a tracked `.md`, `.sh`, `.txt` or `.py` file names a `python -m kit` command the parser does not have.
- **Every command and action has a page.** `python -m kit.tooldocs check` fails when a command or action is on no page's Run field, or when a page's usage block, options or defaults differ from this parser ([tooldocs](tooldocs.md)).
- **Console scripts match.** `tests/test_packaging.py` checks that every script in `pyproject.toml`'s `[project.scripts]` points at a function here, that the one-command scripts are exactly `CONSOLE_SCRIPTS`, and that each shows its own name in its usage and errors.

Claim label: None; the entry point makes no claim, and each command's page labels its own output.

## Commands and options

### `python -m kit`

```
usage: python -m kit [-h]
                     {start,prizes,live,style,doctor,plan,cost,fetch,verify,rowscore,auc,fibertensor,hpscore,overlap,collate,stackcheck,uvgate,windconsistency,meshaudit,surfacefix,provenance,compute,ensemble,gate,layers,shuffle,phantom,view,strokenet,volumeview,segzoo,letterread,letterlines,letterdemo,greeklm,routines,stale,releases,leaderboard,run} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `command` | required | One of the commands below. Everything after it goes to that command's parser |
| `-h`, `--help` | off | Print the usage, the module docstring and one line per command, then exit 0 |

`scrolls-workbench` takes the same arguments and shows `scrolls-workbench` in its usage and errors (`main(argv, prog="scrolls-workbench")`).

### Every command and its page

Each command's `--help` line, its actions, its handler and the page that documents it.

| Command | Actions | Handler | Page | What it does (`--help`) |
| --- | --- | --- | --- | --- |
| `start` | none | `starter.run` (in `kit/starter.py`) | [starter](starter.md) | open Scrolls Starter: setup, practice and guided next steps |
| `prizes` | none | `cmd_prizes` | [prizes](prizes.md) | open prizes from the dated snapshot |
| `live` | none | `termview.main` (in `kit/termview.py`) | [termstyle](termstyle.md) | run a command (after --) or page piped output in a full-screen, mouse-driven view in the Scrolls look |
| `style` | none | `termstyle.main` (in `kit/termstyle.py`) | [termstyle](termstyle.md) | the Scrolls terminal look: hook install, remove or status (style every script in a checkout), demo, pipe |
| `doctor` | none | `cmd_doctor` | [doctor](doctor.md) | check GPU, disk, tools and villa paths |
| `plan` | none | `cmd_plan` | [plan](plan.md) | print a First Letters run plan for an eligible scroll |
| `cost` | none | `cmd_cost` | [plan](plan.md) | estimate run cost in USD |
| `fetch` | none | `cmd_fetch` | [fetch](fetch.md) | mirror a public bucket prefix over HTTPS (no AWS CLI needed) |
| `verify` | none | `cmd_verify` | [verify](verify.md) | compare two ink maps (e.g. CPU vs MPS) with a control |
| `rowscore` | none | `cmd_rowscore` | [rowscore](rowscore.md) | text-row periodicity triage score for ink maps (Bullo27's method) |
| `auc` | none | `cmd_auc` | [auc](auc.md) | pixel AUC of an ink map against a segment's published labels |
| `fibertensor` | `train`, `predict` | `cmd_fibertensor` | [fibertensor](fibertensor.md) | fiber-orientation (structure tensor) features and a tiny CPU ink reader |
| `hpscore` | none | `cmd_hpscore` | [hpscore](hpscore.md) | letter-scale score: 48 um high-passed correlation with the labels (Scheirer) |
| `overlap` | none | `cmd_overlap` | [overlap](overlap.md) | do two segments trace the same papyrus? mesh gaps and label agreement |
| `collate` | none | `cmd_collate` | [overlap](overlap.md) | two traces of one sheet as two copies: do their ink maps agree, against a control? |
| `stackcheck` | none | `cmd_stackcheck` | [stackcheck](stackcheck.md) | check consecutive tifxyz segments against the umbilicus: order, missing sectors, skipped windings, turn overlaps, stack ends (geometry only) |
| `uvgate` | none | `cmd_uvgate` (in `kit/uvgate_cli.py`) | [uvgate](uvgate.md) | check a flattened sheet's UV triangles (JSON or CSV): no overlap, enough area, optionally one counterclockwise piece (geometry only) |
| `windconsistency` | none | `cmd_windconsistency` (in `kit/windconsistency.py`) | [windconsistency](windconsistency.md) | check that relative winding counts (a to b is k windings) can all hold at once, around every closed path |
| `meshaudit` | `transforms`, `canvas`, `plan`, `depth` | `cmd_meshaudit` | [meshaudit](meshaudit.md) | audit published meshes, cross-scan transforms and render depth offsets |
| `surfacefix` | `prepare`, `apply` | `cmd_surfacefix` | [surfacefix](surfacefix.md) | experimental region flags and bounded, controlled surface corrections |
| `provenance` | `write`, `check` | `cmd_provenance` | [provenance](provenance.md) | who ran what, when, from which inputs: a record and one digest |
| `compute` | none | `cmd_compute` | [compute](compute.md) | machine time per run, from provenance records (GENChase-style ledger) |
| `ensemble` | none | `cmd_ensemble` | [ensemble](ensemble.md) | average several ink maps of one surface (mean, or rank mean across models) |
| `gate` | none | `cmd_gate` | [gate](gate.md) | Gate A: rank readers on PHerc0841's three crops by the rule in kit/gate.py |
| `layers` | none | `cmd_layers` | [layers](layers.md) | export a surface-volume zarr to 00.tif, 01.tif, ... (v8in's input) |
| `shuffle` | none | `cmd_shuffle` | [layers](layers.md) | depth-shuffle control: copy a surface volume with its layers in a fixed random order |
| `phantom` | none | `cmd_phantom` | [phantom](phantom.md) | synthetic carbon-ink phantoms with known truth: make, stress-test a detector, calibrate AUC noise |
| `view` | none | `cmd_view` | [view](view.md) | one static HTML page overlaying several ink maps, their disagreement and the labels |
| `strokenet` | none | `cmd_strokenet` | [strokenet](strokenet.md) | learned text-likeness score of a 2D ink map (StrokeNet), with rotation and IAAFT controls |
| `volumeview` | none | `cmd_volumeview` | [volumeview](volumeview.md) | build a local viewer link from explicit public volume metadata |
| `segzoo` | none | `cmd_segzoo` | [segzoo](segzoo.md) | model zoo: nnU-Net, MedNeXt, Swin UNETR, Auto3DSeg, SegFormer, DINOv3, MedSAM2 and Mamba families, their licenses and fit; Auto3DSeg datalists |
| `letterread` | none | `cmd_letterread` | [letterread](letterread.md) | Scroll Text Reader: Greek LineNet or local OCR for installed languages, with controls |
| `letterlines` | `build`, `score` | `cmd_letterlines` | [letterlines](letterlines.md) | training lines for the letter reader from your own transcribed lines, and scores on lines kept apart |
| `letterdemo` | none | `cmd_letterdemo` | [letterdemo](letterdemo.md) | offline check of the letter reader: synthetic Greek capitals and a noise image, DEMO PASS or DEMO FAIL |
| `greeklm` | `build`, `score` | `cmd_greeklm` | [greeklm](greeklm.md) | letter n-gram language model for Greek in scriptio continua |
| `routines` | `list`, `due`, `status`, `run`, `check` | `routines.run` (in `kit/routines.py`) | [routines](routines.md) | recurring repository checks any agent runs at session start (kit/routines.py, docs/routines.json) |
| `stale` | none | `stale.run` (in `kit/stale.py`) | [stale](stale.md) | what live pages and registries still say that is no longer true: old handoff rows, gone branches, retired names, dead links, MAP rows (kit/stale.py; read-only) |
| `releases` | `add`, `render`, `check`, `list`, `pin`, `unpin` | `releases.run` (in `kit/releases.py`) | [releases](releases.md) | the list of tools released from private work, and the README section made from it |
| `leaderboard` | `render`, `check` | `leaderboard.run` (in `kit/leaderboard.py`) | [leaderboard](leaderboard.md) | the ink reader leaderboard, docs/leaderboard.md, written from docs/results.json |
| `run` | `init`, `status`, `cost`, `record`, `check`, `list` | `cmd_run` | [run-ledger](run-ledger.md) | local experiment ledger (experiments/, gitignored) |
| `run` | `local`, `backfill` | `cmd_run` | [run-local](run-local.md) | `local`: run a local command and log wall time, CPU time and electricity cost; `backfill`: add estimated local-run costs from a JSON list of logged durations |
| `run` | `modal-row` | `cmd_run` | [modal-row](modal-row.md) | append one Modal job's row to a Modal ledger CSV, once per key (kit/modalledger.py) |
| `run` | `all`, `watch`, `catalog` | `cmd_run` | [batch](batch.md) | `all`: AutoPipeline over every released scan: catalog, per-scan config, priced plan, resumable queue (kit/autobatch.py); launches nothing. `watch`: for a scheduled routine: find new or changed volumes in the bucket, queue them priced in dry run, print them (launches nothing). `catalog`: write the catalog of every volume in the open-data bucket |

`run` takes one option of its own before the action, `--root ROOT` (default `experiments`, `ledger.DEFAULT_ROOT`), the ledger folder, as in `python -m kit run --root ROOT local SLUG -- COMMAND`. AutoPipeline (AP) is the released tool that runs villa's pipeline from a released scan to a scored ink map; its page is pending.

### Console scripts

`pyproject.toml`'s `[project.scripts]` installs four scripts with the package `scrolls-workbench`:

| Script | Function | What it runs |
| --- | --- | --- |
| `scrolls-workbench` | `kit.cli:workbench_main` | Every command, as `python -m kit` does. `gate` and `releases` read the repository's `docs/` and `README.md`, so they need a clone |
| `scrolls-letterread` | `kit.cli:letterread_main` | `python -m kit letterread` alone |
| `scrolls-letterlines` | `kit.cli:letterlines_main` | `python -m kit letterlines` alone (its actions `build` and `score`) |
| `scrolls-letterdemo` | `kit.cli:letterdemo_main` | `python -m kit letterdemo` alone |
| `scrolls-start` | `kit.cli:start_main` | `python -m kit start`, the local beginner app ([starter](starter.md)) |

A one-command script takes that command's own arguments, with no command word: `scrolls-letterdemo --quiet`, not `scrolls-letterdemo letterdemo --quiet`. Its usage and errors show the script's name (`usage: scrolls-letterlines [-h] {build,score} ...`).

### Environment variables

The entry point reads none. Commands that read environment variables list them on their own pages.

## Python API

```python
from kit import cli
code = cli.main(["prizes", "--json"])      # the same as python -m kit prizes --json; returns the exit code
```

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `main(argv=None, prog="python -m kit", sub_progs=None)` | The handler's return value: the exit code (an int, or `None`, which `sys.exit` treats as 0) | `SystemExit(2)` on a usage error and `SystemExit(0)` after `--help`, from argparse; whatever the handler raises | `argv` defaults to `sys.argv[1:]`. Uses the cached parser. For `run ... -- COMMAND`, parses the part before `--` and, when the action is `local`, appends everything after `--` to the child command unchanged |
| `build_parser(prog="python -m kit", sub_progs=None)` | A new `argparse.ArgumentParser` with every command | Nothing of its own | `sub_progs` maps a command to the program name its usage and errors show; `letterread`, `letterlines` and `letterdemo` honor it. [tooldocs](tooldocs.md) reads this parser to check every page |
| `_parser(prog="python -m kit", sub_progs=None)` | The parser for `(prog, sub_progs)`, built once per process and kept in `_PARSERS` | Nothing of its own | The parser is over a thousand `add_argument` calls; pipelines and tests call `main()` many times in one process |
| `_parse(parser, argv)` | A deep copy of `parser.parse_args(argv)` | `SystemExit` from argparse | The copy keeps a handler that changes a list default from leaking it into the next call |
| `_console(script, argv=None)` | The handler's return value | `KeyError` for a script not in `CONSOLE_SCRIPTS`; `SystemExit` from argparse | Runs the one command of a console script, with a fresh parser whose usage shows the script's name |
| `workbench_main(argv=None)` | As `main` | As `main` | Console script `scrolls-workbench` |
| `letterread_main(argv=None)`, `letterlines_main(argv=None)`, `letterdemo_main(argv=None)` | As `_console` | As `_console` | Console scripts `scrolls-letterread`, `scrolls-letterlines`, `scrolls-letterdemo` |
| `import_advice(exc)` | str: the `ImportError`'s text, plus the install line for the missing package | Nothing | Adds `READER_INSTALL` when numpy, Pillow (`PIL`), tifffile or imagecodecs is missing, and a zarr line when zarr is; used by `letterread` and `letterlines` |
| `_shape(v)` | `(v[0], v[1])`, or `(384, 384)` when `v` is empty | Nothing | The default phantom shape of `python -m kit phantom` ([phantom](phantom.md)) |
| `CONSOLE_SCRIPTS` | dict | | Console script name to command: `scrolls-letterread`, `scrolls-letterlines`, `scrolls-letterdemo` |
| `READER_INSTALL` | str | | `python -m pip install "scrolls-workbench[reader]" (numpy, pillow, tifffile and imagecodecs)` |
| `kit.__version__` | str | | The package version, `"0.2.0"` at this commit; `pyproject.toml` reads it (`[tool.setuptools.dynamic]`) |

| `start_main(argv=None)` | As `main` | As `main` | Runs Scrolls Starter through `_console` |

## Inputs

The command line only: a command name, its action where it has actions, and that command's arguments. `main(argv)` takes the same as a list of strings. Everything after `--` in `run ... local SLUG -- COMMAND` is passed to the child command unchanged, including words that look like options and literal text such as `$(not executed)`.

## Outputs

The entry point prints nothing of its own except argparse's usage, help and errors (on stdout for `--help`, on stderr for errors). Each command's output is on its page.

| Exit code | Meaning |
| --- | --- |
| `0` | `--help`, or the command's handler returned 0 (or `None`) |
| `1` | Python could not find the package (`No module named kit`), the output pipe was closed before the command finished writing (no traceback), or a command's own failure or an uncaught error with a traceback; see the command's page |
| `2` | A usage error from argparse (no command, an unknown command or action, a bad option), or a command's own bad-input exit; see the command's page |
| `3` | Only from commands that use it, such as `verify` (`pass-uncontrolled`) and `run watch --exit-code` (something new queued) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `python -m kit: error: the following arguments are required: command`, exit code 2 | No command given | Add a command; `python -m kit --help` lists them |
| `python -m kit: error: argument command: invalid choice: 'NAME' (choose from 'prizes', 'doctor', ...)`, exit code 2 | A misspelled command, or one that exists only on another branch or in Scrolls-private | Pick a command from the list; check the name in the table above |
| `python -m kit run: error: the following arguments are required: action` (and the same for the other commands with actions), exit code 2 | A command with actions given without one | Add the action, such as `run init` or `provenance check` |
| `scrolls-workbench: error: ...`, `scrolls-letterread: error: ...` and the like, exit code 2 | The same usage errors under an installed script's name | As above |
| `/usr/bin/python3: No module named kit`, exit code 1 | `python -m kit` run outside the clone's root, with the package not installed | `cd` to the repository root, or install the package as [CHANGELOG.md](../../CHANGELOG.md) shows and use `scrolls-workbench` |
| `No module named numpy; python -m pip install "scrolls-workbench[reader]" (numpy, pillow, tifffile and imagecodecs)` | `letterread` or `letterlines` needs a package the reader extra brings (`import_advice`) | Run the install line it prints |
| `No module named zarr; python -m pip install zarr (or "scrolls-workbench[all]", Python 3.11 or newer)` | A letter command was given a zarr input without zarr installed (`import_advice`) | Install zarr, on Python 3.11 or newer for zarr 3 |
| No message, exit code 1, and output cut short | A reader that stops early, as in `python -m kit prizes --json \| head -1`, closed the pipe; the command ends quietly, as Python's documentation advises for SIGPIPE | Nothing, when the cut was meant; otherwise write the output to a file |
| A command's own message | That command's input or environment | See the command's page, linked in the table above |

## How it works

1. `python -m kit` runs `kit/__main__.py`, which imports `main` from `kit/cli.py` and calls `sys.exit(main())`.
2. Importing `kit/cli.py` imports the standard-library-only modules its handlers call (`prizes`, `plan`, `ledger`, `verify`, `auc` and the others in its import line). Modules that need numpy or other packages import them inside functions, so the entry point starts without them.
3. `main()` gets the parser from `_parser(prog, sub_progs)`. The first call builds it with `build_parser` and stores it in `_PARSERS` under the key `(prog, sorted sub_progs)`; later calls in the same process reuse it.
4. It parses the arguments with `_parse`, which deep-copies the namespace so a handler that changes a list default cannot affect a later call, exactly as with a fresh parser.
5. Special case: when the first word is `run` and the arguments hold `--`, it parses only the part before `--`. If the action is `local`, it appends everything after `--` to the child command (`args.cmd`); otherwise it parses the whole line as usual. This works around Python 3.10's argparse, which mishandles a trailing `nargs="*"` after wrapper options (commit `7492129`).
6. It calls `args.func(args)`, the handler that `set_defaults(func=...)` attached to the command, through `_run`, which puts the typed command line in `kit.verify.RUNNING` while it runs (so an install hint names the command actually run) and flushes stdout inside the call. A `BrokenPipeError` there, from a reader that closed the pipe early, points stdout at the null device and returns 1 with no traceback. Otherwise the handler's value is the exit code.
7. A one-command console script (`_console`) builds a fresh parser with `sub_progs={command: script}`, takes that command's sub-parser, parses the arguments with it, and calls its handler.

## Cost and time

`python -m kit prizes --json` took 0.19 s wall in a cloud container (measured 2026-10-16, Python 3.13.16). `tests/test_cli_parser_cache.py` requires 20 calls of `main(["prizes", "--json"])` in one process to take under 5 s. Commit `88fbee4`'s message gives a repeated `main()` at 13 ms per call before the parser cache and 2 ms after (machine not recorded). Memory: Not measured. The entry point runs anywhere; where a command must run (a laptop, or Modal for GPU work and long CPU jobs, the Modal rule, hard rule 11) is on its page.

## For agents

- **Command:** `python -m kit COMMAND [ACTION] [OPTIONS]` from the repository root; `python -m kit --help` lists the commands, and `python -m kit COMMAND --help` gives one command's usage. Machine-readable output is each command's `--json` where it has one.
- **Parse:** the command's own output, as its page says. From the entry point itself, only the exit code and argparse's `error:` line on stderr.
- **Rerun:** The entry point changes nothing; whether a rerun is safe depends on the command (see its page's For agents).
- **Success:** Exit code 0, then the command's own success values.
- **Not a pass:** Exit code 0 from a command whose page says 0 is not enough by itself, such as an `auc` with a null `forward.auc`; exit code 3 from `verify` (no control).
- **Go-ahead:** Nothing for the entry point. Commands that post, upload or rent compute need Chase's yes first; their pages say which.
- **Never:** Edit a command's options without updating its page in the same change (the tool-pages rule, hard rule 16); add a command without a page; run a GPU job through any command on a laptop CPU instead of Modal.

## Tests

```bash
python -m unittest tests.test_cli_parser_cache tests.test_packaging tests.test_localcost_regressions tests.test_kit.CliTest -v
```

`tests/test_cli_parser_cache.py` covers the parser cache (one parser per key, the same namespace as a fresh parser, no leaking list defaults, 20 calls under 5 s). `tests/test_packaging.py` covers the console scripts (each in `pyproject.toml` points at a function here, the one-command scripts equal `CONSOLE_SCRIPTS`, each shows its own name in usage and errors, `scrolls-workbench` runs `prizes` and refuses an unknown command with exit code 2) and that the package version comes from `kit.__version__`. `tests/test_localcost_regressions.py` covers the `run ... local SLUG -- COMMAND` split. `tests/test_kit.py`'s `CliTest` checks that the module docstring names every command and that a reader that stops early ends `prizes --json` and `cost` with exit code 1 and no traceback. `tests/test_repo.py` checks that every documented `python -m kit` command exists, `tests/test_letterdemo.py` runs the `scrolls-letterdemo` function, and `tests/test_letter_scripts.py` checks that `CITATION.cff`'s version equals `__version__`. These ran in 0.14 s here (16 tests, 2026-10-16). They do not install the package or run the console scripts as installed executables; the CI workflow does that (its page is [workbench-package](workbench-package.md)).

## History

- 2026-10-21: the usage block and the command table list `start`, `volumeview`, `segzoo`, `routines`, `stale` and `leaderboard`, which they had left out; the checker now compares both (`bbecb37`).
- 2026-10-17: a command whose output pipe closes early (`python -m kit prizes | head -1`) ends with exit code 1 and no traceback; before, it printed a `BrokenPipeError` traceback (`f3b1ac8`).
- 2026-10-17: the module docstring's command list names `meshaudit` and `strokenet`, which it had left out (`e7dce03`).
- 2026-10-16: package version 0.2.0 in `kit/__init__.py`, with `CHANGELOG.md` (`00b0097`).
- 2026-10-16: the parser is built once per process and each parsed namespace is deep-copied; a repeated `main()` went from 13 ms to 2 ms per call (`88fbee4`).
- 2026-10-14: the installable package `scrolls-workbench` with console scripts `scrolls-workbench`, `scrolls-letterread`, `scrolls-letterlines` and `scrolls-letterdemo` (`2582ab7`).
- 2026-10-07: `run ... local SLUG -- COMMAND` parses correctly on Python 3.10 (`7492129`).
- 2026-10-06: first version of `python -m kit` (`2daee8e`).

## Related

- [tooldocs](tooldocs.md): checks every page against this parser.
- [workbench-package](workbench-package.md): `pyproject.toml` and the CI workflow that installs the package and its console scripts.
- [run-ledger](run-ledger.md), [run-local](run-local.md), [modal-row](modal-row.md) and [batch](batch.md): the four pages that split the actions of `run`.
- [CHANGELOG.md](../../CHANGELOG.md): what each package version holds.
- [MAP.md](../MAP.md): one line per module, to find a path.
