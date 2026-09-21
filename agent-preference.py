#!/usr/bin/env python3
"""c3c の CLI 選択記憶（前回正常終了した CLI）のホスト側 helper。

launcher（`c3c` 入口）だけが `python3 -I` で呼ぶ。秘密を読まず、プロジェクト側の設定（`env`）や
シェル環境から保存先・値を変えられない（保存先は launcher が `$HOME` から確定した state directory を
引数で渡す）。記憶は承認記録ではなく列挙値の利便設定で、ビルドコンテキストやイメージへはコピーしない。

    key   <directory>                       stdout にキー（sha256 64桁）。rc 0=キー出力、4=診断不能
    read  <state-directory> <key>           stdout に claude/codex。rc 0=有効、3=未作成、4=破損・診断不能
    write <state-directory> <key> <agent>   rc 0=保存、1=失敗

識別文字列は Git の場合 `git\\0<realpath(common-dir)>`、非 Git は `path\\0<realpath(directory)>`。
同じ repo の linked worktree・symlink 別名・サブディレクトリは同じキー、別 clone は別キーになる。
Git 子プロセスには継承した `GIT_*` を渡さず、system/global 設定を無効にして対象ディレクトリから解決する。
祖先に `.git` があるのに解決できない（壊れた gitfile・権限不足・古い Git 等）場合は path 単位へ落とさず
診断不能（rc 4）にする。
"""

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile

SCHEMA = 1
AGENTS = ('claude', 'codex')
KEY_RE = re.compile(r'^[0-9a-f]{64}$')
MAX_FILE_SIZE = 4096
PREF_DIR_NAME = 'agent-preferences'
GIT_TIMEOUT_SECONDS = 10

RC_OK = 0
RC_WRITE_FAILED = 1
RC_ABSENT = 3
RC_UNDIAGNOSABLE = 4


def log(message):
    print('agent-preference: ' + message, file=sys.stderr)


def fs_bytes(text):
    return os.fsencode(text)


# ---- key ----------------------------------------------------------------

def has_git_ancestor(directory):
    """対象から祖先へ `.git` の有無を調べる。True=あり、False=なし、None=診断不能。

    `.git` が gitfile（通常ファイル）か `HEAD` を持つディレクトリなら「あり」（解決は git に任せ、壊れていれば
    git が失敗して診断不能になる）。空の `.git` ディレクトリだけは Git と同じく無視して親へ進む。
    それ以外の異常 — dangling symlink、非空なのに `HEAD` の無いディレクトリ、FIFO 等の非ディレクトリ、
    中を調べられない（EACCES 等）— は None を返す。Git 自身はこれらを無視して外側の repo へ辿り着けるが、
    helper はそこで別 repo（または path 単位）の記憶を採用しない。
    """
    current = directory
    while True:
        candidate = os.path.join(current, b'.git')
        try:
            st = os.lstat(candidate)
        except FileNotFoundError:
            st = None
        except OSError:
            return None
        if st is not None:
            if stat.S_ISLNK(st.st_mode):
                # リンク先を辿る。dangling・辿れないリンクは診断不能。
                try:
                    st = os.stat(candidate)
                except OSError:
                    return None
            if stat.S_ISREG(st.st_mode):
                return True
            if not stat.S_ISDIR(st.st_mode):
                return None
            try:
                entries = os.listdir(candidate)
            except OSError:
                return None
            if not entries:
                pass
            elif b'HEAD' in entries:
                return True
            else:
                return None
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def git_environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update({
        'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_CONFIG_SYSTEM': '/dev/null',
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_OPTIONAL_LOCKS': '0',
        'LC_ALL': 'C',
    })
    return env


def resolve_git_common_dir(directory):
    """`git rev-parse --path-format=absolute --git-common-dir` の実体パス。失敗は None。"""
    try:
        result = subprocess.run(
            ['git', '-C', directory, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
            env=git_environment(), stdin=subprocess.DEVNULL, capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        log('git を実行できません: %s' % error)
        return None
    if result.returncode != 0:
        log('git で common directory を解決できません（rc=%d）: %s'
            % (result.returncode, result.stderr.decode('utf-8', 'replace').strip()))
        return None
    lines = result.stdout.splitlines()
    if len(lines) != 1 or not lines[0].startswith(b'/'):
        log('git の出力が絶対パス 1 行ではありません')
        return None
    common = lines[0]
    # realpath(strict=) は Python 3.10 以降のため使わず（ホストは 3.9 以上）、解決後に実在を確認する。
    real = os.path.realpath(common)
    if not os.path.isdir(real):
        log('common directory を実体に解決できません、またはディレクトリではありません')
        return None
    return real


def command_key(argv):
    if len(argv) != 1:
        log('使い方: key <directory>')
        return RC_UNDIAGNOSABLE
    directory = fs_bytes(argv[0])
    real_dir = os.path.realpath(directory)
    if not os.path.isdir(real_dir):
        log('ディレクトリを解決できません、またはディレクトリではありません')
        return RC_UNDIAGNOSABLE
    ancestor = has_git_ancestor(real_dir)
    if ancestor is None:
        log('祖先に不完全・辿れない・調べられない .git があるため、CLI 選択の記憶は使いません（別 repo や path 単位へは倒しません）')
        return RC_UNDIAGNOSABLE
    if ancestor:
        common = resolve_git_common_dir(real_dir)
        if common is None:
            log('祖先に .git があるのに Git として解決できないため、CLI 選択の記憶は使いません')
            return RC_UNDIAGNOSABLE
        identity = b'git\0' + common
    else:
        identity = b'path\0' + real_dir
    sys.stdout.write(hashlib.sha256(identity).hexdigest() + '\n')
    return RC_OK


# ---- read ---------------------------------------------------------------

def valid_key(key):
    return isinstance(key, str) and KEY_RE.fullmatch(key) is not None


def preference_dir(state_dir):
    return os.path.join(fs_bytes(state_dir), fs_bytes(PREF_DIR_NAME))


def preference_path(state_dir, key):
    return os.path.join(preference_dir(state_dir), fs_bytes(key + '.json'))


def directory_is_plain(path):
    """symlink でない実ディレクトリだけを許す（保存先の付け替えを拒否する）。"""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    return stat.S_ISDIR(st.st_mode)


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def reject_constant(_name):
    raise ValueError('non-standard constant')


def parse_document(data):
    text = data.decode('utf-8')
    doc = json.loads(text, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_constant)
    if not isinstance(doc, dict) or set(doc) != {'schema', 'agent'}:
        raise ValueError('unexpected keys')
    schema = doc['schema']
    if type(schema) is not int or schema != SCHEMA:
        raise ValueError('unsupported schema')
    agent = doc['agent']
    if type(agent) is not str or agent not in AGENTS:
        raise ValueError('unknown agent')
    return agent


def command_read(argv):
    if len(argv) != 2:
        log('使い方: read <state-directory> <key>')
        return RC_UNDIAGNOSABLE
    state_dir, key = argv
    if not valid_key(key):
        log('キーの形式が不正です')
        return RC_UNDIAGNOSABLE
    pref_dir = preference_dir(state_dir)
    plain = directory_is_plain(pref_dir)
    if plain is None:
        return RC_ABSENT
    if not plain:
        log('記憶ディレクトリが実ディレクトリではありません')
        return RC_UNDIAGNOSABLE
    path = preference_path(state_dir, key)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return RC_ABSENT
    except OSError as error:
        log('記憶ファイルを調べられません: %s' % error)
        return RC_UNDIAGNOSABLE
    if not stat.S_ISREG(st.st_mode):
        log('記憶ファイルが通常ファイルではありません')
        return RC_UNDIAGNOSABLE
    if st.st_size > MAX_FILE_SIZE:
        log('記憶ファイルが大きすぎます')
        return RC_UNDIAGNOSABLE
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        log('記憶ファイルを開けません: %s' % error)
        return RC_UNDIAGNOSABLE
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_SIZE:
            log('記憶ファイルの種別または大きさが不正です')
            return RC_UNDIAGNOSABLE
        data = os.read(fd, MAX_FILE_SIZE + 1)
    except OSError as error:
        log('記憶ファイルを読めません: %s' % error)
        return RC_UNDIAGNOSABLE
    finally:
        os.close(fd)
    if len(data) > MAX_FILE_SIZE:
        log('記憶ファイルが大きすぎます')
        return RC_UNDIAGNOSABLE
    try:
        agent = parse_document(data)
    except (ValueError, UnicodeDecodeError) as error:
        log('記憶ファイルの内容が不正です: %s' % error)
        return RC_UNDIAGNOSABLE
    sys.stdout.write(agent + '\n')
    return RC_OK


# ---- write --------------------------------------------------------------

def ensure_private_dir(path):
    """symlink でない実ディレクトリを用意する。新規作成時だけ 0700 にし（umask に依らない）、既存の
    mode は変えない。既存が symlink・非ディレクトリなら失敗。同時作成（EEXIST）は再検査して受け入れる。"""
    plain = directory_is_plain(path)
    if plain is None:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            plain = directory_is_plain(path)
        else:
            os.chmod(path, 0o700)
            return
    if not plain:
        raise OSError('%s が実ディレクトリではありません' % os.fsdecode(path))


def write_all(fd, data):
    """全 byte を書き終えるまで write(2) を繰り返す。短い書込（RLIMIT_FSIZE・ディスク満杯等）を成功扱いしない。
    書けない（0 byte が返る）場合は OSError にして呼び出し元で rc1 にする。"""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError('write(2) が進みません（%d byte 残）' % len(view))
        view = view[written:]


def command_write(argv):
    # RLIMIT_FSIZE 超過時の SIGXFSZ（既定は強制終了）は無視し、write(2) の EFBIG を通常の失敗として扱う。
    # 強制終了されると一時ファイルの除去と rc1 の報告ができないため、明示的に無視する。
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    if len(argv) != 3:
        log('使い方: write <state-directory> <key> <agent>')
        return RC_WRITE_FAILED
    state_dir, key, agent = argv
    if not valid_key(key):
        log('キーの形式が不正です')
        return RC_WRITE_FAILED
    if agent not in AGENTS:
        log('agent の値が不正です')
        return RC_WRITE_FAILED
    pref_dir = preference_dir(state_dir)
    path = preference_path(state_dir, key)
    document = json.dumps({'schema': SCHEMA, 'agent': agent}, separators=(',', ':')).encode('utf-8') + b'\n'
    tmp_path = None
    try:
        ensure_private_dir(fs_bytes(state_dir))
        ensure_private_dir(pref_dir)
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(st.st_mode):
                raise OSError('保存先が通常ファイルではありません')
        fd, tmp_path = tempfile.mkstemp(prefix=b'.tmp-', dir=pref_dir)
        try:
            os.fchmod(fd, 0o600)
            write_all(fd, document)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, path)
        tmp_path = None
    except OSError as error:
        log('CLI 選択を保存できません: %s' % error)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return RC_WRITE_FAILED
    return RC_OK


def main(argv):
    if not argv:
        log('使い方: key <directory> | read <state-directory> <key> | write <state-directory> <key> <agent>')
        return 2
    command, rest = argv[0], argv[1:]
    if command == 'key':
        return command_key(rest)
    if command == 'read':
        return command_read(rest)
    if command == 'write':
        return command_write(rest)
    log('不明なサブコマンドです: %s' % command)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
