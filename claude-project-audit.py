#!/usr/bin/env python3
"""Claude 経路の project 設定ゲート helper（protocol 1、#163。設計 docs/superpowers/specs/2026-09-26-claude-project-settings-gate-design.md）。

`snapshot`: --root（コンテナ内では /workspace）の `.claude/settings.json`・`.claude/settings.local.json` を
ファイル全体で hash し、表示用の行と合わせて JSON 1 文書を stdout へ出す。
`verify <record>`: host が `:ro` で渡した承認記録と照合する。0 = 通す、3 = 確認が要る、1 = 止める。

設計上の固定点:
- 対象はモデルや利用者の呼び出しを待たずに起動時に効く設定だけ（#29）。skills・agents・commands は対象外。
- plugin の有効化・plugin の読み込み先を変える env・marketplace・skills-directory plugin・.mcp.json の
  headersHelper は、確認の前に止める（中身は読まない）。
- 判定不能（壊れた JSON・型違い・root の外へ出る symlink・dangling・循環・非通常ファイル・読み取り失敗・
  上限超過）は fail-closed。存在しないことは「対象なし」。
- 判定・表示・hash は 1 回の読み取りの同じバイト列から作る。
- git は実行しない。表示用文字列は ASCII 制御文字を除去する。hash には元のバイト列を使う。
"""

import argparse
import hashlib
import json
import os
import re
import stat
import sys

PROTOCOL_VERSION = 1
HASHED_FILES = ('.claude/settings.json', '.claude/settings.local.json')
MCP_FILE = '.mcp.json'
SKILLS_DIR = '.claude/skills'
FILE_LIMIT = 1024 * 1024
DISPLAY_LINES = 200
DOMAIN = b'c3c-claude-project-audit\x00v1\x00'
PLUGIN_ENV_PREFIX = 'CLAUDE_CODE_PLUGIN_'
RECORD_KEYS = frozenset(('protocol_version', 'hash'))
HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')
CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')
EXIT_STOP = 1
EXIT_REVIEW = 3


class Undecidable(Exception):
    """判定不能。fail-closed で止める。"""


class Blocked(Exception):
    """確認を出さずに止める判定。"""


def sanitize(value):
    return CONTROL_CHARS.sub('', str(value))


def within(real, root_real):
    return real == root_real or real.startswith(root_real + os.sep)


def resolve(root_real, rel):
    """rel を root の中で解決した実パスを返す。どこかの段が存在しなければ None。
    root の外へ出る・dangling・循環する symlink は Undecidable。"""
    current = root_real
    for part in rel.split('/'):
        candidate = os.path.join(current, part)
        # lexists は権限エラーでも False を返すので使わない。無いことだけを「対象なし」にする。
        try:
            os.lstat(candidate)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except OSError as exc:
            raise Undecidable(f'{rel} を確かめられません（{sanitize(exc.strerror or exc)}）') from None
        real = os.path.realpath(candidate)
        try:
            os.stat(real)
        except OSError as exc:
            raise Undecidable(f'{rel} を解決できません（{sanitize(exc.strerror or exc)}）') from None
        if not within(real, root_real):
            raise Undecidable(f'{rel} がワークスペースの外を指しています')
        current = real
    return current


def read_regular(real, rel):
    try:
        fd = os.open(real, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise Undecidable(f'{rel} を読めません（{sanitize(exc.strerror or exc)}）') from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Undecidable(f'{rel} が通常ファイルではありません')
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > FILE_LIMIT:
                raise Undecidable(f'{rel} が上限（{FILE_LIMIT} バイト）を超えています')
            chunks.append(chunk)
        return b''.join(chunks)
    except OSError as exc:
        raise Undecidable(f'{rel} を読めません（{sanitize(exc.strerror or exc)}）') from None
    finally:
        os.close(fd)


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def reject_constant(_name):
    raise ValueError('non-standard constant')


def parse_object(data, rel):
    try:
        doc = json.loads(data.decode('utf-8'), object_pairs_hook=strict_pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError):
        raise Undecidable(f'{rel} を JSON として読めません（壊れている・重複 key・非標準の値）') from None
    if not isinstance(doc, dict):
        raise Undecidable(f'{rel} の最上位がオブジェクトではありません')
    return doc


def table(doc, key, rel):
    value = doc.get(key, {})
    if not isinstance(value, dict):
        raise Undecidable(f'{rel} の {key} がオブジェクトではありません')
    return value


def check_settings(doc, rel):
    enabled = sorted(name for name, value in table(doc, 'enabledPlugins', rel).items() if value is not False)
    if enabled:
        raise Blocked(f'{rel} の enabledPlugins で plugin が有効になっています（{sanitize(", ".join(enabled))}）')
    markets = sorted(table(doc, 'extraKnownMarketplaces', rel))
    if markets:
        raise Blocked(f'{rel} の extraKnownMarketplaces に marketplace があります（{sanitize(", ".join(markets))}）')
    plugin_env = sorted(name for name in table(doc, 'env', rel) if name.startswith(PLUGIN_ENV_PREFIX))
    if plugin_env:
        raise Blocked(f'{rel} の env に plugin の読み込み先を変える変数があります（{sanitize(", ".join(plugin_env))}）')


def check_mcp(root_real):
    real = resolve(root_real, MCP_FILE)
    if real is None:
        return
    servers = table(parse_object(read_regular(real, MCP_FILE), MCP_FILE), 'mcpServers', MCP_FILE)
    helpers = []
    for name, server in servers.items():
        if not isinstance(server, dict):
            raise Undecidable(f'{MCP_FILE} の mcpServers.{sanitize(name)} がオブジェクトではありません')
        if 'headersHelper' in server:
            helpers.append(name)
    if helpers:
        raise Blocked(f'{MCP_FILE} に headersHelper を持つサーバーがあります（{sanitize(", ".join(sorted(helpers)))}）')


def check_skills_plugins(root_real):
    skills = resolve(root_real, SKILLS_DIR)
    if skills is None or not os.path.isdir(skills):
        return
    try:
        names = sorted(os.listdir(skills))
    except OSError as exc:
        raise Undecidable(f'{SKILLS_DIR} を列挙できません（{sanitize(exc.strerror or exc)}）') from None
    for name in names:
        rel = f'{SKILLS_DIR}/{name}/.claude-plugin/plugin.json'
        if resolve(root_real, rel) is not None:
            raise Blocked(f'skills-directory plugin があります（{sanitize(rel)}）')


def canonical_hash(files):
    digest = hashlib.sha256(DOMAIN)
    for rel, data in sorted(files, key=lambda item: item[0].encode('utf-8')):
        path = rel.encode('utf-8')
        digest.update(len(path).to_bytes(8, 'big') + path + len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest()


def display(files):
    lines = []
    for rel, data in files:
        lines.append(f'--- {rel} ---')
        body = data.decode('utf-8').splitlines()
        lines.extend('  ' + sanitize(line) for line in body[:DISPLAY_LINES])
        if len(body) > DISPLAY_LINES:
            lines.append(f'  （以下 {len(body) - DISPLAY_LINES} 行を省略。hash はファイル全体から計算しています）')
    return lines


def snapshot(root):
    root_real = os.path.realpath(root)
    if not os.path.isdir(root_real):
        raise Undecidable('--root がディレクトリではありません')
    files = []
    for rel in HASHED_FILES:
        real = resolve(root_real, rel)
        if real is None:
            continue
        data = read_regular(real, rel)
        # 0 バイトは何も設定できない（c3c 自身が ~/.claude/settings.json を 0 バイトで作るため、$HOME を
        # 作業ディレクトリにしたときに止めない）。hash の対象には残し、中身が入れば変更として確認になる。
        if data:
            check_settings(parse_object(data, rel), rel)
        files.append((rel, data))
    check_mcp(root_real)
    check_skills_plugins(root_real)
    return {'protocol_version': PROTOCOL_VERSION, 'hash': canonical_hash(files), 'count': len(files),
            'lines': display(files)}


def read_record_hash(path):
    """承認記録の hash。空・壊れている・別 protocol は None（記録なしと同じ扱い）。"""
    try:
        with open(path, 'rb') as handle:
            data = handle.read(4096)
        record = json.loads(data.decode('utf-8'), object_pairs_hook=strict_pairs, parse_constant=reject_constant)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if (not isinstance(record, dict) or set(record) != RECORD_KEYS or type(record['protocol_version']) is not int
            or record['protocol_version'] != PROTOCOL_VERSION or not isinstance(record['hash'], str)
            or not HASH_PATTERN.match(record['hash'])):
        return None
    return record['hash']


def verify(root, record_path):
    current = snapshot(root)
    if current['count'] == 0:
        print('INFO: Claude project 設定ゲート: 対象の設定はありません。OK', file=sys.stderr)
        return 0
    if read_record_hash(record_path) == current['hash']:
        print(f'INFO: Claude project 設定ゲート: 承認記録と一致（対象 {current["count"]} 件）。OK', file=sys.stderr)
        return 0
    for line in current['lines']:
        print(line, file=sys.stderr)
    return EXIT_REVIEW


def parse_args(argv):
    parser = argparse.ArgumentParser(prog='claude-project-audit.py', allow_abbrev=False)
    parser.add_argument('--root', required=True, help='審査するワークスペースの絶対パス（コンテナ内では /workspace）')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('snapshot')
    sub.add_parser('verify').add_argument('record')
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        # argparse の誤り（rc 2）も「止める」に寄せる。--help は 0。
        return 0 if exc.code in (0, None) else EXIT_STOP
    try:
        if not os.path.isabs(args.root):
            raise Undecidable('--root には絶対パスを指定してください')
        if args.command == 'snapshot':
            sys.stdout.write(json.dumps(snapshot(args.root), ensure_ascii=True) + '\n')
            sys.stdout.flush()
            return 0
        return verify(args.root, args.record)
    except Blocked as exc:
        print(f'ERROR: Claude project 設定ゲート: {exc}。リポジトリの設定からは許可しません。起動を中止します', file=sys.stderr)
    except Undecidable as exc:
        print(f'ERROR: Claude project 設定ゲート: 判定できません: {exc}。起動を中止します', file=sys.stderr)
    return EXIT_STOP


if __name__ == '__main__':
    sys.exit(main())
