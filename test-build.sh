#!/bin/bash
# コンテナイメージのビルド・動作確認スクリプト
# 結果は .claude/test-results/YYYY-MM-DD_HHMMSS.log に保存される
# --clean オプションでテスト用イメージと dangling イメージを削除
# --build-only は実ビルドと CLI 起動、--config-ro-only は既存イメージのマウント保護を検査。

IMAGE="${TEST_IMAGE:-localhost/claude-test}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${TEST_LOG_DIR:-${SCRIPT_DIR}/.claude/test-results}"
LOG_FILE="${LOG_DIR}/$(date +%Y-%m-%d_%H%M%S).log"
PASS=0
FAIL=0

if [[ "${1:-}" == "--clean" ]]; then
  echo "テストイメージを削除します: ${IMAGE}"
  podman rmi "${IMAGE}" 2>/dev/null && echo "完了。" || echo "イメージがないのでスキップします。"
  echo "dangling イメージを整理しています..."
  podman image prune -f
  exit 0
fi

mkdir -p "$LOG_DIR"

log() {
  echo "$@" | tee -a "$LOG_FILE"
}

check() {
  local desc="$1"; shift
  local output status
  output=$("$@" 2>&1) && status=0 || status=$?
  if [ "$status" -eq 0 ]; then
    printf "  %-52s[PASS]\n" "$desc" | tee -a "$LOG_FILE"
    PASS=$((PASS + 1))
  else
    printf "  %-52s[FAIL]\n" "$desc" | tee -a "$LOG_FILE"
    FAIL=$((FAIL + 1))
  fi
  printf "%s\n" "$output" >> "$LOG_FILE"
}

# 結果の 3 行を出して FAIL 件数で終了コードを決める。サブモードと全体実行の両方から呼ぶ
# （claude-container#65: 全体実行だけ FAIL があっても 0 で終わっていた）。
finish_by_result() {
  log "========================================"
  log "  結果: PASS=${PASS}  FAIL=${FAIL}"
  log "========================================"
  if [ "$FAIL" -eq 0 ]; then
    exit 0
  fi
  exit 1
}

# --- 層1: validate-build-input.sh のベクタ表・契約異常系テスト（claude-container#34） ---
# ハーネス本体は1箇所にだけ書き、--validator-only と通常実行の両方から呼ぶ
# （複製すると中核設計2で排除したドリフトを検査側に再導入する）。
# 関数定義は早期ディスパッチより前に置く — bash は関数定義文を実行して初めて
# 関数を登録するため、定義をこれより後ろに置くと呼び出しが command not found に
# なり、しかも rc=0 で終わる（第7版の独立検証で実測確認済み）。
#
# ベクタ表フォーマット: kind|class|input|expected
#   class: accept(rc0、outfile が expected と完全一致) /
#          exclude(rc0、outfile が空) / reject(rc1、outfile が番兵のまま不変)
#   input/expected は printf '%b' で展開するエスケープ表記
#   （\t \r \n \000 \357\273\277=BOM \343\200\200=U+3000）を含みうる。
#   件数: packages 34（有効9・除外7・無効18）／requirements 35（有効11・除外4・無効20）
#   ／総計69／reject 38（計画「ベクタ表」節と1行＝1ベクタで対応、件数はここから機械導出）。
VBI_VECTORS=(
  # packages 有効(9)
  'packages|accept|htop\n|htop\n'
  'packages|accept|python3-pip\n|python3-pip\n'
  'packages|accept|libc6\n|libc6\n'
  'packages|accept|ab\n|ab\n'
  'packages|accept|g++\n|g++\n'
  'packages|accept|htop \n|htop\n'
  'packages|accept|htop\t\n|htop\n'
  'packages|accept|htop\r\n|htop\n'
  'packages|accept|htop|htop'
  # packages 除外(7)
  'packages|exclude|# comment\n|'
  'packages|exclude|  # foo\n|'
  'packages|exclude|\t# foo\n|'
  'packages|exclude|\n|'
  'packages|exclude|\r\n|'
  'packages|exclude| \r\n|'
  'packages|exclude|\t\r\n|'
  # packages 無効(18・reject)
  'packages|reject|-o\n|'
  'packages|reject|htop -o Foo=bar\n|'
  'packages|reject|htop --reinstall\n|'
  'packages|reject|Htop\n|'
  'packages|reject|../etc\n|'
  'packages|reject|htop=1.2\n|'
  'packages|reject|htop # note\n|'
  'packages|reject|tini-\n|'
  'packages|reject|sudo-\n|'
  'packages|reject|htop.\n|'
  'packages|reject|r\n|'
  'packages|reject|lib_a\n|'
  'packages|reject|htop:amd64\n|'
  'packages|reject|\343\200\200htop\n|'
  'packages|reject|\357\273\277htop\n|'
  'packages|reject|ht\rop\n|'
  'packages|reject|htop\r\r\n|'
  'packages|reject|ht\000op\n|'
  # requirements 有効(11)
  'requirements|accept|requests\n|requests\n'
  'requirements|accept|requests[socks]>=2.0,<3\n|requests[socks]>=2.0,<3\n'
  'requirements|accept|ruff==0.4.*\n|ruff==0.4.*\n'
  'requirements|accept|pkg===1.0\n|pkg===1.0\n'
  'requirements|accept|r\n|r\n'
  'requirements|accept|requests  # comment\n|requests\n'
  'requirements|accept|requests#garbage\n|requests\n'
  'requirements|accept|requests\r\n|requests\n'
  'requirements|accept|requests\r#comment\n|requests\n'
  'requirements|accept|pkg==1.0\r#x\n|pkg==1.0\n'
  'requirements|accept|requests|requests'
  # requirements 除外(4)
  'requirements|exclude|# comment\n|'
  'requirements|exclude|  # foo\n|'
  'requirements|exclude|\n|'
  'requirements|exclude|\r\n|'
  # requirements 無効(20・reject)
  'requirements|reject|requests\r\r\n|'
  'requirements|reject|req\ruests\n|'
  'requirements|reject|\rrequests\n|'
  'requirements|reject|\357\273\277requests\n|'
  'requirements|reject|req\000uests\n|'
  'requirements|reject|-e git+https://example.com/x.git#egg=x\n|'
  'requirements|reject|--index-url https://example.com/simple\n|'
  'requirements|reject|git+https://example.com/x.git#egg=x\n|'
  'requirements|reject|pkg @ https://example.com/x.whl\n|'
  'requirements|reject|./local\n|'
  'requirements|reject|-r other.txt\n|'
  'requirements|reject|pkg; python_version<"3.9"\n|'
  'requirements|reject|pkg --config-settings x==y\n|'
  'requirements|reject|pkg --global-option x==y\n|'
  'requirements|reject|pkg\t--config-settings\tx==y\n|'
  'requirements|reject|pkg ~= 1.4\n|'
  'requirements|reject|pkg[,a]\n|'
  'requirements|reject|pkg[a,]\n|'
  'requirements|reject|pkg[a,,b]\n|'
  'requirements|reject|pkg[]\n|'
)

# 層1本体: ベクタ表全69件＋件数アサーション4件を実行する。
run_validator_layer1() {
  local vbi="${SCRIPT_DIR}/validate-build-input.sh"
  local t infile outfile expfile
  t=$(mktemp -d) || { log "  [FAIL] layer1: mktemp -d failed"; FAIL=$((FAIL + 1)); return; }
  infile="$t/in"; outfile="$t/out"; expfile="$t/expected"

  local entry kind class input expected actual_rc
  local pkg_count=0 req_count=0 reject_count=0 total_count=0

  for entry in "${VBI_VECTORS[@]}"; do
    IFS='|' read -r kind class input expected <<< "$entry"
    total_count=$((total_count + 1))
    [ "$kind" = "packages" ] && pkg_count=$((pkg_count + 1))
    [ "$kind" = "requirements" ] && req_count=$((req_count + 1))
    [ "$class" = "reject" ] && reject_count=$((reject_count + 1))

    printf 'SENTINEL' > "$outfile"
    printf '%b' "$input" > "$infile"
    actual_rc=0
    LC_ALL=C sh "$vbi" "$kind" "$infile" "$outfile" >/dev/null 2>&1 || actual_rc=$?

    case "$class" in
      accept)
        printf '%b' "$expected" > "$expfile"
        if [ "$actual_rc" -eq 0 ] && cmp -s "$expfile" "$outfile"; then
          PASS=$((PASS + 1))
        else
          FAIL=$((FAIL + 1))
          log "  [FAIL] layer1 accept kind=$kind input=[$input] rc=$actual_rc"
        fi
        ;;
      exclude)
        if [ "$actual_rc" -eq 0 ] && [ ! -s "$outfile" ]; then
          PASS=$((PASS + 1))
        else
          FAIL=$((FAIL + 1))
          log "  [FAIL] layer1 exclude kind=$kind input=[$input] rc=$actual_rc"
        fi
        ;;
      reject)
        printf 'SENTINEL' > "$expfile"
        if [ "$actual_rc" -eq 1 ] && cmp -s "$expfile" "$outfile"; then
          PASS=$((PASS + 1))
        else
          FAIL=$((FAIL + 1))
          log "  [FAIL] layer1 reject kind=$kind input=[$input] rc=$actual_rc"
        fi
        ;;
    esac
  done

  # 件数アサーション4件（抽出漏れ・区切り記号依存を機械的に検出する。数は
  # 計画「ベクタ表」節の表から機械導出した値で、転記しない）。
  if [ "$pkg_count" -eq 34 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer1 packages件数=$pkg_count (期待34)"; fi
  if [ "$req_count" -eq 35 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer1 requirements件数=$req_count (期待35)"; fi
  if [ "$total_count" -eq 69 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer1 総数=$total_count (期待69)"; fi
  if [ "$reject_count" -eq 38 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer1 reject件数=$reject_count (期待38)"; fi

  rm -rf "$t"
}

# 終了コード契約の異常系・outfile 保全ケース（E1〜E8・P1、計画「4つ組では踏めない
# ケース」節のケースID付き表と1対1対応。1行＝1ケース＝PASS 1件）。
run_validator_contract() {
  local vbi="${SCRIPT_DIR}/validate-build-input.sh"
  local t infile outfile expfile actual_rc
  t=$(mktemp -d) || { log "  [FAIL] contract: mktemp -d failed"; FAIL=$((FAIL + 1)); return; }
  infile="$t/in"; outfile="$t/out"; expfile="$t/expected"

  # E1: 未知の kind → rc2・既存 outfile の番兵不変
  printf 'SENTINEL' > "$outfile"
  printf 'htop\n' > "$infile"
  actual_rc=0
  sh "$vbi" domains "$infile" "$outfile" >/dev/null 2>&1 || actual_rc=$?
  printf 'SENTINEL' > "$expfile"
  if [ "$actual_rc" -eq 2 ] && cmp -s "$expfile" "$outfile"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E1 rc=$actual_rc"; fi

  # E2: 引数不足 → rc2（outfile 引数が無いため状態確認は適用しない）
  actual_rc=0
  sh "$vbi" packages >/dev/null 2>&1 || actual_rc=$?
  if [ "$actual_rc" -eq 2 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E2 rc=$actual_rc"; fi

  # E3: 引数過多 → rc2・既存 outfile の番兵不変（E2 と違い有効な outfile が実在する）
  printf 'SENTINEL' > "$outfile"
  printf 'htop\n' > "$infile"
  actual_rc=0
  sh "$vbi" packages "$infile" "$outfile" extra >/dev/null 2>&1 || actual_rc=$?
  printf 'SENTINEL' > "$expfile"
  if [ "$actual_rc" -eq 2 ] && cmp -s "$expfile" "$outfile"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E3 rc=$actual_rc"; fi

  # E4: infile が存在しない → rc2・番兵不変
  printf 'SENTINEL' > "$outfile"
  rm -f "$t/nonexistent"
  actual_rc=0
  sh "$vbi" packages "$t/nonexistent" "$outfile" >/dev/null 2>&1 || actual_rc=$?
  printf 'SENTINEL' > "$expfile"
  if [ "$actual_rc" -eq 2 ] && cmp -s "$expfile" "$outfile"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E4 rc=$actual_rc"; fi

  # E5: infile が読めない（chmod 000）→ rc2・番兵不変
  printf 'SENTINEL' > "$outfile"
  printf 'htop\n' > "$infile"
  chmod 000 "$infile"
  actual_rc=0
  sh "$vbi" packages "$infile" "$outfile" >/dev/null 2>&1 || actual_rc=$?
  chmod 644 "$infile"
  printf 'SENTINEL' > "$expfile"
  if [ "$actual_rc" -eq 2 ] && cmp -s "$expfile" "$outfile"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E5 rc=$actual_rc"; fi

  # E6: infile と outfile が同一パス → rc2・infile 不変（in-place 置換なし）
  printf 'htop \n' > "$t/same"
  actual_rc=0
  sh "$vbi" packages "$t/same" "$t/same" >/dev/null 2>&1 || actual_rc=$?
  printf 'htop \n' > "$expfile"
  if [ "$actual_rc" -eq 2 ] && cmp -s "$expfile" "$t/same"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E6 rc=$actual_rc"; fi

  # E7: outfile のディレクトリへ一時ファイルを作れない → rc2（outfile は未作成）
  printf 'htop\n' > "$infile"
  actual_rc=0
  sh "$vbi" packages "$infile" "/nonexistent-dir-vbi-e7/packages.norm" >/dev/null 2>&1 || actual_rc=$?
  if [ "$actual_rc" -eq 2 ] && [ ! -e "/nonexistent-dir-vbi-e7/packages.norm" ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E7 rc=$actual_rc"; fi

  # E8: 作業用一時ディレクトリを作れない（TMPDIR 経由で誘発）→ rc2・番兵不変
  printf 'SENTINEL' > "$outfile"
  printf 'htop\n' > "$infile"
  actual_rc=0
  TMPDIR="/nonexistent-tmpdir-vbi-e8" sh "$vbi" packages "$infile" "$outfile" >/dev/null 2>&1 || actual_rc=$?
  printf 'SENTINEL' > "$expfile"
  if [ "$actual_rc" -eq 2 ] && cmp -s "$expfile" "$outfile"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract E8 rc=$actual_rc"; fi

  # P1: outfile がシンボリックリンク＋正当な入力 → rc0・リンク先ファイルが不変
  # （置き換わるのはリンクの名前だけ。mv -f の帰結として意図した挙動）
  printf 'TARGET-ORIGINAL' > "$t/target.dat"
  ln -sf "$t/target.dat" "$t/link.norm"
  printf 'htop\n' > "$infile"
  actual_rc=0
  sh "$vbi" packages "$infile" "$t/link.norm" >/dev/null 2>&1 || actual_rc=$?
  printf 'TARGET-ORIGINAL' > "$expfile"
  if [ "$actual_rc" -eq 0 ] && cmp -s "$expfile" "$t/target.dat"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] contract P1 rc=$actual_rc"; fi

  rm -rf "$t"
}

# 層2: 配線の回帰条件（Dockerfile.claude が validate-build-input.sh を正しく
# 使っているか。「スクリプトが正しい」ことと「Dockerfile がそれを使っている」こと
# は別、claude-container#34）。
# アンカー規則（実測に基づく設計判断。実装コメントとして残す）:
#   - apt-get install・packages.txt を単独のアンカーにしない
#     （現行 Dockerfile で4論理行にヒットし判別力がゼロになる）
#   - 「論理行に /tmp/packages.txt が現れないこと」という否定条件は使えない
#     （T2 が検証呼び出しを同一 RUN 内に置くため、validator の引数として
#     /tmp/packages.txt が必ず現れる。この否定条件はどんな正しい実装に対しても偽になる）
#   - 判定は「install へ入力を供給する位置」に限定する: apt-get install の
#     引数を生成するコマンド置換のリダイレクト元・pip3 install -r の引数・
#     空判定 [ -s ... ] の被検査パスの3点が .norm を指し .txt を指さないことを見る
run_validator_layer2() {
  local dockerfile="${SCRIPT_DIR}/Dockerfile.claude"
  local t rc
  t=$(mktemp -d) || { log "  [FAIL] layer2: mktemp -d failed"; FAIL=$((FAIL + 1)); return; }

  # 論理行化。パイプの終了コードに委ねず中間ファイルで各段の rc を判定する
  # （実装制約9・10・12と同じ制約がハーネス側にも及ぶ）。
  # (1) CR 除去 (2) 行継続中でも先頭非空白が # の物理行はコメント除去
  # (3) 末尾 \ の行を次行へ連結。本リポジトリの整形規約に対応する簡易論理行化
  # であり、Dockerfile パーサ相当を主張しない（ヒアドキュメントは対象外）。
  rc=0
  sed -e 's/\r$//' "$dockerfile" > "$t/step1" || rc=$?
  if [ "$rc" -ne 0 ]; then log "  [FAIL] layer2: sed(CR除去) failed rc=$rc"; FAIL=$((FAIL + 1)); rm -rf "$t"; return; fi

  rc=0
  grep -v '^[[:space:]]*#' "$t/step1" > "$t/step2" || rc=$?
  if [ "$rc" -ge 2 ]; then log "  [FAIL] layer2: grep(コメント除去) failed rc=$rc"; FAIL=$((FAIL + 1)); rm -rf "$t"; return; fi

  awk '{ cur = $0
         if (sub(/\\[[:space:]]*$/, "", cur)) { acc = acc cur; next }
         print acc cur; acc = "" }
       END { if (acc != "") print acc }' "$t/step2" > "$t/logical"
  rc=$?
  if [ "$rc" -ne 0 ]; then log "  [FAIL] layer2: awk(論理行連結) failed rc=$rc"; FAIL=$((FAIL + 1)); rm -rf "$t"; return; fi

  local logical="$t/logical"
  local hits

  # 検査1: apt-get install の入力供給位置(コマンド置換のリダイレクト元)が
  # .norm を指し .txt を指さないこと
  hits=$(grep -cF '< /tmp/packages.norm)' "$logical")
  if [ "$hits" -eq 1 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: packages install入力位置のヒット数=$hits (期待1)"; fi
  hits=$(grep -cF '< /tmp/packages.txt)' "$logical")
  if [ "$hits" -eq 0 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: packages installが.txtを指している(ヒット数=$hits)"; fi

  # 検査2: pip3 install -r の引数が .norm を指し .txt を指さないこと
  hits=$(grep -cF 'pip3 install -r /tmp/requirements.norm' "$logical")
  if [ "$hits" -eq 1 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: requirements install引数のヒット数=$hits (期待1)"; fi
  hits=$(grep -cF 'pip3 install -r /tmp/requirements.txt' "$logical")
  if [ "$hits" -eq 0 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: requirements installが.txtを指している(ヒット数=$hits)"; fi

  # 検査3: requirements 空判定の被検査パスが .norm を指し .txt を指さないこと
  hits=$(grep -cF '[ -s /tmp/requirements.norm ]' "$logical")
  if [ "$hits" -eq 1 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: requirements空判定のヒット数=$hits (期待1)"; fi
  hits=$(grep -cF '[ -s /tmp/requirements.txt ]' "$logical")
  if [ "$hits" -eq 0 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: requirements空判定が.txtを指している(ヒット数=$hits)"; fi

  # 検査4: validator 呼び出しが両 kind について存在し || exit 1 相当で握られていること
  hits=$(grep -F 'sh /tmp/validate-build-input.sh packages' "$logical" | grep -cF '|| exit 1;')
  if [ "$hits" -eq 1 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: packages validator呼び出しのヒット数=$hits (期待1)"; fi
  hits=$(grep -F 'sh /tmp/validate-build-input.sh requirements' "$logical" | grep -cF '|| exit 1;')
  if [ "$hits" -eq 1 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: requirements validator呼び出しのヒット数=$hits (期待1)"; fi

  # 検査5: COPY が validate-build-input.sh をイメージへ運んでいること
  hits=$(grep -cF 'COPY validate-build-input.sh /tmp/' "$logical")
  if [ "$hits" -eq 1 ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); log "  [FAIL] layer2: COPYのヒット数=$hits (期待1)"; fi

  rm -rf "$t"
}

# 層1（ベクタ表・契約異常系）の実行入口。--validator-only と通常実行の両方から
# 呼ぶ（複製しない）。層2（Dockerfile.claude 配線の静的検査）は --validator-only
# の対象外（計画の検証手順が定める合格条件 PASS==82 は層1+契約異常系のみを指す）
# のため、ここには含めず通常実行フロー側で別途呼ぶ。
run_validator_layer1_and_contract() {
  log "## 層1: validate-build-input.sh ベクタ表・契約異常系テスト（claude-container#34）"
  run_validator_layer1
  run_validator_contract
  log ""
}

# --- ホスト ~/.claude 設定の読み取り専用保護（compose.yml の :ro 重ねマウント） ---
# ホスト側で実行・読込される user scope の設定 12 項目を、コンテナ内から書き換え
# られないことを検証する。検証するストリームと実際に使うストリームを分岐させない
# ため、実物の compose.yml・実物のイメージ・userns keep-id をそのまま使い、
# `podman compose run --entrypoint bash` で書き込みを試みる（volumes を抜き出して
# 別コマンドに組み直すと、検証した構成と起動する構成が別物になる）。
CONFIG_RO_DIRS=(hooks skills plugins commands agents workflows rules output-styles .git)
CONFIG_RO_FILES=(settings.json CLAUDE.md statusline.sh)

# コンテナ内で実行する検査スクリプト。各項目について「新規作成」「既存への追記」
# 「削除」（ファイルは加えて rename による置換）を試み、失敗理由が Read-only file
# system（EROFS）または Device or resource busy（EBUSY: mountpoint 自体の削除・置換）
# であることまで確認する。EACCES/EISDIR 等の別理由で失敗した場合は「保護されて
# いる」とは見なさず FAIL にする（権限不足を保護成立と誤認しない）。
# 対象外の projects/ への書き込みは成功しなければならない（状態の永続化を壊さない）。
# shellcheck disable=SC2016  # コンテナ内 bash へ渡す文字列。$ はコンテナ側で展開させる意図
CONFIG_RO_PROBE='
set -u
cd "$HOME/.claude" || { echo "PROBE-ERROR: cannot cd"; exit 2; }
fail=0
expect_ro() {  # $1=ラベル, 残り=コマンド。EROFS/EBUSY で失敗すれば OK
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    echo "RW-LEAK $label (succeeded)"; fail=1; return
  fi
  case "$out" in
    *"Read-only file system"*|*"Device or resource busy"*) echo "RO-OK $label" ;;
    *) echo "RO-WRONG-REASON $label ($out)"; fail=1 ;;
  esac
}
for d in '"${CONFIG_RO_DIRS[*]}"'; do
  expect_ro "$d/create"  sh -c "echo x > $d/probe-new"
  expect_ro "$d/append"  sh -c "echo x >> $d/seed"
  expect_ro "$d/delete"  rm -f "$d/seed"
done
for f in '"${CONFIG_RO_FILES[*]}"'; do
  expect_ro "$f/append"  sh -c "echo x >> $f"
  expect_ro "$f/delete"  rm -f "$f"
  expect_ro "$f/replace" sh -c "echo x > $f.tmp && mv -f $f.tmp $f"
  rm -f "$f.tmp"
done
if echo x > projects/probe-rw; then echo "RW-OK projects"; else echo "RW-BROKEN projects"; fail=1; fi
exit $fail
'

# plugin 別名マウント（compose.plugins-alias.yml、#98）込みの実構成で、別名パス経由でも
# 書けない（EROFS/EBUSY）こと、別名経由で内容が読めること、destination の親（podman が
# コンテナ作成時に作る root 所有ディレクトリ）にも書けないことを確認する。
CONFIG_RO_ALIAS_DEST="/home/hostuser-probe/.claude/plugins"
# shellcheck disable=SC2016  # コンテナ内 bash へ渡す文字列。$ はコンテナ側で展開させる意図
CONFIG_RO_ALIAS_PROBE='
set -u
fail=0
expect_ro() {
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    echo "RW-LEAK $label (succeeded)"; fail=1; return
  fi
  case "$out" in
    *"Read-only file system"*|*"Device or resource busy"*) echo "RO-OK $label" ;;
    *) echo "RO-WRONG-REASON $label ($out)"; fail=1 ;;
  esac
}
cd "'"$CONFIG_RO_ALIAS_DEST"'" || { echo "PROBE-ERROR: alias not mounted"; exit 2; }
if [ "$(cat seed 2>/dev/null)" = seed ]; then echo "READ-OK alias/seed"; else echo "READ-BROKEN alias/seed"; fail=1; fi
expect_ro "alias/create"  sh -c "echo x > probe-new"
expect_ro "alias/append"  sh -c "echo x >> seed"
expect_ro "alias/delete"  rm -f seed
expect_ro "alias/replace" sh -c "echo x > seed.tmp && mv -f seed.tmp seed"
# 親ディレクトリは podman が root 所有で作る（理由は EACCES）。書けなければ十分。
if touch /home/hostuser-probe/probe 2>/dev/null; then echo "RW-LEAK alias-parent"; fail=1; else echo "RO-OK alias-parent"; fi
exit $fail
'

# SHARED_MOUNT の別名 2 箇所と ~/.agents（#99）から読めて書けず、/shared には書けることを確認する。
# shellcheck disable=SC2016  # コンテナ内 bash へ渡す文字列。$ はコンテナ側で展開させる意図
SHARED_ALIAS_PROBE='
set -u
fail=0
expect_ro() {
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    echo "RW-LEAK $label (succeeded)"; fail=1; return
  fi
  case "$out" in
    *"Read-only file system"*|*"Device or resource busy"*) echo "RO-OK $label" ;;
    *) echo "RO-WRONG-REASON $label ($out)"; fail=1 ;;
  esac
}
for d in /home/node/vault-probe /home/hostuser-probe/vault-probe /home/node/.agents; do
  if [ "$(cat "$d/seed" 2>/dev/null)" = seed ]; then echo "READ-OK $d"; else echo "READ-BROKEN $d"; fail=1; fi
  expect_ro "$d/create" sh -c "echo x > $d/probe-new"
  expect_ro "$d/append" sh -c "echo x >> $d/seed"
done
if echo x > /shared/shared-probe 2>/dev/null; then echo "RW-OK /shared"; else echo "RW-BROKEN /shared"; fail=1; fi
exit $fail
'

# ホストの Codex plugin キャッシュ共有。キャッシュは読めて書けず、その親の CODEX_DIR（rw）には書けることを確認する。
# shellcheck disable=SC2016  # コンテナ内 bash へ渡す文字列。$ はコンテナ側で展開させる意図
CODEX_PLUGINS_PROBE='
set -u
fail=0
expect_ro() {
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    echo "RW-LEAK $label (succeeded)"; fail=1; return
  fi
  case "$out" in
    *"Read-only file system"*|*"Device or resource busy"*) echo "RO-OK $label" ;;
    *) echo "RO-WRONG-REASON $label ($out)"; fail=1 ;;
  esac
}
d=/home/node/.codex/plugins/cache
if [ "$(cat "$d/seed" 2>/dev/null)" = seed ]; then echo "READ-OK $d"; else echo "READ-BROKEN $d"; fail=1; fi
expect_ro "cache/create"  sh -c "echo x > $d/probe-new"
expect_ro "cache/append"  sh -c "echo x >> $d/seed"
expect_ro "cache/delete"  rm -f "$d/seed"
expect_ro "cache/replace" sh -c "echo x > $d/seed.tmp && mv -f $d/seed.tmp $d/seed"
expect_ro "cache/rmdir"   rmdir "$d"
if mkdir -p /home/node/.codex/plugins/.staging-probe 2>/dev/null; then echo "RW-OK plugins/"; else echo "RW-BROKEN plugins/"; fail=1; fi
if echo x > /home/node/.codex/rw-probe 2>/dev/null; then echo "RW-OK .codex"; else echo "RW-BROKEN .codex"; fail=1; fi
exit $fail
'

run_config_ro_tests() {
  log "## ホスト ~/.claude 設定の読み取り専用保護（compose.yml :ro 重ねマウント）"
  local proj="${TEST_COMPOSE_PROJECT:-claude-test-config-ro}"
  local compose_args=(-f "${SCRIPT_DIR}/compose.yml")
  if [[ "${TEST_RUNTIME_USERNS:-}" == 1 ]]; then
    compose_args+=(-f "${SCRIPT_DIR}/tests/compose.runtime-userns.yml")
  fi
  local svc_image="localhost/${proj}_claude-auth-workspace:latest"
  local root cfg d f
  root="$(mktemp -d)"
  cfg="$root/.claude"
  mkdir -p "$cfg/projects"
  echo '{}' > "$root/.claude.json"
  for d in "${CONFIG_RO_DIRS[@]}"; do mkdir -p "$cfg/$d"; echo seed > "$cfg/$d/seed"; done
  for f in "${CONFIG_RO_FILES[@]}"; do echo seed > "$cfg/$f"; done

  # compose の暗黙ビルドを避けるため、ビルド済みテストイメージを compose が
  # 期待する名前（<project>_<service>）へタグ付けしてから run する。
  if ! podman tag "$IMAGE" "$svc_image" 2>/dev/null; then
    check "compose run (テストイメージ $IMAGE が無い)" false
    rm -rf "$root"; return
  fi
  check "12項目へ書けず projects/ へは書ける" env \
    CLAUDE_CONFIG_DIR="$root" CONTEXT="$root" CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$root" \
    podman compose "${compose_args[@]}" -p "$proj" --in-pod false \
      run --rm -T --entrypoint bash claude-auth-workspace -c "$CONFIG_RO_PROBE"
  # 別名 override 込みの実構成（#98）。標準パスの保護が override のマージで崩れないことと、
  # 別名パス経由の保護・可読性を、同じ compose.yml + override で起動して確認する。
  check "別名 override 込みでも 12項目へ書けず projects/ へは書ける" env \
    CLAUDE_CONFIG_DIR="$root" CONTEXT="$root" CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$root" \
    CLAUDE_PLUGINS_HOST_PATH="$CONFIG_RO_ALIAS_DEST" \
    podman compose "${compose_args[@]}" -f "${SCRIPT_DIR}/compose.plugins-alias.yml" -p "$proj" --in-pod false \
      run --rm -T --entrypoint bash claude-auth-workspace -c "$CONFIG_RO_PROBE"
  check "別名パスから読めて書けず、親ディレクトリにも書けない" env \
    CLAUDE_CONFIG_DIR="$root" CONTEXT="$root" CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$root" \
    CLAUDE_PLUGINS_HOST_PATH="$CONFIG_RO_ALIAS_DEST" \
    podman compose "${compose_args[@]}" -f "${SCRIPT_DIR}/compose.plugins-alias.yml" -p "$proj" --in-pod false \
      run --rm -T --entrypoint bash claude-auth-workspace -c "$CONFIG_RO_ALIAS_PROBE"
  # shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
  check "別名経由の書き込み試行後もホスト側 plugins/seed が不変" \
    bash -c '[ "$(cat "$1/plugins/seed")" = seed ] && [ ! -e "$1/plugins/probe-new" ] && [ ! -e "$1/plugins/seed.tmp" ]' _ "$cfg"
  # ホスト側に別 uid（サブ uid の root 等）所有の残骸が生えていないこと。
  # 「特定 uid が無い」ではなく全エントリが実行ユーザー所有であることを見る。
  # SHARED_MOUNT の別名と AGENTS_DIR（#99）込みの実構成。
  local shared="$root/vault" agents="$root/agents"
  mkdir -p "$shared" "$agents"
  echo seed > "$shared/seed"
  echo seed > "$agents/seed"
  check "SHARED_MOUNT の別名 2 箇所と ~/.agents は読めて書けず、/shared には書ける" env \
    CLAUDE_CONFIG_DIR="$root" CONTEXT="$root" CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$root" \
    SHARED_MOUNT="$shared" CLAUDE_SHARED_HOME_PATH=/home/node/vault-probe \
    CLAUDE_SHARED_HOST_PATH=/home/hostuser-probe/vault-probe AGENTS_DIR="$agents" \
    podman compose "${compose_args[@]}" -f "${SCRIPT_DIR}/compose.shared-home.yml" \
      -f "${SCRIPT_DIR}/compose.shared-host.yml" -f "${SCRIPT_DIR}/compose.agents.yml" -p "$proj" --in-pod false \
      run --rm -T --entrypoint bash claude-auth-workspace -c "$SHARED_ALIAS_PROBE"
  # shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
  check "別名経由の書き込み試行後もホスト側 seed が不変で、/shared 経由の書き込みだけ残る" \
    bash -c '[ "$(cat "$1/vault/seed")" = seed ] && [ ! -e "$1/vault/probe-new" ] && [ -e "$1/vault/shared-probe" ] && [ "$(cat "$1/agents/seed")" = seed ] && [ ! -e "$1/agents/probe-new" ]' _ "$root"
  # ホストの Codex plugin キャッシュ共有の実構成。
  # source は CONTEXT（= $root、/workspace に rw でマウントされる）の外に置き、この override だけの経路を見る。
  local codex_home="$root/codex-home" codex_src
  codex_src="$(mktemp -d)"
  mkdir -p "$codex_home/plugins/cache"
  echo seed > "$codex_src/seed"
  check "Codex plugin キャッシュは読めて書けず、CODEX_DIR には書ける" env \
    CLAUDE_CONFIG_DIR="$root" CONTEXT="$root" CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$root" \
    CODEX_DIR="$codex_home" C3C_CODEX_PLUGINS_SOURCE="$codex_src" \
    podman compose "${compose_args[@]}" -f "${SCRIPT_DIR}/compose.codex-plugins.yml" -p "$proj" --in-pod false \
      run --rm -T --entrypoint bash claude-auth-workspace -c "$CODEX_PLUGINS_PROBE"
  # shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
  check "書き込み試行後もホスト側 source が不変で、CODEX_DIR 側の書き込みだけ残る" \
    bash -c '[ "$(cat "$2/seed")" = seed ] && [ "$(ls -A "$2")" = seed ] && [ -e "$1/codex-home/rw-probe" ] && [ -d "$1/codex-home/plugins/.staging-probe" ]' _ "$root" "$codex_src"
  rm -rf "$codex_src"
  check "一時 ~/.claude 配下の全エントリが実行ユーザー所有" \
    bash -c "out=\$(find '$root' -not -uid $(id -u) -print 2>&1); [[ \$? -eq 0 && -z \"\$out\" ]]"
  env CLAUDE_CONFIG_DIR="$root" CONTEXT="$root" CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$root" \
    podman compose "${compose_args[@]}" -p "$proj" --in-pod false down >/dev/null 2>&1
  podman rmi "$svc_image" >/dev/null 2>&1
  rm -rf "$root"
  log ""
}

# --- ランチャー（c3c）のダミー podman テスト ---
# ランチャー本体のガード群を、模倣ではなく c3c を実際に起動して検証する
# （podman はダミー化し、compose には到達させない。実 podman 不要のためコンテナ内や
# CI でも回せる）。HOME を一時ディレクトリに向けることで、既定の基点（$HOME/.claude）・
# 起動台帳・MCP 承認記録がすべて一時領域に閉じ、実環境を汚さない。
#
# 各テスト関数は `local root bin home proj out rc before_ctx` を宣言してから
# launcher_sandbox_init を呼び、最後に launcher_sandbox_cleanup を呼ぶ（bash の
# 動的スコープにより、ヘルパーは呼び出し側の local へ代入する）。
launcher_sandbox_init() {
  root="$(mktemp -d)"; bin="$root/bin"; home="$root/home"; proj="$root/proj"
  mkdir -p "$bin" "$home/.claude" "$proj"
  # ダミー podman: compose 呼び出し時の環境と引数を記録する（ランチャー → compose の
  # 接続部 — CLAUDE_CONFIG_DIR の export 等 — を検証するため）。compose-env は最後の
  # 呼び出しの環境（従来互換）、compose-args は全呼び出しの引数の連結。加えて
  # compose-env.<n>・compose-args.<n> に n 回目の呼び出しを個別に残す（-b の build と
  # run で export や override が片方だけ漏れていないかを見分けるため。#98）。
  cat > "$bin/podman" <<DUMMY
#!/bin/bash
if [[ "\${1:-}" == --remote=false ]]; then shift; fi
case "\$1 \$2" in
  "images --all") printf '%s\\n' '[]'; exit 0 ;;
  "image exists") exit 0 ;;
  "image inspect")
    if [[ "\$*" == *claude-container.ipv6-support* ]]; then printf '%s\n' "\${TEST_IPV6_SUPPORT-1}"; fi
    exit 0 ;;
esac
if [[ "\$1" == "compose" ]]; then
  n=\$(( \$(cat "$root/compose-calls" 2>/dev/null || echo 0) + 1 ))
  printf '%s\n' "\$n" > "$root/compose-calls"
  env > "$root/compose-env"; env > "$root/compose-env.\$n"
  printf '%s\n' "\$@" >> "$root/compose-args"; printf '%s\n' "\$@" > "$root/compose-args.\$n"
fi
exit 0
DUMMY
  chmod +x "$bin/podman"
  # ランチャーはプロジェクト毎の .build-context/<name>/ を作るため、前後の差分を控えて後始末する
  before_ctx="$(ls -1 "${SCRIPT_DIR}/.build-context/" 2>/dev/null || true)"
}

# 環境を env -i で空にしてから HOME・PATH だけを与える（実行者のシェルに
# CLAUDE_CONFIG_DIR・SECRETS_DIR 等が export されていても実環境へ波及させない）。
# 引数は KEY=VALUE でランチャーへ渡す環境変数。結果は out（出力）と rc（終了コード）。
launcher_sandbox_reset_records() {
  rm -f "$root/compose-env" "$root/compose-args" "$root/compose-calls" "$root"/compose-env.* "$root"/compose-args.*
}

run_launcher() {
  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "$@" "${SCRIPT_DIR}/c3c" claude "$proj" 2>&1) && rc=0 || rc=$?
}

# run_launcher の --check 版（同じ環境の隔離、同じプロジェクト）。引数は省略可。
# shellcheck disable=SC2120
run_launcher_check() {
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "$@" "${SCRIPT_DIR}/c3c" --check "$proj" 2>&1) && rc=0 || rc=$?
}

# --check の保護対象を記録する。atime は読むだけでも変わるので比較しない。
# NUL 区切りにより空白・改行を含む名前も扱い、収集失敗を空の一致で隠さない。
snapshot_check_targets() (
  set -o pipefail
  local target
  for target in "$home" "$proj" "${SCRIPT_DIR}/.build-context"; do
    if [[ -e "$target" || -L "$target" ]]; then
      find "$target" -printf '%y %m %U %G %T@ %p -> %l\0' | LC_ALL=C sort -z || return 1
      find "$target" -type f -exec sha256sum --zero -- {} + | LC_ALL=C sort -z || return 1
    else
      printf 'absent %s\0' "$target"
    fi
  done
)

# 保護対象（基点の .claude 以下）だけを記録する（claude-container#131）。snapshot_check_targets と
# 同じ属性・同じ NUL 区切りだが、起動台帳・承認記録・ステージングを含めない（拒否経路でも
# 書かれるそれらの差分で、保護対象の不変判定を汚さないため）。引数は基点の .claude。
snapshot_config_ro_targets() (
  set -o pipefail
  local target="$1"
  if [[ -e "$target" || -L "$target" ]]; then
    find "$target" -printf '%y %m %U %G %T@ %p -> %l\0' | LC_ALL=C sort -z || return 1
    find "$target" -type f -exec sha256sum --zero -- {} + | LC_ALL=C sort -z || return 1
  else
    printf 'absent %s\0' "$target"
  fi
)

# 起動前から不正な型の保護対象が 1 つだけある基点を作り直す（claude-container#131）。
# 引数: $1=基点、$2=保護対象名、$3=種別（file / dir / link / linkfile / dangling）。
# 先行する保護対象は欠落のままにし、symlink の実体は .claude の外へ置く（snapshot に混ぜない）。
config_ro_fixture_setup() {
  local base="$1" name="$2" kind="$3"
  rm -rf "$base" || return 1
  mkdir -p "$base/.claude" || return 1
  case "$kind" in
    file) printf 'gitdir: %s\n' "$base/elsewhere/.git" > "$base/.claude/$name" ;;
    dir) mkdir -p "$base/.claude/$name" ;;
    link) mkdir -p "$base/link-target-dir" && ln -s ../link-target-dir "$base/.claude/$name" ;;
    linkfile) printf 'x\n' > "$base/link-target-file" && ln -s ../link-target-file "$base/.claude/$name" ;;
    dangling) ln -s ../missing-target "$base/.claude/$name" ;;
    *) return 1 ;;
  esac
}

# ランチャーが作った .build-context/<name>/ を後始末する（実行前に無かったものだけ）。
launcher_sandbox_cleanup() {
  local after_ctx new_ctx
  after_ctx="$(ls -1 "${SCRIPT_DIR}/.build-context/" 2>/dev/null || true)"
  while IFS= read -r new_ctx; do
    [[ -n "$new_ctx" ]] && rm -rf "${SCRIPT_DIR}/.build-context/${new_ctx}"
  done < <(comm -13 <(echo "$before_ctx" | sort) <(echo "$after_ctx" | sort))
  rm -rf "$root"
}

# ランチャーテストの実行入口。通常実行と --launcher-only の双方がこの関数をちょうど
# 1 回呼ぶ（個別テスト関数を直接呼ばない。呼び出しがここに一本化されていないと、
# 入口を増やしたときに一方からだけ新テストが漏れる）。
run_launcher_tests() {
  log "## ランチャー（c3c）のガード検証（ダミー podman、実 podman 不要）"
  run_config_ro_launcher_tests
  run_plugins_alias_launcher_tests
  run_instruction_mount_launcher_tests
  run_ipv6_launcher_tests
  check "IPv6 のルール・entrypoint テスト" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_ipv6_*.py"
  check "通信待ちの上限・再試行・スナップショット保護" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_network_timeouts.py"
  check "定期更新の診断状態・ログ上限" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_refresh_monitor.py"
  check "欠落プロジェクトの限定清掃・残存イメージ診断" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_project_images.py"
  check "Codex 起動時 MCP 審査 helper（正規化・strict schema・timeout・verify）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_codex_mcp_audit.py"
  check "--agent codex の launcher 経路（parser・label guard・preflight・独立承認・check/clean）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_codex_launch.py"
  check "CLI 選択記憶 helper（Git 識別・strict JSON・無書込 read・原子的 write）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_agent_preference.py"
  check "c3c 入口（symlink 解決・旧名 symlink の同一契約・parser・初回選択/記憶・本 run 終了コード保持・check/clean の無書込）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_c3c_launch.py"
  check "設定ディレクトリの選択（.c3c/旧名/なし/二重配置/型不正・symlink、check の継続と無書込、clean の独立、新旧配置の hash 同一）と Node/Codex の既定ビルド入力（同梱 default・project pin・空 opt-out・npm WARNING）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_c3c_config.py"
  check "entrypoint の agent 分岐（enum・preflight 分離・固定 home/CLI・verify→exec・Claude 順序）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_codex_entrypoint.py"
  check "Codex 同梱 bubblewrap の解決（npm の nested/hoisted/legacy・x64/arm64・欠落/実行不能/target 外/help 4 項目の fail-closed）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_codex_bwrap.py"
  check "lint の compose config 検査（provider 差: 短縮 / long syntax、:ro と TTY 無効）" bash "${SCRIPT_DIR}/tests/test-lint-compose-checks.sh"
  run_base_image_launcher_tests
  run_codex_dir_launcher_tests
  run_codex_host_plugins_launcher_tests
  run_env_file_launcher_tests
  run_clean_ledger_launcher_tests
  run_missing_directory_launcher_tests
  run_allowed_ports_tests
  check "許可ドメインの入力検証とDNS解決前の拒否" bash "${SCRIPT_DIR}/tests/test-allowed-domains.sh"
  check "DNS 応答の除外・継続・エラー処理" bash "${SCRIPT_DIR}/tests/test-refresh-domains.sh"
  check "DNS ルールの更新順序・世代非更新・期限切れ削除" bash "${SCRIPT_DIR}/tests/test-domain-rule-lifecycle.sh"
  log ""
}

# --clean 後も台帳を 600 に保ち、対象以外の行を失わない（#52）。
# 実ランチャーを使い、HOME と podman は既存のテスト用隔離環境に閉じる。
# bash -c の検証式は親で展開せず、位置引数を子シェル内で評価する。
# shellcheck disable=SC2016
run_clean_ledger_launcher_tests() {
  local root bin home proj out rc before_ctx
  launcher_sandbox_init
  local ledger="$home/.local/state/claude-container/projects" mask
  run_launcher
  check "起動時に対象を台帳へ記録する（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && grep -qxF -- "$2" "$3" && [ "$(stat -c %a "$3")" = 600 ]' _ "$rc" "$proj" "$ledger"
  printf '%s\n' "$out" >> "$LOG_FILE"

  mkdir -p "$(dirname "$ledger")"
  for mask in 000 002 022; do
    printf '%s\n' "$root/other project" "$proj" "$root/last-project" > "$ledger"
    chmod 600 "$ledger"
    out=$(umask "$mask"; env -i HOME="$home" PATH="$bin:$PATH" \
      "${SCRIPT_DIR}/c3c" --clean "$proj" 2>&1) && rc=0 || rc=$?
    printf '%s\n' "$root/other project" "$root/last-project" > "$root/expected-ledger"
    check "umask $mask: clean 後の台帳は600、対象行だけ除去（rc=$rc）" \
      bash -c '[ "$1" -eq 0 ] && [ "$(stat -c %a "$2")" = 600 ] && cmp -s "$2" "$3" && [ ! -e "$2.tmp" ]' _ "$rc" "$ledger" "$root/expected-ledger"
    printf '%s\n' "$out" >> "$LOG_FILE"
  done

  printf '%s\n' "$proj" > "$ledger"
  out=$(umask 002; env -i HOME="$home" PATH="$bin:$PATH" \
    "${SCRIPT_DIR}/c3c" --clean "$proj" 2>&1) && rc=0 || rc=$?
  check "最後の対象を clean すると空の600台帳を残す（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && [ -f "$2" ] && [ ! -s "$2" ] && [ "$(stat -c %a "$2")" = 600 ]' _ "$rc" "$ledger"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # root でも確実に失敗するよう、権限設定だけを失敗させる。
  # --clean の chmod は台帳の一時ファイルだけ。ダミーはこのケース後に除去する。
  printf '%s\n' "$proj" "$root/other project" > "$ledger"
  cp "$ledger" "$root/expected-ledger"
  chmod 600 "$ledger"
  printf '#!/bin/bash\nexit 1\n' > "$bin/chmod"
  chmod +x "$bin/chmod"
  out=$(env -i HOME="$home" PATH="$bin:$PATH" \
    "${SCRIPT_DIR}/c3c" --clean "$proj" 2>&1) && rc=0 || rc=$?
  check "権限設定失敗時は ERROR で停止し元の600台帳を保持（rc=$rc）" \
    bash -c '[ "$1" -ne 0 ] && cmp -s "$2" "$3" && [ "$(stat -c %a "$2")" = 600 ] && ! compgen -G "$2.tmp*" >/dev/null && [[ "$4" == *"ERROR: 起動台帳の一時ファイル"* ]]' _ "$rc" "$ledger" "$root/expected-ledger" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
  rm -f "$bin/chmod"

  # grep が一部出力した後に失敗しても、元台帳を置き換えない（#84）。
  # stdout の実ファイル属性を調べ、書き込み前から600であることも検証する（#85）。
  ln -s "$(command -v grep)" "$bin/real-grep"
  cat > "$bin/grep" <<'SHIM'
#!/bin/bash
if [[ "${!#}" == "$HOME/.local/state/claude-container/projects" ]]; then
  stat -Lc %a "/proc/$$/fd/1" > "$HOME/ledger-write-mode"
  case "${LEDGER_TEST_FAILURE:-}" in
    empty) exit 2 ;;
    partial) printf '%s\n' partial-output; exit 2 ;;
  esac
fi
exec real-grep "$@"
SHIM
  chmod +x "$bin/grep"
  local failure
  for failure in empty partial; do
    printf '%s\n' "$proj" "$root/other project" > "$ledger"
    chmod 600 "$ledger"
    cp "$ledger" "$root/expected-ledger"
    out=$(umask 000; env -i HOME="$home" PATH="$bin:$PATH" LEDGER_TEST_FAILURE="$failure" \
      "${SCRIPT_DIR}/c3c" --clean "$proj" 2>&1) && rc=0 || rc=$?
    check "grep $failure 失敗時は元台帳を保持し一時台帳を除去（rc=$rc）" \
      bash -c '[ "$1" -ne 0 ] && cmp -s "$2" "$3" && [ "$(stat -c %a "$2")" = 600 ] && ! compgen -G "$2.tmp*" >/dev/null && [[ "$4" == *"ERROR: 起動台帳"* ]]' _ "$rc" "$ledger" "$root/expected-ledger" "$out"
    printf '%s\n' "$out" >> "$LOG_FILE"
  done
  # 旧版の残置 .tmp があっても内容やモードを変更せず、別の一時ファイルを使う。
  ln -s "$(command -v mktemp)" "$bin/real-mktemp"
  cat > "$bin/mktemp" <<'SHIM'
#!/bin/bash
created=$(real-mktemp "$@") || exit 1
stat -c %a "$created" > "$HOME/ledger-create-mode"
printf '%s\n' "$created"
SHIM
  chmod +x "$bin/mktemp"
  printf '%s\n' old-temp > "$ledger.tmp"
  chmod 666 "$ledger.tmp"
  cp "$ledger.tmp" "$root/old-temp"
  printf '%s\n' "$proj" "$root/other project" > "$ledger"
  printf '%s\n' "$root/other project" > "$root/expected-ledger"
  out=$(umask 000; env -i HOME="$home" PATH="$bin:$PATH" \
    "${SCRIPT_DIR}/c3c" --clean "$proj" 2>&1) && rc=0 || rc=$?
  check "旧tmpを再利用せず、生成時・書き込み前・更新後の権限は600（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && [ "$(cat "$2")" = 600 ] && [ "$(cat "$6")" = 600 ] && [ "$(stat -c %a "$3")" = 600 ] && cmp -s "$3" "$4" && cmp -s "$3.tmp" "$5" && [ "$(stat -c %a "$3.tmp")" = 666 ] && ! compgen -G "$3.tmp.*" >/dev/null' _ "$rc" "$home/ledger-write-mode" "$ledger" "$root/expected-ledger" "$root/old-temp" "$home/ledger-create-mode"
  printf '%s\n' "$out" >> "$LOG_FILE"
  rm -f "$bin/grep" "$bin/real-grep" "$bin/mktemp" "$bin/real-mktemp" "$ledger.tmp"
  # 作成・置き換え・出力を開く処理の失敗でも元台帳を保持し、残置しない。
  local operation shim_command expected_error
  for operation in mktemp mv open; do
    printf '%s\n' "$proj" "$root/other project" > "$ledger"
    chmod 600 "$ledger"
    cp "$ledger" "$root/expected-ledger"
    shim_command="$operation"
    expected_error='ERROR: 起動台帳'
    if [[ "$operation" == open ]]; then
      expected_error='書き込み用に開けません'
      # chmod の直後に出力先を開けない状態へ変え、root でも open を失敗させる。
      shim_command='chmod'
      cat > "$bin/$shim_command" <<'SHIM'
#!/bin/bash
rm -f -- "${!#}" || exit 1
ln -s "$HOME/missing-dir/ledger" "${!#}"
SHIM
    else
      printf '#!/bin/bash\nexit 1\n' > "$bin/$shim_command"
    fi
    chmod +x "$bin/$shim_command"
    out=$(env -i HOME="$home" PATH="$bin:$PATH" \
      "${SCRIPT_DIR}/c3c" --clean "$proj" 2>&1) && rc=0 || rc=$?
    check "$operation 失敗時は元台帳を保持し一時台帳を除去（rc=$rc）" \
      bash -c '[ "$1" -ne 0 ] && cmp -s "$2" "$3" && [ "$(stat -c %a "$2")" = 600 ] && ! compgen -G "$2.tmp*" >/dev/null && [[ "$4" == *"$5"* ]]' _ "$rc" "$ledger" "$root/expected-ledger" "$out" "$expected_error"
    printf '%s\n' "$out" >> "$LOG_FILE"
    rm -f "$bin/$shim_command"
  done
  launcher_sandbox_cleanup
}

# 存在しない引数で素の cd エラーを出さず、削除済みプロジェクトは台帳の同じ識別で清掃する（#54）。
# shellcheck disable=SC2016
run_missing_directory_launcher_tests() {
  local root bin home proj out rc before_ctx missing input kind launched_name ledger original_proj
  launcher_sandbox_init
  original_proj="$proj"
  ledger="$home/.local/state/claude-container/projects"
  log "## 存在しない作業ディレクトリと削除後の清掃（#54）"
  # 削除コマンドの対象を記録する。既存のダミーは compose 側の配線を引き続き検査する。
  mv "$bin/podman" "$bin/base-podman"
  cat > "$bin/podman" <<'SHIM'
#!/bin/bash
printf '%s\n' "$@" >> "$HOME/podman-args"
exec "$(dirname "$0")/base-podman" "$@"
SHIM
  chmod +x "$bin/podman"
  missing="$root/missing project"
  printf '通常ファイル\n' > "$root/file"
  for input in "$missing" "$root/file" ''; do
    out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" claude "$input" 2>&1) && rc=0 || rc=$?
    check "通常起動は不正なディレクトリを ERROR で案内する: '$input'" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* && "$2" != *": cd:"* ]] && [ ! -e "$3/podman-args" ] && [ ! -e "$4" ]' _ "$rc" "$out" "$home" "$ledger"
    out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" --clean "$input" 2>&1) && rc=0 || rc=$?
    check "台帳にない不正なパスの clean は削除を始めない: '$input'" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* && "$2" != *": cd:"* ]] && [ ! -e "$3/podman-args" ]' _ "$rc" "$out" "$home"
  done
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" --check "$missing" 2>&1) && rc=0 || rc=$?
  check "単一引数の check は既存の FAIL 表示を維持して書き込まない" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"[FAIL]"* && "$2" != *": cd:"* ]] && ! grep -Eq "^(rmi|rm|prune|compose|network)$" "$3/podman-args" && [ ! -e "$4" ]' _ "$rc" "$out" "$home" "$ledger"
  rm -f "$home/podman-args"

  for kind in absolute relative symlink logical_cwd logical_parent; do
    mkdir -p "$root/parent/$kind project"
    proj="$root/parent/$kind project"
    if [[ "$kind" == symlink || "$kind" == logical_cwd ]]; then
      ln -s "$root/parent" "$root/$kind-link"
      proj="$root/$kind-link/$kind project"
    fi
    if [[ "$kind" == logical_parent ]]; then
      # link の実体を別階層に置き、.. の論理解決と物理解決の結果を意図的に分ける。
      mkdir -p "$root/nested/deep"
      ln -s "$root/nested/deep" "$root/parent-link"
      launcher_sandbox_reset_records
      out=$(cd "$root/parent-link" && env -i HOME="$home" PATH="$bin:$PATH" PWD="$PWD" \
        "${SCRIPT_DIR}/c3c" claude "../parent/$kind project" 2>&1) && rc=0 || rc=$?
    else
      run_launcher
    fi
    launched_name=$(sed -n 's/^PROJECT: //p' <<<"$out")
    check "$kind: 起動時の識別と台帳を記録する" \
      bash -c '[ "$1" = 0 ] && [ -n "$2" ] && grep -qxF -- "$3" "$4"' _ "$rc" "$launched_name" "$proj" "$ledger"
    printf '%s\n' "$root/other-project" >> "$ledger"
    mkdir -p "$home/.local/state/claude-container/mcp-approvals"
    printf '承認記録\n' > "$home/.local/state/claude-container/mcp-approvals/$launched_name"
    printf '保護する別プロジェクト\n' > "$home/.local/state/claude-container/mcp-approvals/other"
    printf 'ビルドの残骸\n' > "${SCRIPT_DIR}/.build-context/$launched_name/seed"
    rmdir "$root/parent/$kind project"
    [[ "$kind" != absolute && "$kind" != symlink ]] || rmdir "$root/parent"
    rm -f "$home/podman-args"
    # 別の綴りや改行による複数パターン一致から、記録済みの対象を誤って清掃しない。
    input="$root/unrecorded"$'\n'"$root/other-project"
    [[ "$kind" != symlink ]] || input="$root/parent/$kind project"
    cp "$ledger" "$root/ledger-before-reject"
    out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" --clean "$input" 2>&1) && rc=0 || rc=$?
    check "$kind: 台帳と異なる綴りや改行入り引数は削除前に拒否する" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/podman-args" ] && cmp -s "$4" "$5"' _ "$rc" "$out" "$home" "$ledger" "$root/ledger-before-reject"
    input="$proj"
    [[ "$kind" == relative ]] && input="./parent/../parent/$kind project/"
    if [[ "$kind" == logical_cwd ]]; then
      out=$(cd "$root/logical_cwd-link" && env -i HOME="$home" PATH="$bin:$PATH" PWD="$PWD" \
        "${SCRIPT_DIR}/c3c" --clean "./$kind project/" 2>&1) && rc=0 || rc=$?
    elif [[ "$kind" == logical_parent ]]; then
      out=$(cd "$root/parent-link" && env -i HOME="$home" PATH="$bin:$PATH" PWD="$PWD" \
        "${SCRIPT_DIR}/c3c" --clean "../parent/$kind project" 2>&1) && rc=0 || rc=$?
    else
      out=$(cd "$root" && env -i HOME="$home" PATH="$bin:$PATH" \
        "${SCRIPT_DIR}/c3c" --clean "$input" 2>&1) && rc=0 || rc=$?
    fi
    check "$kind: 削除後も起動時と同じイメージ・ネットワークを清掃する" \
      bash -c '[ "$1" = 0 ] && grep -qxF "localhost/${2}_claude-auth-workspace" "$3/podman-args" && grep -qxF "${2}_default" "$3/podman-args"' _ "$rc" "$launched_name" "$home"
    check "$kind: 対象の台帳・ビルド・承認だけを除去する" \
      bash -c '! grep -qxF -- "$1" "$2" && grep -qxF -- "$3/other-project" "$2" && [ "$(stat -c %a "$2")" = 600 ] && [ ! -e "$4/.build-context/$5" ] && [ ! -e "$6/.local/state/claude-container/mcp-approvals/$5" ] && [ -f "$6/.local/state/claude-container/mcp-approvals/other" ]' _ "$proj" "$ledger" "$root" "$SCRIPT_DIR" "$launched_name" "$home"
    printf '%s\n' "$out" >> "$LOG_FILE"
  done
  # cwd の末尾改行をコマンド置換が落とすと、台帳の改行なしの別エントリに一致して誤対象を清掃する（#108）。
  mkdir -p "$root/nl"$'\n'
  printf '%s\n' "$root/nl/victim" >> "$ledger"
  cp "$ledger" "$root/ledger-before-nl"
  rm -f "$home/podman-args"
  out=$(cd "$root/nl"$'\n' && env -i HOME="$home" PATH="$bin:$PATH" PWD="$PWD" \
    "${SCRIPT_DIR}/c3c" --clean victim 2>&1) && rc=0 || rc=$?
  check "cwd 末尾の改行を落として台帳の別エントリを清掃しない" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/podman-args" ] && cmp -s "$4" "$5"' _ "$rc" "$out" "$home" "$ledger" "$root/ledger-before-nl"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # cwd が削除済みで環境にも PWD が無いと bash は PWD を初期化しない（空なら空のまま。#110）。相対引数を
  # "/<引数>" に組み立てて台帳の別エントリ（/victim）へ一致させず、素の unbound variable でもなく ERROR で止める。
  mkdir -p "$root/gone"
  printf '%s\n' "/victim" >> "$ledger"
  cp "$ledger" "$root/ledger-before-nopwd"
  rm -f "$home/podman-args"
  out=$(cd "$root/gone" && rmdir "$root/gone" && env -i HOME="$home" PATH="$bin:$PATH" \
    "${SCRIPT_DIR}/c3c" --clean victim 2>&1) && rc=0 || rc=$?
  check "cwd 削除済みで PWD が無い相対引数は台帳照合せず ERROR で止める" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* && "$2" != *"unbound variable"* ]] && [ ! -e "$3/podman-args" ] && cmp -s "$4" "$5"' _ "$rc" "$out" "$home" "$ledger" "$root/ledger-before-nopwd"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # cwd が削除済みだと bash は cd . / .. を成功させ、pwd -L が引数「.」「..」をそのまま返す（#122）。
  # 幽霊名（「.」の sha256 由来 project-cdb4ee2a 等）で清掃・台帳記録・診断を始めず、PWD の有無に
  # 関わらず絶対パスの指定を求めて止める。
  printf '%s\n' "/victim" > "$ledger"
  cp "$ledger" "$root/ledger-before-dot"
  for input in "--clean ." "--clean .." "claude ." "--check ."; do
    for pwd_env in none stale; do
      read -ra args <<<"$input"
      mkdir -p "$root/gone"
      rm -f "$home/podman-args"
      if [[ "$pwd_env" == stale ]]; then
        out=$(cd "$root/gone" && rmdir "$root/gone" && env -i HOME="$home" PATH="$bin:$PATH" PWD="$root/gone" \
          "${SCRIPT_DIR}/c3c" "${args[@]}" 2>&1) && rc=0 || rc=$?
      else
        out=$(cd "$root/gone" && rmdir "$root/gone" && env -i HOME="$home" PATH="$bin:$PATH" \
          "${SCRIPT_DIR}/c3c" "${args[@]}" 2>&1) && rc=0 || rc=$?
      fi
      check "cwd 削除済み（PWD $pwd_env）の '$input' は幽霊名で進めず止める" \
        bash -c '[ "$1" != 0 ] && [[ "$2" == *"現在のディレクトリを特定できない"* && "$2" != *"project-cdb4ee2a"* && "$2" != *"project-5ec1f7e7"* ]] && ! grep -Eq "^(rmi|rm|prune|compose|network)$" "$3/podman-args" 2>/dev/null && cmp -s "$4" "$5"' _ "$rc" "$out" "$home" "$ledger" "$root/ledger-before-dot"
      printf '%s\n' "$out" >> "$LOG_FILE"
    done
  done
  proj="$original_proj"
  launcher_sandbox_cleanup
}

# init-firewall.sh の resolve_allowed_ports() の検証（claude-container#31、#49）。
# 関数を sed で抜き出し、本番と同じ `bash -euo pipefail` の独立プロセスで
# ALLOWED_PORTS_FILE をフィクスチャに向けて素呼びし、rc・ALLOWED_PORTS（stdout）・
# ERROR 文（stderr）を親で捕捉する。iptables には触れない。
#
# ベクタ表フォーマット: class|input|expected
#   accept: rc0、ALLOWED_PORTS が expected と完全一致
#   reject: rc1、stderr が expected（部分文字列）を含む
#   input は printf '%b' で展開するエスケープ表記（末尾 \n の有無が意味を持つ）。
ALLOWED_PORTS_VECTORS=(
  # 末尾改行なしでも最終行を読む（#49-1）
  'accept|443\n8080|443,8080'
  'accept|443|443'
  # 443 必須・80 禁止（#49-2）。範囲は端点を含めて判定する
  'reject|8080\n|443 を含める必要があります'
  'reject|443\n80\n|80 番を許可できません'
  'reject|443\n79:81\n|80 番を許可できません'
  'reject|443\n79:80\n|80 番を許可できません'
  'reject|443\n80:81\n|80 番を許可できません'
  'accept|442:444\n|442:444'
  'reject|443:443\n|同じ場合は単一ポート'
  # #56: 数値境界・逆順・同値。443も含め、無関係な必須ポート検査による失敗を避ける。
  'reject|443\n0\n|1〜65535'
  'reject|443\n00000\n|1〜65535'
  'reject|443\n65536\n|1〜65535'
  'reject|443\n70000\n|1〜65535'
  'reject|443\n0:2\n|1〜65535'
  'reject|443\n2:0\n|1〜65535'
  'reject|443\n65536:65537\n|1〜65535'
  'reject|443\n65534:65536\n|1〜65535'
  'reject|443\n8010:8000\n|開始ポートは終了ポートより小さく'
  'reject|00443:443\n|同じ場合は単一ポート'
  'accept|443\n1\n65535\n|443,1,65535'
  'accept|443\n1:2\n65534:65535\n|443,1:2,65534:65535'
  'accept|00442:00444\n|442:444'
  # 先頭ゼロは十進として扱う（bash 算術の八進解釈を避ける）
  'accept|00443\n|443'
  'accept|443\n0120\n|443,120'
  'accept|443\n00008\n|443,8'
  'reject|443\n100000\n|ポート番号か port:port'
  'reject|000443\n|ポート番号か port:port'
  'reject|443\n080\n|80 番を許可できません'
  # 既存挙動の固定
  'accept|443\n22\n8000:8010\n|443,22,8000:8010'
  'accept||443,22'
  'accept|# comment only\n\n|443,22'
  'reject|abc\n|不正なエントリ'
  # #88: 単一1枠・範囲2枠。境界15枠と16枠を別々に確認する。
  'accept|443\n1000:65535\n|443,1000:65535'
  'accept|443\n1000:1001\n1002:1003\n1004:1005\n1006:1007\n1008:1009\n1010:1011\n1012:1013\n|443,1000:1001,1002:1003,1004:1005,1006:1007,1008:1009,1010:1011,1012:1013'
  'reject|443\n22\n1000:1001\n1002:1003\n1004:1005\n1006:1007\n1008:1009\n1010:1011\n1012:1013\n|16 枠あります'
  'reject|442:443\n1000:1001\n1002:1003\n1004:1005\n1006:1007\n1008:1009\n1010:1011\n1012:1013\n|16 枠あります'
  'accept|443\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12\n13\n14\n|443,1,2,3,4,5,6,7,8,9,10,11,12,13,14'
  'reject|443\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12\n13\n14\n15\n|16 枠あります'
)

run_allowed_ports_tests() {
  local t harness fixture entry class input expected actual_rc actual_out actual_err
  t=$(mktemp -d) || { log "  [FAIL] allowed-ports: mktemp -d failed"; FAIL=$((FAIL + 1)); return; }
  harness="$t/harness.sh"; fixture="$t/allowed-ports.txt"
  {
    cat <<'HARNESS_HEAD'
#!/bin/bash
set -euo pipefail
ALLOWED_PORTS_FILE="$1"
HARNESS_HEAD
    sed -n '/^resolve_allowed_ports()/,/^}/p' "${SCRIPT_DIR}/init-firewall.sh"
    cat <<'HARNESS_TAIL'
resolve_allowed_ports
printf '%s\n' "$ALLOWED_PORTS"
HARNESS_TAIL
  } > "$harness"
  if ! grep -q '^resolve_allowed_ports()' "$harness"; then
    log "  [FAIL] allowed-ports: init-firewall.sh から resolve_allowed_ports() を抜き出せません"
    FAIL=$((FAIL + 1)); rm -rf "$t"; return
  fi

  for entry in "${ALLOWED_PORTS_VECTORS[@]}"; do
    IFS='|' read -r class input expected <<< "$entry"
    printf '%b' "$input" > "$fixture"
    actual_rc=0
    actual_out=$(bash "$harness" "$fixture" 2>"$t/err") || actual_rc=$?
    actual_err=$(cat "$t/err")
    case "$class" in
      accept)
        if [ "$actual_rc" -eq 0 ] && [ "$actual_out" = "$expected" ]; then
          PASS=$((PASS + 1))
        else
          FAIL=$((FAIL + 1))
          log "  [FAIL] allowed-ports accept input=[$input] rc=$actual_rc out=[$actual_out] err=[$actual_err]"
        fi
        ;;
      reject)
        if [ "$actual_rc" -eq 1 ] && [[ "$actual_err" == *"$expected"* ]]; then
          PASS=$((PASS + 1))
        else
          FAIL=$((FAIL + 1))
          log "  [FAIL] allowed-ports reject input=[$input] rc=$actual_rc out=[$actual_out] err=[$actual_err]"
        fi
        ;;
    esac
  done
  log "  allowed-ports.txt ベクタ表 ${#ALLOWED_PORTS_VECTORS[@]} 件を実行"
  rm -rf "$t"
}

# guard_codex_dir() の検証（claude-container#36、#48）。実ホストの ~/.codex を指す
# CODEX_DIR を、文字列の表記ゆれ・シンボリックリンクによらず実体で検出して fail-closed
# にすること。各ケースを通常起動と --check の対で見る。
run_codex_dir_launcher_tests() {
  local root bin home proj out rc before_ctx
  launcher_sandbox_init
  local label value expected
  mkdir -p "$home/.codex" "$home/.codex-container" "$proj/.codex-container"
  ln -s "$home/.codex" "$home/codex-link"
  ln -s "$home/.codex-container" "$home/link-container"

  # 拒否側: 通常起動は ERROR で compose に進まず、--check は FAIL
  reject_case() {
    local label="$1" value="$2"
    run_launcher CODEX_DIR="$value"
    check "$label は ERROR で起動中止（rc=$rc）" \
      bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q 'CODEX_DIR' && [ ! -e '$root/compose-env' ]" "$out"
    printf '%s\n' "$out" >> "$LOG_FILE"
    run_launcher_check CODEX_DIR="$value"
    check "$label を --check は FAIL で報告する（rc=$rc）" \
      bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q '結果: FAIL'" "$out"
    printf '%s\n' "$out" >> "$LOG_FILE"
  }
  reject_case "H1: 末尾 // の実 ~/.codex"        "$home/.codex//"
  reject_case "H2: ~/./.codex 表記の実 ~/.codex" "$home/./.codex"
  reject_case "H3: ~/.codex/. 表記の実 ~/.codex" "$home/.codex/."
  reject_case "H4: 実 ~/.codex への symlink"      "$home/codex-link"
  reject_case "H4b: 先頭 // 表記の実 ~/.codex"   "/$home/.codex"
  reject_case "H5: 相対パスの CODEX_DIR"          ".codex-container"
  # H6: ~/.codex 自体が symlink で、そのリンク先を直接指す
  rm -rf "$home/.codex"; mkdir -p "$home/real-codex"; ln -s "$home/real-codex" "$home/.codex"
  reject_case "H6: symlink の ~/.codex のリンク先"  "$home/real-codex"
  rm -f "$home/.codex"; mkdir -p "$home/.codex"
  # H7: ~/.codex が存在しない状態で文字列として指す（文字列比較で拒否）
  rm -rf "$home/.codex"
  reject_case "H7: 存在しない ~/.codex を文字列で指定" "$home/.codex"
  mkdir -p "$home/.codex"
  # H8: 存在しないパス → 既存の ERROR
  reject_case "H8: 存在しない CODEX_DIR"            "$home/no-such-dir"

  # 通過側: 正規化済み絶対パスが compose へ渡る（正規化を実装しないと落ちる対照）
  expected="$(cd "$home/.codex-container" && pwd -P)"
  for label in "H9: ~/./.codex-container 表記|$home/./.codex-container" "H10: 専用ディレクトリへの symlink|$home/link-container" "H11: 先頭 // 表記の専用ディレクトリ|/$home/.codex-container"; do
    value="${label#*|}"; label="${label%%|*}"
    run_launcher CODEX_DIR="$value"
    check "$label は起動が進む（rc=$rc）" [ "$rc" -eq 0 ]
    check "$label は compose へ正規化済み絶対パスが渡る" \
      grep -qxF "CODEX_DIR=$expected" "$root/compose-env"
    printf '%s\n' "$out" >> "$LOG_FILE"
    run_launcher_check CODEX_DIR="$value"
    check "$label を --check は最後まで診断して PASS/WARN で終える（rc=$rc）" \
      bash -c "[ $rc -eq 0 ] && printf '%s' \"\$0\" | grep -qE '結果: (PASS|WARN)'" "$out"
    printf '%s\n' "$out" >> "$LOG_FILE"
  done

  launcher_sandbox_cleanup
}

# CODEX_HOST_PLUGINS（ホストの Codex plugin キャッシュを CODEX_DIR の内側へ :ro で重ねる opt-in）の検証。
# opt-in の配線（build と run の両方）、不正値・前提欠落・symlink のマウント先を compose 前に拒否すること、
# --check が何も作らないこと、既存内容が隠れる WARNING を見る。
# shellcheck disable=SC2016  # bash -c の検証式は親で展開せず、位置引数を子シェル内で評価する
run_codex_host_plugins_launcher_tests() {
  local root bin home proj out rc before_ctx value src_real
  launcher_sandbox_init
  log "## ホストの Codex plugin キャッシュ共有（CODEX_HOST_PLUGINS）"
  mkdir -p "$home/.codex/plugins/cache/mk/p/1.0" "$home/.codex-container" "$proj/.claude-container.d" "$root/outside"
  chmod 700 "$home/.codex-container"
  src_real=$(cd "$home/.codex/plugins/cache" && pwd -P)

  run_launcher CODEX_DIR="$home/.codex-container" C3C_CODEX_PLUGINS_SOURCE=/tmp/injected
  check "未設定なら override を選ばず、注入された内部変数も破棄する" \
    bash -c '[ "$1" = 0 ] && ! grep -q "compose\.codex-plugins" "$2/compose-args" && ! grep -q "^C3C_CODEX_PLUGINS_SOURCE=" "$2/compose-env" && [ ! -e "$3/.codex-container/plugins" ]' _ "$rc" "$root" "$home"

  printf 'CODEX_DIR=~/.codex-container\nCODEX_HOST_PLUGINS=1\n' > "$proj/.claude-container.d/env"
  local snapshot_ok=1
  snapshot_check_targets > "$root/before" 2>> "$LOG_FILE" || snapshot_ok=0
  run_launcher_check
  snapshot_check_targets > "$root/after" 2>> "$LOG_FILE" || snapshot_ok=0
  check "--check は共有を診断し、マウント先を作らない" \
    bash -c '[ "$1" -eq 1 ] && [ "$2" = 0 ] && [[ "$3" == *"[OK]   Codex plugin 共有 (ro): $5 -> /home/node/.codex/plugins/cache"* ]] && cmp -s "$4/before" "$4/after"' _ "$snapshot_ok" "$rc" "$out" "$root" "$src_real"

  run_launcher
  check "env の opt-in で実体解決した source と override を渡し、マウント先を作る" \
    bash -c '[ "$1" = 0 ] && grep -qxF "C3C_CODEX_PLUGINS_SOURCE=$3" "$2/compose-env" && grep -qxF "$4/compose.codex-plugins.yml" "$2/compose-args" && [ -d "$5/.codex-container/plugins/cache" ] && [ ! -L "$5/.codex-container/plugins/cache" ]' _ "$rc" "$root" "$src_real" "$SCRIPT_DIR" "$home"
  printf '%s\n' "$out" >> "$LOG_FILE"

  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" claude -b "$proj" 2>&1) && rc=0 || rc=$?
  check "build と run の両方に override が渡る" \
    bash -c '[ "$1" = 0 ] && [ "$(cat "$2/compose-calls")" = 2 ] && grep -qxF "$3/compose.codex-plugins.yml" "$2/compose-args.1" && grep -qxF "$3/compose.codex-plugins.yml" "$2/compose-args.2"' _ "$rc" "$root" "$SCRIPT_DIR"
  : > "$proj/.claude-container.d/env"

  touch "$home/.codex-container/plugins/cache/container-installed"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "マウント先に既存内容があれば隠れることを WARNING で示し、起動は続ける" \
    bash -c '[ "$1" = 0 ] && [[ "$2" == *"WARNING:"*"plugins/cache"* ]]' _ "$rc" "$out"
  rm -f "$home/.codex-container/plugins/cache/container-installed"

  for value in 2 true '1 ' yes; do
    run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS="$value"
    check "不正値 '$value' を起動時に拒否する" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"CODEX_HOST_PLUGINS"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS="$value"
    check "不正値 '$value' を --check も拒否する" [ "$rc" -ne 0 ]
  done

  run_launcher CODEX_HOST_PLUGINS=1
  check "CODEX_DIR 未設定の opt-in を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"CODEX_DIR"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"

  rm -rf "$home/.codex-container/plugins"
  mv "$home/.codex/plugins/cache" "$home/.codex/plugins/cache.off"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "ホストに plugin キャッシュが無ければ拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*".codex/plugins/cache"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "--check もキャッシュ欠落を拒否する" [ "$rc" -ne 0 ]
  check "キャッシュ欠落を拒否した起動/check は source とマウント先を作らない" \
    bash -c '[ ! -e "$1/.codex/plugins/cache" ] && [ ! -e "$1/.codex-container/plugins" ]' _ "$home"
  mv "$home/.codex/plugins/cache.off" "$home/.codex/plugins/cache"

  rm -rf "$home/.codex-container/plugins"
  ln -s "$root/outside" "$home/.codex-container/plugins"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "symlink のマウント先（plugins）を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"symlink"* ]] && [ ! -e "$3/compose-env" ] && [ -z "$(ls -A "$3/outside")" ]' _ "$rc" "$out" "$root"
  run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "--check も symlink の親マウント先（plugins）を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"symlink"* ]] && [ -z "$(ls -A "$3/outside")" ]' _ "$rc" "$out" "$root"
  rm -f "$home/.codex-container/plugins"
  : > "$home/.codex-container/plugins"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "ファイルの親マウント先（plugins）を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "--check もファイルの親マウント先（plugins）を拒否する" [ "$rc" -ne 0 ]
  rm -f "$home/.codex-container/plugins"
  mkdir -p "$home/.codex-container/plugins"
  ln -s "$root/outside" "$home/.codex-container/plugins/cache"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "symlink のマウント先（plugins/cache）を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"symlink"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  run_launcher_check CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "--check も symlink のマウント先を拒否する" [ "$rc" -ne 0 ]
  rm -f "$home/.codex-container/plugins/cache"
  : > "$home/.codex-container/plugins/cache"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "ファイルのマウント先を拒否する" \
    bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  rm -f "$home/.codex-container/plugins/cache"

  # /tmp/.. は guard_codex_dir() が / に正規化する（末尾 / の除去を落とすと見落とす）。
  for value in "$home/.codex/plugins/cache" "$home/.codex/plugins" /tmp/..; do
    run_launcher CODEX_DIR="$value" CODEX_HOST_PLUGINS=1
    check "source と重なる CODEX_DIR を拒否する: $value" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"*"重なり"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
  done

  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1 EXTRA_MOUNT="$home"
  check "別の rw マウントと source の重なりを WARNING で示し、起動は続ける" \
    bash -c '[ "$1" = 0 ] && [[ "$2" == *"WARNING:"*"CODEX_HOST_PLUGINS"*"rw"* ]]' _ "$rc" "$out"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "重ならなければ重なりの WARNING を出さない" \
    bash -c '[ "$1" = 0 ] && [[ "$2" != *"CODEX_HOST_PLUGINS の source"*"rw"* ]]' _ "$rc" "$out"

  # source が symlink なら、compose へは実体を渡す（未解決の綴りを渡す実装を赤にする）。
  mkdir -p "$root/real-cache/mk"
  mv "$home/.codex/plugins/cache" "$home/.codex/plugins/cache.orig"
  ln -s "$root/real-cache" "$home/.codex/plugins/cache"
  run_launcher CODEX_DIR="$home/.codex-container" CODEX_HOST_PLUGINS=1
  check "symlink の source は実体へ解決して渡す" \
    bash -c '[ "$1" = 0 ] && grep -qxF "C3C_CODEX_PLUGINS_SOURCE=$(cd "$2/real-cache" && pwd -P)" "$2/compose-env"' _ "$rc" "$root"
  rm -f "$home/.codex/plugins/cache"
  mv "$home/.codex/plugins/cache.orig" "$home/.codex/plugins/cache"

  launcher_sandbox_cleanup
}

# .claude-container.d/env の許可リスト（claude-container#44）と、対象プロジェクト直下の
# .env を compose の補間に使わせない遮断（claude-container#60）の検証。env ファイルは
# 実際に $proj/.claude-container.d/env へ書く（既存テストのようにシェル環境で渡すと、
# 「ファイルのキーを export するか」という本題を検証できない）。
run_env_file_launcher_tests() {
  local root bin home proj out rc before_ctx
  launcher_sandbox_init
  local envf="$proj/.claude-container.d/env"
  mkdir -p "$proj/.claude-container.d"

  # D1: 対象プロジェクト直下の .env は compose へ --env-file /dev/null で遮断される
  printf 'CLAUDE_CONTAINER_NO_FIREWALL=1\n' > "$proj/.env"
  rm -f "$envf"
  run_launcher
  check "D1: compose に --env-file /dev/null が渡る（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && tr '\n' ' ' < '$root/compose-args' | grep -q -- '--env-file /dev/null '"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # D2: build 側・run 側・Codex preflight 側の全呼び出しに付いている（静的確認。run_launcher は -b を
  # 渡せないため本体を数える。compose 呼び出しの行数と --env-file /dev/null 付きの行数が一致すること）
  check "D2: podman compose の全呼び出しに --env-file /dev/null がある" \
    bash -c "total=\$(grep -c '^ *podman compose ' '${SCRIPT_DIR}/c3c'); with=\$(grep -c '^ *podman compose .*--env-file /dev/null' '${SCRIPT_DIR}/c3c'); [ \"\$total\" -ge 2 ] && [ \"\$total\" -eq \"\$with\" ]"
  rm -f "$proj/.env"

  # 許可リスト（claude-container#44）。偽 grep は実行痕跡を残してから本物へ委譲する
  # （偽物が動いてもランチャーの流れは壊さず、痕跡の有無だけで判定する）。
  local evil="$root/evil" marker="$root/evil-ran" real_grep
  real_grep="$(command -v grep)"
  mkdir -p "$evil" "$home/.codex" "$home/.codex-container"
  cat > "$evil/grep" <<DUMMY
#!/bin/bash
touch "$marker"
exec "$real_grep" "\$@"
DUMMY
  chmod +x "$evil/grep"

  # E1: env の PATH は export されず、以降の grep はホストの本物が動く。
  # $bin を含めるのは、修正前（PATH が export される状態）でもダミー podman が解決され続ける
  # ようにするため（含めないと赤の確認で実 podman の image exists → 実ビルドへ進んでしまう）。
  # 判定は marker の有無なので赤は成立する。
  printf 'PATH=%s:%s:/usr/bin:/bin\n' "$evil" "$bin" > "$envf"
  run_launcher
  check "E1: env の PATH で偽 grep が実行されない（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && [ ! -e '$marker' ] && ! grep -q '^PATH=$evil' '$root/compose-env'"
  check "E1: PATH は未対応キーとして WARNING で報告される" \
    bash -c "printf '%s' \"\$0\" | grep -q 'WARNING:.*PATH.*解釈しないため無視'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # E2: env の HOME で guard_codex_dir の fail-closed が沈黙しない（2026-09-12 の実測の回帰）
  printf 'HOME=%s\nCODEX_DIR=%s/.codex\n' "$root/fake-home" "$home" > "$envf"
  run_launcher
  check "E2: env の HOME では CODEX_DIR ガードを迂回できない（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q 'CODEX_DIR' && [ ! -e '$root/compose-env' ]" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # E3: 許可キー 9 件が全て compose へ届く（許可リストからどれか 1 つ落ちたら赤になる対照）。
  # 3 件だけを見ていると、マウント境界を決める CLAUDE_CONFIG_DIR・EXTRA_MOUNT・SHARED_MOUNT・
  # SECRETS_DIR が配列から消えても緑のままになる（レビュー指摘に基づく拡張）。
  : > "$root/gitconfig"
  mkdir -p "$root/extra" "$root/shared" "$root/secrets" "$home/cfgx/.claude"
  local e_cfg e_extra e_shared e_secrets e_gitcfg e_codex
  e_cfg="$(cd "$home/cfgx" && pwd -P)"
  e_extra="$(cd "$root/extra" && pwd -P)"
  e_shared="$(cd "$root/shared" && pwd -P)"
  e_secrets="$(cd "$root/secrets" && pwd -P)"
  e_gitcfg="$root/gitconfig"
  e_codex="$(cd "$home/.codex-container" && pwd -P)"
  {
    printf 'TZ=Asia/Tokyo\n'
    printf 'CLAUDE_CONTAINER_NO_FIREWALL=1\n'
    printf 'CLAUDE_CONTAINER_IPV6=1\n'
    printf 'CLAUDE_CONFIG_DIR=%s\n' "$e_cfg"
    printf 'EXTRA_MOUNT=%s\n' "$e_extra"
    printf 'SHARED_MOUNT=%s\n' "$e_shared"
    printf 'SECRETS_DIR=%s\n' "$e_secrets"
    printf 'GITCONFIG_FILE=%s\n' "$e_gitcfg"
    printf 'CODEX_DIR=%s\n' "$e_codex"
  } > "$envf"
  run_launcher
  check "E3: 許可キー 9 件が全て compose へ届く（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] \
      && grep -qxF 'TZ=Asia/Tokyo' '$root/compose-env' \
      && grep -qxF 'CLAUDE_CONTAINER_NO_FIREWALL=1' '$root/compose-env' \
      && grep -qxF 'CLAUDE_CONTAINER_IPV6=1' '$root/compose-env' \
      && grep -qxF 'CLAUDE_CONFIG_DIR=$e_cfg' '$root/compose-env' \
      && grep -qxF 'EXTRA_MOUNT=$e_extra' '$root/compose-env' \
      && grep -qxF 'SHARED_MOUNT=$e_shared' '$root/compose-env' \
      && grep -qxF 'SECRETS_DIR=$e_secrets' '$root/compose-env' \
      && grep -qxF 'GITCONFIG_FILE=$e_gitcfg' '$root/compose-env' \
      && grep -qxF 'CODEX_DIR=$e_codex' '$root/compose-env'"
  check "E3: 許可キーには WARNING が出ない" \
    bash -c "! printf '%s' \"\$0\" | grep -q '解釈しないため無視'" "$out"
  check "E3b: GITCONFIG_FILE 設定時は ~/.gitconfig の bind 元がそのファイルになる" \
    grep -qxF "C3C_GITCONFIG_SOURCE=$e_gitcfg" "$root/compose-env"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # E4: 廃止変数を env ファイルに書いた場合の移行案内（ERROR）は許可リスト化後も維持される
  printf 'GH_TOKEN_FILE=/nonexistent\n' > "$envf"
  run_launcher
  check "E4: env の GH_TOKEN_FILE は廃止 ERROR で起動中止（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q '廃止されました' && [ ! -e '$root/compose-env' ]" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # E5: --check は未対応キーを [WARN] として報告し、FAIL にはしない。
  # 修正前は LD_PRELOAD が export され、外部コマンドの exec ごとに ld.so が stderr へ
  # 「ERROR: ld.so: object '/nonexistent/evil.so' from LD_PRELOAD cannot be preloaded」を出す。
  # 単に LD_PRELOAD を grep すると修正前から緑になるので、汎用 WARNING の文言と同一行で結ぶ。
  printf 'LD_PRELOAD=/nonexistent/evil.so\n' > "$envf"
  run_launcher_check
  check "E5: --check は LD_PRELOAD を WARNING で報告し結果は WARN（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && printf '%s' \"\$0\" | grep -q 'WARNING:.*LD_PRELOAD.*解釈しないため無視' && printf '%s' \"\$0\" | grep -q '結果: WARN'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # E6: 未対応キーは compose の環境にも現れない
  run_launcher
  check "E6: LD_PRELOAD は compose の環境に渡らない（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && ! grep -q '^LD_PRELOAD=' '$root/compose-env'"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # E7: 許可リストと README「環境変数」節の表が一致する（静的確認）。両者がずれると、
  # 表に載っているのに無視されるキー（利用者の設定が黙って消える）か、無検証で通るキーが出る。
  check "E7: ENV_FILE_ALLOWED_KEYS と README「環境変数」節の表が一致する" \
    bash -c "diff <(awk '/^ENV_FILE_ALLOWED_KEYS=\(/{f=1;next} f&&/^\)/{exit} f{gsub(/[ \t]/,\"\");print}' '${SCRIPT_DIR}/c3c' | sort) \
                  <(awk '/^## 環境変数/{f=1;next} f&&/^## /{exit} f' '${SCRIPT_DIR}/README.md' | grep -oE '^\| \`[A-Z0-9_]+\`' | tr -d '| \`' | sort)"

  launcher_sandbox_cleanup
}

# guard_base_image() の検証（claude-container#50）。base-image.txt に有効行が無い
# （空・コメントのみ）ときに通常起動が無言で止まらず既定値で進み、--check と結果が
# 一致すること。通常起動と --check は同じ関数を別の呼び出し文脈（素呼び／|| true）で
# 呼ぶため、両者を必ず対で見る。
run_base_image_launcher_tests() {
  local root bin home proj out rc before_ctx
  launcher_sandbox_init
  local conf="$proj/.claude-container.d"
  mkdir -p "$conf"
  local label

  # G1: 空ファイル / G2: コメントのみ → 既定値 debian:stable で起動が進む
  for label in "G1: 空の base-image.txt" "G2: コメントのみの base-image.txt"; do
    if [[ "$label" == G1* ]]; then : > "$conf/base-image.txt"; else printf '# only a comment\n\n' > "$conf/base-image.txt"; fi
    run_launcher
    check "$label は既定値で通常起動が進む（rc=$rc）" \
      bash -c "[ $rc -eq 0 ] && grep -qxF 'BASE_IMAGE=debian:stable' '$root/compose-env'"
    printf '%s\n' "$out" >> "$LOG_FILE"
    run_launcher_check
    check "$label を --check は既定値として報告する（rc=$rc）" \
      bash -c "[ $rc -eq 0 ] && printf '%s' \"\$0\" | grep -q 'base-image.txt は空、既定値'" "$out"
    printf '%s\n' "$out" >> "$LOG_FILE"
  done

  # G3: 有効行が多いファイル（先頭が採用される）。grep | head -1 のパイプでは head の
  # 早期終了で grep が SIGPIPE を受け、pipefail 下で無言停止していた経路。
  { echo debian:stable; yes debian:testing | head -200000; } > "$conf/base-image.txt"
  run_launcher
  check "G3: 有効行 20 万行でも先頭行で通常起動が進む（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && grep -qxF 'BASE_IMAGE=debian:stable' '$root/compose-env'"
  printf '%s\n' "$out" >> "$LOG_FILE"
  run_launcher_check
  check "G3: 有効行 20 万行を --check は先頭行で報告する（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && printf '%s' \"\$0\" | grep -qF '[INFO] ベースイメージ: debian:stable' && ! printf '%s' \"\$0\" | grep -q '既定値'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # G4: 読めないファイル → 通常起動は ERROR で compose に進まず、--check は FAIL
  # （root は chmod 000 でも読めるため、その場合は判定せず SKIP を記録する）
  printf 'debian:testing\n' > "$conf/base-image.txt"
  chmod 000 "$conf/base-image.txt"
  if [[ "$(id -u)" -eq 0 ]]; then
    log "  G4: 読めない base-image.txt（root 実行のため SKIP）"
  else
    run_launcher
    check "G4: 読めない base-image.txt は ERROR で起動中止（rc=$rc）" \
      bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q 'base-image.txt' && [ ! -e '$root/compose-env' ]" "$out"
    printf '%s\n' "$out" >> "$LOG_FILE"
    run_launcher_check
    check "G4: 読めない base-image.txt を --check は FAIL で報告する（rc=$rc）" \
      bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q '結果: FAIL'" "$out"
    printf '%s\n' "$out" >> "$LOG_FILE"
  fi
  chmod 644 "$conf/base-image.txt"

  # G5: 有効値は compose へそのまま渡る（対照）
  run_launcher
  check "G5: debian:testing が compose へ渡る（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && grep -qxF 'BASE_IMAGE=debian:testing' '$root/compose-env'"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # G6: 許容範囲外の値は ERROR（既存挙動の固定）
  printf 'ubuntu:24.04\n' > "$conf/base-image.txt"
  run_launcher
  check "G6: 許容範囲外の値は ERROR で起動中止（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q '許容範囲外' && [ ! -e '$root/compose-env' ]" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  launcher_sandbox_cleanup
}


# IPv6 設定の誤受理と、build/run の片方だけ mode が変わる回帰を検出する。
# shellcheck disable=SC2016 # bash -c の位置引数を子シェル側で展開する。
run_ipv6_launcher_tests() {
  local root bin home proj out rc before_ctx value
  launcher_sandbox_init
  mkdir -p "$proj/.claude-container.d"
  for value in '' 0 1; do
    printf 'CLAUDE_CONTAINER_IPV6=%s\n' "$value" > "$proj/.claude-container.d/env"
    run_launcher
    if [[ "$value" == 1 ]]; then
      check "IPv6=1 は固定 override を run に渡す" \
        bash -c '[ "$1" -eq 0 ] && grep -qxF "$2/compose.ipv6.yml" "$3/compose-args"' _ "$rc" "$SCRIPT_DIR" "$root"
    else
      check "IPv6=$value は既定の Compose を維持" \
        bash -c '[ "$1" -eq 0 ] && ! grep -qF compose.ipv6.yml "$2/compose-args"' _ "$rc" "$root"
    fi
    printf '%s\n' "$out" >> "$LOG_FILE"
  done
  for value in 2 true '1 ' '1;echo unsafe'; do
    printf 'CLAUDE_CONTAINER_IPV6=%s\n' "$value" > "$proj/.claude-container.d/env"
    run_launcher
    check "不正な IPv6=$value で起動を止める" \
      bash -c '[ "$1" -ne 0 ] && [ ! -f "$2/compose-args" ] && [[ "$3" == *ERROR:* ]]' _ "$rc" "$root" "$out"
    run_launcher_check
    check "不正な IPv6=$value を --check も拒否する" [ "$rc" -ne 0 ]
    printf '%s\n' "$out" >> "$LOG_FILE"
  done
  printf 'CLAUDE_CONTAINER_IPV6=1\n' > "$proj/.claude-container.d/env"
  run_launcher TEST_IPV6_SUPPORT=
  check "IPv6 未対応の旧イメージでは起動前に -b を案内して拒否" \
    bash -c '[ "$1" -ne 0 ] && [ ! -e "$2/compose-args" ] && [[ "$3" == *"-b"* ]]' _ "$rc" "$root" "$out"
  run_launcher_check TEST_IPV6_SUPPORT=
  check "IPv6 未対応の旧イメージを --check も拒否" [ "$rc" -ne 0 ]
  cat > "$bin/curl" <<'CURL'
#!/bin/sh
# 実 curl と同じく --output 先へ書く（stdout へ出すと再試行時に巻き戻せない）。
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then
    printf '%s\n' '{"web":[],"api":[],"git":[]}' > "$2"
    exit 0
  fi
  shift
done
exit 2
CURL
  chmod +x "$bin/curl"
  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" TEST_IPV6_SUPPORT= "${SCRIPT_DIR}/c3c" claude -b "$proj" 2>&1) && rc=0 || rc=$?
  check "IPv6=1 の build と run は同じ override を使う" \
    bash -c '[ "$1" -eq 0 ] && [ "$(grep -cxF "$2/compose.ipv6.yml" "$3/compose-args")" -eq 2 ]' _ "$rc" "$SCRIPT_DIR" "$root"
  printf '%s\n' "$out" >> "$LOG_FILE"
  launcher_sandbox_cleanup
}

# prepare_claude_config_ro() の検証（PR #47）。
# shellcheck disable=SC2016  # bash -c の検証式は親で展開せず、位置引数を子シェル内で評価する
run_config_ro_launcher_tests() {
  local root bin home proj out rc d f before_ctx
  launcher_sandbox_init
  # ホストの別プロジェクトの起動と競合せず、.build-context 全体を比較する。
  mkdir -p "$root/runner"
  cp -- "${SCRIPT_DIR}/"{c3c,agent-preference.py,project-images.py,compose.yml,compose.ipv6.yml,compose.plugins-alias.yml,compose.shared-home.yml,compose.shared-host.yml,compose.agents.yml,compose.codex-plugins.yml,compose.codex-preflight.yml,Dockerfile.claude,entrypoint.sh,init-firewall.sh,ipv6-firewall.py,firewall-refresh.py,codex-mcp-audit.py,git-askpass.sh,validate-build-input.sh,packages.txt,requirements.txt,allowed-domains.txt,node-version.txt,codex-version.txt,empty.gitconfig} "$root/runner/" || {
    check "ランチャーの隔離用コピーを作成する" false
    launcher_sandbox_cleanup
    return
  }
  local SCRIPT_DIR="$root/runner"
  before_ctx=""

  # C0: 通常起動前にも台帳・承認記録などを新規作成しない。
  local snapshot_ok=1
  snapshot_check_targets > "$root/check-before" 2>> "$LOG_FILE" || snapshot_ok=0
  run_launcher_check
  snapshot_check_targets > "$root/check-after" 2>> "$LOG_FILE" || snapshot_ok=0
  check "C0: 未起動プロジェクトの --check と保護対象の収集が成功する" [ "$snapshot_ok" -eq 1 -a "$rc" -eq 0 ]
  check "C0: --check は未作成の台帳・承認記録などを作らない" cmp "$root/check-before" "$root/check-after"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # A: 空の ~/.claude → 12 項目が空で作られ、作成が 12 行ログされ、すべてユーザー所有
  run_launcher
  local ok=1
  for d in "${CONFIG_RO_DIRS[@]}"; do [[ -d "$home/.claude/$d" ]] || ok=0; done
  for f in "${CONFIG_RO_FILES[@]}"; do [[ -f "$home/.claude/$f" ]] || ok=0; done
  [[ "$(cat "$home/.claude/settings.json")" == "{}" ]] || ok=0
  [[ ! -s "$home/.claude/CLAUDE.md" && ! -s "$home/.claude/statusline.sh" ]] || ok=0
  check "A: 欠けている 12 項目を空で作成する（rc=$rc）" [ "$ok" -eq 1 -a "$rc" -eq 0 ]
  check "A: 作成を 12 行ログする" \
    [ "$(printf '%s\n' "$out" | grep -c '読み取り専用保護のため空で作成')" -eq 12 ]
  check "A: 作成物がすべて実行ユーザー所有" \
    bash -c "out=\$(find '$home/.claude' -not -uid $(id -u) -print 2>&1); [[ \$? -eq 0 && -z \"\$out\" ]]"
  printf '%s\n' "$out" >> "$LOG_FILE"
  local ctx
  ctx=$(sed -n 's/^BUILD_CONTEXT_DIR=//p' "$root/compose-env")
  if [[ "$ctx" != "$SCRIPT_DIR/.build-context/"* || ! -d "$ctx" ]]; then
    check "C: 前提のステージングディレクトリが隔離領域にある" false
    launcher_sandbox_cleanup
    return
  fi

  # A2: 2 回目は何も作らず、作成ログも出ない（冪等）
  run_launcher
  check "A2: 2 回目の起動では作成ログが出ない（rc=$rc）" \
    [ "$rc" -eq 0 -a "$(printf '%s\n' "$out" | grep -c '読み取り専用保護のため空で作成')" -eq 0 ]

  # B: 型不一致（hooks がディレクトリでなく通常ファイル）→ fail-closed
  rm -rf "$home/.claude/hooks"; echo x > "$home/.claude/hooks"
  run_launcher
  check "B: 型不一致は ERROR で起動中止（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q 'hooks'" "$out"
  check "B: 型不一致の拒否では何も作成しない" \
    [ "$(printf '%s\n' "$out" | grep -c '読み取り専用保護のため空で作成')" -eq 0 ]
  printf '%s\n' "$out" >> "$LOG_FILE"
  rm -f "$home/.claude/hooks"; mkdir -p "$home/.claude/hooks"

  # B2: symlink（有効なものを含む）は拒否する。:ro の子マウントはリンク先に付くが、
  # リンク自体は rw の親マウント内に残るため、コンテナ内で rm + mkdir すれば
  # 書き込み可能な実体に置き換えられてしまう（保護の迂回）。
  mkdir -p "$home/.claude/projects/hooks-target"
  rm -rf "$home/.claude/hooks"; ln -s projects/hooks-target "$home/.claude/hooks"
  run_launcher
  check "B2: symlink の保護対象は ERROR で起動中止（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q 'hooks'" "$out"
  check "B2: symlink の拒否では何も作成しない" \
    [ "$(printf '%s\n' "$out" | grep -c '読み取り専用保護のため空で作成')" -eq 0 ]
  printf '%s\n' "$out" >> "$LOG_FILE"
  rm -f "$home/.claude/hooks"; mkdir -p "$home/.claude/hooks"

  # C: 既存の内容・台帳・承認記録・ステージングも --check で変更しない（#55）。
  # A の通常起動が作った台帳と .build-context に加えて、上書き検出用の内容を置く。
  rm -rf "$home/.claude/skills"
  check "C: 前提の起動台帳がある" test -s "$home/.local/state/claude-container/projects"
  printf 'staging sentinel\n' > "$ctx/existing file"
  mkdir -p "$home/.local/state/claude-container/mcp-approvals"
  printf 'approval sentinel\n' > "$home/.local/state/claude-container/mcp-approvals/${ctx##*/}"
  printf 'project sentinel\n' > "$proj/existing file"
  snapshot_ok=1
  snapshot_check_targets > "$root/check-before" 2>> "$LOG_FILE" || snapshot_ok=0
  run_launcher_check
  snapshot_check_targets > "$root/check-after" 2>> "$LOG_FILE" || snapshot_ok=0
  check "C: --check の保護対象を収集できる（rc=$rc）" [ "$snapshot_ok" -eq 1 -a "$rc" -eq 0 ]
  check "C: --check は HOME・対象リポジトリ・build-context の内容と属性を変更しない" \
    cmp "$root/check-before" "$root/check-after"
  check "C: --check は欠けている項目を WARN で報告する" \
    bash -c "printf '%s' \"\$0\" | grep -q 'WARN' && printf '%s' \"\$0\" | grep -q 'skills'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
  mkdir -p "$home/.claude/skills"

  # C2: 台帳の実体不在を報告する失敗経路でも、台帳を修復・削除しない。
  printf '%s\n' "$root/deleted-project" >> "$home/.local/state/claude-container/projects"
  snapshot_ok=1
  snapshot_check_targets > "$root/check-before" 2>> "$LOG_FILE" || snapshot_ok=0
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" --check 2>&1) && rc=0 || rc=$?
  snapshot_check_targets > "$root/check-after" 2>> "$LOG_FILE" || snapshot_ok=0
  check "C2: 台帳の実体不在を失敗として報告する" [ "$snapshot_ok" -eq 1 -a "$rc" -eq 1 ]
  check "C2: 失敗した --check も台帳と保護対象を変更しない" cmp "$root/check-before" "$root/check-after"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # D: 相対パスの CLAUDE_CONFIG_DIR は拒否（compose 側の相対解決基準と食い違うため）
  run_launcher CLAUDE_CONFIG_DIR=relative/dir
  check "D: 相対パスの CLAUDE_CONFIG_DIR は ERROR（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR' && printf '%s' \"\$0\" | grep -q 'CLAUDE_CONFIG_DIR'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # E: ~/ 始まりは $HOME に展開され、その基点の .claude/ 配下に作られる
  # （基点ディレクトリ自体は存在が必須。無ければ他のマウント変数と同じく ERROR）
  mkdir -p "$home/cfgx"
  run_launcher CLAUDE_CONFIG_DIR='~/cfgx'
  check "E: ~/ の CLAUDE_CONFIG_DIR を基点に作成する（rc=$rc）" \
    [ "$rc" -eq 0 -a -d "$home/cfgx/.claude/hooks" -a -f "$home/cfgx/.claude/settings.json" ]
  check "E: compose には展開済み絶対パスの CLAUDE_CONFIG_DIR が渡る" \
    grep -qxF "CLAUDE_CONFIG_DIR=$home/cfgx" "$root/compose-env"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # F: 作業ディレクトリが基点の .claude を含む（= 別の rw 経路で書ける）→ WARNING
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" claude "$home" 2>&1) && rc=0 || rc=$?
  check "F: 作業ディレクトリが ~/.claude を含むと WARNING（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && printf '%s' \"\$0\" | grep -q 'WARNING' && printf '%s' \"\$0\" | grep -q '別の rw'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # G: 起動前から存在する型不一致・symlink は、先行する不足項目を作る前に拒否する
  #    （claude-container#131）。不正にするのは各配列の末尾（dirs の .git、files の
  #    statusline.sh）で、それより前の項目が作られないことを見る。既存の fixture を汚さない
  #    よう別基点へ隔離し、ケース・モードごとに基点ごと作り直す。
  local g_base g_cfg g_case g_name g_kind g_warn g_mode g_snap_ok
  g_base="$home/cfg131"; g_cfg="$g_base/.claude"
  while IFS='|' read -r g_case g_name g_kind g_warn; do
    for g_mode in run check; do
      if ! config_ro_fixture_setup "$g_base" "$g_name" "$g_kind"; then
        check "G: $g_case（$g_mode）の fixture を作成する" false
        continue
      fi
      g_snap_ok=1
      snapshot_config_ro_targets "$g_cfg" > "$root/g-before" 2>> "$LOG_FILE" || g_snap_ok=0
      launcher_sandbox_reset_records
      if [[ "$g_mode" == run ]]; then
        run_launcher CLAUDE_CONFIG_DIR="$g_base"
      else
        run_launcher_check CLAUDE_CONFIG_DIR="$g_base"
      fi
      snapshot_config_ro_targets "$g_cfg" > "$root/g-after" 2>> "$LOG_FILE" || g_snap_ok=0
      check "G: $g_case は ERROR で起動中止（$g_mode、rc=$rc）" \
        bash -c '[ "$1" -ne 0 ] && printf "%s" "$2" | grep -q "ERROR" && printf "%s" "$2" | grep -qF "$3"' \
          _ "$rc" "$out" "$g_name"
      check "G: $g_case は保護対象を変更しない（$g_mode）" \
        bash -c '[ "$1" -eq 1 ] && cmp -s "$2" "$3"' _ "$g_snap_ok" "$root/g-before" "$root/g-after"
      check "G: $g_case は先行項目を作成しない（$g_mode）" \
        [ "$(printf '%s\n' "$out" | grep -c '読み取り専用保護のため空で作成')" -eq 0 ]
      check "G: $g_case は compose を呼ばない（$g_mode）" [ ! -e "$root/compose-calls" ]
      # --check は事前検査を通さず、不正項目より前の欠落を従来どおり WARN する（g_warn 件）
      if [[ "$g_mode" == check ]]; then
        check "G: $g_case は不正項目より前の欠落 $g_warn 件を WARN する（check）" \
          [ "$(printf '%s\n' "$out" | awk '/ERROR/ { exit } /が無い（通常起動時に空で作成）/ { n++ } END { print n + 0 }')" -eq "$g_warn" ]
      fi
      printf '%s\n' "$out" >> "$LOG_FILE"
    done
  done <<'GCASES'
G1 .git が gitfile|.git|file|8
G2 .git が有効 symlink|.git|link|8
G3 .git が dangling symlink|.git|dangling|8
G4 statusline.sh がディレクトリ|statusline.sh|dir|11
G5 statusline.sh が有効 symlink|statusline.sh|linkfile|11
G6 statusline.sh が dangling symlink|statusline.sh|dangling|11
GCASES
  rm -rf "$g_base"

  launcher_sandbox_cleanup
}

# plugin 別名マウント（claude-container#98）の検証。launcher がホスト側 plugins/ の綴りを
# コンテナ内の同じ絶対パスにも :ro で重ねる override（compose.plugins-alias.yml）を選び、
# build・run の各呼び出しへ export と override を渡すこと。判定関数 plugins_alias_target()
# は副作用が無いので、関数定義だけを抽出して /home/node を作らずに一致分岐まで検証する。
# shellcheck disable=SC2016  # bash -c の検証式は親で展開せず、位置引数を子シェル内で評価する
run_plugins_alias_launcher_tests() {
  local root bin home proj out rc before_ctx
  launcher_sandbox_init
  log "## plugin 別名マウント（compose.plugins-alias.yml、#98）"

  # T: 判定関数の単体検査（関数抽出。ファイルシステムに触れない）。
  # 各行は <ケース名>|<base の綴り>|<HOME>|<期待 rc>|<期待 stdout>。
  local fn t_case t_base t_home t_rc t_out got_rc got_out
  fn=$(sed -n '/^plugins_alias_target()/,/^}/p' "${SCRIPT_DIR}/c3c")
  check "T: plugins_alias_target() を抽出できる" [ -n "$fn" ]
  while IFS='|' read -r t_case t_base t_home t_rc t_out; do
    got_out=$(bash -euo pipefail -c "$fn"$'\n''plugins_alias_target "$1" "$2"' _ "$t_base" "$t_home" 2>/dev/null) && got_rc=0 || got_rc=$?
    check "T: $t_case → rc=$t_rc" [ "$got_rc" = "$t_rc" -a "$got_out" = "$t_out" ]
  done <<'CASES'
通常の HOME 配下|/home/u|/home/u|0|/home/u/.claude/plugins
末尾スラッシュ|/home/u/|/home/u|0|/home/u/.claude/plugins
末尾の /.|/home/u/.|/home/u|0|/home/u/.claude/plugins
二重スラッシュ|/home//u|/home/u|0|/home/u/.claude/plugins
HOME 側の末尾スラッシュ|/home/u|/home/u/|0|/home/u/.claude/plugins
HOME 配下のサブディレクトリ|/home/u/cfg|/home/u|0|/home/u/cfg/.claude/plugins
コンテナ内パスと一致|/home/node|/home/node|1|
コンテナ内パスと一致（末尾スラッシュ）|/home/node/|/home/node|1|
コンテナ内パスと一致（HOME が /）|/home/node|/|1|
コンテナ内パスと一致（HOME が不正）|/home/node|/home/./u|1|
コンテナ内パスと一致（HOME が別）|/home/node|/home/u|1|
HOME 配下でない|/opt/cfg|/home/u|2|
HOME の実体パス綴り違い|/mnt/real/u|/home/u|2|
HOME と前方一致するだけの別ディレクトリ|/home/user2|/home/u|2|
親ディレクトリ参照|/home/u/../x|/home/u|2|
内部の /./|/home/./u|/home/u|2|
ルート|/|/|2|
/workspace 配下|/workspace/cfg|/workspace|2|
/data と一致|/data|/data|2|
/shared 配下|/shared/u|/shared|2|
/home/node 配下|/home/node/cfg|/home/node|2|
CASES

  # P1: 既定（CLAUDE_CONFIG_DIR 未設定）→ run 呼び出しに export と override が渡る
  run_launcher
  check "P1: 既定で別名を export し override を run に渡す（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && [ "$(cat "$3/compose-calls")" -eq 1 ] \
      && grep -qxF "CLAUDE_PLUGINS_HOST_PATH=$2/.claude/plugins" "$3/compose-env.1" \
      && grep -qxF "$4/compose.plugins-alias.yml" "$3/compose-args.1"' _ "$rc" "$home" "$root" "$SCRIPT_DIR"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # P2: -b では build・run の各呼び出しに export と override が 1 回ずつ渡る
  cat > "$bin/curl" <<'CURL'
#!/bin/sh
# 実 curl と同じく --output 先へ書く（stdout へ出すと再試行時に巻き戻せない）。
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then
    printf '%s\n' '{"web":[],"api":[],"git":[]}' > "$2"
    exit 0
  fi
  shift
done
exit 2
CURL
  chmod +x "$bin/curl"
  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" claude -b "$proj" 2>&1) && rc=0 || rc=$?
  check "P2: -b の build と run の各呼び出しに別名が渡る（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && [ "$(cat "$3/compose-calls")" -eq 2 ] \
      && grep -qx build "$3/compose-args.1" && grep -qx run "$3/compose-args.2" \
      && grep -qxF "CLAUDE_PLUGINS_HOST_PATH=$2/.claude/plugins" "$3/compose-env.1" \
      && grep -qxF "CLAUDE_PLUGINS_HOST_PATH=$2/.claude/plugins" "$3/compose-env.2" \
      && [ "$(grep -cxF "$4/compose.plugins-alias.yml" "$3/compose-args.1")" -eq 1 ] \
      && [ "$(grep -cxF "$4/compose.plugins-alias.yml" "$3/compose-args.2")" -eq 1 ]' _ "$rc" "$home" "$root" "$SCRIPT_DIR"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # P3: IPv6=1 併用の -b では両 override が build・run の各呼び出しに 1 回ずつ共存する
  mkdir -p "$proj/.claude-container.d"
  printf 'CLAUDE_CONTAINER_IPV6=1\n' > "$proj/.claude-container.d/env"
  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" claude -b "$proj" 2>&1) && rc=0 || rc=$?
  check "P3: IPv6 override と別名 override が build・run に共存する（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && [ "$(cat "$2/compose-calls")" -eq 2 ] && for n in 1 2; do
      [ "$(grep -cxF "$3/compose.ipv6.yml" "$2/compose-args.$n")" -eq 1 ] || exit 1
      [ "$(grep -cxF "$3/compose.plugins-alias.yml" "$2/compose-args.$n")" -eq 1 ] || exit 1
    done' _ "$rc" "$root" "$SCRIPT_DIR"
  printf '%s\n' "$out" >> "$LOG_FILE"
  rm -f "$proj/.claude-container.d/env"

  # P4: CLAUDE_CONFIG_DIR=~/cfg/（末尾スラッシュ）→ 正規化した綴りで別名を付ける
  mkdir -p "$home/cfg"
  run_launcher CLAUDE_CONFIG_DIR='~/cfg/'
  check "P4: ~/cfg/ の別名は正規化した綴り（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && grep -qxF "CLAUDE_PLUGINS_HOST_PATH=$2/cfg/.claude/plugins" "$3/compose-env"' _ "$rc" "$home" "$root"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # P5: HOME がシンボリックリンク → launcher は綴り（リンク）を保つ（実体パスに解決しない）
  ln -s "$home" "$root/home-link"
  launcher_sandbox_reset_records
  out=$(env -i HOME="$root/home-link" PATH="$bin:$PATH" "${SCRIPT_DIR}/c3c" claude "$proj" 2>&1) && rc=0 || rc=$?
  check "P5: symlink の HOME でも別名はリンクの綴り（rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && grep -qxF "CLAUDE_PLUGINS_HOST_PATH=$2/home-link/.claude/plugins" "$2/compose-env"' _ "$rc" "$root"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # P6: 範囲外（基点が $HOME 配下でない）→ WARNING を出し、override も export も無い。
  # 起動は止めない（plugin が読めないだけで境界には影響しない）。--check も同じ WARNING。
  mkdir -p "$root/outside"
  run_launcher CLAUDE_CONFIG_DIR="$root/outside" CLAUDE_PLUGINS_HOST_PATH=/workspace
  check "P6: HOME 配下でない基点は WARNING で別名を付けない（注入値も残さない、rc=$rc）" \
    bash -c '[ "$1" -eq 0 ] && [[ "$2" == *WARNING*plugins/* ]] \
      && grep -q . "$3/compose-env" && grep -qx run "$3/compose-args" \
      && ! grep -q "^CLAUDE_PLUGINS_HOST_PATH=" "$3/compose-env" \
      && ! grep -qF compose.plugins-alias.yml "$3/compose-args"' _ "$rc" "$out" "$root"
  printf '%s\n' "$out" >> "$LOG_FILE"
  run_launcher_check CLAUDE_CONFIG_DIR="$root/outside"
  check "P6: --check も同じ WARNING を出す（rc=$rc）" bash -c '[[ "$1" == *WARNING*plugins/* ]]' _ "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"

  # P7: --check は保護対象（HOME・対象リポジトリ・build-context）を変更しない。
  # 基点不正では成功風の [OK] を出さず、.claude 不在（早期 return 経路）でも別名は判定する。
  local snapshot_ok label expect
  local -a cargs
  mkdir -p "$home/bare"
  for label in 既定 範囲外 基点不正 .claude不在; do
    case "$label" in
      既定) cargs=(); expect="[OK]   plugin 別名: $home/.claude/plugins" ;;
      範囲外) cargs=(CLAUDE_CONFIG_DIR="$root/outside"); expect="WARNING" ;;
      基点不正) cargs=(CLAUDE_CONFIG_DIR=/nonexistent-plugins-alias); expect="" ;;
      .claude不在) cargs=(CLAUDE_CONFIG_DIR="$home/bare"); expect="[OK]   plugin 別名: $home/bare/.claude/plugins" ;;
    esac
    snapshot_ok=1
    snapshot_check_targets > "$root/check-before" 2>> "$LOG_FILE" || snapshot_ok=0
    run_launcher_check "${cargs[@]}"
    snapshot_check_targets > "$root/check-after" 2>> "$LOG_FILE" || snapshot_ok=0
    check "P7: --check（$label）は保護対象を変更しない" \
      bash -c '[ "$1" -eq 1 ] && cmp -s "$2/check-before" "$2/check-after"' _ "$snapshot_ok" "$root"
    if [[ -n "$expect" ]]; then
      check "P7: --check（$label）の判定表示" bash -c '[[ "$1" == *"$2"* ]]' _ "$out" "$expect"
    else
      check "P7: --check（$label）は成功風の別名表示を出さない（rc=$rc）" \
        bash -c '[ "$1" -ne 0 ] && [[ "$2" != *"plugin 別名"* ]]' _ "$rc" "$out"
    fi
    printf '%s\n' "$out" >> "$LOG_FILE"
  done

  launcher_sandbox_cleanup
}

# 指示ファイル・スキルの追加共有（claude-container#99）の検証。launcher が opt-in と値を検証し、
# compose.shared-home.yml / compose.shared-host.yml / compose.agents.yml を build・run の各呼び出しへ
# export と一緒に渡すこと、不正値と HOME 外・保護先と重なる値を compose に到達する前に拒否すること。
# shellcheck disable=SC2016  # bash -c の検証式は親で展開せず、位置引数を子シェル内で評価する
run_instruction_mount_launcher_tests() {
  local root bin home proj out rc before_ctx value
  launcher_sandbox_init
  log "## 指示ファイルとスキルの追加共有（#99）"
  mkdir -p "$home/obsidian-vault/knowledge" "$home/.agents/skills" "$proj/.claude-container.d"
  printf '索引\n' > "$home/obsidian-vault/knowledge/索引.md"

  run_launcher SHARED_MOUNT="$home/obsidian-vault" \
    CLAUDE_SHARED_HOME_PATH=/tmp/injected CLAUDE_SHARED_HOST_PATH=/tmp/injected
  check "未設定なら /shared のみで内部別名変数も破棄する" \
    bash -c '[ "$1" = 0 ] && ! grep -qE "compose\.(shared|agents)|^CLAUDE_SHARED_(HOME|HOST)_PATH=" "$2/compose-args" "$2/compose-env"' _ "$rc" "$root"

  printf 'SHARED_MOUNT=~/obsidian-vault\nSHARED_MOUNT_HOME_ALIAS=1\nAGENTS_DIR=~/.agents\n' > "$proj/.claude-container.d/env"
  run_launcher
  check "env の opt-in が ~/ とホスト絶対パスの別名、およびスキル共有を渡す" \
    bash -c '[ "$1" = 0 ] && grep -qxF "CLAUDE_SHARED_HOME_PATH=/home/node/obsidian-vault" "$2/compose-env" && grep -qxF "CLAUDE_SHARED_HOST_PATH=$3/obsidian-vault" "$2/compose-env" && grep -qxF "AGENTS_DIR=$3/.agents" "$2/compose-env" && grep -qxF "$4/compose.shared-home.yml" "$2/compose-args" && grep -qxF "$4/compose.shared-host.yml" "$2/compose-args" && grep -qxF "$4/compose.agents.yml" "$2/compose-args"' _ "$rc" "$root" "$home" "$SCRIPT_DIR"
  printf '%s\n' "$out" >> "$LOG_FILE"

  local snapshot_ok=1
  snapshot_check_targets > "$root/before" 2>> "$LOG_FILE" || snapshot_ok=0
  run_launcher_check
  snapshot_check_targets > "$root/after" 2>> "$LOG_FILE" || snapshot_ok=0
  check "有効な --check は追加共有を診断し対象を変更しない" \
    bash -c '[ "$1" -eq 1 ] && [ "$2" = 0 ] && [[ "$3" == *"/home/node/obsidian-vault"* && "$3" == *"AGENTS_DIR"* ]] && cmp -s "$4/before" "$4/after"' _ "$snapshot_ok" "$rc" "$out" "$root"

  launcher_sandbox_reset_records
  out=$(env -i HOME="$home" PATH="$bin:$PATH" CLAUDE_CONTAINER_IPV6=1 \
    "${SCRIPT_DIR}/c3c" claude -b "$proj" 2>&1) && rc=0 || rc=$?
  check "build と run に共有・スキル・plugin・IPv6 の override が共存する" \
    bash -c '[ "$1" = 0 ] && [ "$(cat "$2/compose-calls")" = 2 ] || exit 1
      for n in 1 2; do for f in shared-home shared-host agents plugins-alias ipv6; do
        grep -qxF "$3/compose.$f.yml" "$2/compose-args.$n" || exit 1
      done; done' _ "$rc" "$root" "$SCRIPT_DIR"
  printf '%s\n' "$out" >> "$LOG_FILE"
  : > "$proj/.claude-container.d/env"

  # ガードを落とすと、これらが compose に到達して設定を隠すか、ホストに空の実体を作る。
  for value in '' 2 true '1 '; do
    [[ -n "$value" ]] || continue
    run_launcher SHARED_MOUNT_HOME_ALIAS="$value" SHARED_MOUNT="$home/obsidian-vault"
    check "別名フラグの不正値 '$value' を起動時に拒否する" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check SHARED_MOUNT_HOME_ALIAS="$value" SHARED_MOUNT="$home/obsidian-vault"
    check "別名フラグの不正値 '$value' を --check も拒否する" [ "$rc" -ne 0 ]
  done
  mkdir -p "$home/.claude/notes" "$home/.config/notes" "$home/nested/vault" "$root/outside"
  for value in '' "$home" "$root/outside" "$home/.claude" "$home/.claude/notes" "$home/.agents" "$home/.config/notes" "$home/nested/../obsidian-vault"; do
    run_launcher SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$value"
    check "未指定・HOME外・保護先と重なる別名を拒否する: $value" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"ERROR:"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$value"
    check "--check も同じ別名を拒否する: $value" [ "$rc" -ne 0 ]
  done
  for value in relative "$home/missing-agents" "$home/obsidian-vault/knowledge/索引.md"; do
    run_launcher AGENTS_DIR="$value"
    check "不正な AGENTS_DIR を compose 前に拒否する: $value" \
      bash -c '[ "$1" != 0 ] && [[ "$2" == *"AGENTS_DIR"* ]] && [ ! -e "$3/compose-env" ]' _ "$rc" "$out" "$root"
    run_launcher_check AGENTS_DIR="$value"
    check "--check も同じ AGENTS_DIR を拒否する: $value" [ "$rc" -ne 0 ]
  done
  run_launcher SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$home/nested/vault/" AGENTS_DIR="$home/.agents"
  check "HOME 配下の階層を保ち末尾 / を正規化する" \
    bash -c '[ "$1" = 0 ] && grep -qxF "CLAUDE_SHARED_HOME_PATH=/home/node/nested/vault" "$2/compose-env"' _ "$rc" "$root"
  run_launcher AGENTS_DIR="$home/.agents" EXTRA_MOUNT="$home"
  check "別 rw マウントによるスキル共有への書き込み経路を警告する" \
    bash -c '[ "$1" = 0 ] && [[ "$2" == *"WARNING:"*"AGENTS_DIR"*"rw"* ]]' _ "$rc" "$out"
  ln -s "$home/obsidian-vault" "$home/vault-link"
  run_launcher SHARED_MOUNT_HOME_ALIAS=1 SHARED_MOUNT="$home/vault-link"
  check "symlink の SHARED_MOUNT は綴りを別名に、実体を /shared の source にする" \
    bash -c '[ "$1" = 0 ] && grep -qxF "CLAUDE_SHARED_HOME_PATH=/home/node/vault-link" "$2/compose-env" && grep -qxF "CLAUDE_SHARED_HOST_PATH=$3/vault-link" "$2/compose-env" && grep -qxF "SHARED_MOUNT=$(cd "$3/obsidian-vault" && pwd -P)" "$2/compose-env"' _ "$rc" "$root" "$home"
  launcher_sandbox_cleanup
}

if [[ "${1:-}" == "--validator-only" ]]; then
  run_validator_layer1_and_contract
  finish_by_result
fi

# 保護テストだけを回す入口（イメージはビルド済みの $IMAGE を使う。無ければ FAIL）。
# 従来どおり、実 podman の書き込み検査とランチャー側の placeholder 検証を両方回す。
if [[ "${1:-}" == "--config-ro-only" ]]; then
  run_config_ro_tests
  run_config_ro_launcher_tests
  finish_by_result
fi

# ランチャーテストだけを回す入口（実 podman 不要。コンテナ内開発や CI 向け）。
if [[ "${1:-}" == "--launcher-only" ]]; then
  run_launcher_tests
  finish_by_result
fi

log "========================================"
log "  Build & Smoke Test  $(date)"
log "  Log: $LOG_FILE"
log "========================================"
log ""

log "## 静的チェック"
check "bash -n c3c" bash -n "${SCRIPT_DIR}/c3c"
check "podman compose config" env \
  CLAUDE_CONTAINER_DIR="$SCRIPT_DIR" BUILD_CONTEXT_DIR="$SCRIPT_DIR/.build-context/test" CONTEXT="$SCRIPT_DIR" \
  podman compose -f "${SCRIPT_DIR}/compose.yml" config
log ""

# c3c の stage_build_context() 相当。Dockerfile.claude が要求する
# entrypoint.sh・init-firewall.sh・git-askpass.sh・validate-build-input.sh・
# allowed-domains.txt・node-version.txt・codex-version.txt・allowed-ports.txt・
# github-meta.json を一時ディレクトリへ集約する（packages.txt/requirements.txt は
# 呼び出し側で個別にコピーする — プロジェクト上書きテストではソースが変わるため）。
# node-version.txt・codex-version.txt は同梱 default（c3c 第2b-2段階）をコピーする。
# 通常のテストイメージは default 込み（Node 24 + Codex CLI）で、opt-out 専用のケース
# だけ呼び出し側が空ファイルで上書きする（空 = 明示 opt-out、default で埋めない）。
# リポジトリルート直下には github-meta.json が存在しないため、直接 $SCRIPT_DIR
# をビルドコンテキストに渡すと COPY で失敗する（2026-07-02 の GitHub meta
# スナップショット化以降の既存の不整合、Issue #1 対応の動作確認時に検出・修正）。
stage_common_context() {
  local dest="$1"
  cp "${SCRIPT_DIR}/entrypoint.sh" "$dest/entrypoint.sh"
  cp "${SCRIPT_DIR}/init-firewall.sh" "$dest/init-firewall.sh"
  cp "${SCRIPT_DIR}/ipv6-firewall.py" "$dest/ipv6-firewall.py"
  cp "${SCRIPT_DIR}/firewall-refresh.py" "$dest/firewall-refresh.py"
  cp "${SCRIPT_DIR}/codex-mcp-audit.py" "$dest/codex-mcp-audit.py"
  cp "${SCRIPT_DIR}/git-askpass.sh" "$dest/git-askpass.sh"
  cp "${SCRIPT_DIR}/validate-build-input.sh" "$dest/validate-build-input.sh"
  cp "${SCRIPT_DIR}/allowed-domains.txt" "$dest/allowed-domains.txt"
  cp "${SCRIPT_DIR}/node-version.txt" "$dest/node-version.txt"
  cp "${SCRIPT_DIR}/codex-version.txt" "$dest/codex-version.txt"
  : > "$dest/allowed-ports.txt"

  local sibling gh_meta fetch_rc
  gh_meta=$(mktemp "$dest/github-meta.XXXXXX") || return 1
  # launcher と同じ上限。部分応答を再試行で連結しないよう curl 自身にファイルを渡す。
  if (
    trap 'rm -f "$gh_meta"' EXIT
    timeout --foreground --kill-after=5 90 curl -q -fsS --connect-timeout 10 --max-time 30 \
      --retry 2 --retry-connrefused --retry-max-time 60 \
      --output "$gh_meta" https://api.github.com/meta \
      && jq -e '.web and .api and .git' "$gh_meta" >/dev/null 2>&1 \
      && mv "$gh_meta" "$dest/github-meta.json"
  ); then
    return 0
  else
    fetch_rc=$?
  fi
  echo "WARNING: GitHub meta の取得・検証に失敗しました（rc=$fetch_rc、接続10秒・1試行30秒・再試行2回・全体90秒上限）。通信・レート制限・応答形式を確認してください" >&2
  # shellcheck disable=SC2012 # パスは PROJECT_NAME（サニタイズ済み）+ 固定ファイル名のみで空白・改行を含まない
  sibling=$(ls -t "${SCRIPT_DIR}"/.build-context/*/github-meta.json 2>/dev/null | head -1)
  if [[ -n "$sibling" ]]; then
    echo "WARNING: GitHub meta の取得に失敗しました。$sibling を再利用します" >&2
    cp "$sibling" "$dest/github-meta.json"
  else
    echo "ERROR: GitHub meta の取得に失敗し、既存スナップショットもありません（通信・未認証 API のレート制限・応答形式を確認してください）" >&2
    return 77
  fi
}

log "## ビルド"
BUILD_STAGE_DIR="$(mktemp -d)"
if stage_common_context "$BUILD_STAGE_DIR"; then
  cp "${SCRIPT_DIR}/packages.txt" "$BUILD_STAGE_DIR/packages.txt"
  cp "${SCRIPT_DIR}/requirements.txt" "$BUILD_STAGE_DIR/requirements.txt"
  check "podman build --no-cache" podman build --no-cache \
    -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$IMAGE" "$BUILD_STAGE_DIR"
else
  stage_rc=$?
  if [[ "${1:-}" == --build-only && "$stage_rc" == 77 && "$FAIL" == 0 ]]; then
    log 'not run: GitHub meta を取得できないため実ビルドを開始できません'
    rm -rf "$BUILD_STAGE_DIR"
    exit 77
  fi
  check "podman build --no-cache (staging failed: see stderr above)" false
fi
rm -rf "$BUILD_STAGE_DIR"
log ""

# ビルド段階が失敗したら、同じタグに残る古いイメージで起動検査を続けない。
if [[ "${1:-}" == "--build-only" && "$FAIL" != 0 ]]; then
  finish_by_result
fi

log "## イメージサイズ"
podman images "$IMAGE" --format \
  "  Repository: {{.Repository}}\n  Tag:        {{.Tag}}\n  Size:       {{.Size}}" \
  | tee -a "$LOG_FILE"
log ""

log "## Claude Code ツール"
check "定期更新 helper の依存モジュールと起動" podman run --rm --network=none "$IMAGE" /usr/local/bin/firewall-refresh.py --help
check "IPv6 helper の依存モジュールと起動" podman run --rm --network=none "$IMAGE" /usr/local/bin/ipv6-firewall.py --help
check "Codex 審査 helper の依存モジュールと起動" podman run --rm --network=none "$IMAGE" python3 -I /usr/local/bin/codex-mcp-audit.py --help
check "Codex 審査 helper が使う tomllib（Python 3.11 以上）" podman run --rm --network=none "$IMAGE" python3 -I -c 'import tomllib'
check "claude --version" podman run --rm "$IMAGE" claude --version
check "gh --version"     podman run --rm "$IMAGE" gh --version
check "jq --version"     podman run --rm "$IMAGE" jq --version
log ""

# 同梱 default（c3c 第2b-2段階）の実検査。イメージ内の Node.js / Codex CLI が同梱ファイルの固定値と
# 一致することを必須にする（存在だけでは、ベースイメージ由来の別版や npm の latest 解決を見逃す）。
# 起動時 MCP 審査は #150 から Codex の版に依存しないので、審査側の版との整合は検査しない。
log "## 同梱 default（node-version.txt / codex-version.txt）の実検査"
DEFAULT_NODE_VERSION="$(tr -d '[:space:]' < "${SCRIPT_DIR}/node-version.txt")"
DEFAULT_CODEX_VERSION="$(tr -d '[:space:]' < "${SCRIPT_DIR}/codex-version.txt")"
# shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
check "同梱 node-version.txt が固定版（空・latest でない）" \
  bash -c '[[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]' _ "$DEFAULT_NODE_VERSION"
# shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
check "同梱 codex-version.txt が固定版（空・latest でない）" \
  bash -c '[[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]' _ "$DEFAULT_CODEX_VERSION"
# shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
check "node --version が同梱 default（v$DEFAULT_NODE_VERSION）と一致" \
  bash -c 'actual=$(podman run --rm --network=none "$1" node --version) && echo "$actual" && [ "$actual" = "v$2" ]' _ "$IMAGE" "$DEFAULT_NODE_VERSION"
check "npm --version" podman run --rm --network=none "$IMAGE" npm --version
# shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
check "codex --version が同梱 default（codex-cli $DEFAULT_CODEX_VERSION）と一致" \
  bash -c 'actual=$(podman run --rm --network=none "$1" codex --version) && echo "$actual" && [ "$actual" = "codex-cli $2" ]' _ "$IMAGE" "$DEFAULT_CODEX_VERSION"
# shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
check "codex の実体が entrypoint.sh の固定パス /usr/local/bin/codex にある" \
  bash -c 'podman run --rm --network=none "$1" sh -c "[ -x /usr/local/bin/codex ] && [ -x /usr/local/bin/node ] && [ -x /usr/local/bin/npm ]"' _ "$IMAGE"
# Codex 同梱 bubblewrap の固定リンク（#145）。Dockerfile.claude のビルド時検査と同じ条件を、最終
# イメージで node ユーザーとして確かめ直す（ビルド後の層で所有者・mode が変わっていないことの確認）。
# shellcheck disable=SC2016  # コンテナ内の sh で評価する
CODEX_BWRAP_PROBE='set -e
d=/usr/local/libexec/c3c/codex-bwrap; l="$d/bwrap"
[ -L "$l" ] && [ "$(ls -A "$d")" = bwrap ] || { echo "専用ディレクトリの中身が固定リンク一つではない"; exit 1; }
case "$(uname -m)" in x86_64) t=x86_64-unknown-linux-musl ;; aarch64) t=aarch64-unknown-linux-musl ;; *) exit 1 ;; esac
r="$(readlink "$l")"
e="$(readlink -e "$l")" && [ -n "$e" ] || { echo "固定リンクの実体を解決できない"; exit 1; }
[ "$r" = "$e" ] || { echo "固定リンクが正規化済みの絶対パスではない: $r"; exit 1; }
case "$r" in /usr/local/lib/node_modules/@openai/*/vendor/"$t"/codex-resources/bwrap) ;; *) echo "実体が npm の対応 triple 外: $r"; exit 1 ;; esac
echo "$l -> $r"; "$l" --version
help="$("$l" --help)"
for o in --as-pid-1 --perms --argv0 --ro-bind-fd; do printf "%s\n" "$help" | grep -qE -- "(^|[^-a-z0-9])$o([^-a-z0-9]|\$)" || { echo "help に $o が無い"; exit 1; }; done
bad="$(find "$l" -maxdepth 0 ! -user 0 -print)" || { echo "固定リンクの所有者を検査できない"; exit 1; }
[ -z "$bad" ] || { echo "固定リンクが root 所有でない"; exit 1; }
for p in "$r" "$d"; do
  while :; do
    bad="$(find "$p" -maxdepth 0 \( ! -user 0 -o -perm /022 \) -print)" || { echo "所有者・mode を検査できない: $p"; exit 1; }
    [ -z "$bad" ] || { echo "root 所有でないか group/other 書込可: $p"; exit 1; }
    ! [ -w "$p" ] || { echo "node から書込可: $p"; exit 1; }
    [ "$p" = / ] && break
    p="$(dirname "$p")"
  done
done
[ "$(id -u)" != 0 ]'
check "Codex 同梱 bubblewrap の固定リンク（唯一の symlink・npm の対応 triple・help 4 項目・root 所有・node から書込不可）" \
  podman run --rm --network=none "$IMAGE" sh -c "$CODEX_BWRAP_PROBE"
log ""

# 実コンテナ CI はこのビルドとツール起動を再利用し、続くマウント・通信検査を別段階にする。
# 全体実行の追加パッケージ・不正入力のビルド検査は、従来どおり引数なしで実行する。
if [[ "${1:-}" == "--build-only" ]]; then
  finish_by_result
fi

log "## .claude-container.d によるパッケージ上書き"
OVERRIDE_IMAGE="localhost/claude-test-override"
OVERRIDE_PROJECT_DIR="$(mktemp -d)"
OVERRIDE_CONTEXT_DIR="$(mktemp -d)"
mkdir -p "$OVERRIDE_PROJECT_DIR/.claude-container.d"
echo "htop" > "$OVERRIDE_PROJECT_DIR/.claude-container.d/packages.txt"

# c3c スクリプトが行うステージング（プロジェクト側 packages.txt を
# ビルドコンテキストへ集約する処理）を模して検証する
if stage_common_context "$OVERRIDE_CONTEXT_DIR"; then
  cp "$OVERRIDE_PROJECT_DIR/.claude-container.d/packages.txt" "$OVERRIDE_CONTEXT_DIR/packages.txt"
  cp "${SCRIPT_DIR}/requirements.txt" "$OVERRIDE_CONTEXT_DIR/requirements.txt"
  check "podman build (override context)" podman build --no-cache \
    -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$OVERRIDE_IMAGE" "$OVERRIDE_CONTEXT_DIR"
  check "htop が入っている"  podman run --rm "$OVERRIDE_IMAGE" which htop
else
  check "podman build (override context) (staging failed: see stderr above)" false
  check "htop が入っている" false
fi

podman rmi "$OVERRIDE_IMAGE" 2>/dev/null
rm -rf "$OVERRIDE_PROJECT_DIR" "$OVERRIDE_CONTEXT_DIR"
log ""

run_validator_layer1_and_contract
log "## 層2: Dockerfile.claude 配線の回帰条件（claude-container#34）"
run_validator_layer2
log ""

log "## packages.txt/requirements.txt ビルド時検証テスト（claude-container#34）"
# 失敗期待用ヘルパ。exit≠0 だけを assert しない — 検証段階より前のレイヤー
# （apt基盤・gh・Claudeインストール等、ネットワーク依存）の偶発失敗でも fail
# するため、stderr に検証エラーメッセージが含まれることまで assert して
# 「正しい理由で落ちた」ことを確認する。
check_fails() {
  local desc="$1"; local expect_pattern="$2"; shift 2
  local output status
  output=$("$@" 2>&1) && status=0 || status=$?
  if [ "$status" -ne 0 ] && printf '%s' "$output" | grep -qF "$expect_pattern"; then
    printf "  %-52s[PASS]\n" "$desc" | tee -a "$LOG_FILE"
    PASS=$((PASS + 1))
  else
    printf "  %-52s[FAIL]\n" "$desc" | tee -a "$LOG_FILE"
    FAIL=$((FAIL + 1))
  fi
  printf "%s\n" "$output" >> "$LOG_FILE"
}

# 陰性1: packages.txt に注入行 → ビルドが fail することを assert
NEG1_IMAGE="localhost/claude-test-neg1"
NEG1_PROJECT_DIR="$(mktemp -d)"
NEG1_CONTEXT_DIR="$(mktemp -d)"
mkdir -p "$NEG1_PROJECT_DIR/.claude-container.d"
printf 'tini-\n' > "$NEG1_PROJECT_DIR/.claude-container.d/packages.txt"
if stage_common_context "$NEG1_CONTEXT_DIR"; then
  cp "$NEG1_PROJECT_DIR/.claude-container.d/packages.txt" "$NEG1_CONTEXT_DIR/packages.txt"
  cp "${SCRIPT_DIR}/requirements.txt" "$NEG1_CONTEXT_DIR/requirements.txt"
  check_fails "陰性1: packages.txt注入行でビルドfail" "仕様外の行があります" \
    podman build -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$NEG1_IMAGE" "$NEG1_CONTEXT_DIR"
else
  check "陰性1: packages.txt注入行でビルドfail (staging failed: see stderr above)" false
fi
podman rmi "$NEG1_IMAGE" 2>/dev/null
rm -rf "$NEG1_PROJECT_DIR" "$NEG1_CONTEXT_DIR"

# 陰性2: requirements.txt に --index-url ... → 同上
# （検証が pip3 の有無に依存しないため検証段階で止まる）
NEG2_IMAGE="localhost/claude-test-neg2"
NEG2_PROJECT_DIR="$(mktemp -d)"
NEG2_CONTEXT_DIR="$(mktemp -d)"
mkdir -p "$NEG2_PROJECT_DIR/.claude-container.d"
printf -- '--index-url https://evil.example/simple\n' > "$NEG2_PROJECT_DIR/.claude-container.d/requirements.txt"
if stage_common_context "$NEG2_CONTEXT_DIR"; then
  cp "${SCRIPT_DIR}/packages.txt" "$NEG2_CONTEXT_DIR/packages.txt"
  cp "$NEG2_PROJECT_DIR/.claude-container.d/requirements.txt" "$NEG2_CONTEXT_DIR/requirements.txt"
  check_fails "陰性2: requirements.txt注入行でビルドfail" "仕様外の行があります" \
    podman build -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$NEG2_IMAGE" "$NEG2_CONTEXT_DIR"
else
  check "陰性2: requirements.txt注入行でビルドfail (staging failed: see stderr above)" false
fi
podman rmi "$NEG2_IMAGE" 2>/dev/null
rm -rf "$NEG2_PROJECT_DIR" "$NEG2_CONTEXT_DIR"

# 陽性1: packages.txt に python3-pip、requirements.txt に requests#garbage を置き、
# ビルドが成功することを assert（正規化済み requirements が pip に実際に受理される
# ことを検証する唯一の実行主体。陰性2件は検証段階で止まり pip に到達しない）。
# --no-cache は付けない（付けると検証レイヤに到達する前の全レイヤを毎回再ビルド
# する。python3-pip を置く以上 COPY packages.txt でキャッシュミスとなり実走する）。
POS1_IMAGE="localhost/claude-test-pos1"
POS1_PROJECT_DIR="$(mktemp -d)"
POS1_CONTEXT_DIR="$(mktemp -d)"
mkdir -p "$POS1_PROJECT_DIR/.claude-container.d"
printf 'python3-pip\n' > "$POS1_PROJECT_DIR/.claude-container.d/packages.txt"
printf 'requests#garbage\n' > "$POS1_PROJECT_DIR/.claude-container.d/requirements.txt"
if stage_common_context "$POS1_CONTEXT_DIR"; then
  cp "$POS1_PROJECT_DIR/.claude-container.d/packages.txt" "$POS1_CONTEXT_DIR/packages.txt"
  cp "$POS1_PROJECT_DIR/.claude-container.d/requirements.txt" "$POS1_CONTEXT_DIR/requirements.txt"
  check "陽性1: 正規化済みrequirementsでビルド成功" podman build \
    -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$POS1_IMAGE" "$POS1_CONTEXT_DIR"
  # ビルド成功だけを assert しない — 「pip が正しく走った」と「pip 段が丸ごと
  # スキップされた」を区別できないと、空判定が元ファイル側を見る回帰が素通りする。
  check "陽性1: requestsがpipで実際にインストールされている" \
    podman run --rm "$POS1_IMAGE" python3 -c 'import requests'
else
  check "陽性1: 正規化済みrequirementsでビルド成功 (staging failed: see stderr above)" false
  check "陽性1: requestsがpipで実際にインストールされている" false
fi
podman rmi "$POS1_IMAGE" 2>/dev/null
rm -rf "$POS1_PROJECT_DIR" "$POS1_CONTEXT_DIR"
log ""

# 同梱 default の opt-out と project pin（c3c 第2b-2段階）。stage_common_context() が置く default を
# 呼び出し側で上書きして、Dockerfile.claude が「空 = 導入しない」「npm 不在 = 失敗」「pin 優先」を
# 実際に守ることを実ビルドで確認する（--no-cache は付けない: 変更した COPY より前のレイヤーは
# 上のビルドのキャッシュを流用し、変更したファイル以降だけ実走する）。check_fails() の定義より後に
# 置く — 定義より前で呼ぶと command not found（rc 127）が check の集計に乗らず、検査が黙って抜ける
# （初回の全体実行で実測）。
log "## node-version.txt / codex-version.txt の opt-out と project pin（実ビルド）"
# 陰性: codex-version.txt が空 → Codex CLI を導入しない（Node は default のまま入る）。
OPTOUT_IMAGE="localhost/claude-test-codex-optout"
OPTOUT_CONTEXT_DIR="$(mktemp -d)"
if stage_common_context "$OPTOUT_CONTEXT_DIR"; then
  cp "${SCRIPT_DIR}/packages.txt" "$OPTOUT_CONTEXT_DIR/packages.txt"
  cp "${SCRIPT_DIR}/requirements.txt" "$OPTOUT_CONTEXT_DIR/requirements.txt"
  : > "$OPTOUT_CONTEXT_DIR/codex-version.txt"
  check "Codex opt-out: 空の codex-version.txt でビルド成功" podman build \
    -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$OPTOUT_IMAGE" "$OPTOUT_CONTEXT_DIR"
  check "Codex opt-out: codex が入っていない" \
    podman run --rm --network=none "$OPTOUT_IMAGE" sh -c '! command -v codex >/dev/null && [ ! -e /usr/local/bin/codex ] && [ ! -e /usr/local/libexec/c3c/codex-bwrap ]'
  # shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
  check "Codex opt-out: Node は同梱 default のまま入っている" \
    bash -c '[ "$(podman run --rm --network=none "$1" node --version)" = "v$2" ]' _ "$OPTOUT_IMAGE" "$DEFAULT_NODE_VERSION"
else
  check "Codex opt-out: 空の codex-version.txt でビルド成功 (staging failed: see stderr above)" false
  check "Codex opt-out: codex が入っていない" false
  check "Codex opt-out: Node は同梱 default のまま入っている" false
fi
podman rmi "$OPTOUT_IMAGE" 2>/dev/null
rm -rf "$OPTOUT_CONTEXT_DIR"

# 陰性: node-version.txt が空で Codex が有効、ベース（debian:stable、packages.txt も空）に npm が無い
# → 既存どおり npm 不在のエラーでビルド失敗（黙って Codex を落とさない）。
NPMLESS_IMAGE="localhost/claude-test-npmless"
NPMLESS_CONTEXT_DIR="$(mktemp -d)"
if stage_common_context "$NPMLESS_CONTEXT_DIR"; then
  cp "${SCRIPT_DIR}/packages.txt" "$NPMLESS_CONTEXT_DIR/packages.txt"
  cp "${SCRIPT_DIR}/requirements.txt" "$NPMLESS_CONTEXT_DIR/requirements.txt"
  : > "$NPMLESS_CONTEXT_DIR/node-version.txt"
  check_fails "Node opt-out + Codex 有効 + npm 無し base でビルド fail" "npm が必要" \
    podman build -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$NPMLESS_IMAGE" "$NPMLESS_CONTEXT_DIR"
else
  check "Node opt-out + Codex 有効 + npm 無し base でビルド fail (staging failed: see stderr above)" false
fi
podman rmi "$NPMLESS_IMAGE" 2>/dev/null
rm -rf "$NPMLESS_CONTEXT_DIR"

# 陽性: project の node-version.txt の pin が default より優先される（Codex は default のまま）。
PIN_NODE_VERSION="22.14.0"
PIN_IMAGE="localhost/claude-test-node-pin"
PIN_PROJECT_DIR="$(mktemp -d)"
PIN_CONTEXT_DIR="$(mktemp -d)"
mkdir -p "$PIN_PROJECT_DIR/.c3c"
printf '%s\n' "$PIN_NODE_VERSION" > "$PIN_PROJECT_DIR/.c3c/node-version.txt"
if stage_common_context "$PIN_CONTEXT_DIR"; then
  cp "${SCRIPT_DIR}/packages.txt" "$PIN_CONTEXT_DIR/packages.txt"
  cp "${SCRIPT_DIR}/requirements.txt" "$PIN_CONTEXT_DIR/requirements.txt"
  cp "$PIN_PROJECT_DIR/.c3c/node-version.txt" "$PIN_CONTEXT_DIR/node-version.txt"
  check "project pin: node-version.txt の pin でビルド成功" podman build \
    -f "${SCRIPT_DIR}/Dockerfile.claude" -t "$PIN_IMAGE" "$PIN_CONTEXT_DIR"
  # shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
  check "project pin: node --version が pin（v$PIN_NODE_VERSION）と一致し default ではない" \
    bash -c 'actual=$(podman run --rm --network=none "$1" node --version) && echo "$actual" && [ "$actual" = "v$2" ] && [ "$actual" != "v$3" ]' _ "$PIN_IMAGE" "$PIN_NODE_VERSION" "$DEFAULT_NODE_VERSION"
  # shellcheck disable=SC2016  # 検証式は親で展開せず、位置引数を子シェル内で評価する
  check "project pin: Codex は同梱 default のまま入っている" \
    bash -c '[ "$(podman run --rm --network=none "$1" codex --version)" = "codex-cli $2" ]' _ "$PIN_IMAGE" "$DEFAULT_CODEX_VERSION"
else
  check "project pin: node-version.txt の pin でビルド成功 (staging failed: see stderr above)" false
  check "project pin: node --version が pin（v$PIN_NODE_VERSION）と一致し default ではない" false
  check "project pin: Codex は同梱 default のまま入っている" false
fi
podman rmi "$PIN_IMAGE" 2>/dev/null
rm -rf "$PIN_PROJECT_DIR" "$PIN_CONTEXT_DIR"
log ""

log "## .claude-container.d/env の非混入確認（ランタイム設定はビルド時に焼き込まない）"
# 模倣コピーではなく c3c 本体の stage_build_context() を実際に実行させて
# 検証する。podman をダミー化し「イメージ未ビルド」を常に返させることでビルド分岐に
# 入らせ、実際のステージング結果（.build-context/<project>/）に env が無いことを見る。
# こうすることで、本体のステージングループが将来ワイルドカード化されるリグレッションを
# 実地で検出できる（コピー処理を模倣するだけのテストは本体が壊れても検知できない）。
ENV_TESTROOT="$(mktemp -d)"
mkdir -p "$ENV_TESTROOT/bin"
cat > "$ENV_TESTROOT/bin/podman" <<'DUMMY'
#!/bin/bash
case "$1" in
  image) [[ "$2" == "exists" ]] && exit 1 ;;
esac
exit 0
DUMMY
chmod +x "$ENV_TESTROOT/bin/podman"

ENV_PROJECT_DIR="$ENV_TESTROOT/proj"
mkdir -p "$ENV_PROJECT_DIR/.claude-container.d"
echo "[user]
	name = dummy" > "$ENV_TESTROOT/dummy-gitconfig"
echo "GITCONFIG_FILE=$ENV_TESTROOT/dummy-gitconfig" > "$ENV_PROJECT_DIR/.claude-container.d/env"

BEFORE_BUILD_CONTEXTS="$(ls -1 "${SCRIPT_DIR}/.build-context/" 2>/dev/null || true)"
# 他のランチャーテストと同じく env -i で隔離する。隔離しないと record_project_in_ledger() が
# 実ユーザーの $HOME の起動台帳に一時パスを 1 行残す（claude-container#59）。
env -i HOME="$ENV_TESTROOT" PATH="$ENV_TESTROOT/bin:$PATH" "${SCRIPT_DIR}/c3c" claude "$ENV_PROJECT_DIR" >/dev/null 2>&1
AFTER_BUILD_CONTEXTS="$(ls -1 "${SCRIPT_DIR}/.build-context/" 2>/dev/null || true)"
NEW_BUILD_CONTEXT="$(comm -13 <(echo "$BEFORE_BUILD_CONTEXTS" | sort) <(echo "$AFTER_BUILD_CONTEXTS" | sort) | head -1)"

if [[ -n "$NEW_BUILD_CONTEXT" ]]; then
  check ".claude-container.d/env がビルドコンテキストに含まれない" \
    bash -c "[[ ! -e '${SCRIPT_DIR}/.build-context/${NEW_BUILD_CONTEXT}/env' ]]"
  rm -rf "${SCRIPT_DIR}/.build-context/${NEW_BUILD_CONTEXT}"
else
  check ".claude-container.d/env がビルドコンテキストに含まれない" false
fi

# 起動台帳は隔離 HOME 側に書かれ、実台帳（実ユーザーの ~/.local/state）には触れない（claude-container#59）
check "起動台帳の記録が隔離 HOME に閉じる" grep -qxF -- "$ENV_PROJECT_DIR" "$ENV_TESTROOT/.local/state/claude-container/projects"

rm -rf "$ENV_TESTROOT"
log ""

run_config_ro_tests
run_launcher_tests

log "## TZ"
check "date (UTC確認)"   podman run --rm "$IMAGE" date
log ""

log "## bash history 永続化確認（手動）"
log "  以下を順番に実行してください："
log "  1. mkdir -p /tmp/test-claude-history"
log "  2. podman run --rm -it --userns=keep-id -v /tmp/test-claude-history:/workspace/.claude ${IMAGE} bash"
log "  3. コンテナ内で任意のコマンドを実行（例: ls, echo hello）"
log "  4. exit でコンテナを終了"
log "  5. cat /tmp/test-claude-history/bash_history で履歴を確認"
log ""

finish_by_result
