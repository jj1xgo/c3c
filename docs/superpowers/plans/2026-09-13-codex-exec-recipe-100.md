# README の Codex レシピを `codex exec` 経由に改める計画（#100）

> 実行担当: Codex（host の checkout で `/goal` に渡す。末尾「実装者」参照）。編集対象は README.md のみ。各 Task の置換文は逐語で確定しており、実装中に設計判断は残らない。

**目的:** codex-cli 0.154.0 で削除された `codex mcp-server` を前提にしている README の Codex レシピを、`codex exec`（非対話 CLI）経由の手順に書き換え、`codex-version.txt` の `latest` が手順を黙って壊しうる旨を添える。

**構成:** 既存の Codex レシピ（現在は「MCP サーバーの追加」節の末尾に stdio 型の具体例として置かれている）を独立した `##` 節に昇格し、手順 5 の `.mcp.json` 登録を `codex exec` の呼び出しに置き換える。レシピを参照している 4 箇所の節名を追随させ、セキュリティモデル節の「TOFU の対象になる」を「対象外」に直す。

**根拠（1 次情報、2026-09-13 に確認）:**

- openai/codex の release notes: rust-v0.149.0 で「deprecated MCP server の起動時に警告」、rust-v0.154.0（2026-09-09）で「The deprecated `codex mcp-server` entry point is no longer available. (#42993)」。
- ホストの codex-cli 0.154.0 の `codex --help` に `mcp-server` は無い。`codex mcp` は外部 MCP サーバーを Codex に登録する用途（`list/get/add/remove/login/logout`）。`codex exec --help` に `-s, --sandbox <read-only|workspace-write|danger-full-access>`・`-C, --cd <DIR>`・`--skip-git-repo-check`・`-o, --output-last-message <FILE>` がある。
- ホストで `codex exec --sandbox read-only --skip-git-repo-check -C <空ディレクトリ> "Reply with exactly the single word: pong"` を実行し、最終行 `pong`・終了コード 0・生成物なしを確認した（ホストの `~/.codex` 認証。コンテナ内では未実行）。
- Issue: [jj1xgo/claude-container#100](https://github.com/jj1xgo/claude-container/issues/100)。

## 共通条件

- 文書は日本語のみ（README「表記」節）。英語の固有名（コマンド名・フラグ・Issue 名）はそのまま。
- README.md 以外は編集しない。SECURITY-CLAIMS.md と `.claude-container.d/env.example` には `mcp-server` や「Codex を MCP サーバーとして」の記述が無いことを確認済み（編集不要）。
- 置換は下記の逐語テキストどおりに行う。語句を改善しない。行番号は `main` の `5869603` 時点のもので、目印にはなるが照合は旧文で行う。
- バージョン例 `0.46.0` は 3 箇所とも現行の `0.154.0` に置き換える（固定版を推奨する文の隣に 2025 年の版を例示しないため）。
- 未検証のフラグ（`--ephemeral` 等）や、許可ドメインの追加（`auth.openai.com` 等）は書かない。

## Task 1: レシピを独立節にし、手順 5 を `codex exec` に置き換える

対象: `README.md` 272〜296 行（「MCP サーバーの追加」節の末尾、`## アーキテクチャ` の直前）。

- [ ] 272 行目の見出し行を置き換える。

  旧（1 行）:
  ```
  **Codex CLI をセカンドオピニオン用 MCP サーバーとして使う場合のレシピ**（`stdio` タイプの具体例。内部運用issue参照）:
  ```
  新（見出し＋空行＋段落）:
  ```
  ## Codex CLI をセカンドオピニオンとして使う

  OpenAI の Codex CLI をコンテナ内の Claude Code セッションから諮問・レビュー用のセカンドオピニオンとして呼ぶ場合のレシピ。Codex は `codex exec`（非対話 CLI）として呼び出す。以前はここに Codex を stdio 型 MCP サーバー（`codex mcp-server`）として `.mcp.json` に登録する手順を載せていたが、上流の codex-cli が rust-v0.149.0 で `codex mcp-server` を非推奨にし、rust-v0.154.0（2026-09-09、[openai/codex#42993](https://github.com/openai/codex/pull/42993)）で削除したため、MCP 経路は案内しない（0.153.0 以前に固定すれば動くが非推奨経路のため推奨しない。[`#100`](https://github.com/jj1xgo/claude-container/issues/100)）:
  ```

- [ ] 手順 1（旧 274 行）の版の例を置き換える。

  旧の部分文字列: `導入したい Codex のバージョン（例: \`0.46.0\`）または \`latest\` を書く`
  新の部分文字列: `導入したい Codex のバージョン（例: \`0.154.0\`。固定版を推奨）または \`latest\` を書く`

- [ ] 手順 5（旧 283〜293 行、`.mcp.json` の JSON ブロックを含む 11 行）を丸ごと置き換える。

  旧:
  ````
  5. ターゲットプロジェクトの `.mcp.json` に以下のように書く（`codex mcp-server` は stdio 型のため、初回起動時に前述の対話確認〈TOFU〉が発火する）:
     ```json
     {
       "mcpServers": {
         "codex": {
           "command": "codex",
           "args": ["mcp-server"]
         }
       }
     }
     ```
  ````
  新:
  ````
  5. コンテナ内の Claude Code セッションから、通常のコマンドとして呼ぶ（`.mcp.json` には登録しない）:
     ```bash
     codex exec --sandbox read-only -C /workspace "<依頼文>"
     ```
     `--sandbox read-only` は省略しない（呼び出し時の `--sandbox` が `config.toml` の値に勝つ。諮問・レビュー用途は読み取り専用で足りる）。`-C /workspace` で作業ルートを明示する（Codex は作業ルートの `AGENTS.md` を指示として読むため、起点を固定する）。最終応答だけをファイルに取りたい場合は `-o <ファイル>` を足す。`/workspace` が git リポジトリでない場合は `--skip-git-repo-check` が必要
  ````

- [ ] 「運用上の注意」段落（旧 296 行、1 行）を置き換える。

  旧:
  ```
  **運用上の注意**: MCP サーバー経由の呼び出しは Claude Code 側が `cwd` を明示的に渡す必要があり、渡し忘れると意図しない `AGENTS.md` が拾われるリスクがある（[openai/codex#12128](https://github.com/openai/codex/issues/12128)）。諮問時は `/workspace` を起点にする運用を徹底すること。また auth.json のリフレッシュフローには既知の不具合報告（[openai/codex#15502](https://github.com/openai/codex/issues/15502)）があり、この領域は枯れていない可能性がある点に留意する。
  ```
  新:
  ```
  **運用上の注意**: Codex は作業ルートの `AGENTS.md` を指示として読む。MCP 経路では `cwd` の渡し忘れで意図しない `AGENTS.md` が拾われる問題があった（[openai/codex#12128](https://github.com/openai/codex/issues/12128)）。`codex exec` でも起点が変われば同じことが起きるので、`-C /workspace` を毎回明示する運用を徹底すること。また auth.json のリフレッシュフローには既知の不具合報告（[openai/codex#15502](https://github.com/openai/codex/issues/15502)）があり、この領域は枯れていない可能性がある点に留意する。
  ```

- [ ] 確認する。
  ```bash
  grep -n 'mcp-server' README.md
  ```
  Expected: 新しい節の導入段落（`## Codex CLI をセカンドオピニオンとして使う` の 2 行下）の 1 行だけが出る。JSON ブロックの `"args": ["mcp-server"]` は出ない。
  ```bash
  grep -n '^## ' README.md | sed -n '/MCP サーバーの追加/,/アーキテクチャ/p'
  ```
  Expected: `## MCP サーバーの追加`、`## Codex CLI をセカンドオピニオンとして使う`、`## アーキテクチャ` の 3 行がこの順で出る。

## Task 2: レシピへの参照 4 箇所と `latest` の注意を追随させる

対象: `README.md` 85・125・140・303・406 行。

- [ ] 85 行（環境変数表の `CODEX_DIR` 行）の部分文字列を置き換える。

  旧: `専用ディレクトリを推奨（後述「MCP サーバーの追加」節の Codex レシピ）`
  新: `専用ディレクトリを推奨（後述「Codex CLI をセカンドオピニオンとして使う」節）`

- [ ] 125 行（`.claude-container.d/` 一覧のコードブロック内）を置き換える。

  旧:
  ```
  .claude-container.d/codex-version.txt    # 導入する Codex CLI のバージョン（例: 0.46.0 または latest、1行のみ）。-b 必須、コミット対象
  ```
  新:
  ```
  .claude-container.d/codex-version.txt    # 導入する Codex CLI のバージョン（例: 0.154.0、または latest。固定版を推奨、1行のみ）。-b 必須、コミット対象
  ```

- [ ] 140 行（`codex-version.txt` の説明段落）で 2 箇所を置き換える。

  旧の部分文字列 1: `固定バージョン（例: \`0.46.0\`）の代わりに \`latest\` と書くと`
  新の部分文字列 1: `固定バージョン（例: \`0.154.0\`）の代わりに \`latest\` と書くと`

  旧の部分文字列 2（段落末尾）:
  ```
  MCP サーバーとしての使い方は後述「MCP サーバーの追加」節の Codex レシピを参照。
  ```
  新の部分文字列 2:
  ```
  `latest` では上流の変更（サブコマンドの廃止やフラグの変更）が次の `-b` 再ビルドでそのまま入るため、README の手順や利用側プロジェクトの設定が黙って壊れうる（実例: codex-cli は `codex mcp-server` を rust-v0.149.0 で非推奨にし、rust-v0.154.0 で削除した。[`#100`](https://github.com/jj1xgo/claude-container/issues/100)）。手順の安定を要するプロジェクトは固定版を推奨する。コンテナ内からの呼び出し方は後述「Codex CLI をセカンドオピニオンとして使う」節を参照。
  ```

- [ ] 303 行（アーキテクチャ節の `compose.yml` の説明）の部分文字列を置き換える。

  旧: `auth.json のトークンリフレッシュ書き戻しのため。前述「MCP サーバーの追加」節の Codex レシピ参照）`
  新: `auth.json のトークンリフレッシュ書き戻しのため。前述「Codex CLI をセカンドオピニオンとして使う」節参照）`

- [ ] 406 行（セキュリティモデル節の `CODEX_DIR` 段落）で 2 箇所を置き換える。

  旧の部分文字列 1: `\`CODEX_DIR\`（前述「MCP サーバーの追加」節の Codex レシピ）を設定した場合`
  新の部分文字列 1: `\`CODEX_DIR\`（前述「Codex CLI をセカンドオピニオンとして使う」節）を設定した場合`

  旧の部分文字列 2（段落末尾の 1 文）:
  ```
  Codex を stdio 型 MCP サーバーとして `.mcp.json` に登録する場合は前述の MCP 監査ゲート（TOFU）の対象になる。
  ```
  新の部分文字列 2:
  ```
  Codex は `codex exec` としてセッション中に Claude が判断して実行する通常のコマンドであり、`.mcp.json` には登録しないため、前述の MCP 監査ゲート（TOFU）の対象外である。同ゲートが対象とするのは「セッション開始と同時に人間・モデルどちらの判断も挟まず実行される」経路であり、`codex exec` はそれに当たらない。
  ```

- [ ] 確認する。
  ```bash
  grep -n '「MCP サーバーの追加」節の Codex レシピ' README.md; echo "exit=$?"
  ```
  Expected: 出力なし、`exit=1`。
  ```bash
  grep -c '「Codex CLI をセカンドオピニオンとして使う」節' README.md
  ```
  Expected: `4`（85・140・303・406 行の参照。Task 1 の見出しは `## ` 形式で「」節の形を含まず、手順 1 の参照先は「利用側プロジェクトの設定」節なので数に入らない）。
  ```bash
  grep -n '0\.46\.0' README.md; echo "exit=$?"
  ```
  Expected: 出力なし、`exit=1`。

## 検証

- [ ] `./lint.sh` を実行する。Expected: 終了コード 0（README のみの変更なので失敗しないことの確認）。
- [ ] `./test-build.sh --launcher-only` を実行する。Expected: 全件 PASS（E7 が環境変数表のキー列を照合する。85 行の編集は説明列のみでキー列に触れない）。
- [ ] ホストで手順 5 のコマンドを実走し、形式を確認する。
  ```bash
  d=$(mktemp -d) && codex exec --sandbox read-only --skip-git-repo-check -C "$d" "Reply with exactly the single word: pong"; echo "exit=$?"; ls -A "$d"; rmdir "$d"
  ```
  Expected: 出力の最終行付近に `pong`、`exit=0`、`ls -A` は空。ホストの `~/.codex` の認証を使う。
- [ ] Task 1・2 完了後の最終状態で `grep -n 'mcp-server' README.md` を実行する。Expected: ちょうど 2 行（140 行の `latest` の注意と、新節の導入段落）。
- [ ] `git diff --stat` で変更ファイルが `README.md` だけであることを確認する。
- **not run（この計画では実施しない）**: コンテナ内での `codex exec` の実走（`CODEX_DIR` マウント越しの認証、`allowed-domains.txt` が `chatgpt.com` だけで足りるか、ファイアウォール下の挙動）。レシピはコンテナ内向けに書くが検証はホストのみ。sotlas-frontend が `.mcp.json` から `codex` を外して `codex exec` に切り替える予定なので、最初のコンテナ内検証はそちらで行われる。PR 本文にこの旨を書く。

## 範囲外（この計画では触らない）

- この repo 自身の `.claude-container.d/codex-version.txt`（`latest`）。`.mcp.json` が無いので実害は無い。
- tag と Release。文書のみの変更なので、付けるかどうかは持ち主の判断。
- `allowed-domains.txt` への `auth.openai.com` 追加の要否。知見ノートに記述があるが今回は未検証。
- #98（plugin の cache-miss）と #99（`@~/obsidian-vault` の解決）。別機構なので別計画。

## コミットと PR

- ブランチ: `docs/codex-exec-recipe-100`（`main` の `5869603` から切り、この計画ファイルのコミットを載せた状態で引き渡す。Codex は新たに切らず、このブランチを checkout して続ける）。
- コミットメッセージ（1 コミット）:
  ```
  docs: Codex レシピを codex exec 経由に改め、mcp-server 削除に追随する（#100）
  ```
- PR タイトル: `docs: Codex レシピを codex exec 経由に改める（#100）`。本文に「Closes #100」、検証節の実行結果（lint・launcher-only・ホスト実走）、not run の項目を書く。
- PR を作る前に `claude-review` skill（`~/.agents/skills/claude-review`、Claude Opus 読み取り専用）のレビューを受ける。
- マージは持ち主が手で行う。

## 実装者

**実装: Codex** — README.md のみ、host の checkout で完結し、置換文と Expected が逐語で確定しているため（判定基準 4）。

`/goal` に渡す文面:

```
docs/superpowers/plans/2026-09-13-codex-exec-recipe-100.md を上から順に実施する。

既決事項（蒸し返し不要）: Codex レシピは `codex exec` 経由に改める。MCP 経路は案内しない。レシピは独立した `##` 節に昇格する。置換文は計画の逐語テキストどおりで、語句の改善はしない。版の例は 0.154.0。

制約: 編集するのは README.md だけ。計画ファイル自身と他のファイルは変更しない。検証用の一時ファイルは mktemp の範囲で作って消す。Expected と実結果がずれたら修正せず止めて報告する。

手順: 既存ブランチ docs/codex-exec-recipe-100 を checkout する（計画ファイルのコミットが載っている。新たに切らない）→ Task 1 → Task 2 → 検証（lint.sh、test-build.sh --launcher-only、ホストでの codex exec 実走）→ 計画記載のメッセージで 1 コミット → claude-review skill（~/.agents/skills/claude-review）でレビューを受け、should-fix 以上があれば直してから → push → gh pr create（本文に Closes #100、検証結果、not run 項目）。

成果物: PR の URL と、検証コマンドごとの実出力（Expected との照合）、未実行項目の一覧。
```

- sandbox: `workspace-write`（README 編集・ブランチ作成・コミット）。
- ネットワーク: 必要（`git push`・`gh pr create`・`claude-review`）。
