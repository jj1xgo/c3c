#!/usr/bin/env bash
# lint.sh の ruff の検査（run_ruff_check と、その lint 本体への配線）を、偽の ruff で検証する。
# 実 ruff は起動しない。harness の PATH は試験用のディレクトリだけにするので、
# ruff が入っている環境（コンテナの /usr/bin/ruff など）でも「ruff が無い」ケースが本物を拾わない（#264）。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/empty"

{
  printf '#!/bin/bash\nset -uo pipefail\n'
  sed -n '/^run_ruff_check()/,/^}/p' "$ROOT/lint.sh"
  printf 'run_ruff_check "$@"\n'
} > "$tmp/harness"

# 偽の ruff。--version は FAKE_VER が空なら何も出さずに 0、check は引数を 1 行ずつ argv に書いて FAKE_RC で終わる。
cat > "$tmp/bin/ruff" <<FAKE
#!/bin/bash
case "\$1" in
  --version) [ -z "\${FAKE_VER:-}" ] || echo "ruff \$FAKE_VER"; exit 0 ;;
  check) shift; printf '%s\n' check "\$@" > "$tmp/argv"; exit "\${FAKE_RC:-0}" ;;
esac
exit 99
FAKE
chmod +x "$tmp/bin/ruff"

fail=0 count=0
RC=0
# run_harness <ruff: yes|no> <require: unset|値> <FAKE_VER> <FAKE_RC> <CI 版> [ファイル...]
run_harness() {
  local has_ruff="$1" require="$2" ver="$3" frc="$4" ci="$5"
  shift 5
  local path="$tmp/empty"
  [[ "$has_ruff" == yes ]] && path="$tmp/bin"
  local envs=("PATH=$path" "FAKE_VER=$ver" "FAKE_RC=$frc")
  [[ "$require" == unset ]] || envs+=("LINT_REQUIRE_RUFF=$require")
  rm -f "$tmp/argv"
  RC=0
  env -i "${envs[@]}" /bin/bash "$tmp/harness" "$ci" "$@" > "$tmp/out" 2> "$tmp/err" || RC=$?
}
rc_is() { [[ "$RC" -eq "$1" ]]; }
out_has() { grep -qF -- "$1" "$tmp/out"; }
err_has() { grep -qF -- "$1" "$tmp/err"; }
err_empty() { [[ ! -s "$tmp/err" ]]; }
no_argv() { [[ ! -e "$tmp/argv" ]]; }
argv_is() { [[ -e "$tmp/argv" && "$(cat "$tmp/argv")" == "$(printf '%s\n' "$@")" ]]; }
check() {
  local name="$1" cond="$2"
  count=$((count + 1))
  if eval "$cond"; then
    echo "ok - $name"
  else
    echo "FAIL - $name (rc=$RC)"; cat "$tmp/out" "$tmp/err"; fail=$((fail + 1))
  fi
}

run_harness no unset '' 0 0.16.4 ./a.py
check missing_not_required 'rc_is 0 && err_has "WARNING:" && err_has ruff && no_argv'
run_harness no 1 '' 0 0.16.4 ./a.py
check missing_required 'rc_is 1 && err_has "ERROR:"'
run_harness no 0 '' 0 0.16.4 ./a.py
check missing_require_zero 'rc_is 0 && err_has "WARNING:"'
run_harness no '' '' 0 0.16.4 ./a.py
check missing_require_empty 'rc_is 0 && err_has "WARNING:"'
run_harness yes unset 0.16.4 0 0.16.4 ./a.py -b.py
check clean_argv 'rc_is 0 && out_has "ruff 0.16.4" && err_empty && argv_is check --isolated --no-cache --select F --output-format concise -- ./a.py -b.py'
run_harness yes unset '0.16.4 (abc1234 2026-11-01)' 0 0.16.4 ./a.py
check version_suffix 'rc_is 0 && out_has "ruff 0.16.4" && err_empty'
run_harness yes unset '' 0 0.16.4 ./a.py
check version_unreadable 'rc_is 0 && out_has "ruff 不明" && err_has "WARNING:" && err_has 不明'
run_harness yes unset 0.16.4 1 0.16.4 ./a.py
check findings 'rc_is 1'
run_harness yes 1 0.16.4 2 0.16.4 ./a.py
check ruff_internal_error 'rc_is 1'
run_harness yes unset 0.16.10 0 0.16.4 ./a.py
check version_mismatch 'rc_is 0 && err_has "WARNING:" && err_has 0.16.10 && err_has 0.16.4'
run_harness yes unset 0.16.10 0 '' ./a.py
check no_ci_version 'rc_is 0 && err_empty'
run_harness yes 1 0.16.4 1 0.16.4
check no_files 'rc_is 0 && no_argv'

# lint 本体の配線: 呼び出しの行が行全体の一致でちょうど 1 行あること。`|| true` などに変えると赤になる。
# shellcheck disable=SC2016 # 意図的にリテラル（lint.sh の 1 行と文字どおり比べる。変数展開ではない）
wiring=$(grep -cFx 'run_ruff_check "$ci_ruff_version" "${py_files[@]}" || status=1' "$ROOT/lint.sh" || true)
count=$((count + 1))
if [[ "$wiring" -eq 1 ]]; then
  echo 'ok - wiring: lint 本体が run_ruff_check の結果を status へ反映している'
else
  echo "FAIL - wiring: 呼び出しの行が ${wiring} 行（1 行であるべき）"; fail=$((fail + 1))
fi

echo "結果: $count ケース、失敗 $fail"
[[ "$fail" -eq 0 ]]
