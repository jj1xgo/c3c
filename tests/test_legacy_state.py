#!/usr/bin/env python3
"""旧 state（~/.local/state/claude-container）の検出と案内（改名 第 2 段）の関数単位の回帰試験。

c3c から resolve_state_dir() を抽出し、隔離 HOME で実行する。第 2 段は旧 state を読まない・移さない・消さない。
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


def extract(name):
    text = (REPO / 'c3c').read_text()
    start = text.index(f'\n{name}() {{\n') + 1
    end = text.index('\n}\n', start) + 3
    return text[start:end]


def snapshot(root):
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = os.lstat(path)
            result[str(path)] = (st.st_mode, st.st_size, os.readlink(path) if path.is_symlink() else None)
    return result


class LegacyStateTests(unittest.TestCase):
    def setUp(self, home_name='home'):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-state-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / home_name
        self.base = self.home / '.local/state'
        self.base.mkdir(parents=True)
        self.old = self.base / 'claude-container'
        self.new = self.base / 'c3c'

    def run_resolve(self, check=0):
        script = '\n'.join([extract('resolve_state_dir'), 'resolve_state_dir',
                            'printf "DIR=%s\\nNOTICE=%s\\n" "$CC_STATE_DIR" "$CC_STATE_NOTICE"'])
        env = {'HOME': str(self.home), 'PATH': os.environ['PATH'], 'CHECK': str(check), 'CLEAN': '0',
               'LC_ALL': 'C.UTF-8'}
        return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + script], env=env, capture_output=True, text=True)

    def fields(self, result):
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)

    def make_old(self):
        (self.old / 'mcp-approvals').mkdir(parents=True)
        (self.old / 'projects').write_text('/p\n')

    def mv_commands(self, notice):
        # 案内文の mv -T を順に取り出す。パスは %q 済みなので、空白は \ でエスケープされている（Step 3）。
        token = r'(?:\\.|[^\s\\])+'
        commands = re.findall(rf'mv -T -- {token} {token}', notice)
        self.assertTrue(commands, notice)
        return commands

    def run_commands(self, commands):
        return [subprocess.run(['bash', '-c', c], capture_output=True).returncode for c in commands]

    # S2-1: 旧なし → 新、案内なし
    def test_no_old_uses_new_silently(self):
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r), {'DIR': str(self.new), 'NOTICE': ''})

    # S2-2: 旧だけの --check → 新を使い、旧は動かさない。案内の mv -T（1 つ）をそのまま打てば移る
    def test_old_only_check_hint_works(self):
        self.make_old()
        before = snapshot(self.home)
        r = self.run_resolve(check=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(snapshot(self.home), before)
        f = self.fields(r)
        self.assertEqual(f['DIR'], str(self.new))
        commands = self.mv_commands(f['NOTICE'])
        self.assertEqual(len(commands), 1)
        self.assertEqual(self.run_commands(commands), [0])
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')

    # S2-2b: 旧だけの通常起動 → 起動が新を作る前提で「新を退避 → 旧を移す」の 2 手を案内し、そのとおり打てば移る
    def test_old_only_launch_hint_works_after_new_is_created(self):
        self.make_old()
        r = self.run_resolve()
        commands = self.mv_commands(self.fields(r)['NOTICE'])
        self.assertEqual(len(commands), 2)
        self.new.mkdir()                                  # 起動台帳の記録が新を作った状態
        (self.new / 'projects').write_text('/q\n')
        self.assertEqual(self.run_commands(commands), [0, 0])
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')
        self.assertFalse((self.new / 'claude-container').exists())

    # S2-3: 新旧の両方 → 新を使う。旧を移す mv -T だけを先に打っても、旧を新の中へ入れない（失敗する）
    def test_both_present_hint_never_nests_old_into_new(self):
        self.make_old()
        self.new.mkdir()
        (self.new / 'projects').write_text('/q\n')
        r = self.run_resolve()
        f = self.fields(r)
        self.assertEqual(f['DIR'], str(self.new))
        self.assertIn('残っています', f['NOTICE'])
        commands = self.mv_commands(f['NOTICE'])
        self.assertNotEqual(self.run_commands(commands[-1:]), [0])
        self.assertFalse((self.new / 'claude-container').exists())
        self.assertEqual(self.run_commands(commands), [0, 0])
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')

    # S2-4（第 1 段 Minor 2）: 新が壊れた symlink なら「使えない」と知らせる
    def test_dangling_new_is_reported_as_unusable(self):
        self.make_old()
        self.new.symlink_to(self.base / 'nowhere')
        f = self.fields(self.run_resolve())
        self.assertIn('ディレクトリではない', f['NOTICE'])
        self.assertNotIn('を使います', f['NOTICE'])

    # S2-6: 旧がファイルでも検出する（型を問わない）
    def test_old_file_is_detected(self):
        self.old.write_text('x')
        self.assertIn(str(self.old), self.fields(self.run_resolve())['NOTICE'])

    # S2-7: --check でも何も書かない
    def test_check_writes_nothing(self):
        self.make_old()
        before = snapshot(self.home)
        self.run_resolve(check=1)
        self.assertEqual(snapshot(self.home), before)


class QuotedHomeTests(LegacyStateTests):
    # S2-5（第 1 段 Minor 3）: HOME に ' と空白を含んでも、案内の mv -T をそのまま打てば移る
    def setUp(self):
        super().setUp(home_name="it's home")


if __name__ == '__main__':
    unittest.main()
