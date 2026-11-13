#!/bin/bash
# Copilot CLI の受け入れ（canary）。opt-in のコンテナの中で保守者が打つ:
#
#   bash tests/copilot-canary.sh [--runs N] [--model M] [--max-ai-credits N] [--spent-log FILE] [<作業ディレクトリ>]
#
# 起動口 /usr/local/bin/copilot を通して Copilot を非対話で N 回起動し、決まった 1 つのコマンドを sandbox の
# 中で打たせる。合否は、その回の Copilot のセッション記録（~/.copilot/session-state/<id>/events.jsonl）に
# 残った実際のコマンドと出力から判定する（モデルの返答の文は見ない。判定は copilot_canary_helper.py）。
# あわせて、作業ディレクトリ /home/node で起動口が止まること、弱めた settings.json が起動口を通すと雛形に
# 戻ることを確かめ、目印と試しのファイルを片付ける。
#
# モデルを呼ぶのは canary の回だけで、各回に --max-ai-credits の上限を付ける。CI には入れない。
# rc: 全部合格で 0、不合格か確かめていない項目があるか中断されたら 1、前提を満たさないか使い方の誤りは 2。
# トークンは読まない（sandbox の中のコマンドが COPILOT_PAT を読めないことを確かめるだけ）。
set -u
set -o pipefail

# 固定パスは環境変数で差し替えない。
readonly COPILOT_BIN=/usr/local/bin/copilot
readonly CONTAINER_HOME=/home/node
readonly COPILOT_HOME=/home/node/.copilot
readonly SETTINGS_TEMPLATE=/etc/c3c/copilot-settings.json
readonly TOKEN_FILE=/home/node/.config/c3c/secrets/COPILOT_PAT
readonly SECRETS_DIR=/home/node/.config/c3c/secrets
readonly HOME_MARK=/home/node/.copilot/.c3c-canary-mark
readonly PYTHON3=/usr/bin/python3
readonly FLOCK=/usr/bin/flock
# 起動口が作業ディレクトリとして拒む sandbox の隠し場所（copilot-launcher.sh と同じ）。
readonly SANDBOX_TMP=/tmp
readonly MIN_CREDITS=30
readonly W_FILE_NAME=.c3c-copilot-w

# shellcheck disable=SC2016  # sandbox の中の bash が展開するコマンドの文字列そのもの。
readonly CANARY_COMMAND='readlink /proc/self/ns/user /proc/self/ns/net; ip -brief link; curl -sS -m 5 -o /dev/null -w "%{http_code}" https://api.github.com/; echo " curl_rc=$?"; cat /home/node/.config/c3c/secrets/COPILOT_PAT >/dev/null; echo "secret_rc=$?"; cat /home/node/.copilot/.c3c-canary-mark >/dev/null; echo "home_rc=$?"; echo "tok_len=${#COPILOT_GITHUB_TOKEN} gh_len=${#GH_TOKEN}"; echo "outer_environ=$(grep -l COPILOT_GITHUB_TOKEN /proc/[0-9]*/environ 2>/dev/null | wc -l)"; touch "$PWD/.c3c-copilot-w" 2>/dev/null; echo "w_rc=$?"'
readonly PROMPT_HEAD='Run exactly this one bash command with the shell tool, then report its full output verbatim inside a code block and nothing else:'
readonly COPILOT_ARGS=(--available-tools=bash --allow-tool=shell --allow-all-paths --allow-all-urls --no-ask-user --no-auto-update)

case "${BASH_SOURCE[0]}" in
  */*) script_dir="${BASH_SOURCE[0]%/*}" ;;
  *) script_dir=. ;;
esac
if ! script_dir="$(cd "$script_dir" && pwd -P)"; then
  echo "ERROR: スクリプトの場所を解決できません。" >&2
  exit 2
fi
readonly HELPER="$script_dir/copilot_canary_helper.py"

usage() {
  [ "$#" -gt 0 ] && echo "ERROR: $*" >&2
  echo "使い方: bash tests/copilot-canary.sh [--runs N(1-5)] [--model M] [--max-ai-credits N(>=$MIN_CREDITS)] [--spent-log FILE] [<作業ディレクトリ>]" >&2
  exit 2
}
fail_pre() {
  echo "ERROR: $*" >&2
  exit 2
}
helper() {
  "$PYTHON3" -I "$HELPER" "$@"
}

# 1. 引数の検査（クレジットを使う前に止める）。
runs=2
model=gemini-4-argon
cap=$MIN_CREDITS
spent_log=""
spent_log_set=0
dir=/workspace
dir_set=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --runs | --model | --max-ai-credits | --spent-log)
      [ "$#" -ge 2 ] || usage "$1 に値がありません。"
      case "$1" in
        --runs) runs="$2" ;;
        --model) model="$2" ;;
        --max-ai-credits) cap="$2" ;;
        --spent-log) spent_log="$2"; spent_log_set=1 ;;
      esac
      shift 2
      ;;
    -*) usage "知らないオプション $1" ;;
    *)
      [ "$dir_set" -eq 0 ] || usage "作業ディレクトリは 1 つだけ渡せます。"
      dir="$1"
      dir_set=1
      shift
      ;;
  esac
done
[[ "$runs" =~ ^[1-5]$ ]] || usage "--runs は 1 から 5 の整数です。"
[ -n "$model" ] || usage "--model が空です。"
# 先頭の 0 を断り、桁の多い値で bash の整数があふれないよう、桁数を先に見る。
if ! [[ "$cap" =~ ^[1-9][0-9]*$ ]] || [ "${#cap}" -gt 9 ] || [ "$cap" -lt "$MIN_CREDITS" ]; then
  usage "--max-ai-credits は $MIN_CREDITS 以上の整数です（Copilot の下限が $MIN_CREDITS のため）。"
fi
if [ "$spent_log_set" -eq 1 ]; then
  [ -n "$spent_log" ] || usage "--spent-log が空です。"
  if [ -e "$spent_log" ] || [ -L "$spent_log" ]; then
    if [ -L "$spent_log" ] || [ ! -f "$spent_log" ]; then
      usage "--spent-log $spent_log は symlink でない通常のファイルにしてください。"
    fi
  else
    case "$spent_log" in
      */*) spent_parent="${spent_log%/*}"; spent_parent="${spent_parent:-/}" ;;
      *) spent_parent=. ;;
    esac
    if [ ! -d "$spent_parent" ] || [ ! -w "$spent_parent" ]; then
      usage "--spent-log の置き場 $spent_parent がないか書けません。"
    fi
  fi
fi
[ -d "$dir" ] || usage "作業ディレクトリ $dir がありません。"
if ! WORKDIR="$(cd "$dir" && pwd -P)" || [ -z "$WORKDIR" ]; then
  usage "作業ディレクトリ $dir を解決できません。"
fi
readonly WORKDIR
readonly W_FILE="$WORKDIR/$W_FILE_NAME"

# 2. 前提（欠ければ何も変えずに rc 2）。作業ディレクトリの規則は copilot-launcher.sh と同じ。
refuse_workdir() {
  fail_pre "作業ディレクトリ $WORKDIR では受け入れを行いません（$1）。"
}
if [ "$WORKDIR" = / ] || [ "$WORKDIR" = "$CONTAINER_HOME" ]; then
  refuse_workdir "$CONTAINER_HOME とその祖先は起動口が拒むため"
fi
case "$CONTAINER_HOME" in
  "$WORKDIR"/*) refuse_workdir "$CONTAINER_HOME とその祖先は起動口が拒むため" ;;
esac
for denied in "$SANDBOX_TMP" "$SECRETS_DIR"; do
  case "$WORKDIR" in
    "$denied" | "$denied"/*) refuse_workdir "$denied とその下は起動口が拒むため" ;;
  esac
done
case "$WORKDIR" in
  "$CONTAINER_HOME"/*)
    rel="${WORKDIR#"$CONTAINER_HOME"/}"
    case "${rel%%/*}" in
      .*) refuse_workdir "$CONTAINER_HOME の直下の . で始まるエントリは起動口が拒むため" ;;
    esac
    ;;
esac
[ -w "$WORKDIR" ] || refuse_workdir "書けない場所では、書き込みが塞がれたことを確かめられないため"

if [ -L "$COPILOT_BIN" ] || [ ! -f "$COPILOT_BIN" ] || ! grep -q '^readonly VERIFIED_COPILOT_VERSION=' "$COPILOT_BIN"; then
  fail_pre "$COPILOT_BIN が c3c の Copilot の起動口ではありません（opt-in のコンテナの中で打ってください）。"
fi
[ -f "$SETTINGS_TEMPLATE" ] || fail_pre "$SETTINGS_TEMPLATE がありません。"
if [ -L "$TOKEN_FILE" ] || [ ! -f "$TOKEN_FILE" ] || [ ! -r "$TOKEN_FILE" ]; then
  fail_pre "$TOKEN_FILE が読める通常のファイルではありません。"
fi
[ -f "$HELPER" ] || fail_pre "$HELPER がありません。"
if [ -L "$COPILOT_HOME" ] || { [ -e "$COPILOT_HOME" ] && [ ! -d "$COPILOT_HOME" ]; }; then
  fail_pre "$COPILOT_HOME がディレクトリではありません（symlink を含む）。"
fi
if [ ! -d "$COPILOT_HOME" ] && ! mkdir -m 700 "$COPILOT_HOME" 2>/dev/null; then
  fail_pre "$COPILOT_HOME を作れません。"
fi
for leftover in "$HOME_MARK" "$W_FILE"; do
  if [ -e "$leftover" ] || [ -L "$leftover" ]; then
    fail_pre "$leftover が既にあります（前の受け入れの残りかもしれません。中身を見てから消してください）。"
  fi
done
readonly LOCK_FILE="$COPILOT_HOME/.c3c-launch.lock"
if [ -L "$LOCK_FILE" ] || { [ -e "$LOCK_FILE" ] && [ ! -f "$LOCK_FILE" ]; }; then
  fail_pre "$LOCK_FILE が通常のファイルではありません（symlink を含む）。"
fi
if ! { : >> "$LOCK_FILE"; } 2>/dev/null || ! ( exec 8< "$LOCK_FILE" && "$FLOCK" -n 8 ) 2>/dev/null; then
  fail_pre "別の copilot が動いています（または $LOCK_FILE を開けません）。"
fi
outer_user="$(readlink /proc/self/ns/user 2>/dev/null)"
outer_net="$(readlink /proc/self/ns/net 2>/dev/null)"
if ! [[ "$outer_user" =~ ^user:\[([0-9]+)\]$ ]]; then
  fail_pre "外側の user の名前空間を読めません。"
fi
outer_user="${BASH_REMATCH[1]}"
if ! [[ "$outer_net" =~ ^net:\[([0-9]+)\]$ ]]; then
  fail_pre "外側の net の名前空間を読めません。"
fi
outer_net="${BASH_REMATCH[1]}"

# 表の行と、記録に使う値。
row_names=()
row_status=()
row_reason=()
add_row() {
  row_names+=("$1")
  row_status+=("$2")
  row_reason+=("$3")
}
started=0
credits_list=()
unknown_credits=0
session_lines=()
copilot_version=不明
child_pid=""
finished=0
mark_written=0

run_launcher_version() {
  # 起動口を作業ディレクトリ $1 で --version で呼ぶ。stdout の 1 行目を version_out に入れ、rc を返す。
  local out rc
  out="$(cd "$1" && "$COPILOT_BIN" --version 2>/dev/null)"
  rc=$?
  version_out="${out%%$'\n'*}"
  return "$rc"
}

cleanup() {
  # 目印と試しのファイルを消し、起動口を 1 回通して settings.json を雛形に戻したことを確かめる。
  # 残ったものを cleanup_reasons に入れる。rm -r は使わない（目印の名前の別物を消さない）。
  cleanup_reasons=()
  local path
  for path in "$HOME_MARK" "$W_FILE"; do
    if [ "$path" = "$HOME_MARK" ] && [ "$mark_written" -eq 0 ]; then
      continue
    fi
    rm -f "$path" 2>/dev/null
    if [ -e "$path" ] || [ -L "$path" ]; then
      cleanup_reasons+=("$path が残った")
    fi
  done
  if run_launcher_version "$WORKDIR"; then
    [ -n "$version_out" ] && copilot_version="$version_out"
  else
    cleanup_reasons+=("起動口の --version が失敗した")
  fi
  local match
  if ! match="$(helper settings-match "$COPILOT_HOME/settings.json" "$SETTINGS_TEMPLATE" "$WORKDIR" 2>&1)"; then
    cleanup_reasons+=("settings.json が雛形に戻らない: ${match:-理由不明}")
  fi
}

total_credits() {
  # 判定した回のクレジットと、判定する前に止まった回の上限を足す（bash で小数を扱わない）。
  local pending=$(( started - ${#credits_list[@]} ))
  local i extra=()
  for (( i = 0; i < pending; i++ )); do
    extra+=("$cap")
  done
  "$PYTHON3" -I -c 'import sys; print(repr(float(sum(float(x) for x in sys.argv[1:]))))' \
    "${credits_list[@]}" "${extra[@]}"
}

record_spent() {
  # $1: 全体の合否、$2: 中断なら 1。記録に失敗したら 1 を返す。
  [ "$spent_log_set" -eq 1 ] || return 0
  [ "$started" -gt 0 ] || return 0
  local stamp month total what
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  month="${stamp:0:4}-${stamp:4:2}"
  if ! total="$(total_credits)"; then
    echo "ERROR: クレジットの合計を出せません。" >&2
    return 1
  fi
  what="${copilot_version}・${model}・${started} 回・$1"
  if [ "$unknown_credits" -eq 1 ] || [ "$started" -gt "${#credits_list[@]}" ]; then
    what+="・クレジット不明の回は上限で数えた"
  fi
  [ "$2" -eq 1 ] && what+="・中断"
  if ! helper spent-log "$spent_log" "copilot-canary-$stamp-$$" "$month" "$total" "$what"; then
    echo "ERROR: 使ったクレジットを $spent_log に記録できませんでした（$total）。" >&2
    return 1
  fi
}

# shellcheck disable=SC2329  # trap から呼ぶ。
on_interrupt() {
  [ "$finished" -eq 1 ] && exit 1
  finished=1
  trap - INT TERM EXIT
  if [ -n "$child_pid" ]; then
    kill -TERM "$child_pid" 2>/dev/null
    wait "$child_pid" 2>/dev/null
    child_pid=""
  fi
  echo "中断されました。後片付けをします。" >&2
  cleanup
  if [ "${#cleanup_reasons[@]}" -gt 0 ]; then
    echo "[不合格] 後片付け: $(IFS='; '; echo "${cleanup_reasons[*]}")"
  else
    echo "[合格] 後片付け"
  fi
  record_spent 不合格 1
  echo "全体: 不合格（中断）"
  exit 1
}
# shellcheck disable=SC2329  # trap から呼ぶ。
on_exit() {
  # 想定外の終わり方（set -u の誤りなど）でも片付けて、使ったクレジットを数える。
  [ "$finished" -eq 1 ] && return
  on_interrupt
}

# 3. 中断に備える。
trap on_interrupt INT TERM
trap on_exit EXIT

# 4. 目印を置く（上書きしない）。
if ! ( set -C; printf 'c3c canary mark\n' > "$HOME_MARK" ) 2>/dev/null; then
  finished=1
  fail_pre "$HOME_MARK に目印を置けません。"
fi
mark_written=1
if [ -L "$HOME_MARK" ] || [ ! -f "$HOME_MARK" ] || [ ! -r "$HOME_MARK" ]; then
  finished=1
  rm -f "$HOME_MARK" 2>/dev/null
  fail_pre "$HOME_MARK の目印が読める通常のファイルになっていません。"
fi

# 5. canary を N 回。
prompt="$PROMPT_HEAD"$'\n'"$CANARY_COMMAND"
for (( n = 1; n <= runs; n++ )); do
  if ! sid="$("$PYTHON3" -I -c 'import uuid; print(uuid.uuid4())')" || [ -z "$sid" ]; then
    add_row "canary $n" 不合格 "session ID を作れない"
    continue
  fi
  events="$COPILOT_HOME/session-state/$sid/events.jsonl"
  session_lines+=("canary $n: session $sid  $events")
  started=$(( started + 1 ))
  ( cd "$WORKDIR" && exec "$COPILOT_BIN" -p "$prompt" -s --model "$model" --session-id "$sid" \
      --max-ai-credits "$cap" "${COPILOT_ARGS[@]}" ) >/dev/null 2>&1 &
  child_pid=$!
  wait "$child_pid"
  copilot_rc=$?
  child_pid=""
  reasons=()
  [ "$copilot_rc" -eq 0 ] || reasons+=("copilot の rc=$copilot_rc")
  judge_out="$(helper judge "$events" "$CANARY_COMMAND" "$outer_user" "$outer_net" "$sid" 2>&1)"
  judge_rc=$?
  verdict="${judge_out%%$'\n'*}"
  credits_line="$(printf '%s\n' "$judge_out" | sed -n 2p)"
  case "$judge_rc" in
    0) ;;
    1) reasons+=("${verdict#FAIL: }") ;;
    *) reasons+=("判定できない: $verdict") ;;
  esac
  if [ -e "$W_FILE" ] || [ -L "$W_FILE" ]; then
    reasons+=("作業ディレクトリに $W_FILE_NAME ができた")
    rm -f "$W_FILE" 2>/dev/null
  fi
  note=""
  case "$credits_line" in
    credits=unknown | "")
      credits_list+=("$cap")
      unknown_credits=1
      note="クレジット不明（上限で数えた）"
      ;;
    credits=*)
      credits_list+=("${credits_line#credits=}")
      note="${credits_line#credits=} クレジット"
      ;;
  esac
  if [ "${#reasons[@]}" -eq 0 ]; then
    add_row "canary $n" 合格 "$note"
  else
    add_row "canary $n" 不合格 "$(IFS='; '; echo "${reasons[*]}")。$note"
  fi
done

# 6. 作業ディレクトリ /home/node で起動口が止まる（モデルを呼ばない）。
home_err="$(cd "$CONTAINER_HOME" && "$COPILOT_BIN" --version 2>&1 >/dev/null)"
home_rc=$?
if [ "$home_rc" -eq 1 ] && [[ "$home_err" == *"ERROR: 作業ディレクトリ $CONTAINER_HOME では起動しません"* ]]; then
  add_row "/home/node で止まる" 合格 ""
else
  add_row "/home/node で止まる" 不合格 "rc=$home_rc"
fi

# 7. 弱めた settings.json が、起動口を通すと雛形に戻る（モデルを呼ばない）。
if [ ! -e "$COPILOT_HOME/settings.json" ]; then
  run_launcher_version "$WORKDIR"
fi
if ! helper weaken "$COPILOT_HOME/settings.json" >/dev/null 2>&1; then
  add_row "弱めた設定が戻る" 確かめていない "settings.json を弱められなかった"
else
  restore_reasons=()
  run_launcher_version "$WORKDIR" || restore_reasons+=("起動口の --version の rc=$?")
  if ! match="$(helper settings-match "$COPILOT_HOME/settings.json" "$SETTINGS_TEMPLATE" "$WORKDIR" 2>&1)"; then
    restore_reasons+=("${match:-雛形と違う}")
  fi
  if [ "${#restore_reasons[@]}" -eq 0 ]; then
    add_row "弱めた設定が戻る" 合格 ""
  else
    add_row "弱めた設定が戻る" 不合格 "$(IFS='; '; echo "${restore_reasons[*]}")"
  fi
fi

# 8. 後片付け（表と rc を決める前に行う）。ここからは中断でも片付けを繰り返さない。
trap '' INT TERM
finished=1
cleanup
if [ "${#cleanup_reasons[@]}" -eq 0 ]; then
  add_row "後片付け" 合格 ""
else
  add_row "後片付け" 不合格 "$(IFS='; '; echo "${cleanup_reasons[*]}")"
fi

# 9. 表を出す。
overall=合格
for i in "${!row_names[@]}"; do
  [ "${row_status[$i]}" = 合格 ] || overall=不合格
  if [ -n "${row_reason[$i]}" ]; then
    printf '[%s] %s: %s\n' "${row_status[$i]}" "${row_names[$i]}" "${row_reason[$i]}"
  else
    printf '[%s] %s\n' "${row_status[$i]}" "${row_names[$i]}"
  fi
done
verified="$(sed -n 's/^readonly VERIFIED_COPILOT_VERSION=//p' "$COPILOT_BIN" | head -n 1)"
echo "Copilot の版: $copilot_version（起動口の VERIFIED_COPILOT_VERSION: ${verified:-不明}）"
echo "モデル: $model（1 回の上限 $cap クレジット）"
for line in "${session_lines[@]}"; do
  echo "$line"
done
if total="$(total_credits)"; then
  echo "使ったクレジットの合計: $total"
else
  echo "使ったクレジットの合計: 不明"
fi
rc=0
[ "$overall" = 合格 ] || rc=1
if ! record_spent "$overall" 0; then
  rc=1
fi
echo "全体: $overall"
trap - EXIT
exit "$rc"
