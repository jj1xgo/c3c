# plugin メタデータのホスト絶対パスをコンテナ内で解決する実装計画（#98）

**目的:** ホストで install した plugin が、コンテナ内で `cache-miss` にならず読み込まれる状態に戻す。`~/.claude/plugins` の `:ro` 保護（`0a064c9`、2026-09-11）は維持する。

**構成:** launcher がホスト側 `plugins/` の絶対パス（ホストの Claude Code が記録した綴り）を算出し、同じ実体をコンテナ内の**ホストと同じ絶対パス**にも `:ro` で重ねる固定 Compose override を、条件を満たすときだけ追加する（IPv6 の `compose.ipv6.yml` と同じ選択パターン）。JSON の書き換えは行わない。

**技術:** Bash、Podman Compose（override のマージ）、既存のダミー podman ランチャーテスト（`test-build.sh --launcher-only`）、`tests/` の Python unittest。

## 背景（このセッションでコンテナ内から実測）

- `entrypoint.sh` 37〜41 行は `known_marketplaces.json` / `installed_plugins.json` 内の `/home/<user>/.claude` を `/home/node/.claude` へ `sed -i` で書き換える（`c6f5597` で導入、README「アーキテクチャ」の `entrypoint.sh` 項に記載）。
- `0a064c9`（user scope 11 項目の `:ro` 重ねマウント）以降、`plugins/` は読み取り専用で `sed -i` は `couldn't open temporary file ...: Read-only file system`（終了コード 4）で失敗する。stderr にはエラーが出るが、`[ -f "$f" ] && sed -i ...` の形で `set -e` も無いため終了ステータスは起動中止へ反映されず後続へ進み、`claude plugin list` は `Marketplace claude-plugins-official failed to load: cache-miss` になる。`0a064c9` は `entrypoint.sh` に触れておらず、設計変更ではなく見落としの回帰。
- 旧機構は rw の親マウント越しにホストの JSON を書き換えていた。`:ro` 化はその経路を閉じるのが目的なので、書き込みを戻す選択肢は無い。
- 実証 1: `plugins/` を書き込み可能な場所へコピーし 2 つの JSON のパスをコピー先へ書き換えて `CLAUDE_CONFIG_DIR` で指すと `enabled` になる（パスが解決できれば読める）。
- 実証 2: `CLAUDE_CONFIG_DIR/plugins/` には JSON 2 つと `data/` だけを置き、JSON のパスが指す先を `CLAUDE_CONFIG_DIR` の**外**にある実体（cache/ と marketplaces/ のコピー）にしても `enabled` になる。実体側を `chmod -R a-w` で読み取り専用にしても同じ。→ JSON は書き換えず、メタデータが指す絶対パスにホストと同じ実体を `:ro` で見せれば足りる。
- `entrypoint.sh` は node ユーザーで走り `/home` は root 所有 755 なので、ランタイムに `/home/<user>` を作る案は権限が無い。マウント先は podman がコンテナ作成時に作る（実機確認は Task 5）。
- 観測したメタデータの綴りはホストの `$HOME` 配下（`/home/<user>/.claude/plugins/...`）。ホストの Claude Code が常に「未解決の `$HOME` の綴り」を記録するかは Claude Code 側の保証ではないので、本計画は**綴りが `$HOME` 配下であるケース**を対応範囲とし、それ以外は対応しない（Task 5 の受け入れ条件で実データと照合する）。

## 検討して採らなかった案

- launcher が書き換え済み JSON のコピーを作り 2 ファイルを `:ro` で重ねる（issue の案 2）: 独自の JSON 書き換えロジックが要る。Claude Code 側のメタデータ形式が変わるたびに追随が要り、監査対象が増える。
- `Dockerfile.claude` でホストの `$HOME` へのシンボリックリンクを焼き込む: イメージがホストのユーザー名に結合し、`base-image.txt` 等と違って利用側が宣言する値でもない。
- `compose.yml` に 1 行足す: マウント先が動的で、ホストの `plugins/` が既に `/home/node/.claude/plugins` を指す場合（devcontainer 系ホストで起こりうる）に既存の `:ro` 行と destination が重複する。未設定時の既定 destination も lint 用に要るが、重複か架空パスへの幽霊マウントのどちらかになる。override なら「足さない」で表現できる。
- launcher が JSON を読んで記録された綴りを使う: Claude Code のメタデータ形式への依存が生じる（案 2 と同じ理由）。launcher は JSON を読まない。

## 設計

- **override ファイル** `compose.plugins-alias.yml`（固定アセット、launcher が選ぶ。`compose.ipv6.yml` と同格）:
  ```yaml
  # launcher が guard_plugins_alias() の条件を満たすときだけ追加する固定設定（claude-container#98）。
  # plugin のメタデータ（known_marketplaces.json / installed_plugins.json）はホストの絶対パスを
  # 記録しているため、同じ実体をその絶対パスにも :ro で見せる。source と :ro は compose.yml の
  # 保護マウントと同一。destination は launcher が算出して export する。
  services:
    claude-auth-workspace:
      volumes:
        - ${CLAUDE_CONFIG_DIR:-~}/.claude/plugins:${CLAUDE_PLUGINS_HOST_PATH:?launcher が export する}:ro
  ```
  `:?` により export 漏れは `config` 段階で失敗する（空 destination へのマウントにならない）。
- **destination の綴り**: `prepare_claude_config_ro()` は `CLAUDE_CONFIG_DIR` 明示時に `pwd -P` で実体解決した値を export する。メタデータはホストの Claude Code が見た綴りを記録するので、別名の destination は「`~` 展開済み・実体未解決」の基点から作る。`prepare_claude_config_ro()` は基点の検証（絶対パス・存在・`cd` 可）を通過した直後に `CLAUDE_CONFIG_HOST_BASE` を設定する（明示時は展開直後の値、未設定時は `$HOME` の綴り）。関数冒頭で空に初期化し、検証で `guard_fail` した経路では空のまま残す。
- **判定関数** `plugins_alias_target()`（副作用なし、引数 `<host base の綴り> <$HOME>`、stdout に destination または空、終了コードで理由を返す: 0=適用、1=別名不要〈`/home/node/.claude/plugins` と一致〉、2=対応範囲外）。規則:
  1. まず base を正規化する（末尾の `/`・`/.` の連なりを除去、`//` を `/` に圧縮。正規化後も `/../` や `/./` を含む、または `/` 単体になるものは範囲外=2）。候補 = `<正規化した base>/.claude/plugins`。
  2. 候補が `/home/node/.claude/plugins` と一致 → 1。
  3. 正規化した base が、同じ規則で正規化した `$HOME` と一致するか、その配下でない → 2（実体パスや別基点で指定された `CLAUDE_CONFIG_DIR` は、メタデータの綴りと一致する保証が無い）。
  4. 候補がコンテナ内の固定マウント先 `/workspace`・`/data`・`/shared`・`/home/node` のいずれかと一致または配下 → 2（対象プロジェクトや他マウントの内容を隠すため。ホストの `$HOME` がこれらの場合に起きる）。
  5. それ以外 → 0、候補を出力。
  関数定義だけを `sed -n '/^plugins_alias_target()/,/^}/p'` で抽出して bash から呼べるようにし（`tests/test_ipv6_entrypoint.py` が entrypoint を分割して実行するのと同じ手法）、`/home/node` を作らずに一致分岐をテストする。関数はファイルシステムに触れない（存在確認は `prepare_claude_config_ro()` が済ませている）。
- **`guard_plugins_alias()`**（通常起動と `--check` の両モード共用。`guard_*` 群の規則に従い `guard_warn` を使う。起動を止めない = `guard_fail` は使わない）:
  - `CLAUDE_CONFIG_HOST_BASE` が空（基点検証で失敗）なら何もしない（`--check` で不正な基点に対し成功風の INFO を出さない）。
  - `plugins_alias_target "$CLAUDE_CONFIG_HOST_BASE" "$HOME"` の結果で: 0 → `export CLAUDE_PLUGINS_HOST_PATH=<候補>`、`COMPOSE_OVERRIDE_ARGS+=(-f "$RUN_DIR/compose.plugins-alias.yml")`、`--check` では `[OK]   plugin 別名: <候補>`。1 → `--check` で `[INFO] plugin 別名: 不要（コンテナ内パスと一致）`。2 → `guard_warn "WARNING: ホストの plugins/ の綴り <候補> はコンテナ内で別名にできません（理由）。ホストで install した plugin はコンテナ内で読み込めません"`。
  - 呼び出し位置は両経路とも `prepare_claude_config_ro` の直後。`plugins/` は 11 項目準備で必ず存在するので、別名の source が無いことによるホスト側残骸は起きない。`--check` は固定ファイル参照と変数操作だけで何も作らない（`snapshot_check_targets` で担保）。
- **`COMPOSE_IPV6_ARGS` → `COMPOSE_OVERRIDE_ARGS`**: `guard_ipv6()` と `guard_plugins_alias()` は通常起動の dispatch と `check_one_project()` の両経路から呼ばれる。初期化は関数定義群の後・dispatch 分岐の前のトップレベルで 1 回、`check_one_project()` 冒頭（複数プロジェクトをループ）でもリセット。両関数は `+=`。build と run の両 `podman compose` 行で同じ配列を渡す（`ASSET_HASH` と同じ理由）。
- `CLAUDE_PLUGINS_HOST_PATH` は launcher 内部で算出する値であり、`.claude-container.d/env` の許可リスト（`ENV_FILE_ALLOWED_KEYS`）にも README「環境変数」表にも載せない（E7 は不変）。基点は `guard_env_boundary_keys()` が既に一覧表示する `CLAUDE_CONFIG_DIR` に従う。
- `compose.plugins-alias.yml` を `resolve_asset_source()` の fixed 群と `ASSET_HASH_TARGETS` に登録する（ドリフト検知）。staging はしない（compose は `RUN_DIR` から直接読む。`compose.ipv6.yml` と同じ）。
- **entrypoint.sh**: 37〜41 行の `sed` ループを削除する。`tests/test_ipv6_entrypoint.py` の `test_refresh_loop_preserves_mode` は `split('\nfor f in ')` でこのループを起動前半の抽出境界に使っているため、削除すると後半（シークレット読み込み・MCP ゲート・`exec claude`）まで実行対象になる。`entrypoint.sh` の同じ位置に明示のマーカーコメント（例: `# --- 起動前半ここまで（tests/test_ipv6_entrypoint.py の抽出境界） ---`）を置き、テストの区切りをそのマーカーに変える。境界アセットの変更なので利用側は `-b` が要り、`guard_asset_drift()` が警告する。
- **セキュリティ**: source と `:ro` は保護マウントと同一。destination はホストの `$HOME` 配下の綴りに限り、コンテナ内の固定マウント先配下と `/home/node` 配下は除外する。ホストのユーザー名は既に `~/.claude.json` の `projects` キー経由でコンテナ内から見えており、新たな露出ではない。
- **#99 との関係**: `SHARED_MOUNT` をホストと同じ絶対パスでも見せる要望 1 は同じ override 機構に独自の条件を付けたもので、本計画には含めず #99 で別途扱う。要望 2（`~/.agents`）も対象外。

## 依存先の数え直し

`grep -rn compose.ipv6.yml` の結果は 5 ファイル 8 参照: `lint.sh` 68、`claude-container` 304（選択）・855（fixed 群）・890（`ASSET_HASH_TARGETS`）、`test-build.sh` 1030〜1060（`compose-args` 検査）・1071（隔離コピー一覧）、README 101（IPv6 節、対象外）・299（`compose.yml` 項）。名前検索で拾えない依存先が 2 つある: `tests/test_ipv6_entrypoint.py`（`entrypoint.sh` の行構造に依存）と `run_config_ro_tests()`（`compose.yml` 単独で起動し、override 込みの構成は検証しない）。

## Task 1: テストを先に書く

対象: `test-build.sh`（新関数 `run_plugins_alias_launcher_tests` を `run_launcher_tests` に追加。入口は既存の一本化に従う）、`tests/test_ipv6_entrypoint.py`。

- [x] ダミー podman（`launcher_sandbox_init`）を呼び出しごとの記録に拡張する: 従来の `compose-env`（最後の呼び出し、既存テストの互換維持）に加え、`compose-env.<n>` と `compose-args.<n>` を呼び出し順に残す。
- [x] `plugins_alias_target()` の単体テスト（関数抽出、`/home/node` 不要）: `/home/u` → 0 と `/home/u/.claude/plugins`、`/home/u/` と `/home/u/.` → 同じ正規化値、`/home/node` と `/home/node/` → 1、base が `$HOME` 配下でない（`/opt/cfg`、`$HOME` の実体パス綴り違い）→ 2、候補が `/workspace`・`/data`・`/shared` 配下 → 2、`/home/u/../x` → 2。
- [x] 既定（`CLAUDE_CONFIG_DIR` 未設定、HOME は sandbox の一時ディレクトリ）: run 呼び出しの env に `CLAUDE_PLUGINS_HOST_PATH=$home/.claude/plugins`、args に `compose.plugins-alias.yml`。`-b` では build・run の**各**呼び出しにそれぞれ env と override が 1 回ずつ。
- [x] `CLAUDE_CONTAINER_IPV6=1` 併用の `-b`: build・run の各呼び出しに `compose.ipv6.yml` と `compose.plugins-alias.yml` が 1 回ずつ。
- [x] `CLAUDE_CONFIG_DIR=~/cfg/`（末尾スラッシュ）: 値が `$home/cfg/.claude/plugins`。
- [x] HOME がシンボリックリンク（`$root/home-link -> $root/home`、`HOME=$root/home-link`）: 値がリンクの綴り `$root/home-link/.claude/plugins`（launcher が綴りを保つことの検証。メタデータ側の綴りは Task 5 で実データと照合する）。
- [x] 範囲外: `CLAUDE_CONFIG_DIR=$proj`（`$HOME` 配下でない）→ rc=0、`WARNING` を含む、override 無し、`CLAUDE_PLUGINS_HOST_PATH` 未 export。`--check` でも同じ `WARNING` が出る。
- [x] `--check`: 既定・範囲外・基点不正（`CLAUDE_CONFIG_DIR=/nonexistent`）・`.claude` 不在の 4 ケースで `snapshot_check_targets` の前後が一致し、基点不正では plugin 別名の `[OK]` が出ない。
- [x] 隔離コピー一覧（1071）に `compose.plugins-alias.yml` を足す。
- [x] `tests/test_ipv6_entrypoint.py`: 抽出境界をマーカーコメントに変え、抽出結果に `exec claude` と `secrets` の文字列が含まれないことをアサートする（境界が壊れたら検出する）。
- [x] `bash test-build.sh --launcher-only` で新テストだけが失敗することを確認する。

## Task 2: override・launcher・lint

対象: 新規 `compose.plugins-alias.yml`、`claude-container`、`lint.sh`。

- [x] override を上記のとおり作る。
- [x] `prepare_claude_config_ro()` に `CLAUDE_CONFIG_HOST_BASE` の初期化と設定を入れ、`plugins_alias_target()` と `guard_plugins_alias()` を実装し、通常起動 dispatch と `check_one_project()` の両方で `prepare_claude_config_ro` の直後に呼ぶ。
- [x] `COMPOSE_IPV6_ARGS` → `COMPOSE_OVERRIDE_ARGS` の統合（初期化 2 箇所、`guard_ipv6()` は `+=`）。
- [x] `resolve_asset_source()` fixed 群と `ASSET_HASH_TARGETS` に登録する。
- [x] `lint.sh`: `CLAUDE_PLUGINS_HOST_PATH=/tmp/lint-plugins-alias` を与えて `-f compose.yml -f compose.plugins-alias.yml` と、3 ファイル同時（`compose.ipv6.yml` も）の 2 通りを追加する。3 ファイル同時では `config` の出力に別名 volume と IPv6 の `network_mode`・sysctls・environment が残ることを `grep` で確認する（マージで消えないこと）。
- [x] `./lint.sh`、`bash test-build.sh --launcher-only` が通る（コンテナ内では compose config は graceful skip になるので、config はホスト側で確認する — Task 5）。
- [ ] `${CLAUDE_PLUGINS_HOST_PATH:?}` の fail-closed は compose provider 依存。ホストの `podman compose` バックエンドと CI の Docker Compose provider の両方で、変数未設定のまま 2 ファイル `config` を実行して非 0 で終わることを確認する。どちらかが空文字として通す場合は launcher の無条件 export が唯一のガードになるので、override のコメントにその旨を書く。

## Task 3: entrypoint.sh の死んだ sed を削除する

対象: `entrypoint.sh`。

- [x] 37〜41 行を削除し、同じ位置にマーカーコメントを置く。`bash -n`・shellcheck（PostToolUse hook）を通す。
- [x] `python3 -m unittest discover -s tests -p 'test_ipv6_*.py'` が通る。
- [x] `ASSET_HASH` が変わるので、利用側で `-b` が必要になる旨を PR 本文とリリースノート案に書く。

## Task 4: 文書

対象: `README.md`（公開）、`.claude/CLAUDE.md`（ops リポジトリへ別コミット）。

- [x] README「アーキテクチャ」`entrypoint.sh` 項（301 行）: 「`~/.claude/plugins/` 内に残るホスト側のパスをコンテナ内パスへ自動修正し」を削除する。
- [x] README「アーキテクチャ」`compose.yml` 項（299 行）: `compose.plugins-alias.yml` の役割を 1 文で足す（IPv6 の記述と同じ位置）。
- [x] README「何ができて何ができないか」の 11 項目の行（359 行）: plugin は launcher がホストと同じ絶対パスにも `:ro` で重ねることで読み込まれる旨、対応範囲（`$HOME` 配下の綴り）と範囲外時の `WARNING`、旧版（`0a064c9` 〜本修正）では `cache-miss` になっていた旨を補う。
- [x] README「セキュリティモデル」の読み取り専用保護の段落（398 行）: 限界 (1)〜(6) の後に (7) として別名マウントの位置づけ（同じ source・`:ro`、適用条件、除外条件）を足す。
- [x] README「変更後の確認」: `-b` が要る変更の例に本件を加える必要があるか確認し、不要なら触らない。
- [x] `.claude/CLAUDE.md` の `compose.yml` 不変条件に 1 項目: 「plugin 別名は launcher が選ぶ override（`compose.plugins-alias.yml`）でのみ付け、source は保護マウントと同一、`:ro` を外さない、`compose.yml` 本体に固定 destination で書かない（重複 destination と幽霊マウントを避けるため）。適用条件の正本は `plugins_alias_target()`」。`COMPOSE_OVERRIDE_ARGS` は build・run 両方へ渡す旨を `ASSET_HASH` の項に並べる。`entrypoint.sh` の項に「抽出境界マーカーを `tests/test_ipv6_entrypoint.py` が使う」を足す。
- [x] #102 の「目次に新節が無い」は本 PR の README 改訂で触る範囲に限り相乗りさせる（残りは #102 のまま）。

## Task 5: ホスト側検証・レビュー・PR

- [ ] ホストで `./lint.sh`（compose config 2 通りを含む）、`bash test-build.sh --launcher-only`。
- [ ] **受け入れ条件（メタデータの綴り）**: ホストの `~/.claude/plugins/known_marketplaces.json` の `installLocation` と `installed_plugins.json` の `installPath` の接頭辞が、launcher が export する `CLAUDE_PLUGINS_HOST_PATH` と一致する（`jq` で取り出して比較）。一致しなければ対応範囲の定義を見直す。
- [ ] `-b` で自己ホスト起動し、コンテナ内で: `mount | grep plugins` に別名 destination が `ro` で出る、`claude plugin list` が `enabled`、セッション内で plugin の skill（例: superpowers の brainstorming）が Skill 一覧に現れる、`/home/<host user>` が root 所有で作られ `touch` が失敗する。
- [ ] `run_config_ro_tests()` を override 込みの実構成でも走らせるよう拡張する（`CLAUDE_PLUGINS_HOST_PATH` を一時パスに設定し `-f compose.yml -f compose.plugins-alias.yml` で起動）。プローブは標準パス（11 項目）に加え別名パスでも作成・追記・削除・置換を試み、EROFS/EBUSY で失敗すること、ホスト側の内容が不変であること、ホスト側に実行ユーザー以外の所有エントリが無いことを確認する。`test-build.sh` 本体を通す。
- [ ] 旧イメージ（`-b` 前）で起動して `guard_asset_drift()` の警告が出ることを 1 回確認する。
- [ ] `git status` で利用側リポジトリとホスト `~/.claude` に残骸が無い。
- [ ] 差分を commit し、PR 本文に実測結果・`not run`・レビュー全文を載せる。レビューは Fable と Codex（`codex exec --sandbox read-only`、background、`< /dev/null`）の二重。マージは持ち主が手で行う。
- [ ] マージ後: 既定挙動の変更（plugin が読めるようになる）と `-b` 必須なので `release-tag` skill でタグ案（MINOR）を提示し、承認後に作成する。`--check` は `guard_asset_drift()` を呼ぶのでアセット差分の警告は出すが、別名マウントや plugin 読み込みの実動作は検証しない。タグ提案前の実機確認は「`--check` で drift 警告が出る」と Task 5 の実起動で行う。

## 検証記録

コンテナ内（worktree `fix/plugins-host-path-alias-98`、2026-09-13、実装は Opus）:

- `./lint.sh`: OK（`bash -n`・shellcheck・Python 構文。compose config は podman 不在で graceful skip）。
- `bash test-build.sh --launcher-only`: PASS=171 FAIL=0（新規: 判定関数の単体 21 件、P1〜P7 の配線・`--check` 不変 14 件。IPv6 の Python テスト 27 件を含む）。実装前は新テスト 30 件と IPv6 entrypoint テストが失敗することを確認済み。
- `./test-build.sh --validator-only`: PASS=82 FAIL=0。
- `python3 -m unittest discover -s tests -p 'test_ipv6_*.py'`: 27 件 OK（抽出境界をマーカーへ変更後）。
- not run（ホスト側、Task 5）: `podman compose config`（override 単独・3 ファイル同時・`:?` の provider 依存）、`-b` 実起動での `claude plugin list`・別名マウントの `ro`・親ディレクトリの所有、`run_config_ro_tests()` の override 込みプローブ（実 podman）、メタデータ綴りの受け入れ条件、旧イメージでの drift 警告。
- not run: `.claude/hooks/lint-posttool.sh` の実発火。編集をすべて Bash 経由で行ったため PostToolUse hook は発火していない。加えて worktree には product 側で gitignore された `.claude/` が無く、`$CLAUDE_PROJECT_DIR/.claude/hooks/lint-posttool.sh` は worktree 内で解決しない（worktree 運用の既知の制約として別途記録）。shellcheck は lint.sh で手動実行した。

## レビュー記録

- Codex 監査 1 巡目（2026-09-13、コンテナ内 `codex exec --sandbox read-only < /dev/null`、初実走で正常終了）: blocker 2・should-fix 5・nit 2。全件反映（IPv6 テストの抽出境界、destination の適用範囲と `guard_*` 化、override 込みの `:ro` プローブ、呼び出しごとの env 記録、`CLAUDE_CONFIG_HOST_BASE` の初期化分岐、衝突判定の正規化と関数抽出テスト、メタデータ綴りの受け入れ条件、文言 2 件）。
- Codex 実装レビュー（同日、コンテナ内 `codex exec --sandbox read-only` で `git diff main...HEAD` を照合）: blocker 0・should-fix 1・nit 2。should-fix（規則 2 の一致判定が `$HOME` の検証より後に来ており、`$HOME` が不正または別値のとき計画と異なり範囲外になる）→ 規則 2 を `$HOME` 検証より先に移し、一致ケースを 3 件追加。nit 2 件も反映（単体検査を `bash -euo pipefail` で実行、`guard_plugins_alias()` 冒頭で `CLAUDE_PLUGINS_HOST_PATH` を unset し注入ケースを P6 に追加）。
- Codex 確認限定巡（同日）: 反映済み 8、矛盾 1（base の正規化順序。`/home/u/.` を正常系とするテストと「`/./` を範囲外」が衝突）→ base を先に正規化してから候補を組み立てる順序に修正。

---

実装: Opus — compose の volumes 層（`:ro` 境界そのもの）と境界アセット `entrypoint.sh` を触るため。Codex でなく Claude なのは受け入れ試験がホストでのコンテナ起動と本コンテナ内セッションからの継続を含むため（判定基準 1）。
