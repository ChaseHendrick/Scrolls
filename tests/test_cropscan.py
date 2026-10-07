"""Crop scans must use the same populations and exact scores as direct crop scoring."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from kit import cropscan, verify

try:
    import numpy as np
    from kit import auc
except ImportError:
    np = None


@unittest.skipIf(np is None, 'numpy is needed for crop scans')
class CropScan(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(20261007)
        self.ink = self.rng.random((25, 33)) > .55
        self.mask = np.ones(self.ink.shape, bool)
        self.mask[6:10, 9:13] = False

    def assert_direct(self, prediction, inner=0, bins=65536, keep_zero=False):
        before = [a.copy() for a in (prediction, self.ink, self.mask)]
        rows = cropscan.scan(prediction, self.ink, self.mask, window=16, stride=8,
                             inner=inner, tile=4, bins=bins, min_supervised=0,
                             min_class=0, keep_zero=keep_zero)
        # All full grid windows, including those next to non-tile-sized canvas edges.
        expected_crops = [[y, y+16, x, x+16] for y in range(0, 10, 8) for x in range(0, 18, 8)]
        self.assertEqual([r['crop'] for r in rows], expected_crops)
        for row in rows:
            y0,y1,x0,x1 = row['crop']
            direct = auc.score_array(prediction[y0:y1,x0:x1], self.ink[y0:y1,x0:x1],
                                     self.mask[y0:y1,x0:x1], inner=inner, keep_zero=keep_zero)
            self.assertEqual(row['auc'], direct['auc'])
            self.assertEqual(row['ink_px'], direct['ink_px'])
            self.assertEqual(row['background_px'], direct['background_px'])
        for actual, saved in zip((prediction,self.ink,self.mask),before):
            np.testing.assert_array_equal(actual,saved)

    def test_exact_normalized_float_and_uint16_match_direct_crops_with_holes(self):
        for prediction in (self.rng.random(self.ink.shape).astype(np.float32),
                           self.rng.integers(0,65536,self.ink.shape,dtype=np.uint16)):
            prediction[2:7,:6] = 0
            # Larger tile keeps the full-resolution histogram fixtures small.
            rows = cropscan.scan(prediction,self.ink,self.mask,window=24,stride=8,
                                 inner=8,tile=8,bins=65536,min_supervised=0,min_class=0)
            for row in rows:
                y0,y1,x0,x1=row['crop']
                direct=auc.score_array(prediction[y0:y1,x0:x1],self.ink[y0:y1,x0:x1],
                                       self.mask[y0:y1,x0:x1],inner=8)
                self.assertEqual((row['auc'],row['ink_px'],row['background_px']),
                                 (direct['auc'],direct['ink_px'],direct['background_px']))

    def test_uint8_keeps_all_levels_at_256_bins_and_separate_zero_policy(self):
        pred=self.rng.integers(0,256,self.ink.shape,dtype=np.uint8)
        pred[:4]=0
        for bins in (256,4096,65536):
            self.assert_direct(pred,bins=bins)
        self.assert_direct(pred,bins=256,inner=4,keep_zero=True)

    def test_coverage_and_class_gates_do_not_turn_missing_scores_into_evidence(self):
        pred=np.full(self.ink.shape,.25)
        self.mask[:]=False
        rows=cropscan.scan(pred,self.ink,self.mask,window=16,stride=8,tile=4,inner=0)
        self.assertTrue(all(r['auc'] is None and r['ink_px']==0 and r['background_px']==0 for r in rows))
        self.mask[:]=True;self.ink[:]=False
        rows=cropscan.scan(pred,self.ink,self.mask,window=16,stride=8,tile=4,inner=0)
        self.assertTrue(all(r['auc'] is None and r['ink_px']==0 for r in rows))
        self.ink[:8]=True
        self.assert_direct(pred,bins=256)

    def test_no_full_window_returns_empty_without_histogram_allocation(self):
        with patch.object(np,'bincount',side_effect=AssertionError('unexpected histogram')):
            self.assertEqual(cropscan.scan(np.ones((2,3)),np.zeros((2,3),bool),np.ones((2,3),bool)),[])

    def test_bad_shapes_types_values_and_parameters_are_refused(self):
        pred=np.ones(self.ink.shape,dtype=np.float32)
        bad=[{'tile':0},{'tile':-1},{'window':0},{'stride':0},{'stride':1.5},
             {'inner':-1},{'inner':32},{'bins':1},{'bins':65537},{'window':18},
             {'min_supervised':float('nan')},{'min_supervised':1.01},
             {'min_class':float('inf')},{'min_class':-.1},{'min_class':.51},
             {'max_work_bytes':0},{'keep_zero':'false'}]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs),self.assertRaises(verify.VerifyError):
                cropscan.scan(pred,self.ink,self.mask,**kwargs)
        for value in (np.nan,np.inf,-.1,1.1,256.):
            changed=pred.copy();changed[0,0]=value
            with self.assertRaises(verify.VerifyError):
                cropscan.scan(changed,self.ink,self.mask)
        with self.assertRaises(verify.VerifyError):
            cropscan.scan(pred,self.ink.astype(np.uint8),self.mask)
        with self.assertRaises(verify.VerifyError):
            cropscan.scan(pred[None],self.ink[None],self.mask[None])
        with self.assertRaises(verify.VerifyError):
            cropscan.scan(pred,self.ink[:-1],self.mask)

    def test_memory_guard_precedes_histogram_allocation(self):
        pred=np.ones((64,64),np.float32)
        with patch.object(np,'bincount',side_effect=AssertionError('unexpected allocation')):
            with self.assertRaisesRegex(verify.VerifyError,'estimated work'):
                cropscan.scan(pred,np.zeros_like(pred,dtype=bool),np.ones_like(pred,dtype=bool),
                              window=8,stride=8,tile=1,inner=0,bins=65536)


class HistoricalLaneI(unittest.TestCase):
    def test_default_guard_refuses_before_numpy_or_data_access(self):
        root=Path(__file__).resolve().parents[1]
        script=root/'scripts/experiments/2026-10-07-grok-laneI/run.py'
        guard=script.read_text().split('import glob, json, sys, time',1)[0]
        env=dict(os.environ);env.pop('SCROLLS_REPLAY_HISTORICAL_LANEI',None)
        with tempfile.TemporaryDirectory() as temp:
            run=subprocess.run([os.sys.executable,'-S','-c',guard+'\nraise SystemExit(97)'],
                               cwd=temp,env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,1)
            self.assertIn('Archival run only',run.stderr)
            self.assertIn('nonfinite bootstrap intervals',run.stderr)
            self.assertEqual(list(Path(temp).iterdir()),[])


if __name__=='__main__':
    unittest.main()
