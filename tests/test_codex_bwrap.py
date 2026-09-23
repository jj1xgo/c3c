#!/usr/bin/env python3
"""Codex 同梱 bubblewrap の解決と固定リンク作成（#145 Task 1）の回帰試験。

Dockerfile.claude の開始・終了コメントで区切った RUN から `node -e '...'` の Node スクリプトを抽出し、
Dockerfile の行継続だけを除いて実行する。試験用コピーでは固定 CLI・出力ディレクトリ・`process.arch`
だけを一時領域の値へ置換する。npm の配置は一時領域に fixture として組み、ホストの /usr/local には
触れない。検査範囲は解決処理と help 検査とリンク作成であり、RUN 全体（opt-out 分岐・root 所有と
mode の検査）は test-build.sh の実 build 検査が担う。ただし所有者・mode 検査の shell 部分は、find の
失敗や実体の解決失敗を通過扱いにしない（fail-closed）ことだけを、find を差し替えて別に確かめる。
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / 'Dockerfile.claude'
BEGIN = '# >>> c3c codex-bwrap'
END = '# <<< c3c codex-bwrap'
FIXED_CLI = '"/usr/local/bin/codex"'
FIXED_OUT = '"/usr/local/libexec/c3c/codex-bwrap"'
ARCH = 'process.arch'
REQUIRED = ('--as-pid-1', '--perms', '--argv0', '--ro-bind-fd')
TRIPLES = {'x64': 'x86_64-unknown-linux-musl', 'arm64': 'aarch64-unknown-linux-musl'}


def extract_block():
    text = DOCKERFILE.read_text(encoding='utf-8')
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise AssertionError('Dockerfile.claude の開始・終了コメントが一組ではありません')
    return text.split(BEGIN, 1)[1].split(END, 1)[0].replace('\\\n', '')


def extract_owner_check():
    """Node スクリプトの後に続く、固定リンクの所有者・mode 検査の shell 部分を取り出す。"""
    joined = extract_block()
    start = joined.find('link=' + FIXED_OUT.strip('"') + '/bwrap;')
    end = joined.rfind('done;')
    if start < 0 or end < start:
        raise AssertionError('所有者・mode 検査の shell 部分が見つかりません')
    return joined[start:end + len('done;')]


def extract_script():
    """開始・終了コメントの間の RUN から Node スクリプトを取り出す（行継続だけを除く）。"""
    joined = extract_block()
    found = re.findall(r"node -e '([^']*)'", joined)
    if len(found) != 1 or joined.count("node -e '") != 1:
        raise AssertionError('区切り内の node -e の単一引用符の組が一つではありません')
    return found[0]


def fake_bwrap(path, options=REQUIRED, status=0, sleep=0):
    help_lines = ''.join('    %s VALUE  fixture\\n' % option for option in options)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n'
                    'if [ "$1" = --version ]; then echo "bubblewrap fixture"; exit 0; fi\n'
                    'if [ %d -gt 0 ]; then exec sleep %d; fi\n'
                    'printf "usage: bwrap [OPTIONS...] [--] COMMAND [ARGS...]\\n%s"\n'
                    'exit %d\n' % (sleep, sleep, help_lines, status), encoding='utf-8')
    path.chmod(0o755)


def fake_binary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    path.chmod(0o755)


class CodexBwrapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which('node') is None:
            raise AssertionError('ホストに node がありません（この試験は Node.js を必須とします）')
        cls.script = extract_script()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='c3c-codex-bwrap-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.prefix = self.tmp / 'usr-local'
        self.modules = self.prefix / 'lib' / 'node_modules'
        self.codex = self.modules / '@openai' / 'codex'
        main = self.codex / 'bin' / 'codex.js'
        main.parent.mkdir(parents=True)
        main.write_text('#!/usr/bin/env node\n', encoding='utf-8')
        (self.codex / 'package.json').write_text(json.dumps({'name': '@openai/codex', 'type': 'module'}),
                                                 encoding='utf-8')
        self.cli = self.prefix / 'bin' / 'codex'
        self.cli.parent.mkdir(parents=True)
        self.cli.symlink_to('../lib/node_modules/@openai/codex/bin/codex.js')
        self.out = self.tmp / 'libexec' / 'c3c' / 'codex-bwrap'
        self.out.mkdir(parents=True)

    def package(self, arch='x64', hoisted=False):
        """npm の optional package を nested か hoisted に置き、その target ディレクトリを返す。"""
        base = self.modules if hoisted else self.codex / 'node_modules'
        pkg = base / '@openai' / ('codex-linux-' + arch)
        pkg.mkdir(parents=True)
        (pkg / 'package.json').write_text(json.dumps({'name': '@openai/codex'}), encoding='utf-8')
        return pkg / 'vendor' / TRIPLES[arch]

    def legacy(self, arch='x64'):
        return self.codex / 'vendor' / TRIPLES[arch]

    def populate(self, target, **bwrap):
        fake_binary(target / 'bin' / 'codex')
        fake_bwrap(target / 'codex-resources' / 'bwrap', **bwrap)
        return target

    def run_script(self, arch='x64'):
        code = self.script
        for fixed, value in ((FIXED_CLI, json.dumps(str(self.cli))), (FIXED_OUT, json.dumps(str(self.out))),
                             (ARCH, json.dumps(arch))):
            self.assertEqual(code.count(fixed), 1, fixed)
            code = code.replace(fixed, value)
        return subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=30)

    def assert_linked(self, result, target):
        self.assertEqual(result.returncode, 0, result.stderr)
        link = self.out / 'bwrap'
        self.assertTrue(link.is_symlink())
        expected = os.path.realpath(target / 'codex-resources' / 'bwrap')
        self.assertEqual(os.readlink(link), expected)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ['bwrap'])
        self.assertIn('bubblewrap fixture', result.stdout)

    def assert_failed(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stderr.startswith('ERROR:'), result.stderr)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_script_quoting_is_literal(self):
        for char in ("'", '$', '\\'):
            self.assertNotIn(char, self.script)

    def test_nested_x64(self):
        target = self.populate(self.package())
        self.assert_linked(self.run_script(), target)

    def test_hoisted_x64(self):
        target = self.populate(self.package(hoisted=True))
        self.assert_linked(self.run_script(), target)

    def test_legacy_vendor_x64(self):
        target = self.populate(self.legacy())
        self.assert_linked(self.run_script(), target)

    def test_nested_arm64(self):
        target = self.populate(self.package('arm64'))
        self.assert_linked(self.run_script('arm64'), target)

    def test_optional_package_wins_over_legacy(self):
        self.populate(self.legacy())
        target = self.populate(self.package())
        self.assert_linked(self.run_script(), target)

    def test_other_arch_package_is_not_used(self):
        self.populate(self.package('arm64'))
        self.assert_failed(self.run_script('x64'))

    def test_unsupported_arch(self):
        self.populate(self.package())
        self.assert_failed(self.run_script('ia32'))

    def test_resolved_package_missing_bwrap_does_not_fall_back(self):
        self.populate(self.legacy())
        target = self.populate(self.package())
        (target / 'codex-resources' / 'bwrap').unlink()
        self.assert_failed(self.run_script())

    def test_resolved_package_missing_binary(self):
        target = self.populate(self.package())
        (target / 'bin' / 'codex').unlink()
        self.assert_failed(self.run_script())

    def test_dangling_bwrap(self):
        target = self.populate(self.package())
        bwrap = target / 'codex-resources' / 'bwrap'
        bwrap.unlink()
        bwrap.symlink_to(target / 'missing')
        self.assert_failed(self.run_script())

    def test_non_executable_bwrap(self):
        target = self.populate(self.package())
        (target / 'codex-resources' / 'bwrap').chmod(0o644)
        self.assert_failed(self.run_script())

    def test_bwrap_outside_target(self):
        target = self.populate(self.package())
        outside = self.tmp / 'outside' / 'bwrap'
        fake_bwrap(outside)
        bwrap = target / 'codex-resources' / 'bwrap'
        bwrap.unlink()
        bwrap.symlink_to(outside)
        self.assert_failed(self.run_script())

    def test_help_missing_each_required_option(self):
        for missing in REQUIRED:
            with self.subTest(missing=missing):
                target = self.populate(self.package())
                fake_bwrap(target / 'codex-resources' / 'bwrap',
                           options=tuple(o for o in REQUIRED if o != missing))
                self.assert_failed(self.run_script())
                shutil.rmtree(self.codex / 'node_modules')

    def test_help_nonzero(self):
        self.populate(self.package(), status=1)
        self.assert_failed(self.run_script())

    def test_help_timeout(self):
        self.populate(self.package(), sleep=10)
        self.assert_failed(self.run_script())


class CodexBwrapOwnerCheckTest(unittest.TestCase):
    """所有者・mode 検査が find の失敗・実体の解決失敗で止まること（PR #148 の二重レビュー指摘）。"""

    @classmethod
    def setUpClass(cls):
        cls.check = extract_owner_check()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='c3c-codex-bwrap-owner-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / 'codex-bwrap'
        self.out.mkdir()
        self.real = self.tmp / 'vendor' / 'bwrap'
        fake_bwrap(self.real)
        (self.out / 'bwrap').symlink_to(self.real)
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()

    def fake_find(self, status):
        """出力なしで status を返す find。実 find の所有者判定（root 所有）を試験環境で迂回する。"""
        find = self.bin / 'find'
        find.write_text('#!/bin/sh\nexit %d\n' % status, encoding='utf-8')
        find.chmod(0o755)

    def run_check(self):
        code = self.check.replace(FIXED_OUT.strip('"'), str(self.out))
        env = dict(os.environ, PATH='%s:%s' % (self.bin, os.environ.get('PATH', '')))
        return subprocess.run(['sh', '-c', 'set -e; ' + code], capture_output=True, text=True,
                               timeout=30, env=env)

    def test_passes_when_find_reports_nothing(self):
        self.fake_find(0)
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_find_failure_stops(self):
        self.fake_find(1)
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('検査できません', result.stderr)

    def test_unresolvable_link_stops(self):
        self.fake_find(0)
        self.real.unlink()
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('実体を解決できません', result.stderr)


if __name__ == '__main__':
    unittest.main()
