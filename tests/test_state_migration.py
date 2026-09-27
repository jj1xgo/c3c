#!/usr/bin/env python3
"""state directory の自動移行（改名 第 1 段、spec の遷移表）の関数単位の回帰試験。

c3c から rename_noreplace() と resolve_state_dir() を抽出し、隔離 HOME で実行する。
rename の競合・失敗は rename_noreplace を差し替えて再現する。
"""
import ctypes
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]


def extract(name):
    text = (REPO / 'c3c').read_text()
    start = text.index(f'\n{name}() {{\n') + 1
    end = text.index('\n}\n', start) + 3
    return text[start:end]


class StateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-state-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.base = self.home / '.local/state'
        self.base.mkdir(parents=True)
        self.old = self.base / 'claude-container'
        self.new = self.base / 'c3c'

    def run_resolve(self, check=0, clean=0, override=''):
        script = '\n'.join([extract('rename_noreplace'), override, extract('resolve_state_dir'),
                            'resolve_state_dir',
                            'printf "DIR=%s\\nNOTICE=%s\\n" "$CC_STATE_DIR" "$CC_STATE_NOTICE"'])
        env = {'HOME': str(self.home), 'PATH': os.environ['PATH'], 'CHECK': str(check), 'CLEAN': str(clean),
               'LC_ALL': 'C.UTF-8'}
        return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + script], env=env, capture_output=True, text=True)

    def fields(self, result):
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)

    def skip_if_unsupported(self, result):
        # 実物の rename_noreplace が rc 3（RENAME_NOREPLACE 非対応の FS 等）なら旧 state を使い続ける。
        # その経路は S-6 が検査するので、実 rename を前提にするケースは skip にする。
        if self.fields(result).get('DIR') == str(self.old) and '安全に移行できない' in result.stderr:
            self.skipTest('この環境では RENAME_NOREPLACE が使えない')

    def make_old(self):
        (self.old / 'mcp-approvals').mkdir(parents=True)
        (self.old / 'projects').write_text('/p\n')
        return os.lstat(self.old)

    # S-1: 旧なし → 新、通知なし
    def test_no_old_uses_new_silently(self):
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.new))
        self.assertEqual(r.stderr, '')

    # S-2: 旧ディレクトリだけ → 通常起動でエントリ自体が移り、inode も同じ
    def test_old_directory_is_renamed_on_normal_launch(self):
        st = self.make_old()
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.skip_if_unsupported(r)
        self.assertFalse(os.path.lexists(self.old))
        self.assertEqual((os.lstat(self.new).st_dev, os.lstat(self.new).st_ino), (st.st_dev, st.st_ino))
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')
        self.assertIn('WARNING', r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.new))

    # S-2b: 旧がディレクトリへの symlink → リンク自体が移り、指す先は変わらない
    def test_old_symlink_to_directory_moves_the_link(self):
        real = Path(self.temp.name) / 'elsewhere'
        real.mkdir()
        self.old.symlink_to(real)
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.skip_if_unsupported(r)
        self.assertTrue(self.new.is_symlink())
        self.assertEqual(os.readlink(self.new), str(real))
        self.assertFalse(os.path.lexists(self.old))

    # S-3: 新旧の両方 → 新を使い、旧は残して WARNING
    def test_both_present_keeps_old_and_warns(self):
        self.make_old()
        self.new.mkdir()
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.old.is_dir())
        self.assertEqual(self.fields(r)['DIR'], str(self.new))
        self.assertIn('旧版の c3c のセッションがすべて終わってから', r.stderr)

    # S-3b: 新が壊れた symlink でも「ある」扱い（上書きしない）
    def test_dangling_new_counts_as_present(self):
        self.make_old()
        self.new.symlink_to(self.base / 'nowhere')
        r = self.run_resolve()
        self.assertTrue(self.old.is_dir())
        self.assertTrue(self.new.is_symlink())
        self.assertEqual(self.fields(r)['DIR'], str(self.new))

    # S-4: rename 失敗後に新の同一性が一致（並行起動が先に移した）→ 成功扱い
    def test_concurrent_move_is_accepted_by_identity(self):
        self.make_old()
        override = 'rename_noreplace() { mv -T -- "$1" "$2"; return 1; }'
        r = self.run_resolve(override=override)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.new))

    # S-4b: 同一性を取る前（stat の直前）に並行起動が移し終えた → 判定をやり直して新を使う（ERROR で止めない）
    def test_concurrent_move_before_identity_is_reevaluated(self):
        self.make_old()
        override = ('stat() { if [[ ! -e "$HOME/moved" ]]; then : > "$HOME/moved"; '
                    'mv -T -- "$HOME/.local/state/claude-container" "$HOME/.local/state/c3c"; fi; '
                    'command stat "$@"; }')
        r = self.run_resolve(override=override)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.new))
        self.assertTrue((self.new / 'projects').is_file())
        self.assertNotIn('ERROR', r.stderr)
        self.assertNotIn('ディレクトリではない', r.stderr)

    # S-4c: 旧が見えなくなったのに新も現れていない（権限の喪失・削除など、並行移行ではない）→ 成功扱いにせず止める
    def test_old_vanishing_without_new_is_not_treated_as_concurrent_move(self):
        self.make_old()
        override = ('stat() { if [[ ! -e "$HOME/moved" ]]; then : > "$HOME/moved"; '
                    'rm -rf -- "$HOME/.local/state/claude-container"; fi; command stat "$@"; }')
        r = self.run_resolve(override=override)
        self.assertEqual(r.returncode, 1)
        self.assertIn('ERROR', r.stderr)
        self.assertFalse(os.path.lexists(self.new))

    # S-5: rename 失敗後に新が別物・無い → ERROR で止まる（黙って空にしない）
    def test_failed_move_with_different_target_stops(self):
        self.make_old()
        for override in ('rename_noreplace() { mkdir -p -- "$2"; return 1; }', 'rename_noreplace() { return 1; }'):
            with self.subTest(override=override):
                if self.new.exists():
                    self.new.rmdir()
                r = self.run_resolve(override=override)
                self.assertEqual(r.returncode, 1)
                self.assertIn('ERROR', r.stderr)
                self.assertTrue(self.old.is_dir())

    # S-6: 上書きしない rename が使えない → 旧 state を使い続け、新を作らない
    def test_unsupported_rename_keeps_using_old(self):
        self.make_old()
        r = self.run_resolve(override='rename_noreplace() { return 3; }')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.old))
        self.assertFalse(os.path.lexists(self.new))
        self.assertIn('mv ', r.stderr)

    # S-7: 旧がファイル・壊れた symlink → 移さず新を使い、WARNING
    def test_unusable_old_is_not_moved(self):
        for make in (lambda: self.old.write_text('x'), lambda: self.old.symlink_to(self.base / 'nowhere')):
            with self.subTest():
                if os.path.lexists(self.old):
                    self.old.unlink()
                make()
                r = self.run_resolve()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(os.path.lexists(self.old))
                self.assertFalse(os.path.lexists(self.new))
                self.assertEqual(self.fields(r)['DIR'], str(self.new))
                self.assertIn('WARNING', r.stderr)

    # S-8: --check・--clean は移さず、新が無ければ旧を読む。--check は stderr に出さず NOTICE に積む
    def test_check_and_clean_do_not_migrate(self):
        self.make_old()
        for check, clean in ((1, 0), (0, 1)):
            with self.subTest(check=check, clean=clean):
                r = self.run_resolve(check=check, clean=clean)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(self.old.is_dir())
                self.assertFalse(os.path.lexists(self.new))
                self.assertEqual(self.fields(r)['DIR'], str(self.old))
                if check:
                    self.assertEqual(r.stderr, '')
                    self.assertIn('次の通常起動で', self.fields(r)['NOTICE'])

    # 実物の rename_noreplace: 移動先が空ディレクトリでも上書きしない（通常の rename(2) は空ディレクトリを
    # 置き換えるので、NOREPLACE を外すとここで赤になる）。双方の inode が保たれること。
    def test_real_rename_noreplace_never_overwrites_empty_directory(self):
        old_st = self.make_old()
        self.new.mkdir()
        new_st = os.lstat(self.new)
        script = extract('rename_noreplace') + f'\nrename_noreplace "{self.old}" "{self.new}"'
        r = subprocess.run(['bash', '-c', script], env={'PATH': os.environ['PATH']}, capture_output=True, text=True)
        if r.returncode == 3:
            self.skipTest('この環境では RENAME_NOREPLACE が使えない')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(os.lstat(self.old).st_ino, old_st.st_ino)
        self.assertEqual(os.lstat(self.new).st_ino, new_st.st_ino)
        self.assertEqual(list(self.new.iterdir()), [])

    # errno の対応（E-1）: rename_noreplace の heredoc の Python を、renameat2 を偽物にして実行する。
    def run_helper_with_errno(self, err):
        text = extract('rename_noreplace')
        code = text.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]

        class FakeLibc:
            def renameat2(self, *args):
                ctypes.set_errno(err)
                return -1

        with mock.patch.object(ctypes, 'CDLL', lambda *a, **k: FakeLibc()), \
                mock.patch.object(sys, 'argv', ['-', 'src', 'dst']):
            with self.assertRaises(SystemExit) as caught:
                exec(compile(code, 'rename_noreplace', 'exec'), {'__name__': '__main__'})
        return caught.exception.code

    def test_errno_mapping(self):
        for err in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.EBUSY, errno.EXDEV):
            with self.subTest(errno=errno.errorcode[err]):
                self.assertEqual(self.run_helper_with_errno(err), 3)
        for err in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES, errno.ENOENT):
            with self.subTest(errno=errno.errorcode[err]):
                self.assertEqual(self.run_helper_with_errno(err), 1)

    def test_real_rename_noreplace_moves(self):
        st = self.make_old()
        script = extract('rename_noreplace') + f'\nrename_noreplace "{self.old}" "{self.new}"'
        r = subprocess.run(['bash', '-c', script], env={'PATH': os.environ['PATH']}, capture_output=True, text=True)
        if r.returncode == 3:
            self.skipTest('この環境では RENAME_NOREPLACE が使えない')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.lstat(self.new).st_ino, st.st_ino)


if __name__ == '__main__':
    unittest.main()
