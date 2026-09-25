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

# compose config の provider 差を扱う検査（c3c 第1段階）。podman-compose は volume を短縮表記
# （`- src:target:ro`）のまま出し、docker compose は long syntax（`type/source/target/read_only`）へ
# 正規化する。tty/stdin_open も provider により false が省略される。文字列一致ではなく
# 「対象 mount が読み取り専用」「TTY と stdin が無効」という意味で検査する。stdin に config を渡す。
# python3 標準ライブラリだけを使う（PyYAML 等は CI に無い）。tests/test-lint-compose-checks.sh が
# `sed -n '/^compose_mount_is_ro()/,/^}/p'` 等で関数定義だけを抽出して検証する（開始行と終了行の形を変えない）。
compose_mount_is_ro() {
  # config は stdin から受けるので、script は -c で渡す（stdin を heredoc に取られない）。
  local script
  script=$(cat <<'PYTHON'
import re
import sys

target = re.escape(sys.argv[1])
lines = sys.stdin.read().splitlines()
found = False
ro = False


def indent_of(line):
    return len(line) - len(line.lstrip(' '))


for index, line in enumerate(lines):
    short = re.match(r'^\s*-\s*[^\s]+?:' + target + r'(?::([^\s]+))?\s*$', line)
    if short:
        found = True
        options = (short.group(1) or '').split(',')
        if 'ro' in options:
            ro = True
        continue
    long_form = re.match(r'^(\s*)(-\s*)?target:\s*' + target + r'\s*$', line)
    if not long_form:
        continue
    found = True
    key_indent = indent_of(line) + (len(long_form.group(2)) if long_form.group(2) else 0)
    # 同じ list 要素の範囲: 上は要素の先頭（`- ` で始まり dash の indent が key より浅い行）まで、
    # 下は次の要素の先頭か、より浅い indent の行まで。
    start = index
    while start > 0:
        current = lines[start]
        if current.lstrip(' ').startswith('- ') and indent_of(current) < key_indent:
            break
        if current.strip() and indent_of(current) < key_indent:
            break
        start -= 1
    end = index + 1
    while end < len(lines):
        current = lines[end]
        if current.strip() and (indent_of(current) < key_indent
                                or (current.lstrip(' ').startswith('- ') and indent_of(current) < key_indent + 1)):
            break
        end += 1
    block = lines[start:end]
    if any(re.match(r'^\s*(-\s*)?read_only:\s*[\'"]?true[\'"]?\s*$', item) for item in block):
        ro = True
if not found:
    print('ERROR: compose config に対象の mount がありません: ' + sys.argv[1], file=sys.stderr)
    sys.exit(1)
if not ro:
    print('ERROR: compose config で対象の mount が読み取り専用ではありません: ' + sys.argv[1], file=sys.stderr)
    sys.exit(1)
PYTHON
  )
  python3 -I -c "$script" "$1"
}

# 検査用 override のマージ結果で TTY と stdin が無効であること。provider が false を省略しても
# 「true が無い」ことで判定する。基本 compose.yml 単体には tty: true があるので、対照として
# 同じ関数が失敗することを lint 本体で確認する。
compose_tty_disabled() {
  local violations
  violations=$(grep -nE '^\s*(tty|stdin_open):\s*['"'"'"]?true['"'"'"]?\s*$' || true)
  if [ -n "$violations" ]; then
    printf 'ERROR: compose config に TTY/stdin の有効化が残っています:\n%s\n' "$violations" >&2
    return 1
  fi
  return 0
}

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
  # launcher が export するので lint ではダミー値を与える。7 ファイル同時のマージで plugin 別名・
  # IPv6・3 本の指示ファイル別名 volume・Codex キャッシュが消えないことも見る。
  SHARED_MOUNT=/tmp CLAUDE_SHARED_HOME_PATH=/home/node/lint-shared-home \
    podman compose -f compose.yml -f compose.shared-home.yml config >/dev/null || status=1
  SHARED_MOUNT=/tmp CLAUDE_SHARED_HOST_PATH=/tmp/lint-shared-host \
    podman compose -f compose.yml -f compose.shared-host.yml config >/dev/null || status=1
  AGENTS_DIR=/tmp \
    podman compose -f compose.yml -f compose.agents.yml config >/dev/null || status=1
  # ホストの Codex plugin キャッシュ共有。target の :ro を provider の出力形式に依らず意味で検査する。
  if merged=$(C3C_CODEX_PLUGINS_SOURCE=/tmp podman compose -f compose.yml -f compose.codex-plugins.yml config); then
    compose_mount_is_ro /home/node/.codex/plugins/cache <<<"$merged" || status=1
  else
    status=1
  fi
  # Codex の検査用 override（c3c 第1段階）。tty / stdin_open だけを false にし、他は本起動と同じ。
  # 承認記録の :ro と TTY/stdin 無効は provider の出力形式（短縮 / long syntax、false の省略）に
  # 依らず意味で検査する（compose_mount_is_ro / compose_tty_disabled）。
  if base=$(podman compose -f compose.yml config); then
    for target in /etc/claude-container/codex-mcp-approved.json /etc/claude-container/mcp-approved-hash /home/node/.gitconfig; do
      compose_mount_is_ro "$target" <<<"$base" || status=1
    done
    grep -qE '^\s*CC_CODEX_START_MODE:' <<<"$base" \
      || { echo "ERROR: compose.yml の environment に CC_CODEX_START_MODE がありません" >&2; status=1; }
    # 対照: 基本構成は TTY 有効なので、同じ検査が失敗しなければ検査自体が空振りしている。
    if compose_tty_disabled <<<"$base" 2>/dev/null; then
      echo "ERROR: compose.yml 単体の config に tty: true が無く、compose_tty_disabled の検査が空振りしています" >&2
      status=1
    fi
  else
    status=1
  fi
  if merged=$(podman compose -f compose.yml -f compose.codex-preflight.yml config); then
    compose_tty_disabled <<<"$merged" || status=1
    compose_mount_is_ro /etc/claude-container/codex-mcp-approved.json <<<"$merged" || status=1
  else
    status=1
  fi
  if merged=$(CLAUDE_PLUGINS_HOST_PATH=/tmp/lint-plugins-alias SHARED_MOUNT=/tmp \
      CLAUDE_SHARED_HOME_PATH=/home/node/lint-shared-home CLAUDE_SHARED_HOST_PATH=/tmp/lint-shared-host AGENTS_DIR=/tmp C3C_CODEX_PLUGINS_SOURCE=/tmp \
      podman compose -f compose.yml -f compose.ipv6.yml -f compose.plugins-alias.yml \
        -f compose.shared-home.yml -f compose.shared-host.yml -f compose.agents.yml -f compose.codex-plugins.yml config); then
    # 部分一致だと /home/node/.agents-x のような別の target でも通るので、mount は target の完全一致で
    # 意味を見る（compose_mount_is_ro）。IPv6 は mount ではないので network_mode の行を行頭と行末で照合する（#112）。
    for target in /tmp/lint-plugins-alias /home/node/lint-shared-home /tmp/lint-shared-host /home/node/.agents /home/node/.codex/plugins/cache; do
      compose_mount_is_ro "$target" <<<"$merged" \
        || { echo "ERROR: compose の 7 ファイル同時 config に :ro の '$target' がありません（override のマージで消えています）" >&2; status=1; }
    done
    grep -qE -- "^[[:space:]]*network_mode:[[:space:]]*['\"]?pasta:-g,fe80::1['\"]?[[:space:]]*\$" <<<"$merged" \
      || { echo "ERROR: compose の 7 ファイル同時 config に IPv6 の network_mode がありません（override のマージで消えています）" >&2; status=1; }
  else
    status=1
  fi
  # ${VAR:?} の fail-closed 検査（#98 の CLAUDE_PLUGINS_HOST_PATH と同じ理由）。
  for pair in compose.shared-home.yml:CLAUDE_SHARED_HOME_PATH compose.shared-host.yml:CLAUDE_SHARED_HOST_PATH compose.agents.yml:AGENTS_DIR compose.codex-plugins.yml:C3C_CODEX_PLUGINS_SOURCE; do
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
