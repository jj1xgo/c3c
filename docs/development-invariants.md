# 開発者向け不変条件

claude-container 本体を変更する開発者（AI エージェントを含む）向けに、コード変更時に見落としやすい不変条件（ファイルごとの「壊してはいけない」制約とその理由）をまとめる。各ファイルの役割・利用者向けインターフェースの説明は README.md が正本であり、本ファイルはそれを重複させず、実装を変更する際に踏みやすい罠だけを記録する。README.md の該当節へのポインタは各項目に添える。

## 環境変数

プロジェクト設定ディレクトリの `env`（`.c3c/env`、旧名 `.claude-container.d/env`。`KEY=VALUE`）はランタイム設定。**意図的に `source` しない**（ホスト上でのシェル構文解釈による即時コード実行の防止。この設計を壊さない）。取り込むキーは許可リスト（一覧の正本は README.md「環境変数」節の表）に限る。

## アーキテクチャ

> **前提**: 本節以降の `/home/node/` 等のパスや `sudo` コマンドは、`./c3c` 経由で実際に起動した**コンテナ内部**の事実を説明したものである。このリポジトリのソースをコンテナを介さずホスト上で直接編集している場合、これらのパス・コマンドは実在しない（ビルド対象の仕様として読むこと）。

各ファイルの役割・実装詳細は README.md の「アーキテクチャ」節を参照。

### コアスクリプトの不変条件

- **`c3c`**（launcher。旧 `claude-container` は削除済み）
  - `compute_project_name()` による `PROJECT_NAME`（basename+sha256先頭8文字）でイメージ名・ビルドステージング先をプロジェクトごとに分離する構造を壊さない。固定パスに戻すと複数プロジェクト交互ビルドで無言の上書きが再発する（2026-07-02）。
  - `-b` 時の build と run は別ステップのまま（fail-closed）。
  - `stage_build_context()` の「`env` がステージング先に存在したら `exit 1`」防御的アサーションを削除しない（`env` はビルド時焼き込み禁止）。
  - GitHub meta 取得はここ1箇所のみで行う（詳細は「GitHub meta スナップショット」節を参照）。
  - 境界アセットの正本は `resolve_asset_source()`・`ASSET_HASH_TARGETS`・`stage_build_context()`（本ファイルには列挙しない）。同梱 default を持つファイルは `test-build.sh` の `stage_common_context()`・`run_config_ro_launcher_tests()` の runner コピーリストにも列挙されている（`node-version.txt`・`codex-version.txt` の追加時に 4 FAIL で判明）。「この3箇所を同時に更新する」だけでは閉じておらず、本体外（テスト・Dockerfile・README）にも依存先がある（`claude-container#34` で判明）。**依存先を本ファイルに列挙せず、新設時は既存アセット名の全参照を `grep -rn` して数え直す**（性質の異なる複数で較正する — 固定スクリプトは `entrypoint.sh` と `git-askpass.sh` の両方を使う。前者は README 個別項目を持ち後者は持たないため、片方だけでは較正が偏る。名前を含まない依存〈`find`/glob 走査等〉はこの手段では検出できない）。ただし staging は「ビルドコンテキストへ COPY して初めて読めるファイル」に限る — compose が `RUN_DIR` から直接読む `Dockerfile.claude` と、`FROM` が `COPY` より先に評価される `base-image.txt` はステージせず、`resolve_asset_source()`・`ASSET_HASH_TARGETS` への登録のみ行う。
  - MCP監査ゲートのTOFU承認記録パス（`MCP_APPROVAL_STORE`/`MCP_APPROVAL_RECORD`）は `load_env_file()` より前に `$HOME` から直接算出し freeze する構成を変えない — プロジェクト側 `env` 経由での `HOME` 等書き換えによるパス乗っ取りを防ぐため。`MCP_APPROVAL_FILE` は `check_mcp_approval()` の全分岐の末尾で無条件 export する構成を変えない（env 由来の値を信用しない設計。`claude-container#28`）。
  - **起動可否を判定するガード**は全て `guard_*` 関数（一覧の正本は `c3c` の dispatch 直前の呼び出し列）として通常起動と `--check` モードで共用する構成を壊さない。新ガードは必ず `guard_fail`/`guard_warn` 経由で関数化し両モードを通す（片側だけに足すと診断結果と実際の起動挙動がドリフトする）。起動台帳（`~/.local/state/claude-container/projects`）のパスも `load_env_file()` より前に freeze する（MCP承認記録と同じ流儀）。
  - **`--check` 専用のビルド入力診断**（`packages.txt`/`requirements.txt` の内容診断、`claude-container#34`）は上記と定義上分離する。判定は `validate-build-input.sh` が行い、強制は `Dockerfile.claude` の `RUN` が行う。`guard_warn` は表示・集計のためだけに使う（「新ガードの例外」ではなく別区分）。
  - `--check` の保証は「**対象リポジトリと `.build-context/` を変更しない**」（`/tmp` 配下の一時ファイルは対象外 — 内容診断は `mktemp` 経由で必ず作業ファイルを作るため、無限定の「書き込みなし」は偽になる。文言の正本は README「起動前チェック（`--check`）」節で、実装コメントもこれに揃える）。`podman`/`jq` 不在は fail ではなく graceful skip。
  - `env` による境界変数の直接上書き対策（`claude-container#39`）: 該当する変数は `readonly` 属性そのものが保護対象の登録簿であり、本ファイルには列挙しない（新しい境界変数は宣言箇所で `readonly` するだけで自動保護される）。`readonly` 化時は次を守る — (1) 「最後の書き込みの後」かつ全 dispatch 経路で `load_env_file()` より前に置く、(2) `readonly VAR="$(...)"` は代入と別文にする（コマンド置換の失敗を握り潰すため）、(3) 保護変数を子プロセスへ渡すときは前置代入でなく `export` を使う（前置代入は代入エラーになり `set -euo pipefail` 下で起動が止まる）。
  - 境界アセットのドリフト検知（`claude-container#30`）: `resolve_asset_source()`（fixed/overridable/optionalの解決規則分岐、副作用なし）を `stage_build_context()` と `compute_asset_hash()` の両方から使う構成を壊さない — 2箇所が別々に解決規則を持つとドリフトする。`compute_asset_hash()` はファイル内容のみをハッシュする（パスを含めない — 同一内容を別パスへ clone しただけの誤警告を防ぐ）。`ASSET_HASH` は dispatch セクションで `build` と `run` 両方の env プレフィックスへ渡す構成を崩さない — `run` 側を外すと `-b` 無しの初回起動（暗黙ビルド）でラベルが空になり、直後の通常起動で必ず誤警告が出る。`guard_asset_drift()` は fail-open（`guard_warn` に留め `guard_fail` にしない）— セルフホスト開発時に本リポジトリを編集した瞬間ドリフトするため fail-closed にすると開発フローが壊れる。ベースイメージは内容ハッシュに加えラベル `claude-container.base-image` との直接比較も行う（「変更→`-b`→元の値へ戻して `-b` 忘れ」は内容ハッシュが一致し検知できないため）。この比較は `$BASE_IMAGE` に依存するため `guard_base_image()` を `guard_asset_drift()` より先に呼ぶ順序を崩さない。
  - Codex 経路（c3c 第1段階、`--agent codex`）: `AGENT`/`READ_ONLY` は CLI 引数だけから決めて `readonly` にし、`CC_AGENT`・`CC_CODEX_READ_ONLY`・`CC_CODEX_START_MODE` を `load_env_file()` より前に export する（許可リストへ加えない）。Codex の承認記録パス（`CODEX_APPROVAL_DIR`/`CODEX_APPROVAL_RECORD` = `mcp-approvals/codex/<project>/<対応版>.json`）は `freeze_project_paths()` で freeze する。`CODEX_MCP_APPROVAL_FILE` は `MCP_APPROVAL_FILE` と同じく launcher の値だけを全経路で export する。Claude の `check_mcp_approval()` と Codex の `check_codex_approval()` は互いに代用しない。Claude のゲートは placeholder 作成前。Codex の順序は guard 群 → placeholder 作成 → 必要な明示ビルド → `guard_codex_image_support()`（label `io.c3c.codex-audit-protocol` の一致でだけ先へ進む）→ `run_codex_preflight()`（`compose.codex-preflight.yml` を最後に積み `run -T`、stdin は `/dev/null`、stdout は 0700/0600 の一時領域で `python3 -I` により protocol 1 文書として検証してから削除）→ `check_codex_approval()`（拒否・TTY 無し・EOF は起動しない）→ 本起動。`--check --agent codex` はコンテナを起動せず、動的照合は `not run` と表示する。
  - `c3c` 入口（c3c 第2a段階で導入、段階Cで唯一の入口）: `c3c` は通常ファイルで、呼出名 `${0##*/}` では分岐しない（旧 `claude-container` の実行ファイル・旧 parser〈未知オプションを位置引数として扱う〉・`C3C_INTERFACE`・`guard_legacy_entry()` は削除済み。旧名の外部 symlink から呼ばれても同じ parser・選択記憶を使い、basename で旧 parser を復活させない）。parser は `BUILD`/`CHECK`/`CLEAN`/`AGENT`/`READ_ONLY`/`POSITIONAL_ARGS` へ渡し、`AGENT`/`READ_ONLY`/`CC_AGENT`/`CC_CODEX_READ_ONLY` の `readonly` と export は `finalize_agent()` に集約して各 dispatch 経路でちょうど 1 回呼ぶ（通常起動は対象ディレクトリ解決→`freeze_agent_preference_key()`→`select_c3c_agent()` の後、`--check`/`--clean` はその直前。いずれも `load_env_file()` より前。引数解析直後には確定しない）。`--read-only` の検証は最終的な agent に対して `finalize_agent()` が行う（`--read-only` から agent を推定しない）。`RUN_DIR` は `resolve_launcher_path()` で実ファイルまで symlink を辿った親で、解決失敗は明示エラー（`readlink` 1 段を cwd 基準で cd する旧方式へ戻さない — 相対リンクを別 cwd から呼ぶと別ディレクトリを基点にする）。
  - 入口移行の案内は `--check` ドライバの `[INFO] 入口移行:` 1 行だけ（外部の alias・PATH は走査しない）。起動可否は判定しないため dispatch 直前のガード呼び出し列には含めず、対象ごとの WARN にも集計しない。
  - 設定ディレクトリの選択（`select_project_conf_dir()`、c3c 第2b-1段階）: `PROJECT_CONF_DIR` は `freeze_project_paths()` では決めず、`select_project_conf_dir()` が新名 `.c3c` と旧名 `.claude-container.d` を計画の配置表で解決して返してから `readonly` にする（両方の存在は `-e` に加えて `-L` でも判定し、内容や実体が同じでも `guard_fail`。片方だけなら `-d` へ解決できるものだけ採用し、file・dangling link は `guard_fail`。旧名だけは `guard_warn`。どちらも無ければ `.c3c` を参照元にして作らない）。呼ぶ位置は通常起動・`--check` とも `load_env_file()` より前、`--clean` の分岐より後（清掃に要るパスは `freeze_project_paths()` が持ち、清掃は設定の状態に依存しない — 設定解決を cleanup 分岐より前へ戻さない）。`--check` は `select_project_conf_dir || return 20` で失敗した対象の env・ガード・resolver・hash を呼ばず、ドライバは次の対象へ進む。採用パスは `resolve_asset_source()`・`stage_build_context()`・`compute_asset_hash()`・`ENV_FILE`・案内文のすべてで `$PROJECT_CONF_DIR` を使い、`.claude-container.d`/`.c3c` の綴りを個別の関数へ再び埋め込まない（新旧配置で同じ入力なら同じ hash・同じ staging になる契約）。fixed アセットの解決は `RUN_DIR` 固定のままで、どちらの名前からも上書きできない。入口名（`c3c`/`claude-container`）で探索結果を変えない。
  - CLI 選択の記憶（`agent-preference.py`、c3c 第2a段階）: 記憶は承認記録ではなく列挙値の利便設定で、`--check`・`--clean` は読まない・書かない・消さない（image/承認とは寿命が異なる）。キー `C3C_PREF_KEY` と保存先（`CC_STATE_DIR`＝`$HOME` 由来）は `load_env_file()` より前に確定して `readonly` にし、helper は `project-images.py` と同じく固定パスを `python3 -I` で呼び、`resolve_asset_source()`・`stage_build_context()` へ登録しない（ビルドコンテキスト・イメージへ COPY しない）。更新は `run_main_compose()` が終了コード 0 で戻った後だけ（`run_rc=0; run_main_compose || run_rc=$?; ... exit "$run_rc"` の構造を崩さない。`write_agent_preference()` は失敗を WARNING に留め、launcher の終了コードは常に本 run のもの）。helper 側は symlink・非通常ファイル・4096 byte 超・未知 enum・重複 key・bool の schema を拒否し、`read` は何も書かず、`write` は同じディレクトリの mkstemp→全 byte 書込（`write_all()`、短い書込を成功扱いしない。`SIGXFSZ` は無視して `EFBIG` を失敗にする）→fsync→`os.replace`（失敗時は自分の一時ファイルだけ除去し旧文書を残す）。Git 子プロセスには継承した `GIT_*` を渡さず system/global 設定を無効にする（別 repo の記憶へ誘導しない）。祖先の `.git` は最寄りの候補（空ディレクトリだけは Git と同じく無視して親へ進む）を `GIT_DIR` に明示して Git に検証させ、Git の通常探索（不完全な `.git` を無視して外側 repo へ辿る）を使わない — `HEAD`/`objects`/`refs` の有無を helper が個別に検査する方式へ戻さない（Git が repository と認めない条件は Git の版で変わり、列挙が閉じない。PR #134 のレビューで `HEAD` だけ見る実装が objects 欠落で外側 repo へ倒れることが判明）。候補を Git が解決できない・祖先を調べられない場合は path 単位へ落とさず rc4（診断不能）にし、launcher は明示 CLI なら WARNING で記憶を省略、無指定なら明示指定を案内して exit 2 にする（自動 fallback・失敗後の連続プロンプトを設けない）。
  - 固定 Compose override の選択（`compose.ipv6.yml`・`compose.plugins-alias.yml`・`compose.shared-home.yml`・`compose.shared-host.yml`・`compose.agents.yml`・`compose.codex-preflight.yml`）は `COMPOSE_OVERRIDE_ARGS` 配列 1 本（preflight 専用の `compose.codex-preflight.yml` だけは `run_codex_preflight()` が検査用 run に限って最後に追加する）に集約し、`guard_ipv6()`・`guard_plugins_alias()`・`guard_shared_home_alias()`・`guard_agents_dir()` が `+=` で積む。`ASSET_HASH` と同じ理由で dispatch の `build` と `run` の両方へ渡す構成を崩さない（片方だけだと `-b` の build と直後の run で構成が食い違う）。`check_one_project()` の冒頭でプロジェクトごとにリセットする。任意の podman 引数は受け付けない。
  - plugin 別名マウント（`claude-container#98`）: 適用条件の正本は副作用なしの `plugins_alias_target()`（`test-build.sh` が `sed` で関数定義だけを抽出して単独実行するため、開始行 `plugins_alias_target() {` と終了行 `}` の形を変えず、他の関数を呼ばない）。destination はホストの `$HOME` 配下の綴りに限り、`/workspace`・`/data`・`/shared`・`/home/node` と一致または配下なら付けない。`guard_plugins_alias()` は起動を止めない（`guard_warn` のみ）。基点の綴りは `prepare_claude_config_ro()` が `CLAUDE_CONFIG_HOST_BASE` に残す「`~` 展開済み・実体未解決」の値を使う（`pwd -P` 解決値を使うと symlink 経由の `HOME` でメタデータの綴りと食い違う）。
  - `SHARED_MOUNT` の別名マウントと `AGENTS_DIR`（`claude-container#99`）: `SHARED_MOUNT_HOME_ALIAS=1` の別名（`compose.shared-home.yml`・`compose.shared-host.yml`）は `:ro` だが境界ではない（同じ実体が `/shared` に rw で見える）。`guard_shared_home_alias()` は冒頭で `CLAUDE_SHARED_HOME_PATH`・`CLAUDE_SHARED_HOST_PATH` を `unset` してから算出値を `export` する構成を崩さない（環境からの注入で任意の destination にマウントさせない。`AGENTS_DIR` も検証後の実体を `export` で上書きする）。destination の綴りは symlink 未解決、source（`SHARED_MOUNT`・`AGENTS_DIR`）は `pwd -P` の実体。opt-in の不正値・HOME 外・予約領域との重なりは `guard_fail`、`AGENTS_DIR` と他の rw マウントの重なり検査は `guard_warn` に留める（`EXTRA_MOUNT=$HOME` 等で必ず重なり、利用者が意図している可能性が高いため）。
  - ベースイメージ設定（`base-image.txt`）: `BASE_IMAGE` は `guard_base_image()` 冒頭で env 由来の値を無視し既定値から開始する構成を崩さない（env 由来の値を信用しないという点で MCP承認記録・起動台帳のパス freeze と同じ流儀。ただし `BASE_IMAGE` は `readonly` でなく毎回既定値から再導出する別機構）。`ASSET_HASH` と同じ理由で `build`・`run` 両方の env プレフィックスへ渡す。
- **`project-images.py`**（ホスト専用）
  - 通常 `--check` はイメージも台帳も変更しない。`--check --clean-missing` でも台帳は保持する（削除済みパスを旧 `--clean` で指定する根拠を失わせない）。
  - `ENOENT` だけを欠落の根拠とし、壊れた symlink、種別違い、権限・検査エラーを削除へ落とさない。名前と由来の整合を検証し、不完全な由来ラベルを台帳による旧形式照合へフォールバックしない。
  - ローカル Podman を `--remote=false` で固定する。参照検査は停止中・外部コンテナも含む。削除直前の再検査、非強制の `rmi --no-prune`、削除後の消失確認を維持する。名前なし・別名付きは削除しない。Podman の失敗や JSON 破損を空の成功結果に変えない。
  - launcher からは固定パスを `python3 -I` で呼ぶ。戻り値は既存診断の結果と論理和で集約し、結果 JSON を shell として評価しない。ヘルパーはビルドコンテキストへ COPY しない。
- **`compose.yml`**
  - 既定の IPv6 無効モードでは、`sysctls` による無効化と `init-firewall.sh` の `ip6tables` DROP は両方必要（片方だけでは glibc の Happy Eyeballs 経由の間欠停止を防げない、2026-07-02）。既存の IPv6 opt-in は `compose.ipv6.yml` と IPv6 専用ファイアウォールで成立する別モードであり、README.md「IPv6 を任意で有効にする」節に従う。
  - `userns_mode: keep-id`・`NET_ADMIN`/`NET_RAW` capability は維持する。ただし単独では非root プロセスへ継承されるため、`Dockerfile.claude` の `ENTRYPOINT` の `setpriv` 剥奪とセットで維持する（`Dockerfile.claude` 項目参照）。
  - MCP承認記録マウント（`${MCP_APPROVAL_FILE:-/dev/null}:/etc/claude-container/mcp-approved-hash`）は `:ro` 必須（コンテナ内からの改竄で次回起動の自動承認を偽装できてしまうため。`claude-container#28`）。
  - `build.args` の `ASSET_HASH`・`BASE_IMAGE` はデフォルト参照のみを持つ（両経路へ渡す責務は `c3c` 側。上記項目参照）。ベースイメージ既定値は `Dockerfile.claude` の `ARG`・`compose.yml`・`guard_base_image()` の3箇所に重複するため同時に更新する。
  - 由来ラベル用の `CC_PROJECT_METADATA` / `CC_PROJECT_PATH` / `CC_PROJECT_NAME` は launcher が `load_env_file()` より前に確定・freeze・export し、build と run の両方へ渡す。Compose と Dockerfile の既定値は空とし、Dockerfile は全命令の最後の単一 LABEL で三つを記録する。
  - plugin 別名マウント（`claude-container#98`）は launcher が選ぶ override `compose.plugins-alias.yml` でのみ付け、`compose.yml` 本体に固定 destination で書かない（destination はホストごとに変わり、ホストの `plugins/` が既に `/home/node/.claude/plugins` の場合は既存の `:ro` 行と重複する。未設定時の既定 destination も重複か幽霊マウントのどちらかになる）。override の source は保護マウントの `plugins/` 行と同一、`:ro` を外さない。destination の `${CLAUDE_PLUGINS_HOST_PATH:?}` は保険で、保護の本体は launcher の無条件 export（compose provider によっては `:?` が空文字を通す）。
  - `${CODEX_DIR:-/dev/null}:/home/node/.codex` は rw 必須（codex が書き戻すため。`GITCONFIG_FILE` の `:ro` とは逆）。`CODEX_DIR` にホストの実 `~/.codex` を指させない前提を崩さない — コンテナ側から `config.toml` の notify フックを書けばホスト側で任意コード実行になる。
  - Codex 承認記録マウント（`${CODEX_MCP_APPROVAL_FILE:-/dev/null}:/etc/claude-container/codex-mcp-approved.json`）も `:ro` 必須（本起動の verify の偽装防止）。台帳ディレクトリ全体やホストの socket をコンテナへ公開しない。`CC_AGENT`/`CC_CODEX_START_MODE`/`CC_CODEX_READ_ONLY` は launcher が export した値だけを渡す environment で、プロジェクト設定 `env`（`.c3c/env`、旧 `.claude-container.d/env`）の許可リストへ加えない。既定値は未設定のときだけ効く `${VAR-default}` を使う（`${VAR:-default}` にすると明示した空文字が既定値に化け、`entrypoint.sh` の空文字拒否に届かない）。`lint.sh` の compose 検査（`compose_mount_is_ro`・`compose_tty_disabled`）は provider の出力形式（podman-compose の短縮表記 / docker compose の long syntax）に依らず意味で判定する。`compose.codex-preflight.yml` は `tty`/`stdin_open` の 2 項目だけを上書きし、mount・working_dir・environment を本起動と同じに保つ（検査と本起動の一致）。
  - `~/.claude/.git` の `:ro` 重ね（`claude-container#129`）は `CLAUDE_CONFIG_RO_DIRS` の 12 項目目として扱い、`.git` だけ条件付き（存在時のみ）の override にしない — 親マウントが rw のため、`.git` が無いホストでもコンテナが `.git` を植え付けられ、ホストで後から `git init` すると既存の `.git`（hooks・config）が再利用される。空の `.git` は git の通常のリポジトリ探索では認識されない（実測）。`.git` の存在だけで判定する他のツールへの影響は保証しない。
- **`Dockerfile.claude`**
  - `ca-certificates` の HTTP→HTTPS 2段階インストール順序を変えない（debian:stable 未同梱のため。削除しないこと）。
  - `tini` を PID1 に据える構成、および `packages.txt` でなく固定 apt-get レイヤーに置く配置を変えない（プロジェクト側上書きでの消失防止。関連インシデント: 2026-07-02、`podman stop` でコンテナを回収できなくなる障害。詳細は README.md「アーキテクチャ」節の `Dockerfile.claude` 説明を参照）。
  - `ENTRYPOINT` の `setpriv --ambient-caps=-all --inh-caps=-all` ラップを外さない — 外すと `compose.yml` の `cap_add` が非root プロセスの ambient set に残り、Claude が sudoers（`init-firewall.sh` 限定）を迂回して iptables を直接操作できる状態に戻る（`setpriv` は exec するため tini が PID1 である上記不変条件と両立する。機構と残存制約は README「セキュリティモデル」節）。
  - ベースイメージ可変化（`base-image.txt`）に伴うビルド時アサーション（固定 apt レイヤー直後の独立 `RUN`）を外さない — `ENTRYPOINT` が絶対パスで呼ぶ `/usr/bin/setpriv`・`/usr/bin/tini` の存在と `--ambient-caps` 受理を検証しており、外すとベースイメージ差し替え時にビルドは成功するが起動時に境界機構が無言で壊れる（アサーションの内訳と検知限界〈偽装ベースイメージは検知不能〉は README「利用側プロジェクトの設定」節）。
  - `packages.txt`/`requirements.txt` を取り込む2つの `RUN`（`grep -n validate-build-input Dockerfile.claude` で特定）で `validate-build-input.sh` による allowlist 検証を `apt-get`/`pip3` の実行より前に置く構成を外さない — 上記 setpriv/tini アサーションと同格の fail-closed 検証で、外すとビルド時 root コード実行経路（`packages.txt`/`requirements.txt` 経由のインジェクション）が復活する（`claude-container#34`）。安全性は同一 `RUN` 内の先行する `|| exit 1` にのみ依存する（コマンド置換の終了ステータスは捨てられるため）。
  - `ARG CACHEBUST` はキャッシュ破棄用に `RUN` 内で実際に参照して初めて効く（宣言のみでは無効）。`ARG ASSET_HASH` / `LABEL claude-container.asset-hash`（`claude-container#30`）も同型の罠を踏まないよう `CACHEBUST` 消費 `RUN` より後ろに置く配置を変えない（それより前に置くとキャッシュ無効化のタイミングがズレる）。`LABEL io.c3c.codex-audit-protocol`（c3c 第1段階の対応 protocol、launcher の `guard_codex_image_support()` が照合）も同じ位置に置く。
  - `codex-mcp-audit.py` は `entrypoint.sh` 等と同じ root 所有 755 の `/usr/local/bin/` に置く（`USER node` より前の `COPY`）。Codex CLI の実体は `npm install -g @openai/codex` が置く `/usr/local/bin/codex` で、`entrypoint.sh` の固定パスと一致させる（別の導入先へ変える場合は両方を同時に変える）。
  - GitHub meta の検証は「GitHub meta スナップショット」節を参照。
- **`entrypoint.sh`**
  - `init-firewall.sh`・`git-askpass.sh` と同じ root 所有 755 パターンで `/usr/local/bin/` へ配置し、ランタイムに node ユーザーが改変できないようにする構成を変えない — node 書込可能な場所（`/home/node` 配下等）へ戻すと、`/home/node` 自体が node:node 0700 のため非特権のまま直接改変できる状態に戻る（`claude-container#40`）。
  - ファイアウォール適用（fail-closed）→バックグラウンド更新ループ起動（詳細は「CDN IP ローテーション追従」節を参照）→`exec claude` の順序を変えない。更新ループ直後のマーカーコメント（`# --- 起動前半ここまで（tests/test_ipv6_entrypoint.py の抽出境界） ---`）は `tests/test_ipv6_entrypoint.py` が起動前半だけを抽出する境界で、文言を変えたらテスト側の `BOUNDARY` も同時に変える（消すとテストが後半〈シークレット・MCP ゲート・`exec claude`〉まで実行対象にする。`claude-container#98`）。
  - `~/.claude/plugins/*.json` のホストパスを `sed` で書き換える処理を復活させない — `plugins/` は `:ro` 保護対象で書けず、書けてはいけない。plugin の解決は launcher 側の別名マウント（`compose.plugins-alias.yml`、`claude-container#98`）が担う。
  - PID1 は tini（`Dockerfile.claude` 項目参照）。
  - `GITHUB_MAIN_PAT` 検知時の `credential.helper` 無効化（`GIT_CONFIG_*`）を外さない — `GITCONFIG_FILE` の `credential.helper=store` が askpass 経由の PAT を平文永続化する（`claude-container#25`）。
  - Claude 経路の起動引数は `claude --permission-mode auto` 固定（2026-09-21。従来の既定は `--dangerously-skip-permissions`）。引数を受理しない版では非ゼロ終了のままにし、auto が利用できないセッションで Claude Code 本体が Manual に戻す場合（公式 permission-modes 文書、2026-09-21 確認）も含め、旧フラグへ戻す分岐・env による切替を設けない（`tests/test_codex_entrypoint.py` が argv を検査）。auto / Manual の判定は Claude Code 本体の機能で、境界に数えない。
  - MCP監査ゲート（`/workspace/.mcp.json` の stdio 型サーバー検知＋TTY確認、fail-closed）を外さない、環境変数による opt-out を追加しない — 対象の帰結（セッション開始と同時の任意コード実行）に対しては迂回経路自体を作らない設計判断（根拠は README「セキュリティモデル」節、`claude-container#29`）。このゲートは Claude 経路（`CC_AGENT=claude`）だけで、Codex 経路の代用にしない。
  - Codex 経路（c3c 第1段階）: `CC_AGENT` は未設定のときだけ `claude`、空文字を含む不正値と `CC_CODEX_START_MODE`/`CC_CODEX_READ_ONLY` の enum 外は firewall 適用前に停止し、別 CLI へ fallback しない。preflight では初期化ログより前に元 stdout を fd3 へ確保し通常 stdout を stderr へ向ける（protocol は fd3 に 1 文書だけ）。順序は firewall → 更新ループ →（Claude のみ MCP ゲート）→ 固定 `CODEX_HOME=/home/node/.codex`・`CODEX_CLI=/usr/local/bin/codex` の確定（`readonly`、秘密 export より前 — export ループの「設定済み名はスキップ」により `secrets/export/` の `CODEX_HOME`・`HOME`・`PATH` で差し替えられない）→ 秘密 export → `cd /workspace` → `codex-mcp-audit.py` の `snapshot`（preflight、agent 非起動で終了）または `verify /etc/claude-container/codex-mcp-approved.json`（run）→ 固定 argv での `exec`。検査・再照合・本起動で home・cwd・CLI 実体・設定解決用 override（`projects={"/workspace"={trust_level="trusted"}}`、helper の `LIST_ARGS` と同値）を揃える構成を崩さない。
- **`init-firewall.sh`**
  - ipset は使わない（rootless podman で `ip_set` カーネルモジュールを autoload できないため素の iptables で代替）。
  - GitHub IP レンジはビルド時スナップショットの読み込みのみ、ランタイムでのライブ取得を追加しない（詳細は「GitHub meta スナップショット」節を参照）。
  - ドメイン IP の追従は「CDN IP ローテーション追従」節を参照。
  - `refresh_domains()` のNXDOMAIN判定（一時的な解決失敗とは区別し、恒久的にドメイン自体が存在しない場合のみ `had_errors` をセットしない）を壊さない — ハードコード済み許可ドメインが恒久的にNXDOMAIN化すると起動そのものがfail-closedで止まり続ける（`statsig.anthropic.com`、2026-07-06）。
  - エグレス許可のポート限定（`ALLOWED_PORTS`、既定 `443,22`。`claude-container#31`）は `add_cidr()`/`add_cidr_tagged()`（＝`CHAIN` 経由のGitHub CIDR・タグ付きドメインルール）にのみ適用する。DNSリゾルバ宛ルールとホストネットワーク宛ルール（`OUTPUT`/`INPUT` へ直接 append、`CHAIN` を経由しない）を対象に含めない — 誤って含めると起動そのものが壊れる（DNS）か、host_network限定の意図が失われる。`host_network` はゲートウェイ単一IP（`/32`）に縮小済み、`/24` へ戻さない。
- **`ipv6-firewall.py`** / **`firewall-refresh.py`**
  - 固定境界アセットとして root 所有 755 で `/usr/local/bin/` に配置する。`init-firewall.sh` の `REFRESH_INTERVAL_SECONDS` と `firewall-refresh.py` の更新後待機時間、`GRACE_WINDOW_SECONDS` と `ipv6-firewall.py` の `GRACE_SECONDS` をそれぞれ同期させる。
  - `firewall-refresh.py` は非特権の監視ヘルパーとしてシークレットの export より前に起動する。sudo の許可対象は `init-firewall.sh` のみとし、監視ヘルパー自体を特権起動しない。
  - `init-firewall.sh --refresh-domains` の終了コード 75 を部分失敗として区別する契約を維持する。更新・診断の詳細は [firewall-refresh.md](firewall-refresh.md) を参照する。
- **`git-askpass.sh`**
  - `init-firewall.sh` と同じ root 所有 755 パターンで `/usr/local/bin/` へ配置し、ランタイムに node ユーザーが改変できないようにする構成を変えない。
  - fail-closed 設計（github.com 宛の Username/Password プロンプト以外は応答せず exit 1）を壊さない。ホスト判定は `github.com.evil.com` 型の前方一致すり抜けを防ぐアンカー済み正規表現を維持する。
- **`validate-build-input.sh`**（`claude-container#34`）
  - `packages.txt`/`requirements.txt` の検証はこのスクリプト**単独が正本**。`Dockerfile.claude`・`--check`・`test-build.sh` は呼び出すだけで、各自が regex・正規化を再実装しない（複製すると3者の判定がドリフトする）。
  - 終了コード契約 0/1/2（0=適合／1=不適合・outfile 不変／2=診断不能・outfile 不変）と「`outfile` は成功時にのみ確定させる」を変えない。
  - `#!/bin/sh`・POSIX sh の範囲を維持する（ビルド時はコンテナ内の dash、`--check`・`test-build.sh` はホストの sh で走るため）。
  - `resolve_asset_source()` では `fixed` に置き、利用側の設定ディレクトリ（`.c3c/`・旧 `.claude-container.d/`）から差し替え可能にしない。
- **`packages.txt`** / **`requirements.txt`** / **`allowed-domains.txt`** — claude-container 同梱のデフォルト（フォールバック値）。`allowed-ports.txt`・`base-image.txt`（一覧は README「利用側プロジェクトの設定」節）は同梱デフォルトを持たず、未配置でも WARNING を出さない（上記3ファイルとの非対称は既知。経緯は `claude-container#7`）。
- **`node-version.txt`** / **`codex-version.txt`**（c3c 第2b-2段階）— 同梱 default は固定版（`24.18.0` / 起動時 MCP 審査の対応版）で、`latest` にしない（`test-build.sh` が書式と、launcher の `CODEX_SUPPORTED_VERSION`・`codex-mcp-audit.py` の `SUPPORTED_VERSION` との一致を検査する。対応版を上げるときは 3 箇所を同時に変える）。`resolve_asset_source()` では `packages.txt` と同じ overridable（project 優先→`$RUN_DIR` の default）に置き、project 側の**空ファイルを missing と同一視しない**（空の内容がそのままステージ・ハッシュされる明示 opt-out。計画 §8-5: 空を default で埋めると Codex を勝手に導入する）。`stage_build_context()` で「`missing` なら空ファイル生成」の分岐に戻さない。採用元（project / 同梱 default / 空 opt-out）の表示と Node 空＋Codex 有効の WARNING は `guard_build_input_defaults()` が両モードで行い、ここで別の解決規則を持たない（resolver の結果だけを見る）。この WARNING は `guard_warn` に留める — ベースイメージや `packages.txt` で npm が入るかはホスト側では判定できず、fail-closed の判定は Dockerfile.claude の npm 検査が担う。同梱 default の変更は `ASSET_HASH` に入るため、pin していない全利用側でドリフト診断が出る（意図した挙動。旧イメージは自動削除しない）。

### Node.js 任意バージョン導入（`node-version.txt`）

詳細は README.md「利用側プロジェクトの設定」節を参照。設計判断: 汎用スクリプト実行フックにせず宣言的ファイルにした（監査対象を無限定にしないため）。c3c 第2b-2段階から同梱 default を持つ（上記項目）。

### GitHub meta スナップショット

詳細は README.md「アーキテクチャ」内「GitHub meta スナップショット」節を参照。未認証GitHub APIレート制限回避のため取得は `stage_build_context()` 内1箇所のみ（2026-07-02）。

### CDN IP ローテーション追従

詳細は README.md「アーキテクチャ」節（`init-firewall.sh` の説明内）と [firewall-refresh.md](firewall-refresh.md) を参照。世代タグ（`gen=<epoch>`）による差分リフレッシュ構造を壊さない — 起動時1回解決に戻すと CDN の IP ローテーション後に新規接続が全滅する（2026-07-02）。

### プロジェクト固有設定（`.c3c/`、旧 `.claude-container.d/`）

ビルド時焼き込み設定（一覧の正本は README.md「利用側プロジェクトの設定」節）とランタイム設定（`env`）の区別、フォールバック時のWARNING設計、新旧の名前の選択規則と移行手順は同節を参照。秘密情報は設定ディレクトリ（`env` を含む）にも通さない — 唯一の正規の置き場所は `SECRETS_DIR` 配下のパス参照の独立ホスト側ファイル（README.md「GitHub トークンの配線」参照）。

## セキュリティ設計の帰結（開発者が壊してはいけない前提）

コンテナ内で Claude は `--permission-mode auto`（Claude Code の auto mode）で動作し、claude-container はツール使用ごとの人手の確認プロンプトを境界として当てにしない（auto が利用できないセッションでは Claude Code 本体が Manual に戻り確認プロンプトが出るが、境界の扱いは変わらない）。ガードレールはコンテナ境界であり、Claude は `/workspace` と、rw で opt-in された追加マウント（一覧の正本は README.md「環境変数」節）への読み書き権限を全面的に持つ（詳細は README.md「セキュリティモデル」節）。意図したプロジェクトスコープ外の機密データを含むディレクトリはマウントしない。複数プロジェクトから同じホストパスを共有する追加マウント（`SHARED_MOUNT` の `/shared`）は、他プロジェクトのセッションも書き込める領域として扱う。書き込みは他プロジェクトへ波及し、読み取る内容は自セッション由来でない入力になりうる（信頼境界の詳細は README.md「セキュリティモデル」節）。

ネットワーク面は `init-firewall.sh` による deny-by-default のエグレス許可リストで制限される（既定で有効）。認証情報（`~/.claude.json`）やソースが実行時にマウントされるため、悪意ある pip パッケージやプロンプトインジェクションによる外部送信・C2 化を「許可済みエンドポイント以外への通信不可」で封じる。

以下は本リポジトリのコード（本体スクリプト・hook）が守るべき、製品設計上の帰結である。本ファイルは製品としての既定・機構を扱い、トークンの具体的な配線方法は README.md「GitHub トークンの配線」節を参照する。

- トークン体制（メイン PAT／MCP・issues 用 PAT の2本、exposure 軸設計）は README.md「GitHub トークンの配線」節が正本。
- **コンテナ内で `gh auth login` を実行しない**（ambient 認証を復活させ、非export・明示読みという設計原則を無効化するため。README.md「GitHub トークンの配線」節参照）。
- **`git push` は既定で不可のまま**（`SECRETS_DIR/GITHUB_MAIN_PAT` に `Contents: write` を明示配線した対象リポジトリでのみ opt-in 可能。README.md「git push を使う場合」参照）。

## 変更後の確認

`Dockerfile.claude` の `ENTRYPOINT` を触った場合、または `packages.txt`/`requirements.txt` の検証呼び出し配線（`validate-build-input.sh` の呼び出し、`claude-container#34`）を触った場合は lint では担保できず、`-b` リビルド＋実機起動での確認が要る（後者は `test-build.sh` の層1〈`--validator-only`、コンテナ内可〉・層2静的検査が担保する範囲があり、実ビルドを伴う確認のみホスト側が必要）。テストコマンドの全体像・CI の実行内容は README.md「変更後の確認」節を参照する。
