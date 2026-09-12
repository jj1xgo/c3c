# CI のレビュー追随（失敗ログの表示、hook 回帰テストの追加、取得と版確認の堅牢化）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task（この host の Codex には multi_agent が無いので subagent-driven-development は使わない）. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #63 でマージした CI に対して、Claude（Opus）のレビューが挙げた追随項目を反映する。赤になったときに原因が Actions のログで読めること、同梱 hook の回帰テストが CI で回ること、shellcheck の取得と版確認が一時障害と shell 設定の変更に耐えること。

**Architecture:** `.github/workflows/ci.yml` に 2 ステップを足す（hook 回帰テスト、`if: failure()` でテストログを出す）。既存の取得ステップに `curl` の再試行と時間上限を足し、版確認をパイプラインを使わない `case` 式にする。README の「変更後の確認」節の 2 文を実装に合わせる。`test-build.sh`・`lint.sh`・hook 本体は変更しない。

**Tech Stack:** GitHub Actions（`ubuntu-24.04`）、bash、shellcheck 0.11.0、`gh` CLI。

**Spec:** この文書の「設計」節。由来は PR #63 の Claude レビューコメント https://github.com/jj1xgo/claude-container/pull/63#issuecomment-5642772510 （Important 1、計画の欠陥 A・B、Minor 4・5）。前回の設計 `docs/superpowers/specs/2026-09-12-ci-design.md` の制約はそのまま引き継ぐ。

**実装: Codex（host）。** 理由: host の checkout で完結し、手順と Expected が逐語で確定していて、設計判断が残らない（CLAUDE.md「モデルと実装者の使い分け」の 4）。

## 設計

### 調査で確定した事実（2026-09-12）

- `test-build.sh` の `check()`（`test-build.sh:26-39`）は PASS / FAIL の 1 行だけを stdout に出し、検査コマンドの出力は `$LOG_FILE`（`.claude/test-results/YYYY-MM-DD_HHMMSS.log`、`test-build.sh:8-9`）にだけ書く。ランチャーテスト（`run_launcher_tests()`、`test-build.sh:493-911`）はランチャーの出力もこのログにだけ追記する（`test-build.sh:903,909`）。`.claude/` は `.gitignore:13` で無視される。現在の workflow はこのログを表示も保存もしないので、赤になっても原因が Actions で読めない。
- `examples/hooks/tests/test-block-pr-approve.sh` は podman 不要の回帰テストで、FAIL があれば `exit 1`（同 `:72-78`）。`jq` を使う（同 `:22`）。host で `bash examples/hooks/tests/test-block-pr-approve.sh` は「全ケース green」、rc=0。テスト冒頭（同 `:4-8`）の注意は「トリガー文字列をコマンド行に書かない」であり、`bash <ファイル>` での実行は明示的に許されている。
- `ubuntu-24.04` runner には jq 1.7 がある（actions/runner-images の `Ubuntu2404-Readme.md`）。
- GitHub Actions の `run` は `shell` 未指定だと `bash -e {0}`（pipefail なし）、`shell: bash` を明示すると `bash --noprofile --norc -eo pipefail {0}` になる（workflow 構文の公式ドキュメント）。現在の版確認 `shellcheck --version | grep -Fqx …` はパイプラインなので、将来 `shell: bash` を足すと `grep -q` の早期終了で左側が SIGPIPE を受ける経路が生じる。
- `GITHUB_PATH` への追記は PATH の先頭に前置され、後続ステップで有効（workflow コマンドの公式ドキュメント）。現在の配線はこれに依存しており正しい。
- host で `case "$(shellcheck --version)" in *$'\n'"version: 0.11.0"$'\n'*)` は一致し、`0x11y0` は一致しない（実測）。
- host の curl は 8.21.0。`--retry-all-errors` は curl 7.71 以降で使える。runner の curl はそれより新しい。
- `lint.sh` は `git ls-files` と shebang で対象を決めるので、`examples/hooks/` 配下のスクリプトも既に shellcheck の対象に入っている。

### 変更

1. `.github/workflows/ci.yml`
   - 取得ステップの `curl` に `--retry 3 --retry-all-errors --max-time 120` を足す。
   - 版確認ステップをパイプラインなしの `case` 式にする。不一致なら実際の出力を表示して `exit 1`。
   - `--launcher-only` の後に `bash examples/hooks/tests/test-block-pr-approve.sh` のステップを足す。
   - 最後に `if: failure()` のステップを足し、`.claude/test-results/*.log` を `::group::` で囲んで `cat` する。ログが無ければ何も出さず成功で終える。
2. `README.md`「変更後の確認」節
   - 400 行目: テストの列挙に `examples/hooks/tests/test-block-pr-approve.sh`（同梱 hook の回帰テスト）を足す。
   - 402 行目: CI で回すものに hook の回帰テストを足し、失敗時にテストログを Actions に出すことを 1 文足す。

### 捨てた案と理由

- `actions/upload-artifact` でログを保存する: marketplace action の追加は前回の設計で避けている。赤の原因を読むだけなら `cat` で足りる。
- `shell: bash` を明示して pipefail を有効にする: 現在の版確認がパイプラインのままだと SIGPIPE の経路を作る。パイプラインを無くす方が根本的で、shell の既定にも依存しない。
- `test-build.sh` の `check()` を stdout にも出すよう変える: host での実行時に出力が長くなり、既存の使い勝手を変える。CI 側で失敗時だけ出す方が影響が小さい。
- `cancel-in-progress` を PR だけにする（レビューの Minor 3）: 前回の設計で main にも適用すると決めた既決事項。変えない。
- Dependabot に `github-actions` を足す（レビューの Minor 2）: #67 で別に扱う。Dependabot が SHA 固定を追随するかの確認が先。

### 合格条件

- 本 PR の CI が緑で、hook 回帰テストのステップが「全ケース green」を出す。失敗時ログのステップは緑のときスキップされる。
- 使い捨て PR で 2 通りが赤: (1) ランチャーテストの期待値を改変すると `--launcher-only` が赤になり、失敗時ログのステップがログ本文（`[FAIL]` の行とランチャーの出力）を表示する。(2) hook 回帰テストの期待値を改変すると hook のステップが赤になる。
- host で `case` 式の版確認が 0.11.0 に一致し、偽の版に一致しない。
- README の記述が実装と一致する。
- PR を作る前に `claude-review` skill で Claude のレビューを受け、Critical と Important が無い（あれば直す）。

## 実行者への前提

- 実行者は Codex（host）。作業ブランチは `ci/review-followup`（既に存在し、この計画がコミット済み）。このブランチの上で作業する。skill は `superpowers:executing-plans` を使う。
- **PR のマージは行わない。** PR 作成まで行い、レビューは Fable のセッションが行い、マージは持ち主が手で行う。
- 必要な権限: リポジトリの作業ツリーと `.git` への書き込み、`git push`、`gh`（PR の作成・コメント・使い捨て PR の close）、`claude -p` のためのネットワーク。sandbox は workspace-write でネットワーク許可（`-c sandbox_workspace_write.network_access=true`）か、持ち主が承認する運用のどちらか。読み取り専用 sandbox では Task 2 以降が進まない。
- commit メッセージ、PR の題名と本文、PR コメント、workflow の表示名とコメントは日本語のみ（README「表記」節）。commit の型は `fix:`、`feat:`、`docs:` の接頭辞＋日本語の要約。
- 外部操作は次に限る: `git push`、本 PR の `gh pr create`、本 PR への `gh pr comment`、使い捨て PR の `gh pr create --draft` と `gh pr close --delete-branch`。Issue の起票はしない。
- **この checkout の `gh` の既定 repo は upstream の `sethjensen1/claude-container` を指す。** すべての `gh` コマンドに `-R jj1xgo/claude-container` を付ける。`-R` 付きの `gh pr checks` / `gh pr comment` / `gh pr close` は PR 番号の引数が必須。既定 repo は変更しない。
- `./test-build.sh` を引数なしで実行しない（実 podman build が走り、#59 により実台帳に 1 行残る）。使うのは `--validator-only` と `--launcher-only` だけ。
- hook 回帰テストは `bash examples/hooks/tests/test-block-pr-approve.sh` の 1 コマンドで実行し、トリガー文字列（承認系のサブコマンド）をシェルのコマンド行や commit メッセージに書かない（テスト冒頭の注意）。
- **CI の完了待ちは commit 単位で行い、run の `conclusion` と失敗ステップ名で判定する**（監視コマンドの終了コードでは判定しない）。次の手順を毎回そのまま使う:

  ```bash
  sha=$(git rev-parse HEAD); id=""
  for i in $(seq 1 20); do
    id=$(gh run list -R jj1xgo/claude-container --commit "$sha" --json databaseId,workflowName -q '[.[] | select(.workflowName == "CI")][0].databaseId')
    [ -n "$id" ] && break
    sleep 15
  done
  if [ -z "$id" ]; then echo "判定不能: 5 分待っても run が登録されない"; else
    echo "run=$id  https://github.com/jj1xgo/claude-container/actions/runs/$id"
    gh run watch -R jj1xgo/claude-container "$id" >/dev/null 2>&1
    gh run view -R jj1xgo/claude-container "$id" --json status,conclusion --jq '"status=" + .status + " conclusion=" + .conclusion'
    echo "失敗したステップ:"; gh api "repos/jj1xgo/claude-container/actions/runs/$id/jobs" --jq '.jobs[].steps[] | select(.conclusion=="failure") | .name'
  fi
  ```
  `conclusion=success` なら緑。`conclusion=failure` なら赤で、失敗したステップ名を読む。`status` が `completed` 以外、または `id` が空なら判定不能として扱い、再実行する（赤とも緑とも書かない）。ログは `gh run view -R jj1xgo/claude-container "$id" --log` で読む。

---

### Task 1: `ci.yml` を書き換える（取得の再試行、版確認の `case` 化、hook 回帰テスト、失敗時ログ）

**Files:**
- Modify: `.github/workflows/ci.yml`（全文を下の内容に置き換える）

**Interfaces:**
- Produces: ステップ名 `block-pr-approve.sh の回帰テストを実行する` と `失敗時にテストログを出す`。Task 3 の README と Task 4 の赤の確認がこの名前を参照する。

- [ ] **Step 1: 版確認の `case` 式を host で確かめる**

Run:
```bash
v=$(shellcheck --version)
case "$v" in *$'\n'"version: 0.11.0"$'\n'*) echo ok;; *) echo ng;; esac
case "$v" in *$'\n'"version: 0x11y0"$'\n'*) echo ok;; *) echo ng;; esac
```
Expected: 1 行目 `ok`、2 行目 `ng`（host の shellcheck は 0.11.0）。

- [ ] **Step 2: `ci.yml` を全文置き換える**

`.github/workflows/ci.yml` を次の内容にする（既存ファイルを上書き）:

```yaml
# lint.sh と test-build.sh のうち podman を必要としない部分、および同梱 hook の回帰テストを回す。
# 全体実行（実 podman build）は対象外。設計: docs/superpowers/specs/2026-09-12-ci-design.md、
# 追随: docs/superpowers/plans/2026-09-12-ci-review-followup.md
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

env:
  # host の開発環境と同じ版に固定する。SHA256 は公式 Releases の tarball のもの。
  SHELLCHECK_VERSION: "0.11.0"
  SHELLCHECK_SHA256: "8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198"

jobs:
  lint-and-test:
    name: lint と podman 不要のテスト
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - name: リポジトリを取得する
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: shellcheck を版固定で取得する
        run: |
          set -euo pipefail
          cd "$RUNNER_TEMP"
          curl -fsSL --retry 3 --retry-all-errors --max-time 120 -o shellcheck.tar.xz \
            "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz"
          echo "${SHELLCHECK_SHA256}  shellcheck.tar.xz" | sha256sum --check
          tar -xJf shellcheck.tar.xz
          echo "$RUNNER_TEMP/shellcheck-v${SHELLCHECK_VERSION}" >> "$GITHUB_PATH"

      - name: shellcheck の版を確かめる
        # パイプラインを使わない（shell: bash を後から足しても pipefail の影響を受けない）
        run: |
          v=$(shellcheck --version)
          case "$v" in
            *$'\n'"version: ${SHELLCHECK_VERSION}"$'\n'*) echo "shellcheck ${SHELLCHECK_VERSION}" ;;
            *) echo "ERROR: 期待した版 ${SHELLCHECK_VERSION} と一致しない:"; printf '%s\n' "$v"; exit 1 ;;
          esac

      - name: lint.sh を実行する（compose 検証はスキップ）
        run: LINT_SKIP_COMPOSE=1 ./lint.sh

      - name: test-build.sh --validator-only を実行する
        run: ./test-build.sh --validator-only

      - name: test-build.sh --launcher-only を実行する
        run: ./test-build.sh --launcher-only

      - name: block-pr-approve.sh の回帰テストを実行する
        run: bash examples/hooks/tests/test-block-pr-approve.sh

      - name: 失敗時にテストログを出す
        # test-build.sh は検査コマンドとランチャーの出力を .claude/test-results/ にしか書かない。
        # 赤の原因を Actions で読めるよう、失敗時だけ全文を出す。
        if: failure()
        run: |
          shopt -s nullglob
          for f in .claude/test-results/*.log; do
            echo "::group::$f"
            cat "$f"
            echo "::endgroup::"
          done
```

- [ ] **Step 3: 構文と差分を確かめる**

Run:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print([s['name'] for s in d['jobs']['lint-and-test']['steps']])"
git diff --stat
```
Expected: ステップ名 8 個のリスト（取得、shellcheck 取得、版確認、lint、validator、launcher、hook 回帰テスト、失敗時ログ）。差分は `ci.yml` のみ。

- [ ] **Step 4: hook 回帰テストを host で実行する**

Run: `bash examples/hooks/tests/test-block-pr-approve.sh; echo "rc=$?"`
Expected: 末尾に `全ケース green`、`rc=0`。

- [ ] **Step 5: Commit と push、CI の緑を確認する**

```bash
git add .github/workflows/ci.yml
git commit -m "feat: CI に hook 回帰テストと失敗時のテストログ表示を足し、shellcheck の取得と版確認を堅牢にする"
git push -u origin ci/review-followup
```
続けて「実行者への前提」の完了待ちの手順を実行する。
Expected: `conclusion=success`。ログに `全ケース green` があり、`失敗時にテストログを出す` はスキップされている（`gh api .../jobs` の該当ステップの `conclusion` が `skipped`）。赤なら失敗ステップとログを読んで直す。runner 側の差（jq、curl のオプション）で赤になった場合は、その事実を PR 本文に書いて直す。

---

### Task 2: README の「変更後の確認」節を実装に合わせる

**Files:**
- Modify: `README.md:400`（テストの列挙）、`README.md:402`（CI の段落）

- [ ] **Step 1: 対象の 2 文が 1 か所ずつあることを確かめる**

Run:
```bash
grep -c '^テストは `lint.sh` と `test-build.sh`（ベクタ表・契約テスト・ランチャーテスト・実イメージのビルドと起動確認）で行う。' README.md
grep -c '`./test-build.sh --launcher-only` を `ubuntu-24.04` の runner で実行する。' README.md
```
Expected: どちらも `1`。

- [ ] **Step 2: 置換する**

```bash
python3 - <<'EOF'
p="README.md"; s=open(p).read()
old1="テストは `lint.sh` と `test-build.sh`（ベクタ表・契約テスト・ランチャーテスト・実イメージのビルドと起動確認）で行う。"
new1="テストは `lint.sh`、`test-build.sh`（ベクタ表・契約テスト・ランチャーテスト・実イメージのビルドと起動確認）、`examples/hooks/tests/test-block-pr-approve.sh`（同梱 hook の回帰テスト）で行う。"
old2="`./test-build.sh --launcher-only` を `ubuntu-24.04` の runner で実行する。"
new2="`./test-build.sh --launcher-only`、`bash examples/hooks/tests/test-block-pr-approve.sh` を `ubuntu-24.04` の runner で実行する。`test-build.sh` は検査の詳細を `.claude/test-results/` のログにしか書かないので、CI はどれかが失敗したときだけそのログを Actions に出す。"
assert s.count(old1)==1 and s.count(old2)==1
open(p,"w").write(s.replace(old1,new1).replace(old2,new2)); print("ok")
EOF
git diff --stat
```
Expected: `ok`、差分は `README.md` のみ 2 行。

- [ ] **Step 3: README と `ci.yml` の対応を確かめる**

Run:
```bash
grep -c 'test-block-pr-approve.sh' README.md .github/workflows/ci.yml
grep -c 'test-results' README.md .github/workflows/ci.yml
```
Expected: `README.md:2`（400 行目と 402 行目）、`ci.yml:1`。`test-results` は `README.md:1` 以上、`ci.yml:1` 以上。

- [ ] **Step 4: Commit と push**

```bash
git add README.md
git commit -m "docs: 変更後の確認節に hook 回帰テストと CI の失敗時ログ表示を書く"
git push
```
CI の完了待ちは Task 3 の前にまとめて行う（docs だけの commit でも CI は走る。`conclusion=success` を確認する）。

---

### Task 3: 本 PR を作る前に Claude のレビューを受ける

**Files:** なし（レビュー結果は `/tmp/claude-review-<sha>.md`）

- [ ] **Step 1: `claude-review` skill を読む**

`~/.agents/skills/claude-review/SKILL.md` を読み、その手順 1〜4 を実行する。`{説明}` は「CI に hook 回帰テストと失敗時のテストログ表示を足し、shellcheck の取得に再試行、版確認をパイプラインなしにした。README を合わせた。」、`{計画}` はこの計画のパス `docs/superpowers/plans/2026-09-12-ci-review-followup.md`。`base` は `git merge-base origin/main HEAD`。

- [ ] **Step 2: 指摘に対応する**

Expected: Critical と Important が 0 件ならそのまま Task 4 へ。あれば直して commit し、直した差分だけを「確認限定」で再レビューする（skill の手順 4）。Minor は直すか、直さない理由を PR 本文に書く。レビューが `rc` 0 以外か空なら `not run` と報告して止まり、PR を作らない。

---

### Task 4: 本 PR を作り、使い捨て PR で赤 2 通りを確かめる

**Files:** なし（GitHub 上の操作と、使い捨てブランチ上の改変のみ。本ブランチには改変を含めない）

- [ ] **Step 1: 本 PR を作る**

```bash
gh pr create -R jj1xgo/claude-container --base main --head ci/review-followup \
  --title "feat: CI に hook 回帰テストと失敗時のテストログ表示を足し、取得と版確認を堅牢にする（PR #63 のレビュー追随）" \
  --body-file - <<'BODY'
## 概要

PR #63 の Claude レビュー（https://github.com/jj1xgo/claude-container/pull/63#issuecomment-5642772510）の追随。

- `test-build.sh` の検査詳細は `.claude/test-results/` にしか残らず、赤の原因が Actions で読めなかった。失敗時だけログを出すステップを足した。
- `examples/hooks/tests/test-block-pr-approve.sh`（podman 不要、FAIL で exit 1）が CI に無かった。ステップを足した。
- shellcheck の取得に `curl --retry 3 --retry-all-errors --max-time 120`。版確認をパイプラインなしの `case` 式にした（`shell: bash` を後から足しても pipefail の影響を受けない）。
- README「変更後の確認」節を合わせた。

## 範囲外

- `cancel-in-progress` を PR だけにする案は前回の設計で既決（main にも適用）。
- Dependabot の `github-actions` は #67。

## 検証

- host: hook 回帰テスト「全ケース green」。`case` 式の版確認が 0.11.0 に一致し偽の版に一致しない。
- CI: この PR のチェック結果。
- Claude レビュー: （Task 3 の結果を書く。モデル、範囲、判定、未対応の Minor）
- 赤の確認: 使い捨て PR で 2 通り（実施後にコメントで記録）。

計画: `docs/superpowers/plans/2026-09-12-ci-review-followup.md`
BODY
gh pr list -R jj1xgo/claude-container --head ci/review-followup --json number,url -q '.[0]'
```
Expected: PR の番号と URL（以後 `<本 PR の番号>`）。PR 本文の「Claude レビュー」行は Task 3 の実際の結果で埋めてから作る（プレースホルダのまま作らない）。Task 3 で得た `/tmp/claude-review-<sha>.md` の全文を `gh pr comment -R jj1xgo/claude-container <本 PR の番号> --body-file /tmp/claude-review-<sha>.md` で投稿する。

- [ ] **Step 2: 使い捨てブランチと draft PR を作り、ランチャーテストの期待値改変で「赤＋失敗時ログ」を確かめる**

```bash
git switch -c ci-red-probe-2
grep -c 'cfgx/.claude/hooks" -a' test-build.sh
```
Expected: `1`。
```bash
sed -i 's|cfgx/.claude/hooks" -a|cfgx/.claude/hooks-probe" -a|' test-build.sh
grep -c 'hooks-probe' test-build.sh
./test-build.sh --launcher-only; echo "rc=$?"
```
Expected: `1`。host で `結果: PASS=74  FAIL=1`、`rc=1`（E の検査が失敗する）。
```bash
git commit -am "probe: ランチャーテストの期待値を改変して赤と失敗時ログを確かめる（使い捨て）"
git push -u origin ci-red-probe-2
gh pr create -R jj1xgo/claude-container --draft --base ci/review-followup --head ci-red-probe-2 --title "probe: CI の赤と失敗時ログを確かめる（使い捨て、マージしない）" --body "壊し方 2 通りで CI が赤になり、失敗時にテストログが出ることの確認。確認後に閉じてブランチを削除する。"
gh pr list -R jj1xgo/claude-container --head ci-red-probe-2 --json number -q '.[0].number'
```
続けて「実行者への前提」の完了待ちの手順を実行する。
Expected: `conclusion=failure`、失敗したステップが `test-build.sh --launcher-only を実行する`。さらに:
```bash
gh run view -R jj1xgo/claude-container "$id" --log | grep '失敗時にテストログを出す' | grep -c -E '\[FAIL\]|hooks-probe|::group::'
```
Expected: 1 以上（失敗時ログのステップが実行され、ログ本文に `[FAIL]` の行が含まれる）。run の URL を控える。

- [ ] **Step 3: 改変を戻し、hook 回帰テストの期待値改変で赤を確かめる**

```bash
git revert --no-commit HEAD && git commit -m "probe: ランチャーテストの改変を戻す（使い捨て）"
grep -c 'run_case "N5 --request-changes" pass' examples/hooks/tests/test-block-pr-approve.sh
```
Expected: `1`。
```bash
sed -i 's|run_case "N5 --request-changes" pass|run_case "N5 --request-changes" deny|' examples/hooks/tests/test-block-pr-approve.sh
bash examples/hooks/tests/test-block-pr-approve.sh; echo "rc=$?"
```
Expected: `1 件 FAIL`、`rc=1`。
```bash
git commit -am "probe: hook 回帰テストの期待値を改変して赤を確かめる（使い捨て）"
git push
```
続けて完了待ちの手順を実行する。
Expected: `conclusion=failure`、失敗したステップが `block-pr-approve.sh の回帰テストを実行する`。run の URL を控える。

- [ ] **Step 4: 結果を本 PR にコメントし、使い捨て PR を閉じる**

```bash
gh pr comment -R jj1xgo/claude-container <本 PR の番号> --body-file - <<'CMT'
## 赤の確認（使い捨て PR #<使い捨て PR の番号>）

| 壊し方 | 失敗したステップ | 失敗時ログ | run |
|---|---|---|---|
| ランチャーテストの期待値改変（PASS=74 / FAIL=1） | test-build.sh --launcher-only を実行する | 実行され、`[FAIL]` の行を表示 | <run の URL> |
| hook 回帰テストの期待値改変（1 件 FAIL） | block-pr-approve.sh の回帰テストを実行する | 実行された（test-results のログを表示） | <run の URL> |
CMT
gh pr close -R jj1xgo/claude-container <使い捨て PR の番号> --delete-branch
git switch ci/review-followup
git branch -D ci-red-probe-2 2>/dev/null || true
git status --short --branch
```
Expected: 使い捨て PR が closed、ブランチが remote と local から消えている。`ci/review-followup` は clean。

- [ ] **Step 5: PR 本文を最終状態にする**

`gh pr edit -R jj1xgo/claude-container <本 PR の番号> --body-file -` で、「赤の確認」行を「使い捨て PR #<番号> で 2 通り確認、結果はコメント参照」に書き換える。「（実施後に…）」の文言を残さない。

---

### Task 5: 完了報告

- [ ] **Step 1: 計画のチェック欄を更新し、実行結果を追記して commit する**

この計画のチェック欄を `[x]` にし、末尾に `## 実行結果（2026-09-12、Codex）` の節を足して次を書く: 本 PR の番号と URL、CI の最終状態、Claude レビューの判定と対応、赤 2 通りの run、計画から外れた点、`not run` と理由。commit して push する。

- [ ] **Step 2: handover を書く**

`handover` skill で引き継ぎを残す。**PR はマージしていない**ことを明記する。

## 範囲外（Fable がレビュー時に行う）

- PR のレビュー（Fable と Codex の二重）。マージは持ち主。
- #67（Dependabot）の扱い。
