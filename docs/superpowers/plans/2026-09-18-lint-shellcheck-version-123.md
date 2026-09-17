# shellcheck の版差で lint が緑にならない問題の修正 実装計画（#123）

> **実行エージェント向け:** `superpowers:executing-plans` を使い、このセッション内でタスク単位に実行する。ユーザー承認前の自動コミット・push は行わない。

**目的:** コンテナ内（shellcheck 0.10.0）と CI（0.11.0）の両方で `./lint.sh` を終了コード 0・警告ゼロにし、版差が原因の NG を `lint.sh` 自身が指摘できるようにする。

**構成:** 3 点の最小変更。(1) `tests/test-runtime.sh` の directive を両版の警告コードに広げる。(2) `lint.sh` が shellcheck の版を表示し、CI の固定版（`.github/workflows/ci.yml` の `SHELLCHECK_VERSION`）と違えば WARNING を出す（失敗にはしない）。(3) `lint.sh` がロケール未指定のときだけ `LC_ALL=C.UTF-8` を補い、日本語コメント行の出力が途中で切れないようにする。イメージの shellcheck を 0.11.0 に揃える案は採らない（`Dockerfile.claude` に取得経路とハッシュ照合を足すのは監査対象の拡大で、directive 1 行で両版が通るため）。

**技術:** bash、shellcheck 0.10.0（Debian パッケージ）と 0.11.0（GitHub Releases、CI と同じ SHA256）。

**仕様:** Issue [#123](https://github.com/jj1xgo/claude-container/issues/123)。基準 commit: `7f1aae1`。

## 共通制約

- 日本語の文書・メッセージ（README「表記」節）。
- `lint.sh` の判定（終了コード）は変えない。版の WARNING と LC_ALL の補完は出力の追加だけで、既存の NG / OK 判定に影響しない。
- 利用者から見えるインターフェース（CLI 引数・設定形式・既定挙動）は変えない。タグ提案の対象外。
- 挙動を変えたら README の該当節（「変更後の確認」節の `lint.sh` 段落）を同じコミットで更新する。
- `.claude/hooks/lint-posttool.sh`（ops リポジトリ）は本計画で触らない。同じ LANG 未設定の影響を受けるが、hook の改修は別件（Opus）とする。

## 実測済みの事実（計画時、コンテナ内）

- `sed 's/disable=SC2329 #/disable=SC2317,SC2329 #/' tests/test-runtime.sh | shellcheck -s bash -` は 0.10.0 で rc=0。
- 0.10.0 の SC2317 は `finish()` の本体（35〜78 行）にだけ出る。他ファイルに SC2317 は出ない。
- コンテナ内は `LANG`・`LC_ALL` とも未設定で、`./lint.sh` の shellcheck 出力が `not run（` の直後で切れる（`commitBuffer: invalid argument`）。`locale -a` に `C.utf8` がある。
- コンテナ内から `https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.x86_64.tar.xz` に HTTP 200 で到達できる（firewall 許可済み）。CI の固定 SHA256 は `8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198`。
- `shellcheck --version | awk '/^version:/ {print $2}'` は `0.10.0`、`sed -nE 's/^[[:space:]]*SHELLCHECK_VERSION:[[:space:]]*"([^"]+)".*/\1/p' .github/workflows/ci.yml` は `0.11.0` を返す。

## 変更するファイル

| ファイル | 責務 |
| --- | --- |
| `tests/test-runtime.sh` | `finish()` の directive を `SC2317,SC2329` にする |
| `lint.sh` | ロケールの補完、shellcheck の版表示と CI 固定版との差の WARNING |
| `README.md` | 「変更後の確認」節の `lint.sh` 段落に版表示・WARNING・ロケールの説明を足す |

## 作業場所

memory の方針どおり worktree で作業する。`/workspace` で次を実行する。

```bash
git worktree add .claude/worktrees/lint-shellcheck-123 -b fix/lint-shellcheck-version-123 main
cd .claude/worktrees/lint-shellcheck-123
```

worktree には ops の `.claude/`（PostToolUse hook）が無いので、編集ごとに `shellcheck <file>` を手で実行する。以下のコマンドはすべて worktree 内で実行する。

## Task 0: 0.11.0 を検証用に取得する（隔離、リポジトリ外）

**目的:** コンテナ内で CI と同じ版でも検証できるようにする。取得先は scratchpad で、リポジトリには何も入れない。

- [ ] scratchpad へ取得し、CI と同じ SHA256 で照合する。

  ```bash
  sc=/tmp/claude-1000/-workspace/0ddc3b8c-3e8b-41be-8af9-65110638b11e/scratchpad/shellcheck-0.11.0
  mkdir -p "$sc" && cd "$sc"
  curl -fsSL --retry 3 --max-time 120 -o shellcheck.tar.xz \
    "https://github.com/koalaman/shellcheck/releases/download/v0.11.0/shellcheck-v0.11.0.linux.x86_64.tar.xz"
  echo "8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198  shellcheck.tar.xz" | sha256sum --check
  tar -xJf shellcheck.tar.xz
  "$sc/shellcheck-v0.11.0/shellcheck" --version | grep '^version: 0.11.0'
  cd - >/dev/null
  ```

  Expected: `shellcheck.tar.xz: OK` と `version: 0.11.0`。SHA256 が合わなければ止めて報告する（取得物を使わない）。scratchpad が別パスならそのパスに読み替える（scratchpad は環境の system prompt に書かれている）。

- [ ] 0.11.0 で現状の main が緑であることを確認する（現状把握）。

  ```bash
  PATH="$sc/shellcheck-v0.11.0:$PATH" LC_ALL=C.UTF-8 LINT_SKIP_COMPOSE=1 ./lint.sh; echo "rc=$?"
  ```

  Expected: `lint OK`、rc=0（CI と同じ結果）。ここで NG なら計画の前提が崩れているので止めて報告する。

## Task 1: `tests/test-runtime.sh` の directive を両版に広げる

**Files:**
- Modify: `tests/test-runtime.sh:33`

- [ ] **Step 1: 失敗を再現する（0.10.0）**

  ```bash
  LC_ALL=C.UTF-8 shellcheck tests/test-runtime.sh; echo "rc=$?"
  ```

  Expected: SC2317 が複数件、rc=1。

- [ ] **Step 2: directive を書き換える**

  33 行目を次にする（コメントも版差の理由を書く）。

  ```bash
  # shellcheck disable=SC2317,SC2329 # EXIT trap から間接的に呼び出す（0.10.0 は SC2317、0.11.0 は SC2329 を出す）。
  ```

- [ ] **Step 3: 両版で通ることを確認する**

  ```bash
  LC_ALL=C.UTF-8 shellcheck tests/test-runtime.sh; echo "rc(0.10.0)=$?"
  "$sc/shellcheck-v0.11.0/shellcheck" tests/test-runtime.sh; echo "rc(0.11.0)=$?"
  ```

  Expected: どちらも出力なし、rc=0。

- [ ] **Step 4: コミット**

  ```bash
  git add tests/test-runtime.sh
  git commit -m "fix: test-runtime.sh の directive を shellcheck 0.10.0 の SC2317 にも広げる

コンテナ内の shellcheck 0.10.0 は EXIT trap から間接的に呼ぶ finish() を
SC2317（unreachable）として報告し、CI の 0.11.0 が出す SC2329 とコードが違う。
両方を disable して両版で ./lint.sh が通るようにする（#123）。"
  ```

## Task 2: `lint.sh` にロケール補完と版の表示・WARNING を足す

**Files:**
- Modify: `lint.sh:8-16`（`set -uo pipefail` の直後、shellcheck の存在確認の後）

**インターフェース:** 標準出力に `shellcheck <版>` を 1 行出す。CI の固定版と違うときだけ標準エラーに `WARNING: shellcheck の版（…）が CI の固定版（…）と異なります…` を出す。`ci.yml` が無い・版が読めないときは WARNING を出さず版表示だけにする。終了コードは変えない。

- [ ] **Step 1: 現象を再現する（ロケール）**

  ```bash
  env -u LANG -u LC_ALL LINT_SKIP_COMPOSE=1 ./lint.sh 2>&1 | grep -c 'commitBuffer'
  ```

  Expected: Task 1 が済んでいると shellcheck の指摘自体が無いので 0 になる。再現には一時的に日本語コメントを含む違反ファイルを使う。

  ```bash
  printf '#!/bin/bash\n# 日本語のコメント\necho $x\n' > "$sc/../lint-locale-probe.sh"
  env -u LANG -u LC_ALL shellcheck "$sc/../lint-locale-probe.sh" 2>&1 | tail -n 2
  ```

  Expected: 出力の末尾に `commitBuffer: invalid argument` が出る（途中で切れる）。出ない場合は環境が違うので、Step 2 のロケール補完は入れるが「再現せず」と報告する。

- [ ] **Step 2: `lint.sh` に追記する**

  `if ! command -v shellcheck ...; fi` のブロックの直後（`status=0` の前）に次を入れる。

  ```bash
  # コンテナ内は LANG・LC_ALL とも未設定で、shellcheck が日本語を含む行を出力しようとすると
  # "commitBuffer: invalid argument" で途中で切れる（claude-container#123）。ロケールが
  # 未指定のときだけ UTF-8 を補う（利用者の設定は上書きしない）。
  if [ -z "${LC_ALL:-}" ] && [ -z "${LANG:-}" ]; then
    export LC_ALL=C.UTF-8
  fi

  # shellcheck の版を表示し、CI（.github/workflows/ci.yml）の固定版と違えば WARNING を出す。
  # 版差で指摘の有無が変わる（0.10.0 の SC2317 と 0.11.0 の SC2329 等）ため、NG の原因の
  # 切り分けを早くする目的で、失敗にはしない（claude-container#123）。
  shellcheck_version=$(shellcheck --version | awk '/^version:/ { print $2 }')
  ci_shellcheck_version=$(sed -nE 's/^[[:space:]]*SHELLCHECK_VERSION:[[:space:]]*"([^"]+)".*/\1/p' \
    .github/workflows/ci.yml 2>/dev/null | head -n 1)
  echo "shellcheck ${shellcheck_version:-不明}"
  if [ -n "$ci_shellcheck_version" ] && [ "$shellcheck_version" != "$ci_shellcheck_version" ]; then
    echo "WARNING: shellcheck の版（${shellcheck_version:-不明}）が CI の固定版（$ci_shellcheck_version）と異なります。版差で指摘が増減することがあります（claude-container#123）。" >&2
  fi
  ```

- [ ] **Step 3: `lint.sh` 自身が両版の shellcheck を通ることを確認する**

  ```bash
  LC_ALL=C.UTF-8 shellcheck lint.sh; echo "rc(0.10.0)=$?"
  "$sc/shellcheck-v0.11.0/shellcheck" lint.sh; echo "rc(0.11.0)=$?"
  ```

  Expected: どちらも出力なし、rc=0。

- [ ] **Step 4: 4 通りの実行で期待どおりの出力になることを確認する**

  ```bash
  # (a) 0.10.0、ロケール未設定: 版表示 + WARNING + lint OK
  env -u LANG -u LC_ALL LINT_SKIP_COMPOSE=1 ./lint.sh; echo "rc=$?"
  # (b) 0.11.0（CI と同じ版）: 版表示、WARNING なし、lint OK
  PATH="$sc/shellcheck-v0.11.0:$PATH" LINT_SKIP_COMPOSE=1 ./lint.sh 2>&1 | grep -E '^(shellcheck |WARNING: shellcheck|lint )'
  # (c) ci.yml が読めない: 版表示だけで WARNING なし（一時的に退避して確認し、必ず戻す）
  mv .github/workflows/ci.yml "$sc/../ci.yml.bak" && LINT_SKIP_COMPOSE=1 ./lint.sh 2>&1 | grep -E '^(shellcheck |WARNING: shellcheck)'; mv "$sc/../ci.yml.bak" .github/workflows/ci.yml; git status --short .github
  # (d) ロケールの補完で切れなくなる（Step 1 の probe を lint.sh と同じ条件で）
  env -u LANG -u LC_ALL LC_ALL=C.UTF-8 shellcheck "$sc/../lint-locale-probe.sh" 2>&1 | grep -c commitBuffer
  ```

  Expected:
  - (a) 標準出力に `shellcheck 0.10.0`、標準エラーに `WARNING: shellcheck の版（0.10.0）が CI の固定版（0.11.0）と異なります…` と compose スキップの WARNING、最後に `lint OK`、rc=0。
  - (b) `shellcheck 0.11.0` と `lint OK` だけで、`WARNING: shellcheck` の行が無い。
  - (c) `shellcheck 0.10.0` だけ。`git status --short .github` は空（戻し忘れ検出）。
  - (d) `0`。

- [ ] **Step 5: コミット**

  ```bash
  rm -f "$sc/../lint-locale-probe.sh"
  git add lint.sh
  git commit -m "fix: lint.sh が shellcheck の版を表示し CI の固定版との差を WARNING にする

コンテナ内の shellcheck 0.10.0 と CI の 0.11.0 で指摘が変わり、NG の原因が
版差なのか変更なのかを切り分けにくかった。版を表示し、ci.yml の
SHELLCHECK_VERSION と違えば WARNING を出す（判定は変えない）。
併せて LANG・LC_ALL 未設定のときだけ LC_ALL=C.UTF-8 を補い、日本語を含む行で
shellcheck の出力が commitBuffer エラーで切れないようにする（#123）。"
  ```

## Task 3: README の `lint.sh` 段落を更新する

**Files:**
- Modify: `README.md`（「変更後の確認」節、`lint.sh` は、リポジトリ内の bash スクリプト… で始まる段落）

- [ ] **Step 1: 段落の末尾に次を足す**

  既存の段落「…（Compose を実行できない環境用。CI では指定しない）。」の直後に、同じ段落として続ける。

  ```markdown
  実行時に shellcheck の版を表示し、CI（`.github/workflows/ci.yml` の `SHELLCHECK_VERSION`）の固定版と違えば WARNING を出す（判定は変えない。版差で指摘の有無が変わることがあるため、NG の原因の切り分け用）。コンテナ内の開発イメージは Debian パッケージの shellcheck を使うため CI と版が違うことがあり、この WARNING は想定内。`LANG`・`LC_ALL` とも未設定のときは `LC_ALL=C.UTF-8` を補い、日本語を含む行で shellcheck の出力が途中で切れないようにする。
  ```

- [ ] **Step 2: lint と表記を確認する**

  ```bash
  LINT_SKIP_COMPOSE=1 ./lint.sh | tail -n 1
  grep -n 'SHELLCHECK_VERSION' README.md
  ```

  Expected: `lint OK`。README に追記行が 1 箇所。

- [ ] **Step 3: コミット**

  ```bash
  git add README.md
  git commit -m "docs: lint.sh の版表示・WARNING・ロケール補完を README に書く"
  ```

## Task 4: 最終検証と PR

- [ ] **Step 1: 両版で全体 lint（compose 検証はコンテナ内で not run）**

  ```bash
  env -u LANG -u LC_ALL ./lint.sh; echo "rc=$?"
  PATH="$sc/shellcheck-v0.11.0:$PATH" ./lint.sh; echo "rc=$?"
  ```

  Expected: どちらも `lint OK`、rc=0。compose 検証は podman 不在の WARNING でスキップされる（README の説明どおり。`not run` として報告し、CI の結果で補う）。

- [ ] **Step 2: `./test-build.sh --launcher-only`**

  `lint.sh` と `tests/test-runtime.sh` の変更は launcher の挙動に触れないので必須ではないが、CI と同じ組み合わせを事前に確認する。

  ```bash
  TMPDIR=/tmp ./test-build.sh --launcher-only; echo "rc=$?"
  ```

  Expected: rc=0。失敗したら変更との関係を切り分けてから報告する（既知の環境差なら `not run` 扱いにせず、失敗として報告する）。

- [ ] **Step 3: 持ち主の承認後に push と PR**

  push は不可逆・対外操作なので持ち主に確認してから行う。PR 本文には「検証」節を置き、(a)(b) の実行結果と compose 検証 `not run` の理由を書く。

  ```bash
  git push -u origin fix/lint-shellcheck-version-123
  (
    set +x
    github_pat=$(cat "$GITHUB_MAIN_PAT_FILE") || exit 1
    [ -n "$github_pat" ] || exit 1
    GH_TOKEN="$github_pat" gh pr create --repo jj1xgo/claude-container \
      --base main --head fix/lint-shellcheck-version-123 \
      --title "fix: shellcheck の版差で lint が緑にならない問題を直す（#123）" \
      --body-file "$sc/../pr-body-123.md"
  )
  ```

  PR 本文の末尾は `Closes #123` と、system reminder の帰属行。

- [ ] **Step 4: 二重レビュー**

  `.claude/AGENTS.md` の「レビュー」項に従う。Codex（`codex exec --sandbox read-only`、stdin は `< /dev/null`）を background で先に起動し、Claude 側は CI の結果（0.11.0 で `lint.sh` が WARNING なしで通ること）を GitHub で確認する。マージはレビューした Claude セッションが host で行う（コンテナ内からはマージしない）。

## 自己レビュー

- Issue の 4 候補のうち、directive 併記・版表示 WARNING・`LC_ALL` の 3 つを採り、イメージの 0.11.0 固定は不採用（理由は「構成」に記載）。
- 版差以外の SC2317 が将来出た場合は directive の対象外なので、通常どおり NG になる（抑止の範囲は `finish()` の 1 関数だけ）。
- `lint.sh` の判定と終了コードは不変。追加はすべて表示のみ。
- worktree で作業するため hook が効かない点を「作業場所」に明記した。

実装: Sonnet。理由: 0.10.0 / 0.11.0 の照合と `LANG` 未設定の再現はコンテナ内でしか実測できず（判定基準 1）、設計判断は本計画で確定済み。
