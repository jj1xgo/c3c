#!/usr/bin/env python3
"""`c3c` 入口（c3c 第2a段階 Task 1・Task 2）の launcher 経路の回帰試験。

tests/test_codex_launch.py と同じ方式（隔離 HOME・fixture project・fake podman/compose・専用 PTY）で本物の
`c3c`（通常ファイル。旧 `claude-container` は削除済み）を起動する。実 Podman・実ユーザー設定・認証には触れない。
旧名 `claude-container` は fixture 外部の bin に置いた symlink（→ runner/c3c）としてだけ検証し、配布ツリーには
再作成しない。fixture は symlink を保ったまま runner へコピーする。

契約は計画の第4節「2a の利用者向け契約」と「記憶の形式と更新」。
"""

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SUPPORTED = '0.156.0'
PREFLIGHT_OVERRIDE = 'compose.codex-preflight.yml'
HASH_A = 'a' * 64

# 実 Podman の代わり。状態ファイルで image の有無・label・preflight の応答・本 run と build の終了コードを
# 切り替え、全呼び出しを記録する（旧 suite の fake に run_rc / build_rc を足したもの）。
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
                                                  'CODEX_MCP_APPROVAL_FILE', 'MCP_APPROVAL_FILE', 'CODEX_DIR',
                                                  'CONTEXT', 'CLAUDE_CONTAINER_DIR', 'ASSET_HASH', 'BASE_IMAGE',
                                                  'C3C_GITCONFIG_SOURCE', 'GITCONFIG_FILE')}}
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
        rc = state.get('build_rc', 0)
        if rc:
            sys.exit(rc)
        state['image_exists'] = True
        state['label'] = state.get('build_label', '2')
        save()
    elif verb == 'run' and any(a.endswith('compose.codex-preflight.yml') for a in args):
        spec = state.get('preflight', {})
        sys.stdout.write(spec.get('stdout', ''))
        sys.stdout.flush()
        sys.stderr.write(spec.get('stderr', 'INFO: preflight log line\\n'))
        sys.stderr.flush()
        sys.exit(spec.get('rc', 0))
    elif verb == 'run':
        sys.exit(state.get('run_rc', 0))
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


def protocol(hash_value=HASH_A, servers=None):
    if servers is None:
        servers = [{'name': 'alpha', 'command': 'python3', 'args': ['server.py'], 'cwd': '/workspace',
                    'env_keys': [], 'env_vars': [], 'environment_id': None}]
    doc = {'protocol_version': 2, 'hash': hash_value, 'count': len(servers), 'servers': servers}
    return json.dumps(doc, ensure_ascii=False) + '\n'


def copy_tree_keeping_symlinks(source_dir, dest_dir):
    for source in source_dir.iterdir():
        if source.name.startswith('.'):
            continue
        dest = dest_dir / source.name
        if source.is_symlink():
            os.symlink(os.readlink(source), dest)
        elif source.is_file():
            shutil.copy2(source, dest)


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-c3c-launch-', dir='/tmp')
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
        self.runner = self.root / 'runner'
        self.runner.mkdir()
        copy_tree_keeping_symlinks(REPO, self.runner)
        self.launcher = self.runner / 'c3c'
        self.c3c = self.launcher
        # 旧名の外部 symlink（配布ツリーの外）。旧 alias・PATH が残る利用側の呼び出しを表す。
        self.legacy_link = self.root / 'legacy-bin' / 'claude-container'
        self.legacy_link.parent.mkdir()
        self.legacy_link.symlink_to(Path('..') / 'runner' / 'c3c')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.state_path = self.root / 'state.json'
        (self.bin / 'podman').write_text(PODMAN % str(self.state_path))
        (self.bin / 'podman').chmod(0o755)
        (self.bin / 'curl').write_text(CURL)
        (self.bin / 'curl').chmod(0o755)
        self.state = {'image_exists': True, 'label': '2', 'preflight': {'stdout': protocol()}}
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'HOME': str(self.home),
                    'TMPDIR': str(self.tmpdir), 'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
        self.state_dir = self.home / '.local/state/claude-container'
        self.pref_dir = self.state_dir / 'agent-preferences'
        self.store = self.state_dir / 'mcp-approvals'

    # --- fixture helpers -------------------------------------------------

    def project_name(self, path=None):
        func = self.launcher.read_text().split('compute_project_name() {', 1)[1].split('\n}', 1)[0]
        result = subprocess.run(['bash', '-c', 'WORKING_DIR=$1\ncompute_project_name() {' + func + '\n}\n'
                                 'compute_project_name\nprintf %s "$PROJECT_NAME"', '_', str(path or self.proj)],
                                capture_output=True, check=True)
        return os.fsdecode(result.stdout)

    def approve_codex(self, hash_value=HASH_A):
        record = self.store / 'codex' / self.project_name() / 'project-config.json'
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'protocol_version': 2, 'hash': hash_value}, separators=(',', ':')) + '\n')
        return record

    def pref_key(self, path=None):
        result = subprocess.run([sys.executable, '-I', str(self.runner / 'agent-preference.py'), 'key', str(path or self.proj)],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def pref_file(self, path=None):
        return self.pref_dir / (self.pref_key(path) + '.json')

    def set_pref(self, agent, path=None, raw=None):
        target = self.pref_file(path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_text(raw if raw is not None else json.dumps({'schema': 1, 'agent': agent}, separators=(',', ':')) + '\n')
        return target

    def saved_agent(self, path=None):
        target = self.pref_file(path)
        if not target.exists():
            return None
        return json.loads(target.read_text())['agent']

    def snapshot(self, path):
        entries = []
        for item in sorted(path.rglob('*')):
            st = item.lstat()
            body = item.read_bytes() if item.is_file() and not item.is_symlink() else b''
            entries.append((str(item), st.st_mode, st.st_size, body))
        return entries

    # --- launcher invocation ---------------------------------------------

    def run_entry(self, entry, *args, answer=None, tty=False, env_extra=None, cwd=None, interrupt=False,
                  command_prefix=('bash',)):
        """entry（c3c、または c3c を指す symlink の path）を隔離環境で起動する。

        tty=True なら専用 PTY を制御端末にする。answer は /dev/tty へ流す 1 行、None は EOF（Ctrl-D）。
        interrupt=True は Ctrl-C（SIGINT）を送る。ハングはタイムアウト（60 秒）で失敗にする。
        """
        self.state_path.write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        env = dict(self.env, **(env_extra or {}))
        command = [*command_prefix, str(entry), *args]
        if tty:
            master, slave = pty.openpty()

            def preexec():
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

            proc = subprocess.Popen(command, cwd=cwd or self.root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    preexec_fn=preexec, pass_fds=(slave,))
            os.close(slave)
            early_stderr = ''
            if interrupt:
                # プロンプト（番号 [1/2]）が stderr に出て read に入ってから Ctrl-C を届ける
                # （起動前に送ると先頭の trap 'exit 1' INT に当たり、130 の検証にならない）。
                deadline = time.monotonic() + 30
                err_fd = proc.stderr.fileno()
                while '[1/2]' not in early_stderr:
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, 'プロンプトが出ない: ' + early_stderr)
                    ready, _, _ = select.select([err_fd], [], [], remaining)
                    if ready:
                        chunk = os.read(err_fd, 4096)
                        if not chunk:
                            break
                        early_stderr += chunk.decode('utf-8', 'replace')
                os.write(master, b'\x03')
            elif answer is None:
                os.write(master, b'\x04')
            else:
                os.write(master, (answer + '\n').encode())
            try:
                stdout, stderr = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
            finally:
                os.close(master)
            result = subprocess.CompletedProcess(command, proc.returncode, stdout, early_stderr + stderr)
        else:
            result = subprocess.run(command, cwd=cwd or self.root, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=60, start_new_session=True)
        self.calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.state = json.loads(self.state_path.read_text())
        return result

    def run_c3c(self, *args, **kwargs):
        return self.run_entry(self.c3c, *args, **kwargs)

    def run_legacy(self, *args, **kwargs):
        # 旧名の外部 symlink から新入口を実行する（cwd は link の親の兄弟にしない）。
        kwargs.setdefault('cwd', self.root)
        return self.run_entry(self.legacy_link, *args, **kwargs)

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

    def assert_single_run(self, result, agent, context=None):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CC_AGENT'], agent)
        self.assertEqual(run['env']['CONTEXT'], str(context or self.proj))
        return run


class EntryResolutionTests(LaunchCase):
    """c3c を symlink インストールから呼んでも新 parser と正しいアセット基点になる（計画 §8-1）。"""

    def assert_run_dir(self, result, entry_is_c3c=True):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'RUN DIR: {self.runner}', result.stdout)
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CLAUDE_CONTAINER_DIR'], str(self.runner))
        self.assertIn(str(self.runner / 'compose.yml'), run['args'])
        self.assertEqual(run['env']['CC_AGENT'], 'claude')

    def test_c3c_is_the_only_executable_launcher(self):
        self.assertTrue((REPO / 'c3c').is_file())
        self.assertFalse((REPO / 'c3c').is_symlink())
        self.assertTrue(os.access(REPO / 'c3c', os.X_OK))
        self.assertFalse(os.path.lexists(REPO / 'claude-container'))

    def test_absolute_symlink_from_another_directory(self):
        link = self.root / 'abs-bin' / 'c3c'
        link.parent.mkdir()
        link.symlink_to(self.c3c)
        self.assert_run_dir(self.run_entry(link, 'claude', str(self.proj), cwd=self.home))

    def test_relative_symlink_from_another_directory(self):
        link = self.root / 'rel-bin' / 'c3c'
        link.parent.mkdir()
        link.symlink_to(Path('..') / 'runner' / 'c3c')
        # cwd は link の親の兄弟にしない（相対リンクを cwd 基準で解いた偶然の一致を防ぐ）。
        self.assert_run_dir(self.run_entry(link, 'claude', str(self.proj), cwd=self.root))

    def test_two_hop_symlink(self):
        first = self.root / 'hop1' / 'c3c'
        first.parent.mkdir()
        first.symlink_to(Path('..') / 'runner' / 'c3c')
        second = self.root / 'hop2' / 'c3c'
        second.parent.mkdir()
        second.symlink_to(Path('..') / 'hop1' / 'c3c')
        self.assert_run_dir(self.run_entry(second, 'claude', str(self.proj), cwd=self.root))

    def test_invocation_via_path_without_bash_prefix(self):
        link = self.root / 'path-bin' / 'c3c'
        link.parent.mkdir()
        link.symlink_to(Path('..') / 'runner' / 'c3c')
        env_extra = {'PATH': str(link.parent) + ':' + self.env['PATH']}
        result = self.run_entry('c3c', 'claude', str(self.proj), cwd=self.root, env_extra=env_extra, command_prefix=())
        self.assert_run_dir(result)

    def test_bash_dot_slash_in_runner_directory(self):
        result = self.run_entry('./c3c', 'claude', str(self.proj), cwd=self.runner)
        self.assert_run_dir(result)

    def test_dangling_symlink_is_an_explicit_error(self):
        link = self.root / 'dangling' / 'c3c'
        link.parent.mkdir()
        link.symlink_to(Path('..') / 'nowhere' / 'c3c')
        result = self.run_entry(link, 'claude', str(self.proj), cwd=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls, [])

    def test_legacy_name_via_relative_symlink_uses_the_c3c_contract(self):
        # 旧名の外部 symlink でも新 parser・選択記憶・同じアセット基点を使う（旧 parser は復活させない）。
        result = self.run_legacy('claude', str(self.proj))
        self.assert_run_dir(result)
        self.assertNotIn('前回の選択', result.stderr)
        self.approve_codex()
        pref = self.set_pref('codex')
        result = self.run_legacy(str(self.proj))
        self.assert_single_run(result, 'codex')
        self.assertIn('前回の選択', result.stderr)
        self.assertIn(f'RUN DIR: {self.runner}', result.stdout)
        self.assertEqual(self.saved_agent(), 'codex')
        result = self.run_legacy('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertEqual(self.saved_agent(), 'claude')
        self.assertTrue(pref.is_file())


class ParserTests(LaunchCase):
    def test_subcommands_select_the_agent_without_prompt_or_memory(self):
        self.approve_codex()
        before = self.snapshot(self.home)
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertEqual(self.preflight_calls(), [])
        result = self.run_c3c('codex', str(self.proj))
        self.assert_single_run(result, 'codex')
        self.assertEqual(len(self.preflight_calls()), 1)
        self.assertNotIn('[1/2]', result.stderr)
        # 記憶は正常終了後に書く（別テストで検証）。ここでは書込前後で HOME 以下の他項目が変わらないことだけ見る。
        self.assertNotEqual(self.snapshot(self.home), before)

    def test_agent_option_is_accepted_and_duplicates_are_exit_2(self):
        self.approve_codex()
        for args in (['--agent', 'codex'], ['--agent=codex']):
            with self.subTest(args=args):
                self.assert_single_run(self.run_c3c(*args, str(self.proj)), 'codex')
        cases = {
            'same value twice': ['codex', '--agent', 'codex', str(self.proj)],
            'subcommand then option': ['claude', '--agent=codex', str(self.proj)],
            'option then subcommand': ['--agent', 'codex', 'claude', str(self.proj)],
            'option twice': ['--agent', 'codex', '--agent', 'codex', str(self.proj)],
            'missing value': ['--agent', str(self.proj)],
            'unknown value': ['--agent', 'gemini', str(self.proj)],
        }
        for label, args in cases.items():
            with self.subTest(case=label):
                result = self.run_c3c(*args)
                self.assertEqual(result.returncode, 2, label + ': ' + result.stdout + result.stderr)
                self.assertEqual(self.calls, [])

    def test_unknown_options_and_extra_directories_are_exit_2(self):
        other = self.root / 'other'
        other.mkdir()
        cases = {
            'unknown long': ['--foo', str(self.proj)],
            'unknown short': ['-x', str(self.proj)],
            'lone dash': ['-', str(self.proj)],
            'two dirs': [str(self.proj), str(other)],
            'two dirs after subcommand': ['claude', str(self.proj), str(other)],
            'two dirs after --': ['claude', '--', str(self.proj), str(other)],
            'clean two dirs': ['--clean', str(self.proj), str(other)],
            'read-only twice': ['codex', '--read-only', '--read-only', str(self.proj)],
        }
        before = self.snapshot(self.home)
        for label, args in cases.items():
            with self.subTest(case=label):
                result = self.run_c3c(*args)
                self.assertEqual(result.returncode, 2, label + ': ' + result.stdout + result.stderr)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.snapshot(self.home), before)

    def test_legacy_name_uses_the_strict_c3c_parser(self):
        # 旧名の外部 symlink でも旧 parser（未知オプションを位置引数として扱う）は復活しない。
        other = self.root / 'other'
        other.mkdir()
        before = self.snapshot(self.home)
        for label, args in (('unknown option', ['--foo', str(self.proj)]),
                            ('two dirs', [str(self.proj), str(other)]),
                            ('duplicate agent', ['claude', '--agent', 'claude', str(self.proj)]),
                            ('no memory no tty', [str(self.proj)])):
            with self.subTest(case=label):
                result = self.run_legacy(*args)
                self.assertEqual(result.returncode, 2, label + ': ' + result.stdout + result.stderr)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.snapshot(self.home), before)
        # 引数なしは c3c と同じく `.`（cwd）を対象にする。
        self.assert_single_run(self.run_legacy('claude', cwd=self.proj), 'claude')

    def test_directory_defaults_to_cwd_only_for_normal_launch(self):
        self.assert_single_run(self.run_c3c('claude', cwd=self.proj), 'claude')
        # 記憶を置き、無指定でも cwd を対象にする。
        self.set_pref('claude')
        self.assert_single_run(self.run_c3c(cwd=self.proj), 'claude')
        # --check は引数なしを `.` に置き換えず、台帳全件の診断になる（cwd の home は診断せず、台帳の proj を診断する）。
        result = self.run_c3c('--check', cwd=self.home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'=== {self.proj} ===', result.stdout)
        self.assertNotIn(f'=== {self.home} ===', result.stdout)
        # --clean は引数なしを全プロジェクト清掃にする（`.` ではない）。
        result = self.run_c3c('--clean', cwd=self.proj)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(f'イメージを削除します: localhost/{self.project_name()}', result.stdout)

    def test_directory_named_like_a_subcommand_needs_dot_slash_or_double_dash(self):
        codex_dir = self.proj / 'codex'
        codex_dir.mkdir()
        self.set_pref('claude')
        self.set_pref('claude', path=codex_dir)
        self.assert_single_run(self.run_c3c('./codex', cwd=self.proj), 'claude', context=codex_dir)
        self.assert_single_run(self.run_c3c('--', 'codex', cwd=self.proj), 'claude', context=codex_dir)
        self.assert_single_run(self.run_c3c('claude', '--', 'codex', cwd=self.proj), 'claude', context=codex_dir)
        # 先頭の裸の codex は cwd に同名ディレクトリがあってもサブコマンド。
        self.approve_codex()
        self.assert_single_run(self.run_c3c('codex', cwd=self.proj), 'codex', context=self.proj)
        # 2 つ目の位置引数はサブコマンドにならない（dir 2 件で exit 2）。
        result = self.run_c3c(str(self.proj), 'codex')
        self.assertEqual(result.returncode, 2)

    def test_directory_with_spaces(self):
        spaced = self.root / 'my project dir'
        spaced.mkdir()
        self.assert_single_run(self.run_c3c('claude', str(spaced)), 'claude', context=spaced)

    def test_read_only_requires_final_agent_codex(self):
        self.approve_codex()
        self.assertEqual(self.run_c3c('codex', '--read-only', str(self.proj)).returncode, 0)
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CC_CODEX_READ_ONLY'], '1')
        self.pref_file().unlink()
        for label, args, kwargs in (
                ('explicit claude', ['claude', '--read-only', str(self.proj)], {}),
                ('option claude', ['--agent', 'claude', '--read-only', str(self.proj)], {}),
                ('check default claude', ['--check', '--read-only', str(self.proj)], {}),
                ('prompt chooses claude', ['--read-only', str(self.proj)], {'tty': True, 'answer': '1'})):
            with self.subTest(case=label):
                result = self.run_c3c(*args, **kwargs)
                self.assertEqual(result.returncode, 2, label + ': ' + result.stdout + result.stderr)
                self.assertEqual(self.main_runs(), [])
        self.set_pref('claude')
        result = self.run_c3c('--read-only', str(self.proj))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.set_pref('codex')
        result = self.run_c3c('--read-only', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CC_CODEX_READ_ONLY'], '1')
        self.assertIn('前回の選択: codex', result.stderr)

    def test_clean_rejects_agent_and_never_prompts(self):
        for args in (['claude', '--clean', str(self.proj)], ['--agent', 'codex', '--clean', str(self.proj)],
                     ['codex', '--check', '--clean-missing', str(self.proj)]):
            with self.subTest(args=args):
                result = self.run_c3c(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.calls, [])
        result = self.run_c3c('--clean', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('[1/2]', result.stderr)

    def test_help_shows_c3c_syntax_per_entry_name(self):
        result = self.run_c3c('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('c3c', result.stdout.splitlines()[0])
        self.assertIn('claude', result.stdout)
        self.assertIn('codex', result.stdout)
        self.assertIn('削除済み', result.stdout)
        self.assertNotIn('廃止予定', result.stdout)
        legacy = self.run_legacy('--help')
        self.assertEqual(legacy.returncode, 0)
        self.assertEqual(legacy.stdout, result.stdout)


class CheckMigrationInfoTests(LaunchCase):
    """--check の入口移行案内と、対象0件・複数件・FAIL 併存・欠落清掃の契約（旧入口の WARN は削除済み）。"""

    INFO = '入口移行: 旧入口は削除済み。外部スクリプト・alias・PATH の呼び出しは c3c claude / c3c codex へ移行してください'

    def test_check_reports_migration_info_without_mutating_projects_or_home(self):
        self.conf.rename(self.proj / '.c3c')
        for directory in (self.proj / '.c3c', self.home / '.c3c'):
            directory.mkdir(exist_ok=True)
            for name in ('packages.txt', 'requirements.txt', 'allowed-domains.txt'):
                (directory / name).write_text('')
        for name in ('hooks', 'skills', 'plugins', 'commands', 'agents', 'workflows', 'rules', 'output-styles', '.git'):
            (self.home / '.claude' / name).mkdir()
        for name in ('settings.json', 'CLAUDE.md', 'statusline.sh'):
            (self.home / '.claude' / name).write_text('')
        self.state['image_exists'] = False
        self.set_pref('codex')
        self.approve_codex()
        (self.state_dir / 'projects').write_text(str(self.proj) + '\n')
        before = self.snapshot(self.home), self.snapshot(self.proj)
        for entry in (self.legacy_link, self.c3c):
            with self.subTest(entry=entry.name):
                result = self.run_entry(entry, '--check', str(self.proj), str(self.home))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(self.INFO, result.stdout)
                self.assertNotIn('WARNING: 旧入口', result.stdout + result.stderr)
                # HOME を対象にした2件目には既存の rw マウント警告が残る。
                self.assertIn('PASS: 1   WARN: 1   FAIL: 0', result.stdout)
                self.assert_no_containers()
                self.assertEqual((self.snapshot(self.home), self.snapshot(self.proj)), before)

    def test_empty_ledger_check_reports_zero_targets_without_creating_state(self):
        before = self.snapshot(self.home)
        result = self.run_legacy('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(self.INFO, result.stdout)
        self.assertNotIn('WARNING: 旧入口', result.stdout + result.stderr)
        self.assertIn('検査対象: 0 プロジェクト', result.stdout)
        self.assertEqual(self.snapshot(self.home), before)
        self.assert_no_containers()

    def test_check_failure_is_not_hidden_and_next_project_is_still_checked(self):
        result = self.run_legacy('--check', str(self.root / 'missing'), str(self.proj))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        # 2件目（旧名設定 directory の WARN）は 1件目の FAIL に隠れず診断される。
        self.assertIn('PASS: 0   WARN: 1   FAIL: 1', result.stdout)
        self.assertIn('→ 結果: WARN', result.stdout.split(f'=== {self.proj} ===', 1)[1])
        self.assertNotIn('WARNING: 旧入口', result.stdout + result.stderr)
        self.assert_no_containers()

    def test_clean_missing_with_all_targets_filtered_reports_zero_without_warning(self):
        missing = self.root / 'missing'
        self.set_pref('codex')
        (self.state_dir / 'projects').write_text(str(missing) + '\n')
        before = self.snapshot(self.home), self.snapshot(self.proj)
        for entry in (self.legacy_link, self.c3c):
            for args in ((), (str(missing),)):
                with self.subTest(entry=entry.name, explicit=bool(args)):
                    result = self.run_entry(entry, '--check', '--clean-missing', *args)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('検査対象: 0 プロジェクト', result.stdout)
                    self.assertIn(self.INFO, result.stdout)
                    self.assertNotIn('WARNING: 旧入口', result.stdout + result.stderr)
                    self.assert_no_containers()
                    self.assertEqual((self.snapshot(self.home), self.snapshot(self.proj)), before)


class SelectionTests(LaunchCase):
    def test_first_launch_prompts_on_tty_and_answer_selects_claude(self):
        result = self.run_c3c(str(self.proj), tty=True, answer='1')
        self.assert_single_run(result, 'claude')
        self.assertIn('Claude', result.stderr)
        self.assertIn('Codex', result.stderr)
        self.assertEqual(self.saved_agent(), 'claude')

    def test_answer_2_selects_codex(self):
        self.approve_codex()
        result = self.run_c3c(str(self.proj), tty=True, answer='2')
        self.assert_single_run(result, 'codex')
        self.assertEqual(len(self.preflight_calls()), 1)
        self.assertEqual(self.saved_agent(), 'codex')

    def test_invalid_answer_or_eof_is_exit_2_without_retry(self):
        for label, answer in (('three', '3'), ('word', 'codex'), ('empty', ''), ('eof', None), ('two numbers', '1 2'),
                              ('zero', '0'), ('twelve', '12')):
            with self.subTest(case=label):
                result = self.run_c3c(str(self.proj), tty=True, answer=answer)
                self.assertEqual(result.returncode, 2, label + ': ' + result.stdout + result.stderr)
                self.assert_no_containers()
                self.assertFalse(self.pref_dir.exists())
                self.assertEqual(result.stderr.count('Codex'), 1, '再プロンプトしない')

    def test_surrounding_whitespace_in_answer_is_tolerated(self):
        result = self.run_c3c(str(self.proj), tty=True, answer=' 1 ')
        self.assert_single_run(result, 'claude')

    def test_sigint_during_prompt_is_exit_130(self):
        result = self.run_c3c(str(self.proj), tty=True, interrupt=True)
        self.assertEqual(result.returncode, 130, result.stdout + result.stderr)
        self.assert_no_containers()
        self.assertFalse(self.pref_dir.exists())

    def test_no_tty_is_exit_2_with_explicit_examples_and_no_stdin_read(self):
        stdin_file = self.root / 'stdin.txt'
        stdin_file.write_text('1\n')
        self.state_path.write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        with open(stdin_file) as handle:
            result = subprocess.run(['bash', str(self.c3c), str(self.proj)], cwd=self.root, env=self.env, stdin=handle,
                                    capture_output=True, text=True, timeout=60, start_new_session=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('c3c claude', result.stderr)
        self.assertIn('c3c codex', result.stderr)
        self.assertEqual((self.root / 'calls').read_text(), '')
        self.assertFalse(self.pref_dir.exists())

    def test_saved_choice_is_used_and_announced(self):
        self.approve_codex()
        self.set_pref('codex')
        result = self.run_c3c(str(self.proj))
        self.assert_single_run(result, 'codex')
        self.assertIn('INFO: 前回の選択: codex', result.stderr)
        self.set_pref('claude')
        result = self.run_c3c(str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertIn('INFO: 前回の選択: claude', result.stderr)

    def test_explicit_agent_wins_over_saved_choice_and_is_saved_after_success(self):
        self.approve_codex()
        self.set_pref('claude')
        result = self.run_c3c('codex', str(self.proj))
        self.assert_single_run(result, 'codex')
        self.assertNotIn('前回の選択', result.stderr)
        self.assertEqual(self.saved_agent(), 'codex')

    def test_corrupt_saved_choice_warns_and_prompts(self):
        for raw in ('{"schema":1,"agent":"gemini"}\n', 'garbage', '{"schema":true,"agent":"codex"}'):
            with self.subTest(raw=raw[:16]):
                self.set_pref(None, raw=raw)
                result = self.run_c3c(str(self.proj), tty=True, answer='1')
                self.assert_single_run(result, 'claude')
                self.assertIn('WARNING', result.stderr)
                self.assertEqual(self.saved_agent(), 'claude')
                # 明示 CLI は不正記憶を採用せず、そのまま起動して上書きする。
                self.set_pref(None, raw=raw)
                self.approve_codex()
                result = self.run_c3c('codex', str(self.proj))
                self.assert_single_run(result, 'codex')
                self.assertEqual(self.saved_agent(), 'codex')

    def test_saved_codex_that_fails_its_guard_shows_reselect_command(self):
        self.set_pref('codex')
        (self.conf / 'env').write_text('')
        result = self.run_c3c(str(self.proj))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('CODEX_DIR', result.stderr)
        self.assertIn(f'c3c claude {self.proj}', result.stderr)
        self.assert_no_containers()
        self.assertEqual(self.saved_agent(), 'codex', '失敗では上書きしない')
        # 明示指定なら再選択の案内は不要。
        result = self.run_c3c('codex', str(self.proj))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('c3c claude', result.stderr)


# python3 不在の環境。fake podman も python なので、jq で同じ形式の記録を書く bash 版に差し替える。
BASH_PODMAN = '''#!/bin/bash
root=%r
if [[ "${1:-}" == --remote=false ]]; then shift; fi
args_json=$(printf '%%s\\0' "$@" | jq -Rsc 'split("\\u0000")[:-1]')
jq -cn --argjson args "$args_json" --arg agent "${CC_AGENT-}" --arg ctx "${CONTEXT-}" --arg ccd "${CLAUDE_CONTAINER_DIR-}" \\
  '{args: $args, stdin: "?", env: {CC_AGENT: $agent, CONTEXT: $ctx, CLAUDE_CONTAINER_DIR: $ccd}}' >> "$root/calls"
case "${1:-} ${2:-}" in
  "images --all") echo '[]' ;;
  "image exists") exit 0 ;;
  "image inspect") echo '' ;;
esac
exit 0
'''


class NoPythonMixin:
    def path_without_python(self):
        if shutil.which('jq') is None:
            self.skipTest('jq がないため python 不在の fake podman を用意できない')
        (self.bin / 'podman').write_text(BASH_PODMAN % str(self.root))
        nopy = self.root / 'nopy'
        nopy.mkdir()
        for directory in ('/usr/bin', '/bin', '/usr/local/bin'):
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                if name.startswith('python') or (nopy / name).exists():
                    continue
                (nopy / name).symlink_to(os.path.join(directory, name))
        return str(self.bin) + ':' + str(nopy)


class SelectionDegradedTests(LaunchCase, NoPythonMixin):
    def test_without_python3_explicit_agent_runs_without_memory_and_implicit_stops(self):
        env_extra = {'PATH': self.path_without_python()}
        self.set_pref('codex')
        result = self.run_c3c('claude', str(self.proj), env_extra=env_extra)
        self.assert_single_run(result, 'claude')
        self.assertIn('WARNING', result.stderr)
        self.assertEqual(self.saved_agent(), 'codex', '書込は省略')
        result = self.run_c3c(str(self.proj), env_extra=env_extra)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('c3c claude', result.stderr)
        self.assert_no_containers()

    def test_undiagnosable_git_skips_memory_for_explicit_and_stops_for_implicit(self):
        (self.proj / '.git').write_text('gitdir: /nonexistent/c3c-test/.git\n')
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertIn('WARNING', result.stderr)
        self.assertFalse(self.pref_dir.exists())
        result = self.run_c3c(str(self.proj), tty=True, answer='1')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('c3c claude', result.stderr)
        self.assertNotIn('Codex CLI', result.stderr, '選択を尋ねない')
        self.assert_no_containers()
        self.assertFalse(self.pref_dir.exists())


class MemoryUpdateTests(LaunchCase):
    def test_memory_is_written_only_after_main_run_exits_zero(self):
        self.approve_codex()
        self.set_pref('claude')
        self.state['run_rc'] = 17
        result = self.run_c3c('codex', str(self.proj))
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertEqual(len(self.main_runs()), 1)
        self.assertEqual(self.saved_agent(), 'claude')
        self.state['run_rc'] = 0
        result = self.run_c3c('codex', str(self.proj))
        self.assert_single_run(result, 'codex')
        self.assertEqual(self.saved_agent(), 'codex')
        saved = self.pref_file()
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(saved.parent.stat().st_mode & 0o777, 0o700)

    def test_build_preflight_and_rejected_approval_keep_old_value(self):
        self.set_pref('claude')
        with self.subTest(stage='build'):
            self.state = {'image_exists': False, 'build_rc': 3, 'preflight': {'stdout': protocol()}}
            result = self.run_c3c('codex', str(self.proj))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.main_runs(), [])
            self.assertEqual(self.saved_agent(), 'claude')
        with self.subTest(stage='preflight'):
            self.state = {'image_exists': True, 'label': '2', 'preflight': {'stdout': protocol(), 'rc': 5}}
            result = self.run_c3c('codex', str(self.proj))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.main_runs(), [])
            self.assertEqual(self.saved_agent(), 'claude')
        with self.subTest(stage='approval rejected'):
            self.state = {'image_exists': True, 'label': '2', 'preflight': {'stdout': protocol()}}
            result = self.run_c3c('codex', str(self.proj), tty=True, answer='n')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.main_runs(), [])
            self.assertEqual(self.saved_agent(), 'claude')
        with self.subTest(stage='prompt then build failure'):
            self.pref_file().unlink()
            self.state = {'image_exists': False, 'build_rc': 3, 'preflight': {'stdout': protocol()}}
            result = self.run_c3c('-b', str(self.proj), tty=True, answer='1')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.pref_file().exists())

    def test_write_failure_is_a_warning_and_keeps_exit_zero(self):
        self.pref_dir.parent.mkdir(parents=True, mode=0o700)
        self.pref_dir.write_text('not a directory')
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertIn('WARNING', result.stderr)
        self.assertEqual(self.pref_dir.read_text(), 'not a directory')

    def test_check_and_clean_never_touch_memory(self):
        self.approve_codex()
        self.set_pref('codex')
        record = self.pref_file()
        before = record.read_bytes(), record.stat().st_mtime_ns
        for label, runner, args, kwargs in (
                ('check', self.run_c3c, ['--check', str(self.proj)], {}),
                ('check codex', self.run_c3c, ['codex', '--check', str(self.proj)], {}),
                ('check all', self.run_c3c, ['--check'], {}),
                ('check clean-missing', self.run_c3c, ['--check', '--clean-missing', str(self.proj)], {}),
                ('legacy-name check', self.run_legacy, ['--check', str(self.proj)], {}),
                ('clean project', self.run_c3c, ['--clean', str(self.proj)], {}),
                ('clean all', self.run_c3c, ['--clean'], {})):
            with self.subTest(case=label):
                result = runner(*args, **kwargs)
                self.assertEqual(result.returncode, 0, label + ': ' + result.stdout + result.stderr)
                self.assertEqual((record.read_bytes(), record.stat().st_mtime_ns), before, label)
                self.assertNotIn('前回の選択', result.stderr, label)
                self.assertNotIn('前回の選択', result.stdout, label)
        # 記憶が無くても --check は対話しない（TTY があっても。旧名の symlink からでも同じ）。
        record.unlink()
        for label, runner, args in (('legacy-name check tty', self.run_legacy, ['--check', str(self.proj)]),
                                    ('check tty', self.run_c3c, ['--check', str(self.proj)])):
            with self.subTest(case=label):
                result = runner(*args, tty=True, answer=None)
                self.assertEqual(result.returncode, 0, label + ': ' + result.stdout + result.stderr)
                self.assertFalse(record.exists())
                self.assertNotIn('Codex CLI', result.stderr)

    def test_check_does_not_prompt_when_memory_is_absent_and_reports_claude_diagnostics(self):
        result = self.run_c3c('--check', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('MCP監査ゲート', result.stdout)
        self.assertNotIn('io.c3c.codex-audit-protocol', result.stdout)
        self.assertFalse(self.pref_dir.exists())
        result = self.run_c3c('codex', '--check', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('io.c3c.codex-audit-protocol', result.stdout)
        self.assertFalse(self.pref_dir.exists())

    def test_clean_keeps_preferences_while_removing_approvals_and_ledger(self):
        self.set_pref('codex')
        self.approve_codex()
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertTrue((self.state_dir / 'projects').exists())
        result = self.run_c3c('--clean', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.saved_agent(), 'claude')
        result = self.run_c3c('--clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.store.exists())
        self.assertFalse((self.state_dir / 'projects').exists())
        self.assertEqual(self.saved_agent(), 'claude')

    def test_project_env_cannot_move_or_disable_memory(self):
        (self.conf / 'env').write_text(f'CODEX_DIR={self.codex_dir}\nHOME={self.root}/evil\n'
                                       f'CC_STATE_DIR={self.root}/evil\nC3C_PREF_KEY=x\n')
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertEqual(self.saved_agent(), 'claude')
        self.assertFalse((self.root / 'evil').exists())


class GitIdentityThroughLauncherTests(LaunchCase):
    def git(self, *args, cwd):
        env = {'PATH': os.environ['PATH'], 'HOME': str(self.home), 'GIT_CONFIG_GLOBAL': '/dev/null',
               'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
        subprocess.run(['git', *args], cwd=str(cwd), env=env, check=True, capture_output=True, timeout=60)

    def test_linked_worktree_and_subdirectory_share_the_choice_but_another_clone_does_not(self):
        self.git('init', '-q', '-b', 'main', cwd=self.proj)
        self.git('add', '.', cwd=self.proj)
        self.git('commit', '-q', '-m', 'init', cwd=self.proj)
        linked = self.root / 'linked'
        self.git('worktree', 'add', '-q', str(linked), '-b', 'wt', cwd=self.proj)
        clone = self.root / 'clone'
        self.git('clone', '-q', str(self.proj), str(clone), cwd=self.root)
        sub = self.proj / 'sub'
        sub.mkdir()
        # linked worktree にも同じ設定を用意する（fixture の env は追跡済みなので clone/worktree にも入る）。
        self.assert_single_run(self.run_c3c('claude', str(self.proj)), 'claude')
        self.assert_single_run(self.run_c3c(str(linked)), 'claude', context=linked)
        self.assert_single_run(self.run_c3c(str(sub)), 'claude', context=sub)
        result = self.run_c3c(str(clone))
        self.assertEqual(result.returncode, 2, '別 clone は記憶なし → 非 TTY で停止: ' + result.stdout + result.stderr)
        self.assert_no_containers()
        # 別プロジェクトの記憶は別ファイル（自分の env・GIT_* の継承では他 repo へ誘導しない）。
        result = self.run_c3c(str(linked), env_extra={'GIT_DIR': str(clone / '.git'), 'GIT_WORK_TREE': str(clone)})
        self.assert_single_run(result, 'claude', context=linked)


class GitconfigSourceTests(LaunchCase):
    """#149: GITCONFIG_FILE 未設定時の ~/.gitconfig は同梱の空ファイル（:ro）。bind 元は launcher が決める。"""

    def empty(self):
        return self.runner / 'empty.gitconfig'

    def append_env(self, line):
        with (self.conf / 'env').open('a') as handle:
            handle.write(line + '\n')

    def test_repository_ships_an_empty_regular_file(self):
        path = REPO / 'empty.gitconfig'
        self.assertFalse(path.is_symlink())
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_size, 0)

    def test_unset_uses_the_bundled_empty_file(self):
        run = self.assert_single_run(self.run_c3c('claude', str(self.proj)), 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()))
        self.assertIsNone(run['env']['GITCONFIG_FILE'])

    def test_set_uses_the_configured_file(self):
        gitconfig = self.root / 'host.gitconfig'
        gitconfig.write_text('[user]\n\tname = x\n')
        self.append_env(f'GITCONFIG_FILE={gitconfig}')
        run = self.assert_single_run(self.run_c3c('claude', str(self.proj)), 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(gitconfig))

    def test_host_environment_value_is_ignored(self):
        result = self.run_c3c('claude', str(self.proj), env_extra={'C3C_GITCONFIG_SOURCE': '/etc/shadow'})
        run = self.assert_single_run(result, 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()))

    def test_env_file_cannot_set_the_source(self):
        self.append_env('C3C_GITCONFIG_SOURCE=/etc/shadow')
        result = self.run_c3c('claude', str(self.proj))
        run = self.assert_single_run(result, 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()))
        self.assertIn('解釈しないため無視', result.stderr)

    def test_broken_fallback_stops_before_any_container(self):
        target = self.root / 'other.gitconfig'
        target.write_text('')
        for label, breaker in (('nonempty', lambda p: p.write_text('[credential]\n\thelper = store\n')),
                               ('symlink', lambda p: (p.unlink(), p.symlink_to(target))),
                               ('missing', lambda p: p.unlink()),
                               ('directory', lambda p: (p.unlink(), p.mkdir()))):
            with self.subTest(label=label):
                path = self.empty()
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                elif path.exists() or path.is_symlink():
                    path.unlink()
                path.write_text('')
                breaker(path)
                result = self.run_c3c('claude', str(self.proj))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('empty.gitconfig', result.stderr)
                self.assert_no_containers()

    def test_check_reports_broken_fallback(self):
        self.empty().write_text('x\n')
        result = self.run_c3c('--check', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('empty.gitconfig', result.stdout + result.stderr)
        self.assert_no_containers()

    def test_check_reports_the_fallback(self):
        result = self.run_c3c('--check', str(self.proj))
        self.assertIn('git 設定: GITCONFIG_FILE 未設定', result.stdout)

    def test_colon_in_source_path_stops(self):
        gitconfig = self.root / 'a:b.gitconfig'
        gitconfig.write_text('')
        self.append_env(f'GITCONFIG_FILE={gitconfig}')
        result = self.run_c3c('claude', str(self.proj))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('コロン', result.stderr)
        self.assert_no_containers()

    def test_colon_in_run_dir_stops(self):
        # GITCONFIG_FILE 未設定のまま、c3c の置き場所（RUN_DIR）にコロンを含める。
        colon_runner = self.root / 'a:b'
        colon_runner.mkdir()
        copy_tree_keeping_symlinks(REPO, colon_runner)
        result = self.run_entry(colon_runner / 'c3c', 'claude', str(self.proj))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('コロン', result.stderr)
        self.assert_no_containers()

    def test_every_compose_call_gets_the_source(self):
        # 明示ビルド → Codex の preflight → 本起動の 3 種すべてに同じ bind 元が渡る。
        self.state['image_exists'] = False
        self.approve_codex()
        result = self.run_c3c('codex', '-b', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.compose_calls('build')), 1)
        self.assertEqual(len(self.preflight_calls()), 1)
        self.assertEqual(len(self.main_runs()), 1)
        for call in self.compose_calls():
            self.assertEqual(call['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()), call['args'])


if __name__ == '__main__':
    unittest.main()
