"""kit.accelbench: the correctness gate, synchronized ABBA timing, controls and receipts.

Every timing test uses an injected fake clock and a recording sync, never real elapsed time, so
none can flake on a busy machine. Device tests inject fake torch and kit.accel modules; the real
CUDA and MPS checks skip on a machine without them.
"""
import hashlib
import importlib.util
import json
import operator
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from kit import accelbench as B

ROOT = Path(__file__).resolve().parent.parent
HAVE_NP = importlib.util.find_spec('numpy') is not None
HAVE_TORCH = importlib.util.find_spec('torch') is not None
CLEAN_GIT = {'commit': '0' * 40, 'dirty': False, 'dirty_paths': [], 'files_sha256': {}}


class Bench:
    """A fake clock, a recording sync and arms that advance the clock by a given cost per call."""

    def __init__(self):
        self.t = 0.0
        self.events = []
        self.calls = {}

    def clock(self):
        self.events.append('clock')
        return self.t

    def sync(self):
        self.events.append('sync')

    def arm(self, label, costs, output, default=0.0):
        queue = list(costs)
        self.calls[label] = 0

        def fn(*args, **kwargs):
            self.events.append(label)
            self.calls[label] += 1
            self.t += queue.pop(0) if queue else default
            return output(self.calls[label]) if callable(output) else output
        fn.__qualname__ = f'arm_{label}'
        return fn


def run(bench, reference, candidate, **kw):
    kw.setdefault('clock', bench.clock)
    kw.setdefault('sync', bench.sync)
    with mock.patch.object(B, 'git_state', return_value=dict(CLEAN_GIT)):
        return B.benchmark(reference, candidate, **kw)


def fake_accel(available=('cuda', 'mps'), calls=None, resolved=None):
    """A stand-in for kit/accel.py with its resolve_device, device_type and synchronize."""
    mod = types.ModuleType('kit.accel')
    calls = [] if calls is None else calls

    def device_type(device):
        return str(device).split(':', 1)[0]

    def resolve_device(name):
        kind = device_type(name)
        if kind not in ('cpu', 'cuda', 'mps'):
            raise ValueError(f'unsupported device {name!r}')
        if kind != 'cpu' and kind not in available:
            raise ValueError(f'{name} requested but this torch cannot use it')
        return resolved or name

    def synchronize(device):
        calls.append(device)
    mod.device_type, mod.resolve_device, mod.synchronize = device_type, resolve_device, synchronize
    return mod, calls


def without_warnings(problems):
    return [p for p in problems if not p.startswith('warning:')]


@unittest.skipUnless(HAVE_NP, 'numpy not installed')
class GateTest(unittest.TestCase):
    def test_faster_wrong_candidate_is_refused(self):
        import numpy as np
        want = np.arange(12, dtype=np.float32)
        wrong = want.copy()
        wrong[5] += np.float32(1e-3)
        ints = [1, 2, 3, 4]
        for reference_out, candidate_out in ((want, wrong), (ints, [1, 2, 4, 4])):
            bench = Bench()
            reference = bench.arm('R', [], reference_out, default=10.0)
            candidate = bench.arm('C', [], candidate_out, default=1.0)
            r = run(bench, reference, candidate)
            self.assertEqual(r['status'], 'refused-mismatch')
            for key in ('speedup', 'speedup_median', 'speedup_paired_median', 'timing', 'post_check'):
                self.assertIsNone(r[key], key)
            self.assertEqual(B.check_receipt(r), [])
            self.assertEqual(bench.calls['C'], 1)                        # never timed
            self.assertNotIn('clock', bench.events)
            self.assertEqual(r['comparison']['different_elements'], 1)
            self.assertTrue(r['control']['failed_as_required'])

    def test_exact_candidate_reports_speedup_from_min(self):
        import numpy as np
        out = np.linspace(0, 1, 7)
        bench = Bench()
        warm = [0.0] * 4                                                 # correctness call and 3 warm-up calls
        reference = bench.arm('R', warm + [5, 4, 6, 4, 5, 4, 5], out)
        candidate = bench.arm('C', warm + [2, 3, 2, 2, 3, 2, 2], out.copy())
        r = run(bench, reference, candidate, warmup=3, repeats=7)
        self.assertEqual(r['status'], 'pass')
        self.assertEqual(r['timing']['reference']['seconds'], [5, 4, 6, 4, 5, 4, 5])
        self.assertEqual(r['speedup'], 2.0)                              # 4 / 2
        self.assertEqual(r['speedup_median'], 2.5)                       # 5 / 2
        paired = sorted([5 / 2, 4 / 3, 6 / 2, 4 / 2, 5 / 3, 4 / 2, 5 / 2])[3]
        self.assertEqual(r['speedup_paired_median'], paired)
        self.assertEqual(paired, 2.0)
        self.assertEqual(B.check_receipt(r), [])
        self.assertEqual(r['timing']['reference']['spread'], (6 - 4) / 5)

    def test_every_clock_read_follows_a_sync(self):
        for number in (1, 2):
            bench = Bench()
            reference = bench.arm('R', [], 1.0, default=3.0)
            candidate = bench.arm('C', [], 1.0, default=1.0)
            warmup, repeats = 3, 5
            r = run(bench, reference, candidate, warmup=warmup, repeats=repeats, number=number)
            self.assertEqual(r['status'], 'pass')
            ev = bench.events
            clocks = [i for i, e in enumerate(ev) if e == 'clock']
            self.assertEqual(len(clocks), 2 * 2 * repeats)               # two reads per sample
            self.assertTrue(all(ev[i - 1] == 'sync' for i in clocks))
            first = clocks[0]
            self.assertEqual(ev[:first - 1], ['R', 'sync', 'C', 'sync'] * (1 + warmup))
            self.assertEqual(bench.calls, {'R': 1 + warmup + repeats * number, 'C': 1 + warmup + repeats * number})
            for start, end in zip(clocks[::2], clocks[1::2]):
                inside = ev[start + 1:end]
                self.assertEqual(inside[-1], 'sync')
                self.assertEqual(len(inside) - 1, number)
                self.assertEqual(len(set(inside[:-1])), 1)
            self.assertEqual(r['timing']['candidate']['min_s'], 1.0)    # per call, not per sample

    def test_abba_order(self):
        bench = Bench()
        reference = bench.arm('R', [], 0, default=1.0)
        candidate = bench.arm('C', [], 0, default=1.0)
        run(bench, reference, candidate, warmup=2, repeats=7)
        first = bench.events.index('clock')
        timed = [e for e in bench.events[first:] if e in ('R', 'C')]
        self.assertEqual(''.join(timed), 'RC' 'CR' 'RC' 'CR' 'RC' 'CR' 'RC')

    def test_setup_runs_outside_the_timed_region(self):
        bench = Bench()
        made = []

        def setup():
            bench.events.append('setup')
            made.append(1)
            return ([3],), {}
        mutate = bench.arm('R', [], 0, default=1.0)

        def reference(xs):
            mutate()
            xs.append(0)                                                 # changes its input
            return len(xs)
        r = run(bench, reference, reference, setup=setup, warmup=2, repeats=5)
        self.assertEqual(r['status'], 'pass')                            # fresh inputs each call
        self.assertEqual(len(made), 2 + 2 * 2 + 2 * 5)
        ev = bench.events
        for start, end in zip([i for i, e in enumerate(ev) if e == 'clock'][::2],
                              [i for i, e in enumerate(ev) if e == 'clock'][1::2]):
            self.assertNotIn('setup', ev[start:end])
        t = B.time_callable(reference, setup=setup, warmup=2, repeats=5, clock=bench.clock, sync=bench.sync)
        self.assertEqual(t['repeats'], 5)
        self.assertEqual(len(t['seconds']), 5)

    def test_time_callable_syncs_and_summarises(self):
        bench = Bench()
        fn = bench.arm('F', [0, 0, 3, 1, 2, 5, 4], 0)
        t = B.time_callable(fn, warmup=2, repeats=5, clock=bench.clock, sync=bench.sync)
        self.assertEqual(t['seconds'], [3, 1, 2, 5, 4])
        self.assertEqual((t['min_s'], t['median_s'], t['max_s'], t['mean_s']), (1, 3, 5, 3))
        self.assertEqual(t['spread'], 4 / 3)
        ev = bench.events
        self.assertEqual(ev[:4], ['F', 'sync', 'F', 'sync'])
        self.assertTrue(all(ev[i - 1] == 'sync' for i, e in enumerate(ev) if e == 'clock'))
        self.assertIn('Bench.sync', t['sync'])
        self.assertEqual(B.time_callable(fn, warmup=0, repeats=5, clock=bench.clock)['sync'], 'none (cpu)')

    def test_loose_tolerance_control_is_invalid(self):
        import numpy as np
        out = np.ones(4)
        bench = Bench()
        reference = bench.arm('R', [], out, default=2.0)
        candidate = bench.arm('C', [], out.copy(), default=1.0)
        r = run(bench, reference, candidate, atol=1.0, control=lambda o: o + 0.1)
        self.assertEqual(r['status'], 'invalid-control')
        self.assertTrue(r['comparison']['pass'])
        self.assertFalse(r['control']['failed_as_required'])
        self.assertEqual(r['control']['kind'], 'caller')
        self.assertIsNone(r['speedup'])
        self.assertIsNone(r['timing'])
        self.assertEqual(B.check_receipt(r), [])
        for value, kw in ((1.5, {}), (np.float32(2.0), {'atol': 0.25}), (np.arange(3, dtype=np.float16), {'rtol': 0.1}),
                          (7, {}), (np.array([255], dtype=np.uint8), {}), ([True, False], {}), (np.array([True]), {}),
                          ({'a': ('x', 2.0), 'b': 1}, {'atol': 0.5}), (float('nan'), {'equal_nan': True}),
                          (np.array([np.inf, 1e300]), {'rtol': 1.0}), (complex(1, 2), {'atol': 0.1})):
            moved = B._perturb(value, kw.get('atol', 0.0), kw.get('rtol', 0.0))
            self.assertFalse(B.compare_outputs(value, moved, **kw)['pass'], (value, kw))
            self.assertTrue(B.compare_outputs(value, value, **kw)['pass'], (value, kw))
        with self.assertRaises(ValueError):
            B._perturb('text')
        bench = Bench()
        with self.assertRaises(ValueError):
            run(bench, bench.arm('R', [], 'text'), bench.arm('C', [], 'text'))
        r = run(Bench(), Bench().arm('R', [], 'text'), Bench().arm('C', [], 'text'), control=None)
        self.assertEqual(r['status'], 'pass')
        self.assertIsNone(r['control']['kind'])
        self.assertEqual(B.check_receipt(r), ['warning: no control was run'])

    def test_perturb_leaves_the_reference_alone(self):
        import numpy as np
        ref = {'a': np.zeros(3), 'b': [1.0, 2]}
        moved = B._perturb(ref)
        self.assertEqual(ref['a'].tolist(), [0.0, 0.0, 0.0])
        self.assertEqual(ref['b'], [1.0, 2])
        self.assertIsNot(moved['a'], ref['a'])
        self.assertIs(moved['b'], ref['b'])                              # off the path: shared, not copied

    def test_unstable_candidate_refused(self):
        bench = Bench()
        reference = bench.arm('R', [], 2.0, default=3.0)
        candidate = bench.arm('C', [], lambda n: 2.0 if n == 1 else 2.5, default=1.0)
        r = run(bench, reference, candidate)
        self.assertEqual(r['status'], 'refused-unstable')
        self.assertTrue(r['comparison']['pass'])
        self.assertFalse(r['post_check']['pass'])
        self.assertIsNone(r['speedup'])
        self.assertIsNotNone(r['timing'])
        self.assertEqual(B.check_receipt(r), [])

    def test_argument_bounds(self):
        bench = Bench()
        f = bench.arm('R', [], 1.0)
        for kw in ({'repeats': 4}, {'number': 0}, {'warmup': -1}, {'atol': float('nan')}, {'rtol': -1.0},
                   {'atol': 0.1, 'bitwise': True}, {'repeats': 7.0}, {'control': 'other'}, {'device': 'auto'}):
            with self.assertRaises(ValueError, msg=kw):
                run(bench, f, f, **kw)
        for kw in ({'repeats': 4}, {'number': 0}, {'warmup': -1}):
            with self.assertRaises(ValueError, msg=kw):
                B.time_callable(f, clock=bench.clock, sync=bench.sync, **kw)
        with self.assertRaises(ValueError):
            B.compare_outputs(1.0, 1.0, atol=float('inf'))
        self.assertEqual(bench.calls['R'], 0)


@unittest.skipUnless(HAVE_NP, 'numpy not installed')
class CompareTest(unittest.TestCase):
    def test_tolerance_boundaries(self):
        import numpy as np
        eps = 2.0 ** -20
        for wrap in (float, lambda v: np.array([v])):
            self.assertTrue(B.compare_outputs(wrap(1.0), wrap(1.5), atol=0.5)['pass'])
            self.assertFalse(B.compare_outputs(wrap(1.0), wrap(1.5 + eps), atol=0.5)['pass'])
            self.assertTrue(B.compare_outputs(wrap(2.0), wrap(3.0), rtol=0.5)['pass'])
            self.assertFalse(B.compare_outputs(wrap(2.0), wrap(3.0 + eps), rtol=0.5)['pass'])
            self.assertTrue(B.compare_outputs(wrap(-2.0), wrap(-1.0), rtol=0.5)['pass'])
            self.assertTrue(B.compare_outputs(wrap(0.0), wrap(-0.0))['pass'])
            self.assertFalse(B.compare_outputs(wrap(0.0), wrap(-0.0), bitwise=True)['pass'])
            self.assertFalse(B.compare_outputs(wrap(1.0), wrap(1.0 + 2 ** -52))['pass'])
        nan = np.array([np.nan])
        self.assertTrue(B.compare_outputs(nan, nan.copy(), bitwise=True)['pass'])    # identical NaN bits
        self.assertTrue(B.compare_outputs(float('nan'), float('nan'), bitwise=True)['pass'])
        with self.assertRaises(ValueError):
            B.compare_outputs(1.0, 1.0, atol=0.5, bitwise=True)
        r = B.compare_outputs(np.array([1.0, 2.0, 4.0]), np.array([1.0, 2.5, 4.0]))
        self.assertEqual((r['different_leaves'], r['different_elements'], r['max_abs_diff']), (1, 1, 0.5))
        self.assertEqual(r['max_rel_diff'], 0.25)
        self.assertEqual(r['differences'][0]['path'], 'output')
        self.assertEqual(B.compare_outputs(np.array([3]), np.array([3.4]), atol=0.5, check_dtype=False)['pass'], False)

    def test_fail_closed_on_type_shape_dtype_nan(self):
        import numpy as np
        a32 = np.array([1.0, 2.0], dtype=np.float32)
        self.assertFalse(B.compare_outputs(a32, a32.astype(np.float64))['pass'])
        self.assertTrue(B.compare_outputs(a32, a32.astype(np.float64), check_dtype=False)['pass'])
        self.assertFalse(B.compare_outputs(a32, a32.astype(np.float64), check_dtype=False, bitwise=True)['pass'])
        self.assertFalse(B.compare_outputs(a32, a32.reshape(1, 2))['pass'])
        self.assertFalse(B.compare_outputs([1, 2], (1, 2))['pass'])
        self.assertFalse(B.compare_outputs({'a': 1}, {'b': 1})['pass'])
        self.assertFalse(B.compare_outputs({'a': 1}, {'a': 1, 'b': 2})['pass'])
        self.assertFalse(B.compare_outputs([1, 2], [1, 2, 3])['pass'])
        self.assertFalse(B.compare_outputs(1, 1.0)['pass'])
        self.assertFalse(B.compare_outputs(True, 1)['pass'])
        self.assertFalse(B.compare_outputs(np.float32(1), np.array(1, dtype=np.float32))['pass'])
        self.assertFalse(B.compare_outputs(object(), object())['pass'])
        nan = np.array([np.nan, 1.0])
        self.assertFalse(B.compare_outputs(nan, nan.copy())['pass'])
        self.assertTrue(B.compare_outputs(nan, nan.copy(), equal_nan=True)['pass'])
        self.assertFalse(B.compare_outputs(nan, np.array([1.0, 1.0]), equal_nan=True, atol=1e9)['pass'])
        self.assertFalse(B.compare_outputs(float('nan'), float('nan'))['pass'])
        self.assertFalse(B.compare_outputs(np.array([np.inf]), np.array([-np.inf]), atol=1e9)['pass'])
        self.assertFalse(B.compare_outputs(float('inf'), 1e308, rtol=1.0)['pass'])
        self.assertTrue(B.compare_outputs(np.array([np.inf]), np.array([np.inf]))['pass'])
        r = B.compare_outputs({'x': [np.zeros(2), 3]}, {'x': [np.ones(2), 4]})
        self.assertEqual([d['path'] for d in r['differences']], ["output['x'][0]", "output['x'][1]"])
        self.assertEqual(len(B.compare_outputs(list(range(50)), [i + 1 for i in range(50)], max_reported=4)
                             ['differences']), 4)
        if HAVE_TORCH:
            import torch
            self.assertFalse(B.compare_outputs(torch.ones(2), np.ones(2, dtype=np.float32))['pass'])


@unittest.skipUnless(HAVE_NP, 'numpy not installed')
class ReceiptTest(unittest.TestCase):
    def receipt(self):
        import numpy as np
        bench = Bench()
        out = np.arange(5, dtype=np.float32)
        return run(bench, bench.arm('R', [], out, default=2.0), bench.arm('C', [], out.copy(), default=1.0),
                   name='round trip', sizes={'patch': [17, 128, 128]})

    def test_receipt_round_trip(self):
        r = self.receipt()
        self.assertEqual(r['status'], 'pass')
        self.assertEqual(r['speedup'], 2.0)
        self.assertEqual(r['sizes']['patch'], [17, 128, 128])
        self.assertEqual(r['dtype'], None)                              # no floating input leaf
        r['extra'] = [float('nan'), float('inf'), 1.5]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sub' / 'r.json'
            self.assertEqual(B.write_receipt(r, path), path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            back = json.loads(path.read_text())
            self.assertEqual(back['extra'], [None, None, 1.5])
            self.assertEqual(back, B._jsonable(r))
            with self.assertRaises(FileExistsError):
                B.write_receipt(r, path)
            B.write_receipt(r, path, overwrite=True)
            self.assertEqual(sorted(os.listdir(path.parent)), ['r.json'])   # no temporary file left
        del r['extra']
        self.assertEqual(B.check_receipt(r), [])
        edited = json.loads(json.dumps(B._jsonable(r)))
        edited['speedup'] = 2.2
        self.assertTrue(any(p.startswith('speedup ') for p in B.check_receipt(edited)))
        edited = json.loads(json.dumps(B._jsonable(r)))
        edited['timing']['candidate']['min_s'] = 0.5
        self.assertTrue(B.check_receipt(edited))
        edited = json.loads(json.dumps(B._jsonable(r)))
        edited['comparison']['pass'] = False
        self.assertIn('pass without a passing comparison', B.check_receipt(edited))
        edited = json.loads(json.dumps(B._jsonable(r)))
        edited['settings']['repeats'] = 3
        self.assertTrue(B.check_receipt(edited))
        edited = json.loads(json.dumps(B._jsonable(r)))
        edited['status'] = 'refused-mismatch'
        self.assertTrue(B.check_receipt(edited))
        edited = dict(r, git={'commit': None, 'dirty': True})
        self.assertEqual(B.check_receipt(edited), ['warning: no git commit recorded',
                                                   'warning: the source tree differed from its commit'])
        self.assertEqual(B.check_receipt([]), ['receipt is not a mapping'])

    def test_timing_receipt_has_no_speedup(self):
        bench = Bench()
        t1 = B.time_callable(bench.arm('A', [], 0, default=1.0), clock=bench.clock, sync=bench.sync)
        t2 = B.time_callable(bench.arm('B', [], 0, default=2.0), clock=bench.clock, sync=bench.sync)
        with mock.patch.object(B, 'git_state', return_value=dict(CLEAN_GIT)):
            r = B.timing_receipt('variants', {'a': t1, 'b': t2}, dtype='float32')
        self.assertEqual(r['status'], 'timing-only')
        self.assertFalse(set(B.SPEEDUP_KEYS) & set(r))
        self.assertEqual(B.check_receipt(r), [])
        r['speedup'] = 2.0
        self.assertTrue(B.check_receipt(r))
        with self.assertRaises(ValueError):
            B.timing_receipt('x', {'a': dict(t1, repeats=3)})

    def test_git_state(self):
        rel = 'kit/accelbench.py'
        g = B.git_state(ROOT, [rel, 'no/such/file'])
        if (ROOT / '.git').exists():                                     # a clone or a worktree, not an export
            self.assertIsNotNone(g['commit'])
        if g['commit'] is not None:
            self.assertRegex(g['commit'], r'^[0-9a-f]{40}$')
            self.assertIn(g['dirty'], (True, False))
        self.assertEqual(g['files_sha256'][rel], hashlib.sha256((ROOT / rel).read_bytes()).hexdigest())
        self.assertIsNone(g['files_sha256']['no/such/file'])
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'a.txt').write_text('x')
            g = B.git_state(tmp, ['a.txt'])
            self.assertEqual((g['commit'], g['dirty']), (None, None))
            self.assertEqual(g['files_sha256']['a.txt'], hashlib.sha256(b'x').hexdigest())
        with mock.patch.object(B.subprocess, 'run', side_effect=FileNotFoundError('git')):
            self.assertIsNone(B.git_state(ROOT)['commit'])

    def test_environment(self):
        env = B.environment('cpu')
        self.assertEqual(env['device']['type'], 'cpu')
        self.assertEqual(env['logical_cpus'], os.cpu_count())
        self.assertIn('numpy', env['packages'])


class DeviceTest(unittest.TestCase):
    def test_sync_for_devices(self):
        s = B.sync_for('cpu')
        self.assertIsNone(s())
        self.assertEqual(s.description, 'none (cpu)')
        fake, calls = fake_accel()
        with mock.patch.dict(sys.modules, {'kit.accel': fake}):
            s = B.sync_for('cuda:1')
            s()
            self.assertEqual(calls, ['cuda:1'])
            self.assertEqual(s.description, 'kit.accel.synchronize(cuda:1)')
            B.sync_for('mps')()
            self.assertEqual(calls, ['cuda:1', 'mps'])
            for bad in ('xpu', 'auto', ''):
                with self.assertRaises(ValueError):
                    B.sync_for(bad)
        fake, _ = fake_accel(available=())
        with mock.patch.dict(sys.modules, {'kit.accel': fake}):
            for bad in ('cuda', 'mps'):
                with self.assertRaises(ValueError):
                    B.sync_for(bad)
        fake, _ = fake_accel(resolved='xpu:0')                         # a type kit.accel cannot wait on
        with mock.patch.dict(sys.modules, {'kit.accel': fake}):
            with self.assertRaises(ValueError):
                B.sync_for('cuda')
        with mock.patch.dict(sys.modules, {'kit.accel': None}):
            with self.assertRaisesRegex(ValueError, 'kit/accel.py'):
                B.sync_for('cuda')

    def test_sync_for_on_this_machine(self):
        cuda = mps = False
        if HAVE_TORCH:
            import torch
            cuda = torch.cuda.is_available()
            mps = bool(getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available())
        if not cuda:
            with self.assertRaises(ValueError):
                B.sync_for('cuda')
        if not mps:
            with self.assertRaises(ValueError):
                B.sync_for('mps')

    @unittest.skipUnless(HAVE_NP, 'numpy not installed')
    def test_cuda_receipt_with_fake_torch(self):
        """The CUDA path: kit.accel's sync before each clock read and each arm's peak bytes."""
        import numpy as np
        fake, calls = fake_accel()
        torch = types.ModuleType('torch')
        torch.Tensor = type('Tensor', (), {})
        torch.device = lambda name: types.SimpleNamespace(type='cuda', index=None)
        peaks = iter([100, 250])
        torch.cuda = types.SimpleNamespace(reset_peak_memory_stats=lambda device: None,
                                           max_memory_allocated=lambda device: next(peaks))
        bench = Bench()
        out = np.ones(3)
        with mock.patch.dict(sys.modules, {'kit.accel': fake, 'torch': torch}):
            r = run(bench, bench.arm('R', [], out, default=2.0), bench.arm('C', [], out.copy(), default=1.0),
                    device='cuda', sync=None, repeats=5)
        self.assertEqual(r['status'], 'pass')
        self.assertEqual(r['peak_device_bytes'], {'reference': 100, 'candidate': 250})
        self.assertEqual(r['settings']['sync'], 'kit.accel.synchronize(cuda)')
        self.assertEqual(len(calls), 2 + 2 * 3 + 2 * 2 * 5)
        self.assertEqual(r['environment']['device']['type'], 'cuda')

    def test_imports_without_numpy_or_torch(self):
        code = '\n'.join([
            'import sys',
            "sys.modules['numpy'] = None",
            "sys.modules['torch'] = None",
            'from kit import accelbench as B',
            "assert B.compare_outputs([1.0, [2, True], {'a': 'x'}, None], [1.0, [2, True], {'a': 'x'}, None])['pass']",
            'assert not B.compare_outputs([1.0, 2], [1.0, 3])["pass"]',
            "s = B.sync_for('cpu'); s()",
            "assert 'kit.accel' not in sys.modules",
            'r = B.benchmark(lambda xs: [x * 2.0 for x in xs], lambda xs: [x + x for x in xs], args=([1.0, 2.5],))',
            "assert r['status'] == 'pass', r['status']",
            "assert r['control']['failed_as_required'] is True",
            "assert sys.modules['numpy'] is None and sys.modules['torch'] is None",
            "print('ok')"])
        out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), 'ok')


@unittest.skipUnless(HAVE_NP and HAVE_TORCH, 'numpy and torch needed')
class TorchTest(unittest.TestCase):
    def test_tensors_and_a_real_cpu_benchmark(self):
        import numpy as np
        import torch
        for dtype in (torch.float32, torch.bfloat16):
            t = torch.linspace(-2, 2, 12, dtype=dtype).reshape(3, 4)
            self.assertTrue(B.compare_outputs(t, t.clone(), bitwise=True)['pass'])
            self.assertTrue(B.compare_outputs(t, t.t().contiguous().t())['pass'])       # strides ignored
            self.assertFalse(B.compare_outputs(t, B._perturb(t))['pass'])
            self.assertFalse(B.compare_outputs(t, B._perturb(t), bitwise=True)['pass'])
            self.assertFalse(B.compare_outputs(t, t.to(torch.float64))['pass'])
            self.assertTrue(B.compare_outputs(t, t.to(torch.float64), check_dtype=False)['pass'])
            z = torch.zeros(2, dtype=dtype)
            self.assertTrue(B.compare_outputs(z, -z)['pass'])
            self.assertFalse(B.compare_outputs(z, -z, bitwise=True)['pass'])
            self.assertFalse(B.compare_outputs(t, t.numpy() if dtype == torch.float32 else np.zeros((3, 4)))['pass'])
        r = B.compare_outputs(torch.tensor([1.0], dtype=torch.bfloat16), torch.tensor([1.0078125], dtype=torch.bfloat16))
        self.assertEqual(r['max_abs_diff'], 0.0078125)
        self.assertFalse(B.compare_outputs(torch.tensor([1, 2]), B._perturb(torch.tensor([1, 2])))['pass'])
        self.assertFalse(B.compare_outputs(torch.tensor([True]), B._perturb(torch.tensor([True])))['pass'])
        a, b = torch.randn(48, 48), torch.randn(48, 48)
        r = B.benchmark(operator.matmul, torch.matmul, args=(a, b), bitwise=True, repeats=5, warmup=1)
        self.assertEqual(r['status'], 'pass', r['reason'])
        for arm in ('reference', 'candidate'):
            self.assertLessEqual(r['timing'][arm]['min_s'], r['timing'][arm]['median_s'])
        self.assertEqual(r['dtype'], 'torch.float32')
        self.assertEqual(without_warnings(B.check_receipt(r)), [])
        self.assertEqual(r['sizes']['outputs']['reference']['shape'], [48, 48])

    def accel(self):
        if importlib.util.find_spec('kit.accel') is None:
            self.skipTest('kit/accel.py is not on this branch')

    def test_cuda_sync(self):
        import torch
        if not torch.cuda.is_available():
            self.skipTest('no CUDA device')
        self.accel()
        s = B.sync_for('cuda')
        self.assertEqual(s.description, 'kit.accel.synchronize(cuda)')
        s()

    def test_mps_sync(self):
        import torch
        if not (getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available()):
            self.skipTest('no MPS device')
        self.accel()
        s = B.sync_for('mps')
        self.assertEqual(s.description, 'kit.accel.synchronize(mps)')
        s()


if __name__ == '__main__':
    unittest.main()
