# README の codex exec の起動例で stdin を閉じる（#208）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** README「Codex CLI をセカンドオピニオンとして使う」節の手順 5 の起動例に `< /dev/null` を足し、なぜ閉じるかを 1 文で説明する。呼び出し元の stdin の中身が依頼文に混ざらないようにするため。

**Architecture:** README.md だけを変える docs の変更。計画の写しは `docs/superpowers/plans/` に置く。製品の挙動、`docs/development-invariants.md`、`SECURITY-CLAIMS.md` は変えない。挙動が変わらないので SemVer のタグは提案しない（AGENTS.md「バージョン管理」）。

**Tech Stack:** Markdown（README.md）、`./lint.sh`

**Spec:** [#208](https://github.com/jj1xgo/c3c/issues/208)（2026-10-17 に起票した本文）。「直し方の案」の 1・2 を採る。3（依頼文をファイルや stdin で渡す形）は範囲外。

## Global Constraints

- 日本語で書く。コマンド名・オプションは原文のまま（README.md「表記」節）。
- 根拠は `codex exec --help`（codex-cli 0.163.0）の `[PROMPT]` の説明の文: `If stdin is piped and a prompt is also provided, stdin is appended as a <stdin> block`（2026-10-17 にホストで実行して確認。help では `<stdin>` がバッククォートで囲まれ、`stdin` と `is appended` の間で改行される）。README には英語の引用を貼らず、出典として「`codex exec --help` の `[PROMPT]` の説明、codex-cli 0.163.0」と書く。
- 「閉じないと待ち続ける」とは書かない（help の文面からの推論で、実測していない）。書くのは「stdin の中身が依頼文に足される」ことだけ。help の言い方に合わせて「stdin がパイプなら」と書く（ファイルのリダイレクトでも読むかは確かめていない）。
- 既存の文は書き換えない。変更は、起動例のコードの行末への追記と、説明の段落への 1 文の挿入だけ。
- 公開側に置く計画の写しには、ホストの絶対パス、`~` 配下の個人設定のパス、レビューの session id と一時ファイルのパスを書かない（`.claude/AGENTS.md`「`.claude/` 配下の git 運用」）。コマンドは checkout のルートからの相対で書く。計画レビューの生の出力は公開側に置かず、この計画の「計画レビューの記録」節を正本にする。
- TDD のスキルは読み込まない（文書だけの変更で、テストする振る舞いのコードが無いため）。実装者は、読み込まない理由を台帳か報告に 1 行書く。
- `./lint.sh` で Compose 検証が実行できない環境（podman が無い、または podman があっても `Error: no such file or directory` などで Compose 検証だけが失敗する、Codex の sandbox など）では、`LINT_SKIP_COMPOSE=1 ./lint.sh` で残りを確かめ、Compose 検証を `not run`（理由を添える）と報告して、PR の CI の lint で補う。

## Review Focus

1. 写したコマンドがそのまま動くこと: `< /dev/null` が `"<依頼文>"` の後、同じ行にあり、コードブロックが 1 行のまま → Task 1 Step 4 の grep で確かめる。
2. 説明の文が、未確認の挙動（待ち続ける、など）を断定していないこと → Task 1 Step 5 の読み直しで確かめる。
3. 既存の文を消していないこと → Task 1 Step 4 の 1 文字単位の `--word-diff` で `[-` が 0 件。
4. `-o <ファイル>` や `--skip-git-repo-check` を足す読者が、`< /dev/null` を消さないこと → Step 3 の文に「オプションを足すときも残す」と書き、Step 5 で読み直す。
5. 出典の版と help の文が一致すること → Task 1 Step 4 で `codex exec --help` と照合する（codex が無い環境では `not run`）。

---

### Task 0: ブランチを切り、計画を commit する（計画者が、計画の承認直後に最初の作業として行う）

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

計画レビューと、その記録節への書き込みは、承認の前に済んでいる。Task 0 はそのあとに行う。

**Files:**
- Create: `docs/superpowers/plans/2026-10-17-codex-exec-stdin-208.md`（承認された計画ファイルの写し）

- [ ] **Step 1: 作業状態を確かめ、ブランチを切って計画の写しを commit する**

checkout のルートで実行する。`<計画ファイル>` は Plan Mode が計画者に示した計画ファイル。

```bash
git status --short
git worktree list
git fetch origin
git switch -c docs/codex-exec-stdin-208 origin/main
cp <計画ファイル> docs/superpowers/plans/2026-10-17-codex-exec-stdin-208.md
grep -cE '/home/[a-z]|/tmp/[a-z]|~/[.a-z]' docs/superpowers/plans/2026-10-17-codex-exec-stdin-208.md
./lint.sh; echo "lint rc=$?"
git add docs/superpowers/plans/2026-10-17-codex-exec-stdin-208.md
git commit -m "docs: #208 の計画を足す"
```

Expected:
- `status --short` は既知の ` M .c3c/allowed-domains.txt`（`api.typesafe.ai` の行。触れない、stage しない）だけ。worktree はこの checkout の 1 件。それ以外の変更や worktree があれば、他セッションの作業として触れずに持ち主へ確かめる。
- `git switch` は未 commit の `.c3c/allowed-domains.txt` を持ったまま切り替わる（origin/main で同じファイルが変わっていなければ通る。通らなければ止まって持ち主に確かめる）。
- `grep -c` は `0`（ホームや一時ディレクトリの下の実在のパスが写しに無い。パターンの文字クラスは自分自身の行に当たらない）。0 でなければ、`grep -n` で行を見て写しを直してから commit する。
- `./lint.sh`: rc=0、警告ゼロ。Compose 検証が実行できなければ Global Constraints のとおり。
- ブランチ `docs/codex-exec-stdin-208` に計画の commit が 1 つ載る。

### Task 1: README.md の手順 5 に stdin を閉じる指定を足す

**Files:**
- Modify: `README.md`（「Codex CLI をセカンドオピニオンとして使う」節の手順 5）

**Interfaces:**
- Consumes: なし
- Produces: なし（README の 1 か所だけの変更）

行番号は main（dd33a77）の時点の目安（起動例は 501 行目、説明は 503 行目）。各 Step は「探す文字列」で場所を決める。コマンドはどれも checkout のルートで実行する。

- [ ] **Step 1: ブランチを確かめる**

```bash
git branch --show-current
git log --oneline -1
```

Expected: `docs/codex-exec-stdin-208`、最新 commit は `docs: #208 の計画を足す`。違えば実装を始めず、進行役に戻す。

- [ ] **Step 2: 起動例に `< /dev/null` を足す**

探す文字列（README 全体で 1 か所）:

```text
   codex exec --sandbox read-only -c 'approval_policy="never"' -C /workspace "<依頼文>"
```

この行を、行末に ` < /dev/null` を足した次の行に置き換える（字下げの 3 文字の空白はそのまま）。

```text
   codex exec --sandbox read-only -c 'approval_policy="never"' -C /workspace "<依頼文>" < /dev/null
```

- [ ] **Step 3: 説明の段落に 1 文を挿入する**

探す文字列（同じ段落の中、1 か所。末尾の `。` の後に空白は無い）:

```text
`never` に固定すると、外での実行の要求は断られる）。
```

この文字列の `。` と、その直後に同じ行で続く `` `-C /workspace` で作業ルートを明示する `` の間に、次の 1 文を空白を入れずに挿入する。

```text
末尾の `< /dev/null` も省略しない（`codex exec` は、依頼文を引数で渡しても、stdin がパイプならその中身を `<stdin>` のブロックとして依頼文に足す〈`codex exec --help` の `[PROMPT]` の説明、codex-cli 0.163.0〉。呼び出し元の stdin がパイプのままだと、前のコマンドの出力などが依頼文に混ざりうる。オプションを足すときも残す）。
```

- [ ] **Step 4: 機械的に確かめる**

```bash
grep -c '"<依頼文>" < /dev/null$' README.md
grep -c '末尾の `< /dev/null` も省略しない' README.md
grep -c '断られる）。末尾の `< /dev/null` も省略しない' README.md
grep -c 'オプションを足すときも残す）。`-C /workspace` で作業ルートを明示する' README.md
git diff --stat
git diff --check; echo "check rc=$?"
git diff --word-diff=plain --word-diff-regex=. README.md | grep -c '\[-'
git diff --word-diff=plain --word-diff-regex=. README.md
codex --version
codex exec --help | grep -F 'If stdin is piped and a prompt is also provided'
./lint.sh; echo "lint rc=$?"
```

Expected:
- 1〜4 行目の grep: どれも `1`（main ではどれも `0`）。3・4 行目は、挿入した文が前後の文と空白なしでつながっていることを見る。
- `git diff --stat`: `README.md`（2 行の置き換えなので `4 ++--`）と、既存の未 commit の `.c3c/allowed-domains.txt`（`1 +`）の 2 ファイル。この 2 つ以外が出たら止まって進行役に戻す。
- `git diff --check`: 出力なし、rc=0。
- `[-` の件数: `0`（README.md だけを比べる。既存の文字を 1 つも消さず、追記と挿入だけであることを見る）。
- 1 文字単位の `--word-diff` の本文: 追加（`{+…+}`）が Step 2 の ` < /dev/null` と Step 3 の 1 文の 2 か所だけ。
- `codex --version` が `codex-cli 0.163.0` で、help の grep で該当の 1 行が出る（help の文は改行で 2 行に割れるので、前半だけで照合する）。codex が無い環境では `not run`、版が違えば版を添えて報告する（版が違って文が消えていたら、止まって進行役に戻す）。
- `./lint.sh`: rc=0、警告ゼロ。Compose 検証が実行できなければ Global Constraints のとおり。

- [ ] **Step 5: 読み直す**

`git diff README.md` を読み、次を確かめる。外れていたら直してから Step 4 をやり直す。
- 起動例が 1 行のまま、`< /dev/null` が行末にある。
- 挿入した文が「待ち続ける」などの未確認の挙動を書いていない。
- 挿入した文が、`approval_policy` の文の後、`-C /workspace` の文の前にある。

- [ ] **Step 6: commit し、完了を報告する**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

```bash
git add README.md
git commit -m "docs: README の codex exec の起動例で stdin を閉じる（#208）"
git show --stat HEAD
```

Expected: `git show --stat` は `README.md` の 1 ファイルだけ。`.c3c/allowed-domains.txt` は stage しない。commit の末尾には、実装者のセッションの attribution の行を付ける。進行役への報告には、Step 4 の各コマンドの実際の出力と、`not run` の項目とその理由を書く。

### Task 2: PR 前レビューと PR（進行役が行う）

- [ ] **Step 1: PR 前の二重レビュー（区分が境界のため）**

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review

進行役（計画者のホストの Claude セッション）が行う。材料は、`git diff <base の SHA>..<head の SHA>` を書き出した差分ファイルと、この計画ファイル（root の外にあれば、どちらも `-r` で渡す）。依頼文と材料は同じものを 3 者に渡す。グローバル指示の二重レビューの項の既定の順（初回は Claude → kimi-k3 → Codex）で、続けて background で起動する。起動の手順は、グローバル指示の claude-review・nous-review・codex-review の各 skill に従う（Codex は `codex-review.sh --provider openai -m gpt-6-astra`、root はこの checkout）。

Critical と Important は実装者に差し戻して直し、commit する。直したら Task 1 の Step 4・Step 5 をやり直す（文言が変わったら、Step 4 の grep の固定文字列も同じに直す）。そのうえで、指摘したレビュアーに確認限定巡を頼む。

- [ ] **Step 2: 台帳に記録する**

レビューの区切りで、vault `knowledge/モデル別の実績.md` の「本運用の記録」節に、事実だけを 1 行で足す（グローバル指示「モデルと実装者の使い分け」）。書くのは、計画レビューと PR 前レビューの巡数、どのレビュアーが何を挙げ何を見落としたか、各レビュアーの所要（秒）、実装の手戻り、Claude と Codex の 5 時間枠と週枠の残量（持ち主に `/usage` を確かめてもらう。取れなければ「未取得」）、推奨と違う実装者を指定したならその理由。

- [ ] **Step 3: 範囲を確かめ、PR を作る**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

```bash
git diff --stat origin/main...HEAD
```

Expected: `README.md` と `docs/superpowers/plans/2026-10-17-codex-exec-stdin-208.md` の 2 ファイルだけ。

finishing-a-development-branch では、push して PR を作る選択肢を名前で選ぶ。push は持ち主に確認してから行う。PR 本文には、`Closes #208`、変更の要約、`./lint.sh` の結果（Compose 検証が `not run` ならその理由）、PR 前の二重レビューの判定と未対応の Minor（`not run` のレビュアーは理由）を書き、末尾に `— <実効モデル名> (c3c)` の署名を置く（モデル名は、投稿の直前にこのセッションの transcript の `.message.model` で確かめる）。走らせたレビュアーの全文は、それぞれ PR コメントに投稿する。投稿の前に、各全文のファイルに Task 0 Step 1 と同じ `grep -cE '/home/[a-z]|/tmp/[a-z]|~/[.a-z]' <全文のファイル>` を実行する。0 でなければ、当たったパスを `<checkout>`・`<計画ファイル>`・`<一時ファイル>` などの置き換えにし、その旨（「ホストのパスを置き換えた」）をコメントの先頭に 1 行書いてから投稿する（置き換え以外は全文のまま）。PR 本文にも同じ grep をかける。PR 後は、作成に関わっていない Codex・kimi-k3・Claude（Opus、対話セッション）の二重レビューを行う（進行役が handover で渡す）。

## 検証

- Task 0 Step 1 と Task 1 Step 4 の grep・diff・help の照合・`./lint.sh`。
- CI（`.github/workflows/ci.yml`）の lint が PR で成功すること。
- パイプの stdin が実際に依頼文に足されることの実測（`echo x | codex exec ...`）は行わない。help の文を根拠にし、README にも help を出典として書く。`not run` と報告する。

## 計画レビューの記録

- Self-Review: `git diff --stat` の Expected を、既存の未 commit の `.c3c/allowed-domains.txt` が並ぶ形に修正。探す文字列と Expected の基準値（main で各 1 件・0 件）を grep で確認
- Claude（claude-opus-5-5、所要 119 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 公開側にホストのパスと生の出力を置く → 採用（Global Constraints に置かない規則を足し、コマンドを相対にし、生の出力は保存せず記録節を正本に。Task 0 に grep の確認を追加）
  - I2 PR 本文の署名が無い → 採用（Task 2 Step 3）
  - M1 完了報告の直前に verification-before-completion が無い → 採用（Task 1 Step 6）
  - M2 台帳への記録の Step が無い → 採用（Task 2 Step 2）
  - M3 差し戻し後に Step 4 をやり直す記述が無い → 採用（Task 2 Step 1）
  - M4 Review Focus 4 と挿入する文の食い違い → 採用（Review Focus 4 を書き直し）
  - M5 「パイプなら」は狭いかもしれない → 不採用（help の言い方に合わせ、確かめていない範囲を広げない。Global Constraints に理由を明記）
- kimi-k3（moonshotai/kimi-k3、所要 59 秒）: 実装に渡せる。生の出力はハーネスの一時出力（公開しない）
  - M1 探す文字列の末尾に空白があるように読める → 採用（Step 3 をコードブロックにし、空白が無いこと、挿入位置を明記。Step 4 に前後とのつながりの grep を追加）
  - M2 PR 前レビューの材料が曖昧 → 採用（差分ファイルと計画を `-r` で渡すと明記）
  - M3 Task 0 を行う時機が読み取りにくい → 採用（見出しと冒頭の文）
- Codex（gpt-6-astra、所要 80 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 公開側にホストのパス → 採用（Claude I1 と同じ）
  - I2 Sonnet の推奨が Opus の条件を狭めている → 採用（推奨を Opus に。下の推奨実装の行）
  - M1 Task 0 の lint が無い、commit の Step の verification-before-completion → 一部採用（Task 0 に lint を追加。verification-before-completion は、表の場面が「完了の報告・取り込み・PR 作成の直前」なので、完了報告を兼ねる Task 1 Step 6 にだけ付けた）
  - M2 podman があっても Compose が動かない場合 → 採用（Global Constraints に `LINT_SKIP_COMPOSE=1` の経路を追加）
  - M3 挿入する文が長い → 採用（英語の引用を外し、出典だけにした）
- 確認限定巡 1: Codex（I1・I2、所要 16 秒）→ I2 は解消。I1 は、PR コメントに載せるレビューの全文を確かめる手順が無いので一部未解消 → 反映（Task 2 Step 3 に投稿前の grep と置き換えの手順を追加）
- 確認限定巡 1: Claude（I1・I2、所要 18 秒）→ どちらも解消、実装に渡せる
- 確認限定巡 2: Codex（I1 の残件、所要 22 秒）→ 解消、実装に渡せる

区分: 境界 — README だけの docs だが、利用者に案内する Codex の起動手順（依頼文に何が送られるか、独立レビューの前提）を変える文書なので、グローバル指示の「規則・権限・レビュー手順・秘密の扱いを変える文書は、docs でも境界」に当たる。計画・PR 前・PR 後の 3 段のレビューを行う。

推奨実装: Opus — 判定順を上から当てると、1〜5 はどれも当たらない（ホストでもコンテナでもでき、Claude Code の設定ディレクトリ・hook・秘密に触れず、足す文字列と場所は逐語で決めてあり、変更は 2 か所だけ）。6 は c3c のプロジェクト既定で Claude Code 面の Claude（Sonnet）になる。ただし、この変更は外部のモデルに何が送られるか（送信範囲）の案内を変えるので、グローバル指示の「Opus は … セキュリティ境界を含むときに推す」に当たると判断した（迷う要素があるので重い方を採った。Codex の計画レビュー I2）。計画者と同じモデルになるが、Sonnet にしても変える量が 2 か所なので差は小さく、Codex にする理由（ホスト限定、Claude の利用枠の不足）は無い。

実装: Opus 5.5（持ち主指定、2026-10-17。推奨どおり。計画者と同じセッションで、`/model` の切り替えなし）
