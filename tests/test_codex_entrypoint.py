#!/usr/bin/env python3
"""entrypoint の agent 分岐（c3c 第1段階 Task 3）の回帰試験。

実物の entrypoint.sh を隔離 fixture で実行する（tests/test_ipv6_entrypoint.py と同じ流儀で、固定パスを
試験用コピーへ置換する）。sudo/firewall-refresh/claude は記録だけの fake、Codex CLI は `--version` と
`mcp list --json` に fixture を返し exec 時の argv/env/cwd を記録する dummy、MCP 審査 helper は Task 1 で
検証済みの実物 codex-mcp-audit.py を使う。実 /home/node・/workspace・ホストの設定や認証には触れない。
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
HELPER = ROOT / 'codex-mcp-audit.py'
SUPPORTED = '0.155.1'
TRUST_OVERRIDE = 'projects={"/workspace"={trust_level="trusted"}}'
FIXED_HOME = '/home/node/.codex'
FIXED_CLI = '/usr/local/bin/codex'
FIXED_HELPER = '/usr/local/bin/codex-mcp-audit.py'
FIXED_APPROVED = '/etc/claude-container/codex-mcp-approved.json'
CLAUDE_APPROVED = '/etc/claude-container/mcp-approved-hash'
SECRETS_MOUNT = '/home/node/.config/claude-container/secrets'

# Codex CLI の dummy: 版と一覧は状態ファイルの fixture、それ以外の argv は exec として記録する。
CODEX = '''#!/usr/bin/env python3
import json, os, sys
state_path = %r
with open(state_path) as handle:
    state = json.load(handle)
args = sys.argv[1:]
kind = 'version' if args == ['--version'] else 'list' if 'mcp' in args and 'list' in args else 'exec'
with open(state['calls'], 'a') as out:
    out.write(json.dumps({'kind': kind, 'args': args, 'argv0': sys.argv[0], 'cwd': os.getcwd(),
                          'env': {k: os.environ.get(k) for k in ('CODEX_HOME', 'HOME', 'PATH', 'MCP_TOKEN', 'CC_AGENT')}}) + '\\n')
if kind == 'version':
    sys.stdout.write(state.get('version', 'codex-cli 0.155.1\\n'))
elif kind == 'list':
    sys.stdout.write(json.dumps(state['listing']) + '\\n')
sys.exit(0)
'''

RECORDER = '''#!/bin/sh
printf '%s %s\\n' "{name}" "$*" >> "$RECORD"
{extra}
exit 0
'''


def stdio(name, command='python3', args=('server.py',), env=None, env_vars=('HOME',), cwd='/workspace', enabled=True):
    return {'name': name, 'enabled': enabled, 'disabled_reason': None,
            'transport': {'type': 'stdio', 'command': command, 'args': list(args), 'env': env,
                          'env_vars': list(env_vars), 'cwd': cwd},
            'startup_timeout_sec': None, 'tool_timeout_sec': None, 'auth_status': 'unsupported'}


def http_helper(name):
    return {'name': name, 'enabled': True, 'disabled_reason': None,
            'transport': {'type': 'streamable_http', 'url': 'https://mcp.example/mcp', 'bearer_token_env_var': None,
                          'http_headers': None, 'env_http_headers': None, 'http_headers_helper': '<redacted>'},
            'startup_timeout_sec': None, 'tool_timeout_sec': None, 'auth_status': 'unsupported'}


class EntrypointCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-codex-entry-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.record = self.root / 'record'
        self.calls = self.root / 'codex-calls'
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.codex_home = self.root / 'codex-home'
        self.codex_home.mkdir()
        self.secrets = self.root / 'secrets'
        (self.secrets / 'export').mkdir(parents=True)
        self.approved = self.root / 'codex-approved.json'
        self.claude_approved = self.root / 'claude-approved'
        self.state_path = self.root / 'state.json'
        self.state = {'calls': str(self.calls), 'listing': [stdio('alpha', env={'API_KEY': 'v'})]}
        self.codex = self.root / 'codex'
        self.codex.write_text(CODEX % str(self.state_path))
        self.codex.chmod(0o755)
        for name, extra in (('sudo', 'echo "firewall stdout noise"'), ('refresh', ''), ('claude', 'printf "claude-env MCP_TOKEN=%s CODEX_HOME=%s\\n" "${MCP_TOKEN-unset}" "${CODEX_HOME-unset}" >> "$RECORD"')):
            path = self.bin / name
            path.write_text(RECORDER.format(name=name, extra=extra))
            path.chmod(0o755)
        source = (ROOT / 'entrypoint.sh').read_text()
        for needle in (FIXED_HOME, FIXED_HELPER, FIXED_CLI, FIXED_APPROVED, CLAUDE_APPROVED, SECRETS_MOUNT,
                       '/usr/local/bin/firewall-refresh.py', '/workspace/.mcp.json', 'cd -- /workspace'):
            self.assertIn(needle, source, f'entrypoint.sh に固定パス {needle} がない')
        # 固定パスを試験用コピーへ置換する。trust override の "/workspace" は helper 側の固定値と一致させるため置換しない。
        source = (source.replace(FIXED_HELPER, str(HELPER)).replace(FIXED_CLI, str(self.codex))
                  .replace(FIXED_HOME, str(self.codex_home)).replace(FIXED_APPROVED, str(self.approved))
                  .replace(CLAUDE_APPROVED, str(self.claude_approved)).replace(SECRETS_MOUNT, str(self.secrets))
                  .replace('/usr/local/bin/firewall-refresh.py', str(self.bin / 'refresh'))
                  .replace('/workspace/.mcp.json', str(self.workspace / '.mcp.json'))
                  .replace('cd -- /workspace', 'cd -- ' + str(self.workspace)))
        self.entrypoint = self.root / 'entrypoint.sh'
        self.entrypoint.write_text(source)
        self.env = {'PATH': str(self.bin) + ':' + os.defpath, 'RECORD': str(self.record), 'HOME': str(self.root / 'home'),
                    'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}

    def run_entrypoint(self, agent=None, mode=None, read_only=None, tty_answer=None):
        self.state_path.write_text(json.dumps(self.state))
        self.record.write_text('')
        self.calls.write_text('')
        env = dict(self.env)
        for key, value in (('CC_AGENT', agent), ('CC_CODEX_START_MODE', mode), ('CC_CODEX_READ_ONLY', read_only)):
            if value is not None:
                env[key] = value
        result = subprocess.run(['bash', str(self.entrypoint)], env=env, cwd=self.root, text=True, capture_output=True,
                                stdin=subprocess.DEVNULL, timeout=90, start_new_session=True)
        self.records = self.record.read_text().splitlines()
        self.codex_calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        return result

    def kinds(self):
        return [c['kind'] for c in self.codex_calls]

    def approve_from_preflight(self):
        result = self.run_entrypoint('codex', 'preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        protocol = json.loads(result.stdout)
        self.approved.write_text(json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': protocol['hash']}) + '\n')
        return protocol


class ClaudePathTests(EntrypointCase):
    def test_default_and_explicit_claude_keep_existing_order_and_argv(self):
        (self.secrets / 'export' / 'MCP_TOKEN').write_text('tok\n')
        for agent in (None, 'claude'):
            with self.subTest(agent=agent):
                result = self.run_entrypoint(agent)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([r.split()[0] for r in self.records], ['sudo', 'refresh', 'claude', 'claude-env'])
                self.assertEqual(self.records[2], 'claude --dangerously-skip-permissions')
                self.assertIn('MCP_TOKEN=tok', self.records[3])
                self.assertEqual(self.codex_calls, [])
                self.assertNotIn('Codex', result.stderr)

    def test_claude_gate_still_blocks_without_tty(self):
        (self.workspace / '.mcp.json').write_text(json.dumps({'mcpServers': {'srv': {'command': 'evil'}}}))
        result = self.run_entrypoint('claude')
        self.assertEqual(result.returncode, 1)
        self.assertIn('TTY', result.stderr)
        self.assertFalse(any(r.startswith('claude') for r in self.records))


class AgentValidationTests(EntrypointCase):
    def test_unknown_or_empty_agent_is_rejected_before_firewall(self):
        for agent in ('', 'gemini', 'Codex', ' codex'):
            with self.subTest(agent=agent):
                result = self.run_entrypoint(agent)
                self.assertEqual(result.returncode, 1)
                self.assertIn('CC_AGENT', result.stderr)
                self.assertEqual(self.records, [])
                self.assertEqual(self.codex_calls, [])

    def test_codex_requires_valid_mode_and_read_only_enum(self):
        for mode, read_only in ((None, '0'), ('', '0'), ('verify', '0'), ('run', '2'), ('run', ''), ('preflight', 'yes')):
            with self.subTest(mode=mode, read_only=read_only):
                result = self.run_entrypoint('codex', mode, read_only)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.records, [])
                self.assertEqual(self.codex_calls, [])


class PreflightTests(EntrypointCase):
    def test_preflight_stdout_is_only_the_protocol_and_logs_go_to_stderr(self):
        (self.workspace / '.mcp.json').write_text(json.dumps({'mcpServers': {'claude-only': {'command': 'evil'}}}))
        result = self.run_entrypoint('codex', 'preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        protocol = json.loads(result.stdout)
        self.assertEqual(set(protocol), {'protocol_version', 'codex_version', 'hash', 'count', 'servers'})
        self.assertEqual(protocol['count'], 1)
        self.assertIn('firewall stdout noise', result.stderr)
        self.assertNotIn('firewall stdout noise', result.stdout)
        self.assertEqual([r.split()[0] for r in self.records], ['sudo', 'refresh'])
        self.assertEqual(self.kinds(), ['version', 'list'])
        self.assertNotIn('claude-only', result.stderr)
        self.assertNotIn('TTY', result.stderr)

    def test_preflight_after_firewall_and_secret_export(self):
        (self.secrets / 'export' / 'MCP_TOKEN').write_text('tok\n')
        result = self.run_entrypoint('codex', 'preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.records[0].startswith('sudo'))
        self.assertEqual(self.codex_calls[0]['env']['MCP_TOKEN'], 'tok')
        self.assertEqual(self.codex_calls[0]['env']['CODEX_HOME'], str(self.codex_home))

    def test_preflight_failure_is_nonzero_with_empty_stdout(self):
        self.state['listing'] = [stdio('alpha'), http_helper('remote')]
        result = self.run_entrypoint('codex', 'preflight')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('remote', result.stderr)
        self.assertNotIn('exec', self.kinds())


class RunTests(EntrypointCase):
    def test_run_verifies_then_execs_fixed_argv(self):
        self.approve_from_preflight()
        for read_only, sandbox in (('0', 'workspace-write'), ('1', 'read-only')):
            with self.subTest(read_only=read_only):
                result = self.run_entrypoint('codex', 'run', read_only)
                self.assertEqual(result.returncode, 0, result.stderr)
                # 本起動では stdout の分離契約は無い（firewall 等の通常出力が出る）。protocol は出ない。
                self.assertNotIn('"hash"', result.stdout)
                self.assertEqual(self.kinds(), ['version', 'list', 'exec'])
                execd = self.codex_calls[-1]
                self.assertEqual(execd['args'], ['--sandbox', sandbox, '--ask-for-approval', 'on-request', '-c', TRUST_OVERRIDE])
                self.assertEqual([r.split()[0] for r in self.records], ['sudo', 'refresh'])
                self.assertIn('一致', result.stderr)

    def test_three_stages_share_home_cwd_override_and_cli(self):
        self.approve_from_preflight()
        preflight_list = next(c for c in self.codex_calls if c['kind'] == 'list')
        result = self.run_entrypoint('codex', 'run', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        verify_list = next(c for c in self.codex_calls if c['kind'] == 'list')
        execd = self.codex_calls[-1]
        for stage in (preflight_list, verify_list, execd):
            self.assertEqual(stage['env']['CODEX_HOME'], str(self.codex_home))
            self.assertEqual(stage['env']['HOME'], str(self.root / 'home'))
            self.assertEqual(stage['cwd'], str(self.workspace))
            self.assertEqual(stage['argv0'], str(self.codex))
            self.assertEqual(stage['args'][stage['args'].index('-c') + 1], TRUST_OVERRIDE)

    def test_verify_failure_never_execs_native_cli(self):
        self.approve_from_preflight()
        cases = {
            'changed definition': lambda: self.state.update(listing=[stdio('alpha', args=('server.py', '--evil'), env={'API_KEY': 'v'})]),
            'empty record': lambda: self.approved.write_text(''),
            'missing record': lambda: self.approved.unlink(),
            'wrong hash': lambda: self.approved.write_text(json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': '0' * 64})),
            'helper http appears': lambda: self.state.update(listing=[stdio('alpha', env={'API_KEY': 'v'}), http_helper('remote')]),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                self.setUp()
                self.approve_from_preflight()
                mutate()
                result = self.run_entrypoint('codex', 'run', '0')
                self.assertEqual(result.returncode, 1, label)
                self.assertNotIn('exec', self.kinds(), label)
                self.assertFalse(any(r.startswith('claude') for r in self.records), label)

    def test_missing_cli_or_unsupported_version_has_no_fallback(self):
        self.approve_from_preflight()
        for label, mutate in (('missing cli', lambda: self.codex.unlink()),
                              ('wrong version', lambda: self.state.update(version='codex-cli 0.156.0\n'))):
            with self.subTest(case=label):
                mutate()
                for mode in ('preflight', 'run'):
                    result = self.run_entrypoint('codex', mode, '0')
                    self.assertEqual(result.returncode, 1, mode)
                    if mode == 'preflight':
                        self.assertEqual(result.stdout, '')
                    self.assertNotIn('"hash"', result.stdout)
                    self.assertNotIn('exec', self.kinds())
                    self.assertFalse(any(r.startswith('claude') for r in self.records))
                    self.assertIn('Codex', result.stderr)
                self.setUp()
                self.approve_from_preflight()


class ComposeContractTests(EntrypointCase):
    """compose.yml の変数解決を実 provider の config で取り、その値を entrypoint に通す（正規表現の推測ではなく実解決）。"""

    KEYS = ('CC_AGENT', 'CC_CODEX_START_MODE', 'CC_CODEX_READ_ONLY')

    def resolved(self, overrides):
        podman = shutil.which('podman')
        if podman is None:
            self.skipTest('podman が無いため compose の実解決を確認できない')
        # provider は bind source（~ 配下）を lstat するので、隔離 HOME に空の実体を置く。
        home = Path(self.env['HOME'])
        (home / '.claude').mkdir(parents=True, exist_ok=True)
        (home / '.claude.json').touch()
        env = {'PATH': os.environ['PATH'], 'HOME': self.env['HOME'], 'BUILD_CONTEXT_DIR': str(self.root),
               'CONTEXT': str(self.workspace), 'CLAUDE_CONTAINER_DIR': str(ROOT)}
        env.update(overrides)
        result = subprocess.run([podman, 'compose', '-f', str(ROOT / 'compose.yml'), '--env-file', '/dev/null', 'config'],
                                env=env, cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = {}
        for line in result.stdout.splitlines():
            match = re.match(r'^\s+(CC_AGENT|CC_CODEX_START_MODE|CC_CODEX_READ_ONLY):\s*(.*?)\s*$', line)
            if match:
                value = match.group(2)
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
                    value = value[1:-1]
                values[match.group(1)] = value
        self.assertEqual(set(values), set(self.KEYS), result.stdout)
        return values

    def test_unset_defaults_reach_entrypoint_as_claude_run(self):
        values = self.resolved({})
        self.assertEqual(values, {'CC_AGENT': 'claude', 'CC_CODEX_START_MODE': 'run', 'CC_CODEX_READ_ONLY': '0'})
        result = self.run_entrypoint(values['CC_AGENT'], values['CC_CODEX_START_MODE'], values['CC_CODEX_READ_ONLY'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(r.startswith('claude ') for r in self.records))

    def test_explicit_empty_or_unknown_values_are_not_defaulted_and_are_rejected(self):
        cases = {
            'empty agent': ({'CC_AGENT': ''}, 'CC_AGENT', ''),
            'unknown agent': ({'CC_AGENT': 'gemini'}, 'CC_AGENT', 'gemini'),
            'empty mode': ({'CC_AGENT': 'codex', 'CC_CODEX_START_MODE': ''}, 'CC_CODEX_START_MODE', ''),
            'unknown mode': ({'CC_AGENT': 'codex', 'CC_CODEX_START_MODE': 'verify'}, 'CC_CODEX_START_MODE', 'verify'),
            'empty read-only': ({'CC_AGENT': 'codex', 'CC_CODEX_READ_ONLY': ''}, 'CC_CODEX_READ_ONLY', ''),
            'unknown read-only': ({'CC_AGENT': 'codex', 'CC_CODEX_READ_ONLY': 'yes'}, 'CC_CODEX_READ_ONLY', 'yes'),
        }
        for label, (overrides, key, expected) in cases.items():
            with self.subTest(case=label):
                values = self.resolved(overrides)
                self.assertEqual(values[key], expected, values)
                result = self.run_entrypoint(values['CC_AGENT'], values['CC_CODEX_START_MODE'], values['CC_CODEX_READ_ONLY'])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(key, result.stderr)
                self.assertEqual(self.records, [])
                self.assertEqual(self.codex_calls, [])

    def test_codex_selection_resolves_to_run_or_preflight_only_when_explicit(self):
        for mode in ('run', 'preflight'):
            with self.subTest(mode=mode):
                values = self.resolved({'CC_AGENT': 'codex', 'CC_CODEX_START_MODE': mode, 'CC_CODEX_READ_ONLY': '1'})
                self.assertEqual(values, {'CC_AGENT': 'codex', 'CC_CODEX_START_MODE': mode, 'CC_CODEX_READ_ONLY': '1'})


class SecretIsolationTests(EntrypointCase):
    def test_secrets_cannot_replace_fixed_home_cli_path_but_general_secrets_pass(self):
        other_home = self.root / 'other-home'
        other_home.mkdir()
        (self.secrets / 'export' / 'CODEX_HOME').write_text(str(other_home) + '\n')
        (self.secrets / 'export' / 'HOME').write_text('/tmp/evil-home\n')
        (self.secrets / 'export' / 'PATH').write_text('/tmp/evil-bin\n')
        (self.secrets / 'export' / 'MCP_TOKEN').write_text('tok\n')
        self.approve_from_preflight()
        for mode in ('preflight', 'run'):
            with self.subTest(mode=mode):
                result = self.run_entrypoint('codex', mode, '0')
                self.assertEqual(result.returncode, 0, result.stderr)
                for call in self.codex_calls:
                    self.assertEqual(call['env']['CODEX_HOME'], str(self.codex_home))
                    self.assertEqual(call['env']['HOME'], str(self.root / 'home'))
                    self.assertTrue(call['env']['PATH'].startswith(str(self.bin)))
                    self.assertEqual(call['env']['MCP_TOKEN'], 'tok')
                for name in ('CODEX_HOME', 'HOME', 'PATH'):
                    self.assertIn(f"'{name}' は既に環境変数に設定されています", result.stderr)
                self.assertEqual(list(other_home.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
