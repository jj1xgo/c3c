# Claude 経路の project 設定に起動前ゲートを設ける（#163）設計

**Issue:** [#163](https://github.com/jj1xgo/c3c/issues/163)
**状態:** 設計の合意済み（持ち主 2026-09-26）。1 巡目の二重レビューを反映済みで、確認限定巡の待ち。
**区分:** 境界（セッション開始と同時に秘密を読めるコードを実行させる経路に、新しいゲートを置く。`c3c`・`entrypoint.sh`・`compose.yml`・`Dockerfile.claude` と SECURITY-CLAIMS の保証範囲を変える）。

## 目的

Claude 経路で、リポジトリ同梱の Claude Code の project 設定（hook・`env`・helper・plugin 等）が、運用者の確認なしにセッション開始と同時に効く状態をなくす。README「帰結の重大性で線を引いている」節（`claude-container#29`）の基準を、`.mcp.json` の stdio だけでなく、モデルや利用者の判断を挟まずに起動時に効く project 設定の全体へ一貫して適用する。

成功条件:

- 審査対象（後述）が初回、または前回承認から変わった状態で `c3c`（Claude 経路）を起動すると、Claude Code の起動前に内容と `[y/N]` の確認が出る。拒否・TTY なしは起動しない。
- 承認済みで変化がなければ確認なしで起動する。
- plugin の有効化・plugin の読み込み先の指定・marketplace の定義・skills-directory plugin・`.mcp.json` の `headersHelper` があれば、確認の前に起動を止める。
- 審査に対応しない旧イメージや、審査できない状態（ホストに python3 が無い等）で、黙って Claude Code を起動しない。
- ホストの `~/.claude.json` を c3c が書き換えない。

## 背景と事実（2026-09-26 確認）

- Claude Code は workspace trust を `~/.claude.json` の `projects["<repo root>"].hasTrustDialogAccepted` に保存する（公式 [permissions](https://code.claude.com/docs/en/permissions#project-allow-rules-and-workspace-trust)）。c3c は全プロジェクトを `/workspace` にマウントし、`~/.claude.json` を rw 共有する（`compose.yml`）。保守者のホストには `"/workspace"` のキーが実在し `hasTrustDialogAccepted` を持つ。したがって trust は全プロジェクトで 1 つで、一度受け入れると以降どの repo も trust 済みで開く。
- 公式「What runs before you trust a folder」表: trust 後は settings の hook・`env`・`apiKeyHelper` 等の helper、`permissions.allow`・`additionalDirectories`、`.mcp.json` のサーバーの `headersHelper`、subagent frontmatter の hook と inline `mcpServers`、`@skills-dir` plugin、`extraKnownMarketplaces` が使われる。起動時の trust ダイアログは allow 規則と `additionalDirectories` を一覧すると書かれている。`/cd` の trust プロンプトは v2.1.246 以降 hook と helper も一覧すると書かれているが、起動時のダイアログが hook の内容を一覧するかは明記されていない（未実測）。
- 公式 [plugins/loading](https://code.claude.com/docs/en/plugins/loading): project の `enabledPlugins` は user 層より優先される。`.claude/skills/<dir>/.claude-plugin/plugin.json` があれば `@skills-dir` plugin として、trust 後に読み込まれる。`CLAUDE_CODE_PLUGIN_DIRS` でも plugin を読み込める（project settings の `env` からこれが効くかは未確認）。c3c はホストの `~/.claude/plugins` を `:ro` で共有するため、ホストで install した plugin を repo から有効にできる。
- 公式 [skills](https://code.claude.com/docs/en/skills): `.claude/commands/` は skills と同じ frontmatter（hook・`allowed-tools` を含む）を受け付ける。入れ子の `.claude/skills/` は、Claude がそのサブディレクトリのファイルを読むか編集したときに読み込まれる。skill・command・subagent が効くのは、モデルか利用者が呼び出したときである。
- 公式の表にない key（例: `statusLine` の `command`）も起動時に実行される。対象は開放集合で、key の列挙は網羅できない。
- 持ち主の 3 repo（c3c・findsummits・sotlas-frontend）は、いずれも `.claude/settings.json` に hook を持つ。`enabledPlugins`・`extraKnownMarketplaces`・`env`・`apiKeyHelper` はどれにもない。findsummits と sotlas-frontend は未追跡の `settings.local.json` に allow 規則（17 件・3 件）を持つ。`.mcp.json` に `headersHelper` を持つものはない。
- launcher は現在、対象 repo で git を実行しない。repo の `.git/config`（`core.fsmonitor` 等）がホストで実行される経路を作らないため、本設計でも実行しない。
- Codex 経路（C-3）は、イメージ内の python3 を使う検査用コンテナ（preflight）で審査し、ホストで確認し、本起動で再照合する。対応 protocol の image label が無いイメージでは起動しない（`guard_codex_image_support()`）。

## 設計

### 方式の選択

採用: 検査用コンテナによる TOFU ゲート（C-3 と同じ型）。

不採用:

- 起動のたびに `/workspace` の trust を外して Claude Code のダイアログに任せる: 記録はコンテナから書き換えられる `~/.claude.json` にあり、README の「承認系の設定は壁に数えない」と同じ理由で壁にならない。起動時のダイアログが hook の内容を一覧するかも明記されていない。launcher がホストの生きた `~/.claude.json` に書くことになり、ホストのセッションや同時に動く別コンテナとの書き込み競合・書き戻しが残る。旧イメージ（`--dangerously-skip-permissions`）でダイアログが出るかも未確認。
- ホスト上の python3 で審査する: ホストとコンテナで symlink の解決先が違いうる（絶対パスのリンク等）。ホストに python3 が無いときや旧イメージのときの委譲が fail-open になる（1 巡目のレビュー指摘）。
- 文書化だけ: #29 の基準と実装がずれたままになる。

### 審査対象と基準

基準: repo が供給し、モデルや利用者の呼び出しを待たずにセッション開始時（または接続時）に効く設定。

| 対象（`/workspace` 配下） | 扱い |
| --- | --- |
| `.claude/settings.json` | ファイル全体（バイト列）を hash に入れる |
| `.claude/settings.local.json` | 同上。追跡の有無にかかわらず、存在すれば入れる（追跡の判定には git が要るため。コンテナ内で書き足された hook も次回起動で検出できる） |
| `.mcp.json` | `headersHelper` を持つサーバーがあれば止める（下の判定 1）。stdio の承認は従来どおり `.mcp.json` ゲートが担う |
| `.claude/skills/*/.claude-plugin/plugin.json` | 存在すれば止める（skills-directory plugin） |

hash の入力は、対象ごとの「相対パス・内容のバイト列」を、区切りの衝突が起きない単射な符号化（長さの前置き等）で、相対パスのバイト列の順に並べたものとする。正確な符号化は実装計画で固定する。hash の対象が 1 つも無ければ確認なしで通す。

対象外（「残る経路」に明記する）: `.claude/skills/`・`.claude/agents/`・`.claude/commands/` の frontmatter と本文（hook・`allowed-tools`・inline `mcpServers`・本文の `` !`cmd` `` を含む。効くのはモデルか利用者が呼び出したときで、#29 の基準の外）。入れ子の `.claude/` も同じ扱い。`CLAUDE.md` とその import。`--add-dir` の追加ディレクトリ。Codex 経路（C-3 が別途審査する）。

### 判定

判定・表示・hash は、1 回の読み取りの結果から作る（同じバイト列から 3 つを作り、別々に読み直さない）。

1. 起動前に止める（確認を出さない。承認記録があっても止める）:
   - settings の `enabledPlugins` に、値が `false` でないエントリがある。
   - settings の `extraKnownMarketplaces` にエントリがある。
   - settings の `env` に、名前が `CLAUDE_CODE_PLUGIN_` で始まる key がある（plugin の読み込み先を変える経路。project の `env` から効くかは未確認のため、保守的に止める）。
   - `.claude/skills/*/.claude-plugin/plugin.json` がある。
   - `.mcp.json` のサーバーに `headersHelper` がある（C-3 の `http_headers_helper` と同じ扱い）。
2. 判定不能として止める:
   - settings・`.mcp.json` が JSON として壊れている、最上位がオブジェクトでない、重複 key がある。
   - 対象のパス（`.claude` 自体、`.claude/skills`、各対象ファイル）に、解決先が `/workspace` の外に出る symlink がある。解決できない symlink（dangling・循環）も含む。
   - 対象ファイルが通常ファイルでない（FIFO 等。`O_NONBLOCK` で開いて `fstat` し、同じ fd から読む）。
   - ディレクトリの列挙やファイルの読み取りが失敗した（存在しないことは「対象なし」、読めないことは「判定不能」として区別する）。
   - ファイルが上限（実装計画で決める）を超える。
3. 対象なし → 通す。hash が承認記録と一致 → 通す。それ以外（初回・変更）→ 確認を出す。

`.mcp.json` ゲートは解析失敗時に先へ進むが、本ゲートは境界なので fail-closed にする。stdio MCP の承認は `.mcp.json` ゲートが、settings の承認は本ゲートが担い、片方の承認がもう片方を兼ねない。

### 確認の表示

- settings の 2 ファイルは、ASCII 制御文字を除いたファイル全体を表示する（未知の key に入ったコマンドや `env` の値も運用者に見せるため）。上限を超えて切り詰めたときは、切り詰めたことを明示する。hash は表示ではなく内容全体から計算する。
- `env` の値も表示する。`settings.local.json` に秘密を置けば確認表示に出る（限界として明記する。永続化するのは hash だけ）。
- 文言で「承認は定義の承認で、スクリプトの中身や安全性は保証しない」「セッション開始と同時に実行され、export された秘密を読める」ことを伝える。
- Unicode の bidi 制御等は除去しない（C-3 と同じ限界）。

### 処理の流れ

新しい固定アセット `claude-project-audit.py`（python3 標準ライブラリだけ）をイメージの `/usr/local/bin/` に root 所有 755 で置き、`USER node` より前に `COPY` する。`python3 -I` で起動する。イメージに新しい label `io.c3c.claude-project-audit-protocol` を付ける。

ホスト（`c3c`、Claude 経路）:

1. `/workspace` に当たる `$WORKING_DIR` に `.claude` か `.mcp.json` が存在しない（`-e` でも `-L` でもない）なら、本ゲートの処理を行わずに進む（旧イメージのままでもよい）。
2. どちらかが存在するなら、必要な明示ビルド（`-b`）の後に、イメージの label を照合する。一致しなければ `-b` を案内して止める。ホストに python3 が無ければ、検査用コンテナの出力を検証できないので止める。
3. 検査用コンテナを起動する（Codex の preflight と同じ作法: `compose.yml` と選択済みの override に、tty・stdin だけを上書きする固定 override を積み、`run --rm -T` と `</dev/null`。起動モードは launcher が明示 export する変数で指定する）。コンテナ内の `claude-project-audit.py` が `/workspace` を審査し、protocol の JSON 1 文書（判定・hash・表示用の行）を出す。ホストは python3 -I で厳密に検証する。
4. 止める判定・判定不能 → 理由を出して起動を中止する。
5. 対象なし → 記録を渡さずに進む。承認済み（記録の protocol と hash が一致）→ 記録ファイルを `CLAUDE_PROJECT_APPROVAL_FILE` として export する。
6. 未承認か変更あり → 表示して `/dev/tty` で確認する。y なら記録を書いて export する。それ以外・TTY なしは中止する。

承認記録: `$HOME/.local/state/claude-container/mcp-approvals/claude-project/$PROJECT_NAME.json`。内容は `{"protocol_version":N,"hash":"<64 桁の小文字 hex>"}`。書き込みは `write_codex_record()` と同じく、umask 077、ディレクトリ 700、同じディレクトリの一時ファイルからの atomic replace にする。格納パスは `MCP_APPROVAL_STORE` と同じく `load_env_file()` より前に `$HOME` から算出し `readonly` にする。`--clean-all` は既存の `mcp-approvals` 一括削除に含まれ、`clean_project()` は当該ファイルを削除する。`compose.yml` は `${CLAUDE_PROJECT_APPROVAL_FILE:-/dev/null}` を `/etc/claude-container/claude-project-approved.json` へ `:ro` でマウントし、env 経由の値は参照しない。launcher は Claude 経路・Codex 経路（本起動と Codex の preflight）のすべての分岐で、この変数を明示的に export する（Codex 経路では空）。

コンテナ（`entrypoint.sh`、`CC_AGENT=claude` の本起動のときだけ。`.mcp.json` ゲートの直後、秘密の export より前）:

1. 同じスクリプトで `/workspace` を審査し直す。止める判定・判定不能 → 中止。
2. 対象なし・記録と一致 → 進む。
3. 不一致か記録なし → 表示して `/dev/tty` で確認する。TTY が無ければ中止する。y でも記録しない（記録先は `:ro`）。ホストでの確認から本起動までの間に repo が変わった場合は、ここで止まるか確認が出る。

環境変数による opt-out は設けない（#29。`.c3c/env` に書くだけで迂回できるため）。

### `--check`

Claude 経路の診断に次を足す。`--check` は確認を出さず、記録も書かない。

- `[OK]` 対象なし（`.claude` も `.mcp.json` も無い）／承認済み。
- `[INFO]` 未承認・変更あり（初回起動時に確認が出る）。
- `[FAIL]` 止める判定・判定不能・label 不一致（`-b` の案内）・ホストに python3 が無い。
- Codex 経路では `[INFO]` で「使用しない」と出す。

`--check` で検査用コンテナを起動するか、ホストで静的に判定できる範囲（存在・label・記録の形式）に留めるかは、実装計画で決める。

### 旧イメージと版

- `.claude` か `.mcp.json` を持つ repo は、label の無い旧イメージでは起動しない（`-b` の案内）。持たない repo は旧イメージのまま起動できる。
- 網羅性（審査対象の集合）は、実装時に確認した Claude Code の版と公式ドキュメントの日付でだけ成り立つ。同梱の既定は `CLAUDE_CODE_VERSION=latest` なので、新しい版が新しい経路を足しても追えない。これを限界として明記し、再確認契機に「Claude Code の設定形式・trust・plugin の読み込み仕様の変更」を入れる。

## 文書

- README「セキュリティモデル」節: #29 の適用範囲を project の Claude 設定に広げる。`/workspace` の trust が全プロジェクトで共有されていること、本ゲートがそれを補うこと、残る経路（下記）を書く。「http／sse タイプは接続先をファイアウォールが審査する」の記述に、`headersHelper` は本ゲートが止めることを足す。「MCP サーバーの追加」節の近くに確認の出方・再確認の条件・止まる条件を書く。「変更後の確認」節に新アセットの検証を足す。
- SECURITY-CLAIMS: C-5 を新設する（成立条件・脅威モデル、保証する動作、限界・非対象、根拠・検証範囲、再確認契機）。
- `docs/development-invariants.md`: 新アセットを固定アセットの一覧に加え、検査用コンテナと本起動で同じスクリプトを使うこと、fail-closed、opt-out を作らないこと、承認記録の書き込み方を書く。`.mcp.json` ゲートの対象の記述（http は対象外）に `headersHelper` の扱いを足す。AGENTS.md の「変更前に読む」対象一覧にも新アセットを加える。

## 残る経路（範囲外。限界として明記する）

- 本起動の再照合の後に repo の設定が書き換えられた場合（Claude Code が設定を読むまでの間を含む）。project 設定は稼働中のセッションにも反映されうる。書き換える主体には、セッション自身・同じプロジェクトを開いた別コンテナ・ホストのエディタがある。検出は次回起動になる。判定・表示・hash を同じ読み取りから作ることは保証するが、ファイル群を原子的に固定することは保証しない。
- skills・agents・commands（入れ子を含む）の frontmatter と本文。呼び出しにモデルか利用者の判断が入るため #29 の外とし、プロンプトインジェクション一般と同じ扱いにする。
- コンテナ内で書き換えられた repo の hook が、ホストで Claude Code を起動したときにホストの権限で走る経路（ホスト側の trust の問題で、本ゲートの外）。
- `~/.claude.json` の `projects["/workspace"]` に、侵害されたセッションが local scope の MCP 等を書き足す経路（README の既存の記述と同じ）。
- 確認は定義の承認で、hook が呼ぶスクリプトや依存パッケージの中身は審査しない。

## 検証

- `claude-project-audit.py` の unittest: hash の符号化（単射・順序・非 UTF-8 のパス）、止める判定の各条件、判定不能の各条件（symlink の外向き・dangling・循環、非通常ファイル、読み取り失敗、上限超過、重複 key）、表示の制御文字除去と切り詰めの明示、判定・表示・hash が同じ読み取りから作られること。CI の `run_launcher_tests()` に登録する。
- `test-build.sh --launcher-only`: 対象なし（旧イメージでも起動する）、label 不一致で止まる、ホストに python3 が無いと止まる、承認済み、未承認（y・N・TTY なし）、変更の検出、検査用コンテナの出力の厳密な検証（不正な protocol で止まる）、各停止条件、`--check` の各状態、`compose` のマウントと env を参照しないこと、Codex 経路で空に export すること、`--clean`／`--clean-all` の削除、承認記録の atomic 書き込み。`lint.sh` の `compose_mount_is_ro` の対象に新しいマウントを加える。
- 実機（`-b` で再ビルド）: 持ち主の 3 repo で初回に確認が出て 2 回目は出ないこと、hook を書き換えると再確認になること、ホストで承認した後・本起動の前に書き換えるとコンテナ内のゲートで確認になること、TTY なしで止まること、旧イメージで止まり `-b` の案内が出ること。
- Issue の not run の解消: 使い捨ての repo で、修正前は `/workspace` の trust 共有により SessionStart hook が確認なしで走り、修正後はゲートで止まることを確かめる。ホストの実物の `~/.claude.json` は書き換えない。

## バージョン

MAJOR の見込み。README「バージョニング」節の MAJOR（デフォルト挙動の変更で、利用者が対応しないと従来どおり動かないもの）に当たる変更が 3 つある: project 設定で plugin を有効にする repo が起動しなくなる、`.claude` か `.mcp.json` を持つ repo は `-b` で作り直すまで起動しない、TTY なしで未承認の repo を起動すると止まる。番号・移行手順・`--check` が移行の要否を検出できることの実機確認は、実装計画とタグ提案で扱う。利用側への移行通知は ops リポジトリの運用に従う。

## レビュー記録

- 1 巡目（spec 6fd8916）: Codex（gpt-6-astra、`codex exec --sandbox read-only`）は「修正後に進める」（Important 3: 旧イメージへの委譲の fail-open、`env` 経由の plugin 読み込み、探索失敗の契約。Minor 3: TOCTOU の範囲、commands を外す理由、MAJOR 判定）。Claude（claude-opus-5-5、headless、Read/Grep/Glob/WebFetch）は「修正後に進める」（Critical 2: `.mcp.json` の `headersHelper` の抜け、旧イメージへの委譲の fail-open。Important 4: commands の扱い、symlink のホストとコンテナの差、frontmatter の切り出しのずれ、表示の範囲。Minor 9）。旧イメージへの委譲は両者が独立に出した（Claude は Critical、Codex は Important。重い方を採った）。持ち主の判断で、審査は検査用コンテナで行い、対象は #29 を厳密に適用して settings と plugin 類と `headersHelper` に絞った（skills・agents・commands を外したことで、frontmatter の切り出しと表示の指摘は対象ごと無くなった）。
