#!/usr/bin/env python3
"""entrypoint が sudo の環境保持に依存せず mode を伝えることを確認する。"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class EntrypointTests(unittest.TestCase):
    def test_initialization_mode_and_failure(self):
        for value, expected in [('0', []), ('1', ['--ipv6'])]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                tmp = pathlib.Path(td)
                fake = tmp / 'sudo'
                fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD"\nexit 1\n')
                fake.chmod(0o755)
                env = {'PATH': td + ':' + os.defpath, 'RECORD': str(tmp / 'record'), 'CLAUDE_CONTAINER_IPV6': value}
                response = subprocess.run(['bash', str(ROOT / 'entrypoint.sh')], env=env, text=True, capture_output=True)
                self.assertEqual(response.returncode, 1)
                self.assertIn('起動を中止', response.stderr)
                self.assertEqual((tmp / 'record').read_text().splitlines(), ['/usr/local/bin/init-firewall.sh', *expected])

    def test_invalid_mode_rejected_before_sudo(self):
        with tempfile.TemporaryDirectory() as td:
            fake = pathlib.Path(td) / 'sudo'
            fake.write_text('#!/bin/sh\ntouch "$RECORD"\nexit 1\n')
            fake.chmod(0o755)
            record = pathlib.Path(td) / 'record'
            response = subprocess.run(['bash', str(ROOT / 'entrypoint.sh')],
                                      env={'PATH': td + ':' + os.defpath, 'RECORD': str(record),
                                           'CLAUDE_CONTAINER_IPV6': 'true'}, text=True, capture_output=True)
            self.assertEqual(response.returncode, 1)
            self.assertIn('CLAUDE_CONTAINER_IPV6', response.stderr)
            self.assertFalse(record.exists())


if __name__ == '__main__':
    unittest.main()
