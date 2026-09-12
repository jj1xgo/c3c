#!/usr/bin/env bash
# block-pr-approve.sh — PreToolUse hook (Bash)
# gh の「PR 承認」操作（gh pr review --approve / -a、および生 API 経由の
# event=APPROVE）だけをブロックし、--comment / --request-changes 等その他の
# PR 操作・gh コマンドはすべて通す。
#
# 目的（issue #10）: コンテナ内トークン（Pull requests: write を持つが
# Contents: write は持たない）による自律承認が、auto-merge 経由でマージ境界を
# 迂回するリスクを機構的に防ぐ「2枚目の壁」。1枚目の壁はリポジトリの
# auto-merge 無効維持（CLAUDE.md セキュリティモデル節）。
#
# 脅威モデルは「Claude 自身のうっかり自律承認の抑止」。変数展開・コマンド置換
# 等による意図的な難読化までは防げない（公式もコマンド文字列パターンは fragile
# と明記）。誤検知は必ず安全方向（承認をブロックする側）へ倒す設計とする。
#
# 判定(1)(2)とも、実行コマンドかどうかの検出は $stripped_hd（ヒアドキュメント
# 本文＋引用符囲み文字列を除去した文字列）に対して行う（issue #17）。無関係な
# 操作（gh issue comment 等）のヒアドキュメント本文中に承認コマンドを引用した
# だけで誤ブロックする false positive を防ぐため。判定(2)の内容検査
# （pulls/N/reviews・event=APPROVE パターン）だけは raw $cmd に対して行う。
# --input - <<EOF 形式の JSON 本文や引用付き -f "event=APPROVE" のような、
# 引用符・ヒアドキュメント経由で成立する真正の承認を見逃さないため
# （stripped 化した文字列だけを見ると、これらは検出できず既存の false
# negative になっていた）。
#
# 既知の残存 false positive（安全方向、意図的に許容）:
#   - 実行コマンドが本当に gh api で、そのヒアドキュメント本文に
#     pulls/N/reviews と event=APPROVE の両方を引用しているケース
#   - 複数行にまたがるダブルクォート文字列内に承認コマンド文字列があるケース
#     （sed の引用符除去が行単位のため。ヒアドキュメント以外は対象外）
#   - --approve=false / -a=false など、値付き承認フラグの偽値・不正値
#     （引用符除去後の文字列で値を評価せず、= が続けば安全側に拒否する）
# 既知の残存 false negative（意図的な難読化、脅威モデル外）:
#   - 引用文字列内に `<<X` を含む行を挟んでヒアドキュメント除去を誤爆させ、
#     その直後に真正の承認コマンドを紛れ込ませるようなケース
#
# 注意: このファイルのコメント行を「# shellcheck」で始めないこと
# （directive として解釈されパースエラーになる）。
set +e

# ヒアドキュメント本文行のみを除去する awk プログラム。開始行はそのまま残す
# （コマンドライン引数を消さないため）。<<-?['"\\]?WORD 形式の区切り語を
# FIFO キューで管理し、同一行の複数ヒアドキュメント・連続ヒアドキュメントに
# 対応する。<<- は行頭タブを剥がしてから照合する。ヒアストリング <<< は
# 事前に <<< をマスクして誤検出を防ぐ。POSIX awk のみで書かれており
# mawk/gawk 双方で動作確認済み。
# 順序が決定的に重要: この除去は「引用符除去（sed）より前」に「raw $cmd」に
# 対して行うこと。逆順だと <<'EOF'（最頻出形式）の区切り語 'EOF' が sed の
# 引用符除去で 'EOF' → （空）に変換され、ヒアドキュメントとして認識できなく
# なり本文除去が効かなくなる。
read -r -d '' HEREDOC_STRIP_AWK <<'AWKEOF'
nq > 0 {
  check = $0
  if (tabs[1]) sub(/^\t+/, "", check)
  if (check == queue[1]) {
    for (i = 1; i < nq; i++) { queue[i] = queue[i+1]; tabs[i] = tabs[i+1] }
    nq--
  }
  next
}
{
  print
  scan = $0
  gsub(/<<</, " ", scan)
  while (match(scan, /<<-?[ \t]*['"\\]?[A-Za-z_][A-Za-z0-9_.-]*/)) {
    op = substr(scan, RSTART, RLENGTH)
    scan = substr(scan, RSTART + RLENGTH)
    isdash = (op ~ /^<<-/)
    word = op
    sub(/^<<-?[ \t]*['"\\]?/, "", word)
    nq++; queue[nq] = word; tabs[nq] = isdash
  }
}
AWKEOF

reason='gh pr review --approve（PR 承認）の自律実行は禁止です（issue #10）。承認は auto-merge の引き金になりうるため、承認とマージは人間がホスト側で行います。値付き承認フラグは --approve=false 等でも拒否します。レビュー補助が目的なら承認フラグ自体を省き、--comment / --request-changes を使ってください。'

emit_deny() {
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  else
    # jq 不在時も承認だけは確実に止める（fail-safe）。reason に " \ % を含めない前提。
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}' "$1"
  fi
  exit 0
}

input=$(cat)

if command -v jq >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
  [ -z "$cmd" ] && exit 0
  # ヒアドキュメント本文を除去した cmd_hd を作る（引用符除去より先、raw $cmd に
  # 対して）。awk 失敗・不在時は cmd_hd が空になるため raw $cmd にフォールバック
  # する（現行挙動へ退化＝false positive 側＝安全方向）。
  cmd_hd=""
  if command -v awk >/dev/null 2>&1; then
    cmd_hd=$(printf '%s' "$cmd" | awk "$HEREDOC_STRIP_AWK")
  fi
  [ -z "$cmd_hd" ] && cmd_hd=$cmd
  # クォートされた文字列（--body 等の値）を除去し、body テキスト中の
  # "-a" 等による誤検知を減らす。
  stripped_hd=$(printf '%s' "$cmd_hd" | sed -E 's/"[^"]*"//g; s/'"'"'[^'"'"']*'"'"'//g')
else
  # jq 不在は環境異常。承認判定は生 JSON 文字列に対して継続する（fail-safe）。JSON の
  # 引用符（\"、"）と改行・タブ・復帰のエスケープ（\n、\t、\r）を空白に置き換えてから
  # 判定する。置き換えないと command 値の末尾が `--approve"` のように引用符で閉じられ、
  # または `--approve\necho` のようにエスケープが続き、末尾を空白か行末に限定した判定に
  # 当たらない（claude-container#71）。引用文字列の除去はできないので、引用内の承認語は偽陽性側に
  # 倒れる。JSON の Unicode エスケープ（\u0022 など）は復号しないので、その形の入力は検出しない。
  cmd=$(printf '%s' "$input" | sed -E 's/\\["ntr]/ /g; s/"/ /g')
  stripped_hd=$cmd
fi

# gh コマンドでなければ即通過（高速パス）
printf '%s' "$stripped_hd" | grep -qE '(^|[^[:alnum:]])gh([[:space:]]|$)' || exit 0

# (1) gh pr review の承認フラグ（--approve / -a を含む短オプションクラスタ）
#     -c / -r / -b / -F 等 a を含まない短オプションは通す。
#     空白・行末だけでなくシェルの区切り文字もフラグの終端になる（issue #72）。
#     例: --approve; echo done、-a&&true、(gh pr review 1 --approve)。
#     = は値付き指定（--approve=true / -a=1 等）。引用値は除去されうるため
#     真偽値を評価せず、false・不正値も含めて拒否する（issue #75）。
if printf '%s' "$stripped_hd" | grep -qE '(^|[^[:alnum:]])gh[[:space:]]+pr[[:space:]]+review([[:space:]]|$)'; then
  if printf '%s' "$stripped_hd" | grep -qE '(^|[[:space:]])(--approve|-[[:alpha:]]*a[[:alpha:]]*)([[:space:];&|()<>=]|$)'; then
    emit_deny "$reason"
  fi
fi

# (2) 生 API 経由の承認（.../pulls/<N>/reviews に event=APPROVE を渡す形）
#     実行コマンドの検出（gh api か）は stripped_hd で行うが、内容検査
#     （pulls/N/reviews・event=APPROVE パターン）は raw $cmd に対して行う。
#     --input - <<EOF の JSON 本文や引用付き -f "event=APPROVE" 経由の真正の
#     承認は、引用符・ヒアドキュメント除去後の文字列だけでは検出できないため。
if printf '%s' "$stripped_hd" | grep -qE '(^|[^[:alnum:]])gh[[:space:]]+api([[:space:]]|$)' \
   && printf '%s' "$cmd" | grep -qiE 'pulls/[0-9]+/reviews' \
   && printf '%s' "$cmd" | grep -qE 'event["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?APPROVE'; then
  emit_deny "$reason"
fi

exit 0
