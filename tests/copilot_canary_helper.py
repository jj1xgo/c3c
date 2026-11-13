#!/usr/bin/env python3
"""Copilot の受け入れ（canary）の判定のヘルパー。tests/copilot-canary.sh が python3 -I で呼ぶ。

サブコマンド:
  judge EVENTS EXPECTED_COMMAND OUTER_USER OUTER_NET SESSION_ID
      その回の events.jsonl から、bash の実行がちょうど 1 回で、打たれたコマンドが EXPECTED_COMMAND と
      1 字も違わず、その実行の結果の出力が期待の値か判定する。モデルの返答の文（assistant.message）は見ない。
      標準出力の 1 行目は PASS か FAIL: <理由>; …、2 行目は credits=<小数> か credits=unknown。
      rc は PASS で 0、FAIL で 1、引数の誤りで 2。
  weaken SETTINGS
      sandbox.userPolicy.network.allowOutbound を true にして書き戻し、読み直して確かめる。rc 0／1。
  settings-match SETTINGS TEMPLATE WORKDIR
      SETTINGS が、TEMPLATE の sandbox.userPolicy.filesystem.readonlyPaths に [WORKDIR] を入れたものと、
      葉の型も含めて等しければ rc 0、違えば理由を出して rc 1。
  spent-log FILE ID MONTH CREDITS WHAT
      FILE に {"id", "month", "credits", "what"} の 1 行を追記する。誤りは rc 2 で何も書かない。

標準ライブラリだけを使う。トークンは読まない。
"""

import json
import math
import os
import re
import stat
import sys
import tempfile

KEYS = ('curl_rc', 'secret_rc', 'home_rc', 'tok_len', 'gh_len', 'outer_environ', 'w_rc')
RC_KEYS = ('curl_rc', 'secret_rc', 'home_rc', 'w_rc')
ZERO_KEYS = ('tok_len', 'gh_len', 'outer_environ')
# rc の値のうち、塞いだ結果と読めるもの。0（成功）、126・127（コマンドが実行できない・無い）、
# 128 以上（信号での終了）は、塞いだ証拠にならない。
GOOD_RC = range(1, 126)

# 数字は ASCII だけ（全角の数字を通さない）。行全体で当てる（$ が末尾の改行の前でも当たるのを避ける）。
USER_RE = re.compile(r'user:\[([0-9]+)\]', re.ASCII)
NET_RE = re.compile(r'net:\[([0-9]+)\]', re.ASCII)
# ip -brief link の行: 名前、大文字の状態（一覧で当てない。TESTING など知らない状態も数える）、残り。
IFACE_RE = re.compile(r'(\S+)\s+([A-Z][A-Z_]*)(?:\s.*)?', re.ASCII)
KV_RE = re.compile(r'(?:(?<=\s)|^)(' + '|'.join(KEYS) + r')=([0-9]+)(?=\s|$)', re.MULTILINE | re.ASCII)
DIGITS_RE = re.compile(r'[0-9]+', re.ASCII)
MONTH_RE = re.compile(r'[0-9]{4}-[0-9]{2}', re.ASCII)
# コマンドの中の「cat <パス> >/dev/null; echo "<key>=$?"」。その key の rc は、cat 自身がそのパスを読めなかった
# 行があるときだけ塞いだ結果と読む（sandbox で /dev/null に書けないと、読めても redirect で rc 1 になるため）。
CAT_RC_RE = re.compile(r'cat (\S+) >/dev/null; echo "(' + '|'.join(RC_KEYS) + r')=\$\?"')
CAT_DENIED = ('No such file or directory', 'Permission denied')
# curl の出力の行の始まり: stderr の「curl: (N) …」（前に stdout の状態コードが付くことがある）か、
# stdout の「<状態コード> curl_rc=…」。名前に curl を含むインターフェースの行（curl0 など）とは分ける。
CURL_START_RE = re.compile(r'(?:[0-9]{3})?curl: \(|[0-9]{3} curl_rc=', re.ASCII)
# curl -w "%{http_code}" の状態コード。続く echo " curl_rc=$?" か、間に挟まった stderr の「curl: (」の直前の 3 桁。
HTTP_CODE_RE = re.compile(r'(?<![0-9])([0-9]{3})(?= curl_rc=|curl: \()', re.ASCII)
CREDITS_RE = re.compile(r'[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?', re.ASCII)


def _one_line(value):
    """理由に埋め込む値を 1 行にする（改行で出力の 2 行目を偽造させない）。"""
    text = value if isinstance(value, str) else repr(value)
    return re.sub(r'[\x00-\x1f\x7f\u0085\u2028\u2029]', '?', text)


def _dict(value):
    return value if isinstance(value, dict) else {}


def _credits(snapshot):
    snapshot = _dict(snapshot)
    if snapshot.get('aiCreditsStatus') != 'complete':
        return None
    nano = snapshot.get('totalNanoAiu')
    if isinstance(nano, bool) or not isinstance(nano, (int, float)):
        return None
    if not math.isfinite(nano) or nano < 0:
        return None
    return nano / 1e9


def _judge_output(content, outer_user, outer_net, command):
    reasons = []
    lines = content.split('\n')
    for path, key in CAT_RC_RE.findall(command):
        expected = {f'cat: {path}: {why}' for why in CAT_DENIED}
        if not any(line.rstrip() in expected for line in lines):
            reasons.append(f'{key}: cat が {_one_line(path)} を読めなかった行が無い')
    for name, regex, outer in (('user', USER_RE, outer_user), ('net', NET_RE, outer_net)):
        found = [m.group(1) for m in (regex.fullmatch(line.strip()) for line in lines) if m]
        if len(found) != 1:
            reasons.append(f'{name} の名前空間の行が {len(found)} 個')
        elif found[0] == outer:
            reasons.append(f'{name} の名前空間が外側と同じ')
    # ip -brief link の出力は、net: の行の次から、curl の出力（stderr の「curl: (6) …」か「000 curl_rc=…」の形）の
    # 行の前まで。その範囲の行は、どれもインターフェースの行として読めなければならない。
    net_rows = [i for i, line in enumerate(lines) if NET_RE.fullmatch(line.strip())]
    if len(net_rows) == 1:
        section = []
        for line in lines[net_rows[0] + 1:]:
            if CURL_START_RE.match(line):
                break
            section.append(line.rstrip())
        unreadable = [line for line in section if not IFACE_RE.fullmatch(line)]
        ifaces = [IFACE_RE.fullmatch(line).group(1) for line in section if IFACE_RE.fullmatch(line)]
        if unreadable:
            reasons.append(f'ip -brief link の範囲に読めない行がある: {_one_line(repr(unreadable))}')
        elif ifaces != ['lo']:
            reasons.append(f'インターフェースが lo の 1 つだけでない: {_one_line(repr(ifaces))}')
    # 状態コードが 000（通信できなかった）でなければ、curl_rc が 0 でなくても塞いだ結果と読まない
    # （/dev/null に書けないと 200 curl_rc=23、ボディの途中の打ち切りで 200 curl_rc=28 になる）。
    codes = HTTP_CODE_RE.findall(content)
    if codes != ['000']:
        reasons.append(f'curl の状態コードが 000 の 1 つだけでない: {_one_line(repr(codes))}')
    values = {}
    for match in KV_RE.finditer(content):
        values.setdefault(match.group(1), []).append(int(match.group(2)))
    for key in KEYS:
        got = values.get(key, [])
        if len(got) != 1:
            reasons.append(f'{key} が {len(got)} 回')
            continue
        value = got[0]
        if key in RC_KEYS and value not in GOOD_RC:
            reasons.append(f'{key}={value}')
        if key in ZERO_KEYS and value != 0:
            reasons.append(f'{key}={value}')
    return reasons


def judge(events_path, expected_command, outer_user, outer_net, session_id):
    """不合格の理由の一覧（空なら合格）と、クレジット（分からなければ None）を返す。"""
    try:
        with open(events_path, encoding='utf-8') as f:
            raw_lines = f.read().split('\n')  # splitlines は U+2028 なども行の区切りにするので使わない
    except (OSError, UnicodeDecodeError):
        return ['events.jsonl が無い'], None

    reasons = []
    events = []
    for number, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            reasons.append(f'events.jsonl の {number} 行目が JSON でない')
            continue
        if isinstance(event, dict):
            events.append(event)

    def of_type(name):
        return [e for e in events if e.get('type') == name]

    starts = of_type('session.start')
    if len(starts) != 1:
        reasons.append(f'session.start が {len(starts)} 個')
    elif _dict(starts[0].get('data')).get('sessionId') != session_id:
        reasons.append('別のセッションの記録')

    bash_calls = []
    for event in of_type('tool.execution_start'):
        data = _dict(event.get('data'))
        name = data.get('toolName')
        if name == 'bash':
            bash_calls.append(data)
        else:
            reasons.append(f'bash 以外の道具 {_one_line(name)} が走った')
    if len(bash_calls) != 1:
        reasons.append(f'bash の実行が {len(bash_calls)} 回')
    else:
        call = bash_calls[0]
        if _dict(call.get('arguments')).get('command') != expected_command:
            reasons.append('打たれたコマンドが渡したものと違う')
        call_id = call.get('toolCallId')
        completes = [_dict(e.get('data')) for e in of_type('tool.execution_complete')
                     if isinstance(call_id, str) and _dict(e.get('data')).get('toolCallId') == call_id]
        if len(completes) != 1:
            reasons.append(f'bash の実行の完了が {len(completes)} 個')
        elif completes[0].get('success') is not True:
            reasons.append('bash の実行が成功していない')
        else:
            content = _dict(completes[0].get('result')).get('content')
            if not isinstance(content, str):
                reasons.append('bash の実行の出力が無い')
            else:
                reasons.extend(_judge_output(content, outer_user, outer_net, expected_command))

    credits = None
    shutdowns = of_type('session.shutdown')
    if len(shutdowns) == 1:
        credits = _credits(_dict(shutdowns[0].get('data')).get('accountingSnapshot'))
    return reasons, credits


def _load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _same(a, b):
    """葉の型まで含めて等しい（True と 1、False と 0 を区別する）。"""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def cmd_judge(args):
    if len(args) != 5:
        return _usage()
    events, command, outer_user, outer_net, session_id = args
    if not DIGITS_RE.fullmatch(outer_user) or not DIGITS_RE.fullmatch(outer_net) or not session_id:
        print('ERROR: OUTER_USER・OUTER_NET は数字だけ、SESSION_ID は空でない値', file=sys.stderr)
        return 2
    reasons, credits = judge(events, command, outer_user, outer_net, session_id)
    print('PASS' if not reasons else 'FAIL: ' + _one_line('; '.join(reasons)))
    print('credits=unknown' if credits is None else f'credits={credits!r}')
    return 0 if not reasons else 1


def cmd_weaken(args):
    if len(args) != 1:
        return _usage()
    path = args[0]
    try:
        settings = _load_json(path)
        network = settings['sandbox']['userPolicy']['network']
        if not isinstance(network, dict):
            raise TypeError('network が dict でない')
        network['allowOutbound'] = True
        directory = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix='.settings.', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(settings, f)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
        if _load_json(path)['sandbox']['userPolicy']['network']['allowOutbound'] is not True:
            raise ValueError('書き戻した値が true でない')
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f'ERROR: settings.json を弱められない: {e}', file=sys.stderr)
        return 1
    return 0


def cmd_settings_match(args):
    if len(args) != 3:
        return _usage()
    settings_path, template_path, workdir = args
    try:
        settings = _load_json(settings_path)
        expected = _load_json(template_path)
        expected['sandbox']['userPolicy']['filesystem']['readonlyPaths'] = [workdir]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f'settings.json か雛形を読めない: {e}')
        return 1
    if not _same(settings, expected):
        print('settings.json が雛形＋readonlyPaths と違う')
        return 1
    return 0


def cmd_spent_log(args):
    if len(args) != 5:
        return _usage()
    path, entry_id, month, credits_text, what = args
    credits = float(credits_text) if CREDITS_RE.fullmatch(credits_text) else math.nan
    if not entry_id or not MONTH_RE.fullmatch(month) or not math.isfinite(credits) or credits < 0:
        print('ERROR: spent-log の値が不正', file=sys.stderr)
        return 2
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        st = None
    except OSError as e:
        print(f'ERROR: 記録先を見られない: {e}', file=sys.stderr)
        return 2
    if st is not None and not stat.S_ISREG(st.st_mode):
        print('ERROR: 記録先が通常のファイルでない', file=sys.stderr)
        return 2
    line = json.dumps({'id': entry_id, 'month': month, 'credits': credits, 'what': what},
                      ensure_ascii=False) + '\n'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise OSError('通常のファイルでない')
            f.write(line)
    except OSError as e:
        print(f'ERROR: 記録先に書けない: {e}', file=sys.stderr)
        return 2
    return 0


def _usage():
    print(__doc__.split('\n\n', 1)[1].split('\n\n')[0], file=sys.stderr)
    return 2


COMMANDS = {
    'judge': cmd_judge,
    'weaken': cmd_weaken,
    'settings-match': cmd_settings_match,
    'spent-log': cmd_spent_log,
}


def main(argv):
    if len(argv) < 1 or argv[0] not in COMMANDS:
        return _usage()
    return COMMANDS[argv[0]](argv[1:])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
