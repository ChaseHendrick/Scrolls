"""Tests for kit.datacard: a good card passes, and each planted fault fails its own rule."""

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from kit import datacard as dc


def _write_good(root, synthetic=True):
    root = Path(root)
    readme, prov = dc.template(synthetic)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "a.bin").write_bytes(b"alpha")
    (root / "data" / "b.bin").write_bytes(b"beta")
    (root / "README.md").write_text(readme, encoding="utf-8")
    prov["code"]["commit"] = "51a17e6"
    (root / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    (root / "SHA256SUMS").write_text(dc.make_sums(root), encoding="utf-8")
    return prov


def _rules(rec, level="fail"):
    return {f["rule"] for f in rec["findings"] if f["level"] == level}


class TemplatePasses(unittest.TestCase):
    def test_synthetic_and_real_templates_pass(self):
        for synthetic in (True, False):
            with tempfile.TemporaryDirectory() as d:
                _write_good(d, synthetic)
                rec = dc.check(dc.Folder(d))
                self.assertEqual(rec["verdict"], "PASS", _rules(rec))
                self.assertEqual(rec["counts"]["verified"], 3)    # a.bin, b.bin, provenance.json

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            _write_good(d)
            out = io.StringIO()
            import contextlib
            with contextlib.redirect_stdout(out):
                self.assertEqual(dc.main(["check", d, "--json"]), dc.EXIT_OK)
            self.assertEqual(json.loads(out.getvalue())["verdict"], "PASS")
            (Path(d) / "data" / "a.bin").write_bytes(b"changed")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dc.main(["check", d]), dc.EXIT_FAIL)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(dc.main(["check", "not a repo id"]), dc.EXIT_INPUT)

    def test_template_refuses_to_overwrite(self):
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(dc.main(["template", d]), dc.EXIT_OK)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(dc.main(["template", d]), dc.EXIT_INPUT)


class PlantedFaults(unittest.TestCase):
    """Each planted fault must flip the verdict to FAIL through the named rule."""

    def plant(self, edit, rule, synthetic=True):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            prov = _write_good(root, synthetic)
            edit(root, prov)
            rec = dc.check(dc.Folder(root))
            self.assertEqual(rec["verdict"], "FAIL", f"{rule} did not fail")
            self.assertIn(rule, _rules(rec))

    @staticmethod
    def _prov(root, prov, **changes):
        prov.update(changes)
        (root / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
        (root / "SHA256SUMS").write_text(dc.make_sums(root), encoding="utf-8")

    @staticmethod
    def _card(root, old, new):
        p = root / "README.md"
        text = p.read_text(encoding="utf-8")
        assert old in text, old
        p.write_text(text.replace(old, new), encoding="utf-8")

    def test_changed_file(self):
        self.plant(lambda r, p: (r / "data" / "a.bin").write_bytes(b"tampered"), "sums.match")

    def test_unlisted_file(self):
        self.plant(lambda r, p: (r / "data" / "c.bin").write_bytes(b"new"), "sums.coverage")

    def test_listed_but_missing(self):
        self.plant(lambda r, p: (r / "data" / "b.bin").unlink(), "sums.missing")

    def test_bad_sums_line(self):
        self.plant(lambda r, p: (r / "SHA256SUMS").write_text("abc  data/a.bin\n"), "sums.format")

    def test_no_sums(self):
        self.plant(lambda r, p: (r / "SHA256SUMS").unlink(), "sums.present")

    def test_no_provenance(self):
        def edit(r, p):
            (r / "provenance.json").unlink()
            (r / "SHA256SUMS").write_text(dc.make_sums(r))
        self.plant(edit, "provenance.present")

    def test_license_mismatch(self):
        self.plant(lambda r, p: self._prov(r, p, license="mit"), "license.match")

    def test_noncommercial_source_dropped(self):
        def edit(r, p):
            p["sources"].append({"name": "scans", "url": "https://example.org", "license": "cc-by-nc-4.0"})
            self._prov(r, p)
        self.plant(edit, "license.inherit")          # card and provenance say cc-by-4.0

    def test_vesuvius_source_mislicensed(self):
        def edit(r, p):
            p["sources"].append({"name": "scan", "url": "https://dl.ash2txt.org/full-scrolls/", "license": "cc0-1.0"})
            self._prov(r, p)
        self.plant(edit, "license.vesuvius")

    def test_no_code_commit(self):
        self.plant(lambda r, p: self._prov(r, p, code={"repo": "https://github.com/x/y", "commit": "HEAD"}),
                   "provenance.code")

    def test_no_caveats(self):
        self.plant(lambda r, p: self._prov(r, p, caveats=[]), "provenance.caveats")

    def test_synthetic_without_seeds(self):
        self.plant(lambda r, p: self._prov(r, p, spent={"seeds": [], "truth": [], "none_reason": "n/a"}),
                   "spent.seeds")

    def test_spent_empty(self):
        self.plant(lambda r, p: self._prov(r, p, spent={}), "spent.present", synthetic=False)

    def test_spent_seed_not_in_card(self):
        def edit(r, p):
            p["spent"]["seeds"].append(999123456)
            self._prov(r, p)
        self.plant(edit, "spent.seeds-in-card")

    def test_bad_truth_use(self):
        def edit(r, p):
            p["spent"]["truth"] = [{"what": "ink labels", "scope": "w00", "use": "looked at"}]
            self._prov(r, p)
        self.plant(edit, "spent.truth")

    def test_missing_section(self):
        self.plant(lambda r, p: self._card(r, "## Spent seeds and truth", "## Something else"), "section.spent")

    def test_empty_limits(self):
        self.plant(lambda r, p: self._card(r, "- One bullet per limit.", ""), "section.limits")

    def test_no_license_in_front_matter(self):
        self.plant(lambda r, p: self._card(r, "license: cc-by-4.0\n", ""), "front-matter.license")

    def test_model_output_unlabeled(self):
        self.plant(lambda r, p: self._prov(r, p, kind=["model-output", "images"]), "model-output.label")

    def test_reading_claim(self):
        self.plant(lambda r, p: self._card(r, "- One bullet per limit.",
                                           "- One bullet per limit.\n\nThe letters were read in column 3."),
                   "model-output.reading")


class Parsing(unittest.TestCase):
    def test_front_matter(self):
        meta, body = dc.front_matter("---\nlicense: cc-by-nc-4.0\ntags: [a, b]\nlist:\n- x\n- y\n"
                                     "configs:\n- config_name: d\n  data_files: z\n---\n# T\n")
        self.assertEqual(meta["license"], "cc-by-nc-4.0")
        self.assertEqual(meta["tags"], ["a", "b"])
        self.assertEqual(meta["list"], ["x", "y"])
        self.assertIs(meta["configs"], True)
        self.assertEqual(body.strip(), "# T")

    def test_sums_dot_prefix_and_binary_mark(self):
        h = "a" * 64
        rows, bad = dc.parse_sums(f"{h}  ./x/y.png\n{h} *z.bin\nnot a line\n")
        self.assertEqual(rows, [(h, "x/y.png"), (h, "z.bin")])
        self.assertEqual(bad, [3])

    def test_seed_items(self):
        self.assertEqual(dc.seed_items([5, "10-12", "20..21"]), [(5, 5), (10, 12), (20, 21)])
        with self.assertRaises(ValueError):
            dc.seed_items(["12-10"])

    def test_negated_reading_is_allowed(self):
        self.assertEqual(dc.reading_claims("Nothing here says that letters were found or read."), [])
        self.assertTrue(dc.reading_claims("Two letters were found on the left."))

    def test_sections_ignore_code_blocks(self):
        heads = dc.headings("## Quick start\n```bash\n# Limits\n```\n## Limits\n- one\n")
        self.assertEqual(heads["limits"], "- one")


class Hub(unittest.TestCase):
    """The Hub source with a fake opener: LFS digests come from the tree, small files are downloaded."""

    def setUp(self):
        self.card, prov = dc.template(True)
        prov["code"]["commit"] = "51a17e6"
        self.files = {"README.md": self.card.encode(), "provenance.json": json.dumps(prov).encode(),
                      "small.json": b"{}"}
        big = b"x" * 1000
        import hashlib
        self.big_sha = hashlib.sha256(big).hexdigest()
        sums = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in sorted(self.files.items())
                       if k != "README.md")
        sums += f"{self.big_sha}  data/big.bin\n"
        self.files["SHA256SUMS"] = sums.encode()
        tree = [{"type": "file", "path": k, "size": len(v)} for k, v in self.files.items()]
        tree.append({"type": "file", "path": "data/big.bin", "size": 1000,
                     "lfs": {"oid": self.big_sha, "size": 1000}})
        self.tree = json.dumps(tree).encode()

    def opener(self, req, timeout=None):
        url = req.full_url
        if "/api/datasets/" in url:
            body = self.tree
        else:
            name = url.split("/resolve/main/", 1)[1]
            if name not in self.files:
                raise urllib.error.HTTPError(url, 404, "nf", {}, None)
            body = self.files[name]

        class R(io.BytesIO):
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R(body)

    def test_hub_pass_uses_lfs_digest(self):
        rec = dc.check(dc.HubDataset("o/n", opener=self.opener))
        self.assertEqual(rec["verdict"], "PASS", _rules(rec))
        self.assertEqual(rec["counts"]["verified"], 3)

    def test_hub_lfs_mismatch_fails(self):
        self.tree = self.tree.replace(self.big_sha.encode(), b"0" * 64)
        rec = dc.check(dc.HubDataset("o/n", opener=self.opener))
        self.assertIn("sums.match", _rules(rec))

    def test_hub_budget_leaves_small_files_unverified(self):
        rec = dc.check(dc.HubDataset("o/n", opener=self.opener), max_download_mb=0)
        self.assertEqual(rec["counts"]["verified"], 1)
        self.assertIn("sums.unverified", _rules(rec, "warn"))

    def test_hub_sums_from_lfs_digest_and_downloads(self):
        text = dc.make_sums(dc.HubDataset("o/n", opener=self.opener))
        self.assertIn(f"{self.big_sha}  data/big.bin", text)
        self.assertNotIn("README.md", text)
        with self.assertRaises(dc.InputError):    # a sums file never leaves a file out
            dc.make_sums(dc.HubDataset("o/n", opener=self.opener), max_download_mb=0)

    def test_overlay_checks_the_upload_before_it_happens(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            # a new provenance.json in the overlay changes its hash: the Hub's SHA256SUMS no longer matches
            prov = json.loads(self.files["provenance.json"])
            prov["version"] = "1.0.1"
            Path(d, "provenance.json").write_text(json.dumps(prov))
            src = dc.Overlay(dc.HubDataset("o/n", opener=self.opener), d)
            self.assertIn("sums.match", _rules(dc.check(src)))
            # new sums over the overlay fix it, and the overlay's own files are the ones hashed
            Path(d, "SHA256SUMS").write_text(dc.make_sums(src))
            rec = dc.check(src)
            self.assertEqual(rec["verdict"], "PASS", _rules(rec))
            self.assertIn(hashlib.sha256(Path(d, "provenance.json").read_bytes()).hexdigest(),
                          Path(d, "SHA256SUMS").read_text())


if __name__ == "__main__":
    unittest.main()
