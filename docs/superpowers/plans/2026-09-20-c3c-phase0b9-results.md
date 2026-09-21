# c3c 第0B-9段階: 起動時審査とnative状態の境界確認結果

対象main `93211ed`、固定評価image `28b724cd6363`、codex-cli 0.155.1。[計画](2026-09-20-c3c-phase0b9-boundary-validation.md)。製品コードは未変更。

## 無認証実測

起動前inspectでmount 0・network none・User node・追加capabilityなしを確認。新規のコンテナ内CODEX_HOMEだけを使用し、auth.json不在を開始・終了時に確認した。モデルturnは送っていない。通常entrypoint/firewall初期化はnot run（CMD置換による無認証の機能観測で、以前の通常起動検証とは分ける）。

| 観測 | 結果 | 限界 |
|---|---|---|
| config/read・hooks/listだけの専用server | 応答後5秒観測し、停止完了後もmarker 0 | このfixture/期間で未観測。全plugin・全設定・無期限の無副作用を保証しない |
| 別serverのthread/start・status取得 | stdio v1とHTTP helper v1のmarkerあり | tool呼出しや人間の承認入力なし |
| v2保存→reload→同じthreadのstatus取得 | v2 stdio/helperの新PID markerあり | この操作列で反映。reload単独とstatus取得の寄与は分離していない |
| さらに新threadを開始しstatus取得 | v2の新PID marker、serverInfo.version=v2 | 各段階のmarker増分で確認し、履歴全体のv2存在だけでは判定していない |
| 新規user configのhooks.stateへ同一UIDでhashを書き、別serverでhooks/list | untrustedからtrustedへ変化 | Codex sandbox外のfixture操作。workspace-write内のAIから書ける証明ではない |
| trusted hookを含むthread/start | hook marker 0 | 実行確認は未達。c3c安全性の肯定材料にしない |

HTTP helperは `http://127.0.0.1:9/mcp` に対する接続失敗の前に、空のheader JSONを返すローカルmarkerを実行した。したがって対象0.155.1でもHTTP MCPがローカルcommandを含みうる。HTTPの分類だけで起動時審査対象から外してはいけない。stdioとhelperのmarker数は最終で各7。status取得を含む操作列で複数回起動しており、起動時の受動的な設定取得へ `mcpServerStatus/list` を流用しない。

native hook trustは、通常の設定内のhash状態を根拠に扱われることをfixtureで確認した。正式UIで信頼登録したという人間の来歴は証明しないため、c3cの起動確認省略の根拠には使用しない。

## G3レビューの訂正と結論

前回G3レビューのI1（起動後の全変更を強制審査）・I2（native hook trust全体の偽造耐性必須）は、既存Claude TOFUの保証から広げすぎた解釈だった。独立レビュアーが現行launcher・entrypoint・READMEと比較して訂正した。

[仕様G3](../specs/2026-09-20-c3c-incremental-design.md)を以下の契約へ明確化した。

- c3cの起動時に実効MCPのcommand経路を審査し、初回・変更後の人間確認と、確認省略に使う独立承認記録の保護を行う。
- native trust状態を、その独立承認記録の代わりにはしない。managed MCP identityの部分一致も、定義全体の承認と同等とは扱わない。
- 稼働中の全設定変更・再接続を監視する新機構は追加しない。標準CLIの登録・保存・再接続を維持し、実行中の変更も反映されうるという限界を説明する。
- 外側の通信/権限境界と、既存の保護対象ホスト設定は維持する。Codexのworkspace-writeを第一候補とし、許可済みの作業が成立しない具体的な理由が出た場合だけ広いモードを比較する。

これにより「標準CLIの全内部状態を保護する」ための追加研究を第1段階の前提にしない。詳細実装計画では、起動時の有効な設定源、コマンドを実行せず解決する方式、hashへ含む定義、c3c独立承認の保存・照合、不明な経路の拒否を確定する。起動時審査の網羅性を今回の小さなfixtureだけで達成済みとはしない。hook実行条件と通常起動/再開・refresh・vault・Claude回帰は実装後受入に残る。

## 検証と記録

- Python構文PASS。実行前独立レビューC0/I2/M1→修正後確認C0/I0/M0。
- metadata専用server分離・停止後観測、段階別marker差分/status判定、無認証用の清掃表示へ修正。
- runner probe rc0、cleanup rc0、完了マーカーあり。所有コンテナ削除後の残留照合を実施。実認証homeは一切参照していない。
- 計画lintはhostでrc0・lint OK。独立結果/境界レビューはC0/I0/M1（節番号重複のみ）→修正と補足の確認限定巡C0/I0/M0。結果/仕様のhost lintはrc0・lint OK。
- private証跡は `.claude/test-results/c3c-0b9-boundary-validation/`。本試験と補足の72 regular artifactをSHA256一致で退避した。製品ビルド・回帰テストはnot run（製品変更なし）。

一次資料: [公式App Server](https://learn.chatgpt.com/docs/app-server)、[HTTP helper](https://learn.chatgpt.com/docs/config-file/config-reference)、[managed照合範囲](https://learn.chatgpt.com/docs/enterprise/managed-configuration)。上表の判定は対象版の実測を根拠とする。

## 第1段階の候補を絞った補足

公式tag `rust-v0.155.1` のcommit `be2951ea34f0d295ed0becf97079f92fa5f6950e` を読んだ。`mcp list --json` はactive pluginを含む設定済みMCPを列挙し、stdioはcommand/args/env/env_vars/cwdを返す。HTTP helperがある場合は認証状態確認でhelperを実行しないが、本文を `<redacted>` にする。helper無しHTTPではOAuth discovery通信があり得る。[公式対象ソース](https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/cli/src/mcp_cmd.rs#L674)

同じv1 fixtureを使う別の無認証・network none・mount0コンテナで、この一覧だけを実行した。stdio定義が得られ、HTTP helperは `<redacted>`、marker 0。probe/cleanupともrc0。この補足にはplugin fixtureを含めておらず、plugin列挙は静的根拠であり、実物fixtureの受入を第1段階へ残す。

これを踏まえた第1段階候補は、native一覧で取得できるstdioの実行定義を審査し、enabled HTTP helperなど完全な定義が取得できない場合は明示的に拒否する方式である。一覧そのものを全MCPの完全な実効定義や無通信APIと呼ばない。生JSONにはenv値等が含まれるため製品のログに保存せず、auth_statusを承認hashから除外する。helper拒否を含む製品設計は [第1段階詳細計画](2026-09-20-c3c-phase1-codex-launch.md) のレビュー対象で、補足probeだけで承認済みとはしない。

SessionStartのmarker不在もソースで整理できた。対象版は保留したSessionStartを作業turn内で消費するため、CLI画面やthread/startだけの今回の観測と整合する。[対象turn処理](https://github.com/openai/codex/blob/be2951ea34f0d295ed0becf97079f92fa5f6950e/codex-rs/core/src/session/turn.rs#L320)。実行成功自体は引き続き実装後の受入で確認する。
