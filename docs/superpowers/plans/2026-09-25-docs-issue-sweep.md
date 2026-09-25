# 溜まった Issue の文書側の片付け（#102・#127・#5・#7）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

## 目的と状態

優先度 low と on-hold のまま溜まっていた Issue のうち、文書だけで閉じられるものを 1 本の PR で片付ける。基準は main `151ec20`（v14.1.1）。コード側の片付け（#112・#126・#132・#159）は別の計画 `2026-09-25-code-issue-sweep.md` で扱う。

持ち主の判断（2026-09-25）:

- #127 は選択肢 (a)（現状維持。README に 1 文足す）で閉じる。
- #5 と #7 は not planned で閉じた（閉じる際のコメントに、再検討のトリガーを残した）。その判断を README にも記録する。
- #62 は、README「イメージの変更」節に既に記述があったので閉じた。この計画では扱わない。

持ち主が実装者を指定するまで、README は編集しない。

## 事実（2026-09-25 に main `151ec20` で確かめたこと）

- **#102-1（目次）:** 解消済み。README には目次が無い。`grep -n '目次' README.md` は 0 件。
- **#102-2（`0.46.0`）:** 解消済み。`grep -n '0\.46\.0' Dockerfile.claude README.md` は 0 件。
- **#102-3（`auth.openai.com`）:** 許可が要ることは、既に実測されている。
  - `docs/codex-proc-investigation.md:107`（2026-09-23、Codex 0.156.0 の認証済み対話セッションでの受入）に記録がある。`chatgpt.com` と `auth.openai.com` の両方を許可しないと、TUI の起動時に `account/read failed ... workspace routing discovery failed` で終了する。
  - 補足の静的な根拠として、Codex の実体バイナリにトークン更新先の `https://auth.openai.com/oauth/token` が入っている。確かめたのは、ホストの Podman ストレージにある実体で、版は確かめていない。
  - 保守者の自運用の設定（`.claude-container.d/allowed-domains.txt`）にも、既に入っている。
  - README（445 行目の手順 2）は、`chatgpt.com` だけを許可するよう案内している。
- **#102-4:** README 678 行目の `CODEX_DIR` の段落は、`auth.json` が読めることは書いているが、次の 2 点を書いていない。
  - c3c が起動する構成の Codex の sandbox が、コンテナ内にマウントされた秘密（`SECRETS_DIR` のマウント先、`~/.claude`）を読めるかどうか。Codex 本体が指示として読み込むものと、sandbox 内のコマンドが読むものは区別する。読み取りの範囲は未確認で、Task 1 の 4 で公式ドキュメントを確かめる。
  - `-C /workspace` の `AGENTS.md` は、リポジトリ側が書ける指示である。
- **#102-5:** README 460 行目の #12128 の引用は、実体（`project_root_markers` が `AGENTS.md` の探索で無視される報告）と一致していない。
- **#127:** README 104 行目の `--clean` の段落は、削除済みの cwd から `.` を指定したときに止めることは書いている。一方、同じ状態の `--clean <子>` は、`$PWD` を使って台帳と照合して通る。この非対称は書いていない。
- **#5:** README 660 行目「制限しても残るリスク」が、ローテーション直後の数十秒を残るリスクとして書いている。`ssl_preread` 方式を見送った判断は書いていない。
- **#7:** README 251 行目と 273 行目が、フォールバックと WARNING を書いている。WARNING を一律に出す理由（移行漏れの検知）は書いていない。

## Task 1: #102 の残り（3・4・5）

**Files:** `README.md`

- [ ] 3: 手順 2（445 行目）で、許可するドメインに `auth.openai.com` を加える。
  - 理由: 起動時のアカウント確認（workspace routing discovery）とトークン更新（`https://auth.openai.com/oauth/token`）に使う。許可しないと、TUI の起動時に `account/read failed ... workspace routing discovery failed` で終了する。
  - 根拠は `docs/codex-proc-investigation.md` の受入記録（Codex 0.156.0 での実測）とする。
  - 「トークンの期限が切れた日の更新」の挙動は実測していない。README には、起動時の失敗（実測済み）を主な理由として書く。
  - 470 行目の「前節と同じ通信許可」は、手順 2 を指しているので、そのままでよい。
- [ ] 4: 678 行目の `CODEX_DIR` の段落に、次の 2 点を足す。
  - 1 点目: c3c が起動する構成（`--sandbox read-only` と `workspace-write`）の Codex の sandbox を、コンテナ内にマウントされた秘密（`SECRETS_DIR` のマウント先、`~/.claude`、`CODEX_DIR`）を隠す境界として扱わない。
    - この構成で sandbox 内のコマンドから読めるかは、Codex の公式ドキュメント（sandbox と、読み取りの制限の設定とその既定値）で確かめ、URL を書く。
    - 公式に restricted read access の設定がある場合は、既定値と、c3c がそれを使っていないことを書く。
    - 「どのモードでも読み取りを制限しない」とは断定しない。
    - 確かめられなければ、1 点目は書かずに #102 に残す。
  - 2 点目: `-C /workspace` で読む `AGENTS.md` は、リポジトリ側が書ける指示である（Codex 本体が指示として読み込むもので、sandbox 内のコマンドの読み取りとは別）。
- [ ] 5: 460 行目を、「Codex が拾う `AGENTS.md` は起点（cwd）とリポジトリの境界で変わる（[openai/codex#12128](https://github.com/openai/codex/issues/12128) は、nested な `.git` が探索の境界になる例）」という趣旨に直す。「MCP 経路では `cwd` の渡し忘れで」の部分は、#12128 を根拠にしない書き方にする。

**Expected:** `grep -n 'auth.openai.com' README.md` が 1 件以上。`grep -n '12128' README.md` の行が MCP と `cwd` の渡し忘れを #12128 の根拠にしていない。

## Task 2: #127（`--clean` の非対称を明記する）

**Files:** `README.md`

- [ ] 104 行目の「cwd が削除済みのまま `.`・`..` を指定した場合も同様で…」の文の後に、次の趣旨の 1 文を足す。
  - 同じ状態でも、`--clean <存在しない子ディレクトリ名>` は、環境の `PWD` と結合した絶対パスが起動台帳にあれば、それを対象にして進む（`resolve_project_directory()` の台帳照合の分岐）。
  - 環境の `PWD` が無いか空なら止まる（#110）。
  - 実在する相対パス（`.`・`..`・`../<隣>` など）は、`pwd -L` が相対のまま返すので止まる（2026-09-25 に bash で実測。`../sibling` も相対のまま返った）。
  - `.`・`..` は、利用者の意図が曖昧なので絶対パスを求める（#127）。

**Expected:** `grep -n '#127' README.md` が 1 件。

## Task 3: #5 と #7 の判断を記録する

**Files:** `README.md`

- [ ] #5: 660 行目「制限しても残るリスク」の、ローテーションの文の後に次の趣旨を足す。
  - SNI を見るプロキシ（nginx の `ssl_preread`）への置き換えは、検討したうえで見送った（#5）。
  - 再検討するのは、ローテーションが原因の接続失敗で作業の中断が月 5 回以上になった場合と、ECH が普及した場合。
- [ ] #7: 251 行目のフォールバックの文の後に次の趣旨を足す。
  - 置かなかったときの WARNING は、プロジェクト固有の設定の移行漏れ（2026-07-02 の事故）に気づくためのもので、意図的に置かないプロジェクトにも出す（#7）。
  - 再検討するのは、既存の利用側プロジェクトの移行がおおむね済んだと判断できる時期と、置かないプロジェクトの方が多くなった場合。そのときは #7 を参照して新しい Issue を立てる。

**Expected:** 表記は README の既存の Issue 参照の書き方（`` [`#NN`](URL) ``）に合わせる。`grep -c 'issues/5)' README.md` と `grep -c 'issues/7)' README.md` が、それぞれ 1 以上。

## Task 4: 検証

- [ ] `./lint.sh` が rc 0（README の表と許可リストの一致検査を含む）。
- [ ] `git diff --stat` が `README.md` と本計画だけ。
- [ ] 文体は README「表記」節に従う。

## PR

- 本文: `Closes #127`。#102 は、Task 1 の 3・4・5 をすべて反映できたときだけ `Closes #102` にする。4 の 1 点目を確かめられず #102 に残した場合は `Refs #102` にし、残した項目を #102 にコメントする。#5 と #7 は閉じ済みなので `Refs`。
- 作業の区分により、PR 後に Codex と Claude の二重レビューを行う。

## リリース判定

文書だけなので、タグは提案しない。

区分: 通常 — README のセキュリティモデル節（`CODEX_DIR` で読めるものの説明）に触れるが、規則・権限・秘密の扱いは変えず、現状の説明を正確にするだけ。挙動の変更は無い（計画と PR 後に二重レビュー）。
推奨実装: Sonnet — 実装者の判定基準の 3（実装中に判断が残る）に当たる。Task 1 の 4 で、Codex の公式ドキュメントの読み取り範囲を調べ、書ける範囲を決める判断が残るため。逐語の手順まで確定していないので、4（Codex）には当たらない。Opus を使うほどの境界の判断は無い。
実装: Sonnet（持ち主指定、2026-09-25。計画を書いたこのセッションで、コード側の PR の後にモデルを Sonnet に切り替えて実装する）

## 計画レビューの記録

2026-09-25 初回。Codex（`codex exec --sandbox read-only`）と Claude（`claude-opus-5-5`、headless、Read/Grep/Glob のみ）が独立にレビューした。両者とも「修正後に渡せる」。

- Important（Claude A-1）: `auth.openai.com` が要ることは `docs/codex-proc-investigation.md:107` で実測済みで、理由も「トークン更新」だけではない → 根拠と理由を差し替えた。
- Important（Codex 1）: #102 を無条件に閉じる書き方 → 条件付きの `Closes` にした。
- Important（Codex 2）: 読み取りの範囲を全モード共通として断定している → 確かめられた範囲に限る書き方にした。
- Important（Codex 3）: #7 の再検討トリガーが抜けている → 足した。
- Important（Claude A-2）: #127 の記述と、コード計画の #126-3 が食い違う。
  - 2026-09-25 に bash で実測した結果、削除済みの cwd からの `cd ../sibling` の後、`pwd -L` は PWD の有無にかかわらず相対の `../sibling` を返した。したがって、今の実装は止まる。
  - #127 の記述は「存在しない子」に限る書き方にして、コード計画と揃えた。
- Minor: grep の書式（Claude A-3）、PWD が無いときの #110（A-4）、バイナリのパス（Codex Minor 1。確認を不要にしたので削除）、推奨実装の理由（Codex Minor 2）→ 反映した。
- 区分を境界にするか（Claude A-5）: 許可を勧めるエグレス先を足すが、Codex を使う利用者が既に必要としている先の記述を正すだけなので、通常のままとした。持ち主の確定を待つ。
- 確認限定巡（同日）: Claude（`--resume`）は「実装に渡せる」と判定した。Codex は、事実の節に旧い断定（全モードでファイルシステム全体を読める）が残っていると指摘した → Task 1 と同じ限定に直した。
- 2 巡目の確認限定巡（同日）: Codex（新しい `codex exec`）は、前回未完了とした項目をすべて解消と判定し、「実装に渡せる」とした。これで両レビュアーとも「実装に渡せる」になった。計画の静的なレビューで、実装・テストは not run。
