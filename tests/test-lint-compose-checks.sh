#!/usr/bin/env bash
# lint.sh の compose config 検査（compose_mount_is_ro / compose_tty_disabled）を、podman-compose の
# 短縮表記と docker compose の long syntax の両 fixture で検証する。実 provider は起動しない
# （docker compose provider での実 config は not run。CI の provider 差を fixture で代表する）。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

{
  printf '#!/bin/bash\nset -euo pipefail\n'
  sed -n '/^compose_mount_is_ro()/,/^}/p; /^compose_tty_disabled()/,/^}/p' "$ROOT/lint.sh"
  cat <<'TAIL'
case "$1" in
  ro) compose_mount_is_ro "$2" ;;
  tty) compose_tty_disabled ;;
esac
TAIL
} > "$tmp/harness"

TARGET=/etc/claude-container/codex-mcp-approved.json
fail=0 count=0
run_case() {
  local label="$1" kind="$2" expected_rc="$3" input="$4" rc=0
  printf '%s\n' "$input" | bash "$tmp/harness" "$kind" "$TARGET" > "$tmp/out" 2> "$tmp/err" || rc=$?
  count=$((count + 1))
  if [[ "$rc" -eq "$expected_rc" ]] && { [[ "$expected_rc" -eq 0 ]] || grep -q 'ERROR:' "$tmp/err"; }; then
    echo "ok - $label"
  else
    echo "FAIL - $label (rc=$rc, expected $expected_rc)"; cat "$tmp/out" "$tmp/err"; fail=$((fail + 1))
  fi
}

# --- podman-compose 風（短縮表記のまま） ---
short_ro='services:
  claude-auth-workspace:
    tty: false
    stdin_open: false
    volumes:
      - /home/u/.claude:/home/node/.claude
      - /dev/null:/etc/claude-container/mcp-approved-hash:ro
      - /home/u/.local/state/record.json:/etc/claude-container/codex-mcp-approved.json:ro
      - /etc/localtime:/etc/localtime:ro'
run_case '短縮表記: :ro は合格' ro 0 "$short_ro"
run_case '短縮表記: :ro,z も合格' ro 0 "${short_ro/codex-mcp-approved.json:ro/codex-mcp-approved.json:ro,z}"
run_case '短縮表記: :rw は失敗' ro 1 "${short_ro/codex-mcp-approved.json:ro/codex-mcp-approved.json:rw}"
run_case '短縮表記: オプション無しは失敗' ro 1 "${short_ro/codex-mcp-approved.json:ro/codex-mcp-approved.json}"
run_case '短縮表記: 対象 mount が無ければ失敗（他の :ro があっても）' ro 1 "${short_ro//codex-mcp-approved.json/other.json}"
# target の末尾に文字が続く別の mount（例: .agents に対する .agents-x）を対象と取り違えない（#112）。
run_case '短縮表記: target に接尾辞が付いた別 mount は失敗' ro 1 "${short_ro//codex-mcp-approved.json:ro/codex-mcp-approved.json-x:ro}"

# --- docker compose 風（long syntax へ正規化、false は省略） ---
long_ro='name: proj
services:
  claude-auth-workspace:
    environment:
      CC_AGENT: claude
    volumes:
      - type: bind
        source: /home/u/.claude
        target: /home/node/.claude
        bind:
          create_host_path: true
      - type: bind
        source: /dev/null
        target: /etc/claude-container/mcp-approved-hash
        read_only: true
        bind:
          create_host_path: true
      - type: bind
        source: /home/u/.local/state/record.json
        target: /etc/claude-container/codex-mcp-approved.json
        read_only: true
        bind:
          create_host_path: true
      - type: bind
        source: /etc/localtime
        target: /etc/localtime
        read_only: true
    working_dir: /workspace'
run_case 'long syntax: read_only: true は合格' ro 0 "$long_ro"
# 対象要素の直後行（read_only: true）だけを書き換えた対照。
long_rw=$(printf '%s\n' "$long_ro" | sed '/codex-mcp-approved\.json$/{n;s/read_only: true/read_only: false/}')
run_case 'long syntax: read_only: false は失敗' ro 1 "$long_rw"
long_missing=$(printf '%s\n' "$long_ro" | sed '/codex-mcp-approved\.json$/{n;/read_only: true/d}')
run_case 'long syntax: read_only 欠落は失敗' ro 1 "$long_missing"
[[ "$long_rw" != "$long_ro" && "$long_missing" != "$long_ro" ]] || { echo 'FAIL - 対照 fixture の生成'; fail=$((fail + 1)); }
# 隣の要素の read_only: true を自分のものと誤認しない（対象要素の直後に別要素の read_only がある形）。
long_neighbor='services:
  claude-auth-workspace:
    volumes:
      - type: bind
        source: /home/u/.local/state/record.json
        target: /etc/claude-container/codex-mcp-approved.json
        bind:
          create_host_path: true
      - type: bind
        source: /etc/localtime
        target: /etc/localtime
        read_only: true'
run_case 'long syntax: 隣接要素の read_only を取り込まない' ro 1 "$long_neighbor"
long_dash_target='services:
  claude-auth-workspace:
    volumes:
      - target: /etc/claude-container/codex-mcp-approved.json
        source: /dev/null
        type: bind
        read_only: true
      - target: /etc/localtime
        source: /etc/localtime
        type: bind'
run_case 'long syntax: target が先頭キーの要素も合格' ro 0 "$long_dash_target"
run_case 'long syntax: 対象 mount が無ければ失敗' ro 1 "${long_ro//codex-mcp-approved.json/other.json}"
run_case 'long syntax: target に接尾辞が付いた別 mount は失敗' ro 1 "${long_ro//codex-mcp-approved.json/codex-mcp-approved.json-x}"

# --- TTY / stdin ---
run_case 'tty: false が明示されていれば合格（podman-compose）' tty 0 "$short_ro"
run_case 'tty/stdin_open が省略されていれば合格（docker compose）' tty 0 "$long_ro"
run_case 'tty: true が残れば失敗' tty 1 "${short_ro/tty: false/tty: true}"
run_case 'stdin_open: true が残れば失敗' tty 1 "${short_ro/stdin_open: false/stdin_open: true}"
long_quoted_tty="services:
  claude-auth-workspace:
    tty: 'true'
    volumes: []"
run_case "引用された 'true' も失敗" tty 1 "$long_quoted_tty"

echo "結果: $count ケース、失敗 $fail"
[[ "$fail" -eq 0 ]]
