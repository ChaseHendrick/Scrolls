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
  {"frames": N, "every": MS}            N frames, MS milliseconds apart (pages that run in real time)
  {"tween": {"selector": S, "from": A, "to": B, "n": N}}
                                        move a slider from A to B, one frame per step
  {"step": {"js": "seek({t})", "n": N}} frame-stepped time: for t from 0 to 1 in N steps, run the JavaScript with
                                        {t} replaced, wait two animation frames, take a frame

Frame-stepping gives a smooth clip whatever the renderer's speed. Encode the frames with encode.py. It never downloads
a browser: it uses --browser, $CHROMIUM_PATH, Playwright's own Chromium, or a system chromium, in that order. Needs the
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
             "frames", "every", "tween", "step"}


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
            every = step.get("every", 100) / 1000
            for _ in range(int(step["frames"])):
                t0 = time.monotonic()
                rec.frame()
                left = every - (time.monotonic() - t0)
                if left > 0:
                    time.sleep(left)
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
        if "step" in step:
            st = step["step"]
            n = int(st.get("n", 60))
            for i in range(n):
                t = i / max(n - 1, 1)
                page.evaluate(st["js"].replace("{t}", repr(round(t, 6))))
                page.evaluate(RAF2)
                rec.frame()


def capture(page_or_url, out_dir, actions, width=1280, height=800, scale=1.0, scheme="dark", browser=None,
            timeout=60000):
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
                b = pw.chromium.launch(executable_path=t) if t else pw.chromium.launch()
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
    args = p.parse_args(argv)
    try:
        actions = json.loads(Path(args.actions).read_text(encoding="utf-8")) if args.actions else [{"shot": "page"}]
        result = capture(args.page, args.out_dir, actions, args.width, args.height, args.scale, args.scheme,
                         args.browser, args.timeout)
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
