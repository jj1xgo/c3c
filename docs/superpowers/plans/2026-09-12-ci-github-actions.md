# GitHub Actions による CI 導入 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task（この repo の Codex には multi_agent が無いので subagent-driven-development は使わない）. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `lint.sh` と `test-build.sh` の podman 不要な部分を GitHub Actions で PR と main への push のたびに実行し、赤・緑が出る状態にする。

**Architecture:** `.github/workflows/ci.yml` を 1 ジョブ構成で新設し、shellcheck 0.11.0 を SHA256 固定で取得してから `lint.sh`、`test-build.sh --validator-only`、`--launcher-only` を順に実行する。runner に compose provider が無いため、`lint.sh` に `LINT_SKIP_COMPOSE=1` で compose 検証を明示的に外す分岐を足し、CI はこれを宣言して呼ぶ。実装が緑になった後、使い捨ての draft PR で 3 通りの壊し方が赤になることを確かめる。

**Tech Stack:** GitHub Actions（`ubuntu-24.04`）、bash、shellcheck 0.11.0、`gh` CLI。

**Spec:** `docs/superpowers/specs/2026-09-12-ci-design.md`（この計画は設計文書に従う。両方を読むこと）。

## 実行者への前提

- 実行者は Codex（host）。作業ブランチは `ci/github-actions`（既に存在し、設計文書とこの計画がコミット済み）。このブランチの上で作業する。skill は `superpowers:executing-plans` を使う（`subagent-driven-development` は `~/.codex/config.toml` に `[features] multi_agent = true` が無いため使えない）。
- `gh pr checks --watch` は失敗したチェックがあると 0 以外で終了する。Task 4 の「Expected: fail」はその状態が意図どおりという意味で、コマンドの異常ではない。
- `<本 PR の番号>`、`<使い捨て PR の番号>`、`<run の URL>`、`<ID>` は実行時に埋める値。計画の未記入ではない。
- runner と host の差: runner のユーザーは `runner`、`env -i` 下のランチャーは C ロケールで動く。`--launcher-only` は日本語リテラルをバイト列として扱うだけなので影響しない想定だが、runner での初回実行が実検証になる（Task 2 Step 5 の「赤なら直す」で対応）。
- **PR のマージは行わない。** PR 作成まで行い、レビューとマージは別の担当（Fable）が行う。
- commit メッセージ、PR の題名と本文は日本語のみ（repo の表記方針。README「表記」節）。既存の commit の型は `fix: ...`、`docs: ...` のような接頭辞＋日本語の要約。
- 外部操作は `git push` と `gh pr create`、使い捨て PR の `gh pr create --draft`・`gh pr close --delete-branch` に限る。Issue の起票は行わない（Fable がレビュー時に行う）。
- `./test-build.sh` を引数なしで実行しない（実 podman build が走り、#59 により実台帳に 1 行残る）。使うのは `--validator-only` と `--launcher-only` だけ。

## Global Constraints

- runner は `ubuntu-24.04` を明示する。`ubuntu-latest` は使わない。
- `permissions: contents: read` のみ。
- `actions/checkout` は commit SHA `3d3c42e5aac5ba805825da76410c181273ba90b1` で固定し、コメント `# v7.0.1` を添える。
- shellcheck は 0.11.0。tarball `shellcheck-v0.11.0.linux.x86_64.tar.xz` の SHA256 は `8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198`。
- `timeout-minutes: 10`。`continue-on-error` は使わない。
- 表記は日本語のみ（workflow 内の `name:` とコメントも日本語）。

---

### Task 1: `lint.sh` に `LINT_SKIP_COMPOSE` を足す

**Files:**
- Modify: `lint.sh:1-8`（先頭コメント）と `lint.sh:62-66`（compose 検証の分岐）

**Interfaces:**
- Produces: 環境変数 `LINT_SKIP_COMPOSE`。値が `1` のとき compose 検証をスキップし WARNING を stderr へ出す。未設定または `1` 以外なら従来どおり。Task 2 の workflow がこれを `LINT_SKIP_COMPOSE=1 ./lint.sh` として使う。

- [ ] **Step 1: 変更前の挙動を確かめる（失敗するダミー podman で rc=1）**

Run:
```bash
d=$(mktemp -d); printf '#!/bin/sh\nexit 1\n' > "$d/podman"; chmod +x "$d/podman"
PATH="$d:$PATH" ./lint.sh; echo "rc=$?"
PATH="$d:$PATH" LINT_SKIP_COMPOSE=1 ./lint.sh; echo "rc=$?"
```
Expected: 1 回目も 2 回目も `lint NG` が出て `rc=1`（変更前は変数を見ないので両方失敗する）。

- [ ] **Step 2: `lint.sh` の compose 分岐を書き換える**

`lint.sh:62-66` の次のブロックを:
```bash
if command -v podman >/dev/null 2>&1; then
  podman compose -f compose.yml config >/dev/null || status=1
else
  echo "WARNING: podman が見つからないため compose config 検証をスキップしました（コンテナ内開発時は想定内）。" >&2
fi
```
次に置き換える:
```bash
if [ "${LINT_SKIP_COMPOSE:-}" = "1" ]; then
  echo "WARNING: LINT_SKIP_COMPOSE=1 のため compose config 検証をスキップしました（GitHub Actions の runner には compose provider が無いため、CI では意図的に外している）。" >&2
elif command -v podman >/dev/null 2>&1; then
  podman compose -f compose.yml config >/dev/null || status=1
else
  echo "WARNING: podman が見つからないため compose config 検証をスキップしました（コンテナ内開発時は想定内）。" >&2
fi
```

- [ ] **Step 3: 先頭コメントに変数の説明を足す**

`lint.sh:2-5` のコメントの末尾（`set -uo pipefail` の前）に次の 2 行を足す:
```bash
# LINT_SKIP_COMPOSE=1 を与えると podman compose config の検証だけを WARNING 付きで
# スキップする（CI 用。.github/workflows/ci.yml が使う）。
```

- [ ] **Step 4: 変更後の 3 パターンを確かめる**

Run:
```bash
d=$(mktemp -d); printf '#!/bin/sh\nexit 1\n' > "$d/podman"; chmod +x "$d/podman"
PATH="$d:$PATH" ./lint.sh; echo "rc=$?"
PATH="$d:$PATH" LINT_SKIP_COMPOSE=1 ./lint.sh; echo "rc=$?"
./lint.sh; echo "rc=$?"
```
Expected:
- 1 回目: `lint NG`、`rc=1`（従来の挙動が変わっていない）。
- 2 回目: stderr に `WARNING: LINT_SKIP_COMPOSE=1 のため ...`、`lint OK`、`rc=0`。
- 3 回目: `lint OK`、`rc=0`（host の実 podman で compose 検証も通る。`lint.sh` 自身も shellcheck の対象なので、ここで自分の変更が lint を通ることも確認される）。

- [ ] **Step 5: Commit**

```bash
git add lint.sh
git commit -m "feat: lint.sh に LINT_SKIP_COMPOSE を足し、CI から compose 検証を明示的に外せるようにする"
```

---

### Task 2: `.github/workflows/ci.yml` を新設し、PR を作る

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 の `LINT_SKIP_COMPOSE=1`。`test-build.sh --validator-only` と `--launcher-only`（FAIL が 1 以上なら `exit 1`、既存）。
- Produces: PR と main への push で走るワークフロー `CI`。Task 3 の README が参照し、Task 4 の壊し方がこのワークフローの赤を確かめる。

- [ ] **Step 1: workflow を書く**

`.github/workflows/ci.yml` を次の内容で作る:
```yaml
# lint.sh と test-build.sh のうち podman を必要としない部分を回す。
# 全体実行（実 podman build）は対象外。設計: docs/superpowers/specs/2026-09-12-ci-design.md
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
      - name: checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - name: shellcheck を版固定で取得する
        run: |
          set -euo pipefail
          cd "$RUNNER_TEMP"
          curl -fsSL -o shellcheck.tar.xz \
            "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz"
          echo "${SHELLCHECK_SHA256}  shellcheck.tar.xz" | sha256sum --check
          tar -xJf shellcheck.tar.xz
          echo "$RUNNER_TEMP/shellcheck-v${SHELLCHECK_VERSION}" >> "$GITHUB_PATH"

      - name: shellcheck の版を確かめる
        run: |
          shellcheck --version | grep -qx "version: ${SHELLCHECK_VERSION}"

      - name: lint.sh（compose 検証はスキップ）
        run: LINT_SKIP_COMPOSE=1 ./lint.sh

      - name: test-build.sh --validator-only
        run: ./test-build.sh --validator-only

      - name: test-build.sh --launcher-only
        run: ./test-build.sh --launcher-only
```

- [ ] **Step 2: YAML として読めることと lint を通ることを確かめる**

Run:
```bash
python3 -c 'import yaml,sys; d=yaml.safe_load(open(".github/workflows/ci.yml")); print(sorted(d["jobs"]["lint-and-test"].keys()))'
./lint.sh; echo "rc=$?"
```
Expected: 1 行目が `['name', 'runs-on', 'steps', 'timeout-minutes']` を出す。`lint.sh` は `lint OK`、`rc=0`（`ci.yml` は shebang が無いので lint の対象外。対象スクリプト数が増えていないことを出力の `対象スクリプト (N)` で見る）。

- [ ] **Step 3: Commit と push**

```bash
git add .github/workflows/ci.yml
git commit -m "feat: GitHub Actions で lint.sh と podman 不要のテストを回す CI を追加する"
git push -u origin ci/github-actions
```

- [ ] **Step 4: PR を作る（draft ではない）**

```bash
gh pr create --base main --title "feat: GitHub Actions による CI を導入する（lint と podman 不要のテスト）" --body-file - <<'PRBODY'
## 概要

`lint.sh` と `test-build.sh` の podman を必要としない部分（`--validator-only`、`--launcher-only`）を GitHub Actions で PR と main への push のたびに実行する。

## 変更

- `.github/workflows/ci.yml` を新設。`ubuntu-24.04`、`contents: read`、shellcheck 0.11.0 を SHA256 固定で取得。
- `lint.sh` に `LINT_SKIP_COMPOSE=1` を追加。runner に compose provider が無いため CI では compose 検証を明示的に外す。
- README「変更後の確認」節に CI の記述を追記。

## 範囲外

- `test-build.sh` 全体実行の CI 化（終了コードが常に 0 のため先に修正が要る。#59 も関連）。

## 検証

- host: `LINT_SKIP_COMPOSE` の 3 パターン（失敗する podman で rc=1、変数ありで rc=0、通常で rc=0）。
- CI: この PR が緑。
- 赤の確認: 使い捨て draft PR で shellcheck 違反、ベクタ表の期待値改変、SHA256 改変の 3 通りが赤（結果は後述のコメントに記録）。

設計: `docs/superpowers/specs/2026-09-12-ci-design.md`、計画: `docs/superpowers/plans/2026-09-12-ci-github-actions.md`
PRBODY
```

- [ ] **Step 5: CI が緑になるのを待つ**

Run:
```bash
gh pr checks --watch
```
Expected: `CI / lint と podman 不要のテスト` が pass。赤なら `gh run list --branch ci/github-actions --limit 1` で run ID を取り、`gh run view <ID> --log-failed` で失敗ステップを読んで直す。直したら commit して push し、再び待つ。

---

### Task 3: README「変更後の確認」節に CI の記述を足す

**Files:**
- Modify: `README.md:398-406`（「変更後の確認」節の冒頭と `lint.sh` の説明文）

**Interfaces:**
- Consumes: Task 1 の `LINT_SKIP_COMPOSE`、Task 2 の workflow。

- [ ] **Step 1: `lint.sh` の説明文に変数の 1 文を足す**

`README.md:406` の段落は次の文で終わる:
```
podman が無い環境（コンテナ内での開発時）では Compose 検証のみ警告付きでスキップされる。
```
その直後に次の 1 文を足す（同じ段落内）:
```
`LINT_SKIP_COMPOSE=1` を与えると、podman の有無に関わらず Compose 検証だけを警告付きでスキップする（CI 用）。
```

- [ ] **Step 2: CI の段落を足す**

`README.md:400` の `テストスイートはない。スクリプトや Compose / Dockerfile を編集した後は以下で確認する。` の段落の直後に、次の段落を足す:
```
GitHub Actions（`.github/workflows/ci.yml`）が、PR と `main` への push のたびに `lint.sh`（Compose 検証は `LINT_SKIP_COMPOSE=1` でスキップ）、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only` を `ubuntu-24.04` の runner で実行する。shellcheck はホストの開発環境と同じ版を SHA256 固定で取得する。実 podman が必要な `./test-build.sh` の全体実行は CI の対象外で、ホストで手動実行する。
```

- [ ] **Step 3: 記述と実装の一致を確かめる**

Run:
```bash
grep -c "LINT_SKIP_COMPOSE" README.md lint.sh .github/workflows/ci.yml
grep -n "validator-only\|launcher-only" .github/workflows/ci.yml
```
Expected: 3 ファイルとも 1 以上。workflow に `--validator-only` と `--launcher-only` の両方がある。

- [ ] **Step 4: Commit と push**

```bash
git add README.md
git commit -m "docs: README の変更後の確認節に CI で回す 3 本と LINT_SKIP_COMPOSE を書く"
git push
gh pr checks --watch
```
Expected: CI が pass。

---

### Task 4: 使い捨て draft PR で 3 通りの壊し方が赤になることを確かめる

**Files:**
- 一時的に変更（本 PR には含めない）: `git-askpass.sh`、`test-build.sh:58`、`.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 2 の workflow。

- [ ] **Step 1: 使い捨てブランチと draft PR を作る**

```bash
git switch -c ci-red-probe
printf '\n# 赤の確認用（使い捨て）\nprobe="a b"\necho $probe\n' >> git-askpass.sh
git commit -am "probe: shellcheck 違反で CI が赤になることを確かめる（使い捨て）"
git push -u origin ci-red-probe
gh pr create --draft --base ci/github-actions --title "probe: CI の赤を確かめる（使い捨て、マージしない）" --body "壊し方 3 通りで CI が赤になることの確認。確認後に閉じてブランチを削除する。"
gh pr checks --watch
```
Expected: fail。`gh run list --branch ci-red-probe --limit 1` で run ID を取り、`gh run view <ID> --log-failed | grep -m3 SC2086` に SC2086（`echo $probe` の未クォート）が出る。失敗したステップ名が `lint.sh（compose 検証はスキップ）` であること。

- [ ] **Step 2: 1 を戻し、ベクタ表の期待値を 1 件改変する**

```bash
git revert --no-edit HEAD
sed -i "58s/|python3-pip\\\\n'$/|python3-pipX\\\\n'/" test-build.sh
sed -n '58p' test-build.sh
```
Expected: 58 行目が `  'packages|accept|python3-pip\n|python3-pipX\n'` になる。
```bash
./test-build.sh --validator-only; echo "rc=$?"
```
Expected: `FAIL=1`、`rc=1`（host で先に赤を確認）。
```bash
git commit -am "probe: ベクタ表の期待値を改変して --validator-only が赤になることを確かめる（使い捨て）"
git push
gh pr checks --watch
```
Expected: fail。失敗したステップ名が `test-build.sh --validator-only`。

- [ ] **Step 3: 2 を戻し、SHA256 を 1 文字改変する**

```bash
git revert --no-edit HEAD
sed -i 's/8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198/8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227190/' .github/workflows/ci.yml
git diff --stat
git commit -am "probe: SHA256 を改変して shellcheck の取得が止まることを確かめる（使い捨て）"
git push
gh pr checks --watch
```
Expected: fail。失敗したステップ名が `shellcheck を版固定で取得する`、ログに sha256sum の不一致（runner の英語ロケールでは `1 computed checksum did NOT match`、host の日本語ロケールでは `1 個の計算したチェックサムが一致しませんでした`）。

- [ ] **Step 4: 結果を本 PR にコメントし、使い捨て PR を閉じる**

```bash
gh pr comment <本 PR の番号> --body-file - <<'CMT'
## 赤の確認（使い捨て PR #<番号>）

| 壊し方 | 失敗したステップ | run |
|---|---|---|
| shellcheck 違反（SC2086） | lint.sh（compose 検証はスキップ） | <run の URL> |
| ベクタ表の期待値改変 | test-build.sh --validator-only | <run の URL> |
| SHA256 改変 | shellcheck を版固定で取得する | <run の URL> |
CMT
gh pr close <使い捨て PR の番号> --delete-branch
git switch ci/github-actions
git branch -D ci-red-probe 2>/dev/null || true
git status --short --branch
```
Expected: 使い捨て PR が closed、ブランチが remote と local から消えている。`ci/github-actions` は clean。

---

### Task 5: 完了報告

- [ ] **Step 1: 報告を書く**

作業の最後に次を報告する（handover の skill があればそれで、無ければ PR のコメントで）:
- 本 PR の番号と URL、CI の最終状態。
- host の `LINT_SKIP_COMPOSE` の 3 パターンの実測結果。
- 赤の確認 3 通りの結果（Task 4 のコメントへの参照）。
- 計画から外れた点、未実行の検証（`not run` と理由）。
- **PR はマージしていない**こと。

## 範囲外（Fable がレビュー時に行う）

- `test-build.sh` 全体実行の終了コードが常に 0 である件の Issue 起票（#59 との関係を含む）。
- PR のレビュー（Fable と Codex の二重）とマージ。
