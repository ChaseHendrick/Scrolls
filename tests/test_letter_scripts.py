"""The letter reader's benchmark scripts (scripts/letters/) and its guide (docs/letter-reader.md).

Scripts: reference letters outside the reader's alphabet are refused with the alphabet printed, a
released model name works wherever the guide passes weights, eval_p1667.py and eval_p172.py print the
guide's row and measure first and their summary JSON last, the data scripts refuse unknown options,
and an --out folder is made before the read. Guide: every shell command runs as written when pasted
(no trailing comments, which stock zsh passes to the command, and comment lines of plain words only,
since zsh runs a pasted comment line as a command and would act on quotes, brackets or '>' in it),
every script and option it names exists, the Quick start opens with the virtual environment, and its
letter-size table follows the formula. README.md: the shell blocks of its hand-written parts follow the
same two comment rules. CITATION.cff: the fields GitHub and the guide rely on.
Synthetic images and random weights only; no network.
"""
import contextlib
import io
import json
import os
import re
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "letter-reader.md"
SHELL_BLOCK = re.compile(r"```(bash|sh|shell|console|powershell|bat|cmd)\n(.*?)```", re.S)

try:
    import numpy as np
    from kit import letterlines as LL
    from kit import letterread as R
    try:
        from test_letterread import lined_image, random_weights
    except ImportError:   # run as tests.test_letter_scripts
        from tests.test_letterread import lined_image, random_weights
except ImportError:  # the core kit is standard library only
    np = LL = R = None


def load_script(name):
    sys.path.insert(0, str(ROOT / "scripts" / "letters"))
    try:
        return __import__(name)
    finally:
        sys.path.remove(str(ROOT / "scripts" / "letters"))


def shell_lines(text):
    """(block number, line) of every line in the shell code blocks of a Markdown text."""
    out = []
    for n, m in enumerate(SHELL_BLOCK.finditer(text)):
        out += [(n, line) for line in m.group(2).splitlines()]
    return out


def trailing_comment(line):
    """The comment after a command on a shell line ('#' after a blank, outside quotes), or None."""
    quote, prev = None, " "
    for i, c in enumerate(line):
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "#" and prev.isspace():
            return line[i:] if line[:i].strip() else None
        prev = c
    return None


# A comment line pasted into zsh with interactive comments off (its default) is run as the command '#':
# harmless when it holds plain words, but quotes swallow the lines after it, '>' creates a file, ';', '&'
# and '|' run what follows, '$' and backticks expand, and brackets and glob characters stop the line.
SAFE_COMMENT = re.compile(r"#[\w .,:/+%-]*")


def unsafe_comment(line):
    """The comment line itself when it holds anything but plain words, else None (not a comment line: None)."""
    s = line.strip()
    if not s.startswith("#"):
        return None
    return None if SAFE_COMMENT.fullmatch(s) else s


def commands(text):
    """Every command line of the shell blocks (comment lines dropped, continuation lines joined)."""
    out, cur = [], ""
    for _, line in shell_lines(text):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        c = trailing_comment(s)
        s = s[:len(s) - len(c)].rstrip() if c else s
        cur += " " + s.rstrip("\\").strip()
        if not s.endswith("\\"):
            out.append(cur.strip())
            cur = ""
    return out


class GuideCommandsTest(unittest.TestCase):
    def test_the_comment_finder_can_fail(self):
        self.assertEqual(trailing_comment("scrolls-letterdemo   # prints DEMO PASS"), "# prints DEMO PASS")
        self.assertIsNone(trailing_comment("# a comment on its own line"))
        self.assertIsNone(trailing_comment('curl -o x "https://example.org/a#b"'))
        self.assertIsNone(trailing_comment("echo a#b"))

    def test_no_trailing_comments_in_the_guide(self):
        # Stock zsh (macOS) has interactive comments off: a pasted 'cmd   # note' passes '#' and the note to cmd.
        lines = shell_lines(GUIDE.read_text(encoding="utf-8"))
        self.assertGreater(len(lines), 50)
        bad = [line for _, line in lines if trailing_comment(line)]
        self.assertEqual(bad, [], "put each comment on its own line, above its command")

    def test_the_safe_comment_rule_can_fail(self):
        self.assertIsNone(unsafe_comment("# Row 3, its second value, the same windows with nothing given"))
        self.assertIsNone(unsafe_comment("python -m kit letterdemo"))
        for bad in ("# Perseus's Greek texts", "#    -> work/letters/demo/w013.json", "# a (note)",
                    "# one; two", "# $HOME", "# `date`", '# "quoted"', "# a | b", "# a & b", "# work/*.png"):
            self.assertEqual(unsafe_comment(bad), bad)

    def test_comment_lines_hold_plain_words(self):
        bad = [line.strip() for n, line in shell_lines(GUIDE.read_text(encoding="utf-8"))
               if n in self.zsh_blocks() and unsafe_comment(line)]
        self.assertEqual(bad, [], "a comment line in a shell block may hold letters, digits, spaces and .,:/+%- only")

    def test_readme_shell_blocks_run_when_pasted(self):
        # The README's hand-written parts; its Released tools section is generated from docs/releases.json,
        # whose letter-reader entry test_no_trailing_comments_in_the_readme_entry checks.
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        start, end = text.index("<!-- releases:start"), text.index("<!-- releases:end -->")
        hand = text[:start] + text[end:]
        lines = [line for m in SHELL_BLOCK.finditer(hand) if m.group(1) in ("bash", "sh", "shell", "console")
                 for line in m.group(2).splitlines()]
        self.assertGreater(len(lines), 20)
        self.assertEqual([line.strip() for line in lines if unsafe_comment(line)], [],
                         "a comment line in a shell block may hold letters, digits, spaces and .,:/+%- only")
        self.assertEqual([line for line in lines if trailing_comment(line)], [],
                         "put each comment on its own line, above its command")

    def zsh_blocks(self):
        return {n for n, m in enumerate(SHELL_BLOCK.finditer(GUIDE.read_text(encoding="utf-8")))
                if m.group(1) in ("bash", "sh", "shell", "console")}

    def test_quick_start_opens_with_a_virtual_environment(self):
        text = GUIDE.read_text(encoding="utf-8")
        part = text[text.index("## Quick start"):text.index("### Install")]
        blocks = SHELL_BLOCK.findall(part)
        self.assertEqual(blocks[0][0], "bash")
        self.assertEqual(blocks[0][1].splitlines()[:2], ["python3 -m venv .venv", ". .venv/bin/activate"])
        self.assertEqual(blocks[1][0], "powershell")
        self.assertEqual(blocks[1][1].splitlines()[0], "py -m venv .venv")
        self.assertTrue(blocks[1][1].splitlines()[1].startswith(".venv\\Scripts\\python.exe -m pip install"))
        clone = blocks[2][1].splitlines()
        self.assertIn('python -m pip install -e ".[reader]"', clone)
        self.assertIn("PEP 668", part)

    def test_no_trailing_comments_in_the_readme_entry(self):
        # Since 20 October 2026 the reader is a line (tool) of the Scrolls kit entry; its old id still finds it.
        from kit import releases
        registry = json.loads((ROOT / "docs" / "releases.json").read_text(encoding="utf-8"))
        entry, tool = releases.find(registry, "letter-reader")
        commands = entry.get("commands", []) + ([tool["command"]] if tool else [])
        self.assertTrue(commands)
        self.assertEqual([c for c in commands if trailing_comment(c) or unsafe_comment(c)], [])
        self.assertIn("python3 -m venv .venv", commands)
        self.assertIn("scrolls-letterdemo", commands)
        self.assertIn("38 um grid", tool["summary"] if tool else entry["details"])

    def test_scripts_and_options_in_the_guide_exist(self):
        text = GUIDE.read_text(encoding="utf-8")
        cli = (ROOT / "kit" / "cli.py").read_text(encoding="utf-8")
        seen = 0
        for cmd in commands(text):
            for part in re.split(r"[;|]|&&|\$\(", cmd):
                try:
                    words = shlex.split(part)
                except ValueError:
                    continue
                for i, w in enumerate(words):
                    if re.fullmatch(r"(\.\./\.\./)?scripts/letters/\w+\.py|\w+\.py", w) and i and "python" in words[i - 1]:
                        name = Path(w).name
                        src = (ROOT / "scripts" / "letters" / name)
                        self.assertTrue(src.is_file(), f"{w} in: {cmd}")
                        body = src.read_text(encoding="utf-8")
                        source, flags = body, [x.split("=")[0] for x in words[i + 1:] if x.startswith("--")]
                        where = name
                    elif w in ("kit", "scrolls-letterread", "scrolls-letterlines", "scrolls-letterdemo") and (
                            w != "kit" or words[i - 1] == "-m"):
                        source, flags = cli + (ROOT / "kit" / "letterdemo.py").read_text(encoding="utf-8"), \
                            [x.split("=")[0] for x in words[i + 1:] if x.startswith("--")]
                        where = "kit/cli.py"
                    else:
                        continue
                    for f in flags:
                        self.assertTrue(f'"{f}"' in source, f"{f} is not an option of {where}: {cmd}")
                    seen += 1
        self.assertGreater(seen, 30)

    def test_letter_size_table_follows_the_formula(self):
        # | image | um per px | letter px | ... rows under "Letter size matters most"; 3.3 mm letters
        text = GUIDE.read_text(encoding="utf-8")
        part = text[text.index("### Letter size matters most"):]
        part = part[:part.index("\n### ", 5)]
        rows = re.findall(r"^\|[^|\n]+\| ([0-9.]+) \| ([0-9.]+) \|", part, re.M)
        self.assertGreaterEqual(len(rows), 4)
        for um, px in rows:          # a whole number of pixels, or the value to one decimal (1375.6)
            digits = len(px.partition(".")[2])
            self.assertEqual(round(3.3 * 1000 / float(um), digits), float(px), (um, px))
        if R is not None:
            self.assertEqual(round(R.letter_px_from_units(3.3, 2.399)), 1376)


@unittest.skipIf(np is None, "numpy not installed")
class BenchmarkScriptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.weights = random_weights(self.d / "w.npz")
        img = lined_image()          # four lines of 16 px letters, centered on rows 30, 60, 90 and 120
        g = self.d / "groups"
        (g / "npy").mkdir(parents=True)
        (g / "map-npy").mkdir()
        groups = []
        for i, y in enumerate((30, 60, 90)):
            gid = f"w001-g{i:03d}"
            np.save(g / "npy" / f"{gid}.npy", img[y - 15:y + 15, 10:300])
            np.save(g / "map-npy" / f"{gid}.npy", img[y - 15:y + 15, 0:310])
            groups.append({"id": gid, "segment": "w001", "centre_y": 15, "letter_h": 16})
        (g / "groups.json").write_text(json.dumps({"groups": groups}))
        self.groups = g
        self.refs = self.d / "refs.json"
        self.refs.write_text(json.dumps({"agreed": {"w001-g000": "ΑΒΓΔ", "w001-g001": "ΕΖΗ", "w001-g002": "Θ?Ι"}},
                                        ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_eval_p1667_refuses_letters_outside_the_alphabet(self):
        E = load_script("eval_p1667")
        self.assertEqual(sorted(E.references(self.refs)), ["w001-g000", "w001-g001"])   # a '?' group is left out
        bad = self.d / "bad.json"
        bad.write_text(json.dumps({"agreed": {"w001-g000": "AΒΓ", "w001-g001": "ΕΖΗς", "w001-g002": None}},
                                  ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            E.references(bad)
        msg = str(cm.exception.code)
        self.assertIn("LATIN CAPITAL LETTER A", msg)
        self.assertIn("FINAL SIGMA", msg)
        self.assertIn(LL.ALPHABET, msg)
        with self.assertRaises(SystemExit):
            E.read(self.groups, bad, str(self.weights))       # refused before the weights are loaded
        unsure = self.d / "unsure.json"                        # a group with '?' is not scored, so not checked
        unsure.write_text(json.dumps({"agreed": {"w001-g000": "ΑΒΓΔ", "w001-g001": "C?Σ"}}, ensure_ascii=False),
                          encoding="utf-8")
        self.assertEqual(E.references(unsure), {"w001-g000": "ΑΒΓΔ"})
        with self.assertRaises(SystemExit) as cm:              # no references yet: where the guide says how
            E.references(self.d / "refs-missing.json")
        self.assertIn("References paragraph", str(cm.exception.code))
        G = load_script("p1667_groups")
        with mock.patch.dict(sys.modules, {"zarr": None}), self.assertRaises(SystemExit) as cm:
            G.downsample(self.d / "labels.zarr")
        self.assertIn("pip install zarr", str(cm.exception.code))

    def test_eval_p1667_takes_a_released_name_and_prints_the_guide_measure_first(self):
        E = load_script("eval_p1667")
        reg = self.d / "reg.json"
        reg.write_text(json.dumps({"models": {"tiny": {"file": "tiny.npz", "sha256": R._sha256(self.weights),
                                                       "url": self.weights.resolve().as_uri()}}}))
        with mock.patch.object(R, "WEIGHTS_REGISTRY", reg), \
                mock.patch.dict(os.environ, {"KIT_LETTER_WEIGHTS": str(self.d / "cache")}):
            by_name = E.read(self.groups, self.refs, "tiny", source="map")
        by_path = E.read(self.groups, self.refs, str(self.weights), source="map")
        self.assertEqual(by_name["weights"], "tiny")                     # recorded as given, as on 9 October
        self.assertEqual(by_path["weights"], str(self.weights))
        self.assertEqual(by_name["summary"], by_path["summary"])
        self.assertEqual(by_name["segments"], by_path["segments"])
        head = E.headline(by_path)
        self.assertIn("row 2, Same 87 groups read from the 2.4 um ink maps", head[0])
        self.assertTrue(head[1].startswith("ink_only: free-ends error"), head[1])
        label = E.read(self.groups, self.refs, str(self.weights), source="label")
        self.assertTrue(E.headline(label)[1].startswith("ink_only: character error"))
        argv = ["eval_p1667.py", "read", str(self.groups), str(self.refs), "--weights", str(self.weights),
                "--source", "map", "--out", str(self.d / "new" / "folder" / "out.json")]
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
            E.main()
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(lines[:-1], head)
        self.assertEqual(json.loads(lines[-1]), by_path["summary"])     # the JSON stays last, for `| tail -1`
        out = json.loads((self.d / "new" / "folder" / "out.json").read_text(encoding="utf-8"))   # folder made
        self.assertEqual(sorted(out), sorted(by_path))                    # the --out file keeps its fields
        self.assertTrue(E.headline({**by_path, "source": "map-region", "letter_px": "auto"})[0].startswith(
            "source map-region, letter height auto: the guide's row 4, Maps"))
        self.assertIn("no row of the table", E.headline({**by_path, "source": "map-region", "letter_px": "given"})[0])
        rows = {v.split(",")[0].split("'")[0] for v in E.GUIDE_ROWS.values()}
        self.assertTrue({"row 1", "row 2", "row 3", "row 4"} <= rows, rows)    # every PHerc. 1667 row of the table

    def test_eval_p172_prints_its_row_and_measure_first(self):
        P = load_script("eval_p172")
        res = {"split": "test", "columns": "auto", "segments": [{"segment": "s1"}, {"segment": "s2"}],
               "summary": {"ink_only": {"cer_matched_lines": 0.426, "ref_letters": 122},
                           "with_lm": {"cer_matched_lines": 0.451, "ref_letters": 122}}}
        head = P.headline(res)
        self.assertIn("the guide's PHerc. 172 row", head[0])
        self.assertEqual(head[1], "ink_only: character error over matched lines 0.426 (122 reference letters)")
        self.assertTrue(head[2].startswith("with_lm:"))
        self.assertIn("for choosing a checkpoint", P.headline({**res, "split": "dev"})[0])
        self.assertIn("no row", P.headline({**res, "columns": "off"})[0])
        res["segments"] = [{"segment": "s1", "ink_only": {"cer": 0.4, "ref_letters": 10}, "kept": 12, "null_kept": [1, 2]}]
        argv = ["eval_p172.py", str(self.d), "--weights", "w", "--split", "test", "--columns", "auto",
                "--out", str(self.d / "p172" / "out.json")]
        buf = io.StringIO()
        with mock.patch.object(P, "evaluate", return_value=res), mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(buf):
            P.main()
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(lines[:3], P.headline(res)[:3])
        self.assertEqual(json.loads(lines[-1]), res["summary"])          # last, for the guide's `| tail -1` loop
        self.assertTrue((self.d / "p172" / "out.json").is_file())

    def test_data_scripts_refuse_unknown_options(self):
        fetch, mapcrops = load_script("p1667_fetch"), load_script("p1667_mapcrops")
        groups, text = load_script("p1667_groups"), load_script("p1667_text")
        self.assertTrue(fetch.parse_args(["work/p1667", "--labels-only"]).labels_only)
        self.assertFalse(fetch.parse_args(["work/p1667"]).labels_only)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for parse, argv in ((fetch.parse_args, ["work/p1667", "--label-only"]),   # a typo never fetches 1.9 GB
                                (fetch.parse_args, []),
                                (mapcrops.parse_args, ["g", "m", "--wide", "--region"]),
                                (mapcrops.parse_args, ["g", "m", "--regions"]),
                                (groups.parse_args, ["labels"]),
                                (text.parse_args, ["paper.pdf", "out.json", "extra"])):
                with self.assertRaises(SystemExit, msg=argv):
                    parse(argv)
        a = mapcrops.parse_args(["g", "m", "--region"])
        self.assertEqual((a.groups_dir, a.maps_dir, a.wide, a.region), ("g", "m", False, True))
        self.assertEqual(vars(groups.parse_args(["l", "o"])), {"labels_dir": "l", "out_dir": "o"})
        # p1667_text.py writes its docstring's second paragraph into every reference as its rule
        self.assertTrue(text.__doc__.split("\n\n")[1].startswith("The text is the column-by-column transcription"))

    def test_p1667_fetch_refuses_label_keys_outside_out(self):
        fetch = load_script("p1667_fetch")
        root = self.d / "labels" / "w013" / "z" / "1"
        self.assertEqual(fetch.label_path(root, "B/1/", "B/1/0/0/0"), root / "0/0/0")
        self.assertEqual(fetch.label_path(root, "B/1/", "B/1/.zarray"), root / ".zarray")
        for key in ("B/1/../../../../../x", "B/1/", "B/1//etc/x", "B/1/a/../../x", "C/1/x", "B/1/a\\..\\x", "B/1/a//b"):
            with self.subTest(key=key), self.assertRaises(SystemExit):
                fetch.label_path(root, "B/1/", key)

    def test_text_reference_and_alignment_refuse_letters_outside_the_alphabet(self):
        T = load_script("eval_p1667_text")
        good = {"columns": {"5": [{"line": 1, "letters": "ΚΑΙ??ΤΟΥϹ"}, {"line": 2, "letters": ""}]}}
        self.assertIs(T.check_reference(good), good)
        bad = {"columns": {"5": [{"line": 1, "letters": "ΚΑΙΤΟΥΣ"}], "6": [{"line": 3, "letters": "KAI"}]}}
        with self.assertRaises(SystemExit) as cm:
            T.check_reference(bad, "text.json")
        msg = str(cm.exception.code)
        self.assertIn("column 5 line 1", msg)
        self.assertIn("column 6 line 3", msg)
        self.assertIn(T.ALPHABET, msg)
        ref = self.d / "text.json"
        ref.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        argv = ["eval_p1667_text.py", "decoys", str(ref), str(self.d / "no-corpus.xml"), "--out", str(self.d / "d.json")]
        with mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit) as cm:
            T.main()                                   # refused before the corpus is read
        self.assertIn("lunate sigma", str(cm.exception.code))
        self.assertFalse((self.d / "d.json").exists())

    def test_p172_scripts_refuse_letters_outside_the_alphabet(self):
        P = load_script("eval_p172")
        self.assertEqual(P.LETTERS, LL.ALPHABET)
        P.check_alphabet({"s1": ["ΑΒΓ", "ΔΕ"]}, LL.ALPHABET)
        with self.assertRaises(SystemExit) as cm:
            P.check_alphabet({"s1": ["ΑΒΓ"]}, LL.ALPHABET.replace("Γ", ""), "weights of your own")
        self.assertIn("'Γ'", str(cm.exception.code))
        C = load_script("compare_p172")
        res = {"segments": [{"segment": "s1", "ink_only": {"pairs": [["ΑΒ", "ΑΒΓ"], ["Δ", "ΔΕ"]]}}]}
        C.check_result_references(res)
        a, b = self.d / "a.json", self.d / "b.json"
        a.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        res["segments"][0]["ink_only"]["pairs"][1][1] = "ΔE"            # a Latin E typed by hand
        b.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            C.main([str(a), str(b)])
        self.assertIn("LATIN CAPITAL LETTER E", str(cm.exception.code))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            C.main([str(a), str(a), "--n", "200"])
        self.assertEqual(json.loads(buf.getvalue())["diff_b_minus_a"], 0.0)

    def test_finetune_refuses_lines_outside_the_alphabet_before_torch(self):
        F = load_script("finetune_maps")
        lines = LL.save_lines(self.d / "lines.npz", [np.zeros((36, 80), np.float32)] * 2, ["ΑΒΓ", "ABΓ"],
                              [["x", 0, 0], ["x", 0, 1]], {})
        with mock.patch.dict(sys.modules, {"torch": None}), self.assertRaises(SystemExit) as cm:
            F.train(lines, self.d / "shards", self.weights, self.d / "out", steps=20)
        self.assertIn("line 1", str(cm.exception.code))
        self.assertIn(F.ALPHABET, str(cm.exception.code))
        self.assertFalse((self.d / "out").exists())

    def test_font_roots(self):
        try:
            L = load_script("letterdata")
        except ImportError:
            self.skipTest("letterdata needs numpy")
        env = {"LETTER_FONT_DIRS": os.pathsep.join(["/my/fonts", "/usr/share/fonts", ""]), "WINDIR": "C:/Windows",
               "LOCALAPPDATA": "C:/Users/me/AppData/Local"}
        roots = L.font_roots(env, home="/home/me")
        self.assertEqual(roots[:2], [Path("/my/fonts"), Path("/usr/share/fonts")])     # yours first
        self.assertEqual(len(roots), len(set(roots)))
        for p in (Path("/home/me/.local/share/fonts"), Path("/home/me/Library/Fonts"), Path("/Library/Fonts"),
                  Path("C:/Windows") / "Fonts", Path("C:/Users/me/AppData/Local") / "Microsoft" / "Windows" / "Fonts"):
            self.assertIn(p, roots)
        self.assertNotIn(Path("C:/Windows") / "Fonts", L.font_roots({}, home="/home/me"))


    def test_font_candidates_lists_each_file_once(self):
        try:
            L = load_script("letterdata")
        except ImportError:
            self.skipTest("letterdata needs numpy")
        root = self.d / "fonts"
        (root / "truetype").mkdir(parents=True)
        for name in ("truetype/A.ttf", "truetype/B-Mono.ttf", "C.otf", "notes.txt"):
            (root / name).write_bytes(b"")
        inner = root / "truetype"
        # a $LETTER_FONT_DIRS folder inside a default one, and that default one given twice by another path
        got = L.font_candidates([inner, root, root / "truetype" / "..", self.d / "missing"])
        self.assertEqual(got, [inner / "A.ttf", root / "C.otf"])
        if hasattr(os, "symlink"):
            try:
                os.symlink(inner, self.d / "linked", target_is_directory=True)   # ~/.fonts linked to another folder
            except OSError:
                return
            self.assertEqual(L.font_candidates([inner, self.d / "linked"]), [inner / "A.ttf"])
            os.symlink(inner / "A.ttf", inner / "Alias.ttf")          # a file link keeps its entry, as before
            self.assertEqual(L.font_candidates([inner, root]), [inner / "A.ttf", inner / "Alias.ttf", root / "C.otf"])

class CitationTest(unittest.TestCase):
    """CITATION.cff: the fields GitHub's citation box and the guide's Citing section rely on.

    Read with PyYAML when it is installed (and its parse checked); the core checks need no package."""

    def setUp(self):
        self.text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")

    def test_fields(self):
        for line in ("cff-version: 1.2.0", "type: software", "license: Apache-2.0",
                     'repository-code: "https://github.com/ChaseHendrick/Scrolls"', "family-names: Hendrick",
                     "given-names: Chase", "license: CC-BY-NC-4.0", "license: CC-BY-4.0",
                     'url: "https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-real"',
                     'url: "https://github.com/ChaseHendrick/Scrolls/releases/tag/letters-v2-ccby"'):
            self.assertIn(line, self.text)
        version = re.search(r"^version: (\S+)$", self.text, re.M).group(1)
        init = (ROOT / "kit" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{version}"', init)            # the package's version, kit.__version__
        registry = json.loads((ROOT / "kit" / "data" / "letter-weights.json").read_text(encoding="utf-8"))
        for name in ("letters-v2-ccby", "letters-v2-real"):                     # one reference per released model
            self.assertIn(registry["models"][name]["sha256"], " ".join(self.text.split()))
        for ch in (chr(0x2014), chr(0x2013), "\t"):
            self.assertNotIn(ch, self.text)

    def test_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        d = yaml.safe_load(self.text)
        self.assertEqual(d["cff-version"], "1.2.0")
        self.assertEqual(d["authors"], [{"given-names": "Chase", "family-names": "Hendrick"}])
        self.assertEqual(d["license"], "Apache-2.0")
        refs = {r["title"].split(":")[0]: r for r in d["references"]}
        self.assertEqual(list(refs), ["letters-v2-ccby", "letters-v2-real"])     # the default weights first
        for name, licence, file in (("letters-v2-ccby", "CC-BY-4.0", "letters-v2-ccby-step026000.npz"),
                                    ("letters-v2-real", "CC-BY-NC-4.0", "letters-v2-real-step030000.npz")):
            self.assertEqual((refs[name]["license"], refs[name]["type"]), (licence, "data"))
            self.assertIn(file, refs[name]["notes"])
            self.assertEqual(refs[name]["url"], f"https://github.com/ChaseHendrick/Scrolls/releases/tag/{name}")
        for key in ("message", "title", "abstract", "version"):
            self.assertIsInstance(d[key], str)


if __name__ == "__main__":
    unittest.main()
