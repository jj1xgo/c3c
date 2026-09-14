#!/bin/bash
# test-build.sh の隔離ハーネスを利用する。実ランチャーの拒否と compose への配線を検証する。
# shellcheck disable=SC2016,SC2034,SC2154
run_instruction_mount_launcher_tests() {
  local root bin home proj out rc before_ctx value key
  launcher_sandbox_init
  log "## 指示ファイルとスキルの追加共有（#99）"
  mkdir -p "$home/obsidian-vault/knowledge" "$home/.agents/skills" "$proj/.claude-container.d"
  printf '索引\n' > "$home/obsidian-vault/knowledge/索引.md"

  run_launcher SHARED_MOUNT="$home/obsidian-vault" \
    CLAUDE_SHARED_HOME_PATH=/tmp/injected CLAUDE_SHARED_HOST_PATH=/tmp/injected
  check "未設定なら /shared のみで内部別名変数も破棄する" \
    bash -c '[ "$1" = 0 ] && ! grep -qE "compose\.(shared|agents)|^CLAUDE_SHARED_(HOME|HOST)_PATH=" "$2/compose-args" "$2/compose-env"' _ "$rc" "$root"

  printf 'SHARED_MOUNT=~/obsidian-vault\nSHARED_MOUNT_HOME_ALIAS=1\nAGENTS_DIR=~/.agents\n' > "$proj/.claude-container.d/env"
  run_launcher
  check "env の opt-in が ~/ とホスト絶対パスの別名、およびスキル共有を渡す" \
    bash -c '[ "$1" = 0 ] && grep -qxF "CLAUDE_SHARED_HOME_PATH=/home/node/obsidian-vault" "$2/compose-env" && grep -qxF "CLAUDE_SHARED_HOST_PATH=$3/obsidian-vault" "$2/compose-env" && grep -qxF "AGENTS_DIR=$3/.agents" "$2/compose-env" && grep -qxF "$4/compose.shared-home.yml" "$2/compose-args" && grep -qxF "$4/compose.shared-host.yml" "$2/compose-args" && grep -qxF "$4/compose.agents.yml" "$2/compose-args"' _ "$rc" "$root" "$home" "$SCRIPT_DIR"
  printf '%s\n' "$out" >> "$LOG_FILE"

  snapshot_check_targets > "$root/before"
  run_launcher_check
  snapshot_check_targets > "$root/after"
  check "有効な --check は追加共有を診断し対象を変更しない" \
    bash -c '[ "$1" = 0 ] && [[ "$2" == *"/home/node/obsidian-vault"* && "$2" == *"AGENTS_DIR"* ]] && cmp -s "$3/before" "$3/after"' _ "$rc" "$out" "$root"

  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" CLAUDE_CONTAINER_IPV6=1 \
    "${SCRIPT_DIR}/claude-container" -b "$proj" 2>&1) && rc=0 || rc=$?
  check "build と run に共有・スキル・plugin・IPv6 の override が共存する" \
    bash -c '[ "$1" = 0 ] && [ "$(cat "$2/compose-calls")" = 2 ] || exit 1
      for n in 1 2; do for f in shared-home shared-host agents plugins-alias ipv6; do
        grep -qxF "$3/compose.$f.yml" "$2/compose-args.$n" || exit 1
      done; done' _ "$rc" "$root" "$SCRIPT_DIR"
  printf '%s\n' "$out" >> "$LOG_FILE"
  : > "$proj/.claude-container.d/env"

  # ガードを落とすと、これらが compose に到達して設定を隠すか、ホストに空の実体を作る。
  for value in '' 2 true '1 '; do
    [[ -n "$value" ]] || continue
    run_launcher SHARED_MOUNT_HOME_ALIAS="$value" SHARED_MOUNT="$home/obsidian-vault"
    check "別名フラグの不正値 '$value' を起動時に拒否する" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check SHARED_MOUNT_HOME_ALIAS="$value" SHARED_MOUNT="$home/obsidian-vault"
    check "別名フラグの不正値 '$value' を --check も拒否する" [ "$rc" -ne 0 ]
  done
  mkdir -p "$home/.claude/notes" "$home/.config/notes" "$home/nested/vault" "$root/outside"
  for value in '' "$home" "$root/outside" "$home/.claude" "$home/.claude/notes" "$home/.agents" "$home/.config/notes" "$home/nested/../obsidian-vault"; do
    run_launcher SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$value"
    check "未指定・HOME外・保護先と重なる別名を拒否する: $value" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$value"
    check "--check も同じ別名を拒否する: $value" [ "$rc" -ne 0 ]
  done
  for value in relative "$home/missing-agents" "$home/obsidian-vault/knowledge/索引.md"; do
    run_launcher AGENTS_DIR="$value"
    check "不正な AGENTS_DIR を compose 前に拒否する: $value" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"AGENTS_DIR"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check AGENTS_DIR="$value"
    check "--check も同じ AGENTS_DIR を拒否する: $value" [ "$rc" -ne 0 ]
  done
  run_launcher SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$home/nested/vault/" AGENTS_DIR="$home/.agents"
  check "HOME 配下の階層を保ち末尾 / を正規化する" \
    bash -c '[ "$1" = 0 ] && grep -qxF "CLAUDE_SHARED_HOME_PATH=/home/node/nested/vault" "$2/compose-env"' _ "$rc" "$root"
  run_launcher AGENTS_DIR="$home/.agents" EXTRA_MOUNT="$home"
  check "別 rw マウントによるスキル共有への書き込み経路を警告する" \
    bash -c '[ "$1" = 0 ] && [[ "$2" == *"WARNING:"*"AGENTS_DIR"*"rw"* ]]' _ "$rc" "$out"
  launcher_sandbox_cleanup
}
