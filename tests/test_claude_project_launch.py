#!/usr/bin/env python3
"""launcher の Claude project 設定ゲート（#163）の回帰試験。

tests/test_codex_launch.py の LaunchCase（隔離 HOME・fixture project・fake podman/compose・専用 PTY）を使う。
検査用コンテナの protocol は fake compose が state['claude_preflight'] から返す。
"""

import json
import os
from pathlib import Path
import shutil
import sys
import unittest

from test_codex_launch import LaunchCase

HASH_A = 'a' * 64
HASH_B = 'b' * 64


def claude_protocol(hash_value=HASH_A, count=1, lines=None, extra=None):
    if lines is None:
        lines = ['--- .claude/settings.json ---', '  {"hooks": {}}'] if count else []
    doc = {'protocol_version': 1, 'hash': hash_value, 'count': count, 'lines': lines}
    doc.update(extra or {})
    return json.dumps(doc, ensure_ascii=False) + '\n'


class ClaudeProjectLaunchCase(LaunchCase):
    def setUp(self):
        super().setUp()
        (self.conf / 'env').write_text('')
        self.state.update({'claude_label': '1', 'claude_preflight': {'stdout': claude_protocol()}})
        (self.proj / '.claude').mkdir()
        (self.proj / '.claude' / 'settings.json').write_text('{"hooks": {}}')

    def claude_record(self):
        return self.store / 'claude-project' / (self.project_name() + '.json')

    def approve_claude(self, hash_value=HASH_A):
        record = self.claude_record()
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'protocol_version': 1, 'hash': hash_value}, separators=(',', ':')) + '\n')
        return record

    def launch(self, **kwargs):
        return self.run_launcher('--agent', 'claude', str(self.proj), **kwargs)


class GateSelectionTests(ClaudeProjectLaunchCase):
    def test_no_targets_skips_gate_even_on_old_image(self):
        shutil.rmtree(self.proj / '.claude')
        self.state['claude_label'] = ''
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.preflight_calls(), [])
        self.assertEqual(len(self.main_runs()), 1)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], '')
        self.assertEqual(self.main_runs()[0]['env']['CC_CLAUDE_START_MODE'], 'run')

    def test_mcp_json_alone_or_symlinked_claude_dir_triggers_gate(self):
        shutil.rmtree(self.proj / '.claude')
        (self.proj / '.mcp.json').write_text('{}')
        self.state['claude_preflight'] = {'stdout': claude_protocol(count=0)}
        self.launch()
        self.assertEqual(len(self.preflight_calls()), 1)
        (self.proj / '.mcp.json').unlink()
        (self.proj / '.claude').symlink_to('/nonexistent-outside')
        self.launch()
        self.assertEqual(len(self.preflight_calls()), 1)

    def test_missing_or_unknown_label_blocks_before_any_container_run(self):
        for label in ('', '2', '0'):
            with self.subTest(label=label):
                self.state['claude_label'] = label
                result = self.launch()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('-b', result.stderr)
                self.assertEqual(self.compose_calls('run'), [])

    def test_missing_host_python_blocks(self):
        # PATH から python3 だけを外す。fake podman は python3 で書かれているので、shebang を絶対パスに替える。
        podman = self.bin / 'podman'
        text = podman.read_text().split('\n', 1)[1]
        podman.write_text('#!' + sys.executable + '\n' + text)
        bare = self.root / 'bare-bin'
        bare.mkdir()
        for directory in os.environ['PATH'].split(':'):
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                target = Path(directory) / name
                if name.startswith('python') or (bare / name).exists() or not os.access(target, os.X_OK):
                    continue
                (bare / name).symlink_to(target)
        result = self.run_launcher('--agent', 'claude', str(self.proj),
                                   env_extra={'PATH': str(self.bin) + ':' + str(bare)})
        self.assertNotEqual(result.returncode, 0)
        # CLI 選択記憶も python3 不在の WARNING を出すので、ゲート固有の文言で確かめる。
        self.assertIn('Claude project 設定ゲート', result.stderr)
        self.assertIn('python3', result.stderr)
        self.assertEqual(self.main_runs(), [])


class PreflightTests(ClaudeProjectLaunchCase):
    def test_preflight_is_non_tty_claude_preflight_with_devnull_stdin(self):
        self.approve_claude()
        self.launch()
        call = self.preflight_calls()[0]
        self.assertEqual(call['env']['CC_AGENT'], 'claude')
        self.assertEqual(call['env']['CC_CLAUDE_START_MODE'], 'preflight')
        self.assertEqual(call['stdin'], '/dev/null')
        self.assertIn('-T', call['args'])

    def test_preflight_failure_or_malformed_protocol_blocks_run_and_writes_nothing(self):
        bad = ({'stdout': '', 'rc': 1}, {'stdout': 'noise\n' + claude_protocol()},
               {'stdout': claude_protocol(extra={'x': 1})}, {'stdout': claude_protocol(hash_value='A' * 64)},
               {'stdout': claude_protocol(count=0, lines=['x'])}, {'stdout': claude_protocol().replace('"protocol_version": 1', '"protocol_version": 2')})
        for spec in bad:
            with self.subTest(spec=spec):
                self.state['claude_preflight'] = spec
                result = self.launch(tty=True, answer='y')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.main_runs(), [])
                self.assertFalse(self.claude_record().exists())


class ApprovalTests(ClaudeProjectLaunchCase):
    def test_first_run_prompts_on_tty_and_records_atomically(self):
        result = self.launch(tty=True, answer='y')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--- .claude/settings.json ---', result.stderr)
        record = self.claude_record()
        self.assertEqual(record.read_text(), '{"protocol_version":1,"hash":"%s"}\n' % HASH_A)
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(record.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], str(record))
        self.assertEqual(list(record.parent.glob('.tmp.*')), [])

    def test_same_hash_skips_prompt_without_tty(self):
        record = self.approve_claude()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], str(record))

    def test_changed_hash_prompts_and_rejection_keeps_old_record(self):
        record = self.approve_claude(HASH_B)
        result = self.launch(tty=True, answer='n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_runs(), [])
        self.assertIn(HASH_B, record.read_text())

    def test_no_tty_blocks_unapproved(self):
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TTY', result.stderr)
        self.assertEqual(self.main_runs(), [])

    def test_zero_count_passes_without_record(self):
        self.state['claude_preflight'] = {'stdout': claude_protocol(count=0)}
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], '')
        self.assertFalse(self.claude_record().exists())

    def test_corrupt_record_requires_reconfirmation(self):
        record = self.approve_claude()
        record.write_text('{"protocol_version":1,"hash":"%s","x":1}\n' % HASH_A)
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_runs(), [])

    def test_env_file_cannot_set_claude_gate_variables(self):
        # 承認済みで本起動まで進め、本起動へ渡る値が env ファイル・シェル環境ではなく launcher の値であることを見る。
        record = self.approve_claude()
        evil = self.root / 'evil.json'
        evil.write_text(record.read_text())
        (self.conf / 'env').write_text(f'CLAUDE_PROJECT_APPROVAL_FILE={evil}\nCC_CLAUDE_START_MODE=preflight\n')
        shell = {'CLAUDE_PROJECT_APPROVAL_FILE': str(evil), 'CC_CLAUDE_START_MODE': 'preflight'}
        result = self.launch(env_extra=shell)
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.main_runs()[0]['env']
        self.assertEqual(run['CLAUDE_PROJECT_APPROVAL_FILE'], str(record))
        self.assertEqual(run['CC_CLAUDE_START_MODE'], 'run')
        self.assertIn('CLAUDE_PROJECT_APPROVAL_FILE', result.stderr)  # 許可リスト外の key の警告
        # 対象なしの経路でも launcher の値（空と run）になる。
        shutil.rmtree(self.proj / '.claude')
        result = self.launch(env_extra=shell)
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.main_runs()[0]['env']
        self.assertEqual(run['CLAUDE_PROJECT_APPROVAL_FILE'], '')
        self.assertEqual(run['CC_CLAUDE_START_MODE'], 'run')

    def test_record_write_failure_keeps_old_record_and_cleans_temp(self):
        record = self.approve_claude(HASH_B)
        real_mv = shutil.which('mv')
        fake = self.bin / 'mv'
        fake.write_text(f'#!/bin/sh\ncase "$*" in *claude-project*) exit 1 ;; esac\nexec {real_mv} "$@"\n')
        fake.chmod(0o755)
        result = self.launch(tty=True, answer='y')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(HASH_B, record.read_text())
        self.assertEqual(list(record.parent.glob('.tmp.*')), [])
        self.assertEqual(self.main_runs(), [])

    def test_codex_path_exports_empty_claude_gate_variables(self):
        (self.conf / 'env').write_text(f'CODEX_DIR={self.codex_dir}\n')
        self.approve()
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.preflight_calls() + self.main_runs():
            self.assertEqual(call['env']['CLAUDE_PROJECT_APPROVAL_FILE'], '')


class CleanTests(ClaudeProjectLaunchCase):
    def test_clean_project_removes_record_and_keeps_others(self):
        record = self.approve_claude()
        other = record.parent / 'other-0123456789ab.json'
        other.write_text('{}')
        result = self.run_launcher('--clean', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(record.exists())
        self.assertTrue(other.exists())

    def test_clean_all_removes_store(self):
        self.approve_claude()
        result = self.run_launcher('--clean')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.claude_record().exists())


class CheckTests(ClaudeProjectLaunchCase):
    def check(self):
        return self.run_launcher('--check', '--agent', 'claude', str(self.proj))

    def test_no_targets_is_ok(self):
        shutil.rmtree(self.proj / '.claude')
        result = self.check()
        self.assertIn('[OK]   Claude project 設定ゲート: 対象なし', result.stdout)
        self.assertEqual(self.compose_calls(), [])

    def test_unapproved_is_info_and_writes_nothing(self):
        before = self.snapshot(self.home)
        result = self.check()
        self.assertIn('[INFO] Claude project 設定ゲート: 未承認または変更あり', result.stdout)
        self.assertEqual(self.compose_calls(), [])
        self.assertEqual(self.snapshot(self.home), before)

    def test_approved_matching_host_view_is_ok(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('audit', str(self.runner / 'claude-project-audit.py'))
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        self.approve_claude(audit.snapshot(str(self.proj))['hash'])
        result = self.check()
        self.assertIn('[OK]   Claude project 設定ゲート: 承認済み', result.stdout)

    def test_plugin_setting_is_fail_for_migration(self):
        (self.proj / '.claude' / 'settings.json').write_text('{"enabledPlugins": {"x@y": true}}')
        result = self.check()
        self.assertIn('[FAIL]', result.stdout)
        self.assertIn('enabledPlugins', result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_old_image_label_is_fail_with_rebuild_hint(self):
        self.state['claude_label'] = ''
        result = self.check()
        self.assertIn('[FAIL] Claude project 設定ゲート: イメージが未対応', result.stdout)
        self.assertIn('-b', result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_codex_check_says_not_used(self):
        (self.conf / 'env').write_text(f'CODEX_DIR={self.codex_dir}\n')
        result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertIn('[INFO] Claude project 設定ゲート: Codex 経路では使用しない', result.stdout)

if __name__ == '__main__':
    unittest.main()
