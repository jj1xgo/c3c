# #150 Codex 起動時 MCP 審査の範囲を Claude 経路に揃える Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codex 経路の起動時 MCP 審査を、native `codex mcp list --json` と版の完全一致から、リポジトリ同梱の `/workspace/.codex/config.toml` を直接読む方式へ置き換え、`codex-version.txt` が `latest` や任意の固定版でも `c3c codex` が起動できるようにする。

**Architecture:** `codex-mcp-audit.py` は Codex CLI を実行せず、`tomllib` で `/workspace/.codex/config.toml` を読む。`mcp_servers` の enabled stdio を hash し、`plugins` の有効エントリは fail-closed で拒否する。launcher・entrypoint・preflight の構造（label 検査 → 検査用コンテナで snapshot → ホスト確認 → 本起動で verify）は変えず、protocol を 2 に上げて版の照合を外す。

**Tech Stack:** bash（`c3c`・`entrypoint.sh`）、Python 3.11+ の標準ライブラリ（`tomllib`。イメージ内の python3）、unittest、Podman。

**Spec:** `docs/superpowers/specs/2026-09-23-codex-mcp-audit-scope-design.md`

**作業場所:** worktree `~/Projects/worktrees/c3c-issue150`、ブランチ `feat/issue150-codex-audit-scope`（origin/main 039abf1 起点）。Task 1 着手前に `PLAN=$(git rev-parse HEAD)` を控える（Task 4 Step 5 で使う）。Task 1〜3 の commit は作業途中の区切りで、Task 4 Step 5 で 1 つにまとめる。

## Global Constraints

- 審査対象は `/workspace/.codex/config.toml` の `mcp_servers` と `plugins` だけ。`CODEX_DIR`（`/home/node/.codex`）の設定と plugin キャッシュは読まない。
- `plugins` のエントリが 1 つでもあり、`enabled = false`（真偽値の false）と明示されていないものがあれば拒否する。
- `marketplaces` のエントリが 1 つでもあれば拒否する（project 層の marketplace は user 層で有効化した plugin の取得元を差し替えうる）。空の `[marketplaces]` は通す。
- `mcp_servers.<name>` の許可 key は codex-cli 0.156.0 の `RawMcpServerConfig`（`codex-rs/config/src/mcp_types.rs`）の 28 個: `command` `args` `env` `env_vars` `cwd` `http_headers` `env_http_headers` `url` `bearer_token` `bearer_token_env_var` `http_headers_helper` `environment_id` `auth` `startup_timeout_sec` `startup_timeout_ms` `tool_timeout_sec` `enabled` `required` `supports_parallel_tool_calls` `omit_tools_from` `default_tools_approval_mode` `enabled_tools` `disabled_tools` `scopes` `oauth` `oauth_resource` `name` `tools`。これ以外の key を持つエントリは拒否する。各 key の値の型は `RawMcpServerConfig` に合わせて検査し（helper の `KEY_CHECKS`）、disabled なエントリも検査する。
- hash の対象は enabled stdio の名前・`command`・`args`・`env`・`env_vars`・`cwd`・`environment_id`。
- enabled で `http_headers_helper` が非 null のエントリは transport を問わず拒否する。helper の無い HTTP（`url` のみ）は hash 対象外で通す。
- protocol は 2。`CODEX_AUDIT_PROTOCOL_VERSION=2`、`LABEL io.c3c.codex-audit-protocol="2"`、`PROTOCOL_VERSION = 2` を同期させる。
- 承認記録は `~/.local/state/claude-container/mcp-approvals/codex/<project>/project-config.json`、内容は `{"protocol_version":2,"hash":"<64 桁小文字 hex>"}` + 改行。
- 同梱 default の `codex-version.txt` は固定版 `0.156.0` のまま変えない。`CODEX_SUPPORTED_VERSION` と `SUPPORTED_VERSION` は削除する。
- 空の `codex-version.txt`（opt-out）で Codex を起動しようとした場合の拒否は維持する。
- 表示用の文字列は ASCII 制御文字を除去し、hash には元の値を使う（現行方針）。env の値と HTTP header は表示しない。
- 変更前に `docs/development-invariants.md` の該当節を読む（`c3c`・`entrypoint.sh`・`Dockerfile.claude`・`codex-mcp-audit.py` を触るため）。編集のたびに `./lint.sh` を実行し、終了コード 0・警告ゼロを確認する。

## Review Focus

1. **イメージの python3 が 3.11 未満（`tomllib` が無い）**: 利用側が `base-image.txt` で古いベースを選ぶと起きうる。helper は `tomllib` の import 失敗を判定不能として明確なメッセージで止まり（Codex は起動しない）、README の前提に「イメージ内 python3 3.11 以上」を書く。→ Task 1 の `test_missing_tomllib_is_reported_as_audit_error`、Task 4 の README。
2. **`.codex/config.toml` が symlink・ディレクトリ・FIFO・読めないファイル、または検査中に差し替えられる**: symlink は Codex と同じく辿り、通常ファイルでなければ拒否する。`O_NONBLOCK` で開いた同じ fd を `fstat` して読むので、`stat` と `open` の間に FIFO へ差し替えても止まり続けない（検査と読み取りの窓が無い）。→ Task 1 の `test_non_regular_or_unreadable_config_is_rejected`。
3. **検査と本起動の間に `.codex/config.toml` が変わる**: 本起動の verify が同じファイルを再度読み、hash 不一致で止まる（現行の再照合と同じ）。→ Task 2 の既存 `test_verify_failure_never_execs_native_cli` を新方式で維持。
4. **旧イメージ（protocol 1）と旧承認記録（`0.156.0.json`）**: 旧イメージは label 不一致で preflight 前に `-b` を案内して止まる。旧記録は読まず、初回だけ再確認になる。`--clean <dir>` は Codex subdirectory ごと消す。→ Task 3 の label・record・clean の試験。
5. **`latest` で入った版が 0.156.0 と違う**: 版を理由に止まらない。→ Task 3 の guard 試験（`latest` と任意の固定版がどちらも OK）、Task 5 の実機確認。

---

### Task 1: `codex-mcp-audit.py` を `config.toml` 読み取り方式に書き換える

**Files:**
- Modify（全面置換）: `codex-mcp-audit.py`
- Modify（全面置換）: `tests/test_codex_mcp_audit.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - CLI: `python3 -I codex-mcp-audit.py --config <絶対パス> snapshot` → stdout に JSON 1 文書 `{"protocol_version":2,"hash":str,"count":int,"servers":[{"name","command","args","cwd","env_keys","env_vars","environment_id"}]}`、終了コード 0。失敗時は stderr に `ERROR: ...`、終了コード 1、stdout は空。
  - CLI: `python3 -I codex-mcp-audit.py --config <絶対パス> verify <record>` → 一致時 0、不一致・不正時 1。
  - 承認記録の形 `{"protocol_version":2,"hash":str}`（Task 3 の launcher が書く）。

- [ ] **Step 1: 試験を書く（全面置換）**

`tests/test_codex_mcp_audit.py` を次の内容で置き換える。

```python
#!/usr/bin/env python3
"""Codex 起動時 MCP 審査 helper（protocol 2、#150）の回帰試験。

helper は Codex CLI を実行せず、`--config` で渡したリポジトリ同梱の `.codex/config.toml` を tomllib で読む。
enabled stdio の実行定義だけを canonical hash にまとめ、project 設定での plugin 有効化は拒否する。
ここで固定する protocol / 承認記録の形は launcher（c3c）と entrypoint が消費する。
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
HELPER = REPO / 'codex-mcp-audit.py'
SECRET_ENV = 'hunter2-env-value'
SECRET_HEADER = 'Bearer sekrit-header-value'
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
''' % SECRET_ENV


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
            'env': {'TOKEN': SECRET_ENV}, 'env_vars': ['HOME', {'name': 'PATH', 'source': 'local'}],
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
                         (SECRET_ENV, 'other-value'),
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
                          'http_headers = { Authorization = "%s" }\n' % SECRET_HEADER)
        self.write(text)
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET_ENV, result.stdout + result.stderr)
        self.assertNotIn(SECRET_HEADER, result.stdout + result.stderr)

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

    def test_valid_values_for_all_keys_are_accepted_in_a_disabled_entry(self):
        text = ('[mcp_servers.x]\nenabled = false\ncommand = "a"\nargs = ["b"]\nenv = { K = "v" }\n'
                'env_vars = ["A", { name = "B", source = "remote" }]\ncwd = "/w"\nhttp_headers = { H = "v" }\n'
                'env_http_headers = { H = "E" }\nurl = "https://a.example"\nbearer_token = "t"\n'
                'bearer_token_env_var = "T"\nhttp_headers_helper = "/bin/x"\nenvironment_id = "local"\n'
                'auth = "chatgpt"\nstartup_timeout_sec = 1.5\nstartup_timeout_ms = 10\ntool_timeout_sec = 3\n'
                'required = true\nsupports_parallel_tool_calls = false\nomit_tools_from = ["s"]\n'
                'default_tools_approval_mode = "auto"\nenabled_tools = ["a"]\ndisabled_tools = ["b"]\n'
                'scopes = ["s"]\noauth = { callback_port = 1 }\noauth_resource = "r"\nname = "n"\n'
                'tools = { t = { approval_mode = "auto" } }\n')
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
```

- [ ] **Step 2: 試験が失敗することを確かめる**

Run: `python3 -m unittest tests.test_codex_mcp_audit -v 2>&1 | tail -5`
Expected: FAIL（現行 helper は `--config` を受け付けず argparse のエラーで終了コード 2）

- [ ] **Step 3: helper を書き換える（全面置換）**

`codex-mcp-audit.py` を次の内容で置き換える。

```python
#!/usr/bin/env python3
"""Codex 起動時 MCP 審査 helper（protocol 2、#150。設計 docs/superpowers/specs/2026-09-23-codex-mcp-audit-scope-design.md）。

`snapshot`: リポジトリ同梱の `.codex/config.toml`（`--config` の絶対パス）を tomllib で読み、enabled な stdio
定義だけを canonical JSON にまとめた hash と表示用 metadata を stdout へ 1 つの JSON 文書として出す。
`verify <record>`: host が `:ro` で渡した承認記録と現在の snapshot を照合し、一致時のみ 0 で終了する。

設計上の固定点:
- Codex CLI は実行しない。読むのは公開の設定形式（Config Reference）だけで、Codex の版に依存しない。
- 審査するのはリポジトリ同梱の project 設定だけ。CODEX_HOME の user 設定は Claude 経路の ~/.claude.json と
  同じく審査対象外（README「帰結の重大性で線を引いている」節）。
- project 設定での plugin 有効化と marketplace 定義は、中身を読まずに fail-closed で拒否する（中身を読むと
  Codex の内部形式に依存するため）。
- 判定不能（壊れた TOML・型違い・未知 key・command と url の併記・helper 付き定義）は fail-closed。
  型は disabled なエントリも含め、許可する全 key について検査する。
- 表示用文字列は制御文字を除去する（entrypoint/launcher の既存方針と同じ）。hash には元の値を使う。
"""

import argparse
import hashlib
import json
import os
import re
import stat
import sys

try:
    import tomllib
except ImportError:
    tomllib = None

PROTOCOL_VERSION = 2
# env_vars は McpServerEnvVar: 文字列名か {name, source?}。source は local/remote。
ENV_VAR_KEYS = frozenset(('name', 'source'))
ENV_VAR_SOURCES = ('local', 'remote')
# auth は McpServerAuth の serde 名。
AUTH_VALUES = ('oauth', 'chatgpt', 'ema_auth')
RECORD_KEYS = frozenset(('protocol_version', 'hash'))
HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')
CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')


class AuditError(Exception):
    """審査を継続できない状態。メッセージは表示済みにサニタイズされている。"""


def sanitize(value):
    return CONTROL_CHARS.sub('', str(value))


def is_str(value):
    return isinstance(value, str)


def is_bool(value):
    return isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_nonneg_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_table(value):
    return isinstance(value, dict)


def is_str_list(value):
    return isinstance(value, list) and all(is_str(item) for item in value)


def is_str_map(value):
    return isinstance(value, dict) and all(is_str(k) and is_str(v) for k, v in value.items())


def is_env_var(item):
    if is_str(item):
        return True
    if not isinstance(item, dict) or 'name' not in item or not set(item) <= ENV_VAR_KEYS:
        return False
    return is_str(item['name']) and ('source' not in item or item['source'] in ENV_VAR_SOURCES)


def is_env_var_list(value):
    return isinstance(value, list) and all(is_env_var(item) for item in value)


# codex-cli 0.156.0 の RawMcpServerConfig（codex-rs/config/src/mcp_types.rs）の key と、その型の検査。
# これ以外の key は審査できない。値は disabled なエントリでも検査する（native の受理と食い違わせない）。
KEY_CHECKS = {
    'command': is_str, 'args': is_str_list, 'env': is_str_map, 'env_vars': is_env_var_list, 'cwd': is_str,
    'http_headers': is_str_map, 'env_http_headers': is_str_map, 'url': is_str, 'bearer_token': is_str,
    'bearer_token_env_var': is_str, 'http_headers_helper': is_str, 'environment_id': is_str,
    'auth': lambda value: is_str(value) and value in AUTH_VALUES,
    'startup_timeout_sec': is_number, 'startup_timeout_ms': is_nonneg_int, 'tool_timeout_sec': is_number,
    'enabled': is_bool, 'required': is_bool, 'supports_parallel_tool_calls': is_bool,
    'omit_tools_from': is_str_list, 'default_tools_approval_mode': is_str,
    'enabled_tools': is_str_list, 'disabled_tools': is_str_list, 'scopes': is_str_list,
    'oauth': is_table, 'oauth_resource': is_str, 'name': is_str,
    'tools': lambda value: is_table(value) and all(is_table(item) for item in value.values()),
}
SERVER_KEYS = frozenset(KEY_CHECKS)


def strict_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise AuditError('JSON に重複 key があります: ' + sanitize(key))
        obj[key] = value
    return obj


def strict_constant(name):
    raise AuditError('JSON に非標準の定数があります: ' + sanitize(name))


def parse_json(data, what):
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise AuditError(what + ' が UTF-8 ではありません') from None
    try:
        return json.loads(text, object_pairs_hook=strict_pairs, parse_constant=strict_constant)
    except ValueError as exc:
        raise AuditError(what + ' を単一の JSON 文書として解析できません: ' + sanitize(exc.__class__.__name__)) from None


def load_config(path):
    """project 設定を読む。無ければ None（dangling symlink も Codex と同じく無い扱い）。"""
    if tomllib is None:
        raise AuditError('イメージの python3 に tomllib がありません（Python 3.11 以上が必要です）。'
                         'Codex の起動時審査を行えないため起動を中止します')
    # 検査と読み取りの間の差し替え（FIFO 等）で止まり続けないよう、O_NONBLOCK で開いた同じ fd を
    # fstat して通常ファイルか確かめ、その fd から読む。symlink は Codex と同じく辿る。
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise AuditError(f'{sanitize(path)} を開けません: {sanitize(exc.strerror or exc)}') from None
    try:
        with os.fdopen(fd, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise AuditError(f'{sanitize(path)} が通常ファイルではありません')
            data = handle.read()
    except OSError as exc:
        raise AuditError(f'{sanitize(path)} を読めません: {sanitize(exc.strerror or exc)}') from None
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise AuditError(f'{sanitize(path)} が UTF-8 ではありません') from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise AuditError(f'{sanitize(path)} を TOML として解析できません: {sanitize(exc)}') from None


def check_plugin_sources(config):
    """project 設定での plugin 有効化と marketplace 定義を、中身を読まずに拒否する。"""
    plugins = config.get('plugins')
    if plugins is not None:
        if not isinstance(plugins, dict):
            raise AuditError('.codex/config.toml の plugins が table ではありません')
        active = sorted(sanitize(name) for name, entry in plugins.items()
                        if not (isinstance(entry, dict) and entry.get('enabled') is False))
        if active:
            raise AuditError('リポジトリの .codex/config.toml で plugin が有効化されています（' + ', '.join(active) + '）。'
                             'リポジトリ同梱の plugin は c3c の起動時審査で内容を確認できないため起動を中止します。'
                             '使わないなら該当エントリを削除するか enabled = false にしてください')
    marketplaces = config.get('marketplaces')
    if marketplaces is not None:
        if not isinstance(marketplaces, dict):
            raise AuditError('.codex/config.toml の marketplaces が table ではありません')
        if marketplaces:
            names = ', '.join(sorted(sanitize(name) for name in marketplaces))
            raise AuditError('リポジトリの .codex/config.toml で plugin の marketplace が定義されています（' + names + '）。'
                             'plugin の取得元を差し替えうる設定は c3c の起動時審査で確認できないため起動を中止します。'
                             '該当エントリを削除してください')


def normalize(config):
    """mcp_servers を検証し、hash 対象の enabled stdio 定義（name 順）を返す。"""
    table = config.get('mcp_servers')
    if table is None:
        return []
    if not isinstance(table, dict):
        raise AuditError('.codex/config.toml の mcp_servers が table ではありません')
    servers = []
    for raw_name, entry in table.items():
        name = sanitize(raw_name)
        if not isinstance(entry, dict):
            raise AuditError(f'MCP server {name}: 定義が table ではありません')
        unknown = set(entry) - SERVER_KEYS
        if unknown:
            shown = ', '.join(sorted(sanitize(key) for key in unknown))
            raise AuditError(f'MCP server {name}: c3c が審査できない key があります（{shown}）')
        for key, value in entry.items():
            if not KEY_CHECKS[key](value):
                raise AuditError(f'MCP server {name}: {key} の型が不正です')
        if not entry.get('enabled', True):
            continue
        if entry.get('http_headers_helper') is not None:
            raise AuditError(f'MCP server {name}: enabled な定義が http_headers_helper（ローカル command）を持つため、'
                             '実行定義を審査できません。設定を見直してから起動してください')
        if 'command' in entry and 'url' in entry:
            raise AuditError(f'MCP server {name}: command と url の両方があり transport を判定できません')
        if 'url' in entry:
            continue
        if 'command' not in entry:
            raise AuditError(f'MCP server {name}: command も url も無いため transport を判定できません')
        transport = {'type': 'stdio', 'command': entry['command'], 'args': entry.get('args', []),
                     'env': entry.get('env') or None, 'env_vars': entry.get('env_vars', []),
                     'cwd': entry.get('cwd'), 'environment_id': entry.get('environment_id')}
        servers.append({'name': raw_name, 'transport': transport})
    servers.sort(key=lambda server: server['name'])
    return servers


def canonical_hash(servers):
    doc = {'protocol_version': PROTOCOL_VERSION, 'servers': servers}
    text = json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def display_env_var(item):
    if is_str(item):
        return sanitize(item)
    return {key: sanitize(value) for key, value in item.items()}


def display(server):
    transport = server['transport']
    return {'name': sanitize(server['name']),
            'command': sanitize(transport['command']),
            'args': [sanitize(arg) for arg in transport['args']],
            'cwd': None if transport['cwd'] is None else sanitize(transport['cwd']),
            'env_keys': sorted(sanitize(key) for key in (transport['env'] or {})),
            'env_vars': [display_env_var(item) for item in transport['env_vars']],
            'environment_id': None if transport['environment_id'] is None else sanitize(transport['environment_id'])}


def snapshot(config_path):
    config = load_config(config_path)
    servers = []
    if config is not None:
        check_plugin_sources(config)
        servers = normalize(config)
    return {'protocol_version': PROTOCOL_VERSION, 'hash': canonical_hash(servers), 'count': len(servers),
            'servers': [display(server) for server in servers]}


def read_record(path):
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError as exc:
        raise AuditError(f'承認記録を読めません: {sanitize(exc.strerror or exc)}') from None
    record = parse_json(data, '承認記録')
    if not isinstance(record, dict) or set(record) != RECORD_KEYS:
        raise AuditError('承認記録の形式が対応 protocol と異なります')
    if type(record['protocol_version']) is not int or record['protocol_version'] != PROTOCOL_VERSION:
        raise AuditError('承認記録の protocol_version が対応版と異なります')
    if not is_str(record['hash']) or not HASH_PATTERN.match(record['hash']):
        raise AuditError('承認記録の hash の形式が不正です')
    return record


def verify(config_path, record_path):
    record = read_record(record_path)
    current = snapshot(config_path)
    if current['hash'] != record['hash']:
        raise AuditError('MCP 実行定義が承認記録と一致しません（検査後に設定が変わった可能性）。起動を中止します')
    print(f'INFO: Codex MCP 審査: 承認記録と一致（対象 {current["count"]} 件）。OK', file=sys.stderr)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='codex-mcp-audit.py', allow_abbrev=False)
    parser.add_argument('--config', required=True, help='リポジトリ同梱の .codex/config.toml の絶対パス')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('snapshot')
    sub.add_parser('verify').add_argument('record')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if not os.path.isabs(args.config):
            raise AuditError('--config には .codex/config.toml の絶対パスを指定してください')
        if args.command == 'snapshot':
            sys.stdout.write(json.dumps(snapshot(args.config), ensure_ascii=False) + '\n')
            sys.stdout.flush()
        else:
            verify(args.config, args.record)
    except AuditError as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: 試験が通ることを確かめる**

Run: `python3 -m unittest tests.test_codex_mcp_audit -v 2>&1 | tail -5`
Expected: `OK`（全件成功）。`test_non_regular_or_unreadable_config_is_rejected` の権限部分は root 実行時だけ省略される。

- [ ] **Step 5: lint と commit**

Run: `./lint.sh`
Expected: 終了コード 0、`lint OK`

```bash
git add codex-mcp-audit.py tests/test_codex_mcp_audit.py
git commit -m "feat: #150 Codex MCP 審査 helper を project の config.toml 読み取り方式にする"
```

---

### Task 2: entrypoint と Dockerfile の label を protocol 2 に合わせる

**Files:**
- Modify: `entrypoint.sh:227-262`（Codex の snapshot / verify 呼び出し）
- Modify: `Dockerfile.claude:316-320`（helper のコメント）、`:352-358`（label）
- Modify: `tests/test_codex_entrypoint.py`

**Interfaces:**
- Consumes: Task 1 の CLI（`--config <絶対パス> snapshot|verify <record>`）と record 形 `{"protocol_version":2,"hash":...}`
- Produces: entrypoint の固定パス `CODEX_PROJECT_CONFIG=/workspace/.codex/config.toml`、label `io.c3c.codex-audit-protocol="2"`

- [ ] **Step 1: 試験を新方式に書き換える**

`tests/test_codex_entrypoint.py` を次のように変える。

1. モジュール docstring の「`mcp list --json` に fixture を返し」を「exec 時の argv/env/cwd を記録する dummy」に直し、`.codex/config.toml` を fixture にする旨を書く。
2. 定数を追加する: `FIXED_PROJECT_CONFIG = '/workspace/.codex/config.toml'`。`SUPPORTED` は削除する。
3. `setUp` の固定パス置換（現 108-115 行）の `for needle in (...)` の一覧と置換列に `FIXED_PROJECT_CONFIG` を足す。置換は `'/workspace/.mcp.json'` の置換より前に置く:
   ```python
   source = (source.replace(FIXED_HELPER, str(HELPER)).replace(FIXED_CLI, str(self.codex))
             .replace(FIXED_PROJECT_CONFIG, str(self.workspace / '.codex' / 'config.toml'))
             ...
   ```
4. dummy codex の `mcp list` 応答に依存していた fixture 生成（`stdio()`・`http_helper()` を使って state に一覧を入れている箇所）を、`self.workspace / '.codex' / 'config.toml'` に TOML を書く関数へ置き換える:
   ```python
   def write_project_config(self, text):
       path = self.workspace / '.codex' / 'config.toml'
       path.parent.mkdir(parents=True, exist_ok=True)
       path.write_text(text)
   ```
   stdio の既定 fixture は `'[mcp_servers.alpha]\ncommand = "python3"\nargs = ["server.py"]\ncwd = "/workspace"\nenv_vars = ["HOME"]\n'`、helper 付き HTTP は `'[mcp_servers.web]\nurl = "https://a.example"\nhttp_headers_helper = "/bin/x"\n'`。
5. 承認記録の書き込み（現 142 行・253 行）を `{'protocol_version': 2, 'hash': ...}` にする。
6. `test_preflight_stdout_is_only_the_protocol_and_logs_go_to_stderr` の key 集合を `{'protocol_version', 'hash', 'count', 'servers'}` にする。
7. `test_missing_cli_or_unsupported_version_has_no_fallback` を `test_missing_cli_has_no_fallback` に改名し、「未対応版」部分（dummy の `--version` を変えて拒否を確かめる部分）を削除する。代わりに、dummy の `--version` が `codex-cli 9.9.9` を返しても preflight と run が成功し、dummy が `mcp list` で一度も呼ばれない（呼び出し記録に `mcp` が無い）ことを確かめる新しい試験 `test_codex_version_is_not_consulted` を足す。
8. `test_three_stages_share_home_cwd_override_and_cli` は、snapshot / verify が Codex CLI を呼ばなくなるので、「本起動の exec だけが CLI を呼び、その argv に固定 trust override が入る」ことの確認に縮める。
9. `test_verify_failure_never_execs_native_cli` に、承認後に `.codex/config.toml` を書き換えると exec されないケース（`'config changed'`）を足す。
10. CLI の呼び出し記録（`self.kinds()`・`self.codex_calls`）に依存する次の assert を新方式に合わせる。preflight と verify は CLI を呼ばない。
    - 197 行 `self.kinds() == ['version', 'list']` → `[]`
    - 227 行 `['version', 'list', 'exec']` → `['exec']`
    - 379 行・386 行（`BundledBwrapPathTests`）の kinds 比較 → preflight は `[]`、run は `['exec']`。PATH の先頭が同梱 bwrap のディレクトリであることは、exec の記録の env で確かめる。
    - 206-207 行 `self.codex_calls[0]['env']`（preflight が秘密 export の後であることの観測）→ 削除する。preflight は Codex CLI も MCP command も実行しないので、秘密 export との順序は境界の要件ではなくなる（entrypoint 内の実行位置は変えない。Task 4 で不変条件 72 行をこの内容に更新する）。代わりに、run の exec の env に export した秘密が入り、`CODEX_HOME`・CLI 実体が固定値であることを確かめる。
    - 361-365 行（`SecretIsolationTests` の preflight 側）→ preflight の CLI 呼び出しが無いことを `assertEqual(self.kinds(), [])` で確かめ、秘密の差し替えの検査は run の exec の env だけで行う。

- [ ] **Step 2: 試験が失敗することを確かめる**

Run: `python3 -m unittest tests.test_codex_entrypoint -v 2>&1 | tail -5`
Expected: FAIL（entrypoint がまだ `--codex` を渡すため helper が argparse エラーで失敗する）

- [ ] **Step 3: entrypoint を変える**

`entrypoint.sh` の Codex 審査部分を次のようにする（`CODEX_AUDIT`・`CODEX_APPROVED` の定義の直後に 1 行足し、2 箇所の呼び出しを置き換える。コメントの「native の一覧」の記述も直す）。

```sh
CODEX_AUDIT=/usr/local/bin/codex-mcp-audit.py
CODEX_APPROVED=/etc/claude-container/codex-mcp-approved.json
# 審査対象はリポジトリ同梱の project 設定だけ（#150）。Codex の CLI 実体や版には依存しない。
CODEX_PROJECT_CONFIG=/workspace/.codex/config.toml
```

```sh
if [ "$CODEX_START_MODE" = preflight ]; then
  echo "INFO: Codex 起動時 MCP 審査: $CODEX_PROJECT_CONFIG の MCP 定義を読みます（agent は起動しません）" >&2
  if ! python3 -I "$CODEX_AUDIT" --config "$CODEX_PROJECT_CONFIG" snapshot >&3; then
```

```sh
if ! python3 -I "$CODEX_AUDIT" --config "$CODEX_PROJECT_CONFIG" verify "$CODEX_APPROVED"; then
```

235 行のメッセージ「対応版を書くか空ファイルを削除して」を「固定版か latest を書くか空ファイルを削除して」にする。227-231 行付近のコメント（snapshot / verify の説明、「protocol 1」「版不一致」を含む）を「リポジトリ同梱の `.codex/config.toml` を読む。Codex CLI は本起動の exec だけで使う」に直す。263 行のコメント「snapshot/verify（codex-mcp-audit.py の LIST_ARGS）と同じ値を渡す」は、LIST_ARGS が無くなるので「固定の trust override（検査用コンテナと本起動で同じ設定解決にするため、launcher の preflight と同じ値）」に直す。

- [ ] **Step 4: Dockerfile を変える**

`Dockerfile.claude` の label を `LABEL io.c3c.codex-audit-protocol="2"` にし、直前のコメント「この label が対応版（1）と一致する」を「（2）」に直す。152 行のコメント「（c3c 第2b-2段階から起動時 MCP 審査の対応版に固定）」を「（固定版 0.156.0）」にする。helper の COPY 前のコメントに「protocol 2 から Codex CLI を呼ばず、`/workspace/.codex/config.toml` を `tomllib` で読む（イメージの python3 は 3.11 以上が必要）」を足す。

- [ ] **Step 5: 試験が通ることを確かめる**

Run: `python3 -m unittest tests.test_codex_entrypoint tests.test_codex_mcp_audit -v 2>&1 | tail -5`
Expected: `OK`

- [ ] **Step 6: lint と commit**

Run: `./lint.sh`
Expected: 終了コード 0

```bash
git add entrypoint.sh Dockerfile.claude tests/test_codex_entrypoint.py
git commit -m "feat: #150 entrypoint の Codex 審査を project 設定の読み取りにし protocol を 2 にする"
```

---

### Task 3: launcher から版の照合を外し、protocol 2 の記録と検証に切り替える

**Files:**
- Modify: `c3c:23-28`（定数）、`:460-464`（承認記録パス）、`:995-1027`（`guard_codex_agent`）、`:1044-1086`（`codex_record_content`・`validate_codex_record_file`）、`:1133`・`:1145-1240`（preflight の表示と protocol 検証）、`:1266`（確認の WARNING 文言）
- Modify: `tests/test_codex_launch.py`、`tests/test_c3c_launch.py`、`tests/test_c3c_config.py`

**Interfaces:**
- Consumes: Task 1 の protocol 2 文書（`servers[]` に `environment_id` が増えた）、Task 2 の label `2`
- Produces: `CODEX_AUDIT_PROTOCOL_VERSION=2`、`CODEX_APPROVAL_RECORD=$CODEX_APPROVAL_DIR/project-config.json`、`codex_record_content <hash>` → `{"protocol_version":2,"hash":"<hash>"}`

- [ ] **Step 1: 試験を書き換える**

`tests/test_codex_launch.py`:
1. `SUPPORTED` は `codex-version.txt` の fixture 値としてだけ残す（`'0.156.0'`）。`protocol()` の既定を `protocol_version=2` にし、文書から `codex_version` を外す。`servers` の要素に `'environment_id': None` を足す。
2. `record_path()` は `self.approvals / 'codex' / <project> / 'project-config.json'` を返す（引数 `version` を削除）。記録の中身は `{'protocol_version': 2, 'hash': ...}`。
3. `test_codex_version_file_is_diagnosed_statically`: 期待を「空は FAIL（opt-out）、`latest`・`0.156.0`・`0.155.1`・`9.9.9` はすべて OK（WARNING なし）」に変える。`--check` では `[OK]   Codex 版指定: <値>（採用元: project）` を確かめる。
4. `test_preflight_failure_or_malformed_protocol_blocks_run_and_writes_nothing`: `'protocol 2'` ケースを `'protocol 1'`（`protocol(protocol_version=1)`）に変え、`'missing servers'`・`'extra key'` の文書から `codex_version` を外す。`'codex_version present'`（protocol 2 文書に `codex_version` を足したもの）を拒否ケースに足す。`servers` 要素の `environment_id` が数値のものも拒否ケースに足す。
5. 承認の試験群（`ApprovalTests`）と `--check` の記録検証（`test_check_record_format_is_validated_as_one_strict_json_document`）の正しい記録を `{"protocol_version":2,"hash":...}` にする。`'wrong version'`・`'dot as wildcard'` ケースは削除し、`'old shape'`（`codex_version` を含む 3 key の記録）と `'protocol 1'` を不正ケースに足す。`test_corrupt_or_foreign_record_requires_reconfirmation` の旧形式の記録（`codex_version` 付き）は再確認になることを確かめる。
6. 旧記録の扱い: `test_old_versioned_record_is_ignored_and_clean_removes_it` を足す。`<project>/0.156.0.json` に旧記録があっても `project-config.json` が無ければ確認プロンプトが出ること、`--clean <dir>` 後に Codex subdirectory ごと消えることを確かめる。
7. 表示: `environment_id` が非 null の server は確認の表示行に `environment: <値>` が出ることを確かめる（`test_each_server_and_approval_question_have_separate_lines` に 1 ケース足す）。

`tests/test_codex_launch.py` の追加分: 142 行・332 行（`build_label` を含む）・430 行の `'label': '1'` を `'2'` にする。

`tests/test_c3c_launch.py`: 113 行・181 行の protocol / 記録を protocol 2 の形にし、`SUPPORTED` 依存を外す。64 行の fake podman が返す label の既定を `'2'` にする（`self.state['label']` の既定値を探して `'2'` に揃える）。

`tests/test_c3c_config.py`:
1. `test_bundled_defaults_are_the_contract_values_and_match_the_codex_helper` を `test_bundled_defaults_are_the_contract_values` に改名し、`CODEX_SUPPORTED_VERSION`・`SUPPORTED_VERSION` の assert 2 行を削除する（`codex-mcp-audit.py` に `SUPPORTED_VERSION` が無いことを `assertNotIn('SUPPORTED_VERSION', helper)` で確かめる）。
2. 606 行の `self.assertIn(DEFAULT_CODEX, result.stderr, '使うなら対応版を案内する')` を `self.assertIn('latest', result.stderr, '使うなら固定版か latest を案内する')` にする。
3. fake podman の label 既定値 `'1'` を `'2'` にする（`self.state = {'image_exists': ..., 'label': '1', ...}` の全箇所）。
4. 358 行の `{SUPPORTED}.json` の承認記録を `project-config.json`・protocol 2 の形にする。

各ファイルで `grep -n "'label': '1'\|codex_version\|SUPPORTED}.json" tests/` が何も出さないことを確かめる。

- [ ] **Step 2: 試験が失敗することを確かめる**

Run: `python3 -m unittest tests.test_codex_launch tests.test_c3c_launch tests.test_c3c_config 2>&1 | tail -5`
Expected: FAIL（launcher はまだ protocol 1・`codex_version` を要求する）

- [ ] **Step 3: launcher の定数と記録パスを変える**

```bash
# Codex の起動時 MCP 審査の protocol（codex-mcp-audit.py・Dockerfile.claude の label と同期）。
# protocol 2（#150）から Codex の版には依存しない。未知 protocol は同じ審査方式として黙認しない。
CODEX_AUDIT_PROTOCOL_VERSION=2
CODEX_AUDIT_PROTOCOL_LABEL=io.c3c.codex-audit-protocol
readonly CODEX_AUDIT_PROTOCOL_VERSION CODEX_AUDIT_PROTOCOL_LABEL
```

`freeze_project_paths()`:

```bash
  # Codex の起動時 MCP 審査の承認記録（#150 の protocol 2）。既存の Claude 記録とは別に、agent 固定の
  # subdirectory へ hash を保存する。版は含めない（旧 <版>.json は読まない）。同じく env 読込前に freeze する。
  CODEX_APPROVAL_DIR="$MCP_APPROVAL_STORE/codex/$PROJECT_NAME"
  CODEX_APPROVAL_RECORD="$CODEX_APPROVAL_DIR/project-config.json"
```

- [ ] **Step 4: `guard_codex_agent` から版の照合を外す**

`case "$value" in` のブロックを次に置き換え、関数前のコメントの「イメージ内の実際の版は起動時に codex-mcp-audit.py が `codex --version` で厳密に照合する」を「起動時審査は Codex の版に依存しない（#150）。固定版・latest のどちらも通し、空ファイル（opt-out）だけを止める」に直す。

```bash
  case "$value" in
    "")
      guard_fail "ERROR: $PROJECT_CONF_DIR/codex-version.txt が空です（Codex の opt-out。このイメージには Codex CLI を導入しません）。Codex を使うには固定版（例: 0.156.0）か latest を書くか、ファイルを削除して同梱 default を使い、-b で再ビルドしてください（npm が必要なため node-version.txt も空にしないでください）。起動を中止します。" ${AGENT_RESELECT_HINT:+"$AGENT_RESELECT_HINT"} || return 1
      ;;
    *)
      [[ ${CHECK_MODE:-0} -eq 1 ]] && echo "[OK]   Codex 版指定: $value（採用元: $origin_text）"
      ;;
  esac
```

- [ ] **Step 5: 記録の生成と静的検証を protocol 2 にする**

```bash
codex_record_content() {
  printf '{"protocol_version":%s,"hash":"%s"}\n' "$CODEX_AUDIT_PROTOCOL_VERSION" "$1"
}
```

`validate_codex_record_file()` の呼び出しを `python3 -I - "$1" "$CODEX_AUDIT_PROTOCOL_VERSION" <<'PYTHON'` にし、Python 側を `path, protocol_version = sys.argv[1:3]`、判定を次にする。

```python
ok = (isinstance(doc, dict) and set(doc) == {'protocol_version', 'hash'}
      and type(doc['protocol_version']) is int and doc['protocol_version'] == int(protocol_version)
      and isinstance(doc['hash'], str) and re.fullmatch(r'[0-9a-f]{64}', doc['hash']) is not None)
```

関数前のコメントの「固定 version」を削る。

- [ ] **Step 6: preflight の protocol 検証と表示を protocol 2 にする**

`run_codex_preflight()`:
- INFO を `echo "INFO: Codex 起動時 MCP 審査: リポジトリの .codex/config.toml の MCP 定義を検査用コンテナで読みます（agent と MCP command は起動しません）" >&2` にする。
- python の引数から `"$CODEX_SUPPORTED_VERSION"` を外し、`source, summary, protocol_version = sys.argv[1:4]` にする。
- 文書の key 集合を `{'protocol_version', 'hash', 'count', 'servers'}` にし、`codex_version` の検査 2 行を削除する。
- server の key 集合を `{'name', 'command', 'args', 'cwd', 'env_keys', 'env_vars', 'environment_id'}` にし、型検査に `and (server['environment_id'] is None or is_str(server['environment_id']))` を足す。
- 表示行を次にする。

```python
    line = '  - %s: %s%s（cwd: %s、env: %s、env_vars: %s%s）' % (
        server['name'], server['command'], ''.join(' ' + arg for arg in server['args']),
        server['cwd'] if server['cwd'] is not None else '-',
        ', '.join(server['env_keys']) or '-', ', '.join(env_vars) or '-',
        '、environment: ' + server['environment_id'] if server['environment_id'] is not None else '')
```

`check_codex_approval()` の WARNING を `"WARNING: リポジトリの .codex/config.toml に、前回の承認から変わっている（または未承認の）ローカル command 定義があります。そのコードは Codex のセッション中に実行され、export された全ての秘密を読めます:"` にする。

次の取り残しも直す。
- 23 行のコメントは Step 3 で置き換え済み。462 行のコメントは Step 3 で置き換え済み。
- 955 行のコメント「値の妥当性（書式・対応版）は」を「値の妥当性（書式）は」にする。
- 1108 行のコメント「protocol 1 文書」を「protocol 2 文書」にする。
- 1197-1216 行の `fail()` のメッセージの「対応版と異なります」を「対応 protocol と異なります」にする。
- 1875 行のコメント「同梱 default（24.18.0 / 対応版 Codex）」を「同梱 default（24.18.0 / Codex 0.156.0）」にする。

最後に `grep -nE 'CODEX_SUPPORTED_VERSION|codex_version|対応版|protocol 1|LIST_ARGS|版不一致' c3c entrypoint.sh Dockerfile.claude codex-mcp-audit.py` を実行し、Codex の版に関する記述が残っていないことを確かめる（Task 2 の entrypoint 229-231 行「protocol 1」「版不一致」・235 行「対応版を書くか」、Dockerfile 152 行・355 行を含む。235 行は「固定版か latest を書くか」にする）。

- [ ] **Step 7: 試験が通ることを確かめる**

Run: `python3 -m unittest tests.test_codex_launch tests.test_c3c_launch tests.test_c3c_config tests.test_codex_entrypoint tests.test_codex_mcp_audit 2>&1 | tail -5`
Expected: `OK`

- [ ] **Step 8: lint と commit**

Run: `./lint.sh`
Expected: 終了コード 0

```bash
git add c3c tests/test_codex_launch.py tests/test_c3c_launch.py tests/test_c3c_config.py
git commit -m "feat: #150 launcher の Codex 版照合を外し protocol 2 の承認記録に切り替える"
```

---

### Task 4: test-build.sh と文書を新しい審査範囲に合わせる

**Files:**
- Modify: `test-build.sh:1874-1892`
- Modify: `README.md`（「利用側プロジェクトの設定」の `codex-version.txt` の行 245 と説明 262、「Codex CLI をセカンドオピニオンとして使う」の手順 1（443）、「Codex CLI を対話で使う」の前提（468）・起動フロー・審査の範囲と限界（482-484）、「変更後の確認」の該当行（709）、`codex-version.txt` を説明する 534 行）
- Modify: `SECURITY-CLAIMS.md` の C-3
- Modify: `docs/development-invariants.md:29`・`:93`
- Modify: `docs/superpowers/specs/2026-09-23-codex-mcp-audit-scope-design.md` の **状態** 行

**Interfaces:**
- Consumes: Task 1〜3 の挙動
- Produces: なし

- [ ] **Step 1: test-build.sh の整合検査を外す**

1877-1880 行のコメントのうち、`CODEX_SUPPORTED_VERSION`・`SUPPORTED_VERSION` との不一致を失敗にする理由の 3 行を削除し、1889-1892 行の `check` 2 件（launcher と helper の `SUPPORTED_VERSION` 一致）を削除する。同梱 default が固定版であることと、イメージ内の `codex --version` が同梱 default と一致する検査は残す。1869 行の `codex-mcp-audit.py --help` の検査は残す。`--help` は `tomllib` の有無を確かめないので、その直後に次の検査を足す。

```bash
check "Codex 審査 helper が使う tomllib（Python 3.11 以上）" podman run --rm --network=none "$IMAGE" python3 -I -c 'import tomllib'
```

Run: `bash -n test-build.sh && grep -c SUPPORTED_VERSION test-build.sh`
Expected: 構文エラーなし、`0`

- [ ] **Step 2: README を直す**

次の内容に置き換える（前後の文は変えない）。
- 245 行の注記を `（例: 0.156.0、または latest。1行のみ。置かなければ同梱 default の 0.156.0、空ファイルは導入しない opt-out）` にする（「起動時 MCP 審査の対応版」「固定版を推奨」を外す）。
- 262 行の `default: 起動時 MCP 審査の対応版 \`0.156.0\`。c3c 第2b-2段階から` を `default: \`0.156.0\`` にする。`latest` の説明と「手順の安定を要するプロジェクトは固定版を推奨する」は残す。
- 443 行の `\`codex-version.txt\`＝対応版 \`0.156.0\`` を `\`codex-version.txt\`＝\`0.156.0\`` にし、`固定版（推奨）または \`latest\`` を `固定版または \`latest\`` にする。
- 468 行を次にする: `` `codex-version.txt` は固定版か `latest`（未指定なら同梱 default の `0.156.0`。npm が必要で、同梱 default の `node-version.txt` か `packages.txt` の `nodejs`/`npm` で導入）。起動時審査は Codex の版に依存しない。プロジェクト側の空ファイル（opt-out）は起動を中止する。起動時審査はイメージ内の python3（3.11 以上。`tomllib` を使う）で行う ``
- 起動フロー（482 行）の (2) の `io.c3c.codex-audit-protocol=1` を `=2` に、(3) を「同じマウント・作業ディレクトリの検査用コンテナ（非 TTY、`compose.codex-preflight.yml`、stdin は `/dev/null`）を起動し、コンテナ内の `codex-mcp-audit.py` がリポジトリ同梱の `/workspace/.codex/config.toml` を読んで、enabled な stdio 定義の canonical hash と表示用情報だけを 1 つの JSON 文書として返す。Codex CLI・agent・MCP の command はこの段階で起動しない」に、(4) の承認記録パスを `.../codex/<project>/project-config.json` に、表示項目に environment（指定時）を足す。(5) の「同じ home・CLI 実体・設定解決で」を「同じファイルを読み直して」にする。
- 審査の範囲と限界（484 行）を次の要点で書き直す: 対象はリポジトリ同梱の `/workspace/.codex/config.toml` の `mcp_servers`（stdio は hash、helper 付きは拒否、helper 無し HTTP は外側のエグレス制限に委ねる）。同じファイルで plugin が有効化されていれば、plugin の中身を読めないため起動前に拒否する（`enabled = false` なら通す）。hash には名前・command・args・cwd・env の値・env_vars・environment_id を含め、timeout 等の診断値は含めない。未知の key・壊れた TOML・型違いは判定不能として停止する。`CODEX_DIR` の user 設定と plugin キャッシュは審査しない（Claude 経路の `~/.claude.json` と同じ。README の #29 の節）。そのため、セッションが `CODEX_DIR` の `config.toml` に MCP を書き足しても次回起動で確認は出ない。検査用コンテナは Codex CLI を実行しないので、旧方式の版取得・一覧取得の期限と cloud config 取得等の副作用の記述は削除する。同じファイルで marketplace が定義されていれば、plugin の取得元を差し替えうるため起動前に拒否する。Codex は設定層を table ごとに深く merge するので、project の `url` だけのエントリが user 層の同名エントリの宛先を変えたり、project の `command` だけのエントリに user 層の `args`・`env` が合わさったりしうる（user 設定を読まないための限界）。`latest` で入った版がリポジトリ設定から新しい実行経路を取り込んでも追えない（網羅性は 0.156.0 で確認）。固定 trust override・hooks・sandbox 設定・実行ファイルの内容・Claude 共有領域の記述は残す。
- 534 行の `Codex CLI（対応版 \`0.156.0\`）の固定版 default` を `Codex CLI（\`0.156.0\`）の固定版 default` にする。
- 709 行の `同梱 default と \`CODEX_SUPPORTED_VERSION\`・\`codex-mcp-audit.py\` の対応版の一致` を削除する。

Run: `grep -n '対応版' README.md`
Expected: Codex の版に関する「対応版」が残っていない（Podman の「対応版」等、無関係な行だけ）

- [ ] **Step 3: SECURITY-CLAIMS C-3 を書き直す**

C-3 を次の内容に置き換える。

```markdown
## C-3

**対象**: `--agent codex` の起動時 MCP 審査（protocol 2、#150）。

**成立条件・脅威モデル**: 信頼する launcher・イメージ・Podman を通常の起動経路で使い、利用者が
表示されたローカル実行定義を確認する。対象はリポジトリ同梱の `/workspace/.codex/config.toml`
（第三者が内容を制御しうる project 設定）で、`CODEX_DIR` の user 設定は運用者自身が書く設定として
対象外にする（Claude 経路の `.mcp.json` ゲートと同じ線引き。README「帰結の重大性で線を引いている」節）。
既存の Claude 用 `.mcp.json` ゲートとは独立している。

**保証する動作**: 対応 protocol の image label を起動前に検査する。検査用コンテナで project 設定を
読み、enabled stdio の名前、command、args、cwd、env、env_vars、environment_id を正規化して hash 化し、
初回・変更時はホストで確認する。project 設定で plugin が有効化されているか marketplace が定義されていれば、確認の前に停止する。
承認記録はホスト側の agent/project 別に保存し、本起動には 1 ファイルだけを `:ro` で渡す。
本起動でも同じファイルを読み直して一致したときだけ Codex へ進む。対象ゼロは空定義として確認なしで記録する。
未知 key・壊れた TOML・型違い・command と url の併記・承認拒否・必要な TTY の欠如・再照合不一致は
停止し、別 CLI へ fallback しない。Codex の版は判定に使わない。

**限界・非対象**:

- `CODEX_DIR` の `config.toml`・plugin キャッシュ・user 層で有効化した plugin は審査しない。
  セッションがそこへ MCP を書き足しても、次回起動の確認では検出しない（Claude 経路の `~/.claude.json` と同じ限界）。
- enabled な定義に `http_headers_helper` がある場合は審査不能として拒否する。helper の無い HTTP と
  disabled server は hash 対象外で、HTTP URL の変更も再承認対象外。通信先は外側の firewall に従う。
- Codex は設定層を table ごとに深く merge する。project の `url` だけのエントリが user 層の同名エントリ
  （helper 付きを含む）の宛先を変えたり、project の `command` だけのエントリに user 層の `args`・`env` が
  合わさったりしうる。確認表示は project 設定の内容だけで、実効の定義とは一致しない場合がある。
- 網羅性（project 層の探索規則、MCP・plugin・marketplace 以外に repo から実行経路を持ち込める設定が無いこと、
  許可 key の集合）は codex-cli 0.156.0 でだけ確認している。`latest` 等で入った別の版が新しい経路を取り込んでも追えない。
- 定義の承認であり、実行ファイル・script・依存パッケージの内容や安全性を保証しない。本起動の
  再照合後の変更、セッション中の設定変更・再接続・plugin の追加、利用者やモデルが直接起動するコマンドは継続監視しない。
- env の値と HTTP header は表示しないが、command/args に秘密を埋め込めば確認表示に出る。
  除去するのは ASCII 制御文字であり、Unicode の bidi 制御等は対象外。内容の秘匿ではない。永続化する承認記録は protocol・hash のみである。
- 固定 repo trust は `.codex/config.toml`、適用対象の hooks・exec policy・sandbox 設定も有効化する。
  MCP 承認はこれらの承認を兼ねず、hooks の信頼確認は Codex の native 機能に委ねる。
  CLI の sandbox/approval 指定は固定するが、追加の書込み先などは native 設定の影響を受ける。
- 審査はイメージ内の python3（3.11 以上）で行う。`tomllib` が無ければ停止する。

**根拠・検証範囲**: `c3c`、`entrypoint.sh`、`codex-mcp-audit.py`、`compose.yml`、
`compose.codex-preflight.yml` と各 Codex 回帰テスト。実装の契約と実機受入は区別し、現在の受入状況は
[README の Codex 節](README.md#codex-cli-を対話で使う) を参照する。

**再確認契機**: 同梱 default の Codex 版を上げるとき。Codex の公開設定形式（`mcp_servers` の key・plugin と marketplace の設定方法）・
project 設定の探索規則・trust、起動経路、承認保存先、マウントの変更時。
```

- [ ] **Step 4: development-invariants を直す**

- 72 行: 「検査・再照合・本起動で home・cwd・CLI 実体・設定解決用 override（…、helper の `LIST_ARGS` と同値）を揃える構成を崩さない」を、「検査（snapshot）と再照合（verify）は同じ `/workspace/.codex/config.toml` を読み、Codex CLI も MCP command も実行しない。本起動は固定の CLI 実体・home・cwd・trust override（`projects={"/workspace"={trust_level="trusted"}}`）で exec する。snapshot は秘密 export の後の現在位置に置くが、CLI を実行しないので順序は境界の要件ではない」に書き換える（同じ行の他の要件は残す）。

- 29 行: 承認記録パスの `mcp-approvals/codex/<project>/<対応版>.json` を `mcp-approvals/codex/<project>/project-config.json` に、`run_codex_preflight()` の説明の `protocol 1 文書` を `protocol 2 文書` にし、「`codex-mcp-audit.py` は Codex CLI を実行せず、リポジトリ同梱の `/workspace/.codex/config.toml` だけを読む。`CODEX_DIR` の設定を審査対象へ戻す場合は #150 の判断（#29 の線引き）を見直す」を 1 文足す。
- 93 行: `（\`24.18.0\` / 起動時 MCP 審査の対応版）` を `（\`24.18.0\` / \`0.156.0\`）` に、`（\`test-build.sh\` が書式と、launcher の \`CODEX_SUPPORTED_VERSION\`・\`codex-mcp-audit.py\` の \`SUPPORTED_VERSION\` との一致を検査する。対応版を上げるときは 3 箇所を同時に変える）` を `（\`test-build.sh\` が書式とイメージ内の版の一致を検査する）` にする。

- [ ] **Step 5: spec の状態行を更新し、実装と文書を 1 commit にまとめる**

spec の **状態** 行を `設計確定（持ち主承認 2026-09-23）。実装計画: docs/superpowers/plans/2026-09-23-issue150-codex-audit-scope.md` にする。

Run: `./lint.sh`
Expected: 終了コード 0

AGENTS.md の「挙動を変えたら README.md の該当節も同じコミットで更新する」に合わせ、Task 1〜3 の commit と本 Task の変更を 1 つの commit にまとめる。`PLAN` は本計画の最新の commit（Task 1 着手前の HEAD）。

```bash
git add test-build.sh README.md SECURITY-CLAIMS.md docs/development-invariants.md docs/superpowers/specs/2026-09-23-codex-mcp-audit-scope-design.md
git reset --soft "$PLAN"
git commit -m "feat: #150 Codex 起動時 MCP 審査をリポジトリの .codex/config.toml に揃え、版の照合を外す"
git log --oneline "$PLAN"..HEAD   # 1 行だけであること
```

---

### Task 5: 実ビルドと実機で受け入れる

**Files:**
- Modify: 本計画の末尾「結果」節（実施結果を追記）

**Interfaces:**
- Consumes: Task 1〜4 の全変更
- Produces: 受入記録

- [ ] **Step 1: 全回帰を実行する**

Run: `./lint.sh && python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: lint 終了コード 0、unittest `OK`

- [ ] **Step 2: test-build.sh を実行する**

Run: `./test-build.sh 2>&1 | tail -20`
Expected: `FAIL: 0`。README「変更後の確認」節で本変更に該当する項目（Codex helper・launcher・entrypoint）を確認する。実行できない項目は理由とともに `not run` と記録する。

- [ ] **Step 3: fixture で実機受入を行う（持ち主の操作を含む）**

一時 fixture（`/tmp` 配下の git repo。`.c3c/env` に `CODEX_DIR` と `GITCONFIG_FILE`、`.c3c/allowed-domains.txt` に `chatgpt.com` と `auth.openai.com`）で次を行う。

1. `.c3c/codex-version.txt` を `latest` にして `c3c codex -b <fixture>` を実行する。Expected: npm の最新（2026-09-23 時点 0.156.1）が入り、版を理由に止まらず、審査（対象 0 件）を経て TUI に入る。`podman run --rm <image> codex --version` で実際の版を記録する。
2. fixture の `.codex/config.toml` に `[mcp_servers.probe]` の stdio 定義（`command = "/bin/true"`）を書いて `c3c codex <fixture>` を実行する。Expected: ホストで確認プロンプトが出る。`n` で Codex が起動しないこと、`y` で起動し、2 回目は確認が省略されることを確認する。
3. `.codex/config.toml` に `[plugins."probe@fxmkt"]\nenabled = true` を足して起動する。Expected: 確認の前に plugin 有効化を理由に停止し、Codex は起動しない。plugin の行を消し、`[marketplaces.fxmkt]\nsource_type = "git"\nsource = "https://example.invalid/r.git"` を足して起動する。Expected: marketplace 定義を理由に停止する。
4. protocol 1 の旧イメージ（Task 前にビルドしたもの）で `-b` なしに起動し、label 不一致で `-b` を案内して止まることを確認する（旧イメージが無ければ `not run`）。

TUI の操作と確認プロンプトへの応答は持ち主が行う。確認プロンプトへの応答を自動化しない。

- [ ] **Step 4: 結果を記録して commit**

本計画の末尾に「結果」節を足し、実行した検証・実測値（版、プロンプトの有無、停止メッセージ）・`not run` とその理由を書く。

```bash
git add docs/superpowers/plans/2026-09-23-issue150-codex-audit-scope.md
git commit -m "docs: #150 の実装検証と実機受入を記録する"
```

---

区分: 境界 — SECURITY-CLAIMS C-3 の保証範囲と、launcher・entrypoint・審査 helper・イメージ label という境界機構を変えるため。計画・実装完了時（PR 前）・PR 後の 3 段階で Claude と Codex の二重レビューを行う。

推奨実装: Opus — セキュリティ境界の変更で、判定基準 2（秘密を読める MCP の審査経路）に当たり、Task 5 は持ち主の対話操作を伴うコンテナ実機受入でもあるため（判定基準 1）。Sonnet は境界変更のため推さない。Codex は host の checkout で完結せず、計画も Task 2〜4 の試験の書き換えが逐語まで確定していないため推さない。
