#!/bin/sh
# check-boundary-files.sh — upgrade の層の前後で、境界のファイルの状態を記録して比べる（#273）
#
# 使い方: check-boundary-files.sh snapshot <記録のファイル> <パス>...
#         check-boundary-files.sh verify   <記録のファイル> <パス>...
#   パスはディレクトリかファイル。ディレクトリはその下を find -xdev で辿る。各エントリを
#   「パス、種類、uid:gid、mode、symlink の先、通常のファイルの sha256」の 1 行にして整列したものを記録する。
#   存在しないパスは「無い」と 1 行書く（後で作られたら違いになる）。
#   verify は記録を作り直して snapshot の記録と比べ、違えば差分の行を出して rc 1。
#
# 終了コード: 0 同じ（snapshot は記録を書けた）、1 違う・記録を読めない・名前に改行がある、2 引数の誤り
#
# Dockerfile.claude の upgrade の RUN が、apt-get update の前に snapshot、upgrade の後に verify を呼ぶ。
# 外部の取得元のパッケージ（#273）や Debian のパッケージのインストールスクリプトが、COPY した後の境界の
# ファイルを書き換えたまま最終のイメージに残る「正直な壊れ方」だけを捕まえる。悪意のある差し替え
# （setpriv・sudo の差し替えなど）は防げない（README「セキュリティモデル」の残余）。
set -eu
export LC_ALL=C

usage() {
  echo "usage: check-boundary-files.sh snapshot|verify <記録のファイル> <パス>..." >&2
  exit 2
}
[ "$#" -ge 3 ] || usage
mode=$1
state=$2
shift 2
case "$mode" in
  snapshot | verify) ;;
  *) usage ;;
esac

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM

# 引数のパスの状態を $1 に書く
record() {
  out=$1
  shift
  : > "$work/raw"
  for p in "$@"; do
    if [ ! -e "$p" ] && [ ! -L "$p" ]; then
      printf '%s\tmissing\n' "$p" >> "$work/raw"
      continue
    fi
    # パス名に改行があると 1 エントリが 2 行に割れ、比べ方が崩れるので拒む
    find "$p" -xdev -name '*
*' > "$work/nl"
    if [ -s "$work/nl" ]; then
      echo "ERROR: 改行を含む名前があります（$p の下）" >&2
      return 1
    fi
    find "$p" -xdev \( -type d -o -type f -o -type l \) -printf '%p\t%y\t%U:%G\t%m\t%l\n' > "$work/entries"
    while IFS="$(printf '\t')" read -r path type owner perm target; do
      sum=-
      if [ "$type" = f ]; then
        sum=$(sha256sum < "$path") || return 1
        sum=${sum%% *}
      fi
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$path" "$type" "$owner" "$perm" "$target" "$sum" >> "$work/raw"
    done < "$work/entries"
  done
  sort "$work/raw" > "$out"
}

if [ "$mode" = snapshot ]; then
  record "$work/now" "$@" || exit 1
  cp "$work/now" "$state"
  exit 0
fi

if [ ! -f "$state" ] || [ ! -r "$state" ]; then
  echo "ERROR: 境界のファイルの記録を読めません: $state" >&2
  exit 1
fi
record "$work/now" "$@" || exit 1
if ! cmp -s "$state" "$work/now"; then
  echo "ERROR: upgrade の層で境界のファイルが変わりました（< 前、> 後）:" >&2
  diff "$state" "$work/now" >&2 || true
  exit 1
fi
