#!/usr/bin/env bash
# init-firewall.sh の init モードを固定入力で走らせ、ルールを変える呼び出しの列を
# 期待値と照合する（#225）。iptables・ip6tables・dig・curl・timeout・ip・date と
# IPv6 helper を差し替え、iptables/ip6tables の変更系と helper の呼び出しだけを記録する。
# 読むだけの呼び出し（-L・-S・dig・curl など）の順番と、標準出力・標準エラーは照合しない。
# カーネルのルール適用と実ネットワークは検証しない（tests/test-runtime.sh の範囲）。
#
# /proc/sys の IPv6 の予備の無効化の結果（disable_ipv6）は、記録の外で expect_ipv6_conf が照合する。
#
# UPDATE_EXPECTED=1 で、期待値ファイルを持つシナリオの記録を書き出す（disable_ipv6 の期待は
# expect_ipv6_conf の引数で、書き出しの対象外）。
# bad-meta・no-default-route は、ルールを 1 つも変えずに止まることを判定する（EXPECT_EARLY_STOP=0 で rc だけの判定）。
set -euo pipefail
export LC_ALL=C
ROOT=$(cd "$(dirname "$0")/.." && pwd)
FIXTURES="$ROOT/tests/fixtures/firewall-init-trace"
UPDATE_EXPECTED="${UPDATE_EXPECTED:-0}"
EXPECT_EARLY_STOP="${EXPECT_EARLY_STOP:-1}"

if [ "$(id -u)" -eq 0 ]; then
  echo "FAIL: root では走らせない（差し替えが効かないと実ホストのルールを変えるため）" >&2
  exit 1
fi

tmp=$(mktemp -d)
trap '[ -n "${KEEP_TMP:-}" ] || rm -rf "$tmp"' EXIT

# 写しの固定パスを一時ディレクトリの下へ置き換える。置き換え先は元のパスを部分文字列に
# 含まない名前にし、置き換え漏れを grep で検出できるようにする。
script="$tmp/init-firewall.sh"
sed -e "s|/etc/c3c/|$tmp/c3c-etc/|g" \
    -e "s|/etc/resolv.conf|$tmp/resolv.conf|g" \
    -e "s|/usr/local/bin/ipv6-firewall.py|$tmp/ipv6-helper|g" \
    -e "s|/proc/sys/net/ipv6/conf/|$tmp/ipv6-conf/|g" \
    "$ROOT/init-firewall.sh" > "$script"
if grep -nF -e /etc/c3c/ -e /etc/resolv.conf -e /usr/local/bin/ipv6-firewall.py \
     -e /proc/sys/net/ipv6/conf/ "$script" >&2; then
  echo "FAIL: 写しに固定パスが残っています（上の行）" >&2
  exit 1
fi

stubs="$tmp/stubs"
mkdir -p "$stubs" "$tmp/c3c-etc" "$tmp/ipv6-conf/all" "$tmp/ipv6-conf/default"

# iptables・ip6tables: 変更系を「コマンド名 引数」の 1 行で記録する。
cat > "$stubs/iptables" <<'STUB'
#!/bin/bash
name=${0##*/}
case "${1:-}" in
  -L)
    [ "$name" = ip6tables ] && [ "${TRACE_IP6_LIST_FAIL:-0}" = 1 ] && exit 1
    exit 0 ;;
  -S)
    printf -- '-N %s\n' "${2:-}"
    exit 0 ;;
esac
line="$name $*"
printf '%s\n' "$line" >> "$TRACE_RECORD"
[ "$line" = "${TRACE_FAIL_RULE:-}" ] && exit 1
exit 0
STUB
chmod +x "$stubs/iptables"
cp "$stubs/iptables" "$stubs/ip6tables"

# dig: 許可ドメインの解決（+comments 付き）と、verify_ipv4 の api.github.com の解決。
cat > "$stubs/dig" <<'STUB'
#!/bin/bash
if [ "$*" = "+short +time=2 +tries=2 A api.github.com" ]; then
  echo 140.82.112.5
  exit 0
fi
if [ "$#" -ne 7 ] || [ "$1 $2 $3 $4 $5 $6" != "+noall +answer +comments +time=2 +tries=2 A" ]; then
  echo "stub dig: 想定外の引数: $*" >&2
  exit 99
fi
domain=$7
if [ "$domain" = "${TRACE_DIG_FAIL:-}" ]; then
  echo ';; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 1'
  exit 9
fi
case "$domain" in
  api.anthropic.com) ip=160.79.104.10 ;;
  claude.ai) ip=160.79.104.11 ;;
  console.anthropic.com) ip=160.79.104.12 ;;
  statsig.anthropic.com) ip=34.36.57.103 ;;
  statsig.com) ip=104.18.20.1 ;;
  sentry.io) ip=35.186.247.156 ;;
  alpha.example) ip=192.0.2.10 ;;
  beta.example) ip=192.0.2.20 ;;
  *) echo "stub dig: 想定外のドメイン: $domain" >&2; exit 99 ;;
esac
echo ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1'
printf '%s. 60 IN A %s\n' "$domain" "$ip"
STUB
chmod +x "$stubs/dig"

# curl: verify_ipv4 の 2 つの呼び出しの形（上限時間を含む）だけを受け付ける。
cat > "$stubs/curl" <<'STUB'
#!/bin/bash
case "$*" in
  "-q -4 --connect-timeout 5 --max-time 10 --retry 0 -s https://example.com")
    [ "${TRACE_VERIFY:-}" = example-reachable ] && exit 0
    exit 7 ;;
  "-q -4 --connect-timeout 10 --max-time 20 --retry 0 -sS -o /dev/null https://api.anthropic.com")
    [ "${TRACE_VERIFY:-}" = anthropic-blocked ] && exit 28
    exit 0 ;;
esac
echo "stub curl: 想定外の引数: $*" >&2
exit 99
STUB
chmod +x "$stubs/curl"

# timeout: verify_ipv4 の TCP 接続確認（443 は 10 秒、80 は 5 秒）だけを受け付ける。
# shellcheck disable=SC2016 # 照合する引数の字面そのもの。
cat > "$stubs/timeout" <<'STUB'
#!/bin/bash
if [ "$#" -eq 7 ] && [ "$2" = bash ] && [ "$3" = -c ] && [ "$4" = 'exec 3<>/dev/tcp/$1/$2' ] &&
   [ "$5" = probe ] && [ "$6" = 140.82.112.5 ]; then
  case "$1:$7" in
    10:443) [ "${TRACE_VERIFY:-}" = github443-blocked ] && exit 1; exit 0 ;;
    5:80) [ "${TRACE_VERIFY:-}" = github80-reachable ] && exit 0; exit 1 ;;
  esac
fi
echo "stub timeout: 想定外の引数: $*" >&2
exit 99
STUB
chmod +x "$stubs/timeout"

cat > "$stubs/ip" <<'STUB'
#!/bin/bash
if [ "$*" != route ]; then
  echo "stub ip: 想定外の引数: $*" >&2
  exit 99
fi
[ "${TRACE_NO_DEFAULT_ROUTE:-0}" = 1 ] || echo 'default via 10.88.0.1 dev eth0 proto static'
echo '10.88.0.0/16 dev eth0 proto kernel scope link src 10.88.0.5'
STUB
chmod +x "$stubs/ip"

real_date=$(command -v date)
cat > "$stubs/date" <<STUB
#!/bin/bash
if [ "\$*" = +%s ]; then echo 1700000000; exit 0; fi
exec "$real_date" "\$@"
STUB
chmod +x "$stubs/date"

# IPv6 helper: サブコマンドと引数を同じ記録に書く。refresh の stdin は読み捨てる。
cat > "$tmp/ipv6-helper" <<'STUB'
#!/bin/bash
case "${1:-}" in
  prepare|verify) ;;
  refresh) cat >/dev/null ;;
  *) echo "stub ipv6 helper: 想定外の引数: $*" >&2; exit 99 ;;
esac
printf '%s\n' "$*" >> "$TRACE_RECORD"
[ "$1" = "${TRACE_HELPER_FAIL:-}" ] && exit 1
exit 0
STUB
chmod +x "$tmp/ipv6-helper"

good_meta='{"web":["192.30.252.0/22","185.199.108.0/22"],"api":["192.30.252.0/22","140.82.112.0/20"],"git":["143.55.64.0/20","2a0a:a440::/29"]}'

fail=0
count=0
# disable_ipv6 の初期値。0 でも 1 でもない値にし、--ipv6 で「書かない」ことを確かめられるようにする。
ipv6_conf_unwritten=unwritten

# シナリオ名 期待の種類（full = 期待値ファイルと全体照合、early = ルールを変える前に止まる）
# の後に、スクリプトの引数と TRACE_* の環境変数を「--」で区切って渡す。
run_scenario() {
  local name="$1" kind="$2"; shift 2
  local -a args=() envs=()
  while [ "$#" -gt 0 ] && [ "$1" != -- ]; do args+=("$1"); shift; done
  [ "$#" -gt 0 ] && shift
  envs=("$@")
  local resolv='nameserver 10.88.0.53' meta="$good_meta" kv
  for kv in "${envs[@]}"; do
    case "$kv" in
      TRACE_RESOLV=*) resolv="${kv#TRACE_RESOLV=}" ;;
      TRACE_META=*) meta="${kv#TRACE_META=}" ;;
    esac
  done
  printf '%s\n' "$resolv" > "$tmp/resolv.conf"
  printf '%s\n' "$meta" > "$tmp/c3c-etc/github-meta.json"
  printf '%s\n' alpha.example beta.example > "$tmp/c3c-etc/allowed-domains.txt"
  echo "$ipv6_conf_unwritten" > "$tmp/ipv6-conf/all/disable_ipv6"
  echo "$ipv6_conf_unwritten" > "$tmp/ipv6-conf/default/disable_ipv6"
  local record="$tmp/$name.record" rc
  : > "$record"
  count=$((count + 1))
  set +e
  env PATH="$stubs:$PATH" TRACE_RECORD="$record" "${envs[@]}" \
    bash "$script" "${args[@]}" > "$tmp/$name.out" 2>&1
  rc=$?
  set -e
  echo "rc=$rc" >> "$record"

  local expected="$FIXTURES/$name.expected"
  case "$kind" in
    full)
      if [ "$UPDATE_EXPECTED" = 1 ]; then
        mkdir -p "$FIXTURES"
        cp "$record" "$expected"
      fi
      if [ ! -f "$expected" ]; then
        echo "FAIL: $name: 期待値ファイルがありません: $expected" >&2
        fail=$((fail + 1))
      elif ! diff -u "$expected" "$record" >&2; then
        echo "FAIL: $name: ルールを変える呼び出しの列が期待値と違います（スクリプトの出力: 下）" >&2
        tail -n 5 "$tmp/$name.out" >&2
        fail=$((fail + 1))
      fi
      ;;
    early)
      if [ "$rc" -ne 1 ]; then
        echo "FAIL: $name: rc=1 で止まるべきところ rc=$rc" >&2
        fail=$((fail + 1))
      elif [ "$EXPECT_EARLY_STOP" = 1 ] && [ "$(wc -l < "$record")" -ne 1 ]; then
        echo "FAIL: $name: ルールを 1 つも変えずに止まるべきところ、次の呼び出しがありました" >&2
        sed '$d' "$record" >&2
        fail=$((fail + 1))
      fi
      ;;
  esac
}

no_resolver='nameserver fd00::53'

# 直前のシナリオの後の /proc/sys の IPv6 の予備の無効化の結果（all と default の disable_ipv6）を照合する。
# 既定のモードは 1 を書き、--ipv6 では書かない（初期値の $ipv6_conf_unwritten のまま）。
expect_ipv6_conf() {
  local name="$1" want="$2" got
  got="$(cat "$tmp/ipv6-conf/all/disable_ipv6") $(cat "$tmp/ipv6-conf/default/disable_ipv6")"
  if [ "$got" != "$want $want" ]; then
    echo "FAIL: $name: disable_ipv6 が $want $want のはずが $got" >&2
    fail=$((fail + 1))
  fi
}

# 成功
run_scenario ipv4-resolver full
expect_ipv6_conf ipv4-resolver 1
run_scenario ipv4-no-resolver full -- "TRACE_RESOLV=$no_resolver"
run_scenario ipv4-no-ip6tables full -- TRACE_IP6_LIST_FAIL=1
run_scenario ipv6-resolver full --ipv6
expect_ipv6_conf ipv6-resolver "$ipv6_conf_unwritten"
run_scenario ipv6-no-resolver full --ipv6 -- "TRACE_RESOLV=$no_resolver"
# 途中の失敗の注入（失敗させた呼び出しで記録が終わる）
run_scenario rule-add-fails full -- \
  "TRACE_FAIL_RULE=iptables -A CLAUDE_EGRESS -d 140.82.112.0/20 -p tcp -m multiport --dports 443,22 -j ACCEPT"
run_scenario ip6-drop-fails full -- "TRACE_FAIL_RULE=ip6tables -P INPUT DROP"
run_scenario resolve-fails full -- TRACE_DIG_FAIL=alpha.example
run_scenario ipv6-prepare-fails full --ipv6 -- TRACE_HELPER_FAIL=prepare
# ルールを変える前に止まる
run_scenario bad-meta early -- 'TRACE_META={"web":[]}'
run_scenario no-default-route early -- TRACE_NO_DEFAULT_ROUTE=1
# 自己検証（1 項目だけを期待と逆にする）
run_scenario verify-example-reachable full -- TRACE_VERIFY=example-reachable
run_scenario verify-github443-blocked full -- TRACE_VERIFY=github443-blocked
run_scenario verify-anthropic-blocked full -- TRACE_VERIFY=anthropic-blocked
run_scenario verify-github80-reachable full -- TRACE_VERIFY=github80-reachable
run_scenario ipv6-verify-fails full --ipv6 -- TRACE_HELPER_FAIL=verify

if [ "$fail" -ne 0 ]; then
  echo "FAIL: 照合の失敗 $fail 件（$count シナリオ。disable_ipv6 の照合を含む）" >&2
  exit 1
fi
echo "OK: $count シナリオ"
