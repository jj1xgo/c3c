# c3c 第1段階の実装・検証記録

2026-09-21 更新。第1段階は進行中。Task 4 の残りの受入と最終レビューを完了条件として残す。

対象は `93211ed80ad3e4b4231f40ba5096df6924e76f34` を基点とする `c3c/phase1-codex-launch` worktree の未コミット差分。基点 commit 自体が新機能を含むという意味ではない。

## 実装と回帰検証

`--agent claude|codex`、Codex 専用 `--read-only`、固定 home/CLI による native MCP 一覧、ホスト側承認と本起動の再照合、検査用の非 TTY Compose、境界アセットへの組み込みを実装した。既定の Claude 起動を維持する。

- helper: 36 件成功。実 native CLI の user/project/plugin 設定解決と HTTP helper 拒否も個別 fixture で確認。
- launcher 回帰: PASS 250 / FAIL 0。内包する Codex launcher 試験は 32 件（表示改行の回帰確認を含む）。
- entrypoint: 15 件成功。validator: PASS 82 / FAIL 0。既存 hook 試験成功。
- `./lint.sh`: ホストの podman-compose 検証を含め成功。
- 通常 runtime suite: 6 段階すべて成功。build 8/0、設定の読み取り専用 mount 25/0、通常 entrypoint の capability 剥奪、IPv4 許可/拒否、refresh 成功、対照プローブと清掃を確認。この suite は標準 image の実境界を検証するもので、Codex 対話作業の証拠とは分ける。

## 実ランチャーによる Codex 起動受入

専用の ChatGPT 認証 home と使い捨て project/Claude 設定を使用。ホストの実 Claude/Codex 設定は共有せず、認証ファイルの本文は表示・複製・削除していない。launcher の HOME も fixture に隔離した。

| 確認項目 | 実測結果 |
|---|---|
| 通常/検査用 Compose の mount・capability・起動 mode | 両方の実解決値を検査、成功 |
| image の protocol label・ENTRYPOINT・CMD・user | 成功 |
| 初回承認 | 承認前 marker 0、本起動後 1。表示と直接 preflight の定義が fixture と完全一致してから承認 |
| 同一定義で `--read-only` 再起動 | 確認省略、本起動の hash 照合成功、marker 1 |
| 承認記録の `:ro` | node による追記が read-only filesystem で拒否された |
| MCP 引数変更後の拒否 | 再確認へ進み、n で自然終了コード 1。旧記録と marker に変化なし |
| enabled HTTP の `http_headers_helper` | 確認前に終了コード 1、helper/stdio marker とも実行なし |
| secrets/export の別 CODEX_HOME | スキップ警告を確認し、別 home の marker は全段階で 0 |
| 清掃 | 専用コンテナ・image・network・build context と fixture を清掃。認証ファイルの mode/所有者を確認 |

非 TTY の直接 preflight は stdout が JSON 1 文書、stderr が起動ログとなることを実測した。marker は command プロセス起動の証拠であり、MCP の全機能成功を意味しない。対話 UI には startup issue 表示もあり、その詳細はこの batch では取得していない。

試験 harness の初回実行は build 出力の `login` パッケージを認証要求と誤認して停止した。これは製品の認証失敗ではない。判定を承認後の UI に限定して再実行し、上表の結果を得た。初回も清掃成功。harness 自己検証は 11 件成功。

## 実対話・再開・native hook

同じ専用認証 home を使い、実 launcher から codex-cli 0.155.1 / gpt-6-astra を起動した。fixture の repo config は model と hooks の有効化を指定し、MCP 定義は空。host の承認記録や native hook trust の保存先を直接書き換えず、標準 UI の個別 handler 画面で承認した。

| 条件 | 観測 |
|---|---|
| v1 未承認で最初の作業 turn | 結果ファイル作成成功、hook marker なし |
| v1 を個別承認→停止→再起動→最初の作業 turn | marker `v1` が 1 行 |
| 停止→再起動→`/resume` で直前の会話を選択→続きの作業 | 前の会話を UI で復元し、`C3C_RESUMED` と前の入力を新規ファイルへ記録。resume hook で `v1` がもう 1 行 |
| hook 引数を v2 に変更→起動 | `Modified since last trusted - review required` と表示 |
| v2 未承認で作業 turn | 作業成功、marker は v1 の 2 行から増えない |
| v2 を個別再承認→停止→再起動→最初の作業 turn | marker `v2` が 1 行追加 |

モデルは repo の `AGENTS.md`、repo skill の `SKILL.md`、fixture の memory Markdown と入力を読み、指示された 4 つの marker を結果ファイルへ記録した。これは Markdown 読取りと明示スキル利用の実測であり、Claude auto-memory と Codex memory の同等性を示すものではない。

vault を模した `/shared` の Markdown は読取りと workspace への転記に成功した。共有先への追記は Codex の `workspace-write` sandbox 内で read-only filesystem として拒否され、内容が不変であることをホストから確認した。mount 自体が rw であることと、native sandbox が書込みを許すことは別である。制約を迂回する操作は行っていない。

起動時の 1 件の issue は「OS の PATH に bubblewrap がないため、Codex 同梱の bubblewrap を使用する」という native の案内だった。対話作業での workspace 書込みと `/shared` 書込み拒否を確認している。最初の MCP marker batch の追加 MCP issue の詳細は未取得であり、その batch では command 起動だけを検証済みとする。

5 回の launcher セッションはすべて終了コード 0。専用コンテナ・image・network・build context の清掃を確認し、fixture と証跡は private に保存した。

### MCP 初期化完了を待つ追加確認

別の実 launcher 起動で `initialize` → `notifications/initialized` → `tools/list` を観測し、初期化後に待機してから UI を取得した。意図的な停止前に MCP startup issue はなく、command marker は 1 行だった。残る表示は同梱 bubblewrap を使う案内。launcher は終了コード 0、専用資源の清掃も成功した。モデル turn と tool 呼出しはこの確認の対象外。

初期化完了を待つ条件では最初の batch の追加 MCP 警告は再現しなかった。ただし、元の警告の原因を確定したわけではない。再開時に保存済み証跡と manifest の SHA-256 を照合した。

## 既存 Claude の未認証起動

2026-09-21 に、ホストの認証を使わない専用 fixture で image を実ビルドし、既定起動と `--agent claude` の両方が Claude Code 2.1.278 のログイン方法選択画面に到達した。Codex 用 MCP の marker は両方で 0。ログイン操作やモデル turn は送っていない。

確認後は harness が所有するコンテナを停止したため、launcher の終了コードは両方 143。正常な対話終了コード 0 の検証ではない。専用 image・network・build context・fixture の清掃は成功し、証跡を private に保存した。最初の試行は ANSI のカーソル移動が表す空白を画面判定が扱えず待機したため中断・清掃し、保存画面で判定の修正を検証してから再実行した。製品の起動失敗ではない。

認証後の Claude 対話は、利用者の指定により日常利用受入に残す。

## 認証済み preflight の計測

使用済み専用 home と同じ実 image で、毎回新しい検査コンテナを起動した。firewall 初期化を含む preflight 全体は 2.227 秒、2.226 秒で、どちらも終了コード 0、同じ空定義 hash、stdout の JSON と stderr の分離を確認した。native 一覧単独の時間でも、空 cache の cold 計測でもない。

停止済み fixture に helper なし HTTP MCP（`https://example.com/c3c-accept-mcp`、firewall で拒否される宛先）を一時追加すると、preflight は 2.275 秒で終了コード 0、stdio 対象 0 件だった。設定は試験後に復元した。HTTP の到達性はローカル command 審査の成功条件ではなく、native が一覧を返せる場合に c3c が全 HTTP 通信の成功を要求するわけではない。この試験は discovery 成功や cloud config 取得の成功を示さない。

## レビューと残項目

Codex による Tasks 1–3 の独立レビューは Critical 0 / Important 0 / Minor 1。Minor は複数の MCP 定義と確認文が 1 行につながる表示不良で、再現試験の失敗を確認してから修正し、launcher 回帰 250/0 を確認した。

README の受入状況と本記録を指定証跡へ照合する Codex の確認限定レビューは Critical 0 / Important 0 / Minor 0。これは文書と証跡の整合確認であり、製品差分全体の再レビューではない。

Fable による実装レビューは利用上限で未完了（not run として扱い、合格判定に数えない）。計画への Fable レビューが成功済みであることと、製品差分のレビューは別である。2026-09-21 の運用に従い、残る受入を整理した後、PR 前に claude-review による Opus レビューを 1 回行い、必要な確認限定巡は同じ session を resume する。途中の Task 単位では再起動しない。

以下は本記録時点で未完了:

- Claude の認証後の対話。専用 fixture で既定/明示起動の未認証画面までは確認済み。2026-09-21 の利用者指定により、認証後は日常利用受入に残す。
- 空 cache の cold preflight は not run。2026-09-21 に利用者が、既存キャッシュを消さず、制約を明記して最終レビューへ進むことを選択した。使用済み認証 home の計測を cold の代用にはしない。cloud config 取得・HTTP discovery 成功の個別観測も not run であり、成功や所要時間の保証はしない。
- CLI ごとの自動 memory の同等性。今回は既存 Markdown を読む経路を検証した。
- 最終レビューと日常利用受入。

日常利用は最終レビュー後、2 project × 各 5 session を候補とする。各 project で Claude 起動、Codex 起動、Codex 再開、Codex read-only、別 CLI への戻しを行い、指示・MCP・共有ノート・履歴が意図どおりか確認する。実施には利用者の実環境を使うため、本 fixture 成功で日常利用まで完了したとは扱わない。認証状態の共通 mount という残余も上記 README/SECURITY-CLAIMS のまま残る。

期限切れ認証の refresh は not run（期限切れを観測していない）。Docker Compose provider の実検証は not run（ホストに Docker がない。出力形式の fixture は検証済み）。今回の実 runtime は IPv4 対象であり、IPv6 の実測成功を主張しない。
