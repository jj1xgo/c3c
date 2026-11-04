#!/bin/bash
# test-github-meta-agreement.sh — GitHub meta のスナップショットの検査（#238）
#
# validate-build-input.sh の kind github-meta（ビルド時の検査）が、表の入力に
# 期待どおりの rc を返すことを確かめる。
#
# 表の 1 行は「名前|検証器の期待 rc|init の期待 rc|ファイルの中身」。中身は
# 書いてある文字のまま printf '%s\n' で書く（エスケープを展開しない。\n・\u0000 は
# JSON の文字列のエスケープとしてファイルに入る）。

set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VALIDATOR="$SCRIPT_DIR/validate-build-input.sh"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

CASES=$(cat <<'EOF'
good|0|0|{"web":["192.30.252.0/22","2a0a:a440::/29"],"api":["140.82.112.0/20"],"git":[]}
bounds|0|0|{"web":["255.255.255.255/32","0.0.0.0/0"],"api":[],"git":[]}
no-prefix|0|0|{"web":["0.0.0.0"],"api":[],"git":[]}
extra-key|0|0|{"web":["1.2.3.4/8"],"api":[],"git":[],"hooks":5}
duplicates|0|0|{"web":["1.2.3.4/8"],"api":["1.2.3.4/8"],"git":[]}
empty|1|1|
not-json|1|1|not json
trailing-garbage|1|1|{"web":["1.2.3.4/8"],"api":[],"git":[]} x
array-wrapped|1|1|[{"web":["1.2.3.4/8"],"api":[],"git":[]}]
concat-both-valid|1|1|{"web":["1.2.3.4/8"],"api":[],"git":[]} {"web":["5.6.7.8/32"],"api":[],"git":[]}
missing-key|1|1|{"web":["1.2.3.4/8"],"api":[]}
null-key|1|1|{"web":["1.2.3.4/8"],"api":null,"git":[]}
not-array|1|1|{"web":"1.2.3.4/8","api":[],"git":[]}
non-string|1|1|{"web":[1],"api":["1.2.3.4/8"],"git":[]}
octet-256|1|1|{"web":["256.0.0.0/8","1.2.3.4/8"],"api":[],"git":[]}
prefix-33|1|1|{"web":["1.1.1.1/33","1.2.3.4/8"],"api":[],"git":[]}
leading-zero-octet|1|1|{"web":["010.1.1.1/8"],"api":[],"git":[]}
double-zero-octet|1|1|{"web":["00.1.1.1/8"],"api":[],"git":[]}
leading-zero-prefix|1|1|{"web":["1.2.3.4/08"],"api":[],"git":[]}
no-ipv4|1|1|{"web":[],"api":[],"git":[]}
ipv6-only|1|1|{"web":["2a0a:a440::/29"],"api":[],"git":[]}
spaced-only|1|1|{"web":[" 1.2.3.4/8"],"api":[],"git":[]}
newline-hides-bad|1|1|{"web":["1.2.3.4/8\n300.0.0.0/8"],"api":[],"git":[]}
nul-in-string|1|0|{"web":["1.2.\u00003.4/8"],"api":[],"git":[]}
nul-hides-bad-prefix|1|1|{"web":["1.2.3.4\u0000/40","5.6.7.8/32"],"api":[],"git":[]}
nul-hides-bad-octet|1|1|{"web":["1.2.3.4/8","256.0.\u00000.0/8"],"api":[],"git":[]}
EOF
)
# 注記:
# - newline-hides-bad: JSON の文字列の中の改行。init はコマンド置換の出力を行に
#   分けて 2 行目で止まるので、検証器も行に分けて見る。
# - nul-in-string: init はコマンド置換が NUL を落として 1.2.3.4/8 と読むので通る
#   （実測で rc 0）。検証器は NUL を含む文字列を拒否するので、ここだけ厳しい側に
#   ずれる。NUL を落とすと別の値になる値（下の 2 行）を、検証器が init より緩く
#   通さないための意図したずれ。
# - nul-hides-bad-*: init は NUL を落として範囲外の値として読み止まる。

COUNT=0
FAILS=0

fail() {
  echo "FAIL: $*" >&2
  FAILS=$((FAILS + 1))
}

run_validator() {
  local rc=0
  sh "$VALIDATOR" "$@" >/dev/null 2>&1 || rc=$?
  echo "$rc"
}

while IFS='|' read -r name want_v _want_i content; do
  file="$WORK/$name.json"
  printf '%s\n' "$content" > "$file"
  got=$(run_validator github-meta "$file")
  COUNT=$((COUNT + 1))
  [ "$got" = "$want_v" ] || fail "$name: 検証器 rc=$got (期待 $want_v)"
done <<< "$CASES"

# 検証器の契約（init の列は使わない）。
good="$WORK/good.json"

got=$(run_validator github-meta "$good" "$WORK/outfile")
COUNT=$((COUNT + 1))
if [ "$got" != 2 ] || [ -e "$WORK/outfile" ]; then
  fail "outfile-given: 検証器 rc=$got (期待 2、outfile は作られない)"
fi

got=$(run_validator github-meta "$WORK/missing.json")
COUNT=$((COUNT + 1))
[ "$got" = 2 ] || fail "missing-file: 検証器 rc=$got (期待 2)"

nojq="$WORK/nojq-bin"
mkdir "$nojq"
for tool in sh mktemp rm wc tr cat sed grep dirname; do
  ln -s "$(command -v "$tool")" "$nojq/$tool"
done
got=0
PATH="$nojq" "$nojq/sh" "$VALIDATOR" github-meta "$good" >/dev/null 2>&1 || got=$?
COUNT=$((COUNT + 1))
[ "$got" = 2 ] || fail "no-jq: 検証器 rc=$got (期待 2)"

if [ "$FAILS" -gt 0 ]; then
  echo "失敗: $FAILS / $COUNT 件" >&2
  exit 1
fi
echo "OK: $COUNT 件"
