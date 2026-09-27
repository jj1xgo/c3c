# project 設定ゲートと lint の残りの Minor を片付ける（#174〜#177）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #164・#168・#172 のレビューで Minor として残った 4 件を、1 本の PR で片付ける。承認記録の読み取り上限の穴を塞ぐ（#177）、回帰テストの穴を埋める（#174・#175）、審査範囲の限界を文書に書く（#176）。

**Architecture:** どれも既存の仕組みの中で直す。
- #177: helper の `read_record_hash()` が上限を 1 バイト超えて読み、超えたら記録なしとして扱う。
- #174: `lint.sh` の 7 ファイル同時検査を、stdin で config を受ける関数に切り出す。既存の `tests/test-lint-compose-checks.sh` と同じ sed 抽出で fixture を渡す。
- #175: 既存の launcher テストの土台（fake compose・実 helper）にケースを足す。
- #176: README と SECURITY-CLAIMS C-5 の文言を直す。

**Tech Stack:** python3 標準ライブラリ（helper と unittest）、bash（`lint.sh` と fixture テスト）、Markdown。

**Issue:** #174・#175・#176・#177（出どころと根拠は各 Issue の本文）

## Global Constraints

- 日本語で書く（README「表記」節の例外に従う）。`ERROR:`・`[FAIL]` などの接頭辞は英語のまま。
- helper の `PROTOCOL_VERSION`・image label・launcher の `CLAUDE_PROJECT_AUDIT_PROTOCOL_VERSION` は変えない（`docs/development-invariants.md` 69 行: 3 つは同期する）。
- project 設定ゲートの停止条件・終了コード（0 = 通す、3 = 確認、1 = 止める）・fail-closed は弱めない（同 81 行）。
- `lint.sh` の compose 検査は、provider の出力形式（短縮表記 / long syntax）に依らず意味で判定する（同 56 行）。関数定義は `sed -n '/^<name>()/,/^}/p'` で抽出できる形（開始行 `name() {`、終了行 `}`）に保つ（`lint.sh` 70 行のコメント）。
- Python テストは `PYTHONDONTWRITEBYTECODE=1` を付けて走らせる（`tests/__pycache__/` を作らない）。
- 公開の計画なので、ホスト固有のパスを書かない。

## 前提（計画時に確かめた事実、main 58acf3a）

- **#177**:
  - `claude-project-audit.py:220-232` の `read_record_hash()` は `handle.read(4096)` で読む。先頭 4096 バイトが「有効な JSON と空白」だけで完結し、その先に何かが続く記録を、有効として扱う。有効な JSON の直後に破損を置いた記録は、今でも `json.loads` の trailing data で失敗する。このため、red のテストは空白で 4096 バイトまで埋める必要がある。
  - c3c が書く記録は `{"protocol_version":1,"hash":"<64 hex>"}\n` の 97 バイト。
  - ホスト側（`c3c:1480-1484` の `check_claude_project_approval`）は、記録の内容が `claude_project_record_content` の出力と一致したときだけ `CLAUDE_PROJECT_APPROVAL_FILE` に記録を渡す。比べるのは `$(cat)` の結果なので、末尾の改行はいくつあっても無視される。このため、97 バイトの記録の末尾に改行を足した記録（例: 5097 バイト）でもホストの比較は一致し、コンテナの helper に届く（計画時に実測。計画レビューで Codex が指摘）。c3c 自身がそういう記録を書くことはなく、ホスト側で記録を書き換えた場合に限られる。
  - 修正の後、そうした 4096 バイトを超える記録は helper で「記録なし」になり、コンテナ内で確認が出る（TTY が無ければ止まる）。確認が増える側（fail-closed 側）の変化で、迂回にはならない。修正の目的は、上限より後ろのバイトを見ないまま承認済みと判定することを無くすこと（深層防御）である。Task 1 に、この場合を固定するテストも入れる。
- **#175**:
  - PR #168 の Claude レビューの M6 の原文は、(a)「launcher 側で表示行から制御文字を除く処理（`CONTROL.sub`）を試すテストがない」、(b)「skills の項目が外向きの symlink のとき判定不能になるテストがない」、(c)「`--check` が `.mcp.json` の `headersHelper` を `[FAIL]` にするテストがない」。
  - (a) の `CONTROL.sub` は `c3c` の `run_claude_project_preflight()` に埋め込んだ Python（`handle.write(CONTROL.sub('', line) + '\n')`）にある。検査用コンテナの出力は、テストでは fake compose が `state['claude_preflight']` から返す。表示行に ESC を入れれば、この行を外したときに赤になる。
  - (b) は、helper 単体ではすでに `tests/test_claude_project_audit.py` の `test_error_messages_strip_control_characters_from_repo_names` が確かめている（skills に、名前に ESC を含み、root の外を指す symlink を置いて「判定できません」を検査する）。通常起動の経路は fake compose なので、本物の helper は走らない。そのため、本物の helper を launcher 経由で走らせる `--check` の経路（`c3c:2635-2640`）に絞る。Issue #175 の本文は「通常起動と `--check`」と書いたが、通常起動の経路では fake の出力をなぞるだけになるので、ここで範囲を絞る（PR 本文に書く）。
  - Issue #175 の完了条件は、`--check` の表示で helper の stderr から制御文字を除く `tr -d`（`c3c:2638`）にも触れている（M6 の原文より広い）。本物の helper は自分で制御文字を除くので、helper を使うテストでは `tr -d` を外しても赤にならない。そこで、runner のコピーの helper を stub に差し替え、制御文字を含む stderr を返させて確かめる（計画レビューで Codex が指摘）。これを (d) として足す。
  - launcher テストは、実 launcher と実アセットを `self.runner`（一時ディレクトリ）へ **コピー** して使う（`tests/test_codex_launch.py:141-149`）。helper もコピーされるので、テストの中で `self.runner / 'claude-project-audit.py'` を書き換えても、リポジトリのファイルは変わらない。ミューテーション確認は、対象ファイルが clean であることを確かめてからリポジトリのファイルを一時的に書き換え、確かめた後に `git checkout --` で戻す。
  - `self.proj` は `self.root / 'proj'`。`self.root` の直下は proj の外に当たる。
- **#174**:
  - 7 ファイル同時検査は `lint.sh:246-259`。ループの target は `/tmp/lint-plugins-alias /home/node/lint-shared-home /tmp/lint-shared-host /home/node/.agents /home/node/.codex/plugins/cache` の 5 つ。IPv6 は `network_mode: pasta:-g,fe80::1` の行を grep する。
  - `tests/test-lint-compose-checks.sh` は `test-build.sh:841`（`run_launcher_tests()` の中）から呼ばれる。CI の `--launcher-only` でも走る。
  - 関数を fixture で試すだけでは、lint 本体の呼び出しを `|| true` に変えても赤にならない（計画レビューで Codex が指摘）。偽の provider で `lint.sh` 全体を走らせる方式は採らない。`lint.sh` は他にも十数回 `podman compose` を呼び、`${VAR:?}` の検査は config の失敗を期待するので、偽の provider がそれを全部まねる必要があるためである。代わりに、7 ファイル同時の config を取る `if` の直後の行が `compose_merged_overrides_ok <<<"$merged" || status=1` であることを、同じテストで固定する。
  - 7 ファイル同時の config を取る `if` の行は、`-f compose.agents.yml -f compose.codex-plugins.yml config); then` で終わる唯一の行である（`-f compose.codex-plugins.yml config); then` で終わる行は、Codex キャッシュ単独の検査にもう 1 行ある）。
- **#176**:
  - 実測（計画時、ホスト）: ホームディレクトリを作業ディレクトリにして `c3c claude --check <ホーム>` を実行した。user 設定 `~/.claude/settings.json` の `enabledPlugins` で plugin を有効にしていると、`[FAIL] Claude project 設定ゲート: 起動時に止まります（ホストでの参考判定）: ERROR: ... .claude/settings.json の enabledPlugins で plugin が有効になっています（...）` が出る。同時に、既存の `WARNING: <ホーム> が <ホーム>/.claude を含む（または含まれる）ため、別の rw マウント経由で書けます。` も出る。
  - helper の `check_skills_plugins()`（`claude-project-audit.py:166-177`）は、まず `.claude/skills` 自体を `resolve()` で解決し（`.claude` と `.claude/skills` の段を確かめる）、列挙した各 `<name>` について `.claude/skills/<name>/.claude-plugin/plugin.json` を段ごとに解決する。どの段であれ root の外・dangling・循環の symlink や、`lstat`・`stat` の失敗（権限エラー等）なら判定不能で止まる。これより下にある skill の他のファイル（`SKILL.md` など）は辿らない。
  - ホームを作業ディレクトリにしたときに user 設定で止まりうる条件は、plugin の有効化に限らない。`check_settings` の停止条件（`enabledPlugins`・`extraKnownMarketplaces`・`env` の `CLAUDE_CODE_PLUGIN_*`）と、`~/.claude/skills/` の skills-directory plugin や `/workspace` の外を指す symlink（計画レビューで Claude が指摘）。
  - 直す文言は 3 か所。README 441 節の箇条書き（「確認を出さずに起動を止める条件」の後）、同節の移行手順 4、SECURITY-CLAIMS C-5 の「限界・非対象」の skills の項。

- 計画時の試行（main 58acf3a から切ったリポジトリ外の worktree。リポジトリの実装対象は編集していない。計画レビューの反映後にやり直した）: Task 1〜4 のコードとコマンドを、この計画から逐語で抜き出して適用した。
  - Task 1: red は `FAILED (failures=2)`、green は 38 件 OK。
  - Task 2: green は 28 件 OK。ミューテーション 4 回は、それぞれ FAIL 1・2・1・1 で、どれも戻した後に `restored`。
  - Task 3: red は 25 ケース中 7 件 FAIL、green は 25 ケース・shellcheck rc 0。ミューテーション 2 回は、それぞれ 3 件・1 件 FAIL で、どちらも `restored`。worktree での `./lint.sh` は rc 0・`lint OK`（実 Podman の Compose 検証を含む）。
  - Task 4: `git diff --check` は出力なし。grep の件数は Expected どおり。
  - 切り出した関数は、ホストの実 Podman で作った 7 ファイル同時の config でも rc 0 だった。`.agents` の target を `.agents-x` に書き換えると rc 1 になった。

## Review Focus

1. **ちょうど 4096 バイトの承認記録**: 上限いっぱいの記録は、今までどおり有効として読む（上限を 1 バイト縮めない）。→ Task 1 の `test_verify_accepts_record_of_exactly_4096_bytes`。
2. **docker compose の long syntax**: CI の Compose 検証は docker compose provider で走るので、切り出した関数は long syntax の config でも合格する必要がある。→ Task 3 の long syntax の合格ケース。
3. **IPv6 の network_mode の欠落**: 関数に切り出しても、network_mode の検査を落とさない。→ Task 3 の「network_mode なしは失敗」ケース。
4. **skills の項目が dangling の symlink**: 外向きの symlink だけでなく、解決できない symlink でも `--check` は `[FAIL]` を出す。→ Task 2 の (b) の subTest。
5. **制御文字の除去で表示の本文まで消さない**: ESC を除いた後も、同じ行の本文は表示に残る。→ Task 2 の (a) で、除去後の行そのもの（`  {"x": "[2J[Hfake"}`）が stderr の 1 行として出ることを検査する。

---

### Task 1: helper が承認記録を上限まで読み、超えたら記録なしとして扱う（#177）

**Files:**
- Modify: `claude-project-audit.py`（定数の並び 29-40 行、`read_record_hash()` 220-232 行）
- Test: `tests/test_claude_project_audit.py`（`VerifyTests` の末尾、`test_blocked_state_wins_over_matching_record` の後）

**Interfaces:**
- Consumes: なし
- Produces: 定数 `RECORD_LIMIT = 4096`。`read_record_hash(path)` の戻り値の型は変えない（`str` か `None`）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_claude_project_audit.py` の `VerifyTests` の `test_blocked_state_wins_over_matching_record` の直後（`if __name__ == '__main__':` の前）に、次の 3 つを足す。

```python
    def test_verify_rejects_record_with_bytes_beyond_4096(self):
        # #177: 先頭 4096 バイトだけで有効な JSON と空白が完結し、その先にバイトが続く記録を、承認済みと読まない。
        self.put('.claude/settings.json', HOOKS)
        head = json.dumps({'protocol_version': 1, 'hash': self.snapshot()['hash']}, separators=(',', ':')).encode()
        self.record.write_bytes(head + b' ' * (4096 - len(head)) + b'garbage')
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 3)

    def test_verify_accepts_record_of_exactly_4096_bytes(self):
        # 上限いっぱいの記録は今までどおり読む（境界を 1 バイト縮めない）。
        self.put('.claude/settings.json', HOOKS)
        head = json.dumps({'protocol_version': 1, 'hash': self.snapshot()['hash']}, separators=(',', ':')).encode()
        self.record.write_bytes(head + b' ' * (4096 - len(head)))
        self.assertEqual(self.record.stat().st_size, 4096)
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 0)

    def test_verify_treats_newline_padded_record_over_4096_as_missing(self):
        # host は $(cat) で比べるので末尾の改行を無視し、この記録も helper に渡す。helper は上限を超えた記録を
        # 記録なしとして扱い、確認に回す（fail-closed 側。#177）。
        self.put('.claude/settings.json', HOOKS)
        head = json.dumps({'protocol_version': 1, 'hash': self.snapshot()['hash']}, separators=(',', ':')).encode()
        self.record.write_bytes(head + b'\n' * 5000)
        self.assertEqual(self.run_helper('verify', str(self.record)).returncode, 3)
```

- [ ] **Step 2: 赤を確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_audit.py -k 4096 -v`
Expected: `Ran 3 tests`、`FAILED (failures=2)`。`test_verify_rejects_record_with_bytes_beyond_4096` と `test_verify_treats_newline_padded_record_over_4096_as_missing` が FAIL（どちらも `AssertionError: 0 != 3`）。`test_verify_accepts_record_of_exactly_4096_bytes` は ok。

- [ ] **Step 3: 最小の実装**

`claude-project-audit.py` の定数の並びで、`RECORD_KEYS = frozenset(('protocol_version', 'hash'))` の直前に次の 1 行を足す。

```python
RECORD_LIMIT = 4096
```

`read_record_hash()` を次のように直す（docstring、`read` の引数、上限の判定の 3 点）。

```python
def read_record_hash(path):
    """承認記録の hash。空・壊れている・RECORD_LIMIT を超える・別 protocol は None（記録なしと同じ扱い）。"""
    try:
        with open(path, 'rb') as handle:
            data = handle.read(RECORD_LIMIT + 1)
        if len(data) > RECORD_LIMIT:
            # 先頭だけで判定すると、上限より後ろに続くバイトを見落とす（#177）。host は記録全体を比べる。
            return None
        record = json.loads(data.decode('utf-8'), object_pairs_hook=strict_pairs, parse_constant=reject_constant)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
```

（`if (not isinstance(record, dict) ...` 以降は変えない。）

- [ ] **Step 4: 緑を確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_audit.py -v 2>&1 | tail -3`
Expected: `Ran 38 tests`、`OK`（既存 35 + 3）。

- [ ] **Step 5: コミット**

```bash
git add claude-project-audit.py tests/test_claude_project_audit.py
git commit -m "fix: helper が承認記録の 4096 バイトより後ろを見落とさないようにする（#177）"
```

### Task 2: project 設定ゲートの launcher・`--check` 経路のテストの穴を埋める（#175）

**Files:**
- Test: `tests/test_claude_project_launch.py`（`PreflightTests` の末尾と `CheckTests` の末尾）
- 本体の変更は無い

**Interfaces:**
- Consumes: 既存の `claude_protocol(hash_value, count, lines, extra)`、`ClaudeProjectLaunchCase.launch()`、`CheckTests.check()`、`self.main_runs()`
- Produces: なし

- [ ] **Step 1: テストを書く**

`PreflightTests` の `test_preflight_failure_or_malformed_protocol_blocks_run_and_writes_nothing` の直後に足す。

```python
    def test_launcher_strips_control_characters_from_preflight_lines(self):
        # #175 (a): 検査用コンテナの表示行に ESC 等が混じっても、launcher 側（run_claude_project_preflight の
        # CONTROL.sub）で除いてから端末へ出す。helper 側の除去とは独立の二重の防御。
        lines = ['--- .claude/settings.json ---', '  {"x": "\x1b[2J\x1b[Hfake\x07"}']
        self.state['claude_preflight'] = {'stdout': claude_protocol(lines=lines)}
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('\n  {"x": "[2J[Hfake"}\n', result.stderr)
        self.assertNotIn('\x1b', result.stderr)
        self.assertNotIn('\x07', result.stderr)
        self.assertEqual(self.main_runs(), [])
```

`CheckTests` の `test_plugin_setting_is_fail_for_migration` の直後（ファイル末尾の `if __name__` より前で、`CheckTests` の中）に足す。

```python
    def test_outward_or_dangling_skills_symlink_is_fail(self):
        # #175 (b): .claude/skills/<name> が proj の外を指す、または解決できない symlink なら、--check は
        # ホストの実 helper の判定不能を [FAIL] で知らせる。helper 単体の検査は test_claude_project_audit.py にある。
        outside = self.root / 'outside-skill'
        outside.mkdir()
        skills = self.proj / '.claude' / 'skills'
        skills.mkdir()
        for name, target in (('outward', outside), ('dangling', self.root / 'missing-skill')):
            with self.subTest(name=name):
                link = skills / name
                link.symlink_to(target)
                try:
                    result = self.check()
                finally:
                    link.unlink()
                self.assertIn('[FAIL] Claude project 設定ゲート: 起動時に止まります', result.stdout)
                self.assertIn('判定できません', result.stdout)
                self.assertNotEqual(result.returncode, 0)

    def test_headers_helper_is_fail(self):
        # #175 (c): .mcp.json の http 型サーバーに headersHelper があれば、--check は [FAIL] を出す。
        (self.proj / '.mcp.json').write_text(json.dumps(
            {'mcpServers': {'remote': {'type': 'http', 'url': 'https://example.invalid', 'headersHelper': '/bin/x'}}}))
        result = self.check()
        self.assertIn('[FAIL] Claude project 設定ゲート: 起動時に止まります', result.stdout)
        self.assertIn('headersHelper', result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_check_strips_control_characters_from_helper_stderr(self):
        # #175 (d): --check は helper の stderr を tr -d で除いてから [FAIL] の行に出す（c3c の --check 経路）。
        # 本物の helper は自分で除くので、runner のコピーを、制御文字を出して rc 1 で終わる stub に差し替える。
        (self.runner / 'claude-project-audit.py').write_text(
            'import sys\nsys.stderr.write("ERROR: \\x1b[2Jfake\\x07\\n")\nsys.exit(1)\n')
        result = self.check()
        self.assertIn('[FAIL] Claude project 設定ゲート: 起動時に止まります（ホストでの参考判定）: ERROR: [2Jfake', result.stdout)
        self.assertNotIn('\x1b', result.stdout)
        self.assertNotIn('\x07', result.stdout)
        self.assertNotEqual(result.returncode, 0)
```

- [ ] **Step 2: 緑を確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_launch.py -v 2>&1 | tail -3`
Expected: `Ran 28 tests`、`OK`（既存 24 + 4）。

- [ ] **Step 3: ミューテーションで赤を確かめる（4 回。各回の後に必ず戻す）**

本体の変更が無いタスクなので、red は処理を一時的に外して確かめる。各回は `set -e` のサブシェルで行う。対象ファイルが clean でなければ（`git diff --quiet -- <file>` が非 0 なら）何も書き換えずに止まる。clean なら `trap` を置いてから書き換えるので、テストの失敗や中断でサブシェルが終わっても、`git checkout -- <file>` で必ず戻る。最後に、サブシェルの外で `git diff --quiet -- <file>` を確かめる（テストの追加はまだコミットしていないので、ファイルを指定する）。

注意: Task 1 をコミットした後に行うこと（`git checkout --` は、そのファイルの未コミットの変更まで消すため。先頭の clean の確認も、未コミットの変更があれば止める）。

(a) `c3c` の `handle.write(CONTROL.sub('', line) + '\n')` を `handle.write(line + '\n')` にする。

```bash
( set -e; f=c3c; git diff --quiet -- "$f"; trap 'git checkout -- "$f"' EXIT
  sed -i "s/handle.write(CONTROL.sub('', line) + '\\\\n')/handle.write(line + '\\\\n')/" "$f"
  git diff --stat -- "$f"   # 1 行だけ変わっていること
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_launch.py -k strips_control -v 2>&1 | tail -3 )
git diff --quiet -- c3c && echo restored
```
Expected: `FAILED (failures=1)`、その後 `restored`。`git diff --stat` の行が出なければ sed が当たっていない（その回はやり直す）。

(b) `claude-project-audit.py` の `check_skills_plugins()` の `names = sorted(os.listdir(skills))` を `names = []` にする。

```bash
( set -e; f=claude-project-audit.py; git diff --quiet -- "$f"; trap 'git checkout -- "$f"' EXIT
  sed -i 's/        names = sorted(os.listdir(skills))/        names = []/' "$f"
  git diff --stat -- "$f"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_launch.py -k skills_symlink -v 2>&1 | tail -3 )
git diff --quiet -- claude-project-audit.py && echo restored
```
Expected: `FAILED (failures=2)`（subTest 2 件とも）、その後 `restored`。

(c) `check_mcp()` の `if 'headersHelper' in server:` を `if False:` にする。

```bash
( set -e; f=claude-project-audit.py; git diff --quiet -- "$f"; trap 'git checkout -- "$f"' EXIT
  sed -i "s/        if 'headersHelper' in server:/        if False:/" "$f"
  git diff --stat -- "$f"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_launch.py -k headers_helper -v 2>&1 | tail -3 )
git diff --quiet -- claude-project-audit.py && echo restored
```
Expected: `FAILED (failures=1)`、その後 `restored`。

(d) `c3c` の `--check` の `$(LC_ALL=C tr -d '\000-\037\177' < "$project_err")` を `$(cat "$project_err")` にする。

```bash
( set -e; f=c3c; git diff --quiet -- "$f"; trap 'git checkout -- "$f"' EXIT
  sed -i "s/\$(LC_ALL=C tr -d '\\\\000-\\\\037\\\\177' < \"\$project_err\")/\$(cat \"\$project_err\")/" "$f"
  git diff --stat -- "$f"
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_claude_project_launch.py -k helper_stderr -v 2>&1 | tail -3 )
git diff --quiet -- c3c && echo restored
```
Expected: `FAILED (failures=1)`、その後 `restored`。

- [ ] **Step 4: コミット**

```bash
git add tests/test_claude_project_launch.py
git commit -m "test: project 設定ゲートの launcher と --check 経路のテストの穴を埋める（#175）"
```

### Task 3: lint の 7 ファイル同時検査を関数に切り出し、回帰テストを足す（#174）

**Files:**
- Modify: `lint.sh`（`compose_tty_disabled()` の定義の直後 144 行の後に関数を足す。246-259 行の呼び出し側を関数呼び出しに置き換える）
- Test: `tests/test-lint-compose-checks.sh`

**Interfaces:**
- Consumes: 既存の `compose_mount_is_ro <target>`（stdin に config）
- Produces: `compose_merged_overrides_ok`（引数なし、stdin に 7 ファイル同時の config。合格なら 0、不合格なら `ERROR:` を stderr に出して 1）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test-lint-compose-checks.sh` を 4 か所直す。

0. 冒頭コメント（2 行目）の `（compose_mount_is_ro / compose_tty_disabled）` を `（compose_mount_is_ro / compose_tty_disabled / compose_merged_overrides_ok と、その lint 本体への配線）` に置き換える。

1. harness を作る sed に、新しい関数の抽出を足す。

```bash
  sed -n '/^compose_mount_is_ro()/,/^}/p; /^compose_tty_disabled()/,/^}/p; /^compose_merged_overrides_ok()/,/^}/p' "$ROOT/lint.sh"
```

2. harness の `case` に 1 行足す。

```bash
case "$1" in
  ro) compose_mount_is_ro "$2" ;;
  tty) compose_tty_disabled ;;
  merged) compose_merged_overrides_ok ;;
esac
```

3. `# --- TTY / stdin ---` の節の後、`echo "結果: $count ケース、失敗 $fail"` の前に次を足す。

```bash
# --- 7 ファイル同時 config（lint.sh の compose_merged_overrides_ok、#174） ---
# 呼び出し側を部分一致（grep -F 等）へ戻すと、.agents-x の fixture が合格して赤になる。
merged_short='services:
  claude-auth-workspace:
    network_mode: pasta:-g,fe80::1
    volumes:
      - /tmp:/tmp/lint-plugins-alias:ro
      - /tmp:/home/node/lint-shared-home:ro
      - /tmp:/tmp/lint-shared-host:ro
      - /tmp:/home/node/.agents:ro
      - /tmp:/home/node/.codex/plugins/cache:ro'
run_case '7 ファイル（短縮表記）: 5 つの :ro と network_mode があれば合格' merged 0 "$merged_short"
run_case '7 ファイル（短縮表記）: .agents が .agents-x に化けていれば失敗' merged 1 "${merged_short/\/home\/node\/.agents:ro/\/home\/node\/.agents-x:ro}"
run_case '7 ファイル（短縮表記）: 1 つが :rw なら失敗' merged 1 "${merged_short/lint-shared-host:ro/lint-shared-host:rw}"
merged_no_ipv6=$(printf '%s\n' "$merged_short" | sed '/network_mode:/d')
run_case '7 ファイル（短縮表記）: network_mode が無ければ失敗' merged 1 "$merged_no_ipv6"
merged_long='services:
  claude-auth-workspace:
    network_mode: pasta:-g,fe80::1
    volumes:'
for t in /tmp/lint-plugins-alias /home/node/lint-shared-home /tmp/lint-shared-host /home/node/.agents /home/node/.codex/plugins/cache; do
  merged_long+="
      - type: bind
        source: /tmp
        target: $t
        read_only: true
        bind:
          create_host_path: true"
done
run_case '7 ファイル（long syntax）: 5 つの read_only と network_mode があれば合格' merged 0 "$merged_long"
run_case '7 ファイル（long syntax）: .agents が .agents-x に化けていれば失敗' merged 1 "${merged_long/target: \/home\/node\/.agents$'\n'/target: \/home\/node\/.agents-x$'\n'}"
[[ "${merged_short/\/home\/node\/.agents:ro/\/home\/node\/.agents-x:ro}" != "$merged_short" \
  && "${merged_long/target: \/home\/node\/.agents$'\n'/target: \/home\/node\/.agents-x$'\n'}" != "$merged_long" \
  && "$merged_no_ipv6" != "$merged_short" ]] || { echo 'FAIL - 7 ファイルの対照 fixture の生成'; fail=$((fail + 1)); }
# lint 本体の配線（#174）: 7 ファイル同時 config を取る if の直後の行が、関数の結果を status へ反映する呼び出しであること。
# 偽の provider で lint.sh 全体を走らせる方式は採らない（lint.sh は他にも十数回 compose を呼び、${VAR:?} の検査は
# config の失敗を期待するので、偽の provider がそれを全部まねる必要がある）。呼び出しを || true 等へ変えると赤になる。
wiring=$(awk 'prev ~ /-f compose\.agents\.yml -f compose\.codex-plugins\.yml config\); then$/ { print; exit } { prev = $0 }' "$ROOT/lint.sh")
count=$((count + 1))
# shellcheck disable=SC2016 # 意図的にリテラル（lint.sh の 1 行と文字どおり比べる。変数展開ではない）
if [[ "$wiring" == '    compose_merged_overrides_ok <<<"$merged" || status=1' ]]; then
  echo 'ok - lint 本体: 7 ファイル同時 config の検査結果を status へ反映している'
else
  echo "FAIL - lint 本体: 7 ファイル同時 config の直後の行が想定と違う: ${wiring:-（見つからない）}"; fail=$((fail + 1))
fi
```

- [ ] **Step 2: 赤を確かめる**

Run: `bash tests/test-lint-compose-checks.sh; echo rc=$?`
Expected: 関数がまだ無いので、`7 ファイル（...）` の 6 ケースすべてが `(rc=127, expected ...)` で FAIL になる（失敗を期待するケースも、rc 127 では `ERROR:` が無いので FAIL）。配線のケースも、直後の行がまだ `# 部分一致だと…` のコメントなので FAIL。`結果: 25 ケース、失敗 7`、`rc=1`。既存の 18 ケースは ok のまま。（計画時にリポジトリ外のコピーで確かめた）

- [ ] **Step 3: 最小の実装**

`lint.sh` の `compose_tty_disabled()` の終わりの `}`（144 行）の直後に、空行を 1 つ挟んで次を足す。

```bash

# 7 ファイル同時の compose config（stdin）に、plugin 別名・指示ファイルの共有・AGENTS_DIR・Codex キャッシュの
# :ro mount と IPv6 の network_mode が残っていることを確かめる（override のマージで消えていないこと）。
# 部分一致だと /home/node/.agents-x のような別の target でも通るので、mount は target の完全一致で
# 意味を見る（compose_mount_is_ro）。IPv6 は mount ではないので network_mode の行を行頭と行末で照合する（#112）。
# tests/test-lint-compose-checks.sh が関数定義だけを抽出して fixture で検証する（#174）。
compose_merged_overrides_ok() {
  local merged target rc=0
  merged=$(cat)
  for target in /tmp/lint-plugins-alias /home/node/lint-shared-home /tmp/lint-shared-host /home/node/.agents /home/node/.codex/plugins/cache; do
    compose_mount_is_ro "$target" <<<"$merged" \
      || { echo "ERROR: compose の 7 ファイル同時 config に :ro の '$target' がありません（override のマージで消えています）" >&2; rc=1; }
  done
  grep -qE -- "^[[:space:]]*network_mode:[[:space:]]*['\"]?pasta:-g,fe80::1['\"]?[[:space:]]*\$" <<<"$merged" \
    || { echo "ERROR: compose の 7 ファイル同時 config に IPv6 の network_mode がありません（override のマージで消えています）" >&2; rc=1; }
  return "$rc"
}
```

呼び出し側（今の 246-259 行）を次のように置き換える。`if merged=$(...config); then` の 3 行と `else` 以降は変えず、`then` と `else` の間だけを 1 行にする。

```bash
  if merged=$(CLAUDE_PLUGINS_HOST_PATH=/tmp/lint-plugins-alias SHARED_MOUNT=/tmp \
      CLAUDE_SHARED_HOME_PATH=/home/node/lint-shared-home CLAUDE_SHARED_HOST_PATH=/tmp/lint-shared-host AGENTS_DIR=/tmp C3C_CODEX_PLUGINS_SOURCE=/tmp \
      podman compose -f compose.yml -f compose.ipv6.yml -f compose.plugins-alias.yml \
        -f compose.shared-home.yml -f compose.shared-host.yml -f compose.agents.yml -f compose.codex-plugins.yml config); then
    compose_merged_overrides_ok <<<"$merged" || status=1
  else
```

（元の 2 行のコメント「部分一致だと…（#112）。」は関数の上へ移したので、呼び出し側からは消す。）

- [ ] **Step 4: 緑を確かめる**

Run: `bash tests/test-lint-compose-checks.sh; echo rc=$?`
Expected: 全ケース `ok`、`結果: 25 ケース、失敗 0`、`rc=0`。`shellcheck -x lint.sh tests/test-lint-compose-checks.sh` も rc 0（呼び出し側を置き換える前は、新しい関数に SC2329「never invoked」が出る。配線の比較の SC2016 は、テストに書いた disable の注記で抑える）。

- [ ] **Step 5: ミューテーションで赤を確かめる（2 回。Step 3 の変更はまだコミットしていないので、控えから戻す）**

各回は `set -e` のサブシェルで行う。控えを取ってから `trap` を置き、書き換えるので、テストの失敗や中断でサブシェルが終わっても控えから必ず戻る。最後に、サブシェルの外で `cmp` で控えと比べる。

(1) 関数の中の完全一致を、部分一致（`grep -qF`）に戻す。

```bash
bak="${TMPDIR:-/tmp}/c3c-lint-174.bak"
( set -e; cp lint.sh "$bak"; trap 'cp "$bak" lint.sh' EXIT
  sed -i 's/    compose_mount_is_ro "$target" <<<"$merged" \\$/    grep -qF -- "$target" <<<"$merged" \\/' lint.sh
  diff "$bak" lint.sh | grep -c '^> .*grep -qF'   # 1 であること
  bash tests/test-lint-compose-checks.sh | grep -E '^FAIL|結果' )
cmp lint.sh "$bak" && echo restored
```
Expected: `.agents-x` の 2 ケースと `1 つが :rw なら失敗` の計 3 ケースが `(rc=0, expected 1)` で FAIL、`結果: 25 ケース、失敗 3`。その後 `restored`。

(2) lint 本体の呼び出しを `|| true` にする。

```bash
bak="${TMPDIR:-/tmp}/c3c-lint-174.bak"
( set -e; cp lint.sh "$bak"; trap 'cp "$bak" lint.sh' EXIT
  sed -i 's/    compose_merged_overrides_ok <<<"$merged" || status=1$/    compose_merged_overrides_ok <<<"$merged" || true/' lint.sh
  diff "$bak" lint.sh | grep -c '^> .*|| true'   # 1 であること
  bash tests/test-lint-compose-checks.sh | grep -E '^FAIL|結果' )
cmp lint.sh "$bak" && echo restored && rm -f "$bak"
```
Expected: 配線のケースだけが FAIL、`結果: 25 ケース、失敗 1`。その後 `restored`。

- [ ] **Step 6: lint 全体を確かめる**

Run: `./lint.sh > /tmp/c3c-lint-174.log 2>&1; echo rc=$?; tail -3 /tmp/c3c-lint-174.log`
Expected: `rc=0`、`lint OK`、WARNING なし（shellcheck の版の WARNING は環境差として別に記録する）。Compose 検証がスキップされた（podman が無い・`LINT_SKIP_COMPOSE`）場合は、7 ファイル検査の実 config での確認を `not run` として報告する。

- [ ] **Step 7: コミット**

```bash
git add lint.sh tests/test-lint-compose-checks.sh
git commit -m "test: lint の 7 ファイル同時検査を関数に切り出し、呼び出し側の回帰テストを足す（#174）"
```

### Task 4: project 設定ゲートの審査範囲の限界を README と C-5 に書く（#176）

**Files:**
- Modify: `README.md`（441 節「リポジトリの Claude 設定の確認（project 設定ゲート）」の箇条書きと移行手順 4）
- Modify: `SECURITY-CLAIMS.md`（C-5 の「限界・非対象」）

**Interfaces:** なし

- [ ] **Step 1: README の箇条書きに 2 項目を足す**

441 節の箇条書きで、`- 確認を出さずに起動を止める条件: ...（...1 MiB を超えるファイル）も止まる。` の行の直後、`- \`.claude\` か \`.mcp.json\` を持つリポジトリは、...` の行の前に、次の 2 行を足す。

```markdown
- `.claude/skills/` で確かめるのは、`.claude/skills` 自体と、各項目 `.claude/skills/<name>` から `.claude-plugin/plugin.json` までの各段。どこかの段がリポジトリの外を指す symlink や解決できない symlink なら止まる（権限エラー等で段を確かめられないときも止まる）。それより下にある skill のファイル（例: `.claude/skills/foo/SKILL.md`）がリポジトリの外を指していても止まらない（skills の本文は審査しない。[SECURITY-CLAIMS の C-5](SECURITY-CLAIMS.md#c-5)）。
- 作業ディレクトリが Claude Code の設定ディレクトリの親（既定の `~/.claude` ならホームディレクトリ。`c3c claude ~` など）だと、user 設定（`~/.claude/settings.json`・`settings.local.json`・`~/.claude/skills/`）が `/workspace/.claude/` の project 設定として見え、表示と確認の対象になる。user 設定が確認の前に止める条件や判定できない条件に当たれば（plugin の有効化、`extraKnownMarketplaces`、`env` の `CLAUDE_CODE_PLUGIN_*`、`~/.claude/skills/` の skills-directory plugin やホームの外を指す symlink など）、起動しない（`--check` も `[FAIL]`）。この構成では、`~/.claude` の読み取り専用保護が `/workspace` 経由の書き込みには効かないので、起動時に WARNING が出る（後述「セキュリティモデル」節の「ホストの Claude Code 設定の読み取り専用保護」の限界 (1)）。
```

- [ ] **Step 2: README の移行手順 4 を直す**

移行手順の 4 を、次の 1 行に置き換える。

```markdown
4. `.claude`、`.claude/skills` やその各項目 `.claude/skills/<name>`（と、その `.claude-plugin/plugin.json` までの途中の段）、`.claude/settings*.json`、`.mcp.json` を、リポジトリの外を指す symlink や解決できない symlink にしているリポジトリは起動しなくなる。実体をリポジトリ内へ置くか、user 設定（`~/.claude/skills/`）へ移す（`--check` が `[FAIL]` で知らせる）。それより下にある skill のファイル（`SKILL.md` など）の symlink では止まらない。
```

- [ ] **Step 3: C-5 の「限界・非対象」を直す**

`SECURITY-CLAIMS.md` の C-5 の「限界・非対象」で、次の 1 行を置き換える。

置き換え前:

```markdown
- `.claude/skills/` の配下に `/workspace` の外を指す symlink や解決できない symlink があると、判定不能で起動しない。
```

置き換え後（2 項目）:

```markdown
- `.claude/skills` 自体と、各項目 `.claude/skills/<name>` から `.claude-plugin/plugin.json` までのどこかの段が、`/workspace` の外を指す symlink や解決できない symlink だと、判定不能で起動しない。それより下にある skill の他のファイル（`SKILL.md` など）の symlink は辿らず、止めない（本文を審査しないのと同じ扱い）。
- 作業ディレクトリが Claude Code の設定ディレクトリの親（既定ではホームディレクトリ）だと、user 設定（settings と skills）が `/workspace/.claude/` の配下として見え、project 設定として審査される。user 設定での plugin の有効化・`extraKnownMarketplaces`・`CLAUDE_CODE_PLUGIN_*`・skills-directory plugin・外を指す symlink も、確認の前に止める対象や判定不能になる。
```

- [ ] **Step 4: 表記と整合を確かめる**

Run: `git diff --check && grep -c 'それより下にある skill' README.md SECURITY-CLAIMS.md`
Expected: `git diff --check` は出力なし。grep は `README.md:2`、`SECURITY-CLAIMS.md:1`。

読み比べる点: README の 2 項目と C-5 の 2 項目で、止まる条件（`.claude/skills` 自体と `<name>` から `plugin.json` までの段、ホームを作業ディレクトリにしたときの user 設定の停止条件）が食い違っていない。README の他の箇所（171 行の `--check` の説明、691 行の #163 の説明）と矛盾しない。

- [ ] **Step 5: コミット**

```bash
git add README.md SECURITY-CLAIMS.md
git commit -m "docs: project 設定ゲートの審査範囲の限界を README と C-5 に書く（#176）"
```

### Task 5: まとめの検証

**Files:** 変更なし

- [ ] **Step 1: 対象の Python テストをまとめて走らせる**

Run: `for p in 'test_claude_project_*.py' test_codex_launch.py test_codex_entrypoint.py; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "$p" 2>&1 | tail -3; done`
Expected: どれも `OK`。

- [ ] **Step 2: `--launcher-only`**

Run: `./test-build.sh --launcher-only > /tmp/c3c-launcher-174.log 2>&1; echo rc=$?; grep -E 'PASS=|FAIL=' /tmp/c3c-launcher-174.log | tail -2`
Expected: `rc=0`、`FAIL=0`。`TMPDIR` が `/var/tmp` や `/run/user/<uid>` の配下なら `TMPDIR=/tmp` を付ける（README「変更後の確認」節）。

- [ ] **Step 3: 通常モード（ホストの実 Podman・実ビルド）**

`claude-project-audit.py` はイメージに入る境界アセットなので、実イメージの helper を `./test-build.sh`（通常モード）で確かめる（README「変更後の確認」節）。実 Podman と外部ネットワークが要るので、Codex で実装する場合は `not run` として進行役がホストで行う。

Run: `./test-build.sh > /tmp/c3c-full-174.log 2>&1; echo rc=$?; grep -E 'PASS=|FAIL=' /tmp/c3c-full-174.log | tail -2`
Expected: `rc=0`、`FAIL=0`。

---

## PR 本文に書くこと

- closes #174、#175、#176、#177。
- #175 (b) は、通常起動の経路では検査用コンテナが fake なので、`--check` の経路に絞った（helper 単体は既存のテストが確かめている）。(d) の `--check` の `tr -d` は、M6 の原文には無く Issue の完了条件にあったので足した。
- #177 は深層防御の修正である。c3c が書いた記録では挙動は変わらない。ホストで末尾に改行を足した 4096 バイト超の記録だけが、コンテナ内で確認に回るようになる（fail-closed 側）。
- #174 の lint 本体の配線は、偽の provider で lint.sh 全体を走らせる代わりに、呼び出しの 1 行をテストで固定した（理由は計画の前提）。
- `claude-project-audit.py` が変わるので、既存のイメージは `-b` で再ビルドするまで境界アセットのドリフトの WARNING が出る。
- SemVer: CLI 引数・設定形式・既定の挙動は変わらない（#177 で変わるのは、ホストで書き換えた記録の扱いだけ）。タグは提案しない。

---

区分: 境界（`claude-project-audit.py` は `docs/development-invariants.md` が定める境界アセットで、承認記録の読み方を変える。SECURITY-CLAIMS C-5 の保証文も直す。計画・実装完了時（PR 前）・PR 後の 3 段の二重レビュー。4 件を 1 本にまとめるのは、分けると境界の PR と通常の PR でレビューの呼び出しが計 10 回、まとめると 6 回で済むため）
推奨実装: Codex（実装者の判定 1〜3 に当たらない。コンテナ内でしか成立しない作業ではなく、`~/.claude` 配下・hook・秘密の経路にも触れない。文書の文言まで逐語で確定しているので、設計判断も残らない。4 の「host の checkout で完結し、逐語手順と Expected まで確定」に当たる）

## Codex で実装する場合の実行条件

- sandbox: `workspace-write`。外部ネットワークは Task 1〜4 と Task 5 Step 1・2 には不要。ただし、PTY（`pty.openpty`・`TIOCSCTTY`）、`setsid`、loopback の bind（`--launcher-only` の `tests/test_network_timeouts.py`）、`lint.sh` の `podman compose config` は要る。Task 5 Step 3（実 Podman・実ビルド・外部ネットワーク）は Codex では行わず、`not run` として進行役がホストで行う。
- #170 の実装では、sandbox 内で `/run/user/<uid>/libpod` が read-only のため、ComposeContractTests と lint の Compose 検証が失敗した。sandbox の制約（PTY・`setsid`・socket・Podman・`/tmp` の書き込み・`.git` への書き込み）でテストが ERROR になる、Compose 検証がスキップされる、commit が拒否される場合は、該当の名前とエラー文を記録する。そのうえで昇格を求めて sandbox 外で再実行するか、差分を残して報告して止まる。sandbox 由来の失敗やスキップを FAIL=0 や完了と報告しない。
- `/goal` に渡す文面:

  > `docs/superpowers/plans/2026-09-27-issues174-177-gate-followups.md` の計画を、superpowers:executing-plans に従ってブランチ `fix/issues174-177-gate-followups` で Task 1 から順に実装する。Task ごとに 1 コミットにする（計 4 コミット）。Task 1 と Task 3 は red を確かめてから実装し、Task 2 と Task 3 のミューテーション確認は、書き換える前に対象が clean（Task 3 は控えを取る）であることを確かめ、各回の後に戻したことを `git diff --quiet -- <file>`（Task 3 は `cmp`）で確かめる。Task 5 は Step 1・2 を行い、Step 3 は `not run` として進行役に残す。push と PR 作成はしない。実装完了時（PR 前）の二重レビューは進行役が行う。完了時は次を報告して止まる: コミットの一覧、各 red・ミューテーションの結果（FAIL の件数と該当行）、green の件数、lint と `--launcher-only` の rc と実出力の該当行、`not run` にした項目（Compose 検証のスキップ、sandbox 由来の ERROR を含む）とその理由。

## 計画レビューの記録

- 1 巡目（2026-09-27、対象 c30b1a2）:
  - Codex（gpt-6-astra、`codex exec --sandbox read-only`）: 修正後に渡せる。Critical 0・Important 3・Minor 2。
  - Claude（claude-opus-5-5、headless、Read/Grep/Glob）: 実装に渡せる。Critical 0・Important 0・Minor 7。
  - 深刻度が割れたので、重い方（Codex の Important）を暫定で採った。3 件とも実物で確かめ、正しかった。
  - 反映した:
    - Codex の I1: #177 の前提を直した（ホストの `$(cat)` は末尾の改行を無視するので、改行を足した 4096 バイト超の記録は helper に届く。記録は 97 バイト）。この場合を固定するテストを足し、PR 本文と SemVer の根拠を書き直した。
    - Codex の I2: `--check` の `tr -d` を守るテスト (d) と、そのミューテーションを足した。
    - Codex の I3: lint 本体の呼び出しの 1 行を固定する検査と、`|| true` のミューテーションを足した。偽の provider で lint 全体を走らせる方式を採らない理由は、前提に書いた。
    - Codex の M4 と Claude の M4: ミューテーションの前に clean を確かめるようにした。Task 3 は控えから戻して `cmp` で比べる。
    - Codex の M5 と Claude の M1: skills の検査の範囲の文言を直した（`.claude/skills` 自体を含め、「それより下にある skill のファイル」に限る）。
    - Claude の M2（ホームの場合の停止条件を一般化）、M3（除去後の行を完全一致で検査）、M5（テストの冒頭コメント）、M6（行番号）、M7（「`/workspace` 経由では効かない」）。
- 確認限定 1 巡目（2026-09-27、対象 b9534a1）: Codex（新しい `codex exec`、gpt-6-astra、read-only）だけで行った（Important を出したレビュアーのため）。Important 1〜3 と Minor 5 は「直った」、Minor 4 は「一部」で、判定は「修正後に渡せる」。
  - 残った Minor 4（Task 2 のブロックで clean の確認が失敗しても後続へ進む、中断時の復元が手動）を直した。各ミューテーションを `set -e` のサブシェルで行い、clean でなければ書き換えずに止め、`trap` で必ず戻す。リポジトリ外の worktree で逐語どおりに試し、未コミットの変更があると止まって変更が残ること、各回が赤になって `restored` で戻ることを確かめた。
  - 残っていたのは Minor だけなので、確認限定巡を重ねずに実装へ渡す（グローバル指示: 確認限定巡は Critical か Important を出したレビュアーだけで回す）。計画は 1 巡＋確認限定 1 巡で収束した。
