#!/bin/sh
# install-apt-sources.sh — 外部の APT 取得元の鍵を取り、主鍵の指紋の集合で照合してから、鍵と取得元を置く（#273）
#
# 使い方: install-apt-sources.sh <正規化済みの apt-sources のファイル>
#   入力は validate-build-input.sh apt-sources の出力（1 行 1 取得元、半角空白区切り:
#   <名前> <鍵の URL> <主鍵の指紋>[,<主鍵の指紋>...] <URI> <suite> <component>...）。
#   Dockerfile.claude が 2 か所から呼ぶ: packages.txt の層の直前（初回の導入）と、-b のたびに作り直す
#   upgrade の層の中（鍵の取り直し。提供元が鍵を替えても、キャッシュに残った古い鍵で止まらないため）。
#
# 終了コード: 0 成功（入力が空なら何もしない）、1 取得・照合・書き込みの失敗、2 引数の誤り
#
# 照合の規則（持ち主の判断、2026-11-15）: 取った鍵束の主鍵の指紋の集合が、宣言した集合と完全に一致する
# ときだけ通す（足りない・余分がある、どちらも止める）。鍵は形式（ASCII armor かバイナリか）によらず、
# 取得元ごとの空の鍵束に import し、宣言した指紋だけを export して置く。export した鍵にも同じ照合を
# かけ直す（gpg が読み飛ばす鍵が元のファイルにあっても、apt に渡すのは照合した鍵だけにするため）。
# 全行の照合が通ってから初めて書く（途中で止めたとき、前回の鍵と取得元を半端に書き換えない）。
#
# 照合するのは宣言した取得元の鍵まで。パッケージがインストールのときに自分で足す取得元と鍵（Google Chrome の
# google-chrome.sources など）は照合の外で、消さない（README「利用側プロジェクトの設定」）。
#
# 置き場と所有者は固定で、環境変数では変えられない（readonly。試験は文字列を置換する）。
set -eu
readonly KEYRING_DIR=/etc/apt/keyrings
readonly SOURCES_DIR=/etc/apt/sources.list.d
readonly INSTALL_OWNER=root:root
export LC_ALL=C

if [ "$#" -ne 1 ]; then
  echo "usage: install-apt-sources.sh <正規化済みの apt-sources のファイル>" >&2
  exit 2
fi
in=$1
if [ ! -f "$in" ] || [ ! -r "$in" ]; then
  echo "ERROR: $in を読めません" >&2
  exit 1
fi
[ -s "$in" ] || exit 0

if ! command -v gpg >/dev/null 2>&1; then
  # 指紋を読むのに gpg が要る。入れた gnupg は消さない（利用側が packages.txt で求めていることがある）
  apt-get update || { echo "ERROR: gnupg を入れるための apt-get update に失敗しました" >&2; exit 1; }
  apt-get install -y --no-install-recommends gnupg || { echo "ERROR: gnupg を入れられません" >&2; exit 1; }
fi

work=$(mktemp -d)
cleanup() {
  for h in "$work"/home-*; do
    [ -d "$h" ] && GNUPGHOME=$h gpgconf --kill all >/dev/null 2>&1
  done
  rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

# $1 の鍵ファイルの主鍵の指紋（pub の直後の fpr）を、整列して $2 に書く。読めなければ rc 1
primaries() {
  GNUPGHOME="$work/home-show" gpg --batch --show-keys --with-colons "$1" > "$work/colons" 2>/dev/null || return 1
  awk -F: '$1 == "fpr" && prev == "pub" { print $10 } { prev = $1 }' "$work/colons" > "$work/fprs" || return 1
  sort -u "$work/fprs" > "$2" || return 1
}

mkdir -m 700 "$work/home-show"
n=0
: > "$work/plan"
while IFS=' ' read -r name keyurl fprs uri suite comps || [ -n "${name:-}" ]; do
  case "$name" in
    '' | *[!a-z0-9-]*) echo "ERROR: 取得元の名前が不正です: $name" >&2; exit 1 ;;
  esac
  n=$((n + 1))
  key="$work/$name.key"
  if ! curl -fsSL --proto =https --proto-redir =https --tlsv1.2 --max-time 60 --max-filesize 1048576 \
      -o "$key" "$keyurl"; then
    echo "ERROR: $name の鍵を取得できません（$keyurl）" >&2
    exit 1
  fi
  printf '%s\n' "$fprs" > "$work/declared.raw"
  tr ',' '\n' < "$work/declared.raw" > "$work/declared.lines"
  sort -u "$work/declared.lines" > "$work/declared"
  if ! primaries "$key" "$work/got"; then
    echo "ERROR: $name の鍵を読めません（$keyurl）" >&2
    exit 1
  fi
  if ! cmp -s "$work/declared" "$work/got"; then
    echo "ERROR: $name の鍵の指紋が一致しません（宣言: $(tr '\n' ' ' < "$work/declared")/ 取得: $(tr '\n' ' ' < "$work/got")）" >&2
    exit 1
  fi
  home="$work/home-$name"
  mkdir -m 700 "$home"
  if ! GNUPGHOME=$home gpg --batch --quiet --import "$key" 2>/dev/null; then
    echo "ERROR: $name の鍵を読めません（$keyurl）" >&2
    exit 1
  fi
  # 宣言した指紋だけを書き出す（tr の出力は引数に分けて渡す。指紋は検査済みの 40 桁の英数字）
  # shellcheck disable=SC2046  # 指紋ごとに 1 つの引数に分けるため。値は [0-9A-F] だけで空白や glob を含まない
  if ! GNUPGHOME=$home gpg --batch --export $(cat "$work/declared") > "$work/$name.gpg"; then
    echo "ERROR: $name の鍵を書き出せません" >&2
    exit 1
  fi
  if ! primaries "$work/$name.gpg" "$work/exported" || ! cmp -s "$work/declared" "$work/exported"; then
    echo "ERROR: $name の鍵の指紋が一致しません（書き出した鍵）" >&2
    exit 1
  fi
  printf 'deb [signed-by=%s/c3c-%s.gpg] %s %s %s\n' "$KEYRING_DIR" "$name" "$uri" "$suite" "$comps" > "$work/$name.list"
  printf '%s\n' "$name" >> "$work/plan"
done < "$in"

owner=${INSTALL_OWNER%%:*}
group=${INSTALL_OWNER#*:}
install -d -o "$owner" -g "$group" -m 0755 "$KEYRING_DIR" "$SOURCES_DIR"
placed=0
while IFS= read -r name; do
  install -o "$owner" -g "$group" -m 0644 "$work/$name.gpg" "$KEYRING_DIR/c3c-$name.gpg"
  install -o "$owner" -g "$group" -m 0644 "$work/$name.list" "$SOURCES_DIR/c3c-$name.list"
  placed=$((placed + 1))
  echo "INFO: $name の鍵を照合して置きました" >&2
done < "$work/plan"

if [ "$placed" -ne "$n" ]; then
  echo "ERROR: 置いた取得元の数（$placed）が宣言の数（$n）と違います" >&2
  exit 1
fi
