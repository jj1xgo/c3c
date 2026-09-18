#!/bin/bash
# 集約 lint target: bash -n + shellcheck + podman compose config をまとめて実行する。
# 対象の bash スクリプトは git ls-files（追跡済み + 未追跡。gitignore 対象は除く）+
# shebang 判定で動的に決定する
# （ハードコードのファイルリストを持たない — 追加/削除時のリスト同期漏れを構造的に防ぐ）。
# LINT_SKIP_COMPOSE=1 を与えると podman compose config の検証だけを WARNING 付きで
# スキップする（Compose を実行できない環境での明示的な省略用）。
set -uo pipefail

cd "$(dirname "$0")" || exit 1

if ! command -v shellcheck >/dev/null 2>&1; then
  echo "ERROR: shellcheck が見つかりません。sudo apt-get install shellcheck でインストールしてください。" >&2
  exit 1
fi

# コンテナ内は LANG・LC_ALL とも未設定で、shellcheck が日本語を含む行を出力しようとすると
# "commitBuffer: invalid argument" で途中で切れる（claude-container#123）。ロケールが
# 未指定のときだけ UTF-8 を補う。LC_ALL は LC_CTYPE を含む全カテゴリを上書きしてしまうため
# 使わず、文字コードだけに効く LC_CTYPE を補う（利用者の LC_CTYPE 個別指定を上書きしない）。
if [ -z "${LC_ALL:-}" ] && [ -z "${LC_CTYPE:-}" ] && [ -z "${LANG:-}" ]; then
  export LC_CTYPE=C.UTF-8
fi

# 検査ツールの版を表示し、CI（.github/workflows/ci.yml）の固定版と違えば WARNING を出す。
# 版差で指摘の有無が変わる（0.10.0 の SC2317 と 0.11.0 の SC2329 等）ため、NG の原因の
# 切り分けを早くする目的で、失敗にはしない（claude-container#123）。
shellcheck_version=$(shellcheck --version | awk '/^version:/ { print $2 }')
ci_shellcheck_version=$(sed -nE 's/^[[:space:]]*SHELLCHECK_VERSION:[[:space:]]*"([^"]+)".*/\1/p' \
  .github/workflows/ci.yml 2>/dev/null | head -n 1)
echo "shellcheck ${shellcheck_version:-不明}"
if [ -n "$ci_shellcheck_version" ] && [ "$shellcheck_version" != "$ci_shellcheck_version" ]; then
  echo "WARNING: shellcheck の版（${shellcheck_version:-不明}）が CI の固定版（$ci_shellcheck_version）と異なります。版差で指摘が増減することがあります（claude-container#123）。" >&2
fi

status=0

bash_scripts=()
sh_scripts=()
while IFS= read -r f; do
  [ -f "$f" ] || continue
  first_line=$(head -n1 "$f" 2>/dev/null)
  if printf '%s' "$first_line" | grep -qE '^#!/bin/bash|^#!/usr/bin/env bash'; then
    bash_scripts+=("$f")
  elif printf '%s' "$first_line" | grep -qE '^#!/bin/sh'; then
    sh_scripts+=("$f")
  fi
done < <(git ls-files -co --exclude-standard)

# .claude/ は別途管理される場合がある
# （メンテナのローカル環境限定。第三者のクローンには存在せず何もしない）。
if [ -d .claude/.git ]; then
  while IFS= read -r f; do
    [ -f ".claude/$f" ] || continue
    first_line=$(head -n1 ".claude/$f" 2>/dev/null)
    if printf '%s' "$first_line" | grep -qE '^#!/bin/bash|^#!/usr/bin/env bash'; then
      bash_scripts+=(".claude/$f")
    elif printf '%s' "$first_line" | grep -qE '^#!/bin/sh'; then
      sh_scripts+=(".claude/$f")
    fi
  done < <(git -C .claude ls-files -co --exclude-standard)
fi

scripts=("${bash_scripts[@]}" "${sh_scripts[@]}")

if [ "${#scripts[@]}" -eq 0 ]; then
  echo "ERROR: 対象のスクリプトが1つも見つかりません（git ls-files + shebang 判定）。" >&2
  exit 1
fi

echo "対象スクリプト (${#scripts[@]}):"
printf '  %s\n' "${scripts[@]}"

for f in "${bash_scripts[@]}"; do
  bash -n "$f" || status=1
done
for f in "${sh_scripts[@]}"; do
  sh -n "$f" || status=1
done

shellcheck "${scripts[@]}" || status=1

if [ "${LINT_SKIP_COMPOSE:-}" = "1" ]; then
  echo "WARNING: LINT_SKIP_COMPOSE=1 のため compose config 検証をスキップしました。" >&2
elif command -v podman >/dev/null 2>&1; then
  podman compose -f compose.yml config >/dev/null || status=1
  podman compose -f compose.yml -f compose.ipv6.yml config >/dev/null || status=1
  # plugin 別名 override（claude-container#98）。destination は launcher が export するので
  # lint ではダミー値を与える。3 ファイル同時のマージで別名 volume と IPv6 の network・
  # sysctls・environment が消えないことも見る（override 同士の上書きの検出）。
  CLAUDE_PLUGINS_HOST_PATH=/tmp/lint-plugins-alias \
    podman compose -f compose.yml -f compose.plugins-alias.yml config >/dev/null || status=1
  if merged=$(CLAUDE_PLUGINS_HOST_PATH=/tmp/lint-plugins-alias \
      podman compose -f compose.yml -f compose.ipv6.yml -f compose.plugins-alias.yml config); then
    # 値の引用符は provider 依存（podman-compose は '1'、docker compose は "1"）なので両方を許す。
    q="['\"]?"
    for needle in '/tmp/lint-plugins-alias' 'fe80::1' \
        "net\.ipv6\.conf\.all\.disable_ipv6: ${q}0${q}" "CLAUDE_CONTAINER_IPV6: ${q}1${q}"; do
      grep -qE -- "$needle" <<<"$merged" \
        || { echo "ERROR: compose の 3 ファイル同時 config に '$needle' がありません（override のマージで消えています）" >&2; status=1; }
    done
  else
    status=1
  fi
  # ${CLAUDE_PLUGINS_HOST_PATH:?} の fail-closed 検査（claude-container#98）。launcher は
  # 別名 override を選ぶとき必ず export するが、compose provider によっては :? が空文字を
  # 通す可能性があるため、未設定・空文字の両方で config が失敗することを直接確認する。
  # ホスト実測（podman-compose 1.6.0）ではどちらも rc=1。provider が通してしまう場合は
  # override のコメントどおり launcher の無条件 export が唯一のガードになるため、この
  # 検査は WARNING へ格下げすべき変更点として扱う（現時点では ERROR のまま fail-closed）。
  # shellcheck disable=SC2016 # 意図的にリテラル表示（変数展開ではなく compose 変数名の文字列）
  compose_var_literal='${CLAUDE_PLUGINS_HOST_PATH:?}'
  if env -u CLAUDE_PLUGINS_HOST_PATH \
      podman compose -f compose.yml -f compose.plugins-alias.yml config >/dev/null 2>&1; then
    printf 'ERROR: compose.plugins-alias.yml の %s が未設定を通しています（provider が :? を強制していません）\n' \
      "$compose_var_literal" >&2
    status=1
  fi
  if CLAUDE_PLUGINS_HOST_PATH="" \
      podman compose -f compose.yml -f compose.plugins-alias.yml config >/dev/null 2>&1; then
    printf 'ERROR: compose.plugins-alias.yml の %s が空文字を通しています（provider が :? を強制していません）\n' \
      "$compose_var_literal" >&2
    status=1
  fi
  # 指示ファイル・スキルの追加共有 override（claude-container#99）。source と destination は
  # launcher が export するので lint ではダミー値を与える。6 ファイル同時のマージで plugin 別名・
  # IPv6・3 本の別名 volume が消えないことも見る。
  SHARED_MOUNT=/tmp CLAUDE_SHARED_HOME_PATH=/home/node/lint-shared-home \
    podman compose -f compose.yml -f compose.shared-home.yml config >/dev/null || status=1
  SHARED_MOUNT=/tmp CLAUDE_SHARED_HOST_PATH=/tmp/lint-shared-host \
    podman compose -f compose.yml -f compose.shared-host.yml config >/dev/null || status=1
  AGENTS_DIR=/tmp \
    podman compose -f compose.yml -f compose.agents.yml config >/dev/null || status=1
  if merged=$(CLAUDE_PLUGINS_HOST_PATH=/tmp/lint-plugins-alias SHARED_MOUNT=/tmp \
      CLAUDE_SHARED_HOME_PATH=/home/node/lint-shared-home CLAUDE_SHARED_HOST_PATH=/tmp/lint-shared-host AGENTS_DIR=/tmp \
      podman compose -f compose.yml -f compose.ipv6.yml -f compose.plugins-alias.yml \
        -f compose.shared-home.yml -f compose.shared-host.yml -f compose.agents.yml config); then
    for needle in '/tmp/lint-plugins-alias' 'fe80::1' '/home/node/lint-shared-home' '/tmp/lint-shared-host' '/home/node/\.agents'; do
      grep -qE -- "$needle" <<<"$merged" \
        || { echo "ERROR: compose の 6 ファイル同時 config に '$needle' がありません（override のマージで消えています）" >&2; status=1; }
    done
  else
    status=1
  fi
  # ${VAR:?} の fail-closed 検査（#98 の CLAUDE_PLUGINS_HOST_PATH と同じ理由）。
  for pair in compose.shared-home.yml:CLAUDE_SHARED_HOME_PATH compose.shared-host.yml:CLAUDE_SHARED_HOST_PATH compose.agents.yml:AGENTS_DIR; do
    file="${pair%%:*}"
    var="${pair#*:}"
    # shellcheck disable=SC2016 # 意図的にリテラル表示（変数展開ではなく compose 変数名の文字列）
    var_literal='${'"$var"':?}'
    if env -u "$var" SHARED_MOUNT=/tmp podman compose -f compose.yml -f "$file" config >/dev/null 2>&1; then
      printf 'ERROR: %s の %s が未設定を通しています（provider が :? を強制していません）\n' "$file" "$var_literal" >&2
      status=1
    fi
    if env "$var=" SHARED_MOUNT=/tmp podman compose -f compose.yml -f "$file" config >/dev/null 2>&1; then
      printf 'ERROR: %s の %s が空文字を通しています（provider が :? を強制していません）\n' "$file" "$var_literal" >&2
      status=1
    fi
  done
else
  echo "WARNING: podman が見つからないため compose config 検証をスキップしました（コンテナ内開発時は想定内）。" >&2
fi

# bytecode を生成せず Python の構文を確認する。
python3 - <<'PYTHON' || status=1
from pathlib import Path
for path in [*Path('.').glob('*.py'), *Path('tests').glob('*.py')]:
    compile(path.read_text(), str(path), 'exec')
PYTHON

if [ "$status" -eq 0 ]; then
  echo "lint OK"
else
  echo "lint NG: 上記の違反を解消してください。" >&2
fi
exit "$status"
