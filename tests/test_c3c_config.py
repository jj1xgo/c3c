#!/usr/bin/env python3
"""設定ディレクトリの新旧選択（c3c 第2b-1段階 Task 3）の launcher 経路の回帰試験。

tests/test_c3c_launch.py の隔離 HOME・fixture project・fake podman/compose をそのまま使い、本物の `c3c` を直接と
旧名 `claude-container` の外部 symlink 経由で起動する（旧入口は削除済みで、どちらも同じ parser・選択記憶）。
実 Podman・実ユーザー設定・認証には触れない。

契約は計画の第5節「2b-1: 設定名だけの移行」の配置表:

| `.c3c` | `.claude-container.d` | 通常起動 / check |
|---|---|---|
| なし | なし | `.c3c` を参照元として既存 fallback。directory は作らない |
| directory | なし | `.c3c` を採用 |
| なし | directory | 旧名を採用し移行推奨 WARNING。check は既存 WARN 集計へ |
| 存在 | 存在 | 内容が同じ・同じ実体でも ERROR、混ぜない |
| file / dangling link 等 | なし（または逆） | ERROR、ビルドや env 読込より前に停止 |

directory へ解決できる symlink は許容し、二重配置は `-e` だけでなく `-L` でも検出する。`--check` は対象ごとに診断を続け
何も書かず、選択に失敗した対象では env・resolver・hash を呼ばない。clean 系は設定の状態に関わらず既存対象を清掃する。
呼出名（`c3c` / 旧名 symlink `claude-container`）で探索結果を変えない。
"""

import hashlib
import os
from pathlib import Path
import re
import unittest

from test_c3c_launch import LaunchCase, REPO, SUPPORTED

NEW = '.c3c'
LEGACY = '.claude-container.d'
# env が読まれたら必ず出る目印（legacy トークン変数は fail-closed の ERROR 文言に変数名が載る）。
ENV_PROBE = 'GH_TOKEN_FILE'
# 同梱 default（c3c 第2b-2段階、計画 §5「2b-2: 既定イメージ」の固定値）。latest へ追従させない。
DEFAULT_NODE = '24.18.0'
DEFAULT_CODEX = SUPPORTED
EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ConfigCase(LaunchCase):
    def setUp(self):
        super().setUp()
        self.legacy = self.proj / LEGACY
        self.new = self.proj / NEW
        self.build_context = self.runner / '.build-context'

    # --- layout helpers ---------------------------------------------------

    def use_new_layout(self):
        self.legacy.rename(self.new)
        self.conf = self.new
        return self.new

    def use_no_layout(self):
        for item in self.legacy.iterdir():
            item.unlink()
        self.legacy.rmdir()

    def remove_entry(self, path):
        """symlink・file・directory のどれでも、`path` という名前を消す（リンク先は消さない）。"""
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            for item in path.iterdir():
                item.unlink()
            path.rmdir()

    def clear_layout(self):
        for path in (self.new, self.legacy):
            self.remove_entry(path)

    def make_env(self, directory, extra=''):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'env').write_text(f'CODEX_DIR={self.codex_dir}\n' + extra)

    def staged_files(self, path=None):
        target = self.build_context / self.project_name(path)
        if not target.is_dir():
            return None
        result = {}
        for item in sorted(target.iterdir()):
            if item.name.startswith('github-meta'):
                continue
            result[item.name] = hashlib.sha256(item.read_bytes()).hexdigest()
        return result

    def snapshot_all(self):
        return self.snapshot(self.home), self.snapshot(self.proj), self.snapshot(self.build_context) \
            if self.build_context.exists() else None

    def run_check(self, entry, *dirs):
        if entry == 'c3c':
            return self.run_c3c('--check', *[str(d) for d in dirs])
        return self.run_legacy('--check', *[str(d) for d in dirs])

    def assert_env_not_read(self, output):
        self.assertNotIn(ENV_PROBE, output, 'select が失敗した対象で env を読んでいる')


class SelectionTableTests(ConfigCase):
    """計画第5節の配置表。通常起動（c3c 直接と旧名 symlink 経由）と --check の双方で同じ結果になる。"""

    def test_no_config_dir_uses_c3c_as_reference_without_creating_it(self):
        self.use_no_layout()
        self.state['image_exists'] = False
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertFalse(self.new.exists(), '.c3c を作らない')
        self.assertFalse(self.legacy.exists(), '旧名も作らない')
        self.assertNotIn('旧名', result.stderr)
        # fallback の案内は採用パス（.c3c）で出す。
        self.assertIn(f'{self.proj}/{NEW}/packages.txt', result.stderr)
        self.assertNotIn(LEGACY, result.stderr)
        for entry in ('c3c', 'legacy'):
            with self.subTest(entry=entry):
                result = self.run_check(entry, self.proj)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f'{NEW}/env なし', result.stdout)
                self.assertNotIn(LEGACY, result.stdout + result.stderr)
                self.assertFalse(self.new.exists())

    def test_new_layout_is_adopted_by_both_entries_without_warning(self):
        self.use_new_layout()
        self.approve_codex()
        for label, runner, args in (('c3c', self.run_c3c, ['codex', str(self.proj)]),
                                    ('legacy', self.run_legacy, ['--agent', 'codex', str(self.proj)])):
            with self.subTest(entry=label):
                result = runner(*args)
                run = self.assert_single_run(result, 'codex')
                self.assertEqual(run['env']['CODEX_DIR'], str(self.codex_dir), '.c3c/env を読んでいる')
                self.assertNotIn('旧名', result.stderr)
                self.assertNotIn(LEGACY, result.stderr)
        for entry in ('c3c', 'legacy'):
            with self.subTest(check=entry):
                result = self.run_check(entry, self.proj)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f'{NEW}/env あり', result.stdout)
                self.assertNotIn('旧名', result.stdout)
                self.assertNotIn(LEGACY, result.stdout + result.stderr)

    def test_legacy_layout_is_adopted_with_migration_warning(self):
        self.approve_codex()
        for label, runner, args in (('c3c', self.run_c3c, ['codex', str(self.proj)]),
                                    ('legacy', self.run_legacy, ['--agent', 'codex', str(self.proj)])):
            with self.subTest(entry=label):
                result = runner(*args)
                run = self.assert_single_run(result, 'codex')
                self.assertEqual(run['env']['CODEX_DIR'], str(self.codex_dir))
                self.assertRegex(result.stderr, r'WARNING:.*' + LEGACY.replace('.', r'\.') + r'.*旧名')
                self.assertIn(NEW, result.stderr, '移行先を案内する')
                self.assertFalse(self.new.exists(), '勝手に移動・作成しない')
                self.assertTrue((self.legacy / 'env').is_file())
        for entry in ('c3c', 'legacy'):
            with self.subTest(check=entry):
                result = self.run_check(entry, self.proj)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f'{LEGACY}/env あり', result.stdout)
                self.assertRegex(result.stdout, r'\[WARN\].*旧名')
                self.assertIn('→ 結果: WARN', result.stdout)
                self.assertFalse(self.new.exists())

    def test_both_directories_are_rejected_before_env_is_read_even_with_identical_content(self):
        self.make_env(self.new, f'{ENV_PROBE}=x\n')
        (self.legacy / 'env').write_text((self.new / 'env').read_text())
        before = self.snapshot(self.proj)
        for label, runner, args in (('c3c', self.run_c3c, ['claude', str(self.proj)]),
                                    ('c3c codex', self.run_c3c, ['codex', str(self.proj)]),
                                    ('legacy-name', self.run_legacy, ['claude', str(self.proj)]),
                                    ('legacy-name -b', self.run_legacy, ['claude', '-b', str(self.proj)])):
            with self.subTest(entry=label):
                result = runner(*args)
                self.assertEqual(result.returncode, 1, label + ': ' + result.stdout + result.stderr)
                self.assertIn('ERROR', result.stderr)
                self.assertIn(NEW, result.stderr)
                self.assertIn(LEGACY, result.stderr)
                self.assert_env_not_read(result.stderr)
                self.assertEqual(self.calls, [], 'podman を呼ばない（image 確認・build・run のいずれも）')
                self.assertIsNone(self.staged_files(), 'ステージングしない')
                self.assertEqual(self.snapshot(self.proj), before, '対象リポジトリを変更しない')
        # c3c の無指定起動では他のガードと同じく初回選択の後に止まる。記憶は書かれず container も起動しない。
        result = self.run_c3c(str(self.proj), tty=True, answer='1')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.pref_dir.exists())
        # 起動台帳には他のガード失敗と同じく記録される（--check の一括診断で拾うため）。
        self.assertIn(str(self.proj), (self.state_dir / 'projects').read_text())

    def test_two_links_to_the_same_directory_are_still_both_present(self):
        real = self.root / 'shared-conf'
        self.make_env(real)

        def two_symlinks():
            self.new.symlink_to(real)
            self.legacy.symlink_to(real)

        def legacy_links_into_new():
            self.make_env(self.new)
            self.legacy.symlink_to(self.new)

        def new_links_into_legacy():
            self.make_env(self.legacy)
            self.new.symlink_to(self.legacy)

        def relative_pair():
            self.new.symlink_to(Path('..') / 'shared-conf')
            self.legacy.symlink_to(Path('..') / 'shared-conf')

        for arrange in (two_symlinks, legacy_links_into_new, new_links_into_legacy, relative_pair):
            with self.subTest(case=arrange.__name__):
                self.clear_layout()
                arrange()
                result = self.run_c3c('claude', str(self.proj))
                self.assertEqual(result.returncode, 1, arrange.__name__ + ': ' + result.stdout + result.stderr)
                self.assertIn('ERROR', result.stderr)
                self.assertEqual(self.calls, [])
                result = self.run_check('c3c', self.proj)
                self.assertEqual(result.returncode, 1, arrange.__name__ + ': ' + result.stdout + result.stderr)
                self.assertIn('→ 結果: FAIL', result.stdout)
                self.assertTrue(real.is_dir(), 'リンク先を消していない')

    def test_symlink_to_a_directory_is_accepted_for_either_name(self):
        real = self.root / 'conf-real'
        self.make_env(real)
        (real / 'codex-version.txt').write_text(SUPPORTED + '\n')
        (real / 'node-version.txt').write_text('22\n')
        self.approve_codex()
        with self.subTest(name=NEW):
            self.use_no_layout()
            self.new.symlink_to(real)
            run = self.assert_single_run(self.run_c3c('codex', str(self.proj)), 'codex')
            self.assertEqual(run['env']['CODEX_DIR'], str(self.codex_dir))
            result = self.run_check('legacy', self.proj)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('旧名', result.stdout)
            self.new.unlink()
        with self.subTest(name=LEGACY):
            self.legacy.symlink_to(Path('..') / 'conf-real')
            result = self.run_c3c('codex', str(self.proj))
            run = self.assert_single_run(result, 'codex')
            self.assertEqual(run['env']['CODEX_DIR'], str(self.codex_dir))
            self.assertIn('旧名', result.stderr)
            self.assertTrue(self.legacy.is_symlink(), 'symlink のまま（移動しない）')

    def test_file_or_dangling_link_is_an_error_before_env_and_build(self):
        real_file = self.root / 'not-a-dir'
        real_file.write_text('x')

        def as_file(path):
            path.write_text('x')

        def as_dangling(path):
            path.symlink_to(self.root / 'nowhere')

        def as_link_to_file(path):
            path.symlink_to(real_file)

        cases = {
            '.c3c is a file': (self.new, as_file, None),
            '.c3c is a dangling link': (self.new, as_dangling, None),
            '.c3c links to a file': (self.new, as_link_to_file, None),
            'legacy is a file': (self.legacy, as_file, None),
            'legacy is a dangling link': (self.legacy, as_dangling, None),
            'legacy links to a file': (self.legacy, as_link_to_file, None),
            # 片方が正しい directory でも、もう片方が不正なら二重配置として止める（混ぜない）。
            '.c3c dir + legacy dangling': (self.legacy, as_dangling, self.new),
            'legacy dir + .c3c file': (self.new, as_file, self.legacy),
        }
        for label, (target, arrange, keep_dir) in cases.items():
            with self.subTest(case=label):
                self.clear_layout()
                if keep_dir is not None:
                    self.make_env(keep_dir, f'{ENV_PROBE}=x\n')
                arrange(target)
                before = self.snapshot(self.proj)
                self.state = {'image_exists': False, 'preflight': {}}
                for entry, runner, args in (('c3c', self.run_c3c, ['claude', str(self.proj)]),
                                            ('legacy', self.run_legacy, ['claude', '-b', str(self.proj)])):
                    result = runner(*args)
                    self.assertEqual(result.returncode, 1, f'{label}/{entry}: ' + result.stdout + result.stderr)
                    self.assertIn('ERROR', result.stderr)
                    self.assertIn(str(target), result.stderr, '不正なパスを名指しする')
                    self.assert_env_not_read(result.stderr)
                    self.assertEqual(self.calls, [], 'build・run へ進まない')
                    self.assertIsNone(self.staged_files())
                    self.assertEqual(self.snapshot(self.proj), before)
                for entry in ('c3c', 'legacy'):
                    result = self.run_check(entry, self.proj)
                    self.assertEqual(result.returncode, 1, f'{label}/{entry} check: ' + result.stdout + result.stderr)
                    self.assertIn('→ 結果: FAIL', result.stdout)
                    self.assert_env_not_read(result.stdout + result.stderr)
                    self.assertNotIn('unexpected exit', result.stdout)
                    self.assertNotIn('unbound', result.stdout + result.stderr)
                    self.assertEqual(self.snapshot(self.proj), before)


class CheckAndCleanContractTests(ConfigCase):
    def test_check_reports_fail_for_one_target_and_continues_with_the_next_without_writing(self):
        # proj: 二重配置（env に probe）。other: 新配置で正常。
        self.make_env(self.new, f'{ENV_PROBE}=x\n')
        other = self.root / 'other'
        self.make_env(other / NEW)
        for name in ('packages.txt', 'requirements.txt', 'allowed-domains.txt'):
            (other / NEW / name).write_text('')
        # 起動台帳に両方を載せ、引数なし --check でも同じ経路を通す。
        ledger = self.state_dir / 'projects'
        ledger.parent.mkdir(parents=True, mode=0o700)
        ledger.write_text(f'{self.proj}\n{other}\n')
        self.build_context.mkdir(exist_ok=True)
        (self.build_context / 'stale').mkdir()
        before = self.snapshot(self.home), self.snapshot(self.proj), self.snapshot(other), self.snapshot(self.build_context)
        for label, args in (('explicit', [str(self.proj), str(other)]), ('ledger', [])):
            for entry in ('c3c', 'legacy'):
                with self.subTest(case=label, entry=entry):
                    runner = self.run_c3c if entry == 'c3c' else self.run_legacy
                    result = runner('--check', *args)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    out = result.stdout
                    proj_part = out.split(f'=== {self.proj} ===', 1)[1].split(f'=== {other} ===', 1)[0]
                    other_part = out.split(f'=== {other} ===', 1)[1]
                    self.assertIn('ERROR', proj_part)
                    self.assertIn('→ 結果: FAIL', proj_part)
                    self.assert_env_not_read(proj_part)
                    self.assertNotIn('MCP監査ゲート', proj_part, 'select 失敗後の診断へ進まない')
                    # other は fixture の都合（~/.claude の placeholder 未作成・fake image のラベル無し）で WARN。
                    self.assertRegex(other_part, r'→ 結果: (PASS|WARN)')
                    self.assertIn('MCP監査ゲート', other_part, '次の対象は最後まで診断する')
                    self.assertRegex(out, r'PASS: \d+   WARN: \d+   FAIL: 1\n')
                    self.assertIn(f'  - {self.proj}\n', out)
                    self.assertNotIn('unexpected exit', out)
                    self.assertNotIn('unbound', out + result.stderr)
                    self.assertEqual((self.snapshot(self.home), self.snapshot(self.proj), self.snapshot(other),
                                      self.snapshot(self.build_context)), before, '何も書かない')

    def test_clean_removes_existing_targets_regardless_of_config_state(self):
        # まず正常に起動してイメージ・build-context・台帳・承認記録を作る。
        self.approve_codex()
        self.state['image_exists'] = False
        self.assert_single_run(self.run_c3c('claude', str(self.proj)), 'claude')
        name = self.project_name()
        self.assertIsNotNone(self.staged_files())
        self.assertIn(str(self.proj), (self.state_dir / 'projects').read_text())
        record = self.store / 'codex' / name
        self.assertTrue(record.is_dir())
        for label, arrange in (('double placement', lambda: self.make_env(self.new)),
                               ('.c3c is a file', lambda: self.new.write_text('x'))):
            with self.subTest(case=label):
                self.remove_entry(self.new)
                arrange()
                # 清掃対象を再度用意する（前の subTest が消しているため）。
                (self.build_context / name).mkdir(parents=True, exist_ok=True)
                (self.build_context / name / 'packages.txt').write_text('')
                record.mkdir(parents=True, exist_ok=True)
                (record / 'project-config.json').write_text('{}')
                (self.state_dir / 'projects').write_text(f'{self.proj}\n{self.root}/keep\n')
                self.state['image_exists'] = True
                # 設定が不正でも通常起動は止まる…
                result = self.run_c3c('claude', str(self.proj))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                # …が、清掃は既存契約どおり進む（c3c 直接と旧名 symlink 経由の両方）。
                for entry, runner in (('c3c', self.run_c3c), ('legacy', self.run_legacy)):
                    result = runner('--clean', str(self.proj))
                    self.assertEqual(result.returncode, 0, f'{label}/{entry}: ' + result.stdout + result.stderr)
                    self.assertIn(f'イメージを削除します: localhost/{name}', result.stdout)
                    self.assertTrue(any(c['args'][:2] == ['rmi', f'localhost/{name}_claude-auth-workspace'] for c in self.calls))
                    self.assertFalse((self.build_context / name).exists())
                    self.assertFalse(record.exists())
                    self.assertEqual((self.state_dir / 'projects').read_text(), f'{self.root}/keep\n')
                    self.assertNotIn('ERROR', result.stderr)
                    (self.build_context / name).mkdir(parents=True, exist_ok=True)
                    record.mkdir(parents=True, exist_ok=True)
                    (self.state_dir / 'projects').write_text(f'{self.proj}\n{self.root}/keep\n')
        # --clean（全件）も設定状態に依存しない。
        result = self.run_c3c('--clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_env_cannot_move_the_config_directory_after_selection(self):
        self.use_new_layout()
        evil = self.root / 'evil'
        self.make_env(evil)
        (self.new / 'env').write_text(f'CODEX_DIR={self.codex_dir}\nPROJECT_CONF_DIR={evil}\nPROJECT_CONF_NAME=evil\n')
        (evil / 'base-image.txt').write_text('debian:evil\n')
        self.approve_codex()
        result = self.run_c3c('codex', str(self.proj))
        run = self.assert_single_run(result, 'codex')
        self.assertEqual(run['env']['CODEX_DIR'], str(self.codex_dir))
        self.assertEqual(run['env']['BASE_IMAGE'], 'debian:stable', 'evil 側の base-image.txt は読まれない')
        self.assertIn('PROJECT_CONF_DIR', result.stderr, '許可リスト外として WARNING')


class ResolverConsistencyTests(ConfigCase):
    """同じ入力の新旧配置で staged file と asset hash が同一、env は build context に混入しない、.env は遮断。"""

    def fill_inputs(self, directory):
        (directory / 'packages.txt').write_text('htop\n')
        (directory / 'requirements.txt').write_text('requests\n')
        (directory / 'allowed-domains.txt').write_text('example.org\n')
        (directory / 'allowed-ports.txt').write_text('443\n')
        (directory / 'base-image.txt').write_text('debian:testing\n')

    def run_and_capture(self, *args):
        self.state = {'image_exists': False, 'label': '2', 'preflight': {}}
        result = self.run_c3c(*args)
        run = self.assert_single_run(result, 'claude')
        self.assertEqual(run['env']['CODEX_DIR'], str(self.codex_dir), '採用した配置の env を読んでいる')
        return run, self.staged_files()

    def test_same_inputs_stage_identically_and_hash_matches_between_layouts(self):
        self.fill_inputs(self.legacy)
        (self.proj / '.env').write_text('CODEX_DIR=/evil\nCLAUDE_CONTAINER_NO_FIREWALL=1\n')
        legacy_run, legacy_staged = self.run_and_capture('claude', str(self.proj))
        self.assertIsNotNone(legacy_staged)
        self.assertEqual(legacy_staged and hashlib.sha256(b'htop\n').hexdigest(), legacy_staged['packages.txt'])
        self.assertNotIn('env', legacy_staged, 'ランタイム設定を焼き込まない')
        self.assertEqual(legacy_run['env']['BASE_IMAGE'], 'debian:testing')
        self.use_new_layout()
        new_run, new_staged = self.run_and_capture('claude', str(self.proj))
        self.assertEqual(new_staged, legacy_staged)
        self.assertNotIn('env', new_staged)
        self.assertRegex(new_run['env']['ASSET_HASH'], r'^[0-9a-f]{64}$')
        self.assertEqual(new_run['env']['ASSET_HASH'], legacy_run['env']['ASSET_HASH'])
        self.assertEqual(new_run['env']['BASE_IMAGE'], 'debian:testing')
        # .env はどちらの配置でも補間に使わせない（--env-file /dev/null）。
        for run in (legacy_run, new_run):
            args = run['args']
            self.assertIn('--env-file', args)
            self.assertEqual(args[args.index('--env-file') + 1], '/dev/null')
            self.assertEqual(run['env']['CODEX_DIR'], str(self.codex_dir))
        # 入力を変えれば hash は変わる（同一の比較が空の一致でないことの確認）。
        (self.new / 'packages.txt').write_text('htop\nvim\n')
        changed_run, changed_staged = self.run_and_capture('claude', str(self.proj))
        self.assertNotEqual(changed_run['env']['ASSET_HASH'], new_run['env']['ASSET_HASH'])
        self.assertNotEqual(changed_staged['packages.txt'], new_staged['packages.txt'])

    def test_fixed_boundary_assets_cannot_be_overridden_from_the_new_layout(self):
        self.use_new_layout()
        baseline_run, baseline_staged = self.run_and_capture('claude', str(self.proj))
        for name in ('entrypoint.sh', 'init-firewall.sh', 'git-askpass.sh', 'validate-build-input.sh',
                     'Dockerfile.claude', 'codex-mcp-audit.py', 'codex-launcher.sh', 'ipv6-firewall.py', 'firewall-refresh.py',
                     'compose.ipv6.yml', 'compose.codex-preflight.yml'):
            (self.new / name).write_text('#!/bin/sh\nexit 99\n')
        run, staged = self.run_and_capture('claude', str(self.proj))
        self.assertEqual(staged, baseline_staged, 'project 側の同名ファイルはステージされない')
        self.assertEqual(run['env']['ASSET_HASH'], baseline_run['env']['ASSET_HASH'])
        for name in ('entrypoint.sh', 'validate-build-input.sh'):
            self.assertEqual(staged[name], hashlib.sha256((self.runner / name).read_bytes()).hexdigest())


class GuidanceTests(ConfigCase):
    """エラー・警告の案内先は採用パスを使う（旧配置は旧名、新配置は .c3c、無しは .c3c）。"""

    def test_codex_guard_names_the_adopted_env_path(self):
        (self.legacy / 'env').write_text('')
        result = self.run_c3c('codex', str(self.proj))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'{self.proj}/{LEGACY}/env', result.stderr)
        self.use_new_layout()
        result = self.run_c3c('codex', str(self.proj))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'{self.proj}/{NEW}/env', result.stderr)
        self.assertNotIn(LEGACY, result.stderr)
        # 空ファイルは明示 opt-out（欠落は同梱 default に倒れるので、案内先の検証は空ファイルで行う）。
        (self.new / 'codex-version.txt').write_text('')
        (self.new / 'env').write_text(f'CODEX_DIR={self.codex_dir}\n')
        result = self.run_c3c('codex', str(self.proj))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'{self.proj}/{NEW}/codex-version.txt', result.stderr)

    def test_base_image_guidance_and_missing_fallback_name_the_adopted_directory(self):
        self.use_new_layout()
        (self.new / 'env').write_text(f'CODEX_DIR={self.codex_dir}\nBASE_IMAGE=debian:testing\n')
        (self.new / 'base-image.txt').write_text('ubuntu:latest\n')
        result = self.run_c3c('claude', str(self.proj))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f'{self.proj}/{NEW}/base-image.txt', result.stderr)
        self.assertNotIn(LEGACY, result.stderr)
        result = self.run_check('c3c', self.proj)
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'{NEW}/base-image.txt', result.stdout + result.stderr)
        self.assertIn(f'{NEW}/packages.txt', result.stdout, 'fallback 案内も採用名')
        self.assertNotIn(LEGACY, result.stdout + result.stderr)


class BuildInputDefaultTests(ConfigCase):
    """Node/Codex の既定ビルド入力（c3c 第2b-2段階 Task 4）。

    `node-version.txt`・`codex-version.txt` は project 優先→同梱 default。project の空ファイルは明示 opt-out で、
    missing と同一視して Codex を勝手に導入しない（計画 §8-5）。新旧 directory それぞれで absent/default・
    project pin・project empty の 3 通りを通常起動（staging・hash・採用元の表示）と `--check` で検証する。
    `allowed-ports.txt`・`base-image.txt` の missing 契約は変えない。
    """

    PIN_NODE = '22.14.0'

    def layouts(self):
        """legacy → new の順に、同じ入力を持つ設定ディレクトリを返す（fixture は旧名で始まる）。"""
        yield 'legacy', self.legacy
        self.use_new_layout()
        yield 'new', self.new

    def launch_claude(self, *extra):
        self.state = {'image_exists': False, 'label': '2', 'preflight': {}}
        result = self.run_c3c('claude', *extra, str(self.proj))
        run = self.assert_single_run(result, 'claude')
        return result, run, self.staged_files()

    def test_bundled_defaults_are_the_contract_values(self):
        self.assertEqual((REPO / 'node-version.txt').read_bytes(), (DEFAULT_NODE + '\n').encode())
        self.assertEqual((REPO / 'codex-version.txt').read_bytes(), (DEFAULT_CODEX + '\n').encode())
        # #150 から起動時審査は Codex の版に依存しない（launcher・helper に対応版の定数を持たない）。
        self.assertNotIn('CODEX_SUPPORTED_VERSION', (REPO / 'c3c').read_text())
        self.assertNotIn('SUPPORTED_VERSION', (REPO / 'codex-mcp-audit.py').read_text())

    def test_absent_files_use_bundled_defaults_in_both_layouts(self):
        hashes = {}
        for label, conf in self.layouts():
            with self.subTest(layout=label):
                (conf / 'node-version.txt').unlink(missing_ok=True)
                (conf / 'codex-version.txt').unlink(missing_ok=True)
                result, run, staged = self.launch_claude()
                self.assertEqual(staged['node-version.txt'], sha256_text(DEFAULT_NODE + '\n'))
                self.assertEqual(staged['codex-version.txt'], sha256_text(DEFAULT_CODEX + '\n'))
                self.assertRegex(result.stderr, r'INFO: Node\.js 版: ' + re.escape(DEFAULT_NODE) + r'（採用元: 同梱 default）')
                self.assertRegex(result.stderr, r'INFO: Codex 版: ' + re.escape(DEFAULT_CODEX) + r'（採用元: 同梱 default）')
                self.assertNotIn('opt-out', result.stderr)
                hashes[label] = run['env']['ASSET_HASH']
                for entry in ('c3c', 'legacy'):
                    check = self.run_check(entry, self.proj)
                    self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                    self.assertRegex(check.stdout, r'\[INFO\] Node\.js 版: ' + re.escape(DEFAULT_NODE) + r'（採用元: 同梱 default）')
                    self.assertRegex(check.stdout, r'\[INFO\] Codex 版: ' + re.escape(DEFAULT_CODEX) + r'（採用元: 同梱 default）')
                    self.assertNotIn('npm', check.stdout, 'Node default＋Codex default では npm の WARNING を出さない')
        self.assertEqual(hashes['legacy'], hashes['new'])

    def test_missing_config_dir_uses_bundled_defaults_without_creating_it(self):
        self.use_no_layout()
        result, _, staged = self.launch_claude()
        self.assertEqual(staged['node-version.txt'], sha256_text(DEFAULT_NODE + '\n'))
        self.assertEqual(staged['codex-version.txt'], sha256_text(DEFAULT_CODEX + '\n'))
        # allowed-ports.txt は missing 契約のまま（空ファイルを都度生成、init-firewall.sh が既定値を適用）。
        self.assertEqual(staged['allowed-ports.txt'], EMPTY_SHA256)
        self.assertFalse(self.new.exists())
        self.assertFalse(self.legacy.exists())
        self.assertIn('採用元: 同梱 default', result.stderr)

    def test_project_pin_overrides_the_default_in_both_layouts(self):
        for label, conf in self.layouts():
            with self.subTest(layout=label):
                (conf / 'node-version.txt').write_text(self.PIN_NODE + '\n')
                (conf / 'codex-version.txt').write_text(DEFAULT_CODEX + '\n')
                result, _, staged = self.launch_claude()
                self.assertEqual(staged['node-version.txt'], sha256_text(self.PIN_NODE + '\n'))
                self.assertEqual(staged['codex-version.txt'], sha256_text(DEFAULT_CODEX + '\n'))
                self.assertRegex(result.stderr, r'INFO: Node\.js 版: ' + re.escape(self.PIN_NODE) + r'（採用元: project '
                                 + re.escape(str(conf / 'node-version.txt')) + r'）')
                self.assertRegex(result.stderr, r'INFO: Codex 版: ' + re.escape(DEFAULT_CODEX) + r'（採用元: project '
                                 + re.escape(str(conf / 'codex-version.txt')) + r'）')
                self.assertNotIn('同梱 default', result.stderr)
                check = self.run_check('c3c', self.proj)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                self.assertRegex(check.stdout, r'\[INFO\] Node\.js 版: ' + re.escape(self.PIN_NODE) + r'（採用元: project ')
                self.assertRegex(check.stdout, r'\[INFO\] Codex 版: ' + re.escape(DEFAULT_CODEX) + r'（採用元: project ')
                self.assertNotIn('npm', check.stdout)

    def test_pin_equal_to_default_yields_the_same_hash_as_absent(self):
        (self.legacy / 'node-version.txt').write_text(DEFAULT_NODE + '\n')
        (self.legacy / 'codex-version.txt').write_text(DEFAULT_CODEX + '\n')
        _, pinned, pinned_staged = self.launch_claude()
        (self.legacy / 'node-version.txt').unlink()
        (self.legacy / 'codex-version.txt').unlink()
        _, absent, absent_staged = self.launch_claude()
        self.assertEqual(pinned_staged, absent_staged)
        self.assertEqual(pinned['env']['ASSET_HASH'], absent['env']['ASSET_HASH'], '内容だけをハッシュする（採用元は含めない）')
        (self.legacy / 'node-version.txt').write_text('')
        _, empty, empty_staged = self.launch_claude()
        self.assertNotEqual(empty['env']['ASSET_HASH'], absent['env']['ASSET_HASH'], '空 opt-out は default と別の image になる')
        self.assertEqual(empty_staged['node-version.txt'], EMPTY_SHA256)

    def test_empty_project_file_is_an_explicit_opt_out_not_missing(self):
        """計画 §8-5: 空の project 設定を missing と同一視して Codex を勝手に導入しない。"""
        self.approve_codex()
        for label, conf in self.layouts():
            with self.subTest(layout=label):
                (conf / 'node-version.txt').write_text('')
                (conf / 'codex-version.txt').write_text('\n')
                result, _, staged = self.launch_claude()
                self.assertEqual(staged['node-version.txt'], EMPTY_SHA256, '空のまま COPY する（default で埋めない）')
                self.assertEqual(staged['codex-version.txt'], sha256_text('\n'), 'project の内容をそのまま使う')
                self.assertRegex(result.stderr, r'INFO: Node\.js 版: なし（' + re.escape(str(conf / 'node-version.txt')) + r' が空 = opt-out')
                self.assertRegex(result.stderr, r'INFO: Codex 版: なし（' + re.escape(str(conf / 'codex-version.txt')) + r' が空 = opt-out')
                self.assertNotIn('同梱 default', result.stderr)
                self.assertNotIn('npm', result.stderr, '両方 opt-out なら npm の WARNING は出ない')
                # Codex を起動しようとすると opt-out を理由に止まり、container を起動しない。
                for entry, runner, args in (('c3c', self.run_c3c, ['codex', str(self.proj)]),
                                            ('legacy', self.run_legacy, ['--agent', 'codex', str(self.proj)])):
                    self.state = {'image_exists': True, 'label': '2', 'preflight': {}}
                    result = runner(*args)
                    self.assertEqual(result.returncode, 1, f'{entry}: ' + result.stdout + result.stderr)
                    self.assertIn(f'{conf}/codex-version.txt', result.stderr)
                    self.assertIn('opt-out', result.stderr)
                    self.assertIn('latest', result.stderr, '使うなら固定版か latest を案内する')
                    self.assert_no_containers()
                check = self.run_c3c('codex', '--check', str(self.proj))
                self.assertEqual(check.returncode, 1, check.stdout + check.stderr)
                self.assertIn('→ 結果: FAIL', check.stdout)
                self.assertIn('opt-out', check.stdout)
                # Claude の check は opt-out を表示するだけで FAIL にしない。
                check = self.run_check('legacy', self.proj)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                self.assertRegex(check.stdout, r'\[INFO\] Node\.js 版: なし（.* が空 = opt-out')
                self.assertRegex(check.stdout, r'\[INFO\] Codex 版: なし（.* が空 = opt-out')

    def test_node_opt_out_with_codex_enabled_warns_before_build_and_proceeds(self):
        """Node 空＋Codex 有効: base に npm があるかを断定せず WARNING。通常起動は進み、check は WARN 集計。"""
        for label, conf in self.layouts():
            for codex_source in ('default', 'pin'):
                with self.subTest(layout=label, codex=codex_source):
                    (conf / 'node-version.txt').write_text('')
                    if codex_source == 'default':
                        (conf / 'codex-version.txt').unlink(missing_ok=True)
                    else:
                        (conf / 'codex-version.txt').write_text(DEFAULT_CODEX + '\n')
                    result, _, staged = self.launch_claude('-b')
                    self.assertEqual(len(self.compose_calls('build')), 1)
                    self.assertEqual(staged['node-version.txt'], EMPTY_SHA256)
                    self.assertEqual(staged['codex-version.txt'], sha256_text(DEFAULT_CODEX + '\n'))
                    warning = [line for line in result.stderr.splitlines() if line.startswith('WARNING:') and 'npm' in line]
                    self.assertEqual(len(warning), 1, result.stderr)
                    self.assertIn(f'{conf}/node-version.txt', warning[0])
                    self.assertIn('codex-version.txt', warning[0])
                    self.assertNotIn('ERROR', result.stderr)
                    # build 前に出る: ステージング時の fallback WARNING（packages.txt 無し）より前に並ぶ。
                    lines = result.stderr.splitlines()
                    staging_index = next(i for i, line in enumerate(lines) if '同梱の空のフォールバック' in line)
                    self.assertLess(lines.index(warning[0]), staging_index)
                    for entry in ('c3c', 'legacy'):
                        check = self.run_check(entry, self.proj)
                        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
                        self.assertRegex(check.stdout, r'\[WARN\] WARNING: .*node-version\.txt が空.*npm')
                        self.assertIn('→ 結果: WARN', check.stdout)
                        self.assertNotIn('→ 結果: FAIL', check.stdout)
                    (conf / 'node-version.txt').unlink()

    def test_node_pinned_with_codex_enabled_does_not_warn(self):
        (self.legacy / 'node-version.txt').write_text(self.PIN_NODE + '\n')
        (self.legacy / 'codex-version.txt').unlink()
        result, _, _ = self.launch_claude()
        self.assertNotIn('npm', result.stderr)
        self.assertRegex(result.stderr, r'INFO: Node\.js 版: ' + re.escape(self.PIN_NODE) + r'（採用元: project ')
        self.assertRegex(result.stderr, r'INFO: Codex 版: ' + re.escape(DEFAULT_CODEX) + r'（採用元: 同梱 default）')


if __name__ == '__main__':
    unittest.main()
