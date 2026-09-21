#!/usr/bin/env python3
"""`agent-preference.py`（c3c 第2a段階の CLI 選択記憶 helper）の契約試験。

実ファイルを subprocess で呼ぶ。Git fixture は一時ディレクトリに作り、実 HOME・実プロジェクトの Git 構成・
認証情報には触れない。契約は計画の第4節「記憶の形式と更新」:
  key   <directory>                → rc0 でキー（sha256 64桁）、rc4 で診断不能
  read  <state-directory> <key>    → rc0 で claude/codex、rc3 で未作成、rc4 で破損・診断不能
  write <state-directory> <key> <agent> → rc0 で保存、rc1 で失敗
"""

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'agent-preference.py'
KEY_RE = re.compile(r'^[0-9a-f]{64}$')


def run_helper(*args, env=None, timeout=30):
    return subprocess.run([sys.executable, '-I', str(HELPER), *[os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in args]],
                          capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)


def git(*args, cwd, env_extra=None):
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/'), 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid', 'LC_ALL': 'C'}
    env.update(env_extra or {})
    return subprocess.run(['git', *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=True, timeout=60)


def snapshot(path):
    entries = []
    if not os.path.lexists(path):
        return [('absent', str(path))]
    for item in sorted([path, *path.rglob('*')]):
        st = item.lstat()
        body = item.read_bytes() if stat.S_ISREG(st.st_mode) else b''
        entries.append((str(item), st.st_mode, st.st_size, body))
    return entries


class HelperCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-agent-pref-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.assertTrue(HELPER.is_file(), 'agent-preference.py が無い')

    def key_of(self, directory, env=None):
        result = run_helper('key', directory, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        key = result.stdout.strip()
        self.assertRegex(key, KEY_RE)
        self.assertEqual(result.stdout, key + '\n')
        return key

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        git('init', '-q', '-b', 'main', cwd=repo)
        (repo / 'README').write_text('x\n')
        git('add', 'README', cwd=repo)
        git('commit', '-q', '-m', 'init', cwd=repo)
        return repo

    def pref_path(self, key):
        return self.state / 'agent-preferences' / f'{key}.json'


class KeyIdentityTests(HelperCase):
    def test_main_linked_worktree_symlink_and_subdirectory_share_one_key(self):
        repo = self.make_repo('repo')
        linked = self.root / 'linked-wt'
        git('worktree', 'add', '-q', str(linked), '-b', 'feature', cwd=repo)
        alias = self.root / 'alias'
        alias.symlink_to(repo)
        sub = repo / 'src' / 'deep'
        sub.mkdir(parents=True)
        main_key = self.key_of(repo)
        self.assertEqual(self.key_of(linked), main_key)
        self.assertEqual(self.key_of(alias), main_key)
        self.assertEqual(self.key_of(sub), main_key)
        (linked / 'src').mkdir()
        self.assertEqual(self.key_of(linked / 'src'), main_key)

    def test_separate_clone_and_unrelated_repo_have_different_keys(self):
        repo = self.make_repo('repo')
        clone = self.root / 'clone'
        git('clone', '-q', str(repo), str(clone), cwd=self.root)
        other = self.make_repo('other')
        keys = {self.key_of(repo), self.key_of(clone), self.key_of(other)}
        self.assertEqual(len(keys), 3)

    def test_non_git_directory_uses_path_identity(self):
        plain = self.root / 'plain'
        plain.mkdir()
        (plain / 'child').mkdir()
        alias = self.root / 'plain-alias'
        alias.symlink_to(plain)
        other = self.root / 'plain2'
        other.mkdir()
        key = self.key_of(plain)
        self.assertEqual(self.key_of(alias), key)
        self.assertNotEqual(self.key_of(plain / 'child'), key)
        self.assertNotEqual(self.key_of(other), key)
        repo = self.make_repo('repo')
        self.assertNotEqual(self.key_of(repo), key)

    def test_moved_repository_gets_a_new_key(self):
        repo = self.make_repo('repo')
        before = self.key_of(repo)
        moved = self.root / 'moved'
        repo.rename(moved)
        self.assertNotEqual(self.key_of(moved), before)

    def test_inherited_git_environment_does_not_redirect_to_another_repo(self):
        repo = self.make_repo('repo')
        other = self.make_repo('other')
        plain = self.root / 'plain'
        plain.mkdir()
        expected_repo = self.key_of(repo)
        expected_plain = self.key_of(plain)
        expected_other = self.key_of(other)
        env = dict(os.environ, GIT_DIR=str(other / '.git'), GIT_WORK_TREE=str(other),
                   GIT_COMMON_DIR=str(other / '.git'), GIT_CEILING_DIRECTORIES=str(self.root),
                   GIT_DISCOVERY_ACROSS_FILESYSTEM='1', GIT_CONFIG_COUNT='1',
                   GIT_CONFIG_KEY_0='core.worktree', GIT_CONFIG_VALUE_0=str(other))
        self.assertEqual(self.key_of(repo, env=env), expected_repo)
        self.assertEqual(self.key_of(plain, env=env), expected_plain)
        self.assertNotEqual(expected_other, expected_repo)

    def test_broken_gitfile_is_undiagnosable_not_path_or_other_repo(self):
        broken = self.root / 'broken'
        broken.mkdir()
        (broken / '.git').write_text('gitdir: /nonexistent/claude-container-test/.git\n')
        result = run_helper('key', broken)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotEqual(result.stderr.strip(), '')

    def test_nested_repo_with_incomplete_git_directory_is_undiagnosable_not_outer_repo(self):
        # レビュー should-fix 1: 非空で HEAD の無い .git は Git が無視して外側 repo へ辿るが、helper は
        # 別 repo の記憶へ誘導せず rc4 にする（空の .git だけを無視する既知判断は保持）。
        outer = self.make_repo('outer')
        inner = outer / 'inner'
        inner.mkdir()
        git('init', '-q', '-b', 'main', cwd=inner)
        outer_key = self.key_of(outer)
        inner_key = self.key_of(inner)
        self.assertNotEqual(inner_key, outer_key, '正常な nested repo は別キー')
        (inner / '.git' / 'HEAD').unlink()
        self.assertTrue(any((inner / '.git').iterdir()), 'fixture: .git は非空のまま')
        result = run_helper('key', inner)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')
        # 空の .git ディレクトリは Git と同じく無視し、外側 repo（nested）または path（非 Git）になる。
        shutil.rmtree(inner / '.git')
        (inner / '.git').mkdir()
        self.assertEqual(self.key_of(inner), outer_key)
        plain = self.root / 'plain'
        (plain / '.git').mkdir(parents=True)
        self.assertRegex(self.key_of(plain), KEY_RE)
        self.assertNotEqual(self.key_of(plain), outer_key)

    def test_dangling_or_non_directory_git_entry_is_undiagnosable(self):
        outer = self.make_repo('outer')
        for label, make in (('dangling symlink', lambda p: p.symlink_to(self.root / 'nowhere' / '.git')),
                            ('fifo', lambda p: os.mkfifo(p))):
            with self.subTest(case=label):
                inner = outer / ('inner-' + label.split()[0])
                inner.mkdir()
                make(inner / '.git')
                result = run_helper('key', inner, timeout=10)
                self.assertEqual(result.returncode, 4, label + ': ' + result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
        # symlink が実 repo の .git を指す場合は通常どおりその repo。
        other = self.make_repo('other')
        linked = self.root / 'via-link'
        linked.mkdir()
        (linked / '.git').symlink_to(other / '.git')
        self.assertEqual(self.key_of(linked), self.key_of(other))

    def test_broken_linked_worktree_is_undiagnosable(self):
        repo = self.make_repo('repo')
        linked = self.root / 'linked'
        git('worktree', 'add', '-q', str(linked), '-b', 'wt', cwd=repo)
        shutil.rmtree(repo)
        result = run_helper('key', linked)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')

    @unittest.skipIf(os.geteuid() == 0, 'root では権限不足を再現できない')
    def test_unreadable_git_directory_is_undiagnosable(self):
        repo = self.make_repo('repo')
        (repo / '.git').chmod(0)
        self.addCleanup((repo / '.git').chmod, 0o700)
        result = run_helper('key', repo)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')

    def test_missing_directory_or_file_is_undiagnosable(self):
        plain = self.root / 'plain'
        plain.mkdir()
        (plain / 'file').write_text('')
        for target in (self.root / 'nope', plain / 'file'):
            with self.subTest(target=target.name):
                result = run_helper('key', target)
                self.assertEqual(result.returncode, 4)
                self.assertEqual(result.stdout, '')

    def test_key_does_not_write_anywhere(self):
        repo = self.make_repo('repo')
        before = snapshot(self.root)
        self.key_of(repo)
        self.assertEqual(snapshot(self.root), before)

    def test_non_utf8_path_is_accepted(self):
        raw = os.path.join(os.fsencode(self.root), b'dir-\xff\xfe')
        os.mkdir(raw)
        key = self.key_of(os.fsdecode(raw))
        self.assertRegex(key, KEY_RE)


class ReadTests(HelperCase):
    def setUp(self):
        super().setUp()
        self.key = 'a' * 64
        self.path = self.pref_path(self.key)

    def write_raw(self, content, mode=0o600):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.write_bytes(content if isinstance(content, bytes) else content.encode())
        self.path.chmod(mode)

    def test_valid_document_returns_agent_on_stdout(self):
        for agent in ('claude', 'codex'):
            with self.subTest(agent=agent):
                self.write_raw('{"schema": 1, "agent": "%s"}\n' % agent)
                result = run_helper('read', self.state, self.key)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, agent + '\n')

    def test_missing_file_is_rc3_and_creates_nothing(self):
        before = snapshot(self.root)
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(snapshot(self.root), before)
        self.path.parent.mkdir(parents=True, mode=0o700)
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 3)

    def test_invalid_documents_are_rc4(self):
        cases = {
            'unknown agent': '{"schema":1,"agent":"gemini"}',
            'empty agent': '{"schema":1,"agent":""}',
            'agent not string': '{"schema":1,"agent":1}',
            'schema string': '{"schema":"1","agent":"codex"}',
            'schema bool': '{"schema":true,"agent":"codex"}',
            'schema 2': '{"schema":2,"agent":"codex"}',
            'schema float': '{"schema":1.0,"agent":"codex"}',
            'duplicate agent': '{"schema":1,"agent":"claude","agent":"codex"}',
            'duplicate schema': '{"schema":1,"schema":1,"agent":"codex"}',
            'extra key': '{"schema":1,"agent":"codex","note":"x"}',
            'missing schema': '{"agent":"codex"}',
            'missing agent': '{"schema":1}',
            'list': '[{"schema":1,"agent":"codex"}]',
            'two documents': '{"schema":1,"agent":"codex"}\n{"schema":1,"agent":"codex"}',
            'trailing garbage': '{"schema":1,"agent":"codex"} x',
            'nan constant': '{"schema":NaN,"agent":"codex"}',
            'empty file': '',
            'not json': 'codex',
            'invalid utf-8': b'{"schema":1,"agent":"codex\xff"}',
            'nul in agent': '{"schema":1,"agent":"codex\\u0000"}',
        }
        for label, content in cases.items():
            with self.subTest(case=label):
                self.write_raw(content)
                result = run_helper('read', self.state, self.key)
                self.assertEqual(result.returncode, 4, label + ': ' + result.stdout + result.stderr)
                self.assertEqual(result.stdout, '', label)

    def test_oversized_file_is_rc4_without_reading_it_all(self):
        padding = ' ' * 4096
        self.write_raw('{"schema":1,"agent":"codex"%s}' % padding)
        self.assertGreater(self.path.stat().st_size, 4096)
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 4)
        # 4096 byte ちょうどまでは許容する（空白は JSON として無視される）。
        content = '{"schema":1,"agent":"codex"}'
        self.write_raw(content + ' ' * (4096 - len(content)))
        self.assertEqual(self.path.stat().st_size, 4096)
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'codex\n')

    def test_symlink_directory_and_fifo_are_rejected_without_waiting(self):
        real = self.root / 'real.json'
        real.write_text('{"schema":1,"agent":"codex"}')
        self.path.parent.mkdir(parents=True, mode=0o700)
        self.path.symlink_to(real)
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 4, 'symlink: ' + result.stdout + result.stderr)
        self.path.unlink()
        self.path.mkdir()
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 4, 'directory')
        self.path.rmdir()
        os.mkfifo(self.path)
        result = run_helper('read', self.state, self.key, timeout=10)
        self.assertEqual(result.returncode, 4, 'fifo: ' + result.stdout + result.stderr)

    def test_symlinked_parent_directory_is_rejected(self):
        real_dir = self.root / 'real-prefs'
        real_dir.mkdir(mode=0o700)
        (real_dir / f'{self.key}.json').write_text('{"schema":1,"agent":"codex"}')
        self.state.mkdir(mode=0o700)
        (self.state / 'agent-preferences').symlink_to(real_dir)
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)

    def test_invalid_key_is_rc4(self):
        for key in ('', 'A' * 64, 'a' * 63, 'a' * 65, '../' + 'a' * 61, 'a' * 64 + '\n', 'g' * 64):
            with self.subTest(key=repr(key)):
                result = run_helper('read', self.state, key)
                self.assertEqual(result.returncode, 4)
                result = run_helper('write', self.state, key, 'codex')
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.state.exists())

    def test_read_does_not_modify_state_tree(self):
        self.write_raw('{"schema":1,"agent":"codex"}', mode=0o644)
        (self.state / 'agent-preferences').chmod(0o755)
        before = snapshot(self.root)
        result = run_helper('read', self.state, self.key)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.root), before)
        self.write_raw('garbage')
        before = snapshot(self.root)
        self.assertEqual(run_helper('read', self.state, self.key).returncode, 4)
        self.assertEqual(snapshot(self.root), before)


class WriteTests(HelperCase):
    def setUp(self):
        super().setUp()
        self.key = 'b' * 64
        self.path = self.pref_path(self.key)

    def test_write_creates_private_directory_and_exact_document(self):
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)
        result = run_helper('write', self.state, self.key, 'codex')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.path.read_text()), {'schema': 1, 'agent': 'codex'})
        self.assertEqual(self.path.read_text(), '{"schema":1,"agent":"codex"}\n')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])
        read = run_helper('read', self.state, self.key)
        self.assertEqual((read.returncode, read.stdout), (0, 'codex\n'))
        result = run_helper('write', self.state, self.key, 'claude')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.path.read_text(), '{"schema":1,"agent":"claude"}\n')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_agent_or_arity_is_rc1_and_writes_nothing(self):
        for args in (('write', self.state, self.key, 'gemini'), ('write', self.state, self.key, ''),
                     ('write', self.state, self.key), ('write', self.state, self.key, 'codex', 'extra'),
                     ('write', self.state, self.key, 'Codex')):
            with self.subTest(args=args[3:]):
                result = run_helper(*args)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.state.exists())

    def test_unknown_subcommand_is_an_error(self):
        for args in ((), ('list',), ('read',), ('key',), ('key', self.root, 'x')):
            with self.subTest(args=args):
                result = run_helper(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(result.returncode, (3,))

    def test_concurrent_writes_leave_one_complete_document(self):
        procs = []
        for i in range(24):
            agent = 'codex' if i % 2 else 'claude'
            procs.append(subprocess.Popen([sys.executable, '-I', str(HELPER), 'write', str(self.state), self.key, agent],
                                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
        for proc in procs:
            _, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, err)
        self.assertIn(self.path.read_text(), ('{"schema":1,"agent":"claude"}\n', '{"schema":1,"agent":"codex"}\n'))
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(os.geteuid() == 0, 'root では書込不能を再現できない')
    def test_unwritable_directory_keeps_old_document_and_leaves_no_temp(self):
        self.assertEqual(run_helper('write', self.state, self.key, 'claude').returncode, 0)
        old = self.path.read_bytes()
        self.path.parent.chmod(0o500)
        self.addCleanup(self.path.parent.chmod, 0o700)
        result = run_helper('write', self.state, self.key, 'codex')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotEqual(result.stderr.strip(), '')
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_short_write_under_file_size_limit_keeps_old_document(self):
        # レビュー should-fix 2: RLIMIT_FSIZE=10 の子プロセスでは write(2) が 10 byte の部分書込を返し、続く
        # write は SIGXFSZ（既定で強制終了）＋ EFBIG になる。helper は全 byte を書けない限り replace せず rc1、
        # 旧文書不変、一時ファイルなし（SIGXFSZ は helper 側で無視し EFBIG を通常の失敗として扱う）。
        import resource
        self.assertEqual(run_helper('write', self.state, self.key, 'claude').returncode, 0)
        old = self.path.read_bytes()

        def limit():
            resource.setrlimit(resource.RLIMIT_FSIZE, (10, 10))

        result = subprocess.run([sys.executable, '-I', str(HELPER), 'write', str(self.state), self.key, 'codex'],
                                capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, preexec_fn=limit)
        self.assertEqual(result.returncode, 1, 'rc=%r stderr=%s' % (result.returncode, result.stderr))
        self.assertNotEqual(result.stderr.strip(), '')
        self.assertEqual(self.path.read_bytes(), old)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])
        read = run_helper('read', self.state, self.key)
        self.assertEqual((read.returncode, read.stdout), (0, 'claude\n'))

    def test_write_refuses_symlink_or_non_regular_target(self):
        real = self.root / 'real.json'
        real.write_text('{"schema":1,"agent":"claude"}\n')
        self.path.parent.mkdir(parents=True, mode=0o700)
        self.path.symlink_to(real)
        result = run_helper('write', self.state, self.key, 'codex')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(real.read_text(), '{"schema":1,"agent":"claude"}\n')
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])
        self.path.unlink()
        self.path.mkdir()
        result = run_helper('write', self.state, self.key, 'codex')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.path.is_dir())

    def test_write_refuses_symlinked_preference_directory(self):
        real_dir = self.root / 'elsewhere'
        real_dir.mkdir()
        self.state.mkdir(mode=0o700)
        (self.state / 'agent-preferences').symlink_to(real_dir)
        result = run_helper('write', self.state, self.key, 'codex')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(list(real_dir.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
