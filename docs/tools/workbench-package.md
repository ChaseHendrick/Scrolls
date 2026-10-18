# workbench-package: the pip-installable scrolls-workbench package and the CI that tests it

`pyproject.toml` makes this repository's `kit` folder an installable package, `scrolls-workbench`, with three extras and five console scripts; `.github/workflows/check.yml` tests it on every push and pull request, and `CITATION.cff` says how to cite it.

| Field | Value |
| --- | --- |
| Id | `workbench-package` |
| Status | Current |
| Kind | package, workflow |
| Area | Releases and repository |
| Run | `python -m pip install "scrolls-workbench[reader] @ git+https://github.com/ChaseHendrick/Scrolls"`, then `scrolls-workbench`, `scrolls-letterread`, `scrolls-letterlines`, `scrolls-letterdemo`, `scrolls-start`, `import kit` |
| Code | `pyproject.toml`, `.github/workflows/check.yml`, `CITATION.cff`, `CHANGELOG.md`, `kit/__init__.py`, `kit/cli.py` (`workbench_main`, `letterread_main`, `letterlines_main`, `letterdemo_main`, `start_main`, `_console`, `CONSOLE_SCRIPTS`) |
| Tests | `tests/test_packaging.py` |
| Needs | Python 3.10 or newer (`requires-python = ">=3.10"`); pip with network access to fetch `setuptools>=77` for the build. The core needs no other package; the extras add numpy, pillow, tifffile, imagecodecs, zarr 3 (Python 3.11 or newer only) and scipy |
| Runs on | Linux, macOS and Windows (the CI's reader job runs all three). Installing with no extras from a local copy took about 6 s (measured 2026-10-16, cloud container, Python 3.13) |
| Network | The install fetches `setuptools>=77` and the chosen extras from PyPI, and clones GitHub for a `git+https` URL. The letter reader's commands download the released weights from GitHub. The CI runs on GitHub-hosted runners |
| Writes | pip writes the `kit` package into the environment's `site-packages` and the five console scripts into its `bin` (`Scripts` on Windows). A build from a source folder leaves `build/` and `scrolls_workbench.egg-info/` there (both gitignored) |
| Go-ahead | Not needed to install or test. Publishing the package anywhere new (such as PyPI) or tagging a release is an outward step that needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Public `main`: installable since 2026-10-14; version 0.4.1 fixes the offline viewer hover readout and includes Scrolls Starter and local viewer-state generation ([release](https://github.com/ChaseHendrick/Scrolls/releases/tag/workbench-v0.4.1)) |
| License | Apache-2.0 ([LICENSE](../../LICENSE), [NOTICE](../../NOTICE)). The letter reader's weights are separate works: `letters-v2-ccby` is CC BY 4.0 and `letters-v2-real` CC BY-NC 4.0 (`CITATION.cff`) |
| Guide | [letter-reader.md, "Install"](../letter-reader.md#install) |
| Checked | 2026-10-17 against commit `36d64e2` |

## What it does

The tools in `kit/` run from a clone as `python -m kit COMMAND`. `pyproject.toml` also lets anyone install them with pip, without cloning, under the distribution name `scrolls-workbench`. The installed package is the same `kit` folder: its version is `kit.__version__` (0.2.0), and the letter reader writes that version into every result's provenance.

The core (prizes, plan, cost, fetch, the run ledger, provenance) is standard library only, so a plain install has no dependencies. Three extras add what the other tools need: `reader` for Scroll Text Reader, `maps` for the map scoring and checks, and `all` for both. Five console scripts come with it: `scrolls-workbench` runs every `python -m kit` command, and `scrolls-letterread`, `scrolls-letterlines` and `scrolls-letterdemo` each run one reader command under their own name. `scrolls-start` opens [Scrolls Starter](starter.md), the local beginner app with an offline exercise and guided next steps.

The name is not `kit` or `scrolls-kit` on purpose. AutoPipeline's released package is the distribution `vc-autopipeline`, with a `scrolls-kit` script, and both install a top-level package named `kit`. Installed into one environment, one would overwrite the other, so each goes in its own virtual environment.

`check.yml` is the Kit checks workflow. It runs the whole test suite with no third-party package (the core), the letter reader as users get it on three systems, and every test with every extra plus the saved experiment regression tests. `CITATION.cff` gives the citation for the software (version 0.4.1) and for the reader's two sets of weights, which carry their own licenses.

Nothing here makes a claim. What the installed letter reader prints is model output, letter hypotheses for a person to check, not a reading.

## When to use it

- To use the letter reader or the scoring tools without a clone: install with the `reader`, `maps` or `all` extra.
- To pin the tools in another project's environment.
- To cite the workbench or the reader's weights: `CITATION.cff` (GitHub shows it as "Cite this repository").
- To see why a pull request fails CI: the jobs and steps under Commands and options.

Do not use it:

- For `python -m kit gate` and `python -m kit releases`: they read the repository's `docs/` and `README.md`, which the package does not include; run them from a clone, or give `--results`, or `--list` and `--readme`.
- In the same environment as AutoPipeline: make a separate virtual environment for each.
- For work on `kit` itself: clone and use `python -m kit`, or `python -m pip install -e ".[all]"` from the clone.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install "scrolls-workbench[reader] @ git+https://github.com/ChaseHendrick/Scrolls"
scrolls-workbench prizes
scrolls-letterdemo --out letterdemo
```

On Windows, activate with `.venv\Scripts\activate`. Add nothing in brackets for the core only, `[maps]` for the map tools, or `[all]` for both.

Run on 2026-10-16 with no extras, from a copy of commit `63ee638` (`git archive`) installed into a fresh virtual environment and called from another folder, it printed:

```
$ python -c "import kit, pathlib; print(kit.__version__, 'site-packages' in pathlib.Path(kit.__file__).parts)"
0.2.0 True
$ scrolls-workbench prizes
Open prizes, snapshot checked 2026-10-11 (https://scrollprize.org/prizes)
...
$ scrolls-letterdemo --quiet
DEMO ERROR: the letter reader needs numpy (No module named 'numpy'); python -m pip install "scrolls-workbench[reader]" (numpy, pillow, tifffile and imagecodecs)
```

That last line, with exit code 2, is the expected answer without the `reader` extra; the CI checks it. It worked when `kit.__version__` prints `0.4.1` from `site-packages` and `scrolls-workbench prizes` prints the prize table.

## Checks and controls

- **Installed, not the checkout.** The CI runs the installed package from outside the clone (`cd "$RUNNER_TEMP"`) and asserts that `kit` is imported from `site-packages`, so a test cannot pass by reading the checkout by accident.
- **The core really has no dependencies.** The `test` job runs the whole suite with no third-party package installed; tests that need numpy and the others skip there and run in the `reader` and `verify` jobs. The no-extras install must stop the demo with `DEMO ERROR` and exit code 2, not a traceback.
- **The released weights, end to end.** The `reader` job runs `scrolls-letterdemo` and `scrolls-letterread ... --weights letters-v2-ccby` on Linux, macOS and Windows with Python 3.10 and 3.13; the demo downloads the weights from the GitHub release named in `kit/data/letter-weights.json` and checks them by SHA-256.
- **pyproject against the code.** `tests/test_packaging.py` checks the name and dynamic version, the Python floor against the guide and the CI matrix, the empty core and the extras, the console scripts against `kit.cli` and against AutoPipeline's `scrolls-kit`, that every data file in `kit/` is packaged, and the license files.

Claim label: None; the package and the CI make no claim.

## Commands and options

### Extras

| Extra | Installs | For |
| --- | --- | --- |
| none | Nothing | The core: `prizes`, `plan`, `cost`, `fetch`, the run ledger, provenance |
| `reader` | `numpy`, `pillow`, `tifffile`, `imagecodecs` | The letter reader (`letterread`, `letterlines`, `letterdemo`) |
| `maps` | `numpy`, `tifffile`, `imagecodecs`, `zarr>=3; python_version >= '3.11'`, `scipy` | Map scoring and checks (`auc`, `verify`, `rowscore`, `hpscore`, `overlap`, `layers`); the set the CI's `verify` job uses |
| `all` | The union of `reader` and `maps` | Everything |

On Python 3.10 the `maps` and `all` extras leave zarr out, because pip would pick zarr 2.18, whose missing `create_array` breaks `kit shuffle` and the zarr outputs. The tools that read or write zarr then need Python 3.11 or newer.

### Console scripts

| Script | Entry point | What it runs |
| --- | --- | --- |
| `scrolls-workbench` | `kit.cli:workbench_main` | Every `python -m kit` command, with `scrolls-workbench` in its usage and errors |
| `scrolls-letterread` | `kit.cli:letterread_main` | `python -m kit letterread` ([letterread](letterread.md)) |
| `scrolls-letterlines` | `kit.cli:letterlines_main` | `python -m kit letterlines` ([letterlines](letterlines.md)) |
| `scrolls-letterdemo` | `kit.cli:letterdemo_main` | `python -m kit letterdemo`, which prints `DEMO PASS` or `DEMO FAIL` ([letterdemo](letterdemo.md)) |
| `scrolls-start` | `kit.cli:start_main` | `python -m kit start`, the local beginner app ([starter](starter.md)) |

Each command's options are on its own page; `scrolls-workbench COMMAND --help` prints them.

### The CI workflow, `.github/workflows/check.yml`

Name "Kit checks". It runs on a push to `main`, on every pull request, and by hand (`workflow_dispatch`), with read-only access to the repository (`permissions: contents: read`).

| Job | Runs on | Timeout | Steps |
| --- | --- | --- | --- |
| `test` | `ubuntu-latest`, Python 3.10 and 3.13 | 10 min | `python -m unittest discover -s tests -v` with nothing installed; a CLI smoke (`python -m kit prizes`, `python -m kit plan PHerc0826`, `python -m kit cost --gpu-hours 6.5 --rate 1.10`); then `python -m pip install .` and, from `$RUNNER_TEMP`, `scrolls-workbench prizes`, `scrolls-workbench plan PHerc0826` and `scrolls-letterdemo --quiet`, which must exit 2 |
| `reader` | `ubuntu-latest`, `macos-latest`, `windows-latest`, each with Python 3.10 and 3.13 (`fail-fast: false`, bash shell) | 20 min | `python -m pip install ".[reader]"`; the reader's tests (`test_letter*.py`, `test_greeklm.py`, `test_packaging.py`); from `runner.temp`, `scrolls-letterdemo --out letterdemo` and `scrolls-letterread letterdemo/demo-page.png --weights letters-v2-ccby --letter-px 32 --quiet --no-orientation` |
| `verify` | `ubuntu-latest`, Python 3.13 | 10 min | `python -m pip install ".[all]"`; the whole suite; then every folder under `scripts/experiments/` that holds a `test_*.py` ([experiment-records](experiment-records.md)), failing with `No experiment regression tests found` when there are none |

The installed Starter is checked outside the clone on Linux, macOS and Windows: `scrolls-start --portable --out starter-portable.html --no-open`, `scrolls-start --check`, and `scrolls-start --out starter-local.html --no-open`. The checks require the installed version in the setup JSON and both generated HTML files. The no-extras job also checks portable output and the setup command.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `RUNNER_TEMP` | Set by GitHub Actions | A folder outside the checkout, where the `test` job runs the installed scripts (the `reader` job uses `runner.temp`, the same folder) |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `kit.__version__` | str, `"0.2.0"` | Nothing | The package version; pyproject reads it (`version = { attr = "kit.__version__" }`) |
| `kit.cli.workbench_main(argv=None)` | The command's return value, used as the exit code | `SystemExit` from argparse (code 2) on a usage error | `scrolls-workbench`; `argv` defaults to `sys.argv[1:]` |
| `kit.cli.letterread_main(argv=None)`, `letterlines_main(argv=None)`, `letterdemo_main(argv=None)`, `start_main(argv=None)` | As above | As above | One command each, through `_console`, with the script's name in usage and errors |
| `kit.cli.CONSOLE_SCRIPTS` | dict | Nothing | `{"scrolls-letterread": "letterread", "scrolls-letterlines": "letterlines", "scrolls-letterdemo": "letterdemo", "scrolls-start": "start"}` |

## Inputs

| Input | Notes |
| --- | --- |
| The source tree | `pyproject.toml` packages the folder `kit` (`packages = ["kit"]`) and its data files `kit/data/*.json` (the prize snapshots and the letter-weights registry), plus `kit/data/starter.html` and `starter.js` for the self-contained beginner app; nothing from `docs/`, `scripts/` or `tests/` |
| `README.md` | The package's long description |
| `LICENSE`, `NOTICE` | The license files (`license-files`) |
| The extra in brackets | `reader`, `maps`, `all`, or none |

## Outputs

An installed distribution `scrolls-workbench` (version in `kit/__init__.py`): the `kit` package in `site-packages`, its data files, the five console scripts, and its metadata (name, version, summary, Apache-2.0, the project URLs "Source" and "Scroll Text Reader guide"). The CI's result is the check status GitHub shows on the commit or pull request.

| Exit code | Meaning |
| --- | --- |
| `0` | pip installed it; a console script's command succeeded |
| `1` | pip failed (for example no network to fetch `setuptools>=77`); a console script's own failure, as its page says |
| `2` | A usage error from a console script (`scrolls-workbench: error: ...`), or `DEMO ERROR` from `scrolls-letterdemo` without the `reader` extra |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `DEMO ERROR: the letter reader needs numpy (No module named 'numpy'); python -m pip install "scrolls-workbench[reader]" (numpy, pillow, tifffile and imagecodecs)`, exit code 2 | Installed without the `reader` extra | Install `scrolls-workbench[reader]` |
| `scrolls-workbench: error: argument command: invalid choice: ...`, exit code 2 | No such command | `scrolls-workbench --help` lists them |
| `cannot read the scores: no .../site-packages/docs/results.json. The gate reads the repository's docs/results.json, which an installed package does not have: ...` | `scrolls-workbench gate` outside a clone | Run it from a clone, or give `--results` |
| `releases: no release list at .../site-packages/docs/releases.json; it reads the repository's docs/releases.json and README.md, which an installed package does not have: ...` | `scrolls-workbench releases` outside a clone | Run it from a clone, or give `--list` and `--readme` |
| `externally-managed-environment` from pip | The system Python refuses installs outside a virtual environment (PEP 668) | Make and activate a virtual environment first ([guide](../letter-reader.md#install)) |
| `kit` turns out to be AutoPipeline's, or AutoPipeline's `kit` turns out to be this one | Both packages install a top-level `kit` in one environment | One virtual environment per package |
| zarr tools fail on Python 3.10 after `pip install ".[maps]"` | The extras leave zarr out on 3.10 | Use Python 3.11 or newer for zarr inputs and outputs |
| The install of `@workbench-v0.2.0` fails | `CHANGELOG.md` names the tag `workbench-v0.2.0`, which was not on GitHub when this page was checked (2026-10-16, `git ls-remote --tags`) | Install from `main`, or pin a commit: `@63753fa` is the merge of PR #102 |
| `BrokenPipeError: [Errno 32] Broken pipe` and a traceback after `scrolls-workbench prizes \| head` | The command keeps printing after `head` closed the pipe | Harmless; redirect to a file instead of piping into `head` |
| The `test` job's `PyprojectTest` tests are skipped on Python 3.10 | `tomllib` needs Python 3.11 | Expected; Python 3.13 runs them |

## How it works

1. `pip install` builds the package with setuptools (`setuptools>=77`, `build-backend = "setuptools.build_meta"`), reading the version from `kit.__version__` and packaging `kit` with `kit/data/*.json`.
2. Each console script is a small wrapper that calls its function in `kit.cli`. `workbench_main` calls `main(argv, prog="scrolls-workbench")`, the same entry point as `python -m kit`. The one-command scripts call `_console`, which builds the parser with that command's program name set to the script's (`sub_progs`) and parses `argv` with that subcommand's parser alone.
3. `kit` reads its data files from `kit/data/` beside its own code, so the installed copy finds the prize snapshots and the weights registry without a clone.
4. On every push to `main` and every pull request, GitHub runs the three CI jobs in parallel; the `reader` matrix runs 6 combinations and does not stop the others when one fails.

## Cost and time

Installing without extras from a local copy took about 6 s (2026-10-16, cloud container, Python 3.13, with network for `setuptools`). With extras it also downloads their wheels; Not measured. The CI's run times are Not measured here; its timeouts are 10 min (`test`, `verify`) and 20 min (`reader`). GitHub-hosted runners cost nothing for this public repository's Actions; nothing rents compute.

## For agents

- **Command:** `python -m pip install "scrolls-workbench[reader] @ git+https://github.com/ChaseHendrick/Scrolls"` in a fresh virtual environment; check with `python -c "import kit; print(kit.__version__)"`.
- **Parse:** `kit.__version__` (`0.2.0`); `pip show scrolls-workbench` for the installed version and location; the CI's check status on the pull request.
- **Rerun:** Safe; reinstalling replaces the installed copy. A build from a source folder rewrites its `build/` and `*.egg-info/`, which are gitignored.
- **Success:** pip exits 0, `kit.__version__` is `0.2.0`, and `scrolls-workbench prizes` exits 0. In CI, all three jobs pass.
- **Not a pass:** Tests run from the checkout, which import `kit` from the clone rather than the installed copy; a `reader` job that passed only on Linux; a green `test` job alone, where the reader's and map tools' tests skip.
- **Go-ahead:** Publishing to PyPI or another index, creating or moving a release tag, or uploading anywhere.
- **Never:** Edit `pyproject.toml`'s name or version or `CHANGELOG.md` without the owner's say; install it in the same environment as AutoPipeline; add a dependency to the core (it must stay standard library only).

## Tests

```bash
python -m unittest tests.test_packaging -v
```

They check `pyproject.toml` (name, dynamic version, `requires-python`, empty core, extras, zarr pinned to 3 on Python 3.11 or newer, console scripts against `kit.cli` and AutoPipeline's, package data, license files; these need `tomllib`, so they skip on Python 3.10), that each one-command script shows its own name in usage and errors, that `scrolls-workbench` runs every command, that the data the package reads lives in `kit/data/`, LF line endings in `.gitattributes`, and that the CI runs the reader and its demo on three systems. They do not build or install the package; the CI's `test` and `reader` jobs do.

## History

- 2026-10-16: version 0.2.0, the first with a changelog; `CITATION.cff` at 0.2.0 (`00b0097`, [PR #102](https://github.com/ChaseHendrick/Scrolls/pull/102)).
- 2026-10-14: `letters-v2-ccby` (CC BY 4.0) becomes the reader's default weights, and the CI demo reads with it (`0366ed7`).
- 2026-10-14: `CITATION.cff` added with the guide and checks (`e30ff76`).
- 2026-10-14: the package becomes installable, with the reader extra, the console scripts, an offline demo and CI on Linux, macOS and Windows (`2582ab7`).
- 2026-10-07: the saved experiment regression tests run in the `verify` job (`b768319`).
- 2026-10-07: the `verify` job installs zarr so the `kit layers` and `kit auc` tests run (`6461572`).
- 2026-10-06: first CI workflow (`2daee8e`).

## Related

- [`CHANGELOG.md`](../../CHANGELOG.md): what each version holds.
- [letter-reader.md, "Install"](../letter-reader.md#install): installing on macOS, Linux and Windows.
- [letterread](letterread.md), [letterlines](letterlines.md), [letterdemo](letterdemo.md): the commands behind the one-command scripts.
- [experiment-records](experiment-records.md): the saved tests the `verify` job runs.
- [releases](releases.md): the README's "Released tools" list, which the package does not carry.
