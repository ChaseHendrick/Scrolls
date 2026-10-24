"""A full-screen, mouse-driven view of any command's output, in the Scrolls terminal look.

    python -m kit live -- COMMAND [ARGS...]          # run it and watch its output live
    COMMAND | python -m kit live                     # or page what another command printed

Scroll with the wheel, the arrows, j and k, PgUp and PgDn; click a link to open it; / searches and n jumps to the
next hit; f follows the end; s stops the command, r runs it again; q quits. Lines are coloured by the same rules as
every other Scrolls command (`kit.termstyle.classify`). The command runs with its input closed, so a command that
asks a question gets an end of file: run those directly. Standard library only (`curses`, so macOS and Linux).

The full-screen view lives on the terminal's alternate screen, which vanishes when it closes, so on every exit the
whole output is printed again on the normal screen, with a closing line (exit code, line count), and stays in the
scrollback. Keys typed or pasted before the view opened (the rest of a pasted block) are thrown away and keys in its
first half second are ignored: on 23 Oct 2026 the letters "s" and "q" of a pasted block stopped and closed the view
before Chase saw anything, twice. With no usable terminal (output not a terminal, TERM=dumb, or curses fails to
start) the command runs plainly instead.
"""
import curses
import os
import subprocess
import sys
import threading
import time
import webbrowser

from . import termstyle as ts

ROLE_PAIR = {"plain": 0, "head": 1, "section": 6, "rule": 2, "dim": 2, "key": 2, "ok": 3, "warn": 4, "bad": 5,
             "link": 7, "money": 8}
PAIRS = [(45, -1), (244, -1), (42, -1), (214, -1), (203, -1), (-1, -1), (75, -1), (220, -1), (252, 236), (16, 45)]
CLICK = curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED
WHEEL_DOWN = getattr(curses, "BUTTON5_PRESSED", 0x200000)
GRACE_S = 0.5        # keys in the view's first half second are ignored (see the module docstring)
HELP = ("wheel or ↑↓ jk scroll   PgUp PgDn g G page   click a link to open it   / search  n next   "
        "f follow   s stop   r rerun   q quit")


class Source:
    """Lines from a running command or from a pipe, collected by a thread."""

    def __init__(self, argv=None, fd=None):
        self.argv, self.fd, self.lines, self.code, self.proc = argv, fd, [], None, None
        self.started = time.time()

    def start(self):
        self.lines, self.code, self.started = [], None, time.time()
        if self.argv is None:
            threading.Thread(target=self._read_fd, daemon=True).start()
            return
        try:
            self.proc = subprocess.Popen(self.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace",
                                         env=dict(os.environ, PYTHONUNBUFFERED="1"))
        except OSError as e:
            self.lines.append(f"could not start: {e}")
            self.code = 127
            return
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for ln in self.proc.stdout:
            self.lines.append(ln.rstrip("\n"))
        self.code = self.proc.wait()

    def _read_fd(self):
        with os.fdopen(self.fd, "r", errors="replace") as f:
            for ln in f:
                self.lines.append(ln.rstrip("\n"))
        self.code = 0

    def stop(self):
        if self.proc and self.code is None:
            self.proc.terminate()

    def wait(self, timeout):
        """Wait up to timeout seconds for the reader to finish, so the transcript has every line."""
        end = time.time() + timeout
        while self.code is None and time.time() < end:
            time.sleep(0.02)

    @property
    def state(self):
        if self.code is None:
            return "running"
        return "ok" if self.code == 0 else f"exit {self.code}"


def visual_lines(lines, w):
    """Each source line soft-wrapped to w cells: a list of (source index, text)."""
    out = []
    for i, ln in enumerate(lines):
        clean = ts.ANSI.sub("", ln).replace("\t", "    ").replace("\r", "")
        for part in ts.soft_wrap(clean, max(10, w)) or [""]:
            out.append((i, part))
    return out


def find(vis, query, start):
    """Index of the next visual line at or after start that contains query (case-insensitive), wrapping round."""
    q = query.lower()
    n = len(vis)
    for k in range(n):
        j = (start + k) % n
        if q in vis[j][1].lower():
            return j
    return None


class View:
    def __init__(self, scr, source, title, clock=time.monotonic):
        self.scr, self.src, self.title, self.clock = scr, source, title, clock
        self.opened = clock()
        self.top, self.follow, self.query, self.searching, self.msg = 0, True, "", False, ""
        self.regions = []

    def put(self, y, x, text, attr=0, w=None, on_click=None):
        h, sw = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= sw:
            return
        w = min(w if w is not None else sw - x, sw - x)
        text = fit(text, w) if w > 0 else ""
        try:
            self.scr.addstr(y, x, text, attr)
        except curses.error:
            pass
        if on_click:
            self.regions.append((y, x, x + ts.width(text), on_click))

    def draw(self):
        self.scr.erase()
        self.regions = []
        h, w = self.scr.getmaxyx()
        bar = curses.color_pair(9)
        self.put(0, 0, " " * w, bar)
        self.put(0, 1, "◆ SCROLLS", bar | curses.A_BOLD)
        self.put(0, 12, self.title, bar, w - 30)
        state = self.src.state
        colour = {"running": 4, "ok": 3}.get(state, 5)
        self.put(0, w - 16, f"● {state}", curses.color_pair(colour) | curses.A_BOLD, 15)
        body = h - 2
        self.vis = visual_lines(self.src.lines, w - 3)
        if self.follow:
            self.top = max(0, len(self.vis) - body)
        self.top = max(0, min(self.top, max(0, len(self.vis) - body)))
        for r, (_, text) in enumerate(self.vis[self.top:self.top + body]):
            self.draw_line(1 + r, 1, text, w - 3)
        if len(self.vis) > body:
            thumb = 1 + int((body - 1) * self.top / max(1, len(self.vis) - body))
            self.put(thumb, w - 1, "┃", curses.color_pair(1))
        foot = (f"/ {self.query}▏" if self.searching else self.msg) or HELP
        self.put(h - 1, 0, " " * w, bar)
        self.put(h - 1, 1, foot, bar, w - 30)
        x = w - 27
        for label, fn in (("Stop", self.src.stop), ("Rerun", self.rerun), ("Quit", None)):
            self.put(h - 1, x, f" {label} ", curses.color_pair(10) | curses.A_BOLD, on_click=fn or self.quit)
            x += len(label) + 3
        self.scr.refresh()

    def draw_line(self, y, x, text, w):
        used = 0
        for seg, role in ts.classify(text):
            if used >= w:
                break
            attr = curses.color_pair(ROLE_PAIR.get(role, 0))
            if role in ("head", "section", "money", "ok", "bad"):
                attr |= curses.A_BOLD
            if role == "link":
                attr |= curses.A_UNDERLINE
                self.put(y, x + used, seg, attr, w - used, on_click=lambda u=seg: self.open(u))
            else:
                self.put(y, x + used, seg, attr, w - used)
            used += ts.width(seg)

    def open(self, url):
        try:
            webbrowser.open(url)
            self.msg = "opened " + url
        except Exception as e:  # no browser here: say so and keep going
            self.msg = f"could not open: {e}"

    def rerun(self):
        if self.src.argv is not None:
            self.src.stop()
            self.src.start()
            self.follow, self.msg = True, "started again"

    def quit(self):
        raise SystemExit(self.src.code or 0)

    def scroll(self, d):
        self.follow = False
        self.top = max(0, self.top + d)

    def on_key(self, k):
        if k != curses.KEY_MOUSE and self.clock() - self.opened < GRACE_S:
            return                       # the tail of a paste, not a person: a stray s or q must not stop or close
        h, _ = self.scr.getmaxyx()
        if self.searching:
            if k in (10, 13, curses.KEY_ENTER):
                self.searching = False
                self.jump()
            elif k == 27:
                self.searching = False
            elif k in (curses.KEY_BACKSPACE, 127, 8):
                self.query = self.query[:-1]
            elif isinstance(k, str):
                self.query += k
            return
        if k in ("q", "Q"):
            self.quit()
        elif k in (curses.KEY_DOWN, "j"):
            self.scroll(1)
        elif k in (curses.KEY_UP, "k"):
            self.scroll(-1)
        elif k in (curses.KEY_NPAGE, " "):
            self.scroll(h - 3)
        elif k == curses.KEY_PPAGE:
            self.scroll(-(h - 3))
        elif k in ("g", curses.KEY_HOME):
            self.follow, self.top = False, 0
        elif k in ("G", curses.KEY_END, "f"):
            self.follow = not self.follow if k == "f" else True
        elif k == "/":
            self.searching, self.query = True, ""
        elif k == "n":
            self.jump(self.top + 1)
        elif k == "s":
            self.src.stop()
            self.msg = "stopped"
        elif k == "r":
            self.rerun()
        elif k == curses.KEY_MOUSE:
            self.on_mouse()

    def jump(self, start=None):
        if not self.query:
            return
        j = find(self.vis, self.query, self.top if start is None else start)
        if j is None:
            self.msg = f"not found: {self.query}"
        else:
            self.follow, self.top, self.msg = False, j, f"found: {self.query}  (n for the next)"

    def on_mouse(self):
        try:
            _, x, y, _, b = curses.getmouse()
        except curses.error:
            return
        if b & curses.BUTTON4_PRESSED:
            self.scroll(-3)
        elif b & WHEEL_DOWN:
            self.scroll(3)
        elif b & CLICK:
            for ry, x0, x1, fn in self.regions:
                if ry == y and x0 <= x < x1:
                    fn()
                    return

    def loop(self):
        while True:
            self.draw()
            try:
                k = self.scr.get_wch()
            except curses.error:
                continue
            k = {"\n": 10, "\r": 10, "\x1b": 27, "\x7f": 127}.get(k, k) if isinstance(k, str) else k
            self.on_key(k)


def fit(text, w):
    out, used = "", 0
    for c in str(text).replace("\n", " ").replace("\t", " "):
        cw = ts.cells(c)
        if used + cw > w:
            break
        out, used = out + c, used + cw
    return out + " " * (w - used)


def usable_terminal(stream=None, environ=None):
    """True when a full-screen view can work: output to a terminal and a TERM curses knows."""
    stream = stream or sys.stdout
    env = os.environ if environ is None else environ
    try:
        tty = stream.isatty()
    except (AttributeError, ValueError):
        tty = False
    return tty and env.get("TERM", "") not in ("", "dumb", "unknown")


def transcript(src, title, out=None, on=None):
    """Print what the view showed onto the normal screen, then a closing line; the scrollback keeps it."""
    out = out or sys.stdout
    on = ts.color_on(out) if on is None else on
    lines = list(src.lines)
    out.write(ts.paint(f"── kit live: {title}", "1", on) + "\n")
    for ln in lines:
        out.write((ts.ansi(ln) if on else ts.ANSI.sub("", ln)) + "\n")
    state = src.state if src.code is not None else "stopped"
    out.write(f"── {state}, {len(lines)} line(s)\n")
    out.flush()


def plain(argv):
    """Run the command with its output straight to this terminal (no view); its exit code."""
    try:
        return subprocess.call(argv, stdin=subprocess.DEVNULL)
    except OSError as e:
        print(f"kit live: could not start {argv[0]}: {e}", file=sys.stderr)
        return 127


def run(argv=None, fd=None, title=None):
    """Show a command's output (argv) or a pipe's (fd) until the person quits, then print it plainly on the normal
    screen; returns the command's exit code."""
    title = title or (" ".join(argv) if argv else "piped output")
    if argv is not None and not usable_terminal():
        return plain(argv)
    src = Source(argv=argv, fd=fd)
    os.environ.setdefault("ESCDELAY", "25")
    opened = []

    def inner(scr):
        try:
            curses.curs_set(0)
        except curses.error:
            pass                         # some terminals cannot hide the cursor
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)
        curses.start_color()
        curses.use_default_colors()
        for i, (f, b) in enumerate(PAIRS, start=1):
            try:
                curses.init_pair(i, f if curses.COLORS > 16 else min(max(f, -1), 7),
                                 b if curses.COLORS > 16 or b < 0 else min(b, 7))
            except curses.error:
                pass
        scr.timeout(150)
        scr.idlok(False)
        scr.scrollok(False)
        scr.keypad(True)
        curses.flushinp()                # drop what was typed or pasted before the view opened
        src.start()
        opened.append(True)
        View(scr, src, title).loop()
    code = None
    try:
        curses.wrapper(inner)
    except SystemExit as e:
        code = e.code or 0
    except KeyboardInterrupt:
        code = 130
    except curses.error as e:
        if not opened and argv is not None:
            print(f"kit live: the full-screen view could not start ({e}); running plainly", file=sys.stderr)
            return plain(argv)
        print(f"kit live: the view failed ({e})", file=sys.stderr)
    src.stop()
    src.wait(2.0)
    transcript(src, title)
    if code == 130 or src.code is None or src.code < 0:
        return 130                       # interrupted, or stopped before it finished
    return src.code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv:
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        return run(argv=argv)
    if sys.stdin.isatty():
        print(__doc__.strip())
        return 2
    pipe = os.dup(0)
    try:
        tty = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        print("kit live needs a terminal to read keys from (/dev/tty)", file=sys.stderr)
        return 2
    os.dup2(tty, 0)
    return run(fd=pipe)


if __name__ == "__main__":
    sys.exit(main())
