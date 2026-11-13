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
# rc の値のうち、塞いだ結果と読めないもの（成功、コマンドが実行できない、コマンドが無い）。
BAD_RC = {0, 126, 127}

USER_RE = re.compile(r'^user:\[(\d+)\]$')
NET_RE = re.compile(r'^net:\[(\d+)\]$')
IFACE_RE = re.compile(r'^(\S+)\s+(UNKNOWN|UP|DOWN|DORMANT|LOWERLAYERDOWN|NOTPRESENT)\b')
KV_RE = re.compile(r'(?:(?<=\s)|^)(' + '|'.join(KEYS) + r')=(\d+)(?=\s|$)', re.MULTILINE)
DIGITS_RE = re.compile(r'^\d+$')
MONTH_RE = re.compile(r'^\d{4}-\d{2}$')


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


def _judge_output(content, outer_user, outer_net):
    reasons = []
    lines = content.splitlines()
    for name, regex, outer in (('user', USER_RE, outer_user), ('net', NET_RE, outer_net)):
        found = [m.group(1) for m in (regex.match(line.strip()) for line in lines) if m]
        if len(found) != 1:
            reasons.append(f'{name} の名前空間の行が {len(found)} 個')
        elif found[0] == outer:
            reasons.append(f'{name} の名前空間が外側と同じ')
    ifaces = [m.group(1) for m in (IFACE_RE.match(line) for line in lines) if m]
    if ifaces != ['lo']:
        reasons.append(f'インターフェースが lo の 1 つだけでない: {ifaces}')
    values = {}
    for match in KV_RE.finditer(content):
        values.setdefault(match.group(1), []).append(int(match.group(2)))
    for key in KEYS:
        got = values.get(key, [])
        if len(got) != 1:
            reasons.append(f'{key} が {len(got)} 回')
            continue
        value = got[0]
        if key in RC_KEYS and value in BAD_RC:
            reasons.append(f'{key}={value}')
        if key in ZERO_KEYS and value != 0:
            reasons.append(f'{key}={value}')
    return reasons


def judge(events_path, expected_command, outer_user, outer_net, session_id):
    """不合格の理由の一覧（空なら合格）と、クレジット（分からなければ None）を返す。"""
    try:
        with open(events_path, encoding='utf-8') as f:
            raw_lines = f.read().splitlines()
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
            reasons.append(f'bash 以外の道具 {name} が走った')
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
                reasons.extend(_judge_output(content, outer_user, outer_net))

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
    if not DIGITS_RE.match(outer_user) or not DIGITS_RE.match(outer_net) or not session_id:
        print('ERROR: OUTER_USER・OUTER_NET は数字だけ、SESSION_ID は空でない値', file=sys.stderr)
        return 2
    reasons, credits = judge(events, command, outer_user, outer_net, session_id)
    print('PASS' if not reasons else 'FAIL: ' + '; '.join(reasons))
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
    try:
        credits = float(credits_text)
    except ValueError:
        credits = math.nan
    if not entry_id or not MONTH_RE.match(month) or not math.isfinite(credits) or credits < 0:
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
