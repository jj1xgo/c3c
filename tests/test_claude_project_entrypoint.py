#!/usr/bin/env python3
"""entrypoint の Claude project 設定ゲート（#163）の回帰試験。

tests/test_codex_entrypoint.py の EntrypointCase（固定パスを試験用コピーへ置換する fixture）を使う。
helper は実物の claude-project-audit.py。確認の応答は専用 PTY から /dev/tty へ流す。
"""

import fcntl
import json
import os
import pty
import subprocess
import sys
import termios
import unittest

from test_codex_entrypoint import EntrypointCase, ROOT

HOOKS = {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo hi'}]}]}}

# helper の呼び出し時点の環境を記録してから実物へ exec する wrapper（entrypoint は python3 -I で呼ぶので Python で書く）。
# 秘密（secrets/export の MCP_TOKEN）が helper の時点で未設定であることを観測し、ゲートが秘密の export より前にあることを確かめる。
AUDIT_WRAPPER = '''import os, sys
with open(os.environ['RECORD'], 'a') as out:
    out.write('audit MCP_TOKEN=%%s\\n' %% os.environ.get('MCP_TOKEN', 'unset'))
os.execv(sys.executable, [sys.executable, '-I', %r] + sys.argv[1:])
'''


class ClaudeProjectEntrypointCase(EntrypointCase):
    def setUp(self):
        super().setUp()
        wrapper = self.root / 'audit-wrapper.py'
        wrapper.write_text(AUDIT_WRAPPER % str(ROOT / 'claude-project-audit.py'))
        text = self.entrypoint.read_text()
        self.assertIn(str(ROOT / 'claude-project-audit.py'), text)
        self.entrypoint.write_text(text.replace(str(ROOT / 'claude-project-audit.py'), str(wrapper)))

    def audit_records(self):
        return [r for r in self.records if r.startswith('audit ')]

    def put(self, rel, doc):
        path = self.workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def run_claude(self, mode=None, tty_answer=None):
        if tty_answer is None:
            return self.run_entrypoint('claude', claude_mode=mode)
        self.state_path.write_text(json.dumps(self.state))
        self.record.write_text('')
        self.calls.write_text('')
        env = dict(self.env, CC_AGENT='claude')
        if mode is not None:
            env['CC_CLAUDE_START_MODE'] = mode
        master, slave = pty.openpty()

        def preexec():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(['bash', str(self.entrypoint)], env=env, cwd=self.root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=preexec,
                                pass_fds=(slave,))
        os.close(slave)
        os.write(master, (tty_answer + '\n').encode())
        try:
            stdout, stderr = proc.communicate(timeout=90)
        finally:
            os.close(master)
        self.records = self.record.read_text().splitlines()
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)

    def approve_from_preflight(self):
        result = self.run_entrypoint('claude', claude_mode='preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        self.claude_project_approved.write_text(json.dumps({'protocol_version': 1, 'hash': doc['hash']}) + '\n')
        return doc

    def launched(self):
        return any(r.startswith('claude --permission-mode') for r in self.records)


class PreflightTests(ClaudeProjectEntrypointCase):
    def test_preflight_stdout_is_only_the_protocol_and_claude_is_not_started(self):
        self.put('.claude/settings.json', HOOKS)
        (self.workspace / '.mcp.json').write_text(json.dumps({'mcpServers': {'s': {'command': 'evil'}}}))
        result = self.run_entrypoint('claude', claude_mode='preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        self.assertEqual(set(doc), {'protocol_version', 'hash', 'count', 'lines'})
        self.assertEqual(doc['count'], 1)
        self.assertIn('firewall stdout noise', result.stderr)
        self.assertFalse(self.launched())
        self.assertNotIn('MCP サーバーの起動を許可', result.stderr)

    def test_preflight_block_is_nonzero_with_empty_stdout(self):
        self.put('.claude/settings.json', {'enabledPlugins': {'x@y': True}})
        result = self.run_entrypoint('claude', claude_mode='preflight')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('enabledPlugins', result.stderr)

    def test_claude_mode_enum_is_validated_before_firewall(self):
        for mode in ('', 'verify', 'Preflight'):
            with self.subTest(mode=mode):
                result = self.run_entrypoint('claude', claude_mode=mode)
                self.assertEqual(result.returncode, 1)
                self.assertIn('CC_CLAUDE_START_MODE', result.stderr)
                self.assertEqual(self.records, [])


class RunTests(ClaudeProjectEntrypointCase):
    def test_no_targets_launches_as_before(self):
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.launched())

    def test_approved_record_launches_without_prompt(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.launched())

    def test_run_prompts_when_changed_after_approval_and_blocks_without_tty(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        self.put('.claude/settings.json', dict(HOOKS, env={'X': '1'}))
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 1)
        self.assertIn('TTY', result.stderr)
        self.assertFalse(self.launched())

    def test_run_prompt_yes_launches_and_no_blocks(self):
        self.put('.claude/settings.json', HOOKS)
        yes = self.run_claude('run', tty_answer='y')
        self.assertEqual(yes.returncode, 0, yes.stderr)
        self.assertIn('--- .claude/settings.json ---', yes.stderr)
        self.assertTrue(self.launched())
        no = self.run_claude('run', tty_answer='n')
        self.assertEqual(no.returncode, 1)
        self.assertFalse(self.launched())

    def test_blocked_state_never_launches_even_with_record(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        self.put('.mcp.json', {'mcpServers': {'r': {'url': 'https://x', 'headersHelper': 'x'}}})
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.launched())

    def test_gate_runs_before_secrets_are_exported(self):
        (self.fixture_mount_dir / 'export' / 'MCP_TOKEN').write_text('tok\n')
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 0, result.stderr)
        # 起動まで進むケースで、helper の時点では秘密が未設定、claude の時点では設定済み。
        self.assertEqual(self.audit_records(), ['audit MCP_TOKEN=unset'])
        self.assertTrue(any('MCP_TOKEN=tok' in r for r in self.records if r.startswith('claude-env')))


if __name__ == '__main__':
    unittest.main()
