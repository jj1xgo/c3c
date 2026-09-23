# Codex 起動時 MCP 審査の範囲を Claude 経路に揃える（#150）設計

**Issue:** [#150](https://github.com/jj1xgo/c3c/issues/150)
**状態:** 設計案（持ち主のレビュー待ち）。実装計画は本 spec の承認後に writing-plans で作る。
**区分:** 境界（SECURITY-CLAIMS C-3 の保証範囲と、`compose`・launcher・`entrypoint.sh`・`codex-mcp-audit.py` の審査経路を変える）。

## 目的

`codex-version.txt` に `latest`（または対応確認していない任意の版）を書いても `c3c codex` が起動できるようにする。そのために、Codex 経路の起動時 MCP 審査を Claude 経路と同じ基準（README「帰結の重大性で線を引いている」節、`claude-container#29`）に揃え、Codex 本体の内部出力（`codex mcp list --json`）と版の完全一致への依存をなくす。

成功条件:

- `codex-version.txt` が `latest` または任意の固定版のイメージで、`c3c codex` が起動する（版を理由に止まらない）。
- リポジトリ同梱の Codex 設定から起動される stdio MCP は、これまでどおり初回・変更時にホストで確認される。
- リポジトリ同梱の設定で有効化された plugin は、起動前に fail-closed で拒否される。

## 背景と事実（2026-09-23 確認、codex-cli 0.156.0）

- Claude 経路は `/workspace/.mcp.json` を `jq` で直接読み、版に依存しない（`entrypoint.sh` の MCP 監査ゲート、ホスト側 `check_mcp_approval()`）。
- Codex 経路は native `codex mcp list --json` の出力を `codex-mcp-audit.py` が厳密に検証し、版を `SUPPORTED_VERSION` と完全一致で照合する。phase1 計画（`docs/superpowers/plans/2026-09-20-c3c-phase1-codex-launch.md`「審査対象」）で user / project / 有効な plugin を範囲にした結果であり、#29 の原則との突き合わせの記録は無い。
- Codex はプロジェクト root（既定の marker は `.git`）から cwd までの各 `.codex/config.toml` を trusted project の層として読む（`codex-rs/config/src/loader/local.rs`）。c3c は cwd と project root がともに `/workspace` で、固定の trust override で `/workspace` を trusted にする。
- 公式 Config Reference では、project 層は `mcp_servers` を受け付け、`notify`・`profile`・`profiles`・`model_provider(s)`・`otel` 等を無視する。plugin は trusted-project の `config.toml` でも設定できる。
- Codex はリポジトリ root の marketplace（`.agents/plugins/marketplace.json`・`.claude-plugin/marketplace.json` 等）を自動探索し、設定で有効な plugin を `CODEX_HOME` のキャッシュへ自動でインストールしうる（詳細は非公開の記録）。plugin の manifest は `.codex-plugin/plugin.json` と `.claude-plugin/plugin.json` の 2 系統があり、`mcpServers` はパス指定とオブジェクトの両方を取る。c3c がこれを読むと、再び Codex の内部形式に依存する。

## 設計

### 審査対象

| 設定源 | 新しい扱い | 理由 |
| --- | --- | --- |
| `/workspace/.codex/config.toml` の `mcp_servers` | 審査する（stdio は hash して初回・変更時に確認、helper 付き HTTP は拒否、helper 無し HTTP は通す。現行と同じ判定） | リポジトリ同梱で第三者が仕込める |
| `/workspace/.codex/config.toml` の `plugins` | エントリが 1 つでもあり、`enabled = false` と明示されていないものがあれば起動前に拒否する | リポジトリ同梱で第三者が仕込める。plugin の中身を読まずに版非依存で塞げる |
| `CODEX_DIR`（コンテナ内 `~/.codex`）の `config.toml`・plugin キャッシュ | 審査しない | 運用者自身が書く設定（#29）。Claude 経路の `~/.claude.json` と同じ扱い |
| `/workspace` より上の階層 | 対象外 | c3c はコンテナに対象ディレクトリだけを mount し、上位はイメージの内容で repo からは制御できない |

`/workspace/.codex/config.toml` が無ければ審査対象は 0 件（空定義として記録し、確認なし）。

### 読み取り方

- `codex-mcp-audit.py` の snapshot / verify は、native CLI を実行せず、`/workspace/.codex/config.toml` を Python 標準の `tomllib` で読む。イメージ内の python3 を使う（ホストの Python 版には依存しない）。
- 読み取りは公開の設定形式だけに基づく。`mcp_servers.<name>` の既知 key（公式 Config Reference の `command`・`args`・`env`・`env_vars`・`cwd`・`url`・`http_headers_helper`・`enabled`・`bearer_token_env_var`・`oauth`・`startup_timeout_sec`・`tool_timeout_sec` 等）以外の key を持つエントリは、判定不能として fail-closed で拒否する。既知 key の正確な一覧と型は、実装計画で公式 Reference と対象版のソースに照合して確定する。
- TOML として壊れている、`mcp_servers` や `plugins` の型が想定と違う、重複定義などは判定不能として拒否する（現行の fail-closed 方針を維持）。
- hash の対象は enabled な stdio エントリの名前・`command`・`args`・`cwd`・`env`・`env_vars`（現行と同じ項目）。timeout 等の診断値は含めない。

### 起動の流れ（構造は現行を維持）

1. launcher の guard 群（版の一致検査を外す。後述）。
2. イメージの `io.c3c.codex-audit-protocol` label を検査する。protocol を 2 に上げ、旧イメージ（1）は `-b` を案内して止める。
3. preflight コンテナで snapshot を取り、ホストで確認する。native CLI を呼ばないので、版取得 5 秒・一覧 60 秒の期限と、cloud config 取得・auth refresh 等の副作用の記述は不要になる。
4. 本起動の `entrypoint.sh` で verify（同じファイルを再度読み、承認 hash と一致したときだけ Codex へ進む）。

### 版の扱い

- `CODEX_SUPPORTED_VERSION`（launcher）と `SUPPORTED_VERSION`（audit）は審査の条件から外す。`codex-version.txt` の固定版・`latest` はどちらも起動を止めない。空ファイル（opt-out）で Codex を起動しようとした場合の拒否は維持する。
- 同梱 default の `codex-version.txt` は固定版のまま残す（再現性と `test-build.sh` の検査のため）。`latest` を使うかは利用側が選ぶ。
- 承認記録の保存先を `mcp-approvals/codex/<project>/<版>.json` から版を含まない名前（例: `mcp-approvals/codex/<project>/project-config.json`）に変える。record の `codex_version` は廃止し、`protocol_version` を 2 にする。旧記録は読まない（初回だけ再確認になる）。`--clean` の対象は現行どおり project の Codex subdirectory 全体。

### 失う保護と残余（SECURITY-CLAIMS・README に明記する）

- `CODEX_DIR` の `config.toml` にセッションが MCP を書き足しても、次回起動の確認で止まらなくなる。Claude 経路の `~/.claude.json` と同じ限界。
- 利用者自身が user 層で有効化した plugin（リポジトリの marketplace 由来を含む）は審査しない。
- 起動後の設定変更・再接続・plugin の追加は、現行どおり継続監視しない。
- C-3 の「native 一覧で user / project / plugin を網羅する」主張は取り下げ、「リポジトリ同梱の project 設定の stdio MCP を審査し、project 設定での plugin 有効化を拒否する」に書き換える。

## 範囲外

- Claude 経路でリポジトリ同梱の設定から plugin を有効化できるか（`.claude/settings.json` の `enabledPlugins`・`extraKnownMarketplaces` 等）は未確認。一次情報で確認したうえで別 Issue の候補として記録する。
- hooks・sandbox 設定など MCP 以外の project 設定の扱いは現行のまま。
- 同梱 default を `latest` にすることはしない。

## 検証の方針

- `codex-mcp-audit.py` の単体試験を、`config.toml` の fixture（stdio / helper 付き HTTP / helper 無し HTTP / 未知 key / 壊れた TOML / plugins の有効・`enabled = false` / ファイル無し）で書き直す。
- launcher 試験で、固定版・`latest`・空 opt-out の各 `codex-version.txt` の guard 結果、protocol 1 の旧イメージの拒否、新しい承認記録パスと `--clean` を確認する。
- 実イメージで、`codex-version.txt` を `latest`（npm の最新が 0.156.0 と異なる状態）にして `-b` 後に `c3c codex` が審査を経て起動すること、project 設定の stdio MCP で確認プロンプトが出ること、project 設定の plugin 有効化で起動前に止まることを確認する。
