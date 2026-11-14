#!/usr/bin/env python3
"""Copilot CLI の起動口 copilot-launcher.sh の回帰試験。

イメージでは /usr/local/bin/copilot がこの起動口になる（opt-in のときだけ）。起動口は、作業ディレクトリの
検査、sandbox の設定の作り直しと検査（雛形＋作業ディレクトリを読み取りだけで許す readonlyPaths）、トークンの
読み込み、環境の allowlist を行ってから、bwrap の中継を PATH の先頭にして npm-loader.js を exec する。
実物のスクリプトと雛形の固定パスを試験用の一時ディレクトリへ置換して実行する（tests/test_codex_launcher.py と
同じ流儀）。Copilot の実体は argv・環境・cwd を記録する dummy。python3 は argv を記録してから本物を exec する
wrapper に替える（どの外部コマンドの引数にもトークンが載らないことを見るため）。実 /usr/local・/etc・
ホストの設定や認証には触れない。
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'copilot-launcher.sh'
TEMPLATE = ROOT / 'copilot-settings.json'
ENTRYPOINT = ROOT / 'entrypoint.sh'

FIXED_HOME = '/home/node'
FIXED_BWRAP_DIR = '/usr/local/libexec/c3c/copilot-bwrap'
FIXED_COPILOT_JS = '/usr/local/lib/node_modules/@github/copilot/npm-loader.js'
FIXED_TEMPLATE = '/etc/c3c/copilot-settings.json'
FIXED_PYTHON = '/usr/bin/python3'
FIXED_TMP_LINE = 'readonly SANDBOX_TMP=/tmp\n'
REAL_PYTHON = shutil.which('python3')

TOKEN = 'c3c-dummy-copilot-credential-0123456789'
ALLOWED_ENV = {'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM', 'TZ', 'NO_COLOR', 'COLORTERM'}
SET_BY_LAUNCHER = {'PATH', 'COPILOT_HOME', 'COPILOT_GITHUB_TOKEN', 'COPILOT_AUTO_UPDATE'}
# exec の前後でシェルが自分で足すもの（起動口が渡すものではない）。
SHELL_ADDED = {'PWD', 'OLDPWD', 'SHLVL', '_'}

DUMMY_JS = '''#!/bin/sh
for arg in "$@"; do printf '%s\\0' "$arg"; done > "{record}.argv"
/usr/bin/env -0 > "{record}.env"
pwd -P > "{record}.cwd"
exit 0
'''

PYTHON_WRAPPER = '''#!/bin/sh
for arg in "$@"; do printf '%s\\0' "$arg"; done >> "{record}.python-argv"
printf '\\n' >> "{record}.python-argv"
exec {real} "$@"
'''


VERIFIED = '1.0.109'
TIERS = ('standard', 'high', 'max')
WARNING_PREFIX = f'WARNING: Copilot CLI {{}} は、c3c が sandbox を canary で確かめた版（{VERIFIED}）と違います。'


class CopilotLauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home' / 'node'
        (self.home / '.config' / 'c3c' / 'secrets').mkdir(parents=True)
        self.token_file = self.home / '.config' / 'c3c' / 'secrets' / 'COPILOT_PAT'
        self.token_file.write_text(TOKEN + '\n')
        self.copilot_home = self.home / '.copilot'
        self.settings = self.copilot_home / 'settings.json'
        self.bwrap_dir = self.root / 'copilot-bwrap'
        self.bwrap_dir.mkdir()
        (self.bwrap_dir / 'bwrap').write_text('#!/bin/sh\nexit 0\n')
        (self.bwrap_dir / 'bwrap').chmod(0o755)
        self.record = self.root / 'record'
        self.js = self.root / 'npm-loader.js'
        self.js.write_text(DUMMY_JS.format(record=self.record))
        self.js.chmod(0o755)
        # 起動口は COPILOT_JS の隣の package.json の版を、確かめた版（VERIFIED_COPILOT_VERSION）と比べる。
        self.package_json = self.root / 'package.json'
        self.package_json.write_text(json.dumps({'version': VERIFIED}) + '\n')
        self.python = self.root / 'python3'
        self.python.write_text(PYTHON_WRAPPER.format(record=self.record, real=REAL_PYTHON))
        self.python.chmod(0o755)
        self.template = self.root / 'copilot-settings.json'
        # sandbox が隠す /tmp は、試験の一時ディレクトリ（/tmp の下）と重なるので、起動口と雛形の両方で別の場所に替える。
        self.fake_tmp = self.root / 'faketmp'
        self.fake_tmp.mkdir()
        self.template.write_text(self.render_template(TEMPLATE.read_text()))
        self.work = self.home / 'copilot-work'
        self.work.mkdir()
        text = LAUNCHER.read_text()
        for fixed in (FIXED_BWRAP_DIR, FIXED_COPILOT_JS, FIXED_TEMPLATE, FIXED_PYTHON, FIXED_HOME):
            self.assertIn(fixed, text)
        text = (text.replace(FIXED_BWRAP_DIR, str(self.bwrap_dir))
                .replace(FIXED_COPILOT_JS, str(self.js))
                .replace(FIXED_TEMPLATE, str(self.template))
                .replace(FIXED_PYTHON, str(self.python))
                .replace(FIXED_HOME, str(self.home)))
        self.assertIn(FIXED_TMP_LINE, text)
        text = text.replace(FIXED_TMP_LINE, f'readonly SANDBOX_TMP={self.fake_tmp}\n')
        self.launcher = self.root / 'copilot'
        self.launcher.write_text(text)
        self.launcher.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def render_template(self, text):
        self.assertIn('"/tmp"', text)
        return text.replace(FIXED_HOME, str(self.home)).replace('"/tmp"', json.dumps(str(self.fake_tmp)))

    def run_launcher(self, *args, cwd=None, env_extra=None):
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(self.home), 'LANG': 'C.UTF-8'}
        env.update(env_extra or {})
        return subprocess.run(['/bin/bash', str(self.launcher), *args], env=env,
                              cwd=str(cwd or self.work), capture_output=True, text=True, timeout=30)

    def ran(self):
        return Path(str(self.record) + '.argv').exists()

    def recorded_env(self):
        data = Path(str(self.record) + '.env').read_bytes()
        result = {}
        for item in data.split(b'\0'):
            if item:
                key, _, value = item.decode().partition('=')
                result[key] = value
        return result

    def recorded_argv(self):
        data = Path(str(self.record) + '.argv').read_bytes()
        return [part.decode() for part in data.split(b'\0')[:-1]]

    def assert_refused(self, result, pattern=None):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r'(?m)^ERROR: ')
        if pattern:
            self.assertRegex(result.stderr, pattern)
        self.assertFalse(self.ran(), 'Copilot を起動していない')
        self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def assert_ran(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.ran())

    def expected_settings(self, cwd):
        doc = json.loads(self.template.read_text())
        doc['sandbox']['userPolicy']['filesystem']['readonlyPaths'] = [str(cwd)]
        return doc

    def write_template(self, mutate):
        doc = json.loads(self.render_template(TEMPLATE.read_text()))
        mutate(doc)
        self.template.write_text(json.dumps(doc))

    # --- 確かめた版との比較 -------------------------------------------------

    def test_verified_version_constant(self):
        lines = [line for line in LAUNCHER.read_text().splitlines() if line.startswith('readonly VERIFIED_COPILOT_VERSION=')]
        self.assertEqual(lines, [f'readonly VERIFIED_COPILOT_VERSION={VERIFIED}'])

    def test_no_warning_for_verified_version(self):
        result = self.run_launcher()
        self.assert_ran(result)
        self.assertNotIn('WARNING', result.stderr)

    def test_warns_for_other_version(self):
        for version in ('1.0.110', '1.0.90'):
            with self.subTest(version=version):
                Path(str(self.record) + '.argv').unlink(missing_ok=True)
                self.package_json.write_text(json.dumps({'version': version}))
                result = self.run_launcher()
                self.assert_ran(result)
                warnings = [line for line in result.stderr.splitlines() if line.startswith('WARNING')]
                self.assertEqual(len(warnings), 1, result.stderr)
                self.assertTrue(warnings[0].startswith(WARNING_PREFIX.format(version)), warnings[0])
                self.assertIn('変更後の確認', warnings[0])
                self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_refuses_unreadable_package_json(self):
        cases = [('missing', None), ('not json', '{'), ('no version', '{}'), ('number', '{"version": 1}'),
                 ('empty', '{"version": ""}'), ('newline', '{"version": "1.0.103\\n"}'), ('array', '[]')]
        for label, text in cases:
            with self.subTest(label):
                if text is None:
                    self.package_json.unlink(missing_ok=True)
                else:
                    self.package_json.write_text(text)
                self.assert_refused(self.run_launcher(), r'package\.json')

    # --- 雛形 ---------------------------------------------------------------

    def test_template_is_the_contract_value(self):
        doc = json.loads(TEMPLATE.read_text())
        self.assertEqual(doc, {'sandbox': {
            'enabled': True, 'allowBypass': False, 'addCurrentWorkingDirectory': False, 'allowDevToolAccess': False,
            'auth': {'git': False, 'gh': False}, 'sandboxMcpServers': True, 'sandboxLspServers': True,
            'userPolicy': {'network': {'allowOutbound': False, 'allowLocalNetwork': False},
                           'filesystem': {'deniedPaths': ['/tmp', '/home/node/.config/c3c/secrets']}}}})

    # --- settings.json の作り直し ---------------------------------------------

    def test_regenerates_settings_each_run(self):
        result = self.run_launcher('--version')
        self.assert_ran(result)
        self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings(self.work))
        self.assertEqual(self.copilot_home.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        # Copilot や利用者が書き換えた設定（弱めたものを含む）は、次の起動で雛形から作り直される。
        weakened = json.loads(self.settings.read_text())
        weakened['sandbox']['userPolicy']['network']['allowOutbound'] = True
        weakened['model'] = 'x'
        self.settings.write_text(json.dumps(weakened))
        other = self.home / 'work' / 'sub'
        other.mkdir(parents=True)
        os.unlink(str(self.record) + '.argv')
        result = self.run_launcher('--version', cwd=other)
        self.assert_ran(result)
        self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings(other))
        self.assertEqual(sorted(p.name for p in self.copilot_home.iterdir()), ['.c3c-launch.lock', 'settings.json'],
                         '一時ファイルを残さない')

    def test_refuses_settings_symlink(self):
        self.copilot_home.mkdir(mode=0o700)
        target = self.root / 'elsewhere.json'
        target.write_text('{}')
        self.settings.symlink_to(target)
        self.assert_refused(self.run_launcher('--version'))
        self.assertEqual(target.read_text(), '{}', 'リンク先を書き換えない')

    def test_refuses_copilot_home_symlink(self):
        target = self.root / 'elsewhere'
        target.mkdir()
        self.copilot_home.symlink_to(target)
        self.assert_refused(self.run_launcher('--version'))
        self.assertEqual(list(target.iterdir()), [])

    # --- Fusion の段階 -------------------------------------------------------

    def test_fusion_tier_written(self):
        for tier in TIERS:
            with self.subTest(tier=tier):
                result = self.run_launcher('--c3c-fusion-tier', tier, '-p', 'a b', '--model', 'fusion')
                self.assert_ran(result)
                self.assertEqual(self.recorded_argv(), ['-p', 'a b', '--model', 'fusion'])
                expected = self.expected_settings(self.work)
                expected['fusionTier'] = tier
                self.assertEqual(json.loads(self.settings.read_text()), expected)

    def test_fusion_tier_does_not_persist(self):
        self.assert_ran(self.run_launcher('--c3c-fusion-tier', 'max', '--version'))
        self.assertEqual(json.loads(self.settings.read_text())['fusionTier'], 'max')
        os.unlink(str(self.record) + '.argv')
        self.assert_ran(self.run_launcher('--version'))
        self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings(self.work))

    def test_fusion_tier_refused(self):
        cases = [
            ['--c3c-fusion-tier'],
            ['--c3c-fusion-tier', ''],
            ['--c3c-fusion-tier', 'Max'],
            ['--c3c-fusion-tier', 'max '],
            ['--c3c-fusion-tier', 'auto'],
            ['--c3c-fusion-tier', '--version'],
            ['--c3c-fusion-tier=max', '--version'],
            ['--c3c-fusion-tier=', '--version'],
            ['--c3c-fusion-tier', 'high', '--c3c-fusion-tier', 'max', '--version'],
            ['--c3c-fusion-tier', 'max', '--c3c-fusion-tier'],
            ['--c3c-fusion-tier', 'max', '--c3c-fusion-tier=high', '--version'],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_launcher(*args)
                self.assert_refused(result, r'--c3c-fusion-tier')
                self.assertFalse(self.copilot_home.exists(), '~/.copilot も lock も作らない')
        for value in ('auto', 'Max'):
            with self.subTest(value=value):
                self.assertNotIn(value, self.run_launcher('--c3c-fusion-tier', value).stderr, '受け取った値を出さない')

    def test_fusion_tier_later_args_pass_through(self):
        args = ['-p', 'x', '--c3c-fusion-tier', 'max', '--c3c-fusion-tier=bad']
        self.assert_ran(self.run_launcher(*args))
        self.assertEqual(self.recorded_argv(), args)
        self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings(self.work))

    def test_fusion_tier_with_template_value(self):
        self.write_template(lambda d: d.update(fusionTier='standard'))
        self.assert_ran(self.run_launcher('--version'))
        self.assertEqual(json.loads(self.settings.read_text())['fusionTier'], 'standard')
        os.unlink(str(self.record) + '.argv')
        self.assert_ran(self.run_launcher('--c3c-fusion-tier', 'max', '--version'))
        self.assertEqual(json.loads(self.settings.read_text())['fusionTier'], 'max')

    # --- 雛形の検査 -----------------------------------------------------------

    def test_refuses_weakened_settings(self):
        cases = {
            'allowOutbound': lambda d: d['sandbox']['userPolicy']['network'].update(allowOutbound=True),
            'allowLocalNetwork': lambda d: d['sandbox']['userPolicy']['network'].update(allowLocalNetwork=True),
            'allowBypass': lambda d: d['sandbox'].update(allowBypass=True),
            'enabled': lambda d: d['sandbox'].update(enabled=False),
            'auth.gh': lambda d: d['sandbox']['auth'].update(gh=True),
            'auth.git': lambda d: d['sandbox']['auth'].update(git=True),
            'allowDevToolAccess': lambda d: d['sandbox'].update(allowDevToolAccess=True),
            'sandboxMcpServers': lambda d: d['sandbox'].update(sandboxMcpServers=False),
            'sandboxLspServers': lambda d: d['sandbox'].update(sandboxLspServers=False),
            'addCurrentWorkingDirectory': lambda d: d['sandbox'].update(addCurrentWorkingDirectory=True),
            'no sandbox': lambda d: d.pop('sandbox'),
            'no network': lambda d: d['sandbox']['userPolicy'].pop('network'),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.write_template(mutate)
                self.assert_refused(self.run_launcher('--version'))

    def test_refuses_missing_denied_paths(self):
        secrets = str(self.home / '.config' / 'c3c' / 'secrets')
        tmp = str(self.fake_tmp)
        for value in ([], [tmp], [secrets], tmp, [secrets, tmp, 3]):
            with self.subTest(value=value):
                self.write_template(lambda d: d['sandbox']['userPolicy']['filesystem'].update(deniedPaths=value))
                self.assert_refused(self.run_launcher('--version'))
        self.write_template(lambda d: d['sandbox']['userPolicy']['filesystem']['deniedPaths'].append('/srv'))
        self.assert_ran(self.run_launcher('--version'))

    def test_refuses_non_bool_values(self):
        cases = {
            'allowBypass 0': lambda d: d['sandbox'].update(allowBypass=0),
            'auth.git null': lambda d: d['sandbox']['auth'].update(git=None),
            'enabled "true"': lambda d: d['sandbox'].update(enabled='true'),
            'allowOutbound "false"': lambda d: d['sandbox']['userPolicy']['network'].update(allowOutbound='false'),
            'enabled 1': lambda d: d['sandbox'].update(enabled=1),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.write_template(mutate)
                self.assert_refused(self.run_launcher('--version'))

    def test_refuses_unknown_sandbox_keys(self):
        cases = {
            'filesystem.readwritePaths': lambda d: d['sandbox']['userPolicy']['filesystem'].update(readwritePaths=['/x']),
            'filesystem.readonlyPaths in template': lambda d: d['sandbox']['userPolicy']['filesystem'].update(readonlyPaths=['/x']),
            'sandbox.maskedEnv': lambda d: d['sandbox'].update(maskedEnv=[]),
            'sandbox.credentials': lambda d: d['sandbox'].update(credentials={'envVars': {}}),
            'userPolicy.proxy': lambda d: d['sandbox']['userPolicy'].update(proxy='http://x'),
            'network.proxy': lambda d: d['sandbox']['userPolicy']['network'].update(proxy='http://x'),
            'auth.extra': lambda d: d['sandbox']['auth'].update(extra=False),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.write_template(mutate)
                self.assert_refused(self.run_launcher('--version'))

    def test_ignores_keys_outside_sandbox(self):
        self.write_template(lambda d: d.update(model='gemini-4-argon', banner='never'))
        self.assert_ran(self.run_launcher('--version'))

    def test_refuses_broken_json(self):
        for text in ('{', '', '[]', 'null', '{"sandbox": []}'):
            with self.subTest(text=text):
                self.template.write_text(text)
                self.assert_refused(self.run_launcher('--version'))

    def test_refuses_missing_template(self):
        self.template.unlink()
        self.assert_refused(self.run_launcher('--version'))

    # --- 作業ディレクトリ -----------------------------------------------------

    def test_refuses_sensitive_cwd(self):
        refused = [Path('/'), self.home, self.home.parent, self.root,
                   self.home / '.config' / 'c3c' / 'secrets', self.home / '.claude', self.home / '.codex',
                   self.home / '.copilot', self.home / '.ssh', self.home / '.local' / 'share']
        for path in refused:
            path.mkdir(parents=True, exist_ok=True)
        for path in refused:
            with self.subTest(cwd=str(path)):
                self.assert_refused(self.run_launcher('--version', cwd=path))
        allowed = [self.work, self.work / 'sub', self.home / 'work' / '.hidden',
                   self.root / 'workspace', self.root / 'home' / 'node2']
        for path in allowed:
            path.mkdir(parents=True, exist_ok=True)
        for path in allowed:
            with self.subTest(cwd=str(path)):
                result = self.run_launcher('--version', cwd=path)
                self.assert_ran(result)
                self.assertEqual(Path(str(self.record) + '.cwd').read_text().strip(), str(path))
                os.unlink(str(self.record) + '.argv')

    def test_refuses_cwd_in_denied_paths(self):
        """作業ディレクトリは readonlyPaths に入るので、deniedPaths（/tmp・SECRETS_DIR）とその下と重ねない。"""
        refused = [self.fake_tmp, self.fake_tmp / 'sub', self.home / '.config' / 'c3c' / 'secrets' / 'sub']
        for path in refused:
            path.mkdir(parents=True, exist_ok=True)
            with self.subTest(cwd=str(path)):
                self.assert_refused(self.run_launcher('--version', cwd=path))
        sibling = self.root / 'faketmp2'
        sibling.mkdir()
        self.assert_ran(self.run_launcher('--version', cwd=sibling))

    def test_refuses_cwd_with_newline(self):
        for name in ('trailing\n', 'mid\ndle'):
            path = self.home / name
            path.mkdir()
            with self.subTest(name=name):
                self.assert_refused(self.run_launcher('--version', cwd=path))

    def test_refuses_concurrent_launch(self):
        """settings.json は 1 つを共有するので、別の copilot が動いている間は起動しない。"""
        self.copilot_home.mkdir(mode=0o700)
        lock = self.copilot_home / '.c3c-launch.lock'
        with open(lock, 'a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_launcher('--version')
            self.assert_refused(result, r'並行')
        self.assert_ran(self.run_launcher('--version'))

    def test_refuses_symlink_into_sensitive_cwd(self):
        link = self.root / 'link-to-secrets'
        link.symlink_to(self.home / '.config' / 'c3c' / 'secrets')
        result = subprocess.run(['/bin/bash', '-c', 'cd "$1" && exec /bin/bash "$2" --version', '_', str(link),
                                 str(self.launcher)], env={'PATH': '/usr/bin:/bin', 'HOME': str(self.home)},
                                capture_output=True, text=True, timeout=30)
        self.assert_refused(result)

    def test_refuses_missing_cwd(self):
        gone = self.home / 'gone'
        gone.mkdir()
        result = subprocess.run(['/bin/bash', '-c', 'cd "$1" && rmdir "$1" && exec /bin/bash "$2" --version', '_',
                                 str(gone), str(self.launcher)], env={'PATH': '/usr/bin:/bin', 'HOME': str(self.home)},
                                capture_output=True, text=True, timeout=30)
        self.assert_refused(result)

    # --- トークン -------------------------------------------------------------

    def test_requires_token_file(self):
        cases = {
            'missing': None, 'empty': b'', 'lf only': b'\n', 'two lines': b'abc\ndef\n', 'cr': b'abc\r\n',
            'space': b'abc def\n', 'tab': b'abc\tdef\n', 'nul': b'abc\0def\n', 'non-ascii': 'abcé\n'.encode(),
            'two lf': b'abc\n\n',
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                if self.token_file.exists():
                    self.token_file.unlink()
                if content is not None:
                    self.token_file.write_bytes(content)
                self.assert_refused(self.run_launcher('--version'), r'COPILOT_PAT')
        for content in (TOKEN.encode(), (TOKEN + '\n').encode()):
            with self.subTest(ok=content):
                self.token_file.write_bytes(content)
                result = self.run_launcher('--version')
                self.assert_ran(result)
                self.assertEqual(self.recorded_env()['COPILOT_GITHUB_TOKEN'], TOKEN)
                os.unlink(str(self.record) + '.argv')

    def test_token_file_matches_entrypoint(self):
        mount = re.search(r'(?m)^SECRETS_MOUNT=(\S+)$', ENTRYPOINT.read_text()).group(1)
        self.assertRegex(LAUNCHER.read_text(), r'(?m)^readonly TOKEN_FILE=' + re.escape(mount) + r'/COPILOT_PAT$')

    # --- 環境と引数 -----------------------------------------------------------

    def test_env_is_allowlisted(self):
        extra = {'GH_TOKEN': 'gh-secret', 'GITHUB_TOKEN': 'github-secret', 'COPILOT_GITHUB_TOKEN': 'old',
                 'GITHUB_MCP_PAT': 'mcp-secret', 'AWS_ACCESS_KEY_ID': 'aws-secret', 'COPILOT_HOME': '/elsewhere',
                 'COPILOT_ALLOW_ALL': 'true', 'GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS': '1', 'BASH_ENV': '/x',
                 'PYTHONPATH': '/x', 'CONTAINER_HOME': '/elsewhere', 'SAFE_PATH': '/x', 'TERM': 'xterm', 'TZ': 'Asia/Tokyo', 'NO_COLOR': '1'}
        result = self.run_launcher('--version', env_extra=extra)
        self.assert_ran(result)
        env = self.recorded_env()
        unexpected = set(env) - ALLOWED_ENV - SET_BY_LAUNCHER - SHELL_ADDED
        self.assertEqual(unexpected, set())
        self.assertEqual(env['COPILOT_GITHUB_TOKEN'], TOKEN)
        self.assertEqual(env['COPILOT_HOME'], str(self.copilot_home))
        self.assertEqual(env['COPILOT_AUTO_UPDATE'], 'false')
        self.assertEqual(env['PATH'], f'{self.bwrap_dir}:/usr/local/bin:/usr/bin:/bin')
        self.assertEqual((env['TERM'], env['TZ'], env['NO_COLOR'], env['HOME']),
                         ('xterm', 'Asia/Tokyo', '1', str(self.home)))
        for value in ('gh-secret', 'github-secret', 'mcp-secret', 'aws-secret', '/elsewhere'):
            self.assertNotIn(value, env.values())

    def test_exported_internal_names_do_not_break(self):
        extra = {'token': 'x', 'cwd': '/', 'rel': 'x', 'name': 'x', 'saved_lc_all': 'x', 'saved_lc_all_set': 'set',
                 'fusion_tier': 'max'}
        result = self.run_launcher('--version', env_extra=extra)
        self.assert_ran(result)
        env = self.recorded_env()
        self.assertEqual(env['COPILOT_GITHUB_TOKEN'], TOKEN)
        self.assertEqual(set(extra) & set(env), set())
        self.assertNotIn('fusionTier', json.loads(self.settings.read_text()))

    def test_exported_functions_are_removed(self):
        # dash は名前に % を含む環境変数を落とすので、この試験の dummy は環境をそのまま記録する python にする。
        self.js.write_text(f'#!{REAL_PYTHON}\nimport os\nopen({str(self.record) + ".env"!r}, "w").write("\\n".join(os.environ))\n'
                           f'open({str(self.record) + ".argv"!r}, "w").close()\n')
        result = self.run_launcher('--version', env_extra={'BASH_FUNC_leak%%': '() {  echo leaked\n}'})
        self.assert_ran(result)
        names = Path(str(self.record) + '.env').read_text().splitlines()
        self.assertIn('COPILOT_HOME', names, 'dummy が環境を記録している')
        self.assertEqual([n for n in names if n.startswith('BASH_FUNC_')], [])

    def test_xtrace_does_not_print_token(self):
        for how in ('-x', 'SHELLOPTS'):
            with self.subTest(how=how):
                env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(self.home)}
                argv = ['/bin/bash', str(self.launcher), '--version']
                if how == '-x':
                    argv.insert(1, '-x')
                else:
                    env['SHELLOPTS'] = 'xtrace'
                result = subprocess.run(argv, env=env, cwd=str(self.work), capture_output=True, text=True, timeout=30)
                self.assert_ran(result)
                self.assertNotIn(TOKEN, result.stdout + result.stderr)
                os.unlink(str(self.record) + '.argv')

    def test_token_not_in_any_argv(self):
        result = self.run_launcher('-p', 'hello', '--model', 'x')
        self.assert_ran(result)
        python_argv = Path(str(self.record) + '.python-argv').read_bytes()
        self.assertTrue(python_argv, 'python3 の wrapper を通っている（置換が効いている）')
        self.assertNotIn(TOKEN.encode(), python_argv)
        self.assertNotIn(TOKEN, self.recorded_argv())
        self.assertNotIn(TOKEN, LAUNCHER.read_text())

    def test_args_passthrough(self):
        args = ['-p', 'a b', '--model', 'x', '', '--available-tools=bash']
        result = self.run_launcher(*args)
        self.assert_ran(result)
        self.assertEqual(self.recorded_argv(), args)

    def test_exit_code_passthrough(self):
        self.js.write_text('#!/bin/sh\n: > "{0}.argv"\nexit 7\n'.format(self.record))
        result = self.run_launcher('--version')
        self.assertEqual(result.returncode, 7)

    def test_refuses_missing_shim_or_copilot(self):
        for target in ('shim', 'shim-not-executable', 'js', 'js-not-executable'):
            with self.subTest(target=target):
                shim = self.bwrap_dir / 'bwrap'
                shim.write_text('#!/bin/sh\nexit 0\n')
                shim.chmod(0o755)
                self.js.write_text(DUMMY_JS.format(record=self.record))
                self.js.chmod(0o755)
                if target == 'shim':
                    shim.unlink()
                elif target == 'shim-not-executable':
                    shim.chmod(0o644)
                elif target == 'js':
                    self.js.unlink()
                else:
                    self.js.chmod(0o644)
                self.assert_refused(self.run_launcher('--version'))


if __name__ == '__main__':
    unittest.main()
