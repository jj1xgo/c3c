# `--read-only` の「断る」に、拒否の場面は未観測という但し書きを足す（#216）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

コードを変えない文書だけの計画なので、test-driven-development は読み込まない（実装者は読み込まない理由を台帳か報告に 1 行書く）。

**Goal:** SECURITY-CLAIMS.md と README.md の「`never` にすると Codex の sandbox の外での実行の要求は断られる」という主張に、根拠は `approval_policy = "never"` の仕様で、拒否の場面そのものは実測していないことを書き足し、主張と根拠の範囲を文書全体で揃える（jj1xgo/c3c#216）。

**Architecture:** 主張の本文は変えず、但し書きを 3 か所に足す。SECURITY-CLAIMS.md C-3 の「根拠・検証範囲」の段落に 2 行、README.md「Codex CLI を対話で使う」節の該当文に括弧書きを 1 つ、README.md の `codex exec` の手順 5 の説明の括弧の中に 1 文。コード・テスト・`docs/development-invariants.md` は変えない。

**Tech Stack:** Markdown、`./lint.sh`

**Spec:** この計画の「## 背景」節（brainstorming で持ち主が 2026-10-18 にチャットで承認した、小さな変更の文面と、計画レビューの後に持ち主が足すと決めた 3 か所目）

## 背景

- PR #210（#207）は、`--read-only` の Codex を `--ask-for-approval never` で起動するようにした。その PR 後レビューで、Claude と Codex が同じ Minor を指摘した（PR #210 の本文の「PR 後レビュー」節）。
  - 指摘の中身: SECURITY-CLAIMS.md の「`--read-only` では承認の方針を `never` にし、モデルが求める sandbox の外での実行を断る（#207）」と、README.md の「人にも自動レビュー（…）にも回らず、失敗としてモデルに返る」は、`never` の仕様に基づく主張である。
  - 実測で確かめたのは、書き込みが失敗したことと、外での実行が起きなかったことまで。昇格の要求が出て断られる場面そのものは、exec でも TUI でも観測していない。PR #210 の本文の「検証」にはこの区別があるが、文書の「根拠・検証範囲」には無い。
- 2026-10-18 に持ち主が直すと決め、SECURITY-CLAIMS.md と README.md の 510 行付近の 2 か所の文面を承認した。
- 計画レビューで、README.md の `codex exec` の手順 5 の説明（今の 503 行）の末尾「`never` に固定すると、外での実行の要求は断られる」も同じ根拠の主張だと分かった（Claude I1）。持ち主が 2026-10-18 に、ここにも足すと決め、Task 1 Step 4 の文面を承認した。
- 製品の文書で `断る`・`断られる`・`失敗としてモデルに返る` が当たるのは、SECURITY-CLAIMS.md の 103 行、README.md の 503 行・510 行の 3 か所だけ（計画レビューで確認）。
- `docs/development-invariants.md` の Codex 経路の行は「read-only を `on-request` に戻さない（…承認されうる、#207）」という形で、拒否を主張していない。変えない。
- 文書を検査するテストは、`test-build.sh` の README「環境変数」節の表の照合（1603 行付近）だけで、今回の 3 か所には掛からない。

## Global Constraints

- 変更するファイルは `SECURITY-CLAIMS.md` と `README.md` の 2 つだけ（計画の写しの `docs/superpowers/plans/2026-10-18-read-only-never-caveat-216.md` を除く）。
- 足す文面は Task 1 のとおりに逐語で入れる。主張の本文（「断る」「失敗としてモデルに返る」「断られる」）は消さず、書き換えない。
- 足す文面は持ち主が承認したもの。レビューの指摘でこの文面を変えるときは、直す前に持ち主に示して承認を得る。文面を変えたら、Task 1 Step 5 の grep の文字列と Expected も直す。
- 公開側に置く計画の写しには、`~` 配下の個人設定のパス、レビューの session id、一時ファイルのパスを書かない（前例: `2026-10-17-launcher-meta-stub-213.md`）。計画レビューの生の出力は公開側に置かず、この計画の「計画レビューの記録」節を正本にする。
- `/workspace` の main の作業ツリーにある未コミットの `.c3c/allowed-domains.txt`（`+api.typesafe.ai`）は触らない。作業は worktree で行う。
- `./lint.sh` は rc 0。コンテナ内（podman が無い）では、`lint.sh` が自分で Compose 検証を飛ばして出す `WARNING: podman が見つからないため compose config 検証をスキップしました` と、shellcheck の版が CI の固定版と違うときの版の WARNING だけを許す（README.md「変更後の確認」節で、コンテナ内では想定内とされている）。このとき Compose 検証は `not run`（理由: podman が無い）とし、PR の CI の `lint とビルド不要のテスト` で確かめる。
- SemVer のタグは提案しない（文書だけの変更。root `AGENTS.md`「バージョン管理」）。
- push と PR 作成は、実行前に持ち主に確認する（`.claude/AGENTS.md`「セキュリティに関する保守者の行動規範」）。

## Review Focus

1. 足した文が、元の主張と矛盾して読めないこと（「断る」と書いた直後に「断る場面は観測していない」と書くので、主張を撤回したように読めないか）→ 足す文は「根拠」と「実測の範囲」を述べる形にし、主張は残す（Task 1 Step 2〜4）。
2. 実測の範囲を、実際より広く書かないこと → PR #210 の「検証」の 4（TUI で `touch` が `Read-only file system` で失敗、ホストに `.probe-207` が無い）と exec の実測（ファイルが作られず、`touch` の実行イベントが出なかった）の範囲に限る。README の 510 行付近の括弧書きは「書き込みが止まったことまで」と短く書き、外での実行が起きなかったことは書かない（狭く書く分には範囲を超えないので、承認済みの文面のまま採る）（Task 1 Step 2〜4）。
3. 3 か所で、言い回しが食い違わないこと → 3 か所とも「`never` の仕様に基づく」と「断られる場面そのものは観測していない」を使う（Task 1 Step 5 の grep）。
4. 置き換えの対象の文字列が 1 か所だけに当たること → Task 1 Step 1 で件数を確かめる。
5. Markdown の段落が崩れないこと（SECURITY-CLAIMS.md の「根拠・検証範囲」は手で折り返した 3 行の段落）→ 足す行は段落の最後の行の直後に続け、空行を入れない（Task 1 Step 2）。

---

### Task 0: worktree を作り、計画の写しを commit する

**Files:**
- Create: `docs/superpowers/plans/2026-10-18-read-only-never-caveat-216.md`（この計画の写し）

- [ ] **Step 1: worktree を作る**

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

```bash
cd /workspace && git fetch origin && git worktree add -b docs/read-only-never-caveat-216 .worktrees/read-only-never-caveat-216 origin/main
git -C /workspace/.worktrees/read-only-never-caveat-216 rev-parse HEAD
```

Expected: `.worktrees/read-only-never-caveat-216` ができる。2 行目の SHA を `BASE` として控える（以後の確認で使う。`origin/main` が後で進んでも、比べる基点はこの SHA）。

- [ ] **Step 2: 計画の写しを置く**

計画レビューの記録節まで確定した計画ファイルを、Write で `docs/superpowers/plans/2026-10-18-read-only-never-caveat-216.md` に写す。写すときに、記録節の生の出力の一時パスと session id を「ハーネスの一時出力（公開しない）」に置き換える。

```bash
cd /workspace/.worktrees/read-only-never-caveat-216
grep -cE '~/|/home/|/tmp/|session `' docs/superpowers/plans/2026-10-18-read-only-never-caveat-216.md
```

Expected: `2`（当たるのは、この grep の行自身と、記録節の M3 の行だけ。どちらもパスではなく検索の文字列）。ほかの行に当たったら、その行を直してからもう一度確かめる。

- [ ] **Step 3: commit する**

```bash
git add docs/superpowers/plans/2026-10-18-read-only-never-caveat-216.md
git commit -m "docs: #216 の計画を足す"
git status --short
```

Expected: commit が 1 つでき、`git status --short` が空。

### Task 1: 但し書きを足す

**Files:**
- Modify: `SECURITY-CLAIMS.md`（C-3 の「**根拠・検証範囲**」の段落。今の 106〜108 行）
- Modify: `README.md`（`codex exec` の手順 5 の説明。今の 503 行。「Codex CLI を対話で使う」節の最初の段落。今の 510 行）

作業はすべて `/workspace/.worktrees/read-only-never-caveat-216` で行う。

- [ ] **Step 1: 置き換えの対象が 1 か所ずつであることを確かめる**

```bash
grep -c '現在の受入状況は' SECURITY-CLAIMS.md
grep -c '失敗としてモデルに返る。信頼済みの' README.md
grep -c '外での実行の要求は断られる）。' README.md
```

Expected: どれも `1`。`1` でなければ止まって持ち主に報告する。

- [ ] **Step 2: SECURITY-CLAIMS.md に 2 行足す**

次の 3 行（今の 106〜108 行）の直後に、空行を入れずに 2 行を足す。

今:

```markdown
**根拠・検証範囲**: `c3c`、`entrypoint.sh`、`codex-mcp-audit.py`、`compose.yml`、
`compose.codex-preflight.yml` と各 Codex 回帰テスト。実装の契約と実機受入は区別し、現在の受入状況は
[README の Codex 節](README.md#codex-cli-を対話で使う) を参照する。
```

後:

```markdown
**根拠・検証範囲**: `c3c`、`entrypoint.sh`、`codex-mcp-audit.py`、`compose.yml`、
`compose.codex-preflight.yml` と各 Codex 回帰テスト。実装の契約と実機受入は区別し、現在の受入状況は
[README の Codex 節](README.md#codex-cli-を対話で使う) を参照する。
`--read-only` で sandbox の外での実行を断るという主張は、Codex の `approval_policy = "never"` の仕様に基づく。
実測で確かめたのは、read-only での書き込みが失敗し、sandbox の外での実行が起きなかったことまでで、要求が断られる場面そのものは観測していない（#207）。
```

- [ ] **Step 3: README.md の 510 行付近に括弧書きを足す**

`失敗としてモデルに返る。信頼済みの` を次に置き換える（ほかの部分は変えない）。

```text
失敗としてモデルに返る（`never` の仕様に基づく説明。実測で確かめたのは書き込みが止まったことまでで、要求が断られる場面そのものは観測していない）。信頼済みの
```

- [ ] **Step 4: README.md の 503 行付近に 1 文足す**

`外での実行の要求は断られる）。` を次に置き換える（ほかの部分は変えない）。

```text
外での実行の要求は断られる。これは `never` の仕様に基づく説明で、断られる場面そのものは観測していない）。
```

- [ ] **Step 5: 差分と言い回しを確かめる**

`<BASE>` は Task 0 Step 1 で控えた SHA。このコマンドは作業ツリーと `BASE` を比べるので、commit の前でも後でも同じ結果になる。

```bash
git diff --stat <BASE> -- SECURITY-CLAIMS.md README.md
git diff --word-diff=plain --word-diff-regex=. <BASE> -- SECURITY-CLAIMS.md README.md | grep -c '\[-'
grep -c '断られる場面そのものは観測していない' SECURITY-CLAIMS.md README.md
grep -c '仕様に基づく' SECURITY-CLAIMS.md README.md
grep -c '断る（#207）' SECURITY-CLAIMS.md
grep -c '失敗としてモデルに返る' README.md
grep -c '外での実行の要求は断られる' README.md
```

Expected:
- 1 つ目: `README.md` と `SECURITY-CLAIMS.md` の 2 ファイルで、`2 files changed, 4 insertions(+), 2 deletions(-)`（README は行の途中への挿入なので、行単位では 2 行の置き換えに見える。SECURITY-CLAIMS.md は 2 行の追加だけ）。
- 2 つ目: `0`（文字単位で見て、消した文字が無い。日本語は空白で区切られないので、`--word-diff-regex=.` を付けないと行全体が 1 語になり、`[-` が出てしまう）。
- 3 つ目: `SECURITY-CLAIMS.md:1`、`README.md:2`。
- 4 つ目: `SECURITY-CLAIMS.md:1`、`README.md:2`（今の両ファイルに `仕様に基づく` は無い。計画レビューの時点で確認する）。
- 5 つ目: `1`（主張の本文が残っている）。
- 6 つ目: `1`。
- 7 つ目: `1`。

- [ ] **Step 6: lint**

Run: `./lint.sh; echo rc=$?`
Expected: `rc=0`。WARNING は Global Constraints で許した 2 種類だけ。Compose 検証は `not run`（podman が無い）として報告に書く。

- [ ] **Step 7: commit**

```bash
git add SECURITY-CLAIMS.md README.md
git commit -m "docs: --read-only の「断る」に、拒否の場面は実測していないという但し書きを足す（#216）"
git status --short
```

Expected: commit が 1 つでき、`git status --short` が空。

### Task 2: PR 前の二重レビュー

区分が境界なので、PR を作る前に Claude と Codex の二重レビューを行う（グローバル指示「モデルと実装者の使い分け」）。対象は `<BASE>..HEAD`。

- [ ] **Step 1: 二重レビューを起動する**

Claude は claude-review skill、Codex は codex-review skill（`codex-review.sh --provider openai -m gpt-6-astra`、root は worktree）の手順で起動する。起動の順はグローバル指示の初回の既定の順（Claude → Codex）で、間に別の作業をはさまず、どちらも `run_in_background: true` で起動する。依頼文には、ほかのレビュアーの結果と計画者の自己評価を入れない。見る観点に「足した文が主張を撤回したように読めないか」「実測の範囲を PR #210 の検証より広く書いていないか」を含める。

Expected: 両方が rc 0 で、出力に判定がある。どちらかが起動できなければ `not run` とし、先へ進まずに持ち主に報告する。

- [ ] **Step 2: 結果を受け取って反映する**

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review

Critical と Important を直して commit し、Task 1 Step 5〜7 の確認をやり直す。足す文面を変える指摘は、Global Constraints のとおり直す前に持ち主に示す。深刻度が割れたら重い方を暫定で採る。Critical か Important を出したレビュアーにだけ、確認限定巡を頼む。Minor は採否と理由を控え、未対応のものは PR 本文に書く。

Expected: 未対応の Critical・Important が 0。

- [ ] **Step 3: 実績の台帳に記録する**

vault の `knowledge/モデル別の実績.md` の「本運用の記録」節に、この PR 前レビューの行を、既存の行と同じ形で足して commit する（push は hermes が担うので、頼まない）。利用枠の残量は「未取得（持ち主の判断）」と書く。

Expected: vault に commit が 1 つできる。

### Task 3: PR を作る

- [ ] **Step 1: 完了前の確認**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

Task 1 Step 5・6 の確認を、最後の commit の上でやり直す。加えて `git diff --stat <BASE>..HEAD` を実行する。

Expected: Task 1 Step 5・6 の Expected のとおり。`git diff --stat <BASE>..HEAD` は、計画の写しを含む 3 ファイル（`README.md`・`SECURITY-CLAIMS.md`・`docs/superpowers/plans/2026-10-18-read-only-never-caveat-216.md`）。

- [ ] **Step 2: 持ち主に確認してから push と PR 作成**

**REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch

push して PR を作る選択肢を名前で選ぶ。push の前に持ち主に確認する。PR 本文には、変更の要約、`Closes #216`、検証（実行したものと `not run` とその理由）、PR 前レビューの判定と未対応の Minor、末尾の署名 `— <実効モデル名> (c3c)` を書く。Claude と Codex のレビューの全文は、それぞれ PR コメントに投稿する。

Expected: PR ができ、CI の 4 本（`lint とビルド不要のテスト`・`Analyze (actions)`・`Analyze (python)`・`CodeQL`）が走る。

- [ ] **Step 3: handover を残す**

handover skill で、PR 後の二重レビューとマージを、作成に関わっていない対話セッションへ渡す。次を書く: PR の番号、対象の commit、PR 前レビューの結果のコメントの場所、区分が境界であること、マージ後に worktree（`.worktrees/read-only-never-caveat-216`）とローカルブランチを片付けること、`/workspace` の main の未コミットの `.c3c/allowed-domains.txt` の行は持ち主の指示で残していて触らないこと。

Expected: `/shared/handovers/c3c/` に handover が 1 本できる。

## 計画レビューの記録

- Self-Review: Task 1 の差分の確認で、日本語の行が 1 語に見える件（`--word-diff-regex=.` を付ける）を修正
- Claude（claude-opus-5-5、所要 136 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 README の 503 行にも同じ根拠の「断られる」が残る → 採用（持ち主が 2026-10-18 に足すと決め、文面を承認。Task 1 Step 4 を追加、Goal・Architecture・背景・Step 1・Step 5 を揃えた）
  - I2 commit の後に `git diff` をやり直すと空になり、Expected と合わない → 採用（Codex I1 と同じ。比べる基点を Task 0 Step 1 の `BASE` に固定し、作業ツリーと比べる形にした。Task 3 Step 1 に 3 ファイルの `--stat` を足し、Task 2 Step 2 の参照を「Task 1 Step 5〜7」と書いた）
  - I3 レビューの指摘で承認済みの文面を変えるときの扱いが無い → 採用（Global Constraints と Task 2 Step 2 に、直す前に持ち主に示すことを書いた）
  - M1 README の実測の範囲の句が SECURITY-CLAIMS.md より短い → 承認済みの文面のまま採り、Review Focus 2 に狭く書く意図を書いた
  - M2 推奨実装の理由が規則と前例に合わない → 採用（Codex I2 と同じ論点で、深刻度が割れたので重い方の Important を暫定で採る。推奨を Opus に変えた）
  - M3 写しを作る操作が無い → 採用（Task 0 Step 2 に Write での写しと、`~/`・`/tmp/` などが残らないことの grep を足した）
  - M4 handover に片付けと注意点が無い → 採用（Task 3 Step 3 に足した）
- Codex（gpt-6-astra、所要 63 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 commit の後の差分の確認が必ず Expected と食い違う → 採用（Claude I2 と同じ修正）
  - I2 推奨実装の Sonnet が、Opus を推す条件の例外を独自に作っている → 採用（推奨を Opus に変えた）
  - M1 スキルの指定の位置が Step とずれている → 採用（using-git-worktrees を Task 0 Step 1 に、finishing-a-development-branch を Task 3 Step 2 に移した）
  - 参考: Codex の sandbox では `./lint.sh` が `/dev/fd/63` を作れず rc 1（レビュー環境の制約。計画の Expected は変えない）
- 確認限定巡 1: Codex（I1・I2、所要 14 秒）→ 両方直った、実装に渡せる。生の出力はハーネスの一時出力（公開しない）
- 確認限定巡 1: Claude（I1・I2・I3、claude-opus-5-5、`--resume`、所要 23 秒）→ 3 件とも直った、実装に渡せる。生の出力はハーネスの一時出力（公開しない）
- 承認後の修正（2026-10-18、Task 0 Step 2 を実行して見つけた）: 写しの grep が、grep の行自身と記録節の M3 の行に当たり、Expected の `0` が成り立たなかった → Expected を `2` に直した。Task 2 Step 1 のスキルの個人設定のパスを、前例どおりスキル名だけにした。文面と手順の中身は変えていない

区分: 境界（セキュリティの主張と、その根拠の範囲を述べる文書〈SECURITY-CLAIMS.md〉の変更。グローバル指示の「規則・権限・レビュー手順・秘密の扱いを変える文書は、docs でも境界にする」に当てはめ、迷うので重い方にした）
推奨実装: Opus（判定順の 1〜5 には当たらず、プロジェクト既定は Sonnet だが、グローバル指示の Opus を推す条件のうち「不可逆・対外操作」〈push と PR 作成〉と「セキュリティ境界」〈SECURITY-CLAIMS.md の主張の範囲〉に当たる。前例の #208〈README だけの docs、境界〉も Opus を推した。Sonnet を選ばない理由は、規則が Opus 条件をプロジェクト既定より優先させているため。文面は逐語で確定済みで作業量は小さいので、Opus にしても利用枠への影響は小さい見込み）
