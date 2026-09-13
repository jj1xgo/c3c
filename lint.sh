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
else
  echo "WARNING: podman が見つからないため compose config 検証をスキップしました（コンテナ内開発時は想定内）。" >&2
fi

# bytecode を生成せず Python の構文を確認する。
python3 - <<'PYTHON' || status=1
from pathlib import Path
for path in [Path('ipv6-firewall.py'), *Path('tests').glob('test_ipv6_*.py')]:
    compile(path.read_text(), str(path), 'exec')
PYTHON

if [ "$status" -eq 0 ]; then
  echo "lint OK"
else
  echo "lint NG: 上記の違反を解消してください。" >&2
fi
exit "$status"
