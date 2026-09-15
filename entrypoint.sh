#!/bin/bash
# エグレス制限（deny-by-default 許可リスト）。失敗時は起動しない（fail-closed）。
# 無効化する場合は利用側プロジェクトの .claude-container.d/env に CLAUDE_CONTAINER_NO_FIREWALL=1 を書く。
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
# 環境変数による opt-out は設けない。根拠は「.claude-container.d/env が信頼できない」
# ではなく、このゲートが対象とする帰結（セッション開始と同時の任意コード実行）に
# 対しては opt-out という迂回経路自体を作らない、という設計判断（README「セキュリティ
# モデル」節、`claude-container#29`）。env は全キー無条件で export されるため、
# opt-out 変数を設ければそのプロジェクト自身の env に書くだけでゲートが無効化できて
# しまう（CLAUDE_CONTAINER_NO_FIREWALL と同じ迂回経路）。env 自体は運用者が書く
# 信頼入力として扱っており（README同節）、この判断は env 全般の信頼性を疑うものではない。
MCP_CONFIG=/workspace/.mcp.json
if [ -f "$MCP_CONFIG" ]; then
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

exec claude --dangerously-skip-permissions
