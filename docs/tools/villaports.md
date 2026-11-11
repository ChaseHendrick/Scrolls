# villaports: find what villa #2440 broke in your scripts

`python -m kit villaports` scans a folder of your Python and shell scripts for references to villa's `vesuvius` and `vc_reader` packages, says which ones break at a villa commit and what replaces each, and compares any two villa commits. Read-only.

| Field | Value |
| --- | --- |
| Id | `villaports` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Releases and repository |
| Run | `python -m kit villaports scan`, `python -m kit villaports diff`, `python -m kit.villaports`, `from kit import villaports` |
| Code | `kit/villaports.py`, `kit/data/villaports-map.json`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_villaports.py` |
| Needs | Python 3.10 or newer, standard library only; `git` 2.43 or newer on `PATH` (blobless partial clones and `git fetch --stdin`). villa itself need not be installed |
| Runs on | Any CPU. The first run clones villa without file contents: 8.9 s end to end on a made-up five-reference folder, 36 MB of cache. Later runs: 0.97 s and 49 MB peak for `scan`, 1.15 s for `diff`, on this repository with `--offline` (measured 2026-11-04, 4-core Intel Xeon at 2.10 GHz cloud container) |
| Network | `github.com` over anonymous git only: the first run clones villa without blobs, later runs fetch its branches and the blobs they read, each in one batch. `--offline` or `--villa-git` contacts nothing beyond blobs a partial clone lacks. Never the GitHub REST API |
| Writes | Only its villa cache, `~/.cache/scrolls-villaports/villa.git` (or under `$XDG_CACHE_HOME`, or `--cache PATH`), and the missing objects of a clone `--villa-git` names; it prints its report |
| Go-ahead | Not needed: it reads villa, which is public, and your own folder |
| Released | Public `main` from the change that adds it (4 Nov 2026), in the Scrolls kit release entry |
| Checked | 2026-11-04 against commit `77933ca` |

## What it does

villa PR [#2440](https://github.com/ScrollPrize/villa/pull/2440), the vc_reader takeover, merged on 4 Nov 2026 as `baf5e605b`. It moved villa's zarr, tifxyz and image I/O into the new `vc_reader` package and took a lot out of the `vesuvius` package: `vesuvius.tifxyz` and `vesuvius.image_proc` are gone, `vesuvius.Volume` and `vesuvius.data.utils` are gone, several modules moved (`vesuvius.image_proc.run.voxelize_objs` is now `vesuvius.label_processing.voxelize_objs`), the augmentation transforms became `vc_reader.transforms` configs, and zarr and tifffile are no longer dependencies of the package. A script that did `from vesuvius.tifxyz import read_tifxyz` or `from vesuvius import Volume` fails with an ImportError the next time it runs against villa main.

`scan` finds every reference to villa's packages in your folder and looks each one up in villa's tree at a commit: is the module there, and does it define the name you import? References are Python imports (read with `ast`), `importlib.import_module` and similar calls with a constant name, `-m vesuvius.x` in subprocess lists, shell lines, YAML, JSON, TOML, .cfg files and Dockerfiles, and import statements inside strings meant for `python -c`. Each break gets a suggested replacement from a curated map, `kit/data/villaports-map.json`: 31 entries read from the #2440 diff, each naming the villa file at `baf5e605b` that holds the replacement. Where the map has nothing, it names the villa module that now defines the missing name, if any. `diff --from OLD --to NEW` lists the modules and names your code uses that resolve at OLD and not at NEW, with git's renames.

Two things keep it from crying wolf. An import inside `try` whose `except ImportError` imports the same names from a module of yours (a shim) reports as ok via shim once that module is in the scanned folder and defines them. And when the importing file's own folder holds a copy of the package, Python imports that copy first, so the reference is checked against the copy, not villa.

It does not port anything. It does not check attribute use after an import (`vesuvius.a.b.func(...)`), villa's console scripts, or third-party dependencies: code that imports zarr or tifffile and relied on villa's package to install them is not flagged.

## When to use it

- Before you upgrade villa past `baf5e605b`: `python3 -m kit villaports scan --root YOUR_FOLDER`.
- After villa merges a large change: `diff --from OLD --to main --root YOUR_FOLDER` shows what it took away from your code.
- While porting: run `scan` again after each edit; a ported reference turns ok or ok via shim.

Do not use it:

- As proof a script runs: a resolved import is necessary, not sufficient. Run the script's own test.
- For the wording of a villa PR or issue about a break: use [villapr](villapr.md) (`kit prtext`).
- For villa's C++ or VC3D code: it reads Python packages only.

## Quick start

```bash
python3 -m kit villaports scan --root YOUR_FOLDER          # villa main; exit 3 when a reference breaks
python3 -m kit villaports diff --from baf5e605b^ --root YOUR_FOLDER --json
```

YOUR_FOLDER is the folder of scripts to check; without `--root` the current folder is scanned. Run from a clone of this repository (`git clone https://github.com/ChaseHendrick/Scrolls`).

On a made-up example folder of three files (a render script importing `Volume`, `read_tifxyz` and `write_tifxyz`; a label script importing `normalize_robust` and, inside a `try` with an `except ImportError` fallback to `mytools.compat`, `read_tifxyz`; a shell script running `python -m vesuvius.image_proc.run.voxelize_objs`), against villa main at `baf5e605b` on 4 Nov 2026, the first command printed (long lines cut):

```
kit villaports scan: villa baf5e605b 2026-11-03 open data parsing and zarr / tifxyz reading and interpolati (baf5e605b); vesuvius at vesuvius/src/vesuvius, vc_reader at vc_reader/src/vc_reader; cloned https://github.com/ScrollPrize/villa
scanned EXAMPLE: 5 references in 3 files: 0 ok, 1 ok via shim, 3 missing module, 1 missing name, 0 unknown; 3 files break
ok via shim: 1 references via shim mytools/compat.py (--all lists them)

missing-name   render_segment.py:2  vesuvius (Volume)  no name Volume in vesuvius
               -> scroll volumes are read with vc_reader: vc_reader.reader.open_zarr(path_or_url, level=...) returns a ZarrReader you slice ...
missing-module render_segment.py:3  vesuvius.tifxyz (read_tifxyz, write_tifxyz)  no module vesuvius.tifxyz
               -> read_tifxyz: vc_reader.tifxyz.read(path) (mask=False for the raw stored grid) in place of read_tifxyz ...
missing-module voxelize.sh:2  vesuvius.image_proc.run.voxelize_objs  no module vesuvius.image_proc
               -> moved to vesuvius.label_processing.voxelize_objs (map: villa vesuvius/src/vesuvius/label_processing/voxelize_objs.py at baf5e605b)

breaks by removed module or name:
     2  vesuvius.image_proc  (2 files)
     1  vesuvius.Volume  (1 files)
     1  vesuvius.tifxyz  (1 files)
```

and exited 3. It worked when the first line names the villa commit and the package folders (`vesuvius at vesuvius/src/vesuvius`), and every break has a file, a line and, where the map knows one, a replacement.

## Checks and controls

Each status can fail, and the tests show it on a two-commit fake villa: a module removed in the second commit is ok at the first and missing at the second; a function removed from a module is a missing name while its sibling stays ok; `from x import *` leaves names unknown rather than ok; `-m` on a package without `__main__.py` fails; a docstring that mentions an import, a commented shell line, ignored and excluded folders produce no reference. A shim counts only when its handler catches ImportError and its module is in the scanned folder and defines the names; a missing shim module or name keeps the break.

The map checks itself: a map entry whose replacement is not in villa at the commit is marked `[map target not found at ...]`. On 4 Nov 2026, at villa main (`baf5e605b`), every one of the 31 entries' replacements resolved, every cited villa file existed, and every old module or name the map covers no longer resolved.

The real control: `diff --from baf5e605b^ --to baf5e605b` (the commit before #2440 and #2440 itself) on the made-up folder listed exactly the three removals above and nothing else; on this repository it listed the two references below and nothing else.

Claim label: None. The tool reports the state of your files and of villa's tree; it makes no scientific claim.

## Commands and options

### `python -m kit villaports scan`

```
usage: python -m kit villaports scan [-h] [--villa VILLA] [--all]
                                     [--root ROOT] [--exclude GLOB]
                                     [--no-default-excludes]
                                     [--villa-git VILLA_GIT] [--cache CACHE]
                                     [--offline] [--map MAP] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--villa VILLA` | `main` | Villa commit, branch or tag to resolve against |
| `--all` | off | Also list references that resolve (ok and ok via shim) |
| `--root ROOT` | none | Folder to scan (repeatable); without it, the current folder. Paths print relative to the root, prefixed with the root when there are several |
| `--exclude GLOB` | none | Leave out files whose path from the root, or any of whose folders (by path or by name), matches GLOB (repeatable), such as `old` or `scripts/*.sh` |
| `--no-default-excludes` | off | Also scan git-ignored files, the folders in `DEFAULT_EXCLUDES` and vendored copies of villa packages (Inputs) |
| `--villa-git VILLA_GIT` | none | Read this existing villa clone instead of the cache (not fetched, except blobs a partial clone lacks) |
| `--cache CACHE` | none | Where to keep the villa clone; without it `~/.cache/scrolls-villaports/villa.git`, or under `$XDG_CACHE_HOME` |
| `--offline` | off | Use the cached clone without fetching; with no cache, exit 75 |
| `--map MAP` | none | Replacement map; without it `kit/data/villaports-map.json` |
| `--json` | off | Print JSON (Outputs) instead of text |

### `python -m kit villaports diff`

```
usage: python -m kit villaports diff [-h] --from FROM_REF [--to TO_REF]
                                     [--root ROOT] [--exclude GLOB]
                                     [--no-default-excludes]
                                     [--villa-git VILLA_GIT] [--cache CACHE]
                                     [--offline] [--map MAP] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--from FROM_REF` | required | The older villa commit, branch or tag |
| `--to TO_REF` | `main` | The newer villa commit |
| `--root ROOT` | none | Folder to scan (repeatable); without it, the current folder |
| `--exclude GLOB` | none | Leave out matching files (repeatable), as for `scan` |
| `--no-default-excludes` | off | Also scan git-ignored files, the default folders and vendored copies |
| `--villa-git VILLA_GIT` | none | Read this existing villa clone instead of the cache |
| `--cache CACHE` | none | Where to keep the villa clone |
| `--offline` | off | Use the cached clone without fetching |
| `--map MAP` | none | Replacement map |
| `--json` | off | Print JSON instead of text |

`python -m kit.villaports scan|diff ...` takes the same options.

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `XDG_CACHE_HOME` | `~/.cache` | The folder under which `scrolls-villaports/villa.git` is kept when `--cache` is not given |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `default_cache(environ=None)` | `Path` | Nothing | Where the villa clone is cached: `$XDG_CACHE_HOME/scrolls-villaports/villa.git`, else under `~/.cache` |
| `VillaError()` | An exception (a `RuntimeError`) | Nothing | Villa's tree could not be read (a bad ref, a failed fetch): exit 1 |
| `Unreachable()` | An exception (a `VillaError`) | Nothing | Villa could not be reached and there is no cached clone: exit 75 |
| `Ref(path, line, module, names=(), kind='import', fallbacks=(), file=None)` | A reference | Nothing | One reference to a villa module; `kind` is import, from, -m, string-import or the call name; `fallbacks` are its shims as [(module, names)]; `file` the absolute path; `as_dict()` gives the JSON row |
| `Patterns(packages)` | A matcher | Nothing | The regular expressions for one set of package names; `in_text(text)` gives [(module, names, kind)] and `hint(text)` says whether a text may hold a reference |
| `refs_in_python(text, rel, pats)` | list of `Ref` | Nothing | References in one Python source; falls back to line reading when ast cannot parse it |
| `shim_fallbacks(tree, pats)` | dict | Nothing | {id(import node): [(module, names)]} for villa imports in a `try` whose ImportError handler imports from a module that is not villa's |
| `refs_in_text(text, rel, pats)` | list of `Ref` | Nothing | References in a shell, YAML, JSON, TOML, .cfg or Dockerfile text, line by line; `#` comment lines skipped |
| `excluded(rel, globs)` | bool | Nothing | True when the path from the root, or any of its folders by path or by name, matches one of globs |
| `vendored_copy(root, rel, packages)` | bool | Nothing | True when a folder on the path is named like a scanned package and holds an `__init__.py` |
| `iter_files(roots, excludes=(), defaults=True, packages=None, skipped=None)` | iterator of (path, shown, root) | `ValueError` when a root is no folder | Every candidate file under roots, exclusions applied; `skipped`, a Counter, counts vendored files left out |
| `find_refs(roots=None, packages=None, excludes=(), defaults=True, skipped=None)` | list of `Ref` | `ValueError` from `iter_files` | Every reference in the files under roots (default the current folder), deduplicated, sorted by path and line; identical texts are parsed once |
| `ensure_clone(cache, url=VILLA_URL, offline=False)` | (path, note) | `Unreachable`, `VillaError` | The cached blobless bare clone, made or fetched with anonymous git; a failed fetch with a cache only warns in the note |
| `Villa(path, packages=None)` | A `Villa` | `VillaError` when path is no git repository | Read-only access to one clone: `resolve(ref)`, `describe(sha)`, `prefetch(oids)`, `blobs(oids)`, `tree(commit, prefix)`, `package_root(commit, package)`, `snapshot(ref)` |
| `Shims(roots=())` | A finder | Nothing | Your modules that ImportError fallbacks name, and local copies of a package: `find(module, near)`, `local_copy(ref)`, `check(ref, status, detail)` |
| `Snapshot(villa, commit)` | A snapshot | `VillaError` from git | Villa's packages at one commit: `module_kind`, `first_missing`, `names`, `resolve(ref)`, `resolve_all(refs, shims=None)`, `definitions()` |
| `top_level_names(text)` | (set, bool) | Nothing | Names bound at a module's top level, including under top-level if, try and with; open (True) with `import *`, a `__getattr__`, a top-level `globals().update`, or a parse error |
| `defined_names(text)` | set | Nothing | Names a module defines itself (functions, classes, assignments), not ones it imports |
| `load_map(path=None)` | dict | `ValueError` on a bad file | The curated map: `packages`, `entries` (Inputs); an absent file gives an empty map |
| `map_lookup(entries, module, name=None)` | entry dict or None | Nothing | An entry for this exact name first, then the module entry with the longest matching prefix |
| `suggestion(snap, entries, ref, detail)` | str | Nothing | A replacement text for a broken reference, or an empty string; marks a map target that is not in villa at the snapshot |
| `scan(refs, snap, entries, shims=None)` | list of dict | Nothing | Rows for every reference at one snapshot (Outputs) |
| `summarize(rows)` | dict | Nothing | References, files, counts by status, breaking files, breaks by removed module or name |
| `module_renames(villa, old, new)` | dict | Nothing | {old module: new module} for package files git sees as renamed between two snapshots |
| `add_arguments(p)` | None | Nothing | Adds the two actions to an argparse parser |
| `run(args)` | int exit code | Nothing | The command line's work; errors print to stderr |
| `main(argv=None)` | int exit code | `SystemExit` on a bad argument | `python -m kit.villaports` |

## Inputs

- **Your folder:** each `--root`, or the current folder. Inside a git work tree, the files git tracks or would track (ignored files left out); outside git, every file. Scanned types: `.py`, `.sh`, `.bash`, `.zsh`, `.yml`, `.yaml`, `.json`, `.toml`, `.cfg` and `Dockerfile*` (`TEXT_SUFFIXES`); files over 8 MB (`MAX_BYTES`) are skipped.
- **Left out by default** (`--no-default-excludes` scans them): folders named in `DEFAULT_EXCLUDES` (`.git`, `.hg`, `.svn`, `.venv`, `venv`, `env`, `.env`, `.tox`, `.nox`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.ipynb_checkpoints`, `node_modules`, `site-packages`, `build`, `dist`, `.eggs`, `*.egg-info`), git-ignored files, and vendored copies of villa's packages: any folder named `vesuvius` or `vc_reader` that holds an `__init__.py`, which is villa's code, not yours. This tool's own three files are never scanned, since its map and tests name villa modules on purpose.
- **Villa:** the cached clone, or `--villa-git PATH`. A REF is a branch, tag, short or full sha; branch names are also tried as `origin/REF`.
- **The map** `kit/data/villaports-map.json`: `packages` ({package: [villa folders]}; `vesuvius` at `vesuvius/src/vesuvius`, `vc_reader` at `vc_reader/src/vc_reader`) and `entries`, each with `old` (module), optional `name`, `new_module`, optional `new_name`, `use` (the replacement in words), `villa` (the villa file holding it), `commit` (all `baf5e605bb42a3d55a62b7c5c728e0908137225c`) and `pr` (2440). Entries marked "by name" in `use` were matched by name and role, not by a villa caller: check the arguments.

## Outputs

`scan` prints a header (villa commit and where each package lives), one count line, a line for vendored files left out when there are any, one line per shim with its count, each break (and each unknown) as `STATUS PATH:LINE MODULE (NAMES)  DETAIL` with `-> SUGGESTION` below, then the breaks grouped by removed module or name. `diff` prints each removed module or name with its suggestion, its references and any git rename. On a terminal the lines take the Scrolls look ([termstyle](termstyle.md)); pipes and `--json` stay plain.

`scan --json` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `villa`, `ref` | str | The resolved villa commit and the REF given |
| `roots` | dict | {package: villa folder, or null when absent at that commit} |
| `scanned` | list of str | The folders scanned, as absolute paths |
| `note` | str | How villa was reached (cloned, fetched, cached, existing clone) |
| `summary` | dict | `references`, `files`, `statuses` (ok, ok-via-shim, missing-module, missing-name, unknown), `breaking_files`, `groups` ({removed module or module.name: count}), `skipped_vendored_files` |
| `references[]` | list | `path`, `line`, `module`, `names`, `kind`, `fallbacks` (when in a try with an ImportError fallback), `status`, `detail`, and for a break `suggestion` and `group` |
| `exit` | int | The exit code |

`diff --json`: `from`, `to`, `note`, `changes[]` (`what` module or name, `removed`, `renamed_to`, `suggestion`, `references[]` with `path`, `line`, `module`, `names`, `shim`), `unshimmed` (references that still break), `exit`.

| Exit code | Meaning |
| --- | --- |
| `0` | Nothing breaks: no reference breaks at REF (scan), or nothing your code uses was removed, or all of it resolves through a shim (diff) |
| `1` | An error: a bad REF, a bad map, a missing folder, a failed git call |
| `2` | A missing or wrong argument |
| `3` | Attention: a reference breaks at REF (scan), or a removed module or name has a reference without a shim (diff) |
| `75` | Villa could not be reached and there is no cached clone (or `--offline` without one) |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit villaports: villa unreachable: cannot clone villa from URL (offline?): REASON; pass --villa-git PATH to read an existing clone`, exit 75 | No network to github.com and no cached clone | Run once online, or pass `--villa-git PATH` |
| `kit villaports: villa unreachable: no cached villa clone at PATH and --offline was given; run once online or pass --villa-git PATH`, exit 75 | `--offline` before any clone | Drop `--offline` once, or pass `--villa-git` |
| `kit villaports failed: villa has no commit 'REF' in PATH`, exit 1 | The REF is no commit in the clone | Drop `--offline` to fetch, or check the name |
| `kit villaports failed: no folder ROOT to scan`, exit 1 | A `--root` that is not a folder | Check the path |
| `kit villaports failed: PATH is not a git repository`, exit 1 | `--villa-git` names a folder that is no clone | Point it at a villa clone |
| `kit villaports failed: cannot fetch N villa blobs (offline?): REASON`, exit 1 | A partial clone lacks blobs and cannot reach its remote | Go online once; later runs read the fetched blobs |
| `kit villaports failed: N blobs missing from PATH and it has no promisor remote`, exit 1 | A clone with missing objects but no promisor remote | Use a full clone or the cache |
| `kit villaports failed: git ARGS failed: REASON`, exit 1 | A git call failed | Read git's message; rerun |
| `kit villaports failed: git ACTION timed out after N s`, exit 1 | A git call took longer than its limit (600 s, 900 s for the clone) | Check the network; rerun |
| `kit villaports failed: cannot run git: REASON`, exit 1 | `git` is not installed or not on `PATH` | Install git 2.43 or newer |
| `kit villaports failed: bad map PATH: PROBLEMS`, exit 1 | A map entry lacks a field, or `packages` is not {name: [folders]} | Fix the map file |
| Header note `fetch failed (...); using the cached clone as it is` | Offline with a cache | The report is as of the cache's last fetch |
| `[map target not found at ...]` after a suggestion | The map's replacement is not in villa at that commit (villa changed it again) | Read villa's current code for the replacement; report the entry |
| `unknown` rows | The villa module has `from x import *` or a module-level `__getattr__`, so a name cannot be ruled out | Check that name by hand |

## How it works

1. **Your references.** `iter_files` lists candidate files (git's list of tracked and untracked, not ignored, files when the root is in a work tree; a walk otherwise), then drops excluded paths and vendored copies. A fast check (`Patterns.hint`) skips files where no package name follows a quote, `import`, `from` or `-m`. Python files are parsed once per distinct text (`hashlib.sha1`); `ast.walk` collects imports, constant-name import calls, `"-m"` list pairs and string constants (docstrings left out), and `shim_fallbacks` records each villa import inside a `try` whose handler catching ImportError, ModuleNotFoundError, Exception or everything imports from a module that is not villa's.
2. **Villa access.** `ensure_clone` keeps a `git clone --filter=blob:none --bare` of `VILLA_URL` (`https://github.com/ScrollPrize/villa`) and fetches `+refs/heads/*:refs/heads/*`. Commits and trees are local, so trees are read with `git ls-tree -r`; the blobs a run needs are compared with the local object list, fetched in batches of up to 2000 with `git fetch --stdin`, and read with `git cat-file --batch`.
3. **Package roots.** `package_root` takes the first map folder holding `__init__.py`, else the shallowest `<x>/src/<package>` folder outside `deprecated/` and `archive/`.
4. **Resolution.** `first_missing` walks the dotted path; a `.py` file mid-path followed by more parts means the module is missing. Names come from `top_level_names` of the module and its `.pyi` stub (vc_reader builds its transforms at import time, and the stub names them), plus submodules. A reference whose own folder holds a copy of the package goes to `Shims.local_copy`; a break with ImportError fallbacks goes to `Shims.check`.
5. **Suggestions.** `map_lookup` picks the entry for (module, name), else the longest module prefix; `suggestion` resolves the entry's `new_module` and `new_name` at the same snapshot and marks it when they are absent. Without an entry, `definitions()` lists the modules that define the lost name at that commit.
6. **Diff.** Each reference is resolved at both commits; one that resolves at OLD and breaks at NEW is a change, grouped by the removed module or name, with `git diff -M --diff-filter=R` renames between the package folders.

Constants: `TAKEOVER = "baf5e605bb42a3d55a62b7c5c728e0908137225c"` (villa #2440's merge); exit codes `EXIT_OK, EXIT_FAIL, EXIT_ATTENTION, EXIT_UNREACHABLE = 0, 1, 3, 75`.

## Cost and time

Measured 2026-11-04 on a 4-core Intel Xeon at 2.10 GHz cloud container, Python 3.13, git 2.43: the first `scan` of a made-up five-reference folder took 8.9 s including the blobless clone (36 MB cache); with a warm cache and `--offline`, `scan` of this repository took 0.97 s and 49 MB peak, `diff --from baf5e605b^` 1.15 s and 51 MB. Runs on any laptop CPU. Rents nothing.

## For agents

- **Command:** `python3 -m kit villaports scan --root FOLDER --json` (or `diff --from OLD --to main --root FOLDER --json`).
- **Parse:** `summary.statuses` and `summary.groups`; each `references[]` row with `status` missing-module or missing-name is a break, with `suggestion`; for `diff`, `changes[]` and `unshimmed`.
- **Rerun:** Safe; it only updates the villa cache.
- **Success:** Exit 0 with `summary.breaking_files` 0; exit 3 lists what to port.
- **Not a pass:** ok means the import resolves, not that the code runs (arguments and return values changed too); `unknown` is not ok; files left out by excludes were not checked.
- **Go-ahead:** Nothing.
- **Never:** Edit a vendored copy of villa to make the count drop; copy villa source into your docs beyond names; describe a suggestion marked `[map target not found ...]` as the replacement.

## Tests

```bash
python3 -m unittest tests.test_villaports -v
```

32 tests, no network: they build a fake villa git repository with two commits (the second removes a package and a function, renames a package, adds a `vc_reader` package) and a fake user folder. They cover every reference form, the default excludes, `--exclude` globs, vendored copies, a plain folder outside git and two roots, the tool never scanning itself, ast fallback, statuses at both commits, star imports, stubs, `-m` on packages, shims (a good one, a missing module, a missing name, a handler that does not catch ImportError), a local copy of a package, the map lookup and its target check, that every entry of the real map cites `baf5e605b` and that its two `points_at` hints ask for `bicubic`, `scan` text and JSON, the current folder as default root, `diff` with renames and shims, errors (bad REF, missing folder), the cache path, an offline run without cache (exit 75), a failed clone, a clone then fetch from a local file URL, and a blobless partial clone that fetches blobs in a batch. Not covered: the real villa layout and GitHub, which the real runs in Quick start and Checks and controls check.

## History

- 2026-11-11: the two `points_at` hints in the map now say `interpolation="bicubic"`: vc_reader accepts only `linear` or `bicubic`, and villa [#2506](https://github.com/ScrollPrize/villa/pull/2506) (`f0e4410`, 11 Nov 2026) changed villa's own seven callers from `smooth` to `bicubic`; a test keeps `smooth` out of the hints.
- 2026-11-04: first public version, from `main` at `77933ca`: `scan` and `diff` over your own folder, a map of 31 replacements read from villa #2440 at `baf5e605b`, generic shim and local-copy detection, `--exclude` and default excludes. Its run on this repository found two references that break at `baf5e605b`: `kit/spaceconnect.py` line 148 (a `from vesuvius import Volume` snippet) and `tests/test_inklens.py` line 268 (`normalize_robust`).

## Related

- [villapr](villapr.md): `kit prtext` checks the text of a villa PR or issue before you post it, and `kit prclock` its time limits.
- [tifxyz](tifxyz.md): this repository's own tifxyz reader and checks, which do not depend on villa's package.
- [termstyle](termstyle.md): the terminal look its output takes.
- [villa PR #2440](https://github.com/ScrollPrize/villa/pull/2440): the change the map is read from.
