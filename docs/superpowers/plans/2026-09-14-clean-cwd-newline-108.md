# 削除済み `--clean` の cwd 連結で末尾改行を保持する計画（#108）

> 実行担当: Codex（host の checkout で `/goal` に渡す。末尾「実装者」参照）。編集対象は `claude-container`・`test-build.sh`・`README.md` の 3 ファイルで、置換文と Expected は逐語で確定しており、実装中に設計判断は残らない。

**目的:** PR #107（#54）で入った削除済みプロジェクトの `--clean` が、cwd の末尾が改行のディレクトリから相対名を渡されたときに改行を落とし、起動台帳の別エントリに一致して別プロジェクトを清掃する欠陥（fail-open）を直す。同じレビューで出た nit 2 件（`--check` の「台帳を手動編集」案内、先頭 `//` 綴りの README 注記）を同じ PR に含める。

**構成:** `resolve_project_directory()` の相対引数の連結に使う `$(pwd -L)` を `$PWD` に置き換える。コマンド置換は出力末尾の改行を落とすが、変数 `PWD` は落とさないため、直後の改行拒否（`[[ "$candidate" != *$'\n'* ]]`）に落ちる。bash は起動時に環境の `PWD` が cwd を指すか照合し、指さなければ `getcwd()` で設定し直すため、この時点（スクリプトがまだ `cd` していない）では `$PWD` と `pwd -L` の出力は末尾改行の有無を除いて同じ。

**根拠（1 次情報、2026-09-14 に host で実測）:**

- 再現: `S=/tmp/b2test; mkdir -p "$S/b2/base"$'\n'`、台帳に `$S/b2/base/child` を 1 行書き、`cd "$S/b2/base"$'\n' && claude-container --clean child` → `INFO: 削除済みディレクトリを起動台帳のパスで清掃します: .../b2/base/child`、`PROJECT: child-f677a144`、rc=0、台帳から当該行が消える（ダミー podman）。
- 修正後（`$(pwd -L)` を `$PWD` にした複製で実測）: 同じ手順が `ERROR: ディレクトリが存在せず、起動台帳で対象を確認できません: child`、rc=1、台帳不変。通常の相対ケース `cd "$S/b2/base" && claude-container --clean ./child/` は従来どおり `INFO:` と清掃、rc=0。`env -i` で `PWD` を渡さない起動でも同じ（bash が起動時に設定する）。
- `//`: `cd //tmp && pwd -L` は `//tmp`、`realpath -ms //tmp` は `/tmp`。削除後の照合は台帳不一致で拒否される（fail-closed）。
- 計画の dry run（2026-09-14、`e4290dc` の使い捨て worktree に Task 1〜3 を逐語で適用、Fable が実測）: Task 1 後の `--launcher-only` は新規 check が `[FAIL]` で `PASS=198 FAIL=1`。Task 2 後は `PASS=199 FAIL=0`（relative・logical_cwd・logical_parent の 12 件も `[PASS]`）。Task 3 後に `lint.sh` rc=0、`--launcher-only` `PASS=199 FAIL=0`、`--validator-only` `PASS=82 FAIL=0`、`git diff --check` 出力なし、`git status --short` は 3 ファイルのみ、`grep 手動編集` は出力なし、台帳だけにあるパスの `--check` が新しい案内文を表示。
- Issue: [jj1xgo/claude-container#108](https://github.com/jj1xgo/claude-container/issues/108)。レビュー記録: https://github.com/jj1xgo/claude-container/pull/107#issuecomment-5656732969

## 共通条件

- 文書・メッセージは日本語のみ（README「表記」節）。
- 編集するのは `claude-container`・`test-build.sh`・`README.md` だけ。計画ファイル自身と他のファイルは変更しない。
- 置換は下記の逐語テキストどおりに行う。語句を改善しない。行番号は `main` の `e4290dc` 時点のもので、目印にはなるが照合は旧文で行う。
- テストの合格条件は `FAIL=0` で書く。PASS 件数は実測値を PR 本文に記録する（見込みは 199 = 198 + 1 だが固定で書かない）。
- `.claude/` 配下は手で編集しない（`test-build.sh` が `.claude/test-results/` にログを書くのは想定内で、ops リポジトリの `.gitignore` 済み）。`.build-context/` にテストが残す生成物はテスト自身が片付ける（残っていれば `git status` に出ないことを確認するだけでよい）。

## Task 1: 回帰テスト（赤）

対象: `test-build.sh` の `run_missing_directory_launcher_tests()`（721〜804 行）。`for kind in ...; do ... done` ループの閉じ `done`（801 行）と `proj="$original_proj"`（802 行）の間に挿入する。

- [ ] 次の 10 行を、`  done`（801 行、ループの閉じ）の直後・`  proj="$original_proj"` の直前に挿入する。

  ```bash
  # cwd の末尾改行をコマンド置換が落とすと、台帳の改行なしの別エントリに一致して誤対象を清掃する（#108）。
  mkdir -p "$root/nl"$'\n'
  printf '%s\n' "$root/nl/victim" >> "$ledger"
  cp "$ledger" "$root/ledger-before-nl"
  rm -f "$home/podman-args"
  out=$(cd "$root/nl"$'\n' && env -i HOME="$home" PATH="$bin:$PATH" PWD="$PWD" \
    "${SCRIPT_DIR}/claude-container" --clean victim 2>&1) && rc=0 || rc=$?
  check "cwd 末尾の改行を落として台帳の別エントリを清掃しない" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/podman-args" ] && cmp -s "$4" "$5"' _ "$rc" "$out" "$home" "$ledger" "$root/ledger-before-nl"
  printf '%s\n' "$out" >> "$LOG_FILE"
  ```

  挿入後の並びは次のとおり（前後 1 行ずつ）:

  ```bash
    printf '%s\n' "$out" >> "$LOG_FILE"
  done
  # cwd の末尾改行をコマンド置換が落とすと、台帳の改行なしの別エントリに一致して誤対象を清掃する（#108）。
  ...（上の 10 行）...
  printf '%s\n' "$out" >> "$LOG_FILE"
  proj="$original_proj"
  launcher_sandbox_cleanup
  ```

- [ ] 赤を確認する。

  Run: `bash test-build.sh --launcher-only 2>&1 | grep -E 'cwd 末尾の改行|結果:'`
  Expected: `  cwd 末尾の改行を落として台帳の別エントリを清掃しない[FAIL]` と `結果: PASS=198  FAIL=1`（修正前は `INFO:` を出して rc=0 で清掃を始め、`$home/podman-args` が作られ台帳から `victim` の行が消えるため落ちる）。

## Task 2: 修正（緑）

対象: `claude-container` の `resolve_project_directory()`（198〜221 行）。

- [ ] 208 行目を置き換える。

  旧（1 行）:

  ```bash
      [[ "$candidate" == /* ]] || candidate="$(pwd -L)/$candidate"
  ```

  新（1 行）:

  ```bash
      [[ "$candidate" == /* ]] || candidate="$PWD/$candidate"
  ```

- [ ] 直前の関数コメント（197 行目）を置き換える。

  旧（1 行）:

  ```bash
  # 相対引数は論理 cwd に連結してから正規化する（realpath に直接渡すと物理 cwd になる）。
  ```

  新（2 行）:

  ```bash
  # 相対引数は論理 cwd に連結してから正規化する（realpath に直接渡すと物理 cwd になる）。
  # 連結には $(pwd -L) でなく $PWD を使う — コマンド置換は末尾の改行を落とし、改行拒否をすり抜ける（#108）。
  ```

- [ ] 緑を確認する。

  Run: `bash test-build.sh --launcher-only 2>&1 | grep -E 'cwd 末尾の改行|relative:|logical_cwd:|logical_parent:|結果:'`
  Expected: `  cwd 末尾の改行を落として台帳の別エントリを清掃しない[PASS]`、`relative:`・`logical_cwd:`・`logical_parent:` の 3 種 × 4 件 = 12 行がすべて `[PASS]`（既存の相対ケースの退行なし）、`結果: PASS=<実測>  FAIL=0`。

## Task 3: nit 2 件（`--check` の案内、README の `//` 注記）

対象: `claude-container` の `check_one_project()`（1185 行）、`README.md`（57 行）。

- [ ] `claude-container` 1185 行目を置き換える。

  旧（1 行）:

  ```bash
        echo "  (起動台帳に記録がありますが実体が見つかりません。不要なら $CC_LEDGER_FILE を手動編集してください)"
  ```

  新（1 行）:

  ```bash
        echo "  (起動台帳に記録がありますが実体が見つかりません。不要なら --clean にこの絶対パスを指定すると台帳ごと清掃できます: $dir)"
  ```

  補足: この分岐は `from_ledger=1`（台帳から読んだエントリ）のときだけ通り、`$dir` は台帳の 1 行（`pwd -L` で記録した絶対パス）そのもの。#54 で `--clean` がその綴りを完全一致で受け付けるようになったため、手動編集でなくこちらへ案内する。

- [ ] `README.md` 57 行目の文「シンボリックリンクの綴りは起動時と同じものを使う（リンク先の実体パスとは別プロジェクト扱い）。」の直後に、次の 1 文を挿入する（同じ段落内、改行しない）。

  挿入文:

  ```
  先頭が `//` の綴りで起動したプロジェクトは対象外（bash は先頭の `//` を保持し `realpath` は `/` に畳むため、削除後の照合が一致せずエラーで停止する）。
  ```

  挿入後（該当部分のみ）:

  ```
  ...シンボリックリンクの綴りは起動時と同じものを使う（リンク先の実体パスとは別プロジェクト扱い）。先頭が `//` の綴りで起動したプロジェクトは対象外（bash は先頭の `//` を保持し `realpath` は `/` に畳むため、削除後の照合が一致せずエラーで停止する）。台帳にない削除済みパスや、...
  ```

- [ ] 案内文の変更で既存テストが落ちないことを確認する。

  Run: `grep -n '手動編集' claude-container test-build.sh README.md`
  Expected: 出力なし（旧文言への依存が残っていない）。

## 検証

- [ ] `bash lint.sh` — Expected: 終了コード 0、かつ stderr に `WARNING: LINT_SKIP_COMPOSE=1 のため compose config 検証をスキップしました。` が**出ていない**こと（`LINT_SKIP_COMPOSE` を設定せず host の podman で compose config まで通す。出ていたら compose 検証が未実施なので合格にしない）。
- [ ] `bash test-build.sh --launcher-only` — Expected: `FAIL=0`。PASS の実測値を PR 本文に書く。
- [ ] `bash test-build.sh --validator-only` — Expected: `FAIL=0`。
- [ ] `bash examples/hooks/tests/test-block-pr-approve.sh` — Expected: 全ケース成功（上の 3 つと合わせて CI の `ci.yml` が回す検査と同じ範囲になる）。
- [ ] `git diff --check` — Expected: 出力なし。
- [ ] `git status --short` — Expected: 変更が `claude-container`・`test-build.sh`・`README.md` の 3 ファイルだけ（計画ファイルはブランチにコミット済みなので出ない）。`.build-context/` 配下の生成物が残っていれば `rm -rf .build-context/*` で消してよい（gitignore 済み）。

## コミットと PR

- 実装は 1 コミット（Task 1〜3 をまとめる）。`claude-review` の指摘対応が生じたら別コミットにする（amend しない。PR #107 の d38a2f5 + 756571c と同じ形）。メッセージ:

  ```
  fix: 削除済み --clean の cwd 連結を $PWD にして末尾改行を保持する（#108）

  $(pwd -L) のコマンド置換が cwd 末尾の改行を落とし、改行拒否をすり抜けて
  起動台帳の改行なしの別エントリに一致し、別プロジェクトを清掃していた。
  $PWD は改行を保持するため既存の改行拒否に落ちる。回帰テストを 1 件追加。
  あわせて --check の欠落ディレクトリ案内を「台帳を手動編集」から
  --clean への案内に改め、README に先頭 // 綴りが対象外である旨を足す。
  ```

- PR タイトル: `fix: 削除済み --clean の cwd 連結で末尾改行を保持する（#108）`。本文に「Closes #108」、検証節の実行結果（lint・launcher-only の PASS 実測値と FAIL=0・validator-only）、not run の項目（実 podman による清掃）を書く。
- PR を作る前に `claude-review` skill（`~/.agents/skills/claude-review`、Claude Opus 読み取り専用）のレビューを受ける。
- マージは持ち主が手で行う。

## 実装者

**実装: Codex** — host の checkout で完結し、置換文・回帰テスト・Expected が逐語で確定しているため（判定基準 4）。ただし Codex の対話セッションが同じ `claude-container` を編集する #99 を `/tmp/claude-issue99` で実装中のため、#99 と同じセッションで扱うか別セッションで扱うかは持ち主が決める（変更箇所は `resolve_project_directory()`〈208 行付近〉と `check_one_project()`〈1185 行〉で、#99 の `guard_*` 追加〈730 行付近・1280 行付近・1488 行付近〉と重ならず、git のマージは衝突しない見込み）。

`/goal` に渡す文面:

```
docs/superpowers/plans/2026-09-14-clean-cwd-newline-108.md を上から順に実施する。

既決事項（蒸し返し不要）: 修正は $(pwd -L) を $PWD に置き換える 1 行。回帰テストは計画の逐語テキストどおりで、Task 1 で赤（FAIL=1）を確認してから Task 2 で緑にする。nit 2 件（--check の案内文、README の // 注記）も計画の逐語テキストどおり。語句の改善はしない。

制約: 編集するのは claude-container・test-build.sh・README.md だけ。計画ファイル自身と .claude/ 配下は変更しない。検証用の一時ファイルは mktemp の範囲で作って消す。Expected と実結果がずれたら修正せず止めて報告する。

手順: origin から既存ブランチ fix/clean-cwd-newline-108 を checkout する（計画ファイルのコミットだけが載っている。新たに切らない）→ Task 1（赤の確認まで）→ Task 2（緑の確認まで）→ Task 3 → 検証（lint.sh、test-build.sh --launcher-only、--validator-only、git diff --check）→ 計画記載のメッセージで 1 コミット → claude-review skill（~/.agents/skills/claude-review）でレビューを受け、should-fix 以上があれば別コミットで直してから → push → gh pr create（本文に Closes #108、検証結果、not run 項目）。

成果物: PR の URL と、検証コマンドごとの実出力（Expected との照合）、未実行項目の一覧。
```

- sandbox: `workspace-write`（3 ファイルの編集・コミット。テストは mktemp・`.build-context/`・`.claude/test-results/` に書く）。
- ネットワーク: 必要（`git push`・`gh pr create`・`claude-review`）。
