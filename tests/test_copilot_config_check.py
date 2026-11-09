#!/usr/bin/env python3
"""Dockerfile.claude の `# >>> c3c copilot` の区間の、版の検査と sandbox の設定の読みの確認の回帰試験。

区間を開始・終了のコメントで切り出し、Dockerfile の行継続だけを除いて、shell の部分を `sh -c` で、
`node -e` の確認のスクリプトを本物の node で動かす（`tests/test_codex_bwrap.py` と同じ形）。Copilot の
実体の代わりに、一時領域に置いた偽の node・偽の npm-loader.js を使う。実物の Copilot での確認（知らない
項目を捨てて止まること）は test-build.sh の全体実行が担う。
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / 'Dockerfile.claude'
TEMPLATE = ROOT / 'copilot-settings.json'
BEGIN = '# >>> c3c copilot'
END = '# <<< c3c copilot'


def extract_block():
    text = DOCKERFILE.read_text(encoding='utf-8')
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise AssertionError('Dockerfile.claude の Copilot の区間の開始・終了コメントが一組ではありません')
    return text.split(BEGIN, 1)[1].split(END, 1)[0].replace('\\\n', '')


def extract_version_check():
    """入った版の検査の shell 部分（`installed="$(` から、その検査の `exit 1; };` まで）を取り出す。"""
    joined = extract_block()
    start = joined.find('installed="$(')
    if start < 0 or joined.count('installed="$(') != 1:
        raise AssertionError('区間に installed="$(...)" がちょうど 1 つではありません')
    end = joined.find('exit 1; };', start)
    if end < 0:
        raise AssertionError('版の検査の終わりが見つかりません')
    return joined[start:end + len('exit 1; };')]


class InstalledVersionCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        node = self.bin / 'node'
        # -p の式は見ずに、決めた版を返す（空なら失敗する node を模す）。
        node.write_text('#!/bin/sh\n[ -n "$FAKE_VERSION" ] || exit 1\nprintf "%s\\n" "$FAKE_VERSION"\n')
        node.chmod(0o755)
        self.pkg = self.root / 'pkg'
        self.pkg.mkdir()
        (self.pkg / 'package.json').write_text('{}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, requested, installed):
        env = {'PATH': f'{self.bin}:/usr/bin:/bin', 'COPILOT_VERSION': requested, 'pkg': str(self.pkg),
               'FAKE_VERSION': installed}
        return subprocess.run(['sh', '-c', 'set -e; ' + extract_version_check()], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_installed_version_check(self):
        cases = [
            ('latest', '1.0.110', True),
            ('latest', '1.1.0-beta.1', False),
            ('latest', '', False),
            ('latest', 'latest', False),
            ('1.0.103', '1.0.103', True),
            ('1.0.103', '1.0.110', False),
            ('1.0.103', '', False),
            ('latest', 'junk\n1.0.110', False),
            ('latest', '1.0.110\njunk', False),
        ]
        for requested, installed, ok in cases:
            with self.subTest(requested=requested, installed=installed):
                result = self.run_check(requested, installed)
                if ok:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertRegex(result.stderr, r'(?m)^ERROR: ')


class BuildArgTest(unittest.TestCase):
    def test_cachebust_arg_is_echoed(self):
        block = extract_block()
        self.assertIn('ARG COPILOT_CACHEBUST=pinned', block)
        self.assertIn('echo "copilot-cachebust=${COPILOT_CACHEBUST}"', block)

    def test_no_bypass(self):
        block = extract_block()
        self.assertEqual(re.findall(r'(?m)^ARG (\w+)', block), ['COPILOT_CACHEBUST'])
        self.assertNotRegex(block, r'SKIP')


def extract_script():
    """区間の中の `node -e '...'`（設定の読みの確認）の中身を、ちょうど 1 つ取り出す。"""
    joined = extract_block()
    found = re.findall(r"node -e '([^']*)'", joined)
    if len(found) != 1 or joined.count("node -e '") != 1:
        raise AssertionError("区間の node -e の単一引用符の組が一つではありません")
    return found[0]


def extract_check_call():
    """確認の呼び出しの shell 部分（`node -e '` から、失敗時の `exit 1; };` まで）を取り出す。"""
    joined = extract_block()
    start = joined.find("node -e '")
    close = joined.find("'", start + len("node -e '"))
    end = joined.find('exit 1; };', close)
    if start < 0 or close < 0 or end < 0:
        raise AssertionError('確認の呼び出しが見つかりません')
    return joined[start:end + len('exit 1; };')]


FAKE_LOADER = """#!/bin/sh
rec={rec}
printf '%s\\n' "$@" > "$rec/argv"
tr '\\0' '\\n' < /proc/$$/environ > "$rec/env"
printf '%s\\n' "$COPILOT_HOME" > "$rec/home"
cp "$COPILOT_HOME/settings.json" "$rec/settings.json"
[ -e "$rec/sleep" ] && exec sleep 5
if [ -e "$rec/ignore-term" ]; then trap '' TERM; while :; do :; done; fi
cat "$rec/out"
exit "$(cat "$rec/rc")"
"""


class ConfigCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rec = self.root / 'rec'
        self.rec.mkdir()
        self.loader = self.root / 'npm-loader.js'
        self.loader.write_text(FAKE_LOADER.format(rec=self.rec))
        self.loader.chmod(0o755)
        self.script = extract_script()

    def tearDown(self):
        self.tmp.cleanup()

    def expected_input(self, template=TEMPLATE, readonly='/workspace'):
        doc = json.loads(Path(template).read_text())
        doc['sandbox']['userPolicy']['filesystem']['readonlyPaths'] = [readonly]
        return doc

    def run_check(self, out=None, rc=0, template=TEMPLATE, sleep=False, raw=None):
        if raw is None:
            raw = json.dumps(out if out is not None else self.expected_input(template))
        (self.rec / 'out').write_text(raw)
        (self.rec / 'rc').write_text(str(rc))
        if sleep:
            (self.rec / 'sleep').write_text('')
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'TMPDIR': str(self.root)}
        return subprocess.run(['node', '-e', self.script, str(self.loader), str(template), '/workspace', '1'],
                              env=env, capture_output=True, text=True, timeout=30)

    def assert_failed(self, result, name=None):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r'(?m)^ERROR: ')
        self.assertNotRegex(result.stderr, r'(?m)^\s+at ', 'traceback を出さない')
        if name:
            self.assertIn(name, result.stderr)

    def test_passes_when_all_leaves_match(self):
        doc = self.expected_input()
        reordered = {'sandbox': dict(reversed(list(doc['sandbox'].items())))}
        result = self.run_check(reordered)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.rec / 'argv').read_text().splitlines(), ['config', '--list', '--json'])
        env = dict(line.split('=', 1) for line in (self.rec / 'env').read_text().splitlines() if line)
        self.assertEqual(set(env), {'HOME', 'COPILOT_HOME', 'PATH', 'COPILOT_AUTO_UPDATE'})
        self.assertEqual(env['COPILOT_AUTO_UPDATE'], 'false')
        self.assertEqual(env['PATH'], '/usr/local/bin:/usr/bin:/bin')
        self.assertEqual(env['HOME'], env['COPILOT_HOME'])
        self.assertEqual(json.loads((self.rec / 'settings.json').read_text()), self.expected_input())

    def test_matches_launcher_settings(self):
        import test_copilot_launcher
        case = test_copilot_launcher.CopilotLauncherTest('test_args_passthrough')
        case.setUp()
        try:
            launched = case.run_launcher()
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            written = json.loads(case.settings.read_text())
            written['sandbox']['userPolicy']['filesystem']['readonlyPaths'] = ['/workspace']
            result = self.run_check(written, template=case.template)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads((self.rec / 'settings.json').read_text()), written,
                             'ビルドの確認は起動口と同じ設定を組み立てる')
        finally:
            case.tearDown()

    def test_extra_output_is_allowed(self):
        doc = self.expected_input()
        doc['sandbox']['newKey'] = True
        doc['footer'] = {'showQuota': False}
        result = self.run_check(doc)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dropped_or_changed_leaf_fails(self):
        def drop_readonly(d):
            del d['sandbox']['userPolicy']['filesystem']['readonlyPaths']

        def set_network(value):
            return lambda d: d['sandbox']['userPolicy']['network'].__setitem__('allowOutbound', value)

        def reorder_denied(d):
            d['sandbox']['userPolicy']['filesystem']['deniedPaths'].reverse()

        cases = [
            ('drop readonlyPaths', drop_readonly, 'sandbox.userPolicy.filesystem.readonlyPaths'),
            ('allowOutbound true', set_network(True), 'sandbox.userPolicy.network.allowOutbound'),
            ('allowOutbound 0', set_network(0), 'sandbox.userPolicy.network.allowOutbound'),
            ('enabled "true"', lambda d: d['sandbox'].__setitem__('enabled', 'true'), 'sandbox.enabled'),
            ('reorder deniedPaths', reorder_denied, 'sandbox.userPolicy.filesystem.deniedPaths'),
            ('drop auth', lambda d: d['sandbox'].pop('auth'), 'sandbox.auth.git'),
        ]
        for label, mutate, name in cases:
            with self.subTest(label):
                doc = self.expected_input()
                mutate(doc)
                self.assert_failed(self.run_check(doc), name)

    def test_config_command_failures_fail_closed(self):
        cases = [('rc 1', dict(rc=1)), ('not json', dict(raw='Error: nope')), ('empty', dict(raw='')),
                 ('array', dict(raw='[]')), ('null', dict(raw='null')),
                 ('sandbox array', dict(raw='{"sandbox": []}')), ('timeout', dict(sleep=True))]
        for label, kwargs in cases:
            with self.subTest(label):
                for name in ('sleep',):
                    (self.rec / name).unlink(missing_ok=True)
                self.assert_failed(self.run_check(**kwargs))

    def test_timeout_kills_child_ignoring_sigterm(self):
        (self.rec / 'ignore-term').write_text('')
        started = time.monotonic()
        result = self.run_check()
        self.assertLess(time.monotonic() - started, 10, 'SIGTERM を無視する子でも打ち切る')
        self.assert_failed(result)

    def test_check_runs_native_binary(self):
        self.assertIn('"$native"', extract_check_call(), '孫を残さないよう、loader でなくネイティブのバイナリを直接起動する')

    def test_temp_home_removed(self):
        for label, kwargs in (('pass', {}), ('fail', dict(rc=1))):
            with self.subTest(label):
                self.run_check(**kwargs)
                home = Path((self.rec / 'home').read_text().strip())
                self.assertTrue(str(home).startswith(str(self.root)), home)
                self.assertFalse(home.exists(), '一時の home を消す')

    def test_missing_template_fails(self):
        self.assert_failed(self.run_check(raw='{}', template=self.root / 'missing.json'))


class CheckWiringTest(unittest.TestCase):
    def run_wiring(self, node_rc):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            node = bin_dir / 'node'
            node.write_text(f'#!/bin/sh\nexit {node_rc}\n')
            node.chmod(0o755)
            env = {'PATH': f'{bin_dir}:/usr/bin:/bin', 'native': '/x/copilot', 'installed': '1.0.103'}
            return subprocess.run(['sh', '-c', 'set -e; ' + extract_check_call() + ' echo after'], env=env,
                                  capture_output=True, text=True, timeout=30)

    def test_run_wiring_fails_build(self):
        failed = self.run_wiring(1)
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertNotIn('after', failed.stdout)
        self.assertRegex(failed.stderr, r'(?m)^ERROR: ')
        passed = self.run_wiring(0)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertIn('after', passed.stdout)

    def test_called_with_fixed_arguments(self):
        call = extract_check_call()
        self.assertRegex(call, r"""' "\$native" /tmp/copilot-settings\.json /workspace 60 \|\|""")


if __name__ == '__main__':
    unittest.main()
