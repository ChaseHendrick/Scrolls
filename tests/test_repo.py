"""Repository checks that run with the unit tests, so CI catches them on every push.

- every shell script parses (bash -n);
- the Mac scripts use nothing newer than bash 3.2, which is what macOS ships;
- no em or en dashes in tracked text (house style);
- every JSON file under docs/ parses;
- every `python -m kit <command>` written in the docs and scripts is a real subcommand.
- no live file calls PHerc0139 w045 held out from `ink_9um` (it trained on w045's 2.4 um render).
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from kit import cli

ROOT = Path(__file__).resolve().parent.parent
TEXT = (".md", ".py", ".sh", ".txt", ".json", ".yml", ".yaml", ".toml")
# Dated logs, evidence and experiment records keep their original wording; the correction is
# docs/logs/2026-10-08-w045-not-held-out.md.
HISTORICAL = ("docs/logs/", "docs/evidence/", "scripts/experiments/")
W045_HELD_OUT = re.compile(r"(?<!not )held[ -]out from `?ink_9um|held out from both models")
# Bash 4+ features macOS's /bin/bash 3.2 lacks.
BASH4 = [
    (re.compile(r"\bdeclare\s+-[a-zA-Z]*A"), "associative arrays (declare -A)"),
    (re.compile(r"\b(mapfile|readarray)\b"), "mapfile/readarray"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z_0-9]*(,,|\^\^|,|\^)\}"), "case conversion ${x,,}"),
    (re.compile(r"&>>"), "&>> redirection"),
    (re.compile(r"\|&"), "|& pipe"),
    (re.compile(r"\bcoproc\b"), "coproc"),
    (re.compile(r"\$\{[A-Za-z_][A-Za-z_0-9]*\[-1\]\}"), "negative array index"),
]


def tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [ROOT / f for f in out.split("\n") if f]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def code_lines(path):
    """Lines of a shell script outside heredoc bodies (they hold Python, not bash)."""
    lines, end = [], None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_]+)['\"]?", line)
        if m:
            end = m.group(1)
        if not line.lstrip().startswith("#"):
            lines.append((n, line))
    return lines


class RepoTest(unittest.TestCase):
    def test_shell_scripts_parse(self):
        # Public labelled-control entry points remain runnable after private
        # operational runners move to the private repository.
        for name in ("mac-w045.sh", "mac-phase0.sh", "mac-verify.sh"):
            self.assertTrue((ROOT / "scripts" / name).is_file(), name)
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("no bash")
        for f in sorted((ROOT / "scripts").glob("*.sh")):
            r = subprocess.run([bash, "-n", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{f.name}: {r.stderr}")

    def test_mac_scripts_are_bash_32(self):
        for f in sorted((ROOT / "scripts").glob("mac-*.sh")):
            for n, line in code_lines(f):
                for pattern, what in BASH4:
                    self.assertIsNone(pattern.search(line), f"{f.name}:{n} uses {what}, which macOS bash 3.2 lacks")

    def test_no_long_dashes(self):
        for f in tracked():
            if f.suffix not in TEXT or not f.exists():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            for ch, name in ((chr(0x2014), "em dash"), (chr(0x2013), "en dash")):
                self.assertFalse(ch in text, f"{f.relative_to(ROOT)} has an {name}")

    def test_docs_json_parses(self):
        for f in sorted((ROOT / "docs").rglob("*.json")):
            json.loads(f.read_text(encoding="utf-8"))

    def test_documented_kit_commands_exist(self):
        parser = cli.build_parser()
        commands = set(next(a for a in parser._actions if a.dest == "command").choices)
        seen = {}
        for f in tracked():
            if f.suffix in (".md", ".sh", ".txt", ".py") and f.exists():
                for m in re.finditer(r"python3? -m kit ([a-z]+)", f.read_text(encoding="utf-8", errors="replace")):
                    seen.setdefault(m.group(1), str(f.relative_to(ROOT)))
        missing = {c: where for c, where in seen.items() if c not in commands}
        self.assertEqual(missing, {}, f"documented but not in kit: {missing}")

    def test_w045_is_not_called_held_out_from_ink_9um(self):
        # The ink_9um label dataset trains on w045's 2.399 um render (its segment pherc0139-w029).
        for f in tracked():
            rel = f.relative_to(ROOT).as_posix()
            if f.suffix not in TEXT or not f.exists() or rel.startswith(HISTORICAL) or rel == "tests/test_repo.py":
                continue
            m = W045_HELD_OUT.search(f.read_text(encoding="utf-8", errors="replace"))
            self.assertIsNone(m, f"{rel} says {m.group(0)!r}" if m else "")
        held_out = json.loads((ROOT / "docs" / "results.json").read_text(encoding="utf-8"))["held_out"]
        self.assertTrue(held_out["w045"].startswith("held out from v8in only"), held_out["w045"])


if __name__ == "__main__":
    unittest.main()
