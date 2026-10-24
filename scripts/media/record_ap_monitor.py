#!/usr/bin/env python3
"""Record AutoPipeline's monitor on the synthetic demo: a paced live run, then a captioned walk through every panel.

    python scripts/media/record_ap_monitor.py --package AP_FOLDER --frames FRAMES [--pace 1.2] [--port 8793]

AP_FOLDER is an AutoPipeline release folder (it holds kit/, tests/ and scripts/demo_synthetic.py). The recorder starts
scripts/media/capture_web.py with captures/autopipeline-walkthrough.json, then runs the package's synthetic demo in
this process with each stage held PACE seconds before it starts (the demo alone takes a few seconds, too fast to
watch), and serves the package's monitor on PORT with the console on, as its own monitor command
does. The run, the kit home of the console's jobs and notes, and the frames stay in scratch folders; encode the
frames with encode.py. Everything shown is the demo's stand-in tools and stand-in ink model on a synthetic scroll.
"""

import argparse
import functools
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--package", required=True, help="an AutoPipeline release folder")
    ap.add_argument("--frames", required=True, help="scratch folder for the frames")
    ap.add_argument("--actions", default=str(HERE / "captures" / "autopipeline-walkthrough.json"))
    ap.add_argument("--pace", type=float, default=1.2, help="seconds each stage waits before it starts")
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--width", type=int, default=1512)
    ap.add_argument("--height", type=int, default=904)
    ap.add_argument("--work", help="scratch folder for the run and the console's kit home (default: a new temp folder)")
    a = ap.parse_args(argv)
    pkg = Path(a.package).resolve()
    work = Path(tempfile.mkdtemp(prefix="ap-monitor-demo-", dir=a.work))
    os.environ["KIT_HOME"] = str(work / "kit-home")      # the console's jobs and notes, never the user's kit home
    sys.path[:0] = [str(pkg), str(pkg / "tests"), str(pkg / "scripts")]
    import demo_synthetic                                # noqa: E402 (from the package)
    from kit import autopipe, vc3d_agent                 # noqa: E402
    from kit import autopipe_monitor as mon              # noqa: E402

    cap = subprocess.Popen([sys.executable, str(HERE / "capture_web.py"), "about:blank", "--out-dir", a.frames,
                            "--actions", a.actions, "--width", str(a.width), "--height", str(a.height)])
    served = {}

    def paced(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kw):
            time.sleep(a.pace)
            return fn(self, *args, **kw)
        return wrapper

    for stage in autopipe.STAGES:
        setattr(autopipe.Run, f"s_{stage}", paced(getattr(autopipe.Run, f"s_{stage}")))
    start = autopipe.Run.run

    def run(self, *args, **kw):         # the monitor comes up on plan.json, before the first stage
        ctx = vc3d_agent.Context()
        served["ctx"] = ctx
        served["mon"] = mon.serve(self.out, port=a.port, thumbs="on", ctx=ctx).start()
        time.sleep(3.0)                 # the browser finds the page and draws the empty run
        return start(self, *args, **kw)

    autopipe.Run.run = run
    try:
        code = demo_synthetic.main(["--out", str(work / "demo")])
        if code:
            raise SystemExit(f"the synthetic demo failed (exit {code}); the run is in {work / 'demo'}")
        cap.wait(timeout=1800)
    finally:
        if cap.poll() is None:
            cap.kill()
        if "mon" in served:
            served["mon"].stop(0)
            served["ctx"].close()
    print(f"frames in {a.frames}; run and kit home in {work}")
    return cap.returncode


if __name__ == "__main__":
    sys.exit(main())
