#!/bin/sh
# validate-build-input.sh — packages.txt / requirements.txt のビルド時インジェクション対策検証と
#                           GitHub meta のスナップショットの検査
#
# 使い方: validate-build-input.sh <kind> <infile> [outfile]
#   kind    : packages | requirements
#             | github-meta（outfile を取らない。GitHub meta のスナップショットの検査、#238）
#   infile  : 検証対象（正規化前）
#   outfile : 省略時は正規化結果を書き出さない（--check 用の dry-run）
#
# 終了コード:
#   0 : 全行が仕様に適合（outfile 指定時は正規化結果を書き出し済み）
#   1 : 仕様に適合しない行がある（該当行を stderr へ提示済み。outfile は変更しない）
#   2 : 診断不能（引数不正・infile が読めない・infile と outfile が同一パス・
#       outfile のディレクトリへ一時ファイルを作れない・作業用一時ディレクトリを
#       作れない・内部エラー。outfile は変更しない）
#
# 責務は正規化と照合のみ。インストール・ネットワークアクセスは行わない。
# ビルド時（Dockerfile.claude の RUN）・起動前診断（--check）・テスト（test-build.sh）
# の3者が同じスクリプトを呼ぶ（#34）。
# github-meta は照合だけで正規化しない。c3c の stage_build_context()・test-build.sh の
# stage_common_context()・Dockerfile.claude の RUN が呼ぶ。規則は init-firewall.sh の
# load_github_ranges() と同じで、一致は tests/test-github-meta-agreement.sh が確かめる。

set -e
export LC_ALL=C

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: validate-build-input.sh <kind> <infile> [outfile]" >&2
  exit 2
fi

VBI_KIND="$1"
VBI_INFILE="$2"
VBI_OUTFILE="${3:-}"

case "$VBI_KIND" in
  packages)
    VBI_RE='^[a-z0-9][a-z0-9+.-]*[a-z0-9+]$'
    ;;
  requirements)
    VBI_RE='^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._-]+(,[A-Za-z0-9._-]+)*\])?((==|!=|<=|>=|<|>|~=|===)[A-Za-z0-9.*+!]+(,(==|!=|<=|>=|<|>|~=|===)[A-Za-z0-9.*+!]+)*)?$'
    ;;
  github-meta)
    if [ "$#" -eq 3 ]; then
      echo "error: github-meta は outfile を取りません" >&2
      exit 2
    fi
    ;;
  *)
    echo "error: 未知の kind です: $VBI_KIND（packages・requirements・github-meta を想定）" >&2
    exit 2
    ;;
esac

if [ -n "$VBI_OUTFILE" ] && [ "$VBI_INFILE" = "$VBI_OUTFILE" ]; then
  echo "error: infile と outfile に同じパスは指定できません" >&2
  exit 2
fi

if [ ! -f "$VBI_INFILE" ] || [ ! -r "$VBI_INFILE" ]; then
  echo "error: infile を読めません: $VBI_INFILE" >&2
  exit 2
fi

VBI_TMPDIR=$(mktemp -d) || exit 2
trap 'rm -rf "$VBI_TMPDIR"' EXIT

# NUL バイト検出は正規化・照合より前に行う（実装制約6）。判定手段自体が NUL を
# 落とさないこと — バイト数の比較（tr -d '\000' で NUL を除いた長さと元の長さ）
# なら、GNU grep の NUL 分割やシェル変数の切り詰めを経由しない。
VBI_TOTAL_BYTES=$(wc -c < "$VBI_INFILE") || exit 2
tr -d '\000' < "$VBI_INFILE" > "$VBI_TMPDIR/nonul" || exit 2
VBI_NONUL_BYTES=$(wc -c < "$VBI_TMPDIR/nonul") || exit 2
if [ "$VBI_TOTAL_BYTES" -ne "$VBI_NONUL_BYTES" ]; then
  echo "error: $VBI_INFILE に NUL バイトが含まれています（拒否）" >&2
  exit 1
fi

if [ "$VBI_KIND" = "github-meta" ]; then
  # init-firewall.sh の load_github_ranges() の規則を jq に写したもの（#238）。
  # 単一の JSON オブジェクトで、web・api・git が文字列の配列。IPv4 らしい値は
  # どれも範囲内（オクテット 0〜255、プレフィックス /0〜/32、2 桁以上で先頭 0 は
  # 不可）で、1 件以上ある。split("\n") は init がコマンド置換の出力を行に分けるのに
  # 合わせる。init はコマンド置換で NUL を落として読むので、NUL を含む文字列は
  # 1 つでも拒否する（落とすと別の値になる値を読み飛ばして init より緩くしない）。
  if ! command -v jq >/dev/null 2>&1; then
    echo "error: jq がありません" >&2
    exit 2
  fi
  VBI_JQ_RC=0
  jq -se '
    def ipv4: test("^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}(/[0-9]{1,2})?$");
    def part($max): (length == 1 or (startswith("0") | not)) and (tonumber <= $max);
    length == 1 and (.[0] | type == "object")
    and ([.[0].web, .[0].api, .[0].git] | all(type == "array" and all(.[]; type == "string" and (explode | all(. != 0)))))
    and ([.[0].web[], .[0].api[], .[0].git[] | split("\n")[] | select(ipv4)]
         | length >= 1
           and all(split("/") as $p
                   | ($p[0] | split(".") | all(part(255)))
                     and ($p[1] == null or ($p[1] | part(32)))))
  ' "$VBI_INFILE" >/dev/null 2>&1 || VBI_JQ_RC=$?
  # jq の終了コード: 0 = 適合、1 = 結果が false・null、2・5 = 入力を解析できない
  # （jq 1.6 は 2、1.7 以降は 5）。それ以外（3 = 式の誤りなど）は診断不能。
  case "$VBI_JQ_RC" in
    0)
      exit 0
      ;;
    1|2|5)
      echo "error: $VBI_INFILE は GitHub meta のスナップショットとして不正です" >&2
      exit 1
      ;;
    *)
      echo "error: GitHub meta の検査に失敗しました（jq rc=$VBI_JQ_RC）" >&2
      exit 2
      ;;
  esac
fi

VBI_NORM_TMP="$VBI_TMPDIR/norm"
VBI_BAD_TMP="$VBI_TMPDIR/bad"

# CR は実バイトを式へ埋め込む（実装制約3。\r エスケープは GNU sed 拡張で
# BSD sed では通らない）。
VBI_CR=$(printf '\r')

# 正規化は単一 sed コマンドで中間ファイルへ書き出す（実装制約9）。
# trim は [[:blank:]] に限定する（実装制約4）。
if [ "$VBI_KIND" = "packages" ]; then
  # 行末 CR 除去 → trim(行頭/行末) → # 始まりの行を除外 → 空行を除外
  # （行内 # は剥がさない — 「1行1パッケージ」仕様に忠実）
  sed \
    -e "s/${VBI_CR}\$//" \
    -e 's/^[[:blank:]]*//' \
    -e 's/[[:blank:]]*$//' \
    -e '/^#/d' \
    -e '/^$/d' \
    "$VBI_INFILE" > "$VBI_NORM_TMP"
else
  # 行内 # 以降を剥がす → 行末 CR 除去 → trim(行頭/行末) → 空行を除外
  # （空白の全除去はしない）
  sed \
    -e 's/#.*//' \
    -e "s/${VBI_CR}\$//" \
    -e 's/^[[:blank:]]*//' \
    -e 's/[[:blank:]]*$//' \
    -e '/^$/d' \
    "$VBI_INFILE" > "$VBI_NORM_TMP"
fi

if [ ! -s "$VBI_NORM_TMP" ]; then
  # 正規化結果が空 = 全行がコメント・空行のみで除外された。
  # 照合対象が無いため exit 0、outfile は空のまま確定する。
  if [ -n "$VBI_OUTFILE" ]; then
    VBI_OUTDIR=$(dirname "$VBI_OUTFILE")
    VBI_CONFIRM=$(mktemp "$VBI_OUTDIR/.vbi-confirmXXXXXX") || exit 2
    mv -f "$VBI_CONFIRM" "$VBI_OUTFILE" || exit 2
  fi
else
  # 照合。grep -Ev の終了コードは 0/1/2以上 の3分岐で扱う（実装制約10・11）。
  # `rc=0; grep ... || rc=$?` の形にする — `grep -Ev` は set -e 下で正常時
  # （不一致行なし）に exit 1 を返すため、素の `grep ...; rc=$?` では
  # `rc=$?` へ到達する前にシェルが終了してしまう。
  VBI_GREP_RC=0
  grep -Ev "$VBI_RE" "$VBI_NORM_TMP" > "$VBI_BAD_TMP" || VBI_GREP_RC=$?

  if [ "$VBI_GREP_RC" -eq 0 ]; then
    # 不一致行が見つかった = 仕様に適合しない行がある。
    # 提示にパイプを使わない（実装制約12）。不可視文字を可視化する
    # （実装制約13。cat -A の可搬性を避け POSIX の sed -n l を使う）。
    echo "error: $VBI_INFILE に仕様外の行があります（不可視文字は下記で可視化）:" >&2
    sed -n l "$VBI_BAD_TMP" >&2
    exit 1
  elif [ "$VBI_GREP_RC" -ne 1 ]; then
    echo "error: 照合に失敗しました（grep rc=$VBI_GREP_RC）" >&2
    exit 2
  fi

  # grep rc=1: 不一致行なし = 全行が仕様に適合。
  if [ -n "$VBI_OUTFILE" ]; then
    # outfile は成功時にのみ確定させる。outfile と同じディレクトリに
    # mktemp してから mv -f で置く（原子性・シンボリックリンク非追従のため）。
    VBI_OUTDIR=$(dirname "$VBI_OUTFILE")
    VBI_CONFIRM=$(mktemp "$VBI_OUTDIR/.vbi-confirmXXXXXX") || exit 2
    cp "$VBI_NORM_TMP" "$VBI_CONFIRM" || exit 2
    mv -f "$VBI_CONFIRM" "$VBI_OUTFILE" || exit 2
  fi
fi
