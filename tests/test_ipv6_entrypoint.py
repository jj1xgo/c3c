#!/usr/bin/env python3
"""entrypoint が sudo の環境保持に依存せず mode を伝えることを確認する。"""
import os
import pathlib
import signal
import time
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
# entrypoint.sh の起動前半（ファイアウォール適用と更新ループ）と後半（シークレット・
# MCP ゲート・exec claude）を分ける抽出境界。entrypoint.sh 側に同じ文字列のコメント行がある。
BOUNDARY = '# --- 起動前半ここまで（tests/test_ipv6_entrypoint.py の抽出境界） ---'


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

    def test_refresh_loop_preserves_mode(self):
        # 起動前半をそのまま実行し、後半の認証ファイル処理は実行しない。
        # sudo/sleep とログ出力先だけを fixture にする。境界が消えたり後半が混入したら
        # ここで検出する（黙って exec claude まで実行対象にしない）。
        full = (ROOT / 'entrypoint.sh').read_text()
        self.assertIn(BOUNDARY, full)
        source = full.split(BOUNDARY)[0]
        self.assertNotIn('\nexec claude', source)
        self.assertNotIn('SECRETS_MOUNT=', source)
        self.assertNotIn('MCP_CONFIG=', source)
        source = source.replace('/tmp/claude-firewall-refresh.log', '"$REFRESH_LOG"')
        for value, expected in [('0', []), ('1', ['--ipv6'])]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                tmp = pathlib.Path(td)
                for name, body in {
                    'sudo': '#!/bin/sh\nprintf "%s\n" "$*" >> "$RECORD"\n',
                    'sleep': '#!/bin/sh\nexec /bin/sleep 0.05\n',
                }.items():
                    fake = tmp / name
                    fake.write_text(body)
                    fake.chmod(0o755)
                record = tmp / 'record'
                env = {'PATH': td + ':' + os.defpath, 'RECORD': str(record),
                       'CLAUDE_CONTAINER_IPV6': value, 'REFRESH_LOG': str(tmp / 'refresh.log')}
                proc = subprocess.Popen(['bash', '-c', source + '\nwait'], env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
                try:
                    deadline = time.monotonic() + 3
                    lines = []
                    while time.monotonic() < deadline:
                        lines = record.read_text().splitlines() if record.exists() else []
                        if len(lines) >= 2:
                            break
                        time.sleep(0.01)
                    self.assertGreaterEqual(len(lines), 2)
                    self.assertEqual(lines[0].split(), ['/usr/local/bin/init-firewall.sh', *expected])
                    self.assertEqual(lines[1].split(), ['/usr/local/bin/init-firewall.sh', '--refresh-domains', *expected])
                finally:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.communicate(timeout=3)

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
