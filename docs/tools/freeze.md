# freeze: freeze a run by hash, guard what it loads, and keep review pins honest

Fixes the exact files a run executes by their sha256 before the run exists, refuses a launch or a run that loads anything else, and ties each review verdict to the commit it covered so a later edit drops it. For any git repository.

| Field | Value |
| --- | --- |
| Id | `freeze` |
| Status | Current |
| Kind | kit command, kit module |
| Area | Records and provenance |
| Run | `python -m kit freeze list`, `python -m kit freeze add`, `python -m kit freeze check`, `python -m kit freeze pin`, `python -m kit freeze collect`, `python -m kit freeze prereg`, `python -m kit reviewpin record`, `python -m kit reviewpin delta`, `python -m kit reviewpin explain`, `python -m kit reviewpin list`, `python -m kit.freeze`, `python -m kit.reviewpin`, `from kit import freeze, freezeguard, reviewpin` |
| Code | `kit/freeze.py`, `kit/freezeguard.py`, `kit/preregsets.py`, `kit/reviewpin.py`, `kit/cli.py` (`build_parser`) |
| Tests | `tests/test_freeze.py`, `tests/test_freezechain.py`, `tests/test_freezeguard.py`, `tests/test_reviewpin.py` |
| Needs | Python 3.10 or newer, standard library only; git (2.38 or newer for the review pins' merge replay, `git merge-tree --write-tree`) |
| Runs on | Any machine. `freeze check` of a two-file freeze took 0.30 s wall (measured 2026-11-20, 4-core cloud container) |
| Network | None, except `reviewpin delta` and `explain` without `--head` or `--no-fetch`, which run `git fetch origin` for the PR head and the base branch |
| Writes | `freeze add`, `pin` and `collect`: the registry (`freeze/freezes.json` by default). `reviewpin record`: one line in the verdict log (`freeze/verdicts.jsonl` by default). Every other action, and every library guard, writes nothing in the repository (`run_script` uses a temporary folder) |
| Go-ahead | Not needed: it records and checks; it launches nothing |
| Released | Public `main` from the PR that adds this page (2026-11-20) |
| Checked | 2026-11-20 against commit `357d2bd` |

## What it does

A result is only as honest as the rule that was fixed before it was seen. This tool makes that rule checkable. A **freeze** is a registry entry that records the commit that froze a run (the freezing commit, which changes only the preregistration, the document that fixes the readout rule), the preregistration's sha256 and the sha256 of every file the run executes, read with `git show` at that commit. A freeze is **live** until its run's evidence is collected, then **spent**.

`kit freeze check ID` says whether the freeze still holds: the freezing commit changes only the preregistration, the recorded hashes are true at that commit, and every listed file is unchanged now (a failure, exit 1, for a live freeze) or the preregistration gained text (attention, exit 3). In the run itself, `freeze.launch_check(entry)` refuses a launch when a listed file differs, and `freeze.executed_check` and `freeze.run_script` refuse a run that loaded a repository file the freeze does not list (from `sys.modules`, in this process or in a child script). `kit/freezeguard.py` adds the same guard for children started by other code, and `import_closure`, which reads the source of the entry files and lists every repository module they can import, including imports inside functions, so the freeze can list them all. A spent freeze is rerun only from `git worktree add DIR COMMIT`.

Preregistrations can pin files themselves, in fenced `code-sha256` blocks of `SHA256  PATH` lines: the readout set (scoring code, labels, thresholds) changes only by a dated amendment; the plumbing set (container image, installs, logging) may change by a dated deviation line that gives the new hash. `kit freeze add` checks those lines against the files, and `kit freeze prereg PATH` checks a preregistration on its own.

**Review pins** (`kit reviewpin`) tie a verdict (GO, NO-GO or GO-WITH-NOTES) to the commit a review covered. `delta` compares the pull request's own patch at that commit (the diff from its merge base with the base branch) with its own patch at the head. A head that only merged the base branch in has the same own patch, so the GO carries; one byte changed in the PR's own lines, in a later commit or inside a merge commit, drops it to recheck (exit 3). When the base moved lines next to the PR's hunk, a **derived cover** may still keep the GO: every commit after the pin is a merge of the base, each file's own change is the same by content (and a JSON file by parsed value), and each merge equals what `git merge-tree` gives for its parents, so a conflict resolved by hand voids it.

What it does not do: it does not see files a run opens without importing them (data files, shell scripts, binaries), unless they are listed and hashed; it cannot tell whether a review was any good, only whether the code it covered changed; and a check that passes is not evidence that the result is right.

## When to use it

- Before any test whose result could tempt a change: write the preregistration, commit the code, commit the preregistration alone, then `kit freeze add`.
- Inside the runner: `launch_check` before the work, `executed_check` after the imports and again after the work, `run_script` for each child script.
- Before merging a reviewed pull request: `kit reviewpin delta PR` (exit 0 carries, 3 recheck).

Do not use it:

- For a run with no fixed rule to protect: a plain record of who ran what belongs in [provenance](provenance.md).
- To decide whether a result is valid: read the result against its controls ([integrity](integrity.md)).
- To restart a frozen run after a crash: a rerun needs a new freeze; [drivers](drivers.md) refuses to start a frozen run as restartable.

## Quick start

```bash
cd "$(mktemp -d)" && git init -q -b main
mkdir -p toy prereg docs/compute
printf 'import helpers\nprint("accuracy", helpers.score())\n' > toy/eval.py
printf 'def score():\n    return 0.95\n' > toy/helpers.py
echo '{"freezes": []}' > freeze/freezes.json
echo "Status: Draft" > prereg/toy.md
git add -A && git commit -qm code
echo "Status: Frozen" > prereg/toy.md && git commit -qam "freeze toy-eval"
python -m kit freeze add --id toy-eval --prereg prereg/toy.md --file toy/eval.py --file toy/helpers.py --note "toy evaluation"
git commit -qam "register toy-eval"
python -m kit freeze check toy-eval; echo "exit $?"
sed -i 's/0.95/0.96/' toy/helpers.py
python -m kit freeze check toy-eval; echo "exit $?"
git checkout -q -- toy/helpers.py
python3 -c "
from kit import freeze
e = freeze.find(freeze.load(), 'toy-eval')
freeze.launch_check(e)
print(freeze.run_script('toy/eval.py', [], e, '.'), 'repository files loaded, all listed')"
```

Run it with the Scrolls checkout on `PYTHONPATH` (or the kit installed), and git's user name and email set. Printed (2026-11-20, cloud container):

```
added toy-eval: live from 86d29a08c629, 2 file(s), preregistration prereg/toy.md (freeze/freezes.json)
check ok: 2 of 2 listed file(s) match
exit 0
changed        toy/helpers.py +1 -1 lines
FAIL: toy/helpers.py changed in the working tree (+1 -1 lines): a live freeze's files must not change until its run is collected
check failed: 1 of 2 listed file(s) match
exit 1
accuracy 0.95
2 repository files loaded, all listed
```

It worked when the one-character change fails the check and the reverted tree runs. A review pin on a branch `pr`:

```bash
python -m kit reviewpin record 1 HEAD GO --base main --reviewer me
python -m kit reviewpin delta 1 --head pr --base main --no-fetch; echo "exit $?"
```

After a merge of `main` into `pr` it printed `GO carries (own patch identical)` and exit 0; after one more own edit, `GO at 01f2be72d98f does not cover the head: 1 file(s) changed since review` and exit 3.

## Checks and controls

Every guard here must refuse when it should and let the run go when it should; both directions have controls.

Outside check (20 Nov 2026): a toy evaluation repository with no scroll data (a fixed threshold rule's accuracy on a 40-row CSV, three Python files, one imported inside a function), a clean copy of the modules with nothing else from the repository loaded, and the calls through each module's own functions. All 8 preregistered bars were met:

| Bar | Result |
| --- | --- |
| Baseline | check exit 0, launch_check ok, run_script ran the evaluation |
| One byte in the frozen script | check exit 1, launch refused (`toy/eval.py differ from the freeze`); after the revert it runs |
| One byte in an imported module, and in a module imported inside a function | both refused, check exit 1; both reverts run |
| Controls | one byte in an unlisted README (never executed): runs. A hand-written list that leaves out the imports: launches, then run_script is refused for loading `toy/helpers.py, toy/metrics.py` |
| import_closure | exactly the script and both modules (it found the import inside a function) |
| GO kept | head at the reviewed commit, a base-only merge of another file, a base-only merge into the same file far from the hunk: all exit 0, "GO carries (own patch identical)" |
| GO dropped | one byte in the PR's own line: exit 3, recheck, the file named. A merge commit that also edited that line: exit 3, recheck |
| Revert | after `git revert` of the one-byte change: exit 0, carries |

`tests/test_freezechain.py` repeats these bars on the same toy repository, in a temporary folder. That check ran the workbench copy of these modules; this public copy drops the checks and merge modes tied to that workbench's own files and rules, and makes the root, the registry path, the verdict log and the base branch configurable, with `main` as the default branch.

Not covered by the outside check: the derived cover and its merge replay, `freeze collect`, a spent freeze's rerun from a worktree, and `freezeguard.recording_argv`. The public tests cover each of these on throwaway repositories (a context-only base merge keeps a derived cover; an edit inside the merge, a hand-resolved conflict and a moved line in a resolution void it).

Scope: software correctness of the guards on git repositories. It makes no claim about any result a frozen run produces.

Claim label: Sourced fact (the outside check's exit codes and refusals on a toy repository, 20 Nov 2026, and the public tests).

## Commands and options

### Options of `python -m kit freeze` (before the action)

```
usage: python -m kit freeze [-h] [--root ROOT] [--registry REGISTRY]
                            {list,add,check,pin,collect,prereg} ...
```

These go before the action: `python -m kit freeze --root R --registry ops/frozen.json check ID`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--root ROOT` | none | The repository (default: the git top level of the current folder). Every path in the registry and on the command line is relative to it |
| `--registry REGISTRY` | none | The registry, relative to the root (default `$KIT_FREEZE_REGISTRY`, else `freeze/freezes.json`) |


### `python -m kit freeze list`

```
usage: python -m kit freeze list [-h] [--state {live,spent}] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--state STATE` | none | only live or only spent freezes |
| `--json` | off | print JSON |

### `python -m kit freeze add`

```
usage: python -m kit freeze add [-h] --id ID --prereg PREREG [--file FILE]
                                [--files-from FILES_FROM] [--from-prereg]
                                --note NOTE [--commit COMMIT]
                                [--run-token RUN_TOKEN] [--spec SPEC]
                                [--branch BRANCH] [--frozen-on FROZEN_ON]
                                [--allow-other-changes] [--dry-run] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--id ID` | required | a new id, such as toy-eval-f1 |
| `--prereg PREREG` | required | the preregistration (or the document that fixes the rule) |
| `--file FILE` | none | a file the run executes; repeatable, never a folder |
| `--files-from FILES_FROM` | none | a text file with one path per line (# starts a comment) |
| `--from-prereg` | off | also list every file the preregistration's code-sha256 blocks hash |
| `--note NOTE` | required | what the freeze is and where its run is recorded |
| `--commit COMMIT` | `HEAD` | the freezing commit (default HEAD) |
| `--run-token RUN_TOKEN` | none | the launch token, when known |
| `--spec SPEC` | none | the run's spec file, recorded with the entry |
| `--branch BRANCH` | none | the branch that keeps the commit while it is not on the default branch |
| `--frozen-on FROZEN_ON` | none | YYYY-MM-DD (default: the freezing commit's UTC date) |
| `--allow-other-changes` | off | accept a freezing commit that changes files besides the preregistration (an older freeze); the entry records them as other_changes, which check then reports as information |
| `--dry-run` | off | print the entry, write nothing |
| `--json` | off | print the entry as JSON |

### `python -m kit freeze check`

```
usage: python -m kit freeze check [-h] [--at AT] [--registry-rev REGISTRY_REV]
                                  [--json]
                                  id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The freeze id |
| `--at AT` | none | compare the listed files at this commit (default: the working tree) |
| `--registry-rev REGISTRY_REV` | none | read the registry as committed at this revision, such as origin/main (from a worktree at an old freezing commit) |
| `--json` | off | print JSON |

### `python -m kit freeze pin`

```
usage: python -m kit freeze pin [-h] [--commit COMMIT] [--dry-run] [--json] id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The freeze id |
| `--commit COMMIT` | none | the commit the run executes from (default: the freezing commit) |
| `--dry-run` | off | print the entry, write nothing |
| `--json` | off | print the entry as JSON |

### `python -m kit freeze collect`

```
usage: python -m kit freeze collect [-h] --evidence EVIDENCE [--on ON]
                                    [--note NOTE] [--keep-live] [--dry-run]
                                    [--json]
                                    id
```

| Option | Default | Meaning |
| --- | --- | --- |
| `id` | required | The freeze id |
| `--evidence EVIDENCE` | required | the collected evidence, a file or folder in the working tree |
| `--on ON` | none | YYYY-MM-DD (default: today, UTC) |
| `--note NOTE` | none | appended to the entry's note |
| `--keep-live` | off | record the collected run but keep the freeze live (it still guards a later run) |
| `--dry-run` | off | print the entry, write nothing |
| `--json` | off | print the entry as JSON |

### `python -m kit freeze prereg`

```
usage: python -m kit freeze prereg [-h] [--at AT] [--record RECORD] [--json]
                                   path
```

| Option | Default | Meaning |
| --- | --- | --- |
| `path` | required | the preregistration, relative to the root |
| `--at AT` | none | compare the hashed files at this commit (default: the working tree) |
| `--record RECORD` | none | a run record file whose deviations block also counts; repeatable |
| `--json` | off | print JSON |

### Options of `python -m kit reviewpin` (before the action)

```
usage: python -m kit reviewpin [-h] [--root ROOT] [--log LOG]
                               {record,delta,explain,list} ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--root ROOT` | none | The repository (default: the git top level of the current folder) |
| `--log LOG` | none | The verdict log, relative to the root or absolute (default `$KIT_REVIEWPIN_LOG`, else `freeze/verdicts.jsonl`) |

### `python -m kit reviewpin record`

```
usage: python -m kit reviewpin record [-h] [--scope FILE [FILE ...]]
                                      [--reviewer REVIEWER] [--note NOTE]
                                      [--base BASE] [--branch BRANCH]
                                      [--dry-run] [--json]
                                      pr sha verdict
```

| Option | Default | Meaning |
| --- | --- | --- |
| `pr` | required | the PR number, such as 101 |
| `sha` | required | the commit the review covered (must exist in this clone) |
| `verdict` | required | GO, NO-GO or GO-WITH-NOTES |
| `--scope FILE ...` | none | the files, folders or globs the review covered (default: the whole patch) |
| `--reviewer REVIEWER` | none | who reviewed, such as a session link or agent name |
| `--note NOTE` | none | one line: what the review found |
| `--base BASE` | `origin/main` | the base branch (default origin/main) |
| `--branch BRANCH` | none | the local branch of the PR (default: the one branch at the commit, if any) |
| `--dry-run` | off | print the line and write nothing |
| `--json` | off | print the line as JSON |

### `python -m kit reviewpin delta`

```
usage: python -m kit reviewpin delta [-h] [--head HEAD] [--base BASE]
                                     [--no-fetch] [--log-from REF] [--json]
                                     pr
```

| Option | Default | Meaning |
| --- | --- | --- |
| `pr` | required | the PR number |
| `--head HEAD` | none | the head commit or ref (default: refs/pull/PR/head fetched from origin, else the branch stored with the verdict) |
| `--base BASE` | `origin/main` | the base branch (default origin/main) |
| `--no-fetch` | off | use local refs only, no git fetch |
| `--log-from REF` | none | read the verdicts as commit REF has them, such as the base branch a merge gate fetched (default: the working tree) |
| `--json` | off | print the result as JSON |

### `python -m kit reviewpin explain`

```
usage: python -m kit reviewpin explain [-h] [--head HEAD] [--base BASE]
                                       [--no-fetch] [--log-from REF] [--json]
                                       pr
```

| Option | Default | Meaning |
| --- | --- | --- |
| `pr` | required | the PR number |
| `--head HEAD` | none | the head commit or ref (default: refs/pull/PR/head fetched from origin, else the branch stored with the verdict) |
| `--base BASE` | `origin/main` | the base branch (default origin/main) |
| `--no-fetch` | off | use local refs only, no git fetch |
| `--log-from REF` | none | read the verdicts as commit REF has them, such as the base branch a merge gate fetched (default: the working tree) |
| `--json` | off | print the result as JSON |

### `python -m kit reviewpin list`

```
usage: python -m kit reviewpin list [-h] [--pr PR] [--json]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--pr PR` | none | only this PR |
| `--json` | off | print them as JSON |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `KIT_FREEZE_REGISTRY` | `freeze/freezes.json` | The registry path, relative to the root (`REGISTRY_ENV`); `--registry` sets it for one command |
| `KIT_REVIEWPIN_LOG` | `freeze/verdicts.jsonl` | The verdict log, relative to the root (`LOG_ENV`), read when the module is imported |
| `KIT_REVIEWPIN_BASE` | `origin/main` | The default `--base` (`BASE_ENV`), read when the module is imported |

## Python API

### `kit/freeze.py`

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `FreezeRefused()` | an exception (a `SystemExit`) | | A runner's guard refused: it loaded a file its freeze does not list, or a listed file changed |
| `registry_path()` | `str` | | The registry's path relative to the root: `KIT_FREEZE_REGISTRY` when set, else `FREEZES` |
| `default_root(cwd=None)` | `Path` | | The git top level of `cwd` (default the current folder), else `cwd` |
| `validate(data)` | list of entries | `FreezeError` | The base shape (unique ids, prereg, note, commit hash, state, collected_on, dates), then the added fields |
| `load(root=None, rev=None)` | dict | `FreezeError` | The registry, validated; with `rev`, as committed at that revision (for a rerun from an old worktree, pass `origin/main`) |
| `save(root, data)` | `Path` | `FreezeError` | Validates, then replaces the registry atomically |
| `find(data, fid)` | the entry | `FreezeError` | One entry by id |
| `listing(root=None, state=None, today=None)` | list of dicts | `FreezeError` | One row per entry with ages and file counts, optionally only live or spent |
| `make_entry(root, fid, prereg, files, note, commit='HEAD', run_token=None, spec=None, branch=None, frozen_on=None, allow_other_changes=False, from_prereg=False, data=None)` | the new entry | `FreezeError` | Hashes read at the freezing commit; refuses folders, missing files, mismatched hash lines and a commit that changes anything but the preregistration |
| `needs_new_freeze_at(data, commit)` | list of entries | | Entries with `rerun_needs_new_freeze` whose freezing commit is this one |
| `add(root, entry, dry_run=False)` | the entry | `FreezeError` | Appends and saves; a taken id is refused |
| `collect(root, fid, evidence, on=None, note=None, keep_live=False, dry_run=False)` | the entry | `FreezeError` | Records `collected_on` and `evidence`; state spent unless `keep_live` |
| `check(root, fid, at=None, data=None)` | report dict | `FreezeError` | problems (exit 1), attention (exit 3), info, one row per file, and `exit` |
| `pin_commit(root, fid, commit=None, dry_run=False)` | the entry | `FreezeError` | Records `frozen_commit` once check passes there |
| `commit_pin_problems(root, entry, base_entry, changed)` | list of str | | Why a change touching a pinned live freeze's files may not land; empty when it may |
| `executed_files(root, modules=None)` | list of paths | | Repository files the loaded modules came from (installed packages excluded) |
| `executed_check(files, root, modules=None, when='run', loaded=None)` | count of repository files | `FreezeRefused` | Refuses a loaded repository file `files` does not list |
| `run_script(script, args, files, root, python=None, when=None)` | count of repository files | `FreezeRefused`, `subprocess.CalledProcessError` | Runs `python SCRIPT ARGS` and checks what the child loaded, the script included |
| `launch_check(entry, root=None)` | count of files checked | `FreezeRefused` | Refuses a launch the freeze does not allow (a changed file, a pinned or spent freeze outside its commit) |
| `add_arguments(p)` | `None` | | Adds `--root`, `--registry` and the actions |
| `run(args, root=None)` | exit code | | Runs parsed arguments; `--registry` applies for that call only |
| `main(argv=None)` | exit code | | The `python -m kit.freeze` entry point |

`FreezeError` is `kit/preregsets.py`'s `PreregError`, so one `except` catches both modules' errors.

### `kit/freezeguard.py`

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `CHILD_RUNNER` | `str` | | The `python -c` program that runs a module or script and writes the files it loaded to a record |
| `PYTHON_FLAGS` | tuple | | Interpreter flags `recording_argv` keeps (`-I`, `-E`, `-s`, `-S`, `-P`, `-u`, `-B`, `-O`, `-OO`) |
| `recording_argv(argv, record)` | list or `None` | | The argv that runs a `python -m MODULE` or `python SCRIPT.py` child through `CHILD_RUNNER`; None for anything else |
| `recording_check(files, root, records, when='children')` | dict | `FreezeRefused` | `executed_check` on what the children recorded; a missing record is counted |
| `guard_record(files, root, when, records=None)` | dict | | The check that records a refusal under `refused` instead of raising it |
| `guard_void(marker_doc, records=())` | list of str | | The void reasons read back from recorded refusals |
| `import_closure(root, entries, top_only=(), search=('',), discover=(), always=())` | sorted list of paths | `FreezeError` | Every repository file the entries can import, read from source, inside functions too |

### `kit/preregsets.py`

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `PreregError()` | an exception (a `ValueError`) | | A preregistration, record, path or argument is malformed, or a request is refused (exit 2) |
| `sha256_bytes(data)` | `str` | | Hex sha256 |
| `prereg_sets(text)` | `{path: (set, sha256)}` | `PreregError` | From every code-sha256 block; a later block of a set replaces an earlier hash |
| `deviations(text)` | list of dicts | `PreregError` | `{date, sha256, path, reason}` from every deviations block |
| `record_deviations(items)` | list of dicts | `PreregError` | The same, from a run record's JSON `deviations` list |
| `check_prereg(root, prereg, at=None, records=(), extra=())` | report dict | `PreregError` | Every hashed file against the working tree or `at`: readout changed fails, plumbing changed needs a dated line |
| `format_prereg(report)` | `str` | | The text `kit freeze prereg` prints |

### `kit/reviewpin.py`

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `PinError()` | an exception | | Bad input or a git failure; the message says which |
| `default_root(cwd=None)` | `Path` | | The git top level of `cwd`, else `cwd` |
| `parse_pr(text)` | `int` | `PinError` | `101` or `#101` |
| `parse_verdict(text)` | `str` | `PinError` | GO, NO-GO or GO-WITH-NOTES, any case |
| `read_log(root, log=None)` | list of dicts | `PinError` | Every verdict in the log, in file order |
| `read_log_at(root, ref, log=None)` | list of dicts | `PinError` | The log as commit `ref` has it |
| `parse_log_text(text, name=LOG)` | list of dicts | `PinError` | Parses log text; each line needs `pr` and `sha` |
| `latest(records, pr)` | dict or `None` | | The newest verdict for a PR |
| `make_record(root, pr, sha, verdict, scope=(), reviewer=None, note=None, base=DEFAULT_BASE, branch=None, time=None)` | dict | `PinError` | The verdict line, with the full sha and its merge base |
| `append(root, rec, log=None)` | `Path` | | Adds one line to the log |
| `split_patch(text)` | dict | | Files and hunks of a diff, line numbers and blob hashes dropped |
| `in_scope(path, scope)` | `bool` | | A path, a folder or a glob |
| `compare(old, new)` | list of dicts | | Files whose own patch differs, with new and gone hunks |
| `fetch_head(root, pr, base, fetch=True)` | `(sha, ref, notes)` | | The PR head from `refs/pull/PR/head`, fetched or local |
| `delta(root, pr, head=None, base=DEFAULT_BASE, fetch=True, log=None, log_ref=None, always_in_scope=(), explain=False)` | result dict | `PinError` | `status` carries, recheck, nogo or no-verdict, with `exit` |
| `json_delta(a, b, path='$')` | list of tuples | | JSON change, lists compared as multisets |
| `own_change(root, mb, sha, path)` | tuple | `PinError` | A file's own change by content: `json` or `text` mode |
| `replay_differs(root, merge, ours, theirs, paths)` | `str` or `None` | | Why a merge's result differs from an automatic merge of its parents |
| `derive_checks(root, rec, head, base, old_mb, new_mb, paths, stop=True)` | list of dicts | `PinError` | The derived-cover checks in order |
| `judge_checks(checks, base, paths)` | `(bool, str)` | | Covered or not, and why |
| `derived_cover(root, rec, head, base, old_mb, new_mb, paths)` | `(bool, str)` | `PinError` | The derived cover, stopping at the first failure |
| `explain_own_change(old, new)` | dict | | What differs between two own changes |
| `explain(root, pr, head=None, base=DEFAULT_BASE, fetch=True, log=None, log_ref=None, always_in_scope=())` | result dict | `PinError` | `delta` with every check under `checks` |
| `format_explain(r, item_lines=8)` | `str` | | The text `explain` prints |
| `format_delta(r, hunk_lines=14)` | `str` | | The text `delta` prints |
| `format_list(records)` | `str` | | The table `list` prints |
| `add_arguments(p)` | the parser | | Adds `--root`, `--log` and the actions |
| `run(args, root=None)` | exit code | | Runs parsed arguments |
| `main(argv=None)` | exit code | | The `python -m kit.reviewpin` entry point |

## Inputs

- A git repository (the root). Registry paths, preregistrations and listed files are repository paths: relative, with `/`, no `.` or `..` parts.
- The registry: `{"freezes": [ENTRY, ...]}`. An entry needs `id`, `prereg`, `note`, `freezing_commit` (7 to 40 hex digits), `state` (`live` or `spent`) and `collected_on` (null until collected); `kit freeze add` writes the rest.
- A preregistration: any text file. Optional hash blocks:

````
```code-sha256 readout
SHA256  kit/score.py
```

```code-sha256 plumbing
SHA256  scripts/container_run.py
```

```deviations
2026-11-02  NEWSHA256  scripts/container_run.py  image: add numpy
```
````

  Plain `code-sha256` counts as readout. A preregistration that hashes nothing makes `kit freeze prereg` exit 3, never a vacuous pass.
- The verdict log: one JSON object per line with `pr`, `sha`, `verdict`, `scope`, `reviewer`, `time`, `note`, `base`, `merge_base`, `branch`.

## Outputs

`freeze check --json` prints:

| Field | Type | Meaning |
| --- | --- | --- |
| `id`, `state` | string | The entry |
| `freezing_commit`, `prereg` | string | As recorded |
| `target` | string | The `--at` commit, or `working tree` |
| `problems` | list of str | Failures (exit 1) |
| `attention` | list of str | Needs a look (exit 3) |
| `info` | list of str | For information |
| `files[]` | list | `path`, `recorded`, `at_freeze`, `now` (sha256), `status` (`ok`, `changed`, `missing`, `not at freeze`, `record wrong`), `change` |
| `exit` | integer | The exit code |

`reviewpin delta --json` prints `pr`, `status` (`carries`, `recheck`, `nogo`, `no-verdict`), `exit`, `verdict`, `message`, `notes`, `reviewed`, `reviewer`, `reviewed_at`, `scope`, `base`, `head`, `head_ref`, `reviewed_base`, `head_base`, and `changes[]` (`path`, `change`, `in_scope`, `head_lines`, `new_hunks`, `gone_hunks`), with `derived` and `derive` when a derived cover was tried; `explain` adds `checks[]` (`check`, `ok`, `why`, and `compare` for an own change).

| Exit code | Meaning |
| --- | --- |
| `0` | `freeze`: done, or the check passed. `reviewpin delta`: the verdict carries |
| `1` | `freeze check` or `prereg`: failed. `reviewpin`: an error (`kit reviewpin: ...`) |
| `2` | `freeze`: a refusal or bad input (`kit freeze: ...`). `reviewpin delta`: no verdict recorded |
| `3` | `freeze check` or `prereg`: needs a look. `reviewpin delta`: recheck |
| `4` | `reviewpin delta`: NO-GO stands |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `no freeze...in...; python -m kit freeze list shows the ids` | The id is not in the registry | List the ids with `python -m kit freeze list` |
| `...needs a list under "freezes"` | The registry is not a JSON object with a freezes list | Fix the registry file, or start one as `{"freezes": []}` |
| `--id...: use letters, digits, dot, dash and underscore, starting with a letter or digit` | The id has other characters | Use letters, digits, dot, dash and underscore |
| `--commit...: not a commit in this clone` | The commit is not in this clone | Fetch it, or give another revision |
| `--commit...is the freezing commit of..., whose rerun needs a new freeze that includes the guards added since (...): freeze a later commit that has them, never this one again` | That commit's code lacks a guard added since | Freeze a later commit that has the guard |
| `--prereg...is not a file at...` | The preregistration is not committed at the freezing commit | Commit it, then freeze |
| `list the files the run executes with --file (or --files-from); a freeze without files guards nothing` | No `--file`, `--files-from` or `--from-prereg` | List the files the run executes |
| `the preregistration hashes..., which the file list leaves out: add each with --file, or pass --from-prereg to add every hashed file` | The preregistration hashes a file the list does not name | Add it with `--file`, or pass `--from-prereg` |
| `git cannot list what...changes` | git failed on the commit | Check the clone with `git log` |
| `the freezing commit...also changes...: a freezing commit changes only the preregistration, so commit the code first (or pass --allow-other-changes to record an older freeze as it was; the entry then lists those paths as other_changes)` | The freezing commit changes code as well as the preregistration | Commit the code first, then a commit that changes only the preregistration |
| `--frozen-on...is before the freezing commit...was written (...): a freeze cannot predate its commit (pass --allow-other-changes only to record an older freeze as it was)` | The date is earlier than the commit | Leave out `--frozen-on`, or give a later date |
| `freeze...is already in...; pick a new id (a refreeze is a new entry)` | The id was used | Pick a new id: a refreeze is a new entry |
| `...is already spent (collected...); a rerun is a new freeze` | The run was collected | Freeze again under a new id for a rerun |
| `--evidence...is not in the working tree: commit or copy the collected evidence first` | The evidence path is not on disk | Commit or copy the evidence, then collect |
| `--on...is before the freeze (...)` | The collection date is before the freeze | Give the real date |
| `...is...: only a live freeze is pinned by commit` | The freeze is spent | Pin only live freezes |
| `--commit...: not a commit in this clone (fetch it first)` | The commit or revision is not in this clone | Fetch it first |
| `...: loaded..., which the freeze does not list, so it does not cover it: list it, amend the preregistration and freeze again` | The run loaded a repository file the freeze does not name | List it, amend the preregistration and freeze again |
| `...: no file list recorded, so this guard cannot vouch for the launch` | The entry has no files (recorded by hand) | Freeze again with `kit freeze add` |
| `...is...and a rerun needs a new freeze that includes the guards added since; do not launch from...:...` | The entry carries rerun_needs_new_freeze | Freeze a later commit |
| `...:...differ from the freeze at...` | A listed file changed since the freeze | Revert it, or freeze again |
| `kit freeze:...` | Any refusal above, from the command line | Read the message; exit 2 |
| `--registry-rev...: not a commit in this clone (fetch it first)` | The commit or revision is not in this clone | Fetch it first |
| `...is not a file at...` | The registry is not committed at `--registry-rev` | Give a revision that has it |
| `...is not JSON:...` | The registry does not parse | Fix the JSON |
| `...is a folder at...: a freeze lists the files its run executes, never a whole folder` | A `--file` is a folder | List the files inside it one by one |
| `...is not a file at...: commit it before the freezing commit` | A listed file is not committed at the freezing commit | Commit it before the freezing commit |
| `--run-token...is not a short token such as run-a1b2c3` | The token has other characters | Use a short token such as a UTC stamp |
| `--at...: not a commit in this clone` | The `--at` revision is not in this clone | Fetch it, or give another revision |
| `...is pinned by commit: its run launches from git worktree add DIR..., not from...` | A pinned live freeze launched from another HEAD | Launch from `git worktree add DIR FROZEN_COMMIT` |
| `...is spent: a rerun launches from git worktree add DIR..., not from...` | A spent freeze launched outside its freezing commit | Launch from `git worktree add DIR COMMIT` |
| `cannot read --files-from...:...` | The list file cannot be read | Check its path |
| `cannot read...:...` | The registry file cannot be read | Check `--root` and `--registry` |
| `import_closure:...has no module-level function...named in always` | A name in `always` is not a module-level function of its file | Fix the name |
| `...is not a repository file path (relative, no . or .. parts, not a folder)` | A path is absolute, has `.` or `..` parts, or ends in `/` | Give a path relative to the repository root |
| `a code-sha256 block is not closed` | A fence is missing its closing line | Close the block |
| `...listed in both the readout and the plumbing set: a file is in one set only, and a readout file changes only by a dated amendment in a readout block` | One path is in both sets | Keep it in one set |
| `a deviations block is not closed` | A fence is missing its closing line | Close the block |
| `"deviations" must be a list of {date, sha256, path, reason}` | A run record's deviations is not a list | Fix the record |
| `...is not a file in the...` | The preregistration is not at that path | Check the path and `--at` |
| `...is not YYYY-MM-DD:...` | A date does not parse | Write YYYY-MM-DD |
| `a code-sha256 block holds a line that is not 'SHA256 PATH':...` | A hash line is malformed | Write `SHA256  PATH` as sha256sum prints it |
| `a deviations block holds a line that is not 'YYYY-MM-DD SHA256 PATH REASON':...` | A deviation line is malformed | Write `YYYY-MM-DD  SHA256  PATH  REASON` |
| `the deviation of...on...gives no reason` | A deviation line has no reason | Add the reason |
| `deviations[...] must be an object with date, sha256, path and reason` | A deviation entry is not an object | Fix the record |
| `deviations[...].sha256 must be a sha256 of 64 lower-case hex digits` | A deviation hash is malformed | Give 64 lower-case hex digits |
| `deviations[...] needs a path and a reason` | A deviation entry lacks a field | Add the path and the reason |
| `cannot read --record...:...` | The record file cannot be read | Check its path |
| `unknown code-sha256 block...: its fence takes no qualifier, or readout or plumbing in lower case, so no hashed file is skipped` | A fence has another qualifier | Use plain, readout or plumbing |
| `git...failed:...` | A git command failed | Read git's message |
| `not a PR number:...` | The PR is not a positive number | Give the number, such as 101 |
| `verdict must be one of...:...` | Another verdict word | Use GO, NO-GO or GO-WITH-NOTES |
| `log ref not found:...` | The `--log-from` revision is not in this clone | Fetch it |
| `commit not found in this clone:...(fetch it first, for example git fetch origin pull/.../head)` | The reviewed commit is not in this clone | Fetch the PR head first |
| `the reviewed commit...is not in this clone (git fetch origin pull/.../head)` | The reviewed commit is not in this clone | Fetch the PR head first |
| `base not found:...` | The base branch is not in this clone | Fetch it, or pass `--base` |
| `no merge base with...` | The commits share no history with the base | Check `--base` |
| `the reviewed commit...is already in..., so its own patch cannot be found; pass --base with the base commit from before the merge` | The id was used | Pick a new id: a refreeze is a new entry |
| `the head...is already in..., so the PR's own patch cannot be found; pass --base with the base commit from before the merge` | The id was used | Pick a new id: a refreeze is a new entry |
| `kit reviewpin:...` | Any reviewpin error above, from the command line | Read the message; exit 1 |
| `...line...has no pr or sha` | A log line lacks a field | Fix or remove that line |
| `--head not found:...` | The `--head` ref is not in this clone | Fetch it, or give another ref |
| `no head for PR...: pass --head REF (no refs/pull/.../head and no stored branch)` | No PR head ref and no stored branch | Pass `--head REF` |
| `...line...is not JSON:...` | The registry does not parse | Fix the JSON |

## How it works

1. `add` resolves the freezing commit, reads the preregistration and each listed file with `git show COMMIT:PATH`, refuses a folder or a missing file, checks the preregistration's own hash lines against those files, and refuses a freezing commit that changes more than the preregistration (`git diff --name-only` against its first parent) unless `--allow-other-changes` records the extra paths.
2. `check` repeats those reads, compares each file now (or at `--at`) with its recorded sha256, and sorts every difference into problems, attention or info by the entry's state.
3. `launch_check` reads each listed file from the working tree and compares hashes; a pinned live freeze also needs HEAD to be `frozen_commit`, and a spent one HEAD to be its freezing commit.
4. `executed_check` maps each loaded module's `__file__` (taken as given and with symbolic links resolved) to a repository path, leaving out `site-packages`, `dist-packages` and an interpreter prefix inside the repository, and refuses any path the freeze does not list. `run_script` runs the child through `RUNNER`, which writes the child's loaded files to a temporary record even when it fails.
5. `import_closure` parses each entry file with `ast`, collects `import`, `from ... import`, `__import__("NAME")` and `importlib.import_module("NAME")` with literal names at any depth, resolves them against the root as Python would, and follows them transitively.
6. `reviewpin delta` diffs `merge_base(SHA, BASE)..SHA` for the reviewed commit and for the head (`--unified=3`, no renames, full index), keys each hunk by its body without line numbers, and compares file by file. A changed file outside the review's `--scope` is noted, not counted. When files differ, `derive_checks` requires every commit after the pin to be a two-parent merge whose second parent is on the base and that was made after the pin was recorded, the same own change by content (`git diff --unified=0` lines, or `json_delta` for `.json`), and a `git merge-tree --write-tree` replay that matches each merge's tree for those files.

Constants: `LINE_CUT` 160 characters in printed lines, `FETCH_TIMEOUT_S` 120 s for `git fetch`.

## Cost and time

`freeze check` of a two-file freeze took 0.30 s wall; `reviewpin delta` on a small repository about 0.2 s (measured 2026-11-20, 4-core cloud container). Both scale with the number of files and commits git reads. It rents nothing.

## For agents

- **Command:** `python -m kit freeze check ID --json`; in the runner `freeze.launch_check(freeze.find(freeze.load(), ID))`; before a merge `python -m kit reviewpin delta PR --json`.
- **Parse:** `exit` and `problems` from check; `status` and `changes[].path` from delta.
- **Rerun:** `check`, `list`, `prereg`, `delta`, `explain` and `list` are read-only. `add` refuses a used id; `collect` refuses a spent freeze; `record` appends a new line each time, and the latest verdict wins.
- **Success:** `freeze check` exit 0; `reviewpin delta` exit 0 with `status` `carries`.
- **Not a pass:** a check that passes on a freeze whose list leaves out files the run imports (run `executed_check`, or list `import_closure`); a GO that carries says the code is what was reviewed, not that the review was sound; a freeze recorded after the result was seen.
- **Go-ahead:** Nothing.
- **Never:** never edit a live freeze's files or its registry entry to make a check pass; never rerun a spent freeze from the moving branch; never record your own pull request's GO in the PR's own tree and read it from there (read with `--log-from` the base branch).

## Tests

`python -m unittest tests.test_freeze tests.test_freezeguard tests.test_reviewpin tests.test_freezechain` covers every freeze action on throwaway repositories (hashes at the freezing commit, dates, refusals, other_changes, the preregistration's own hash lines, a spent rerun from a real worktree, pins by commit, collect), the registry shape and a configurable registry path, the runner guards (installed packages inside the repository are not repository files), the preregistration hash sets and deviations, `freeze prereg` from the command line, freezeguard's recording children and import closure (checked against what `python -m kit freeze --help` really loads), the review pins (own-patch compares, moved lines, scopes, NO-GO, derived covers and their failures, explain, the configurable log), and the outside check's bars. They do not test a real CI merge gate.

## History

- 2026-11-20: released to public Scrolls, on top of `357d2bd`, after an outside check on a toy repository; made generic: configurable root, registry, verdict log and base branch, workbench-only checks and merge modes dropped, `freeze prereg` added.

## Related

- [drivers](drivers.md): refuses to start a frozen run as restartable.
- [hubcall](hubcall.md): released with it after the same outside checks.
- [provenance](provenance.md): a record and digest of who ran what, without a freeze.
- [integrity](integrity.md): checks of claims, controls and preregistration order.
