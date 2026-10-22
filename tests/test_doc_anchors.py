"""Every #fragment in a live Markdown link to a tracked .md file lands on GitHub.

GitHub makes an anchor from each heading's text (lower case, punctuation dropped, spaces to hyphens, -1, -2 for
repeats) and from <a id="..."> or <a name="..."> tags. It ignores Pandoc's heading ids ({#id}), so a heading such as
'# Ink Detection {#ch-ink}' needs an '<a id="ch-ink"></a>' line before it (the Vesuvius Bible does this), and a link
from one chapter file to another names that file ('05-inks.md#ch-inks'). Dated logs, evidence, experiment records and
frozen preregistrations keep their wording, as in tests/test_repo.py.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = ("docs/logs/", "docs/evidence/", "scripts/experiments/", "docs/prereg/2026-10-14-strokenet.md",
        "docs/prereg/2026-10-14-gridpilot.md")
FENCE = re.compile(r"^(`{3,}|~{3,}).*?^\1[`~]*[ \t]*$", re.S | re.M)
LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")


def slug(text):
    """GitHub's anchor for a heading: its visible text, lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def anchors(text):
    out, seen = set(), {}
    for line in FENCE.sub("", text).splitlines():
        m = HEADING.match(line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            out.add(s if n == 0 else f"{s}-{n}")
            seen[s] = n + 1
        out.update(HTML_ANCHOR.findall(line))
    return out


def missing_anchors(files, read):
    """[(file, link target)] whose #fragment is not an anchor of the .md file it points at."""
    cache, bad = {}, []
    for rel in files:
        text = re.sub(r"`[^`\n]*`", "", FENCE.sub("", read(rel)))
        for target in LINK.findall(text):
            if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target) or "#" not in target:
                continue
            path, frag = target.split("#", 1)
            dest = (Path(rel).parent / path).as_posix() if path else rel
            dest = "/".join(_normalize(dest.split("/")))
            if not dest.endswith(".md") or dest not in files:
                continue
            if dest not in cache:
                cache[dest] = anchors(read(dest))
            if frag not in cache[dest]:
                bad.append((rel, target))
    return bad


def _normalize(parts):
    out = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == ".." and out:
            out.pop()
        else:
            out.append(p)
    return out


class DocAnchorsTest(unittest.TestCase):
    def test_fragments_land_on_github(self):
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"], cwd=ROOT,
                             capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest("needs git")
        files = {f for f in out.stdout.split("\n") if f and (ROOT / f).exists()}
        live = sorted(f for f in files if not f.startswith(SKIP))
        bad = missing_anchors(live, lambda rel: (ROOT / rel).read_text(encoding="utf-8", errors="replace"))
        self.assertEqual(bad[:20], [], f"{len(bad)} links whose #fragment GitHub cannot find (first 20 shown)")

    def test_the_check_can_fail(self):
        docs = {
            "a.md": "# Ink Detection {#ch-ink}\n\n## Two words\n\n## Two words\n\n<a id=\"x-1\"></a>\n",
            "b.md": "[ok](a.md#two-words) [ok](a.md#two-words-1) [ok](a.md#x-1) [ok](a.md#ink-detection-ch-ink)\n"
                    "[bad](a.md#ch-ink) [bad](a.md#two-words-2) [bad](#nowhere)\n# B\n[ok](#b)\n",
        }
        bad = missing_anchors(sorted(docs), docs.__getitem__)
        self.assertEqual(bad, [("b.md", "a.md#ch-ink"), ("b.md", "a.md#two-words-2"), ("b.md", "#nowhere")])
        self.assertEqual(slug("Appendix A. Glossary {#app-glossary}"), "appendix-a-glossary-app-glossary")
        self.assertEqual(slug("`kit stale`: what [it](x.md) checks"), "kit-stale-what-it-checks")


if __name__ == "__main__":
    unittest.main()
