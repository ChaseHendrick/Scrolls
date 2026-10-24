"""Repository checks that run with the unit tests, so CI catches them on every push.

- every shell script parses (bash -n);
- the Mac scripts use nothing newer than bash 3.2, which is what macOS ships;
- no em or en dashes in tracked text (house style);
- every JSON file under docs/ parses;
- every `python -m kit <command>` written in the docs and scripts is a real subcommand.
- no live file calls PHerc0139 w045 held out from `ink_9um` (it trained on w045's 2.4 um render).
- no live file says no candidate or released reader trained on PHerc0841 without naming Hecate,
  whose base model's committed trainer lists all three PHerc0841 segments;
- no tracked file outside docs/vesuvius-bible/ links a Discord message (the archive stays private);
- every `kit/*.py` module has a row in the repository map, docs/MAP.md;
- AGENTS.md and docs/HANDOFF.md stay short, since every agent reads them first;
- every relative link in live Markdown resolves to a tracked file or directory;
- every file under docs/assets/ has a row in docs/assets/README.md with its size, bytes, media label and license
  and is named by a sidecar JSON with the same label, and every sidecar passes the public media rule
  (docs/media/README.md, scripts/media/common.py public_problems): Concept illustration, Synthetic demo, or a Real
  data render of a public scan that is not prize-eligible and shows no held-out labels, never model output; every
  file at most 1920 px wide and 4 MB; heroes (*-hero.webp) exactly 1920 x 640 and at most 300 KB;
- pictures and clips are tracked only under docs/assets/ (with a row and a sidecar) or docs/images/ (interface
  screenshots that show no scan data), at most 1920 px wide and 4 MB.
"""

import json
import re
import shutil
import struct
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

from kit import cli

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "media"))

import common as media  # noqa: E402  (scripts/media/common.py: the public media rule, standard library only)
TEXT = (".md", ".py", ".sh", ".txt", ".json", ".yml", ".yaml", ".toml")
# Dated logs, evidence and experiment records keep their original wording; the correction is
# docs/logs/2026-10-08-w045-not-held-out.md.
HISTORICAL = ("docs/logs/", "docs/evidence/", "scripts/experiments/")
# Preregistrations whose bytes a published run recorded by SHA-256 (its results.json provenance):
# published verbatim, so the wording and link checks leave them as they were frozen.
FROZEN = ("docs/prereg/2026-10-14-strokenet.md", "docs/prereg/2026-10-14-gridpilot.md")
W045_HELD_OUT = re.compile(r"(?<!not )held[ -]out from `?ink_9um|held out from both models")
# PHerc0841 is held out from ink_9um, v8in, d9v2 and Reader v2, but not from Hecate, whose
# base model's committed trainer lists w00, ag896 and ag405; docs/logs/2026-10-16-reader-exposure.md.
PHERC0841_HELD_OUT = re.compile(
    r"no candidate'?s training|in no candidate'?s|no (?:released )?(?:reader|model)s? (?:has |have |was |were |ever )*trained on"
    r"|no released reader'?s training", re.I)
# Discord messages are archived in Scrolls-private only, and its rule is that no message, name or link
# goes into public Scrolls; a public note cites a message the anonymous way, by channel and date
# (docs/logs/2026-10-14-upright-before-ink.md). The bible's prize table keeps the award posts' links.
DISCORD_MESSAGE = re.compile(r"discord(?:app)?\.com/channels/\d+/\d+/\d+")
DISCORD_ALLOWED = ("docs/vesuvius-bible/",)
MD_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
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


# docs/assets/: media labels and the public media rule (docs/media/README.md, scripts/media/common.py) and size
# limits. Model output of any scroll and renders of prize-eligible scrolls live in Scrolls-private's docs/media/.
ASSET_ROW = re.compile(r"^\| \[`([^`]+)`\]\(([^)]+)\) \| ([^|]+) \| ([0-9,]+) \| ([^|]+) \| ([^|]+) \|")
HERO_MAX_BYTES = 300_000
# Picture and clip files: tracked only in these folders (docs/images/ holds interface screenshots, used as hero inputs).
MEDIA_SUFFIXES = (".png", ".gif", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov", ".avif", ".tif", ".tiff", ".bmp")
MEDIA_DIRS = ("docs/assets/", "docs/images/")


def asset_rows():
    """{path under docs/assets/: (size, bytes, label, license)} from docs/assets/README.md's tables."""
    rows = {}
    for line in (ROOT / "docs" / "assets" / "README.md").read_text(encoding="utf-8").splitlines():
        m = ASSET_ROW.match(line)
        if m:
            rows[m.group(2)] = (m.group(3).strip(), int(m.group(4).replace(",", "")), m.group(5).strip(),
                                m.group(6).strip())
    return rows


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
        # Public labeled-control entry points remain runnable after private
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
                for m in re.finditer(r"python3? -m kit ([a-z][a-z0-9]*)", f.read_text(encoding="utf-8", errors="replace")):
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

    def test_pherc0841_held_out_wording_names_hecate(self):
        # A line saying no candidate or released reader trained on PHerc0841 must name Hecate on
        # that line or the next. Dated logs and records (HISTORICAL) keep their original wording.
        for f in tracked():
            rel = f.relative_to(ROOT).as_posix()
            if (f.suffix not in TEXT or not f.exists() or rel.startswith(HISTORICAL) or rel in FROZEN
                    or rel == "tests/test_repo.py"):
                continue
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            for n, line in enumerate(lines):
                m = PHERC0841_HELD_OUT.search(line)
                if m:
                    near = line + " " + (lines[n + 1] if n + 1 < len(lines) else "")
                    self.assertIn("Hecate", near, f"{rel}:{n + 1} says {m.group(0)!r} without naming Hecate")
        held_out = json.loads((ROOT / "docs" / "results.json").read_text(encoding="utf-8"))["held_out"]
        self.assertIn("Hecate", held_out["PHerc0841"])

    def test_pherc0841_pattern_catches_the_old_wording(self):
        # The check above must be able to fail: the wording it replaced is caught.
        for old in ("\"PHerc0841\": \"in no candidate's training set\"",
                    "PHerc0841, the labelled scroll no released reader trained on.",
                    "| PHerc0841 | Scroll in no candidate's training set, with labelled segments"):
            self.assertIsNotNone(PHERC0841_HELD_OUT.search(old), old)
        self.assertIsNone(PHERC0841_HELD_OUT.search("no candidate with usable selection variation"))

    def test_no_discord_message_links(self):
        for f in tracked():
            rel = f.relative_to(ROOT).as_posix()
            if f.suffix not in TEXT + (".csv",) or not f.exists() or rel.startswith(DISCORD_ALLOWED):
                continue
            m = DISCORD_MESSAGE.search(f.read_text(encoding="utf-8", errors="replace"))
            self.assertIsNone(m, f"{rel} links a Discord message: {m.group(0)}" if m else "")
        # The check can fail: a message link is caught, a plain mention is not.
        self.assertIsNotNone(DISCORD_MESSAGE.search("(https://discord.com/channels/" "1079907749569237093/1/2)"))
        self.assertIsNone(DISCORD_MESSAGE.search("(Discord #general, 26 February 2025)"))

    def test_agents_map_lists_every_kit_module(self):
        # Every kit module has a row in the repository map, docs/MAP.md (AGENTS.md points there); a row
        # may name several.
        section = (ROOT / "docs" / "MAP.md").read_text(encoding="utf-8")
        mapped = set(re.findall(r"`(kit/[A-Za-z0-9_]+\.py)`", section))
        modules = set()
        for f in tracked():
            rel = f.relative_to(ROOT).as_posix()
            if re.fullmatch(r"kit/[A-Za-z0-9_]+\.py", rel) and rel != "kit/__init__.py":
                modules.add(rel)
        self.assertTrue(modules)
        self.assertEqual(sorted(modules - mapped), [], "kit modules missing from the repository map, docs/MAP.md")

    def test_agent_entry_files_stay_short(self):
        # Every agent reads AGENTS.md (Claude loads it each session) and docs/HANDOFF.md first, so both stay
        # short. Over the limit: move the handoff's oldest dated sections, unchanged, to the top of
        # docs/HANDOFF-archive.md, and keep per-module rows in docs/MAP.md rather than AGENTS.md.
        for rel, limit in {"AGENTS.md": 20_000, "docs/HANDOFF.md": 40_000}.items():
            size = len((ROOT / rel).read_bytes())
            self.assertLessEqual(size, limit, f"{rel} is {size} bytes, over {limit}; see the comment above")

    def test_assets_are_listed_labeled_and_within_limits(self):
        # Chase, 18 October 2026: every released tool gets a hero like the README's, plus GIFs and videos, and every
        # picture says what it is. The public media rule (set on Chase's delegation the same day, docs/media/README.md)
        # allows concept illustrations, synthetic demos and Real data renders of public scans that are not
        # prize-eligible and show no held-out labels; never model output; every file at most 1920 px wide and 4 MB.
        base = ROOT / "docs" / "assets"
        rows = asset_rows()
        table, _ = media.prize_scrolls()
        files = sorted(f.relative_to(base).as_posix() for f in tracked()
                       if f.exists() and base in f.parents and f.name != "README.md")
        self.assertTrue(files, "no files under docs/assets/")
        media_files = [f for f in files if not f.endswith(".json")]
        missing = [f for f in media_files if f not in rows]
        self.assertEqual(missing, [], "files under docs/assets/ without a row in docs/assets/README.md")
        stale = [f for f in rows if not (base / f).is_file()]
        self.assertEqual(stale, [], "rows in docs/assets/README.md for files that are not there")
        dims_of = {}
        for rel in media_files:
            size, nbytes, label, license_ = rows[rel]
            path = base / rel
            actual = path.stat().st_size
            self.assertEqual(nbytes, actual, f"{rel}: the README says {nbytes:,} bytes, the file has {actual:,}")
            self.assertIn(label, media.PUBLIC_LABELS, f"{rel}: label {label!r} (public Git holds no model output)")
            self.assertTrue(license_, f"{rel}: no license")
            if label == "Real data render":
                self.assertEqual(license_, media.DATA_LICENSE, f"{rel}: a Real data render carries the data's license")
            self.assertLessEqual(actual, media.MAX_BYTES, f"{rel} is over 4 MB")
            dims = media.media_size(path)
            self.assertIsNotNone(dims, f"{rel}: its width and height cannot be read (PNG, GIF, JPEG, WebP or MP4)")
            dims_of[rel] = dims
            self.assertIn(f"{dims[0]} x {dims[1]} pixels", size, f"{rel}: the file is {dims[0]} x {dims[1]}")
            self.assertLessEqual(dims[0], media.MAX_WIDTH, f"{rel} is {dims[0]} px wide, over {media.MAX_WIDTH}")
            if rel.endswith("-hero.webp"):
                self.assertEqual(dims, (1920, 640), f"{rel}: a hero is 1920 x 640")
                self.assertLessEqual(actual, HERO_MAX_BYTES, f"{rel}: a hero is at most 300 KB")
        # A sidecar NAME.json describes media beside it; it passes the rule, and its label, bytes and pixel sizes
        # match the files and their rows.
        described = set()
        for rel in (f for f in files if f.endswith(".json")):
            record = json.loads((base / rel).read_text(encoding="utf-8"))
            self.assertEqual(media.public_problems(record, table), [], f"{rel}: the public media rule")
            self.assertNotIn("/tmp/", json.dumps(record), f"{rel}: a scratch path; record commands with placeholders")
            folder = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""
            for out in record["outputs"]:
                target = folder + out["file"]
                self.assertIn(target, rows, f"{rel} names {target}, which has no row")
                self.assertEqual(rows[target][2], record["label"], f"{target}: row and sidecar labels differ")
                self.assertEqual(out["bytes"], (base / target).stat().st_size, f"{rel}: {target} changed since")
                self.assertEqual((out["width"], out["height"]), dims_of[target], f"{rel}: {target}'s pixel size")
                described.add(target)
        undescribed = [f for f in media_files if f not in described]
        self.assertEqual(undescribed, [], "files under docs/assets/ that no sidecar NAME.json describes")

    def test_pictures_and_clips_live_in_the_media_folders(self):
        # The rule is checked where the pictures live: a picture or clip anywhere else would skip its row, sidecar and
        # prize check. docs/images/ holds interface screenshots that show no scan data (hero inputs).
        outside, too_big = [], []
        for f in tracked():
            rel = f.relative_to(ROOT).as_posix()
            if f.suffix.lower() not in MEDIA_SUFFIXES or not f.exists():
                continue
            if not rel.startswith(MEDIA_DIRS):
                outside.append(rel)
                continue
            dims = media.media_size(f)
            if f.stat().st_size > media.MAX_BYTES or (dims and dims[0] > media.MAX_WIDTH):
                too_big.append(rel)
        self.assertEqual(outside, [], "pictures or clips outside docs/assets/ and docs/images/ (docs/media/README.md)")
        self.assertEqual(too_big, [], f"pictures or clips over {media.MAX_WIDTH} px wide or 4 MB")

    def test_vector_files_carry_no_raster_pixels(self):
        # SVG files are not pictures under the media rule (charts drawn from numbers may sit anywhere), so one that embeds
        # or links a raster picture would carry scan pixels past every check above. tests/test_media.py shows this failing.
        raster = [f.relative_to(ROOT).as_posix() for f in tracked()
                  if f.suffix.lower() == ".svg" and f.exists()
                  and media.svg_embeds_raster(f.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(raster, [], "SVG files that embed or link a raster picture (docs/media/README.md)")

    def test_media_size_reads_headers(self):
        # The checks above must be able to fail: they read real dimensions, so a wrong size string is caught.
        png = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1920, 640) + b"\0" * 8
        gif = b"GIF89a" + struct.pack("<HH", 960, 540) + b"\0" * 8
        vp8x = b"RIFF\0\0\0\0WEBPVP8X" + b"\0" * 8 + (1919).to_bytes(3, "little") + (639).to_bytes(3, "little")
        jpeg = b"\xff\xd8\xff\xe0\x00\x04\x00\x00\xff\xc0\x00\x11\x08" + struct.pack(">HH", 630, 1200) + b"\0" * 8

        def box(kind, body):
            return struct.pack(">I", 8 + len(body)) + kind + body

        def tkhd(w, h, version=0):
            times = b"\0" * (32 if version else 20)
            return box(b"tkhd", bytes([version, 0, 0, 3]) + times + b"\0" * 52 + struct.pack(">II", w << 16, h << 16))

        audio = box(b"trak", tkhd(0, 0))
        mp4 = box(b"ftyp", b"isom\0\0\x02\0") + box(b"moov", box(b"mvhd", b"\0" * 100) + audio
                                                       + box(b"trak", tkhd(1280, 960, version=1)))
        tmp = ROOT / "tests" / "_image_size_probe"
        try:
            for data, want in ((png, (1920, 640)), (gif, (960, 540)), (vp8x, (1920, 640)), (jpeg, (1200, 630)),
                               (mp4, (1280, 960))):
                tmp.write_bytes(data)
                self.assertEqual(media.media_size(tmp), want)
            tmp.write_bytes(b"not an image")
            self.assertIsNone(media.media_size(tmp))
        finally:
            tmp.unlink(missing_ok=True)
        self.assertIsNone(ASSET_ROW.match("| Asset | Size | Bytes | Label | License | Alt text |"))
        m = ASSET_ROW.match("| [`a/b-hero.webp`](a/b-hero.webp) | 1920 x 640 pixels | 81,234 | Concept illustration "
                            "| Apache-2.0 | A thing. |")
        self.assertEqual(m.group(2, 4, 5), ("a/b-hero.webp", "81,234", "Concept illustration"))

    def test_relative_links_resolve(self):
        # Live Markdown only. Dated logs, evidence and experiment records (HISTORICAL) are frozen as
        # written, so a link there that later moved is corrected by a new log, not by an edit.
        files = [f.relative_to(ROOT).as_posix() for f in tracked()]
        known = set(files)
        for rel in files:
            parts = rel.split("/")
            known.update("/".join(parts[:i]) for i in range(1, len(parts)))
        # Tool pages still to be written (docs/TOOL-DOCS.md) may be linked by their future path.
        pending = ROOT / "docs" / "tools" / "pending.json"
        if pending.exists():
            known.update(f"docs/tools/{pid}.md" for pid in json.loads(pending.read_text(encoding="utf-8"))["pages"])
        missing = []
        for f in tracked():
            rel = f.relative_to(ROOT).as_posix()
            if f.suffix != ".md" or not f.exists() or rel.startswith(HISTORICAL) or rel in FROZEN:
                continue
            text = re.sub(r"```.*?```", "", f.read_text(encoding="utf-8", errors="replace"), flags=re.S)
            for target in MD_LINK.findall(text):
                if target.startswith("#") or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
                    continue
                path = unquote(target.split("#", 1)[0].split("?", 1)[0])
                if not path:
                    continue
                base = ROOT if path.startswith("/") else f.parent
                resolved = (base / path.lstrip("/")).resolve()
                try:
                    key = resolved.relative_to(ROOT.resolve()).as_posix()
                except ValueError:
                    key = None
                if key is None or (key not in known and key != "."):
                    missing.append(f"{rel} -> {target}")
        self.assertEqual(missing, [], "relative links that do not resolve")


if __name__ == "__main__":
    unittest.main()
