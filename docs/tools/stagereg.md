# stagereg: pick any stage's option by name, in any workflow

The stage registry lists every option we know for each stage of reading a scroll (ours, the community's, the organisers' team models), with licence and maturity, and lets every workflow pick one by name.

| Field | Value |
| --- | --- |
| Id | `stagereg` |
| Status | Current |
| Kind | kit command,kit module |
| Area | Pipeline and agents |
| Run | `python -m kit stages` |
| Code | `kit/stagereg.py` |
| Tests | `tests/test_stagereg.py` |
| Needs | Python 3.10 or newer, standard library only; the data file `kit/data/stages.json` |
| Runs on | CPU, under a second (measured 2026-10-25 in a 4-core cloud container) |
| Network | None |
| Writes | Nothing (prints only) |
| Go-ahead | Not needed: it chooses, it never runs a stage |
| Released | Public `main` from this change (25 Oct 2026) |
| Checked | 2026-10-25 against commit `cac6c1f` |

## What it does

Each stage of reading a scroll (centre line, surface prediction, lasagna field, spiral fit, trace, repair, snap, flatten, render, ink, ensemble, letters and others) has more than one option: villa's tools, community models, the organisers' team models and our own. The registry is one list of them. Each option says who made it (origin: ours, community, team or published), its licence, its maturity, why it has that maturity, and which workflows can run it, so a workflow swaps a stage by naming an option instead of by editing code.

Maturity is one scale for every stage: `default` (what a workflow runs when nothing is named), `validated` (a held-out or published benchmark with its control), `experimental` (it runs; no passing held-out result here yet), `pending` (still in development checks; refused until it passes) and `failed` (failed a frozen test or its controls; kept for comparisons). Naming an option is the opt-in: an experimental option runs when named, and its maturity and why go into the run's record. The registry never makes an experimental option a default.

Licences are stated per option. Code or weights with no stated licence are only read from their own host at run time (`fetch: runtime`), never copied; `check` fails a row that breaks this.

Where a workflow already has a backend table, an extension module `kit/stagereg_ext_NAME.py` reads it instead of repeating it, and can add workflows. The facts no code table carries live in `kit/data/stages.json`. In this repository the workflow that picks through it is [scroll2ink](scroll2ink.md) (`--use ink=d9v2`).

## When to use it

- To see what options a stage has and which a workflow can run: `python -m kit stages list STAGE`.
- To swap a stage in a scroll2ink run: `python -m kit scroll2ink run ... --use ink=v8in` (or `KIT_STAGE_INK=v8in` in the environment).
- To make a new workflow choose its stages: call `stagereg.add_arguments(parser)` and `stagereg.picks(args.use, "WORKFLOW")`, and keep `stagereg.record(...)` in the run's record.
- To add a new tool as a stage option: a row in `kit/data/stages.json` (with `use` for the workflow that runs it, or `reach` for where to get it).

Do not use it:

- to score an option: use [auc](auc.md) with its control;
- to check whether a machine can run a tool: use `python -m kit doctor`.

## Quick start

```bash
python -m kit stages list ink
python -m kit stages pick ink --workflow scroll2ink --use d9v2 --json
```

Printed on 25 Oct 2026 (excerpt):

```text
ink: the ink reader: 2.5D (reads the render's layers) or 3D (reads the scan around the mesh) (defaults: scroll2ink reader-v2)
  d9v2: validated, 2.5d; community; none stated on its model page (checked 25 Oct 2026); fetched from its own repo, never copied; runs in scroll2ink
  reader-v2: default, 2.5d; community; MIT (Domenico Russo); runs in scroll2ink
```

It worked when `pick` exits 0 and prints the option with `picked_by`.

## Checks and controls

`python -m kit stages check` (and `tests/test_stagereg.py`) fails when an option names an unknown stage, a maturity off the scale or an origin off the list; when a data row has no licence, or is unlicensed without `fetch: runtime`; when an experimental, pending or failed data row does not say why; when no workflow runs an option and no `reach` says how to get it; when a data row is listed twice (a later file may annotate an earlier file's option with a row that has no `by` but never list it again); or when a workflow's default is missing or cannot run there. The test plants each of these faults and requires the check to name it.

Claim label: Sourced fact, for the catalogue's own consistency; each option's `why` carries its own label in its source.

## Commands and options

### `python -m kit stages`

```
usage: python -m kit stages [-h] ...
```

The rest of the line goes to the registry's own parser (`usage: python -m kit stages [-h] {list,show,pick,check} ...`).

| Option | Default | Meaning |
| --- | --- | --- |
| `cmd` | none | The action and its arguments: `list`, `show`, `pick` or `check`, as below |
| `list [STAGE] [--workflow W] [--json]` | every stage | Every option, or a stage's; with `--workflow`, only those that workflow can run |
| `show STAGE NAME [--json]` | none | One option in full |
| `pick STAGE --workflow W [--use NAME] [--json]` | the workflow's default | What the workflow would use and why; NAME may list several with commas |
| `check [--json]` | none | The catalogue against its rules; exit 1 with the problems |

### `--use STAGE=NAME` in a workflow

`python -m kit scroll2ink run ... --use STAGE=NAME` (repeatable). The pick sets the run's own option (the ink reader is `--model`) and goes into `settings.json` under `stages`, with its maturity; a pick that contradicts an option given outright is refused, and so is one scroll2ink cannot run.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_STAGE_<STAGE>` | unset | The option a workflow picks for that stage when none is named, such as `KIT_STAGE_INK=v8in`; scroll2ink records it in `settings.json` |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `StageError()` | an exception | none | A `ValueError`; every refusal |
| `catalogue(refresh=False, files=FILES, folder=DATA)` | `({(stage, name): option}, {workflow: {stage: name}})` | `StageError` on a bad data file | {(stage, name): option} and {workflow: {stage: default name}} from every source. |
| `options(stage=None, workflow=None)` | list of options | none | The options of a stage (or every stage), those a workflow can run when one is named, in a stable order. |
| `find(stage, name)` | one option | `StageError` | Unknown stage or option |
| `default(stage, workflow)` | a name or `None` | none | The workflow's default for that stage |
| `env_name(stage)` | `KIT_STAGE_<STAGE>` | none | The environment variable for a stage |
| `pick(stage, workflow, name=None, env=None)` | an option, or a list for a comma list | `StageError` | The option a workflow uses for a stage: the one named, else KIT_STAGE_<STAGE>'s, else the workflow's default. |
| `record(option)` | a dict (or list) | none | What a run's record keeps about the option it used. |
| `add_arguments(parser)` | the parser | none | Adds `--use STAGE=NAME` |
| `uses(values)` | `{stage: name}` | `StageError` | {stage: name} from --use STAGE=NAME values; refuses a malformed one or a stage named twice. |
| `picks(values, workflow, env=None, stages=None)` | `{stage: option}` | `StageError` | {stage: picked option} for every stage named by --use (or the environment), checked for this workflow. |
| `ap_settings(picked)` | AutoPipeline settings | `StageError` | AutoPipeline settings for the picked options: AutoPipeline's backends shorthand, for copies that run AutoPipeline |
| `check(files=FILES, folder=DATA)` | list of problems | `StageError` on a bad data file | Problems with the catalogue: every option names a known stage, a maturity on the scale, an origin and a licence |
| `main(argv=None)` | exit code | none | The command line |


## Inputs

The data files are JSON, schema `scrolls-stages/1`: `{"schema", "about", "defaults": {workflow: {stage: name}}, "options": [row]}`. A row has `stage`, `name`, and as needed `by`, `origin` (ours, community, team or published), `licence`, `maturity`, `why`, `dims` (`2.5d` or `3d`, ink only), `use` (`{workflow: how}`: AutoPipeline takes `{"backend": NAME}` or `{"settings": {...}}`, scroll2ink `{"args": [...]}`, the command line `{"command": [...]}`), `reach` (how to get an option no workflow runs) and `fetch` (`runtime` for unlicensed code).

## Outputs

`list` and `show` print lines, or JSON with `--json` (a list of options, or one option, with the fields above plus `source`, the files it came from). `pick --json` prints `record()`: `stage`, `name`, `origin`, `by`, `licence`, `maturity`, `dims`, `picked_by` (`named`, `KIT_STAGE_<STAGE>` or `default`) and `warning` when the maturity is not default or validated.

| Exit code | Meaning |
| --- | --- |
| `0` | Success; for `check`, no problems |
| `1` | `check` found problems (printed) |
| `2` | A refusal (`kit stages: ...` on stderr), or a usage error |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit stages: MESSAGE` on stderr, exit code 2 | A refusal; MESSAGE is one of the rows below | As that row says |
| `no stage STAGE; stages: ...` | A stage name the registry does not have | Use one listed |
| `STAGE: no option NAME; options: ...` | An option the stage does not list | Use one listed, or add a row |
| `WORKFLOW has no default for STAGE: name one (--use STAGE=NAME)` | The workflow has no default for that stage | Name one with `--use STAGE=NAME` |
| `STAGE NAME is pending (WHY): it runs once it passes and its maturity changes` | The option is still in development checks | Wait for its checks, or pick another option |
| `STAGE NAME is listed but WORKFLOW cannot run it; it runs in ...` | This workflow has no way to run the option | Use a workflow it names, or follow its `reach` |
| `--use 'VALUE': give STAGE=NAME` | A `--use` value without `=` | Write `--use ink=d9v2` |
| `--use 'VALUE': no stage STAGE; stages: ...` | A `--use` stage the registry does not have | Use one listed |
| `--use names STAGE twice` | One stage named twice | Name it once (a comma list where the stage takes several) |
| `PATH: not JSON (...)` | A data file does not parse | Fix the JSON |
| `PATH: schema is not scrolls-stages/1` | A data file has another schema | Fix the file's `schema` |
| `STAGE NAME: AutoPipeline cannot run it` | An option with no AutoPipeline route was passed to AutoPipeline's settings | Pick an option `list --workflow autopipeline` shows |

## How it works

`catalogue()` collects each extension's `rows()`, then lays the data files over them by `(stage, name)`. A row from a code table keeps its own description and gains the data row's facts; a data row with no `by` only annotates an option listed elsewhere. An option with no maturity is `experimental`, an off switch `validated`, and a workflow's default `default`. `pick()` resolves a name, refuses a pending option first, then one the workflow cannot run (with its `reach`), and adds a warning for any maturity other than default or validated.

## Cost and time

Under a second; it reads one JSON file.

## For agents

- **Command:** `python -m kit stages list STAGE --workflow WORKFLOW --json`; to swap in scroll2ink, `python -m kit scroll2ink run ... --use STAGE=NAME`.
- **Parse:** each option's `name`, `maturity`, `dims`, `use` and `why`; `pick --json` gives `picked_by` and `warning`.
- **Rerun:** safe; it writes nothing.
- **Success:** exit 0; for `check`, `stage registry: no problems`.
- **Not a pass:** an option listed here is not evidence that it works; only its `why` and its source say how far it is proven.
- **Go-ahead:** Nothing for the registry; running a picked option follows that workflow's rules.
- **Never:** never make an option a default without a passing held-out result; never copy unlicensed code or weights to make them runnable (`fetch: runtime`).

## Tests

`python -m unittest tests.test_stagereg`: the shipped catalogue passes `check`; planted faults each fail; picks by name, environment and default; refusals for unknown and unrunnable options; `--use` parsing; scroll2ink's `--use` setting `--model` and recording the pick. It does not run any stage.

## History

- 2026-10-25: first version, with scroll2ink's `--use` (`fb2170a`).

## Related

- [scroll2ink](scroll2ink.md): the workflow that picks its stages through the registry here.
- [auc](auc.md): scoring a picked ink reader against its control.
