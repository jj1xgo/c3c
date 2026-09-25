#!/bin/bash
# Codex の起動口（#152）。Dockerfile.claude がこのファイルで npm の symlink /usr/local/bin/codex を置き換える
# （opt-out のときは置かない）。名前で呼ばれる codex（Claude 経路の Bash ツール、ログインシェル、podman exec、
# entrypoint.sh の Codex 経路の CODEX_CLI）はすべてここを通る。Codex の Linux sandbox は PATH 上で最初に
# 見つかった bwrap を使うので、Codex 同梱 bubblewrap の固定リンクの置き場（#145）を PATH の先頭にしてから
# 実体の codex.js を exec する。PATH が変わるのは exec した Codex とその子孫だけで、呼び出し元（Claude 本体
# など）の PATH と、そこから名前で呼ぶ bwrap（/usr/bin/bwrap）は変わらない。
# 秘密は読まない。固定パスは環境変数で差し替えられない（readonly、上書き口を作らない）。
set -u

readonly CODEX_BWRAP_DIR=/usr/local/libexec/c3c/codex-bwrap
readonly CODEX_JS=/usr/local/lib/node_modules/@openai/codex/bin/codex.js

# 上流の PATH 探索は、存在しない・実行できない候補を飛ばして次の候補（システム版 /usr/bin/bwrap）を
# 黙って選ぶ。それを止める fail-closed で、entrypoint.sh の Codex 経路の検査と同じ文言にする。外さない。
if [ ! -f "$CODEX_BWRAP_DIR/bwrap" ] || [ ! -x "$CODEX_BWRAP_DIR/bwrap" ]; then
  echo "ERROR: Codex 同梱の bubblewrap がありません。-b で再ビルドしてください。" >&2
  exit 1
fi

# 先頭が既に同梱ディレクトリなら PATH を一字も変えない（entrypoint の Codex 経路が足した PATH を、
# snapshot・verify・本起動と同じまま渡す）。空・未設定の PATH では末尾に空要素（= カレント
# ディレクトリ）を作らない。環境に PATH が無いと bash は `.` を含む既定値を export せずに持つので、
# export されていない PATH は未設定として扱い、既定値を Codex へ渡さない。
path_in=""
if [[ "$(declare -p PATH 2>/dev/null)" == "declare -x "* ]]; then
  path_in="$PATH"
fi
case "$path_in" in
  "$CODEX_BWRAP_DIR" | "$CODEX_BWRAP_DIR":*) ;;
  "") export PATH="$CODEX_BWRAP_DIR" ;;
  *) export PATH="$CODEX_BWRAP_DIR:$path_in" ;;
esac

exec "$CODEX_JS" "$@"
