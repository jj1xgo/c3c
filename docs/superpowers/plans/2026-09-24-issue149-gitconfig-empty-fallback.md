# #149 GITCONFIG_FILE 未設定時のフォールバックを空の通常ファイルにする Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GITCONFIG_FILE` 未設定のとき、コンテナ内 `~/.gitconfig` を `/dev/null`（キャラクタデバイス）ではなく、c3c 同梱の空の通常ファイルの `:ro` bind にし、Codex の sandbox（bubblewrap）内で `git` が rc 128 にならないようにする。

**Architecture:** c3c 本体に 0 バイトの `empty.gitconfig` を同梱する。launcher の `guard_gitconfig_file()` が、bind 元のパスを内部変数 `C3C_GITCONFIG_SOURCE` に**無条件に代入して** export する。値は、`GITCONFIG_FILE` が設定されていればそのパス、未設定なら `$RUN_DIR/empty.gitconfig` で、後者は空の通常ファイルであることを確かめ、そうでなければ fail-closed で止める。`compose.yml` はこの変数を `~/.gitconfig` へ `:ro` で bind する。イメージは変えない。

**Tech Stack:** bash（`c3c`・`lint.sh`・`test-build.sh`）、Compose（podman-compose 1.6.0 / CI の provider）、Python unittest（`tests/test_c3c_launch.py`・`tests/test_codex_entrypoint.py`）。

**Spec:** Issue #149（対応案 1）。設計は本計画の Global Constraints を正とする。

**作業場所:** worktree `~/Projects/worktrees/c3c-issue149`、ブランチ `fix/issue149-gitconfig-fallback`（origin/main b83f7f8 起点）。本計画の commit もこのブランチに置く。

## 背景（実測済みの事実）

- `compose.yml:98` は `${GITCONFIG_FILE:-/dev/null}:/home/node/.gitconfig:ro`。未設定時はコンテナ内 `~/.gitconfig` がキャラクタデバイスになる。
- #145 の受入（`docs/codex-proc-investigation.md` の「#145 の受入」）で、`GITCONFIG_FILE` 未設定の fixture では `codex sandbox` 内の `git status --short --branch` が read-only・workspace-write とも rc 128。`GIT_CONFIG_GLOBAL=/dev/null` を与えると rc 0、`GITCONFIG_FILE=~/.gitconfig` 設定時は rc 0。
- #25 の `credential.helper` リセット（`entrypoint.sh:207-214`）は `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0` の環境変数で行い、`~/.gitconfig` の内容に依存しない（git の仕様上、`GIT_CONFIG_*` は全 config ファイルより後に適用される）。空の global 設定との衝突は無い。
- compose の bind 元はホスト側のパスで、イメージ内のファイルは指せない。launcher は既に `CLAUDE_CONTAINER_DIR="$RUN_DIR"` を build・preflight・run の 3 つの compose 呼び出しへ渡している（`c3c:687`・`:1133`・`:1303`）が、それとは別の変数にする（下記 Global Constraints の理由）。
- `compose.yml` は `ASSET_HASH_TARGETS`（`c3c:1914-1937`）に含まれず、イメージにも焼き込まれない。本変更で利用側の `-b` 再ビルドもドリフト WARNING も発生しない。
- `compose.yml` を launcher を通さず直接展開する箇所が複数ある: `lint.sh` の Compose 検証、`test-build.sh:1779`（静的チェック）と `:520-526` 付近（実 compose run）、`tests/test_codex_entrypoint.py:321`（`ComposeContractTests`）、`tests/test-runtime.sh:159`。

## Global Constraints

- 同梱ファイル名は `empty.gitconfig`（リポジトリ直下、0 バイト、通常ファイル、symlink 不可、git 追跡）。先頭を `.` にしない（`tests/test_c3c_launch.py` の `copy_tree_keeping_symlinks` と `tests/test_codex_launch.py` の runner コピーが dotfile を除外するため）。
- 内部変数名は `C3C_GITCONFIG_SOURCE`。`guard_gitconfig_file()` が**無条件に代入**してから export する（`${C3C_GITCONFIG_SOURCE:-...}` のような既存値の継承をしない — ホストのシェル環境に残った値を通さない）。`ENV_FILE_ALLOWED_KEYS`（`c3c:710-725` 付近）には加えない（`.c3c/env` からは設定できず、既存の「解釈しないため無視」WARNING になる）。
- `GITCONFIG_FILE` 自体の意味・既存の検査（未存在・非通常ファイルで停止）と、`c3c:1675` の境界キー INFO（env ファイルの行を見る）は変えない。`GITCONFIG_FILE` を launcher 内部で書き換えてフォールバックを表現しない（境界キー INFO と README の「未設定」の意味が崩れるため）。
- フォールバックの検査: `$RUN_DIR/empty.gitconfig` が symlink でない・通常ファイル・0 バイト、かつ bind 元のパス（`C3C_GITCONFIG_SOURCE` に入れる値。`GITCONFIG_FILE` 設定時はそのパス）にコロン `:` と制御文字を含まない。満たさなければ `guard_fail`（通常起動は停止、`--check` は FAIL 集計）。コロンは compose の短縮 volume 表記を分割するため（`c3c:1581` の前例と同じ判定）。
- `compose.yml` の行は `- ${C3C_GITCONFIG_SOURCE:-/dev/null}:/home/node/.gitconfig:ro`。`:ro` を外さない。既定値 `/dev/null` は launcher を通さない直接展開（lint・test-build・unittest・runtime test）用で、launcher 経由では必ず上書きされることを Task 1 の試験で固定する。`:?` にしない理由: 直接展開する 5 箇所すべてにダミー値の配線が要り、失敗時の帰結も「従来どおりのデバイス bind（読み取り専用のまま）」で安全側だから。
- 変更前に `docs/development-invariants.md` の `c3c`・`compose.yml`・`entrypoint.sh` の項を読む。編集のたびに `./lint.sh` を実行し、終了コード 0・警告ゼロを確認する。
- 挙動を変えたら README.md の該当節を同じ commit で更新する。

## Review Focus

1. **ホスト環境・env ファイルからの注入**: シェルに `C3C_GITCONFIG_SOURCE=/etc/shadow` が export されていても、`.c3c/env` に同じ行があっても、bind 元は launcher の決めた値になる（env ファイルの行には WARNING）。→ Task 1 Step 1 の `test_host_environment_value_is_ignored`・`test_env_file_cannot_set_the_source`。
2. **同梱ファイルの欠落・改変**: 部分的なコピー（`c3c` だけを別の場所へ置く）、内容の追記、symlink への差し替えで、中身のある設定や別ファイルが `~/.gitconfig` になる。→ 停止する（`test_broken_fallback_stops_before_any_container`、`--check` は `test_check_reports_broken_fallback`）。
3. **`GITHUB_MAIN_PAT` あり・`GITCONFIG_FILE` なし**: `credential.helper` のリセットは従来どおり効く（`GIT_CONFIG_*` は `entrypoint.sh` が設定し、本変更は触れない）。→ Task 2 の実機受入の Step 4 で、agent のプロセス木の中から `git config --show-origin --get-all credential.helper` を確認する。
4. **コンテナ内からの書き込み**: `git config --global user.name x` が EROFS 系で失敗し、ホスト側の `empty.gitconfig` が 0 バイトのまま。→ Task 2 の Step 3。
5. **RUN_DIR にコロンを含む配置**: `/opt/c:3c/` のような置き場所で compose が volume を誤分割しない（`GITCONFIG_FILE` 未設定でも起動前に停止する）。これは本変更で新しく生まれる停止条件で、README とリリースノートに書く。→ `test_colon_in_run_dir_stops`（設定した `GITCONFIG_FILE` 側は `test_colon_in_source_path_stops`）。
6. **build・preflight・本起動のすべての compose 呼び出し**: 将来 guard より前に compose 呼び出しが増えても、既定値 `/dev/null` へ黙って戻らない。→ `test_every_compose_call_gets_the_source`。

---

### Task 1: launcher・compose・文書のフォールバックを空ファイルに替える（1 commit）

挙動の変更と README の更新は同じ commit にする（root `AGENTS.md`「挙動を変えたら README.md の該当節も同じコミットで更新する」）。そのため Task 1 は最後の Step でだけ commit する。

**Files:**
- Create: `empty.gitconfig`（0 バイト）
- Modify: `c3c:809-821`（`guard_gitconfig_file()`）
- Modify: `compose.yml:94-98`（コメントと volume 行）
- Modify: `lint.sh`（`compose_mount_is_ro` の対象に `/home/node/.gitconfig` を追加）
- Modify: `test-build.sh:1361`（runner コピー一覧に `empty.gitconfig`）、`test-build.sh` の E3（`compose-env` の検査に 1 行）
- Test: `tests/test_c3c_launch.py`（fake podman の記録キーと新しい試験クラス）
- Modify: `README.md:187`（環境変数表）、`README.md:405-415`（「コンテナ内 git commit（`GITCONFIG_FILE`）」）、`README.md:534`（アーキテクチャ節の同梱ファイル一覧）
- Modify: `docs/development-invariants.md`（`compose.yml` の項と `c3c` の項に 1 項目ずつ）
- Modify: `docs/codex-proc-investigation.md`（`git status` の行の後に #149 での対処を追記）

**Interfaces:**
- Produces: 環境変数 `C3C_GITCONFIG_SOURCE`（launcher → compose）。値は `GITCONFIG_FILE`（展開後の絶対パス）または `$RUN_DIR/empty.gitconfig`。
- Produces: `--check` の出力行 `[OK]   git 設定: GITCONFIG_FILE 未設定（空の <path> を ~/.gitconfig へ :ro で bind）`。

- [ ] **Step 1: 失敗する試験を書く**

`tests/test_c3c_launch.py` の `PODMAN` の記録キー（`'CONTEXT', 'CLAUDE_CONTAINER_DIR', 'ASSET_HASH', 'BASE_IMAGE'` の並び）に `'C3C_GITCONFIG_SOURCE', 'GITCONFIG_FILE'` を足す:

```python
          'env': {k: os.environ.get(k) for k in ('CC_AGENT', 'CC_CODEX_START_MODE', 'CC_CODEX_READ_ONLY',
                                                  'CODEX_MCP_APPROVAL_FILE', 'MCP_APPROVAL_FILE', 'CODEX_DIR',
                                                  'CONTEXT', 'CLAUDE_CONTAINER_DIR', 'ASSET_HASH', 'BASE_IMAGE',
                                                  'C3C_GITCONFIG_SOURCE', 'GITCONFIG_FILE')}}
```

ファイル末尾の `if __name__ == '__main__':` より前に次のクラスを足す（`claude` 経路で起動し、本 run の環境を見る。`run_c3c` と `assert_single_run`・`assert_no_containers` は既存の helper）:

```python
class GitconfigSourceTests(LaunchCase):
    """#149: GITCONFIG_FILE 未設定時の ~/.gitconfig は同梱の空ファイル（:ro）。bind 元は launcher が決める。"""

    def empty(self):
        return self.runner / 'empty.gitconfig'

    def append_env(self, line):
        with (self.conf / 'env').open('a') as handle:
            handle.write(line + '\n')

    def test_repository_ships_an_empty_regular_file(self):
        path = REPO / 'empty.gitconfig'
        self.assertFalse(path.is_symlink())
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_size, 0)

    def test_unset_uses_the_bundled_empty_file(self):
        run = self.assert_single_run(self.run_c3c('claude', str(self.proj)), 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()))
        self.assertIsNone(run['env']['GITCONFIG_FILE'])

    def test_set_uses_the_configured_file(self):
        gitconfig = self.root / 'host.gitconfig'
        gitconfig.write_text('[user]\n\tname = x\n')
        self.append_env(f'GITCONFIG_FILE={gitconfig}')
        run = self.assert_single_run(self.run_c3c('claude', str(self.proj)), 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(gitconfig))

    def test_host_environment_value_is_ignored(self):
        result = self.run_c3c('claude', str(self.proj), env_extra={'C3C_GITCONFIG_SOURCE': '/etc/shadow'})
        run = self.assert_single_run(result, 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()))

    def test_env_file_cannot_set_the_source(self):
        self.append_env('C3C_GITCONFIG_SOURCE=/etc/shadow')
        result = self.run_c3c('claude', str(self.proj))
        run = self.assert_single_run(result, 'claude')
        self.assertEqual(run['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()))
        self.assertIn('解釈しないため無視', result.stderr)

    def test_broken_fallback_stops_before_any_container(self):
        target = self.root / 'other.gitconfig'
        target.write_text('')
        for label, breaker in (('nonempty', lambda p: p.write_text('[credential]\n\thelper = store\n')),
                               ('symlink', lambda p: (p.unlink(), p.symlink_to(target))),
                               ('missing', lambda p: p.unlink()),
                               ('directory', lambda p: (p.unlink(), p.mkdir()))):
            with self.subTest(label=label):
                path = self.empty()
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                elif path.exists() or path.is_symlink():
                    path.unlink()
                path.write_text('')
                breaker(path)
                result = self.run_c3c('claude', str(self.proj))
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('empty.gitconfig', result.stderr)
                self.assert_no_containers()

    def test_check_reports_broken_fallback(self):
        self.empty().write_text('x\n')
        result = self.run_c3c('--check', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('empty.gitconfig', result.stdout + result.stderr)
        self.assert_no_containers()

    def test_check_reports_the_fallback(self):
        result = self.run_c3c('--check', str(self.proj))
        self.assertIn('git 設定: GITCONFIG_FILE 未設定', result.stdout)

    def test_colon_in_source_path_stops(self):
        gitconfig = self.root / 'a:b.gitconfig'
        gitconfig.write_text('')
        self.append_env(f'GITCONFIG_FILE={gitconfig}')
        result = self.run_c3c('claude', str(self.proj))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('コロン', result.stderr)
        self.assert_no_containers()

    def test_colon_in_run_dir_stops(self):
        # GITCONFIG_FILE 未設定のまま、c3c の置き場所（RUN_DIR）にコロンを含める。
        colon_runner = self.root / 'a:b'
        colon_runner.mkdir()
        copy_tree_keeping_symlinks(REPO, colon_runner)
        result = self.run_entry(colon_runner / 'c3c', 'claude', str(self.proj))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('コロン', result.stderr)
        self.assert_no_containers()

    def test_every_compose_call_gets_the_source(self):
        # 明示ビルド → Codex の preflight → 本起動の 3 種すべてに同じ bind 元が渡る。
        self.state['image_exists'] = False
        self.approve_codex()
        result = self.run_c3c('codex', '-b', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.compose_calls('build')), 1)
        self.assertEqual(len(self.preflight_calls()), 1)
        self.assertEqual(len(self.main_runs()), 1)
        for call in self.compose_calls():
            self.assertEqual(call['env']['C3C_GITCONFIG_SOURCE'], str(self.empty()), call['args'])
```

`test_every_compose_call_gets_the_source` の呼び出し形（`codex -b <dir>`）が parser に合わない場合は、既存の `-b` 試験（`grep -n "'-b'" tests/test_c3c_launch.py`）と Codex 経路の試験（`approve_codex()` の使用箇所）の形に合わせる。fake podman の build は `state['label'] = state.get('build_label', '2')` を立てるので、ビルド後の label 検査は通る。

注意: `run_c3c('claude', ...)` の初回で CLI 選択の記憶が作られる挙動は既存の `EntryResolutionTests` と同じ。既存の試験が `claude` を明示して単一 run を得ている形（`assert_run_dir`）に合わせている。`--check` の呼び出し形が既存の試験と違う場合は、既存の `--check` 試験（`grep -n "'--check'" tests/test_c3c_launch.py`）の形に合わせる。

- [ ] **Step 2: 失敗を確かめる**

Run: `python3 -m unittest tests.test_c3c_launch.GitconfigSourceTests -v`
Expected: `test_repository_ships_an_empty_regular_file` が FAIL（ファイルが無い）、`test_unset_uses_the_bundled_empty_file` などが FAIL（`C3C_GITCONFIG_SOURCE` が None）。

- [ ] **Step 3: 空ファイルと guard を実装する**

```bash
: > empty.gitconfig
```

`c3c` の `guard_gitconfig_file()`（現 809-821 行）を次に置き換える（コメントも更新）:

```bash
# ホスト側 git 設定ファイルの参照（GITCONFIG_FILE）と、~/.gitconfig の bind 元の決定（#149）。
# 設定済みでファイルが無い場合は起動を中止する（不存在パスを bind mount すると podman が
# ホスト側に空ディレクトリを誤作成し、コンテナ内 ~/.gitconfig もディレクトリになって
# git が壊れるため）。未設定時は同梱の空ファイル $RUN_DIR/empty.gitconfig を bind 元にする
# （/dev/null の bind はキャラクタデバイスになり、Codex の sandbox 内で git が rc 128 になる）。
# C3C_GITCONFIG_SOURCE は無条件に代入する（ホスト環境の同名変数を継承しない。.c3c/env の
# 許可キーにも入れない）。compose.yml の既定値 /dev/null は launcher を通さない直接展開用。
guard_gitconfig_file() {
  local fallback="$RUN_DIR/empty.gitconfig"
  C3C_GITCONFIG_SOURCE=""
  if [[ -n "${GITCONFIG_FILE:-}" ]]; then
    GITCONFIG_FILE="${GITCONFIG_FILE/#\~\//$HOME/}"
    export GITCONFIG_FILE
    if [[ ! -f "$GITCONFIG_FILE" ]]; then
      guard_fail "ERROR: GITCONFIG_FILE=$GITCONFIG_FILE が見つかりません(存在しないか通常ファイルではありません)。起動を中止します。" || return 1
    fi
    C3C_GITCONFIG_SOURCE="$GITCONFIG_FILE"
  else
    if [[ -L "$fallback" || ! -f "$fallback" || -s "$fallback" ]]; then
      guard_fail "ERROR: 同梱の $fallback が 0 バイトの通常ファイルではありません（欠落・内容あり・symlink）。c3c の checkout を git で復元してください。起動を中止します。" || return 1
    fi
    C3C_GITCONFIG_SOURCE="$fallback"
  fi
  if [[ "$C3C_GITCONFIG_SOURCE" == *:* || "$C3C_GITCONFIG_SOURCE" =~ [[:cntrl:]] ]]; then
    guard_fail "ERROR: ~/.gitconfig の bind 元 $C3C_GITCONFIG_SOURCE にコロンか制御文字が含まれます（compose の volume 指定を分割するため使えません）。起動を中止します。" || return 1
  fi
  export C3C_GITCONFIG_SOURCE
  if [[ ${CHECK_MODE:-0} -eq 1 && -z "${GITCONFIG_FILE:-}" ]]; then
    echo "[OK]   git 設定: GITCONFIG_FILE 未設定（空の $C3C_GITCONFIG_SOURCE を ~/.gitconfig へ :ro で bind）"
  fi
}
```

- [ ] **Step 4: compose.yml を書き換える**

`compose.yml:94-98` を次にする:

```yaml
      # ホスト側 git 設定のオプトインマウント（issue #6: Author identity unknown 対策）。
      # bind 元は launcher の guard_gitconfig_file() が C3C_GITCONFIG_SOURCE に export する:
      # GITCONFIG_FILE 設定時はそのファイル、未設定時は同梱の空ファイル empty.gitconfig（#149。
      # /dev/null のデバイスだと Codex の sandbox 内で git が読めない）。既定値 /dev/null は
      # launcher を通さない直接展開（lint・試験）用。
      # :ro 必須 — コンテナ内から credential.helper 等を書き換えられるとホスト側
      # 任意コマンド実行につながるため。entrypoint.sh 側の処理は不要（git が直接読む）。
      - ${C3C_GITCONFIG_SOURCE:-/dev/null}:/home/node/.gitconfig:ro
```

- [ ] **Step 5: lint と test-build を合わせる**

`lint.sh` の `for target in /etc/claude-container/codex-mcp-approved.json /etc/claude-container/mcp-approved-hash; do` を次にする:

```bash
    for target in /etc/claude-container/codex-mcp-approved.json /etc/claude-container/mcp-approved-hash /home/node/.gitconfig; do
```

`test-build.sh:1361` の `cp -- "${SCRIPT_DIR}/"{c3c,agent-preference.py,...,codex-version.txt}` の波括弧内の末尾に `,empty.gitconfig` を足す（足さないと隔離 runner で guard が停止し、C0 以降が全部赤になる）。

`test-build.sh` の E3（`check "E3: 許可キーには WARNING が出ない" ...` の直後、`printf '%s\n' "$out" >> "$LOG_FILE"` の前）に、許可キーとは別の検査として次を足す（`C3C_GITCONFIG_SOURCE` は許可キーではないので E3 の件数に混ぜない）:

```bash
  check "E3b: GITCONFIG_FILE 設定時は ~/.gitconfig の bind 元がそのファイルになる" \
    grep -qxF "C3C_GITCONFIG_SOURCE=$e_gitcfg" "$root/compose-env"
```

- [ ] **Step 6: 試験を通す**

Run: `python3 -m unittest tests.test_c3c_launch -v 2>&1 | tail -5`
Expected: `OK`（新クラス 11 件を含む）。

Run: `python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK`（`test_codex_launch.py` の runner コピーは dotfile 以外を全部コピーするので `empty.gitconfig` も入る）。

Run: `./lint.sh; echo rc=$?`
Expected: `rc=0`、警告なし。

Run: `./test-build.sh --launcher-only 2>&1 | tail -3`
Expected: FAIL 0。

- [ ] **Step 7: 修正前に戻して試験が赤になることを確かめる**

stash は他の worktree・セッションと共有されるので使わない。変更後のファイルを一時ディレクトリへ退避し、HEAD の版に戻して試験してから書き戻す:

```bash
keep=$(mktemp -d) && cp c3c compose.yml "$keep/" \
  && git checkout HEAD -- c3c compose.yml \
  && { python3 -m unittest tests.test_c3c_launch.GitconfigSourceTests 2>&1 | tail -3; } ; \
  cp "$keep/c3c" "$keep/compose.yml" . && rm -r "$keep" && git diff --stat -- c3c compose.yml
```

Expected: 退避中は FAIL/ERROR が出る（`empty.gitconfig` は残るので、ファイル検査の 1 件だけは通ってよい）。最後の `git diff --stat` に `c3c` と `compose.yml` の変更が戻っていることを確かめ、Step 6 を再実行して OK。

ここではまだ commit しない（Step 14 で文書と一緒に commit する）。

- [ ] **Step 8: README の表**

`README.md:187` の説明列を次にする:

```
| `GITCONFIG_FILE` | (unset) | コンテナ内 `~/.gitconfig` として read-only マウントするホスト側 git 設定ファイルのパス。未設定なら c3c 同梱の空ファイルを read-only マウントする（後述） |
```

- [ ] **Step 9: README の本文**

`README.md` の「未設定なら従来どおり（`git commit` が `Author identity unknown` で失敗するだけで、他への影響はない）」の箇条を次にする:

```
- 未設定なら、c3c 同梱の空ファイル `empty.gitconfig` を `~/.gitconfig` として read-only マウントする（`git commit` が `Author identity unknown` で失敗するだけで、他への影響はない）。以前は `/dev/null` をマウントしており、Codex の sandbox 内では `~/.gitconfig` を読めず `git` が rc 128 で失敗していた（#149）。`empty.gitconfig` が欠けている・中身がある・symlink になっている場合は起動時に停止するので、c3c の checkout を git で復元する。c3c の置き場所と `GITCONFIG_FILE` のパスには、コロン・制御文字を含めない（compose の volume 指定を分割するため起動時に停止する）
```

同じ箇条群の「read-only マウントのため…」の箇条は、未設定時にも当てはまるので「read-only マウントのため（未設定時の空ファイルも同じ）…」とする。

`README.md:534` のアーキテクチャ節の同梱ファイル一覧（`packages.txt` … の項）の直後に 1 項目足す:

```
- **`empty.gitconfig`** — 0 バイトの空ファイル。`GITCONFIG_FILE` 未設定時に `c3c` が `~/.gitconfig` の bind 元にする（read-only。前述「コンテナ内 git commit（`GITCONFIG_FILE`）」）。中身を書かない。
```

- [ ] **Step 10: 不変条件**

`docs/development-invariants.md` の `compose.yml` の項（`${CODEX_DIR:-/dev/null}` の項目の直前）に足す:

```
  - `~/.gitconfig` の bind（`${C3C_GITCONFIG_SOURCE:-/dev/null}:/home/node/.gitconfig:ro`）は `:ro` 必須（コンテナ内から `credential.helper` 等を書けるとホスト側の任意コマンド実行につながる）。bind 元は launcher の `guard_gitconfig_file()` が決め、未設定時は同梱の 0 バイトの `empty.gitconfig`（#149）。`/dev/null` へ戻さない — キャラクタデバイスになり、Codex の sandbox 内で git が読めない。既定値 `/dev/null` は launcher を通さない直接展開用に限る。フォールバックの完全性は RUN_DIR にコンテナから書けないことに依存する（c3c 自身をセルフホストで開発するときは `/workspace` が RUN_DIR になり書ける。bind は inode を共有するので、ホスト側での書き換えは稼働中のコンテナにも即座に及ぶ）。
```

`c3c` の項に足す:

```
  - `guard_gitconfig_file()` は `C3C_GITCONFIG_SOURCE` を無条件に代入して export する（ホスト環境の同名変数を継承しない）。`ENV_FILE_ALLOWED_KEYS` に加えない。未設定時の `$RUN_DIR/empty.gitconfig` は symlink でない 0 バイトの通常ファイルであることを確かめ、そうでなければ停止する。bind 元のコロン・制御文字も停止する。`GITCONFIG_FILE` を内部で書き換えてフォールバックを表さない（`.c3c/env` の境界キー INFO と README の「未設定」の意味が崩れる）。
```

- [ ] **Step 11: 調査記録**

`docs/codex-proc-investigation.md` の表の後（「コンテナ側では、非特権の `iptables -S` が拒否され」の段落の前）に次の段落を足す:

```
`git status` の rc 128 は #149 で対処した。`GITCONFIG_FILE` 未設定時の bind 元を c3c 同梱の空ファイル（`empty.gitconfig`、`:ro`）にし、`~/.gitconfig` が通常ファイルになるようにした。対処後の実測は `docs/superpowers/plans/2026-09-24-issue149-gitconfig-empty-fallback.md` の末尾に記録する。
```

- [ ] **Step 12: README の表の検査（E7）が緑のままか**

`C3C_GITCONFIG_SOURCE` は README の環境変数表に足さない（許可キーではないため）。Run: `./test-build.sh --launcher-only 2>&1 | grep -E 'E7|FAIL' | head`
Expected: E7 が PASS、FAIL 0。

- [ ] **Step 13: lint と試験の再実行**

Run: `./lint.sh; echo rc=$?` と `python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: `rc=0`・警告なし、`OK`。

- [ ] **Step 14: Commit**

```bash
git add empty.gitconfig c3c compose.yml lint.sh test-build.sh tests/test_c3c_launch.py \
  README.md docs/development-invariants.md docs/codex-proc-investigation.md
git commit -m "fix: #149 GITCONFIG_FILE 未設定時の ~/.gitconfig を同梱の空ファイルの :ro bind にする"
```

### Task 2: 実機受入（host、Podman）

コンテナの実起動が要る。fixture は #145 の受入と同じ作り（`GITCONFIG_FILE` 未設定、Codex 導入済みのイメージ）を使う。Codex の認証は不要（`codex sandbox` の診断は #145 の受入と同じ方法で、`podman exec` から Codex と同じ PATH・同じ `setpriv` の剥奪で実行する。手順は `docs/codex-proc-investigation.md` の「sandbox の診断」段落）。

- [ ] **Step 1: 再ビルド不要の確認**

Run: `./c3c --check --agent codex <fixture>`
Expected: `[OK]   git 設定: GITCONFIG_FILE 未設定（空の …/empty.gitconfig を ~/.gitconfig へ :ro で bind）`。境界アセットのドリフト WARNING が本変更で新たに出ない（`compose.yml` は `ASSET_HASH` の対象外）。

- [ ] **Step 2: Codex sandbox 内の git（主目的）**

fixture のコンテナを起動し、コンテナ内で `stat -c %F ~/.gitconfig` が `regular empty file` であること。`codex sandbox`（read-only と workspace-write）で `git status --short --branch` を実行し、両方 rc 0。

- [ ] **Step 3: 書き込み不可**

コンテナ内で `git config --global user.name x; echo rc=$?` が非 0（`could not lock config file` など）。ホスト側で `stat -c %s <c3c>/empty.gitconfig` が `0`。

- [ ] **Step 4: `GITHUB_MAIN_PAT` と #25**

`GIT_CONFIG_*` は `entrypoint.sh` が entrypoint のプロセスの中で export するので、`podman exec` のシェルには無い。この確認は **agent のプロセス木の中**（`c3c claude <fixture>` の Claude セッションで Bash ツールから実行）で行う。

1. `SECRETS_DIR` に `GITHUB_MAIN_PAT`（ダミー値でよい）を置き、`GITCONFIG_FILE` は未設定の fixture: `git config --show-origin --get-all credential.helper` の出力が `command line:` 由来の空値 1 件だけ。
2. 同じ fixture で `GITCONFIG_FILE` に `[credential]\n\thelper = store` を書いた専用ファイルを指定: 出力が「`file:/home/node/.gitconfig` の `store` 1 件」＋「`command line:` の空値 1 件」の順（空値が後に来て helper のリストをリセットする。#25 の回帰確認）。

- [ ] **Step 5: `GITCONFIG_FILE` 設定時と Claude 経路の不変**

`GITCONFIG_FILE=~/.gitconfig` を設定した fixture で、コンテナ内 `git config --global user.name` がホストの値を返す。`c3c claude <fixture>` でも Step 2 の `stat` と Step 3 の書込不可が同じ結果になる。

- [ ] **Step 6: 結果を計画末尾に記録して commit**

本計画の末尾に「実機受入の結果（日付、commit、image ID、各 Step の実測）」を追記する。

```bash
git add docs/superpowers/plans/2026-09-24-issue149-gitconfig-empty-fallback.md
git commit -m "docs: #149 の実機受入を記録する"
```

## 完了条件

- Task 1 の試験・`./lint.sh`・`python3 -m unittest discover -s tests -p 'test_*.py'`・`./test-build.sh --launcher-only` がすべて成功。
- Task 2 の Step 2 で両モード rc 0。
- `./test-build.sh`（全体）: 実行する。実行できない部分は理由とともに not run と書く。
- SemVer: 利用者から見える既定挙動（未設定時の `~/.gitconfig` の実体）が変わるが後方互換なバグ修正で、利用側の移行作業は無い（再ビルド不要）。PATCH（v14.0.1）を提案する。リリースノートには、c3c の置き場所にコロンを含む場合と、`c3c` だけを別の場所へコピーして使う場合に起動が止まるようになったことを書く。

---

## 計画レビュー（1 巡目、7b07c62）

- Codex（gpt-6-astra、`codex exec --sandbox read-only`）: 修正後に渡せる。Important 1（挙動変更と README が別 commit になる手順）、Minor 2（build・preflight の export を試験していない、RUN_DIR のコロンを試験していない）。すべて反映した。
- Claude（claude-opus-5-5、headless `claude -p`、Read/Grep/Glob のみ）: 修正後に渡せる。Important 2（共有 stash を push/pop する手順、`podman exec` からは #25 の `GIT_CONFIG_*` が見えない受入手順）、Minor 6。Minor は M-1〜M-5 を反映した。M-6（`test-runtime.sh` で実マウントを検査する）は採らない: 実マウントの挙動は Task 2 の実機受入で確かめ、runtime test の compose 環境の配線を増やすほどの回帰リスクが無いため。

## 計画レビュー（確認限定巡、fbce603）

- Codex（gpt-6-astra、read-only）: Important 1・Minor 2 すべて解消、新たな破損なし。実装に渡せる。
- Claude（claude-opus-5-5、headless、1 巡目の会話を `--resume`）: Important 2・Minor 5 すべて解消、新たな破損なし。実装に渡せる。`codex -b <dir>` の呼び出し形は未確認（Task 1 に合わせ方の指示あり）。

区分: 境界 — `compose.yml` のマウント（`:ro` 保護の対象）と launcher の bind 元の決定という、`docs/development-invariants.md` に載る境界機構を変えるため。計画・実装完了時（PR 前）・PR 後の 3 段階で Claude と Codex の二重レビューを行う。

推奨実装: Opus — `compose.yml:96-97` のとおりこの `:ro` はホスト側の任意コマンド実行を防ぐセキュリティ境界で、グローバル指示の「セキュリティ境界を含むときは Opus」に当たる。Task 2 はコンテナの実起動を伴う（判定基準 1 で Claude）。Sonnet は境界変更のため推さない。Codex は host の checkout で完結せず、Task 2 の実機受入を担えないため推さない。

実装: Opus（持ち主指定。2026-09-24「このまま #149 を進めて」。実行方法は executing-plans）

## 実機受入の結果（Task 2）

2026-09-24、ホスト（x86_64、Podman 5.8.6）で、commit `eba50b7` の c3c を使って確認した。fixture は新しく作った隔離プロジェクト（git リポジトリ。`.c3c/env` は Codex 専用の空の `CODEX_DIR` だけで、`GITCONFIG_FILE` は未設定）。`c3c codex -b` でビルドしたイメージは `98f9df4ab59c`、Codex は 0.156.0。持ち主の Codex 認証とホストの実 `~/.codex` は使っていない。

| Step | 実測 |
| --- | --- |
| 1 `--check` | `[OK]   git 設定: GITCONFIG_FILE 未設定（空の <c3c>/empty.gitconfig を ~/.gitconfig へ :ro で bind）`。WARN は fixture の `CODEX_DIR` のパーミッションだけ（700 にして解消）。イメージが未ビルドだったので、ドリフトの WARNING は出ない |
| 2 Codex sandbox 内の git | コンテナ内の `stat -c %F ~/.gitconfig` は `regular empty file`。`podman inspect` の bind 元は `<c3c>/empty.gitconfig`、`RW=false`。#145 と同じ方法（Codex プロセスと同じ PATH、`setpriv --ambient-caps=-all --inh-caps=-all`）で `codex sandbox -c sandbox_mode=…` を実行した。`git status --short --branch` は、read-only と workspace-write のどちらも rc 0（`## master`）。sandbox 内でも `~/.gitconfig` は `regular empty file` |
| 3 書き込み不可 | `git config --global user.name x` は rc 4（`could not write config file … Device or resource busy`）。追記は `Read-only file system`。ホスト側の `empty.gitconfig` は 0 バイトのまま |
| 4 `GITHUB_MAIN_PAT` と #25 | `SECRETS_DIR/GITHUB_MAIN_PAT`（ダミー値）を置いた。agent（Codex）プロセスの `/proc/<pid>/environ` にある `GIT_CONFIG_COUNT=1`・`GIT_CONFIG_KEY_0=credential.helper`・`GIT_CONFIG_VALUE_0=`（空）を、`podman exec` で同じ値のまま与えて確かめた（agent のプロセス木で直接実行したのではなく、その環境を再現したもの）。(1) `GITCONFIG_FILE` 未設定: `git config --show-origin --get-all credential.helper` は `command line:` の空値 1 件だけ。(2) `helper = store` を書いた専用ファイルを `GITCONFIG_FILE` に指定: `file:/home/node/.gitconfig	store` の後に `command line:` の空値の順（リセットが効く） |
| 5 設定時と Claude 経路 | `GITCONFIG_FILE=~/.gitconfig`: コンテナ内の `git config --global user.name` はホストの値を返した。bind 元はホストの `~/.gitconfig`、`RW=false`。`c3c claude`（PTY 付きで起動し、プロンプトは送っていない。`CC_AGENT=claude`）で `GITCONFIG_FILE` を未設定にした場合: `~/.gitconfig` は `regular empty file 0`、書き込みは rc 4、bind 元は `empty.gitconfig`、`RW=false`、ホスト側は 0 バイトのまま |

補足: 最初の `./test-build.sh --launcher-only` で 1 件だけ FAIL した（`build と run に共有・スキル・plugin・IPv6 の override が共存する`）。ログでは、`-b` の中で GitHub meta を取りに行ったときの HTTP 403 が原因だった。直後の `api.github.com/meta` は 200 を返し、再実行では PASS=311・FAIL=0 になった。
