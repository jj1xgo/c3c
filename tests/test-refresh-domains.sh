#!/usr/bin/env bash
# DNS 応答の除外とエラー時の継続を、実物の refresh_domains で検証する（#53）。
# DNS とルール適用先だけを固定し、ネットワーク・実 iptables には触れない。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/harness" <<'HEAD'
#!/bin/bash
set -euo pipefail
IFS=$'\n\t'
build_domain_list() { printf '%s\n' fixture.invalid next.invalid; }
dig() {
  if [ "${!#}" = next.invalid ]; then
    printf '%s\n' 'next.invalid. 60 IN A 192.0.2.10'
  else
    cat "$FIXTURE"
    return "${DIG_RC:-0}"
  fi
}
add_or_touch_domain_ip() {
  if [ "$1" = "${FAIL_IP:-}" ]; then return 1; fi
  printf '%s\n' "$1" >> "$RECORD"
}
HEAD
sed -n '/^refresh_domains()/,/^}/p' "$ROOT/init-firewall.sh" >> "$tmp/harness"
grep -q '^refresh_domains()' "$tmp/harness"
printf '%s\n' 'refresh_domains 1000' >> "$tmp/harness"

fail=0
count=0
run_case() {
  local label="$1" answer="$2" expected_rc="$3" expected_ips="$4" warning="$5"
  local actual_rc=0
  printf '%b' "$answer" > "$tmp/answer"
  : > "$tmp/record"
  FIXTURE="$tmp/answer" RECORD="$tmp/record" DIG_RC="${6:-0}" FAIL_IP="${7:-}" \
    bash "$tmp/harness" > "$tmp/out" 2> "$tmp/err" || actual_rc=$?
  count=$((count + 1))
  if [ "$actual_rc" -eq "$expected_rc" ] && [ "$(cat "$tmp/record")" = "$expected_ips" ] && \
    { { [ -z "$warning" ] && [ ! -s "$tmp/err" ]; } ||
      { [ -n "$warning" ] && grep -qF 'WARNING:' "$tmp/err" && grep -qF "$warning" "$tmp/err"; }; }; then
    echo "ok - $label"
  else
    echo "FAIL - $label (rc=$actual_rc、期待=$expected_rc)"
    cat "$tmp/out" "$tmp/err" "$tmp/record"
    fail=$((fail + 1))
  fi
}

# 各 /8 の端点と内部値。除外だけの応答でも次ドメインへ進み、成功を返す。
for ip in 0.0.0.0 0.1.2.3 0.255.255.255 127.0.0.0 127.1.2.3 127.255.255.255; do
  run_case "特殊用途 $ip は除外して継続" "fixture.invalid. 60 IN A $ip\n" 0 '192.0.2.10' "$ip"
done
# 隣接ブロック・通常の宛先と、明示的な内部ホストの許可を変えない。
for ip in 1.0.0.0 126.255.255.255 128.0.0.0 192.0.2.1 10.0.0.1 169.254.1.2; do
  run_case "通常の適用 $ip" "fixture.invalid. 60 IN A $ip\n" 0 "$ip"$'\n192.0.2.10' ''
done
run_case '混在応答の正常 IP を保持' \
  'fixture.invalid. 60 IN A 0.0.0.0\nfixture.invalid. 60 IN A 192.0.2.1\n' \
  0 $'192.0.2.1\n192.0.2.10' '0.0.0.0'
run_case 'NXDOMAIN は警告して成功' ';; status: NXDOMAIN\n' 0 '192.0.2.10' NXDOMAIN
run_case 'SERVFAIL は次ドメインへ進むが全体は失敗' ';; status: SERVFAIL\n' 1 '192.0.2.10' fixture.invalid
run_case 'dig の非ゼロ終了も全体は失敗' '' 1 '192.0.2.10' fixture.invalid 9
run_case '適用失敗を握り潰さない' 'fixture.invalid. 60 IN A 192.0.2.1\n' \
  1 '192.0.2.10' 'ルール適用に失敗' 0 '192.0.2.1'

echo "DNS 応答テスト: $count 件、失敗 $fail 件"
[ "$fail" -eq 0 ]
