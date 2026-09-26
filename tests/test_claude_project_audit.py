#!/usr/bin/env python3
"""Claude 経路の project 設定ゲート helper（#163、protocol 1）の回帰試験。

helper は /workspace に当たる --root の `.claude/settings.json`・`.claude/settings.local.json` をファイル全体で
hash し、plugin 類と `.mcp.json` の headersHelper を止める。ここで固定する protocol と終了コードは
launcher（c3c）と entrypoint.sh が消費する。
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'claude-project-audit.py'
DOMAIN = b'c3c-claude-project-audit\x00v1\x00'
HOOKS = {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo hi'}]}]}}


def expected_hash(files):
    digest = hashlib.sha256(DOMAIN)
    for rel, data in sorted(files, key=lambda item: item[0].encode()):
        path = rel.encode()
        digest.update(len(path).to_bytes(8, 'big') + path + len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest()


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'workspace'
        (self.root / '.claude').mkdir(parents=True)
        self.record = self.base / 'record.json'

    def put(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else json.dumps(content).encode()
        path.write_bytes(data)
        return data

    def run_helper(self, *args, root=None):
        return subprocess.run([sys.executable, '-I', str(HELPER), '--root', str(root or self.root), *args],
                              capture_output=True, text=True, timeout=30)

    def snapshot(self):
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_blocked(self, needle):
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout, '')
        self.assertIn(needle, result.stderr)
        verify = self.run_helper('verify', os.devnull)
        self.assertEqual(verify.returncode, 1)


class SnapshotTests(AuditCase):
    def test_no_targets_is_count_zero_with_empty_lines(self):
        doc = self.snapshot()
        self.assertEqual(doc, {'protocol_version': 1, 'hash': expected_hash([]), 'count': 0, 'lines': []})

    def test_hash_covers_whole_settings_files_with_fixed_encoding(self):
        a = self.put('.claude/settings.json', HOOKS)
        b = self.put('.claude/settings.local.json', {'permissions': {'allow': ['Bash(ls:*)']}})
        doc = self.snapshot()
        self.assertEqual(doc['count'], 2)
        self.assertEqual(doc['hash'], expected_hash([('.claude/settings.json', a), ('.claude/settings.local.json', b)]))

    def test_any_byte_change_changes_hash_including_unknown_keys(self):
        self.put('.claude/settings.json', HOOKS)
        first = self.snapshot()['hash']
        self.put('.claude/settings.json', dict(HOOKS, statusLine={'type': 'command', 'command': 'x'}))
        self.assertNotEqual(self.snapshot()['hash'], first)
        self.put('.claude/settings.json', json.dumps(HOOKS, indent=2).encode())
        self.assertNotEqual(self.snapshot()['hash'], first)

    def test_hash_is_independent_of_read_order_and_length_prefixed(self):
        a = self.put('.claude/settings.json', {'a': 1})
        b = self.put('.claude/settings.local.json', {'b': 2})
        forward = expected_hash([('.claude/settings.json', a), ('.claude/settings.local.json', b)])
        self.assertEqual(forward, expected_hash([('.claude/settings.local.json', b), ('.claude/settings.json', a)]))
        self.assertEqual(self.snapshot()['hash'], forward)
        # 区切りの衝突: 内容の境界をずらしても同じ hash にならない（長さの前置き）。
        self.assertNotEqual(expected_hash([('x', b'ab'), ('y', b'c')]), expected_hash([('x', b'a'), ('y', b'bc')]))

    def test_empty_settings_file_is_hashed_as_no_settings(self):
        # c3c の prepare_claude_config_ro() は ~/.claude/settings.json を 0 バイトで作る。$HOME を作業ディレクトリに
        # すると、それが /workspace/.claude/settings.json になる。0 バイトは何も設定できないので判定不能にしない。
        data = self.put('.claude/settings.json', b'')
        doc = self.snapshot()
        self.assertEqual(doc['count'], 1)
        self.assertEqual(doc['hash'], expected_hash([('.claude/settings.json', data)]))
        self.assertEqual(doc['lines'], ['--- .claude/settings.json ---'])

    def test_local_settings_is_always_hashed(self):
        self.put('.claude/settings.local.json', {'permissions': {'allow': []}})
        self.assertEqual(self.snapshot()['count'], 1)

    def test_display_shows_whole_file_including_env_values_without_control_chars(self):
        self.put('.claude/settings.json', b'{"env": {"BASH_ENV": "./x.sh\\u001b[2J"},\n "k": "a\x7fb"}')
        lines = self.snapshot()['lines']
        self.assertEqual(lines[0], '--- .claude/settings.json ---')
        joined = '\n'.join(lines)
        self.assertIn('BASH_ENV', joined)
        self.assertIn('./x.sh', joined)
        for line in lines:
            self.assertNotRegex(line, '[\x00-\x1f\x7f]')

    def test_display_truncates_after_200_lines_and_says_so(self):
        body = '{\n' + ',\n'.join(f'"k{i}": {i}' for i in range(300)) + '\n}'
        self.put('.claude/settings.json', body.encode())
        lines = self.snapshot()['lines']
        self.assertEqual(len(lines), 1 + 200 + 1)
        self.assertIn('省略', lines[-1])

    def test_disabled_plugins_and_empty_marketplaces_are_allowed(self):
        self.put('.claude/settings.json', {'enabledPlugins': {'x@y': False}, 'extraKnownMarketplaces': {}})
        self.assertEqual(self.snapshot()['count'], 1)


class BlockTests(AuditCase):
    def test_enabled_plugins_are_blocked(self):
        for value in (True, 'yes', None, 1):
            with self.subTest(value=value):
                self.put('.claude/settings.json', {'enabledPlugins': {'evil@mk': value}})
                self.assert_blocked('enabledPlugins')

    def test_plugins_in_local_settings_are_blocked(self):
        self.put('.claude/settings.local.json', {'enabledPlugins': {'evil@mk': True}})
        self.assert_blocked('settings.local.json')

    def test_marketplaces_are_blocked(self):
        self.put('.claude/settings.json', {'extraKnownMarketplaces': {'mk': {'source': {'source': 'github', 'repo': 'a/b'}}}})
        self.assert_blocked('extraKnownMarketplaces')

    def test_plugin_env_keys_are_blocked(self):
        self.put('.claude/settings.json', {'env': {'CLAUDE_CODE_PLUGIN_DIRS': '/workspace/p'}})
        self.assert_blocked('CLAUDE_CODE_PLUGIN_DIRS')

    def test_skills_directory_plugin_is_blocked(self):
        self.put('.claude/skills/tool/.claude-plugin/plugin.json', {'name': 'tool'})
        self.assert_blocked('plugin.json')

    def test_mcp_headers_helper_is_blocked(self):
        self.put('.mcp.json', {'mcpServers': {'remote': {'type': 'http', 'url': 'https://x', 'headersHelper': '/bin/x'}}})
        self.assert_blocked('headersHelper')

    def test_empty_mcp_json_is_not_a_target(self):
        # 従来の .mcp.json ゲート（jq）は 0 バイトの .mcp.json を通していた。0 バイトは何も定義できないので止めない。
        self.put('.mcp.json', b'')
        self.assertEqual(self.snapshot()['count'], 0)

    def test_whitespace_only_mcp_json_is_not_a_target(self):
        # 従来の .mcp.json ゲート（jq）は空白だけの .mcp.json も通していた。
        self.put('.mcp.json', b' \n\t\r\n')
        self.assertEqual(self.snapshot()['count'], 0)

    def test_mcp_without_helper_is_not_a_target(self):
        self.put('.mcp.json', {'mcpServers': {'s': {'command': 'node'}}})
        self.assertEqual(self.snapshot()['count'], 0)


class UndecidableTests(AuditCase):
    def test_broken_or_non_object_or_duplicate_json_is_undecidable(self):
        for data in (b'{broken', b'[]', b'{"a": 1, "a": 2}', b'{"a": NaN}', b'\xff\xfe'):
            with self.subTest(data=data):
                self.put('.claude/settings.json', data)
                self.assert_blocked('判定できません')

    def test_wrong_types_of_checked_keys_are_undecidable(self):
        for doc in ({'enabledPlugins': []}, {'extraKnownMarketplaces': 'x'}, {'env': ['a']}):
            with self.subTest(doc=doc):
                self.put('.claude/settings.json', doc)
                self.assert_blocked('判定できません')
        (self.root / '.claude' / 'settings.json').unlink()
        self.put('.mcp.json', {'mcpServers': []})
        self.assert_blocked('判定できません')

    def test_outward_symlinks_are_undecidable(self):
        outside = self.base / 'outside'
        (outside / '.claude').mkdir(parents=True)
        (outside / '.claude' / 'settings.json').write_text(json.dumps(HOOKS))
        cases = (('.claude/settings.json', outside / '.claude' / 'settings.json'),
                 ('.mcp.json', outside / '.claude' / 'settings.json'))
        for rel, target in cases:
            with self.subTest(rel=rel):
                link = self.root / rel
                link.symlink_to(target)
                self.assert_blocked('判定できません')
                link.unlink()
        (self.root / '.claude').rmdir()
        (self.root / '.claude').symlink_to(outside / '.claude')
        self.assert_blocked('判定できません')

    def test_error_messages_strip_control_characters_from_repo_names(self):
        # skills の名前は repo 側が決められる。判定不能のエラー文に埋め込まれた ESC 等を、そのまま端末へ出さない（#35）。
        skills = self.root / '.claude' / 'skills'
        skills.mkdir()
        (skills / 'x\x1b[2J\x1b[Hfake').symlink_to(self.base)
        for args in (('snapshot',), ('verify', os.devnull)):
            with self.subTest(args=args):
                result = self.run_helper(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn('判定できません', result.stderr)
                self.assertIn('fake', result.stderr)
                self.assertNotRegex(result.stderr.rstrip('\n'), '[\x00-\x09\x0b-\x1f\x7f]')

    def test_dangling_and_looping_symlinks_are_undecidable(self):
        link = self.root / '.claude' / 'settings.json'
        link.symlink_to(self.root / 'missing.json')
        self.assert_blocked('判定できません')
        link.unlink()
        a, b = self.root / 'a', self.root / 'b'
        a.symlink_to(b)
        b.symlink_to(a)
        link.symlink_to(a)
        self.assert_blocked('判定できません')

    def test_inward_symlink_is_followed(self):
        real = self.put('shared/settings.json', HOOKS)
        (self.root / '.claude' / 'settings.json').symlink_to(self.root / 'shared' / 'settings.json')
        self.assertEqual(self.snapshot()['hash'], expected_hash([('.claude/settings.json', real)]))

    def test_fifo_and_directory_are_undecidable_without_blocking(self):
        os.mkfifo(self.root / '.claude' / 'settings.json')
        self.assert_blocked('判定できません')
        (self.root / '.claude' / 'settings.json').unlink()
        (self.root / '.claude' / 'settings.json').mkdir()
        self.assert_blocked('判定できません')

    def test_oversized_file_is_undecidable(self):
        self.put('.claude/settings.json', b'{"a": "' + b'x' * (1024 * 1024) + b'"}')
        self.assert_blocked('判定できません')

    @unittest.skipIf(os.geteuid() == 0, 'root は読み取り権限を無視する')
    def test_unreadable_file_and_unlistable_skills_are_undecidable(self):
        path = self.root / '.claude' / 'settings.json'
        self.put('.claude/settings.json', HOOKS)
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        self.assert_blocked('判定できません')
        path.chmod(0o644)
        skills = self.root / '.claude' / 'skills'
        skills.mkdir()
        skills.chmod(0)
        self.addCleanup(skills.chmod, 0o755)
        self.assert_blocked('判定できません')

    @unittest.skipIf(os.geteuid() == 0, 'root は検索権限を無視する')
    def test_unsearchable_claude_dir_is_undecidable_not_absent(self):
        self.put('.claude/settings.json', HOOKS)
        claude = self.root / '.claude'
        claude.chmod(0o600)
        self.addCleanup(claude.chmod, 0o755)
        self.assert_blocked('判定できません')

    def test_bad_arguments_exit_1_and_help_exits_0(self):
        bad = subprocess.run([sys.executable, '-I', str(HELPER), 'snapshot'], capture_output=True, text=True, timeout=30)
        self.assertEqual(bad.returncode, 1)
        ok = subprocess.run([sys.executable, '-I', str(HELPER), '--help'], capture_output=True, text=True, timeout=30)
        self.assertEqual(ok.returncode, 0)

    def test_relative_root_is_rejected(self):
        result = subprocess.run([sys.executable, '-I', str(HELPER), '--root', 'workspace', 'snapshot'],
                                capture_output=True, text=True, cwd=self.base, timeout=30)
        self.assertEqual(result.returncode, 1)


class VerifyTests(AuditCase):
    def approve(self):
        doc = self.snapshot()
        self.record.write_text(json.dumps({'protocol_version': 1, 'hash': doc['hash']}, separators=(',', ':')) + '\n')

    def test_no_targets_passes_without_record(self):
        self.assertEqual(self.run_helper('verify', os.devnull).returncode, 0)

    def test_matching_record_passes_and_change_requires_review(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve()
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 0)
        self.put('.claude/settings.json', dict(HOOKS, extra=1))
        result = self.run_helper('verify', str(self.record))
        self.assertEqual(result.returncode, 3)
        self.assertIn('--- .claude/settings.json ---', result.stderr)

    def test_missing_record_requires_review(self):
        self.put('.claude/settings.json', HOOKS)
        self.assertEqual(self.run_helper('verify', os.devnull).returncode, 3)

    def test_verify_treats_malformed_record_as_missing(self):
        self.put('.claude/settings.json', HOOKS)
        doc = self.snapshot()
        for text in ('', '{broken', json.dumps({'protocol_version': 2, 'hash': doc['hash']}),
                     json.dumps({'protocol_version': 1, 'hash': doc['hash'], 'x': 1})):
            with self.subTest(text=text):
                self.record.write_text(text)
                self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 3)

    def test_blocked_state_wins_over_matching_record(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve()
        self.put('.mcp.json', {'mcpServers': {'r': {'url': 'https://x', 'headersHelper': 'x'}}})
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 1)


if __name__ == '__main__':
    unittest.main()
