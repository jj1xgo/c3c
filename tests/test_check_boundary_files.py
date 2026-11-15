#!/usr/bin/env python3
"""upgrade の層の前後で境界のファイルを比べる check-boundary-files.sh の回帰試験（#273）。

snapshot で記録し、変えてから verify で比べる。所有者は試験を走らせるユーザーのまま比べる。
"""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'check-boundary-files.sh'


class CheckBoundaryFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.d = self.root / 'bin'
        self.d.mkdir()
        (self.d / 'tool.sh').write_text('#!/bin/sh\necho ok\n')
        (self.d / 'tool.sh').chmod(0o755)
        (self.d / 'link').symlink_to('tool.sh')
        self.f = self.root / 'single'
        self.f.write_text('one\n')
        self.missing = self.root / 'missing-dir'

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, mode, *paths, state=None):
        args = [str(p) for p in (paths or (self.d, self.f, self.missing))]
        return subprocess.run(['/bin/sh', str(SCRIPT), mode, str(state or self.state), *args],
                              capture_output=True, text=True, timeout=60)

    def snapshot(self):
        result = self.run_script('snapshot')
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_changed(self):
        result = self.run_script('verify')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('ERROR: upgrade の層で境界のファイルが変わりました', result.stderr)

    def test_unchanged_passes(self):
        self.snapshot()
        result = self.run_script('verify')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_content_change_detected(self):
        self.snapshot()
        (self.d / 'tool.sh').write_text('#!/bin/sh\necho evil\n')
        self.assert_changed()

    def test_mode_change_detected(self):
        self.snapshot()
        (self.d / 'tool.sh').chmod(0o777)
        self.assert_changed()

    def test_added_file_detected(self):
        self.snapshot()
        (self.d / 'new').write_text('x\n')
        self.assert_changed()

    def test_removed_file_detected(self):
        self.snapshot()
        (self.d / 'tool.sh').unlink()
        self.assert_changed()

    def test_symlink_target_change_detected(self):
        self.snapshot()
        (self.d / 'link').unlink()
        (self.d / 'link').symlink_to('/bin/sh')
        self.assert_changed()

    def test_missing_dir_recorded(self):
        self.snapshot()
        self.missing.mkdir()
        self.assert_changed()

    def test_single_file_path(self):
        self.snapshot()
        self.f.write_text('two\n')
        self.assert_changed()

    def test_unreadable_directory_fails_snapshot(self):
        """走査（find）が失敗したら、記録を作らずに止まる（走査できなかった部分を「同じ」と見なさない）。"""
        if os.getuid() == 0:
            self.skipTest('root は読めないディレクトリを作れない')
        locked = self.d / 'locked'
        locked.mkdir()
        (locked / 'inner').write_text('x\n')
        locked.chmod(0)
        try:
            result = self.run_script('snapshot')
        finally:
            locked.chmod(0o755)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('ERROR:', result.stderr)
        self.assertFalse(self.state.exists())

    def test_newline_in_name_rejected(self):
        (self.d / 'a\nb').write_text('x\n')
        result = self.run_script('snapshot')
        self.assertEqual(result.returncode, 1)
        self.assertIn('ERROR:', result.stderr)

    def test_bad_args_rc2(self):
        for args in (['snapshot'], ['bogus', str(self.state), str(self.d)], ['verify', str(self.state)]):
            with self.subTest(args=args):
                result = subprocess.run(['/bin/sh', str(SCRIPT), *args], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 2)
                self.assertIn('usage: check-boundary-files.sh', result.stderr)

    def test_verify_without_snapshot_fails(self):
        result = self.run_script('verify')
        self.assertEqual(result.returncode, 1)
        self.assertIn('境界のファイルの記録を読めません', result.stderr)
        self.assertFalse(os.path.exists(self.state))


if __name__ == '__main__':
    unittest.main()
