# c3c 第2b-2段階の実装・検証記録

2026-09-21 作成。[第2段階計画](2026-09-21-c3c-phase2.md) の Task 4（2b-2: Node/Codex の既定ビルド入力）の実装、fake Podman による回帰検証、実ビルド・実 Podman・実認証での受入を記録する。独立レビューは完了（Critical 0 / Important 0 / Minor 1）。検証件数の文書誤記 1 件は修正済み。[PR #136](https://github.com/jj1xgo/c3c/pull/136) の二重レビュー・必須 CI 4 件を通過し、マージ済み。`v10.0.0` として公開済み。

対象は `9c6b21df1867314a592119c01984150b97354ea1`（PR #135 マージ）を基点とする `c3c/phase2b2-defaults` worktree の差分。実装・検証はコミット前の差分に対して行った。実装 commit は `5a3191827f8af3aa24aefaaed56d026924d487e3`、マージ commit は `2c361f863a1116928b0539f3d7759c4955232f21`。実装者は Opus 5（ユーザー指定。advisor・Fable・subagent は使っていない）。

実機検証・独立レビュー前の実装ファイルの sha256（先頭 16 桁。文書は含めない）:

| ファイル | sha256 |
|---|---|
| `claude-container`（`c3c` は symlink） | 3f1964040ad0ff98 |
| `node-version.txt`（新規、`24.18.0\n`） | 55075b5ec4e8b319 |
| `codex-version.txt`（新規、`0.155.1\n`） | 3bec841237f6716b |
| `Dockerfile.claude` | 611be0ad10b56ee3 |
| `entrypoint.sh` | 7f7d0bcd9ca79d35 |
| `test-build.sh` | cc1874135617eae3 |
| `tests/test_c3c_config.py` | bd97193b23c572ab |
| `tests/test_codex_launch.py` | 72607c7653b8556b |
| `packages.txt` / `requirements.txt` / `allowed-domains.txt` | 4908a0728c3d72a5 / 363fc69f53ca4405 / 90fdcb911a653d8f |
| `compose.yml` / `SECURITY-CLAIMS.md` | e56eda40a60c65e4 / 288f32e1805cc767 |

## 実装

- 同梱 default: ルートに `node-version.txt`（`24.18.0`）と `codex-version.txt`（`0.155.1`、起動時 MCP 審査の対応版）を追加。`latest` にはしない。
- `claude-container`: `resolve_asset_source()` で 2 ファイルを `packages.txt` 等と同じ overridable（project 優先→`$RUN_DIR` の同梱 default、`ASSET_ORIGIN=default`）に移した。`allowed-ports.txt`・`base-image.txt` の missing 契約は不変。project 側の空ファイルは `project` 由来の空内容としてそのままステージ・ハッシュされる（明示 opt-out。missing と同一視して default で埋めない）。`stage_build_context()`・`compute_asset_hash()`・`guard_codex_agent()` は同じ resolver の結果を使う（構造は不変、コメントを更新）。
- `guard_build_input_defaults()` を新設し、通常起動（`INFO:`）と `--check`（`[INFO]`）で `Node.js 版: 24.18.0（採用元: 同梱 default）` / `（採用元: project <path>）` / `なし（<path> が空 = opt-out、… を導入しません）` を表示する。Node が空で Codex が有効な組合せは、ベースイメージや `packages.txt` で npm が入るかをホスト側で断定せず `guard_warn`（通常起動は進行、`--check` は `[WARN]` 集計）で、npm が必要なことと `codex-version.txt` も空にして無効化できることをビルド前に案内する。呼出位置は env 読込後・`guard_codex_dir` と `guard_codex_agent` の間（両モード）。
- `guard_codex_agent()`: missing 分岐（到達不能になった）を削除し、空ファイルは「Codex の opt-out。使うには対応版を書くか、ファイルを削除して同梱 default を使い `-b`」の案内で `guard_fail`。`latest`・未知版の案内先は採用したパス（`$ASSET_PATH`）。`--check` の `[OK] Codex 版指定` に採用元を添えた。`CODEX_DIR` 明示・`latest` 警告・対応版/protocol/image label のガードは維持。
- 旧名表記の回収（2b-1 からの繰越）: `Dockerfile.claude` のコメントとビルド時エラー文（base-image・packages・node・codex）、`entrypoint.sh`（firewall opt-out の案内、MCP ゲートの根拠、Codex CLI 不在のエラー文）、同梱 `packages.txt`・`requirements.txt`・`allowed-domains.txt` のコメント、`SECURITY-CLAIMS.md` C-1 の限界、`compose.yml` の environment コメントを `.c3c/` に更新した。Dockerfile の node/codex の説明は「同梱 default・project で上書き・空は opt-out」に、npm 不在のエラー文には opt-out の案内を足した。テスト fixture（旧名互換の検査）、旧名互換の説明（README・invariants・`.gitignore`・`examples/c3c/env.example`）、過去の計画記録は置換していない。
- `test-build.sh`: `stage_common_context()` が同梱 default をコピーする（空にするのは `allowed-ports.txt` だけ。opt-out 専用ケースは呼出側で上書き）。`run_config_ro_launcher_tests()` の runner コピーリストに 2 ファイルを追加。`--build-only` 経路に「同梱 default の実検査」（固定版の書式、launcher の `CODEX_SUPPORTED_VERSION`・`codex-mcp-audit.py` の `SUPPORTED_VERSION` との一致、`node --version`＝v24.18.0、`npm --version`、`codex --version`＝codex-cli 0.155.1、`/usr/local/bin/{codex,node,npm}` の実在、`codex-mcp-audit.py --help`）を追加。全体実行に「opt-out と project pin（実ビルド）」（codex 空→codex 不在かつ Node は default、node 空＋codex 有効＋npm 無し base→`npm が必要` で fail、node pin 22.14.0→`node --version` が pin と一致し codex は default）を追加。
- `tests/test_c3c_config.py` に `BuildInputDefaultTests` 8 件、`GuidanceTests` の Codex 案内先の検査を unlink→空ファイルに変更。`tests/test_codex_launch.py` の missing ケースを「同梱 default で起動できる」に変更（他の期待値は不変）。
- 文書: README（設定一覧、node/codex の段落、Codex の各節、アーキテクチャ、イメージの変更、変更後の確認、移行節）、`docs/development-invariants.md`（同梱 default の不変条件、runner コピーリストの較正）、`docs/runtime-ci.md`。

## 回帰検証（fake Podman、実 Podman 不要）

2026-09-21 にホスト（Python 3.14.7、Git 2.53.0、bash 5.3.15、shellcheck 0.11.0、podman 5.8.6 / podman-compose 1.6.0）で実行。

| コマンド | 結果 |
|---|---|
| `python3 -m unittest discover -s tests -p test_c3c_config.py -v` | 22/22 成功。実装前に fixture を修正したうえで新規クラス 8 件を単独実行し、failures=13・errors=2（subtest を含む）を確認。失敗理由は staged が空 hash・INFO/WARNING 行なし等 |
| `... -p test_codex_launch.py` | 32/32 成功（実装前は missing の subtest 1 件が失敗） |
| `... -p test_c3c_launch.py` / `test_agent_preference.py` / `test_project_images.py` / `test_codex_entrypoint.py` / `test_codex_mcp_audit.py`（無変更） | 38/38、30/30、47/47、15/15、36/36 |
| `TMPDIR=/tmp ./test-build.sh --launcher-only` | PASS 253 / FAIL 0（runner コピーリストに default を足す前は 4 FAIL / PASS 237） |
| `./test-build.sh --validator-only` | PASS 82 / FAIL 0 |
| `./lint.sh` | OK（対象 15 本、警告 0、Compose 検証はホストの podman-compose で実行） |

新 suite の検査: 同梱ファイルが契約の固定値で、launcher と Codex helper の対応版と一致する。新旧配置それぞれで、欠落→同梱 default をステージし採用元を表示、project pin→pin をステージし採用元に path を表示、空ファイル→空のままステージし opt-out を表示（`c3c codex`・`--agent codex` は opt-out を理由に rc 1・container 起動なし、`c3c codex --check` は FAIL、Claude の check は FAIL にしない）。設定ディレクトリ無しでも default を使い `.c3c` を作らない（`allowed-ports.txt` は空生成のまま）。pin＝default と欠落の staged file・`ASSET_HASH` は同一（内容だけをハッシュ）、空 opt-out は別 hash。Node 空＋Codex 有効（default/pin）は `WARNING`（npm、`codex-version.txt` を空にする案内）がステージング時の fallback WARNING より前に出て `-b` の build へ進み、`--check` は `[WARN]` と `→ 結果: WARN`。Node pin＋Codex default は WARNING なし。

## 実ビルド（`./test-build.sh` 全体、`tests/test-runtime.sh`）

隔離した Podman storage（第2a段階の GraphRoot を `XDG_DATA_HOME` で再利用。ホストの通常 storage は image 18・container 0 で前後同一）で実行。

- `./test-build.sh` 全体（2 回目、6 分）: PASS 384 / FAIL 0、rc 0。`podman build --no-cache` で `localhost/claude-test`（1.57 GB）を作り、`node --version`＝v24.18.0、`npm --version`、`codex --version`＝codex-cli 0.155.1、`claude --version`、Codex 審査 helper の `--help`、対応版の一致を実検査。opt-out/pin の実ビルド 7 件（codex 空→不在、npm 無し base→`ERROR: codex-version.txt（0.155.1）には npm が必要ですが入っていません…` で fail、node pin→v22.14.0 かつ codex-cli 0.155.1）を含む。1 回目（PASS 383 / FAIL 0）は npm 無し陰性の `check_fails` を定義より前で呼んでいて `command not found`（rc 127）が集計に乗らず黙って抜けていたため成功扱いにせず、block を定義の後へ移して再実行した（`test-build.sh` にこの罠をコメントで残した）。
- `bash tests/test-runtime.sh`（82 秒）: environment / build / mounts / control-before / protected / control-after すべて PASS、rc 0、後始末 0。build 段は `--build-only` 17/17（同梱 default の実検査を含む）、mounts 段は `--config-ro-only` 25/25、protected は `CapEff=0`・iptables 直接操作の拒否・api.github.com:443 到達/80 拒否・`RUNTIME_PROBE_OK`。IPv6 は not run（既定の IPv4 構成、計画の対象外）。`env -i` で `XDG_DATA_HOME` が落ちるため、一時 HOME の `~/.config/containers/storage.conf` に隔離 GraphRoot を書いて起動した。

## 実 Podman・実認証での受入（2026-09-21）

持ち主の既存承認（コンテナ用の既存認証で Claude/Codex を確認する）の範囲で実施。CLI への推論依頼はしていない（起動と通常終了のみ）。詳細な環境・生ログは非公開の検証記録（`/tmp` 配下の実行 ledger と logs）に保存し、ホストの個人パスや認証情報を公開側へ転記しない。

- 環境: 新しい一時 HOME（0700）と新しい使い捨て project（旧配置 `.claude-container.d/`: 第2b-1段階の受入 project と同じ `env`（`CLAUDE_CONFIG_DIR`＝既存の Claude 認証の基点、`CODEX_DIR`＝既存の専用ディレクトリ。byte と mode 0600 を保って複製、値は出力していない）と `allowed-domains.txt` だけ。node/codex の版指定ファイルは置かず、同梱 default を使う）。`CODEX_DIR` が実 `~/.codex` と別実体であることを `-ef` で確認。観測は実 podman をそのまま呼ぶ rc 記録 shim と、第2a段階と同じ PTY harness（ログ先だけ新規）。先行段階の project・logs は変更していない。
- 対象: worktree の `c3c`（symlink）。旧 launcher は基点 `9c6b21d` を `git archive` で展開したもの（worktree は増やしていない）。PROJECT_NAME `project-ddab480a`。

| # | 操作 | 結果 |
|---|---|---|
| 01 | 基点 `9c6b21d` の旧 `c3c claude -b`（旧配置）→ Bypass Permissions 受諾 → `/exit` | build 0 / run 0 / launcher 0。旧 image `a98d16193df7`（`claude-container.asset-hash=ca598737…`、protocol=1）。`podman run` で `node`・`codex` とも不在を実測（旧 launcher は空ファイルをステージ）。Claude Code v2.1.278。記憶 `claude` |
| 02 | 新 launcher `c3c --check`（旧 image） | rc 0。`[INFO] Node.js 版: 24.18.0（採用元: 同梱 default）`・`[INFO] Codex 版: 0.155.1（採用元: 同梱 default）`、`[OK] イメージ既ビルド`、`WARNING: 境界アセット…がイメージのビルド後に変更されています。-b でのリビルドを推奨します`、`→ 結果: WARN`。project と `.build-context` に書込なし |
| 03 | 新 launcher `c3c claude -b`（旧配置）→ 受諾 → `/exit` | build 0 / run 0 / launcher 0。起動前に旧 image に対する drift WARNING。新 image `d170c9cd88dc`（asset-hash `a50df480…`）。`node --version`＝v24.18.0、`npm --version`＝11.16.0、`codex --version`＝codex-cli 0.155.1 を実測。v2.1.278。記憶 `claude` |
| 04 | `c3c codex`（旧配置）→ `/quit` | preflight 0 / run 0 / launcher 0。Codex v0.155.1。MCP ローカル command 定義 0 件（空定義を自動記録、任意コマンドの承認なし）。drift WARNING なし。記憶 `codex` |
| 05 | backup を project 外へ `cp -a` → `mv .claude-container.d .c3c` → `c3c --check` | manifest（mode＋sha256）は改名前と同一。rc 0、`[OK] 設定ディレクトリ: …/.c3c`、default の `[INFO]` 2 行、drift なし、旧名の WARN なし（残る WARN は `packages.txt`/`requirements.txt` fallback と一時 HOME の plugin 別名） |
| 06 | `.c3c` 配置で `c3c claude`（`-b` なし）→ 受諾 → `/exit` | 再ビルドなし（`compose run` のみ）、run 0 / launcher 0。記憶 `claude` |
| 07 | `.c3c` 配置で `c3c codex` → `/quit` | preflight 0 / run 0 / launcher 0、v0.155.1、承認記録と一致（0 件）。記憶 `codex` |
| 08 | opt-out（実 launcher、ビルドなし）: 空の `.c3c/codex-version.txt` で `c3c codex` / `c3c codex --check`、空の `.c3c/node-version.txt`（codex は default）で `c3c --check` | `c3c codex`: rc 1、`INFO: Codex 版: なし（… が空 = opt-out …）`、`ERROR: … が空です（Codex の opt-out …）`、podman の build/run 呼出 0。`c3c codex --check`: FAIL。`c3c --check`（Node 空）: `[WARN] WARNING: … node-version.txt が空 … codex-version.txt は有効（0.155.1）… npm …`、`→ 結果: WARN`、rc 0。opt-out ファイルを除去して project を元の内容へ戻した |
| 09 | `mv .c3c .claude-container.d`（戻し）→ 基点の旧 `claude-container --check`（新 image） | manifest は 01 の原本・backup と同一。旧 launcher の視点では drift WARNING（旧固定入力＝空と旧 Dockerfile の差。ロールバック時は旧 launcher で `-b` が要る、の実測）、rc 0。新 launcher の `--check` は旧名 WARN と default の INFO、drift なし |
| 10 | `bash tests/test-runtime.sh` | 上記「実ビルド」節のとおり全段 PASS |
| 11 | `c3c --clean <project>` | rc 0。image `d170c9cd88dc`・network `project-ddab480a_default`・`.build-context/project-ddab480a`・Codex 承認記録・台帳エントリを削除、記憶 `codex` は残る。`--clean` 契約の dangling prune は隔離 storage 内だけ（旧 image `a98d1619` を含む）。第2a段階の image と `debian:stable`、`localhost/claude-test` は残したまま（一括削除・system reset は行っていない） |

- container のライフサイクル: すべて `--rm` の compose run で、各試行は CLI の通常終了で完了した。`podman stop`/`kill` は 0 回（shim の記録）。停止操作を親と分担していない。
- ホストへの影響: ホストの Podman storage（image 18・container 0）は不変。CLI 標準動作の範囲で Claude の `.claude.json`・`~/.claude/projects/` の履歴、`CODEX_DIR` の sessions が更新されうる（認証の表示・複製なし）。実在利用側の設定ディレクトリは読んでいない。transcript に token 形の文字列・メールアドレスが無いことを走査した。
- 残留する一時資源（削除していない）: 新しい一時 HOME（記憶 JSON・空の承認記録ディレクトリ・storage.conf）、使い捨て project（`env` に既存の専用パスを含む、旧配置のまま）、project 外の backup、logs、`/tmp` の基点 launcher 展開（`.build-context` を含む）。隔離 storage には第2a段階の image・`debian:stable`・`localhost/claude-test` が残る。

## 判断の記録（計画からの差分）

- 採用元の表示は `guard_*` の流儀（両モード共用、`guard_warn`/`guard_fail` 経由）で 1 関数にまとめ、resolver の結果だけを見る（表示側に別の解決規則を持たない）。npm の WARNING は fail-closed にしない — ホスト側では npm の有無を断定できず、ビルド時の `Dockerfile.claude` の検査が fail-closed を担う。
- `guard_codex_agent()` の missing 分岐は resolver が missing を返さなくなったため削除した（防御的に残す案もあったが、到達不能な案内文を残すと「opt-in 必須」の古い説明が残るため）。
- 同梱 default の変更は `ASSET_HASH` に入るため、pin していない全利用側でドリフト診断が出る。これは意図した挙動（旧 image を自動削除せず、`--check` と起動時の WARNING が `-b` を案内する。実機 02・03 で確認）。pin 済みの利用側でも Dockerfile 等の固定アセットが変わるため同様に drift が出る。
- `test-build.sh` の新規 block は `check_fails()` の定義より後に置く必要があった（1 回目の全体実行で `command not found` が集計に乗らず黙って抜けた）。同種の罠は `test-build.sh` 冒頭のコメントにもあるが、`check_fails` は後方で定義されるため別途コメントを残した。
- `tests/test-runtime.sh` は `env -i HOME=$HOME` で `XDG_DATA_HOME` を落とすため、隔離 storage を保つには一時 HOME の `storage.conf` が要る（script は変更していない）。
- `docs/sandbox-considerations.md` の旧名 1 箇所は評価記録の文脈で、今回の回収範囲（現在有効な説明）に含めなかった。

## 独立レビューと確認

GPT-6 Astra が Task 4 の全差分と新規 3 ファイルをレビューし、Critical 0 / Important 0 / Minor 1 と判定した。開始・終了で差分と新規ファイルのハッシュが一致し、新旧配置の resolver/guard を用いた最小確認 12 ケースはすべて成功した。Minor は上記 RED 件数の混在で、実ログに合わせて修正した。レビュー後の変更は文書のみで、実装・テストの内容は変えていない。

親セッションは全体試験の 2 回目（384/0、rc 0）、runtime 全 6 段、CLI 起動・通常終了の全 5 試行（rc 0）を実ログで照合した。レビュー担当は実ビルド・認証受入を再実行していない。

レビューで判断を留保した範囲は、次のように整理した。

- 版指定は従来どおり regular file を採用する。空の regular file とそれを指す symlink は opt-out、`/dev/null` への symlink・dangling link・directory は採用せず同梱 default に進む。非 regular の入力を無効化手段とする契約は追加せず、README に明記した。
- 実ビルドの pin 検査は Dockerfile への入力効果を、本物の launcher を使う fake Podman 検査は resolver・staging・hash を検証する分担である。
- 版の INFO は採用するビルド入力を表す。既存 image の状態は drift 診断と Codex の起動時 version gate が扱う。
- 空ファイルは導入工程を省く指定で、ベースイメージに既設の Node/Codex を削除する指定ではない。

## マージ・公開後の照合

2026-09-21、PR #136 の Codex と Opus 5 による二重レビューで未対応の should-fix 以上はなく、必須 CI 4 件が成功してマージされた。同じマージ commit を指す annotated tag [v10.0.0](https://github.com/jj1xgo/c3c/releases/tag/v10.0.0) を公開した（draft=false、prerelease=false、公開時刻 2026-09-21 06:51:25 UTC）。既定で Node/Codex を導入する変更は、従来の未導入構成を維持するために空ファイルの追加が必要になるので MAJOR と判定した。

GitHub 改名後も PR のマージ SHA、必須 CI 4 件の成功、タグの参照先と Release の公開状態を再取得して照合した。成功済みの実ビルド・runtime・対話受入は再実行していない。

## 未実施・not run

- 実在利用側プロジェクトでの `-b` 再ビルド（同梱 default により Node 24 と Codex CLI が既定で入るため、全利用側で drift 診断→再ビルドが要る。README の手順は使い捨て project で実測。実運用のディレクトリは動かしていない）。
- Docker Compose provider での実起動、IPv6 モード、arm64 での Node tarball 取得。
- 日常利用・認証 refresh・`/resume`・複数セッション同時起動・実モデルへの作業依頼（第2a段階からの対象外を維持）。
