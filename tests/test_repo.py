"""Repository checks that run with the unit tests, so CI catches them on every push.

- every shell script parses (bash -n);
- the Mac scripts use nothing newer than bash 3.2, which is what macOS ships;
- no em or en dashes in tracked text (house style);
- every JSON file under docs/ parses;
- every `python -m kit <command>` written in the docs and scripts is a real subcommand.
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
            for ch, name in (("—", "em dash"), ("–", "en dash")):
                self.assertNotIn(ch, text, f"{f.relative_to(ROOT)} has an {name}")

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


if __name__ == "__main__":
    unittest.main()
