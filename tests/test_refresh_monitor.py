#!/usr/bin/env python3
"""実更新関数と監視ヘルパーの状態遷移・ログ上限を検査する（#106）。"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def shell_function(name):
    match = re.search(r'^' + name + r'\(\) \{\n.*?^\}',
                      (ROOT / 'init-firewall.sh').read_text(), re.M | re.S)
    if not match:
        raise AssertionError(name)
    return match[0]


class RefreshResultTests(unittest.TestCase):
    def test_cycle_reports_partial_failure_but_still_prunes(self):
        for refresh_rc, prune_rc, expected in ((0, 0, 0), (1, 0, 75), (0, 1, 75), (1, 1, 75)):
            with self.subTest(refresh=refresh_rc, prune=prune_rc):
                script = f'''set -euo pipefail
GRACE_WINDOW_SECONDS=180
refresh_domains() {{ return {refresh_rc}; }}
prune_stale_domain_rules() {{ echo PRUNED; return {prune_rc}; }}
'''
                result = subprocess.run(['bash', '-c', script + shell_function('do_refresh') + '\ndo_refresh'],
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn('PRUNED', result.stdout)

    def test_prune_listing_and_delete_errors_are_reported(self):
        for mode in ('list', 'delete'):
            with self.subTest(mode=mode):
                script = f'''set -euo pipefail
CHAIN=CLAUDE_EGRESS
iptables() {{
  if [[ "$1" == -S ]]; then
    [[ {mode} == list ]] && return 1
    printf '%s\\n' '-N CLAUDE_EGRESS' '-A CLAUDE_EGRESS -m comment --comment "domain=old.invalid;gen=1" -j ACCEPT'
  else
    return 1
  fi
}}
'''
                result = subprocess.run(['bash', '-c', script + shell_function('prune_stale_domain_rules') + '\nprune_stale_domain_rules 10'],
                                        capture_output=True, text=True, timeout=3)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('WARNING:', result.stderr)


class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('refresh_monitor', ROOT / 'firewall-refresh.py')
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = self.root / 'diagnostics'
        self.command = self.root / 'worker.py'
        self.monitor = self.module.Monitor(self.directory, [sys.executable, str(self.command)])

    def worker(self, rc=0, output='cycle output', delay=0):
        self.command.write_text(f'import time\nprint({output!r}, flush=True)\ntime.sleep({delay})\nraise SystemExit({rc})\n')

    def state(self):
        return json.loads((self.directory / 'state.json').read_text())

    def test_success_partial_failure_failure_and_recovery(self):
        last_success = None
        for rc, result, failures in ((0, 'success', 0), (75, 'partial', 1),
                                     (1, 'failure', 2), (1, 'failure', 3), (0, 'success', 0)):
            with self.subTest(rc=rc, failures=failures):
                self.worker(rc, 'WARNING: fixture DNS failed' if rc else 'resolved')
                self.monitor.run_cycle()
                state = self.state()
                self.assertEqual(state['result'], result)
                self.assertEqual(state['consecutive_failures'], failures)
                self.assertEqual(state['phase'], 'waiting')
                self.assertLessEqual(state['last_attempt_at'], state['last_completed_at'])
                if rc:
                    self.assertEqual(state['last_success_at'], last_success)
                    self.assertIn('fixture DNS failed', state['last_failure']['summary'])
                else:
                    last_success = state['last_success_at']
                    self.assertIsNotNone(last_success)
        self.assertEqual(self.state()['last_failure']['exit_code'], 1)

    def test_missing_worker_is_failure_with_diagnostic(self):
        monitor = self.module.Monitor(self.directory, [str(self.root / 'missing-command')])
        monitor.run_cycle()
        self.assertEqual(self.state()['result'], 'failure')
        self.assertEqual(self.state()['consecutive_failures'], 1)
        self.assertIn('missing-command', self.state()['last_failure']['summary'])

    def test_logs_are_bounded_even_for_one_huge_line_and_many_cycles(self):
        self.command.write_text("import sys\nsys.stdout.write('x' * 900000 + 'LATEST\\n')\nraise SystemExit(75)\n")
        for _ in range(4):
            self.monitor.run_cycle()
            logs = list(self.directory.glob('refresh.log*'))
            self.assertLessEqual(len(logs), 2)
            self.assertLessEqual(sum(path.stat().st_size for path in logs), 524288)
            self.assertTrue(all(path.stat().st_size <= 262144 for path in logs))
        self.assertIn(b'LATEST', (self.directory / 'refresh.log').read_bytes())
        self.assertLess(len(self.state()['last_failure']['summary']), 1200)

    def test_running_heartbeat_and_stopped_state_age(self):
        self.monitor.heartbeat_interval = .03
        self.worker(delay=.3)
        thread = threading.Thread(target=self.monitor.run_cycle)
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                state = self.state()
                if state['phase'] == 'running':
                    break
                time.sleep(.01)
            self.assertEqual(state['phase'], 'running')
            first = state['heartbeat_at']
            time.sleep(.1)
            self.assertGreater(self.state()['heartbeat_at'], first)
        finally:
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        state = self.state()
        status = self.module.read_status(self.directory, now=state['heartbeat_at'] + 61)
        self.assertTrue(status['stale'])
        self.assertEqual(status['heartbeat_age_seconds'], 61)
        self.assertEqual(status['result'], 'success')

    def test_second_writer_cannot_replace_active_state(self):
        with self.module.writer_lock(self.directory):
            with self.assertRaises(BlockingIOError):
                with self.module.writer_lock(self.directory):
                    self.fail('二重 writer を許可しました')

    def test_main_retries_partial_cycles_and_preserves_ipv6_mode(self):
        fake = self.root / 'sudo'
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$RECORD"\nexit 75\n')
        fake.chmod(0o755)
        for mode in ([], ['--ipv6']):
            with self.subTest(mode=mode):
                record = self.root / 'calls'
                record.write_text('')
                with patch.object(self.module, 'DIRECTORY', self.directory), \
                     patch.object(sys, 'argv', ['firewall-refresh.py', *mode]), \
                     patch.dict(os.environ, PATH=f'{self.root}:{os.defpath}', RECORD=str(record)), \
                     patch.object(self.module.time, 'sleep', side_effect=[None, None, KeyboardInterrupt]):
                    with self.assertRaises(KeyboardInterrupt):
                        self.module.main()
                self.assertEqual(self.state()['consecutive_failures'], 2)
                self.assertEqual(self.state()['result'], 'partial')
                expected = ['-n', '/usr/local/bin/init-firewall.sh', '--refresh-domains', *mode]
                self.assertEqual([line.split() for line in record.read_text().splitlines()], [expected, expected])

    def test_unknown_and_corrupt_state_are_not_healthy(self):
        with self.assertRaises(FileNotFoundError):
            self.module.read_status(self.root / 'absent')
        (self.directory / 'state.json').write_text('broken')
        with self.assertRaises(ValueError):
            self.module.read_status(self.directory)


if __name__ == '__main__':
    unittest.main()
