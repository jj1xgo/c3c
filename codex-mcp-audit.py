#!/usr/bin/env python3
"""Codex 起動時 MCP 審査 helper（c3c 第1段階、計画 docs/superpowers/plans/2026-09-20-c3c-phase1-codex-launch.md）。

`snapshot`: 固定絶対パスの Codex CLI に `--version` と `mcp list --json` を問い合わせ、対象版の schema を
厳密に検証し、enabled な stdio 定義だけを canonical JSON にまとめた hash と表示用 metadata を stdout へ
1 つの JSON 文書として出す。`verify <record>`: host が `:ro` で渡した承認記録と現在の snapshot を照合し、
一致時のみ 0 で終了する。

設計上の固定点:
- CLI 実体は `--codex` の絶対パスだけ。PATH 探索や env による差替え・opt-out は持たない。
- native の生 stdout/stderr はメモリ上でのみ扱い、env 値・HTTP header・stderr 本文をログや表示へ出さない。
- native は独立 process group で起動し、成功・失敗・timeout のいずれでも群の停止を確認してから戻る。
- 判定不能（型違い・未知 key・重複 key・非標準定数・未知 transport・helper 付き HTTP・未知版）は fail-closed。
- 表示用文字列は制御文字を除去する（entrypoint/launcher の既存方針と同じ）。hash には元の値を使う。
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = 1
SUPPORTED_VERSION = '0.155.1'
VERSION_LINE = 'codex-cli ' + SUPPORTED_VERSION
LIST_TIMEOUT_SECONDS = 60
VERSION_TIMEOUT_SECONDS = 5
GROUP_STOP_GRACE_SECONDS = 1.0
GROUP_STOP_CONFIRM_SECONDS = 3.0
# 検査と本起動で同じ設定解決を得るための固定 override（計画「検査と本起動の一致」）。
TRUST_OVERRIDE = 'projects={"/workspace"={trust_level="trusted"}}'
LIST_ARGS = ['-c', TRUST_OVERRIDE, 'mcp', 'list', '--json']

ENTRY_KEYS = frozenset(('name', 'enabled', 'disabled_reason', 'transport',
                        'startup_timeout_sec', 'tool_timeout_sec', 'auth_status'))
STDIO_KEYS = frozenset(('type', 'command', 'args', 'env', 'env_vars', 'cwd'))
# env_vars は対象版 mcp_types.rs の untagged enum McpServerEnvVar: 文字列名か {name, source?}。
# source は local/remote。native の serialize では None の source は key ごと省略されるが、Option 型として
# 既知の null も同じ意味として受理する（実測では省略形のみ観測）。hash は受け取った形をそのまま保つ。
ENV_VAR_KEYS = frozenset(('name', 'source'))
ENV_VAR_SOURCES = (None, 'local', 'remote')
INTERRUPT_SIGNALS = (signal.SIGTERM, signal.SIGINT)
HTTP_KEYS = frozenset(('type', 'url', 'bearer_token_env_var', 'http_headers',
                       'env_http_headers', 'http_headers_helper'))
RECORD_KEYS = frozenset(('protocol_version', 'codex_version', 'hash'))
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


def is_str_list(value):
    return isinstance(value, list) and all(is_str(item) for item in value)


def is_str_map(value):
    return isinstance(value, dict) and all(is_str(k) and is_str(v) for k, v in value.items())


def is_env_var(item):
    if is_str(item):
        return True
    if not isinstance(item, dict) or 'name' not in item or not set(item) <= ENV_VAR_KEYS:
        return False
    source = item.get('source')
    return is_str(item['name']) and (source is None or source in ENV_VAR_SOURCES[1:])


def is_env_var_list(value):
    return isinstance(value, list) and all(is_env_var(item) for item in value)


class Interrupted(Exception):
    """SIGTERM/SIGINT を受けた。run_native の finally で群を停止してから main へ伝播する。"""


def raise_interrupt(signum, frame):
    raise Interrupted(signum)


def block_signals():
    return signal.pthread_sigmask(signal.SIG_BLOCK, INTERRUPT_SIGNALS)


def unblock_signals():
    signal.pthread_sigmask(signal.SIG_UNBLOCK, INTERRUPT_SIGNALS)


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
        # JSONDecodeError は ValueError。位置情報だけで本文は出さない。
        raise AuditError(what + ' を単一の JSON 文書として解析できません: ' + sanitize(exc.__class__.__name__)) from None


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def stop_group(proc):
    """process group を SIGTERM→SIGKILL で停止し、群が消えたことを確認する。"""
    pgid = proc.pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + GROUP_STOP_GRACE_SECONDS
        while time.monotonic() < deadline:
            proc.poll()
            if not group_alive(pgid):
                return True
            time.sleep(0.02)
    proc.wait()
    deadline = time.monotonic() + GROUP_STOP_CONFIRM_SECONDS
    while time.monotonic() < deadline:
        if not group_alive(pgid):
            return True
        time.sleep(0.02)
    return False


def run_native(codex, args, timeout, stage):
    """native CLI を独立 process group で実行し、stdout bytes を返す。失敗は段階・経過秒・終了コードで報告する。"""
    started = time.monotonic()
    # Popen の前後で SIGTERM/SIGINT を block し、proc を握ってから unblock する（fork 直後に割り込まれて
    # 子を見失う窓を閉じる）。子は mask を継承するので preexec_fn で元に戻す（この時点で thread は無い）。
    block_signals()
    try:
        proc = subprocess.Popen([codex, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True, preexec_fn=unblock_signals)
    except OSError as exc:
        unblock_signals()
        raise AuditError(f'段階 {stage}: Codex CLI を起動できません: {sanitize(exc.strerror or exc)}') from None
    # 孫プロセスが pipe を継承しても親の終了で判定できるよう、communicate() ではなく wait() を使い、
    # 群停止後に読み切る。読み手は daemon thread なので停止不能でも helper 自体は終了できる。
    output = {}

    def drain(name, stream):
        with stream:
            output[name] = stream.read()

    readers = [threading.Thread(target=drain, args=(name, stream), daemon=True)
               for name, stream in (('stdout', proc.stdout), ('stderr', proc.stderr))]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        unblock_signals()  # 保留中の signal はここで handler が走り、下の finally が群を止める
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        # 停止処理中の追加 signal で子群を取り残さないよう、確認が終わるまで block する。
        block_signals()
        stopped = stop_group(proc)
        for reader in readers:
            reader.join(timeout=GROUP_STOP_CONFIRM_SECONDS)
        unblock_signals()
    elapsed = time.monotonic() - started
    if timed_out:
        raise AuditError(f'段階 {stage}: Codex CLI が期限 {timeout:g} 秒を超えたため timeout として停止しました'
                         f'（経過 {elapsed:.1f} 秒、終了コード: timeout）')
    if not stopped:
        raise AuditError(f'段階 {stage}: Codex CLI の process group の停止を確認できません（経過 {elapsed:.1f} 秒）')
    if any(reader.is_alive() for reader in readers):
        raise AuditError(f'段階 {stage}: Codex CLI の出力の終端を確認できません（経過 {elapsed:.1f} 秒）')
    if proc.returncode != 0:
        raise AuditError(f'段階 {stage}: Codex CLI が終了コード {proc.returncode} で失敗しました（経過 {elapsed:.1f} 秒）')
    return output.get('stdout', b'')


def check_version(codex):
    data = run_native(codex, ['--version'], VERSION_TIMEOUT_SECONDS, 'version')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = ''
    if text.endswith('\n'):
        text = text[:-1]
    if text != VERSION_LINE:
        shown = sanitize(text[:80]) or '(空)'
        raise AuditError(f'段階 version: 対応していない Codex 版です（対応: {VERSION_LINE}、実際: {shown}）。'
                         '対応確認が必要です')
    return SUPPORTED_VERSION


def validate_transport(name, transport):
    if not isinstance(transport, dict):
        raise AuditError(f'MCP server {name}: transport が object ではありません')
    kind = transport.get('type')
    if kind == 'stdio':
        expected = STDIO_KEYS
    elif kind == 'streamable_http':
        expected = HTTP_KEYS
    else:
        raise AuditError(f'MCP server {name}: 未知の transport 型です: {sanitize(kind) if is_str(kind) else type(kind).__name__}')
    if set(transport) != expected:
        raise AuditError(f'MCP server {name}: 対象版と異なる transport フィールドです（{kind}）')
    if kind == 'stdio':
        ok = (is_str(transport['command']) and is_str_list(transport['args'])
              and (transport['env'] is None or is_str_map(transport['env']))
              and is_env_var_list(transport['env_vars'])
              and (transport['cwd'] is None or is_str(transport['cwd'])))
    else:
        ok = (is_str(transport['url'])
              and (transport['bearer_token_env_var'] is None or is_str(transport['bearer_token_env_var']))
              and (transport['http_headers'] is None or is_str_map(transport['http_headers']))
              and (transport['env_http_headers'] is None or is_str_map(transport['env_http_headers']))
              and (transport['http_headers_helper'] is None or is_str(transport['http_headers_helper'])))
    if not ok:
        raise AuditError(f'MCP server {name}: transport フィールドの型が対象版と異なります（{kind}）')
    return kind


def normalize(listing):
    """native 一覧を検証し、hash 対象の enabled stdio 定義（name 順）を返す。"""
    if not isinstance(listing, list):
        raise AuditError('MCP 一覧が top-level array ではありません')
    seen = set()
    servers = []
    for entry in listing:
        if not isinstance(entry, dict):
            raise AuditError('MCP 一覧の要素が object ではありません')
        if set(entry) != ENTRY_KEYS:
            raise AuditError('MCP 一覧の要素が対象版と異なるフィールドを持ちます')
        raw_name = entry['name']
        if not is_str(raw_name):
            raise AuditError('MCP server の name が文字列ではありません')
        name = sanitize(raw_name)
        if not is_bool(entry['enabled']):
            raise AuditError(f'MCP server {name}: enabled が真偽値ではありません')
        if not (entry['disabled_reason'] is None or is_str(entry['disabled_reason'])):
            raise AuditError(f'MCP server {name}: disabled_reason の型が対象版と異なります')
        for key in ('startup_timeout_sec', 'tool_timeout_sec'):
            if not (entry[key] is None or is_number(entry[key])):
                raise AuditError(f'MCP server {name}: {key} の型が対象版と異なります')
        if not (entry['auth_status'] is None or is_str(entry['auth_status'])):
            raise AuditError(f'MCP server {name}: auth_status の型が対象版と異なります')
        transport = entry['transport']
        kind = validate_transport(name, transport)
        if raw_name in seen:
            raise AuditError(f'MCP server {name}: name が重複しています')
        seen.add(raw_name)
        if not entry['enabled']:
            continue
        if kind == 'streamable_http':
            if transport['http_headers_helper'] is not None:
                raise AuditError(f'MCP server {name}: enabled な HTTP 型が http_headers_helper（ローカル command）を持つため、'
                                 '対象版の一覧では実行定義を完全に審査できません。設定を見直してから起動してください')
            continue
        servers.append({'name': raw_name,
                        'transport': {key: transport[key] for key in ('type', 'command', 'args', 'env', 'env_vars', 'cwd')}})
    servers.sort(key=lambda server: server['name'])
    return servers


def canonical_hash(codex_version, servers):
    doc = {'protocol_version': PROTOCOL_VERSION, 'codex_version': codex_version, 'servers': servers}
    text = json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def display_env_var(item):
    if is_str(item):
        return sanitize(item)
    return {key: None if value is None else sanitize(value) for key, value in item.items()}


def display(server):
    transport = server['transport']
    return {'name': sanitize(server['name']),
            'command': sanitize(transport['command']),
            'args': [sanitize(arg) for arg in transport['args']],
            'cwd': None if transport['cwd'] is None else sanitize(transport['cwd']),
            'env_keys': sorted(sanitize(key) for key in (transport['env'] or {})),
            'env_vars': [display_env_var(item) for item in transport['env_vars']]}


def snapshot(codex):
    codex_version = check_version(codex)
    listing = parse_json(run_native(codex, LIST_ARGS, LIST_TIMEOUT_SECONDS, 'list'), 'MCP 一覧の stdout')
    servers = normalize(listing)
    return {'protocol_version': PROTOCOL_VERSION, 'codex_version': codex_version,
            'hash': canonical_hash(codex_version, servers), 'count': len(servers),
            'servers': [display(server) for server in servers]}


def read_record(path):
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError as exc:
        raise AuditError(f'承認記録を読めません: {sanitize(exc.strerror or exc)}') from None
    record = parse_json(data, '承認記録')
    if not isinstance(record, dict) or set(record) != RECORD_KEYS:
        raise AuditError('承認記録の形式が対象版と異なります')
    if type(record['protocol_version']) is not int or record['protocol_version'] != PROTOCOL_VERSION:
        raise AuditError('承認記録の protocol_version が対応版と異なります')
    if not is_str(record['codex_version']) or record['codex_version'] != SUPPORTED_VERSION:
        raise AuditError('承認記録の codex_version が対応版と異なります')
    if not is_str(record['hash']) or not HASH_PATTERN.match(record['hash']):
        raise AuditError('承認記録の hash の形式が不正です')
    return record


def verify(codex, record_path):
    record = read_record(record_path)
    current = snapshot(codex)
    if current['hash'] != record['hash']:
        raise AuditError('MCP 実行定義が承認記録と一致しません（検査後に設定が変わった可能性）。起動を中止します')
    print(f'INFO: Codex MCP 審査: 承認記録と一致（対象 {current["count"]} 件）。OK', file=sys.stderr)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='codex-mcp-audit.py', allow_abbrev=False)
    parser.add_argument('--codex', required=True, help='Codex CLI 実体の絶対パス')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('snapshot')
    sub.add_parser('verify').add_argument('record')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    for signum in INTERRUPT_SIGNALS:
        signal.signal(signum, raise_interrupt)
    try:
        if not os.path.isabs(args.codex):
            raise AuditError('--codex には Codex CLI 実体の絶対パスを指定してください')
        if not os.path.isfile(args.codex) or not os.access(args.codex, os.X_OK):
            raise AuditError(f'Codex CLI 実体が見つからないか実行できません: {sanitize(args.codex)}')
        if args.command == 'snapshot':
            sys.stdout.write(json.dumps(snapshot(args.codex), ensure_ascii=False) + '\n')
            sys.stdout.flush()
        else:
            verify(args.codex, args.record)
    except AuditError as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1
    except Interrupted as exc:
        print(f'ERROR: signal {exc.args[0]} を受信したため Codex MCP 審査を中止しました（native の process group は停止済み）',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
