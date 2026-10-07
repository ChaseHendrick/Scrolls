"""Regression checks for the collector using committed historic score rows.

Run: python -m unittest discover -s scripts/experiments/2026-10-07-cloud/tricks -p test_collect.py -v
No source maps, inference, downloads or writes to the checkout are needed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


class CollectorRegression(unittest.TestCase):
    def test_preserves_saved_scores_and_labels_correlated_aggregation(self):
        historic = json.loads((HERE / 'results.json').read_text())
        by_segment = {}
        for row in historic:
            shuffled = row['map'].endswith('_shuf')
            values = [row.get('auc_shuffled') if shuffled else row.get('auc_as_stored'),
                      row.get('auc_reversed'),
                      row.get('hp_r_shuffled') if shuffled else row.get('hp_r'),
                      row.get('hp_r_reversed'), row['hp_null_max_abs']]
            by_segment.setdefault(row['segment'], {})[row['map']] = [values]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            score_dir = root / 'tricks'
            score_dir.mkdir()
            for segment, values in by_segment.items():
                (score_dir / f'scores_{segment}.json').write_text(json.dumps(values))
            collector = root / 'collect.py'
            shutil.copyfile(HERE / 'collect.py', collector)
            result = subprocess.run([sys.executable, str(collector)],
                                    env={**os.environ, 'S': str(root)}, cwd=root,
                                    capture_output=True, text=True, check=True)
            regenerated = json.loads((root / 'results.json').read_text())
            self.assertEqual(len(regenerated), len(historic))
            saved = {(r['segment'], r['map']): r for r in historic}
            numeric_fields = ('auc_as_stored', 'auc_reversed', 'auc_shuffled',
                              'hp_r', 'hp_r_reversed', 'hp_r_shuffled', 'hp_null_max_abs')
            for row in regenerated:
                expected = saved[row['segment'], row['map']]
                for field in numeric_fields:
                    self.assertEqual(row.get(field), expected.get(field),
                                     (row['segment'], row['map'], field))
            table = (root / 'tables.md').read_text()
            self.assertEqual(table, result.stdout)
            self.assertIn('one shared sheet', table)
            self.assertIn('not independent replications', table)
            self.assertIn('uncertainty in the differences was not measured', table)
            self.assertIn('default 0.7821 / +0.0150', table)
            self.assertIn('4-window mean 0.8199 / +0.0166', table)
            self.assertNotIn('run noise of 0.005', table)


if __name__ == '__main__':
    unittest.main()
