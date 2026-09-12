#!/usr/bin/env bash
# test-block-pr-approve.sh — block-pr-approve.sh（issue #10/#17）の回帰テスト。
#
# 注意: トリガー文字列（gh pr review --approve 等）をこのファイル外のコマンド行
# （シェルのコマンド履歴・呼び出し元スクリプトの引数）に平文で書くと、稼働中の
# block-pr-approve.sh 自体に誤ブロックされうる。テストケースは必ずこのファイル内
# の変数として保持し、実行は「bash examples/hooks/tests/test-block-pr-approve.sh」
# のみで完結させること。
#
# 判定（claude-container#70）: hook の stdout・stderr・終了コードを別々に取り、
# deny 期待は「終了コード 0 かつ stdout が単一の JSON オブジェクトで permissionDecision が
# deny」、pass 期待は「終了コード 0 かつ stdout も stderr も空」を要求する。出力の有無だけで
# 判定すると、deny 応答が allow に変わる回帰や hook 自体の起動失敗を見逃す。
set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd) || { echo "FAIL - 準備: ROOT を解決できない"; exit 1; }
HOOK="$ROOT/examples/hooks/block-pr-approve.sh"
[ -f "$HOOK" ] || { echo "FAIL - 準備: $HOOK が無い"; exit 1; }

TMPDIR_T=$(mktemp -d) || { echo "FAIL - 準備: mktemp -d に失敗"; exit 1; }
trap 'rm -rf "$TMPDIR_T"' EXIT

fail=0

# $1=説明 $2=期待("deny"|"pass") $3=コマンド文字列 [$4=hook 起動時の PATH（fail-safe 検証用）]
run_case() {
  desc="$1"
  expect="$2"
  cmdstr="$3"
  path_override="${4:-}"
  outfile="$TMPDIR_T/stdout"
  errfile="$TMPDIR_T/stderr"
  if ! input=$(jq -n --arg c "$cmdstr" '{tool_input:{command:$c}}'); then
    echo "FAIL - $desc (準備: 入力 JSON を生成できない)"
    fail=$((fail + 1))
    return
  fi
  if [ -n "$path_override" ]; then
    printf '%s' "$input" | PATH="$path_override" bash "$HOOK" >"$outfile" 2>"$errfile" && rc=0 || rc=$?
  else
    printf '%s' "$input" | bash "$HOOK" >"$outfile" 2>"$errfile" && rc=0 || rc=$?
  fi
  out=$(cat "$outfile")
  err=$(cat "$errfile")
  # stdout 全体が単一の JSON オブジェクトで、permissionDecision が deny か（jq -e: 真なら 0、偽なら 1、解析失敗は 2 以上）
  if printf '%s' "$out" | jq -es 'length == 1 and (.[0] | type == "object") and (.[0].hookSpecificOutput.permissionDecision == "deny")' >/dev/null 2>&1; then
    deny_json=1
  else
    deny_json=0
  fi
  if [ "$rc" -eq 0 ] && [ "$deny_json" -eq 1 ]; then
    actual="deny"
  elif [ "$rc" -eq 0 ] && [ ! -s "$outfile" ] && [ ! -s "$errfile" ]; then
    actual="pass"
  else
    actual="invalid"
  fi
  if [ "$actual" = "$expect" ]; then
    echo "ok   - $desc"
  else
    echo "FAIL - $desc (expected $expect, got $actual; rc=$rc stdout=${out:0:80} stderr=${err:0:80})"
    fail=$((fail + 1))
  fi
}

# --- DENY 期待 ---
run_case "C1 真正承認 --approve" deny 'gh pr review 123 --approve'
run_case "C2 真正承認 -a" deny 'gh pr review -a 123'
run_case "C3 真正承認 --approve --body" deny 'gh pr review 123 --approve --body "lgtm"'
run_case "C4 gh api unquoted event=APPROVE" deny 'gh api repos/o/r/pulls/1/reviews -f event=APPROVE'
run_case "C5 gh api quoted event=APPROVE (hardening)" deny 'gh api repos/o/r/pulls/1/reviews -f "event=APPROVE"'
run_case "C6 gh api --input - でJSON本文にAPPROVE (hardening)" deny "$(printf 'gh api repos/o/r/pulls/1/reviews --input - <<EOF\n{"event": "APPROVE"}\nEOF')"
run_case "C7 benign heredoc後に真正承認" deny "$(printf 'gh issue comment 1 --body-file - <<EOF\nsome text\nEOF\ngh pr review 1 --approve')"
run_case "C8 ヒアストリング併用の真正承認" deny 'gh pr review 1 --approve <<< "x"'
run_case "C9 残存FP許容: gh apiが実コマンドでheredoc本文に両パターン引用" deny \
  "$(printf 'gh api repos/o/r/issues/1/comments -f body=x --input - <<EOF\nplease see gh api pulls/2/reviews event=APPROVE for reference\nEOF')"

# --- pass 期待 ---
run_case "N1 issue17原再現 (single quote heredoc)" pass \
  "$(printf 'gh issue comment 17 --body-file - <<%s\n(quoted) gh pr review --approve\n%s' "'EOF'" "EOF")"
run_case "N2 gh pr comment heredocにgh api引用" pass \
  "$(printf 'gh pr comment 1 --body-file - <<EOF\ngh api pulls/1/reviews event=APPROVE\nEOF')"
run_case "N3 git commit -am 引用FP解消" pass 'git commit -am "docs: explain gh pr review --approve flow"'
run_case "N4 --comment" pass 'gh pr review 123 --comment --body "note"'
run_case "N5 --request-changes" pass 'gh pr review 123 --request-changes -b "fix"'

# issue #72: フラグ直後のシェル演算子を終端として扱わない回帰を検出する。
# 入力は hook に渡す文字列だけであり、承認コマンドやリダイレクトは実行しない。
# 同じケースを通常経路と jq 不在経路で確認する。
run_delimiter_cases() {
  local mode="$1" hook_path="${2:-}" flag
  for flag in --approve -a -aa; do
    run_case "$mode $flag セミコロン" deny "gh pr review 1 $flag; echo done" "$hook_path"
    run_case "$mode $flag AND" deny "gh pr review 1 $flag&&true" "$hook_path"
    run_case "$mode $flag OR" deny "gh pr review 1 $flag||true" "$hook_path"
    run_case "$mode $flag パイプ" deny "gh pr review 1 $flag|cat" "$hook_path"
    run_case "$mode $flag バックグラウンド" deny "gh pr review 1 $flag& wait" "$hook_path"
    run_case "$mode $flag サブシェル終端" deny "(gh pr review 1 $flag)" "$hook_path"
    run_case "$mode $flag 入力リダイレクト" deny "gh pr review 1 $flag</dev/null" "$hook_path"
    run_case "$mode $flag 出力リダイレクト" deny "gh pr review 1 $flag>/dev/null" "$hook_path"
  done
  run_case "$mode コメントと区切り文字" pass 'gh pr review 1 --comment; echo done' "$hook_path"
  run_case "$mode 変更要求と区切り文字" pass 'gh pr review 1 --request-changes&&true' "$hook_path"
  run_case "$mode 長オプションの接頭辞だけでは承認にしない" pass 'gh pr review 1 --approve-extra;' "$hook_path"
  run_case "$mode 短オプションの接頭辞だけでは承認にしない" pass 'gh pr review 1 -a1;' "$hook_path"
}
run_delimiter_cases "通常"
run_case "引用した承認フラグと区切り文字" pass 'gh pr review 1 --comment --body "example --approve; -a&&true"'
run_case "heredoc本文の承認フラグと区切り文字" pass \
  $'gh pr comment 1 --body-file - <<EOF\ngh pr review 1 --approve;\nEOF'

# issue #75: 値付き承認フラグは値の真偽によらず拒否する。
# 真値の見逃しと、安全側に倒す false・不正値・引用値の契約を両経路で確認する。
run_value_cases() {
  local mode="$1" hook_path="${2:-}" flag value
  for flag in --approve -a -aa; do
    for value in true 1 t T TRUE True false 0 f F FALSE False bogus ''; do
      run_case "$mode 値付き $flag=$value" deny "gh pr review 1 $flag=$value" "$hook_path"
    done
    run_case "$mode 値付き $flag と区切り文字" deny "gh pr review 1 $flag=true; echo done" "$hook_path"
    run_case "$mode 値付き $flag の引用値" deny "gh pr review 1 $flag=\"true\"" "$hook_path"
    run_case "$mode 値付き $flag の引用した偽値" deny "gh pr review 1 $flag='false'" "$hook_path"
  done
  run_case "$mode 値付きコメント" pass 'gh pr review 1 --comment=true --body "note"' "$hook_path"
  run_case "$mode 値付き変更要求" pass 'gh pr review 1 --request-changes=true --body "fix"' "$hook_path"
  run_case "$mode 値付き別の長オプション" pass 'gh pr review 1 --approve-extra=true' "$hook_path"
  run_case "$mode コメント併用でも偽値を拒否" deny 'gh pr review 1 --approve=false --comment --body "note"' "$hook_path"
}
run_value_cases "通常"
run_case "引用文の値付き承認フラグ" pass 'gh pr review 1 --comment --body "example --approve=true"'
run_case "heredoc本文の値付き承認フラグ" pass \
  $'gh pr comment 1 --body-file - <<EOF\ngh pr review 1 --approve=true\nEOF'

# issue #76: バッククォート終端。文字列を JSON に入れるだけで置換は実行しない。
run_backtick_cases() {
  local mode="$1" hook_path="${2:-}" flag
  for flag in --approve -a -aa; do
    run_case "$mode $flag バッククォート終端" deny 'x=`gh pr review 1 '"$flag"'`' "$hook_path"
  done
  # コマンド置換を実行せず、hook 入力としてそのまま渡す。
  # shellcheck disable=SC2016
  run_case "$mode バッククォート内のコメント" pass 'x=`gh pr review 1 --comment`' "$hook_path"
  # shellcheck disable=SC2016
  run_case "$mode バッククォート内の変更要求" pass 'x=`gh pr review 1 --request-changes`' "$hook_path"
}
run_backtick_cases "通常"
# 単一引用符と引用した heredoc 区切り語で、実行されない引用例を作る。
quoted_backtick=$'gh pr comment 1 --body \'example x=`gh pr review 1 --approve`\''
heredoc_backtick=$'gh pr comment 1 --body-file - <<\'EOF\'\nx=`gh pr review 1 --approve`\nEOF'
run_case "単一引用文のバッククォート" pass "$quoted_backtick"
run_case "引用 heredoc 本文のバッククォート" pass "$heredoc_backtick"

# --- fail-safe（jq不在） ---
# hook が使う外部コマンド（bash・cat・grep・sed・awk）だけを symlink した shim ディレクトリを
# PATH にする。PATH から jq のディレクトリを丸ごと落とす方式だと、usrmerge 環境では bash 自体が
# 消えて hook が起動せず、テストが空振りする（claude-container#70）。
SHIM="$TMPDIR_T/shim"
shim_ok=1
mkdir -p "$SHIM" || shim_ok=0
for c in bash cat grep sed awk; do
  if p=$(type -P "$c") && [ -n "$p" ] && ln -s "$p" "$SHIM/$c"; then
    :
  else
    echo "FAIL - C10 準備: $c を shim に置けない"
    fail=$((fail + 1))
    shim_ok=0
  fi
done
if [ "$shim_ok" -eq 1 ]; then
  run_case "C10 jq不在fail-safe: 真正承認は引き続きDENY" deny 'gh pr review 123 --approve' "$SHIM"
  run_delimiter_cases "jq不在" "$SHIM"
  run_value_cases "jq不在" "$SHIM"
  run_backtick_cases "jq不在" "$SHIM"
  # jq 不在経路は引用と本文を除去できず、安全側の偽陽性として拒否する。
  run_case "jq不在: 単一引用文のバッククォートは安全側に拒否" deny "$quoted_backtick" "$SHIM"
  run_case "jq不在: 引用 heredoc 本文のバッククォートは安全側に拒否" deny "$heredoc_backtick" "$SHIM"
else
  echo "FAIL - C10 jq不在fail-safe: 準備に失敗したため未実行"
  fail=$((fail + 1))
fi

echo ''
if [ "$fail" -eq 0 ]; then
  echo "全ケース green"
  exit 0
else
  echo "$fail 件 FAIL"
  exit 1
fi
