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

# 対象の集め方（collect_py_files）を、fixture のディレクトリで確かめる。ルートと tests/ の *.py を
# `.` 始まりも含めて集め、ほかの拡張子・tests/ の下の階層・ほかのディレクトリは入れず、
# 0 本なら空の配列にし、終わった後に nullglob・dotglob を元（無効）に戻すこと。
{
  printf '#!/bin/bash\nset -uo pipefail\n'
  sed -n '/^collect_py_files()/,/^}/p' "$ROOT/lint.sh"
  # shellcheck disable=SC2016 # 意図的にリテラル（harness の中で展開する）
  printf 'collect_py_files\nprintf "%%s\\n" "${#py_files[@]}" "${py_files[@]}"\n'
  # shellcheck disable=SC2016 # 同上
  printf 'for o in nullglob dotglob; do if shopt -q "$o"; then echo "$o=on"; else echo "$o=off"; fi; done\n'
} > "$tmp/collect"
mkdir -p "$tmp/fx/tests/sub" "$tmp/fx/other" "$tmp/fx0"
touch "$tmp/fx/a.py" "$tmp/fx/.b.py" "$tmp/fx/c.txt" "$tmp/fx/tests/d.py" "$tmp/fx/tests/.e.py" \
  "$tmp/fx/tests/f.pyc" "$tmp/fx/tests/sub/g.py" "$tmp/fx/other/h.py"
collect_in() { RC=0; (cd "$1" && env -i PATH=/usr/bin:/bin /bin/bash "$tmp/collect") > "$tmp/out" 2> "$tmp/err" || RC=$?; }
out_is() { [[ "$(cat "$tmp/out")" == "$(printf '%s\n' "$@")" ]]; }
collect_in "$tmp/fx"
check collect_files 'rc_is 0 && err_empty && out_is 4 ./.b.py ./a.py tests/.e.py tests/d.py nullglob=off dotglob=off'
collect_in "$tmp/fx0"
check collect_none 'rc_is 0 && err_empty && out_is 0 nullglob=off dotglob=off'

# lint 本体の配線: 集める行と呼び出しの行が、行全体の一致でちょうど 1 行ずつあること。
# `|| true` に変える、集める行を消すなどすると赤になる。
# shellcheck disable=SC2016 # 意図的にリテラル（lint.sh の 1 行と文字どおり比べる。変数展開ではない）
for line in 'collect_py_files' 'run_ruff_check "$ci_ruff_version" "${py_files[@]}" || status=1'; do
  wiring=$(grep -cFx -- "$line" "$ROOT/lint.sh" || true)
  count=$((count + 1))
  if [[ "$wiring" -eq 1 ]]; then
    echo "ok - wiring: lint 本体に「$line」がちょうど 1 行ある"
  else
    echo "FAIL - wiring: 「$line」が ${wiring} 行（1 行であるべき）"; fail=$((fail + 1))
  fi
done
# 集める行の直後の行が呼び出しであること（後ろへ移すと py_files が空のまま呼ばれ、検査が黙って消える。
# 間に別の行〈py_files=() など〉を挟む・集める行を関数の定義より前へ移す、も赤にするため、隣り合うことを見る）。
# grep が当たらなくても set -e で止めずに FAIL と「結果:」まで出すため、|| true を付ける。
collect_at=$(grep -nFx -- 'collect_py_files' "$ROOT/lint.sh" | head -n 1 | cut -d: -f1 || true)
# shellcheck disable=SC2016 # 意図的にリテラル（行全体で比べ、コメントの部分一致に当てない）
call_at=$(grep -nFx -- 'run_ruff_check "$ci_ruff_version" "${py_files[@]}" || status=1' "$ROOT/lint.sh" | head -n 1 | cut -d: -f1 || true)
count=$((count + 1))
if [[ -n "$collect_at" && -n "$call_at" && "$call_at" -eq $((collect_at + 1)) ]]; then
  echo 'ok - wiring: collect_py_files の直後の行が run_ruff_check の呼び出し'
else
  echo "FAIL - wiring: collect_py_files（${collect_at:-なし}行目）の直後が呼び出し（${call_at:-なし}行目）でない"; fail=$((fail + 1))
fi

echo "結果: $count ケース、失敗 $fail"
[[ "$fail" -eq 0 ]]
