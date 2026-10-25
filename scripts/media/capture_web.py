#!/usr/bin/env python3
"""Capture a web page as frames or screenshots with headless Chromium, stepping time instead of recording it.

    python scripts/media/capture_web.py PAGE --out-dir FRAMES --actions ACTIONS.json [--width 1280 --height 800]
    python scripts/media/capture_web.py http://127.0.0.1:8765/ --out-dir shots --actions shots.json --scale 2

PAGE is a URL or a local HTML file. ACTIONS.json is a list of steps, run in order:

  {"goto": URL}                         open URL, retrying for up to 60 s until a server answers (start the browser
                                        before a short live run, then the server)
  {"wait": MS}                          wait MS milliseconds
  {"wait_for": SELECTOR}                wait until the element is visible
  {"click": SELECTOR}                   click it
  {"fill": [SELECTOR, TEXT]}            type into an input
  {"press": KEY}                        press a key, such as "Tab" or "Enter"
  {"eval": JS}                          run JavaScript in the page
  {"set": [SELECTOR, VALUE]}            set an input's value and fire its input and change events (sliders)
  {"scroll": [X, Y]}                    scroll the window
  {"clip": SELECTOR or null}            limit later frames and shots to that element's box (null: the viewport)
  {"shot": NAME}                        one screenshot, NAME.png, in the out folder
  {"frame": 1}                          one numbered frame (frame-00000.png, frame-00001.png, ...)
  {"hold": N}                           repeat the last frame N times (a pause in the clip)
  {"frames": N, "every": MS}            N frames, MS milliseconds of wall clock apart (pages that run in real time):
                                        screenshots as fast as possible, then each frame is the last one taken by
                                        its time, so a slow machine repeats frames instead of stretching the clip
  {"tween": {"selector": S, "from": A, "to": B, "n": N}}
                                        move a slider from A to B, one frame per step
  {"step": {"js": "seek({t})", "n": N}} frame-stepped time: for t from 0 to 1 in N steps, run the JavaScript with
                                        {t} replaced, wait two animation frames, take a frame
  {"cursor": "show" or "hide"}          draw a pointer in the palette (headless Chromium draws none)
  {"point": {"selector": S, "n": N}}    move the pointer to S, eased, one frame per step
  {"tap": {"selector": S, "n": N}}      click S and draw a copper ring growing from the pointer over N frames
  {"glide": {"selector": S, "from": A, "to": B, "n": N}}
                                        a tween whose pointer follows the slider's thumb
  {"scrollto": {"selector": S, "offset": PX, "n": N}}
                                        scroll smoothly until S's top is PX below the window's top, one frame per step

Frame-stepping gives a smooth clip whatever the renderer's speed. Encode the frames with encode.py. The out folder may
not be under docs/assets/: raw frames carry no media label, so they stay in a scratch folder. It never downloads
a browser: it uses --browser, $CHROMIUM_PATH, Playwright's own Chromium, or a system chromium, in that order. --webgl
turns on software WebGL for 3D pages, and remote pages go through $HTTPS_PROXY when it is set. Needs the
playwright Python package (pip install playwright; set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 where a browser exists).
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

CANDIDATES = ("/opt/pw-browsers/chromium", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium")
STEP_KEYS = {"goto", "wait", "wait_for", "click", "fill", "press", "eval", "set", "scroll", "clip", "shot", "frame", "hold",
             "frames", "every", "tween", "step", "cursor", "point", "tap", "glide", "scrollto"}
EASE = "function(t){return t<.5?2*t*t:1-Math.pow(-2*t+2,2)/2;}"
# A drawn pointer and click ring in the palette, so a clip shows where each interaction happens. Headless Chromium
# draws no system cursor; this one lives in the page as two fixed elements that ignore pointer events.
CURSOR_JS = """() => { if (window.__mediaCursor) return; const ease = """ + EASE + """;
  const c = document.createElement('div'); c.style.cssText = 'position:fixed;left:0;top:0;width:24px;height:24px;' +
    'z-index:2147483647;pointer-events:none;will-change:transform';
  c.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M3 2 L3 19 L7.6 14.8 L10.8 21.6 L13.7 20.3 ' +
    'L10.6 13.6 L16.8 13.6 Z" fill="#EEE7D9" stroke="#171A1C" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const r = document.createElement('div'); r.style.cssText = 'position:fixed;left:0;top:0;width:46px;height:46px;' +
    'margin:-23px 0 0 -23px;border:3px solid #B77A54;border-radius:50%;z-index:2147483646;pointer-events:none;opacity:0';
  document.body.append(r, c);
  let x = innerWidth * 0.55, y = innerHeight * 0.6, sx = x, sy = y;
  const place = () => { c.style.transform = `translate(${x - 3}px,${y - 2}px)`; };
  const center = (sel) => { const e = document.querySelector(sel); if (!e) throw new Error('no ' + sel);
    const b = e.getBoundingClientRect(); return [b.left + Math.min(b.width / 2, 80), b.top + b.height / 2]; };
  window.__mediaCursor = {
    show(on) { c.style.opacity = on ? '1' : '0'; if (!on) r.style.opacity = '0'; },
    point(sel, t) { if (t === 0) { sx = x; sy = y; } const [tx, ty] = center(sel), e = ease(t);
      x = sx + (tx - sx) * e; y = sy + (ty - sy) * e; place(); },
    ring(t) { r.style.left = x + 'px'; r.style.top = y + 'px'; r.style.opacity = String(Math.max(0, 1 - t));
      r.style.transform = `scale(${0.35 + 1.15 * t})`; },
    thumb(sel, value) { const e = document.querySelector(sel), b = e.getBoundingClientRect();
      const lo = +e.min || 0, hi = +e.max || 100, k = (value - lo) / (hi - lo);
      x = b.left + 8 + k * (b.width - 16); y = b.top + b.height / 2; place(); },
    scrollTo(sel, offset, t) { if (t === 0) { this.s0 = scrollY;
        this.s1 = document.querySelector(sel).getBoundingClientRect().top + scrollY - offset; }
      scrollTo(0, this.s0 + (this.s1 - this.s0) * ease(t)); } };
  place(); }"""


class CaptureError(ValueError):
    pass


def check_actions(actions):
    if not isinstance(actions, list):
        raise CaptureError("actions must be a JSON list of steps")
    for i, step in enumerate(actions):
        if not isinstance(step, dict) or not step or set(step) - STEP_KEYS:
            raise CaptureError(f"step {i}: unknown or empty step {step!r}")
        if "every" in step and "frames" not in step:
            raise CaptureError(f"step {i}: every goes with frames")
    return actions


def page_url(page):
    page = str(page)
    if "://" in page or page == "about:blank":
        return page
    p = Path(page).expanduser().resolve()
    if not p.is_file():
        raise CaptureError(f"no such page: {page}")
    return p.as_uri()


def find_browser(explicit=None):
    for c in ([explicit] if explicit else []) + [os.environ.get("CHROMIUM_PATH")]:
        if c:
            return c
    return None


def fallback_browsers():
    out = []
    for c in CANDIDATES:
        path = c if os.path.isabs(c) else shutil.which(c)
        if path and os.path.exists(path):
            out.append(path)
    return out


def pick_timed(times, n, every):
    """For output frames at 0, every, 2 * every, ... (n of them), the index of the last screenshot taken at or before
    each time (the first one before any was taken). times are seconds since the first screenshot, ascending."""
    out, j = [], 0
    for k in range(n):
        target = k * every
        while j + 1 < len(times) and times[j + 1] <= target:
            j += 1
        out.append(j)
    return out


class Recorder:
    def __init__(self, page, out_dir):
        self.page, self.out = page, Path(out_dir)
        self.n, self.clip, self.last = 0, None, None
        self.shots = []

    def _box(self):
        if not self.clip:
            return None
        box = self.page.locator(self.clip).first.bounding_box()
        if not box:
            raise CaptureError(f"clip element {self.clip!r} has no box")
        return box

    def frame(self):
        path = self.out / f"frame-{self.n:05d}.png"
        self.page.screenshot(path=str(path), clip=self._box(), animations="disabled", caret="hide")
        self.n += 1
        self.last = path
        return path

    def timed(self, n, every):
        """n frames of a page that runs in real time, one per `every` seconds of wall clock. Screenshots are taken as
        fast as the machine allows for n * every seconds, then each output frame is the last screenshot taken at or
        before its time, so a slow machine repeats frames instead of slowing the clip down."""
        tmp = self.out / ".timed"
        tmp.mkdir(exist_ok=True)
        shots, t0 = [], time.monotonic()
        while True:
            t = time.monotonic() - t0
            path = tmp / f"{len(shots):05d}.png"
            self.page.screenshot(path=str(path), clip=self._box(), animations="disabled", caret="hide")
            shots.append((t, path))
            if t >= n * every:
                break
        for i in pick_timed([t for t, _ in shots], n, every):
            path = self.out / f"frame-{self.n:05d}.png"
            shutil.copyfile(shots[i][1], path)
            self.n += 1
            self.last = path
        shutil.rmtree(tmp)

    def hold(self, count):
        if self.last is None:
            raise CaptureError("hold needs an earlier frame")
        for _ in range(count):
            path = self.out / f"frame-{self.n:05d}.png"
            shutil.copyfile(self.last, path)
            self.n += 1

    def shot(self, name):
        path = self.out / (name if name.endswith(".png") else f"{name}.png")
        self.page.screenshot(path=str(path), clip=self._box(), animations="disabled", caret="hide")
        self.shots.append(str(path))


SETTER = """([sel, value]) => { const el = document.querySelector(sel); if (!el) throw new Error('no ' + sel);
  const proto = Object.getPrototypeOf(el); const d = Object.getOwnPropertyDescriptor(proto, 'value');
  d.set.call(el, String(value)); el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true})); }"""
RAF2 = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"


def goto_retry(page, url, limit=60.0):
    t0 = time.monotonic()
    while True:
        try:
            page.goto(url, wait_until="load")
            return
        except Exception as exc:   # connection refused while the server starts
            if time.monotonic() - t0 > limit:
                raise CaptureError(f"{url} did not answer within {limit:.0f} s: {str(exc).splitlines()[0]}") from None
            time.sleep(0.1)


def run_actions(page, rec, actions):
    for step in actions:
        if "goto" in step:
            goto_retry(page, step["goto"])
        if "wait" in step:
            page.wait_for_timeout(step["wait"])
        if "wait_for" in step:
            page.locator(step["wait_for"]).first.wait_for(state="visible", timeout=30000)
        if "click" in step:
            page.locator(step["click"]).first.click()
        if "fill" in step:
            page.locator(step["fill"][0]).first.fill(step["fill"][1])
        if "press" in step:
            page.keyboard.press(step["press"])
        if "eval" in step:
            page.evaluate(step["eval"])
        if "set" in step:
            page.evaluate(SETTER, step["set"])
        if "scroll" in step:
            page.evaluate("([x, y]) => window.scrollTo(x, y)", step["scroll"])
        if "clip" in step:
            rec.clip = step["clip"]
        if "shot" in step:
            page.evaluate(RAF2)
            rec.shot(step["shot"])
        if "frame" in step:
            page.evaluate(RAF2)
            for _ in range(int(step["frame"])):
                rec.frame()
        if "hold" in step:
            rec.hold(int(step["hold"]))
        if "frames" in step:
            rec.timed(int(step["frames"]), step.get("every", 100) / 1000)
        if "tween" in step:
            tw = step["tween"]
            n = int(tw.get("n", 30))
            for i in range(n):
                value = tw["from"] + (tw["to"] - tw["from"]) * i / max(n - 1, 1)
                if isinstance(tw["from"], int) and isinstance(tw["to"], int):
                    value = round(value)
                page.evaluate(SETTER, [tw["selector"], value])
                page.evaluate(RAF2)
                rec.frame()
        if "cursor" in step:
            page.evaluate(CURSOR_JS)
            page.evaluate("(on) => window.__mediaCursor.show(on)", step["cursor"] != "hide")
        if "point" in step:
            pt = step["point"]
            n = int(pt.get("n", 10))
            for i in range(n):
                page.evaluate("([s, t]) => window.__mediaCursor.point(s, t)", [pt["selector"], i / max(n - 1, 1)])
                page.evaluate(RAF2)
                rec.frame()
        if "tap" in step:
            tp = step["tap"]
            page.locator(tp["selector"]).first.click()
            n = int(tp.get("n", 6))
            for i in range(n):
                page.evaluate("(t) => window.__mediaCursor.ring(t)", i / max(n - 1, 1))
                page.evaluate(RAF2)
                rec.frame()
        if "glide" in step:
            gl = step["glide"]
            n = int(gl.get("n", 30))
            for i in range(n):
                value = gl["from"] + (gl["to"] - gl["from"]) * i / max(n - 1, 1)
                if isinstance(gl["from"], int) and isinstance(gl["to"], int):
                    value = round(value)
                page.evaluate(SETTER, [gl["selector"], value])
                page.evaluate("([s, v]) => window.__mediaCursor && window.__mediaCursor.thumb(s, v)",
                              [gl["selector"], value])
                page.evaluate(RAF2)
                rec.frame()
        if "scrollto" in step:
            sc = step["scrollto"]
            n = int(sc.get("n", 12))
            page.evaluate(CURSOR_JS)
            for i in range(n):
                page.evaluate("([s, o, t]) => window.__mediaCursor.scrollTo(s, o, t)",
                              [sc["selector"], sc.get("offset", 16), i / max(n - 1, 1)])
                page.evaluate(RAF2)
                rec.frame()
        if "step" in step:
            st = step["step"]
            n = int(st.get("n", 60))
            for i in range(n):
                t = i / max(n - 1, 1)
                page.evaluate(st["js"].replace("{t}", repr(round(t, 6))))
                page.evaluate(RAF2)
                rec.frame()


WEBGL_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def launch_options(webgl=False):
    """Chromium launch options: software WebGL when asked (headless machines have no GPU), and $HTTPS_PROXY for remote
    pages when one is set, with local servers reached directly."""
    opts = {"args": list(WEBGL_ARGS)} if webgl else {}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        opts["proxy"] = {"server": proxy, "bypass": "127.0.0.1,localhost"}
    return opts


def capture(page_or_url, out_dir, actions, width=1280, height=800, scale=1.0, scheme="dark", browser=None,
            timeout=60000, webgl=False):
    out = Path(out_dir)
    parts = out.resolve().parts
    if any(parts[i:i + 2] == ("docs", "assets") for i in range(len(parts) - 1)):
        raise CaptureError("capture into a scratch folder, not docs/assets/: raw frames carry no label; encode.py "
                           "--meta or hero.py writes the labeled result there")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise CaptureError("the playwright package is missing: pip install playwright "
                           "(with PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 where a Chromium is installed)") from None
    url = page_url(page_or_url)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    check_actions(actions)
    with sync_playwright() as pw:
        exe = find_browser(browser)
        tries = [exe] if exe else [None] + fallback_browsers()
        b, last_err = None, None
        for t in tries:
            try:
                opts = launch_options(webgl)
                b = pw.chromium.launch(executable_path=t, **opts) if t else pw.chromium.launch(**opts)
                break
            except PlaywrightError as exc:
                last_err = exc
        if b is None:
            raise CaptureError(f"no Chromium could start (give --browser PATH): {str(last_err).splitlines()[0]}")
        try:
            ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale,
                                color_scheme=scheme, reduced_motion="reduce")
            page = ctx.new_page()
            page.set_default_timeout(timeout)
            page.goto(url, wait_until="load")
            rec = Recorder(page, out)
            run_actions(page, rec, actions)
            return {"url": url, "frames": rec.n, "shots": rec.shots, "out_dir": str(out), "width": width,
                    "height": height, "scale": scale}
        finally:
            b.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="python scripts/media/capture_web.py", description=__doc__.split("\n")[0])
    p.add_argument("page", help="a URL, or a local HTML file")
    p.add_argument("--out-dir", required=True, help="folder for frame-NNNNN.png frames and named shots")
    p.add_argument("--actions", help="JSON list of steps (default: one shot named page.png)")
    p.add_argument("--width", type=int, default=1280, help="viewport width in CSS pixels (default 1280)")
    p.add_argument("--height", type=int, default=800, help="viewport height in CSS pixels (default 800)")
    p.add_argument("--scale", type=float, default=1.0, help="device pixel ratio; 2 for sharp stills (default 1)")
    p.add_argument("--scheme", choices=("dark", "light"), default="dark", help="prefers-color-scheme (default dark)")
    p.add_argument("--browser", help="Chromium executable (default: $CHROMIUM_PATH, Playwright's, then a system one)")
    p.add_argument("--timeout", type=int, default=60000, help="per-action timeout in milliseconds (default 60000)")
    p.add_argument("--webgl", action="store_true", help="software WebGL (SwiftShader) for 3D pages such as Neuroglancer")
    args = p.parse_args(argv)
    try:
        actions = json.loads(Path(args.actions).read_text(encoding="utf-8")) if args.actions else [{"shot": "page"}]
        result = capture(args.page, args.out_dir, actions, args.width, args.height, args.scale, args.scheme,
                         args.browser, args.timeout, args.webgl)
        print(json.dumps(result))
        return 0
    except (CaptureError, OSError, ValueError) as exc:
        print(f"capture_web: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:   # Playwright's own errors: a selector that never appears, a page that will not load
        print(f"capture_web: {type(exc).__name__}: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
