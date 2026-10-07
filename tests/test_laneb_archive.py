"""Keep the known-uncorrected historical launcher from running as a new experiment."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/experiments/2026-10-07-grok-laneB/run_mac.sh"


class LaneBArchive(unittest.TestCase):
    def test_historical_launcher_refuses_before_accessing_data_or_running_python(self):
        with tempfile.TemporaryDirectory() as temp:
            task_env = dict(os.environ)
            task_env.pop("SCROLLS_RUN_HISTORICAL_LANEB", None)
            # Exercise the launcher's actual guard, replacing the historical payload
            # with a sentinel so a missing guard cannot start a real data analysis.
            guard = LAUNCHER.read_text().split("set -o pipefail", 1)[0]
            run = subprocess.run(["bash"], input=guard + "exit 97\n", cwd=temp, env=task_env,
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 2)
            self.assertIn("Archival launcher only", run.stderr)
            self.assertIn("SCROLLS_RUN_HISTORICAL_LANEB=1", run.stderr)
            self.assertEqual(run.stdout, "")
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
