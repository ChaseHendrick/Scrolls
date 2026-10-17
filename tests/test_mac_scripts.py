"""The Mac scripts' own logic, run off a Mac with stubs for git, uv and the venv's Python (no GPU, no network)."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STUB_PY = r"""#!/bin/bash
# Stands in for WORK/venv/bin/python: kit verify answers $STUB_VERDICT, inference records the fallback setting.
case "$1 $2" in
  "-m kit")
    if [ "$3" = verify ]; then
      echo "{\"verdict\": \"$STUB_VERDICT\", \"candidate\": {\"max_abs_diff\": 0.5, \"fraction_over_tolerance\": 0.2,
             \"pearson\": 0.3}, \"control\": {\"fraction_over_tolerance\": 0.9}}"
      [ "$STUB_VERDICT" = pass ] && exit 0
      exit 1
    fi
    exit 0 ;;
  "-m vesuvius.ink_detection.inference.infer")
    echo "${PYTORCH_ENABLE_MPS_FALLBACK-unset}" >> "$STUB_RUNS"
    echo "Using MPS device"
    exit 0 ;;
  "-c "*) echo "0.0 mps available: False"; exit 0 ;;
  "- "*pyproject.toml) cat > /dev/null; echo torch; exit 0 ;;   # the requirements step uses tomllib (3.11+)
esac
exec python3 "$@"
"""


@unittest.skipIf(shutil.which("bash") is None or shutil.which("python3") is None, "needs bash and python3")
class MacVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.work = t / "work"
        (self.work / "villa" / ".git").mkdir(parents=True)
        (self.work / "villa" / "vesuvius").mkdir()
        (self.work / "villa" / "vesuvius" / "pyproject.toml").write_text(
            '[project.optional-dependencies]\nmodels = ["torch"]\n')
        ckpt = self.work / "checkpoints" / "ink_9um" / "hybrid_3d2d-seed42" / "step-075000.pth"
        ckpt.parent.mkdir(parents=True)
        ckpt.write_bytes(b"weights")
        py = self.work / "venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text(STUB_PY)
        py.chmod(0o755)
        self.bin = t / "bin"
        self.bin.mkdir()
        for name, body in (("git", 'case "$*" in *rev-parse*) echo abc1234 ;; esac\nexit 0\n'),
                           ("uv", "exit 0\n"), ("uvx", "exit 0\n")):
            (self.bin / name).write_text("#!/bin/bash\n" + body)
            (self.bin / name).chmod(0o755)
        self.runs = t / "runs"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, verdict="pass", **env):
        env = dict(os.environ, EXPECT_GPU="cpu", WORK=str(self.work), PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                   STUB_VERDICT=verdict, STUB_RUNS=str(self.runs), **env)
        return subprocess.run(["bash", str(ROOT / "scripts" / "mac-verify.sh")], env=env, capture_output=True,
                              text=True, timeout=120)

    def test_failing_verdict_fails_the_script(self):
        r = self.run_script("pass")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("cpu_vs_gpu: verdict pass (exit 0)", r.stdout)
        r = self.run_script("fail")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("cpu_vs_gpu: verdict fail (exit 1)", r.stdout)   # the summary still prints in full

    def test_mps_fallback_is_off_for_every_inference(self):
        r = self.run_script("pass", PYTORCH_ENABLE_MPS_FALLBACK="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.runs.read_text().split(), ["unset"] * 3)

    def test_shares_the_gpu_lock_with_mac_w045(self):
        lock = self.work / ".gpu-job.lock"
        lock.mkdir()
        (lock / "pid").write_text(str(os.getpid()))   # a live process holds it
        r = self.run_script("pass")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("Another run is using the GPU", r.stderr)
        self.assertFalse(self.runs.exists())
        (lock / "pid").write_text("")   # a lock with no live process is taken over, and removed at the end
        r = self.run_script("pass")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(lock.exists())



@unittest.skipIf(shutil.which("bash") is None or shutil.which("python3") is None, "needs bash and python3")
class MacPhase0Test(unittest.TestCase):
    def dry_run(self, jobs):
        with tempfile.TemporaryDirectory() as work:
            env = dict(os.environ, WORK=work, JOBS=jobs, DRY_RUN="1")
            return subprocess.run(["bash", str(ROOT / "scripts" / "mac-phase0.sh")], env=env, capture_output=True,
                                  text=True, timeout=120)

    def test_refuses_the_segments_mac_w045_refuses(self):
        r = self.dry_run("v8in:0841-w00")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would run MODEL=v8in SEGMENT=0841-w00", r.stdout)
        for job in ("v8in:0841-w01", "v8in-1447:0841-ag"):
            r = self.dry_run(f"v8in:0841-w00 {job}")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn(f"unknown job {job}", r.stderr)
            self.assertNotIn("would run", r.stdout)


if __name__ == "__main__":
    unittest.main()
