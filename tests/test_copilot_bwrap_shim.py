#!/usr/bin/env python3
"""Copilot CLI の sandbox 用 bwrap の中継 copilot-bwrap-shim.sh の回帰試験。

イメージでは /usr/local/libexec/c3c/copilot-bwrap/bwrap がこの中継になり、Copilot の起動口が PATH の
先頭に置く。Copilot の sandbox（MXC）が bwrap に渡す `--proc /proc` は、Podman の /proc のマスクの下では
失敗するので、最初の `--` より前にある組だけを `--ro-bind /proc /proc` に替えて本物の bwrap を exec する。
実物のスクリプトの固定パス（REAL_BWRAP）を試験用の dummy へ置換して実行する（tests/test_codex_launcher.py
と同じ流儀）。dummy は argv を NUL 区切りで記録し、DUMMY_RC の終了コードで終わる。
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / 'copilot-bwrap-shim.sh'
FIXED_REAL_BWRAP = '/usr/bin/bwrap'
MISSING_MESSAGE = 'ERROR: /usr/bin/bwrap がありません。-b で再ビルドしてください。'

DUMMY = '''#!/bin/sh
for arg in "$@"; do printf '%s\\0' "$arg"; done > "{record}"
exit "${{DUMMY_RC:-0}}"
'''


class CopilotBwrapShimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.record = self.root / 'record.argv'
        self.real = self.root / 'real-bwrap'
        self.real.write_text(DUMMY.format(record=self.record))
        self.real.chmod(0o755)
        text = SHIM.read_text()
        self.assertIn(f'readonly REAL_BWRAP={FIXED_REAL_BWRAP}\n', text)
        self.shim = self.root / 'bwrap'
        self.shim.write_text(text.replace(f'readonly REAL_BWRAP={FIXED_REAL_BWRAP}\n',
                                          f'readonly REAL_BWRAP={self.real}\n'))
        self.shim.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_shim(self, *args, env_extra=None):
        env = {'PATH': '/usr/bin:/bin'}
        env.update(env_extra or {})
        return subprocess.run(['/bin/bash', str(self.shim), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def recorded(self):
        data = self.record.read_bytes()
        return [part.decode() for part in data.split(b'\0')[:-1]]

    def test_rewrites_proc_pair(self):
        result = self.run_shim('--unshare-pid', '--proc', '/proc', '--dev', '/dev', '--', 'sh', '-c', 'x')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(),
                         ['--unshare-pid', '--ro-bind', '/proc', '/proc', '--dev', '/dev', '--', 'sh', '-c', 'x'])

    def test_passes_through_without_pair(self):
        for args in (['--proc', '/other', '--', 'true'],
                     ['--unshare-pid', '--proc'],
                     ['--ro-bind', '/proc', '/proc', '--', 'true'],
                     ['--bind', '--proc', '/x']):
            with self.subTest(args=args):
                result = self.run_shim(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded(), args)

    def test_stops_at_double_dash(self):
        result = self.run_shim('--proc', '/proc', '--', 'sh', '-c', 'x', '--proc', '/proc')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(),
                         ['--ro-bind', '/proc', '/proc', '--', 'sh', '-c', 'x', '--proc', '/proc'])

    def test_preserves_args_with_spaces_and_empty(self):
        args = ['--setenv', 'A', 'x y', '--setenv', 'B', '', '--', 'printf', '%s\n', 'a\tb']
        result = self.run_shim(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), args)

    def test_fails_closed_without_real_bwrap(self):
        for state in ('missing', 'not-executable', 'directory'):
            with self.subTest(state=state):
                if self.real.exists():
                    if self.real.is_dir():
                        self.real.rmdir()
                    else:
                        self.real.unlink()
                if state == 'not-executable':
                    self.real.write_text('#!/bin/sh\nexit 0\n')
                    self.real.chmod(0o644)
                elif state == 'directory':
                    self.real.mkdir()
                result = self.run_shim('--proc', '/proc', '--', 'true')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr.strip(), MISSING_MESSAGE)
                self.assertFalse(self.record.exists())

    def test_exit_code_passthrough(self):
        result = self.run_shim('--', 'true', env_extra={'DUMMY_RC': '7'})
        self.assertEqual(result.returncode, 7)


if __name__ == '__main__':
    unittest.main()
