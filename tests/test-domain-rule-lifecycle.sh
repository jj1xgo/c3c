#!/usr/bin/env bash
# DNS 許可ルールの世代非更新・期限切れ削除を実物の関数で検証する（#78）。
# iptables は固定一覧と呼び出し記録のみ。カーネルのルール適用は検証しない。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/harness" <<'HEAD'
#!/bin/bash
set -euo pipefail
IFS=$'\n\t'
CHAIN=CLAUDE_EGRESS
ALLOWED_PORTS=443,22
build_domain_list() { printf '%s\n' zero.invalid loop.invalid; }
dig() {
  case "${!#}" in
    zero.invalid) printf '%s\n' 'zero.invalid. 60 IN A 0.0.0.0' ;;
    loop.invalid) printf '%s\n' 'loop.invalid. 60 IN A 127.0.0.1' ;;
    *) return 1 ;;
  esac
}
iptables() {
  case "$1" in
    -S) cat "$RULES" ;;
    -A|-D) printf '%s\n' "$@" >> "$RECORD" ;;
    *) echo "ERROR: 想定外の iptables 呼び出し" >&2; return 1 ;;
  esac
}
HEAD
for name in add_cidr_tagged add_or_touch_domain_ip refresh_domains prune_stale_domain_rules; do
  sed -n "/^${name}()/,/^}/p" "$ROOT/init-firewall.sh" >> "$tmp/harness"
  grep -q "^${name}()" "$tmp/harness"
done
cat >> "$tmp/harness" <<'TAIL'
if [ "$MODE" = refresh ]; then
  refresh_domains 1000
  cp "$RECORD" "$REFRESH_RECORD"
fi
prune_stale_domain_rules "$CUTOFF"
TAIL

fail=0
count=0
# 固定の一覧から選ばれる行番号と順序を照合する。-D の適用自体はモデル化しない。
run_case() {
  local label="$1" mode="$2" cutoff="$3" expected="$4" rc=0
  : > "$tmp/record"
  rm -f "$tmp/refresh-record"
  RULES="$tmp/rules" RECORD="$tmp/record" REFRESH_RECORD="$tmp/refresh-record" \
    MODE="$mode" CUTOFF="$cutoff" bash "$tmp/harness" > "$tmp/out" 2> "$tmp/err" || rc=$?
  count=$((count + 1))
  if [ "$rc" -eq 0 ] && [ "$(cat "$tmp/record")" = "$expected" ] && \
    { { [ "$mode" = prune ] && [ ! -s "$tmp/err" ]; } ||
      { [ "$mode" = refresh ] && [ -f "$tmp/refresh-record" ] && [ ! -s "$tmp/refresh-record" ] &&
        grep -qF 'WARNING: zero.invalid -> 0.0.0.0' "$tmp/err" &&
        grep -qF 'WARNING: loop.invalid -> 127.0.0.1' "$tmp/err"; }; }; then
    echo "ok - $label"
  else
    echo "FAIL - $label (rc=$rc)"
    cat "$tmp/out" "$tmp/err" "$tmp/record"
    fail=$((fail + 1))
  fi
}

# 先頭/末尾の期限切れ、cutoff 同値/直後、タグのないルールを混在させる。
# -N 行をルール番号に数える回帰や、タグなし行を番号から落とす回帰も検出する。
cat > "$tmp/rules" <<'RULES'
-N CLAUDE_EGRESS
-A CLAUDE_EGRESS -d 0.0.0.0/32 -m comment --comment "domain=zero.invalid;gen=819" -j ACCEPT
-A CLAUDE_EGRESS -d 192.0.2.0/24 -j ACCEPT
-A CLAUDE_EGRESS -d 127.0.0.1/32 -m comment --comment "domain=loop.invalid;gen=820" -j ACCEPT
-A CLAUDE_EGRESS -d 192.0.2.1/32 -m comment --comment "domain=current.invalid;gen=821" -j ACCEPT
-A CLAUDE_EGRESS -d 192.0.2.2/32 -m comment --comment "gen=1" -j ACCEPT
-A CLAUDE_EGRESS -d 127.0.0.2/32 -m comment --comment "domain=old.invalid;gen=1" -j ACCEPT
RULES
run_case 'cutoff より古いルールだけを降順で削除' prune 820 $'-D\nCLAUDE_EGRESS\n6\n-D\nCLAUDE_EGRESS\n1'
run_case '除外 IP を更新せず期限切れだけを削除' refresh 820 $'-D\nCLAUDE_EGRESS\n6\n-D\nCLAUDE_EGRESS\n1'
run_case '次の cutoff で旧境界のルールも削除' refresh 821 $'-D\nCLAUDE_EGRESS\n6\n-D\nCLAUDE_EGRESS\n3\n-D\nCLAUDE_EGRESS\n1'

# 該当するルールがないときも成功し、削除を要求しない。
printf '%s\n' '-N CLAUDE_EGRESS' > "$tmp/rules"
run_case '空チェーンでは削除なし' prune 820 ''
cat >> "$tmp/rules" <<'RULES'
-A CLAUDE_EGRESS -d 192.0.2.0/24 -j ACCEPT
-A CLAUDE_EGRESS -d 192.0.2.1/32 -m comment --comment "domain=current.invalid;gen=820" -j ACCEPT
RULES
run_case '非期限切れとタグなしのみなら削除なし' prune 820 ''

echo "DNS ルールの世代テスト: $count 件、失敗 $fail 件"
[ "$fail" -eq 0 ]
