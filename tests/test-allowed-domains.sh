#!/usr/bin/env bash
# 実物の許可ドメイン読込と refresh_domains を検証する。DNS・iptables は実行しない。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/harness" <<'HEAD'
#!/bin/bash
set -euo pipefail
IFS=$'\n\t'
dig() {
  printf '%s\n' "${!#}" >> "$RECORD"
  printf '%s\n' 'fixture. 60 IN A 192.0.2.1'
}
add_or_touch_domain_ip() { :; }
HEAD
sed -n '/^build_domain_list()/,/^}/p; /^refresh_domains()/,/^}/p' "$ROOT/init-firewall.sh" >> "$tmp/harness"
cat >> "$tmp/harness" <<'TAIL'
if [ "$1" = list ]; then
  build_domain_list
else
  # 呼び出し側が終了コードを検査する文脈でも、不正入力を握り潰さない。
  if refresh_domains 1000; then exit 0; else exit 1; fi
fi
TAIL

base=$'api.anthropic.com\nclaude.ai\nconsole.anthropic.com\nstatsig.anthropic.com\nstatsig.com\nsentry.io'
fail=0 count=0
run_case() {
  local label="$1" input="$2" expected_rc="$3" extra="${4:-}" rc=0 expected="$base"
  printf '%b' "$input" > "$tmp/domains"
  [[ -z "$extra" ]] || expected+=$'\n'"$extra"
  ALLOWED_DOMAINS_FILE="$tmp/domains" bash "$tmp/harness" list > "$tmp/out" 2> "$tmp/err" || rc=$?
  count=$((count + 1))
  if [[ "$expected_rc" -eq 0 && "$rc" -eq 0 && "$(cat "$tmp/out")" = "$expected" && ! -s "$tmp/err" ]] ||
     { [[ "$expected_rc" -eq 1 && "$rc" -eq 1 && ! -s "$tmp/out" ]] && grep -q 'ERROR:' "$tmp/err"; }; then
    echo "ok - $label"
  else
    echo "FAIL - $label (rc=$rc)"; cat "$tmp/out" "$tmp/err"; fail=$((fail + 1))
  fi
}

run_case '空ファイルは基本ドメインのみ' '' 0
run_case 'コメントと空白行' '# comment\n \t\r\n  # comment\n' 0
run_case '大文字・数字・ハイフン・最終改行なし' '3A-b.example' 0 '3A-b.example'
run_case '前後空白とCRLF' ' \tapi.example\t \r\n' 0 'api.example'
run_case '末尾ドットと単一ラベル' 'api.example.\ninternal\n' 0 $'api.example.\ninternal'
run_case 'punycode 表記' 'xn--r8jz45g.example\n' 0 'xn--r8jz45g.example'
run_case '行内空白を結合しない' 'evil.com good.com\n' 1
run_case '行内タブを結合しない' 'evil.com\tgood.com\n' 1
run_case '行内コメントは拒否' 'api.example # comment\n' 1
run_case 'NULを落として受理しない' 'api\000.example\n' 1
run_case '途中のCR' 'api\r.example\n' 1
run_case 'CRの重複' 'api.example\r\r\n' 1
run_case '制御文字' 'api\033.example\n' 1
run_case 'URL' 'https://api.example\n' 1
run_case 'wildcard' '*.example\n' 1
run_case 'DNSオプション形' '-f\n' 1
run_case 'DNSサーバー指定形' '@example\n' 1
# shellcheck disable=SC2016
run_case 'シェル式' '$(id).example\n' 1
run_case '非ASCII' '例.example\n' 1
run_case 'ラテン拡張文字' 'caf\303\251.example\n' 1
run_case 'BOM' '\357\273\277api.example\n' 1
run_case '空ラベル' 'api..example\n' 1
run_case '先頭ドット' '.api.example\n' 1
run_case '末尾ドットの重複' 'api.example..\n' 1
run_case 'ラベル先頭ハイフン' 'api.-bad.example\n' 1
run_case 'ラベル末尾ハイフン' 'api.bad-.example\n' 1
run_case 'アンダースコア' '_srv.example\n' 1
run_case '途中の不正行でも部分出力なし' 'good.example\nbad example\n' 1
printf -v label63 '%063d' 0
run_case 'ラベル63文字' "$label63.example" 0 "$label63.example"
run_case 'ラベル64文字' "${label63}0.example" 1
name253="$label63.$label63.$label63.${label63:0:61}"
run_case '全長253文字' "$name253" 0 "$name253"
run_case '末尾ドットを除き全長253文字' "$name253." 0 "$name253."
run_case '全長254文字' "${name253}0" 1

# 不在は任意設定として許容し、存在するが読込対象として不適切なら拒否する。
ln -s "$tmp/missing" "$tmp/dangling"
for kind in missing directory dangling; do
  path="$tmp/$kind"
  [[ "$kind" != directory ]] || mkdir "$path"
  rc=0
  ALLOWED_DOMAINS_FILE="$path" bash "$tmp/harness" list > "$tmp/out" 2> "$tmp/err" || rc=$?
  count=$((count + 1))
  if { [[ "$kind" = missing && "$rc" -eq 0 && "$(cat "$tmp/out")" = "$base" && ! -s "$tmp/err" ]]; } ||
     { [[ "$kind" != missing && "$rc" -eq 1 && ! -s "$tmp/out" ]] && grep -q 'ERROR:' "$tmp/err"; }; then
    echo "ok - 設定ファイル $kind"
  else
    echo "FAIL - 設定ファイル $kind (rc=$rc)"; fail=$((fail + 1))
  fi
done

# 実 refresh_domains への配線: 不正行があれば基本ドメインを含め1件も解決しない。
printf 'good.example\nbad example\n' > "$tmp/domains"
: > "$tmp/record"
rc=0
ALLOWED_DOMAINS_FILE="$tmp/domains" RECORD="$tmp/record" bash "$tmp/harness" refresh > "$tmp/out" 2> "$tmp/err" || rc=$?
count=$((count + 1))
if [[ "$rc" -eq 1 && ! -s "$tmp/record" ]] && grep -q 'ERROR:' "$tmp/err"; then
  echo 'ok - 不正入力はDNS解決前に拒否する'
else
  echo "FAIL - 不正入力がDNS解決へ到達した (rc=$rc)"; fail=$((fail + 1))
fi
printf 'api.example\n' > "$tmp/domains"
: > "$tmp/record"
rc=0
ALLOWED_DOMAINS_FILE="$tmp/domains" RECORD="$tmp/record" bash "$tmp/harness" refresh > "$tmp/out" 2> "$tmp/err" || rc=$?
count=$((count + 1))
if [[ "$rc" -eq 0 && "$(cat "$tmp/record")" = "$base"$'\napi.example' ]]; then
  echo 'ok - 検証済みのリスト全体を解決する'
else
  echo "FAIL - 検証済みリストの解決 (rc=$rc)"; fail=$((fail + 1))
fi
# 世代タグは iptables の comment 領域に完全に収まる必要がある。
cat > "$tmp/comment-harness" <<'HEAD'
#!/bin/bash
set -euo pipefail
CHAIN=TEST
ALLOWED_PORTS=443
iptables() { printf '%s\n' "$@" > "$RECORD"; }
HEAD
sed -n '/^add_cidr_tagged()/,/^}/p' "$ROOT/init-firewall.sh" >> "$tmp/comment-harness"
# shellcheck disable=SC2016
printf '%s\n' 'add_cidr_tagged 192.0.2.1 "$1" "$2"' >> "$tmp/comment-harness"
name233="$label63.$label63.$label63.${label63:0:41}"
for item in '255 1700000000 0' '256 1700000000 1' 'future 17000000000 1'; do
  IFS=' ' read -r label generation expected_rc <<< "$item"
  domain="$name233"
  [[ "$label" != 256 ]] || domain+='0'
  : > "$tmp/record"
  rc=0
  RECORD="$tmp/record" bash "$tmp/comment-harness" "$domain" "$generation" > "$tmp/out" 2> "$tmp/err" || rc=$?
  count=$((count + 1))
  if [[ "$rc" -eq "$expected_rc" ]] &&
     { { [[ "$rc" -eq 0 ]] && grep -qxF "domain=$domain;gen=$generation" "$tmp/record"; } ||
       { [[ "$rc" -eq 1 && ! -s "$tmp/record" ]] && grep -q 'ERROR:' "$tmp/err"; }; }; then
    echo "ok - comment $label"
  else
    echo "FAIL - comment $label (rc=$rc)"; fail=$((fail + 1))
  fi
done
echo "$count cases, $fail failures"
[[ "$fail" -eq 0 ]]
