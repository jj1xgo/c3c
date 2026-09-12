#!/bin/bash -p
# GIT_ASKPASS ヘルパー。github.com 宛の Username/Password プロンプトにのみ、
# ファイルから just-in-time で応答する。それ以外は fail-closed（exit 1）。
# ホスト判定はクォートで囲まれた URL 全体への正規表現アンカーで行い、
# 'https://github.com.evil.com' のような前方一致すり抜けを防ぐ。
#
# 実行環境の正規化（claude-container#43）: bash は起動時に BASH_ENV・環境由来の
# シェル関数を読み、これらは本ヘルパーの挙動を呼び出し側から差し替えられるため、
# 本体に入る前に環境を捨てて自己再実行する。shebang の -p は BASH_ENV・ENV・
# 環境由来の関数・SHELLOPTS を無視させ、env -i は再実行後の PATH を固定する。
# ローダの入力（LD_PRELOAD 等）はこの再実行では閉じない — カーネルが shebang の
# bash をロードする時点で作用するため。ただしそれを差し替えられるのはコンテナ内で
# コード実行を得た主体だけで、その主体はトークンを直読できる（secrets は node:node 0700）。
# 再実行の判定に環境変数を使わないのは、攻撃者がそれを立てて回避できるため。
# 再実行先を "$0" にするのは、パスをハードコードするとコピーを起動しただけで
# 実物のヘルパー（実トークンを読む）が走ってしまうため。argv[0] を制御できる者は
# もともと任意引数で直接起動できるので、境界は弱まらない。
set -euo pipefail

if [ "${1-}" != "--sanitized-env" ]; then
  exec /usr/bin/env -i PATH=/usr/bin:/bin /bin/bash -p -- \
    "$0" --sanitized-env "$@"
fi
shift

prompt="$1"
token_file=/home/node/.config/claude-container/secrets/GITHUB_MAIN_PAT
github_host_re="^https://(x-access-token@)?github\.com(/.*)?\$"

case "$prompt" in
  Username\ for\ *)
    url=$(printf '%s' "$prompt" | sed -n "s/^Username for '\\(.*\\)': *\$/\\1/p")
    [[ "$url" =~ $github_host_re ]] || exit 1
    printf '%s\n' "x-access-token"
    ;;
  Password\ for\ *)
    url=$(printf '%s' "$prompt" | sed -n "s/^Password for '\\(.*\\)': *\$/\\1/p")
    [[ "$url" =~ $github_host_re ]] || exit 1
    [ -f "$token_file" ] || exit 1
    printf '%s\n' "$(tr -d '\n\r' <"$token_file")"
    ;;
  *)
    exit 1
    ;;
esac
