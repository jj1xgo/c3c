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
        raise AuditError('承認記録の protocol_version が対応 protocol と異なります')
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
