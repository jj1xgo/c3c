#!/usr/bin/env python3
"""実 staging/IPv4 検証関数を、ローカル HTTP と実 curl で検査する（#104）。

URL と待ち時間だけをテスト用 wrapper で変換する。関数の分岐・再試行・保存は実物。
タイムアウト削除、再試行無制限、部分応答によるキャッシュ破壊を検出する。
"""
import http.server
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
META = b'{"web":["192.0.2.0/24"],"api":["192.0.2.0/24"],"git":["192.0.2.0/24"]}'


def run_shell(script, env, limit):
    with subprocess.Popen(['bash', '-c', script], env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as proc:
        try:
            out, err = proc.communicate(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise AssertionError(f'処理が {limit} 秒以内に終了しませんでした') from None
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def function(file, name):
    match = re.search(r'^' + name + r'\(\) \{\n.*?^\}',
                      (ROOT / file).read_text(), re.M | re.S)
    if not match:
        raise AssertionError(f'{file}: {name} not found')
    return match[0]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.server.requests += 1
        mode = self.server.mode
        if mode == 'stall':
            self.server.stop.wait(15)
            return
        if mode == 'partial' and self.server.requests == 1:
            self.send_response(200)
            self.send_header('Content-Length', str(len(META)))
            self.end_headers()
            self.wfile.write(META[:10])
            self.wfile.flush()
            self.server.stop.wait(15)
            return
        if mode in ('retry', 'retry_after'):
            self.send_response(503)
            if mode == 'retry_after':
                self.send_header('Retry-After', '3600')
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'not json' if mode == 'invalid' else META)


class NetworkTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.requests = 0
        self.server.mode = 'ok'
        self.server.stop = threading.Event()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.stop.set)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        # curl の処理は実物。接続先と時間単位を短縮し、個人の proxy は使わない。
        # retry-max-time は整数秒なので、curl の時間より緩く縮める。
        wrapper = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
for i, arg in enumerate(args[:-1]):
    if arg in ('--connect-timeout', '--max-time'):
        args[i + 1] = str(float(args[i + 1]) / 20)
    elif arg == '--retry-max-time':
        args[i + 1] = str(max(1, int(args[i + 1]) // 10))
for i, arg in enumerate(args):
    if arg.startswith('https://'):
        args[i] = os.environ['TEST_URL']
os.execv(os.environ['REAL_CURL'], [os.environ['REAL_CURL'], '-q', *args])
'''
        (self.bin / 'curl').write_text(wrapper)
        (self.bin / 'curl').chmod(0o755)
        (self.bin / 'timeout').write_text('''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
for i, arg in enumerate(args):
    if arg.startswith('--kill-after='):
        args[i] = '--kill-after=0.5'
    elif not arg.startswith('-'):
        args[i] = str(float(arg) / float(os.environ.get('TEST_TIMEOUT_SCALE', '10')))
        break
os.execv('/usr/bin/timeout', ['timeout', *args])
''')
        (self.bin / 'timeout').chmod(0o755)
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin',
                        REAL_CURL=shutil.which('curl'),
                        TEST_URL=f'http://127.0.0.1:{self.server.server_port}/',
                        no_proxy='*', NO_PROXY='*')
        self.run_dir = self.root / 'run'
        self.stage = self.run_dir / '.build-context' / 'current'
        self.stage.mkdir(parents=True)
        for file in ('entrypoint.sh', 'init-firewall.sh', 'ipv6-firewall.py',
                     'git-askpass.sh', 'validate-build-input.sh', 'allowed-domains.txt'):
            shutil.copy2(ROOT / file, self.run_dir / file)

    def run_meta(self, kind, mode='ok', cache=None):
        self.server.mode = mode
        if kind == 'build':
            self.stage = self.root / 'build-stage'
            self.stage.mkdir(exist_ok=True)
        if cache:
            dest = self.stage if cache == 'current' else self.run_dir / '.build-context' / 'other'
            dest.mkdir(exist_ok=True)
            (dest / 'github-meta.json').write_bytes(META + b'\n')
        self.env.update(RUN_DIR=str(self.run_dir), SCRIPT_DIR=str(self.run_dir),
                        BUILD_CONTEXT_DIR=str(self.stage), SOURCE_ROOT=str(ROOT))
        setup = '''set -uo pipefail
resolve_asset_source() { ASSET_PATH="$SOURCE_ROOT/$1"; ASSET_ORIGIN=repo; }
'''
        file, name, call = ('claude-container', 'stage_build_context', 'stage_build_context') if kind == 'launcher' else (
            'test-build.sh', 'stage_common_context', 'stage_common_context "$BUILD_CONTEXT_DIR"')
        start = time.monotonic()
        result = run_shell(setup + function(file, name) + '\n' + call, self.env, 12)
        self.assertLess(time.monotonic() - start, 11, result.stderr)
        return result

    def test_success_stages_valid_snapshot_in_both_callers(self):
        for kind in ('launcher', 'build'):
            with self.subTest(kind=kind):
                result = self.run_meta(kind)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads((self.stage / 'github-meta.json').read_bytes()), json.loads(META))

    def test_stalled_response_falls_back_without_overwriting_current_snapshot(self):
        result = self.run_meta('launcher', 'stall', 'current')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('WARNING:', result.stderr)
        self.assertEqual((self.stage / 'github-meta.json').read_bytes(), META + b'\n')

    def test_partial_response_then_retry_saves_only_complete_response(self):
        for kind in ('launcher', 'build'):
            with self.subTest(kind=kind):
                self.server.requests = 0
                result = self.run_meta(kind, 'partial')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads((self.stage / 'github-meta.json').read_bytes()), json.loads(META))

    def test_retry_count_is_bounded_and_missing_cache_fails(self):
        for kind, rc in (('launcher', 1), ('build', 77)):
            with self.subTest(kind=kind):
                self.server.requests = 0
                result = self.run_meta(kind, 'retry')
                self.assertEqual(result.returncode, rc, result.stderr)
                self.assertEqual(self.server.requests, 3)

    def test_long_retry_after_cannot_hold_up_fallback(self):
        result = self.run_meta('build', 'retry_after', 'sibling')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.stage / 'github-meta.json').read_bytes(), META + b'\n')

    def test_outer_deadline_stops_unresponsive_fetch_before_fallback(self):
        # curl 内部の上限が効かない処理にも、外側の timeout が実際に効くことを見る。
        (self.bin / 'curl').write_text('#!/bin/sh\nsleep 30\n')
        self.env['TEST_TIMEOUT_SCALE'] = '100'
        result = self.run_meta('launcher', cache='current')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('rc=124', result.stderr)
        self.assertEqual((self.stage / 'github-meta.json').read_bytes(), META + b'\n')

    def test_invalid_response_uses_sibling_snapshot_in_both_callers(self):
        for kind in ('launcher', 'build'):
            with self.subTest(kind=kind):
                (self.stage / 'github-meta.json').unlink(missing_ok=True)
                result = self.run_meta(kind, 'invalid', 'sibling')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('WARNING:', result.stderr)
                self.assertEqual((self.stage / 'github-meta.json').read_bytes(), META + b'\n')

    def test_connection_refused_without_cache_fails(self):
        # bind 済み・listen していないポートへ実 curl を接続する。
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.env['TEST_URL'] = f'http://127.0.0.1:{sock.getsockname()[1]}/'
            result = self.run_meta('launcher')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('ERROR:', result.stderr)

    def test_ipv4_allowed_response_stall_stops_startup(self):
        self.server.mode = 'stall'
        # DNS・GitHub TCP・禁止通信だけを fixture にし、許可 HTTPS の curl は実物。
        harness = '''set -euo pipefail
dig() { echo 192.0.2.42; }
timeout() { [[ "${@: -1}" != 80 ]]; }
curl() {
  [[ "${@: -1}" == https://example.com ]] && return 7
  command curl "$@"
}
'''
        result = run_shell(harness + function('init-firewall.sh', 'verify_ipv4') + '\nverify_ipv4', self.env, 3)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('api.anthropic.com', result.stderr)

    def test_ipv4_denied_response_stall_returns_within_limit(self):
        self.server.mode = 'stall'
        harness = '''set -euo pipefail
dig() { echo 192.0.2.42; }
timeout() { [[ "${@: -1}" != 80 ]]; }
curl() {
  [[ "${@: -1}" == https://api.anthropic.com ]] && return 0
  command curl "$@"
}
'''
        result = run_shell(harness + function('init-firewall.sh', 'verify_ipv4') + '\nverify_ipv4', self.env, 3)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
