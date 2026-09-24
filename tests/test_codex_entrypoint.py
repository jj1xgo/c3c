#!/usr/bin/env python3
"""entrypoint の agent 分岐（c3c 第1段階 Task 3）の回帰試験。

実物の entrypoint.sh を隔離 fixture で実行する（tests/test_ipv6_entrypoint.py と同じ流儀で、固定パスを
試験用コピーへ置換する）。sudo/firewall-refresh/claude は記録だけの fake、Codex CLI は exec 時の
argv/env/cwd を記録する dummy、MCP 審査 helper は実物の codex-mcp-audit.py を使う。審査の fixture は
試験用 workspace の `.codex/config.toml`（#150 の protocol 2 から helper は Codex CLI を呼ばない）。
実 /home/node・/workspace・ホストの設定や認証には触れない。
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
TRUST_OVERRIDE = 'projects={"/workspace"={trust_level="trusted"}}'
FIXED_HOME = '/home/node/.codex'
FIXED_CLI = '/usr/local/bin/codex'
FIXED_HELPER = '/usr/local/bin/codex-mcp-audit.py'
FIXED_APPROVED = '/etc/claude-container/codex-mcp-approved.json'
CLAUDE_APPROVED = '/etc/claude-container/mcp-approved-hash'
SECRETS_MOUNT = '/home/node/.config/claude-container/secrets'
FIXED_BWRAP_DIR = '/usr/local/libexec/c3c/codex-bwrap'
FIXED_PROJECT_CONFIG = '/workspace/.codex/config.toml'

# Codex CLI の dummy: 呼び出しをすべて記録する。protocol 2 の審査は CLI を呼ばないので、'version'/'list' が
# 記録されたら審査が CLI に依存している回帰になる。
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
    sys.stdout.write(state.get('version', 'codex-cli 0.156.0\\n'))
elif kind == 'list':
    sys.stdout.write('[]\\n')
sys.exit(0)
'''

RECORDER = '''#!/bin/sh
printf '%s %s\\n' "{name}" "$*" >> "$RECORD"
{extra}
exit 0
'''


# リポジトリ同梱の .codex/config.toml の fixture。
STDIO_ALPHA = ('[mcp_servers.alpha]\ncommand = "python3"\nargs = ["server.py"]\ncwd = "/workspace"\n'
               'env_vars = ["HOME"]\nenv = { API_KEY = "v" }\n')
HELPER_HTTP = '[mcp_servers.remote]\nurl = "https://mcp.example/mcp"\nhttp_headers_helper = "/bin/x"\n'


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
        # 秘密の値ではなく、試験用コピーへ埋め込む一時 mount 先のパス。
        self.fixture_mount_dir = self.root / 'secrets'
        (self.fixture_mount_dir / 'export').mkdir(parents=True)
        self.approved = self.root / 'codex-approved.json'
        self.claude_approved = self.root / 'claude-approved'
        self.state_path = self.root / 'state.json'
        self.state = {'calls': str(self.calls)}
        self.config_text = STDIO_ALPHA
        self.project_config = self.workspace / '.codex' / 'config.toml'
        self.codex = self.root / 'codex'
        self.codex.write_text(CODEX % str(self.state_path))
        self.codex.chmod(0o755)
        for name, extra in (('sudo', 'echo "firewall stdout noise"'), ('refresh', ''), ('claude', 'printf "claude-env MCP_TOKEN=%s CODEX_HOME=%s PATH=%s\\n" "${MCP_TOKEN-unset}" "${CODEX_HOME-unset}" "$PATH" >> "$RECORD"')):
            path = self.bin / name
            path.write_text(RECORDER.format(name=name, extra=extra))
            path.chmod(0o755)
        # Codex 同梱 bubblewrap の固定リンク（#145）: 専用ディレクトリ内の symlink → 実体の dummy。
        self.bwrap_dir = self.root / 'codex-bwrap'
        self.bwrap_dir.mkdir()
        self.bwrap_real = self.root / 'bwrap-real'
        self.bwrap_real.write_text('#!/bin/sh\nexit 0\n')
        self.bwrap_real.chmod(0o755)
        (self.bwrap_dir / 'bwrap').symlink_to(self.bwrap_real)
        source = (ROOT / 'entrypoint.sh').read_text()
        for needle in (FIXED_HOME, FIXED_HELPER, FIXED_CLI, FIXED_APPROVED, CLAUDE_APPROVED, SECRETS_MOUNT, FIXED_BWRAP_DIR,
                       FIXED_PROJECT_CONFIG,
                       '/usr/local/bin/firewall-refresh.py', '/workspace/.mcp.json', 'cd -- /workspace'):
            self.assertIn(needle, source, f'entrypoint.sh に固定パス {needle} がない')
        # 固定パスを試験用コピーへ置換する。trust override の "/workspace" は helper 側の固定値と一致させるため置換しない。
        source = (source.replace(FIXED_HELPER, str(HELPER)).replace(FIXED_CLI, str(self.codex))
                  .replace(FIXED_PROJECT_CONFIG, str(self.project_config))
                  .replace(FIXED_HOME, str(self.codex_home)).replace(FIXED_APPROVED, str(self.approved))
                  .replace(CLAUDE_APPROVED, str(self.claude_approved)).replace(SECRETS_MOUNT, str(self.fixture_mount_dir))
                  .replace(FIXED_BWRAP_DIR, str(self.bwrap_dir))
                  .replace('/usr/local/bin/firewall-refresh.py', str(self.bin / 'refresh'))
                  .replace('/workspace/.mcp.json', str(self.workspace / '.mcp.json'))
                  .replace('cd -- /workspace', 'cd -- ' + str(self.workspace)))
        self.entrypoint = self.root / 'entrypoint.sh'
        self.entrypoint.write_text(source)
        self.env = {'PATH': str(self.bin) + ':' + os.defpath, 'RECORD': str(self.record), 'HOME': str(self.root / 'home'),
                    'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}

    def write_project_config(self, text):
        self.config_text = text

    def run_entrypoint(self, agent=None, mode=None, read_only=None, tty_answer=None):
        self.state_path.write_text(json.dumps(self.state))
        if self.config_text is None:
            self.project_config.unlink(missing_ok=True)
        else:
            self.project_config.parent.mkdir(parents=True, exist_ok=True)
            self.project_config.write_text(self.config_text)
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
        self.approved.write_text(json.dumps({'protocol_version': 2, 'hash': protocol['hash']}) + '\n')
        return protocol


class ClaudePathTests(EntrypointCase):
    def test_default_and_explicit_claude_keep_existing_order_and_argv(self):
        (self.fixture_mount_dir / 'export' / 'MCP_TOKEN').write_text('tok\n')
        for agent in (None, 'claude'):
            with self.subTest(agent=agent):
                result = self.run_entrypoint(agent)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([r.split()[0] for r in self.records], ['sudo', 'refresh', 'claude', 'claude-env'])
                self.assertEqual(self.records[2], 'claude --permission-mode auto')
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
        self.assertEqual(set(protocol), {'protocol_version', 'hash', 'count', 'servers'})
        self.assertEqual(protocol['count'], 1)
        self.assertIn('firewall stdout noise', result.stderr)
        self.assertNotIn('firewall stdout noise', result.stdout)
        self.assertEqual([r.split()[0] for r in self.records], ['sudo', 'refresh'])
        self.assertEqual(self.kinds(), [])
        self.assertNotIn('claude-only', result.stderr)
        self.assertNotIn('TTY', result.stderr)

    def test_preflight_after_firewall_reads_project_config_without_cli(self):
        # protocol 2 の snapshot は Codex CLI も MCP command も実行しないので、秘密 export との順序は
        # 境界の要件ではない（不変条件 72 行）。firewall の後に走り、CLI を呼ばないことだけを確かめる。
        result = self.run_entrypoint('codex', 'preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.records[0].startswith('sudo'))
        self.assertEqual(self.kinds(), [])
        self.assertEqual(json.loads(result.stdout)['servers'][0]['name'], 'alpha')

    def test_missing_project_config_is_an_empty_definition(self):
        self.write_project_config(None)
        result = self.run_entrypoint('codex', 'preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['count'], 0)

    def test_preflight_failure_is_nonzero_with_empty_stdout(self):
        self.write_project_config(STDIO_ALPHA + HELPER_HTTP)
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
                self.assertEqual(self.kinds(), ['exec'])
                execd = self.codex_calls[-1]
                self.assertEqual(execd['args'], ['--sandbox', sandbox, '--ask-for-approval', 'on-request', '-c', TRUST_OVERRIDE])
                self.assertEqual([r.split()[0] for r in self.records], ['sudo', 'refresh'])
                self.assertIn('一致', result.stderr)

    def test_only_the_run_exec_calls_cli_with_fixed_home_cwd_and_override(self):
        self.approve_from_preflight()
        self.assertEqual(self.kinds(), [])
        (self.fixture_mount_dir / 'export' / 'MCP_TOKEN').write_text('tok\n')
        result = self.run_entrypoint('codex', 'run', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.kinds(), ['exec'])
        execd = self.codex_calls[-1]
        self.assertEqual(execd['env']['CODEX_HOME'], str(self.codex_home))
        self.assertEqual(execd['env']['HOME'], str(self.root / 'home'))
        self.assertEqual(execd['env']['MCP_TOKEN'], 'tok')
        self.assertEqual(execd['cwd'], str(self.workspace))
        self.assertEqual(execd['argv0'], str(self.codex))
        self.assertEqual(execd['args'][execd['args'].index('-c') + 1], TRUST_OVERRIDE)

    def test_codex_version_is_not_consulted(self):
        self.state['version'] = 'codex-cli 9.9.9\n'
        self.approve_from_preflight()
        result = self.run_entrypoint('codex', 'run', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.kinds(), ['exec'])

    def test_verify_failure_never_execs_native_cli(self):
        self.approve_from_preflight()
        cases = {
            'config changed': lambda: self.write_project_config(STDIO_ALPHA.replace('["server.py"]', '["server.py", "--evil"]')),
            'empty record': lambda: self.approved.write_text(''),
            'missing record': lambda: self.approved.unlink(),
            'wrong hash': lambda: self.approved.write_text(json.dumps({'protocol_version': 2, 'hash': '0' * 64})),
            'old record shape': lambda: self.approved.write_text(json.dumps({'protocol_version': 1, 'codex_version': '0.156.0', 'hash': '0' * 64})),
            'helper http appears': lambda: self.write_project_config(STDIO_ALPHA + HELPER_HTTP),
            'plugin enabled': lambda: self.write_project_config(STDIO_ALPHA + '[plugins."p@m"]\n'),
            'marketplace defined': lambda: self.write_project_config(STDIO_ALPHA + '[marketplaces.m]\nsource_type = "git"\n'),
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

    def test_missing_cli_has_no_fallback(self):
        self.approve_from_preflight()
        self.codex.unlink()
        for mode in ('preflight', 'run'):
            with self.subTest(mode=mode):
                result = self.run_entrypoint('codex', mode, '0')
                self.assertEqual(result.returncode, 1, mode)
                if mode == 'preflight':
                    self.assertEqual(result.stdout, '')
                self.assertNotIn('"hash"', result.stdout)
                self.assertNotIn('exec', self.kinds())
                self.assertFalse(any(r.startswith('claude') for r in self.records))
                self.assertIn('Codex', result.stderr)


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

    def gitconfig_mounts(self, overrides):
        """#149: 実 provider の config で ~/.gitconfig の bind を取り出す（短縮形・長形式のどちらでも）。"""
        podman = shutil.which('podman')
        if podman is None:
            self.skipTest('podman が無いため compose の実解決を確認できない')
        home = Path(self.env['HOME'])
        (home / '.claude').mkdir(parents=True, exist_ok=True)
        (home / '.claude.json').touch()
        env = {'PATH': os.environ['PATH'], 'HOME': self.env['HOME'], 'BUILD_CONTEXT_DIR': str(self.root),
               'CONTEXT': str(self.workspace), 'CLAUDE_CONTAINER_DIR': str(ROOT)}
        env.update(overrides)
        result = subprocess.run([podman, 'compose', '-f', str(ROOT / 'compose.yml'), '--env-file', '/dev/null', 'config'],
                                env=env, cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        mounts = re.findall(r'^\s*-\s*([^\s]+?):/home/node/\.gitconfig:([^\s]+)\s*$', result.stdout, re.M)
        self.assertEqual(len(mounts), 1, result.stdout)
        return mounts[0]

    def test_gitconfig_bind_source_comes_from_launcher_variable(self):
        source = self.root / 'bundled.gitconfig'
        source.touch()
        other = self.root / 'host.gitconfig'
        other.touch()
        self.assertEqual(self.gitconfig_mounts({'C3C_GITCONFIG_SOURCE': str(source), 'GITCONFIG_FILE': str(other)}),
                         (str(source), 'ro'))
        # launcher を通さない展開（GITCONFIG_FILE だけ）は既定値のまま。bind 元は launcher だけが決める。
        self.assertEqual(self.gitconfig_mounts({'GITCONFIG_FILE': str(other)}), ('/dev/null', 'ro'))

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
        (self.fixture_mount_dir / 'export' / 'CODEX_HOME').write_text(str(other_home) + '\n')
        (self.fixture_mount_dir / 'export' / 'HOME').write_text('/tmp/evil-home\n')
        (self.fixture_mount_dir / 'export' / 'PATH').write_text('/tmp/evil-bin\n')
        (self.fixture_mount_dir / 'export' / 'MCP_TOKEN').write_text('tok\n')
        self.approve_from_preflight()
        self.assertEqual(self.kinds(), [], 'preflight は CLI を呼ばない')
        for mode in ('preflight', 'run'):
            with self.subTest(mode=mode):
                result = self.run_entrypoint('codex', mode, '0')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.kinds(), [] if mode == 'preflight' else ['exec'])
                for call in self.codex_calls:
                    self.assertEqual(call['env']['CODEX_HOME'], str(self.codex_home))
                    self.assertEqual(call['env']['HOME'], str(self.root / 'home'))
                    self.assertEqual(call['env']['PATH'], str(self.bwrap_dir) + ':' + self.env['PATH'])
                    self.assertEqual(call['env']['MCP_TOKEN'], 'tok')
                for name in ('CODEX_HOME', 'HOME', 'PATH'):
                    self.assertIn(f"'{name}' は既に環境変数に設定されています", result.stderr)
                self.assertEqual(list(other_home.iterdir()), [])


class BundledBwrapPathTests(EntrypointCase):
    """#145: Codex 経路だけ同梱 bubblewrap の専用ディレクトリを PATH の先頭へ一度加え、全段へ継承する。"""

    def codex_path(self):
        return str(self.bwrap_dir) + ':' + self.env['PATH']

    def test_preflight_and_run_share_prepended_path(self):
        self.approve_from_preflight()
        self.assertEqual(self.kinds(), [])
        for read_only in ('0', '1'):
            with self.subTest(read_only=read_only):
                result = self.run_entrypoint('codex', 'run', read_only)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.kinds(), ['exec'])
                for call in self.codex_calls:
                    self.assertEqual(call['env']['PATH'], self.codex_path())

    def test_claude_path_is_unchanged_and_does_not_need_bundled_bwrap(self):
        for mutate in (lambda: None, lambda: (self.bwrap_dir / 'bwrap').unlink()):
            with self.subTest(mutate=mutate):
                mutate()
                result = self.run_entrypoint('claude')
                self.assertEqual(result.returncode, 0, result.stderr)
                env_line = next(r for r in self.records if r.startswith('claude-env'))
                self.assertTrue(env_line.endswith(' PATH=' + self.env['PATH']), env_line)

    def test_missing_dangling_or_non_executable_link_fails_before_any_codex_call(self):
        cases = {
            'missing link': lambda: (self.bwrap_dir / 'bwrap').unlink(),
            'dangling link': lambda: self.bwrap_real.unlink(),
            'non-executable': lambda: self.bwrap_real.chmod(0o644),
        }
        for label, mutate in cases.items():
            for mode in ('preflight', 'run'):
                with self.subTest(case=label, mode=mode):
                    self.setUp()
                    self.approve_from_preflight()
                    mutate()
                    result = self.run_entrypoint('codex', mode, '0')
                    self.assertEqual(result.returncode, 1, label)
                    self.assertEqual(self.codex_calls, [], label)
                    self.assertIn('ERROR: Codex 同梱の bubblewrap がありません。-b で再ビルドしてください。', result.stderr)
                    if mode == 'preflight':
                        self.assertEqual(result.stdout, '')
                    self.assertFalse(any(r.startswith('claude') for r in self.records))

    def test_opt_out_without_cli_keeps_cli_error(self):
        self.codex.unlink()
        (self.bwrap_dir / 'bwrap').unlink()
        result = self.run_entrypoint('codex', 'run', '0')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Codex CLI が導入されていません', result.stderr)
        self.assertNotIn('bubblewrap', result.stderr)


if __name__ == '__main__':
    unittest.main()
