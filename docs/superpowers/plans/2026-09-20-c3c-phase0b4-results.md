# c3c 第0B-4段階: ChatGPT新規認証の結果

日付: 2026-09-20。source commit `93211ed80ad3e4b4231f40ba5096df6924e76f34`、codex-cli 0.155.1。
計画: [0B-4計画](2026-09-20-c3c-phase0b4-auth-validation.md)。実行・独立レビューはCodex。

## 結果

利用者のブラウザ操作後、専用CODEX_HOMEへの新規ChatGPT認証が成立した。CLIは `Successfully logged in` と `Logged in using ChatGPT` を出力し、後続の完了マーカーを確認した。コンテナは正常終了（exited、rc0）。

認証ファイルは通常ファイル、所有者は実行ユーザー、mode0600。本文は読み出し・コピー・証跡収集していない。専用保存先は0700の一時領域に保持し、次の検証へ引き継ぐ。ホスト既存の認証・設定は共有していない。

owner確認済みの検証用コンテナと専用networkを削除（各rc0）、ownerラベルによる残留コンテナ一覧は空。認証homeは保持した。

## 検査の条件と限界

0B-2と同じ固定imageへmain entrypointのコピーをreadonly指定し、通常ENTRYPOINT/CMDとfirewall初期化を経由した。末尾のClaude呼出しだけを認証用shimへ渡した。mainをそのままbuildした製品imageや、完成したc3cの試験ではない。

firewallの初期化・検証を通過した。ログにはIPv6 sysctl関連の警告もあり、IPv6 DROPが境界である旨が表示された。この認証成功をIPv6全般の検証完了と扱わない。

モデル応答・会話継続・worktree移動後のツール/指示/MCP/sandbox追従・再開は **not run（この段階は認証のみ）**。ChatGPT認証の成立を、モデル利用やworktree管理の受入完了と合算しない。

## 証跡とレビュー

private実行領域のstate・result.json・CLIログ・inspect・清掃ログに保存。認証homeは証跡から分離し、一時コードや実保存先はこの文書に載せない。

計画初回C0/I2/M0、ログ保存権限と検査失敗時の清掃を修正し、確認限定巡C0/I0/M0。失敗分岐の模擬3例とPython構文確認は成功。最終結果の独立レビューはC0/I0/M0。ホストの `./lint.sh` はCompose検証を含めrc0、警告ゼロ。
