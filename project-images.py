#!/usr/bin/env python3
"""ホスト上のプロジェクトイメージを診断し、確認できた欠落パスだけを清掃する。"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys

PREFIX = 'claude-container.project-'
LABELS = tuple(PREFIX + suffix for suffix in ('metadata', 'path', 'name'))
IMAGE_NAME = re.compile(r'^localhost/.+_claude-auth-workspace:latest$')


class InspectionError(Exception):
    """検査不能を「対象なし」と混同しないための例外。"""


def valid_path(path):
    return (isinstance(path, str) and path.startswith('/')
            and not path.startswith('//') and '\n' not in path and '\0' not in path
            and os.path.normpath(path) == path)


def project_key(path):
    # GNU tr の ASCII 変換と LC_ALL=C sed に合わせる。str.lower() は使わない。
    base = os.path.basename(path).translate(str.maketrans(
        'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))
    base = re.sub('[^a-z0-9_-]+', '-', base).strip('-')[:40] or 'project'
    digest = hashlib.sha256(os.fsencode(path)).hexdigest()[:8]
    return f'{base}-{digest}'


def image_name(path):
    return f'localhost/{project_key(path)}_claude-auth-workspace:latest'


def path_state(path):
    """到達できる親の下での ENOENT だけを欠落とする。壊れた link は除外する。"""
    if not valid_path(path):
        return 'unverifiable'
    current = '/'
    try:
        for component in path.split('/')[1:]:
            if not component:
                continue
            current = os.path.join(current, component)
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                return 'missing'
            if stat.S_ISLNK(info.st_mode):
                # dangling / ELOOP / EACCES を親成分の欠落として扱わない。
                info = os.stat(current)
            if not stat.S_ISDIR(info.st_mode) or not os.access(current, os.X_OK):
                return 'unverifiable'
        return 'directory'
    except OSError:
        return 'unverifiable'


def read_ledger(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return []
    if not stat.S_ISREG(info.st_mode):
        raise InspectionError('起動台帳が通常ファイルではありません')
    # 最初の検査後に symlink へ交換されても追わない。
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding=sys.getfilesystemencoding(), errors='surrogateescape', newline='') as src:
        if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
            raise InspectionError('起動台帳の種別が変化しました')
        paths = list(dict.fromkeys(line for line in src.read().split('\n') if line))
    if not all(valid_path(p) for p in paths):
        raise InspectionError('起動台帳に正規化された絶対パス以外の行があります')
    return paths


def podman(*args):
    try:
        # 元パスはこのホストで検査するため、接続設定で別ホストへ切り替えない。
        return subprocess.run(['podman', '--remote=false', *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InspectionError(f'Podman の検査・操作を完了できません: {exc}') from exc


def podman_json(*args):
    result = podman(*args)
    if result.returncode:
        raise InspectionError(f'Podman {args[0]} 失敗（終了コード {result.returncode}）: '
                              + result.stderr.strip())
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise InspectionError('Podman の JSON を解析できません') from exc
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise InspectionError('Podman の一覧形式を確認できません')
    return data


def full_id(value):
    if not isinstance(value, str):
        raise InspectionError('イメージ ID が文字列ではありません')
    value = value.removeprefix('sha256:')
    if not re.fullmatch('[0-9a-f]{64}', value):
        raise InspectionError('完全なイメージ ID を確認できません')
    return value


def string_list(value):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
        raise InspectionError('イメージ名の一覧形式を確認できません')
    return value


def parse_image(row, inspect=False):
    image_id = full_id(row.get('Id'))
    if inspect:
        config = row.get('Config')
        if not isinstance(config, dict) or 'RepoTags' not in row:
            raise InspectionError('image inspect の形式を確認できません')
        labels = config.get('Labels')
        names = string_list(row['RepoTags'])
    else:
        if 'Names' not in row and 'RepoTags' not in row:
            raise InspectionError('イメージの現在名を確認できません')
        labels = row.get('Labels')
        names = string_list(row.get('Names')) + string_list(row.get('RepoTags'))
    if labels is None:
        labels = {}
    if not isinstance(labels, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                              for k, v in labels.items()):
        raise InspectionError('イメージラベルの形式を確認できません')
    return {'id': image_id, 'names': sorted(set(names)), 'labels': labels,
            # inspect の History はビルド命令の配列。images の旧名とは別の形式。
            'history': [] if inspect else string_list(row.get('History'))}


def read_inventory():
    images = [parse_image(row) for row in podman_json('images', '--all', '--format', 'json')]
    if len({item['id'] for item in images}) != len(images):
        raise InspectionError('イメージ一覧の ID が重複しています')
    return images


def provenance(item, ledger):
    """戻り値は対応するパス集合と削除可否の根拠。部分ラベルは旧形式へ落とさない。"""
    values = [item['labels'].get(key, '') for key in LABELS]
    matches = {path for path in ledger if image_name(path) in item['names']}
    if not any(values):
        return matches, 'legacy' if len(matches) == 1 else 'unknown'
    schema, path, key = values
    if valid_path(path):
        matches.add(path)
    if schema == '1' and valid_path(path) and key == project_key(path) and len(matches) == 1:
        return matches, 'labeled'
    return matches, 'invalid'


def container_images():
    rows = podman_json('ps', '--all', '--external', '--no-trunc', '--format', 'json')
    references = set()
    for row in rows:
        if row.get('ImageID') == '':
            # --rootfs のコンテナはイメージ参照を持たない。欠落フィールドとは区別する。
            full_id(row.get('Id'))
            continue
        references.add(full_id(row.get('ImageID')))
    return references


def remove_image(item, path):
    data = podman_json('image', 'inspect', item['id'])
    if len(data) != 1:
        raise InspectionError('削除直前のイメージを一意に確認できません')
    fresh = parse_image(data[0], inspect=True)
    if any(fresh[key] != item[key] for key in ('id', 'names', 'labels')):
        raise InspectionError('削除直前にイメージ名・ラベルが変化しました')
    if path_state(path) != 'missing':
        raise InspectionError('削除直前にパスの欠落を確認できなくなりました')
    if item['id'] in container_images():
        raise InspectionError('稼働中・停止中またはビルド用コンテナから参照されています')
    result = podman('rmi', '--no-prune', item['id'])
    if result.returncode:
        raise InspectionError(f'イメージ削除失敗（終了コード {result.returncode}）: '
                              + result.stderr.strip())
    result = podman('image', 'exists', item['id'])
    if result.returncode != 1:
        raise InspectionError(f'削除後の消失を確認できません（終了コード {result.returncode}）')


def report(kind, message):
    print(f'[{kind}] {message}', flush=True)


def diagnose(args):
    ledger = read_ledger(args.ledger)
    if args.project and not all(valid_path(p) for p in args.project):
        raise InspectionError('対象は改行・先頭 // を含まない正規化済み絶対パスで指定してください')
    images = read_inventory()
    classified = [(item, *provenance(item, ledger)) for item in images]
    known = set(ledger)
    for _, paths, origin in classified:
        if origin == 'labeled':
            known.update(paths)
    selected = set(args.project) if args.project else known
    states = {path: path_state(path) for path in sorted(selected)}
    # 書き込み失敗を削除前に検出する。launcher が作った /tmp の一時ファイルだけ。
    if args.result_file:
        with open(args.result_file, 'w', encoding='utf-8') as output:
            json.dump({'paths': [{'path': p, 'state': s} for p, s in states.items()]}, output)
    failed = False
    for path, state in states.items():
        if args.clean_missing and (state == 'unverifiable' or (state == 'missing' and path not in known)):
            report('FAIL', f'パスの欠落または由来を確認できないため清掃しません: {path!r}')
            failed = True
    candidates = []
    unnamed = 0
    for item, paths, origin in classified:
        if args.project and not paths.intersection(selected):
            continue
        if item['names']:
            # Dockerfile を直接ビルドしたテスト用・派生イメージは名前だけでは対象外。
            relevant = (any(item['labels'].get(k) for k in LABELS)
                        or any(IMAGE_NAME.fullmatch(n) for n in item['names']))
        else:
            relevant = (any(k.startswith('claude-container.') for k in item['labels'])
                        or any(IMAGE_NAME.fullmatch(n) for n in item['history']))
        if not relevant:
            continue
        path = next(iter(paths)) if len(paths) == 1 else None
        state = states.get(path, 'unverifiable')
        if not item['names']:
            if origin == 'labeled' and state == 'missing':
                report('WARN', f'名前なし候補を保持します: {item["id"]} 元パス={path!r}')
            else:
                unnamed += 1
            continue
        if origin not in ('labeled', 'legacy'):
            is_failure = args.clean_missing and origin == 'invalid'
            report('FAIL' if is_failure else 'WARN',
                   f'由来が不明・不整合のため保持します: {item["id"]} 名前={item["names"]!r}')
            failed |= is_failure
            continue
        if state == 'directory':
            if path not in ledger:
                report('INFO', f'台帳外ですが元パスが存在するため保持します: {item["id"]} {path!r}')
            continue
        if state != 'missing':
            report('FAIL' if args.clean_missing else 'WARN',
                   f'欠落を確認できないため保持します: {item["id"]} {path!r}')
            failed |= args.clean_missing
            continue
        if item['names'] != [image_name(path)]:
            report('FAIL' if args.clean_missing else 'WARN',
                   f'別名・別タグを持つため保持します: {item["id"]} 名前={item["names"]!r}')
            failed |= args.clean_missing
            continue
        report('INFO', f'欠落パスのイメージ候補: {item["id"]} 元パス={path!r}')
        candidates.append((item, path))
    if unnamed:
        report('INFO', f'名前なしの旧ビルド・中間イメージ等 {unnamed} 件は保持します。')
    report('INFO', '候補の詳細: podman images --all --no-trunc / podman image inspect <id>')
    if not args.clean_missing:
        return int(failed)
    # 全候補を表示し終わってから検査・削除する。取得不能時は一件も削除しない。
    references = container_images() if candidates else set()
    removed = 0
    for item, path in candidates:
        try:
            if item['id'] in references:
                raise InspectionError('稼働中・停止中またはビルド用コンテナから参照されています')
            remove_image(item, path)
            removed += 1
            report('OK', f'イメージを削除しました: {item["id"]} 元パス={path!r}')
        except InspectionError as exc:
            failed = True
            report('FAIL', f'清掃を完了できません: {item["id"]} {exc}')
    if not candidates:
        report('INFO', '削除できる対象イメージはありません。')
    report('INFO', f'削除成功 {removed} 件。台帳・ネットワーク・承認記録・ビルドコンテキストは保持します。')
    report('INFO', '親・中間イメージとキャッシュは保持するため、ディスク回収量は小さい場合があります。')
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--project', action='append', default=[])
    parser.add_argument('--clean-missing', action='store_true')
    parser.add_argument('--result-file')
    args = parser.parse_args()
    if not shutil.which('podman'):
        report('FAIL' if args.clean_missing else 'INFO', 'Podman がないためイメージ診断をスキップします。')
        return int(args.clean_missing)
    try:
        return diagnose(args)
    except (InspectionError, OSError, ValueError) as exc:
        report('FAIL', f'イメージ診断・清掃に失敗しました: {exc}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
