#!/bin/bash
# c3c のエグレス制限。既定で外向きの通信を拒否し、次の宛先だけを許可リストとして通す。
#   - loopback と、確立済みの接続への応答
#   - /etc/resolv.conf にある IPv4 のリゾルバへの DNS（udp と tcp の 53 番）
#   - GitHub の範囲（ビルド時にイメージへ焼き込んだ /etc/c3c/github-meta.json）
#   - Claude Code のエンドポイントと、/etc/c3c/allowed-domains.txt のドメインの A レコード
#   - ホスト側のゲートウェイ 1 つ（/32）
# GitHub とドメインへの許可は、専用チェーンを通して /etc/c3c/allowed-ports.txt の
# ポート（既定 443,22、#31）に限る。DNS とゲートウェイはチェーンを通らず、ポートを限らない。
# 許可は CIDR ごとに 1 本の iptables ルールで持つ。rootless podman のコンテナからは
# ホストの ip_set モジュールを読み込めないため、ipset に頼らない。
# IPv6 は既定で loopback 以外をすべて遮断する。--ipv6 のときだけ ipv6-firewall.py が
# AAAA と IPv6 の CIDR から同じ形の許可リストを作る。
# ドメイン由来のルールには世代タグを付け（add_cidr_tagged）、--refresh-domains モードが
# 全消去なしに IP の入れ替わりへ追随する。CDN では A レコードの一式が十数秒ごとに
# 入れ替わることがある（2026-07、CloudFront 経由の cyberjapandata.gsi.go.jp で観測）。
# entrypoint.sh が sudo で root として起動する。init モードは fail-closed で、途中で
# 失敗すればコンテナの起動を止める（C3C_NO_FIREWALL=1 で無効化できる）。
# --refresh-domains モード（末尾）は起動時の関門ではない定期の手直しなので、fail-open で動く。
set -euo pipefail
IFS=$'\n\t'

ALLOWED_DOMAINS_FILE=/etc/c3c/allowed-domains.txt
ALLOWED_PORTS_FILE=/etc/c3c/allowed-ports.txt
CHAIN=CLAUDE_EGRESS
readonly IPV6_HELPER=/usr/local/bin/ipv6-firewall.py
# 観測された最短の CDN TTL は 13 秒。それよりやや遅く更新することで、1 回の取りこぼしを
# 毎回の揺らぎを追いかけるのではなく次のサイクルで拾えるようにする。
# sleep 自体は firewall-refresh.py の更新ループ側にある — 両者を同期させておくこと。
# ここでの定数は、下の猶予期間のサイズを決めるためのもの。
REFRESH_INTERVAL_SECONDS=15
# 更新サイクル 12 回分の猶予: CDN が 1 回のクエリで稼働中エッジ IP の一部しか
# 返さなかった場合や、一時的なリゾルバの不調を吸収してから、
# 使われなくなったドメインの IP をようやく削除する。
GRACE_WINDOW_SECONDS=$((REFRESH_INTERVAL_SECONDS * 12))
# IPv6 helper の GRACE_SECONDS=180 と同期させる。

MODE=init
IPV6_ENABLED=0
for option in "$@"; do
  case "$option" in
    --refresh-domains) MODE=refresh ;;
    --ipv6) IPV6_ENABLED=1 ;;
    *) echo "ERROR: 未知の引数です: $option（--refresh-domains / --ipv6 を想定）" >&2; exit 1 ;;
  esac
done

# CHAIN 経由の ACCEPT ルール（下の add_cidr/add_cidr_tagged）が、それ以外は許可された
# IP に対して許可するポート（#31）。init モードと --refresh-domains モードの
# 両方が同じ値を見るよう、ここで一度だけ読む。DNS リゾルバのルールや full_init() の
# ホストネットワークのルールには適用されない — それらは CHAIN を完全にバイパスし、
# 制限なしのままとなる（CHAIN 作成箇所のコメントを参照）。
resolve_allowed_ports() {
  local -a ports=()
  local raw lo hi
  if [ -f "$ALLOWED_PORTS_FILE" ]; then
    # `|| [ -n "$raw" ]` により、末尾に改行のない最終行も読む
    # （read はその行で非 0 を返すが変数は埋まっている。これがないと
    # 最終エントリが黙って落ちていた — #49）。
    while IFS= read -r raw || [ -n "$raw" ]; do
      raw="${raw%%#*}"
      raw="$(printf '%s' "$raw" | tr -d '[:space:]')"
      [ -n "$raw" ] || continue
      if [[ ! "$raw" =~ ^[0-9]{1,5}(:[0-9]{1,5})?$ ]]; then
        echo "ERROR: $ALLOWED_PORTS_FILE に不正なエントリがあります: '$raw'（ポート番号か port:port の範囲を想定。例: 443、8000:8010）" >&2
        exit 1
      fi
      # 書式を確認してから十進数として評価する。単一値は lo == hi になる。
      lo=$((10#${raw%%:*})); hi=$((10#${raw##*:}))
      if (( lo < 1 || lo > 65535 || hi < 1 || hi > 65535 )); then
        echo "ERROR: $ALLOWED_PORTS_FILE に不正なエントリがあります: '$raw'（ポート番号は範囲の両端も含め1〜65535）" >&2
        exit 1
      fi
      if [[ "$raw" == *:* ]] && (( lo >= hi )); then
        echo "ERROR: $ALLOWED_PORTS_FILE に不正なエントリがあります: '$raw'（開始ポートは終了ポートより小さくしてください。同じ場合は単一ポートで指定。例: 443:443 ではなく 443）" >&2
        exit 1
      fi
      # iptables は先頭0を八進数として読むため、検証した十進値を渡す。
      if [[ "$raw" == *:* ]]; then
        ports+=("$lo:$hi")
      else
        ports+=("$lo")
      fi
    done < "$ALLOWED_PORTS_FILE"
  fi
  if [ "${#ports[@]}" -eq 0 ]; then
    ports=(443 22)
  fi
  # multiport の内部枠数は単一値が1、範囲が2（両端の値）。範囲内のポート数ではない。
  local entry port_slots=${#ports[@]}
  for entry in "${ports[@]}"; do
    if [[ "$entry" == *:* ]]; then port_slots=$((port_slots + 1)); fi
  done
  if [ "$port_slots" -gt 15 ]; then
    echo "ERROR: $ALLOWED_PORTS_FILE の許可ポートは換算すると $port_slots 枠あります。iptables の multiport マッチは最大 15 枠です（単一ポートは1枠、範囲は2枠）" >&2
    exit 1
  fi
  # full_init() の起動時自己検証は、api.github.com への 443 番が到達可能で
  # 80 番が遮断されていることを前提にしている。どちらかに反する設定は、以前は
  # そこで「ネットワークの問題」に見えるメッセージ（"unable to reach ...:443"）や
  # 「ルールが壊れている」ように見えるメッセージ（"port restriction not enforced"）で
  # 失敗していたため、ここで本当の理由とともに検証する（#49）。
  # 範囲は両端を含む。入力値は上で先頭ゼロのない十進表記へ正規化済み。
  local has_443=0 has_80=0
  for entry in "${ports[@]}"; do
    lo="${entry%%:*}"; hi="${entry##*:}"
    if (( lo <= 443 && 443 <= hi )); then has_443=1; fi
    if (( lo <= 80 && 80 <= hi )); then has_80=1; fi
  done
  if [ "$has_443" -eq 0 ]; then
    echo "ERROR: $ALLOWED_PORTS_FILE には 443 を含める必要があります（api.anthropic.com・api.github.com への到達と起動時の自己検証に必要）" >&2
    exit 1
  fi
  if [ "$has_80" -eq 1 ]; then
    echo "ERROR: $ALLOWED_PORTS_FILE では 80 番を許可できません（起動時の自己検証が api.github.com:80 を遮断確認のプローブに使う）" >&2
    exit 1
  fi
  local IFS=,
  ALLOWED_PORTS="${ports[*]}"
}
resolve_allowed_ports

# 世代タグなしの、素の CIDR ごとの ACCEPT。短い TTL で入れ替わらない範囲
# （GitHub のビルド時スナップショット）に使い、削除の必要がない。
add_cidr() {
  local cidr="$1" origin="$2"
  if [[ ! "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(/[0-9]{1,2})?$ ]]; then
    echo "$origin の IPv4 以外の範囲をスキップします: $cidr"
    return 0
  fi
  iptables -A "$CHAIN" -d "$cidr" -p tcp -m multiport --dports "$ALLOWED_PORTS" -j ACCEPT
}

# add_cidr と同じだが、ルールにドメインと世代のタグを付け、
# prune_stale_domain_rules() が後で見つけて期限切れにできるようにする。下の
# ドメインごとの動的解決ループでのみ使い、GitHub の CIDR やホストネットワークの
# ルール（どちらも短い TTL では入れ替わらない）には使わない。
add_cidr_tagged() {
  local cidr="$1" domain="$2" generation="$3"
  if [[ ! "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(/[0-9]{1,2})?$ ]]; then
    echo "$domain の IPv4 以外の範囲をスキップします: $cidr"
    return 0
  fi
  if [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo "ERROR: 安全でないドメイン文字列のため、ルールにタグを付けられません: $domain" >&2
    return 1
  fi
  local comment="domain=${domain};gen=${generation}"
  # xt_comment は終端NULを含め256バイト。libxtables は超過を黙って切り詰める。
  # 世代タグの破損で更新・期限切れ削除が崩れないよう、適用前に拒否する。
  if [[ ${#comment} -gt 255 ]]; then
    echo "ERROR: ドメインの世代タグが iptables comment の上限255バイトを超えます: $domain" >&2
    return 1
  fi
  iptables -A "$CHAIN" -d "$cidr" -p tcp -m multiport --dports "$ALLOWED_PORTS" -m comment --comment "$comment" -j ACCEPT
}

# (domain, ip) の組に対して新しいタグ付きルールを追加する。その組にちょうど
# 一致するルールが既にあれば古い方を削除し、世代タグだけが実質的に「前進」し、
# 更新のたびに重複が積み重ならないようにする。新ルールは古いルールを削除する
# *前*に追加するので、その間 IP は許可されたままになる — フラッシュもギャップもない。
# 注記: `iptables -S` が素のホストを "-d IP/32" として描画すること、先頭の
# "-N CHAIN" 行を除いた後の grep の 1 始まりの一致行番号が、
# `iptables -D CHAIN <N>` に渡すルールの位置と一致することを前提にしている。
# 実測で確認済み（iptables 1.8.11/nf_tables）: -S は add_cidr* の呼び出しで
# 渡した順序に関わらず、常にコアフィールド（-A CHAIN -d IP/32 -p ...）を
# マッチ拡張フラグ（-m multiport、-m comment）より先に出力するため、下の
# "-d ${ip}/32 " での grep は、add_cidr_tagged にポート制限（#31）を
# 追加した後も一致し続ける。
add_or_touch_domain_ip() {
  local ip="$1" domain="$2" generation="$3"
  local existing_idx="" rules listing_failed=0
  if rules=$(iptables -S "$CHAIN"); then
    existing_idx=$(printf '%s\n' "$rules" | tail -n +2 | \
      grep -nF -- "-d ${ip}/32 " | grep -F "domain=${domain};" | \
      cut -d: -f1 | head -n1 || true)
  else
    listing_failed=1
  fi
  add_cidr_tagged "$ip" "$domain" "$generation" || return 1
  # 一覧取得に失敗しても従来どおり新しい IP の追加は試すが、成功扱いにしない。
  # 失敗した一覧の部分出力から行番号を選んで削除しない。
  if [[ "$listing_failed" == 1 ]]; then
    echo "WARNING: $CHAIN の旧ルール一覧を取得できませんでした" >&2
    return 1
  fi
  if [ -n "$existing_idx" ]; then
    iptables -D "$CHAIN" "$existing_idx"
  fi
}

# Claude Code のエンドポイントとプロジェクト固有のドメイン、1 行に 1 つ。
build_domain_list() {
  local LC_ALL=C raw domain label line=0
  local -a labels domains=()
  local -a base_domains=(
    api.anthropic.com
    claude.ai
    console.anthropic.com
    statsig.anthropic.com
    statsig.com
    sentry.io
  )
  if [[ -e "$ALLOWED_DOMAINS_FILE" || -L "$ALLOWED_DOMAINS_FILE" ]]; then
    if [[ ! -f "$ALLOWED_DOMAINS_FILE" || ! -r "$ALLOWED_DOMAINS_FILE" ]]; then
      printf 'ERROR: 許可ドメインファイルを読めません: %s\n' "$ALLOWED_DOMAINS_FILE" >&2
      return 1
    fi
    # 通常の read は NUL を捨てるため、NUL 区切りの read で先に検出する。
    if IFS= read -r -d '' raw < "$ALLOWED_DOMAINS_FILE"; then
      printf 'ERROR: %s に NUL バイトが含まれています\n' "$ALLOWED_DOMAINS_FILE" >&2
      return 1
    fi
    while IFS= read -r raw || [[ -n "$raw" ]]; do
      line=$((line + 1))
      raw="${raw%$'\r'}"
      raw="${raw#"${raw%%[![:blank:]]*}"}"
      raw="${raw%"${raw##*[![:blank:]]}"}"
      [[ -n "$raw" && "$raw" != \#* ]] || continue
      domain="${raw%.}"
      if [[ ${#domain} -gt 253 || "$domain" == *..* ||
            ! "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
        printf 'ERROR: %s:%d: 不正なホスト名です: %q（1行1ホスト名、ASCII英数字・ハイフン・ドット、末尾ドットを除き最大253文字）\n' "$ALLOWED_DOMAINS_FILE" "$line" "$raw" >&2
        return 1
      fi
      IFS=. read -r -a labels <<< "$domain"
      for label in "${labels[@]}"; do
        if [[ ! "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]]; then
          printf 'ERROR: %s:%d: 不正なラベルです: %q（各ラベルは1〜63文字、先頭・末尾は英数字）\n' "$ALLOWED_DOMAINS_FILE" "$line" "$raw" >&2
          return 1
        fi
      done
      domains+=("$raw")
    done < "$ALLOWED_DOMAINS_FILE"
  fi
  # 全行の検証後にだけ出力し、不正行より前のリストを部分適用させない。
  printf '%s\n' "${base_domains[@]}" "${domains[@]}"
}

# 許可された全ドメインを解決し、返ってきた IP それぞれに add_or_touch_domain_ip を
# 適用する。1 つのドメインの解決失敗は他を中断させない（この層では fail-open）
# — 戻り値が非 0 であることの意味は呼び出し側が決める: full_init はそれを
# 致命的として扱い（fail-closed の起動ゲート）、do_refresh はログに残して次の
# サイクルで再試行する（fail-open のバックグラウンドの手直し）。
#
# NXDOMAIN（ドメイン自体が存在しない）は警告として扱い、失敗としない。一時的な失敗
# （タイムアウト・SERVFAIL・リゾルバ到達不能。これらは下で引き続きエラーとして
# 数える）とは区別する: どちらの場合も ACCEPT ルールは追加されないので
# セキュリティ境界は変わらないが、ここで致命的として扱うと、このスクリプトを
# 編集する以外に回復手段のないまま fail-closed の起動ゲートが永久に詰まってしまう。
refresh_domains() {
  local generation="$1" had_errors=0 domain ips ip dig_output domain_list
  local -a domains
  # process substitution では生成側の終了コードが mapfile に伝わらない。
  domain_list=$(build_domain_list) || return 1
  mapfile -t domains <<< "$domain_list"
  for domain in "${domains[@]}"; do
    echo "$domain を解決しています..."
    # +comments（+answer に加えて）によりヘッダの "status:" 行
    # （NOERROR/NXDOMAIN/SERVFAIL/…）が同じ 1 回の dig 呼び出しで見えるため、
    # 2 回目の往復なしで下の一時的な失敗と NXDOMAIN を区別できる。`|| true`:
    # dig 自体は、応答を見る前の一時的な失敗（例: サーバーに到達できない）で
    # 非 0 終了することがある。`set -o pipefail` の下ではそれが `set -e` を
    # 発動させ、下の had_errors の処理が走る前にこのスクリプト全体を
    # 中断させてしまう。
    dig_output=$(dig +noall +answer +comments +time=2 +tries=2 A "$domain" || true)
    ips=$(printf '%s\n' "$dig_output" | awk '$4 == "A" {print $5}')
    if [ -z "$ips" ]; then
      if [[ "${IPV6_ENABLED:-0}" == 1 && "$dig_output" =~ status:\ NOERROR ]]; then
        # 併用モードでは AAAA のみのホストも正常。IPv6側を後で確認する。
        :
      elif [[ "$dig_output" =~ status:\ NXDOMAIN ]]; then
        echo "WARNING: $domain は存在しません（NXDOMAIN）。起動は失敗させずにスキップします（いずれにせよ ACCEPT ルールは追加しません）" >&2
      else
        echo "WARNING: $domain をこのサイクルで解決できませんでした（次の間隔で再試行します）" >&2
        had_errors=1
      fi
      continue
    fi
    while read -r ip; do
      # DNS の sinkhole 応答や loopback はドメイン由来の許可に使わない（#53）。
      # private/link-local は内部ホストの明示的な許可に使えるため変更しない。
      # 既存の該当ルールは世代を更新せず、通常の猶予期間後に prune で除去する。
      case "$ip" in
        0.*|127.*)
          echo "WARNING: $domain -> $ip は特殊用途の IPv4 アドレスのためスキップします（0.0.0.0/8・127.0.0.0/8。ACCEPT ルールは追加・更新しません）" >&2
          continue
          ;;
      esac
      if ! add_or_touch_domain_ip "$ip" "$domain" "$generation"; then
        echo "WARNING: $domain -> $ip のルール適用に失敗しました" >&2
        had_errors=1
      fi
    done <<<"$ips"
  done
  if [[ "${IPV6_ENABLED:-0}" == 1 ]]; then
    if ! printf '%s\n' "${domains[@]}" | "$IPV6_HELPER" refresh --ports "$ALLOWED_PORTS" --generation "$generation"; then
      had_errors=1
    fi
  fi
  return "$had_errors"
}

# 世代が cutoff_epoch より古いドメインタグ付きルールを削除する。GitHub の
# CIDR ルールとホストネットワークのルールには "domain=" コメントがなく、
# ここで一致することはない。行番号の降順で削除する。`iptables -D CHAIN N` は
# N を削除するとそれ以降の全行の番号が詰まるため。
prune_stale_domain_rules() {
  local cutoff="$1" rules had_errors=0
  if ! rules=$(iptables -S "$CHAIN"); then
    echo "WARNING: $CHAIN の期限切れルール一覧を取得できませんでした" >&2
    return 1
  fi
  local -a stale_line_numbers=()
  local idx=0 line rule_gen
  while IFS= read -r line; do
    idx=$((idx + 1))
    if [[ "$line" =~ --comment\ \"domain=[^\;]+\;gen=([0-9]+)\" ]]; then
      rule_gen="${BASH_REMATCH[1]}"
      if (( rule_gen < cutoff )); then
        stale_line_numbers+=("$idx")
      fi
    fi
  done < <(printf '%s\n' "$rules" | tail -n +2)
  local n
  for (( n=${#stale_line_numbers[@]}-1; n>=0; n-- )); do
    if ! iptables -D "$CHAIN" "${stale_line_numbers[n]}" 2>/dev/null; then
      echo "WARNING: $CHAIN の ${stale_line_numbers[n]} 行目の古いルールを削除できませんでした" >&2
      had_errors=1
    fi
  done
  return "$had_errors"
}

# 禁止先へ届かず、許可先へ届くことを確かめる。どれか 1 つでも期待と違えば起動を止める。
# 宛先の名前ではなく IPv4 で確かめ、dual-stack の環境で IPv6 の成功が IPv4 の故障を隠さない
# ようにする。ほかの関数を呼ばない（tests/ が本体だけを抜き出して走らせる）。
# shellcheck disable=SC2016 # bash -c 内の位置引数は接続確認の子シェルで展開する。
verify_ipv4() {
  echo "ファイアウォールのルールを検証しています..."
  # api.github.com は TCP の接続だけを確かめ、HTTP のリクエストは送らない。
  # 起動のたびに未認証の GitHub API のレート制限を使わないため。
  local github_ipv4
  github_ipv4=$(dig +short +time=2 +tries=2 A api.github.com | awk '/^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/ { print; exit }')
  if [ -z "$github_ipv4" ]; then
    echo "ERROR: ファイアウォール検証に失敗しました。api.github.com:443 へ到達できません" >&2
    exit 1
  fi

  # 禁止先: 許可リストの外と、許可された IP の許可していないポート。
  if curl -q -4 --connect-timeout 5 --max-time 10 --retry 0 -s https://example.com >/dev/null 2>&1; then
    echo "ERROR: ファイアウォール検証に失敗しました。https://example.com へ到達できてしまいました" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり https://example.com へ到達できません（接続5秒・全体10秒上限）"
  # api.github.com は 80 番でも待ち受けている（HTTPS へのリダイレクト）ので、届かないのは
  # 相手の都合ではなく、こちらのポート制限（#31）が拒否したことを意味する。確かめられるのは
  # チェーンを通る許可（GitHub の範囲とドメイン）だけで、DNS とゲートウェイは対象外。
  if timeout 5 bash -c 'exec 3<>/dev/tcp/$1/$2' probe "$github_ipv4" 80 2>/dev/null; then
    echo "ERROR: ファイアウォール検証に失敗しました。api.github.com:80 へ到達できてしまいました（ポート制限が効いていません）" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり api.github.com:80 へ到達できません（ポート制限が有効）"

  # 許可先: GitHub の範囲と、Claude Code のエンドポイント。
  if ! timeout 10 bash -c 'exec 3<>/dev/tcp/$1/$2' probe "$github_ipv4" 443 2>/dev/null; then
    echo "ERROR: ファイアウォール検証に失敗しました。api.github.com:443 へ到達できません" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり api.github.com:443 へ到達できます"
  local curl_rc=0
  curl -q -4 --connect-timeout 10 --max-time 20 --retry 0 -sS -o /dev/null https://api.anthropic.com || curl_rc=$?
  if [ "$curl_rc" -ne 0 ]; then
    echo "ERROR: ファイアウォール検証に失敗しました。https://api.anthropic.com へ到達できません（curl rc=$curl_rc、接続10秒・全体20秒上限、再試行なし）" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり https://api.anthropic.com へ到達できます"
}

# ---- init モードの準備（ルールを変えない） ----
# 失敗しうる読み込みと検査は、最初の iptables -F より前に済ませる。ここで止まれば、
# 既存のルールには手を付けない。

# GitHub の範囲は起動のたびに API から取らない（未認証のレート制限は IP あたり 60 req/h）。
# c3c の stage_build_context() がビルド時に 1 回取得して焼き込んだスナップショットを読む。
# 範囲はめったに変わらないので、古い版でも使える。
readonly GITHUB_META_SNAPSHOT=/etc/c3c/github-meta.json
load_github_ranges() {
  local meta
  echo "ビルド時スナップショットから GitHub の IP 範囲を読み込んでいます..."
  meta=$(cat "$GITHUB_META_SNAPSHOT" 2>/dev/null || true)
  if ! printf '%s\n' "$meta" | jq -e '.web and .api and .git' >/dev/null 2>&1; then
    echo "ERROR: GitHub meta のスナップショット $GITHUB_META_SNAPSHOT がないか不正です" >&2
    exit 1
  fi
  mapfile -t GITHUB_CIDRS < <(printf '%s\n' "$meta" | jq -r '(.web + .api + .git)[]' | sort -u)
}

# ホスト側のサービスへは、デフォルトルートのゲートウェイ 1 つだけを通す（/24 全体ではない、#31）。
detect_host_gateway() {
  local gateway
  gateway=$(ip route | awk '/^default/ {print $3; exit}')
  if [ -z "$gateway" ]; then
    echo "ERROR: ホスト IP を検出できませんでした" >&2
    exit 1
  fi
  HOST_GATEWAY="${gateway}/32"
  echo "ホストネットワークを検出しました: $HOST_GATEWAY"
}

# ---- init モードのルールの構築 ----
# 各関数は失敗したルールの直後に set -e で止まる。条件（if・||・&&）の中から呼ぶと
# 関数の中の set -e が効かなくなるので、そう呼ばない。

# 既存のルールとユーザー定義のチェーンを消し、許可リストのチェーンを作り直す。
# -F は既定ポリシーを戻さないので、2 回目以降の実行では、ここから下でルールが揃うまで
# 通信が止まる。名前の解決が要る処理（ドメインの解決）より先に loopback・確立済み・DNS を
# 入れておくので、セッションの途中で手で実行し直しても、最悪で DNS だけが通る状態になり、
# 締め出されはしない。CDN の IP の入れ替わりへの追随は --refresh-domains が受け持つ。
reset_ipv4_rules() {
  local table
  for table in filter nat mangle; do
    if [ "$table" = filter ]; then
      iptables -F
      iptables -X
    else
      iptables -t "$table" -F
      iptables -t "$table" -X
    fi
  done
  # チェーンに置く ACCEPT は add_cidr/add_cidr_tagged が $ALLOWED_PORTS に限る（#31）。
  iptables -N "$CHAIN"
}

allow_loopback_and_established() {
  iptables -A INPUT -i lo -j ACCEPT
  iptables -A OUTPUT -o lo -j ACCEPT
  local chain
  for chain in INPUT OUTPUT; do
    iptables -A "$chain" -m state --state ESTABLISHED,RELATED -j ACCEPT
  done
}

# DNS の許可を udp と tcp（大きな応答用）の組で入れる。引数は宛先の指定（無ければ任意の宛先）。
allow_dns_to() {
  local proto
  for proto in udp tcp; do
    iptables -A OUTPUT "$@" -p "$proto" --dport 53 -j ACCEPT
  done
}

# DNS は設定済みのリゾルバだけへ通す。ドメインの解決がこれを使うので、その前に入れる。
allow_dns() {
  local -a resolvers
  local resolver
  mapfile -t resolvers < <(awk '/^nameserver/ {print $2}' /etc/resolv.conf | grep -E '^[0-9.]+$' || true)
  if [ "${#resolvers[@]}" -gt 0 ]; then
    for resolver in "${resolvers[@]}"; do
      allow_dns_to -d "$resolver"
    done
  elif [[ "$IPV6_ENABLED" == 1 ]]; then
    echo "INFO: IPv4 リゾルバなし。IPv6 の設定済みリゾルバのみ許可します"
  else
    echo "WARNING: /etc/resolv.conf に IPv4 リゾルバがないため、DNS を任意のホストへ許可します" >&2
    allow_dns_to
  fi
}

allow_github_ranges() {
  local cidr
  for cidr in "${GITHUB_CIDRS[@]}"; do
    add_cidr "$cidr" "GitHub meta"
  done
}

# ゲートウェイへの許可はチェーンを通らず、ポートを限らない。
allow_host_gateway() {
  iptables -A INPUT -s "$HOST_GATEWAY" -j ACCEPT
  iptables -A OUTPUT -d "$HOST_GATEWAY" -j ACCEPT
}

# 許可のルールが揃った後で既定を DROP にし、OUTPUT の残りを許可リストのチェーンへ渡す。
# チェーンに当たらなければ REJECT で即座に失敗を返す（DROP の待ちにしない）。
enforce_ipv4_default_deny() {
  local chain
  for chain in INPUT FORWARD OUTPUT; do
    iptables -P "$chain" DROP
  done
  iptables -A OUTPUT -j "$CHAIN"
  iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited
}

# 既定（IPv6 無効）の IPv6 は 3 段で扱う。
#   1) 主経路は compose.yml の sysctls（net.ipv6.conf.*.disable_ipv6=1）で、このスクリプトより
#      前に IPv6 が無効になっている。glibc の getaddrinfo(AI_ADDRCONFIG) が、デフォルトルートの
#      無いリンクローカルのアドレスだけで IPv6 を使えると判断し、Happy Eyeballs が許可済みの
#      CDN の届かない AAAA で詰まる不具合を防ぐ（2026-07、cyberjapandata.gsi.go.jp で観測）。
#   2) 予備として、sysctls が効かなかった場合（`sysctls:` を扱えない古い podman-compose など）に
#      /proc/sys から同じ無効化を試す。信頼性のための手直しで関門ではないので、失敗しても
#      警告だけにする（この関数だけ fail-closed の例外）。
#   3) 1) と 2) の結果に関わらず、lock_down_ipv6 が ip6tables で loopback 以外を遮断する。
#      許可リストは A レコードしか解決しないので、残った IPv6 の経路はそれを迂回できてしまう。
disable_ipv6_fallback() {
  local path ok=1
  for path in /proc/sys/net/ipv6/conf/*/disable_ipv6; do
    [ -e "$path" ] || continue
    echo 1 > "$path" 2>/dev/null || ok=0
  done
  [ "$ok" -eq 1 ]
}

report_ipv6_fallback() {
  if [[ "$IPV6_ENABLED" == 1 ]]; then
    echo "INFO: IPv6 は専用の許可リストで制限しています"
  elif disable_ipv6_fallback; then
    echo "/proc/sys 経由で IPv6 を無効化しました（フォールバック確認 OK。主経路は compose.yml の sysctls）"
  else
    echo "WARNING: /proc/sys/net/ipv6/conf/*/disable_ipv6 経由で IPv6 を無効化できませんでした（フォールバック）。" >&2
    echo "WARNING: compose.yml の sysctls も効いていない場合、glibc が許可済み CDN ドメインの AAAA を" >&2
    echo "WARNING: 優先し、Happy Eyeballs による断続的な失敗が起きる可能性があります。" >&2
    echo "WARNING: 下の ip6tables DROP が引き続き有効なセキュリティ境界です。" >&2
  fi
}

# --ipv6 のときは、prepare 済みの IPv6 の許可ルールを残す。
lock_down_ipv6() {
  [[ "$IPV6_ENABLED" == 1 ]] && return 0
  if ! ip6tables -L >/dev/null 2>&1; then
    echo "ip6tables が使えないため、IPv6 接続はないものとみなします"
    return 0
  fi
  ip6tables -F
  ip6tables -X
  ip6tables -A INPUT -i lo -j ACCEPT
  ip6tables -A OUTPUT -o lo -j ACCEPT
  local chain
  for chain in INPUT FORWARD OUTPUT; do
    ip6tables -P "$chain" DROP
  done
}

# 起動時の初期化。ルールをすべて作り直し、自己検証まで行う。fail-closed。
full_init() {
  load_github_ranges
  detect_host_gateway

  reset_ipv4_rules
  allow_loopback_and_established
  allow_dns
  if [[ "$IPV6_ENABLED" == 1 ]]; then
    "$IPV6_HELPER" prepare --ports "$ALLOWED_PORTS"
  fi
  allow_github_ranges
  # ドメインのルールには今の時刻を世代として付け、--refresh-domains が古いものを期限切れにする。
  # refresh_domains は 1 つのドメインの失敗で残りを止めない（失敗は戻り値で返す）ので、
  # ここで起動を止める判断をする。
  if ! refresh_domains "$(date +%s)"; then
    echo "ERROR: 初期ファイアウォール設定中に許可ドメインの検証・解決・ルール適用に失敗しました" >&2
    exit 1
  fi
  allow_host_gateway
  enforce_ipv4_default_deny
  report_ipv6_fallback
  lock_down_ipv6

  echo "ファイアウォールの設定が完了しました"
  verify_ipv4
  if [[ "$IPV6_ENABLED" == 1 ]]; then
    "$IPV6_HELPER" verify --ports "$ALLOWED_PORTS"
  fi
}

# 軽量な定期的手直し: 許可された全ドメインを再解決し、新たに見えた IP を追加し、
# まだローテーション中の IP の世代タグを更新し、GRACE_WINDOW_SECONDS の間
# 見えなかった IP を削除する。フラッシュもポリシー変更も自己検証もしない
# — full_init が既に一度成功して実行済みであることを前提にする
# （entrypoint.sh はその後にだけバックグラウンドの更新ループを開始する）。
# fail-open で動く: 失敗したサイクルは警告をログに残し、コンテナを畳むのではなく
# 次のサイクルの再試行に任せる。
do_refresh() {
  local gen result=0
  gen="$(date +%s)"
  echo "--- 更新サイクル $(date -Is) ---"
  if ! refresh_domains "$gen"; then
    echo "WARNING: このサイクルで更新に失敗したドメインがあります" >&2
    result=75
  fi
  if ! prune_stale_domain_rules "$(( gen - GRACE_WINDOW_SECONDS ))"; then
    echo "WARNING: このサイクルで期限切れルールの削除に失敗しました" >&2
    result=75
  fi
  # 75 はサイクルを完走したが一部処理で失敗。監視ループは止めず次回も実行する。
  return "$result"
}

case "$MODE" in
  init) full_init ;;
  refresh) do_refresh ;;
esac
