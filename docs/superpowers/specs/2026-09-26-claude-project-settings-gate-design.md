# Claude 経路の project 設定に起動前ゲートを設ける（#163）設計

**Issue:** [#163](https://github.com/jj1xgo/c3c/issues/163)
**状態:** 設計の合意済み（持ち主 2026-09-26、会話上で方向 A・hash 範囲・`settings.local.json` の扱いを選択）。spec の二重レビュー待ち。
**区分:** 境界（セッション開始と同時に秘密を読めるコードを実行させる経路に、新しいゲートを置く。`c3c`・`entrypoint.sh`・`compose.yml`・`Dockerfile.claude` と SECURITY-CLAIMS の保証範囲を変える）。

## 目的

Claude 経路で、リポジトリ同梱の Claude Code の project 設定（hook・`env`・helper・plugin 等）が、運用者の確認なしにセッション開始と同時に効く状態をなくす。README「帰結の重大性で線を引いている」節（`claude-container#29`）の基準を、`.mcp.json` の stdio だけでなく project 設定にも一貫して適用する。

成功条件:

- `/workspace/.claude/` の対象ファイル（後述）が初回、または前回承認から変わった状態で `c3c`（Claude 経路）を起動すると、Claude Code の起動前に内容の一覧と `[y/N]` の確認が出る。拒否・TTY なしは起動しない。
- 承認済みで変化がなければ確認なしで起動する。
- project 設定で plugin の有効化・marketplace の定義・skills-directory plugin があれば、確認の前に起動を止める。
- ホストの `~/.claude.json` を c3c が書き換えない。

## 背景と事実（2026-09-26 確認）

- Claude Code は workspace trust を `~/.claude.json` の `projects["<repo root>"].hasTrustDialogAccepted` に保存する（公式 [permissions](https://code.claude.com/docs/en/permissions#project-allow-rules-and-workspace-trust)）。c3c は全プロジェクトを `/workspace` にマウントし、`~/.claude.json` を rw 共有する（`compose.yml`）。保守者のホストには `"/workspace"` のキーが実在し `hasTrustDialogAccepted` を持つ。したがって trust は全プロジェクトで 1 つで、一度受け入れると以降どの repo も trust 済みで開く。
- 公式「What runs before you trust a folder」表: trust 後は settings の hook・`env`・`apiKeyHelper` 等の helper、project skill の hook と `allowed-tools`、`permissions.allow`・`additionalDirectories`、subagent frontmatter の hook と inline `mcpServers`、`@skills-dir` plugin、`extraKnownMarketplaces` が使われる。起動時の trust ダイアログは allow 規則と `additionalDirectories` を一覧すると書かれている。`/cd` の trust プロンプトは v2.1.246 以降 hook と helper も一覧すると書かれているが、起動時のダイアログが hook の内容を一覧するかは明記されていない（未実測）。
- 公式 [plugins/loading](https://code.claude.com/docs/en/plugins/loading): project の `enabledPlugins` は user 層より優先される。`.claude/skills/<dir>/.claude-plugin/plugin.json` があれば `@skills-dir` plugin として、trust 後に読み込まれる（manifest の `defaultEnabled` または settings で有効）。c3c はホストの `~/.claude/plugins` を `:ro` で共有するため、ホストで install した plugin を repo から有効にできる。
- 公式の表にない key（例: `statusLine` の `command`）も起動時に実行される。対象は開放集合で、key の列挙は網羅できない。
- 持ち主の 3 repo（c3c・findsummits・sotlas-frontend）は、いずれも `.claude/settings.json` に hook を持つ。`enabledPlugins`・`extraKnownMarketplaces`・`env`・`apiKeyHelper` はどれにもない。findsummits と sotlas-frontend は未追跡の `settings.local.json` に allow 規則（17 件・3 件）を持つ。
- launcher は現在、対象 repo で git を実行しない。repo の `.git/config`（`core.fsmonitor` 等）がホストで実行される経路を作らないため、本設計でも実行しない。

## 設計

### 方式の選択

採用: ホスト側の TOFU ゲート（`.mcp.json` ゲートと C-3 と同じ型）。

不採用:

- 起動のたびに `/workspace` の trust を外して Claude Code のダイアログに任せる: 記録はコンテナから書き換えられる `~/.claude.json` にあり、README の「承認系の設定は壁に数えない」と同じ理由で壁にならない。起動時のダイアログが hook の内容を一覧するかも明記されていない。launcher がホストの生きた `~/.claude.json` に書くことになり、ホストのセッションや同時に動く別コンテナとの書き込み競合・書き戻しが残る。旧イメージ（`--dangerously-skip-permissions`）でダイアログが出るかも未確認。
- 文書化だけ: #29 の基準と実装がずれたままになる。

### 審査対象

`$WORKING_DIR`（コンテナ内 `/workspace`）配下の次のファイル。`.claude` 自体が symlink でもたどる（Claude Code と同じ見え方にする）。

| 対象 | hash に入れる部分 | 理由 |
| --- | --- | --- |
| `.claude/settings.json` | ファイル全体（バイト列） | hook・`env`・helper・`statusLine`・allow など、未知の key も含めて拾う |
| `.claude/settings.local.json` | ファイル全体（追跡の有無にかかわらず、存在すれば） | 追跡の判定に git が要るため（前述）。コンテナ内で書き足された hook も次回起動で検出できる |
| `.claude/agents/` 配下の `*.md`（再帰） | frontmatter（先頭の `---` 行から次の `---` 行まで）のバイト列 | frontmatter の hook・inline `mcpServers` |
| `.claude/skills/` 配下の `SKILL.md`（再帰） | frontmatter のバイト列 | frontmatter の hook・`allowed-tools` |

hash の入力は、対象ごとの「相対パス・種別・内容のバイト列」を相対パス順に並べた正規形とする（正確な符号化は実装計画で固定する）。frontmatter の無い `.md` は「frontmatter なし」として扱い、パスだけを入れる。対象が 1 つも無ければ確認なしで通す（記録も不要）。

対象外（限界として明記する）: `.claude/commands/`（利用者が呼んだときだけ実行）、`CLAUDE.md` とその import（コード実行の経路ではない）、`/workspace` のサブディレクトリにある `.claude/`（入れ子の repo や、サブディレクトリで起動した場合の探索）、`--add-dir` の追加ディレクトリ、Codex 経路（Codex は `.claude/` の設定を読まない。C-3 が別途審査する）。

### 判定

1. 起動前に止める（確認を出さない。承認記録があっても止める）:
   - `settings.json` または `settings.local.json` の `enabledPlugins` に、値が `false` でないエントリがある。
   - 同じく `extraKnownMarketplaces` にエントリがある。
   - `.claude/skills/` 配下に `.claude-plugin/plugin.json` がある（skills-directory plugin）。
2. 判定不能として止める: settings が JSON として壊れている・最上位がオブジェクトでない、対象ファイルが通常ファイルでない（FIFO 等。`O_NONBLOCK` で開いて `fstat` する）、`.claude/agents/` か `.claude/skills/` の配下に symlink のディレクトリがある（中身を列挙できない）、frontmatter の開始行はあるが終了行が無い、ファイルが上限（実装計画で決める）を超える。
3. 対象なし → 通す。hash が承認記録と一致 → 通す。それ以外（初回・変更）→ 確認を出す。

`.mcp.json` ゲートは解析失敗時に先へ進むが、本ゲートは境界なので fail-closed にする。stdio MCP の承認は従来どおり `.mcp.json` ゲートが担い、本ゲートとは独立させる（片方の承認がもう片方を兼ねない）。

### 確認の表示

- 対象ファイルの一覧と、settings については hook のコマンド・`env` の key 名（値は出さない）・helper と `statusLine` のコマンド・allow 規則・`additionalDirectories`・その他の最上位 key 名を出す。frontmatter は、`hooks`・`mcpServers`・`allowed-tools` の key を含むものだけ frontmatter 全体を出し、それ以外は件数だけを出す。
- 表示は ASCII 制御文字を除く（`.mcp.json` ゲートと同じ方針、`claude-container#35`）。長い場合の切り詰め規則は実装計画で決める。hash は表示ではなく内容全体から計算する（表示の省略が承認の範囲を狭めない）。
- 文言で「承認は定義の承認で、スクリプトの中身や安全性は保証しない」「セッション開始と同時に実行され、export された秘密を読める」ことを伝える。

### 処理の流れ

新しい固定アセット `claude-project-audit.py`（python3 標準ライブラリだけ。`-I` で起動）を、ホストとイメージの両方で使い、正規化と hash を 1 か所にまとめる。

ホスト（`c3c`、Claude 経路、`-b` のビルドより前。`check_mcp_approval()` の隣）:

1. python3 が無い場合は判断せず、コンテナ内のゲートに任せる（`.mcp.json` ゲートの `nojq` と同じ）。
2. 止める判定・判定不能 → 理由を出して起動を中止する。
3. 承認済み → 承認記録ファイルを `CLAUDE_PROJECT_APPROVAL_FILE` として export する。
4. 未承認か変更あり → 一覧を出し `/dev/tty` で確認する。y なら記録して export、それ以外は中止。TTY が無ければ記録を渡さずコンテナ内のゲートに任せる。

承認記録: `$HOME/.local/state/claude-container/mcp-approvals/claude-project/$PROJECT_NAME`（hash のみ、`chmod 600`、ディレクトリ `700`）。既存の `mcp-approvals` 配下に置き、`--clean-all` の一括削除に含める。`clean_project()` は当該ファイルを削除する。格納パスは `MCP_APPROVAL_STORE` と同じく `load_env_file()` より前に `$HOME` から算出し `readonly` にする。`compose.yml` は `${CLAUDE_PROJECT_APPROVAL_FILE:-/dev/null}` を `/etc/claude-container/claude-project-approved-hash` へ `:ro` でマウントし、env 経由の値は参照しない（launcher が全分岐で明示 export する）。

コンテナ（`entrypoint.sh`、`CC_AGENT=claude` のときだけ、Claude Code を起動する前）:

1. 同じスクリプトで `/workspace` を審査し直す。止める判定・判定不能 → 中止。
2. 対象なし・記録と一致 → 進む。
3. 不一致か記録なし → 一覧を出し `/dev/tty` で確認する。TTY が無ければ中止（fail-closed）。y でも記録しない（記録先は `:ro`）。

環境変数による opt-out は設けない（#29。`.c3c/env` に書くだけで迂回できるため）。

### `--check`

Claude 経路の診断に 1 行を足す: `[OK]` 対象なし／承認済み、`[INFO]` 未承認・変更あり（初回起動時に確認が出る）、`[FAIL]` plugin 等で止まる・判定不能、`[WARN]` ホストに python3 が無く事前判定できない。Codex 経路では `[INFO]` で「使用しない」と出す（`.mcp.json` ゲートの診断と同じ扱い）。`--check` は確認を出さず、記録も書かない。

### 旧イメージと版

- ホスト側のゲートはイメージの版に依存しない。コンテナ内の再照合は `-b` で作り直すまで効かない。新しいアセットを境界アセットのドリフト検出の対象に入れ、既存の `WARNING` を再ビルドの合図にする。
- 網羅性（審査対象の集合）は、実装時に確認した Claude Code の版と公式ドキュメントの日付でだけ成り立つ。同梱の既定は `CLAUDE_CODE_VERSION=latest` なので、新しい版が新しい経路を足しても追えない。これを限界として明記し、再確認契機に「Claude Code の設定形式・trust の仕様の変更」を入れる。

## 文書

- README「セキュリティモデル」節: #29 の適用範囲を project の Claude 設定に広げる。`/workspace` の trust が全プロジェクトで共有されていること、本ゲートがそれを補うこと、残る経路（下記）を書く。「MCP サーバーの追加」節の近くに確認の出方と再確認の条件を書く。「変更後の確認」節に新アセットの検証を足す。
- SECURITY-CLAIMS: C-5 を新設する（成立条件・脅威モデル、保証する動作、限界・非対象、根拠・検証範囲、再確認契機）。
- `docs/development-invariants.md`: 新アセットを固定アセットの一覧に加え、ホストとコンテナで同じスクリプトを使う不変条件、fail-closed、opt-out を作らないことを書く。AGENTS.md の「変更前に読む」対象一覧にも新アセットを加える。

## 残る経路（範囲外。限界として明記する）

- 承認後のセッション中に repo の設定が書き換えられた場合、そのセッションでは検出しない（次回起動で検出する）。
- コンテナ内で書き換えられた repo の hook が、ホストで Claude Code を起動したときにホストの権限で走る経路（ホスト側の trust の問題で、本ゲートの外）。
- `~/.claude.json` の `projects["/workspace"]` に、侵害されたセッションが local scope の MCP 等を書き足す経路（README の既存の記述と同じ）。
- 確認は定義の承認で、hook が呼ぶスクリプトや依存パッケージの中身は審査しない。

## 検証

- `claude-project-audit.py` の unittest: 正規化と hash（順序・パス・frontmatter の切り出し）、止める判定の各条件、判定不能の各条件、表示の制御文字除去。CI の `run_launcher_tests()` に登録する。
- `test-build.sh --launcher-only`: 対象なし、承認済み、未承認（y・N・TTY なし）、変更の検出、plugin・marketplace・skills-directory plugin で止まる、解析失敗で止まる、ホストに python3 が無いとき、`--check` の各状態、`compose` のマウントと env を参照しないこと、`--clean`／`--clean-all` の削除。
- 実機（`-b` で再ビルド）: 持ち主の 3 repo で初回に確認が出て 2 回目は出ないこと、hook を書き換えると再確認になること、ホストで承認した後に書き換えるとコンテナ内のゲートで確認になること、TTY なしで止まること。
- Issue の not run の解消: 使い捨ての repo で、修正前は `/workspace` の trust 共有により SessionStart hook が確認なしで走り、修正後はゲートで止まることを確かめる。ホストの実物の `~/.claude.json` は書き換えない。

## バージョン

既定の挙動が変わる（hook 等を持つ repo の初回起動で確認が出る、project 設定で plugin を有効にする repo は起動しなくなる）。後者は既存の利用側を止めうるため、MINOR か MAJOR かは README「バージョニング」節に照らして実装計画で判定する。移行が要る変更になる場合は、タグ提案前に `--check` がそれを検出できることを実機で確かめる。利用側への移行通知は ops リポジトリの運用に従う。タグは持ち主の承認後に付ける。
