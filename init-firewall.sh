#!/bin/bash
# デフォルト拒否のエグレス許可リスト。公式 Anthropic devcontainer
# （anthropics/claude-code の .devcontainer/init-firewall.sh）からの移植で、差分は以下:
#   - ipset は使わない: rootless podman はホストの ip_set カーネルモジュールを
#     自動ロードできないため、代わりに専用チェーンでの CIDR ごとの素の iptables ルールを使う。
#   - DNS のエグレスは /etc/resolv.conf のリゾルバに限定し、53番ポート全般ではない。
#   - IPv6 のエグレスは全面遮断する: 許可リストは A レコードのみを解決するため、
#     upstream の IPv4 限定ルールをそのまま使うと IPv6（pasta）が迂回経路として残ってしまう。
#   - 追加の許可ドメインは /etc/claude-container/allowed-domains.txt から読み、
#     ビルド時にイメージへ焼き込む（root 所有で node からは書き込めない）。
#   - ドメイン由来の CIDR ルールには世代タグを付ける（下の add_cidr_tagged を参照）。
#     これにより `--refresh-domains` モードが、短い TTL で IP が入れ替わる CDN に
#     ルール全消去なしで追随できる（2026-07 に観測: CloudFront 経由の
#     cyberjapandata.gsi.go.jp は A レコード一式が 13〜60 秒ごとに丸ごと入れ替わり、
#     起動時 1 回だけの解決では長いセッション中に確実に古くなる）。
# entrypoint.sh から sudo 経由で root として実行する。初回実行では fail-closed を
# 保つ必要がある: エラーが起きればコンテナ起動を中止する（CLAUDE_CONTAINER_NO_FIREWALL=1 で無効化可）。
# `--refresh-domains` モード（末尾を参照）はこの原則の軽量な fail-open 例外である
# — 定期的なバックグラウンドの手直しであり、起動時の安全ゲートではない。
set -euo pipefail
IFS=$'\n\t'

ALLOWED_DOMAINS_FILE=/etc/claude-container/allowed-domains.txt
ALLOWED_PORTS_FILE=/etc/claude-container/allowed-ports.txt
CHAIN=CLAUDE_EGRESS
# 観測された最短の CDN TTL は 13 秒。それよりやや遅く更新することで、1 回の取りこぼしを
# 毎回の揺らぎを追いかけるのではなく次のサイクルで拾えるようにする。
# sleep 自体は entrypoint.sh の更新ループ側にある — 両者を同期させておくこと。
# ここでの定数は、下の猶予期間のサイズを決めるためのもの。
REFRESH_INTERVAL_SECONDS=15
# 更新サイクル 12 回分の猶予: CDN が 1 回のクエリで稼働中エッジ IP の一部しか
# 返さなかった場合や、一時的なリゾルバの不調を吸収してから、
# 使われなくなったドメインの IP をようやく削除する。
GRACE_WINDOW_SECONDS=$((REFRESH_INTERVAL_SECONDS * 12))

MODE=init
if [ -n "${1:-}" ]; then
  if [ "$1" = "--refresh-domains" ]; then
    MODE=refresh
  else
    echo "ERROR: 未知の引数です: $1（--refresh-domains か引数なしを想定）" >&2
    exit 1
  fi
fi

# CHAIN 経由の ACCEPT ルール（下の add_cidr/add_cidr_tagged）が、それ以外は許可された
# IP に対して許可するポート（claude-container#31）。init モードと --refresh-domains モードの
# 両方が同じ値を見るよう、ここで一度だけ読む。DNS リゾルバのルールや full_init() の
# ホストネットワークのルールには適用されない — それらは CHAIN を完全にバイパスし、
# 制限なしのままとなる（CHAIN 作成箇所のコメントを参照）。
resolve_allowed_ports() {
  local -a ports=()
  local raw lo hi
  if [ -f "$ALLOWED_PORTS_FILE" ]; then
    # `|| [ -n "$raw" ]` により、末尾に改行のない最終行も読む
    # （read はその行で非 0 を返すが変数は埋まっている。これがないと
    # 最終エントリが黙って落ちていた — claude-container#49）。
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
  if [ "${#ports[@]}" -gt 15 ]; then
    echo "ERROR: $ALLOWED_PORTS_FILE のポート/範囲が ${#ports[@]} 個あります。iptables の multiport マッチは最大 15 個です" >&2
    exit 1
  fi
  # full_init() の起動時自己検証は、api.github.com への 443 番が到達可能で
  # 80 番が遮断されていることを前提にしている。どちらかに反する設定は、以前は
  # そこで「ネットワークの問題」に見えるメッセージ（"unable to reach ...:443"）や
  # 「ルールが壊れている」ように見えるメッセージ（"port restriction not enforced"）で
  # 失敗していたため、ここで本当の理由とともに検証する（claude-container#49）。
  # 範囲は両端を含む。10# は 10 進として強制するもので、先頭ゼロ（例: 080）を
  # 8 進として読まないようにする。
  local entry has_443=0 has_80=0
  for entry in "${ports[@]}"; do
    lo="${entry%%:*}"; hi="${entry##*:}"
    if (( 10#$lo <= 443 && 443 <= 10#$hi )); then has_443=1; fi
    if (( 10#$lo <= 80 && 80 <= 10#$hi )); then has_80=1; fi
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
  iptables -A "$CHAIN" -d "$cidr" -p tcp -m multiport --dports "$ALLOWED_PORTS" -m comment --comment "domain=${domain};gen=${generation}" -j ACCEPT
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
# "-d ${ip}/32 " での grep は、add_cidr_tagged にポート制限（claude-container#31）を
# 追加した後も一致し続ける。
add_or_touch_domain_ip() {
  local ip="$1" domain="$2" generation="$3"
  local existing_idx
  existing_idx=$(iptables -S "$CHAIN" | tail -n +2 | \
    grep -nF -- "-d ${ip}/32 " | grep -F "domain=${domain};" | \
    cut -d: -f1 | head -n1 || true)
  add_cidr_tagged "$ip" "$domain" "$generation" || return 1
  if [ -n "$existing_idx" ]; then
    iptables -D "$CHAIN" "$existing_idx"
  fi
}

# Claude Code のエンドポイントとプロジェクト固有のドメイン、1 行に 1 つ。
build_domain_list() {
  local -a base_domains=(
    api.anthropic.com
    claude.ai
    console.anthropic.com
    statsig.anthropic.com
    statsig.com
    sentry.io
  )
  printf '%s\n' "${base_domains[@]}"
  if [ -f "$ALLOWED_DOMAINS_FILE" ]; then
    grep -Ev '^\s*(#|$)' "$ALLOWED_DOMAINS_FILE" | tr -d ' \t'
  fi
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
  local generation="$1" had_errors=0 domain ips ip dig_output
  local -a domains
  mapfile -t domains < <(build_domain_list)
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
      if [[ "$dig_output" =~ status:\ NXDOMAIN ]]; then
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
  return "$had_errors"
}

# 世代が cutoff_epoch より古いドメインタグ付きルールを削除する。GitHub の
# CIDR ルールとホストネットワークのルールには "domain=" コメントがなく、
# ここで一致することはない。行番号の降順で削除する。`iptables -D CHAIN N` は
# N を削除するとそれ以降の全行の番号が詰まるため。
prune_stale_domain_rules() {
  local cutoff="$1"
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
  done < <(iptables -S "$CHAIN" | tail -n +2)
  local n
  for (( n=${#stale_line_numbers[@]}-1; n>=0; n-- )); do
    iptables -D "$CHAIN" "${stale_line_numbers[n]}" 2>/dev/null || \
      echo "WARNING: $CHAIN の ${stale_line_numbers[n]} 行目の古いルールを削除できませんでした" >&2
  done
}

# 起動時の完全な初期化: フラッシュし、全ルールをゼロから再構築し、自己検証する。
# fail-closed — ここでのエラーはコンテナ起動を中止する。
full_init() {
  # 既存ルールをフラッシュする。注記: -F はルールのみを消し、-P のデフォルト
  # ポリシーは変えない — このスクリプトが既に一度実行済みなら（前回の実行で
  # ポリシーが DROP のまま）、このフラッシュ直後から下でルールが再構築されるまで
  # トラフィックが即座に遮断される。そのため、ネットワークを必要とする以降の処理
  # （GitHub meta の読み込みはローカルだが、ドメイン解決ループは実際に DNS を
  # 引く）より前に、loopback／確立済み接続／DNS リゾルバの ACCEPT ルールを
  # 先にインストールする。これにより、セッション途中でこのスクリプトを再実行しても
  # 安全になる: 再構築中の最悪ケースは DNS のみ可能な DROP 状態であり、
  # 完全なロックアウトにはならない。CDN の IP ローテーションは今では
  # はるかに軽い `--refresh-domains` モード（ファイル末尾を参照）が扱う。
  # このような完全な再実行は、より重いが手動のフォールバック
  # （例: トラブルシューティング）として引き続き使える。
  iptables -F
  iptables -X
  iptables -t nat -F
  iptables -t nat -X
  iptables -t mangle -F
  iptables -t mangle -X

  # 許可リストチェーン: 許可された CIDR/IP ごとに 1 つの ACCEPT を、
  # $ALLOWED_PORTS に制限して置く（add_cidr/add_cidr_tagged、claude-container#31）。
  # この制限がかかるのは GitHub の CIDR とタグ付きのドメインごとのルール「のみ」。
  # 下の DNS リゾルバのルールと、さらに下のホストネットワークのルールは CHAIN を
  # 完全にバイパスし（INPUT/OUTPUT へ直接追加される）、ポート制限を受けない。
  iptables -N "$CHAIN"

  # loopback と確立済み接続
  iptables -A INPUT -i lo -j ACCEPT
  iptables -A OUTPUT -o lo -j ACCEPT
  iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
  iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

  # DNS: 設定済みのリゾルバへのみ（大きな応答用に udp と tcp の両方）。
  # 下のドメイン解決ループがこれを必要とするため、その前にインストールする。
  mapfile -t resolvers < <(awk '/^nameserver/ {print $2}' /etc/resolv.conf | grep -E '^[0-9.]+$' || true)
  if [ "${#resolvers[@]}" -eq 0 ]; then
    echo "WARNING: /etc/resolv.conf に IPv4 リゾルバがないため、DNS を任意のホストへ許可します" >&2
    iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
    iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
  else
    for resolver in "${resolvers[@]}"; do
      iptables -A OUTPUT -d "$resolver" -p udp --dport 53 -j ACCEPT
      iptables -A OUTPUT -d "$resolver" -p tcp --dport 53 -j ACCEPT
    done
  fi

  # GitHub の IP 範囲（HTTPS・SSH 経由の git/gh 用）。ここでは動的な取得をしない
  # — それをすると、コンテナ起動のたびに未認証の GitHub API のレート制限
  # （IP あたり 60 req/h）を消費してしまう。代わりに、claude-container の
  # stage_build_context() が一度取得しビルド時にイメージへ焼き込んだ
  # スナップショットを読む — この範囲はめったに変わらないため、古いコピーでも
  # 使い続けられる。
  local gh_meta_snapshot=/etc/claude-container/github-meta.json
  echo "ビルド時スナップショットから GitHub の IP 範囲を読み込んでいます..."
  local gh_ranges
  gh_ranges=$(cat "$gh_meta_snapshot" 2>/dev/null || true)
  if ! echo "$gh_ranges" | jq -e '.web and .api and .git' >/dev/null 2>&1; then
    echo "ERROR: GitHub meta のスナップショット $gh_meta_snapshot がないか不正です" >&2
    exit 1
  fi
  while read -r cidr; do
    add_cidr "$cidr" "GitHub meta"
  done < <(echo "$gh_ranges" | jq -r '(.web + .api + .git)[]' | sort -u)

  # Claude Code のエンドポイントとプロジェクト固有のドメインに、世代タイムスタンプの
  # タグを付ける。これにより、バックグラウンドの --refresh-domains ループが、
  # CDN 由来のドメインが IP をローテーションするにつれて古いエントリを見つけて
  # 期限切れにできる。
  if ! refresh_domains "$(date +%s)"; then
    echo "ERROR: 初期ファイアウォール設定中に解決できなかったドメインがあります" >&2
    exit 1
  fi

  # ホストネットワーク（ゲートウェイのみ）、ホスト側サービス用。単一のゲートウェイ
  # IP に限定し、その /24 全体ではない（claude-container#31） — ポート制限なし
  # （これは CHAIN をバイパスする。上の CHAIN 作成箇所の注記を参照）。
  local host_ip host_network
  host_ip=$(ip route | awk '/^default/ {print $3; exit}')
  if [ -z "$host_ip" ]; then
    echo "ERROR: ホスト IP を検出できませんでした" >&2
    exit 1
  fi
  host_network="${host_ip}/32"
  echo "ホストネットワークを検出しました: $host_network"
  iptables -A INPUT -s "$host_network" -j ACCEPT
  iptables -A OUTPUT -d "$host_network" -j ACCEPT

  # デフォルト拒否 + 許可リストチェーン。即座にフィードバックを返すための REJECT を末尾に
  iptables -P INPUT DROP
  iptables -P FORWARD DROP
  iptables -P OUTPUT DROP
  iptables -A OUTPUT -j "$CHAIN"
  iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited

  # IPv6 の扱い:
  #   1) 主経路: compose.yml の sysctls（net.ipv6.conf.*.disable_ipv6=1）が、この
  #      スクリプトが動く前に既に IPv6 を無効化しているはず。これは、glibc の
  #      getaddrinfo(AI_ADDRCONFIG) が（デフォルトルートのない）リンクローカルのみの
  #      アドレスから IPv6 を「使える」と誤報告し、Happy Eyeballs が許可済み CDN
  #      ドメインの到達不能な AAAA 候補で止まってしまう不具合（2026-07 に
  #      CloudFront 経由の cyberjapandata.gsi.go.jp で観測）を修正する。
  #   2) フォールバック（このブロック）: compose 側の sysctls 設定が効かなかった
  #      場合（例: `sysctls:` 未対応の古い podman-compose）に備え、/proc/sys 経由で
  #      同じ無効化を再試行する。非致命的 — これは信頼性のための手直しであり
  #      セキュリティゲートではないため、このスクリプト通常の fail-closed の原則から
  #      意図的に外れる。
  #   3) セキュリティ境界（下は不変）: 1)/2) が成功したかどうかに関わらず、
  #      ip6tables で全ての IPv6 を遮断する。許可リストは A レコードしか
  #      解決しないため、生き残った IPv6 経路があればそれを完全に迂回されてしまう。
  disable_ipv6_fallback() {
    local path ok=1
    for path in /proc/sys/net/ipv6/conf/*/disable_ipv6; do
      [ -e "$path" ] || continue
      echo 1 > "$path" 2>/dev/null || ok=0
    done
    [ "$ok" -eq 1 ]
  }
  if disable_ipv6_fallback; then
    echo "/proc/sys 経由で IPv6 を無効化しました（フォールバック確認 OK。主経路は compose.yml の sysctls）"
  else
    echo "WARNING: /proc/sys/net/ipv6/conf/*/disable_ipv6 経由で IPv6 を無効化できませんでした（フォールバック）。" >&2
    echo "WARNING: compose.yml の sysctls も効いていない場合、glibc が許可済み CDN ドメインの AAAA を" >&2
    echo "WARNING: 優先し、Happy Eyeballs による断続的な失敗が起きる可能性があります。" >&2
    echo "WARNING: 下の ip6tables DROP が引き続き有効なセキュリティ境界です。" >&2
  fi

  # IPv6: loopback を除く全てを遮断する（許可リストは IPv4 のみのため。上の
  # disable_ipv6 sysctl が効いたかどうかに関わらず有効なセキュリティ境界）
  if ip6tables -L >/dev/null 2>&1; then
    ip6tables -F
    ip6tables -X
    ip6tables -A INPUT -i lo -j ACCEPT
    ip6tables -A OUTPUT -o lo -j ACCEPT
    ip6tables -P INPUT DROP
    ip6tables -P FORWARD DROP
    ip6tables -P OUTPUT DROP
  else
    echo "ip6tables が使えないため、IPv6 接続はないものとみなします"
  fi

  echo "ファイアウォールの設定が完了しました"
  echo "ファイアウォールのルールを検証しています..."
  if curl --connect-timeout 5 -s https://example.com >/dev/null 2>&1; then
    echo "ERROR: ファイアウォール検証に失敗しました。https://example.com へ到達できてしまいました" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり https://example.com へ到達できません"
  # TCP の接続確認のみ（HTTP リクエストはしない）。これにより、コンテナ起動の
  # たびに未認証の GitHub API のレート制限を消費しない。
  if ! timeout 10 bash -c 'exec 3<>/dev/tcp/api.github.com/443' 2>/dev/null; then
    echo "ERROR: ファイアウォール検証に失敗しました。api.github.com:443 へ到達できません" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり api.github.com:443 へ到達できます"
  if ! curl --connect-timeout 10 -s -o /dev/null https://api.anthropic.com; then
    echo "ERROR: ファイアウォール検証に失敗しました。https://api.anthropic.com へ到達できません" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり https://api.anthropic.com へ到達できます"
  # ポート制限（claude-container#31）が、それ以外は許可された IP の非許可
  # ポートを実際に遮断していることを確認する。github.com は実際に 80 番でも
  # 待ち受けている（HTTP → HTTPS リダイレクト）ので、ここでの失敗は「相手が
  # 待ち受けていなかった」とは混同しようがなく、必ず自分のルールが拒否している
  # ことになる。これは CHAIN で制限される範囲（GitHub の CIDR／タグ付き
  # ドメインルール）のみを検証する。DNS（53番）とホストネットワークのルールは
  # CHAIN をバイパスするため、この検査の対象外。
  if timeout 5 bash -c 'exec 3<>/dev/tcp/api.github.com/80' 2>/dev/null; then
    echo "ERROR: ファイアウォール検証に失敗しました。api.github.com:80 へ到達できてしまいました（ポート制限が効いていません）" >&2
    exit 1
  fi
  echo "検証 OK: 想定どおり api.github.com:80 へ到達できません（ポート制限が有効）"
}

# 軽量な定期的手直し: 許可された全ドメインを再解決し、新たに見えた IP を追加し、
# まだローテーション中の IP の世代タグを更新し、GRACE_WINDOW_SECONDS の間
# 見えなかった IP を削除する。フラッシュもポリシー変更も自己検証もしない
# — full_init が既に一度成功して実行済みであることを前提にする
# （entrypoint.sh はその後にだけバックグラウンドの更新ループを開始する）。
# fail-open で動く: 失敗したサイクルは警告をログに残し、コンテナを畳むのではなく
# 次のサイクルの再試行に任せる。
do_refresh() {
  local gen
  gen="$(date +%s)"
  echo "--- 更新サイクル $(date -Is) ---"
  refresh_domains "$gen" || echo "WARNING: このサイクルで更新に失敗したドメインがあります" >&2
  prune_stale_domain_rules "$(( gen - GRACE_WINDOW_SECONDS ))"
}

case "$MODE" in
  init) full_init ;;
  refresh) do_refresh ;;
esac
