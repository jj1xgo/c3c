#!/usr/bin/env python3
"""Copilot の canary の判定のヘルパー tests/copilot_canary_helper.py の試験。

判定は Copilot のセッション記録（events.jsonl）に残った bash の実行と、その実行の結果から行う。
モデルの返答の文（assistant.message）は見ない。記録は、実物の形を写した fixture
（tests/fixtures/copilot-canary/events-pass.jsonl）を土台に、試験ごとに形を変えて作る。
"""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import copilot_canary_helper as helper  # noqa: E402

ROOT = TESTS.parent
HELPER = TESTS / 'copilot_canary_helper.py'
FIXTURE = TESTS / 'fixtures' / 'copilot-canary' / 'events-pass.jsonl'
TEMPLATE = ROOT / 'copilot-settings.json'

SID = '00000000-0000-4000-8000-000000000001'
OUTER_USER = '4026531837'
OUTER_NET = '4026531840'
COMMAND = (
    'readlink /proc/self/ns/user /proc/self/ns/net; ip -brief link; '
    'curl -sS -m 5 -o /dev/null -w "%{http_code}" https://api.github.com/; echo " curl_rc=$?"; '
    'cat /home/node/.config/c3c/secrets/COPILOT_PAT >/dev/null; echo "secret_rc=$?"; '
    'cat /home/node/.copilot/.c3c-canary-mark >/dev/null; echo "home_rc=$?"; '
    'echo "tok_len=${#COPILOT_GITHUB_TOKEN} gh_len=${#GH_TOKEN}"; '
    'echo "outer_environ=$(grep -l COPILOT_GITHUB_TOKEN /proc/[0-9]*/environ 2>/dev/null | wc -l)"; '
    'touch "$PWD/.c3c-copilot-w" 2>/dev/null; echo "w_rc=$?"'
)
LO_LINE = 'lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP> '
TRAILER = '<shellId: 0 completed with exit code 0>'

PASS_VALUES = {
    'user': 'user:[4026532001]',
    'net': 'net:[4026532002]',
    'link': LO_LINE,
    'curl': '000 curl_rc=6',
    'secret': 'cat: /home/node/.config/c3c/secrets/COPILOT_PAT: No such file or directory\nsecret_rc=1',
    'home': 'cat: /home/node/.copilot/.c3c-canary-mark: No such file or directory\nhome_rc=1',
    'tok': 'tok_len=0 gh_len=0',
    'environ': 'outer_environ=0',
    'w': 'w_rc=1',
}


def output(**overrides):
    """合格の出力の行を、overrides で差し替えて組む（値を None にするとその行を落とす）。"""
    values = dict(PASS_VALUES)
    values.update(overrides)
    lines = [v for v in values.values() if v is not None]
    return '\n'.join(lines) + '\n' + TRAILER


def fixture_events():
    events = {}
    for line in FIXTURE.read_text().splitlines():
        event = json.loads(line)
        events[event['type']] = event
    return events


def make_events(out, *, command=COMMAND, tools=('bash',), success=True, complete=True,
                shutdown=True, status='complete', nano=2_500_000_000, assistant_text=None):
    """fixture の 4 行の形で記録を作り、行の一覧を返す。"""
    base = fixture_events()
    rows = [base['session.start']]
    for index, name in enumerate(tools):
        call_id = f'call_{index + 1}'
        start = json.loads(json.dumps(base['tool.execution_start']))
        start['data']['toolCallId'] = call_id
        start['data']['toolName'] = name
        start['data']['arguments'] = {'command': command, 'description': 'run'} if name == 'bash' \
            else {'shellId': '0'}
        rows.append(start)
        if complete:
            done = json.loads(json.dumps(base['tool.execution_complete']))
            done['data']['toolCallId'] = call_id
            done['data']['success'] = success
            done['data']['result'] = {'content': out if name == 'bash' else 'read'}
            rows.append(done)
    if assistant_text is not None:
        rows.append({'type': 'assistant.message', 'data': {'content': assistant_text}})
    if shutdown:
        end = json.loads(json.dumps(base['session.shutdown']))
        end['data']['accountingSnapshot'] = {'totalNanoAiu': nano, 'aiCreditsStatus': status}
        rows.append(end)
    return rows


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.events = self.dir / 'events.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows):
        self.events.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
        return str(self.events)

    def judge(self, rows, command=COMMAND, session_id=SID):
        return helper.judge(self.write(rows), command, OUTER_USER, OUTER_NET, session_id)

    def assert_fail(self, rows, contains=None, **kw):
        reasons, _ = self.judge(rows, **kw)
        self.assertTrue(reasons, 'judge は合格にしてはいけない')
        if contains is not None:
            self.assertTrue(any(contains in r for r in reasons), reasons)
        return reasons

    def test_fixture_passes(self):
        # fixture 自体のコマンドは echo なので、そのコマンドを期待にすれば合格。
        reasons, credits = helper.judge(str(FIXTURE), 'echo example', OUTER_USER, OUTER_NET, SID)
        self.assertEqual((reasons, credits), ([], 2.5))

    def test_pass(self):
        self.assertEqual(self.judge(make_events(output())), ([], 2.5))

    def test_no_tool_call(self):
        self.assert_fail(make_events(output(), tools=()))

    def test_two_bash_calls(self):
        self.assert_fail(make_events(output(), tools=('bash', 'bash')))

    def test_command_differs(self):
        self.assert_fail(make_events(output(), command=COMMAND[:-1] + '!'))

    def test_not_complete(self):
        self.assert_fail(make_events(output(), complete=False))

    def test_success_false(self):
        self.assert_fail(make_events(output(), success=False))

    def test_extra_tool_read_bash(self):
        self.assert_fail(make_events(output(), tools=('bash', 'read_bash')),
                         contains='bash 以外の道具 read_bash')

    def test_assistant_message_ignored(self):
        self.assert_fail(make_events(output(secret='secret_rc=0'), assistant_text=output()))

    def test_line_separator_in_assistant_text(self):
        # U+2028 などを含む行も 1 行の JSON として読む（str.splitlines で行を切らない）。
        self.assertEqual(self.judge(make_events(output(), assistant_text='a\u2028b\u0085c')), ([], 2.5))

    def test_session_id_differs(self):
        self.assert_fail(make_events(output()), contains='別のセッションの記録',
                         session_id='00000000-0000-4000-8000-000000000002')

    def test_two_session_starts(self):
        rows = make_events(output())
        rows.insert(1, rows[0])
        self.assert_fail(rows)

    def test_ns_same_as_outer(self):
        for key, value in (('user', f'user:[{OUTER_USER}]'), ('net', f'net:[{OUTER_NET}]')):
            with self.subTest(key=key):
                self.assert_fail(make_events(output(**{key: value})))

    def test_ns_missing(self):
        for key in ('user', 'net'):
            with self.subTest(key=key):
                self.assert_fail(make_events(output(**{key: None})))

    def test_extra_interface(self):
        link = LO_LINE + '\neth0             UP             02:00:00:00:00:01 <BROADCAST,UP,LOWER_UP> '
        self.assert_fail(make_events(output(link=link)))

    def test_no_interface(self):
        self.assert_fail(make_events(output(link=None)))

    def test_interface_not_lo(self):
        link = 'eth0             UP             02:00:00:00:00:01 <BROADCAST,UP,LOWER_UP> '
        self.assert_fail(make_events(output(link=link)))

    def test_interface_unknown_state(self):
        # 状態の一覧に無い状態（TESTING など）のインターフェースも数える。
        for state in ('TESTING', 'WEIRD'):
            with self.subTest(state=state):
                link = LO_LINE + f'\neth0             {state}        02:00:00:00:00:01 <BROADCAST> '
                self.assert_fail(make_events(output(link=link)))

    def test_interface_section_unreadable_line(self):
        # ip -brief link の範囲（net: の行の次から curl の行の前まで）は、どの行もインターフェースの行でなければ不合格。
        for extra in ('eth0 ??? 02:00:00:00:00:01', 'bash: ip: command not found', 'garbage'):
            with self.subTest(extra=extra):
                self.assert_fail(make_events(output(link=LO_LINE + '\n' + extra)))

    def test_real_container_output(self):
        # 2026-11-13 に opt-in のコンテナ（Copilot 1.0.109）で実際に出た bash の出力（名前空間の番号は外側と違う）。
        real = ('user:[4026533232]\nnet:[4026533179]\n'
                'lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP> \n'
                'curl: (6) Could not resolve host: api.github.com\n000 curl_rc=6\n'
                'cat: /home/node/.config/c3c/secrets/COPILOT_PAT: No such file or directory\nsecret_rc=1\n'
                'cat: /home/node/.copilot/.c3c-canary-mark: No such file or directory\nhome_rc=1\n'
                'tok_len=0 gh_len=0\nouter_environ=0\nw_rc=1\n<shellId: 0 completed with exit code 0>')
        self.assertEqual(self.judge(make_events(real)), ([], 2.5))

    def test_rc_signal(self):
        # 信号で終わった rc（128 以上）は、塞いだ結果と読めない。
        for code in ('128', '137', '255'):
            with self.subTest(code=code):
                self.assert_fail(make_events(output(w=f'w_rc={code}')))

    def test_rc_one_and_125_pass(self):
        for code in ('1', '125'):
            with self.subTest(code=code):
                self.assertEqual(self.judge(make_events(output(w=f'w_rc={code}'))), ([], 2.5))

    def test_unicode_digits_in_output(self):
        # 全角の数字の名前空間の行は、名前空間の行として数えない。
        full = OUTER_USER.translate(str.maketrans('0123456789', '０１２３４５６７８９'))
        self.assert_fail(make_events(output(user=f'user:[{full}]')))
        self.assert_fail(make_events(output(w='w_rc=１')))

    def test_completion_with_other_call_id(self):
        rows = make_events(output())
        for row in rows:
            if row['type'] == 'tool.execution_complete':
                row['data']['toolCallId'] = 'call_other'
        self.assert_fail(rows)

    def test_lo_down_passes(self):
        link = 'lo               DOWN           00:00:00:00:00:00 <LOOPBACK> '
        self.assertEqual(self.judge(make_events(output(link=link))), ([], 2.5))

    def test_dev_null_unwritable(self):
        # sandbox で /dev/null に書けないと、cat はファイルを読めても redirect で失敗して rc 1 になる。
        # cat 自身がそのパスを読めなかった行が無ければ合格にしない。
        self.assert_fail(make_events(output(
            secret='bash: line 1: /dev/null: Permission denied\nsecret_rc=1',
            home='bash: line 1: /dev/null: Permission denied\nhome_rc=1')))

    def test_cat_denial_line_for_other_path(self):
        self.assert_fail(make_events(output(
            secret='cat: /elsewhere: No such file or directory\nsecret_rc=1')))

    def test_cat_permission_denied_passes(self):
        secret = 'cat: /home/node/.config/c3c/secrets/COPILOT_PAT: Permission denied\nsecret_rc=1'
        self.assertEqual(self.judge(make_events(output(secret=secret))), ([], 2.5))

    def test_rc_zero(self):
        for key, name in (('curl', 'curl_rc'), ('secret', 'secret_rc'), ('home', 'home_rc'), ('w', 'w_rc')):
            with self.subTest(key=name):
                self.assert_fail(make_events(output(**{key: f'{name}=0'})))

    def test_rc_127(self):
        for code in ('126', '127'):
            for key, name in (('curl', 'curl_rc'), ('secret', 'secret_rc'), ('home', 'home_rc'), ('w', 'w_rc')):
                with self.subTest(key=name, code=code):
                    self.assert_fail(make_events(output(**{key: f'{name}={code}'})))

    def test_tok_len_nonzero(self):
        for tok in ('tok_len=40 gh_len=0', 'tok_len=0 gh_len=40'):
            with self.subTest(tok=tok):
                self.assert_fail(make_events(output(tok=tok)))

    def test_outer_environ_nonzero(self):
        self.assert_fail(make_events(output(environ='outer_environ=1')))

    def test_key_missing(self):
        for key in PASS_VALUES:
            if key in ('user', 'net', 'link'):
                continue
            with self.subTest(key=key):
                self.assert_fail(make_events(output(**{key: None})))

    def test_key_twice(self):
        self.assert_fail(make_events(output(w='w_rc=1\nw_rc=1')))

    def test_key_glued_not_picked(self):
        # 前が空白でない key=value は拾わない（xsecret_rc=1 は secret_rc の代わりにならない）。
        self.assert_fail(make_events(output(secret='xsecret_rc=1')))

    def test_stderr_noise(self):
        cases = {
            'stderr の行が先': 'curl: (6) Could not resolve host: api.github.com\n000 curl_rc=6',
            'stdout の 000 に続けて stderr': '000curl: (6) Could not resolve host: api.github.com\n curl_rc=6',
        }
        for name, curl in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.judge(make_events(output(curl=curl))), ([], 2.5))

    def test_credits_unknown(self):
        for kw in ({'shutdown': False}, {'status': 'partial'}, {'nano': -1}, {'nano': True},
                   {'nano': 'x'}):
            with self.subTest(**{k: repr(v) for k, v in kw.items()}):
                self.assertEqual(self.judge(make_events(output(), **kw)), ([], None))

    def test_bad_json_line(self):
        rows = make_events(output())
        path = self.write(rows)
        with open(path, 'a') as f:
            f.write('{not json\n')
        reasons, _ = helper.judge(path, COMMAND, OUTER_USER, OUTER_NET, SID)
        self.assertTrue(any('JSON でない' in r for r in reasons), reasons)

    def test_non_dict_fields_tolerated(self):
        rows = make_events(output())
        rows.append(['not', 'a', 'dict'])
        rows.append('text')
        self.assertEqual(self.judge(rows), ([], 2.5))
        rows.append({'type': 'tool.execution_start', 'data': 'x'})
        self.assert_fail(rows)


def run_cli(*args):
    return subprocess.run([sys.executable, '-I', str(HELPER), *args],
                          capture_output=True, text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def events(self, rows):
        path = self.dir / 'events.jsonl'
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return str(path)

    def test_cli_judge(self):
        ok = self.events(make_events(output()))
        r = run_cli('judge', ok, COMMAND, OUTER_USER, OUTER_NET, SID)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[:2], ['PASS', 'credits=2.5'])

        bad = self.events(make_events(output(w='w_rc=0')))
        r = run_cli('judge', bad, COMMAND, OUTER_USER, OUTER_NET, SID)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.splitlines()[0].startswith('FAIL: '), r.stdout)

        ok = self.events(make_events(output()))
        r = run_cli('judge', ok, COMMAND, f'user:[{OUTER_USER}]', OUTER_NET, SID)
        self.assertEqual(r.returncode, 2)
        r = run_cli('judge', ok, COMMAND, OUTER_USER, '', SID)
        self.assertEqual(r.returncode, 2)

        r = run_cli('judge', ok, COMMAND, OUTER_USER, OUTER_NET, '00000000-0000-4000-8000-000000000009')
        self.assertEqual(r.returncode, 1)

        r = run_cli('judge', str(self.dir / 'missing.jsonl'), COMMAND, OUTER_USER, OUTER_NET, SID)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines()[1], 'credits=unknown')
        self.assertIn('events.jsonl が無い', r.stdout.splitlines()[0])

        unknown = self.events(make_events(output(), shutdown=False))
        r = run_cli('judge', unknown, COMMAND, OUTER_USER, OUTER_NET, SID)
        self.assertEqual((r.returncode, r.stdout.splitlines()[1]), (0, 'credits=unknown'))

        r = run_cli('judge', ok, COMMAND, OUTER_USER, OUTER_NET)
        self.assertEqual(r.returncode, 2)

        full = OUTER_USER.translate(str.maketrans('0123456789', '０１２３４５６７８９'))
        for bad in (OUTER_USER + '\n', full):
            with self.subTest(outer=repr(bad)):
                self.assertEqual(run_cli('judge', ok, COMMAND, bad, OUTER_NET, SID).returncode, 2)

    def test_cli_judge_two_lines_even_with_newline_in_tool_name(self):
        rows = make_events(output(), tools=('bash', 'view\ncredits=0\nx'))
        r = run_cli('judge', self.events(rows), COMMAND, OUTER_USER, OUTER_NET, SID)
        self.assertEqual(r.returncode, 1)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 2, r.stdout)
        self.assertTrue(lines[0].startswith('FAIL: '))
        self.assertEqual(lines[1], 'credits=2.5')

    def test_weaken_and_match(self):
        settings = json.loads(TEMPLATE.read_text())
        settings['sandbox']['userPolicy']['filesystem']['readonlyPaths'] = ['/w']
        path = self.dir / 'settings.json'
        path.write_text(json.dumps(settings))
        self.assertEqual(run_cli('settings-match', str(path), str(TEMPLATE), '/w').returncode, 0)
        self.assertEqual(run_cli('settings-match', str(path), str(TEMPLATE), '/other').returncode, 1)

        r = run_cli('weaken', str(path))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIs(json.loads(path.read_text())['sandbox']['userPolicy']['network']['allowOutbound'], True)
        r = run_cli('settings-match', str(path), str(TEMPLATE), '/w')
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.strip() or r.stderr.strip(), '違う理由を出す')

        settings['sandbox']['userPolicy']['network']['allowOutbound'] = 0
        path.write_text(json.dumps(settings))
        self.assertEqual(run_cli('settings-match', str(path), str(TEMPLATE), '/w').returncode, 1)

        settings['sandbox']['userPolicy']['network']['allowOutbound'] = False
        settings['sandbox']['enabled'] = 1
        path.write_text(json.dumps(settings))
        self.assertEqual(run_cli('settings-match', str(path), str(TEMPLATE), '/w').returncode, 1)

    def test_weaken_missing_or_broken(self):
        self.assertEqual(run_cli('weaken', str(self.dir / 'missing.json')).returncode, 1)
        broken = self.dir / 'broken.json'
        broken.write_text('{')
        self.assertEqual(run_cli('weaken', str(broken)).returncode, 1)
        self.assertEqual(broken.read_text(), '{')

    def test_spent_log(self):
        log = self.dir / 'spent.jsonl'
        r = run_cli('spent-log', str(log), 'copilot-canary-1', '2026-11', '5.0', '1.0.109・argon・2 回・合格')
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_cli('spent-log', str(log), 'copilot-canary-2', '2026-11', '60', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first, {'id': 'copilot-canary-1', 'month': '2026-11', 'credits': 5.0,
                                 'what': '1.0.109・argon・2 回・合格'})
        self.assertIn('・', lines[0], 'ensure_ascii=False で書く')
        self.assertEqual(set(json.loads(lines[1])), {'id', 'month', 'credits', 'what'})
        self.assertTrue(math.isclose(json.loads(lines[1])['credits'], 60.0))

        before = log.read_text()
        for credits, month in (('-1', '2026-11'), ('nan', '2026-11'), ('inf', '2026-11'),
                               ('x', '2026-11'), ('1', '2026-1'), ('1', '2026-11x'),
                               ('1', '2026-11\n'), ('１', '2026-11'), ('1', '２０２６-１１')):
            with self.subTest(credits=credits, month=month):
                r = run_cli('spent-log', str(log), 'id', month, credits, 'w')
                self.assertEqual(r.returncode, 2)
                self.assertEqual(log.read_text(), before)

        link = self.dir / 'link.jsonl'
        link.symlink_to(log)
        r = run_cli('spent-log', str(link), 'id', '2026-11', '1', 'w')
        self.assertEqual(r.returncode, 2)
        self.assertEqual(log.read_text(), before)

        subdir = self.dir / 'dir.jsonl'
        subdir.mkdir()
        self.assertEqual(run_cli('spent-log', str(subdir), 'id', '2026-11', '1', 'w').returncode, 2)

    def test_unknown_subcommand(self):
        self.assertEqual(run_cli('nope').returncode, 2)
        self.assertEqual(run_cli().returncode, 2)


if __name__ == '__main__':
    unittest.main()
