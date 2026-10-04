# workflow ファイルを含む push の制約を README に書く（#195）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** コンテナ内の `git push` が `.github/workflows/` を作成・更新する push で GitHub に拒否されることがあること、c3c の推奨（メイン PAT に `Workflows` 権限を付けず、workflow を変える commit はホストから push する）とその理由を README に書き、同じ拒否に当たったセッションが迷わないようにする。

**Architecture:** 製品の文書では README.md だけを変える docs の変更（計画の写しは別に `docs/superpowers/plans/` に置く）。正本の説明は「git push を使う場合」の段落群に置き、PAT の設定手順・早見表・切り分け手順・対応表・セキュリティモデルからはそこへ短く参照する。製品の挙動、`docs/development-invariants.md`、`SECURITY-CLAIMS.md` は変えない（c3c は PAT の権限を検査しないので、保証文や不変条件は増えない）。

**Tech Stack:** Markdown（README.md）、`./lint.sh`

**Spec:** [#195](https://github.com/jj1xgo/c3c/issues/195)（本文と持ち主アカウントのコメントを 2026-10-04 に gh で確認）。要望 (a)「README に書く」を採る。要望 (b)「`workflow` に当たる権限を足す設計」は採らない（コメントの方針: コンテナの PAT に `workflow` 権限を足さない、workflow を含む push はホストから行う）。

## Global Constraints

- 日本語で書く。コマンド名・権限名・URL・エラーメッセージは原文のまま（README.md「表記」節）。
- fine-grained PAT の権限名は GitHub の表記どおり `Workflows`（Repository permissions）。出典は https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens （「Repository permissions for "Workflows"」の節があることを 2026-10-04 に WebFetch で確認）。
- README は classic PAT を使わない方針なので（「GitHub トークンの配線」手順 1）、classic の `workflow` スコープの付け方は書かない。エラーメッセージに出る `workflow` scope の語は原文のまま引用する。
- 未確認の GitHub の挙動（他者の workflow 変更を取り込んだ merge commit の push も拒否されるか、同じ内容の workflow が別ブランチにある場合の例外が fine-grained PAT にも当たるか、削除も拒否されるか、など）は書かない。拒否は「拒否されることがある」の形で書く。
- 製品の文書の変更は README.md だけ。計画の写しは `.claude/AGENTS.md`「`.claude/` 配下の git 運用」の置き場所の規則により `docs/superpowers/plans/` に置く（これは既決事項の「README.md だけ」の範囲外の、運用上の記録）。挙動は変わらないので SemVer のタグは提案しない（AGENTS.md「バージョン管理」）。

## Review Focus

1. コンテナ内で拒否を見たセッションが README を grep したとき、エラーメッセージの文字列（`refusing to allow a Personal Access Token to create or update workflow`）で正本の段落に着けること → Task 1 Step 6 の grep で確認する。
2. 権限名・節名の表記が 6 か所（Step 2・3a・3b・4a・4b・5）で揃っていること（`Workflows`、「git push を使う場合」）→ Task 1 Step 6 の grep で確認する。
3. 「c3c が workflow の push を防ぐ」「`Workflows` を付けなければ Actions に届かない」と読める書き方をしないこと（防いでいるのは GitHub と利用者の PAT 設定で、`Contents: write` でも既存の workflow が実行するスクリプトは書き換えられる）→ Task 1 Step 7 の読み直しで確認する。
4. 既存の文の意味を変えないこと（挿入だけで、既存文の書き換えは各 Step に書いた末尾への追記に限る）→ Task 1 Step 6 の 1 文字単位の `git diff --word-diff` の `[-` が 0 件であることで確認する。
5. Markdown の表が壊れないこと（表のセル内に改行や `|` を入れない）→ Task 1 Step 6 の grep で該当行が 1 行のまま `|` で終わることを確認する。

---

### Task 0: ブランチを切り、計画を commit する（計画者が承認直後に行う）

**Files:**
- Create: `docs/superpowers/plans/2026-10-04-workflow-push-docs-195.md`（この計画ファイルの写し）

- [ ] **Step 1: 作業状態を確かめ、ブランチを切って計画の写しを commit する**

```bash
git -C /workspace status --short
git -C /workspace worktree list
git -C /workspace fetch origin
git -C /workspace switch -c docs/workflow-push-195 origin/main
cp /home/node/.claude/plans/elegant-weaving-lemon.md /workspace/docs/superpowers/plans/2026-10-04-workflow-push-docs-195.md
git -C /workspace add docs/superpowers/plans/2026-10-04-workflow-push-docs-195.md
git -C /workspace commit -m "docs: #195 の計画を足す"
```

Expected: `status --short` は既知の未追跡ファイル `?? .c3c/codex-version.txt` だけ（触れない）、worktree は `/workspace` の 1 件。それ以外の変更や worktree があれば、他セッションの作業として触れずに持ち主へ確かめる。ブランチ `docs/workflow-push-195` に計画の commit が 1 つ載る。生の出力の保存先は定めていないので、計画末尾の「計画レビューの記録」節を正本にする。

### Task 1: README.md に workflow を含む push の制約を書く

**Files:**
- Modify: `README.md`（「GitHub トークンの配線」節の手順 1、「git push を使う場合」の段落群、「何ができて何ができないか」節の早見表・切り分け手順・対応表、「セキュリティモデル」節）

**Interfaces:**
- Consumes: なし
- Produces: 「git push を使う場合」内の太字見出し `**workflow ファイルを含む push（`.github/workflows/`）**` の段落。他の 5 か所はこの段落を「「git push を使う場合」参照」の形で指す。

行番号は main（d564e05）の時点の目安で、編集のたびにずれる。各 Step は「探す文字列」で場所を決める。コマンドの `/workspace` はコンテナ内の checkout のパスで、host で実装するときは host の checkout のパス（例 `~/…/c3c`）に読み替える。

- [ ] **Step 1: ブランチを確かめる**（ブランチは Task 0 で計画者が切ってある）

```bash
git -C /workspace branch --show-current
git -C /workspace log --oneline -1
```

Expected: `docs/workflow-push-195`、最新 commit は `docs: #195 の計画を足す`。違えば実装を始めず、進行役に戻す。

- [ ] **Step 2: 正本の段落を足す（「git push を使う場合」）**

探す文字列: 行頭が `**force push 対策**:` の段落（main では 421 行目）。その段落の直後、次の段落（行頭が `**コンテナ内 git commit（`GITCONFIG_FILE`）**`）の前に、前後に空行を挟んで次を挿入する（`entrypoint.sh` の動作を説明する 2 段落を分断しないため、太字見出しの段落が並ぶこの位置に置く）。

````markdown
**workflow ファイルを含む push（`.github/workflows/`）**: `.github/workflows/` 配下のファイルを作成・更新する push は、トークンに workflow の権限（fine-grained PAT では Repository permissions の `Workflows`。[公式の権限表](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens#repository-permissions-for-workflows)）が無いと、GitHub に次のエラーで拒否されることがある。拒否されたブランチは更新されない。

```text
! [remote rejected] <branch> -> <branch> (refusing to allow a Personal Access Token to create or update workflow `.github/workflows/ci.yml` without `workflow` scope)
```

c3c はメイン PAT に `Workflows`（`Read and write`）を付けることを推奨しない。付けると、workflow の定義そのもの（起動の条件、`GITHUB_TOKEN` の権限、参照する secrets）までコンテナ内から書き換えられ、実行の条件と権限によっては、そのリポジトリで使える secrets や `GITHUB_TOKEN` の漏洩につながりうる。ただし付けなくても、`Contents: write` があれば既存の workflow が実行するスクリプト（テストやビルドのスクリプトなど）は書き換えられ、Actions 上で実行されうる。`Workflows` を付けないことは CI への影響をすべて防ぐものではなく、workflow の定義の書き換えをコンテナの権限から外すためのものである。

workflow ファイルを変える commit は、コンテナ内では commit までにとどめ、ホストの端末から push する。ホストからの push にはホスト側の認証（workflow を更新できるもの）を使い、コンテナの PAT は変えない。push の前に、ホストで workflow の変更内容を確かめる（例: 分岐元が `main` なら `git log -p origin/main..<branch> -- .github/workflows/`）（[#195](https://github.com/jj1xgo/c3c/issues/195)）。
````

- [ ] **Step 3: PAT の設定手順と対応表から参照する**

(3a) 「GitHub トークンの配線」手順 1 の箇条書き。探す文字列: `` （`Contents: write` を付与しない限り push・マージ・Release作成はホスト側限定のまま維持される） ``（main では 329 行目、1 か所）。この文字列の直後（同じ行の末尾）に次を追記する。

```markdown
。`Workflows` は付けない（`.github/workflows/` を変える push はホストから行う。後述「git push を使う場合」）
```

(3b) 「メイン PAT / MCP・issues 用 PAT 対応表」の行 `| 持たせるべきでないパーミッション |`（main では 663 行目）。メイン PAT 列のセルの文字列 `用途に不要な権限（非 export でも直接読み取りは可能）` の直後（同じセルの中、セル区切りの ` |` の前）に次を追記する。MCP 列のセルは変えない。

```markdown
。`Workflows`（workflow を変える push はホストから。「git push を使う場合」参照）
```

- [ ] **Step 4: 早見表と切り分け手順から参照する**

(4a) 「操作系統別の認証経路と可否」の表で、行頭が `| git リモート操作（`push` / `pull` / `fetch`）` の行（main では 643 行目）。3 列目のセル末尾 `…private リポジトリの fetch/pull）が可能になる` の直後（行末の ` |` の前）に次を追記する。

```markdown
。`.github/workflows/` を作成・更新する push は、メイン PAT に `Workflows` が無いと拒否されることがある（「git push を使う場合」参照）
```

(4b) 「GitHub 操作が失敗したときの切り分け」の手順 2（行頭が `` 2. `git` の失敗なら、 ``、main では 652 行目）の末尾 `…PAT の更新だけなら不要。` の直後に、同じ行のまま次を追記する。

```markdown
push が `refusing to allow a Personal Access Token to create or update workflow` で拒否された場合は、配線の問題ではなく `Workflows` 権限が無いためである。c3c の推奨ではホストから push する（「git push を使う場合」参照）。
```

- [ ] **Step 5: セキュリティモデルから参照する**

「セキュリティモデル」節で `` `SECRETS_DIR/GITHUB_MAIN_PAT`（前述「git push を使う場合」）に `Contents: write` を付与した場合、 `` で始まる段落（main では 723 行目）の末尾 `…branch protection（force-push 禁止・レビュー必須化）を組み合わせること。` の直後に、同じ段落のまま次を追記する。

```markdown
`Workflows` を付けていなくても、既存の workflow が実行するスクリプトは `Contents: write` で書き換えられ、Actions 上で実行されうる。`Workflows` を付けると、workflow の定義まで書き換えられる（「git push を使う場合」参照）。
```

- [ ] **Step 6: 機械的に確かめる**

```bash
cd /workspace
grep -n 'refusing to allow a Personal Access Token' README.md
grep -c '`Workflows`' README.md
grep -n '「git push を使う場合」参照）\|後述「git push を使う場合」）' README.md
grep -n '^| 持たせるべきでないパーミッション \|^| git リモート操作' README.md
git diff --stat
git diff --check; echo "check rc=$?"
git diff --word-diff=plain --word-diff-regex=. README.md | grep -c '\[-'
git diff --word-diff=plain --word-diff-regex=. README.md
./lint.sh; echo "lint rc=$?"
```

Expected:
- 1 行目の grep: 2 行（Step 2 の code block と Step 4b。main では 0 行）。
- `` `Workflows` `` を含む行数: 7（main では 0。Step 2 の見出しの段落と「c3c はメイン PAT に」の段落に各 1 行、3a・3b・4a・4b・5 に各 1 行）。
- 参照の grep: Step 3a・3b・4a・4b・5 の 5 行が出る（main では 0 行）。
- 表の 2 行: どちらも 1 行のまま、行末が ` |` で終わる。
- `git diff --stat`: `README.md` の 1 ファイルだけ（Task 0 の計画の commit は済んでいるので、ここには出ない）。
- `git diff --check`: 出力なし、rc=0。
- `[-` の件数: 0（1 文字単位の比較で、既存の文字は 1 つも消さず、追記と挿入だけであることを見る。通常の `git diff` や空白区切りの `--word-diff` では、追記した 5 行の行末が削除と追加の組で出るが、それは正しい）。もし 0 にならなければ、表示された `[-…-]` の箇所が追記によるずれだけか（消えた文字が直後の `{+…+}` の先頭にそのまま現れているか）を読んで確かめ、結果を報告に書く。
- 1 文字単位の `--word-diff` の本文: 追加（`{+…+}`）が Step 2 の挿入と、3a・3b・4a・4b・5 の 5 か所の追記だけ。
- `./lint.sh`: rc=0、警告ゼロ。podman が無い環境（コンテナ内、または host の Codex の sandbox で podman が動かない場合）では Compose 検証が警告付きでスキップされる。その場合は Compose 検証を `not run`（理由を添える）と報告し、PR の CI の lint 結果で確かめる。

- [ ] **Step 7: 読み直す**

`git diff README.md` を読み、次を確かめる。外れていたら直してから Step 6 をやり直す。
- 「c3c が防ぐ」と読める文が無い（主語は GitHub か利用者の PAT 設定）。
- 「`Workflows` を付けなければ Actions に届かない」と読める文が無い（`Contents: write` でも既存の workflow が実行するスクリプトは書き換えられる）。
- Global Constraints の未確認事項（merge commit の扱いなど）を書いていない。拒否は「拒否されることがある」の形で書いている。
- Step 2 の挿入は「**force push 対策**」段落と「**コンテナ内 git commit（`GITCONFIG_FILE`）**」段落の間にある。

- [ ] **Step 8: commit**

```bash
cd /workspace
git add README.md
git commit -m "docs: workflow ファイルを含む push の制約と、ホストから push する運用を書く（#195）"
```

commit の末尾には、実装者のセッションの attribution の行を付ける。

### Task 2: PR 前レビューと PR

- [ ] **Step 1: PR 前レビュー（区分が境界のため）**

進行役（計画者のコンテナ内 Claude セッション）が、実装者の commit を対象に行う。Codex（`codex exec --model gpt-6-astra --sandbox read-only -C /workspace "<依頼文>" < /dev/null`）を先に background で起動し、続けて `~/.agents/skills/claude-review/SKILL.md` の手順で headless の Claude レビューを行う。Critical と Important は実装者に差し戻して直し、commit する。

- [ ] **Step 2: push と PR**

push の前に範囲を確かめる。

```bash
git -C /workspace diff --stat origin/main...HEAD
```

Expected: `README.md` と `docs/superpowers/plans/2026-10-04-workflow-push-docs-195.md` の 2 ファイルだけ。


push は持ち主に確認してから行う。PR 本文には、#195 を閉じる `Closes #195`、変更の要約、`./lint.sh` の結果（Compose 検証が `not run` ならその理由）、PR 前の二重レビューの判定と未対応の Minor を書き、両レビュアーの全文を PR コメントに投稿する。PR 後は作成に関わっていない Codex と Claude（Opus、対話セッション）の二重レビューを行う。

## 検証

- Task 1 Step 6 の grep・diff・`./lint.sh`。
- CI（`.github/workflows/ci.yml`）の lint が PR で成功すること。
- 実機の push で拒否が再現することの確認は行わない（#195 の本文に実際の拒否ログがあり、確認のためだけに workflow を含む push を試すと対外操作になるため）。`not run` と報告する。

## 計画レビューの記録

- Self-Review: Step 6 の Expected を main の実測値（`Workflows`・参照・エラー文の各 0 件）から数え直して確定値に修正、ブランチ作成と計画の commit を Task 0 に分離、推奨実装を判定基準 4 に合わせて Codex に修正、host での `/workspace` の読み替えを追記
- Codex（gpt-6-astra）: 修正後に渡せる。生の出力 `/tmp/claude-1000/-workspace/45f0f03d-50aa-4285-9cbd-455a685fc221/tasks/bktf59wnh.output`
  - I1 計画の写しの commit が「README.md だけ」に反する → 一部採用（計画の写しは `.claude/AGENTS.md` の置き場所の規則による運用上の記録で、既決事項の範囲は製品の文書と明記。Task 2 Step 2 に `origin/main...HEAD` の 2 ファイルの確認を追加。計画の commit 自体は外さない）
  - I2 拒否条件の断定が根拠より広い → 採用（「拒否されることがある」に変更、未確認事項に別ブランチの例外を追加）
  - I3 secrets への到達の断定と `Contents: write` との差の誇張 → 採用（Step 2 の推奨の段落と Step 5 を書き直し）
  - I4 diff の Expected が満たせない → 採用（`git diff --check` と `--word-diff` の `[-` 0 件に変更）
  - M1 確認例が新規ブランチで失敗、ホスト側の認証 → 採用
  - M2 ブランチ作成前の状態確認 → 採用（Task 0 Step 1）
  - M3 正本以外での再説明 → 採用（4a・4b・5 を短縮。5 は `Contents: write` の残存リスクの 1 文を残す）
- Claude（claude-opus-5-5、session `e0f099fb-c038-48f3-b7da-5309895ae2f4`）: 修正後に渡せる。生の出力 `/tmp/claude-1000/-workspace/45f0f03d-50aa-4285-9cbd-455a685fc221/tasks/bouk13od7.output`
  - C1 `Workflows` 無しなら Actions に届かないと読める → 採用（Codex I3 と同じ書き直し、Step 7 と Review Focus 3 に確認項目を追加）
  - I1 diff の Expected の誤り → 採用（Codex I4 と同じ）
  - I2 Codex の workspace-write で commit が通らない、podman の前提 → 採用（実行条件と `/goal` に昇格の承認と `not run` の扱いを追記）
  - I3 挿入位置が `entrypoint.sh` の説明を分断 → 採用（「force push 対策」と「コンテナ内 git commit」の間へ移動）
  - M1 「作成・更新」と「変える」の揺れ → 採用（拒否の説明は「作成・更新」、推奨の対象は「変える」）
  - M2 確認例のコマンド → 採用（Codex M1 と同じ）
  - M3 `/goal` に Step 1 と読み替えが無い → 採用
  - M4 権限の段階 → 採用（Step 2 に `Read and write` を 1 回添える）

- 確認限定巡 1: Codex（I1〜I4）→ I3 は解消。I1 は未解消の判定、I2 は Goal に断定が残る、I4 は空白区切りの `--word-diff` でも `[-` が出る。生の出力 `/tmp/claude-1000/-workspace/45f0f03d-50aa-4285-9cbd-455a685fc221/tasks/b070nqyl2.output`
  - I1 → 持ち主が判断（2026-10-04）: 計画の写しはいつもどおり commit する。「README.md だけ」は計画者が書いた前提で、持ち主の指示ではなかった
  - I2 → Goal を「拒否されることがある」の形に修正
  - I4 → 1 文字単位（`--word-diff-regex=.`）の比較に変更し、0 にならないときの読み方を追記
- 確認限定巡 1: Claude（C1・I1〜I3）→ C1・I2・I3 は解消。I1 は空白区切りの `--word-diff` で満たせない → Codex I4 と同じ修正。生の出力 `/tmp/claude-1000/-workspace/45f0f03d-50aa-4285-9cbd-455a685fc221/tasks/bwawqm0mc.output`

- 確認限定巡 2: Codex（I2・I4）→ 解消、実装に渡せる。生の出力 `/tmp/claude-1000/-workspace/45f0f03d-50aa-4285-9cbd-455a685fc221/tasks/b3cr4tq17.output`
- 確認限定巡 2: Claude（I1）→ 解消、実装に渡せる。生の出力 `/tmp/claude-1000/-workspace/45f0f03d-50aa-4285-9cbd-455a685fc221/tasks/bi5s8bnd0.output`

区分: 境界 — README だけの docs だが、PAT に付ける権限の推奨（`Workflows` を付けない）と、秘密を使う push の運用を書く文書なので、グローバル指示の「規則・権限・秘密の扱いを変える文書は docs でも境界」に当たる。迷う要素があるため重い方を採った。計画・PR 前・PR 後の 3 段のレビューを行う。

推奨実装: Codex — 判定基準を上から当てると、1（コンテナ内でしか成立しない）は当たらない（README の編集と `./lint.sh` は host の checkout でもでき、host なら Compose 検証まで通せる）。2（`~/.claude` 配下・hook・秘密を読む経路）も当たらない（文書だけで、秘密を読む実装に触れない）。3（設計判断が残る）も当たらない（挿入する文と場所を逐語で決めてある）。4（host の checkout で完結し、逐語手順と Expected まで確定）に当たる。Sonnet でも実装できるが、基準の 4 に当たる以上、Claude の利用枠を使う理由は無い。

- Codex の実行条件: host の checkout（`~/…/c3c`）。sandbox は `workspace-write`。この sandbox では `.git` が読み取り専用なので、Step 8 の `git commit` には昇格の承認が 1 回要る（持ち主が承認する）。`./lint.sh` の Compose 検証が sandbox で動かなければ、Step 6 の Expected のとおり `not run` として PR の CI に委ねる。ネットワークは不要（push と PR は持ち主の確認後に行う）。`/goal` は持ち主が明示した場合だけ開始する。

`/goal` に渡す文面: 「#195 の計画 `docs/superpowers/plans/2026-10-04-workflow-push-docs-195.md` を executing-plans で実装する。Task 1 の Step 1〜8 を順に行う。コマンド中の `/workspace` は host の checkout のパスに読み替える。Step 1 でブランチ `docs/workflow-push-195` を確かめ、Step 2〜5 のとおり README.md に逐語で挿入・追記し、Step 6 の grep・diff・`./lint.sh` を実行して Expected と照らし、Step 7 の読み直しのあと Step 8 の 1 commit にする（commit の昇格の承認は持ち主に求める）。実際の出力を報告し、未実施の項目は not run と理由を書く。他セッションの変更と未追跡ファイルに触れない。push と PR は行わない。」
