#!/bin/bash
# 起動する CLI の選択（c3c 第1段階）。launcher が CLI 引数から導出した値だけを Compose 経由で
# 明示的に渡す（CC_AGENT=claude|codex）。未設定のときだけ Claude 既定、空文字を含む不正値は拒否
# し、別 CLI へ fallback しない。Codex のときは CC_CODEX_START_MODE=run|preflight と
# CC_CODEX_READ_ONLY=0|1 も enum として検証する（launcher と container の双方で検証する契約）。
case "${CC_AGENT-claude}" in
  claude) CC_AGENT=claude ;;
  codex) ;;
  *)
    echo "ERROR: CC_AGENT が不正です（claude または codex）: '${CC_AGENT-}'。起動を中止します" >&2
    exit 1
    ;;
esac
readonly CC_AGENT
CODEX_START_MODE=""
CODEX_READ_ONLY=0
if [ "$CC_AGENT" = codex ]; then
  case "${CC_CODEX_START_MODE-}" in
    run | preflight) CODEX_START_MODE="$CC_CODEX_START_MODE" ;;
    *)
      echo "ERROR: CC_CODEX_START_MODE が不正です（run または preflight）: '${CC_CODEX_START_MODE-}'。起動を中止します" >&2
      exit 1
      ;;
  esac
  case "${CC_CODEX_READ_ONLY-0}" in
    0 | 1) CODEX_READ_ONLY="${CC_CODEX_READ_ONLY-0}" ;;
    *)
      echo "ERROR: CC_CODEX_READ_ONLY が不正です（0 または 1）: '${CC_CODEX_READ_ONLY-}'。起動を中止します" >&2
      exit 1
      ;;
  esac
  if [ "$CODEX_START_MODE" = preflight ]; then
    # 検査用コンテナでは stdout 全体を protocol の JSON 1 文書専用にする。初期化ログが出る前に
    # 元の stdout を fd3 へ確保し、以後の通常 stdout（firewall 等のログ）は stderr へ向ける。
    exec 3>&1
    exec 1>&2
  fi
fi
readonly CODEX_START_MODE CODEX_READ_ONLY

# エグレス制限（deny-by-default 許可リスト）。失敗時は起動しない（fail-closed）。
# 無効化する場合は利用側プロジェクトの .c3c/env に CLAUDE_CONTAINER_NO_FIREWALL=1 を書く。
firewall_args=()
case "${CLAUDE_CONTAINER_IPV6:-0}" in
  ''|0) ;;
  1) firewall_args+=(--ipv6) ;;
  *) echo "ERROR: CLAUDE_CONTAINER_IPV6 は0または1で指定してください。起動を中止します" >&2; exit 1 ;;
esac
if [ "${CLAUDE_CONTAINER_NO_FIREWALL:-}" = "1" ]; then
  echo "WARNING: エグレスファイアウォールは無効です（CLAUDE_CONTAINER_NO_FIREWALL=1）。コンテナのネットワークは無制限です" >&2
else
  if ! sudo /usr/local/bin/init-firewall.sh "${firewall_args[@]}"; then
    echo "ERROR: ファイアウォールの設定に失敗しました。起動を中止します（無効化するには CLAUDE_CONTAINER_NO_FIREWALL=1）" >&2
    exit 1
  fi
  # 初期化後に非特権の監視ヘルパーを起動する。15秒待機後の差分更新、
  # 容量制限付きログ、最終成功と連続失敗の記録を担当する。
  # sudo は従来と同じ init-firewall.sh のみに使い、シークレットの export より前に起動する。
  # 対話 UI には定期出力しない。状態は firewall-refresh.py --status で確認する。
  /usr/local/bin/firewall-refresh.py "${firewall_args[@]}" >/dev/null 2>&1 &
fi

# --- 起動前半ここまで（tests/test_ipv6_entrypoint.py の抽出境界） ---
# 上の行は tests/test_ipv6_entrypoint.py がファイアウォール適用と更新ループだけを
# 抽出して実行するための境界。文言を変えたらテスト側の BOUNDARY も同時に変える。
# かつてここに plugin メタデータ（~/.claude/plugins/*.json）のホストパスを sed で
# コンテナ内パスへ書き換える処理があったが、plugins/ を :ro で保護した時点で書けなく
# なった（書けてはいけない）。plugin の解決は launcher 側の別名マウント
# （compose.plugins-alias.yml、claude-container#98）が担う。

# MCP監査ゲート（stdio型サーバーの検知＋TTY確認、内部運用issue参照）。
# .mcp.json（project-scoped、Claude Code標準機能により自動ロードされる）のうち
# command フィールドを持つ stdio 型サーバーは、npx 等のネットワーク取得を経ずに
# リポジトリ同梱コードとして実行できるため、ファイアウォール・再ビルドという
# 既存の人間ゲートの対象外になる。セッション開始と同時に人間・モデルどちらの
# 判断も挟まず実行され、export 済みトークン等を読めてしまうため、ここで TTY
# 確認を挟む（http/sse 型は接続先をファイアウォールが審査するため対象外）。
# 環境変数による opt-out は設けない。根拠は「.c3c/env が信頼できない」
# ではなく、このゲートが対象とする帰結（セッション開始と同時の任意コード実行）に
# 対しては opt-out という迂回経路自体を作らない、という設計判断（README「セキュリティ
# モデル」節、`claude-container#29`）。env は全キー無条件で export されるため、
# opt-out 変数を設ければそのプロジェクト自身の env に書くだけでゲートが無効化できて
# しまう（CLAUDE_CONTAINER_NO_FIREWALL と同じ迂回経路）。env 自体は運用者が書く
# 信頼入力として扱っており（README同節）、この判断は env 全般の信頼性を疑うものではない。
# Claude 経路だけのゲート。Codex 経路は下の codex-mcp-audit.py による snapshot/verify を通し、
# Claude 用ゲートを Codex の審査に代用しない（launcher 側の分岐と同じ）。
MCP_CONFIG=/workspace/.mcp.json
if [ "$CC_AGENT" = claude ] && [ -f "$MCP_CONFIG" ]; then
  if ! stdio_servers=$(jq -r '
    (.mcpServers // {}) | to_entries[] | select(.value.command != null) |
    "\(.key)\t\(.value.command)\t\((.value.args // []) | join(" "))"
  ' "$MCP_CONFIG" 2>/dev/null); then
    echo "ERROR: $MCP_CONFIG を JSON として解析できません。起動を中止します" >&2
    exit 1
  fi
  if [ -n "$stdio_servers" ]; then
    # TOFU承認記録との照合（claude-container#28）。ホスト側 claude-container が
    # 事前に対話承認済みなら、その正規化ハッシュが :ro マウントされている
    # （/etc/claude-container/mcp-approved-hash、compose.yml参照）。正規化jqフィルタは
    # ホスト側 check_mcp_approval() と同一でなければならない（変更時は両ファイルを同期）。
    approved_hash_file=/etc/claude-container/mcp-approved-hash
    current_hash=$(jq -S -c '[(.mcpServers // {}) | to_entries[] | select(.value.command != null)]' "$MCP_CONFIG" 2>/dev/null | sha256sum | cut -c1-64)
    recorded_hash=""
    if [ -f "$approved_hash_file" ]; then
      recorded_hash=$(cat "$approved_hash_file" 2>/dev/null || true)
    fi
    if [ -n "$recorded_hash" ] && [ "$recorded_hash" = "$current_hash" ]; then
      echo "INFO: MCP 監査: stdio 型サーバーは承認済み（ハッシュ一致）。OK" >&2
    else
      echo "WARNING: $MCP_CONFIG に stdio 型の MCP サーバーがあります。そのコードはセッション開始時に即座に実行され（ツール呼び出しごとの確認はなく）、export された全ての秘密を読めます:" >&2
      if [ -n "$recorded_hash" ]; then
        echo "  （注: 前回のホスト側承認から定義が変わっています）" >&2
      fi
      # .mcp.json はプロジェクト側リポジトリの一部で攻撃者が制御しうるため、この確認プロンプトが
      # 唯一の人間ゲートになる。制御文字（ANSIエスケープ等）を除去してからでないと、表示を偽装する
      # 「ターミナル・スプーフィング」に無防備になる（claude-container#35）。claude-container 側の
      # 同種の表示ロジックと同一のサニタイズ方式（LC_ALL=C tr -d '\000-\037\177'）を使うこと（同期必須）。
      while IFS=$'\t' read -r mcp_name mcp_cmd mcp_args; do
        mcp_name=$(printf '%s' "$mcp_name" | LC_ALL=C tr -d '\000-\037\177')
        mcp_cmd=$(printf '%s' "$mcp_cmd" | LC_ALL=C tr -d '\000-\037\177')
        mcp_args=$(printf '%s' "$mcp_args" | LC_ALL=C tr -d '\000-\037\177')
        echo "  - $mcp_name: $mcp_cmd $mcp_args" >&2
      done <<<"$stdio_servers"
      printf 'これらの MCP サーバーの起動を許可しますか? [y/N] ' >&2
      if ! read -r mcp_confirm </dev/tty; then
        echo "ERROR: MCP stdio 型サーバーを確認する対話可能な TTY がありません。起動を中止します" >&2
        exit 1
      fi
      case "$mcp_confirm" in
        y | Y | yes | YES | Yes) ;;
        *)
          echo "ERROR: MCP stdio 型サーバーの確認が拒否されました。起動を中止します" >&2
          exit 1
          ;;
      esac
    fi
  else
    echo "INFO: MCP 監査: $MCP_CONFIG に stdio 型サーバーはありません。OK" >&2
  fi
fi

# GitHub トークン配線（v4〜、claude-container#24）。SECRETS_DIR は exposure 軸で設計する:
# 「常時使える（export される）権限は最小に、広い権限は明示操作の壁の向こうに」。
#   - SECRETS_DIR/export/<NAME> ... コンテナ内で環境変数として export される（issues 限定PAT等）
#   - SECRETS_DIR/<NAME>（直下）  ... export されない。ファイルとしてのみ読める（メインPAT等）
# v3 以前とは直下/export の意味が逆転している（旧: 直下=export、noexport/=非export）。
# 後方互換エイリアスは持たない（claude-container 側の fail-closed ガードが旧レイアウト
# 残存を検出する）。GH_TOKEN の ambient export は撤廃済み — gh は既定で未認証になる。
SECRETS_MOUNT=/home/node/.config/claude-container/secrets

# Codex の固定 home と CLI 実体（c3c 第1段階）。firewall と capability 剥奪の後、秘密の export より前に
# 確定する。下の export ループは「既に設定済みの名前」をスキップするため、secrets/export/CODEX_HOME・
# HOME・PATH で差し替えることはできず、検査（preflight）・再照合（verify）・本起動が同じ home と
# CLI 実体を使う。CODEX_HOME は compose.yml が CODEX_DIR を rw で載せる固定マウント先。CLI 実体は
# Dockerfile.claude の `npm install -g @openai/codex` が置く npm global bin の固定絶対パス。
# CODEX_BWRAP_DIR は Codex 同梱 bubblewrap の固定 symlink だけを置く root 所有の専用ディレクトリ
# （Dockerfile.claude が作る。#145）。Codex 経路の PATH の先頭へここで一度だけ加え、snapshot・verify・
# 本起動へ同じ PATH を継承させる。Codex の PATH 探索が最初に見つける bwrap を同梱版にし、システム版
# （画像ライブラリの間接依存等）を選ばせないため。CODEX_HOME と同じく秘密の export より前に確定するので、
# secrets/export/PATH では差し替えられない。Claude 経路の PATH は変えない。
if [ "$CC_AGENT" = codex ]; then
  export CODEX_HOME=/home/node/.codex
  CODEX_CLI=/usr/local/bin/codex
  CODEX_BWRAP_DIR=/usr/local/libexec/c3c/codex-bwrap
  readonly CODEX_HOME CODEX_CLI CODEX_BWRAP_DIR
  export PATH="$CODEX_BWRAP_DIR:$PATH"
fi

# SECRETS_DIR/export/ 配下の各ファイルを「ファイル名＝環境変数名」として export する。
# 未設定時は compose.yml の /dev/null フォールバックによりマウント先がキャラクタ
# デバイスになるため、[ -d ] で確実に偽判定できる。
EXPORT_MOUNT="$SECRETS_MOUNT/export"
if [ -d "$EXPORT_MOUNT" ]; then
  for secret_file in "$EXPORT_MOUNT"/*; do
    # 空ディレクトリ時はグロブがリテラル文字列のまま残るため [ -f ] で弾く
    # （サブディレクトリ・壊れた symlink も同時に除外できる）。
    [ -f "$secret_file" ] || continue
    secret_name=$(basename "$secret_file")
    if ! [[ "$secret_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "WARNING: secrets/export: '$secret_name' は環境変数名として不正です。スキップします" >&2
      continue
    fi
    # ${!name+x} は set 判定（値でなく「存在するか」）。set-but-empty な compose
    # 変数（例: CLAUDE_CONTAINER_NO_FIREWALL）や bash の readonly シェル変数
    # （UID 等）も捕捉できるため、非空判定（${!name:-}）より安全側に倒せる。
    if [ -n "${!secret_name+x}" ]; then
      echo "WARNING: secrets/export: '$secret_name' は既に環境変数に設定されています。スキップします" >&2
      continue
    fi
    secret_value=$(tr -d '\n\r' <"$secret_file")
    export "$secret_name=$secret_value"
  done
fi

# メインPAT（Contents RW 等を含む広い権限）の配線。SECRETS_DIR 直下に置かれ export
# されないため、GH_TOKEN 等の環境変数としては値が現れない。entrypoint はパスだけを
# GITHUB_MAIN_PAT_FILE として export し、利用者（gh CLI 呼び出し・git-askpass.sh）が
# 都度明示的にファイルを読む。配置は export 走査ループの後（SECRETS_DIR/export/ 配下に
# 同名ファイルを置かれても本体設定に乗っ取られないようにするため）。
if [ -f "$SECRETS_MOUNT/GITHUB_MAIN_PAT" ]; then
  export GITHUB_MAIN_PAT_FILE="$SECRETS_MOUNT/GITHUB_MAIN_PAT"

  # git push の opt-in 配線（README「git push を使う場合」節参照）。トークン自体は
  # export しない（git-askpass.sh が上記ファイルから都度読む）ため、GITHUB_MAIN_PAT
  # という環境変数は Claude 本体やその子プロセスの環境には現れない。
  export GIT_ASKPASS=/usr/local/bin/git-askpass.sh
  # GITCONFIG_FILE 経由で持ち込まれた credential.helper（例: store）が askpass で
  # 得たトークンを ~/.git-credentials へ平文保存してしまうのを防ぐ（issue #25）。
  # GIT_CONFIG_* 環境変数は全 config ファイル（system/XDG/global 含む）より後に
  # 適用され、空文字列は helper リストのリセットという公式仕様（git help
  # gitcredentials）。マウントされた ~/.gitconfig は read-only のため
  # `git config --global` での上書きはできず、この手段が唯一の書き換え方法。
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0=credential.helper
  export GIT_CONFIG_VALUE_0=""
fi

if [ "$CC_AGENT" = claude ]; then
  # Claude 経路の起動引数は固定（Claude Code の auto mode）。引数を受理しない版ではそのまま非ゼロで
  # 終了し、auto が利用できないセッションでは Claude Code 本体が Manual に戻す（公式 permission-modes
  # 文書）。いずれの場合も旧既定の --dangerously-skip-permissions で再試行しない（env による切替も
  # 設けない）。auto / Manual の判定は Claude Code 本体の機能で、この container の境界には数えない
  # （README「セキュリティモデル」節）。
  exec claude --permission-mode auto
fi

# Codex 経路（c3c 第1段階）。同一の secret export を終えた環境で、固定 home・固定 CLI 実体・
# 作業基点 /workspace・固定の設定解決用 override のもとに起動時 MCP 審査を行う。
#   preflight: snapshot の protocol 1 文書だけを fd3（元の stdout）へ出し、agent を起動せず終了する。
#   run:       host が :ro で渡した承認記録と再計算した hash が一致した場合だけ Codex を exec する。
# 未導入・版不一致・審査不能・不一致は停止し、Claude へ fallback しない。
CODEX_AUDIT=/usr/local/bin/codex-mcp-audit.py
CODEX_APPROVED=/etc/claude-container/codex-mcp-approved.json
if [ ! -f "$CODEX_CLI" ] || [ ! -x "$CODEX_CLI" ]; then
  echo "ERROR: Codex CLI が導入されていません（$CODEX_CLI）。.c3c/codex-version.txt が空（opt-out）のままビルドしたか、旧いイメージです。対応版を書くか空ファイルを削除して同梱 default を使い、-b で再ビルドしてください。起動を中止します" >&2
  exit 1
fi
# 同梱 bubblewrap の固定リンクが無い（#145 より前の旧いイメージ等）まま起動すると、Codex がシステム版
# を選びうる。欠落を審査・本起動より前に明示する（root が保護するビルド済み資材なので再探索・再生成しない）。
if [ ! -f "$CODEX_BWRAP_DIR/bwrap" ] || [ ! -x "$CODEX_BWRAP_DIR/bwrap" ]; then
  echo "ERROR: Codex 同梱の bubblewrap がありません。-b で再ビルドしてください。" >&2
  exit 1
fi
if ! cd -- /workspace; then
  echo "ERROR: 作業基点 /workspace に入れません。起動を中止します" >&2
  exit 1
fi
if [ "$CODEX_START_MODE" = preflight ]; then
  echo "INFO: Codex 起動時 MCP 審査: 設定済み MCP の実行定義を取得します（agent は起動しません）" >&2
  if ! python3 -I "$CODEX_AUDIT" --codex "$CODEX_CLI" snapshot >&3; then
    echo "ERROR: Codex 起動時 MCP 審査の snapshot に失敗しました。起動を中止します" >&2
    exit 1
  fi
  exec 3>&-
  exit 0
fi
if ! python3 -I "$CODEX_AUDIT" --codex "$CODEX_CLI" verify "$CODEX_APPROVED"; then
  echo "ERROR: Codex の MCP 実行定義がホスト側の承認記録と一致しないか検証できません。Codex を起動しません" >&2
  exit 1
fi
# 固定 argv。sandbox は launcher の --read-only だけで切り替え、設定解決用 override は helper の
# snapshot/verify（codex-mcp-audit.py の LIST_ARGS）と同じ値を渡す（検査と本起動の一致）。
codex_sandbox=workspace-write
if [ "$CODEX_READ_ONLY" = 1 ]; then
  codex_sandbox=read-only
fi
exec "$CODEX_CLI" --sandbox "$codex_sandbox" --ask-for-approval on-request -c 'projects={"/workspace"={trust_level="trusted"}}'
