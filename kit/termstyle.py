"""One terminal look for every Scrolls command: colour, spacing, wrapping, a title line and a closing line.

Chase asked on 23 Oct 2026 for one styled look, with good spacing and mouse support, on every current and future
terminal, so the look needs no install step and works on any branch:

* Automatic. `python -m kit ...` styles itself (`auto()`, called from `kit/cli.py`'s `main()` on a terminal), and a
  script styles itself with `script()` at the top of its `main()`. Either one also writes the startup hook into that
  Python's site-packages (`ensure_hook()`, once; `python -m kit style hook remove` undoes it), so from then on every
  script and every `python -m kit.MODULE` run from a Scrolls checkout with that Python gets the look, on any branch,
  even one older than this file: the hook carries its own copy of this module, kept outside the repository. It
  only changes bytes on a terminal. `kit/__init__.py` is left alone, so importing kit never loads the look.
* `run(argv)` for child commands (`hf jobs run`, `git`, ...): their output joins the look too, over a
  pseudo-terminal so progress bars stay live. Hugging Face's bucket sync chatter folds into one line.
* Building blocks for tools that draw their own screens: `panel`, `table`, `kv`, `dot`, `bar`, `wordmark`.
* `classify(line)`, the line rules shared with the mouse viewer (`kit.termview`).

Styling happens only on a terminal. Pipes, files, logs, `--json`, `NO_COLOR` (https://no-color.org), `SCROLLS_PLAIN=1`
and `TERM=dumb` get the program's own bytes unchanged. Lines that already carry colour codes or carriage returns
(progress bars) pass through untouched, and a partial line (a prompt) is written at once, so `input()` still works.
Widths are terminal cells (wide characters count two), and only glyphs macOS Terminal draws one cell wide are used.
Standard library only.
"""
import atexit
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

LETTERS = {
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "C": [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"],
    "R": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
}
GRADIENT = [51, 45, 39, 33, 99, 135]        # xterm-256 cyan to violet
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
KEY_PAD = 16


def fg(n):
    return f"38;5;{n}"


DIM, BOLD, UNDER = "2", "1", "4"
OK, WARN, BAD, INFO, LINK, KEY = fg(42), fg(214), fg(203), fg(45), fg(75), fg(244)
ROLE_CODE = {"ok": OK, "bad": BAD, "warn": WARN, "head": BOLD + ";" + fg(45), "section": BOLD, "rule": DIM,
             "dim": DIM, "key": KEY, "link": LINK + ";" + UNDER, "money": BOLD + ";" + fg(220), "plain": ""}


# ---- environment ---------------------------------------------------------------------------------------------------

def plain_wanted(environ=None):
    env = os.environ if environ is None else environ
    return bool(env.get("NO_COLOR") or env.get("SCROLLS_PLAIN") or env.get("TERM") == "dumb")


def color_on(stream=None):
    stream = stream or sys.stdout
    try:
        tty = stream.isatty()
    except (AttributeError, ValueError):
        tty = False
    return tty and not plain_wanted()


def paint(text, code, on=None):
    on = color_on() if on is None else on
    return f"\x1b[{code}m{text}\x1b[0m" if on and text and code else text


# ---- widths and wrapping -------------------------------------------------------------------------------------------

def cells(ch):
    if unicodedata.combining(ch) or ch in "​‍️":
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def width(text):
    """Terminal cells the text takes, colour codes excluded."""
    return sum(cells(c) for c in ANSI.sub("", str(text)))


def term_width(default=88, cap=110):
    return max(40, min(shutil.get_terminal_size((default, 24)).columns, cap))


def inner_width():
    """Cells available for text inside a panel at the current terminal width."""
    return term_width() - 7


def cut(text, w):
    """The text cut to w cells, colour dropped if it had to be cut."""
    if width(text) <= w:
        return text
    out, used = "", 0
    for c in ANSI.sub("", text):
        if used + cells(c) > w - 1:
            break
        out, used = out + c, used + cells(c)
    return out + "…"


def soft_wrap(line, w):
    """Wrap a plain line to w cells at spaces, keeping its own spacing (aligned columns stay aligned); continuation
    lines start under the line's indent plus two cells."""
    if width(line) <= w:
        return [line]
    indent = len(line) - len(line.lstrip(" "))
    lead = " " * min(indent + 2, w // 2)
    out, rest, first = [], line, True
    while width(rest) > (w if first else w - len(lead)):
        room = w if first else w - len(lead)
        used, cut_at, space = 0, 0, -1
        for i, c in enumerate(rest):
            if used + cells(c) > room:
                break
            used += cells(c)
            cut_at = i + 1
            if c == " " and i > (indent if first else 0):
                space = i
        k = space if space > 0 else cut_at
        out.append((lead if not first else "") + rest[:k].rstrip())
        rest, first = rest[k:].lstrip(" "), False
    if rest:
        out.append((lead if not first else "") + rest)
    return out


def wrap(line, w):
    """Word-wrap to w cells; continuation lines keep the line's leading indent, and a word longer than a line (a
    URL) is split. Colour is kept when the line fits and dropped from a line that has to wrap."""
    if width(line) <= w:
        return [line]
    plain = ANSI.sub("", line)
    indent = " " * (len(plain) - len(plain.lstrip(" ")))
    if len(indent) > w // 2:
        indent = ""
    room = max(1, w - len(indent))
    out, cur = [], ""
    for word in plain.split():
        for piece in [word[i:i + room] for i in range(0, len(word), room)]:
            trial = f"{cur} {piece}" if cur else piece
            if width(trial) <= room:
                cur = trial
            else:
                out.append(indent + cur)
                cur = piece
    out.append(indent + cur)
    return out


# ---- building blocks -----------------------------------------------------------------------------------------------

def wordmark(word="SCROLLS", on=None):
    rows = ["".join(LETTERS[ch][i] for ch in word) for i in range(6)]
    if width(rows[0]) + 2 > term_width():
        return "  " + paint(word, BOLD + ";" + fg(GRADIENT[0]), on)
    return "\n".join("  " + paint(r, fg(GRADIENT[i]), on) for i, r in enumerate(rows))


def gradient(text, on=None):
    """Text coloured cyan to violet, character by character."""
    if not (color_on() if on is None else on):
        return text
    n = max(1, len(text) - 1)
    return "".join(paint(c, fg(GRADIENT[round(i * (len(GRADIENT) - 1) / n)]), True) for i, c in enumerate(text))


def panel(title, lines, on=None, w=None):
    """A rounded box with a title in its top edge. Every row is exactly w + 3 cells wide."""
    w = w or term_width() - 4
    title = cut(title, w - 6)
    head = f"╭─ {paint(title, BOLD, on)} " + "─" * max(0, w - width(title) - 4) + "╮"
    body = []
    for ln in [sub for ln in (lines or [""]) for sub in str(ln).split("\n")]:
        for part in wrap(ln, w - 3):
            body.append("│ " + part + " " * max(0, w - 2 - width(part)) + "│")
    return "\n".join(["  " + head] + ["  " + b for b in body] + ["  ╰" + "─" * (w - 1) + "╯"])


def dot(state, on=None):
    """● coloured by state: ok, found, error, idle."""
    return paint("●", {"ok": OK, "found": WARN, "error": BAD}.get(state, DIM), on)


def mark(ok, on=None):
    return paint("✓", OK, on) if ok else paint("✗", BAD, on)


def kv(key, value, on=None, pad=KEY_PAD, w=None):
    """`key  value` with keys in one column; a long value wraps onto lines that start under the value."""
    w = w or inner_width()
    value = str(value)
    parts = wrap(value, max(20, w - pad - 1)) if width(value) > w - pad - 1 else [value]
    return "\n".join([f"{paint(key.ljust(pad), DIM, on)} {parts[0]}"] + [" " * (pad + 1) + p for p in parts[1:]])


def table(rows, headers, on=None, maxw=None):
    """Aligned columns with a dim header and a thin rule. When the table is wider than maxw cells (default: a
    panel's inner width), the last column wraps onto extra lines that start under it."""
    rows = [[str(c) for c in r] for r in rows]
    maxw = maxw or inner_width()
    cols = list(zip(*([headers] + rows))) if rows else [[h] for h in headers]
    ws = [max(width(c) for c in col) for col in cols]
    left = sum(ws[:-1]) + 2 * (len(ws) - 1)
    last = max(12, min(ws[-1], maxw - left))
    ws[-1] = last

    def line(cells_):
        return "  ".join(c + " " * (ws[i] - width(c)) for i, c in enumerate(cells_)).rstrip()

    out = [paint(line([cut(h, ws[i]) for i, h in enumerate(headers)]), DIM, on),
           paint("─" * min(maxw, left + last), DIM, on)]
    for r in rows:
        parts = wrap(r[-1], last) if width(r[-1]) > last else [r[-1]]
        out.append(line(r[:-1] + [parts[0]]))
        out += [" " * left + p for p in parts[1:]]
    return out


def bar(score, n=10, on=None):
    k = max(0, min(n, round(score * n)))
    return paint("█" * k, INFO, on) + paint("░" * (n - k), DIM, on)


# ---- line rules (shared with kit.termview) ----------------------------------------------------------------------

STATUS = [
    ("ok", r"PASS(?:ED)?|OK|ok|fits|✓|succeeded|BETTER|merged|done"),
    ("bad", r"FAIL(?:ED|URE)?|ERROR|[Ee]rror|VOID|✗|refused|Traceback|exception|WORSE"),
    ("warn", r"WARN(?:ING)?|[Ww]arning|SKIP(?:PED)?|skipped|pending|stale|DRY RUN|dry run"),
]
TOKEN = re.compile(
    r"(?P<link>https?://[^\s)>\]\"'`]+)"
    r"|(?P<money>(?<![\w.])\d[\d,]*(?:\.\d+)?\s?USD\b|\$\d[\d,]*(?:\.\d+)?)"
    + "".join(rf"|(?P<{role}>(?<![\w-])(?:{pat})(?![\w-]))" for role, pat in STATUS))
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
RULE = re.compile(r"^\s*([-=─━_*])\1{2,}\s*$")
SECTION = re.compile(r"^[A-Z][^:|]{0,58}:$")
KEYVAL = re.compile(r"^(\s*)([A-Za-z][\w .()/-]{0,28}?):(\s+)(\S.*)$")
TABLE = re.compile(r"^\s*\|.*\|\s*$")
SYNC_PLAN = re.compile(r"^Sync plan: (.+?) -> (.+)$")
SYNC_COUNT = re.compile(r"^\s+(Uploads|Downloads|Deletes|Skips): (\d+)\s*$")
SYNC_CHATTER = re.compile(r"^(?:Scanning (?:local directory|remote bucket) \(\d+ files?\)|Comparing files \(\d+ paths?\)"
                          r"|Syncing\.\.\.|Nothing to sync\.|(?:Uploading|Downloading) \d+ files?)$")


def classify(line):
    """The line as (text, role) segments; joined, the texts give back the line exactly. Roles: plain, head,
    section, rule, dim, key, ok, bad, warn, link, money."""
    if not line.strip() or "\x1b" in line or "\r" in line:
        return [(line, "plain")]
    m = HEADING.match(line)
    if m:
        return [(m.group(1) + " ", "dim"), (m.group(2), "head")]
    if RULE.match(line):
        return [(line, "rule")]
    if SECTION.match(line):
        return [(line, "section")]
    if TABLE.match(line):
        if set(line.strip()) <= set("|-: "):
            return [(line, "rule")]
        out = []
        for i, part in enumerate(re.split(r"(\|)", line)):
            out += [(part, "dim")] if part == "|" else _tokens(part)
        return [s for s in out if s[0]]
    m = KEYVAL.match(line)
    if m and "://" not in m.group(2):
        return [s for s in [(m.group(1), "plain"), (m.group(2) + ":", "key"), (m.group(3), "plain")]
                + _tokens(m.group(4)) if s[0]]
    return _tokens(line)


def _tokens(text):
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], "plain"))
        out.append((m.group(0), m.lastgroup))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], "plain"))
    return out or [(text, "plain")]


def ansi(line, links=True):
    """The line coloured for a terminal; links become clickable (OSC 8) where the terminal supports it."""
    out = []
    for text, role in classify(line):
        code = ROLE_CODE.get(role, "")
        if role == "rule" and RULE.match(text):
            text = text[:len(text) - len(text.lstrip())] + "─" * max(3, min(width(text.strip()), term_width() - 2))
        piece = f"\x1b[{code}m{text}\x1b[0m" if code and text.strip() else text
        if role == "link" and links:
            piece = f"\x1b]8;;{text}\x1b\\{piece}\x1b]8;;\x1b\\"
        out.append(piece)
    return "".join(out)


# ---- the styled stream ---------------------------------------------------------------------------------------------

class StyledStream:
    """A text stream that colours and wraps whole lines on their way to a terminal and passes everything else
    (partial lines, colour codes, carriage returns, bytes through .buffer) through unchanged."""

    def __init__(self, raw, wrap_width=None):
        self._raw, self._pending, self._wrap, self._sync = raw, "", wrap_width, None

    def write(self, s):
        if not isinstance(s, str):
            return self._raw.write(s)
        data = self._pending + s
        lines = data.split("\n")
        self._pending = lines.pop()
        for ln in lines:
            for out in self._fold(ln):
                self._raw.write(self._render(out) + "\n")
        if "\r" in self._pending or "\x1b" in self._pending:
            self._raw.write(self._pending)
            self._pending = ""
        return len(s)

    def _fold(self, ln):
        """Hugging Face's bucket sync prints nine lines per transfer; on a terminal they become one."""
        bare = ln.strip()
        if self._sync is not None:
            m = SYNC_COUNT.match(ln)
            if m:
                self._sync["n"][m.group(1).lower()] = int(m.group(2))
                return [self._sync_line()] if len(self._sync["n"]) == 4 else []
            done, self._sync = [self._sync_line()], None
            return done + self._fold(ln)
        m = SYNC_PLAN.match(bare)
        if m:
            self._sync = {"src": m.group(1), "dst": m.group(2), "n": {}}
            return []
        if SYNC_CHATTER.match(bare):
            return []
        return [ln]

    def _sync_line(self):
        sync, self._sync = self._sync, None
        n = sync["n"]
        home = str(Path.home())
        ends = [x.replace(home, "~", 1) if x.startswith(home) else x for x in (sync["src"], sync["dst"])]
        counts = ", ".join(f"{n[k]} {k}" for k in ("uploads", "downloads", "deletes", "skips") if n.get(k))
        return f"  sync {ends[0]} -> {ends[1]}: {counts or 'nothing to do'}"

    def _render(self, ln):
        if "\x1b" in ln or "\r" in ln or not ln.strip():
            return ln
        if ln.startswith("Hint: "):
            return paint(ln, DIM, True)
        w = self._wrap or shutil.get_terminal_size((100, 24)).columns
        parts = soft_wrap(ln, max(20, w - 1)) if width(ln) > w - 1 and not TABLE.match(ln) else [ln]
        return "\n".join(ansi(p) for p in parts)

    def flush(self):
        if self._sync is not None:
            self._raw.write(self._render(self._sync_line()) + "\n")
        if self._pending:
            self._raw.write(self._pending)
            self._pending = ""
        self._raw.flush()

    def __getattr__(self, name):
        return getattr(self._raw, name)


# ---- switching it on -----------------------------------------------------------------------------------------------

_STATE = {"on": False, "t0": None, "code": 0}
SKIP_SCRIPTS = {"atrium.py", "termview.py"}      # full-screen apps draw their own screen


def wanted(argv=None, streams=None):
    """Whether this process should be styled: a terminal, colour allowed, no --json or --plain asked for."""
    argv = list(sys.argv if argv is None else argv)
    if plain_wanted() or any(a in ("--json", "--plain", "--jsonl") for a in argv):
        return False
    if argv and Path(str(argv[0])).name in SKIP_SCRIPTS:
        return False
    return all(color_on(s) for s in (streams or [sys.stdout]))


def install(title=None, argv=None):
    """Style stdout and stderr for the rest of this process, with a title line now and a closing line at exit.
    Does nothing when the output is not a terminal or plain text is asked for. Safe to call twice."""
    if _STATE["on"] or getattr(sys, "_scrolls_styled", False) or not wanted(argv):
        return False
    _STATE.update(on=True, t0=time.time())
    sys._scrolls_styled = True              # one title line per process, whichever copy of this module runs
    raw_out, raw_err = sys.stdout, sys.stderr
    sys.stdout = StyledStream(raw_out)
    if color_on(raw_err):
        sys.stderr = StyledStream(raw_err)
    title = title or command_title(argv)
    raw_out.write(_title_line(title) + "\n")
    raw_out.flush()
    _hook_exit()
    atexit.register(_closing, raw_out)
    return True


def _title_line(title):
    stamp = time.strftime("%H:%M UTC", time.gmtime())
    left = gradient("◆ SCROLLS", True) + "  " + paint(title, BOLD, True)
    right = paint(stamp, DIM, True)
    gap = max(2, term_width(cap=200) - width(left) - width(right) - 1)
    return left + " " * gap + right


def _closing(raw):
    try:
        sys.stdout.flush()
    except Exception:
        pass
    secs = time.time() - (_STATE["t0"] or time.time())
    code = _STATE["code"]
    sign = paint("✓", OK, True) if code in (0, None) else paint("✗ exit " + str(code), BAD, True)
    took = f"{secs:.1f} s" if secs < 120 else f"{secs / 60:.1f} min"
    try:
        raw.write(paint("╰─ ", DIM, True) + sign + paint(f" done · {took}" if code in (0, None) else f" · {took}", DIM, True) + "\n")
        raw.flush()
    except (OSError, ValueError):
        pass


def _hook_exit():
    real_exit, real_hook = sys.exit, sys.excepthook

    def exit_(code=0):
        _STATE["code"] = code if isinstance(code, int) or code is None else 1
        real_exit(code)

    def hook(kind, value, tb):
        _STATE["code"] = 130 if kind is KeyboardInterrupt else 1
        real_hook(kind, value, tb)
    sys.exit, sys.excepthook = exit_, hook


def command_title(argv=None):
    """`kit auc`, `kit.tooldocs check` or `scripts/x.py`: the command as a person would type it."""
    orig = list(getattr(sys, "orig_argv", None) or [])
    if "-m" in orig[:-1]:
        i = orig.index("-m")
        mod = orig[i + 1]
        rest = [a for a in orig[i + 2:] if not a.startswith("-")][:1]
        return " ".join([mod] + rest)
    argv = list(sys.argv if argv is None else argv)
    if argv:
        p = Path(str(argv[0]))
        root = checkout_root(p)
        name = str(p.resolve().relative_to(root)) if root else p.name
        return " ".join([name] + [a for a in argv[1:] if not a.startswith("-")][:1])
    return "python"


def checkout_root(path):
    """The Scrolls checkout (private or public, any worktree) holding path, or None."""
    try:
        p = Path(path).resolve()
    except OSError:
        return None
    for d in [p] + list(p.parents):
        if (d / "kit" / "cli.py").is_file() and (d / "AGENTS.md").is_file():
            return d
    return None


def auto():
    """Called from kit/cli.py's main(): style this process when it was started as a kit command on a terminal.
    (Not from kit/__init__.py, so importing kit never loads the look.)"""
    orig = list(getattr(sys, "orig_argv", None) or [])
    if "-m" in orig[:-1] and orig[orig.index("-m") + 1] == "kit":
        if orig[orig.index("-m") + 2:][:1] in (["live"], ["style"]):
            return False
        on = install()
        if on:
            _announce(ensure_hook())
        return on
    return False


def script(title=None):
    """The look for a script, called at the top of its main(). Guard the import so a Job or a pipe never loads it:

        if sys.stdout.isatty():              # the Scrolls look (AGENTS.md rule 16)
            from kit import termstyle
            termstyle.script()

    Also writes the startup hook (ensure_hook), so later scripts with this Python get the look with no call at all."""
    on = install(title)
    if on:
        _announce(ensure_hook())
    return on


def _announce(new):
    if new:
        print(paint("  terminal look switched on for every Scrolls script run with this Python "
                    "(undo: python -m kit style hook remove)", DIM, True))


def run(argv, **kw):
    """Run a child command and return its exit code. When this process is styled, the child's output goes through
    the look over a pseudo-terminal (so its progress bars stay live and it still sees a terminal); otherwise the
    child writes straight to our stdout and stderr, byte for byte."""
    import subprocess
    if not isinstance(sys.stdout, StyledStream) or os.name != "posix":
        return subprocess.call(argv, **kw)
    import codecs
    import fcntl
    import pty
    import termios
    master, slave = pty.openpty()
    try:
        attrs = termios.tcgetattr(slave)
        attrs[1] &= ~termios.ONLCR                   # keep the child's newlines as they are
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, fcntl.ioctl(sys.__stdout__.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
    except (OSError, ValueError, AttributeError):
        pass
    try:
        proc = subprocess.Popen(argv, stdout=slave, stderr=slave, close_fds=True, **kw)
    finally:
        os.close(slave)
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:                          # the child closed its end (Linux reports EIO)
                break
            if not data:
                break
            sys.stdout.write(dec.decode(data))
        return proc.wait()
    finally:
        os.close(master)
        sys.stdout.flush()


# ---- the startup hook ----------------------------------------------------------------------------------------------

HOOK_NAME = "scrolls_termhook"
LOOK_VERSION = 2                            # raise when this file changes in a way the hook's copy should pick up
HOOK = '''"""Scrolls terminal look (written by kit.termstyle; remove with `python -m kit style hook remove`).
Styles scripts run from a Scrolls checkout on a terminal, any branch; does nothing anywhere else. The look itself is
scrolls_termhook_look.py beside this file, a copy of the checkout's kit/termstyle.py kept outside the repository."""
import os
import sys
from pathlib import Path


def _run():
    if os.environ.get("NO_COLOR") or os.environ.get("SCROLLS_PLAIN") or not sys.stdout.isatty():
        return
    argv = list(getattr(sys, "orig_argv", None) or [])[1:]
    if "-c" in argv:
        return
    if "-m" in argv[:-1]:
        mod, rest = argv[argv.index("-m") + 1], argv[argv.index("-m") + 2:]
        if mod.split(".")[0] != "kit" or mod in ("kit.termstyle", "kit.termview") or rest[:1] in (["live"], ["style"]):
            return
        p, script, args = Path.cwd(), mod, rest
    else:
        script = next((a for a in argv if not a.startswith("-")), None)
        if not script or not script.endswith(".py"):
            return
        try:
            p = Path(script).resolve()
        except OSError:
            return
        args = argv[argv.index(script) + 1:]
    for d in [p] + list(p.parents):
        if (d / "kit" / "cli.py").is_file() and (d / "AGENTS.md").is_file():
            import importlib.util
            look = Path(__file__).with_name("scrolls_termhook_look.py")
            if not look.is_file():
                look = d / "kit" / "termstyle.py"
            if not look.is_file():
                return
            spec = importlib.util.spec_from_file_location("_scrolls_termstyle", look)
            style = importlib.util.module_from_spec(spec)
            sys.modules["_scrolls_termstyle"] = style
            spec.loader.exec_module(style)
            style.install(argv=[script] + args)
            return


try:
    _run()
except Exception:
    pass
'''


def site_dir():
    import sysconfig
    return Path(sysconfig.get_paths()["purelib"])


def _hook_files(d):
    return {d / f"{HOOK_NAME}.py": HOOK, d / f"{HOOK_NAME}.pth": f"import {HOOK_NAME}\n",
            d / f"{HOOK_NAME}_look.py": Path(__file__).read_text(encoding="utf-8")}


def _copy_version(path):
    m = re.search(r"^LOOK_VERSION = (\d+)", path.read_text(encoding="utf-8"), re.M) if path.is_file() else None
    return int(m.group(1)) if m else 0


def hook_install(target=None):
    """Write the startup hook and its copy of the look into a Python environment's site-packages (default: this
    interpreter's)."""
    d = Path(target) if target else site_dir()
    d.mkdir(parents=True, exist_ok=True)
    for path, text in _hook_files(d).items():
        path.write_text(text, encoding="utf-8")
    return d


def ensure_hook(target=None):
    """Install or refresh the hook quietly; True only when it was not there before. Never downgrades the copy (an
    older branch leaves a newer copy alone), skips with SCROLLS_NO_HOOK=1, and gives up silently on a read-only
    site-packages."""
    if os.environ.get("SCROLLS_NO_HOOK"):
        return False
    d = Path(target) if target else site_dir()
    try:
        new = not hook_status(d)
        for path, text in _hook_files(d).items():
            if path.name.endswith("_look.py") and _copy_version(path) > LOOK_VERSION:
                continue
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                d.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        return new
    except OSError:
        return False


def hook_remove(target=None):
    d = Path(target) if target else site_dir()
    gone = []
    for name in (f"{HOOK_NAME}.py", f"{HOOK_NAME}.pth", f"{HOOK_NAME}_look.py"):
        if (d / name).exists():
            (d / name).unlink()
            gone.append(name)
    return gone


def hook_status(target=None):
    d = Path(target) if target else site_dir()
    return (d / f"{HOOK_NAME}.pth").is_file() and (d / f"{HOOK_NAME}.py").is_file()


def demo():
    """Sample output covering every line rule."""
    return [
        "# Demo of the Scrolls terminal look",
        "Summary:",
        "  status: PASS on 9 of 9 slabs, 0 FAILED",
        "  cost: 0.72 USD of a 1.10 USD cap",
        "  warning: one row is pending a card",
        "  page: https://scrollprize.org/prizes",
        "| tool | state |",
        "| --- | --- |",
        "| auc | ok |",
        "----",
        "Long lines wrap at the terminal edge with their indent kept, so nothing runs off the screen or breaks "
        "mid-word, and a URL longer than the line is split cleanly.",
    ]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m kit.termstyle", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hook", help="add or remove the startup hook that styles every script in a checkout")
    h.add_argument("action", choices=["install", "remove", "status"])
    h.add_argument("--site", help="site-packages folder (default: this Python's)")
    sub.add_parser("demo", help="print sample output in the Scrolls look")
    pp = sub.add_parser("pipe", help="style text piped in, for shell scripts: bash x.sh 2>&1 | python -m kit style pipe")
    pp.add_argument("--title", default="", help="title line (default: none)")
    args = ap.parse_args(argv)
    if args.cmd == "demo":
        install(title="kit.termstyle demo")
        for ln in demo():
            print(ln)
        return 0
    if args.cmd == "pipe":
        out = StyledStream(sys.stdout) if color_on(sys.stdout) else sys.stdout
        if args.title and out is not sys.stdout:
            sys.stdout.write(_title_line(args.title) + "\n")
        try:
            for ln in sys.stdin:
                out.write(ln)
                out.flush()
        except KeyboardInterrupt:
            return 130
        return 0
    if args.action == "install":
        print(f"hook installed in {hook_install(args.site)}; scripts in a Scrolls checkout now use the look "
              "(kit commands and styled scripts also do this by themselves)")
    elif args.action == "remove":
        gone = hook_remove(args.site)
        print("removed " + ", ".join(gone) if gone else "no hook to remove")
    else:
        on = hook_status(args.site)
        print(f"hook {'installed' if on else 'not installed'} in {Path(args.site) if args.site else site_dir()}")
        return 0 if on else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
