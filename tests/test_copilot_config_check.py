#!/usr/bin/env python3
"""Dockerfile.claude の `# >>> c3c copilot` の区間の、版の検査と sandbox の設定の読みの確認の回帰試験。

区間を開始・終了のコメントで切り出し、Dockerfile の行継続だけを除いて、shell の部分を `sh -c` で、
`node -e` の確認のスクリプトを本物の node で動かす（`tests/test_codex_bwrap.py` と同じ形）。Copilot の
実体の代わりに、一時領域に置いた偽の node・偽の npm-loader.js を使う。実物の Copilot での確認（知らない
項目を捨てて止まること）は test-build.sh の全体実行が担う。
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / 'Dockerfile.claude'
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


if __name__ == '__main__':
    unittest.main()
