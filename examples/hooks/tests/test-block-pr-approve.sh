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
