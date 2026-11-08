#!/bin/bash
# Copilot CLI の command sandboxing（MXC の bubblewrap）用の bwrap の中継。Dockerfile.claude が、
# opt-in（copilot-version.txt に版がある）のときだけ /usr/local/libexec/c3c/copilot-bwrap/bwrap に置き、
# Copilot の起動口（copilot-launcher.sh）がこのディレクトリを PATH の先頭にする。
#
# MXC は必ず `--proc /proc` を bwrap に渡すが、c3c のコンテナでは Podman の /proc のマスクのせいで新しい
# proc のマウントが失敗する（Codex の #140 と同じ原因）。そこで、最初の `--` より前にある、連続する
# `--proc` `/proc` の組だけを `--ro-bind /proc /proc` に替え、外側の /proc を読み取りだけで引き継ぐ。
# 最初の `--` とそれより後ろ（sandbox の中で動くコマンドの引数）は一字も変えない。組が無ければ何も
# 替えずに渡す。MXC に予備の道が入るまでの暫定（README「Copilot CLI を使う」節）。
#
# 本物の bwrap は環境を空にして起動する（bash の組み込み `exec -c`。値を外部コマンドの引数に載せない）。
# Copilot の環境にあるトークンなどの秘密を bwrap に渡さないため。sandbox の中の環境は MXC が --clearenv と
# --setenv で、作業ディレクトリは --chdir で渡すので、bwrap の環境は要らない。
#
# 秘密は読まない。本物の bwrap のパスは環境変数で差し替えられない（readonly、上書き口を作らない）。
# 本物が無ければ、PATH 上のほかの bwrap を探さずに止める（fail-closed）。
set -u

readonly REAL_BWRAP=/usr/bin/bwrap

if [ ! -f "$REAL_BWRAP" ] || [ ! -x "$REAL_BWRAP" ]; then
  echo "ERROR: /usr/bin/bwrap がありません。-b で再ビルドしてください。" >&2
  exit 1
fi

args=()
seen_double_dash=0
while [ "$#" -gt 0 ]; do
  if [ "$seen_double_dash" -eq 0 ]; then
    if [ "$1" = "--" ]; then
      seen_double_dash=1
    elif [ "$1" = "--proc" ] && [ "$#" -ge 2 ] && [ "$2" = "/proc" ]; then
      args+=(--ro-bind /proc /proc)
      shift 2
      continue
    fi
  fi
  args+=("$1")
  shift
done

exec -c "$REAL_BWRAP" "${args[@]}"
