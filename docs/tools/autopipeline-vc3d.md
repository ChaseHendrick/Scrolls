# autopipeline-vc3d: plan AutoPipeline runs from a VC3D point and open the results in VC3D

`integrations/vc3d/ap_vc3d.py` links the released AutoPipeline (0.1.5) and villa's VC3D both ways: it plans a run seeded at a VC3D focus point, starts that exact plan, and copies or attaches the accepted surfaces and seed points back in VC3D.

| Field | Value |
| --- | --- |
| Id | `autopipeline-vc3d` |
| Status | Experimental |
| Kind | script |
| Area | Pipeline and agents |
| Run | `python3 integrations/vc3d/ap_vc3d.py here`, `python3 integrations/vc3d/ap_vc3d.py start`, `python3 integrations/vc3d/ap_vc3d.py load`, `python3 integrations/vc3d/ap_vc3d.py open`, `python3 integrations/vc3d/ap_vc3d.py manifests` |
| Code | `integrations/vc3d/ap_vc3d.py`, `integrations/vc3d/README.md` |
| Tests | `tests/test_integrations_vc3d.py`, with the stand-in plugin host `tests/vc3d_plugin_host.py` |
| Needs | Python 3.10 or newer, standard library only. `here` and `start`: an AutoPipeline environment with `scrolls-kit` (0.1.5, `submission/progress-2026-10-fix5`). `here --bridge` and `open`: VC3D from villa `main` started with `--agent-bridge`, on Linux or macOS (Unix socket). `manifests`: useful only with VC3D's plugin host, which is not in villa yet |
| Runs on | Any CPU. `here` against the released 0.1.5 package took about 1 s on PHerc0841 (catalog headers only; 21 October 2026, Claude cloud container). `start` returns in under 2.5 s by test. `load` copies tifxyz folders, a few MB per trace |
| Network | Only what `scrolls-kit autopipeline plan` reads (the open-data bucket's headers). The script itself opens no network connection; the bridge is a local Unix socket |
| Writes | `AP_VC3D_HOME` (default `~/.autopipeline-vc3d`): `last.json`, `runs/DIGEST16.pid` and `runs/DIGEST16.log`, `open/DIGEST16/` for `open`. `load`: `DEST/segments/ap-DIGEST10-SID/`, `DEST/seeds.json`, `DEST/load.json`. `--summary FILE` writes the printed text. `manifests --install DIR`: four `autopipeline-*.json` files. AutoPipeline itself writes its run folder |
| Go-ahead | Not needed: it plans and runs AutoPipeline locally and never starts paid compute; ink without a GPU environment stops at a handoff file. Posting its media or output anywhere needs Chase's yes (the go-ahead rule, hard rule 8) |
| Released | Not yet: branch `claude/apguide-1020` of public Scrolls, for a PR into `main` (21 October 2026) |
| Guide | [AutoPipeline how-to guide](../autopipeline/guide.md), sections 5 and 6; [`integrations/vc3d/README.md`](../../integrations/vc3d/README.md) |
| License | Apache License 2.0, the repository's |
| Checked | 2026-10-21 against commit `249096b` |

## What it does

AutoPipeline (AP) runs villa's pipeline on one catalog scan without a person in between. VC3D is where people look at scans and edit surfaces. Until now the two met only through files and copied numbers. This script joins them in both directions without changing either.

**VC3D to AutoPipeline.** `here` takes a VC3D focus point (x, y, z in full-resolution voxels) and the open volume, works out the catalog scan from the volume's location, and runs `scrolls-kit autopipeline plan` with that volume and the point as the only seed. It computes nothing and prints the run folder, the plan digest and the exact start command. `start` checks that digest, refuses a second run of the same plan while one is going, and starts the run in the background so VC3D stays free.

**AutoPipeline to VC3D.** `load` copies the surfaces the run's rule accepted (tifxyz folders) and writes the seed points as a VC3D point collection. `open` does the same, then asks a running VC3D over its agent bridge (villa's `apps/VC3D/agent_bridge/SPEC.md`) to attach the volume, the segments and the points, calling only the methods VC3D lists in `rpc.describe`.

**The Plugins menu.** `manifests` writes four plugin manifests (schema `vc3d-plugin/1`) so the same commands appear under Plugins > AutoPipeline. VC3D's plugin host is part of the combined VC3D change that Chase will post to villa; VC3D on villa `main` has no Plugins menu and ignores these files.

It does not render, score or move ink maps: AutoPipeline's maps are on the render canvas, and VC3D's ink overlays need the segment's own grid. Every surface it moves is model output, not a reading.

## When to use it

- You have a point on the papyrus in VC3D and want AutoPipeline to trace from there.
- A run finished and you want its accepted surfaces in VC3D to inspect or edit them.
- An agent drives VC3D over its bridge and needs AutoPipeline runs started from what is open.

Do not use it:

- To plan a published segment benchmark or an external prediction: use `scrolls-kit autopipeline plan` directly; `here` refuses `segment` and `external_prediction`.
- For a scan outside the open-data catalog: AutoPipeline plans only catalog scans.
- To check a surface by itself: use the agent tool `scrolls-kit vc3d call check_surface` in the AutoPipeline package.

## Quick start

```bash
. AP_DIR/.venv/bin/activate          # the AutoPipeline 0.1.5 environment
python3 integrations/vc3d/ap_vc3d.py here --point 3960,3700,9500 \
  --volume https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/PHerc0841/volumes/20250821151531-9.366um-1.2m-113keV-masked.zarr/
python3 integrations/vc3d/ap_vc3d.py start --run last --digest last
python3 integrations/vc3d/ap_vc3d.py load --run last --dest OUT
```

`AP_DIR` is the AutoPipeline package folder; `OUT` is any new folder. Run on 21 October 2026 against the released 0.1.5 package, `here` printed:

```text
AutoPipeline plan made. Nothing was computed or launched.
Scan: PHerc0841, volume 20250821151531
Seed point (x,y,z, full-resolution voxels): 3960,3700,9500
Run folder: AP_DIR/work/autopipe/PHerc0841-20250821151531-1a064eceed
Plan digest: 1a064eceed518d326dde681ad249f91f81655c3d8e3d9aa26207960917dce59c
```

On the synthetic demo's run folder, `load` printed `Copied 2 accepted surface(s)` and `Wrote 2 seed point(s)`. It worked when the exit code is 0 and `OUT/segments/` holds one `ap-DIGEST10-SID` folder per accepted surface.

## Checks and controls

- **The digest check can fail.** `start` refuses a plan whose `plan.json` digest does not begin with the digest given (at least 10 characters). `tests/test_integrations_vc3d.py` shows a wrong and a too-short digest refused, with no `autopipeline run` started.
- **Only accepted surfaces move.** `load` skips any surface whose `accepted` is not true in `state.json`; the test's stand-in run has one accepted and one rejected surface, and only the accepted one is copied.
- **The manifest rules can fail.** The stand-in host refuses unknown keys, a program with placeholders, a bad id, unknown placeholders, undeclared inputs, a result path outside `{output}/` and an unknown result kind; a test shows each refused. With `VILLA_ROOT` set to a villa checkout that has the plugin host, a test compares the host's placeholders, result kinds and keys with villa's `docs/plugins.md` (passed on 21 October 2026 against the plugin branch).
- **Bridge calls are limited to what VC3D offers.** `open` calls nothing that `rpc.describe` does not list; a test with a stand-in bridge that lacks `viewer.center_on_point` shows it skipped, and a refused call stops `open` with exit 2.

Claim label: None; the tool plans, starts and copies, and makes no measurement.

## Commands and options

### `python3 integrations/vc3d/ap_vc3d.py here`

```text
usage: ap_vc3d.py here [-h] [--point POINT] [--volume VOLUME] [--settings SETTINGS] [--bridge] [--socket SOCKET]
                       [--kit KIT] [--summary SUMMARY] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--point` | none | x,y,z in full-resolution voxels (VC3D's `{point}`) |
| `--volume` | none | The open volume's URL or path (VC3D's `{volume}`) |
| `--settings` | `{}` | AutoPipeline settings over the defaults, a JSON object |
| `--bridge` | off | Read the point and volume from a running VC3D |
| `--socket` | none | VC3D bridge socket (default: the newest live one) |
| `--kit` | none | The `scrolls-kit` command of the AutoPipeline environment (default: `AP_KIT`, then `scrolls-kit` on `PATH`) |
| `--summary` | none | Also write the printed text to this file |
| `--json` | off | Print one JSON object instead of text |

### `python3 integrations/vc3d/ap_vc3d.py start`

```text
usage: ap_vc3d.py start [-h] [--run RUN] [--digest DIGEST] [--kit KIT] [--summary SUMMARY] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--run` | `last` | Run folder, or `last` (the plan `here` made last) |
| `--digest` | `last` | The plan digest you saw (at least 10 characters), or `last` |
| `--kit` | none | As for `here` |
| `--summary` | none | Also write the printed text to this file |
| `--json` | off | Print one JSON object instead of text |

### `python3 integrations/vc3d/ap_vc3d.py load`

```text
usage: ap_vc3d.py load [-h] [--run RUN] --dest DEST [--need {any,segments,seeds}] [--summary SUMMARY] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--run` | `last` | Run folder, or `last` |
| `--dest` | required | Folder to write `segments/`, `seeds.json` and `load.json` into |
| `--need` | `any` | Refuse unless this was written: `any`, `segments` or `seeds` |
| `--summary` | none | Also write the printed text to this file |
| `--json` | off | Print one JSON object instead of text |

### `python3 integrations/vc3d/ap_vc3d.py open`

```text
usage: ap_vc3d.py open [-h] [--run RUN] [--dest DEST] [--socket SOCKET] [--summary SUMMARY] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--run` | `last` | Run folder, or `last` |
| `--dest` | none | Folder for the copies (default: `AP_VC3D_HOME/open/DIGEST16`) |
| `--socket` | none | VC3D bridge socket (default: the newest live one) |
| `--summary` | none | Also write the printed text to this file |
| `--json` | off | Print one JSON object instead of text |

### `python3 integrations/vc3d/ap_vc3d.py manifests`

```text
usage: ap_vc3d.py manifests [-h] [--install INSTALL] [--force] [--kit KIT] [--summary SUMMARY] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--install` | none | Write the manifests into this folder instead of printing them |
| `--force` | off | Replace manifests that differ |
| `--kit` | none | As for `here`; written into the manifests as an absolute path |
| `--summary` | none | Also write the printed text to this file |
| `--json` | off | Print one JSON object instead of text |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `AP_KIT` | none | The `scrolls-kit` command to run, when `--kit` is not given |
| `AP_VC3D_HOME` | `~/.autopipeline-vc3d` | Where `last.json`, `runs/` and `open/` go |

## Python API

Not applicable: a command-line script; `tests/test_integrations_vc3d.py` imports it by path, but it is not a supported library.

## Inputs

- **Point:** three numbers at or above 0, `x,y,z`, in full-resolution (level 0) voxels of the open volume, as VC3D's `{point}` or `state.get`'s `focusPoi.position` gives it. AutoPipeline's `seeds.points` uses the same frame.
- **Volume:** an open-data catalog volume, `.../SAMPLE/volumes/ID-....zarr`, where `SAMPLE` starts with `PHerc` and `ID` has 14 digits, as a URL or a local copy that keeps the bucket's layout (`VOLUME_PATTERN`).
- **Settings:** a JSON object over AutoPipeline's defaults; `segment`, `external_prediction`, `seeds.points` and a different `volume` are refused.
- **Run folder:** an AutoPipeline run folder with `plan.json` (`digest`, `resolved.volume_url`) and, after a run, `state.json` (`surfaces.SID.surface`, `surfaces.SID.accepted`) and `seeds.json` (`seeds[].xyz`).
- **Bridge:** VC3D's agent bridge socket, from `--socket` or the newest live record under `~/.vc3d/agent_bridge/` (`pid`, `path`, `startedAt`).

## Outputs

Text by default; with `--json`, one JSON object. `here --json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `sample`, `volume` | string | Catalog sample and 14-digit volume id |
| `point_xyz` | list of 3 numbers | The seed point, full-resolution voxels |
| `out` | string | The run folder AutoPipeline made |
| `digest` | string | The plan digest (SHA-256, hex) |
| `volume_url` | string | The scan's URL from the plan |
| `settings` | object | The settings passed to `plan` |
| `start_command` | string | The exact `start` command for this plan |

`start --json`: `out`, `digest`, `pid` (the background process) and `log`. `load --json` and `DEST/load.json`: `segments` (one `{surface, segment}` per copy), `skipped` (`{surface, why}`), `segments_dir`, `seeds`, `seed_points`, `volume_url` and a `note`. `open --json` adds `bridge_calls`: `{method, done, why}` per call. `DEST/seeds.json` is a VC3D point collection: `vc_pointcollections_json_version` `"1"`, one collection named `AutoPipeline seeds DIGEST10`.

| Exit code | Meaning |
| --- | --- |
| `0` | Done: planned, started, copied, opened or written |
| `2` | Refused; the reason is on stderr after `ap_vc3d:` (and in `--summary`), or an argument error |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `no scrolls-kit command: activate the AutoPipeline environment, or pass --kit PATH or set AP_KIT to its scrolls-kit` | No AutoPipeline command found | Activate the package's `.venv`, or pass `--kit` |
| `the point must be x,y,z: three numbers at or above 0 in full-resolution voxels, not` | The point is malformed, negative or not finite | Copy VC3D's focus point as three numbers |
| `is not an open-data catalog volume (.../SAMPLE/volumes/ID-....zarr); AutoPipeline plans only catalog scans` | The volume is not a catalog scan, or VC3D reports a local cache path | Pass the catalog URL with `--volume` |
| `the settings are not JSON:` | `--settings` does not parse | Fix the JSON |
| `the settings must be a JSON object` | `--settings` is a list or a value | Give an object such as `{"trace": {"repeats": 2}}` |
| `replaces the seed point; plan it with scrolls-kit autopipeline plan instead` | `segment` or `external_prediction` was given | Plan those directly with `scrolls-kit autopipeline plan` |
| `differs from the volume open in VC3D (` | The settings name another volume | Leave `volume` out |
| `setting seeds must be a JSON object` | `seeds` is not an object | Fix the settings |
| `setting seeds.points is filled from the VC3D point; leave it out` | Points were given twice | Leave `seeds.points` out |
| `autopipeline` ... `exited` | `scrolls-kit autopipeline plan` refused (exit 2) or failed; its last lines follow | Read them; the reference's troubleshooting table explains each |
| `did not finish in` | `plan` took over 600 s | Check the network to the open-data bucket |
| `cannot run` | `--kit` or `AP_KIT` names no program | Fix the path |
| `is missing); run ap_vc3d.py here first, or name the run folder` | `--run last` with no plan made here | Run `here`, or pass the run folder |
| `has no plan.json; name an AutoPipeline run folder` | The folder is not a run folder | Pass the `out` folder `plan` printed |
| `...; plan again with ap_vc3d.py here` | The digest does not match the plan | Plan again and start with the new digest |
| `); watch it with scrolls-kit autopipeline status` | A run of this plan started here is still going | Wait for it, or watch it with `status` or `monitor` |
| `yet; check scrolls-kit autopipeline status` | No accepted surface or seed points yet (or the one `--need` asked for) | Let the run reach qa, then load again |
| `no running VC3D bridge: start VC3D with --agent-bridge, or pass --socket PATH` | No live record under `~/.vc3d/agent_bridge/` | Start `VC3D --agent-bridge` |
| `cannot reach VC3D's bridge at` | The socket is gone or not VC3D's | Restart VC3D with `--agent-bridge` |
| `VC3D's bridge gave no reply to` | VC3D closed the connection | Check VC3D's console |
| `VC3D refused` | A bridge call failed, such as no open project | Open or create a project in VC3D, then run `open` again |
| `VC3D has no volume open` | `here --bridge` with no volume | Open the scan in VC3D |
| `VC3D has no focus point; click on the papyrus first` | No focus point yet | Click on the papyrus |
| `give --point and --volume, or --bridge to read them from VC3D` | Neither was given | Give both, or `--bridge` |
| `exists and differs; read it, then pass --force to replace it` | A manifest in the folder was edited or is older | Read it, then `--force` |

## How it works

1. `here` parses the point, matches the volume against `VOLUME_PATTERN` to get the sample and volume id, merges `{"volume": ID, "seeds": {"points": [[x, y, z]]}}` over the given settings, and runs `scrolls-kit autopipeline plan SAMPLE --settings JSON` (timeout 600 s). It saves the result as `AP_VC3D_HOME/last.json`.
2. `start` reads the run folder's `plan.json`, compares its digest with the one given, checks `runs/DIGEST16.pid` for a live process, and starts `scrolls-kit autopipeline run FOLDER` in a new session with its output in `runs/DIGEST16.log`.
3. `load` reads `state.json` and copies each accepted surface's tifxyz folder (`surface`, the trace as grown, in the scan's frame) to `DEST/segments/ap-DIGEST10-SID`, and converts `seeds.json` to VC3D's point collection format.
4. `open` runs `load`, then sends newline-delimited JSON-RPC 2.0 messages to VC3D's bridge socket (timeout 30 s each, `BRIDGE_TIMEOUT`): `rpc.describe`, then `volume.attach`, `segments.attach`, `points.load_json` and `viewer.center_on_point` on the first seed, each only when listed.
5. `manifests` builds four manifests with this machine's Python, this script and `scrolls-kit` as absolute paths; the plugin host passes arguments with no shell and loads only the declared result from the run's own output folder.

## Cost and time

Free: it runs locally and starts nothing paid. `here` took about 1 s against the released package (21 October 2026, Claude cloud container); the 23 tests take about 9 s on the same machine. The AutoPipeline run it starts has its own cost and time ([AutoPipeline page](autopipeline.md)); GPU ink belongs on Modal (the Modal rule, hard rule 11).

## For agents

- **Command:** `python3 integrations/vc3d/ap_vc3d.py here --point X,Y,Z --volume URL --json`, then `start --run last --digest last --json`, then `load --run last --dest DIR --json` or `open --run last --json`.
- **Parse:** `here`: `out`, `digest`, `start_command`. `start`: `pid`, `log`. `load` and `open`: `segments`, `skipped`, `seeds`, and for `open` `bridge_calls[].done`.
- **Rerun:** `here` makes a new plan only when the point or settings change (AutoPipeline's digest decides the folder) and overwrites `last.json`. `start` refuses while its run is going; after it ends, a new `start` resumes the folder. `load` replaces its own copies in `DEST`.
- **Success:** exit 0. For `open`, check that each wanted call has `done: true`.
- **Not a pass:** a copied surface is accepted by AutoPipeline's rule, not checked by a person; a plan is not a run; tests use stand-ins and do not show a real VC3D window accepting the calls.
- **Go-ahead:** Nothing for local use. Posting results or media needs Chase's yes.
- **Never:** call a surface or map a reading; use it to move model output of prize-eligible scrolls into public places; install manifests you have not read.

## Tests

`python -m unittest tests.test_integrations_vc3d -v` (23 tests, one skipped without `VILLA_ROOT`). They cover planning and every refusal, the digest check and one-run rule, `load`'s accepted-only copy and point format, the manifests through the stand-in plugin host end to end, `open` against a stand-in bridge, reading the point from VC3D's state, and bridge discovery. With `VILLA_ROOT` set, `AgainstVilla` compares the host's rules with villa's `docs/plugins.md`. Not covered: a real VC3D window, a real AutoPipeline run (the tests use a stand-in `scrolls-kit`; `here` was run once by hand against the released package), Windows named pipes.

## History

- 2026-10-21: first version with the people's guide, on branch `claude/apguide-1020` (from `249096b`).

## Related

- [AutoPipeline](autopipeline.md): the released package this script drives.
- [AutoPipeline how-to guide](../autopipeline/guide.md): the people's guide; sections 5 and 6 use this script.
- [AutoPipeline reference](../autopipeline/README.md): every setting, flag and error of AutoPipeline.
- [`integrations/vc3d/README.md`](../../integrations/vc3d/README.md): setup, the Plugins menu and how to add your own tool.
- [media](media.md): `termcast.py` made the guide's GIF and the trailer draft.
