#!/usr/bin/env python3
"""Codex 起動時 MCP 審査 helper の回帰試験。native 一覧 fixture と一時ディレクトリ内の dummy CLI だけで検証する。

実 codex や実認証 home は一切起動・参照しない。helper は `--codex <絶対パス>` で渡した CLI 実体に
`--version` と `mcp list --json` を問い合わせ、enabled stdio の実行定義だけを canonical hash に
まとめる。ここで固定する protocol / 承認記録の形は launcher（Task 2）と entrypoint（Task 3）が消費する。
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'codex-mcp-audit.py'
SUPPORTED = '0.156.0'
VERSION_LINE = 'codex-cli ' + SUPPORTED
TRUST_OVERRIDE = 'projects={"/workspace"={trust_level="trusted"}}'
SECRET_ENV = 'hunter2-env-value'
SECRET_HEADER = 'Bearer sekrit-header-value'
SECRET_STDERR = 'native-stderr-token-xyz'

# 対象版 codex-cli 0.156.0 の `mcp list --json` を模す dummy。状態ファイルのパスは script に焼き込む。
CODEX = '''#!/usr/bin/env python3
import json, os, subprocess, sys, time
state_path = %r
root = os.path.dirname(state_path)
with open(state_path) as handle:
    state = json.load(handle)
args = sys.argv[1:]
with open(os.path.join(root, 'calls'), 'a') as out:
    out.write(json.dumps({'args': args, 'cwd': os.getcwd(), 'pid': os.getpid(), 'pgid': os.getpgid(0),
                          'codex_home': os.environ.get('CODEX_HOME')}) + '\\n')
if args == ['--version']:
    spec = state.get('version', {})
    sys.stdout.write(spec.get('stdout', %r))
    sys.stdout.flush()
    time.sleep(spec.get('sleep', 0))
    sys.exit(spec.get('code', 0))
if 'mcp' in args and 'list' in args and '--json' in args:
    spec = state.get('list', {})
    if spec.get('spawn'):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
        with open(os.path.join(root, 'grandchild'), 'w') as out:
            out.write(str(child.pid))
    sys.stdout.write(spec.get('stdout', '[]\\n'))
    sys.stdout.flush()
    sys.stderr.write(spec.get('stderr', ''))
    sys.stderr.flush()
    time.sleep(spec.get('sleep', 0))
    sys.exit(spec.get('code', 0))
sys.stderr.write('想定外の codex 呼び出し: ' + repr(args) + '\\n')
sys.exit(125)
'''

# 期限の短縮は production の flag/env ではなく module 定数の差替えで行う（実子プロセスは本物）。
BOOTSTRAP = '''import importlib.util, sys
spec = importlib.util.spec_from_file_location('codex_mcp_audit', sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for item in sys.argv[2].split(','):
    name, value = item.split('=')
    setattr(mod, name, float(value))
sys.exit(mod.main(sys.argv[3:]))
'''


def stdio(name, command='node', args=('server.js',), env=None, env_vars=('HOME',), cwd='/workspace',
          enabled=True, auth='unsupported'):
    return {'name': name, 'enabled': enabled, 'disabled_reason': None if enabled else 'disabled in config',
            'transport': {'type': 'stdio', 'command': command, 'args': list(args), 'env': env,
                          'env_vars': list(env_vars) if env_vars is not None else None, 'cwd': cwd},
            'startup_timeout_sec': None, 'tool_timeout_sec': None, 'auth_status': auth}


def http(name, url='https://mcp.example/mcp', helper=None, headers=None, enabled=True):
    return {'name': name, 'enabled': enabled, 'disabled_reason': None if enabled else 'disabled in config',
            'transport': {'type': 'streamable_http', 'url': url, 'bearer_token_env_var': None,
                          'http_headers': headers, 'env_http_headers': None, 'http_headers_helper': helper},
            'startup_timeout_sec': None, 'tool_timeout_sec': None, 'auth_status': 'unsupported'}


def canonical_hash(entries):
    """計画の hash 契約を helper と独立に計算する期待値。enabled stdio だけを name 順に並べる。"""
    servers = sorted(({'name': e['name'],
                       'transport': {k: e['transport'][k] for k in ('type', 'command', 'args', 'env', 'env_vars', 'cwd')}}
                      for e in entries if e['enabled'] and e['transport']['type'] == 'stdio'),
                     key=lambda s: s['name'])
    doc = {'protocol_version': 1, 'codex_version': SUPPORTED, 'servers': servers}
    text = json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def alive(pid):
    try:
        status = Path(f'/proc/{pid}/status').read_text()
    except OSError:
        return False
    return not re.search(r'^State:\s+Z', status, re.M)


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(HELPER.is_file(), 'codex-mcp-audit.py が未実装')
        self.temp = tempfile.TemporaryDirectory(prefix='cc-codex-audit-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.codex_home = self.root / 'codex-home'
        self.codex_home.mkdir()
        self.state_path = self.root / 'state.json'
        self.codex = self.root / 'bin' / 'codex'
        self.codex.parent.mkdir()
        self.codex.write_text(CODEX % (str(self.state_path), VERSION_LINE + '\n'))
        self.codex.chmod(0o755)
        self.state = {}
        self.env = {'PATH': os.defpath, 'HOME': str(self.root / 'home'), 'CODEX_HOME': str(self.codex_home),
                    'TMPDIR': str(self.scratch), 'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
        self.addCleanup(self.kill_grandchild)

    def kill_grandchild(self):
        marker = self.root / 'grandchild'
        if marker.exists():
            try:
                os.kill(int(marker.read_text()), 9)
            except ProcessLookupError:
                pass

    def listing(self, entries):
        self.state.setdefault('list', {})['stdout'] = json.dumps(entries) + '\n'

    def run_helper(self, *argv, codex=None, constants=None):
        self.state_path.write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        codex_args = ['--codex', str(self.codex if codex is None else codex)]
        if constants:
            patched = ','.join(f'{k}={v}' for k, v in constants.items())
            command = [sys.executable, '-I', '-c', BOOTSTRAP, str(HELPER), patched, *codex_args, *argv]
        else:
            command = [sys.executable, '-I', str(HELPER), *codex_args, *argv]
        result = subprocess.run(command, cwd=self.root, env=self.env, capture_output=True, text=True, timeout=60)
        self.calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        return result

    def list_calls(self):
        return [c for c in self.calls if 'list' in c['args']]

    def snapshot(self, entries=None):
        if entries is not None:
            self.listing(entries)
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        protocol = json.loads(result.stdout)  # 余分な文字があれば ValueError
        self.assertIsInstance(protocol, dict)
        return protocol

    def assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)


class HashTests(AuditCase):
    def test_hash_is_stable_across_key_order_server_order_and_auth_status(self):
        a = stdio('alpha', env={'API_KEY': SECRET_ENV})
        b = stdio('beta', command='python3', args=('-m', 'srv'))
        base = self.snapshot([a, b])
        reordered = [dict(reversed(list(b.items()))), dict(reversed(list(a.items())))]
        reordered[1]['transport'] = dict(reversed(list(a['transport'].items())))
        reordered[1]['auth_status'] = 'authenticated'
        reordered[0]['startup_timeout_sec'] = 30
        reordered[0]['tool_timeout_sec'] = 120
        same = self.snapshot(reordered)
        self.assertEqual(same['hash'], base['hash'])
        self.assertEqual([s['name'] for s in same['servers']], ['alpha', 'beta'])

    def test_hash_changes_for_each_execution_field(self):
        base = stdio('alpha', env={'API_KEY': 'v1'}, env_vars=('HOME',), cwd='/workspace')
        variants = {
            'command': stdio('alpha', command='npx', env={'API_KEY': 'v1'}),
            'args': stdio('alpha', args=('other.js',), env={'API_KEY': 'v1'}),
            'env_value': stdio('alpha', env={'API_KEY': 'v2'}),
            'env_key': stdio('alpha', env={'OTHER_KEY': 'v1'}),
            'env_absent': stdio('alpha', env=None),
            'env_vars': stdio('alpha', env={'API_KEY': 'v1'}, env_vars=('HOME', 'PATH')),
            'cwd': stdio('alpha', env={'API_KEY': 'v1'}, cwd='/workspace/sub'),
            'name': stdio('alpha2', env={'API_KEY': 'v1'}),
        }
        hashes = {'base': self.snapshot([base])['hash']}
        for label, entry in variants.items():
            with self.subTest(field=label):
                hashes[label] = self.snapshot([entry])['hash']
                self.assertNotEqual(hashes[label], hashes['base'])
        self.assertEqual(len(set(hashes.values())), len(hashes))

    def test_array_order_is_significant_for_args_and_env_vars(self):
        one = self.snapshot([stdio('alpha', args=('a', 'b'), env_vars=('X', 'Y'))])['hash']
        self.assertNotEqual(self.snapshot([stdio('alpha', args=('b', 'a'), env_vars=('X', 'Y'))])['hash'], one)
        self.assertNotEqual(self.snapshot([stdio('alpha', args=('a', 'b'), env_vars=('Y', 'X'))])['hash'], one)

    def test_disabled_servers_are_excluded_and_enabling_changes_hash(self):
        only_alpha = self.snapshot([stdio('alpha')])
        with_disabled = self.snapshot([stdio('alpha'), stdio('beta', command='evil', enabled=False)])
        self.assertEqual(with_disabled['hash'], only_alpha['hash'])
        self.assertEqual(with_disabled['count'], 1)
        self.assertEqual([s['name'] for s in with_disabled['servers']], ['alpha'])
        enabled = self.snapshot([stdio('alpha'), stdio('beta', command='evil')])
        self.assertNotEqual(enabled['hash'], only_alpha['hash'])
        self.assertEqual(enabled['count'], 2)

    def test_helperless_http_is_excluded_and_url_change_does_not_change_hash(self):
        only_alpha = self.snapshot([stdio('alpha')])
        remote = self.snapshot([stdio('alpha'), http('remote', url='https://one.example/mcp')])
        self.assertEqual(remote['hash'], only_alpha['hash'])
        self.assertEqual(remote['count'], 1)
        moved = self.snapshot([stdio('alpha'), http('remote', url='https://two.example/mcp')])
        self.assertEqual(moved['hash'], only_alpha['hash'])

    def test_fixed_vector_hash_matches_canonical_document(self):
        # env_vars は対象版で Vec<McpServerEnvVar>（null にならない）。空は [] が正当な fixture。
        entries = [stdio('beta', command='python3', args=('-m', 'srv', '--flag'), env={'B': '2', 'A': '1'},
                         env_vars=('PATH', {'name': 'TOKEN', 'source': 'local'}), cwd=None),
                   stdio('alpha', env=None, env_vars=(), cwd='/workspace/日本語'),
                   stdio('gamma', command='evil', enabled=False),
                   http('remote')]
        protocol = self.snapshot(entries)
        self.assertEqual(protocol['hash'], canonical_hash(entries))
        self.assertEqual(protocol['protocol_version'], 1)
        self.assertEqual(protocol['codex_version'], SUPPORTED)
        self.assertEqual(protocol['count'], 2)

    def test_empty_list_is_explicit_valid_result_with_distinct_hash(self):
        empty = self.snapshot([])
        self.assertEqual(empty['count'], 0)
        self.assertEqual(empty['servers'], [])
        self.assertEqual(empty['hash'], canonical_hash([]))
        self.assertNotEqual(empty['hash'], self.snapshot([stdio('alpha')])['hash'])
        disabled_only = self.snapshot([stdio('alpha', enabled=False), http('remote')])
        self.assertEqual(disabled_only['hash'], empty['hash'])
        self.assertEqual(disabled_only['count'], 0)

    def test_protocol_stdout_is_exactly_one_json_document_with_display_fields(self):
        self.state['list'] = {'stderr': 'INFO: native noise line\n'}
        protocol = self.snapshot([stdio('alpha', args=('--port', '4000'), env={'API_KEY': SECRET_ENV},
                                        env_vars=('HOME',), cwd='/workspace')])
        self.assertEqual(set(protocol), {'protocol_version', 'codex_version', 'hash', 'count', 'servers'})
        self.assertRegex(protocol['hash'], r'^[0-9a-f]{64}$')
        (server,) = protocol['servers']
        self.assertEqual(server, {'name': 'alpha', 'command': 'node', 'args': ['--port', '4000'],
                                  'cwd': '/workspace', 'env_keys': ['API_KEY'], 'env_vars': ['HOME']})

    def test_structured_env_vars_are_accepted_hashed_and_displayed_with_metadata(self):
        # 対象版 mcp_types.rs の untagged enum: 文字列名か {name, source?}（source は local/remote）。
        forms = ('HOME', {'name': 'TOKEN'}, {'name': 'NULLSRC', 'source': None},
                 {'name': 'LOCAL', 'source': 'local'}, {'name': 'REMOTE', 'source': 'remote'})
        protocol = self.snapshot([stdio('alpha', env_vars=forms)])
        self.assertEqual(protocol['count'], 1)
        self.assertEqual(protocol['servers'][0]['env_vars'], list(forms))
        self.assertEqual(protocol['hash'], canonical_hash([stdio('alpha', env_vars=forms)]))
        base = self.snapshot([stdio('alpha', env_vars=({'name': 'KEY', 'source': 'local'},))])['hash']
        remote = self.snapshot([stdio('alpha', env_vars=({'name': 'KEY', 'source': 'remote'},))])['hash']
        bare = self.snapshot([stdio('alpha', env_vars=({'name': 'KEY'},))])['hash']
        plain = self.snapshot([stdio('alpha', env_vars=('KEY',))])['hash']
        self.assertEqual(len({base, remote, bare, plain}), 4)

    def test_structured_env_vars_display_strips_control_characters_but_hash_keeps_them(self):
        raw = ({'name': 'K\x1b[31mEY', 'source': 'local'}, 'PA\x00TH')
        protocol = self.snapshot([stdio('alpha', env_vars=raw)])
        self.assertEqual(protocol['servers'][0]['env_vars'], [{'name': 'K[31mEY', 'source': 'local'}, 'PATH'])
        self.assertEqual(protocol['hash'], canonical_hash([stdio('alpha', env_vars=raw)]))
        clean = self.snapshot([stdio('alpha', env_vars=({'name': 'K[31mEY', 'source': 'local'}, 'PATH'))])
        self.assertNotEqual(clean['hash'], protocol['hash'])

    def test_listing_passes_fixed_trust_override_and_inherits_codex_home(self):
        self.snapshot([])
        (call,) = self.list_calls()
        args = call['args']
        self.assertIn('--json', args)
        self.assertEqual(args[args.index('-c') + 1], TRUST_OVERRIDE)
        self.assertEqual(call['codex_home'], str(self.codex_home))
        self.assertEqual(call['cwd'], str(self.root))


class SchemaTests(AuditCase):
    def test_http_with_helper_is_rejected_even_when_redacted(self):
        for helper in ('<redacted>', 'sh -c "cat /run/secrets/token"'):
            with self.subTest(helper=helper):
                self.listing([stdio('alpha'), http('remote', helper=helper)])
                result = self.run_helper('snapshot')
                self.assert_rejected(result)
                self.assertIn('remote', result.stderr)
                self.assertIn('helper', result.stderr)
                self.assertNotIn('/run/secrets/token', result.stderr)
        self.listing([http('remote', helper='<redacted>', enabled=False)])
        self.assertEqual(self.snapshot()['count'], 0)

    def test_rejection_message_strips_control_characters_from_server_name(self):
        self.listing([http('re\x1b[31mmote\x07', helper='<redacted>')])
        result = self.run_helper('snapshot')
        self.assert_rejected(result)
        self.assertNotIn('\x1b', result.stderr)
        self.assertNotIn('\x07', result.stderr)

    def test_unknown_transport_type_is_rejected(self):
        for kind in ('sse', 'websocket', 'STDIO', 'Stdio', ''):
            with self.subTest(kind=kind):
                entry = stdio('alpha')
                entry['transport']['type'] = kind
                self.listing([entry])
                self.assert_rejected(self.run_helper('snapshot'))

    def test_unknown_or_missing_transport_field_is_rejected(self):
        cases = {}
        extra = stdio('alpha')
        extra['transport']['shell'] = True
        cases['extra stdio field'] = extra
        missing = stdio('alpha')
        del missing['transport']['env_vars']
        cases['missing env_vars'] = missing
        missing_cwd = stdio('alpha')
        del missing_cwd['transport']['cwd']
        cases['missing cwd'] = missing_cwd
        http_extra = http('remote')
        http_extra['transport']['command'] = 'evil'
        cases['extra http field'] = http_extra
        http_missing = http('remote')
        del http_missing['transport']['http_headers_helper']
        cases['missing helper field'] = http_missing
        for label, entry in cases.items():
            with self.subTest(case=label):
                self.listing([entry])
                self.assert_rejected(self.run_helper('snapshot'))

    def test_wrong_types_are_rejected(self):
        def mutate(**changes):
            entry = stdio('alpha', env={'A': '1'})
            for key, value in changes.items():
                if key.startswith('t_'):
                    entry['transport'][key[2:]] = value
                else:
                    entry[key] = value
            return [entry]

        cases = {
            'top-level object': {'alpha': stdio('alpha')},
            'entry not object': ['alpha'],
            'name int': mutate(name=1),
            'enabled string': mutate(enabled='true'),
            'enabled null': mutate(enabled=None),
            'transport string': mutate(transport='stdio'),
            'command null': mutate(t_command=None),
            'command list': mutate(t_command=['node']),
            'args string': mutate(t_args='server.js'),
            'args int item': mutate(t_args=['a', 1]),
            'env list': mutate(t_env=['A=1']),
            'env value int': mutate(t_env={'A': 1}),
            'env_vars string': mutate(t_env_vars='HOME'),
            'cwd int': mutate(t_cwd=7),
            'type missing': mutate(t_type=None),
        }
        del cases['type missing'][0]['transport']['type']
        for label, entries in cases.items():
            with self.subTest(case=label):
                self.listing(entries)
                self.assert_rejected(self.run_helper('snapshot'))

    def test_invalid_env_vars_elements_are_rejected(self):
        cases = {
            'null list': None,
            'unknown source': [{'name': 'KEY', 'source': 'cloud'}],
            'source int': [{'name': 'KEY', 'source': 1}],
            'name int': [{'name': 1}],
            'missing name': [{'source': 'local'}],
            'unknown key': [{'name': 'KEY', 'source': 'local', 'default': 'x'}],
            'empty object': [{}],
            'int element': ['HOME', 1],
            'nested list': [['HOME']],
            'null element': [None],
        }
        for label, env_vars in cases.items():
            with self.subTest(case=label):
                self.listing([stdio('alpha', env_vars=env_vars)])
                self.assert_rejected(self.run_helper('snapshot'))

    def test_unknown_or_missing_top_level_entry_key_is_rejected(self):
        extra = stdio('alpha')
        extra['sandbox'] = 'none'
        missing = stdio('alpha')
        del missing['enabled']
        for label, entry in (('extra key', extra), ('missing enabled', missing)):
            with self.subTest(case=label):
                self.listing([entry])
                self.assert_rejected(self.run_helper('snapshot'))

    def test_duplicate_server_names_are_rejected(self):
        self.listing([stdio('alpha'), stdio('alpha', command='evil')])
        self.assert_rejected(self.run_helper('snapshot'))
        self.listing([stdio('alpha'), stdio('alpha', enabled=False)])
        self.assert_rejected(self.run_helper('snapshot'))

    def test_duplicate_json_keys_are_rejected(self):
        entry = json.dumps(stdio('alpha'))
        cases = {
            'transport command': entry.replace('"command": "node"', '"command": "safe", "command": "node"'),
            'entry enabled': entry.replace('"enabled": true', '"enabled": false, "enabled": true'),
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                self.assertNotEqual(text, entry)
                self.state['list'] = {'stdout': '[' + text + ']\n'}
                self.assert_rejected(self.run_helper('snapshot'))

    def test_malformed_native_stdout_is_rejected(self):
        valid = json.dumps([stdio('alpha')])
        for label, text in (('truncated', valid[:-8]), ('empty', ''), ('whitespace', '  \n'),
                            ('prefix line', 'warning: cloud config stale\n' + valid + '\n'),
                            ('two documents', valid + '\n' + valid + '\n'), ('null', 'null\n'),
                            ('bare string', '"[]"\n'),
                            ('nan constant', valid.replace('"startup_timeout_sec": null', '"startup_timeout_sec": NaN'))):
            with self.subTest(case=label):
                self.state['list'] = {'stdout': text}
                self.assert_rejected(self.run_helper('snapshot'))

    def test_nonzero_list_exit_is_rejected_and_reports_stage_and_code_without_raw_stderr(self):
        self.listing([stdio('alpha')])
        self.state['list'].update({'code': 3, 'stderr': 'ERROR: ' + SECRET_STDERR + '\n'})
        result = self.run_helper('snapshot')
        self.assert_rejected(result)
        self.assertIn('list', result.stderr)
        self.assertRegex(result.stderr, r'\b3\b')
        self.assertNotIn(SECRET_STDERR, result.stderr)

    def test_unsupported_version_is_rejected_before_listing(self):
        for label, spec in (('newer', {'stdout': 'codex-cli 0.157.0\n'}),
                            ('older', {'stdout': 'codex-cli 0.155.1\n'}),
                            ('different prefix', {'stdout': 'codex 0.156.0\n'}),
                            ('empty', {'stdout': ''}),
                            ('extra line', {'stdout': VERSION_LINE + '\nextra\n'}),
                            ('trailing space', {'stdout': VERSION_LINE + ' \n'}),
                            ('crlf', {'stdout': VERSION_LINE + '\r\n'}),
                            ('nonzero', {'stdout': VERSION_LINE + '\n', 'code': 1})):
            with self.subTest(case=label):
                self.state['version'] = spec
                self.listing([])
                result = self.run_helper('snapshot')
                self.assert_rejected(result)
                self.assertEqual(self.list_calls(), [])
        self.state['version'] = {'stdout': VERSION_LINE}
        self.assertEqual(self.snapshot([])['codex_version'], SUPPORTED)


class ProcessTests(AuditCase):
    def test_default_deadlines_match_plan(self):
        spec = importlib.util.spec_from_file_location('codex_mcp_audit', HELPER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.LIST_TIMEOUT_SECONDS, 60)
        self.assertEqual(mod.VERSION_TIMEOUT_SECONDS, 5)
        self.assertFalse((self.root / 'calls').exists(), 'import だけで codex が起動された')

    def test_list_timeout_kills_process_group_and_reports_elapsed(self):
        self.state['list'] = {'spawn': True, 'sleep': 30}
        started = time.monotonic()
        result = self.run_helper('snapshot', constants={'LIST_TIMEOUT_SECONDS': 1})
        self.assertLess(time.monotonic() - started, 10)
        self.assert_rejected(result)
        self.assertIn('timeout', result.stderr)
        self.assertIn('list', result.stderr)
        self.assertRegex(result.stderr, r'\d+(?:\.\d+)?\s*(?:秒|s\b|sec)')
        (call,) = self.list_calls()
        self.assertEqual(call['pgid'], call['pid'])
        self.assertNotEqual(call['pgid'], os.getpgid(0))
        grandchild = int((self.root / 'grandchild').read_text())
        deadline = time.monotonic() + 3
        while alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(grandchild), '孫プロセスが process group 停止後も生存')
        self.assertFalse(alive(call['pid']))

    def test_version_timeout_is_independent_and_blocks_listing(self):
        self.state['version'] = {'sleep': 5}
        self.listing([])
        started = time.monotonic()
        result = self.run_helper('snapshot', constants={'VERSION_TIMEOUT_SECONDS': 1, 'LIST_TIMEOUT_SECONDS': 30})
        self.assertLess(time.monotonic() - started, 4)
        self.assert_rejected(result)
        self.assertIn('timeout', result.stderr)
        self.assertEqual(self.list_calls(), [])

    def test_sigterm_to_helper_stops_native_process_group(self):
        self.state['list'] = {'spawn': True, 'sleep': 30}
        self.state_path.write_text(json.dumps(self.state))
        (self.root / 'calls').write_text('')
        helper = subprocess.Popen([sys.executable, '-I', str(HELPER), '--codex', str(self.codex), 'snapshot'],
                                  cwd=self.root, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        native = None
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                lines = (self.root / 'calls').read_text().splitlines()
                calls = [json.loads(line) for line in lines if line.endswith('}')]
                listed = [c for c in calls if 'list' in c['args']]
                if listed and (self.root / 'grandchild').exists():
                    native = listed[0]
                    break
                time.sleep(0.05)
            self.assertIsNotNone(native, 'dummy の list 呼び出しが観測できない')
            grandchild = int((self.root / 'grandchild').read_text())
            self.assertTrue(alive(native['pid']))
            self.assertTrue(alive(grandchild))
            helper.send_signal(signal.SIGTERM)
            stdout, stderr = helper.communicate(timeout=10)
            self.assertNotEqual(helper.returncode, 0)
            self.assertEqual(stdout, '')
            deadline = time.monotonic() + 3
            while (alive(native['pid']) or alive(grandchild)) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(alive(native['pid']), 'SIGTERM 後も native CLI が生存')
            self.assertFalse(alive(grandchild), 'SIGTERM 後も孫プロセスが生存')
        finally:
            # 自分が起動した helper と、その dummy の process group だけを確実に清掃する。
            if helper.poll() is None:
                helper.kill()
                helper.wait()
            if native is not None:
                try:
                    os.killpg(native['pgid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_leftover_group_members_are_stopped_after_success(self):
        self.state['list'] = {'spawn': True}
        self.snapshot([])
        grandchild = int((self.root / 'grandchild').read_text())
        deadline = time.monotonic() + 3
        while alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(grandchild), '一覧成功後も process group の残留が停止していない')


class VerifyTests(AuditCase):
    def record(self, hash_value, version=SUPPORTED, protocol_version=1, text=None):
        path = self.root / 'approved.json'
        if text is None:
            text = json.dumps({'protocol_version': protocol_version, 'codex_version': version, 'hash': hash_value})
        path.write_text(text)
        return path

    def test_verify_accepts_matching_record_and_rejects_changed_definition(self):
        protocol = self.snapshot([stdio('alpha', env={'API_KEY': SECRET_ENV})])
        record = self.record(protocol['hash'])
        result = self.run_helper('verify', str(record))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.listing([stdio('alpha', args=('server.js', '--evil'), env={'API_KEY': SECRET_ENV})])
        self.assert_rejected(self.run_helper('verify', str(record)))
        self.listing([stdio('alpha', env={'API_KEY': SECRET_ENV}), stdio('beta')])
        self.assert_rejected(self.run_helper('verify', str(record)))

    def test_verify_rejects_missing_empty_malformed_and_mismatched_records(self):
        protocol = self.snapshot([stdio('alpha')])
        good = protocol['hash']
        # record は同じファイルを上書きするため、各 subTest の内部で書いてから実行する。
        specs = (('missing', None), ('dev-null', None),
                 ('empty', {'text': ''}),
                 ('garbage', {'text': 'not json'}),
                 ('bare hash', {'text': good + '\n'}),
                 ('list wrapper', {'text': json.dumps([{'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': good}])}),
                 ('duplicate key', {'text': '{"protocol_version": 1, "codex_version": "%s", "hash": "%s", "hash": "%s"}'
                                    % (SUPPORTED, '0' * 64, good)}),
                 ('protocol true', {'text': json.dumps({'protocol_version': True, 'codex_version': SUPPORTED, 'hash': good})}),
                 ('protocol string', {'text': json.dumps({'protocol_version': '1', 'codex_version': SUPPORTED, 'hash': good})}),
                 ('protocol float', {'text': json.dumps({'protocol_version': 1.0, 'codex_version': SUPPORTED, 'hash': good})}),
                 ('extra key', {'text': json.dumps({'protocol_version': 1, 'codex_version': SUPPORTED, 'hash': good, 'servers': []})}),
                 ('other version', {'version': '0.155.1'}),
                 ('other protocol', {'protocol_version': 2}),
                 ('wrong hash', {'hash_value': '0' * 64}),
                 ('short hash', {'hash_value': good[:-1]}),
                 ('uppercase hash', {'hash_value': good.upper()}))
        for label, spec in specs:
            with self.subTest(case=label):
                if label == 'missing':
                    path = self.root / 'absent.json'
                elif label == 'dev-null':
                    path = Path('/dev/null')
                else:
                    path = self.record(spec.pop('hash_value', good), **spec)
                self.assert_rejected(self.run_helper('verify', str(path)))
        self.assertEqual(self.run_helper('verify', str(self.record(good))).returncode, 0)

    def test_verify_does_not_modify_readonly_record_and_hides_secrets(self):
        protocol = self.snapshot([stdio('alpha', env={'API_KEY': SECRET_ENV}),
                                  http('remote', headers={'Authorization': SECRET_HEADER})])
        record = self.record(protocol['hash'])
        record.chmod(0o400)
        self.addCleanup(record.chmod, 0o600)
        before = record.read_bytes(), record.stat().st_mtime_ns
        result = self.run_helper('verify', str(record))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((record.read_bytes(), record.stat().st_mtime_ns), before)
        for output in (result.stdout, result.stderr):
            self.assertNotIn(SECRET_ENV, output)
            self.assertNotIn(SECRET_HEADER, output)

    def test_verify_fails_when_snapshot_cannot_be_taken(self):
        protocol = self.snapshot([stdio('alpha')])
        record = self.record(protocol['hash'])
        self.listing([stdio('alpha'), http('remote', helper='<redacted>')])
        self.assert_rejected(self.run_helper('verify', str(record)))
        self.state['list'] = {'stdout': '', 'code': 2}
        self.assert_rejected(self.run_helper('verify', str(record)))
        self.state['list'] = {}
        self.state['version'] = {'stdout': 'codex-cli 0.157.0\n'}
        self.assert_rejected(self.run_helper('verify', str(record)))


class HygieneTests(AuditCase):
    def test_snapshot_output_hides_env_values_and_http_headers(self):
        entries = [stdio('alpha', env={'API_KEY': SECRET_ENV}, env_vars=('GITHUB_TOKEN',)),
                   http('remote', headers={'Authorization': SECRET_HEADER})]
        self.listing(entries)
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 0, result.stderr)
        for output in (result.stdout, result.stderr):
            self.assertNotIn(SECRET_ENV, output)
            self.assertNotIn(SECRET_HEADER, output)
            self.assertNotIn('Authorization', output)
        (server,) = json.loads(result.stdout)['servers']
        self.assertEqual(server['env_keys'], ['API_KEY'])
        self.assertEqual(server['env_vars'], ['GITHUB_TOKEN'])

    def test_no_temp_files_remain_after_success_and_rejection(self):
        self.snapshot([stdio('alpha')])
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.listing([http('remote', helper='<redacted>')])
        self.assert_rejected(self.run_helper('snapshot'))
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(list(self.codex_home.iterdir()), [])

    def test_argv_errors_never_invoke_codex(self):
        self.listing([])
        for label, command in (('unknown subcommand', [sys.executable, '-I', str(HELPER), '--codex', str(self.codex), 'list']),
                               ('no subcommand', [sys.executable, '-I', str(HELPER), '--codex', str(self.codex)]),
                               ('missing --codex', [sys.executable, '-I', str(HELPER), 'snapshot']),
                               ('relative --codex', [sys.executable, '-I', str(HELPER), '--codex', 'bin/codex', 'snapshot']),
                               ('verify without file', [sys.executable, '-I', str(HELPER), '--codex', str(self.codex), 'verify']),
                               ('snapshot with file', [sys.executable, '-I', str(HELPER), '--codex', str(self.codex), 'snapshot', 'x'])):
            with self.subTest(case=label):
                self.state_path.write_text(json.dumps(self.state))
                (self.root / 'calls').write_text('')
                result = subprocess.run(command, cwd=self.root, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertEqual((self.root / 'calls').read_text(), '')

    def test_missing_or_non_executable_cli_is_diagnosed_without_fallback(self):
        self.env['PATH'] = str(self.codex.parent) + ':' + os.defpath
        for label, path in (('absent', self.root / 'absent-codex'), ('directory', self.root / 'bin')):
            with self.subTest(case=label):
                result = self.run_helper('snapshot', codex=path)
                self.assert_rejected(result)
                self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
