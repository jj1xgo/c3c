# Claude 経路の project 設定ゲート（#163）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude 経路で、リポジトリ同梱の `.claude/settings.json`・`.claude/settings.local.json` を初回・変更時にホストで確認させ、plugin 類と `.mcp.json` の `headersHelper` を起動前に止める。

**Architecture:** 新しい固定アセット `claude-project-audit.py` をイメージに入れ、検査用コンテナ（Codex の preflight と同じ作法）で `/workspace` を審査して protocol の JSON を出す。launcher がホストで検証・確認・承認記録（`:ro`）を行い、本起動の `entrypoint.sh` が同じ helper で再照合する。対応 label の無いイメージでは、審査対象を持つ repo は起動しない。

**Tech Stack:** bash（`c3c`・`entrypoint.sh`）、python3 標準ライブラリ（helper と unittest）、Podman Compose、既存の `test-build.sh` / `lint.sh`。

**Spec:** `docs/superpowers/specs/2026-09-26-claude-project-settings-gate-design.md`（実装前に全文を読む）

## Global Constraints

- protocol 版: `1`。image label: `io.c3c.claude-project-audit-protocol="1"`。launcher 定数 `CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION=1`・`CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL=io.c3c.claude-project-audit-protocol`（`readonly`）。
- helper の固定パス: イメージ内 `/usr/local/bin/claude-project-audit.py`（root 所有 755、`USER node` より前の `COPY`）。呼び出しは常に `python3 -I`。
- 承認記録のコンテナ内パス: `/etc/claude-container/claude-project-approved.json`（`:ro`）。compose の source は `${CLAUDE_PROJECT_APPROVAL_FILE:-/dev/null}`。
- 承認記録のホスト側パス: `$HOME/.local/state/claude-container/mcp-approvals/claude-project/$PROJECT_NAME.json`。内容は `{"protocol_version":1,"hash":"<64 桁小文字 hex>"}` + 改行。書き込みは umask 077、ディレクトリ 700、同じディレクトリの一時ファイルから `mv -f` の atomic replace。
- 起動モード変数: `CC_CLAUDE_START_MODE`（`run` | `preflight`）。compose の既定は `${CC_CLAUDE_START_MODE-run}`（未設定のときだけ既定。空文字は entrypoint で拒否）。
- helper の終了コード: `0` 通す（対象なし・記録と一致・snapshot 成功・`--help`）、`1` 止める（止める判定・判定不能・引数不正。argparse の誤りも `SystemExit` を捕まえて 1 に寄せる）、`3` 確認が要る（verify で未承認・変更あり）。snapshot の JSON は `ensure_ascii=True` で出す（stdout の符号化に依存しない）。
- hash の対象: `.claude/settings.json` と `.claude/settings.local.json` のファイル全体（存在するものだけ）。符号化: `sha256(b'c3c-claude-project-audit\x00v1\x00' + Σ(len(path) 8 byte BE + path + len(data) 8 byte BE + data))`、path は相対パスの UTF-8 バイト列で昇順。
- 上限: 1 ファイル 1 MiB（1048576 バイト）を超えたら判定不能。表示は 1 ファイル 200 行まで（超えたら省略行数を明示）。
- 止める判定: `enabledPlugins` に値が `false` でないエントリ、`extraKnownMarketplaces` が空でない、`env` に `CLAUDE_CODE_PLUGIN_` で始まる key、`.claude/skills/*/.claude-plugin/plugin.json` が存在、`.mcp.json` の `mcpServers.<name>` に `headersHelper` key。
- 環境変数による opt-out は作らない。launcher は `CLAUDE_PROJECT_APPROVAL_FILE`・`CC_CLAUDE_START_MODE` を全分岐で明示 export し、env ファイル由来の値を使わない。
- 対象 repo で git を実行しない。c3c（launcher・entrypoint・helper）はホストの `~/.claude.json` に書かない（Claude Code 本体は従来どおり書く）。
- 日本語で書く（README.md「表記」節）。挙動を変えたら README.md の該当節も同じコミットで更新する（各 Task の README の Step はそのためにある。Task 6 は README 以外の文書）。ファイルを編集したら `./lint.sh` を実行し、終了コード 0・警告ゼロを確認する。

## Review Focus

- `.claude` が `/workspace` の外を指す symlink（絶対パス）: 検査用コンテナでも本起動でも判定不能で止まる（Task 1 の unittest `test_outward_symlinks_are_undecidable`）。
- 検査の後・本起動の前に `settings.json` が書き換えられる: 本起動の entrypoint が確認を出し、TTY が無ければ止まる（Task 3 の `test_run_prompts_when_changed_after_approval_and_blocks_without_tty`）。
- `.claude` も `.mcp.json` も無い repo を旧イメージで起動する: 従来どおり起動し、検査用コンテナも label 照合も行わない（Task 4 の `test_no_targets_skips_gate_even_on_old_image`）。
- 承認記録ファイルが壊れている・別 protocol: ホストは再確認を求め、コンテナ内でも「記録なし」と同じ扱いで確認になる（Task 1 の `test_verify_treats_malformed_record_as_missing`、Task 4 の `test_corrupt_record_requires_reconfirmation`）。
- `CC_CLAUDE_START_MODE` を `.c3c/env` や secrets/export で差し替える: launcher は env の値を使わず、entrypoint は enum 外を拒否する（Task 3 の `test_claude_mode_enum_is_validated_before_firewall`、Task 4 の `test_env_file_cannot_set_claude_gate_variables`）。

---

### Task 1: 審査 helper `claude-project-audit.py` と unittest

**Files:**
- Create: `claude-project-audit.py`
- Create: `tests/test_claude_project_audit.py`
- Modify: `test-build.sh`（`run_launcher_tests()` に 1 行登録）

**Interfaces:**
- Produces: CLI `python3 -I claude-project-audit.py --root <絶対パス> snapshot` → stdout に JSON 1 文書 `{"protocol_version":1,"hash":str,"count":int,"lines":[str]}` と改行、rc 0。止める・判定不能は stderr に `ERROR: ...`、rc 1。
- Produces: CLI `... --root <絶対パス> verify <record>` → rc 0（対象なし・一致）、rc 3（確認が要る。stderr に表示行）、rc 1（止める・判定不能）。`<record>` が空（`/dev/null`）・壊れている・別 protocol のときは「記録なし」として扱う。
- Produces: Python 関数 `snapshot(root) -> dict`、`canonical_hash(files) -> str`（`files` は `[(rel: str, data: bytes)]`）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_claude_project_audit.py`:

```python
#!/usr/bin/env python3
"""Claude 経路の project 設定ゲート helper（#163、protocol 1）の回帰試験。

helper は /workspace に当たる --root の `.claude/settings.json`・`.claude/settings.local.json` をファイル全体で
hash し、plugin 類と `.mcp.json` の headersHelper を止める。ここで固定する protocol と終了コードは
launcher（c3c）と entrypoint.sh が消費する。
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / 'claude-project-audit.py'
DOMAIN = b'c3c-claude-project-audit\x00v1\x00'
HOOKS = {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo hi'}]}]}}


def expected_hash(files):
    digest = hashlib.sha256(DOMAIN)
    for rel, data in sorted(files, key=lambda item: item[0].encode()):
        path = rel.encode()
        digest.update(len(path).to_bytes(8, 'big') + path + len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest()


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'workspace'
        (self.root / '.claude').mkdir(parents=True)
        self.record = self.base / 'record.json'

    def put(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else json.dumps(content).encode()
        path.write_bytes(data)
        return data

    def run_helper(self, *args, root=None):
        return subprocess.run([sys.executable, '-I', str(HELPER), '--root', str(root or self.root), *args],
                              capture_output=True, text=True, timeout=30)

    def snapshot(self):
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_blocked(self, needle):
        result = self.run_helper('snapshot')
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout, '')
        self.assertIn(needle, result.stderr)
        verify = self.run_helper('verify', os.devnull)
        self.assertEqual(verify.returncode, 1)


class SnapshotTests(AuditCase):
    def test_no_targets_is_count_zero_with_empty_lines(self):
        doc = self.snapshot()
        self.assertEqual(doc, {'protocol_version': 1, 'hash': expected_hash([]), 'count': 0, 'lines': []})

    def test_hash_covers_whole_settings_files_with_fixed_encoding(self):
        a = self.put('.claude/settings.json', HOOKS)
        b = self.put('.claude/settings.local.json', {'permissions': {'allow': ['Bash(ls:*)']}})
        doc = self.snapshot()
        self.assertEqual(doc['count'], 2)
        self.assertEqual(doc['hash'], expected_hash([('.claude/settings.json', a), ('.claude/settings.local.json', b)]))

    def test_any_byte_change_changes_hash_including_unknown_keys(self):
        self.put('.claude/settings.json', HOOKS)
        first = self.snapshot()['hash']
        self.put('.claude/settings.json', dict(HOOKS, statusLine={'type': 'command', 'command': 'x'}))
        self.assertNotEqual(self.snapshot()['hash'], first)
        self.put('.claude/settings.json', json.dumps(HOOKS, indent=2).encode())
        self.assertNotEqual(self.snapshot()['hash'], first)

    def test_hash_is_independent_of_read_order_and_length_prefixed(self):
        a = self.put('.claude/settings.json', {'a': 1})
        b = self.put('.claude/settings.local.json', {'b': 2})
        forward = expected_hash([('.claude/settings.json', a), ('.claude/settings.local.json', b)])
        self.assertEqual(forward, expected_hash([('.claude/settings.local.json', b), ('.claude/settings.json', a)]))
        self.assertEqual(self.snapshot()['hash'], forward)
        # 区切りの衝突: 内容の境界をずらしても同じ hash にならない（長さの前置き）。
        self.assertNotEqual(expected_hash([('x', b'ab'), ('y', b'c')]), expected_hash([('x', b'a'), ('y', b'bc')]))

    def test_local_settings_is_always_hashed(self):
        self.put('.claude/settings.local.json', {'permissions': {'allow': []}})
        self.assertEqual(self.snapshot()['count'], 1)

    def test_display_shows_whole_file_including_env_values_without_control_chars(self):
        self.put('.claude/settings.json', b'{"env": {"BASH_ENV": "./x.sh\\u001b[2J"},\n "k": "a\x7fb"}')
        lines = self.snapshot()['lines']
        self.assertEqual(lines[0], '--- .claude/settings.json ---')
        joined = '\n'.join(lines)
        self.assertIn('BASH_ENV', joined)
        self.assertIn('./x.sh', joined)
        for line in lines:
            self.assertNotRegex(line, '[\x00-\x1f\x7f]')

    def test_display_truncates_after_200_lines_and_says_so(self):
        body = '{\n' + ',\n'.join(f'"k{i}": {i}' for i in range(300)) + '\n}'
        self.put('.claude/settings.json', body.encode())
        lines = self.snapshot()['lines']
        self.assertEqual(len(lines), 1 + 200 + 1)
        self.assertIn('省略', lines[-1])

    def test_disabled_plugins_and_empty_marketplaces_are_allowed(self):
        self.put('.claude/settings.json', {'enabledPlugins': {'x@y': False}, 'extraKnownMarketplaces': {}})
        self.assertEqual(self.snapshot()['count'], 1)


class BlockTests(AuditCase):
    def test_enabled_plugins_are_blocked(self):
        for value in (True, 'yes', None, 1):
            with self.subTest(value=value):
                self.put('.claude/settings.json', {'enabledPlugins': {'evil@mk': value}})
                self.assert_blocked('enabledPlugins')

    def test_plugins_in_local_settings_are_blocked(self):
        self.put('.claude/settings.local.json', {'enabledPlugins': {'evil@mk': True}})
        self.assert_blocked('settings.local.json')

    def test_marketplaces_are_blocked(self):
        self.put('.claude/settings.json', {'extraKnownMarketplaces': {'mk': {'source': {'source': 'github', 'repo': 'a/b'}}}})
        self.assert_blocked('extraKnownMarketplaces')

    def test_plugin_env_keys_are_blocked(self):
        self.put('.claude/settings.json', {'env': {'CLAUDE_CODE_PLUGIN_DIRS': '/workspace/p'}})
        self.assert_blocked('CLAUDE_CODE_PLUGIN_DIRS')

    def test_skills_directory_plugin_is_blocked(self):
        self.put('.claude/skills/tool/.claude-plugin/plugin.json', {'name': 'tool'})
        self.assert_blocked('plugin.json')

    def test_mcp_headers_helper_is_blocked(self):
        self.put('.mcp.json', {'mcpServers': {'remote': {'type': 'http', 'url': 'https://x', 'headersHelper': '/bin/x'}}})
        self.assert_blocked('headersHelper')

    def test_mcp_without_helper_is_not_a_target(self):
        self.put('.mcp.json', {'mcpServers': {'s': {'command': 'node'}}})
        self.assertEqual(self.snapshot()['count'], 0)


class UndecidableTests(AuditCase):
    def test_broken_or_non_object_or_duplicate_json_is_undecidable(self):
        for data in (b'{broken', b'[]', b'{"a": 1, "a": 2}', b'{"a": NaN}', b'\xff\xfe'):
            with self.subTest(data=data):
                self.put('.claude/settings.json', data)
                self.assert_blocked('判定できません')

    def test_wrong_types_of_checked_keys_are_undecidable(self):
        for doc in ({'enabledPlugins': []}, {'extraKnownMarketplaces': 'x'}, {'env': ['a']}):
            with self.subTest(doc=doc):
                self.put('.claude/settings.json', doc)
                self.assert_blocked('判定できません')
        (self.root / '.claude' / 'settings.json').unlink()
        self.put('.mcp.json', {'mcpServers': []})
        self.assert_blocked('判定できません')

    def test_outward_symlinks_are_undecidable(self):
        outside = self.base / 'outside'
        (outside / '.claude').mkdir(parents=True)
        (outside / '.claude' / 'settings.json').write_text(json.dumps(HOOKS))
        cases = (('.claude/settings.json', outside / '.claude' / 'settings.json'),
                 ('.mcp.json', outside / '.claude' / 'settings.json'))
        for rel, target in cases:
            with self.subTest(rel=rel):
                link = self.root / rel
                link.symlink_to(target)
                self.assert_blocked('判定できません')
                link.unlink()
        (self.root / '.claude').rmdir()
        (self.root / '.claude').symlink_to(outside / '.claude')
        self.assert_blocked('判定できません')

    def test_dangling_and_looping_symlinks_are_undecidable(self):
        link = self.root / '.claude' / 'settings.json'
        link.symlink_to(self.root / 'missing.json')
        self.assert_blocked('判定できません')
        link.unlink()
        a, b = self.root / 'a', self.root / 'b'
        a.symlink_to(b)
        b.symlink_to(a)
        link.symlink_to(a)
        self.assert_blocked('判定できません')

    def test_inward_symlink_is_followed(self):
        real = self.put('shared/settings.json', HOOKS)
        (self.root / '.claude' / 'settings.json').symlink_to(self.root / 'shared' / 'settings.json')
        self.assertEqual(self.snapshot()['hash'], expected_hash([('.claude/settings.json', real)]))

    def test_fifo_and_directory_are_undecidable_without_blocking(self):
        os.mkfifo(self.root / '.claude' / 'settings.json')
        self.assert_blocked('判定できません')
        (self.root / '.claude' / 'settings.json').unlink()
        (self.root / '.claude' / 'settings.json').mkdir()
        self.assert_blocked('判定できません')

    def test_oversized_file_is_undecidable(self):
        self.put('.claude/settings.json', b'{"a": "' + b'x' * (1024 * 1024) + b'"}')
        self.assert_blocked('判定できません')

    @unittest.skipIf(os.geteuid() == 0, 'root は読み取り権限を無視する')
    def test_unreadable_file_and_unlistable_skills_are_undecidable(self):
        path = self.root / '.claude' / 'settings.json'
        self.put('.claude/settings.json', HOOKS)
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        self.assert_blocked('判定できません')
        path.chmod(0o644)
        skills = self.root / '.claude' / 'skills'
        skills.mkdir()
        skills.chmod(0)
        self.addCleanup(skills.chmod, 0o755)
        self.assert_blocked('判定できません')

    @unittest.skipIf(os.geteuid() == 0, 'root は検索権限を無視する')
    def test_unsearchable_claude_dir_is_undecidable_not_absent(self):
        self.put('.claude/settings.json', HOOKS)
        claude = self.root / '.claude'
        claude.chmod(0o600)
        self.addCleanup(claude.chmod, 0o755)
        self.assert_blocked('判定できません')

    def test_bad_arguments_exit_1_and_help_exits_0(self):
        bad = subprocess.run([sys.executable, '-I', str(HELPER), 'snapshot'], capture_output=True, text=True, timeout=30)
        self.assertEqual(bad.returncode, 1)
        ok = subprocess.run([sys.executable, '-I', str(HELPER), '--help'], capture_output=True, text=True, timeout=30)
        self.assertEqual(ok.returncode, 0)

    def test_relative_root_is_rejected(self):
        result = subprocess.run([sys.executable, '-I', str(HELPER), '--root', 'workspace', 'snapshot'],
                                capture_output=True, text=True, cwd=self.base, timeout=30)
        self.assertEqual(result.returncode, 1)


class VerifyTests(AuditCase):
    def approve(self):
        doc = self.snapshot()
        self.record.write_text(json.dumps({'protocol_version': 1, 'hash': doc['hash']}, separators=(',', ':')) + '\n')

    def test_no_targets_passes_without_record(self):
        self.assertEqual(self.run_helper('verify', os.devnull).returncode, 0)

    def test_matching_record_passes_and_change_requires_review(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve()
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 0)
        self.put('.claude/settings.json', dict(HOOKS, extra=1))
        result = self.run_helper('verify', str(self.record))
        self.assertEqual(result.returncode, 3)
        self.assertIn('--- .claude/settings.json ---', result.stderr)

    def test_missing_record_requires_review(self):
        self.put('.claude/settings.json', HOOKS)
        self.assertEqual(self.run_helper('verify', os.devnull).returncode, 3)

    def test_verify_treats_malformed_record_as_missing(self):
        self.put('.claude/settings.json', HOOKS)
        doc = self.snapshot()
        for text in ('', '{broken', json.dumps({'protocol_version': 2, 'hash': doc['hash']}),
                     json.dumps({'protocol_version': 1, 'hash': doc['hash'], 'x': 1})):
            with self.subTest(text=text):
                self.record.write_text(text)
                self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 3)

    def test_blocked_state_wins_over_matching_record(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve()
        self.put('.mcp.json', {'mcpServers': {'r': {'url': 'https://x', 'headersHelper': 'x'}}})
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 1)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_audit.py`
Expected: FAIL（`claude-project-audit.py` が無いので subprocess が rc 2 を返し、各テストが失敗する）

- [ ] **Step 3: helper を実装する**

`claude-project-audit.py`（実行権限 755 で作る: `chmod 755 claude-project-audit.py`）:

```python
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
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_audit.py -v`
Expected: PASS（root で実行する環境では `test_unreadable_file_and_unlistable_skills_are_undecidable` は skip）

- [ ] **Step 5: `run_launcher_tests()` に登録する**

`test-build.sh` の `run_launcher_tests()` 内、`test_codex_mcp_audit.py` の行の直後に追加:

```bash
  check "Claude project 設定ゲート helper（全体 hash・停止条件・判定不能・verify）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_claude_project_audit.py"
```

- [ ] **Step 6: lint を通す**

Run: `./lint.sh`
Expected: `lint OK`、終了コード 0

- [ ] **Step 7: Commit**

```bash
git add claude-project-audit.py tests/test_claude_project_audit.py test-build.sh
git commit -m "feat: Claude 経路の project 設定ゲート helper を追加する（#163）"
```

---

### Task 2: イメージ・アセット・compose・lint への登録

**Files:**
- Modify: `Dockerfile.claude`（`codex-mcp-audit.py` の `COPY` の直後、`LABEL io.c3c.codex-audit-protocol` の直後）
- Modify: `c3c`（`resolve_asset_source()` の fixed の case、`ASSET_HASH_TARGETS`、`stage_build_context()` の固定アセットのループ）
- Modify: `compose.yml`（environment と volumes）
- Modify: `compose.codex-preflight.yml`（コメントだけ。Claude の検査用コンテナでも同じ override を使う）
- Modify: `lint.sh`（`:ro` の検査対象と environment の検査）
- Modify: `test-build.sh`（`run_config_ro_launcher_tests()` のコピー一覧、`stage_common_context()`、実イメージの helper 起動確認）
- Modify: `tests/test_network_timeouts.py`（run_dir へコピーする固定アセットのタプル。`stage_build_context` を `set -e` で呼ぶので、足さないと赤になる）
- Modify: `tests/test_c3c_config.py`（固定アセットを project 側から上書きできないことの一覧）
- Modify: `tests/test_codex_entrypoint.py`（`ComposeContractTests` の compose 実解決の key）

**Interfaces:**
- Consumes: Task 1 の `claude-project-audit.py`
- Produces: イメージ内 `/usr/local/bin/claude-project-audit.py`、label `io.c3c.claude-project-audit-protocol="1"`、compose の `CC_CLAUDE_START_MODE` と `/etc/claude-container/claude-project-approved.json` の `:ro` マウント

- [ ] **Step 1: Dockerfile.claude に COPY と LABEL を足す**

`RUN chmod 755 /usr/local/bin/codex-mcp-audit.py` の直後に:

```dockerfile

# Claude 経路の project 設定ゲート helper（#163）。entrypoint.sh が検査用コンテナの snapshot と本起動の
# verify で同じ固定パスを python3 -I で呼ぶ。他の境界アセットと同じ root 所有 755。対応する protocol 版は
# 下の LABEL io.c3c.claude-project-audit-protocol。
COPY claude-project-audit.py /usr/local/bin/claude-project-audit.py
RUN chmod 755 /usr/local/bin/claude-project-audit.py
```

`LABEL io.c3c.codex-audit-protocol="2"` の直後に:

```dockerfile
# Claude 経路の project 設定ゲートの protocol（#163）。launcher は、.claude か .mcp.json を持つ repo では
# この label が対応 protocol（1）と一致するイメージでだけ検査用コンテナと本起動を行う。
LABEL io.c3c.claude-project-audit-protocol="1"
```

- [ ] **Step 2: c3c の固定アセット一覧 3 か所に加える**

`resolve_asset_source()` の fixed の case の `codex-mcp-audit.py |` の直後に `claude-project-audit.py |` を加える。`ASSET_HASH_TARGETS` の `codex-mcp-audit.py` の行の直後に `  claude-project-audit.py` を加える。`stage_build_context()` の `for name in entrypoint.sh ... codex-mcp-audit.py codex-launcher.sh ...` の `codex-mcp-audit.py` の直後に `claude-project-audit.py` を加える。同じファイル冒頭付近の fixed 一覧のコメント（`codex-mcp-audit.py・codex-launcher.sh・固定 Compose override 群）`）にも `claude-project-audit.py` を加える。

- [ ] **Step 3: compose.yml に環境変数とマウントを足す**

environment の `CC_CODEX_READ_ONLY: ${CC_CODEX_READ_ONLY-0}` の直後に:

```yaml
      # Claude 経路の起動モード（#163）。preflight は project 設定ゲートの検査用コンテナ。launcher が
      # 明示 export する。未設定のときだけ run（空文字を含む不正値は entrypoint が拒否する）。
      CC_CLAUDE_START_MODE: ${CC_CLAUDE_START_MODE-run}
```

volumes の `- ${CODEX_MCP_APPROVAL_FILE:-/dev/null}:/etc/claude-container/codex-mcp-approved.json:ro` の直後に:

```yaml
      # Claude の project 設定ゲートの承認記録（#163）。launcher が全分岐で明示 export した値だけを使う。
      - ${CLAUDE_PROJECT_APPROVAL_FILE:-/dev/null}:/etc/claude-container/claude-project-approved.json:ro
```

- [ ] **Step 4: compose.codex-preflight.yml のコメントを直す**

1 行目のコメントを「Codex の起動時 MCP 審査と Claude の project 設定ゲート（#163）で使う検査用コンテナの固定 override」に変え、3 行目以降の説明に「Claude では CC_CLAUDE_START_MODE=preflight を launcher が明示 export する」を足す。`services:` 以下は変えない。

- [ ] **Step 5: lint.sh の検査対象を足す**

`for target in /etc/claude-container/codex-mcp-approved.json /etc/claude-container/mcp-approved-hash /home/node/.gitconfig; do` を次に変える:

```bash
    for target in /etc/claude-container/codex-mcp-approved.json /etc/claude-container/mcp-approved-hash /etc/claude-container/claude-project-approved.json /home/node/.gitconfig; do
```

その直後の `CC_CODEX_START_MODE` の grep の直後に:

```bash
    grep -qE '^\s*CC_CLAUDE_START_MODE:' <<<"$base" \
      || { echo "ERROR: compose.yml の environment に CC_CLAUDE_START_MODE がありません" >&2; status=1; }
```

`compose.codex-preflight.yml` を積んだ `merged` の検査（`compose_mount_is_ro /etc/claude-container/codex-mcp-approved.json <<<"$merged"`）の直後に:

```bash
    compose_mount_is_ro /etc/claude-container/claude-project-approved.json <<<"$merged" || status=1
```

- [ ] **Step 6: test-build.sh のコピー一覧と実イメージ確認を足す**

`run_config_ro_launcher_tests()` の `cp -- "${SCRIPT_DIR}/"{...}` の波括弧内で `codex-mcp-audit.py,` の直後に `claude-project-audit.py,` を加える。`stage_common_context()` の `cp "${SCRIPT_DIR}/codex-mcp-audit.py" ...` の直後に:

```bash
  cp "${SCRIPT_DIR}/claude-project-audit.py" "$dest/claude-project-audit.py"
```

「## Claude Code ツール」の `Codex 審査 helper の依存モジュールと起動` の直後に:

```bash
check "Claude project 設定ゲート helper の起動" podman run --rm --network=none "$IMAGE" python3 -I /usr/local/bin/claude-project-audit.py --help
check "Claude project 設定ゲートの protocol label" bash -c '[ "$(podman image inspect --format "{{index .Labels \"io.c3c.claude-project-audit-protocol\"}}" "$1")" = 1 ]' _ "$IMAGE"
```

- [ ] **Step 7: 固定リストを持つ既存テストを直す**

`tests/test_network_timeouts.py` の `for file in ('entrypoint.sh', ..., 'codex-mcp-audit.py', ...)` のタプルに `'claude-project-audit.py'` を加える。`tests/test_c3c_config.py` の `test_fixed_boundary_assets_cannot_be_overridden_from_the_new_layout` の `for name in (...)` に `'claude-project-audit.py'` を加える（旧配置の同種のテストがあれば同じく加える: `grep -n "'codex-mcp-audit.py'" tests/*.py` で固定リストをすべて洗い出し、同じ扱いにする）。

`tests/test_codex_entrypoint.py` の `ComposeContractTests` で、`KEYS` に `'CC_CLAUDE_START_MODE'` を加え、key の正規表現 `(CC_AGENT|CC_CODEX_START_MODE|CC_CODEX_READ_ONLY)` に `|CC_CLAUDE_START_MODE` を加える。`test_unset_defaults_reach_entrypoint_as_claude_run` の期待値の辞書と、`test_codex_selection_resolves_to_run_or_preflight_only_when_explicit` の `assertEqual(values, {...})` の期待値の辞書の両方に `'CC_CLAUDE_START_MODE': 'run'` を加える（`resolved()` が返す辞書に 4 つ目の key が必ず入るため。3 key の辞書と完全一致を見ているテストは `grep -n "'CC_CODEX_READ_ONLY':" tests/test_codex_entrypoint.py` で洗い出し、すべて直す）。`test_explicit_empty_or_unknown_values_are_not_defaulted_and_are_rejected` の表に次の 2 行を足す（`run_entrypoint` の呼び出しに `claude_mode=values.get('CC_CLAUDE_START_MODE')` を渡す。`claude_mode` 引数は Task 3 Step 1 で足すので、この 2 行の追加は Task 3 Step 1 の後に行う）:

```python
            'empty claude mode': ({'CC_AGENT': 'claude', 'CC_CLAUDE_START_MODE': ''}, 'CC_CLAUDE_START_MODE', ''),
            'unknown claude mode': ({'CC_AGENT': 'claude', 'CC_CLAUDE_START_MODE': 'verify'}, 'CC_CLAUDE_START_MODE', 'verify'),
```

- [ ] **Step 8: 検証する**

Run: `./lint.sh`
Expected: `lint OK`、終了コード 0（Compose 検証を含む。環境制約でスキップした場合は `not run` と理由を記録する）

Run: `./test-build.sh --launcher-only`
Expected: `FAIL=0`（ここでは entrypoint がまだ `CC_CLAUDE_START_MODE` を検証しないので、ComposeContractTests の拒否の 2 行は Task 3 で足す。落ちたテストがあれば、固定リストを持つテストの漏れを先に疑う）

- [ ] **Step 9: Commit**

```bash
git add Dockerfile.claude c3c compose.yml compose.codex-preflight.yml lint.sh test-build.sh tests/test_network_timeouts.py tests/test_c3c_config.py tests/test_codex_entrypoint.py
git commit -m "feat: project 設定ゲートの helper をイメージ・アセット・compose に登録する（#163）"
```

---

### Task 3: entrypoint.sh の検査用コンテナと本起動の再照合

**Files:**
- Modify: `entrypoint.sh`
- Modify: `tests/test_codex_entrypoint.py`（固定パスの置換に新しい 3 つを加える）
- Create: `tests/test_claude_project_entrypoint.py`
- Modify: `test-build.sh`（`run_launcher_tests()` に 1 行登録）
- Modify: `README.md`（ファイル構成の `entrypoint.sh` の項と `claude-project-audit.py` の項、「変更後の確認」節）

**Interfaces:**
- Consumes: helper の CLI（Task 1）、`CC_CLAUDE_START_MODE`（Task 2）
- Produces: `CC_AGENT=claude CC_CLAUDE_START_MODE=preflight` で fd3 に protocol の JSON だけを出して rc 0（止める・判定不能は rc 1、stdout は空）。`run` では `.mcp.json` ゲートの直後、秘密の export より前に verify し、rc 3 なら `/dev/tty` で確認する。

- [ ] **Step 1: 既存の entrypoint テストの置換に新しい固定値を足す**

`tests/test_codex_entrypoint.py` の定数に追加:

```python
CLAUDE_PROJECT_AUDIT = '/usr/local/bin/claude-project-audit.py'
CLAUDE_PROJECT_APPROVED = '/etc/claude-container/claude-project-approved.json'
CLAUDE_PROJECT_ROOT = 'CLAUDE_PROJECT_ROOT=/workspace'
```

`setUp()` の needle のタプルに `CLAUDE_PROJECT_AUDIT, CLAUDE_PROJECT_APPROVED, CLAUDE_PROJECT_ROOT` を加え、置換の連鎖に次を加える（`self.claude_project_approved = self.root / 'claude-project-approved.json'` を setUp で定義する）:

```python
                  .replace(CLAUDE_PROJECT_AUDIT, str(ROOT / 'claude-project-audit.py'))
                  .replace(CLAUDE_PROJECT_APPROVED, str(self.claude_project_approved))
                  .replace(CLAUDE_PROJECT_ROOT, 'CLAUDE_PROJECT_ROOT=' + str(self.workspace))
```

`run_entrypoint()` に引数 `claude_mode=None` を足し、`('CC_CLAUDE_START_MODE', claude_mode)` を環境へ渡すループに加える。

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_claude_project_entrypoint.py`:

```python
#!/usr/bin/env python3
"""entrypoint の Claude project 設定ゲート（#163）の回帰試験。

tests/test_codex_entrypoint.py の EntrypointCase（固定パスを試験用コピーへ置換する fixture）を使う。
helper は実物の claude-project-audit.py。確認の応答は専用 PTY から /dev/tty へ流す。
"""

import fcntl
import json
import os
import pty
import subprocess
import sys
import termios
import unittest

from test_codex_entrypoint import EntrypointCase, ROOT

HOOKS = {'hooks': {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'echo hi'}]}]}}

# helper の呼び出し時点の環境を記録してから実物へ exec する wrapper（entrypoint は python3 -I で呼ぶので Python で書く）。
# 秘密（secrets/export の MCP_TOKEN）が helper の時点で未設定であることを観測し、ゲートが秘密の export より前にあることを確かめる。
AUDIT_WRAPPER = '''import os, sys
with open(os.environ['RECORD'], 'a') as out:
    out.write('audit MCP_TOKEN=%%s\\n' %% os.environ.get('MCP_TOKEN', 'unset'))
os.execv(sys.executable, [sys.executable, '-I', %r] + sys.argv[1:])
'''


class ClaudeProjectEntrypointCase(EntrypointCase):
    def setUp(self):
        super().setUp()
        wrapper = self.root / 'audit-wrapper.py'
        wrapper.write_text(AUDIT_WRAPPER % str(ROOT / 'claude-project-audit.py'))
        text = self.entrypoint.read_text()
        self.assertIn(str(ROOT / 'claude-project-audit.py'), text)
        self.entrypoint.write_text(text.replace(str(ROOT / 'claude-project-audit.py'), str(wrapper)))

    def audit_records(self):
        return [r for r in self.records if r.startswith('audit ')]

    def put(self, rel, doc):
        path = self.workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def run_claude(self, mode=None, tty_answer=None):
        if tty_answer is None:
            return self.run_entrypoint('claude', claude_mode=mode)
        self.state_path.write_text(json.dumps(self.state))
        self.record.write_text('')
        self.calls.write_text('')
        env = dict(self.env, CC_AGENT='claude')
        if mode is not None:
            env['CC_CLAUDE_START_MODE'] = mode
        master, slave = pty.openpty()

        def preexec():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(['bash', str(self.entrypoint)], env=env, cwd=self.root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=preexec,
                                pass_fds=(slave,))
        os.close(slave)
        os.write(master, (tty_answer + '\n').encode())
        try:
            stdout, stderr = proc.communicate(timeout=90)
        finally:
            os.close(master)
        self.records = self.record.read_text().splitlines()
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)

    def approve_from_preflight(self):
        result = self.run_entrypoint('claude', claude_mode='preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        self.claude_project_approved.write_text(json.dumps({'protocol_version': 1, 'hash': doc['hash']}) + '\n')
        return doc

    def launched(self):
        return any(r.startswith('claude --permission-mode') for r in self.records)


class PreflightTests(ClaudeProjectEntrypointCase):
    def test_preflight_stdout_is_only_the_protocol_and_claude_is_not_started(self):
        self.put('.claude/settings.json', HOOKS)
        (self.workspace / '.mcp.json').write_text(json.dumps({'mcpServers': {'s': {'command': 'evil'}}}))
        result = self.run_entrypoint('claude', claude_mode='preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        self.assertEqual(set(doc), {'protocol_version', 'hash', 'count', 'lines'})
        self.assertEqual(doc['count'], 1)
        self.assertIn('firewall stdout noise', result.stderr)
        self.assertFalse(self.launched())
        self.assertNotIn('MCP サーバーの起動を許可', result.stderr)

    def test_preflight_block_is_nonzero_with_empty_stdout(self):
        self.put('.claude/settings.json', {'enabledPlugins': {'x@y': True}})
        result = self.run_entrypoint('claude', claude_mode='preflight')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('enabledPlugins', result.stderr)

    def test_claude_mode_enum_is_validated_before_firewall(self):
        for mode in ('', 'verify', 'Preflight'):
            with self.subTest(mode=mode):
                result = self.run_entrypoint('claude', claude_mode=mode)
                self.assertEqual(result.returncode, 1)
                self.assertIn('CC_CLAUDE_START_MODE', result.stderr)
                self.assertEqual(self.records, [])


class RunTests(ClaudeProjectEntrypointCase):
    def test_no_targets_launches_as_before(self):
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.launched())

    def test_approved_record_launches_without_prompt(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.launched())

    def test_run_prompts_when_changed_after_approval_and_blocks_without_tty(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        self.put('.claude/settings.json', dict(HOOKS, env={'X': '1'}))
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 1)
        self.assertIn('TTY', result.stderr)
        self.assertFalse(self.launched())

    def test_run_prompt_yes_launches_and_no_blocks(self):
        self.put('.claude/settings.json', HOOKS)
        yes = self.run_claude('run', tty_answer='y')
        self.assertEqual(yes.returncode, 0, yes.stderr)
        self.assertIn('--- .claude/settings.json ---', yes.stderr)
        self.assertTrue(self.launched())
        no = self.run_claude('run', tty_answer='n')
        self.assertEqual(no.returncode, 1)
        self.assertFalse(self.launched())

    def test_blocked_state_never_launches_even_with_record(self):
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        self.put('.mcp.json', {'mcpServers': {'r': {'url': 'https://x', 'headersHelper': 'x'}}})
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.launched())

    def test_gate_runs_before_secrets_are_exported(self):
        (self.fixture_mount_dir / 'export' / 'MCP_TOKEN').write_text('tok\n')
        self.put('.claude/settings.json', HOOKS)
        self.approve_from_preflight()
        result = self.run_entrypoint('claude', claude_mode='run')
        self.assertEqual(result.returncode, 0, result.stderr)
        # 起動まで進むケースで、helper の時点では秘密が未設定、claude の時点では設定済み。
        self.assertEqual(self.audit_records(), ['audit MCP_TOKEN=unset'])
        self.assertTrue(any('MCP_TOKEN=tok' in r for r in self.records if r.startswith('claude-env')))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 3: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_*entrypoint.py"`
Expected: `test_codex_entrypoint.py` の setUp が「entrypoint.sh に固定パス ... がない」で失敗し、新しいテストも失敗する

- [ ] **Step 4: entrypoint.sh を実装する**

(a) 冒頭の `readonly CC_AGENT` の直後（Codex の enum 検証の前）に:

```bash
# Claude 経路の起動モード（#163）。preflight は project 設定ゲートの検査用コンテナで、stdout を protocol の
# JSON 1 文書専用にする（Codex の preflight と同じく、元の stdout を fd3 へ確保して以後のログを stderr へ）。
CLAUDE_START_MODE=""
if [ "$CC_AGENT" = claude ]; then
  case "${CC_CLAUDE_START_MODE-run}" in
    run | preflight) CLAUDE_START_MODE="${CC_CLAUDE_START_MODE-run}" ;;
    *)
      echo "ERROR: CC_CLAUDE_START_MODE が不正です（run または preflight）: '${CC_CLAUDE_START_MODE-}'。起動を中止します" >&2
      exit 1
      ;;
  esac
  if [ "$CLAUDE_START_MODE" = preflight ]; then
    exec 3>&1
    exec 1>&2
  fi
fi
readonly CLAUDE_START_MODE
```

(b) `# MCP監査ゲート（stdio型サーバーの検知＋TTY確認、内部運用issue参照）。` のコメントブロックの直前に:

```bash
# Claude 経路の project 設定ゲート（#163、設計 docs/superpowers/specs/2026-09-26-claude-project-settings-gate-design.md）。
# /workspace の trust は全プロジェクトで共有されるため、リポジトリ同梱の .claude/settings*.json の hook・env・
# helper 等は確認なしで効く。検査用コンテナ（preflight）で helper の snapshot を fd3 へ出して終了し、
# 本起動（run）では .mcp.json ゲートの後・秘密の export より前に、host が :ro で渡した承認記録と照合する。
# opt-out は設けない（.mcp.json ゲートと同じ理由、claude-container#29）。
CLAUDE_PROJECT_AUDIT=/usr/local/bin/claude-project-audit.py
CLAUDE_PROJECT_APPROVED=/etc/claude-container/claude-project-approved.json
CLAUDE_PROJECT_ROOT=/workspace
if [ "$CC_AGENT" = claude ] && [ "$CLAUDE_START_MODE" = preflight ]; then
  if ! python3 -I "$CLAUDE_PROJECT_AUDIT" --root "$CLAUDE_PROJECT_ROOT" snapshot >&3; then
    echo "ERROR: Claude project 設定ゲートの検査に失敗しました。起動を中止します" >&2
    exit 1
  fi
  exec 3>&-
  exit 0
fi
```

(c) `.mcp.json` ゲートの `if [ "$CC_AGENT" = claude ] && [ -f "$MCP_CONFIG" ]; then ... fi` の直後（`# GitHub トークン配線` のコメントの前）に:

```bash
if [ "$CC_AGENT" = claude ]; then
  project_rc=0
  python3 -I "$CLAUDE_PROJECT_AUDIT" --root "$CLAUDE_PROJECT_ROOT" verify "$CLAUDE_PROJECT_APPROVED" || project_rc=$?
  case "$project_rc" in
    0) ;;
    3)
      echo "WARNING: 上の project 設定（.claude/settings*.json）がホストで承認されていないか、承認後に変わっています。hook・env・helper はセッション開始と同時に実行され、export された全ての秘密を読めます（承認は定義の承認で、スクリプトの中身は保証しません）" >&2
      printf 'この project 設定で Claude Code を起動しますか? [y/N] ' >&2
      if ! read -r project_confirm </dev/tty; then
        echo "ERROR: project 設定を確認する対話可能な TTY がありません。起動を中止します" >&2
        exit 1
      fi
      case "$project_confirm" in
        y | Y | yes | YES | Yes) ;;
        *)
          echo "ERROR: project 設定の確認が拒否されました。起動を中止します" >&2
          exit 1
          ;;
      esac
      ;;
    *)
      exit 1
      ;;
  esac
fi
```

- [ ] **Step 4b: `.mcp.json` ゲートのコメントを直す**

`entrypoint.sh` の `.mcp.json` ゲートのコメント「（http/sse 型は接続先をファイアウォールが審査するため対象外）」の直後に「ただし headersHelper を持つサーバーは、下の project 設定ゲートの helper が止める（#163）」を足す（下は上の (b) のブロックを指す。位置関係に合わせて「上の」「下の」を直す）。

- [ ] **Step 4c: ComposeContractTests に拒否の 2 行を足す**

Task 2 Step 7 で保留した `'empty claude mode'`・`'unknown claude mode'` の 2 行を、`tests/test_codex_entrypoint.py` の `test_explicit_empty_or_unknown_values_are_not_defaulted_and_are_rejected` の表へ足し、`run_entrypoint` の呼び出しに `claude_mode=values.get('CC_CLAUDE_START_MODE')` を渡す。

- [ ] **Step 5: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_*entrypoint.py" -v`
Expected: PASS（既存の Codex・IPv6 の entrypoint テストも含む）

- [ ] **Step 6: `run_launcher_tests()` に登録する**

`test_codex_entrypoint.py` の行の直後に:

```bash
  check "entrypoint の Claude project 設定ゲート（preflight の fd3 分離・enum・再照合・TTY 確認・秘密より前）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_claude_project_entrypoint.py"
```

- [ ] **Step 7: README を同じコミットで直す**

README のファイル構成の一覧で、`entrypoint.sh` の項に「Claude 経路では、`.mcp.json` ゲートの後・秘密の export より前に project 設定ゲート（`claude-project-audit.py` の verify）を通す。`CC_CLAUDE_START_MODE=preflight` の検査用コンテナでは snapshot だけを出して終了する」を足す。`codex-mcp-audit.py` の項の直後に `claude-project-audit.py` の項（Claude 経路の project 設定ゲート helper。`snapshot` と `verify`、終了コード 0/1/3、#163）を足す。「変更後の確認」節に「`claude-project-audit.py` と project 設定ゲート（`entrypoint.sh` のゲート、`c3c` の `run_claude_project_preflight()`・`check_claude_project_approval()`）の変更も `--launcher-only` に含む。単独では `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_claude_project_*.py'`。実イメージの helper と label は `test-build.sh` の通常モードで確認する」を足す。

- [ ] **Step 8: lint を通して Commit**

Run: `./lint.sh`
Expected: `lint OK`

```bash
git add entrypoint.sh tests/test_codex_entrypoint.py tests/test_claude_project_entrypoint.py test-build.sh README.md
git commit -m "feat: entrypoint に Claude project 設定ゲートの検査と再照合を足す（#163）"
```

---

### Task 4: launcher の label 照合・検査用コンテナ・承認・clean

**Files:**
- Modify: `c3c`
- Modify: `tests/test_codex_launch.py`（fake podman を Claude の label と preflight に対応させ、記録する env を足す）
- Create: `tests/test_claude_project_launch.py`
- Modify: `test-build.sh`（`run_launcher_tests()` に 1 行登録）
- Modify: `README.md`（「セキュリティモデル」節、「MCP サーバーの追加」節の近くの小節、移行手順）

**Interfaces:**
- Consumes: protocol（Task 1）、label と compose（Task 2）、entrypoint の preflight（Task 3）
- Produces: bash 関数 `claude_project_gate_needed`（rc 0 = 対象の候補あり）、`guard_claude_project_image_support`、`run_claude_project_preflight`（`CLAUDE_PROJECT_HASH`・`CLAUDE_PROJECT_COUNT`・`CLAUDE_PROJECT_DISPLAY[]` を設定）、`claude_project_record_content <hash>`、`write_claude_project_record <hash>`、`check_claude_project_approval`。変数 `CLAUDE_PROJECT_APPROVAL_DIR`・`CLAUDE_PROJECT_APPROVAL_RECORD`（`readonly`）。

- [ ] **Step 1: fake podman を拡張する**

`tests/test_codex_launch.py` の `PODMAN` で:
- `record` の env のキーに `'CC_CLAUDE_START_MODE', 'CLAUDE_PROJECT_APPROVAL_FILE'` を足す。
- `image inspect` の分岐で、`'io.c3c.claude-project-audit-protocol' in fmt` なら `print(state.get('claude_label', ''))` を `codex` の判定より前に置く。
- `build` の分岐で `state['claude_label'] = state.get('build_claude_label', '1')` も設定する。
- preflight の run の分岐で `spec = state.get('claude_preflight' if os.environ.get('CC_AGENT') == 'claude' else 'preflight', {})` にする。

既存の Codex のテストが変わらず通ることを確かめる:

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_codex_launch.py`
Expected: PASS

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_claude_project_launch.py`:

```python
#!/usr/bin/env python3
"""launcher の Claude project 設定ゲート（#163）の回帰試験。

tests/test_codex_launch.py の LaunchCase（隔離 HOME・fixture project・fake podman/compose・専用 PTY）を使う。
検査用コンテナの protocol は fake compose が state['claude_preflight'] から返す。
"""

import json
import os
from pathlib import Path
import shutil
import sys
import unittest

from test_codex_launch import LaunchCase

HASH_A = 'a' * 64
HASH_B = 'b' * 64


def claude_protocol(hash_value=HASH_A, count=1, lines=None, extra=None):
    if lines is None:
        lines = ['--- .claude/settings.json ---', '  {"hooks": {}}'] if count else []
    doc = {'protocol_version': 1, 'hash': hash_value, 'count': count, 'lines': lines}
    doc.update(extra or {})
    return json.dumps(doc, ensure_ascii=False) + '\n'


class ClaudeProjectLaunchCase(LaunchCase):
    def setUp(self):
        super().setUp()
        (self.conf / 'env').write_text('')
        self.state.update({'claude_label': '1', 'claude_preflight': {'stdout': claude_protocol()}})
        (self.proj / '.claude').mkdir()
        (self.proj / '.claude' / 'settings.json').write_text('{"hooks": {}}')

    def claude_record(self):
        return self.store / 'claude-project' / (self.project_name() + '.json')

    def approve_claude(self, hash_value=HASH_A):
        record = self.claude_record()
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'protocol_version': 1, 'hash': hash_value}, separators=(',', ':')) + '\n')
        return record

    def launch(self, **kwargs):
        return self.run_launcher('--agent', 'claude', str(self.proj), **kwargs)


class GateSelectionTests(ClaudeProjectLaunchCase):
    def test_no_targets_skips_gate_even_on_old_image(self):
        shutil.rmtree(self.proj / '.claude')
        self.state['claude_label'] = ''
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.preflight_calls(), [])
        self.assertEqual(len(self.main_runs()), 1)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], '')
        self.assertEqual(self.main_runs()[0]['env']['CC_CLAUDE_START_MODE'], 'run')

    def test_mcp_json_alone_or_symlinked_claude_dir_triggers_gate(self):
        shutil.rmtree(self.proj / '.claude')
        (self.proj / '.mcp.json').write_text('{}')
        self.state['claude_preflight'] = {'stdout': claude_protocol(count=0)}
        self.launch()
        self.assertEqual(len(self.preflight_calls()), 1)
        (self.proj / '.mcp.json').unlink()
        (self.proj / '.claude').symlink_to('/nonexistent-outside')
        self.launch()
        self.assertEqual(len(self.preflight_calls()), 1)

    def test_missing_or_unknown_label_blocks_before_any_container_run(self):
        for label in ('', '2', '0'):
            with self.subTest(label=label):
                self.state['claude_label'] = label
                result = self.launch()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('-b', result.stderr)
                self.assertEqual(self.compose_calls('run'), [])

    def test_missing_host_python_blocks(self):
        # PATH から python3 だけを外す。fake podman は python3 で書かれているので、shebang を絶対パスに替える。
        podman = self.bin / 'podman'
        text = podman.read_text().split('\n', 1)[1]
        podman.write_text('#!' + sys.executable + '\n' + text)
        bare = self.root / 'bare-bin'
        bare.mkdir()
        for directory in os.environ['PATH'].split(':'):
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                target = Path(directory) / name
                if name.startswith('python') or (bare / name).exists() or not os.access(target, os.X_OK):
                    continue
                (bare / name).symlink_to(target)
        result = self.run_launcher('--agent', 'claude', str(self.proj),
                                   env_extra={'PATH': str(self.bin) + ':' + str(bare)})
        self.assertNotEqual(result.returncode, 0)
        # CLI 選択記憶も python3 不在の WARNING を出すので、ゲート固有の文言で確かめる。
        self.assertIn('Claude project 設定ゲート', result.stderr)
        self.assertIn('python3', result.stderr)
        self.assertEqual(self.main_runs(), [])


class PreflightTests(ClaudeProjectLaunchCase):
    def test_preflight_is_non_tty_claude_preflight_with_devnull_stdin(self):
        self.approve_claude()
        self.launch()
        call = self.preflight_calls()[0]
        self.assertEqual(call['env']['CC_AGENT'], 'claude')
        self.assertEqual(call['env']['CC_CLAUDE_START_MODE'], 'preflight')
        self.assertEqual(call['stdin'], '/dev/null')
        self.assertIn('-T', call['args'])

    def test_preflight_failure_or_malformed_protocol_blocks_run_and_writes_nothing(self):
        bad = ({'stdout': '', 'rc': 1}, {'stdout': 'noise\n' + claude_protocol()},
               {'stdout': claude_protocol(extra={'x': 1})}, {'stdout': claude_protocol(hash_value='A' * 64)},
               {'stdout': claude_protocol(count=0, lines=['x'])}, {'stdout': claude_protocol().replace('"protocol_version": 1', '"protocol_version": 2')})
        for spec in bad:
            with self.subTest(spec=spec):
                self.state['claude_preflight'] = spec
                result = self.launch(tty=True, answer='y')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.main_runs(), [])
                self.assertFalse(self.claude_record().exists())


class ApprovalTests(ClaudeProjectLaunchCase):
    def test_first_run_prompts_on_tty_and_records_atomically(self):
        result = self.launch(tty=True, answer='y')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--- .claude/settings.json ---', result.stderr)
        record = self.claude_record()
        self.assertEqual(record.read_text(), '{"protocol_version":1,"hash":"%s"}\n' % HASH_A)
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(record.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], str(record))
        self.assertEqual(list(record.parent.glob('.tmp.*')), [])

    def test_same_hash_skips_prompt_without_tty(self):
        record = self.approve_claude()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], str(record))

    def test_changed_hash_prompts_and_rejection_keeps_old_record(self):
        record = self.approve_claude(HASH_B)
        result = self.launch(tty=True, answer='n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_runs(), [])
        self.assertIn(HASH_B, record.read_text())

    def test_no_tty_blocks_unapproved(self):
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TTY', result.stderr)
        self.assertEqual(self.main_runs(), [])

    def test_zero_count_passes_without_record(self):
        self.state['claude_preflight'] = {'stdout': claude_protocol(count=0)}
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.main_runs()[0]['env']['CLAUDE_PROJECT_APPROVAL_FILE'], '')
        self.assertFalse(self.claude_record().exists())

    def test_corrupt_record_requires_reconfirmation(self):
        record = self.approve_claude()
        record.write_text('{"protocol_version":1,"hash":"%s","x":1}\n' % HASH_A)
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.main_runs(), [])

    def test_env_file_cannot_set_claude_gate_variables(self):
        # 承認済みで本起動まで進め、本起動へ渡る値が env ファイル・シェル環境ではなく launcher の値であることを見る。
        record = self.approve_claude()
        evil = self.root / 'evil.json'
        evil.write_text(record.read_text())
        (self.conf / 'env').write_text(f'CLAUDE_PROJECT_APPROVAL_FILE={evil}\nCC_CLAUDE_START_MODE=preflight\n')
        shell = {'CLAUDE_PROJECT_APPROVAL_FILE': str(evil), 'CC_CLAUDE_START_MODE': 'preflight'}
        result = self.launch(env_extra=shell)
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.main_runs()[0]['env']
        self.assertEqual(run['CLAUDE_PROJECT_APPROVAL_FILE'], str(record))
        self.assertEqual(run['CC_CLAUDE_START_MODE'], 'run')
        self.assertIn('CLAUDE_PROJECT_APPROVAL_FILE', result.stderr)  # 許可リスト外の key の警告
        # 対象なしの経路でも launcher の値（空と run）になる。
        shutil.rmtree(self.proj / '.claude')
        result = self.launch(env_extra=shell)
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.main_runs()[0]['env']
        self.assertEqual(run['CLAUDE_PROJECT_APPROVAL_FILE'], '')
        self.assertEqual(run['CC_CLAUDE_START_MODE'], 'run')

    def test_record_write_failure_keeps_old_record_and_cleans_temp(self):
        record = self.approve_claude(HASH_B)
        real_mv = shutil.which('mv')
        fake = self.bin / 'mv'
        fake.write_text(f'#!/bin/sh\ncase "$*" in *claude-project*) exit 1 ;; esac\nexec {real_mv} "$@"\n')
        fake.chmod(0o755)
        result = self.launch(tty=True, answer='y')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(HASH_B, record.read_text())
        self.assertEqual(list(record.parent.glob('.tmp.*')), [])
        self.assertEqual(self.main_runs(), [])

    def test_codex_path_exports_empty_claude_gate_variables(self):
        (self.conf / 'env').write_text(f'CODEX_DIR={self.codex_dir}\n')
        self.approve()
        result = self.run_launcher('--agent', 'codex', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.preflight_calls() + self.main_runs():
            self.assertEqual(call['env']['CLAUDE_PROJECT_APPROVAL_FILE'], '')


class CleanTests(ClaudeProjectLaunchCase):
    def test_clean_project_removes_record_and_keeps_others(self):
        record = self.approve_claude()
        other = record.parent / 'other-0123456789ab.json'
        other.write_text('{}')
        result = self.run_launcher('--clean', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(record.exists())
        self.assertTrue(other.exists())

    def test_clean_all_removes_store(self):
        self.approve_claude()
        result = self.run_launcher('--clean')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.claude_record().exists())


if __name__ == '__main__':
    unittest.main()
```

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_launch.py`
Expected: FAIL（ゲートが無いので preflight が呼ばれない、記録が作られない等）

- [ ] **Step 3: 定数とパスを足す**

`c3c` の `readonly CODEX_AUDIT_PROTOCOL_VERSION CODEX_AUDIT_PROTOCOL_LABEL` の直後に:

```bash
# Claude 経路の project 設定ゲートの protocol（#163。claude-project-audit.py・Dockerfile.claude の label と同期）。
CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION=1
CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL=io.c3c.claude-project-audit-protocol
readonly CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL
```

`freeze_project_paths()` で `CODEX_APPROVAL_DIR=...` の直後に次を足し、同じ関数の `readonly` の行に `CLAUDE_PROJECT_APPROVAL_DIR CLAUDE_PROJECT_APPROVAL_RECORD` を加える:

```bash
  CLAUDE_PROJECT_APPROVAL_DIR="$MCP_APPROVAL_STORE/claude-project"
  CLAUDE_PROJECT_APPROVAL_RECORD="$CLAUDE_PROJECT_APPROVAL_DIR/$PROJECT_NAME.json"
```

- [ ] **Step 4: ゲートの関数を足す**

`check_codex_approval()` の定義の直後に:

```bash
# Claude 経路の project 設定ゲート（#163）。.claude か .mcp.json が存在する（symlink を含む）repo でだけ
# label 照合・検査用コンテナ・承認を行う。存在しない repo は旧イメージのまま起動できる。
claude_project_gate_needed() {
  [[ -e "$WORKING_DIR/.claude" || -L "$WORKING_DIR/.claude" || -e "$WORKING_DIR/.mcp.json" || -L "$WORKING_DIR/.mcp.json" ]]
}

guard_claude_project_image_support() {
  local label
  if ! label=$(podman image inspect --format "{{index .Labels \"$CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL\"}}" "$IMAGE_NAME" 2>/dev/null); then
    guard_fail "ERROR: イメージ $IMAGE_NAME を inspect できないため、Claude の project 設定ゲートへの対応を確認できません。起動を中止します。" || return 1
  fi
  if [[ "$label" != "$CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION" ]]; then
    guard_fail "ERROR: イメージ $IMAGE_NAME は Claude の project 設定ゲート（protocol $CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION）に対応していません（label $CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL=${label:-なし}）。このプロジェクトには .claude か .mcp.json があるため、-b で再ビルドしてください。起動を中止します。" || return 1
  fi
  [[ ${CHECK_MODE:-0} -eq 1 ]] && echo "[OK]   Claude project 設定ゲート protocol: $CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL=$label"
  return 0
}

claude_project_record_content() {
  printf '{"protocol_version":%s,"hash":"%s"}\n' "$CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION" "$1"
}

write_claude_project_record() {
  local hash="$1" tmp
  (
    umask 077
    mkdir -p "$CLAUDE_PROJECT_APPROVAL_DIR" || exit 1
    chmod 700 "$MCP_APPROVAL_STORE" "$CLAUDE_PROJECT_APPROVAL_DIR" || exit 1
    tmp=$(mktemp "$CLAUDE_PROJECT_APPROVAL_DIR/.tmp.XXXXXX") || exit 1
    trap 'rm -f -- "$tmp"' EXIT
    chmod 600 "$tmp" || exit 1
    claude_project_record_content "$hash" > "$tmp" || exit 1
    mv -f -- "$tmp" "$CLAUDE_PROJECT_APPROVAL_RECORD" || exit 1
    trap - EXIT
  ) || {
    echo "ERROR: Claude project 設定の承認記録を書けません: $CLAUDE_PROJECT_APPROVAL_RECORD。起動を中止します" >&2
    exit 1
  }
}

CLAUDE_PROJECT_PREFLIGHT_TMP=""
cleanup_claude_project_preflight() {
  [[ -n "$CLAUDE_PROJECT_PREFLIGHT_TMP" ]] && rm -rf -- "$CLAUDE_PROJECT_PREFLIGHT_TMP"
  CLAUDE_PROJECT_PREFLIGHT_TMP=""
  return 0
}

# 検査用コンテナ（非 TTY、stdin は /dev/null）で /workspace を審査し、stdout の protocol 1 文書だけを
# python3 -I で厳密に検証する。結果は CLAUDE_PROJECT_HASH / CLAUDE_PROJECT_COUNT / CLAUDE_PROJECT_DISPLAY[]。
# 表示行には env の値が含まれうるので、0700 の一時 dir に置いて終了時に削除する。
run_claude_project_preflight() {
  CLAUDE_PROJECT_HASH=""
  CLAUDE_PROJECT_COUNT=""
  CLAUDE_PROJECT_DISPLAY=()
  local override="$RUN_DIR/compose.codex-preflight.yml" rc=0
  if [[ ! -f "$override" ]]; then
    echo "ERROR: 検査用の固定 Compose override がありません: $override。起動を中止します" >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Claude project 設定ゲート: 検査結果の検証に python3 が必要ですが、ホストに見つかりません。起動を中止します" >&2
    exit 1
  fi
  CLAUDE_PROJECT_PREFLIGHT_TMP=$(umask 077; mktemp -d "${TMPDIR:-/tmp}/cc-claude-preflight.XXXXXX") || {
    echo "ERROR: 検査用の一時ディレクトリを作成できません。起動を中止します" >&2
    exit 1
  }
  trap 'cleanup_claude_project_preflight' EXIT
  chmod 700 "$CLAUDE_PROJECT_PREFLIGHT_TMP"
  ( umask 077; : > "$CLAUDE_PROJECT_PREFLIGHT_TMP/protocol" ) || exit 1
  echo "INFO: Claude project 設定ゲート: リポジトリの .claude/settings*.json を検査用コンテナで読みます（Claude Code は起動しません）" >&2
  CC_CLAUDE_START_MODE=preflight
  export CC_CLAUDE_START_MODE
  CONTEXT="$WORKING_DIR" CLAUDE_CONTAINER_DIR="$RUN_DIR" ASSET_HASH="$ASSET_HASH" BASE_IMAGE="$BASE_IMAGE" \
    podman compose -f "$RUN_DIR/compose.yml" "${COMPOSE_OVERRIDE_ARGS[@]}" -f "$override" -p "$PROJECT_NAME" --in-pod false --env-file /dev/null \
    run --rm -T claude-auth-workspace </dev/null >"$CLAUDE_PROJECT_PREFLIGHT_TMP/protocol" || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "ERROR: Claude project 設定ゲート: 検査用コンテナが終了コード $rc で止まりました（上の理由を確認してください）。本起動は行いません" >&2
    exit 1
  fi
  if ! python3 -I - "$CLAUDE_PROJECT_PREFLIGHT_TMP/protocol" "$CLAUDE_PROJECT_PREFLIGHT_TMP/summary" \
      "$CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION" <<'PYTHON'
import json
import os
import re
import sys

source, summary, protocol_version = sys.argv[1:4]
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def fail(message):
    print('ERROR: Claude project 設定ゲート: ' + message + '。本起動は行いません', file=sys.stderr)
    sys.exit(1)


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail('protocol に重複 key があります')
        result[key] = value
    return result


try:
    with open(source, 'rb') as handle:
        text = handle.read().decode('utf-8')
except (OSError, UnicodeDecodeError):
    fail('検査用コンテナの stdout を UTF-8 として読めません')
try:
    doc = json.loads(text, object_pairs_hook=pairs, parse_constant=lambda name: fail('protocol に非標準の定数があります'))
except ValueError:
    fail('検査用コンテナの stdout が protocol の JSON 1 文書ではありません（余分な出力・破損・欠落）')
if not isinstance(doc, dict) or set(doc) != {'protocol_version', 'hash', 'count', 'lines'}:
    fail('protocol の形式が対応 protocol と異なります')
if type(doc['protocol_version']) is not int or doc['protocol_version'] != int(protocol_version):
    fail('protocol version が対応 protocol と異なります')
if not isinstance(doc['hash'], str) or not re.fullmatch(r'[0-9a-f]{64}', doc['hash']):
    fail('hash の形式が不正です')
if type(doc['count']) is not int or not 0 <= doc['count'] <= 2:
    fail('count の形式が不正です')
lines = doc['lines']
if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
    fail('lines の形式が不正です')
if (doc['count'] == 0) != (lines == []):
    fail('count と lines が一致しません')
fd = os.open(summary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as handle:
    handle.write(doc['hash'] + '\n' + str(doc['count']) + '\n')
    for line in lines:
        handle.write(CONTROL.sub('', line) + '\n')
PYTHON
  then
    exit 1
  fi
  local -a summary_lines=()
  mapfile -t summary_lines < "$CLAUDE_PROJECT_PREFLIGHT_TMP/summary"
  CLAUDE_PROJECT_HASH="${summary_lines[0]:-}"
  CLAUDE_PROJECT_COUNT="${summary_lines[1]:-}"
  if [[ ! "$CLAUDE_PROJECT_HASH" =~ ^[0-9a-f]{64}$ || ! "$CLAUDE_PROJECT_COUNT" =~ ^[0-2]$ ]]; then
    echo "ERROR: Claude project 設定ゲート: 検証結果を読み取れません。本起動は行いません" >&2
    exit 1
  fi
  CLAUDE_PROJECT_DISPLAY=("${summary_lines[@]:2}")
  cleanup_claude_project_preflight
  trap - EXIT
  CC_CLAUDE_START_MODE=run
  export CC_CLAUDE_START_MODE
  return 0
}

# TOFU＋変更検知。拒否・TTY 無し・EOF ではコンテナへ委ねず起動しない。count=0 は記録を渡さない
# （本起動の entrypoint も対象なしとして通し、検査後に対象が現れたら確認か停止になる）。
check_claude_project_approval() {
  CLAUDE_PROJECT_APPROVAL_FILE=""
  local expected recorded=""
  if [[ "$CLAUDE_PROJECT_COUNT" -eq 0 ]]; then
    echo "INFO: Claude project 設定ゲート: 対象の設定はありません" >&2
    export CLAUDE_PROJECT_APPROVAL_FILE
    return 0
  fi
  expected=$(claude_project_record_content "$CLAUDE_PROJECT_HASH")
  if [[ -f "$CLAUDE_PROJECT_APPROVAL_RECORD" ]]; then
    recorded=$(cat "$CLAUDE_PROJECT_APPROVAL_RECORD" 2>/dev/null || echo "")
  fi
  if [[ -n "$recorded" && "$recorded" == "$expected" ]]; then
    echo "INFO: Claude project 設定ゲート: 承認済み（ハッシュ一致）。確認を省略します" >&2
  else
    echo "WARNING: リポジトリの project 設定（.claude/settings*.json）が、前回の承認から変わっているか未承認です。hook・env・helper 等はセッション開始と同時に実行され、export された全ての秘密を読めます（承認は定義の承認で、スクリプトの中身は保証しません）:" >&2
    [[ -n "$recorded" ]] && echo "  （注: 前回のホスト側承認から内容が変わっています）" >&2
    printf '%s\n' "${CLAUDE_PROJECT_DISPLAY[@]}" >&2
    printf 'この project 設定で Claude Code を起動し、この承認を記憶しますか? [y/N] ' >&2
    local project_confirm=""
    if ! read -r project_confirm </dev/tty 2>/dev/null; then
      echo "ERROR: 対話可能な TTY がないため project 設定を確認できません。起動を中止します" >&2
      exit 1
    fi
    case "$project_confirm" in
      y | Y | yes | YES | Yes) write_claude_project_record "$CLAUDE_PROJECT_HASH" ;;
      *)
        echo "ERROR: project 設定の確認が拒否されました。起動を中止します" >&2
        exit 1
        ;;
    esac
  fi
  CLAUDE_PROJECT_APPROVAL_FILE="$CLAUDE_PROJECT_APPROVAL_RECORD"
  export CLAUDE_PROJECT_APPROVAL_FILE
}
```

- [ ] **Step 5: 本起動の流れに組み込む**

通常起動の `CODEX_MCP_APPROVAL_FILE=""` / `export CODEX_MCP_APPROVAL_FILE` の直後に:

```bash
# Claude の project 設定ゲートの変数も、全経路で launcher の値だけを export する（env 由来の値を使わない）。
CLAUDE_PROJECT_APPROVAL_FILE=""
CC_CLAUDE_START_MODE=run
export CLAUDE_PROJECT_APPROVAL_FILE CC_CLAUDE_START_MODE
CLAUDE_PROJECT_GATE=0
if [[ "$AGENT" == claude ]] && claude_project_gate_needed; then
  CLAUDE_PROJECT_GATE=1
fi
```

`if [[ $BUILD -eq 1 || ( "$AGENT" == codex && $IMAGE_PRESENT -eq 0 ) ]]; then` を次に変える（ゲート対象の repo も、label 照合の前に暗黙ビルドで本起動へ進まないよう明示ビルドする）:

```bash
if [[ $BUILD -eq 1 || ( "$AGENT" == codex && $IMAGE_PRESENT -eq 0 ) || ( $CLAUDE_PROJECT_GATE -eq 1 && $IMAGE_PRESENT -eq 0 ) ]]; then
```

`if [[ "$AGENT" == codex ]]; then ... fi`（Codex の preflight）の直後に:

```bash
if [[ $CLAUDE_PROJECT_GATE -eq 1 ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Claude project 設定ゲート: このプロジェクトには .claude か .mcp.json があり、検査結果の検証に python3 が必要ですが、ホストに見つかりません。起動を中止します" >&2
    exit 1
  fi
  guard_claude_project_image_support
  run_claude_project_preflight
  check_claude_project_approval
fi
```

`.c3c/env` からの上書きを防ぐ: `load_env_file()` の許可リストに `CLAUDE_PROJECT_APPROVAL_FILE`・`CC_CLAUDE_START_MODE` が無いことを確かめる（無ければ変更不要。上の export が env より後に実行されるので、仮に env に書かれても上書きされる）。`guard_env_*` が未知 key を警告する仕組みがあるなら、その出力をテスト `test_env_file_cannot_set_claude_gate_variables` の期待に合わせる（テストは「本起動しない」ことだけを見る。未承認の TTY なしで止まるため）。

- [ ] **Step 6: clean に加える**

`clean_project()` の Codex の承認記録の削除の直後に:

```bash
  echo "Claude project 設定の承認記録を削除します: $CLAUDE_PROJECT_APPROVAL_RECORD"
  rm -f "$CLAUDE_PROJECT_APPROVAL_RECORD" && echo "削除しました。" || echo "見つからないのでスキップします。"
```

`clean_all()` は `mcp-approvals` ごと削除するので変更不要（テストで確かめる）。

- [ ] **Step 7: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_*launch.py" -v`
Expected: PASS（`test_codex_launch.py`・`test_c3c_launch.py` を含む）。python3 の確認は、ゲートの処理の先頭（label 照合の前）で行う。検査用コンテナの起動前にも同じ確認が `run_claude_project_preflight()` にあるが、先頭の確認で先に止まる。

- [ ] **Step 8: `run_launcher_tests()` に登録し、全体を回す**

`test_codex_launch.py` の行の直後に:

```bash
  check "--agent claude の project 設定ゲート（対象判定・label・preflight・TOFU 承認・atomic 記録・env 非参照・clean）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_claude_project_launch.py"
```

Run: `./lint.sh && ./test-build.sh --launcher-only`
Expected: `lint OK`、`FAIL=0`

- [ ] **Step 9: README を同じコミットで直す**

(a) 「セキュリティモデル」節の「Claude 経路で `.mcp.json` に追加ゲートを設ける理由は…」の段落の後に、次の段落を足す:

```markdown
**`/workspace` の trust は全プロジェクトで共有される**（#163）: Claude Code は workspace trust を `~/.claude.json` の `projects["<repo root>"]` に保存する。claude-container はどのプロジェクトも `/workspace` にマウントし `~/.claude.json` を共有するため、一度 trust を受け入れると以降どのリポジトリも trust 済みで開き、リポジトリ同梱の `.claude/settings.json`・`.claude/settings.local.json` の hook・`env`・`apiKeyHelper` 等の helper・`statusLine`・allow 規則が確認なしで効く。これは #29 の基準（セッション開始と同時の任意コード実行）に当たるため、Claude 経路では project 設定ゲートを設けている: この 2 ファイルを検査用コンテナで読み、ファイル全体の hash が初回または前回承認から変わっていればホストで内容を表示して確認する。project 設定での plugin の有効化（`enabledPlugins`）・plugin の読み込み先を変える `env`（`CLAUDE_CODE_PLUGIN_*`）・`extraKnownMarketplaces`・skills-directory plugin（`.claude/skills/*/.claude-plugin/plugin.json`）・`.mcp.json` の `headersHelper` は、確認の前に起動を止める。対象外（残る経路）は [SECURITY-CLAIMS の C-5](SECURITY-CLAIMS.md#c-5) を参照（skills・agents・commands の frontmatter と本文、承認後のセッション中の変更、ホスト側の trust など）。
```

同じ節の「http／sse タイプはこのゲートの対象外だが、接続先はファイアウォールの許可リストが審査する。」の直後に「ただし `headersHelper` を持つサーバーは、project 設定ゲートが起動前に止める。」を足す。

(b) 「MCP サーバーの追加」節の末尾に小節「リポジトリの Claude 設定の確認（project 設定ゲート）」を足し、次を書く: 対象ファイル（`.claude/settings.json`・`.claude/settings.local.json`。未追跡の local も対象）、初回と変更時に内容が表示され確認が出ること、承認記録の場所（`~/.local/state/claude-container/mcp-approvals/claude-project/`）、TTY が無いと未承認のまま起動しないこと、ホストで承認した後・本起動の前に変わった場合はコンテナ内で確認が出ること、止まる条件（(a) の列挙と、判定できないとき: 壊れた JSON・`/workspace` の外を指す symlink・読めないファイル等）、`.claude` か `.mcp.json` を持つ repo は対応 label の無い旧イメージでは起動せず `-b` を案内すること、`--clean <ディレクトリ>` と引数なしの `--clean` で記録が消えること。

(c) 同じ小節に「既存の利用者への影響と移行」を書く: ① `.claude` か `.mcp.json` を持つ repo は `-b` で作り直す（`--check` が `[FAIL]` と `-b` の案内を出す）。② project の `.claude/settings*.json` で plugin を有効にしている repo は起動しなくなる。plugin は user 設定（`~/.claude/settings.json`）で有効にする（`--check` が `[FAIL]` で知らせる）。③ 未承認の repo を TTY なし（スクリプト等）で起動していた場合は、一度対話で起動して承認する。

- [ ] **Step 10: Commit**

```bash
git add c3c tests/test_codex_launch.py tests/test_claude_project_launch.py test-build.sh README.md
git commit -m "feat: launcher に Claude project 設定ゲートを組み込む（#163）"
```

---

### Task 5: `--check` の診断

**Files:**
- Modify: `c3c`（`check_one_project()` の `.mcp.json` ゲートの診断の直前）
- Modify: `tests/test_claude_project_launch.py`（`CheckTests` を追加）
- Modify: `README.md`（`--check` の出力の説明）

**Interfaces:**
- Consumes: `claude_project_gate_needed`、`guard_claude_project_image_support`、`claude_project_record_content`（Task 4）、helper の `snapshot`（Task 1）
- Produces: `--check` の出力行（下の文言）。確認を出さず、記録を書かず、コンテナを起動しない。

方針: `--check` は Codex と同じく検査用コンテナを起動しない。ホストの python3 があれば、ホスト上で `$RUN_DIR/claude-project-audit.py --root "$WORKING_DIR" snapshot` を実行して、停止条件と承認状態を参考として出す（移行が要る repo を `--check` で検出するため。ホストとコンテナで symlink の見え方が違う場合があることを文言に含める）。helper は repo のファイルを読むだけで、git も repo のコードも実行しない。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_claude_project_launch.py` に追加:

```python
class CheckTests(ClaudeProjectLaunchCase):
    def check(self):
        return self.run_launcher('--check', '--agent', 'claude', str(self.proj))

    def test_no_targets_is_ok(self):
        shutil.rmtree(self.proj / '.claude')
        result = self.check()
        self.assertIn('[OK]   Claude project 設定ゲート: 対象なし', result.stdout)
        self.assertEqual(self.compose_calls(), [])

    def test_unapproved_is_info_and_writes_nothing(self):
        before = self.snapshot(self.home)
        result = self.check()
        self.assertIn('[INFO] Claude project 設定ゲート: 未承認または変更あり', result.stdout)
        self.assertEqual(self.compose_calls(), [])
        self.assertEqual(self.snapshot(self.home), before)

    def test_approved_matching_host_view_is_ok(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('audit', str(self.runner / 'claude-project-audit.py'))
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        self.approve_claude(audit.snapshot(str(self.proj))['hash'])
        result = self.check()
        self.assertIn('[OK]   Claude project 設定ゲート: 承認済み', result.stdout)

    def test_plugin_setting_is_fail_for_migration(self):
        (self.proj / '.claude' / 'settings.json').write_text('{"enabledPlugins": {"x@y": true}}')
        result = self.check()
        self.assertIn('[FAIL]', result.stdout)
        self.assertIn('enabledPlugins', result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_old_image_label_is_fail_with_rebuild_hint(self):
        self.state['claude_label'] = ''
        result = self.check()
        self.assertIn('[FAIL] Claude project 設定ゲート: イメージが未対応', result.stdout)
        self.assertIn('-b', result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_codex_check_says_not_used(self):
        (self.conf / 'env').write_text(f'CODEX_DIR={self.codex_dir}\n')
        result = self.run_launcher('--check', '--agent', 'codex', str(self.proj))
        self.assertIn('[INFO] Claude project 設定ゲート: Codex 経路では使用しない', result.stdout)
```

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_claude_project_launch.CheckTests`（`-s tests` で discover するか、`cd tests` で実行）
Expected: FAIL

- [ ] **Step 2: 診断を実装する**

`check_one_project()` の `# Claude の .mcp.json ゲートの診断は Claude 経路だけ。` のコメントの直前に次を足す。この関数は `set -e` の下で動くので、失敗しうるコマンドは `|| rc=$?` か `if` で受ける。`[FAIL]` は stdout へ出して `CHECK_HAS_ERROR=1` にする（`guard_fail` は `[FAIL]` を付けず stderr に出すだけなので、label の確認では `guard_fail` の後に `[FAIL]` 行を足す）。

```bash
  # Claude の project 設定ゲート（#163）。--check は検査用コンテナを起動しない。ホストに python3 があれば
  # 同じ helper をホスト上で参考実行する（repo のファイルを読むだけ。git も repo のコードも実行しない）。
  if [[ "$AGENT" == codex ]]; then
    echo "[INFO] Claude project 設定ゲート: Codex 経路では使用しない（Claude の診断は --agent claude で行う）"
  elif ! claude_project_gate_needed; then
    echo "[OK]   Claude project 設定ゲート: 対象なし（.claude も .mcp.json も無い）"
  else
    if ! command -v podman >/dev/null 2>&1; then
      echo "[SKIP] podman が見つからないため、Claude project 設定ゲートの対応イメージの確認をスキップ"
    elif podman image exists "$IMAGE_NAME" 2>/dev/null; then
      if ! guard_claude_project_image_support; then
        echo "[FAIL] Claude project 設定ゲート: イメージが未対応です。-b で再ビルドしてください"
      fi
    else
      echo "[INFO] Claude project 設定ゲート: イメージ未ビルド（初回起動時にビルドしてから $CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL を確認します）"
    fi
    if ! command -v python3 >/dev/null 2>&1; then
      echo "[FAIL] Claude project 設定ゲート: ホストに python3 が無いため、このプロジェクトは起動できません"
      CHECK_HAS_ERROR=1
    else
      local project_err="" project_out="" project_rc=0 project_hash="" project_count=""
      if ! project_err=$(umask 077; mktemp "${TMPDIR:-/tmp}/cc-claude-check.XXXXXX"); then
        echo "[FAIL] Claude project 設定ゲート: 一時ファイルを作れないため診断できません"
        CHECK_HAS_ERROR=1
      else
        project_out=$(python3 -I "$RUN_DIR/claude-project-audit.py" --root "$WORKING_DIR" snapshot 2>"$project_err" \
          | python3 -I -c 'import json,sys; d=json.load(sys.stdin); print(d["hash"], d["count"])') || project_rc=$?
        if [[ $project_rc -ne 0 ]]; then
          echo "[FAIL] Claude project 設定ゲート: 起動時に止まります（ホストでの参考判定）: $(LC_ALL=C tr -d '\000-\037\177' < "$project_err")"
          CHECK_HAS_ERROR=1
        else
          read -r project_hash project_count <<<"$project_out"
          if [[ "$project_count" == 0 ]]; then
            echo "[OK]   Claude project 設定ゲート: 対象の設定なし"
          elif [[ -f "$CLAUDE_PROJECT_APPROVAL_RECORD" && "$(cat "$CLAUDE_PROJECT_APPROVAL_RECORD" 2>/dev/null || true)" == "$(claude_project_record_content "$project_hash")" ]]; then
            echo "[OK]   Claude project 設定ゲート: 承認済み（ホストでの参考判定。コンテナ内の見え方と異なる場合は起動時に確認が出ます）"
          else
            echo "[INFO] Claude project 設定ゲート: 未承認または変更あり。起動時に確認プロンプトが出ます"
          fi
        fi
        rm -f -- "$project_err"
      fi
    fi
  fi
```

パイプの左（helper）が失敗すると右の `json.load` も失敗するので、`project_rc` は非 0 になる（`pipefail` の有無に依らない）。理由は helper の stderr（`$project_err`）から出す。

- [ ] **Step 3: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_*launch.py"`
Expected: PASS

- [ ] **Step 4: README を同じコミットで直す**

Task 4 で足した小節「リポジトリの Claude 設定の確認（project 設定ゲート）」と、README の `--check` の説明（「`--check`」を含む節を grep して、Codex の審査の診断を説明している箇所）に、`--check` の出力を書く: `[OK]` 対象なし／承認済み、`[INFO]` 未承認または変更あり・イメージ未ビルド、`[FAIL]` 起動時に止まる（plugin 設定・判定不能）・イメージ未対応（`-b`）・ホストに python3 が無い、`[SKIP]` podman が無い。判定はホスト上での参考で、コンテナ内の見え方（symlink 等）と違う場合は起動時の判定が優先されること、`--check` は確認を出さず記録も書かないこと。

- [ ] **Step 5: lint・全体・Commit**

Run: `./lint.sh && ./test-build.sh --launcher-only`
Expected: `lint OK`、`FAIL=0`

```bash
git add c3c tests/test_claude_project_launch.py README.md
git commit -m "feat: --check に Claude project 設定ゲートの診断を足す（#163）"
```

---

### Task 6: 文書（SECURITY-CLAIMS・不変条件・AGENTS.md）

README は各 Task のコミットで直している（Task 3・4・5）。この Task は README 以外の文書を直し、README との整合を見直す。

**Files:**
- Modify: `SECURITY-CLAIMS.md`（C-5 を新設、冒頭の対象一覧）
- Modify: `docs/development-invariants.md`
- Modify: `AGENTS.md`（「変更前に読む」一覧）

**Interfaces:**
- Consumes: Task 1〜5 の挙動（文言は実装に合わせる）。README の `SECURITY-CLAIMS.md#c-5` へのリンク（Task 4）の行き先をこの Task で作る。

- [ ] **Step 1: SECURITY-CLAIMS に C-5 を足す**

C-4 の後に、C-3 と同じ見出し構成で C-5 を書く:
- **対象**: Claude 経路の project 設定ゲート（protocol 1、#163）。
- **成立条件・脅威モデル**: 信頼する launcher・イメージ・Podman を通常の起動経路で使い、利用者が表示された設定を確認する。対象はリポジトリ同梱の `/workspace/.claude/settings.json`・`settings.local.json`（第三者が制御しうる）。`/workspace` の trust が全プロジェクトで共有されることが前提。
- **保証する動作**: spec「判定」「処理の流れ」の内容（label 照合、検査用コンテナ、ホストでの確認と atomic な記録、`:ro` での受け渡し、本起動での再照合と TTY 確認、止める判定と判定不能の列挙、opt-out なし、`~/.claude.json` に書かない、git を実行しない）。
- **限界・非対象**: spec「残る経路」の全項目、表示は ASCII 制御文字（C0 と DEL）だけを除き、C1 制御文字（U+0080〜U+009F）や Unicode の bidi 制御等は除かない、`.claude/skills/` の配下に `/workspace` の外を指す symlink や解決できない symlink があると判定不能で起動しない、`env` の値は表示に出る（秘密を置けば見える。永続化は hash だけ）、網羅性は実装時の Claude Code の版と公式ドキュメント（2026-09-26）でだけ確認、`CLAUDE_CODE_PLUGIN_*` を止めるのは project の `env` から効くか未確認のための保守的な措置、`--check` の判定はホストでの参考。
- **根拠・検証範囲**: `c3c`・`entrypoint.sh`・`claude-project-audit.py`・`compose.yml` と `tests/test_claude_project_*.py`。実機受入の記録は PR を参照。
- **再確認契機**: Claude Code の設定形式・workspace trust・plugin の読み込み・MCP の `headersHelper` の仕様の変更、`CLAUDE_CODE_VERSION` の既定の変更、起動経路・承認保存先・マウントの変更。

冒頭の「記載しています」の一覧に C-5 を加える。

- [ ] **Step 2: docs/development-invariants.md と AGENTS.md**

`codex-mcp-audit.py` の配置の不変条件（66 行付近）の直後に、`claude-project-audit.py` の同じ不変条件（root 所有 755、`USER node` より前の `COPY`、`python3 -I`、検査用コンテナと本起動で同じ固定パスの同じスクリプト、protocol と label の同期、fail-closed、opt-out を作らない、承認記録の atomic 書き込み、`CLAUDE_PROJECT_APPROVAL_FILE`・`CC_CLAUDE_START_MODE` を全分岐で明示 export）を書く。Codex 経路の enum の不変条件（78 行付近）に `CC_CLAUDE_START_MODE` の enum を加える。`.mcp.json` ゲートの対象の記述（77 行付近）に「`headersHelper` は project 設定ゲートが止める」を足す。

`AGENTS.md` の「変更する前に該当節を読むこと」の一覧に `claude-project-audit.py` を加える。

- [ ] **Step 3: lint と Commit**

Run: `./lint.sh`
Expected: `lint OK`（リンク切れ・表記の検査を含む。README から `SECURITY-CLAIMS.md#c-5` へのリンクがここで解決する）

```bash
git add SECURITY-CLAIMS.md docs/development-invariants.md AGENTS.md
git commit -m "docs: Claude 経路の project 設定ゲートを SECURITY-CLAIMS・不変条件に書く（#163）"
```

---

### Task 7: 実機での受入

**Files:** なし（結果は PR 本文に書く）

ホストの実 Podman で行う。c3c（launcher・entrypoint・helper）がホストの `~/.claude.json` に書かないことを確かめる（Claude Code 本体は起動のたびに従来どおり書く）。`/workspace` の trust がホストの `~/.claude.json` で受け入れ済みであること（`jq '.projects["/workspace"].hasTrustDialogAccepted' ~/.claude.json` が `true`）が再現の前提。trust を手で書き換えて前提を作らない。

- [ ] **Step 0: 持ち主の repo の symlink を事前に確かめる**

```bash
for r in ~/Projects/c3c ~/Projects/findsummits ~/Projects/sotlas-frontend; do find "$r/.claude" "$r/.mcp.json" -maxdepth 4 -type l -printf '%p -> %l\n' 2>/dev/null; done
```

`/workspace`（repo の root）の外を指す symlink や dangling の symlink があれば、起動時に判定不能で止まる。見つかったら、受入の前に持ち主へ報告する（直し方は持ち主が決める）。

- [ ] **Step 1: Issue の not run の再現（修正前）**

使い捨ての repo を作る:

```bash
d=$(mktemp -d); mkdir -p "$d/.claude"
printf '%s\n' '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"touch /workspace/HOOK_RAN"}]}]}}' > "$d/.claude/settings.json"
```

main のチェックアウト（`git worktree add` した別ディレクトリ）の `c3c` で `-b` 起動し、Claude Code が起動したらすぐ `/exit` する。`ls "$d/HOOK_RAN"` で hook が確認なしで走ったことを記録する（`/workspace` の trust が既に受け入れ済みのため）。

- [ ] **Step 2: 修正後の受入**

このブランチの `c3c` で次を確かめ、それぞれの出力の要点を記録する:
1. 同じ使い捨て repo（`HOOK_RAN` を消してから）: 旧イメージのままなら label 不一致で止まり `-b` の案内が出る。
2. `-b` 後: 初回に確認が出て、`n` で起動しない（`HOOK_RAN` が作られない）。`y` で起動し、`/exit` 後に 2 回目は確認が出ない。
3. `settings.json` を書き換えると再び確認が出る。
4. ホストで `y` を答えた直後、本起動のコンテナが始まる前に `settings.json` を書き換えると、コンテナ内のゲートで確認が出る（`while` で書き換えを仕掛けるか、確認のプロンプトで止めた状態で別端末から書き換える）。
5. `c3c ... </dev/null` のように TTY なしで未承認の状態を起動すると止まる。
6. `{"enabledPlugins":{"x@y":true}}` を足すと、確認なしで止まる。`--check` が `[FAIL]` を出す。
7. 持ち主の 3 repo（c3c・findsummits・sotlas-frontend）で `-b` 起動し、初回に確認が出て 2 回目は出ない。`--check` の出力も記録する。

- [ ] **Step 3: 検証の一覧を記録する**

`./lint.sh`、`./test-build.sh --launcher-only`、`./test-build.sh --validator-only`、`./test-build.sh`（実イメージのビルドと helper・label の確認）の結果を記録する。実行できなかったものは理由とともに `not run` と書く。

---

## 計画レビューの記録

- 1 巡目（計画 66890e9）: Codex（gpt-6-astra、`codex exec --sandbox read-only`）は「修正後に渡せる」（Important 3: 権限エラーの経路を「対象なし」にする `resolve()`、改行を禁止文字として拾って必ず失敗する表示テスト、秘密の export との前後と atomic 書き込みを判別できないテスト。Minor 4: hash の符号化のテスト、`guard_fail` と `guard_error` の前提、argparse の rc 2、存在しない `--clean-all`）。Claude（claude-opus-5-5、headless、Read/Grep/Glob）は「修正後に渡せる」（Important 5: `tests/test_network_timeouts.py` の固定リストが赤になる、秘密の前後を判別できないテスト、env による上書きを判別できないテスト、README が挙動変更と別コミット、Task 7 が自分の制約を満たせない。Minor 11）。秘密の前後のテストは両者が独立に出した。反映: 全 Important（確認限定 1 巡目で両者が独立に出した、`test_codex_selection_resolves_to_run_or_preflight_only_when_explicit` の期待値の漏れも含む）と、Minor のうち M-2（未定義関数の削除）・M-3（python3 テストの文言）・M-4（compose の契約テスト）・M-5（`--check` の確定コード）・M-6（`ensure_ascii=True`）・M-7（C1 を限界に）・M-8（entrypoint のコメント）・M-9（移行手順を README へ）・M-10（symlink の事前確認）・M-11（未使用 import）、Codex M-1〜M-4。未対応: Codex M-1 のうち「同じ読み取り結果を使うこと」の回帰テスト（実装の構造で保証し、専用テストは置かない。helper は各ファイルを 1 回だけ読み、そのバイト列から判定・表示・hash を作る）と、非 UTF-8 パス（hash 対象のパスは固定の ASCII 名なので該当しない）。

## 自己レビュー（計画者）

- spec の網羅: 目的・成功条件（Task 1〜5）、審査対象と判定（Task 1）、確認の表示（Task 1 の display、Task 3・4 の表示）、処理の流れ（Task 3・4）、承認記録（Task 4）、`--check`（Task 5。spec で計画に送った「検査用コンテナを起動するか」は、Codex と同じく起動せず、ホストで helper を参考実行する方に決めた）、旧イメージ（Task 4 の label と明示ビルド）、文書（Task 6）、検証（Task 1〜5 のテストと Task 7）、バージョン（下記）。
- バージョン: spec のとおり MAJOR の見込み。番号とタグ提案は、Task 7 の後に `release-tag` skill の手順で持ち主に提案する（自動では付けない）。`--check` が移行の要否（label 不一致・plugin 設定）を検出できることは Task 5 のテストと Task 7 の Step 2-6・2-7 で確かめる。

区分: 境界（セッション開始と同時に秘密を読めるコードの実行経路に新しいゲートを置き、`entrypoint.sh` の秘密の export の前段・`compose.yml` のマウント・SECURITY-CLAIMS の保証範囲を変えるため）。
推奨実装: Opus（グローバル指示の判定 2「秘密やトークンを読む経路に触れる変更」に当たり、セキュリティ境界を含むため。Codex は判定 4 の「逐語手順」を満たすが、判定 2 が先に当たる。Sonnet は境界の変更なので推さない。Task 5 の `check_one_project()` への合わせ込みなど、実装中に既存コードへ合わせる判断が残る）。
