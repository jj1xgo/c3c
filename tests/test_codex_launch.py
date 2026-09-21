#!/usr/bin/env python3
"""`--agent codex` の launcher 経路（c3c 第1段階 Task 2）の回帰試験。

実物の launcher を隔離 HOME・fixture project・fake podman/compose で起動する。実 Podman・実 network・
実ユーザー設定には触れない。preflight の protocol は fake compose が fixture を返し、人間確認は専用 PTY で行う。
compose.codex-preflight.yml と codex-mcp-audit.py は実アセットを runner へコピーして使う。
"""

import fcntl
import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import termios
import unittest

REPO = Path(__file__).resolve().parents[1]
SUPPORTED = '0.155.1'
PREFLIGHT_OVERRIDE = 'compose.codex-preflight.yml'
LABEL = 'io.c3c.codex-audit-protocol'
HASH_A = 'a' * 64
HASH_B = 'b' * 64

# 実 Podman の代わり。状態ファイルで image の有無・label・preflight の応答を切り替え、全呼び出しを記録する。
PODMAN = '''#!/usr/bin/env python3
import json, os, sys
state_path = %r
root = os.path.dirname(state_path)
with open(state_path) as handle:
    state = json.load(handle)
args = sys.argv[1:]
if args[:1] == ['--remote=false']:
    args = args[1:]
try:
    stdin = os.readlink('/proc/self/fd/0')
except OSError:
    stdin = '?'
record = {'args': args, 'stdin': stdin,
          'env': {k: os.environ.get(k) for k in ('CC_AGENT', 'CC_CODEX_START_MODE', 'CC_CODEX_READ_ONLY',
                                                  'CODEX_MCP_APPROVAL_FILE', 'MCP_APPROVAL_FILE', 'CODEX_DIR')}}
with open(os.path.join(root, 'calls'), 'a') as out:
    out.write(json.dumps(record) + '\\n')
def save():
    with open(state_path, 'w') as handle:
        json.dump(state, handle)
head = ' '.join(args[:2])
if head == 'images --all':
    print('[]')
elif head == 'image exists':
    sys.exit(0 if state.get('image_exists') else 1)
elif head == 'image inspect':
    if not state.get('image_exists'):
        sys.exit(125)
    fmt = args[args.index('--format') + 1] if '--format' in args else ''
    if 'io.c3c.codex-audit-protocol' in fmt:
        print(state.get('label', ''))
    elif 'ipv6-support' in fmt:
        print('1')
    else:
        print('')
elif head.startswith('ps '):
    print('[]')
elif args[:1] == ['compose']:
    verb = next((a for a in args if a in ('build', 'run')), None)
    if verb == 'build':
        state['image_exists'] = True
        state['label'] = state.get('build_label', '1')
        save()
    elif verb == 'run' and any(a.endswith('compose.codex-preflight.yml') for a in args):
        spec = state.get('preflight', {})
        sys.stdout.write(spec.get('stdout', ''))
        sys.stdout.flush()
        sys.stderr.write(spec.get('stderr', 'INFO: preflight log line\\n'))
        sys.stderr.flush()
        sys.exit(spec.get('rc', 0))
elif args[:1] in (['rmi'], ['network'], ['image']):
    pass
else:
    print('想定外の podman 呼び出し: ' + repr(args), file=sys.stderr)
    sys.exit(125)
'''

CURL = '''#!/bin/sh
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then
    printf '%s\\n' '{"web":[],"api":[],"git":[]}' > "$2"
    exit 0
  fi
  shift
done
exit 2
'''


def protocol(hash_value=HASH_A, count=None, servers=None, version=SUPPORTED, protocol_version=1):
    if servers is None:
        servers = [{'name': 'alpha', 'command': 'python3', 'args': ['server.py', '--flag'], 'cwd': '/workspace',
                    'env_keys': ['API_KEY'], 'env_vars': ['HOME', {'name': 'TOKEN', 'source': 'local'}]}]
    doc = {'protocol_version': protocol_version, 'codex_version': version, 'hash': hash_value,
           'count': len(servers) if count is None else count, 'servers': servers}
    return json.dumps(doc, ensure_ascii=False) + '\n'


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-codex-launch-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        (self.home / '.claude').mkdir(parents=True)
        (self.home / '.claude.json').write_text('{}')
        self.codex_dir = self.root / 'codex-home'
        self.codex_dir.mkdir(mode=0o700)
        self.proj = self.root / 'proj'
        self.conf = self.proj / '.claude-container.d'
        self.conf.mkdir(parents=True)
        (self.conf / 'env').write_text(f'CODEX_DIR={self.codex_dir}\n')
        (self.conf / 'codex-version.txt').write_text(SUPPORTED + '\n')
        (self.conf / 'node-version.txt').write_text('22\n')
        self.tmpdir = self.root / 'tmp'
        self.tmpdir.mkdir()
        # 実 launcher と実アセット（compose.codex-preflight.yml・codex-mcp-audit.py を含む）を runner へコピーする。
        self.runner = self.root / 'runner'
        self.runner.mkdir()
        for source in REPO.iterdir():
            if source.is_file() and not source.name.startswith('.'):
                shutil.copy2(source, self.runner / source.name)
        self.assertTrue((self.runner / PREFLIGHT_OVERRIDE).is_file(), '固定 preflight override が同梱されていない')
        self.assertTrue((self.runner / 'codex-mcp-audit.py').is_file(), '審査 helper が同梱されていない')
        self.launcher = self.runner / 'claude-container'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.state_path = self.root / 'state.json'
        (self.bin / 'podman').write_text(PODMAN % str(self.state_path))
        (self.bin / 'podman').chmod(0o755)
        (self.bin / 'curl').write_text(CURL)
        (self.bin / 'curl').chmod(0o755)
        self.state = {'image_exists': True, 'label': '1', 'preflight': {'stdout': protocol()}}
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'HOME': str(self.home),
                    'TMPDIR': str(self.tmpdir), 'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
        self.store = self.home / '.local/state/claude-container/mcp-approvals'

    def project_name(self):
        """既存 Bash のキー算出を独立した期待値として使う（tests/test_project_images.py と同じ流儀）。"""
        func = self.launcher.read_text().split('compute_project_name() {', 1)[1].split('\n}', 1)[0]
        result = subprocess.run(['bash', '-c', 'WORKING_DIR=$1\ncompute_project_name() {' + func + '\n}\n'
                                 'compute_project_name\nprintf %s "$PROJECT_NAME"', '_', str(self.proj)],
                                capture_output=True, check=True)
        return os.fsdecode(result.stdout)

    def record_path(self, version=SUPPORTED):
        return self.store / 'codex' / self.project_name() / f'{version}.json'

    def approve(self, hash_value=HASH_A):
        """前回のホスト承認を再現する（launcher が書く正本と同じ形）。"""
        record = self.record_path()
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': hash_value},
                                     separators=(',', ':')) + '\n')
        return record

    def run_launcher(self, *args, answer=None, tty=False, env_extra=None, cwd=None):
        """launcher を隔離環境で起動する。tty=True なら専用 PTY を制御端末にし、answer を /dev/tty へ流す。"""
        self.state_path.write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        env = dict(self.env, **(env_extra or {}))
        command = ['bash', str(self.launcher), *args]
        if tty:
            master, slave = pty.openpty()

            def preexec():
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

            proc = subprocess.Popen(command, cwd=cwd or self.root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    preexec_fn=preexec, pass_fds=(slave,))
            os.close(slave)
            os.write(master, (answer + '\n').encode() if answer is not None else b'\x04')
            try:
                stdout, stderr = proc.communicate(timeout=90)
            finally:
                os.close(master)
            result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
        else:
            result = subprocess.run(command, cwd=cwd or self.root, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=90, start_new_session=True)
        self.calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.state = json.loads(self.state_path.read_text())
        return result

    def compose_calls(self, verb=None):
        calls = [c for c in self.calls if c['args'][:1] == ['compose']]
        if verb:
            calls = [c for c in calls if verb in c['args']]
        return calls

    def preflight_calls(self):
        return [c for c in self.compose_calls('run') if any(a.endswith(PREFLIGHT_OVERRIDE) for a in c['args'])]

    def main_runs(self):
        return [c for c in self.compose_calls('run') if not any(a.endswith(PREFLIGHT_OVERRIDE) for a in c['args'])]

    def assert_no_containers(self):
        self.assertEqual(self.compose_calls(), [], [c['args'] for c in self.calls])

    def snapshot(self, path):
        entries = []
        for item in sorted(path.rglob('*')):
            stat = item.lstat()
            entries.append((str(item), stat.st_mode, stat.st_size, stat.st_mtime_ns))
        return entries


class ParserTests(LaunchCase):
    def test_invalid_agent_options_exit_2_without_touching_podman(self):
        cases = {
            'missing value': ['--agent'],
            'missing value before option': ['--agent', '--check'],
            'unknown value': ['--agent', 'gemini'],
            'empty value': ['--agent', ''],
            'empty equals value': ['--agent='],
            'repeated': ['--agent', 'codex', '--agent', 'codex'],
            'repeated mixed': ['--agent=claude', '--agent', 'codex'],
            'read-only with claude': ['--agent', 'claude', '--read-only'],
            'read-only default': ['--read-only'],
            'repeated read-only': ['--agent', 'codex', '--read-only', '--read-only'],
            'clean with agent': ['--agent', 'codex', '--clean'],
            'clean project with agent': ['--clean', '--agent', 'codex'],
            'clean-missing with agent': ['--check', '--clean-missing', '--agent', 'codex'],
        }
        before = self.snapshot(self.home)
        for label, args in cases.items():
            with self.subTest(case=label):
                result = self.run_launcher(*args, str(self.proj))
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.snapshot(self.home), before)

    def test_help_documents_agent_and_read_only(self):
        result = self.run_launcher('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--agent', result.stdout)
        self.assertIn('--read-only', result.stdout)


class DefaultClaudeTests(LaunchCase):
    def test_default_and_explicit_claude_keep_existing_argv_and_never_preflight(self):
        for args in ([], ['--agent', 'claude'], ['--agent=claude']):
            with self.subTest(args=args):
                result = self.run_launcher(*args, str(self.proj))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.preflight_calls(), [])
                (run,) = self.main_runs()
                self.assertEqual(run['args'][-3:], ['run', '--rm', 'claude-auth-workspace'])
                self.assertNotIn('-T', run['args'])
                self.assertEqual(run['env']['CC_AGENT'], 'claude')
                self.assertIsNone(run['env']['CODEX_MCP_APPROVAL_FILE'] or None)
                self.assertFalse(any(a.endswith(PREFLIGHT_OVERRIDE) for a in run['args']))
                self.assertEqual(len(self.compose_calls()), 1)

    def test_env_file_and_shell_cannot_select_agent_or_replace_ledger(self):
        (self.conf / 'env').write_text(f'CODEX_DIR={self.codex_dir}\nCC_AGENT=codex\nCC_CODEX_START_MODE=preflight\n'
                                       f'CC_CODEX_READ_ONLY=1\nCODEX_MCP_APPROVAL_FILE=/etc/passwd\n'
                                       f'MCP_APPROVAL_STORE={self.root}/evil\n')
        result = self.run_launcher(str(self.proj), env_extra={'CC_AGENT': 'codex', 'CC_CODEX_READ_ONLY': '1',
                                                              'CODEX_MCP_APPROVAL_FILE': '/etc/passwd'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.preflight_calls(), [])
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CC_AGENT'], 'claude')
        self.assertIn(run['env']['CC_CODEX_READ_ONLY'], (None, '0'))
        self.assertIn(run['env']['CODEX_MCP_APPROVAL_FILE'], (None, ''))
        for key in ('CC_AGENT', 'CC_CODEX_START_MODE', 'CC_CODEX_READ_ONLY', 'CODEX_MCP_APPROVAL_FILE', 'MCP_APPROVAL_STORE'):
            self.assertIn(f'キー {key} は claude-container が解釈しない', result.stdout + result.stderr)


class CodexStaticGuardTests(LaunchCase):
    def test_codex_requires_codex_dir(self):
        (self.conf / 'env').write_text('')
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CODEX_DIR', result.stderr)
        self.assert_no_containers()
        check = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertNotEqual(check.returncode, 0)
        self.assertIn('CODEX_DIR', check.stdout)
        self.assert_no_containers()

    def test_codex_version_file_is_diagnosed_statically(self):
        self.approve()
        for label, content, ok in (('missing', None, False), ('empty', '\n', False), ('other pin', '0.156.0\n', False),
                                   ('latest', 'latest\n', True), ('supported', SUPPORTED + '\n', True)):
            with self.subTest(case=label):
                path = self.conf / 'codex-version.txt'
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(content)
                result = self.run_launcher('--agent', 'codex', str(self.proj))
                if ok:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(len(self.main_runs()), 1)
                    if label == 'latest':
                        self.assertIn(SUPPORTED, result.stderr)
                        self.assertIn('WARNING', result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('codex-version.txt', result.stderr)
                    self.assert_no_containers()

    def test_codex_does_not_fall_back_to_claude_on_failure(self):
        (self.conf / 'env').write_text('')
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_runs(), [])


class ImageLabelTests(LaunchCase):
    def test_four_build_combinations_inspect_label_before_any_container_run(self):
        self.approve()
        for exists, build, expect_builds in ((False, False, 1), (False, True, 1), (True, False, 0), (True, True, 1)):
            with self.subTest(exists=exists, build=build):
                self.state = {'image_exists': exists, 'label': '1', 'build_label': '1', 'preflight': {'stdout': protocol()}}
                args = (['-b'] if build else []) + ['--agent', 'codex', str(self.proj)]
                result = self.run_launcher(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(len(self.compose_calls('build')), expect_builds)
                self.assertEqual(len(self.preflight_calls()), 1)
                self.assertEqual(len(self.main_runs()), 1)
                order = [('build' if 'build' in c['args'] else 'inspect' if c['args'][:2] == ['image', 'inspect']
                          else 'run' if 'run' in c['args'] else 'other') for c in self.calls]
                self.assertLess(max(i for i, o in enumerate(order) if o == 'inspect'),
                                min(i for i, o in enumerate(order) if o == 'run'))
                if expect_builds:
                    self.assertLess(order.index('build'), max(i for i, o in enumerate(order) if o == 'inspect'))

    def test_missing_or_unknown_label_blocks_preflight_and_run(self):
        for label in ('', '2', 'yes'):
            with self.subTest(label=label):
                self.state = {'image_exists': True, 'label': label, 'preflight': {'stdout': protocol()}}
                result = self.run_launcher('--agent', 'codex', str(self.proj))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('-b', result.stderr)
                self.assert_no_containers()

    def test_build_that_yields_unsupported_label_is_not_run(self):
        self.state = {'image_exists': False, 'build_label': '', 'preflight': {'stdout': protocol()}}
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.compose_calls('build')), 1)
        self.assertEqual(self.compose_calls('run'), [])

    def test_claude_path_ignores_codex_label(self):
        self.state = {'image_exists': True, 'label': '', 'preflight': {'stdout': protocol()}}
        result = self.run_launcher(str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.main_runs()), 1)


class PreflightTests(LaunchCase):
    def test_preflight_is_non_tty_with_fixed_mode_and_devnull_stdin(self):
        self.approve()
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (pre,) = self.preflight_calls()
        self.assertIn('-T', pre['args'])
        self.assertEqual(pre['stdin'], '/dev/null')
        self.assertEqual(pre['env']['CC_AGENT'], 'codex')
        self.assertEqual(pre['env']['CC_CODEX_START_MODE'], 'preflight')
        self.assertEqual(pre['env']['CC_CODEX_READ_ONLY'], '0')
        self.assertEqual(pre['env']['CODEX_DIR'], str(self.codex_dir))
        self.assertIn('--env-file', pre['args'])
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CC_CODEX_START_MODE'], 'run')
        self.assertEqual(run['env']['CC_AGENT'], 'codex')
        self.assertLess(self.calls.index(pre), self.calls.index(run))
        # override は compose.yml の後ろに積む（同じ service の上書き）。
        idx = [i for i, a in enumerate(pre['args']) if a == '-f']
        self.assertTrue(pre['args'][idx[0] + 1].endswith('compose.yml'))
        self.assertTrue(any(pre['args'][i + 1].endswith(PREFLIGHT_OVERRIDE) for i in idx[1:]))

    def test_read_only_flag_reaches_preflight_and_run(self):
        self.approve()
        result = self.run_launcher('--agent', 'codex', '--read-only', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (pre,) = self.preflight_calls()
        (run,) = self.main_runs()
        self.assertEqual(pre['env']['CC_CODEX_READ_ONLY'], '1')
        self.assertEqual(run['env']['CC_CODEX_READ_ONLY'], '1')

    def test_preflight_failure_or_malformed_protocol_blocks_run_and_writes_nothing(self):
        valid = protocol()
        cases = {
            'nonzero': {'stdout': valid, 'rc': 3},
            'empty': {'stdout': ''},
            'prefix log': {'stdout': 'INFO: leaked log\n' + valid},
            'two documents': {'stdout': valid + valid},
            'list': {'stdout': '[]\n'},
            'protocol 2': {'stdout': protocol(protocol_version=2)},
            'other version': {'stdout': protocol(version='0.156.0')},
            'short hash': {'stdout': protocol(hash_value='a' * 63)},
            'uppercase hash': {'stdout': protocol(hash_value='A' * 64)},
            'count mismatch': {'stdout': protocol(count=2)},
            'count negative': {'stdout': protocol(count=-1, servers=[])},
            'missing servers': {'stdout': json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': HASH_A, 'count': 0}) + '\n'},
            'extra key': {'stdout': json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': HASH_A,
                                                'count': 0, 'servers': [], 'raw': 'x'}) + '\n'},
            'server missing field': {'stdout': protocol(servers=[{'name': 'a', 'command': 'x'}])},
            'server env values': {'stdout': protocol(servers=[{'name': 'a', 'command': 'x', 'args': [], 'cwd': None,
                                                              'env_keys': ['K'], 'env_vars': [], 'env': {'K': 'v'}}])},
            'unknown env_vars source': {'stdout': protocol(servers=[{'name': 'a', 'command': 'x', 'args': [], 'cwd': None,
                                                                     'env_keys': [], 'env_vars': [{'name': 'K', 'source': 'cloud'}]}])},
            'env_vars source int': {'stdout': protocol(servers=[{'name': 'a', 'command': 'x', 'args': [], 'cwd': None,
                                                                 'env_keys': [], 'env_vars': [{'name': 'K', 'source': 1}]}])},
            'env_vars unknown key': {'stdout': protocol(servers=[{'name': 'a', 'command': 'x', 'args': [], 'cwd': None,
                                                                  'env_keys': [], 'env_vars': [{'name': 'K', 'default': 'x'}]}])},
            'bool protocol': {'stdout': protocol(protocol_version=True)},
        }
        for label, spec in cases.items():
            with self.subTest(case=label):
                self.state = {'image_exists': True, 'label': '1', 'preflight': spec}
                result = self.run_launcher('--agent', 'codex', str(self.proj))
                self.assertNotEqual(result.returncode, 0, label)
                self.assertEqual(len(self.preflight_calls()), 1)
                self.assertEqual(self.main_runs(), [])
                self.assertFalse(self.store.exists())
                self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_preflight_temp_files_are_owner_only_even_under_permissive_umask(self):
        # launcher が呼ぶ python3 を薄い wrapper で包み、検証後に protocol/summary の実モードを記録する
        # （一時 dir は直後に削除されるため、外から観測できる唯一の時点）。umask 022 で起動する。
        modes = self.root / 'modes'
        (self.bin / 'python3').write_text(f'''#!/bin/bash
"{sys.executable}" "$@"
rc=$?
if [[ "${{1:-}}" == -I && "${{2:-}}" == - && "${{4:-}}" == */summary ]]; then
  stat -c '%n %a' "$3" "$4" >> "{modes}" 2>&1 || echo "stat failed" >> "{modes}"
  stat -c '%n %a' "$(dirname "$4")" >> "{modes}" 2>&1
fi
exit $rc
''')
        (self.bin / 'python3').chmod(0o755)
        self.approve()
        self.state_path.write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        result = subprocess.run(['bash', str(self.launcher), '--agent', 'codex', str(self.proj)], cwd=self.root,
                                env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90,
                                start_new_session=True, preexec_fn=lambda: os.umask(0o022))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        recorded = modes.read_text().splitlines()
        self.assertEqual(len(recorded), 3, recorded)
        self.assertTrue(recorded[0].endswith('/protocol 600'), recorded)
        self.assertTrue(recorded[1].endswith('/summary 600'), recorded)
        self.assertTrue(recorded[2].endswith(' 700'), recorded)
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_preflight_stderr_is_not_treated_as_protocol(self):
        self.approve()
        self.state['preflight'] = {'stdout': protocol(), 'stderr': '{"protocol_version":1}\nWARNING: firewall\n'}
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.main_runs()), 1)


class ApprovalTests(LaunchCase):
    def test_each_server_and_approval_question_have_separate_lines(self):
        first = json.loads(protocol())['servers'][0]
        second = dict(first, name='beta', command='node', args=['other.js'])
        self.state['preflight'] = {'stdout': protocol(servers=[first, second])}
        result = self.run_launcher('--agent', 'codex', str(self.proj), tty=True, answer='n')
        self.assertEqual(result.returncode, 1)
        lines = result.stderr.splitlines()
        self.assertEqual(len([s for s in lines if s.startswith('  - ')]), 2)
        self.assertTrue(any(s.startswith('これらの MCP') for s in lines))
        self.assertEqual(self.main_runs(), [])

    def expected_record(self, hash_value):
        return json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': hash_value}, separators=(',', ':')) + '\n'

    def test_first_run_prompts_on_tty_and_records_approval(self):
        result = self.run_launcher('--agent', 'codex', str(self.proj), tty=True, answer='y')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('alpha', result.stderr)
        self.assertIn('python3 server.py --flag', result.stderr)
        self.assertNotIn('API_KEY=', result.stderr)
        record = self.record_path()
        self.assertTrue(record.is_file())
        self.assertEqual(json.loads(record.read_text()), {'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': HASH_A})
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(record.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(record.parent.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store.stat().st_mode & 0o777, 0o700)
        self.assertEqual([p.name for p in record.parent.iterdir()], [record.name])
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CODEX_MCP_APPROVAL_FILE'], str(record))
        self.assertIn(run['env']['MCP_APPROVAL_FILE'], (None, ''))
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_same_hash_skips_prompt_without_tty(self):
        first = self.run_launcher('--agent', 'codex', str(self.proj), tty=True, answer='y')
        self.assertEqual(first.returncode, 0, first.stderr)
        record = self.record_path()
        before = record.read_bytes(), record.stat().st_mtime_ns
        second = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(len(self.main_runs()), 1)
        self.assertNotIn('[y/N]', second.stderr)
        self.assertEqual((record.read_bytes(), record.stat().st_mtime_ns), before)

    def test_changed_hash_prompts_again_and_rejection_keeps_old_record(self):
        first = self.run_launcher('--agent', 'codex', str(self.proj), tty=True, answer='y')
        self.assertEqual(first.returncode, 0, first.stderr)
        record = self.record_path()
        old = record.read_bytes()
        self.state['preflight'] = {'stdout': protocol(hash_value=HASH_B)}
        rejected = self.run_launcher('--agent', 'codex', str(self.proj), tty=True, answer='n')
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('[y/N]', rejected.stderr)
        self.assertIn('前回', rejected.stderr)
        self.assertEqual(self.main_runs(), [])
        self.assertEqual(record.read_bytes(), old)
        accepted = self.run_launcher('--agent', 'codex', str(self.proj), tty=True, answer='yes')
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(record.read_text())['hash'], HASH_B)
        self.assertEqual(len(self.main_runs()), 1)

    def test_no_tty_or_eof_never_launches_codex(self):
        for label, kwargs in (('no tty', {}), ('eof', {'tty': True, 'answer': None})):
            with self.subTest(case=label):
                result = self.run_launcher('--agent', 'codex', str(self.proj), **kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.main_runs(), [])
                self.assertFalse(self.record_path().exists())
                self.assertNotIn('コンテナ内', result.stderr)

    def test_zero_servers_is_approved_without_prompt_and_still_verified(self):
        empty_hash = 'e' * 64
        self.state['preflight'] = {'stdout': protocol(hash_value=empty_hash, servers=[])}
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('[y/N]', result.stderr)
        record = self.record_path()
        self.assertEqual(json.loads(record.read_text())['hash'], empty_hash)
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CODEX_MCP_APPROVAL_FILE'], str(record))
        # 空定義から定義ありへ変わると改めて確認する。
        self.state['preflight'] = {'stdout': protocol()}
        changed = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertNotEqual(changed.returncode, 0)
        self.assertEqual(self.main_runs(), [])

    def test_corrupt_or_foreign_record_requires_reconfirmation(self):
        record = self.record_path()
        record.parent.mkdir(parents=True)
        for content in ('', HASH_A + '\n', '{"protocol_version":1,"codex_version":"0.155.0","hash":"%s"}\n' % HASH_A,
                        json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': HASH_B})):
            with self.subTest(content=content[:20]):
                record.write_text(content)
                result = self.run_launcher('--agent', 'codex', str(self.proj))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.main_runs(), [])

    def test_prompt_strips_control_characters_from_display(self):
        servers = [{'name': 'al\x1bpha', 'command': 'py\x07thon3', 'args': ['s\x08.py'], 'cwd': '/work\x08space',
                    'env_keys': ['K\x1bEY'], 'env_vars': ['H\x07OME', {'name': 'T\x00OK', 'source': 'local'}]}]
        self.state['preflight'] = {'stdout': protocol(servers=servers)}
        result = self.run_launcher('--agent', 'codex', str(self.proj), tty=True, answer='n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('alpha: python3 s.py', result.stderr)
        self.assertIn('TOK[local]', result.stderr)
        for char in ('\x1b', '\x07', '\x08', '\x00'):
            self.assertNotIn(char, result.stderr)

    def test_claude_gate_is_not_used_for_codex(self):
        (self.proj / '.mcp.json').write_text(json.dumps({'mcpServers': {'claude-only': {'command': 'evil'}}}))
        self.state['preflight'] = {'stdout': protocol(hash_value='e' * 64, servers=[])}
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('claude-only', result.stderr)
        (run,) = self.main_runs()
        self.assertIn(run['env']['MCP_APPROVAL_FILE'], (None, ''))
        self.assertFalse((self.store / self.project_name()).exists())


class CheckAndCleanTests(LaunchCase):
    def test_check_codex_is_static_and_reports_not_run(self):
        record = self.record_path()
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': HASH_A}) + '\n')
        before_proj, before_home = self.snapshot(self.proj), self.snapshot(self.home)
        result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_no_containers()
        self.assertEqual(self.snapshot(self.proj), before_proj)
        self.assertEqual(self.snapshot(self.home), before_home)
        self.assertIn('not run', result.stdout)
        self.assertNotIn('承認済み', result.stdout)
        self.assertIn(LABEL, result.stdout)

    def test_check_codex_reports_old_image_and_missing_record(self):
        self.state = {'image_exists': True, 'label': ''}
        result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('結果: FAIL', result.stdout)
        self.assertIn(LABEL + '=なし', result.stdout)
        self.assertIn('-b', result.stdout)
        self.assert_no_containers()
        self.state = {'image_exists': False}
        result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('明示', result.stdout)
        self.assert_no_containers()

    def test_check_record_format_is_validated_as_one_strict_json_document(self):
        record = self.record_path()
        record.parent.mkdir(parents=True)
        valid = json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': HASH_A}, separators=(',', ':')) + '\n'
        bad = {
            'garbage before': 'garbage\n' + valid,
            'garbage after': valid + 'garbage\n',
            'two documents': valid + valid,
            'duplicate key': '{"protocol_version":1,"codex_version":"%s","hash":"%s","hash":"%s"}\n' % (SUPPORTED, '0' * 64, HASH_A),
            'wrong version': valid.replace(SUPPORTED, '0.155.0'),
            'dot as wildcard': valid.replace(SUPPORTED, '0x155x1'),
            'protocol 1.0': valid.replace('"protocol_version":1,', '"protocol_version":1.0,'),
            'protocol true': valid.replace('"protocol_version":1,', '"protocol_version":true,'),
            'uppercase hash': valid.replace(HASH_A, HASH_A.upper()),
            'short hash': valid.replace(HASH_A, HASH_A[:-1]),
            'extra key': valid.replace('}\n', ',"servers":[]}\n'),
            'missing key': '{"protocol_version":1,"codex_version":"%s"}\n' % SUPPORTED,
            'nan': valid.replace('"protocol_version":1,', '"protocol_version":NaN,'),
        }
        for label, content in bad.items():
            with self.subTest(case=label):
                record.write_text(content)
                result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
                self.assertNotIn('形式 OK', result.stdout, label)
                self.assertIn('形式が不正', result.stdout, label)
                self.assertIn('結果: WARN', result.stdout, label)
                self.assert_no_containers()
        record.write_text(valid)
        result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertIn('形式 OK', result.stdout)
        self.assertNotIn('形式が不正', result.stdout)
        # 空白の違いは JSON として同じ文書なので静的診断では OK（通常起動は完全一致で再確認する）。
        record.write_text(json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': HASH_A}, indent=1))
        result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertIn('形式 OK', result.stdout)

    def claude_gate_hash(self):
        jq = shutil.which('jq')
        if jq is None:
            self.skipTest('jq がないため Claude ゲートの承認記録を再現できない')
        canonical = subprocess.run([jq, '-S', '-c', '[(.mcpServers // {}) | to_entries[] | select(.value.command != null)]',
                                    str(self.proj / '.mcp.json')], capture_output=True, text=True, check=True).stdout
        return __import__('hashlib').sha256(canonical.encode()).hexdigest()

    def test_check_codex_does_not_mix_claude_gate_diagnostics(self):
        (self.proj / '.mcp.json').write_text(json.dumps({'mcpServers': {'claude-only': {'command': 'evil', 'args': ['x']}}}))
        self.store.mkdir(parents=True)
        claude_record = self.store / self.project_name()
        claude_record.write_text(self.claude_gate_hash())
        for state, claude_text in (('approved', 'stdio 型サーバー承認済み'), ('pending', '未承認/変更あり'), ('parsefail', '解析に失敗')):
            with self.subTest(state=state):
                if state == 'pending':
                    claude_record.unlink()
                elif state == 'parsefail':
                    (self.proj / '.mcp.json').write_text('{broken')
                claude = self.run_launcher('--check', str(self.proj))
                self.assertIn(claude_text, claude.stdout, state)
                self.assertNotIn(LABEL, claude.stdout)
                codex = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
                self.assertEqual(codex.returncode, 0, codex.stdout + codex.stderr)
                self.assertNotIn('MCP監査ゲート', codex.stdout, state)
                self.assertNotIn(claude_text, codex.stdout, state)
                self.assertNotIn('claude-only', codex.stdout, state)
                self.assertIn('.mcp.json', codex.stdout, state)
                self.assert_no_containers()

    def test_check_default_claude_output_has_no_codex_diagnostics(self):
        result = self.run_launcher('--check', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(LABEL, result.stdout)
        self.assertNotIn('not run', result.stdout)

    def test_clean_project_removes_both_agents_all_versions_and_keeps_others(self):
        name = self.project_name()
        mine = self.store / 'codex' / name
        mine.mkdir(parents=True)
        (mine / '0.155.1.json').write_text('{}')
        (mine / '0.150.0.json').write_text('{}')
        (self.store / name).write_text(HASH_A)
        other = self.store / 'codex' / 'other-project-12345678'
        other.mkdir(parents=True)
        (other / '0.155.1.json').write_text('{}')
        (self.store / 'other-project-12345678').write_text(HASH_B)
        result = self.run_launcher('--clean', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(mine.exists())
        self.assertFalse((self.store / name).exists())
        self.assertTrue((other / '0.155.1.json').exists())
        self.assertTrue((self.store / 'other-project-12345678').exists())

    def test_clean_all_removes_store(self):
        mine = self.store / 'codex' / self.project_name()
        mine.mkdir(parents=True)
        (mine / '0.155.1.json').write_text('{}')
        result = self.run_launcher('--clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.store.exists())


if __name__ == '__main__':
    unittest.main()
