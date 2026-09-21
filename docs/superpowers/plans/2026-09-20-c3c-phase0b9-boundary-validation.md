# c3c 第0B-9段階: 起動時審査とnative状態の境界確認

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 第1段階の起動時審査を具体化するため、無認証fixtureで実効設定の非実行取得、MCPの再読込、HTTP helper、native hook trustの同一UID書換えを限定観測する。

**Architecture:** 固定imageの使い捨てコンテナ。network none、mountゼロ、User node、追加capabilityなし。CMDをprobeへ置換するため通常firewall初期化の再検証ではない。0B-6の資源管理を再使用し、コンテナ内で新規CODEX_HOMEを作る。実認証home・ホストCodex設定は参照しない。

**Tech Stack:** Python stdlib、codex-cli 0.155.1 App Server、rootless Podman。

## 境界の整理

G3独立レビューの再診断により、前回I1/I2が「既存TOFU同等」から全runtime変更・全native trust保護へ要求を拡大していた点を訂正する。根拠は現行launcherの `check_mcp_approval()`、entrypoint起動時照合、READMEのuser/local MCP・project trustの残余記載。c3cが確認省略に用いる独立承認記録の保護は必須として残す。native trustを人間によるc3c承認の証拠にはしない。追加の継続強制は、この調査から無断で新設しない。

## Global Constraints

- 製品コード・既存worktree・ホスト設定は変更しない。commit/pushなし。Codex限定（15時JST以降はClaude利用可能という申告あり）。
- `CODEX_HOME` はコンテナ内の新規temp。auth.json不在を確認し、login/モデルturn/外部接続を行わない。network noneを起動前inspectで確認する。
- MCPは固定marker実装、公開toolなし。stdio応答はinitialize/list/pingのみ。HTTP URLはloopbackの未使用想定port9で、接続成功は要求しない。helperはmarkerと空のJSON `{}` を出すだけ。
- native hook trustの書換えは新規fixtureのconfig.tomlだけ。Codex sandbox外の同一UIDによる状態書換えを明示的に模擬し（workspace-write内のAIから書ける証明ではない）、正式な人間承認とは呼ばない。実認証homeの保存先探索や改変はしない。
- RPC25秒、観測待ち最大5秒/箇所、host probe240秒、finallyで所有コンテナ清掃。ログはprivate0700/0600。標準入力の承認要求は許可せず失敗させる。

## Files / Interfaces

`$ART=/tmp/c3c-phase0b9`。run.py/manage.py/process_runner.pyは既存0B-6の無認証runnerを複製。body.pyと固定marker文字列をprocess_runnerと結合したprobe.pyが実行対象。

### Task 1: セルフ・独立レビュー

- [ ] Python構文、schemaの `config/mcpServer/reload` null params・thread/start・hooks/listと照合。Expected 構文成功、モデルturnメソッドなし。
- [ ] セルフレビューと独立レビュー。Critical/Important全解消、修正後確認限定巡。lint host rc0。

### Task 2: 無認証観測

- [ ] `python3 /tmp/c3c-phase0b9/run.py`。Expected image固定、mount0/network none、auth不在、runner/cleanup rc0。
- [ ] metadata専用serverでconfig/read・hooks/list後5秒観測し、停止完了後markerゼロを確認。Expected このfixture/観測期間でMCP/hook/helper実行を観測しない。全pluginや無期限の非実行保証へ一般化しない。thread試験は別serverで行う。
- [ ] 無認証thread/startでMCP v1を起動しstatus照合。Expected stdio v1 marker、hook untrusted。HTTP helperは実効設定で受理され、marker有無を記録。接続失敗は想定内。
- [ ] v2保存→reload→同じthreadのstatus→新threadのstatus。Expected v2保存と新threadの接続先serverInfo.version=v2。各段階のmarker差分/PIDを記録し、新規process起動か既存client再利用かを区別する。既存threadの適用時点は実測値を記録し、5秒の不在を永続的な禁止と解釈しない。
- [ ] server終了、新規user configの `hooks.state.<key>.trusted_hash` にfixtureから得たhashを同一UIDで書く。Expected hooks/listの変化を記録する（trustedと決めつけない）。thread/startのmarker有無も観測する。モデルturnなし。
- [ ] 完了マーカー・auth不在・所有資源清掃を確認。

### Task 3: 設計へ反映

- [ ] native操作確認とc3c独立承認の違い、初期metadata取得の範囲、HTTP helperも起動時審査が必要か、reloadの実態を記録。
- [ ] G3を「c3c起動時審査とその承認記録保護」と明確化。標準managed許可リストの全面採用・native trust全体保護を既定にしない。元要件との整合を独立レビュー。
- [ ] 結果と仕様をレビュー、lint、証跡退避。Important未対応を隠さず、実装計画へ渡す判断を具体化する。

## 適用と引渡し

Superpowers writing-plans/executing-plans/requesting-code-reviewを継続。主作業はprobeと文書で製品実装はしない。既存mainの未追跡文書を継続し、他worktreeへ触れない。製品TDDはnot run（製品変更なし）。一時probeは実装の模倣テストではなく標準動作の観測。

一次資料: [MCP再読込](https://learn.chatgpt.com/docs/app-server)、[HTTP helper](https://learn.chatgpt.com/docs/config-file/config-reference)、[Hook trust](https://learn.chatgpt.com/docs/hooks)。ホスト同版binary文字列の `hooks.state` は仮説の出発点であり、実測前の確証とはしない。

`/goal`文面: 「0B-9の無認証・network none・mount0のfixtureだけでmetadata/MCP reload/helper/native trustを観測し、既存TOFUと同等のG3境界を明確化して清掃する。」必要sandboxはhost Podman実行権限。ネットワークはコンテナnone。実際のgoal作成は利用者の明示時のみ。

実装: Codex — 利用者のCodex限定継続範囲で、期限付きの無認証調査を担当する。

### 補足: 第1段階のnative一覧候補を1回だけ照合

公式tag `rust-v0.155.1`（commit `be2951ea34f0d295ed0becf97079f92fa5f6950e`）の静的レビューから、`codex mcp list --json` はstdioやHTTP helperを起動しない一方、helper本文を伏せると判明した。`/tmp/c3c-phase0b9-list` は同じ無認証・network none・mount0 runnerで、同じv1 fixtureに対してこの一覧コマンドだけを1回実行する。stdout/stderrは分離し、30秒期限、finally群停止。Expected stdioのcommand/args/env/cwd、helperの `<redacted>`、marker 0。fixtureの値だけを記録し、実設定の生JSON収集には転用しない。モデル・thread開始なし。

第1段階の候補は、取得できるstdio実行定義を審査し、enabled HTTP helperのように完全な実行定義を得られないものは明示的に拒否する方式。未知の形式を空定義扱いにしない。標準一覧を全MCPの完全取得や無通信のAPIと呼ばない。補足は独立差分レビュー後に実行する。
