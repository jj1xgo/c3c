#!/usr/bin/env python3
"""Codex 起動口 codex-launcher.sh（#152）の回帰試験。

イメージでは /usr/local/bin/codex がこの起動口になり、名前で呼ぶ codex（Claude 経路の Bash ツール、
ログインシェル、podman exec）が Codex 同梱 bubblewrap を選ぶよう PATH の先頭へ専用ディレクトリを足す。
実物のスクリプトの固定パスを試験用コピーへ置換して実行する（tests/test_codex_entrypoint.py と同じ流儀）。
Codex の実体は argv・PATH を記録する dummy。実 /usr/local・ホストの設定や認証には触れない。
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'codex-launcher.sh'
ENTRYPOINT = ROOT / 'entrypoint.sh'
FIXED_BWRAP_DIR = '/usr/local/libexec/c3c/codex-bwrap'
FIXED_CODEX_JS = '/usr/local/lib/node_modules/@openai/codex/bin/codex.js'
MISSING_MESSAGE = 'ERROR: Codex 同梱の bubblewrap がありません。-b で再ビルドしてください。'

# Codex 実体の dummy: argv と PATH を記録し、DUMMY_RC の終了コードで終わる。
DUMMY = '''#!/bin/sh
printf '%s\\n' "$PATH" > "{record}.path"
for arg in "$@"; do printf '%s\\0' "$arg"; done > "{record}.argv"
exit "${{DUMMY_RC:-0}}"
'''


class CodexLauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bwrap_dir = self.root / 'codex-bwrap'
        self.bwrap_dir.mkdir()
        self.real_bwrap = self.root / 'bundled-bwrap'
        self.real_bwrap.write_text('#!/bin/sh\nexit 0\n')
        self.real_bwrap.chmod(0o755)
        (self.bwrap_dir / 'bwrap').symlink_to(self.real_bwrap)
        self.record = self.root / 'record'
        self.codex_js = self.root / 'codex.js'
        self.codex_js.write_text(DUMMY.format(record=self.record))
        self.codex_js.chmod(0o755)
        text = LAUNCHER.read_text()
        self.assertIn(FIXED_BWRAP_DIR, text)
        self.assertIn(FIXED_CODEX_JS, text)
        self.launcher = self.root / 'codex'
        self.launcher.write_text(text.replace(FIXED_BWRAP_DIR, str(self.bwrap_dir))
                                 .replace(FIXED_CODEX_JS, str(self.codex_js)))
        self.launcher.chmod(0o755)
        self.base_path = '/usr/local/bin:/usr/bin:/bin'

    def tearDown(self):
        self.tmp.cleanup()

    def run_launcher(self, *args, path=None, env_extra=None, unset_path=False):
        env = {'PATH': self.base_path if path is None else path}
        if unset_path:
            env.pop('PATH')
        env.update(env_extra or {})
        # bash を絶対パスで起動する（PATH を空・未設定にする試験でも起動口自体は動かせるように）。
        return subprocess.run(['/bin/bash', str(self.launcher), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def recorded_path(self):
        return (self.record.parent / 'record.path').read_text().rstrip('\n')

    def recorded_argv(self):
        data = (self.record.parent / 'record.argv').read_bytes()
        return [part.decode() for part in data.split(b'\0')[:-1]]

    def test_prepends_bundled_dir_once(self):
        result = self.run_launcher('exec', '--sandbox', 'read-only', 'pwd')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_path(), str(self.bwrap_dir) + ':' + self.base_path)

    def test_keeps_path_unchanged_when_already_first(self):
        # Codex 経路: entrypoint が先頭へ足した PATH をそのまま渡す（全段の PATH 一致を崩さない）。
        path = str(self.bwrap_dir) + ':' + self.base_path
        result = self.run_launcher('--version', path=path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_path(), path)

    def test_prepends_when_bundled_dir_is_not_first(self):
        path = self.base_path + ':' + str(self.bwrap_dir)
        result = self.run_launcher(path=path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_path(), str(self.bwrap_dir) + ':' + path)

    def test_empty_or_unset_path_has_no_trailing_empty_element(self):
        for label, kwargs in (('empty', {'path': ''}), ('unset', {'unset_path': True})):
            with self.subTest(label):
                # 前の subtest の記録で緑にならないよう、毎回消してから実行する。
                for suffix in ('path', 'argv'):
                    (self.record.parent / f'record.{suffix}').unlink(missing_ok=True)
                result = self.run_launcher(**kwargs)
                # 実際の codex.js は env node の shebang なので空 PATH では起動できない（置換前も同じ）。
                # dummy は /bin/sh の絶対 shebang なので、ここでは exec まで進んだことも確かめる。
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded_path(), str(self.bwrap_dir))

    def test_path_equal_to_bundled_dir_is_unchanged(self):
        result = self.run_launcher(path=str(self.bwrap_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_path(), str(self.bwrap_dir))

    def test_passes_arguments_and_exit_code_verbatim(self):
        args = ['exec', 'a b', '--', '', '-c', "x='1'", '$HOME', '*']
        result = self.run_launcher(*args, env_extra={'DUMMY_RC': '7'})
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.recorded_argv(), args)

    def assert_refused(self, label):
        result = self.run_launcher('exec', 'pwd')
        self.assertEqual(result.returncode, 1, label)
        self.assertIn(MISSING_MESSAGE, result.stderr, label)
        self.assertFalse((self.record.parent / 'record.path').exists(), label)

    def test_missing_link_is_refused_without_exec(self):
        (self.bwrap_dir / 'bwrap').unlink()
        self.assert_refused('missing')

    def test_dangling_link_is_refused_without_exec(self):
        self.real_bwrap.unlink()
        self.assert_refused('dangling')

    def test_non_executable_link_is_refused_without_exec(self):
        self.real_bwrap.chmod(0o644)
        self.assert_refused('non-executable')

    def test_fixed_values_match_entrypoint(self):
        entrypoint = ENTRYPOINT.read_text()
        match = re.search(r'^\s*CODEX_BWRAP_DIR=(\S+)$', entrypoint, re.M)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), FIXED_BWRAP_DIR)
        self.assertIn('echo "' + MISSING_MESSAGE + '" >&2', entrypoint)
        launcher = LAUNCHER.read_text()
        self.assertRegex(launcher, r'(?m)^readonly CODEX_BWRAP_DIR=' + re.escape(FIXED_BWRAP_DIR) + '$')
        self.assertRegex(launcher, r'(?m)^readonly CODEX_JS=' + re.escape(FIXED_CODEX_JS) + '$')
        self.assertIn('echo "' + MISSING_MESSAGE + '" >&2', launcher)


if __name__ == '__main__':
    unittest.main()
