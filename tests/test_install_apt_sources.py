#!/usr/bin/env python3
"""外部の APT 取得元の鍵を照合して置く install-apt-sources.sh の回帰試験（#273）。

実物のスクリプトの固定の値（KEYRING_DIR・SOURCES_DIR・INSTALL_OWNER）を試験用の一時ディレクトリと
試験を走らせるユーザーへ置換して実行する。PATH は試験用の
bin だけにし、curl・apt-get は記録する dummy、gpg は記録してから実物の gpg を呼ぶ包みにする。試験の鍵は
実物の gpg で作る。gpg が無ければ skip せずに失敗する（CI と c3c の開発用のコンテナには gnupg がある。
skip にすると CI で黙って抜けるため）。
"""

from pathlib import Path
import grp
import os
import pwd
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'install-apt-sources.sh'
REAL_GPG = shutil.which('gpg')
TOOLS = ('sh', 'mktemp', 'rm', 'sort', 'tr', 'cat', 'wc', 'install', 'awk', 'grep', 'sed', 'cut',
         'tail', 'head', 'chmod', 'mkdir', 'mv', 'cp', 'uniq', 'cmp', 'gpgconf', 'env', 'id',
         'gpg-agent', 'printf', 'ls', 'dirname', 'basename', 'rmdir', 'true', 'false')

CURL = '''#!/bin/sh
out=''
url=''
prev=''
for arg in "$@"; do
  if [ "$prev" = -o ]; then out=$arg; fi
  prev=$arg
  url=$arg
done
{ for arg in "$@"; do printf '%s\\0' "$arg"; done; printf '\\n'; } >> "{log}"
line=$(grep -F "$url	" "{map}" | head -n 1)
[ -n "$line" ] || exit 6
rc=$(printf '%s' "$line" | cut -f2)
src=$(printf '%s' "$line" | cut -f3)
[ "$rc" = 0 ] || exit "$rc"
cat "$src" > "$out"
'''

GPG = '''#!/bin/sh
printf 'gpg %s\\n' "$*" >> "{log}"
exec "{real}" "$@"
'''

APT_GET = '''#!/bin/sh
printf 'apt-get %s\\n' "$*" >> "{log}"
case " $* " in
  *" install "*gnupg*) cp "{gpg_src}" "{bin}/gpg"; chmod 755 "{bin}/gpg" ;;
esac
exit 0
'''


def fingerprints(home, uid):
    out = subprocess.run([REAL_GPG, '--batch', '--with-colons', '--list-keys', uid],
                         env={'GNUPGHOME': str(home), 'PATH': os.environ['PATH']},
                         capture_output=True, text=True, check=True).stdout
    lines = out.splitlines()
    return [lines[i + 1].split(':')[9] for i, line in enumerate(lines)
            if line.startswith('pub:') and lines[i + 1].startswith('fpr:')]


def primaries(path, home):
    out = subprocess.run([REAL_GPG, '--batch', '--show-keys', '--with-colons', str(path)],
                         env={'GNUPGHOME': str(home), 'PATH': os.environ['PATH']},
                         capture_output=True, text=True, check=True).stdout
    lines = out.splitlines()
    return sorted({lines[i + 1].split(':')[9] for i, line in enumerate(lines)
                   if line.startswith('pub:') and i + 1 < len(lines) and lines[i + 1].startswith('fpr:')})


class InstallAptSourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if REAL_GPG is None:
            raise AssertionError('gpg がありません（この試験は skip しません。gnupg を入れてください）')
        cls.keys_tmp = tempfile.TemporaryDirectory()
        keys = Path(cls.keys_tmp.name)
        home = keys / 'home'
        home.mkdir(mode=0o700)
        env = {'GNUPGHOME': str(home), 'PATH': os.environ['PATH']}
        for uid in ('a@example.invalid', 'b@example.invalid'):
            subprocess.run([REAL_GPG, '--batch', '--passphrase', '', '--quick-gen-key', uid, 'ed25519', 'sign', 'never'],
                           env=env, capture_output=True, check=True)
        cls.fpr_a = fingerprints(home, 'a@example.invalid')[0]
        cls.fpr_b = fingerprints(home, 'b@example.invalid')[0]
        cls.key_a_bin = keys / 'a.gpg'
        cls.key_a_asc = keys / 'a.asc'
        cls.key_ab_bin = keys / 'ab.gpg'
        cls.key_ab_asc = keys / 'ab.asc'
        for path, armor, ids in ((cls.key_a_bin, False, [cls.fpr_a]), (cls.key_a_asc, True, [cls.fpr_a]),
                                 (cls.key_ab_bin, False, [cls.fpr_a, cls.fpr_b]),
                                 (cls.key_ab_asc, True, [cls.fpr_a, cls.fpr_b])):
            args = [REAL_GPG, '--batch', '--export'] + (['--armor'] if armor else []) + ids
            path.write_bytes(subprocess.run(args, env=env, capture_output=True, check=True).stdout)
        cls.garbage = keys / 'garbage.html'
        cls.garbage.write_text('<html><body>404</body></html>\n')
        subprocess.run(['gpgconf', '--kill', 'all'], env=env, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.keys_tmp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for tool in TOOLS:
            found = shutil.which(tool)
            if found:
                (self.bin / tool).symlink_to(found)
        self.log = self.root / 'calls.log'
        self.curl_log = self.root / 'curl.log'
        self.map = self.root / 'curl.map'
        self.map.write_text('')
        (self.bin / 'curl').write_text(CURL.replace('{log}', str(self.curl_log)).replace('{map}', str(self.map)))
        self.gpg_src = self.root / 'gpg-wrapper'
        self.gpg_src.write_text(GPG.replace('{log}', str(self.log)).replace('{real}', REAL_GPG))
        shutil.copy(self.gpg_src, self.bin / 'gpg')
        (self.bin / 'apt-get').write_text(APT_GET.replace('{log}', str(self.log)).replace('{gpg_src}', str(self.gpg_src))
                                          .replace('{bin}', str(self.bin)))
        for name in ('curl', 'gpg', 'apt-get'):
            (self.bin / name).chmod(0o755)
        self.keyrings = self.root / 'keyrings'
        self.sources = self.root / 'sources'
        owner = f'{pwd.getpwuid(os.getuid()).pw_name}:{grp.getgrgid(os.getgid()).gr_name}'
        text = SCRIPT.read_text()
        for old, new in (('readonly KEYRING_DIR=/etc/apt/keyrings\n', f'readonly KEYRING_DIR={self.keyrings}\n'),
                         ('readonly SOURCES_DIR=/etc/apt/sources.list.d\n', f'readonly SOURCES_DIR={self.sources}\n'),
                         ('readonly INSTALL_OWNER=root:root\n', f'readonly INSTALL_OWNER={owner}\n')):
            self.assertIn(old, text)
            text = text.replace(old, new)
        self.script = self.root / 'install-apt-sources.sh'
        self.script.write_text(text)
        self.input = self.root / 'apt-sources.norm'

    def tearDown(self):
        self.tmp.cleanup()

    def serve(self, url, fixture, rc=0):
        with self.map.open('a') as f:
            f.write(f'{url}\t{rc}\t{fixture}\n')

    def run_script(self, content):
        self.input.write_text(content)
        return subprocess.run([str(self.bin / 'sh'), str(self.script), str(self.input)],
                              env={'PATH': str(self.bin), 'HOME': str(self.root)},
                              capture_output=True, text=True, timeout=120)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ''

    def installed(self):
        names = []
        for d in (self.keyrings, self.sources):
            names += sorted(p.name for p in d.iterdir()) if d.exists() else []
        return names

    def line(self, name, url, fprs, uri='https://r.example/deb', suite='stable', comps='main'):
        return f'{name} {url} {",".join(fprs)} {uri} {suite} {comps}\n'

    def test_empty_input_does_nothing(self):
        result = self.run_script('')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.installed(), [])
        self.assertEqual(self.calls(), '')
        self.assertFalse(self.curl_log.exists())

    def test_single_key_match_writes_files(self):
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        result = self.run_script(self.line('a', 'https://k.example/a.gpg', [self.fpr_a], comps='main contrib'))
        self.assertEqual(result.returncode, 0, result.stderr)
        key = self.keyrings / 'c3c-a.gpg'
        lst = self.sources / 'c3c-a.list'
        self.assertEqual(primaries(key, self.root), [self.fpr_a])
        self.assertEqual(lst.read_text(), f'deb [signed-by={key}] https://r.example/deb stable main contrib\n')
        self.assertEqual(key.stat().st_mode & 0o777, 0o644)
        self.assertEqual(lst.stat().st_mode & 0o777, 0o644)
        self.assertNotIn(b'-----BEGIN', key.read_bytes())

    def test_names_do_not_collide_with_work_files(self):
        """取得元の名前が作業用のディレクトリやファイルの名前と同じでも動く（検査を通る名前はどれも使える）。"""
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        names = ['show', 'declared', 'got', 'exported', 'plan', 'colons', 'fprs']
        result = self.run_script(''.join(self.line(n, 'https://k.example/a.gpg', [self.fpr_a]) for n in names))
        self.assertEqual(result.returncode, 0, result.stderr)
        for n in names:
            self.assertEqual(primaries(self.keyrings / f'c3c-{n}.gpg', self.root), [self.fpr_a])

    def test_multi_primary_exact_set(self):
        self.serve('https://k.example/ab.gpg', self.key_ab_bin)
        result = self.run_script(self.line('ab', 'https://k.example/ab.gpg', sorted([self.fpr_a, self.fpr_b], reverse=True)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(primaries(self.keyrings / 'c3c-ab.gpg', self.root), sorted([self.fpr_a, self.fpr_b]))

    def test_declared_subset_rejected(self):
        self.serve('https://k.example/ab.gpg', self.key_ab_bin)
        result = self.run_script(self.line('ab', 'https://k.example/ab.gpg', [self.fpr_a]))
        self.assertEqual(result.returncode, 1)
        self.assertIn('指紋が一致しません', result.stderr)
        self.assertEqual(self.installed(), [])

    def test_declared_superset_rejected(self):
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        result = self.run_script(self.line('a', 'https://k.example/a.gpg', [self.fpr_a, self.fpr_b]))
        self.assertEqual(result.returncode, 1)
        self.assertIn('指紋が一致しません', result.stderr)
        self.assertEqual(self.installed(), [])

    def test_armored_and_binary_keys(self):
        self.serve('https://k.example/ab.asc', self.key_ab_asc)
        self.serve('https://k.example/ab.gpg', self.key_ab_bin)
        both = [self.fpr_a, self.fpr_b]
        result = self.run_script(self.line('x', 'https://k.example/ab.asc', both) + self.line('y', 'https://k.example/ab.gpg', both))
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('x', 'y'):
            key = self.keyrings / f'c3c-{name}.gpg'
            self.assertNotIn(b'-----BEGIN', key.read_bytes())
            self.assertEqual(primaries(key, self.root), sorted(both))

    def test_installed_key_has_only_declared_primaries(self):
        self.serve('https://k.example/a.asc', self.key_a_asc)
        result = self.run_script(self.line('a', 'https://k.example/a.asc', [self.fpr_a]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(primaries(self.keyrings / 'c3c-a.gpg', self.root), [self.fpr_a])
        self.assertRegex(self.calls(), r'gpg .*--export')
        self.assertRegex(self.calls(), r'gpg .*--import')

    def test_garbage_key_rejected(self):
        self.serve('https://k.example/a.gpg', self.garbage)
        result = self.run_script(self.line('a', 'https://k.example/a.gpg', [self.fpr_a]))
        self.assertEqual(result.returncode, 1)
        self.assertIn('ERROR:', result.stderr)
        self.assertEqual(self.installed(), [])

    def test_fetch_failure_writes_nothing(self):
        self.keyrings.mkdir()
        self.sources.mkdir()
        (self.keyrings / 'c3c-a.gpg').write_bytes(b'previous key')
        (self.sources / 'c3c-a.list').write_text('previous list\n')
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        self.serve('https://k.example/b.gpg', self.key_a_bin, rc=22)
        result = self.run_script(self.line('a', 'https://k.example/a.gpg', [self.fpr_a])
                                 + self.line('b', 'https://k.example/b.gpg', [self.fpr_a]))
        self.assertEqual(result.returncode, 1)
        self.assertIn('鍵を取得できません', result.stderr)
        self.assertEqual((self.keyrings / 'c3c-a.gpg').read_bytes(), b'previous key')
        self.assertEqual((self.sources / 'c3c-a.list').read_text(), 'previous list\n')
        self.assertEqual(self.installed(), ['c3c-a.gpg', 'c3c-a.list'])

    def test_curl_restricted_to_https(self):
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        result = self.run_script(self.line('a', 'https://k.example/a.gpg', [self.fpr_a]))
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.curl_log.read_text().split('\0')
        for pair in (('--proto', '=https'), ('--proto-redir', '=https')):
            self.assertIn(pair[0], args)
            self.assertEqual(args[args.index(pair[0]) + 1], pair[1])

    def test_last_line_without_newline(self):
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        result = self.run_script(self.line('a', 'https://k.example/a.gpg', [self.fpr_a]).rstrip('\n'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.installed(), ['c3c-a.gpg', 'c3c-a.list'])

    def test_refresh_overwrites_own_files(self):
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        content = self.line('a', 'https://k.example/a.gpg', [self.fpr_a])
        first = self.run_script(content)
        before = [(self.keyrings / 'c3c-a.gpg').read_bytes(), (self.sources / 'c3c-a.list').read_text()]
        second = self.run_script(content)
        for result in (first, second):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('INFO: a の鍵を照合して置きました', result.stderr)
        self.assertEqual([(self.keyrings / 'c3c-a.gpg').read_bytes(), (self.sources / 'c3c-a.list').read_text()], before)

    def test_installs_gnupg_only_when_missing(self):
        self.serve('https://k.example/a.gpg', self.key_a_bin)
        content = self.line('a', 'https://k.example/a.gpg', [self.fpr_a])
        result = self.run_script(content)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('apt-get', self.calls())
        (self.bin / 'gpg').unlink()
        self.log.unlink()
        result = self.run_script(content)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apt-get install -y --no-install-recommends gnupg', self.calls())


if __name__ == '__main__':
    unittest.main()
