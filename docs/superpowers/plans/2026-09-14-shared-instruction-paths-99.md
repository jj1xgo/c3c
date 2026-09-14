# ホストの指示ファイルとスキルをコンテナ内で解決する実装計画（#99）

**目的:** ホストの `~/.claude/CLAUDE.md` が `@~/obsidian-vault/knowledge/索引.md` のように `~` 起点で参照する共有ディレクトリと、Codex 等が共通で読む `~/.agents/skills/` を、グローバル指示ファイルを二重管理せずにコンテナ内でも読める状態にする。`/shared` の rw 用途は変えない。

**構成:** launcher が opt-in と値を検証したときだけ、`SHARED_MOUNT` の実体をコンテナ内の `~`（`/home/node`）配下の同じ相対位置とホストと同じ絶対パスにも `:ro` で重ねる固定 Compose override（`compose.shared-home.yml`・`compose.shared-host.yml`）と、`AGENTS_DIR` を `/home/node/.agents` に `:ro` で付ける固定 override（`compose.agents.yml`）を `COMPOSE_OVERRIDE_ARGS` に積む。機構は #98 の plugin 別名マウントと同型。

**技術:** Bash、Podman Compose（override のマージ、bind の long syntax）、既存のダミー podman ランチャーテスト（`test-build.sh --launcher-only`）。

## 前提（ブランチの状態）

- ブランチ `fix/shared-instruction-paths-99` の先頭には、2026-09-14 に削除した Codex worktree の未コミット差分を**未レビューのまま**復元したコミット（`wip: #99 の Codex 草稿を復元する`）が載っている。本計画はその草稿を出発点にし、Task 1〜4 で差分を当てる。草稿を捨てて書き直さない。
- 草稿のまま `./test-build.sh --launcher-only` を回すと `PASS=232 FAIL=1` で、赤は `E7: ENV_FILE_ALLOWED_KEYS と README「環境変数」節の表が一致する` だけ（README に新キーの行が無いため）。`./lint.sh` は緑（host、podman-compose 1.6.0）。草稿自身のテスト群（`## 指示ファイルとスキルの追加共有（#99）`）は全て PASS。
- 草稿の compose override 3 本は `podman compose config` を通り、`${VAR:?}` は未設定・空文字とも rc=1 で拒否する（host 実測）。
- 入れ子の bind mount は volumes の並び順に依存しない（podman 5.8.6 で、親 `/x` と子 `/x/y` をどちらの順で渡しても両方見え、両方 `:ro` が効くことを実測）。

## 検討して採らなかった案

- **entrypoint でシンボリックリンクを張る**（Issue の案 1 系）: `entrypoint.sh` は node ユーザーで走り `/home` は root 所有 755 なので `/home/<host user>` を作れない（#98 の却下理由と同じ）。リンクでは読み取り専用にもできない。
- **#98 と同じく opt-in 無しで自動適用する**: 露出は増えない（同じ実体が `/shared` に rw で既にある）が、持ち主の 2026-09-13 の Issue 追記「追加共有は opt-in・読み取り専用を基本」に従い `SHARED_MOUNT_HOME_ALIAS=1` の明示にする。自動化は将来の判断として残す。
- **別名を rw にする**: 同上の追記に従い `:ro`。ただし `/shared` が rw のままなので**境界ではない**（README に明記する）。書き込みは従来どおり `/shared` 経由で行う運用の目印に留まる。
- **plugin 別名との重なり検査**（草稿に含まれる）: 草稿はこの検査のために `CLAUDE_CONFIG_DIR` の `~` 展開を `prepare_claude_config_ro()` と別に再実装している（2 箇所で解決規則を持つとドリフトする、`.claude/CLAUDE.md` の `resolve_asset_source()` 項と同じ懸念）。`SHARED_MOUNT` の HOME 直下の隠しディレクトリ（`.claude` 等）は別途拒否済みで、残る重なりは「`CLAUDE_CONFIG_DIR` が `SHARED_MOUNT` 配下」の場合だけ。その場合も `:ro` 同士の入れ子で順序に依存せず両方見える（上記実測）ため無害。検査ごと削除する（Task 1）。
- **新ガードを `guard_plugins_alias()` の後ろへ移す**（`CLAUDE_CONFIG_HOST_BASE` を使うため）: `guard_plugins_alias()` は MCP 監査ゲートの TTY 承認より後に走るので、fail-closed の拒否が承認の後になる。上記のとおり検査自体を消すので移さない。位置は草稿のまま（`guard_shared_mount()` の直後）。
- **テストを `tests/*.sh` に分けて `source` する**（草稿）: #98 のランチャーテストは `test-build.sh` 内の関数で、`--launcher-only` の入口も既にある。新しい入口 `--instruction-mounts-only` と `source` 経路を増やさず、関数を `test-build.sh` に置く（Task 2）。`tests/test-*.sh` に単独実行できる形で置いているのは firewall のテスト群だけで、こちらは隔離ハーネス（`launcher_sandbox_init` 等）に依存するため単独実行できない。

## 設計（草稿からの差分を含む確定版）

- **env キー**（`ENV_FILE_ALLOWED_KEYS` に追加済み）:
  - `SHARED_MOUNT_HOME_ALIAS`: `0`（既定）/`1`。`1` のとき `SHARED_MOUNT` が必須で、ホストの `$HOME` 配下・`$HOME` 自身でない・HOME 直下の項目が `.` 始まりでない・`..`/`/./`/コロン/制御文字を含まない・存在するディレクトリ、を満たさなければ `guard_fail`。`0`/`1` 以外も `guard_fail`。
  - `AGENTS_DIR`: 未設定なら何もしない。絶対パスか `~/` 始まりで存在するディレクトリ。`pwd -P` で実体解決して export。他の rw マウント（`WORKING_DIR`・`EXTRA_MOUNT`・`SHARED_MOUNT`・`CODEX_DIR`・`~/.claude`）と範囲が重なるときは `guard_warn`（起動は止めない）。
- **export する変数**（override が `:?` で要求。launcher は選ぶときに必ず export し、選ばないときは冒頭で `unset` して環境からの注入を捨てる）:
  - `CLAUDE_SHARED_HOME_PATH=/home/node/<SHARED_MOUNT の $HOME からの相対パス>` → `compose.shared-home.yml`
  - `CLAUDE_SHARED_HOST_PATH=<SHARED_MOUNT のホストの綴り（symlink 未解決・正規化済み）>` → `compose.shared-host.yml`。ホストの `$HOME` が `/home/node` で両者が一致するときは付けない。
  - `SHARED_MOUNT` は `pwd -P` の実体解決値で再 export する。これにより `/shared` の source も実体になる（symlink を `SHARED_MOUNT` に指定していた場合の挙動変更。README に書く）。
  - `AGENTS_DIR=<実体解決値>` → `compose.agents.yml`（target は固定 `/home/node/.agents`）。
- **override の位置**: 3 ファイルとも `resolve_asset_source()` の fixed 群と `ASSET_HASH_TARGETS` に登録済み（草稿）。ランタイムマウントなので機能に `-b` は不要だが、ハッシュ対象に入るため既存イメージでは `guard_asset_drift()` の WARNING が `-b` まで出る。
- **`--check`**: 有効時に `[OK]   共有別名 (ro): /home/node/<rel> / <host path>（/shared は rw）` と `[OK]   AGENTS_DIR: <path> -> /home/node/.agents (ro)` を出す（草稿のまま）。対象リポジトリと `.build-context/` は変更しない。
- **ガードの呼び出し位置**: `check_one_project()` と dispatch の両方で `guard_shared_mount` の直後（草稿のまま）。

## Task 1: launcher の草稿を確定版に合わせる

対象: `claude-container`

- [ ] `guard_shared_home_alias()` から plugin 別名との重なり検査を削除する。削除範囲は `config_base="${CLAUDE_CONFIG_DIR:-$HOME}"` の行から、`plugin_target=$(plugins_alias_target ...)` の `if` ブロックを閉じる `fi` までの 8 行。`local` 宣言から `plugin_target config_base` を外す。
- [ ] 関数直前のコメント（`# 指示ファイルの別名は HOME 配下の明示したディレクトリだけに限定する（#99）。` から始まる 2 行）を次の 5 行に置き換える:
  ```bash
  # SHARED_MOUNT の別名マウント（claude-container#99）。SHARED_MOUNT_HOME_ALIAS=1 のとき、
  # SHARED_MOUNT の実体をコンテナ内の ~（/home/node）配下の同じ相対位置と、ホストと同じ
  # 絶対パスにも :ro で重ねる固定 override を選ぶ。/shared は rw のままなので境界ではない。
  # HOME 直下の隠し項目（.claude・.codex 等）は設定・認証・実行環境のため別名にしない。
  # ホストで使う綴りは symlink 解決前に保存し、/shared の source は実体に解決する。
  ```
- [ ] `guard_agents_dir()` の直前に次の 3 行を足す:
  ```bash
  # エージェント共通のスキル置き場（AGENTS_DIR、通常 ~/.agents）を /home/node/.agents に :ro で
  # 付ける opt-in（claude-container#99）。~/.claude/agents/（Claude Code の subagent 定義、
  # :ro 保護 11 項目の一つ）とは別物。
  ```
- [ ] 検証: `bash -n claude-container` が無出力。`grep -c 'plugins_alias_target' claude-container` が `3`（関数定義・`guard_plugins_alias()` 内・コメント行の合計。草稿の状態では `4`）。

## Task 2: テストを `test-build.sh` に置く

対象: `test-build.sh`、`tests/test-instruction-mounts.sh`（削除）

- [ ] `tests/test-instruction-mounts.sh` の関数 `run_instruction_mount_launcher_tests()` の本体を、`test-build.sh` の `run_plugins_alias_launcher_tests()` の閉じ `}` の直後（`run_base_image_launcher_tests()` の説明コメントより前）に移す。関数の直前に次のコメントを付ける:
  ```bash
  # 指示ファイル・スキルの追加共有（claude-container#99）の検証。launcher が opt-in と値を検証し、
  # compose.shared-home.yml / compose.shared-host.yml / compose.agents.yml を build・run の各呼び出しへ
  # export と一緒に渡すこと、不正値と HOME 外・保護先と重なる値を compose に到達する前に拒否すること。
  # shellcheck disable=SC2016  # bash -c の検証式は親で展開せず、位置引数を子シェル内で評価する
  ```
  草稿の `# shellcheck disable=SC2016,SC2034,SC2154` は使わない（SC2034・SC2154 は `source` 経路で出ていたもの。関数を同じファイルに置けば出ない。出たらその変数の使い方を直す）。
- [ ] 移した関数の末尾（`launcher_sandbox_cleanup` の直前）に次のケースを追加する（`SHARED_MOUNT` の実体解決の回帰確認）:
  ```bash
    ln -s "$home/obsidian-vault" "$home/vault-link"
    run_launcher SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$home/vault-link"
    check "symlink の SHARED_MOUNT は綴りを別名に、実体を /shared の source にする" \
      bash -c '[ "$1" = 0 ] && grep -qxF "CLAUDE_SHARED_HOME_PATH=/home/node/vault-link" "$2/compose-env" && grep -qxF "CLAUDE_SHARED_HOST_PATH=$3/vault-link" "$2/compose-env" && grep -qxF "SHARED_MOUNT=$(cd "$3/obsidian-vault" && pwd -P)" "$2/compose-env"' _ "$rc" "$root" "$home"
  ```
- [ ] `test-build.sh` から次を削除する: `# shellcheck source=tests/test-instruction-mounts.sh` と `source "${SCRIPT_DIR}/tests/test-instruction-mounts.sh"` の 2 行、および `if [[ "${1:-}" == "--instruction-mounts-only" ]]; then ... fi` の 4 行。`run_launcher_tests()` 内の `run_instruction_mount_launcher_tests` 呼び出しは残す。
- [ ] `git rm tests/test-instruction-mounts.sh`。
- [ ] 検証: `./test-build.sh --launcher-only` の末尾が `FAIL=1` で、赤は E7 だけ（Task 4 で緑になる）。`## 指示ファイルとスキルの追加共有（#99）` 配下のケースが全て PASS で、追加した symlink ケースも PASS。

## Task 3: `lint.sh` に override の Compose 検証を足す

対象: `lint.sh`

- [ ] 既存の `${CLAUDE_PLUGINS_HOST_PATH:?}` の空文字検査（`CLAUDE_PLUGINS_HOST_PATH="" \` で始まる `if` ブロック）の直後、`else` の前に次を足す:
  ```bash
    # 指示ファイル・スキルの追加共有 override（claude-container#99）。source と destination は
    # launcher が export するので lint ではダミー値を与える。6 ファイル同時のマージで plugin 別名・
    # IPv6・3 本の別名 volume が消えないことも見る。
    SHARED_MOUNT=/tmp CLAUDE_SHARED_HOME_PATH=/home/node/lint-shared-home \
      podman compose -f compose.yml -f compose.shared-home.yml config >/dev/null || status=1
    SHARED_MOUNT=/tmp CLAUDE_SHARED_HOST_PATH=/tmp/lint-shared-host \
      podman compose -f compose.yml -f compose.shared-host.yml config >/dev/null || status=1
    AGENTS_DIR=/tmp \
      podman compose -f compose.yml -f compose.agents.yml config >/dev/null || status=1
    if merged=$(CLAUDE_PLUGINS_HOST_PATH=/tmp/lint-plugins-alias SHARED_MOUNT=/tmp \
        CLAUDE_SHARED_HOME_PATH=/home/node/lint-shared-home CLAUDE_SHARED_HOST_PATH=/tmp/lint-shared-host AGENTS_DIR=/tmp \
        podman compose -f compose.yml -f compose.ipv6.yml -f compose.plugins-alias.yml \
          -f compose.shared-home.yml -f compose.shared-host.yml -f compose.agents.yml config); then
      for needle in '/tmp/lint-plugins-alias' 'fe80::1' '/home/node/lint-shared-home' '/tmp/lint-shared-host' '/home/node/\.agents'; do
        grep -qE -- "$needle" <<<"$merged" \
          || { echo "ERROR: compose の 6 ファイル同時 config に '$needle' がありません（override のマージで消えています）" >&2; status=1; }
      done
    else
      status=1
    fi
    # ${VAR:?} の fail-closed 検査（#98 の CLAUDE_PLUGINS_HOST_PATH と同じ理由）。
    for pair in compose.shared-home.yml:CLAUDE_SHARED_HOME_PATH compose.shared-host.yml:CLAUDE_SHARED_HOST_PATH compose.agents.yml:AGENTS_DIR; do
      file="${pair%%:*}"
      var="${pair#*:}"
      # shellcheck disable=SC2016 # 意図的にリテラル表示（変数展開ではなく compose 変数名の文字列）
      var_literal='${'"$var"':?}'
      if env -u "$var" SHARED_MOUNT=/tmp podman compose -f compose.yml -f "$file" config >/dev/null 2>&1; then
        printf 'ERROR: %s の %s が未設定を通しています（provider が :? を強制していません）\n' "$file" "$var_literal" >&2
        status=1
      fi
      if env "$var=" SHARED_MOUNT=/tmp podman compose -f compose.yml -f "$file" config >/dev/null 2>&1; then
        printf 'ERROR: %s の %s が空文字を通しています（provider が :? を強制していません）\n' "$file" "$var_literal" >&2
        status=1
      fi
    done
  ```
- [ ] `lint.sh` が自分自身を shellcheck するので、追加分に指摘が出たらその場で直す（上の断片は host で shellcheck 済みで、`var_literal` 行の SC2016 だけが出るため disable コメントを含めてある）。
- [ ] 検証: `./lint.sh` が `lint OK` で rc=0（上の断片は復元した草稿の compose 3 本に対して host で単独実行し status=0 を確認済み）。変異確認として `compose.agents.yml` の `read_only: true` 行を一時的に消しても緑のまま（この lint は `:ro` の有無を見ない。`:ro` は Task 6 の実コンテナ確認で見る）、`target: /home/node/.agents` を `target: /home/node/agents-x` に一時変更すると `'/home/node/\.agents' がありません` で赤になることを確認して戻す。

## Task 4: README

対象: `README.md`

- [ ] 目次: `- [IPv6 を任意で有効にする](#ipv6-を任意で有効にする)` の直後に `- [ホストの指示ファイルとスキルをコンテナ内で解決する](#ホストの指示ファイルとスキルをコンテナ内で解決する)` を足す。
- [ ] 「起動前チェック（`--check`）」節の検査項目の `SHARED_MOUNT`/`GITCONFIG_FILE`/`SECRETS_DIR`/`CODEX_DIR` を `SHARED_MOUNT`/`SHARED_MOUNT_HOME_ALIAS`/`AGENTS_DIR`/`GITCONFIG_FILE`/`SECRETS_DIR`/`CODEX_DIR` にする。
- [ ] 「環境変数」節の表: `SHARED_MOUNT` の行の直後に次の 2 行を足す（E7 はこの表の `| \`KEY\` |` を拾う。行頭の形を崩さない）:
  ```markdown
  | `SHARED_MOUNT_HOME_ALIAS` | `0` | `1` で `SHARED_MOUNT` のディレクトリを、`/shared`（rw）に加えてコンテナ内の `~`（`/home/node`）配下の同じ相対位置と、ホストと同じ絶対パスにも `:ro` で重ねる（後述「ホストの指示ファイルとスキルをコンテナ内で解決する」節）。`SHARED_MOUNT` がホストの `$HOME` 配下で、`$HOME` 直下の項目名が `.` で始まらないことが条件。条件を満たさない値と `0`/`1` 以外の値は起動と `--check` で拒否 |
  | `AGENTS_DIR` | (unset) | Codex 等のエージェント共通のスキル置き場（通常 `~/.agents`）をコンテナ内 `~/.agents` として `:ro` マウントするホスト側パス。絶対パスか `~/` 始まりで指定する。`~/.claude/agents/`（Claude Code の subagent 定義、後述の `:ro` 保護 11 項目の一つ）とは別物 |
  ```
- [ ] 「IPv6 を任意で有効にする」節の末尾（「利用側プロジェクトの設定」の `## ` の直前）に次の節を足す:
  ````markdown
  ## ホストの指示ファイルとスキルをコンテナ内で解決する

  ホストの `~/.claude/CLAUDE.md` はコンテナへ `:ro` で共有される（後述「ホストの Claude Code 設定の読み取り専用保護」）。その中で `@~/obsidian-vault/knowledge/索引.md` のように `~` 起点で別のディレクトリを参照していると、コンテナ内の `~` は `/home/node` なので参照先が無く、指示が展開されない。同様に Codex 等が共通で読む `~/.agents/skills/` もコンテナ内には無い。グローバル指示をホストとコンテナで二重管理せず、参照先をコンテナ側で解決するための opt-in が 2 つある（[`#99`](https://github.com/jj1xgo/claude-container/issues/99)）。

  ```bash
  # .claude-container.d/env
  SHARED_MOUNT=~/obsidian-vault
  SHARED_MOUNT_HOME_ALIAS=1
  AGENTS_DIR=~/.agents
  ```

  - `SHARED_MOUNT_HOME_ALIAS=1`: `SHARED_MOUNT` の実体が、従来の `/shared`（rw）に加えて、コンテナ内の `~` 配下の同じ相対位置（例 `/home/node/obsidian-vault`）と、ホストと同じ絶対パス（例 `/home/<host user>/obsidian-vault`）にも `:ro` で見える。`@~/...` の参照は前者で、ホストの絶対パスを書いた参照は後者で解決する。ホストの `$HOME` が `/home/node` なら両者は同じなので別名は 1 本になる。条件は `SHARED_MOUNT` がホストの `$HOME` 配下（`$HOME` 自身は不可）で、`$HOME` 直下の項目名が `.` で始まらないこと（`~/.claude`・`~/.codex` 等の設定・認証領域は別名にしない）。`..`・コロン・制御文字を含む値、`0`/`1` 以外の値は起動と `--check` で拒否する。`SHARED_MOUNT` にシンボリックリンクを指定した場合、別名の綴りはリンクのままで、`/shared` を含む 3 箇所の source はリンク先の実体になる。
  - `AGENTS_DIR`: 指定したディレクトリをコンテナ内 `/home/node/.agents` に `:ro` で付ける。`~/.claude/agents/` とは別物。指定先が `EXTRA_MOUNT`・`SHARED_MOUNT`・`CODEX_DIR`・対象プロジェクト・`~/.claude` の範囲と重なると、その rw マウント経由で書けるため WARNING を出す（起動は止めない）。

  どちらもランタイムの bind mount なので `-b` なしで効くが、override ファイルが境界アセットのハッシュ対象に入るため、既存イメージでは `-b` するまで起動時にドリフトの WARNING が出る。**別名の `:ro` は境界ではない**: 同じ実体が `/shared` に rw であるため、コンテナ内のコードは `/shared` 経由で書ける。`:ro` は「書き込みは `/shared` 経由で行う」運用の目印で、別名経由の書き込みが Read-only file system で失敗するだけに留まる。`AGENTS_DIR` は `/shared` のような rw の経路を持たないので、指定先が上記 WARNING の範囲と重ならなければコンテナ内から書けない。`--check` は有効時に `[OK]   共有別名 (ro): ...` と `[OK]   AGENTS_DIR: ...` を表示する。
  ````
- [ ] 「アーキテクチャ」節の `compose.yml` 項: `[\`#98\`](...)）。` の直後（`CODEX_DIR` の文の前）に次の 1 文を足す: `` `SHARED_MOUNT_HOME_ALIAS=1` のときは `compose.shared-home.yml`（`~` 配下の同じ相対位置）と `compose.shared-host.yml`（ホストと同じ絶対パス）で `SHARED_MOUNT` の実体を `:ro` で重ね、`AGENTS_DIR` のときは `compose.agents.yml` で `/home/node/.agents` に `:ro` で付ける（いずれも `claude-container` の `guard_shared_home_alias()`・`guard_agents_dir()` が値を検証したときだけ追加する固定 override。前述「ホストの指示ファイルとスキルをコンテナ内で解決する」節。[`#99`](https://github.com/jj1xgo/claude-container/issues/99)）。 ``
- [ ] 「セキュリティモデル」節の `起動時の可視化を実際に確認したい場合は` の文: `EXTRA_MOUNT`/`SHARED_MOUNT`/`SECRETS_DIR`/`GITCONFIG_FILE`/`CODEX_DIR`/`CLAUDE_CONFIG_DIR` を `EXTRA_MOUNT`/`SHARED_MOUNT`/`SHARED_MOUNT_HOME_ALIAS`/`AGENTS_DIR`/`SECRETS_DIR`/`GITCONFIG_FILE`/`CODEX_DIR`/`CLAUDE_CONFIG_DIR` にする。
- [ ] 「変更後の確認」節: plugin 別名の段落（`plugin の別名マウント（` で始まる）の直後に次の段落を足す:
  ```markdown
  `SHARED_MOUNT` の別名マウントと `AGENTS_DIR`（`compose.shared-home.yml`・`compose.shared-host.yml`・`compose.agents.yml`・`guard_shared_home_alias()`・`guard_agents_dir()`）の変更時も `./test-build.sh --launcher-only` を実行する（opt-in の配線、不正値の拒否、`--check` の不変、symlink の実体解決を含む）。`lint.sh` は override 単独と 6 ファイル同時の Compose 設定、`${VAR:?}` の fail-closed を検証する。実際に別名が読めて別名経由で書けないこと、`/shared` が rw のままであることは `-b` で起動したコンテナ内で確認する（前述「ホストの指示ファイルとスキルをコンテナ内で解決する」節）。
  ```
- [ ] 検証: `./test-build.sh --launcher-only` の末尾が `FAIL=0` で rc=0（PASS 件数は実測値を PR に書く。固定値を期待しない）。`grep -c 'SHARED_MOUNT_HOME_ALIAS' README.md` が 6 以上。

## Task 5: `.claude/CLAUDE.md`（Fable がマージ時に ops リポジトリで行う。Codex の範囲外）

- [ ] `compose.yml` 不変条件の「固定 Compose override の選択（`compose.ipv6.yml`・`compose.plugins-alias.yml`）」に 3 ファイルと `guard_shared_home_alias()`・`guard_agents_dir()` を足す。
- [ ] `claude-container` 不変条件に 1 項目: `SHARED_MOUNT_HOME_ALIAS` の別名は `:ro` だが境界ではない（`/shared` が rw）。`AGENTS_DIR` の rw 重なり検査は `guard_warn` に留める。両ガードは `CLAUDE_SHARED_HOME_PATH`・`CLAUDE_SHARED_HOST_PATH` を冒頭で `unset` してから export する構成を崩さない（環境からの注入で任意の destination にマウントさせない）。

## Task 6: 検証と PR

- [ ] `./lint.sh` → `lint OK`、rc=0。
- [ ] `./test-build.sh --launcher-only` → 末尾 `FAIL=0`、rc=0。PASS の実測値を PR 本文に書く。
- [ ] `--check` の実測: `mktemp -d` で作ったプロジェクトに `.claude-container.d/env` を `SHARED_MOUNT=~/obsidian-vault`・`SHARED_MOUNT_HOME_ALIAS=1`・`AGENTS_DIR=~/.agents` で置き、`./claude-container --check <dir>` の出力に `[OK]   共有別名 (ro): /home/node/obsidian-vault / /home/<user>/obsidian-vault（/shared は rw）` と `[OK]   AGENTS_DIR: /home/<user>/.agents -> /home/node/.agents (ro)` が出る。`SHARED_MOUNT_HOME_ALIAS=2` に変えると `ERROR: SHARED_MOUNT_HOME_ALIAS は 0 または 1 を指定してください。` で rc≠0。終わったら `mktemp` のディレクトリを消す（起動台帳 `~/.local/state/claude-container/projects` は `--check` では増えない）。ホストに `~/.agents` が無ければ `mkdir -p ~/.agents/skills` で作ってよい（空ディレクトリ）。
- [ ] コミットは Task ごとでなく次の 3 つにまとめる: (1) Task 1（launcher）、(2) Task 2〜3（テストと lint）、(3) Task 4（README）。復元コミット `wip:` はそのまま履歴に残す（squash しない。草稿の出自を残す）。
- [ ] PR 作成前に `claude-review` skill で Opus のレビューを受け、should-fix 以上を直してから `gh pr create`（ベース `main`、タイトル `feat: SHARED_MOUNT の ~ 別名と AGENTS_DIR で指示ファイルとスキルをコンテナ内で解決する（#99）`）。本文に `Closes #99`、検証コマンドごとの実出力（Expected との照合）、未実行項目を書く。Draft にしない。
- [ ] **実コンテナでの確認は Codex の範囲外**（Fable がレビュー時に host で行う）: 利用側プロジェクトで `-b` 起動したコンテナ内で `ls ~/obsidian-vault/knowledge/索引.md`、`touch ~/obsidian-vault/x`（Read-only file system）、`touch /shared/x && rm /shared/x`（成功）、`ls ~/.agents/skills/claude-review`、`ls /home/<host user>/obsidian-vault`、`~/.agents` への `touch` が失敗、env を外して起動すると `~/obsidian-vault`・`~/.agents` が無いこと。`@~/obsidian-vault/knowledge/索引.md` が実際に展開されるかはコンテナ内の Claude セッションで `/memory` またはシステムプロンプトの表示で持ち主が確認する。

## 利用側への影響

- 新しい env キー 2 つの追加で、未設定なら従来どおり（既定 `0`・unset）。**MINOR**（v9.4.0 候補）。
- 機能に `-b` は不要。ただし新しい override 3 本がハッシュ対象に入るため、既存イメージでは `-b` するまで `guard_asset_drift()` の WARNING が出る。
- `SHARED_MOUNT` にシンボリックリンクを指定していて `SHARED_MOUNT_HOME_ALIAS=1` を付けた場合だけ、`/shared` の source が実体パスになる（未設定なら変わらない）。

## 五つの問い

- **敵と信頼**: env は運用者が書く信頼入力（#29）。ただし値が境界（マウント先）を動かすので、destination は launcher が算出して export し、環境からの `CLAUDE_SHARED_*_PATH` は冒頭で捨てる。
- **境界を横切る物**: `SHARED_MOUNT` の実体（既に `/shared` で rw）と `AGENTS_DIR`（新規、`:ro`）。前者の別名は露出を増やさない。後者はホストのスキルがコンテナ内の Codex・Claude に読まれる経路で、書き戻し経路は作らない。
- **機構か文書か**: 別名の `:ro` は機構だが境界ではない（文書で明記）。`AGENTS_DIR` の rw 重なりは `guard_warn`（文書＋警告）。不正値の拒否は `guard_fail`（機構）。
- **fail-closed / open の理由**: opt-in の値が不正なら止める（黙って別名無しで起動すると指示が読めないまま作業が進む）。`AGENTS_DIR` の rw 重なりは止めない（`EXTRA_MOUNT=$HOME` のような構成で必ず重なり、利用者が意図している可能性が高い）。
- **隣を見たか**: #98（plugin 別名）と同型で、入れ子順序・`:?` の provider 依存・`ASSET_HASH` の両経路・`--check` の共用ガードを同じ流儀で扱う。`~/.claude/agents/` との名前の混同は README で切り分けた。

---

実装: Codex。理由: host の checkout で完結し、草稿が復元済みで残る手順は逐語で確定している（判定基準 4）。実コンテナ確認はレビュー時に Fable が host で行う。

`/goal` に渡す文面:

```
docs/superpowers/plans/2026-09-14-shared-instruction-paths-99.md を上から順に実施する。

前提: origin の既存ブランチ fix/shared-instruction-paths-99 を checkout する（計画ファイルと、Codex 草稿の復元コミット wip: が載っている。新たに切らない）。ローカルに同名の古いブランチ（6190e51）があれば origin の先頭に合わせる。

既決事項（蒸し返し不要）: 機構は #98 と同型の固定 Compose override 3 本。opt-in は SHARED_MOUNT_HOME_ALIAS=1 と AGENTS_DIR。別名は :ro だが境界ではない。plugin 別名との重なり検査は削除する。テストは test-build.sh 内の関数にし tests/test-instruction-mounts.sh は消す。ガードの呼び出し位置は草稿のまま。

制約: 編集するのは claude-container・test-build.sh・lint.sh・README.md と、削除する tests/test-instruction-mounts.sh だけ。compose.*.yml 3 本と計画ファイル自身、.claude/ 配下は変更しない。検証用の一時ファイルは mktemp の範囲で作って消す。Expected と実結果がずれたら修正せず止めて報告する。

手順: Task 1 → Task 2 → Task 3 → Task 4 → Task 6（lint.sh、test-build.sh --launcher-only、--check の実測、3 コミット、claude-review、gh pr create）。Task 5 と「実コンテナでの確認」は範囲外。

成果物: PR の URL と、検証コマンドごとの実出力（Expected との照合）、未実行項目の一覧。
```

- sandbox: `workspace-write`（5 ファイルの編集・削除・コミット。テストは mktemp・`.build-context/`・`.claude/test-results/` に書く。`--check` の実測はホストの `~/.agents` を読む）。
- ネットワーク: 必要（`git push`・`gh pr create`・`claude-review`）。
