# c3c 第0B-7段階: 標準CLI・MCP・hookの結果

日付: 2026-09-20。source commit `93211ed80ad3e4b4231f40ba5096df6924e76f34`、codex-cli0.155.1。
計画: [0B-7計画](2026-09-20-c3c-phase0b7-cli-validation.md)。実行・レビューはCodex。

## 結果

**標準codex execのworkspace-writeでモデルの固定コマンドが書き込めた。trusted projectのstdio MCPは起動し、定義変更後の別起動でも実行された。** 読み取り専用のCLI JSONはツール実行記録が欠けたため、そのケース単独ではOS拒否を立証しない。

| ケース | 実測と判定 |
|---|---|
| marker実体の直接対照 | mcp/hook-start/hook-stop/notify各1回を記録。MCP handshakeと空tools一覧も別のローカルsmokeで確認 |
| 実効定義の事前確認 | project設定有効、MCP probeあり。hooks/listにSessionStart/Stop各1、enabled=true、trustStatus=untrusted、isManaged=false |
| 標準CLI read-only v1 | CLI rc0・turn完了、cli-write.txt不在。回答にErrno30があるがJSONにtool call/outputがなく、**このケースのOS拒否の裏取りはnot run（観測記録不足）** |
| 標準CLI workspace-write v2 | command_executionの開始/完了、cwd=/workspace、WRITE_ATTEMPT→WRITE_OK、exit0。ファイル内容CLI_WRITE_OKをプローブで確認 |
| MCP起動 | read-only v1後にmcp/v1のmarker1件、定義変更後workspace v2後にmcp/v2が1件増加。各起動にCodex側のMCP専用承認入力を与えていない |
| 未承認hook | 対照以外のhook-start/hook-stop markerなし。定義の発見・未承認状態とモデルturn完了を合わせて、今回のCLIケースでは未起動と記録 |
| project notify | 両CLIでproject-local notifyを無視する警告。対照以外のnotify markerなし。**user-level notifyの実認証発火はnot run** |
| 不正TOML | parse errorでCLI rc1、timeoutではない。thread/turn開始出力なし、marker増分なし。この構文エラーでは初期設定読込で停止 |
| 終了・清掃 | プローブ完了マーカー、container/runner rc0。ownerコンテナ/network削除rc0、残留一覧空、image/専用認証home保持 |

read-onlyモデル経由のOS拒否は、以前の0B-5/6でApp Serverのraw call/outputにより確認済み。ただし、それを今回の標準CLI JSONに不足する記録の代わりに使わない。workspace-writeも固定ファイルへの成功観測であり、範囲外書込や全ツール経路の境界試験ではない。

MCPの正確な開始時点は、各CLI起動前後のmarker差分で確認した範囲に限る。最初のAPI接続やモデル応答との厳密な順序は確定していない。v2は事前に計画した別ケースで、read-only失敗を理由に権限を広げて再実行したものではない。

## 第1段階への判断材料

- 標準CLIでモデルの作業用書込が成立したため、Codex自身のsandboxを残すworkspace-writeを既定候補として検討できる。danger-full-accessへ移す必要があるという結果は出ていない。既定の確定と範囲外保護の受入はまだ行わない。
- 現行の `.mcp.json` 用審査だけではCodexのproject TOMLにあるstdio定義を覆えない。プロジェクトtrustと、個々の実行定義に対するc3cの承認契約を区別する必要がある。今回は無害な定義を人間の依頼・レビューの範囲で検査したもので、製品の承認記録を実装したわけではない。
- hookは発見された未承認定義が発火しなかったが、TTYの正式承認・保存先・持続・変更後再承認・再開時の確認は残る。[公式Hooks](https://learn.chatgpt.com/docs/hooks)のtrustの説明と整合する観測だが、全経路の保護保証ではない。
- `notify` は今回置いたproject層では実効にならなかった。user層やCLI/profile/plugin等の設定源を一律に扱わず、実効層を確認して審査対象を設計する。

## 条件と未確認

0B-6同様の固定image＋readonly main entrypointコピーで、通常firewall初期化後に検査shimを実行した。指定modelはgpt-6-astra、実Claude/ホスト設定/vault/実projectを使用していない。認証は0B-4の専用homeを継続利用し、auth本文は読取・コピーしていない。終了時metadataの異常なし。

この結果を第1段階の安全性受入完了とはしない。MCPのuser/profile/CLI/plugin等の全実効源と審査、承認記録の保護、同会話での定義再読込、正式hook承認、user notify、TTY操作・再開・認証refreshなどは未検証。製品コードは未変更。

## 証跡・レビュー

privateの実行領域に添付、probe-output.log/stderr、各CLIのJSON/診断、marker差分、inspect、rc、清掃結果を保存した。生ログが正本。認証homeは証跡採取の対象外。

計画初回C0/I0/M2、JSON出力排他とApp Serverの通常終了後の群停止を修正し、確認限定巡C0/I0/M0。Python構文・TOML・marker/MCP smoke・実行前host lint成功。最終結果レビューC0/I0/M0。編集後host `./lint.sh` はComposeを含めrc0、警告ゼロ。regular証跡53件を `$CC/.claude/test-results/c3c-0b7-cli-validation/` へ退避し、実行側でSHA-256一致を確認した（認証home非走査）。lintログは完了後追加保存。
