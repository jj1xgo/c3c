# メイン PAT の `Actions` 権限の扱いを README に書く（#222）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Context

README「GitHub トークンの配線」節は、メイン PAT の権限として `Issues`・`Pull requests`・`Contents`・`Workflows` を扱っているが、`Actions` には触れていない。一方 `docs/runtime-ci.md`「手動実行」節は `gh workflow run runtime.yml` を案内しており、コンテナの中からこれを行うにはメイン PAT に `Actions: Read and write` が要る（無いと HTTP 403 で拒否される）。fine-grained PAT の `Actions` は Read か Read and write の二択で、手動起動だけに絞れない。付けるとほかの操作もまとめて付く。利用者がこの権限を付けるかを判断する材料を README に書く。

**Goal:** README を読んだ利用者が、メイン PAT に `Actions: Read and write` を付けるかを、増える操作と自分のリポジトリの workflow の性質から判断できるようにする。

**Architecture:** 製品の文書だけを変える docs の変更。正本の段落を README「git push を使う場合」の workflow の段落群の直後に 1 つ置き、PAT の設定手順・対応表・セキュリティモデル・`docs/runtime-ci.md` からはそこへ短く参照する。製品の挙動、`SECURITY-CLAIMS.md`、`docs/development-invariants.md` は変えない（c3c は PAT の権限を検査しないので、保証文も不変条件も増えない）。

**Tech Stack:** Markdown（README.md、docs/runtime-ci.md）、`./lint.sh`

**Spec:** [#222](https://github.com/jj1xgo/c3c/issues/222)。2026-10-18 の持ち主との会話で決めた方向（下の既決事項）。

## 既決事項（持ち主、2026-10-18）

- README での立場は「用途に応じて（判断の材料を示す）」。`Workflows` のように「推奨しない」とは書かない。
- 書くのは判断の材料: コンテナから workflow を手動で起動するなら必要、付けると増える操作、workflow が secrets や OIDC を使う・fork からの PR を受けるリポジトリでは影響を確かめてから付ける、使わない用途なら付けない。
- 保守者個人の PAT の設定は README にも、この計画の公開の写しにも書かない（README は利用者向けで、`.claude/AGENTS.md`「公開リポジトリのファイル区分ルール」の 3 に当たる）。

## Global Constraints

- 日本語で書く。権限名・コマンド名・URL・API のパスは原文のまま（README.md「表記」節）。
- 権限名は GitHub の表記どおり `Actions`（Repository permissions）、値は `Read and write`。出典は https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens#repository-permissions-for-actions （Write access の一覧を 2026-10-18 に WebFetch で確認: artifacts・caches の DELETE、jobs と runs の rerun、`oidc/customization/sub` の PUT、runs の DELETE・approve・cancel・force-cancel・logs の DELETE、workflows の disable・dispatches・enable）。
- 増える操作として書くのは、上の一覧にある操作だけ。一覧に無い操作（secrets の読み書きなど）は書かない。
- 拒否のエラーは「HTTP 403 で拒否される」までにとどめ、未確認のエラーメッセージの文字列は書かない。
- 「c3c が `Actions` 権限を検査する・防ぐ」と読める書き方をしない（c3c は PAT の権限を検査しない）。
- 既存の文は書き換えない。変更は各 Step に書いた位置への挿入（文末・セル末への追記を含む）だけにする。
- 節名は「workflow の手動起動（`Actions`）」で、正本の段落の見出し（Task 1 Step 2）と参照 4 か所（Task 1 Step 3〜5 の README、Step 6 の `docs/runtime-ci.md`）を揃える。
- 挙動は変わらないので SemVer のタグは提案しない（AGENTS.md「バージョン管理」）。
- 設定・文書だけの計画なので superpowers:test-driven-development は読み込まない（理由は実装者が台帳か報告に 1 行書く）。

## Review Focus

1. 「c3c が防ぐ」「`Actions` を付けなければ CI に影響しない」と読める文が無いこと → Task 1 Step 8 の読み直しで確認する。
2. 公式の一覧に無い操作を書いていないこと → Task 1 Step 8 で、正本の段落の操作を Global Constraints の一覧と 1 つずつ照合する。
3. 既存の文の意味を変えていないこと → Task 1 Step 7 の 1 文字単位の `git diff --word-diff` で `[-` が 0 件。
4. Markdown の表が壊れないこと（セル内に改行や `|` を入れない）→ Task 1 Step 7 の grep で対応表の行が 1 行のまま ` |` で終わる。
5. 節名の参照が揃っていること → Task 1 Step 7 の grep の件数。

---

### Task 0: 作業ツリーと計画の写し

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

**Files:**
- Create: `docs/superpowers/plans/2026-10-18-actions-permission-docs-222.md`（この計画の写し。`.claude/AGENTS.md` の計画の置き場所の規則による）

- [ ] **Step 1:** `git -C /workspace fetch -q origin` の後、`git -C /workspace rev-parse origin/main` の SHA を基点として控える。`/workspace` の未コミットの `.c3c/allowed-domains.txt` は持ち主の指示で残しているので触らない（作業ツリーは origin/main から作るので、`/workspace` の main が遅れていても影響しない）。`/workspace` で `git -c worktree.useRelativePaths=true worktree add .worktrees/actions-permission-222 -b fix/actions-permission-222 <基点の SHA>` を実行する（相対パスにしておくと、ホストからも同じ worktree を使える。README「ホストとコンテナをまたぐ git worktree」）。`git -C /workspace check-ignore -q .worktrees/actions-permission-222` → rc 0（ignore 済み）を確かめる。以降の編集とコマンドはすべてこの作業ツリーで行う。
- [ ] **Step 2:** この計画ファイル（`~/.claude/plans/twinkling-tickling-lark.md`）を Step 1 の作業ツリーの `docs/superpowers/plans/2026-10-18-actions-permission-docs-222.md` に写して commit する: `docs: #222 の計画を置く`。c3c は計画レビューの生の出力の保存先を定めていないので、記録節を正本とし、生の出力は写さない（plan-review 手順 7）。commit の前に写しを読み、保守者個人の PAT の設定、ホストのパス、private リポジトリの名前が無いことを確かめる（`.claude/AGENTS.md` の計画の置き場所の規則）。あれば写しから消し、元の計画ファイルにも同じ修正をする。

### Task 1: README と docs/runtime-ci.md に `Actions` の扱いを書く

**Files:**
- Modify: `README.md`（「GitHub トークンの配線」節の手順 1、「git push を使う場合」の workflow の段落群、「メイン PAT / MCP・issues 用 PAT 対応表」、「セキュリティモデル」節の `Contents: write` の段落）
- Modify: `docs/runtime-ci.md`（「手動実行」節）

位置は行番号でなく、引用した既存の文字列で探す。

- [ ] **Step 1:** 位置を確かめる。`grep -n 'workflow ファイルを変える commit は、コンテナ内では commit までにとどめ' README.md`、`grep -n '`Workflows` は付けない（`.github/workflows/` を変える push はホストから行う' README.md`、`grep -n '^| 一般的に許可してよいパーミッション |' README.md`、`grep -n '`Workflows` を付けると、workflow の定義まで書き換えられる' README.md`、`grep -n '^gh run download' docs/runtime-ci.md` → Expected: それぞれ 1 件。

- [ ] **Step 2: 正本の段落を足す。** README の「workflow ファイルを変える commit は、コンテナ内では commit までにとどめ、」で始まる段落（末尾が `（[#195](https://github.com/jj1xgo/c3c/issues/195)）。`）の直後に、空行を挟んで次の段落を挿入する（逐語）。

  ```markdown
  **workflow の手動起動（`Actions`）**: コンテナ内から workflow を手動で起動する（例: [実コンテナの手動・定期検証](docs/runtime-ci.md)の `gh workflow run`）には、メイン PAT に `Actions: Read and write`（Repository permissions。[公式の権限表](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens#repository-permissions-for-actions)）が要る。無いと GitHub に HTTP 403 で拒否される。この権限は手動起動だけに絞れず、付けると、実行の取り消し・再実行に加えて、fork からの PR の workflow の実行の承認、workflow の無効化・有効化、実行・ログ・成果物・キャッシュの削除、OIDC の subject claim の設定の変更も、コンテナ内からできるようになる。workflow の定義は書き換えられない（それには `Workflows` の権限が要る）。c3c は PAT の権限を検査しないので、付けるかは対象リポジトリの workflow を見て利用者が決める。secrets や OIDC（`id-token: write`）を使う workflow があるリポジトリ、または fork からの PR を受け付けるリポジトリでは、付ける前に次を確かめる: 手動で起動できる workflow が、`Contents: write` で書き換えられるスクリプトを実行するか、その実行に secrets や OIDC のトークンが渡るか。fork からの PR の実行の承認待ちをコンテナ内から外したとき、その実行に何が渡るか。OIDC の subject claim の設定を変えたとき、クラウド側がトークンを受け入れる条件がどう変わるか。コンテナから起動する必要が無ければ付けず、ホストの端末か GitHub の Web 画面から起動する。
  ```

- [ ] **Step 3: 手順 1 から参照する。** README の手順 1 の「Repository permissions:」の行の末尾、`` `Workflows` は付けない（`.github/workflows/` を変える push はホストから行う。後述「git push を使う場合」） `` の直後に、次を追記する（逐語。先頭の句点を含む）。

  ```markdown
  。`Actions` は、コンテナ内から workflow を手動で起動するときだけ `Read and write` を付ける（付けると増える操作は後述「workflow の手動起動（`Actions`）」）
  ```

- [ ] **Step 4: 対応表から参照する。** README の対応表の `| 一般的に許可してよいパーミッション |` の行で、メイン PAT のセルの末尾 `（`Contents: write` を含めると push・PR承認・マージが明示読みで可能になる点を理解した上で）` の直後（セル区切りの ` |` の前）に、次を追記する（逐語。改行を入れない）。

  ```markdown
  。`Actions: Read and write` は workflow をコンテナ内から手動で起動する場合に限る（「workflow の手動起動（`Actions`）」参照）
  ```

- [ ] **Step 5: セキュリティモデルから参照する。** README「セキュリティモデル」節の、`` `SECRETS_DIR/GITHUB_MAIN_PAT`（前述「git push を使う場合」）に `Contents: write` を付与した場合 `` で始まる段落の末尾 `` `Workflows` を付けると、workflow の定義まで書き換えられる（「git push を使う場合」参照）。 `` の直後に、次を追記する（逐語。同じ段落の続き）。

  ```markdown
  `Actions: Read and write` も付けると、`Contents: write` で書き換えたブランチで workflow を手動で起動でき、workflow の無効化、実行の記録の削除、fork からの PR の実行の承認もできる（「workflow の手動起動（`Actions`）」参照）。
  ```

- [ ] **Step 6: `docs/runtime-ci.md` から参照する。** 「手動実行」節のコードブロック（最終行が `gh run download -R jj1xgo/c3c <run-id> --dir ./runtime-results`）の閉じの ```` ``` ```` の直後に、空行を挟んで次の段落を挿入する（逐語）。

  ```markdown
  コンテナ内から `gh workflow run` を使うには、メイン PAT を gh に明示的に渡し、その PAT に `Actions: Read and write` が要る（README「workflow の手動起動（`Actions`）」参照）。private リポジトリでは、実行の一覧・ログ・成果物の取得にも `Actions: Read` が要る。
  ```

- [ ] **Step 7: 機械的に確かめる。**
  - `./lint.sh; echo rc=$?` → Expected: `rc=0`。podman が無い環境では Compose 検証のスキップの WARNING が出るので、その検証は `not run`（理由: podman が無い）と報告する。
  - `git diff --word-diff=plain --word-diff-regex=. <基点の SHA> -- README.md docs/runtime-ci.md > /tmp/wd-222.txt; echo git_rc=$?; grep -c '\[-' /tmp/wd-222.txt` → Expected: `git_rc=0` と `0`（1 文字単位で、削除が無い）。空白区切りの既定の word-diff は文末への追記でも削除を数えるので使わない。0 でなければ、`grep -n '\[-' /tmp/wd-222.txt` で行を見て、消えた文字が直後の `{+…+}` の先頭にそのまま出ているだけか（区切りのずれ）、本当に既存の文字が消えたかを読み分け、後者なら直す。
  - `grep -c 'workflow の手動起動（`Actions`）' README.md docs/runtime-ci.md` → Expected: `README.md:4`、`docs/runtime-ci.md:1`。
  - `grep -n '^| 一般的に許可してよいパーミッション |' README.md` → Expected: 1 件で、行末が ` |`。
  - `grep -n '^| 持たせるべきでないパーミッション |' README.md` → Expected: 1 件で、行末が ` |`（変えていないことの確認）。

- [ ] **Step 8: 読み直す。** `git diff <基点の SHA> -- README.md docs/runtime-ci.md` を読み、Review Focus 1・2 を確かめる。2 は、Step 2 の段落に出てくる操作（取り消し・再実行・実行の承認・無効化・有効化・実行・ログ・成果物・キャッシュの削除・OIDC の subject claim の設定の変更・手動起動）を Global Constraints の一覧の項目と 1 つずつ対応させる。対応しない操作があれば止まって報告する。

- [ ] **Step 9: commit する。** `git add README.md docs/runtime-ci.md && git commit -m "docs: メイン PAT の Actions 権限で増える操作と付けるかの判断を README に書く（#222）"`（本文に、区分が境界であること、計画レビュー済みであることを書く。attribution の行を付ける）。

### Task 2: PR 前の二重レビューと PR の作成

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review（Step 2〜3 のレビュー結果の受け取り）

- [ ] **Step 1:** 範囲 `<Task 0 Step 1 の基点の SHA>..<Task 1 Step 9 の SHA>` の差分（`git diff <SHA>..<SHA>`。`HEAD` を使わない。公開する計画の写しも範囲に入る）をファイルにし、Claude（`~/.agents/skills/claude-review/SKILL.md` の手順、headless の `claude -p`）→ Codex（`~/.agents/skills/codex-review/SKILL.md` の手順、`codex-review.sh --provider openai -m gpt-6-astra`、root は作業ツリー）の順に、間に別の作業をはさまず background で起動する。全員が終わるまで作業ツリーを編集しない。
- [ ] **Step 2:** 結果を受け取り、Critical と Important を直して commit し、出したレビュアーにだけ確認限定巡を頼む（claude-review skill の手順 4、codex-review skill の手順 3）。両方に頼むときは Codex → Claude の順に、続けて background で起動する。修正のたびに Task 1 Step 7 を実行し直す。
- [ ] **Step 3:** vault `knowledge/モデル別の実績.md`「本運用の記録」節に、この作業の PR 前レビューの行を事実だけ足す（所要、指摘、手戻り。残量は「未取得（持ち主の判断）」）。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch（Step 4〜5）

- [ ] **Step 4:** push の前に持ち主に確認する（`.claude/AGENTS.md`「セキュリティに関する保守者の行動規範」）。確認が取れたら `git push -u origin fix/actions-permission-222`。
- [ ] **Step 5:** PR を作る（`gh pr create`、メイン PAT の明示読み）。タイトル `docs: メイン PAT の Actions 権限の扱いを README に書く（#222）`。本文に `Closes #222`、区分（境界）、計画レビュー済みであること、両レビューの要約と判定、未対応の Minor、検証結果と `not run`（理由付き）、署名 `— <実効モデル> (c3c)` を書く。Claude と Codex のレビュー全文を PR コメントに 1 本ずつ投稿する。
- [ ] **Step 6:** プロジェクトの `handover` skill で handover を作り、PR 後の二重レビューとマージを、作成に関わっていない対話セッションに渡すことを書く。この計画を書いたセッションと実装したセッションは、PR 後のレビューもマージもしない。

## 計画レビューの記録

- Self-Review: 節名の参照の数え方（見出し 1 + 参照 4）、Task 0 Step 2 の文、Task 2 のレビュー範囲の基点を修正
- Codex（gpt-6-astra、所要 114 秒）: 修正後に渡せる
  - I1 公開する計画の写しに保守者個人の PAT の設定が残る。レビュー範囲から写しが外れる → 採用（Context と既決事項から除き、Task 0 Step 2 に公開前の読み直し、レビュー範囲の基点を origin/main に）
  - I2 既定の word-diff は文末への追記でも削除を数え、Step 7 の Expected を満たせない → 採用（1 文字単位に変更。git の終了コードも確かめる）。計画者が使い捨てのリポジトリで実測し、既定 2 件・1 文字単位 0 件を確認
  - M1 「確かめること」が操作できることの確認になっている → 採用（評価する対象を明示する文に）
  - M2 main と origin/main の一致の確認が曖昧 → 採用（origin/main の SHA を基点に控え、そこから作業ツリーを作る）
  - 参考: Codex の sandbox では `./lint.sh` が `/dev/fd/63` を開けず rc 1（環境の制約。実装時はコンテナで実行する）
- Claude（claude-opus-5-5、session `9f31a977-ef2d-48d1-bb8b-e5b6d5910e60`、所要 142 秒）: 修正後に渡せる
  - I1 Codex の I2 と同じ → 採用（同上。#195 の前例の形）
  - M1 セキュリティモデルの追記に、`Contents: write` と組み合わせた手動起動が無い → 採用
  - M2 前例の `worktree.useRelativePaths=true` と `check-ignore` が無い → 採用（`.worktrees/` は `.git/info/exclude` で ignore 済みを計画者が確認）
  - M3 確認限定巡の起動順が無い → 採用
  - M4 `docs/runtime-ci.md` の追記が `gh workflow run` だけ → 採用（private リポジトリでの `Actions: Read` を 1 文）
  - M5 handover の Step に skill の指定が無い → 採用
- 確認限定巡 1: Codex（I1・I2、所要 15 秒）→ どちらも直った、実装に渡せる
- 確認限定巡 1: Claude（I1、`--resume`、所要 16 秒）→ 直った、実装に渡せる

区分: 境界（メイン PAT の権限と、その危険の説明を変える文書。グローバル指示「規則・権限・レビュー手順・秘密の扱いを変える文書は、docs でも境界にする」による）
推奨実装: Opus（c3c の Claude Code 面の既定は Sonnet だが、権限の危険の説明はセキュリティ境界に当たり、Opus を推す条件に該当する。Codex を推さないのは、判定順の 1〜5 に当たらず、この計画が Claude Code 面で始まったため。逐語の文まで計画に書いてあるので、Sonnet でも実行はできるが、Step 8 の読み直しと PR 前レビューの受け取りに危険の判断が残る）
実装: Opus（持ち主指定、2026-10-18。計画を書いたコンテナの Opus 5.5 のセッションがそのまま実装する。実行方法は executing-plans）
