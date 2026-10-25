"""Synthetic tests for the complete released-tool inventory."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kit import releases


def registry():
    return {"schema_version": 1, "pinned": ["pipeline"], "releases": [
        {"id": "kit", "title": "Example kit", "released": "2026-10-25", "where": "main",
         "summary": "Local tools.", "tools": [
             {"id": "sampler", "name": "Sample | inspect", "released": "2026-10-25",
              "summary": "Samples synthetic values.", "command": "python sample.py",
              "page": "docs/tools/sampler.md"}]},
        {"id": "pipeline", "title": "Pipeline (local tools)", "released": "2026-10-20",
         "where": "main", "summary": "Plans local work."}]}


class InventoryTest(unittest.TestCase):
    def test_pins_and_grouped_tools_are_all_listed_once(self):
        original = registry()
        before = json.dumps(original, sort_keys=True)
        items = releases.inventory(original)
        self.assertEqual(items, [
            {"id": "pipeline", "name": "Pipeline (local tools)",
             "url": "https://github.com/ChaseHendrick/Scrolls#pipeline-local-tools"},
            {"id": "kit", "name": "Example kit",
             "url": "https://github.com/ChaseHendrick/Scrolls#example-kit"},
            {"id": "sampler", "name": "Sample | inspect",
             "url": "https://github.com/ChaseHendrick/Scrolls/blob/main/docs/tools/sampler.md"}])
        self.assertEqual(json.dumps(original, sort_keys=True), before)

    def test_table_escapes_pipes_and_full_readme_contains_inventory(self):
        table = releases.render_inventory(releases.inventory(registry()))
        self.assertIn("| Sample \\| inspect | [Open](https://github.com/", table)
        self.assertIn(table, releases.render(registry()))
        self.assertEqual(len(table.splitlines()), 5)

    def test_invalid_registry_is_rejected_before_render(self):
        broken = registry()
        broken["releases"][0]["tools"][0]["id"] = "pipeline"
        with self.assertRaises(releases.ReleaseListError):
            releases.inventory(broken)

    def test_inventory_cli_is_read_only_in_both_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.json"
            path.write_text(releases.dumps(registry()), encoding="utf-8")
            before = path.read_bytes()
            for flags in ([], ["--json"]):
                with self.subTest(flags=flags), redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(releases.main(["--list", str(path), "inventory", *flags]), 0)
                if flags:
                    self.assertEqual(json.loads(out.getvalue()), releases.inventory(registry()))
                else:
                    self.assertEqual(out.getvalue().rstrip(),
                                     releases.render_inventory(releases.inventory(registry())))
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(Path(tmp).iterdir()), [path])



if __name__ == "__main__":
    unittest.main()
