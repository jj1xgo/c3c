# 開発者向け不変条件

claude-container 本体を変更する開発者（AI エージェントを含む）向けに、コード変更時に見落としやすい不変条件（ファイルごとの「壊してはいけない」制約とその理由）をまとめる。各ファイルの役割・利用者向けインターフェースの説明は README.md が正本であり、本ファイルはそれを重複させず、実装を変更する際に踏みやすい罠だけを記録する。README.md の該当節へのポインタは各項目に添える。

## 環境変数

`.claude-container.d/env`（`KEY=VALUE`）はランタイム設定。**意図的に `source` しない**（ホスト上でのシェル構文解釈による即時コード実行の防止。この設計を壊さない）。取り込むキーは許可リスト（一覧の正本は README.md「環境変数」節の表）に限る。

## アーキテクチャ

> **前提**: 本節以降の `/home/node/` 等のパスや `sudo` コマンドは、`./claude-container` 経由で実際に起動した**コンテナ内部**の事実を説明したものである。このリポジトリのソースをコンテナを介さずホスト上で直接編集している場合、これらのパス・コマンドは実在しない（ビルド対象の仕様として読むこと）。

各ファイルの役割・実装詳細は README.md の「アーキテクチャ」節を参照。

### コアスクリプトの不変条件

- **`claude-container`**
  - `compute_project_name()` による `PROJECT_NAME`（basename+sha256先頭8文字）でイメージ名・ビルドステージング先をプロジェクトごとに分離する構造を壊さない。固定パスに戻すと複数プロジェクト交互ビルドで無言の上書きが再発する（2026-07-02）。
  - `-b` 時の build と run は別ステップのまま（fail-closed）。
  - `stage_build_context()` の「`env` がステージング先に存在したら `exit 1`」防御的アサーションを削除しない（`env` はビルド時焼き込み禁止）。
  - GitHub meta 取得はここ1箇所のみで行う（詳細は「GitHub meta スナップショット」節を参照）。
  - 境界アセットの正本は `resolve_asset_source()`・`ASSET_HASH_TARGETS`・`stage_build_context()`（本ファイルには列挙しない）。「この3箇所を同時に更新する」だけでは閉じておらず、本体外（テスト・Dockerfile・README）にも依存先がある（`claude-container#34` で判明）。**依存先を本ファイルに列挙せず、新設時は既存アセット名の全参照を `grep -rn` して数え直す**（性質の異なる複数で較正する — 固定スクリプトは `entrypoint.sh` と `git-askpass.sh` の両方を使う。前者は README 個別項目を持ち後者は持たないため、片方だけでは較正が偏る。名前を含まない依存〈`find`/glob 走査等〉はこの手段では検出できない）。ただし staging は「ビルドコンテキストへ COPY して初めて読めるファイル」に限る — compose が `RUN_DIR` から直接読む `Dockerfile.claude` と、`FROM` が `COPY` より先に評価される `base-image.txt` はステージせず、`resolve_asset_source()`・`ASSET_HASH_TARGETS` への登録のみ行う。
  - MCP監査ゲートのTOFU承認記録パス（`MCP_APPROVAL_STORE`/`MCP_APPROVAL_RECORD`）は `load_env_file()` より前に `$HOME` から直接算出し freeze する構成を変えない — プロジェクト側 `env` 経由での `HOME` 等書き換えによるパス乗っ取りを防ぐため。`MCP_APPROVAL_FILE` は `check_mcp_approval()` の全分岐の末尾で無条件 export する構成を変えない（env 由来の値を信用しない設計。`claude-container#28`）。
  - **起動可否を判定するガード**は全て `guard_*` 関数（一覧の正本は `claude-container` の dispatch 直前の呼び出し列）として通常起動と `--check` モードで共用する構成を壊さない。新ガードは必ず `guard_fail`/`guard_warn` 経由で関数化し両モードを通す（片側だけに足すと診断結果と実際の起動挙動がドリフトする）。起動台帳（`~/.local/state/claude-container/projects`）のパスも `load_env_file()` より前に freeze する（MCP承認記録と同じ流儀）。
  - **`--check` 専用のビルド入力診断**（`packages.txt`/`requirements.txt` の内容診断、`claude-container#34`）は上記と定義上分離する。判定は `validate-build-input.sh` が行い、強制は `Dockerfile.claude` の `RUN` が行う。`guard_warn` は表示・集計のためだけに使う（「新ガードの例外」ではなく別区分）。
  - `--check` の保証は「**対象リポジトリと `.build-context/` を変更しない**」（`/tmp` 配下の一時ファイルは対象外 — 内容診断は `mktemp` 経由で必ず作業ファイルを作るため、無限定の「書き込みなし」は偽になる。文言の正本は README「利用側プロジェクトの設定」の `--check` 節で、実装コメントもこれに揃える）。`podman`/`jq` 不在は fail ではなく graceful skip。
  - `env` による境界変数の直接上書き対策（`claude-container#39`）: 該当する変数は `readonly` 属性そのものが保護対象の登録簿であり、本ファイルには列挙しない（新しい境界変数は宣言箇所で `readonly` するだけで自動保護される）。`readonly` 化時は次を守る — (1) 「最後の書き込みの後」かつ全 dispatch 経路で `load_env_file()` より前に置く、(2) `readonly VAR="$(...)"` は代入と別文にする（コマンド置換の失敗を握り潰すため）、(3) 保護変数を子プロセスへ渡すときは前置代入でなく `export` を使う（前置代入は代入エラーになり `set -euo pipefail` 下で起動が止まる）。
  - 境界アセットのドリフト検知（`claude-container#30`）: `resolve_asset_source()`（fixed/overridable/optionalの解決規則分岐、副作用なし）を `stage_build_context()` と `compute_asset_hash()` の両方から使う構成を壊さない — 2箇所が別々に解決規則を持つとドリフトする。`compute_asset_hash()` はファイル内容のみをハッシュする（パスを含めない — 同一内容を別パスへ clone しただけの誤警告を防ぐ）。`ASSET_HASH` は dispatch セクションで `build` と `run` 両方の env プレフィックスへ渡す構成を崩さない — `run` 側を外すと `-b` 無しの初回起動（暗黙ビルド）でラベルが空になり、直後の通常起動で必ず誤警告が出る。`guard_asset_drift()` は fail-open（`guard_warn` に留め `guard_fail` にしない）— セルフホスト開発時に本リポジトリを編集した瞬間ドリフトするため fail-closed にすると開発フローが壊れる。ベースイメージは内容ハッシュに加えラベル `claude-container.base-image` との直接比較も行う（「変更→`-b`→元の値へ戻して `-b` 忘れ」は内容ハッシュが一致し検知できないため）。この比較は `$BASE_IMAGE` に依存するため `guard_base_image()` を `guard_asset_drift()` より先に呼ぶ順序を崩さない。
  - 固定 Compose override の選択（`compose.ipv6.yml`・`compose.plugins-alias.yml`・`compose.shared-home.yml`・`compose.shared-host.yml`・`compose.agents.yml`）は `COMPOSE_OVERRIDE_ARGS` 配列 1 本に集約し、`guard_ipv6()`・`guard_plugins_alias()`・`guard_shared_home_alias()`・`guard_agents_dir()` が `+=` で積む。`ASSET_HASH` と同じ理由で dispatch の `build` と `run` の両方へ渡す構成を崩さない（片方だけだと `-b` の build と直後の run で構成が食い違う）。`check_one_project()` の冒頭でプロジェクトごとにリセットする。任意の podman 引数は受け付けない。
  - plugin 別名マウント（`claude-container#98`）: 適用条件の正本は副作用なしの `plugins_alias_target()`（`test-build.sh` が `sed` で関数定義だけを抽出して単独実行するため、開始行 `plugins_alias_target() {` と終了行 `}` の形を変えず、他の関数を呼ばない）。destination はホストの `$HOME` 配下の綴りに限り、`/workspace`・`/data`・`/shared`・`/home/node` と一致または配下なら付けない。`guard_plugins_alias()` は起動を止めない（`guard_warn` のみ）。基点の綴りは `prepare_claude_config_ro()` が `CLAUDE_CONFIG_HOST_BASE` に残す「`~` 展開済み・実体未解決」の値を使う（`pwd -P` 解決値を使うと symlink 経由の `HOME` でメタデータの綴りと食い違う）。
  - `SHARED_MOUNT` の別名マウントと `AGENTS_DIR`（`claude-container#99`）: `SHARED_MOUNT_HOME_ALIAS=1` の別名（`compose.shared-home.yml`・`compose.shared-host.yml`）は `:ro` だが境界ではない（同じ実体が `/shared` に rw で見える）。`guard_shared_home_alias()` は冒頭で `CLAUDE_SHARED_HOME_PATH`・`CLAUDE_SHARED_HOST_PATH` を `unset` してから算出値を `export` する構成を崩さない（環境からの注入で任意の destination にマウントさせない。`AGENTS_DIR` も検証後の実体を `export` で上書きする）。destination の綴りは symlink 未解決、source（`SHARED_MOUNT`・`AGENTS_DIR`）は `pwd -P` の実体。opt-in の不正値・HOME 外・予約領域との重なりは `guard_fail`、`AGENTS_DIR` と他の rw マウントの重なり検査は `guard_warn` に留める（`EXTRA_MOUNT=$HOME` 等で必ず重なり、利用者が意図している可能性が高いため）。
  - ベースイメージ設定（`base-image.txt`）: `BASE_IMAGE` は `guard_base_image()` 冒頭で env 由来の値を無視し既定値から開始する構成を崩さない（env 由来の値を信用しないという点で MCP承認記録・起動台帳のパス freeze と同じ流儀。ただし `BASE_IMAGE` は `readonly` でなく毎回既定値から再導出する別機構）。`ASSET_HASH` と同じ理由で `build`・`run` 両方の env プレフィックスへ渡す。
- **`compose.yml`**
  - 既定の IPv6 無効モードでは、`sysctls` による無効化と `init-firewall.sh` の `ip6tables` DROP は両方必要（片方だけでは glibc の Happy Eyeballs 経由の間欠停止を防げない、2026-07-02）。既存の IPv6 opt-in は `compose.ipv6.yml` と IPv6 専用ファイアウォールで成立する別モードであり、README.md「IPv6 を任意で有効にする」節に従う。
  - `userns_mode: keep-id`・`NET_ADMIN`/`NET_RAW` capability は維持する。ただし単独では非root プロセスへ継承されるため、`Dockerfile.claude` の `ENTRYPOINT` の `setpriv` 剥奪とセットで維持する（`Dockerfile.claude` 項目参照）。
  - MCP承認記録マウント（`${MCP_APPROVAL_FILE:-/dev/null}:/etc/claude-container/mcp-approved-hash`）は `:ro` 必須（コンテナ内からの改竄で次回起動の自動承認を偽装できてしまうため。`claude-container#28`）。
  - `build.args` の `ASSET_HASH`・`BASE_IMAGE` はデフォルト参照のみを持つ（両経路へ渡す責務は `claude-container` 側。上記項目参照）。ベースイメージ既定値は `Dockerfile.claude` の `ARG`・`compose.yml`・`guard_base_image()` の3箇所に重複するため同時に更新する。
  - plugin 別名マウント（`claude-container#98`）は launcher が選ぶ override `compose.plugins-alias.yml` でのみ付け、`compose.yml` 本体に固定 destination で書かない（destination はホストごとに変わり、ホストの `plugins/` が既に `/home/node/.claude/plugins` の場合は既存の `:ro` 行と重複する。未設定時の既定 destination も重複か幽霊マウントのどちらかになる）。override の source は保護マウントの `plugins/` 行と同一、`:ro` を外さない。destination の `${CLAUDE_PLUGINS_HOST_PATH:?}` は保険で、保護の本体は launcher の無条件 export（compose provider によっては `:?` が空文字を通す）。
  - `${CODEX_DIR:-/dev/null}:/home/node/.codex` は rw 必須（codex が書き戻すため。`GITCONFIG_FILE` の `:ro` とは逆）。`CODEX_DIR` にホストの実 `~/.codex` を指させない前提を崩さない — コンテナ側から `config.toml` の notify フックを書けばホスト側で任意コード実行になる。
- **`Dockerfile.claude`**
  - `ca-certificates` の HTTP→HTTPS 2段階インストール順序を変えない（debian:stable 未同梱のため。削除しないこと）。
  - `tini` を PID1 に据える構成、および `packages.txt` でなく固定 apt-get レイヤーに置く配置を変えない（プロジェクト側上書きでの消失防止。関連インシデント: 2026-07-02、`podman stop` でコンテナを回収できなくなる障害。詳細は README.md「アーキテクチャ」節の `Dockerfile.claude` 説明を参照）。
  - `ENTRYPOINT` の `setpriv --ambient-caps=-all --inh-caps=-all` ラップを外さない — 外すと `compose.yml` の `cap_add` が非root プロセスの ambient set に残り、Claude が sudoers（`init-firewall.sh` 限定）を迂回して iptables を直接操作できる状態に戻る（`setpriv` は exec するため tini が PID1 である上記不変条件と両立する。機構と残存制約は README「セキュリティモデル」節）。
  - ベースイメージ可変化（`base-image.txt`）に伴うビルド時アサーション（固定 apt レイヤー直後の独立 `RUN`）を外さない — `ENTRYPOINT` が絶対パスで呼ぶ `/usr/bin/setpriv`・`/usr/bin/tini` の存在と `--ambient-caps` 受理を検証しており、外すとベースイメージ差し替え時にビルドは成功するが起動時に境界機構が無言で壊れる（アサーションの内訳と検知限界〈偽装ベースイメージは検知不能〉は README「利用側プロジェクトの設定」節）。
  - `packages.txt`/`requirements.txt` を取り込む2つの `RUN`（`grep -n validate-build-input Dockerfile.claude` で特定）で `validate-build-input.sh` による allowlist 検証を `apt-get`/`pip3` の実行より前に置く構成を外さない — 上記 setpriv/tini アサーションと同格の fail-closed 検証で、外すとビルド時 root コード実行経路（`packages.txt`/`requirements.txt` 経由のインジェクション）が復活する（`claude-container#34`）。安全性は同一 `RUN` 内の先行する `|| exit 1` にのみ依存する（コマンド置換の終了ステータスは捨てられるため）。
  - `ARG CACHEBUST` はキャッシュ破棄用に `RUN` 内で実際に参照して初めて効く（宣言のみでは無効）。`ARG ASSET_HASH` / `LABEL claude-container.asset-hash`（`claude-container#30`）も同型の罠を踏まないよう `CACHEBUST` 消費 `RUN` より後ろに置く配置を変えない（それより前に置くとキャッシュ無効化のタイミングがズレる）。
  - GitHub meta の検証は「GitHub meta スナップショット」節を参照。
- **`entrypoint.sh`**
  - `init-firewall.sh`・`git-askpass.sh` と同じ root 所有 755 パターンで `/usr/local/bin/` へ配置し、ランタイムに node ユーザーが改変できないようにする構成を変えない — node 書込可能な場所（`/home/node` 配下等）へ戻すと、`/home/node` 自体が node:node 0700 のため非特権のまま直接改変できる状態に戻る（`claude-container#40`）。
  - ファイアウォール適用（fail-closed）→バックグラウンド更新ループ起動（詳細は「CDN IP ローテーション追従」節を参照）→`exec claude` の順序を変えない。更新ループ直後のマーカーコメント（`# --- 起動前半ここまで（tests/test_ipv6_entrypoint.py の抽出境界） ---`）は `tests/test_ipv6_entrypoint.py` が起動前半だけを抽出する境界で、文言を変えたらテスト側の `BOUNDARY` も同時に変える（消すとテストが後半〈シークレット・MCP ゲート・`exec claude`〉まで実行対象にする。`claude-container#98`）。
  - `~/.claude/plugins/*.json` のホストパスを `sed` で書き換える処理を復活させない — `plugins/` は `:ro` 保護対象で書けず、書けてはいけない。plugin の解決は launcher 側の別名マウント（`compose.plugins-alias.yml`、`claude-container#98`）が担う。
  - PID1 は tini（`Dockerfile.claude` 項目参照）。
  - `GITHUB_MAIN_PAT` 検知時の `credential.helper` 無効化（`GIT_CONFIG_*`）を外さない — `GITCONFIG_FILE` の `credential.helper=store` が askpass 経由の PAT を平文永続化する（`claude-container#25`）。
  - MCP監査ゲート（`/workspace/.mcp.json` の stdio 型サーバー検知＋TTY確認、fail-closed）を外さない、環境変数による opt-out を追加しない — 対象の帰結（セッション開始と同時の任意コード実行）に対しては迂回経路自体を作らない設計判断（根拠は README「セキュリティモデル」節、`claude-container#29`）。
- **`init-firewall.sh`**
  - ipset は使わない（rootless podman で `ip_set` カーネルモジュールを autoload できないため素の iptables で代替）。
  - GitHub IP レンジはビルド時スナップショットの読み込みのみ、ランタイムでのライブ取得を追加しない（詳細は「GitHub meta スナップショット」節を参照）。
  - ドメイン IP の追従は「CDN IP ローテーション追従」節を参照。
  - `refresh_domains()` のNXDOMAIN判定（一時的な解決失敗とは区別し、恒久的にドメイン自体が存在しない場合のみ `had_errors` をセットしない）を壊さない — ハードコード済み許可ドメインが恒久的にNXDOMAIN化すると起動そのものがfail-closedで止まり続ける（`statsig.anthropic.com`、2026-07-06）。
  - エグレス許可のポート限定（`ALLOWED_PORTS`、既定 `443,22`。`claude-container#31`）は `add_cidr()`/`add_cidr_tagged()`（＝`CHAIN` 経由のGitHub CIDR・タグ付きドメインルール）にのみ適用する。DNSリゾルバ宛ルールとホストネットワーク宛ルール（`OUTPUT`/`INPUT` へ直接 append、`CHAIN` を経由しない）を対象に含めない — 誤って含めると起動そのものが壊れる（DNS）か、host_network限定の意図が失われる。`host_network` はゲートウェイ単一IP（`/32`）に縮小済み、`/24` へ戻さない。
- **`git-askpass.sh`**
  - `init-firewall.sh` と同じ root 所有 755 パターンで `/usr/local/bin/` へ配置し、ランタイムに node ユーザーが改変できないようにする構成を変えない。
  - fail-closed 設計（github.com 宛の Username/Password プロンプト以外は応答せず exit 1）を壊さない。ホスト判定は `github.com.evil.com` 型の前方一致すり抜けを防ぐアンカー済み正規表現を維持する。
- **`validate-build-input.sh`**（`claude-container#34`）
  - `packages.txt`/`requirements.txt` の検証はこのスクリプト**単独が正本**。`Dockerfile.claude`・`--check`・`test-build.sh` は呼び出すだけで、各自が regex・正規化を再実装しない（複製すると3者の判定がドリフトする）。
  - 終了コード契約 0/1/2（0=適合／1=不適合・outfile 不変／2=診断不能・outfile 不変）と「`outfile` は成功時にのみ確定させる」を変えない。
  - `#!/bin/sh`・POSIX sh の範囲を維持する（ビルド時はコンテナ内の dash、`--check`・`test-build.sh` はホストの sh で走るため）。
  - `resolve_asset_source()` では `fixed` に置き、利用側 `.claude-container.d/` から差し替え可能にしない。
- **`packages.txt`** / **`requirements.txt`** / **`allowed-domains.txt`** — claude-container 同梱のデフォルト（フォールバック値）。後発のオプトイン設定ファイル（一覧は README「利用側プロジェクトの設定」節）は同梱デフォルトを持たず、未配置でも WARNING を出さない（上記3ファイルとの非対称は既知。経緯は `claude-container#7`）。

### Node.js 任意バージョン導入（`node-version.txt`）

詳細は README.md「利用側プロジェクトの設定」節を参照。設計判断: 汎用スクリプト実行フックにせず宣言的ファイルにした（監査対象を無限定にしないため）。

### GitHub meta スナップショット

詳細は README.md「アーキテクチャ」内「GitHub meta スナップショット」節を参照。未認証GitHub APIレート制限回避のため取得は `stage_build_context()` 内1箇所のみ（2026-07-02）。

### CDN IP ローテーション追従

詳細は README.md「アーキテクチャ」節（`init-firewall.sh` の説明内）を参照。世代タグ（`gen=<epoch>`）による差分リフレッシュ構造を壊さない — 起動時1回解決に戻すと CDN の IP ローテーション後に新規接続が全滅する（2026-07-02）。

### プロジェクト固有設定（`.claude-container.d/`）

ビルド時焼き込み設定（一覧の正本は README.md「利用側プロジェクトの設定」節）とランタイム設定（`env`）の区別、フォールバック時のWARNING設計は同節を参照。秘密情報は `.claude-container.d/`（`env` を含む）にも通さない — 唯一の正規の置き場所は `SECRETS_DIR` 配下のパス参照の独立ホスト側ファイル（README.md「GitHub トークンの配線」参照）。

## セキュリティ設計の帰結（開発者が壊してはいけない前提）

コンテナ内で Claude は `--dangerously-skip-permissions` で動作するため、ツール使用の確認プロンプトなしに動作する。ガードレールはコンテナ境界であり、Claude は `/workspace` と、rw で opt-in された追加マウントへの読み書き権限を全面的に持つ（詳細は README.md「セキュリティモデル」節）。意図したプロジェクトスコープ外の機密データを含むディレクトリはマウントしない。複数プロジェクトから同じホストパスを共有する追加マウント（`SHARED_MOUNT` の `/shared`）は、他プロジェクトのセッションも書き込める領域として扱う。書き込みは他プロジェクトへ波及し、読み取る内容は自セッション由来でない入力になりうる（信頼境界の詳細は README.md「セキュリティモデル」節）。

ネットワーク面は `init-firewall.sh` による deny-by-default のエグレス許可リストで制限される（既定で有効）。認証情報（`~/.claude.json`）やソースが実行時にマウントされるため、悪意ある pip パッケージやプロンプトインジェクションによる外部送信・C2 化を「許可済みエンドポイント以外への通信不可」で封じる。

以下は本リポジトリのコード（本体スクリプト・hook）が守るべき、製品設計上の帰結である。本ファイルは製品としての既定・機構を扱い、トークンの具体的な配線方法は README.md「GitHub トークンの配線」節を参照する。

- トークン体制（メイン PAT／MCP・issues 用 PAT の2本、exposure 軸設計）は README.md「GitHub トークンの配線」節が正本。
- **コンテナ内で `gh auth login` を実行しない**（ambient 認証を復活させ、非export・明示読みという設計原則を無効化するため。README.md「GitHub トークンの配線」節参照）。
- **`git push` は既定で不可のまま**（`SECRETS_DIR/GITHUB_MAIN_PAT` に `Contents: write` を明示配線した対象リポジトリでのみ opt-in 可能。README.md「git push を使う場合」参照）。

## 変更後の確認

`Dockerfile.claude` の `ENTRYPOINT` を触った場合、または `packages.txt`/`requirements.txt` の検証呼び出し配線（`validate-build-input.sh` の呼び出し、`claude-container#34`）を触った場合は lint では担保できず、`-b` リビルド＋実機起動での確認が要る（`test-build.sh` の層1〈`--validator-only`、コンテナ内可〉・層2静的検査が担保する範囲があり、実ビルドを伴う確認のみホスト側が必要）。テストコマンドの全体像・CI の実行内容は README.md「変更後の確認」節を参照する。
