# c3c 第2b-1段階の実装・検証記録

2026-09-21 作成。[第2段階計画](2026-09-21-c3c-phase2.md) の Task 3（2b-1: 設定ディレクトリ `.c3c/` への移行と旧名の互換診断）の実装、fake Podman による回帰検証、実 Podman・実認証での実移行を記録する。実装後に別セッションの Codex が独立コードレビューを行い、Critical 0・Important 0・Minor 1。README の Minor は修正済み（下記参照）。

対象は `3a3efe9efe4d630a913f131595fb245fab570b89`（PR #134 マージ）を基点とする `c3c/phase2b1-config` worktree の差分。実装・検証はコミット前の差分に対して行った（`git diff --binary | sha256sum` = `a965f3222f55…`。`env.example` の移動は `git mv` で index に載せてあり、この hash には含まれない）。公開時の対象 SHA は PR 本文に記録する。実装者は Opus 5（ユーザー指定。advisor・Fable・subagent は使っていない）。

実機検証・独立レビュー前の実装ファイルの sha256（先頭 16 桁。README は後述の文書修正前）:

| ファイル | sha256 |
|---|---|
| `claude-container`（`c3c` は symlink） | 00314de3d024e53a |
| `tests/test_c3c_config.py`（新規） | cb5bef315ce1d6ca |
| `tests/test_c3c_launch.py` | 354a10565c0fc6a7 |
| `test-build.sh` | 8d8f79fd8f4f620c |
| `README.md` | 4a6d3a6e66a4f347 |
| `docs/development-invariants.md` | baedcaf64a680591 |
| `.gitignore` | 4288f0750c5aedf8 |
| `examples/c3c/env.example`（`.claude-container.d/env.example` から移動） | d9239b08615ca3e9 |
| `AGENTS.md` | 24291406c9f869b5 |

## 実装

- `claude-container`: `select_project_conf_dir()` を新設。起動 checkout 直下の `.c3c`（新名）と `.claude-container.d`（旧名）を計画第5節の表で解決し、採用パスを `PROJECT_CONF_DIR` に返してから `readonly` にする。存在判定は `-e` に加えて `-L`（dangling link・同じ実体への 2 本の symlink も「配置あり」）。両方あれば内容や実体が同じでも `guard_fail`、片方だけなら `-d` へ解決できるもの（symlink 可）だけ採用し file・dangling・file への symlink は `guard_fail`、旧名だけは `guard_warn`（`--check` は `[WARN] ` 接頭辞で WARN 集計）、どちらも無ければ `.c3c` を参照元にして作らない。`freeze_project_paths()` からは `PROJECT_CONF_DIR` を外した（清掃に要るパスだけを freeze し、`--clean <dir>` は設定の状態に依存しない）。
- 呼出位置: 通常起動は `record_project_in_ledger` の直後・`ENV_FILE` 確定の前（`--clean` の分岐より後、`load_env_file()` より前）。`--check` は `freeze_project_paths` の直後で `select_project_conf_dir || return 20`（`[FAIL]` と `→ 結果: FAIL` を出し、その対象の env・ガード・resolver・hash・ビルド入力診断へ進まない。ドライバは次の対象へ進む）。
- 案内先の統一: `stage_build_context()` の fallback WARNING、`--check` の `env あり/なし`・`packages.txt` 等の WARN、`guard_base_image()` の指定先を `$PROJECT_CONF_DIR/...`（表示は採用した名前）に変えた。`resolve_asset_source()`・`compute_asset_hash()`・`stage_build_context()`・`guard_codex_agent()` は元から `$PROJECT_CONF_DIR` を使っており、fixed アセットは `RUN_DIR` 固定のまま。
- `tests/test_c3c_config.py`（新規、14 件）: `tests/test_c3c_launch.py` の隔離 HOME・fake podman を継承。fake podman には `ASSET_HASH`・`BASE_IMAGE` の記録だけを足した（既存の期待値は不変）。
- `test-build.sh` の `--launcher-only` に新 suite を登録。`.gitignore` に `.c3c/env` を追加（旧名の行も残す）。`.claude-container.d/env.example` を `examples/c3c/env.example` へ移動（このリポジトリ自身の設定 `.claude-container.d/` はこの変更で動かさない。ルートに `.c3c/` を置くと自身の設定と二重配置になるため、サンプルは `examples/` 配下）。
- README: 現行の操作例・設定一覧・アーキテクチャ・セキュリティモデル・バージョニングの `.claude-container.d/` を `.c3c/` に置き換え（55 箇所）、「利用側プロジェクトの設定」節に配置表・手動移行・backup・ロールバック・両配置不可の小節を追加。互換説明（環境変数節・c3c 入口節・自己ホスト起動・移行小節）には旧名を残した。過去の計画記録・仕様は置換していない。`docs/development-invariants.md` に `select_project_conf_dir()` の不変条件を追加、root `AGENTS.md` の概要とバージョニングの表記を更新。

## 回帰検証（fake Podman、実 Podman 不要）

2026-09-21 にホスト（Python 3.14.7、Git 2.53.0、bash 5.3.15、shellcheck 0.11.0、podman 5.8.6 / podman-compose 1.6.0）で実行。

| コマンド | 結果 |
|---|---|
| `python3 -m unittest discover -s tests -p test_c3c_config.py -v` | 14/14 成功。実装前に 14/14 失敗（failures=38）を先に確認（`test_fixed_boundary_assets...` は当初 `.c3c` が無視されて自明に通ったため、`.c3c/env` が読まれる確認を足して失敗させてから実装） |
| `... -p test_c3c_launch.py`（fake の記録キー追加のみ） | 38/38 成功 |
| `... -p test_codex_launch.py`（旧 suite、無変更） | 32/32 成功 |
| `... -p test_agent_preference.py`（無変更） | 30/30 成功 |
| `... -p test_project_images.py`（無変更） | 47/47 成功 |
| `TMPDIR=/tmp ./test-build.sh --launcher-only` | PASS 253 / FAIL 0（基点の 252 ＋ 新 suite 1） |
| `./test-build.sh --validator-only` | PASS 82 / FAIL 0 |
| `./lint.sh` | OK（対象 15 本、警告 0、Compose 検証はホストの podman-compose で実行） |

新 suite の検査: 配置表の全行（なし/新のみ/旧のみ/両方/file/dangling/file への symlink/ディレクトリへの symlink）を `c3c`・`claude-container` の両入口の通常起動と `--check` で検証。同じ実体への 2 本の symlink・一方が他方への symlink・相対リンク対も二重配置として拒否。二重配置と型不正では env を読まない（env に置いた legacy 変数 `GH_TOKEN_FILE` の ERROR が出ないことで確認）・podman を呼ばない・ステージングしない・対象リポジトリの snapshot が不変。`--check` は 1 対象が不正でも次の対象を最後まで診断し、`unexpected exit`・`unbound` を出さず、HOME・両プロジェクト・`.build-context` の snapshot が不変。`--clean <dir>`・`--clean` は二重配置や `.c3c` がファイルでも image・network・build-context・承認記録・台帳を清掃し、CLI 選択の記憶は残す。`env` に `PROJECT_CONF_DIR=` を書いても許可リスト外の WARNING で無視され、別ディレクトリの `base-image.txt` は読まれない。同じ入力の新旧配置で staged file の sha256 集合と compose へ渡る `ASSET_HASH`・`BASE_IMAGE` が一致し（入力を変えると hash が変わることも確認）、`env` は build context に無く、`--env-file /dev/null` が両配置で付く。`.c3c/` に `entrypoint.sh`・`Dockerfile.claude` 等を置いても staged file と hash は変わらない。`CODEX_DIR` 未設定・`codex-version.txt` 欠落・`base-image.txt` 不正・`env` の `BASE_IMAGE` の案内が採用した名前で出る。

旧名の fixture（`tests/test_codex_launch.py`・`tests/test_c3c_launch.py`・`test-build.sh` のランチャーテスト）は旧名互換の検査として残した。移行推奨の WARNING が増えるだけで、期待値は変えていない（`test-build.sh` の `--check` 検査は `PASS|WARN` を許容済み）。

## 実 Podman・実認証での実移行（2026-09-21）

持ち主の既存承認（コンテナ用の既存認証で Claude/Codex を確認する）の範囲で実施。CLI への推論依頼はしていない（起動と通常終了のみ）。詳細な環境・生ログは非公開の検証記録（`/tmp` 配下の実行 ledger と logs）に保存し、ホストの個人パスや認証情報を公開側へ転記しない。

- 環境: 新しい一時 HOME（0700）と新しい使い捨て project（旧配置 `.claude-container.d/`: 第2a段階の受入 project と同じ `env`（`CLAUDE_CONFIG_DIR`＝既存の Claude 認証の基点、`CODEX_DIR`＝既存の専用ディレクトリ。byte と mode 0600 を保って複製、値は出力していない）、`node-version.txt`=24.18.0、`codex-version.txt`=0.155.1、`allowed-domains.txt`）。Podman storage は `XDG_DATA_HOME` で第2a段階の隔離 storage（GraphRoot を確認。中身は 2a の image と `debian:stable`、container 0）をキャッシュとして再利用し、ホストの通常 storage には触れない（受入前後で `podman images`・`podman ps -a` の一覧が同一）。`CODEX_DIR` が実 `~/.codex` と別実体であることを `-ef` で確認。観測は実 podman をそのまま呼ぶ rc 記録 shim と、第2a段階と同じ PTY harness（ログ先だけ新規）。第2a段階の project・logs は変更していない。
- 対象: worktree の `c3c`（symlink）。旧 launcher は基点 `3a3efe9` を `git archive` で `/tmp` に展開したもの（worktree は増やしていない）。PROJECT_NAME `project-4aaa0d72`。

| # | 操作 | 結果 |
|---|---|---|
| 01 | 旧配置で `c3c --check` | rc 0、`[WARN] WARNING: .../.claude-container.d は旧名です…`、`[OK] .claude-container.d/env あり`、`→ 結果: WARN`。project の snapshot（種別・mode・sha256）は不変 |
| 02 | backup を project 外へ `cp -a` → `mv .claude-container.d .c3c` → `c3c --check` | 改名後の manifest（mode＋sha256）は改名前と同一。rc 0、`[OK] 設定ディレクトリ: .../.c3c`、`[OK] .c3c/env あり`、出力に旧名の文字列なし。残る WARN は既存の `packages.txt`/`requirements.txt` fallback と一時 HOME の plugin 別名で、移行と無関係 |
| 03 | `.c3c` 配置で `c3c claude -b <project>` → Bypass Permissions 受諾 → `/exit` | compose build 0 / run 0 / launcher 0。image `c081636240a3`（label `claude-container.asset-hash=428d020c…`＝第2a段階の同じ入力と同値、`io.c3c.codex-audit-protocol=1`、`project-path` は project）。Claude Code v2.1.278。記憶 `{"schema":1,"agent":"claude"}` 新規作成。残留 container 0 |
| 04 | `.c3c` 配置で `c3c codex <project>` → `/quit` | preflight 0 / run 0 / launcher 0。Codex v0.155.1。MCP ローカル command 定義 0 件（空定義を自動記録、任意コマンドの承認なし）。記憶 `codex` |
| 05 | 二重配置（`.c3c` を `.claude-container.d` へ `cp -a`）で `c3c --check` / `c3c claude` | check: rc 1、`ERROR: 設定ディレクトリが二重配置です…`、`[FAIL] …診断は行いません`、`→ 結果: FAIL`、`FAIL: 1`。project と `.build-context/<project>` の snapshot は不変。launch: rc 1、podman 呼出なし、記憶不変（`codex`） |
| 06 | `mv .c3c .claude-container.d`（戻し）→ `c3c --check` | manifest は 01 の原本・backup と同一（内容と mode を維持）。rc 0、旧名の WARN、`[OK] イメージ既ビルド`、ドリフト WARNING なし（`.c3c` でビルドした image の hash と旧配置の hash が一致） |
| 07 | 基点 `3a3efe9` の旧 `claude-container --check`（旧配置 / `.c3c` 配置） | 旧配置: rc 0、`env あり`、image 既ビルド、ドリフトなし。`.c3c` 配置: 旧 launcher は読まず `env なし` の既定値扱い（ロールバック時に戻し忘れると既定値で起動する、の実測） |
| 08 | 旧配置で基点の旧 `claude-container <project>` → 受諾 → `/exit`（ロールバック経路） | run 0 / launcher 0、再ビルドなし（`compose run` のみ）、ドリフト WARNING なし。v2.1.278 |
| 09 | 二重配置のまま `c3c --clean <project>` | rc 0。image `c081636240a3`・network `project-4aaa0d72_default`・`.build-context/project-4aaa0d72`・Codex 承認記録・台帳エントリを削除、記憶 `codex` は残る。2a の image と `debian:stable` は残したまま（一括削除・system reset は行っていない） |

- container のライフサイクル: すべて `--rm` の compose run で、各試行は CLI の通常終了で完了した。`podman stop`/`kill` は 0 回（shim の記録）。停止操作を親と分担していない。
- ホストへの影響: ホストの Podman storage（image 18 件・container 0）は不変。CLI 標準動作の範囲で Claude の `.claude.json`・`~/.claude/projects/` の履歴、`CODEX_DIR` の sessions が更新されうる（認証の表示・複製なし）。実在利用側の `.claude-container.d/` は読んでいない。transcript に token 形の文字列・メールアドレスが無いことを走査した。
- 残留する一時資源（削除していない）: 新しい一時 HOME（記憶 JSON・空の承認記録ディレクトリ）、使い捨て project（`env` に既存の専用パスを含む、旧配置のまま）、project 外の backup、logs、`/tmp` の基点 launcher 展開（`.build-context` を含む）。第2a段階の隔離 storage には 2a の image と `debian:stable` が残る。

## 判断の記録（計画からの差分）

- 通常起動での `select_project_conf_dir()` は `record_project_in_ledger` の直後（c3c の初回選択・記憶採用の後）に置いた。当初は「設定不正なら CLI を尋ねる前に止める」案も検討したが、既存の「fail-closed ガードで止まる起動も台帳に記録する（`--check` の一括診断で拾うため）」契約と、他のガード（`CODEX_DIR` 未設定等も選択の後に止まる）との整合を優先した。記憶は書かれず container も起動しない。
- 二重配置の判定は `.c3c` 側が正しいディレクトリでも旧名側が dangling link 等なら止める（部分的に読まず、混ぜない）。
- `--check` の失敗対象は `[FAIL] 設定ディレクトリを解決できないため…` と `→ 結果: FAIL` を出して `return 20`（既存の「ディレクトリを開けません」の早期 return と同じ集計）。
- `Dockerfile.claude`・`entrypoint.sh`・同梱 `packages.txt`/`requirements.txt`/`allowed-domains.txt` のコメントとエラー文に残る `.claude-container.d/` は今回触っていない。Task 3 の対象ファイルに無く、Task 4（2b-2）が `Dockerfile.claude（説明・エラー文）` を明示しているため。これらは `ASSET_HASH` の対象で、変更すると全利用側に drift 警告が出る副作用もある。ビルド時のエラー文（例: `.claude-container.d/node-version.txt には …`）は `.c3c/` 配置でも旧名で表示される（残件）。
- `.claude-container.d/env.example` の移動は `git mv`（index に rename が載る。commit はしていない）。

## 独立レビューと親セッションの照合

- 別セッションの Codex が基点からの全差分（sample の staged rename・新規テストを含む）と Task 3 の仕様を静的レビューした。Critical 0・Important 0・Minor 1。開始・終了の差分と新規ファイルの hash は一致した。
- Minor: README の移行説明で CLI 選択記憶まで「起動パス単位」と記載していた。既存の仕様・実装どおり Git common directory 単位（非 Git はパスの実体単位）に訂正した。併せて Dockerfile・entrypoint の旧名エラー文が残る制限を移行説明に明記した。製品コード・テストはレビュー後に変更していない。
- 旧名エラー文の Task 4 への延期は、固定アセット変更による全利用側の hash drift を避ける分割としてレビュアーも妥当と判断した。Task 4 では entrypoint・同梱 fallback コメントも回収する。
- 親セッションは実装前の基点に新 suite と fake 記録だけを載せて RED を再確認し、14 test methods の全失敗（subtest failures 38、errors 0）を確認した。実機ログでは移行前・移行後・戻し後の manifest の byte 一致、Claude/Codex と旧 launcher の終了 rc 0、check の WARN/FAIL 集計、clean 後の CLI 記憶残存を照合した。実機の独立再実行はしていない。
- レビュアーは全 suite・実機・CI を再実行していない。PR 後のレビューと CI は別途確認する。独立レビュー全文と親の照合記録は非公開の検証証跡へ保存する。
- 文書修正後の README sha256: `0bde707ea43bde6d2303712dcf23be1bd9470ea982684378ace90237338b5813`。冒頭の差分 hash と表は実装時点の履歴であり、この文書修正後の差分を表すものではない。

## 未実施・not run

- PR 後のレビュー・必須 CI（未公開）。
- `./test-build.sh` の全体実行と `bash tests/test-runtime.sh`（計画 §7 は 2b-2 の必須。2b-1 では `--launcher-only`・`--validator-only`・lint と上記の実 Podman 実移行で検証）。
- 実在利用側プロジェクトの移行（README の手順は使い捨て project で実測。実運用のディレクトリは動かしていない）。
- 日常利用・認証 refresh・`/resume`・複数セッション同時起動・実モデルへの作業依頼（第2a段階からの対象外を維持）。
- Docker Compose provider での実起動、IPv6 モード。
