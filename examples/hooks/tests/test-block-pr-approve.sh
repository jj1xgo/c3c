#!/usr/bin/env bash
# test-block-pr-approve.sh — block-pr-approve.sh（issue #10/#17）の回帰テスト。
#
# 注意: トリガー文字列（gh pr review --approve 等）をこのファイル外のコマンド行
# （シェルのコマンド履歴・呼び出し元スクリプトの引数）に平文で書くと、稼働中の
# block-pr-approve.sh 自体に誤ブロックされうる。テストケースは必ずこのファイル内
# の変数として保持し、実行は「bash examples/hooks/tests/test-block-pr-approve.sh」
# のみで完結させること。
set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
HOOK="$ROOT/examples/hooks/block-pr-approve.sh"

fail=0

# $1=説明 $2=期待("deny"|"pass") $3=コマンド文字列 [$4=追加のPATH（fail-safe検証用）]
run_case() {
  desc="$1"
  expect="$2"
  cmdstr="$3"
  path_override="${4:-}"
  input=$(jq -n --arg c "$cmdstr" '{tool_input:{command:$c}}')
  if [ -n "$path_override" ]; then
    out=$(printf '%s' "$input" | PATH="$path_override" bash "$HOOK" 2>&1)
  else
    out=$(printf '%s' "$input" | bash "$HOOK" 2>&1)
  fi
  if [ -n "$out" ]; then
    actual="deny"
  else
    actual="pass"
  fi
  if [ "$actual" = "$expect" ]; then
    echo "ok   - $desc"
  else
    echo "FAIL - $desc (expected $expect, got $actual)"
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
run_case "N5 --request-changes" deny 'gh pr review 123 --request-changes -b "fix"'

# --- fail-safe（jq不在） ---
NOJQ_PATH=""
IFS=':' read -ra _dirs <<< "$PATH"
for d in "${_dirs[@]}"; do
  [ -e "$d/jq" ] && continue
  NOJQ_PATH="${NOJQ_PATH:+$NOJQ_PATH:}$d"
done
run_case "C10 jq不在fail-safe: 真正承認は引き続きDENY" deny 'gh pr review 123 --approve' "$NOJQ_PATH"

echo ''
if [ "$fail" -eq 0 ]; then
  echo "全ケース green"
  exit 0
else
  echo "$fail 件 FAIL"
  exit 1
fi
