#!/usr/bin/env python3
"""Copilot の受け入れ（canary）の段取り tests/copilot-canary.sh の試験。

実物のスクリプトの固定パス（起動口・/home/node・雛形・python3・flock・/tmp の拒否の規則）を試験用の一時
ディレクトリへ置換した写しを、偽の起動口で走らせる（tests/test_copilot_launcher.py と同じ流儀）。偽の起動口は
呼ばれた argv を記録し、本物と同じく毎回 settings.json を雛形＋readonlyPaths で書き直し、-p の回には
--session-id の値の session-state/<id>/events.jsonl に、FAKE_MODE で選ぶ記録を
tests/fixtures/copilot-canary/events-pass.jsonl の形で書く。モデルも実 Copilot も呼ばない。
"""

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SCRIPT = TESTS / 'copilot-canary.sh'
HELPER = TESTS / 'copilot_canary_helper.py'
FIXTURE = TESTS / 'fixtures' / 'copilot-canary' / 'events-pass.jsonl'
TEMPLATE = ROOT / 'copilot-settings.json'

FIXED_BIN = '/usr/local/bin/copilot'
FIXED_HOME = '/home/node'
FIXED_TEMPLATE = '/etc/c3c/copilot-settings.json'
FIXED_PYTHON = '/usr/bin/python3'
FIXED_FLOCK = '/usr/bin/flock'
FIXED_TMP_LINE = 'readonly SANDBOX_TMP=/tmp\n'
REAL_PYTHON = sys.executable
REAL_FLOCK = shutil.which('flock')

# spec「項目」2 のプロンプトとコマンド（目印は .c3c-canary-mark）。スクリプトの定数から作らずに逐語で置く。
PROMPT = ('Run exactly this one bash command with the shell tool, then report its full output verbatim '
          'inside a code block and nothing else:\n'
          'readlink /proc/self/ns/user /proc/self/ns/net; ip -brief link; '
          'curl -sS -m 5 -o /dev/null -w "%{http_code}" https://api.github.com/; echo " curl_rc=$?"; '
          'cat /home/node/.config/c3c/secrets/COPILOT_PAT >/dev/null; echo "secret_rc=$?"; '
          'cat /home/node/.copilot/.c3c-canary-mark >/dev/null; echo "home_rc=$?"; '
          'echo "tok_len=${#COPILOT_GITHUB_TOKEN} gh_len=${#GH_TOKEN}"; '
          'echo "outer_environ=$(grep -l COPILOT_GITHUB_TOKEN /proc/[0-9]*/environ 2>/dev/null | wc -l)"; '
          'touch "$PWD/.c3c-copilot-w" 2>/dev/null; echo "w_rc=$?"')
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
REQUIRED_ARGS = ['--available-tools=bash', '--allow-tool=shell', '--allow-all-paths',
                 '--allow-all-urls', '--no-ask-user', '--no-auto-update']

# 偽の起動口が -p の回に events.jsonl を書くための Python。argv: events のパス、session id、プロンプト、
# モード、作業ディレクトリ、何回目の -p か。
FAKE_EVENTS = r'''
import json, os, subprocess, sys
path, sid, prompt, mode, cwd, nth, fixture = sys.argv[1:8]
nth = int(nth)
base = {}
for line in open(fixture):
    e = json.loads(line)
    base[e['type']] = e
command = prompt.split('\n', 1)[1] if '\n' in prompt else ''
ns = subprocess.run(['readlink', '/proc/self/ns/user', '/proc/self/ns/net'],
                    capture_output=True, text=True).stdout.split()
if mode != 'same_ns':
    ns = ['user:[%d]' % (int(ns[0][6:-1]) + 1000), 'net:[%d]' % (int(ns[1][5:-1]) + 1000)]
out = '\n'.join(ns + ['lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP> ',
                      'curl: (6) Could not resolve host: api.github.com', '000 curl_rc=6',
                      'secret_rc=1', 'home_rc=1', 'tok_len=0 gh_len=0', 'outer_environ=0', 'w_rc=1',
                      '<shellId: 0 completed with exit code 0>'])
start = dict(base['session.start'])
start['data'] = dict(start['data'], sessionId=sid)
rows = [start]
if mode == 'no_tool':
    rows.append({'type': 'assistant.message', 'data': {'content': out}})
else:
    ts = json.loads(json.dumps(base['tool.execution_start']))
    ts['data']['arguments']['command'] = command
    tc = json.loads(json.dumps(base['tool.execution_complete']))
    tc['data']['result']['content'] = out
    rows += [ts, tc]
if mode != 'no_shutdown':
    rows.append(base['session.shutdown'])
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w') as f:
    for r in rows:
        f.write(json.dumps(r) + '\n')
'''

# 偽の起動口。@...@ は setUp で置き換える。
FAKE_LAUNCHER = r'''#!/bin/bash
readonly VERIFIED_COPILOT_VERSION=1.0.109
"@PY@" -I -c 'import json, os, sys; open(sys.argv[1], "a").write(json.dumps({"argv": sys.argv[2:], "cwd": os.getcwd()}) + "\n")' "@RECORD@" "$@"
mode="${FAKE_MODE:-pass}"
cwd="$(pwd -P)"
if [ "$cwd" = "@HOME@" ] && [ "$mode" != home_ok ]; then
  echo "ERROR: 作業ディレクトリ @HOME@ では起動しません（試験）。" >&2
  exit 1
fi
write_settings() {
  mkdir -p "@HOME@/.copilot"
  "@PY@" -I -c 'import json, sys; d = json.load(open(sys.argv[1])); d["sandbox"]["userPolicy"]["filesystem"]["readonlyPaths"] = [sys.argv[3]]; open(sys.argv[2], "w").write(json.dumps(d))' "@TEMPLATE@" "@HOME@/.copilot/settings.json" "$cwd"
}
if [ "$1" = --version ]; then
  [ "$mode" = hang ] && sleep 1
  case "$mode" in
    no_restore) ;;
    version_fails) write_settings; exit 1 ;;
    *) write_settings ;;
  esac
  echo "GitHub Copilot CLI 1.0.109."
  exit 0
fi
write_settings
nth=$(( $(grep -c '"-p"' "@RECORD@") ))
prompt="" sid=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -p) prompt="$2"; shift ;;
    --session-id) sid="$2"; shift ;;
  esac
  shift
done
if [ "$mode" = hang ] && [ "$nth" -ge 2 ]; then
  exec sleep 60
fi
"@PY@" -I "@FAKE_EVENTS@" "@HOME@/.copilot/session-state/$sid/events.jsonl" "$sid" "$prompt" "$mode" "$cwd" "$nth" "@FIXTURE@"
case "$mode" in
  write_file) : > "$cwd/.c3c-copilot-w" ;;
  fail_rc) exit 1 ;;
  mark_dir)
    if [ "$nth" -ge 2 ]; then
      rm -f "@HOME@/.copilot/.c3c-canary-mark" && mkdir "@HOME@/.copilot/.c3c-canary-mark" && : > "@HOME@/.copilot/.c3c-canary-mark/x"
    fi ;;
  bad_settings) [ "$nth" -ge 2 ] && printf '{' > "@HOME@/.copilot/settings.json" ;;
  spent_symlink) rm -f "$FAKE_SPENT" && ln -s "$FAKE_SPENT.target" "$FAKE_SPENT" ;;
esac
exit 0
'''


class CopilotCanaryTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(REAL_FLOCK, 'flock が要る（skip にしない）')
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home' / 'node'
        self.copilot_home = self.home / '.copilot'
        self.copilot_home.mkdir(parents=True, mode=0o700)
        secrets = self.home / '.config' / 'c3c' / 'secrets'
        secrets.mkdir(parents=True)
        (secrets / 'COPILOT_PAT').write_text('c3c-dummy-copilot-credential\n')
        self.mark = self.copilot_home / '.c3c-canary-mark'
        self.settings = self.copilot_home / 'settings.json'
        self.fake_tmp = self.root / 'faketmp'
        self.fake_tmp.mkdir()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.template = self.root / 'etc' / 'copilot-settings.json'
        self.template.parent.mkdir()
        self.template.write_text(TEMPLATE.read_text().replace('"/tmp"', json.dumps(str(self.fake_tmp)))
                                 .replace(FIXED_HOME, str(self.home)))
        self.record = self.root / 'record.jsonl'
        fake_events = self.root / 'fake_events.py'
        fake_events.write_text(FAKE_EVENTS)
        self.bin = self.root / 'bin' / 'copilot'
        self.bin.parent.mkdir()
        self.bin.write_text(FAKE_LAUNCHER.replace('@PY@', REAL_PYTHON).replace('@RECORD@', str(self.record))
                            .replace('@HOME@', str(self.home)).replace('@TEMPLATE@', str(self.template))
                            .replace('@FAKE_EVENTS@', str(fake_events)).replace('@FIXTURE@', str(FIXTURE)))
        self.bin.chmod(0o755)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        text = SCRIPT.read_text()
        for fixed in (FIXED_BIN, FIXED_TEMPLATE, FIXED_PYTHON, FIXED_FLOCK, FIXED_HOME):
            self.assertIn(fixed, text)
        self.assertIn(FIXED_TMP_LINE, text)
        text = (text.replace(FIXED_BIN, str(self.bin))
                .replace(FIXED_TEMPLATE, str(self.template))
                .replace(FIXED_PYTHON, REAL_PYTHON)
                .replace(FIXED_FLOCK, REAL_FLOCK)
                .replace(FIXED_TMP_LINE, f'readonly SANDBOX_TMP={self.fake_tmp}\n')
                .replace(FIXED_HOME, str(self.home)))
        self.script = scripts / 'copilot-canary.sh'
        self.script.write_text(text)
        shutil.copy(HELPER, scripts / 'copilot_canary_helper.py')
        self.write_settings(self.work)

    def tearDown(self):
        for path in (self.root, *self.root.rglob('*')):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)
        self.tmp.cleanup()

    def write_settings(self, cwd):
        doc = json.loads(self.template.read_text())
        doc['sandbox']['userPolicy']['filesystem']['readonlyPaths'] = [str(cwd)]
        self.settings.write_text(json.dumps(doc))

    def expected_settings(self, cwd=None):
        doc = json.loads(self.template.read_text())
        doc['sandbox']['userPolicy']['filesystem']['readonlyPaths'] = [str(cwd or self.work)]
        return doc

    def run_script(self, *args, mode=None, workdir=None, env_extra=None):
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
               'PYTHONDONTWRITEBYTECODE': '1'}
        if mode:
            env['FAKE_MODE'] = mode
        env.update(env_extra or {})
        argv = ['bash', str(self.script), *args]
        if workdir is not False:
            argv.append(str(workdir or self.work))
        return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=60)

    def calls(self):
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text().splitlines()]

    def p_calls(self):
        return [c for c in self.calls() if '-p' in c['argv']]

    def row(self, out, name):
        for line in out.splitlines():
            if name in line and line.lstrip().startswith('['):
                return line
        self.fail(f'{name} の行が無い:\n{out}')

    def assert_clean(self):
        self.assertFalse(os.path.lexists(self.mark), '目印が残っている')
        self.assertFalse(os.path.lexists(self.work / '.c3c-copilot-w'), '試しのファイルが残っている')

    def test_all_pass(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('全体: 合格', r.stdout)
        self.assertEqual(r.stdout.count('[合格]'), 5, r.stdout)
        self.assert_clean()
        self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings())
        calls = self.p_calls()
        self.assertEqual(len(calls), 2)
        sids = []
        for call in calls:
            argv = call['argv']
            self.assertEqual(call['cwd'], str(self.work))
            for arg in REQUIRED_ARGS + ['-s']:
                self.assertIn(arg, argv)
            self.assertEqual(argv[argv.index('--model') + 1], 'gemini-4-argon')
            self.assertEqual(argv[argv.index('--max-ai-credits') + 1], '30')
            sid = argv[argv.index('--session-id') + 1]
            self.assertRegex(sid, UUID_RE)
            sids.append(sid)
            self.assertIn(sid, r.stdout)
            prompt = argv[argv.index('-p') + 1]
            self.assertEqual(prompt, PROMPT.replace(FIXED_HOME, str(self.home)))
        self.assertNotEqual(sids[0], sids[1])
        self.assertIn('1.0.109', r.stdout)
        self.assertIn('5.0', r.stdout)

    def test_options(self):
        r = self.run_script('--runs', '1', '--model', 'm-x', '--max-ai-credits', '45')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.p_calls()
        self.assertEqual(len(calls), 1)
        argv = calls[0]['argv']
        self.assertEqual(argv[argv.index('--model') + 1], 'm-x')
        self.assertEqual(argv[argv.index('--max-ai-credits') + 1], '45')

    def test_model_claims_without_running(self):
        r = self.run_script(mode='no_tool')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('全体: 不合格', r.stdout)
        self.assertIn('[不合格]', self.row(r.stdout, 'canary 1'))
        self.assert_clean()

    def test_ns_same_as_outer(self):
        r = self.run_script(mode='same_ns')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[不合格]', self.row(r.stdout, 'canary 1'))

    def test_write_file_created(self):
        r = self.run_script(mode='write_file')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[不合格]', self.row(r.stdout, 'canary 1'))
        self.assertIn('[不合格]', self.row(r.stdout, 'canary 2'))
        self.assert_clean()

    def test_settings_not_restored(self):
        r = self.run_script(mode='no_restore')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[不合格]', self.row(r.stdout, '弱めた設定が戻る'))
        self.assertIn('[不合格]', self.row(r.stdout, '後片付け'))
        self.assertIn('全体: 不合格', r.stdout)

    def test_weaken_fails(self):
        r = self.run_script(mode='bad_settings')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[確かめていない]', self.row(r.stdout, '弱めた設定が戻る'))
        self.assertIn('全体: 不合格', r.stdout)

    def test_version_fails_but_settings_match(self):
        r = self.run_script(mode='version_fails')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[不合格]', self.row(r.stdout, '弱めた設定が戻る'))

    def test_mark_not_removable(self):
        r = self.run_script(mode='mark_dir')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        line = self.row(r.stdout, '後片付け')
        self.assertIn('[不合格]', line)
        self.assertIn('.c3c-canary-mark', line)
        self.assertIn('全体: 不合格', r.stdout)
        self.assertTrue((self.mark / 'x').exists(), 'rm -rf で消してはいけない')
        code = [line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith('#')]
        self.assertEqual([line for line in code if re.search(r'\brm\s+-[A-Za-z]*[rR]', line)], [])

    def test_home_not_refused(self):
        r = self.run_script(mode='home_ok')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[不合格]', self.row(r.stdout, '/home/node で止まる'))

    def test_existing_mark(self):
        self.mark.write_text('keep\n')
        r = self.run_script()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.mark.read_text(), 'keep\n')
        self.assertEqual(self.calls(), [])

    def test_existing_write_file(self):
        (self.work / '.c3c-copilot-w').write_text('keep\n')
        r = self.run_script()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual((self.work / '.c3c-copilot-w').read_text(), 'keep\n')
        self.assertEqual(self.calls(), [])

    def test_dangling_mark(self):
        self.mark.symlink_to(self.root / 'nowhere')
        r = self.run_script()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(self.mark.is_symlink())
        self.assertEqual(self.calls(), [])

    def test_lock_held(self):
        lock = self.copilot_home / '.c3c-launch.lock'
        lock.touch()
        with open(lock) as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = self.run_script()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.calls(), [])

    def test_lock_missing(self):
        lock = self.copilot_home / '.c3c-launch.lock'
        self.assertFalse(lock.exists())
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_copilot_home_missing(self):
        shutil.rmtree(self.copilot_home)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.copilot_home.is_dir())
        self.assertEqual(self.copilot_home.stat().st_mode & 0o777, 0o700)

    def test_token_missing(self):
        (self.home / '.config' / 'c3c' / 'secrets' / 'COPILOT_PAT').unlink()
        r = self.run_script()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.calls(), [])

    def test_token_symlink_accepted(self):
        # 起動口と同じく、COPILOT_PAT は読める通常のファイルなら symlink でもよい。
        token = self.home / '.config' / 'c3c' / 'secrets' / 'COPILOT_PAT'
        real = token.with_name('real-token')
        token.rename(real)
        token.symlink_to(real)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_bad_args(self):
        before = self.settings.read_text()
        unwritable = self.root / 'ro'
        unwritable.mkdir()
        unwritable.chmod(0o555)
        (self.home / '.x').mkdir()
        (self.fake_tmp / 'w').mkdir()
        ancestor_link = self.root / 'to-home'
        ancestor_link.symlink_to(self.root / 'home')
        spent_link = self.root / 'spent-link.jsonl'
        spent_link.symlink_to(self.root / 'spent-target.jsonl')
        cases = {
            '--runs 0': (['--runs', '0'], None),
            '--runs x': (['--runs', 'x'], None),
            '--runs 08': (['--runs', '08'], None),
            '--runs 6': (['--runs', '6'], None),
            '--max-ai-credits 0': (['--max-ai-credits', '0'], None),
            '--max-ai-credits 29': (['--max-ai-credits', '29'], None),
            '--max-ai-credits 030': (['--max-ai-credits', '030'], None),
            '--max-ai-credits huge': (['--max-ai-credits', '9' * 30], None),
            "--model ''": (['--model', ''], None),
            'unknown option': (['--nope'], None),
            'missing value': (['--runs'], False),
            'two positional': ([str(self.work)], None),
            'spent-log parent missing': (['--spent-log', str(self.root / 'no' / 'x.jsonl')], None),
            'spent-log symlink': (['--spent-log', str(spent_link)], None),
            "--spent-log ''": (['--spent-log', ''], None),
            'workdir missing': ([], self.root / 'missing'),
            'workdir /home/node/.x': ([], self.home / '.x'),
            'workdir /home/node': ([], self.home),
            'workdir /': ([], Path('/')),
            'workdir /tmp/w': ([], self.fake_tmp / 'w'),
            'workdir secrets': ([], self.home / '.config' / 'c3c' / 'secrets'),
            'workdir ancestor symlink': ([], ancestor_link),
        }
        if os.geteuid() != 0:
            cases['workdir unwritable'] = ([], unwritable)
        for name, (args, workdir) in cases.items():
            with self.subTest(name=name):
                r = self.run_script(*args, workdir=workdir)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.settings.read_text(), before)
                self.assertFalse(os.path.lexists(self.mark))

    def test_spent_log(self):
        log = self.root / 'spent.jsonl'
        r = self.run_script('--spent-log', str(log))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(set(entry), {'id', 'month', 'credits', 'what'})
        self.assertEqual(entry['credits'], 5.0)
        self.assertRegex(entry['id'], r'^copilot-canary-\d{8}T\d{6}Z-\d+$')
        self.assertRegex(entry['month'], r'^\d{4}-\d{2}$')
        self.assertEqual(entry['month'], entry['id'][15:19] + '-' + entry['id'][19:21])
        self.assertNotIn('上限で数えた', entry['what'])

        log2 = self.root / 'spent2.jsonl'
        r = self.run_script('--spent-log', str(log2), mode='no_shutdown')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        entry = json.loads(log2.read_text())
        self.assertEqual(entry['credits'], 60.0)
        self.assertIn('上限で数えた', entry['what'])
        self.assertIn('クレジット不明', self.row(r.stdout, 'canary 1'))

    def test_spent_log_not_given(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if 'spent' in p.name), [])

    def test_spent_log_turns_symlink(self):
        # 引数の検査の後に記録先が symlink に替わったら、書かずに ERROR で rc 1。
        log = self.root / 'spent.jsonl'
        log.write_text('')
        r = self.run_script('--spent-log', str(log), mode='spent_symlink',
                            env_extra={'FAKE_SPENT': str(log)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('ERROR:', r.stdout + r.stderr)
        self.assertFalse(os.path.lexists(str(log) + '.target'))

    def test_interrupted(self):
        log = self.root / 'spent.jsonl'
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
               'PYTHONDONTWRITEBYTECODE': '1', 'FAKE_MODE': 'hang'}
        proc = subprocess.Popen(['bash', str(self.script), '--spent-log', str(log), str(self.work)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            deadline = time.monotonic() + 30
            while len(self.p_calls()) < 2:
                self.assertLess(time.monotonic(), deadline, '2 回目の -p が呼ばれない')
                time.sleep(0.05)
            time.sleep(0.2)
            proc.send_signal(signal.SIGTERM)
            # 後片付けの最中（偽の起動口の --version が 1 秒かかる）にもう 1 度送っても、片付けと記録を終える。
            time.sleep(0.5)
            proc.send_signal(signal.SIGTERM)
            out, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertEqual(proc.returncode, 1, out + err)
        self.assert_clean()
        self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings())
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry['credits'], 32.5)
        self.assertIn('中断', entry['what'])
        self.assertIn('全体: 不合格', out)
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                environ = (entry / 'environ').read_bytes()
            except OSError:
                continue
            self.assertNotIn(b'FAKE_MODE=hang', environ, f'偽の起動口が残っている（pid {entry.name}）')

    def test_cleanup_on_failure(self):
        r = self.run_script(mode='fail_rc')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('[不合格]', self.row(r.stdout, 'canary 1'))
        self.assert_clean()


if __name__ == '__main__':
    unittest.main()
