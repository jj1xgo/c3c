#!/usr/bin/env bash
# lint.sh の compose config 検査（compose_mount_is_ro / compose_tty_disabled / compose_merged_overrides_ok と、その lint 本体への配線）を、podman-compose の
# 短縮表記と docker compose の long syntax の両 fixture で検証する。実 provider は起動しない
# （docker compose provider での実 config は not run。CI の provider 差を fixture で代表する）。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

{
  printf '#!/bin/bash\nset -euo pipefail\n'
  sed -n '/^compose_mount_is_ro()/,/^}/p; /^compose_tty_disabled()/,/^}/p; /^compose_merged_overrides_ok()/,/^}/p' "$ROOT/lint.sh"
  cat <<'TAIL'
case "$1" in
  ro) compose_mount_is_ro "$2" ;;
  tty) compose_tty_disabled ;;
  merged) compose_merged_overrides_ok ;;
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

# --- 7 ファイル同時 config（lint.sh の compose_merged_overrides_ok、#174） ---
# 関数の中の完全一致を部分一致（grep -F 等）へ戻すと、.agents-x の fixture が合格して赤になる。
merged_short='services:
  claude-auth-workspace:
    network_mode: pasta:-g,fe80::1
    volumes:
      - /tmp:/tmp/lint-plugins-alias:ro
      - /tmp:/home/node/lint-shared-home:ro
      - /tmp:/tmp/lint-shared-host:ro
      - /tmp:/home/node/.agents:ro
      - /tmp:/home/node/.codex/plugins/cache:ro'
run_case '7 ファイル（短縮表記）: 5 つの :ro と network_mode があれば合格' merged 0 "$merged_short"
run_case '7 ファイル（短縮表記）: .agents が .agents-x に化けていれば失敗' merged 1 "${merged_short/\/home\/node\/.agents:ro/\/home\/node\/.agents-x:ro}"
run_case '7 ファイル（短縮表記）: 1 つが :rw なら失敗' merged 1 "${merged_short/lint-shared-host:ro/lint-shared-host:rw}"
merged_no_ipv6=$(printf '%s\n' "$merged_short" | sed '/network_mode:/d')
run_case '7 ファイル（短縮表記）: network_mode が無ければ失敗' merged 1 "$merged_no_ipv6"
merged_long='services:
  claude-auth-workspace:
    network_mode: pasta:-g,fe80::1
    volumes:'
for t in /tmp/lint-plugins-alias /home/node/lint-shared-home /tmp/lint-shared-host /home/node/.agents /home/node/.codex/plugins/cache; do
  merged_long+="
      - type: bind
        source: /tmp
        target: $t
        read_only: true
        bind:
          create_host_path: true"
done
run_case '7 ファイル（long syntax）: 5 つの read_only と network_mode があれば合格' merged 0 "$merged_long"
run_case '7 ファイル（long syntax）: .agents が .agents-x に化けていれば失敗' merged 1 "${merged_long/target: \/home\/node\/.agents$'\n'/target: \/home\/node\/.agents-x$'\n'}"
[[ "${merged_short/\/home\/node\/.agents:ro/\/home\/node\/.agents-x:ro}" != "$merged_short" \
  && "${merged_long/target: \/home\/node\/.agents$'\n'/target: \/home\/node\/.agents-x$'\n'}" != "$merged_long" \
  && "$merged_no_ipv6" != "$merged_short" ]] || { echo 'FAIL - 7 ファイルの対照 fixture の生成'; fail=$((fail + 1)); }
# lint 本体の配線（#174）: 7 ファイル同時 config を取る if の直後の行が、関数の結果を status へ反映する呼び出しであること。
# 偽の provider で lint.sh 全体を走らせる方式は採らない（lint.sh は他にも十数回 compose を呼び、${VAR:?} の検査は
# config の失敗を期待するので、偽の provider がそれを全部まねる必要がある）。呼び出しを || true 等へ変えると赤になる。
wiring=$(awk 'prev ~ /-f compose\.agents\.yml -f compose\.codex-plugins\.yml config\); then$/ { print; exit } { prev = $0 }' "$ROOT/lint.sh")
count=$((count + 1))
# shellcheck disable=SC2016 # 意図的にリテラル（lint.sh の 1 行と文字どおり比べる。変数展開ではない）
if [[ "$wiring" == '    compose_merged_overrides_ok <<<"$merged" || status=1' ]]; then
  echo 'ok - lint 本体: 7 ファイル同時 config の検査結果を status へ反映している'
else
  echo "FAIL - lint 本体: 7 ファイル同時 config の直後の行が想定と違う: ${wiring:-（見つからない）}"; fail=$((fail + 1))
fi

echo "結果: $count ケース、失敗 $fail"
[[ "$fail" -eq 0 ]]
