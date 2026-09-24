# ホストの Codex plugin キャッシュをコンテナへ :ro で共有する 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**状態**: 計画（未レビュー）。2026-09-24 起草。

**Goal:** ホストの Codex で install した plugin（例: superpowers）を、ホストの `~/.claude/plugins` と Claude Code の関係と同じく、コンテナ内の Codex からも読み取り専用で使えるようにする。

**Architecture:** 新しい opt-in キー `CODEX_HOST_PLUGINS=1`（`.c3c/env`）で、ホストの `~/.codex/plugins/cache` を専用 `CODEX_DIR`（コンテナ内 `/home/node/.codex`、rw）の内側 `/home/node/.codex/plugins/cache` へ `:ro` で重ねる固定 Compose override `compose.codex-plugins.yml` を選ぶ。plugin の有効化はコンテナ用 `CODEX_DIR/config.toml` の user 層で利用者が行い、launcher は設定を書かない。更新はホストでのみ行う（Claude の `plugins/` と同じ）。

**Tech Stack:** bash（`c3c`・`lint.sh`・`test-build.sh`）、Podman Compose（long syntax の bind）、Codex CLI 0.156.x。

**Spec:** 本計画の「背景と実測」節（独立の仕様書は作らない）。

## 背景と実測

- 現状: コンテナの Claude は `~/.claude/plugins` を `:ro` で共有しているので、ホストで入れた plugin がそのまま使える（`compose.yml` の `:ro` 12 項目、`compose.plugins-alias.yml`）。コンテナの Codex は専用 `CODEX_DIR` を使い（`docs/development-invariants.md` の `${CODEX_DIR:-/dev/null}:/home/node/.codex` の項、SECURITY-CLAIMS C-4）、ホストの `~/.codex` の plugin は見えない。
- ホストの `~/.codex` を共有しない理由（コンテナが `config.toml` の notify 等を書くとホストで任意コマンド実行）は plugin キャッシュにも当てはまる。ホストの Codex はキャッシュ内の skill・hook を読むため、共有するなら `:ro` 必須。
- 実測（2026-09-24、ホスト、codex-cli 0.156.1、superpowers 6.4.1）:
  1. 一時 `CODEX_HOME` に `plugins/cache/superpowers-dev/superpowers/6.4.1` を複製して `chmod -R a-w` し、`config.toml` に `[plugins."superpowers@superpowers-dev"]` `enabled = true` だけを書いた状態で `codex debug prompt-input hi` → superpowers の 15 skill がモデル入力に載った。skill root は `$CODEX_HOME/plugins/cache/...` で、ホストの絶対パスは記録されない（Claude の `compose.plugins-alias.yml` 相当の別名は不要）。
  2. 同じ状態で `config.toml` を空にすると 0 件（マウントだけでは plugin は有効にならない。user 層での有効化が必要）。`[marketplaces.*]` の定義と marketplace の clone は不要。
  3. 実行中に `plugins/` 配下への書き込みは発生しなかった（`find -newer` で確認）。
  4. `codex plugin marketplace upgrade superpowers-dev` は `plugins/.marketplace-plugin-source-staging` を作れず `Permission denied (os error 13)` で exit 1、キャッシュは不変。
  5. 未確認: 対話起動（TUI・app-server）が起動時に自動で marketplace 更新を試みるか、その失敗が起動を妨げるか。→ Task 4 の実機受入で確認する。
- superpowers の Codex 版 manifest（`.codex-plugin/plugin.json`）は `"skills": "./skills/"`、`"hooks": {}` で、起動時に実行されるフックを持たない。ただし本機構は plugin 一般を対象にするので、hook を持つ plugin も共有されうる（有効化は利用者の user 層設定、hook の信頼確認は Codex の native 機能に委ねる。C-3 と同じ線引き）。

## Global Constraints

- 新規の境界機構は既存パターン（固定 override・`guard_*`・`validate_claude_config_ro_path()`・`${VAR:?}`）の組み合わせで作り、独自の新方式を足さない（root `AGENTS.md`）。
- `CODEX_HOST_PLUGINS` の値は `''`/`0`/`1` だけを受け付け、それ以外は起動と `--check` で拒否する（`SHARED_MOUNT_HOME_ALIAS`・`CLAUDE_CONTAINER_IPV6` と同じ）。
- source は launcher の `$HOME/.codex/plugins/cache` に固定する。任意パスを受け付けるキーは作らない（`.c3c/env` の `HOME` は許可リスト外で差し替えられない）。
- マウントは `:ro` 必須。`create_host_path: false`。マウント先（`$CODEX_DIR/plugins`・`$CODEX_DIR/plugins/cache`）は launcher がユーザー権限で作り、symlink・型不一致は拒否する（podman にサブ uid 所有の残骸を作らせない、rw 親の中の symlink でマウント先をずらさせない）。
- `--check` は何も作らない（書き込みをしない契約）。
- launcher は `CODEX_DIR/config.toml` を読まない・書かない。plugin の有効化は利用者が行う。
- 表記は日本語。`./lint.sh` 終了コード 0・警告ゼロ。

## Review Focus

1. `CODEX_DIR/plugins` か `CODEX_DIR/plugins/cache` が symlink（前回セッションが rw の `CODEX_DIR` へ植えたもの）→ 起動と `--check` で ERROR、compose に進まない（Task 1 のテスト「symlink のマウント先を拒否」）。
2. Codex の対話起動が `:ro` のキャッシュに対して自動更新を試みる → 起動は失敗せず、skill は使える（Task 4 の受入 A3）。失敗するなら実装を止めて計画へ戻す。
3. ホストに `~/.codex/plugins/cache` が無い（ホストで Codex plugin を使っていない）のに `CODEX_HOST_PLUGINS=1` → 分かる ERROR で止まり、ホストに何も作らない（Task 1 のテスト）。
4. `--check` に `CODEX_HOST_PLUGINS=1` → マウント先を作らず、`[OK]` 行を出す（Task 1 のスナップショット比較）。
5. `CODEX_DIR/plugins/cache` にコンテナ側で入れた plugin が既にある → マウント中は隠れることを WARNING で示し、起動は続ける（Task 1 のテスト）。

---

### Task 1: launcher の opt-in・ガード・override と launcher テスト

**Files:**
- Create: `compose.codex-plugins.yml`
- Modify: `c3c`（`ENV_FILE_ALLOWED_KEYS`、`guard_env_boundary_keys()` のキー一覧、新関数 `guard_codex_host_plugins()`・`prepare_codex_host_plugins()`、`check_one_project()` と通常起動の呼出し、`resolve_asset_source()` の fixed 一覧、`ASSET_HASH_TARGETS`、36 行目付近の override 一覧コメント）
- Modify: `test-build.sh`（新関数 `run_codex_host_plugins_launcher_tests()` とその登録、1363 行目付近の runner コピー一覧）
- Modify: `README.md`「環境変数」節の表（E7 が許可リストとの一致を検査するため、このタスクで 1 行足す。説明文の本体は Task 3）

**Interfaces:**
- Produces: env キー `CODEX_HOST_PLUGINS`、内部 export `C3C_CODEX_PLUGINS_SOURCE`（実体解決済みの source の絶対パス）、グローバル `CODEX_HOST_PLUGINS_READY`（`0`/`1`）、override `compose.codex-plugins.yml`、`--check` の表示 `[OK]   Codex plugin 共有 (ro): <source> -> /home/node/.codex/plugins/cache`

- [ ] **Step 1: 既存アセット名の全参照を数える**

`docs/development-invariants.md` 22 行目の規則に従い、新 override の登録先を漏らさないよう既存の override 名で参照箇所を数える。

Run: `grep -rn 'compose\.agents\.yml' --include='*' . | grep -v '^./docs/superpowers/' | grep -v '^./\.git/'`
Expected: `c3c`（コメント 36 行目付近・`guard_agents_dir()`・`resolve_asset_source()`・`ASSET_HASH_TARGETS`）、`test-build.sh`（runner コピー一覧、launcher テスト、実 podman 検査）、`lint.sh`、`README.md`、`docs/development-invariants.md` が出る。以下の各 Step と Task 2・3 でこのすべてに `compose.codex-plugins.yml` を対応させる。一覧に上記以外の箇所があれば、同じ扱いで追加する。

- [ ] **Step 2: 失敗するランチャーテストを書く**

`test-build.sh` の `run_codex_dir_launcher_tests()` の直後に次の関数を追加し、`run_launcher_tests` 内の `run_codex_dir_launcher_tests` の次の行に `run_codex_host_plugins_launcher_tests` を登録する。

```bash
# CODEX_HOST_PLUGINS（ホストの Codex plugin キャッシュを CODEX_DIR の内側へ :ro で重ねる opt-in）の検証。
# opt-in の配線（build と run の両方）、不正値・前提欠落・symlink のマウント先を compose 前に拒否すること、
# --check が何も作らないこと、既存内容が隠れる WARNING を見る。
# shellcheck disable=SC2016  # bash -c の検証式は親で展開せず、位置引数を子シェル内で評価する
run_codex_host_plugins_launcher_tests() {
  local root bin home proj out rc before_ctx value src_real
  launcher_sandbox_init
  log "## ホストの Codex plugin キャッシュ共有（CODEX_HOST_PLUGINS）"
  mkdir -p "$home/.codex/plugins/cache/mk/p/1.0" "$home/.codex-container" "$proj/.claude-container.d" "$root/outside"
  chmod 700 "$home/.codex-container"
  src_real=$(cd "$home/.codex/plugins/cache" && pwd -P)

  run_launcher CODEX_DIR="$home/.codex-container" C3C_CODEX_PLUGINS_SOURCE=/tmp/injected
  check "未設定なら override を選ばず、注入された内部変数も破棄する" \
    bash -c '[ "$1" = 0 ] && ! grep -q "compose\.codex-plugins" "$2/compose-args" && ! grep -q "^C3C_CODEX_PLUGINS_SOURCE=" "$2/compose-env" && [ ! -e "$3/.codex-container/plugins" ]' _ "$rc" "$root" "$home"

  printf 'CODEX_DIR=~/.codex-container\nCODEX_HOST_PLUGINS=1\n' > "$proj/.claude-container.d/env"
  local snapshot_ok=1
  snapshot_check_targets > "$root/before" 2>> "$LOG_FILE" || snapshot_ok=0
  run_launcher_check
  snapshot_check_targets > "$root/after" 2>> "$LOG_FILE" || snapshot_ok=0
  check "--check は共有を診断し、マウント先を作らない" \
    bash -c '[ "$1" -eq 1 ] && [ "$2" = 0 ] && [[ "$3" == *"[OK]   Codex plugin 共有 (ro): $5 -> /home/node/.codex/plugins/cache"* ]] && cmp -s "$4/before" "$4/after"' _ "$snapshot_ok" "$rc" "$out" "$root" "$src_real"

  run_launcher
  check "env の opt-in で実体解決した source と override を渡し、マウント先を作る" \
    bash -c '[ "$1" = 0 ] && grep -qxF "C3C_CODEX_PLUGINS_SOURCE=$3" "$2/compose-env" && grep -qxF "$4/compose.codex-plugins.yml" "$2/compose-args" && [ -d "$5/.codex-container/plugins/cache" ] && [ ! -L "$5/.codex-container/plugins/cache" ]' _ "$rc" "$root" "$src_real" "$SCRIPT_DIR" "$home"
  printf '%s\n' "$out" >> "$LOG_FILE"

  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" claude -b "$proj" 2>&1) && rc=0 || rc=$?
  check "build と run の両方に override が渡る" \
    bash -c '[ "$1" = 0 ] && [ "$(cat "$2/compose-calls")" = 2 ] && grep -qxF "$3/compose.codex-plugins.yml" "$2/compose-args.1" && grep -qxF "$3/compose.codex-plugins.yml" "$2/compose-args.2"' _ "$rc" "$root" "$SCRIPT_DIR"
  : > "$proj/.claude-container.d/env"

  touch "$home/.codex-container/plugins/cache/container-installed"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "マウント先に既存内容があれば隠れることを WARNING で示し、起動は続ける" \
    bash -c '[ "$1" = 0 ] && [[ "$2" == *"WARNING:"*"plugins/cache"* ]]' _ "$rc" "$out"
  rm -f "$home/.codex-container/plugins/cache/container-installed"

  for value in 2 true '1 ' yes; do
    run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS="$value"
    check "不正値 '$value' を起動時に拒否する" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"CODEX_HOST_PLUGINS"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS="$value"
    check "不正値 '$value' を --check も拒否する" [ "$rc" -ne 0 ]
  done

  run_launcher CODEX_HOST_PLUGINS=1
  check "CODEX_DIR 未設定の opt-in を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"CODEX_DIR"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"

  mv "$home/.codex/plugins/cache" "$home/.codex/plugins/cache.off"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "ホストに plugin キャッシュが無ければ拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*".codex/plugins/cache"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "--check もキャッシュ欠落を拒否する" [ "$rc" -ne 0 ]
  mv "$home/.codex/plugins/cache.off" "$home/.codex/plugins/cache"

  rm -rf "$home/.codex-container/plugins"
  ln -s "$root/outside" "$home/.codex-container/plugins"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "symlink のマウント先（plugins）を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"symlink"* ]] && [ ! -e "$3/compose-env" ] && [ -z "$(ls -A "$3/outside")" ]' _ "$rc" "$out" "$root"
  rm -f "$home/.codex-container/plugins"
  mkdir -p "$home/.codex-container/plugins"
  ln -s "$root/outside" "$home/.codex-container/plugins/cache"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "symlink のマウント先（plugins/cache）を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"symlink"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "--check も symlink のマウント先を拒否する" [ "$rc" -ne 0 ]
  rm -f "$home/.codex-container/plugins/cache"
  : > "$home/.codex-container/plugins/cache"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "ファイルのマウント先を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  rm -f "$home/.codex-container/plugins/cache"

  for value in "$home/.codex/plugins/cache" "$home/.codex/plugins"; do
    run_launcher CODEX_DIR="$value" CODEX_HOST_PLUGINS=1
    check "source と重なる CODEX_DIR を拒否する: $value" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"重なり"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  done

  launcher_sandbox_cleanup
}
```

注: `launcher_sandbox_init`・`launcher_sandbox_cleanup`・`snapshot_check_targets`・`check`・`log`・`run_launcher`・`run_launcher_check` は既存（`run_instruction_mount_launcher_tests()` と同じ使い方）。`run_launcher` は `c3c claude` で起動するが、CODEX_DIR の mount は agent によらず compose.yml にあるので、この opt-in も agent によらず効く（Claude セッションからの `codex exec` でも使える）。

- [ ] **Step 3: テストが失敗することを確かめる**

Run: `TMPDIR=/tmp ./test-build.sh --launcher-only 2>&1 | grep -E 'FAIL|PASS:|結果' | head -40`
Expected: 新関数の check の大半が `[FAIL]`（未実装のため。未設定ケースと「CODEX_DIR 未設定」の一部は偶然 PASS しうる）。既存テストは PASS のまま。README の E7 は、許可リストをまだ変えていないので PASS のまま。

- [ ] **Step 4: override ファイルを作る**

`compose.codex-plugins.yml`:

```yaml
# launcher が guard_codex_host_plugins() の条件（CODEX_HOST_PLUGINS=1）を満たすときだけ追加する固定設定。
# ホストの Codex が install した plugin キャッシュ（~/.codex/plugins/cache）を、専用 CODEX_DIR
# （コンテナ内 /home/node/.codex、rw）の内側へ :ro で重ねる。ホストの Codex はこのキャッシュの
# skill・hook を読み込むため、コンテナから書けるとホストで任意の指示・コマンドを読ませる経路になる
# （compose.yml の ~/.claude/plugins の :ro と同じ理由）。plugin の有効化は CODEX_DIR/config.toml の
# user 層で利用者が行い、このマウントだけでは何も有効にならない。
# source は launcher が実体へ解決して export する。マウント先は launcher がユーザー権限で作る
# （create_host_path: false。無いと podman がサブ uid 所有の実体を作って残骸になる）。
# ${VAR:?} は export 漏れを config 段階で失敗させるための保険（compose.agents.yml と同じ）。
services:
  claude-auth-workspace:
    volumes:
      - type: bind
        source: ${C3C_CODEX_PLUGINS_SOURCE:?launcher が export する}
        target: /home/node/.codex/plugins/cache
        read_only: true
        bind:
          create_host_path: false
```

- [ ] **Step 5: 許可リストと境界キー一覧に足す**

`c3c` の `ENV_FILE_ALLOWED_KEYS` の `CODEX_DIR` の次の行に `CODEX_HOST_PLUGINS` を追加する。`guard_env_boundary_keys()` の `for key in ... CODEX_DIR CLAUDE_CONFIG_DIR; do` を `for key in ... CODEX_DIR CODEX_HOST_PLUGINS CLAUDE_CONFIG_DIR; do` にする。

`README.md`「環境変数」節の表で `CODEX_DIR` の行の直後に 1 行追加する:

```markdown
| `CODEX_HOST_PLUGINS` | `0` | `1` でホストの `~/.codex/plugins/cache`（ホストの Codex が install した plugin）を、`CODEX_DIR` の内側（コンテナ内 `~/.codex/plugins/cache`）へ `:ro` で重ねる（後述「ホストの Codex plugin を使う」節）。`CODEX_DIR` の設定と、ホストにキャッシュが実在することが条件。`0`/`1` 以外の値は起動と `--check` で拒否 |
```

- [ ] **Step 6: ガードと準備の関数を書く**

`c3c` の `guard_agents_dir()` の直後に追加する:

```bash
# ホストの Codex plugin キャッシュ（$HOME/.codex/plugins/cache）を、専用 CODEX_DIR（/home/node/.codex、rw）の
# 内側 /home/node/.codex/plugins/cache へ :ro で重ねる opt-in（CODEX_HOST_PLUGINS=1）。ホストの Codex は
# キャッシュの skill・hook を読むので :ro 必須（~/.claude/plugins と同じ理由）。source は $HOME に固定し、
# 任意パスは受け付けない。plugin の有効化は CODEX_DIR/config.toml の user 層で利用者が行う（launcher は読まない・
# 書かない）。ここでは検証と override の選択だけを行い、マウント先の作成は prepare_codex_host_plugins() が
# Claude の placeholder と同じ位置で行う（--check は何も作らない）。マウント先は rw の CODEX_DIR の中にあるため、
# symlink と型不一致を validate_claude_config_ro_path() で拒否する（植えられた symlink でマウント先をずらさせない）。
guard_codex_host_plugins() {
  unset C3C_CODEX_PLUGINS_SOURCE
  CODEX_HOST_PLUGINS_READY=0
  case "${CODEX_HOST_PLUGINS:-0}" in
    ''|0) return 0 ;;
    1) ;;
    *) guard_fail "ERROR: CODEX_HOST_PLUGINS は 0 または 1 を指定してください。起動を中止します。" || return 1; return 1 ;;
  esac
  if [[ -z "${CODEX_DIR:-}" ]]; then
    guard_fail "ERROR: CODEX_HOST_PLUGINS=1 には CODEX_DIR が必要です（plugin キャッシュは CODEX_DIR の内側へ重ねます）。起動を中止します。" || return 1
    return 1
  fi
  local source="$HOME/.codex/plugins/cache" source_real codex_real path
  if [[ ! -d "$source" ]] || ! source_real=$(CDPATH='' cd -- "$source" >/dev/null 2>&1 && pwd -P); then
    guard_fail "ERROR: CODEX_HOST_PLUGINS=1 ですが、ホストの $source がディレクトリとして見つかりません（ホストの Codex で plugin を install してから有効にしてください）。起動を中止します。" || return 1
    return 1
  fi
  if ! codex_real=$(CDPATH='' cd -- "$CODEX_DIR" >/dev/null 2>&1 && pwd -P) ||
     instruction_paths_overlap "$source_real" "$codex_real"; then
    guard_fail "ERROR: CODEX_HOST_PLUGINS=1 の source（$source_real）と CODEX_DIR（$CODEX_DIR）に重なりがあるか、CODEX_DIR を解決できません。起動を中止します。" || return 1
    return 1
  fi
  for path in "$codex_real/plugins" "$codex_real/plugins/cache"; do
    validate_claude_config_ro_path "$path" dir || return 1
  done
  if [[ -d "$codex_real/plugins/cache" && -n "$(ls -A -- "$codex_real/plugins/cache" 2>/dev/null)" ]]; then
    guard_warn "WARNING: $codex_real/plugins/cache に既存の内容があります。CODEX_HOST_PLUGINS=1 の間はホストのキャッシュで隠れ、コンテナ内からは見えません。"
  fi
  export C3C_CODEX_PLUGINS_SOURCE="$source_real"
  CODEX_HOST_PLUGINS_READY=1
  COMPOSE_OVERRIDE_ARGS+=(-f "$RUN_DIR/compose.codex-plugins.yml")
  [[ "${CHECK_MODE:-0}" == 1 ]] && echo "[OK]   Codex plugin 共有 (ro): $source_real -> /home/node/.codex/plugins/cache"
  return 0
}

# guard_codex_host_plugins() が選んだマウント先をユーザー権限で作る。--check では何もしない。
# 作成後にもう一度型と symlink を検査する（検査と作成の間に置き換えられた場合を拒否する。
# 並行変更の完全な排除は prepare_claude_config_ro() と同じく行わない）。
prepare_codex_host_plugins() {
  [[ "${CODEX_HOST_PLUGINS_READY:-0}" == 1 ]] || return 0
  [[ "${CHECK_MODE:-0}" == 1 ]] && return 0
  local path
  if ! mkdir -p -- "$CODEX_DIR/plugins/cache"; then
    guard_fail "ERROR: $CODEX_DIR/plugins/cache を作れません。起動を中止します。" || return 1
    return 1
  fi
  for path in "$CODEX_DIR/plugins" "$CODEX_DIR/plugins/cache"; do
    validate_claude_config_ro_path "$path" dir || return 1
  done
  return 0
}
```

注: `validate_claude_config_ro_path` の ERROR 文言は「読み取り専用保護」を含み汎用に使える（symlink は「symlink です」を含む。テストはこれを見る）。`instruction_paths_overlap` は既存。`guard_fail` は通常起動では exit する。

- [ ] **Step 7: 呼出しを足す**

`check_one_project()` の `guard_agents_dir || true` の次の行に `guard_codex_host_plugins || true` を追加する。通常起動の `guard_agents_dir` の次の行に `guard_codex_host_plugins` を追加する。通常起動の `guard_plugins_alias`（`prepare_claude_config_ro` の直後）の次の行に `prepare_codex_host_plugins` を追加する。

- [ ] **Step 8: アセット登録**

`c3c` の `resolve_asset_source()` の fixed の `case` に `| compose.codex-plugins.yml` を `compose.agents.yml` の後へ足す。`ASSET_HASH_TARGETS` の `compose.agents.yml` の次の行に `compose.codex-plugins.yml` を足す。36 行目付近のコメントの override 一覧に `compose.codex-plugins.yml` を、37 行目付近の `guard_*` 一覧に `guard_codex_host_plugins()` を足す。`test-build.sh` の runner コピー一覧（`cp -- "${SCRIPT_DIR}/"{c3c,...,compose.agents.yml,...}`）に `compose.codex-plugins.yml` を `compose.agents.yml` の次へ足す。

- [ ] **Step 9: テストが通ることを確かめる**

Run: `./lint.sh && TMPDIR=/tmp ./test-build.sh --launcher-only 2>&1 | tail -5`
Expected: lint 終了コード 0・警告ゼロ（Task 2 の lint 追加前なので、compose 検査は既存分のみ）。launcher-only は FAIL 0。E7（許可リストと README 表の一致）も PASS。

- [ ] **Step 10: Commit**

```bash
git add c3c compose.codex-plugins.yml test-build.sh README.md
git commit -m "feat: CODEX_HOST_PLUGINS でホストの Codex plugin キャッシュを CODEX_DIR の内側へ :ro で重ねる"
```

### Task 2: Compose 設定の lint と実 podman の読み取り専用検査

**Files:**
- Modify: `lint.sh`（compose 検査の節、200〜260 行目付近）
- Modify: `test-build.sh`（`SHARED_ALIAS_PROBE` の後に `CODEX_PLUGINS_PROBE`、`run_config_ro_tests()` に実 podman の check）

**Interfaces:**
- Consumes: Task 1 の `compose.codex-plugins.yml`（`C3C_CODEX_PLUGINS_SOURCE`、target `/home/node/.codex/plugins/cache`）

- [ ] **Step 1: lint に override の検査を足す**

`lint.sh` の `AGENTS_DIR=/tmp podman compose -f compose.yml -f compose.agents.yml config >/dev/null || status=1` の直後に:

```bash
  # ホストの Codex plugin キャッシュ共有。target の :ro を provider の出力形式に依らず意味で検査する。
  if merged=$(C3C_CODEX_PLUGINS_SOURCE=/tmp podman compose -f compose.yml -f compose.codex-plugins.yml config); then
    compose_mount_is_ro /home/node/.codex/plugins/cache <<<"$merged" || status=1
  else
    status=1
  fi
```

6 ファイル同時の config を 7 ファイルにする: 環境に `C3C_CODEX_PLUGINS_SOURCE=/tmp` を足し、`-f compose.agents.yml` の後に `-f compose.codex-plugins.yml` を足し、needle 一覧に `'/home/node/\.codex/plugins/cache'` を足し、ERROR 文言の「6 ファイル」を「7 ファイル」にする。`${VAR:?}` の検査ループの対に `compose.codex-plugins.yml:C3C_CODEX_PLUGINS_SOURCE` を足す。上のコメント「6 ファイル同時のマージ」も「7 ファイル」に直す。

- [ ] **Step 2: lint を回す**

Run: `./lint.sh; echo rc=$?`
Expected: `rc=0`、警告ゼロ。podman の無い環境では compose 検査がスキップされる（その場合は `not run` として報告し、ホストで実行する）。

- [ ] **Step 3: lint の検査が効くことを確かめる（一時的な破壊）**

`compose.codex-plugins.yml` の `read_only: true` を一時的に `read_only: false` にして `./lint.sh` → `rc=1` で compose_mount_is_ro の ERROR が出る。`git checkout compose.codex-plugins.yml` で戻す。

- [ ] **Step 4: 実 podman の検査を書く**

`test-build.sh` の `SHARED_ALIAS_PROBE` 定義の後に:

```bash
# ホストの Codex plugin キャッシュ共有。キャッシュは読めて書けず、その親の CODEX_DIR（rw）には書けることを確認する。
# shellcheck disable=SC2016  # コンテナ内 bash へ渡す文字列。$ はコンテナ側で展開させる意図
CODEX_PLUGINS_PROBE='
set -u
fail=0
expect_ro() {
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    echo "RW-LEAK $label (succeeded)"; fail=1; return
  fi
  case "$out" in
    *"Read-only file system"*|*"Device or resource busy"*) echo "RO-OK $label" ;;
    *) echo "RO-WRONG-REASON $label ($out)"; fail=1 ;;
  esac
}
d=/home/node/.codex/plugins/cache
if [ "$(cat "$d/seed" 2>/dev/null)" = seed ]; then echo "READ-OK $d"; else echo "READ-BROKEN $d"; fail=1; fi
expect_ro "cache/create"  sh -c "echo x > $d/probe-new"
expect_ro "cache/append"  sh -c "echo x >> $d/seed"
expect_ro "cache/delete"  rm -f "$d/seed"
expect_ro "cache/replace" sh -c "echo x > $d/seed.tmp && mv -f $d/seed.tmp $d/seed"
expect_ro "cache/rmdir"   rmdir "$d"
if mkdir -p /home/node/.codex/plugins/.staging-probe 2>/dev/null; then echo "RW-OK plugins/"; else echo "RW-BROKEN plugins/"; fail=1; fi
if echo x > /home/node/.codex/rw-probe 2>/dev/null; then echo "RW-OK .codex"; else echo "RW-BROKEN .codex"; fail=1; fi
exit $fail
'
```

`run_config_ro_tests()` の `SHARED_ALIAS_PROBE` の check と「一時 ~/.claude 配下の全エントリが実行ユーザー所有」の check の間に:

```bash
  # ホストの Codex plugin キャッシュ共有の実構成。
  local codex_home="$root/codex-home" codex_src="$root/codex-plugins-src"
  mkdir -p "$codex_home/plugins/cache" "$codex_src"
  echo seed > "$codex_src/seed"
  check "Codex plugin キャッシュは読めて書けず、CODEX_DIR には書ける" env \
    CLAUDE_CONFIG_DIR="$root" CONTEXT="$root" CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$root" \
    CODEX_DIR="$codex_home" C3C_CODEX_PLUGINS_SOURCE="$codex_src" \
    podman compose "${compose_args[@]}" -f "${SCRIPT_DIR}/compose.codex-plugins.yml" -p "$proj" --in-pod false \
      run --rm -T --entrypoint bash claude-auth-workspace -c "$CODEX_PLUGINS_PROBE"
  # shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
  check "書き込み試行後もホスト側 source が不変で、CODEX_DIR 側の書き込みだけ残る" \
    bash -c '[ "$(cat "$1/codex-plugins-src/seed")" = seed ] && [ "$(ls -A "$1/codex-plugins-src")" = seed ] && [ -e "$1/codex-home/rw-probe" ] && [ -d "$1/codex-home/plugins/.staging-probe" ]' _ "$root"
```

（既存の「全エントリが実行ユーザー所有」check が `$root` 全体を見るので、`codex-home` にサブ uid の残骸が無いこともそこで確認される。）

- [ ] **Step 5: 実 podman の検査を回す（ホスト）**

Run: `TMPDIR=/tmp ./test-build.sh --config-ro-only 2>&1 | tail -15`
Expected: `Codex plugin キャッシュは読めて書けず…` と `書き込み試行後もホスト側 source が不変…` が PASS、FAIL 0。テストイメージが無い場合は `./test-build.sh --build-only` を先に回す（README「変更後の確認」節）。コンテナ内では podman が無いため `not run`。

- [ ] **Step 6: Commit**

```bash
git add lint.sh test-build.sh
git commit -m "test: Codex plugin キャッシュ共有の Compose 設定と実マウントの読み取り専用を検査する"
```

### Task 3: 文書

**Files:**
- Modify: `README.md`（Codex 節に「ホストの Codex plugin を使う」小節、「変更後の確認」節、`compose.yml` のアーキテクチャ説明の override 一覧、「セキュリティモデル」の境界キー一覧 662 行目付近）
- Modify: `SECURITY-CLAIMS.md`（C-4 の保証する動作と限界）
- Modify: `docs/development-invariants.md`（34 行目の override 一覧、52 行目の直後に新項目）
- Modify: `examples/c3c/env.example`（CODEX_DIR の説明の後）

- [ ] **Step 1: README の Codex 節に小節を足す**

「Codex CLI を対話で使う」節の「**`--check` と `--clean`**」段落の直前に:

```markdown
**ホストの Codex plugin を使う**: `.c3c/env` に `CODEX_HOST_PLUGINS=1` を書くと、ホストの `~/.codex/plugins/cache`（ホストの Codex が install した plugin の実体）が、コンテナ内の `~/.codex/plugins/cache` に `:ro` で重なる。ホストの Codex はこのキャッシュの skill・hook を読むため、コンテナから書けないようにしている（`~/.claude/plugins` の `:ro` と同じ理由）。マウントだけでは plugin は有効にならない。コンテナ用の `CODEX_DIR/config.toml` に、ホストの `~/.codex/config.toml` と同じ有効化の行を書く（例: `[plugins."superpowers@superpowers-dev"]` と `enabled = true`。marketplace の定義は不要）。

- 更新はホストで行う（ホストの `codex plugin marketplace upgrade` 等）。コンテナ内の `codex plugin add`・`upgrade` はキャッシュに書けず失敗する。ホストでの更新は、bind が inode を共有するため稼働中のコンテナにも見える。
- ホストのキャッシュにある plugin はすべてコンテナから読めるが、読み込まれるのは `CODEX_DIR/config.toml` で有効にしたものだけ。有効化は user 層の設定で、起動時の MCP 審査（C-3）の対象外。plugin の hook の信頼確認は Codex 自身に委ねる。
- 条件: `CODEX_DIR` の設定と、ホストに `~/.codex/plugins/cache` が実在すること。`CODEX_DIR/plugins` または `CODEX_DIR/plugins/cache` が symlink かディレクトリ以外なら起動と `--check` で拒否する（rw の `CODEX_DIR` に置かれた symlink でマウント先をずらさせない）。マウント先はランチャーが作る（`--check` は作らない）。コンテナ内で入れた plugin が `CODEX_DIR/plugins/cache` に既にあれば、有効な間は隠れる旨の WARNING を出す。
- ランタイムの bind mount なので `-b` は不要だが、override ファイルが境界アセットのハッシュ対象なので、既存イメージでは `-b` するまでドリフトの WARNING が出る。`--check` は有効時に `[OK]   Codex plugin 共有 (ro): ...` を表示する。
```

- [ ] **Step 2: README の他の箇所**

1. 「変更後の確認」節の `SHARED_MOUNT` の別名マウントと `AGENTS_DIR` の段落の直後に:

```markdown
ホストの Codex plugin キャッシュ共有（`compose.codex-plugins.yml`・`guard_codex_host_plugins()`・`prepare_codex_host_plugins()`）の変更時も `./test-build.sh --launcher-only` を実行する（opt-in の配線、不正値・前提欠落・symlink のマウント先の拒否、`--check` の不変を含む）。`lint.sh` は override 単独の `:ro`、7 ファイル同時の Compose 設定、`${VAR:?}` の fail-closed を検証する。実マウントの読み取り専用は `./test-build.sh --config-ro-only`（実 Podman）で確認する。plugin が実際に読み込まれるかは、`-b` で起動したコンテナ内の `codex debug prompt-input hi` の skill 一覧で確認する。
```

2. Step 1 の `grep -rn 'compose\.agents\.yml' README.md` で出た残りの箇所（アーキテクチャの override 一覧、セキュリティモデル 662 行目付近の境界キー一覧の `AGENTS_DIR` の並び）に、`compose.codex-plugins.yml` / `CODEX_HOST_PLUGINS` を同じ形で足す。

- [ ] **Step 3: SECURITY-CLAIMS C-4**

「**保証する動作**」段落の末尾に次の文を足す:

```markdown
`CODEX_HOST_PLUGINS=1` のときだけ、ホストの `~/.codex/plugins/cache` を `CODEX_DIR` の内側（`/home/node/.codex/plugins/cache`）へ `:ro` で重ねる。source は launcher の `$HOME` に固定し、マウント先の symlink・型不一致は起動前に拒否する。
```

「**限界・非対象**」段落の末尾に次の文を足す:

```markdown
共有したキャッシュの plugin は、`CODEX_DIR/config.toml`（コンテナから変更可能）で有効化されれば読み込まれる。`:ro` が防ぐのはホストのキャッシュの改変であり、コンテナ内でどの plugin を有効にするかは制御しない。キャッシュ内の skill・hook の内容の安全性は保証しない。
```

「**根拠**」に `guard_codex_host_plugins()`、`compose.codex-plugins.yml` を足す。

- [ ] **Step 4: development-invariants**

34 行目の override 一覧に `compose.codex-plugins.yml` を、`guard_*` 一覧に `guard_codex_host_plugins()` を足す。52 行目（`${CODEX_DIR:-/dev/null}:/home/node/.codex` は rw 必須…）の直後に:

```markdown
  - `compose.codex-plugins.yml` の `${C3C_CODEX_PLUGINS_SOURCE:?}:/home/node/.codex/plugins/cache` は `:ro` 必須（ホストの Codex がキャッシュの skill・hook を読むため）。source は `guard_codex_host_plugins()` が `$HOME/.codex/plugins/cache` から実体解決した値だけで、任意パスを受け付けるキーを作らない。`C3C_CODEX_PLUGINS_SOURCE` は `ENV_FILE_ALLOWED_KEYS` に加えず、guard の冒頭で unset する。マウント先（`$CODEX_DIR/plugins`・`$CODEX_DIR/plugins/cache`）は rw の `CODEX_DIR` 内にあるので、`validate_claude_config_ro_path()` による symlink・型不一致の拒否を外さない。作成は `prepare_codex_host_plugins()` が `prepare_claude_config_ro()` の後で行い、`--check` では作らない。launcher は `CODEX_DIR/config.toml` を読み書きしない。
```

- [ ] **Step 5: env.example**

`examples/c3c/env.example` の `CODEX_DIR` の説明ブロックの後に:

```bash
# ホストの Codex で install した plugin（~/.codex/plugins/cache）を、コンテナ内の Codex からも
# 読み取り専用で使う（CODEX_DIR が必要）。有効化は CODEX_DIR/config.toml に書く。更新はホストで行う。
# CODEX_HOST_PLUGINS=1
```

- [ ] **Step 6: lint と Commit**

Run: `./lint.sh; echo rc=$?`
Expected: `rc=0`、警告ゼロ。

```bash
git add README.md SECURITY-CLAIMS.md docs/development-invariants.md examples/c3c/env.example
git commit -m "docs: CODEX_HOST_PLUGINS（ホストの Codex plugin キャッシュの :ro 共有）を説明する"
```

### Task 4: 実機受入（ホスト、実 Podman）

**Files:**
- Create: `docs/superpowers/plans/2026-09-24-codex-host-plugins-results.md`（ホストのパスと private の名前を書かない。`~` 表記を使う）

前提: ホストの `~/.codex/plugins/cache/superpowers-dev/superpowers/<版>` が存在し、fixture（Codex が使えるプロジェクト。専用 `CODEX_DIR` 設定済み、`allowed-domains.txt` に `chatgpt.com`）がある。ホストの `~/.codex/plugins/cache` の受入前後の `find ~/.codex/plugins/cache -printf '%y %m %U %T@ %p\n' | sort | sha256sum` を記録する。

- [ ] **A1: 有効化**

fixture の `.c3c/env` に `CODEX_HOST_PLUGINS=1` を足し、`CODEX_DIR/config.toml` に `[plugins."superpowers@superpowers-dev"]` と `enabled = true` を足す。`c3c --check <fixture>` → `[OK]   Codex plugin 共有 (ro): ...` が出て、`CODEX_DIR/plugins/cache` が作られていない。

- [ ] **A2: skill の読み込み**

`c3c codex -b <fixture>` で再ビルドして起動した状態で、ホストの別端末から `podman exec <コンテナ名> codex debug prompt-input hi | grep -o 'superpowers:[a-z-]*' | sort -u | wc -l` → ホストで同じコマンドを実行した件数と一致（2026-09-24 時点 15）。コンテナ名は `podman ps` で確認する。

- [ ] **A3: 対話起動（Review Focus 2）**

`c3c codex <fixture>` で対話起動し、起動エラーや marketplace 更新失敗の表示が無いこと、`$` などで skill 一覧に superpowers が出ることを確認する。起動を妨げるエラーが出たら、ここで止めて計画者へ戻す（設計の前提が崩れる）。

- [ ] **A4: 書けないこと**

コンテナ内で `touch ~/.codex/plugins/cache/probe` → `Read-only file system`。`codex plugin marketplace upgrade superpowers-dev` → 失敗し、キャッシュは不変。受入後のホスト側 `sha256sum` が受入前と一致。`CODEX_DIR` 配下に自分以外の uid 所有のエントリが無い（`find <CODEX_DIR> -not -uid $(id -u)` が空）。

- [ ] **A5: Claude 経路**

`c3c claude <fixture>` のコンテナ内で `codex debug prompt-input hi` にも superpowers が出る（CODEX_DIR の mount は agent によらないため）。

- [ ] **A6: 無効化で元に戻る**

`CODEX_HOST_PLUGINS` を消して起動 → `~/.codex/plugins/cache` にホストの plugin が見えない（`CODEX_DIR` 側の空ディレクトリだけ）。

- [ ] **Step: 結果を記録して Commit**

各項目の実行コマンド・出力の要点・PASS/FAIL を結果ファイルに書く。実行できなかった項目は `not run` と理由を書く。

```bash
git add docs/superpowers/plans/2026-09-24-codex-host-plugins-results.md
git commit -m "docs: CODEX_HOST_PLUGINS の実機受入を記録する"
```

## 完了後

- 利用者から見える新しい env キーの追加なので、SemVer は minor（現行 `v14.0.1` → `v14.1.0` を提案）。移行作業は不要（opt-in、既定は従来どおり）。タグは持ち主の承認後。
- PR 後の二重レビュー（Codex `--sandbox read-only` と、作成に関わっていない Claude の対話セッション）。

区分: 境界（`compose.yml` 系の境界マウント・ホストで実行される内容の書込み経路・`docs/development-invariants.md` の不変条件を変えるため）。計画・PR 前・PR 後の 3 段階の二重レビューを行う。

推奨実装: Codex（host の checkout と実 Podman で完結し、各 Step のコードと Expected を逐語で確定させたため。Task 4 の A3 は対話操作なので持ち主か Claude の対話セッションが担う。Sonnet を推さない理由は、逐語手順が確定していて設計判断が残らず、判定基準 4 に当たるため）。
