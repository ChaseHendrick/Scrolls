import contextlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kit import cli, ledger, localcost


class LocalCostRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.root = self.path / 'experiments'
        ledger.save({'slug': 't1', 'status': 'planned', 'history': [], 'costs': [], 'scroll': 's'}, self.root)
        self.config = self.path / 'local.json'
        self.config.write_text('{}')
        self.env = mock.patch.dict(os.environ, {localcost.ENV_CONFIG: str(self.config)})
        self.env.start()
        os.environ.pop(localcost.ENV_RATE, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_wrapper_options_and_child_arguments_survive_python310_parser(self):
        out = self.path / 'arguments.json'
        child = [sys.executable, '-c', 'import json,sys;open(sys.argv[1],"w").write(json.dumps(sys.argv[2:]))',
                 str(out), '--watts', '999', 'literal space', '--', '$(not executed)']
        with contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(['run', '--root', str(self.root), 'local', 't1', '--rate', '.25',
                             '--watts', '12', '--', *child])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.read_text()), child[4:])
        item = ledger.load('t1', self.root)['costs'][0]['local']
        self.assertEqual(item['command_argv'], child)
        self.assertEqual(item['watts'], 12)

    def test_invalid_rate_and_watts_fail_before_child_launch(self):
        bad = [float('nan'), float('inf'), -1, 'not-a-number', True, {}]
        for field in ('rate', 'watts'):
            for value in bad:
                with self.subTest(field=field, value=value), mock.patch.object(localcost.subprocess, 'call') as call:
                    kw = {'rate': .25, 'watts': 30};kw[field] = value
                    with self.assertRaises(localcost.CostError):
                        localcost.run('t1', [sys.executable, '-c', 'pass'], root=self.root, **kw)
                    call.assert_not_called()
        self.assertEqual(ledger.load('t1', self.root)['costs'], [])

    def test_config_schema_missing_override_and_invalid_device_watts(self):
        for text in ('[]', 'null', '{bad JSON'):
            self.config.write_text(text)
            with self.assertRaises(localcost.CostError):
                localcost.load_config()
        self.config.unlink()
        with self.assertRaises(localcost.CostError):
            localcost.load_config()
        for cfg in ({'device_watts': []}, {'device_watts': {'x86-cpu': float('inf')}}, {'device': []}):
            with self.assertRaises(localcost.CostError):
                localcost.resolve_watts(config=cfg)

    def test_subcent_estimates_are_aggregated_before_cent_rounding(self):
        items = [{'what': str(i), 'wall_s': 1200, 'watts': 30} for i in range(100)]
        _, usd = localcost.backfill('t1', items, root=self.root, rate=.1)
        record = ledger.load('t1', self.root)
        self.assertEqual(usd, .1)
        self.assertEqual(ledger.total_cost(record), .1)
        self.assertTrue(all(c['usd'] == .001 for c in record['costs']))
        self.assertEqual(len(record['costs']), 100)

    def test_invalid_backfill_tail_never_partially_commits(self):
        path = ledger.path_for('t1', self.root)
        before = path.read_bytes()
        good = {'what': 'good', 'wall_s': 3600, 'watts': 30}
        for bad in ({'what': 'bad', 'wall_s': -1}, {'what': 'bad', 'wall_s': float('nan')},
                    {'what': 'bad', 'wall_s': 2, 'watts': -3}, {}, 'bad'):
            with self.assertRaises(localcost.CostError):
                localcost.backfill('t1', [good, bad], root=self.root, rate=.1)
            self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(localcost.CostError):
            localcost.backfill('t1', {}, root=self.root, rate=.1)

    def test_invalid_backfill_file_returns_cli_error(self):
        f = self.path / 'backfill.json';f.write_text('{bad JSON')
        with contextlib.redirect_stderr(io.StringIO()) as error:
            code = cli.main(['run', '--root', str(self.root), 'backfill', 't1', '--file', str(f), '--rate', '.1'])
        self.assertEqual(code, 2)
        self.assertIn('cannot read backfill', error.getvalue())
        self.assertEqual(ledger.load('t1', self.root)['costs'], [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX signal return convention')
    def test_signalled_child_is_logged_and_returns_shell_status(self):
        child = [sys.executable, '-c', 'import os,signal;os.kill(os.getpid(),signal.SIGTERM)']
        code, item = localcost.run('t1', child, root=self.root, rate=.1)
        self.assertEqual(code, 143)
        self.assertEqual(item['exit_code'], 143)
        self.assertEqual(item['raw_returncode'], -15)
        self.assertEqual(item['signal'], 15)
        self.assertEqual(len(ledger.load('t1', self.root)['costs']), 1)

    def test_launch_failure_records_attempt_and_exit127(self):
        code, item = localcost.run('t1', [str(self.path / 'missing-executable')], root=self.root, rate=.1)
        self.assertEqual(code, 127)
        self.assertEqual(item['exit_code'], 127)
        self.assertIn('launch_error', item)
        self.assertTrue(math.isfinite(item['usd_exact']))

    def test_unavailable_resource_counter_does_not_break_cli(self):
        with mock.patch.object(localcost, 'resource', None), contextlib.redirect_stderr(io.StringIO()) as message:
            code = cli.main(['run', '--root', str(self.root), 'local', 't1', '--rate', '.1',
                             '--', sys.executable, '-c', 'pass'])
        self.assertEqual(code, 0)
        self.assertIsNone(ledger.load('t1', self.root)['costs'][0]['local']['cpu_s'])
        self.assertIn('unavailable CPU', message.getvalue())

    @unittest.skipIf(localcost.fcntl is None, 'POSIX local-cost writer lock')
    def test_concurrent_cost_writers_preserve_every_entry(self):
        script = ('import sys;from pathlib import Path;from kit import localcost;'
                  'items=[{"what":sys.argv[2]+":"+str(i),"wall_s":3600,"watts":30} for i in range(10)];'
                  'localcost.backfill("t1",items,root=Path(sys.argv[1]),rate=.1)')
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.root), str(i)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
        for process in processes:
            out, error = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, out + error)
        costs = ledger.load('t1', self.root)['costs']
        self.assertEqual(len(costs), 40)
        self.assertEqual(len({c['what'] for c in costs}), 40)
        self.assertEqual(ledger.total_cost({'costs': costs}), .12)

    def test_failed_atomic_replace_preserves_original_ledger(self):
        path = ledger.path_for('t1', self.root);before = path.read_bytes()
        with mock.patch.object(localcost.os, 'replace', side_effect=OSError('test write failure')):
            with self.assertRaises(OSError):
                localcost.backfill('t1', [{'what': 'a', 'wall_s': 3600}], root=self.root, rate=.1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob('.local-cost-*')), [])


if __name__ == '__main__':
    unittest.main()
