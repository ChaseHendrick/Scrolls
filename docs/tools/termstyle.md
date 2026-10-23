# termstyle: one terminal look for every Scrolls command

Gives every kit command and every script in a checkout one look on a terminal (colour, spacing, wrapping, a title and a closing line), keeps plain text for pipes and logs, and opens any output in a mouse-driven viewer (`kit live`).

| Field | Value |
| --- | --- |
| Id | `termstyle` |
| Status | Current |
| Kind | kit module,kit command |
| Area | Viewers and apps |
| Run | `python -m kit style`, `python -m kit live` |
| Code | `kit/termstyle.py`, `kit/termview.py` |
| Tests | `tests/test_termstyle.py` |
| Needs | Python 3.10 or newer (uses `sys.orig_argv`), standard library only; `curses` for `kit live` (macOS and Linux Python have it, Windows does not). A terminal with 256 colours; links are clickable in terminals that support OSC 8 hyperlinks (iTerm2; macOS Terminal opens a URL on Cmd-double-click either way) |
| Runs on | Any machine. `python -m kit style demo` took 0.1 s end to end in a pseudo-terminal (measured 2026-10-23, 4-core cloud container, Python 3.13) |
| Network | None. `kit live` opens a clicked link in the default browser |
| Writes | On a terminal only, the startup hook: `scrolls_termhook.py`, `scrolls_termhook.pth` and `scrolls_termhook_look.py` (its copy of the look) in the running Python's site-packages, written once by the first styled kit command or script (`ensure_hook`), or by `kit style hook install` (`--site DIR` for another environment); `hook remove` deletes them |
| Go-ahead | Not needed. It only changes how output looks on a terminal; `kit live` runs exactly the command typed after `--`, so that command's own gates apply |
| Released | Public `main` from the merge of its pull request (23 Oct 2026); the same files are in Scrolls-private |
| License | This repository's license; no third-party code |
| Checked | 2026-10-23 against commit `1b52e70` |

## What it does

Chase asked on 23 Oct 2026 for one styled look on every terminal we have, today's and future ones ("apply that fancy ascii terminal that one thing had to all our current and future terminals. i want them looking fancy and nice with that good spacing and mouse ability"). Our tools print plain text from hundreds of places, so restyling each one by hand would never finish and would drift. termstyle styles output at one point instead: the stream.

On a terminal, every kit command starts with a title line (`◆ SCROLLS  kit auc  ...  00:21 UTC`, the wordmark in a cyan to violet gradient) and ends with a closing line (`╰─ ✓ done · 1.2 s`, or `✗ exit 3`). In between, each whole line is coloured by a few rules: markdown headings, `Section:` lines, rules, table pipes, `key: value` keys, status words (PASS, ok, fits green; FAIL, ERROR, VOID red; WARNING, SKIPPED, pending, stale amber), amounts in USD, and links (underlined and clickable where the terminal supports it). A line wider than the terminal wraps at a space with its indent plus two cells, keeping its own spacing, so aligned columns stay aligned. Every `python -m kit ...` command, new ones included, gets this without doing anything, because `kit/cli.py`'s `main()` calls `termstyle.auto()` when stdout is a terminal; `python -m kit.MODULE` commands get it from the startup hook below. `kit/__init__.py` stays untouched, so importing kit never loads the look.

Scripts and `python -m kit.MODULE` commands get it from a startup hook that needs no install step (Chase, 01:30 UTC 23 Oct: "the terminal isnt pretty, didnt i tell you to make all future terminals pretty"). The first kit command or styled script run on a terminal writes it into that Python's site-packages and says so in one dim line; from then on any `.py` file inside a Scrolls checkout, and any `kit.MODULE` run from inside one, is styled the same way with that Python, on any branch, including branches older than the look, because the hook carries its own copy of this module (`scrolls_termhook_look.py`, refreshed by newer versions and never downgraded by older ones). Nothing outside a checkout changes. A script styles itself, before the hook exists, with `termstyle.script()` at the top of its `main()` behind an `isatty()` guard, and runs child commands with `termstyle.run(argv)` so their output (Hugging Face's `hf jobs run`, for example) joins the look over a pseudo-terminal. Hugging Face's bucket sync chatter (Scanning, Comparing, the nine-line Sync plan) folds into one `sync A -> B: N uploads` line on a terminal; pipes and logs keep every line. Shell scripts pipe through `python -m kit style pipe`.

Mouse: a printed line cannot react to the mouse once it has scrolled past, so `python -m kit live -- COMMAND` runs any command in a full-screen view in the same colours: wheel scrolling, clickable links and buttons (Stop, Rerun, Quit), search, follow mode. `COMMAND | python -m kit live` pages output from a pipe.

It changes looks only. Pipes, files, logs, `--json`, `--plain`, `NO_COLOR`, `SCROLLS_PLAIN=1` and `TERM=dumb` get the program's own bytes. Lines that already carry colour codes or carriage returns (progress bars and live monitors) pass through untouched, and a partial line such as a prompt is written at once, so `input()` keeps working.

## When to use it

- Every day, automatically: run kit commands as usual.
- Nothing to install: the first kit command or styled script on a terminal installs the hook. `python -m kit style hook install` remains for another environment (`--site`).
- `python -m kit live -- COMMAND` for long output you want to scroll, search or click through.
- `bash x.sh 2>&1 | python -m kit style pipe` for shell scripts.
- In a new tool that draws its own screen: `panel`, `table`, `kv`, `dot`, `bar` and `classify` from this module, so it matches.

Do not use it:

- To make output an agent parses: keep `--json` (styling is off with it) and read the tool page's "For agents" section.
- For commands that ask questions inside `kit live`: their input is closed there, so run them directly.
- On Windows: there is no `curses`, and the stream styling expects a terminal that understands 256-colour codes.

## Quick start

```bash
python3 -m kit style demo
python3 -m kit live -- python3 -m kit prizes
```

The demo printed (colours not shown):

```
◆ SCROLLS  kit.termstyle demo                                         00:26 UTC
# Demo of the Scrolls terminal look
Summary:
  status: PASS on 9 of 9 slabs, 0 FAILED
  cost: 0.72 USD of a 1.10 USD cap
╰─ ✓ done · 0.0 s
```

It worked if the title line has the gradient wordmark and PASS is green; `python3 -m kit style hook status` exits 0 once the hook is in.

## Checks and controls

The control is plain output: the same command into a pipe must carry no escape codes and no title line (`test_kit_command_plain_on_a_pipe`), and `classify` must give back every line exactly when its segments are joined (`test_segments_join_back_exactly`), so styling can never change what a tool says. A wrong rule shows as colour on the wrong word, never as changed text.

Claim label: Sourced fact (it shows the tools' own output, its text unchanged).

## Commands and options

### `python -m kit style`

```
usage: python -m kit style [-h] ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cmd` | none | `hook install`, `hook remove` or `hook status` (with `--site DIR` for another environment); `demo`; `pipe [--title T]` |

### `python -m kit live`

```
usage: python -m kit live [-h] ...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `cmd` | none | the command to run, after -- |

### Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `ESCDELAY` | 25 | Milliseconds curses waits after Esc in `kit live` |
| `NO_COLOR` | unset | Any value turns styling off (https://no-color.org) |
| `SCROLLS_PLAIN` | unset | Any value turns styling off |
| `SCROLLS_NO_HOOK` | unset | Any value stops kit commands and `script()` from installing the startup hook (the tests set it) |
| `TERM` | the terminal's | `dumb` turns styling off |

## Python API

| Function | Returns | Raises | Notes |
| --- | --- | --- | --- |
| `fg(n)` | str | None | xterm-256 foreground code for colour n |
| `plain_wanted(environ=None)` | bool | None | True when NO_COLOR, SCROLLS_PLAIN or TERM=dumb asks for plain text |
| `color_on(stream=None)` | bool | None | A terminal and colour allowed |
| `paint(text, code, on=None)` | str | None | text wrapped in the colour code when colour is on |
| `cells(ch)` | int | None | 0, 1 or 2 terminal cells for one character |
| `width(text)` | int | None | Terminal cells the text takes, colour codes excluded. |
| `term_width(default=88, cap=110)` | int | None | Terminal columns, clamped to 40 to cap |
| `inner_width()` | int | None | Cells available for text inside a panel at the current terminal width. |
| `cut(text, w)` | str | None | The text cut to w cells, colour dropped if it had to be cut. |
| `soft_wrap(line, w)` | list of str | None | Wrap a plain line to w cells at spaces, keeping its own spacing (aligned columns stay aligned); continuation |
| `wrap(line, w)` | list of str | None | Word-wrap to w cells; continuation lines keep the line's leading indent, and a word longer than a line (a |
| `wordmark(word='SCROLLS', on=None)` | str | `KeyError` for letters outside S, C, R, O, L | Six-row block wordmark in the gradient; one line when the terminal is narrow |
| `gradient(text, on=None)` | str | None | Text coloured cyan to violet, character by character. |
| `panel(title, lines, on=None, w=None)` | str | None | A rounded box with a title in its top edge. Every row is exactly w + 3 cells wide. |
| `dot(state, on=None)` | str | None | ● coloured by state: ok, found, error, idle. |
| `mark(ok, on=None)` | str | None | Green ✓ or red ✗ |
| `kv(key, value, on=None, pad=KEY_PAD, w=None)` | str | None | `key  value` with keys in one column; a long value wraps onto lines that start under the value. |
| `table(rows, headers, on=None, maxw=None)` | list of str | None | Aligned columns with a dim header and a thin rule. When the table is wider than maxw cells (default: a |
| `bar(score, n=10, on=None)` | str | None | A bar of n cells filled to score (0 to 1) |
| `classify(line)` | list of (text, role) | None | The line as (text, role) segments; joined, the texts give back the line exactly. Roles: plain, head, |
| `ansi(line, links=True)` | str | None | The line coloured for a terminal; links become clickable (OSC 8) where the terminal supports it. |
| `StyledStream(raw, wrap_width=None)` | a stream | None | A text stream that colours and wraps whole lines on their way to a terminal and passes everything else |
| `wanted(argv=None, streams=None)` | bool | None | Whether this process should be styled: a terminal, colour allowed, no --json or --plain asked for. |
| `install(title=None, argv=None)` | bool, True if it switched on | None | Style stdout and stderr for the rest of this process, with a title line now and a closing line at exit. |
| `command_title(argv=None)` | str | None | `kit auc`, `kit.tooldocs check` or `scripts/x.py`: the command as a person would type it. |
| `checkout_root(path)` | `Path` or None | None | The Scrolls checkout (private or public, any worktree) holding path, or None. |
| `auto()` | bool | None | Called from kit/cli.py's main(): style this process when it was started as a kit command on a terminal. |
| `site_dir()` | `Path` | None | This interpreter's site-packages (`sysconfig` purelib) |
| `script(title=None)` | bool | None | The look for a script, called at the top of its main() behind an `isatty()` guard; also installs the startup hook |
| `run(argv, **kw)` | int exit code | `OSError` when the command cannot start | Run a child command; when this process is styled its output goes through the look over a pseudo-terminal, otherwise plain `subprocess.call` |
| `ensure_hook(target=None)` | bool | None | Install or refresh the hook quietly; True only when it was not there before; never downgrades the copy |
| `hook_install(target=None)` | `Path` written to | `OSError` when the folder is not writable | Write the startup hook into a Python environment's site-packages (default: this interpreter's). |
| `hook_remove(target=None)` | list of removed file names | `OSError` | Removes the hook's three files |
| `hook_status(target=None)` | bool | None | Both hook files present |
| `demo()` | list of str | None | Sample output covering every line rule. |
| `main(argv=None)` | int, the exit code | None | Command-line entry |
| `Source(argv=None, fd=None)` | a source with `lines`, `code`, `state` | None | Lines from a running command or from a pipe, collected by a thread. |
| `visual_lines(lines, w)` | list of (int, str) | None | Each source line soft-wrapped to w cells: a list of (source index, text). |
| `find(vis, query, start)` | int or None | None | Index of the next visual line at or after start that contains query (case-insensitive), wrapping round. |
| `View(scr, source, title)` | the viewer | None | Draws and handles keys and mouse; used by `run` |
| `fit(text, w)` | str | None | Text cut or padded to exactly w cells |
| `run(argv=None, fd=None, title=None)` | int | None | Show a command's output (argv) or a pipe's (fd) until the person quits; returns the command's exit code. |
| `main(argv=None)` | int, the exit code | None | `kit live` entry |

## Inputs

Text a program writes to stdout or stderr; for `kit live`, a command after `--` or a pipe on standard input.

## Outputs

On a terminal: the same text with colour codes, the title line and the closing line; elsewhere, the text unchanged. `kit live` draws a full screen and leaves nothing behind when it quits.

| Exit code | Meaning |
| --- | --- |
| `0` | Done; `kit live` passes back the command's own exit code |
| `2` | `kit live` with nothing to run and no pipe, or no terminal for keys |
| `3` | `kit style hook status`: the hook is not installed |

## Failure modes

| What you see | Why | What to do |
| --- | --- | --- |
| `usage: ...` then `error: ...` on stderr, exit code 2 | A missing or wrong argument | Check the command against Commands and options |
| `kit live needs a terminal to read keys from (/dev/tty)` | Output was piped in, but there is no terminal to read keys from (a cron job, a CI log) | Run it from a terminal, or read the output without `kit live` |
| No colour on a kit command | Output is piped or redirected, `NO_COLOR` or `SCROLLS_PLAIN` is set, or `--json` was given | Expected; run it on a terminal without those |
| Scripts not styled | The hook is not installed for this Python yet (no kit command or styled script has run with it on a terminal), or `SCROLLS_NO_HOOK=1` is set | Run any kit command with that Python once, or `PYTHON -m kit style hook install` |
| Child command output plain | The script started it with `subprocess` directly | `termstyle.run(argv)` |

## How it works

`kit/cli.py`'s `main()` imports this module only when stdout is a terminal, so pipes, logs and containers never load it. `auto()` looks at `sys.orig_argv`: a `-m kit` start (other than `kit live` and `kit style`) calls `install()`, which checks `wanted()` (a terminal on stdout, colour allowed, no `--json`, `--jsonl` or `--plain`, not a full-screen app in `SKIP_SCRIPTS`), wraps `sys.stdout` and `sys.stderr` in `StyledStream`, prints the title line and registers the closing line with `atexit`; `sys.exit` and `sys.excepthook` are wrapped to learn the exit code. `StyledStream.write` holds text until a newline, renders each whole line with `soft_wrap` and `ansi(classify(line))`, and writes partial lines on `flush()`. The startup hook is a `.pth` file that imports `scrolls_termhook`, which finds the script's checkout (for `-m kit.MODULE`, the working folder's) (a folder with `kit/cli.py` and `AGENTS.md`, so branches older than this module count) and loads its own copy, `scrolls_termhook_look.py` beside it (the checkout's `kit/termstyle.py` only when the copy is missing), registered in `sys.modules` as `_scrolls_termstyle`. The copy sits outside the repository and only changes bytes on a terminal. `ensure_hook()` compares the three files with what this version would write and rewrites any that differ, except a copy whose `LOOK_VERSION` is newer. `run()` gives the child a pseudo-terminal of the same size with `ONLCR` off and feeds what it prints through `sys.stdout`; when this process is not styled it is plain `subprocess.call`. `StyledStream._fold` drops the sync chatter lines and turns `Sync plan:` and its four counts into one line. Only one title line is printed per process (`sys._scrolls_styled`). `kit live` reads the command's output in a thread and redraws every 150 ms with `curses`, mapping the same roles to colour pairs (`ROLE_PAIR`).

## Cost and time

Free and local. A styled line costs microseconds; not separately measured. `kit live` holds the whole output in memory.

## For agents

- **Command:** none for agents; agents read plain output (pipes are never styled) or `--json`.
- **Parse:** the tools' own output; styling never reaches a pipe.
- **Rerun:** safe; `hook install` overwrites the same three files, and `ensure_hook` writes only what changed.
- **Success:** exit 0.
- **Not a pass:** a green PASS on screen is the tool's own word, coloured; read the tool's checks.
- **Go-ahead:** Nothing.
- **Never:** parse a styled screen.

## Tests

`python3 -m unittest tests.test_termstyle -v`: line rules (exact round trip, roles, word boundaries), wrapping (spacing kept, long words, wide characters), the stream (partial lines, existing colour codes and carriage returns pass through), when it switches on (pipe, `NO_COLOR`, `--json`, full-screen apps, kit versus other modules), titles and checkout detection, the hook (install, status, remove, a pipe stays plain), a kit command in a pseudo-terminal (styled) and in a pipe (plain), `kit live` running a command, searching and quitting, `ensure_hook` (once, never downgrading, `SCROLLS_NO_HOOK`), the sync fold, a script calling `script()` with a child through `run()` in a pseudo-terminal, the hook styling a branch that has no `kit/termstyle.py` in a fresh virtual environment (and a pipe staying plain), and the viewer's wrapping, search and command collection. Not covered: real mouse events in `kit live` (checked by hand with SGR mouse codes in a pseudo-terminal rendered by pyte, 2026-10-23; pyte does not draw curses' scroll-down code, so that check shows stale rows a real terminal does not).

## History

- 2026-10-23: first public version, the same `kit/termstyle.py` and `kit/termview.py` as Scrolls-private's (`05987e92`), with comments that named private tools reworded (Chase: "apply that fancy ascii terminal that one thing had to all our current and future terminals"; "the terminal isnt pretty, didnt i tell you to make all future terminals pretty").

## Related

- [cli](cli.md): `kit/cli.py`'s `main()` turns the look on for every kit command.
- [TOOL-DOCS.md](../TOOL-DOCS.md): new tools print through this module (AGENTS.md rule 17, "Terminal look").
