#!/usr/bin/env python3
"""Codex 起動時 MCP 審査 helper（protocol 2、#150）の回帰試験。

helper は Codex CLI を実行せず、`--config` で渡したリポジトリ同梱の `.codex/config.toml` を tomllib で読む。
enabled stdio の実行定義だけを canonical hash にまとめ、project 設定での plugin 有効化は拒否する。
ここで固定する protocol / 承認記録の形は launcher（c3c）と entrypoint が消費する。
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'codex-mcp-audit.py'
ENV_SENTINEL = 'hunter2-env-value'
HEADER_SENTINEL = 'Bearer sekrit-header-value'
# codex-cli 0.156.0 の RawMcpServerConfig の key（計画の Global Constraints と同じ 28 個）。
KEY_NAMES = ('command', 'args', 'env', 'env_vars', 'cwd', 'http_headers', 'env_http_headers', 'url',
             'bearer_token', 'bearer_token_env_var', 'http_headers_helper', 'environment_id', 'auth',
             'startup_timeout_sec', 'startup_timeout_ms', 'tool_timeout_sec', 'enabled', 'required',
             'supports_parallel_tool_calls', 'omit_tools_from', 'default_tools_approval_mode', 'enabled_tools',
             'disabled_tools', 'scopes', 'oauth', 'oauth_resource', 'name', 'tools')

STDIO_A = '''
[mcp_servers.alpha]
command = "node"
args = ["server.js", "--port", "1"]
cwd = "/workspace"
env = { TOKEN = "%s" }
env_vars = ["HOME", { name = "PATH", source = "local" }]
''' % ENV_SENTINEL


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / 'workspace' / '.codex' / 'config.toml'
        self.config.parent.mkdir(parents=True)
        self.record = self.root / 'record.json'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        self.config.write_text(text, encoding='utf-8')

    def run_helper(self, *args, config=None):
        return subprocess.run([sys.executable, '-I', str(HELPER), '--config', str(config or self.config), *args],
                              capture_output=True, text=True, timeout=30)

    def snapshot(self, text=None):
        if text is not None:
            self.write(text)
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def rejected(self, text, needle):
        self.write(text)
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout, '')
        self.assertIn(needle, result.stderr)
        return result


class SnapshotTests(AuditCase):
    def test_missing_config_is_an_explicit_empty_result(self):
        self.config.unlink(missing_ok=True)
        doc = self.snapshot()
        self.assertEqual(doc['count'], 0)
        self.assertEqual(doc['servers'], [])
        self.assertEqual(set(doc), {'protocol_version', 'hash', 'count', 'servers'})
        self.assertEqual(doc['protocol_version'], 2)

    def test_empty_file_and_missing_file_have_the_same_hash(self):
        self.config.unlink(missing_ok=True)
        missing = self.snapshot()['hash']
        self.assertEqual(self.snapshot('')['hash'], missing)

    def test_fixed_vector_hash_matches_canonical_document(self):
        doc = self.snapshot(STDIO_A)
        servers = [{'name': 'alpha', 'transport': {
            'type': 'stdio', 'command': 'node', 'args': ['server.js', '--port', '1'],
            'env': {'TOKEN': ENV_SENTINEL}, 'env_vars': ['HOME', {'name': 'PATH', 'source': 'local'}],
            'cwd': '/workspace', 'environment_id': None}}]
        text = json.dumps({'protocol_version': 2, 'servers': servers}, sort_keys=True,
                          separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(doc['hash'], hashlib.sha256(text.encode('utf-8')).hexdigest())
        self.assertEqual(doc['count'], 1)
        self.assertEqual(doc['servers'], [{'name': 'alpha', 'command': 'node', 'args': ['server.js', '--port', '1'],
                                           'cwd': '/workspace', 'env_keys': ['TOKEN'],
                                           'env_vars': ['HOME', {'name': 'PATH', 'source': 'local'}],
                                           'environment_id': None}])

    def test_hash_changes_for_each_execution_field(self):
        base = self.snapshot(STDIO_A)['hash']
        for old, new in (('command = "node"', 'command = "deno"'),
                         ('"--port", "1"', '"--port", "2"'),
                         ('cwd = "/workspace"', 'cwd = "/tmp"'),
                         (ENV_SENTINEL, 'other-value'),
                         ('"HOME", ', '"USER", ')):
            with self.subTest(old=old):
                self.assertNotEqual(self.snapshot(STDIO_A.replace(old, new))['hash'], base)
        self.assertNotEqual(self.snapshot(STDIO_A + 'environment_id = "remote-1"\n')['hash'], base)

    def test_diagnostic_keys_do_not_change_hash(self):
        base = self.snapshot(STDIO_A)['hash']
        extra = STDIO_A + 'startup_timeout_sec = 30\ntool_timeout_sec = 60\nenabled_tools = ["a"]\nrequired = true\n'
        self.assertEqual(self.snapshot(extra)['hash'], base)

    def test_server_order_is_irrelevant_and_array_order_is_significant(self):
        two = STDIO_A + '\n[mcp_servers.beta]\ncommand = "python3"\n'
        swapped = '[mcp_servers.beta]\ncommand = "python3"\n' + STDIO_A
        self.assertEqual(self.snapshot(two)['hash'], self.snapshot(swapped)['hash'])
        self.assertEqual([s['name'] for s in self.snapshot(two)['servers']], ['alpha', 'beta'])
        self.assertNotEqual(self.snapshot(STDIO_A.replace('"--port", "1"', '"1", "--port"'))['hash'],
                            self.snapshot(STDIO_A)['hash'])

    def test_missing_optional_fields_normalize_to_defaults(self):
        minimal = self.snapshot('[mcp_servers.m]\ncommand = "x"\n')
        explicit = self.snapshot('[mcp_servers.m]\ncommand = "x"\nargs = []\nenv_vars = []\nenv = {}\n')
        self.assertEqual(minimal['hash'], explicit['hash'])

    def test_disabled_servers_are_excluded_after_key_validation(self):
        empty = self.snapshot('')['hash']
        self.assertEqual(self.snapshot(STDIO_A + 'enabled = false\n')['hash'], empty)
        self.rejected(STDIO_A + 'enabled = false\nbogus = 1\n', 'bogus')

    def test_helperless_http_is_excluded_and_url_change_does_not_change_hash(self):
        empty = self.snapshot('')['hash']
        http = '[mcp_servers.web]\nurl = "https://a.example/mcp"\nbearer_token_env_var = "T"\n'
        self.assertEqual(self.snapshot(http)['hash'], empty)
        self.assertEqual(self.snapshot(http.replace('a.example', 'b.example'))['hash'], empty)

    def test_plugins_explicitly_disabled_are_allowed(self):
        doc = self.snapshot('[plugins."p@m"]\nenabled = false\n')
        self.assertEqual(doc['count'], 0)

    def test_output_hides_env_values_and_http_headers(self):
        text = STDIO_A + ('\n[mcp_servers.web]\nurl = "https://a.example/mcp"\n'
                          'http_headers = { Authorization = "%s" }\n' % HEADER_SENTINEL)
        self.write(text)
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(ENV_SENTINEL, result.stdout + result.stderr)
        self.assertNotIn(HEADER_SENTINEL, result.stdout + result.stderr)

    def test_display_strips_control_characters_but_hash_keeps_them(self):
        clean = self.snapshot('[mcp_servers.m]\ncommand = "ab"\n')
        dirty = self.snapshot('[mcp_servers.m]\ncommand = "a\\u001bb"\n')
        self.assertEqual(dirty['servers'][0]['command'], 'ab')
        self.assertNotEqual(dirty['hash'], clean['hash'])


class RejectionTests(AuditCase):
    def test_enabled_plugins_are_rejected_with_names(self):
        for text in ('[plugins."probe@mkt"]\nenabled = true\n',
                     '[plugins."probe@mkt"]\n',
                     '[plugins."probe@mkt"]\nenabled = "false"\n',
                     'plugins = { "probe@mkt" = 1 }\n'):
            with self.subTest(text=text):
                self.rejected(text, 'probe@mkt')

    def test_plugins_must_be_a_table(self):
        self.rejected('plugins = ["x"]\n', 'plugins')

    def test_marketplaces_are_rejected_with_names(self):
        for text in ('[marketplaces.evil]\nsource_type = "git"\nsource = "https://a.example/r.git"\n',
                     '[marketplaces.evil]\nsource_type = "local"\nsource = "./plugins"\n',
                     'marketplaces = { evil = 1 }\n'):
            with self.subTest(text=text):
                self.rejected(text, 'evil')
        self.rejected('marketplaces = 1\n', 'marketplaces')
        self.assertEqual(self.snapshot('[marketplaces]\n')['count'], 0)

    def test_every_allowed_key_rejects_wrong_type_even_when_disabled(self):
        bad = {'command': '1', 'args': '"b"', 'env': 'false', 'env_vars': '[1]', 'cwd': '1',
               'http_headers': '{ K = 1 }', 'env_http_headers': '"x"', 'url': '1', 'bearer_token': '1',
               'bearer_token_env_var': '1', 'http_headers_helper': '1', 'environment_id': '1',
               'auth': '"other"', 'startup_timeout_sec': '"30"', 'startup_timeout_ms': '-1',
               'tool_timeout_sec': 'true', 'required': '"yes"', 'supports_parallel_tool_calls': '1',
               'omit_tools_from': '"x"', 'default_tools_approval_mode': '1', 'enabled_tools': '[1]',
               'disabled_tools': '"x"', 'scopes': '[true]', 'oauth': '"x"', 'oauth_resource': '1',
               'name': '1', 'tools': '{ t = 1 }'}
        for key, value in bad.items():
            with self.subTest(key=key):
                self.rejected(f'[mcp_servers.x]\nenabled = false\n{key} = {value}\n', key)

    def test_wrong_types_are_rejected_in_enabled_http_entries(self):
        for key, value in (('args', '[1]'), ('env', 'false'), ('required', '"yes"'), ('scopes', '"x"')):
            with self.subTest(key=key):
                self.rejected(f'[mcp_servers.web]\nurl = "https://a.example"\n{key} = {value}\n', key)

    def test_nested_enum_and_range_types_are_rejected_in_disabled_and_http_entries(self):
        # RawMcpServerConfig の入れ子（McpServerOAuthConfig・McpServerToolConfig）、enum（AppToolApproval・
        # ToolExposureSurface）、整数範囲（u16・u64・NonZeroUsize）、非負の有限秒まで検査する。
        bad = {'oauth': ('{ callback_port = "wrong" }', '{ callback_port = 65536 }', '{ callback_port = -1 }',
                         '{ client_id = 1 }', '{ extra = "x" }'),
               'tools': ('{ t = { approval_mode = 1 } }', '{ t = { approval_mode = "wrong" } }',
                         '{ t = { output_token_limit = 0 } }', '{ t = { extra = 1 } }'),
               'default_tools_approval_mode': ('"wrong"',),
               'omit_tools_from': ('["wrong"]',),
               'startup_timeout_ms': ('18446744073709551616',),
               'startup_timeout_sec': ('-1', 'nan', 'inf', '1e100', '18446744073709551616.0', '1' + '0' * 400),
               'tool_timeout_sec': ('-1.5', 'nan', '-inf', '1e100', '18446744073709551616.0', '1' + '0' * 400)}
        for key, values in bad.items():
            for value in values:
                for head in ('[mcp_servers.x]\nenabled = false\ncommand = "a"\n',
                             '[mcp_servers.x]\nurl = "https://a.example"\n'):
                    with self.subTest(key=key, value=value, head=head[15:30]):
                        self.rejected(f'{head}{key} = {value}\n', key)

    def test_seconds_boundary_values_are_accepted_in_disabled_and_http_entries(self):
        # Duration::try_from_secs_f64 の境界（rustc 1.95 で実測）: 2^64 直前の f64・i64 最大・-0.0・最小の非正規数は Ok。
        for value in ('18446744073709549568.0', '9223372036854775807', '-0.0', '5e-324'):
            for key in ('startup_timeout_sec', 'tool_timeout_sec'):
                for head in ('[mcp_servers.x]\nenabled = false\ncommand = "a"\n',
                             '[mcp_servers.x]\nurl = "https://a.example"\n'):
                    with self.subTest(key=key, value=value, head=head[15:30]):
                        self.assertEqual(self.snapshot(f'{head}{key} = {value}\n')['count'], 0)

    def test_valid_values_for_all_keys_are_accepted_in_a_disabled_entry(self):
        text = ('[mcp_servers.x]\nenabled = false\ncommand = "a"\nargs = ["b"]\nenv = { K = "v" }\n'
                'env_vars = ["A", { name = "B", source = "remote" }]\ncwd = "/w"\nhttp_headers = { H = "v" }\n'
                'env_http_headers = { H = "E" }\nurl = "https://a.example"\nbearer_token = "t"\n'
                'bearer_token_env_var = "T"\nhttp_headers_helper = "/bin/x"\nenvironment_id = "local"\n'
                'auth = "chatgpt"\nstartup_timeout_sec = 1.5\nstartup_timeout_ms = 10\ntool_timeout_sec = 3\n'
                'required = true\nsupports_parallel_tool_calls = false\nomit_tools_from = ["code_mode", "direct"]\n'
                'default_tools_approval_mode = "auto"\nenabled_tools = ["a"]\ndisabled_tools = ["b"]\n'
                'scopes = ["s"]\noauth = { client_id = "c", callback_url = "u", callback_port = 65535, '
                'authorization_server_issuer = "i" }\noauth_resource = "r"\nname = "n"\n'
                'tools = { t = { approval_mode = "writes", output_token_limit = 1 } }\n')
        self.assertEqual(len(KEY_NAMES), 28)
        for key in KEY_NAMES:
            self.assertIn(f'\n{key} = ', text)
        self.assertEqual(self.snapshot(text)['count'], 0)

    def test_http_headers_helper_is_rejected_for_any_enabled_entry(self):
        self.rejected('[mcp_servers.web]\nurl = "https://a.example"\nhttp_headers_helper = "/bin/x"\n',
                      'http_headers_helper')
        self.rejected('[mcp_servers.s]\ncommand = "x"\nhttp_headers_helper = "/bin/x"\n', 'http_headers_helper')

    def test_unknown_key_is_rejected(self):
        self.rejected(STDIO_A + 'future_exec = "/bin/sh"\n', 'future_exec')

    def test_command_and_url_together_or_neither_are_rejected(self):
        self.rejected('[mcp_servers.x]\ncommand = "a"\nurl = "https://a.example"\n', 'transport')
        self.rejected('[mcp_servers.x]\nargs = ["a"]\n', 'transport')

    def test_wrong_types_are_rejected(self):
        for text in ('[mcp_servers.x]\ncommand = 1\n',
                     '[mcp_servers.x]\ncommand = "a"\nargs = "b"\n',
                     '[mcp_servers.x]\ncommand = "a"\nargs = [1]\n',
                     '[mcp_servers.x]\ncommand = "a"\nenv = { K = 1 }\n',
                     '[mcp_servers.x]\ncommand = "a"\nenv_vars = [1]\n',
                     '[mcp_servers.x]\ncommand = "a"\nenv_vars = [{ name = "A", source = "other" }]\n',
                     '[mcp_servers.x]\ncommand = "a"\nenv_vars = [{ name = "A", extra = 1 }]\n',
                     '[mcp_servers.x]\ncommand = "a"\ncwd = 1\n',
                     '[mcp_servers.x]\ncommand = "a"\nenvironment_id = 1\n',
                     '[mcp_servers.x]\ncommand = "a"\nenabled = "yes"\n',
                     '[mcp_servers.x]\nurl = 1\n',
                     'mcp_servers = 1\n',
                     'mcp_servers = { x = 1 }\n'):
            with self.subTest(text=text):
                self.rejected(text, 'ERROR:')

    def test_broken_toml_and_duplicate_keys_are_rejected(self):
        self.rejected('[mcp_servers.x\n', 'TOML')
        self.rejected('[mcp_servers.x]\ncommand = "a"\ncommand = "b"\n', 'TOML')

    def test_non_utf8_is_rejected(self):
        self.config.write_bytes(b'[mcp_servers.x]\ncommand = "\xff"\n')
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 1)
        self.assertIn('UTF-8', result.stderr)

    def test_rejection_message_strips_control_characters_from_server_name(self):
        result = self.rejected('[mcp_servers."a\\u001b[31mb"]\ncommand = 1\n', 'ERROR:')
        self.assertNotIn('\x1b', result.stderr)

    def test_non_regular_or_unreadable_config_is_rejected(self):
        self.config.unlink(missing_ok=True)
        self.config.mkdir()
        self.assertEqual(self.run_helper('snapshot').returncode, 1)
        self.config.rmdir()
        os.mkfifo(self.config)
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 1)
        self.assertIn('通常ファイル', result.stderr)
        self.config.unlink()
        if os.geteuid() != 0:
            self.write('')
            self.config.chmod(0)
            self.assertEqual(self.run_helper('snapshot').returncode, 1)
            self.config.chmod(0o600)

    def test_fifo_is_rejected_without_blocking_and_without_path_based_stat(self):
        # stat と open の間に FIFO へ差し替えられても止まらないことを、構造で固定する:
        # パスへの stat（os.stat / os.path.isfile）を使わず、O_NONBLOCK で開いた fd を fstat する。
        spec = importlib.util.spec_from_file_location('codex_mcp_audit_under_test', HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.config.unlink(missing_ok=True)
        os.mkfifo(self.config)

        def blocked(signum, frame):
            raise TimeoutError('load_config が FIFO で止まった')

        previous = signal.signal(signal.SIGALRM, blocked)
        signal.alarm(5)
        try:
            with mock.patch.object(os, 'stat', side_effect=AssertionError('パスへの stat を使っている')):
                with self.assertRaises(module.AuditError) as ctx:
                    module.load_config(str(self.config))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
        self.assertIn('通常ファイル', str(ctx.exception))

    def test_symlink_to_regular_file_is_followed_and_dangling_is_absent(self):
        target = self.root / 'real.toml'
        target.write_text(STDIO_A)
        self.config.unlink(missing_ok=True)
        self.config.symlink_to(target)
        self.assertEqual(self.snapshot()['count'], 1)
        target.unlink()
        self.assertEqual(self.snapshot()['count'], 0)

    def test_relative_config_path_is_rejected(self):
        result = subprocess.run([sys.executable, '-I', str(HELPER), '--config', 'rel.toml', 'snapshot'],
                                capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn('絶対パス', result.stderr)

    def test_missing_tomllib_is_reported_as_audit_error(self):
        # tomllib の無い python3（3.10 以前のベースイメージ）を import 失敗で模す。
        shim = self.root / 'shim'
        shim.mkdir()
        (shim / 'tomllib.py').write_text('raise ImportError("no tomllib")\n')
        result = subprocess.run([sys.executable, str(HELPER), '--config', str(self.config), 'snapshot'],
                                capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': str(shim)})
        self.assertEqual(result.returncode, 1)
        self.assertIn('tomllib', result.stderr)
        self.assertIn('3.11', result.stderr)


class VerifyTests(AuditCase):
    def write_record(self, hash_value, protocol=2, extra=None):
        doc = {'protocol_version': protocol, 'hash': hash_value}
        doc.update(extra or {})
        self.record.write_text(json.dumps(doc) + '\n')

    def test_verify_accepts_matching_record_and_rejects_changed_definition(self):
        doc = self.snapshot(STDIO_A)
        self.write_record(doc['hash'])
        ok = self.run_helper('verify', str(self.record))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.write(STDIO_A.replace('node', 'deno'))
        changed = self.run_helper('verify', str(self.record))
        self.assertEqual(changed.returncode, 1)
        self.assertIn('一致しません', changed.stderr)

    def test_verify_rejects_missing_malformed_and_foreign_records(self):
        doc = self.snapshot(STDIO_A)
        cases = {
            'missing': None,
            'empty': '',
            'protocol 1': json.dumps({'protocol_version': 1, 'hash': doc['hash']}),
            'old shape': json.dumps({'protocol_version': 2, 'codex_version': '0.156.0', 'hash': doc['hash']}),
            'bool protocol': json.dumps({'protocol_version': True, 'hash': doc['hash']}),
            'upper hash': json.dumps({'protocol_version': 2, 'hash': doc['hash'].upper()}),
            'duplicate key': '{"protocol_version":2,"hash":"%s","hash":"%s"}' % ('0' * 64, doc['hash']),
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                self.record.unlink(missing_ok=True)
                if content is not None:
                    self.record.write_text(content)
                self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 1)

    def test_verify_fails_when_config_becomes_invalid(self):
        doc = self.snapshot(STDIO_A)
        self.write_record(doc['hash'])
        self.write('[plugins."p@m"]\n')
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 1)


if __name__ == '__main__':
    unittest.main()
