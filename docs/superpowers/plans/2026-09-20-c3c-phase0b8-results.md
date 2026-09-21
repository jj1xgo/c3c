# c3c 第0B-8段階: 標準UIのhook trust観測結果

対象: main `93211ed`、固定評価image `28b724cd6363`、codex-cli 0.155.1。製品コードは未変更。[計画](2026-09-20-c3c-phase0b8-hook-trust-validation.md)。

## 観測結果

標準の起動時レビュー画面から個別hookへ進み、event/source/commandを照合して `t` を送った。操作担当はCodexであり、人間がクリックした記録ではない。モデルpromptは送信していない。`/hooks` 文字列を入力する経路は使わず、起動時の Review hooks を使用した。

| 時点 | 独立hooks/listの状態 | marker |
|---|---|---|
| 初回 | v1 untrusted | 直接対照controlだけ |
| 個別UIで信頼登録しCLI終了後 | v1 trusted | controlだけ |
| 次回CLI起動後 | 信頼要求画面なし | controlだけ |
| v2へ定義変更 | v2 modified・hash変更 | controlだけ |
| v2でCLI起動後 | 再レビュー画面、個別画面でもmodified | controlだけ |
| v2を再登録しCLI終了後 | v2 trusted | controlだけ |
| 再起動・終了後の最終確認 | v2 trusted | controlだけ |

**確認できたこと:** 正式UIでの登録、別プロセスへの持続、定義変更時のmodifiedと再レビュー、再登録。

**確認できなかったこと:** 信頼済みv1/v2でもhook実行markerは増えなかった。直接実体の実行は成功しているが、CLI起動のみでSessionStartの実行条件を満たしたか、matcher等の影響かは未確定。従って「未承認定義を確実に遮断した」「hook実行が成立した」とは判定しない。runner rc0は観測・清掃の正常終了であり、計画の実行marker増加というExpected達成ではない。App Serverにbubblewrap未導入・bundled版使用の診断があったが、marker不在の原因とは断定しない。

承認記録の保存先・AIによる書換え可能性は **not run**。実認証homeの探索・認証本文の読取は行わず、G3の偽造耐性を満たした扱いにしない。再開・モデルturnを伴うhook動作もnot run。

## 実行履歴・検証

- 初回: 個別画面で必要な `t` がallowlist外と判明したため、登録せずfinish。runner/container/cleanup rc0。
- r2: 初回標準TUIが専用configに `tui.model_availability_nux.gpt-6-astra=1` を追加し、起動前の完全一致検査が停止。runner rc1、container未作成、清掃rc0。認証情報は保持。cleanupのauth_exists=falseはstateへauth_homeを設定する前の停止によるもので、認証削除を意味しない。
- r3: 上記既知UI設定を含むTOML辞書の完全一致へ変更。未知設定は拒否。runner/container/cleanup rc0、完了マーカーあり、所有コンテナ/network清掃、imageと専用認証home保持。
- 実行前独立レビュー: 初回Important 2（画面復元、承認前marker観測）を修正、確認限定巡C0/I0/M0。`t`追加と既知UI設定の各限定差分もC0/I0/M0。
- Python構文、VT画面消去・セッション切替回帰PASS。製品ビルド/回帰テストはnot run（製品変更なし）。文書最終lintはhost実行rc0・lint OK（Composeを含む）。独立結果レビューC0/I0/M0。観測記述への合格であり、G3のImportant 3件は未解消。
- private証跡: `.claude/test-results/c3c-0b8-hook-trust-validation/`。142件のregular artifactをSHA256一致で退避し、最終markerも保存。認証homeは退避対象に含めない。

## 第1段階へ進むために残る判断

独立G3レビューは **Critical 0 / Important 3 / Minor 1**。以下は未解消の設計事項であり、今回の観測成功とは分ける。

1. MCPの登録保存と実行許可を分け、起動後の追加・変更・再読込時にも承認済み定義との一致を要求する方式を決める。起動時だけのハッシュ照合では不足する。
2. hookの正式登録に加え、採用モードでAIが承認を偽造できない境界を確認する。今回確認したUIの持続だけでは代用できない。
3. native managed設定の照合範囲を既存TOFUと同等と仮定しない。公式のMCP identityはcommand文字列型ではargsを検査せず、構造型でもcwd/env/env_varsを検査しない。[公式Managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)。HTTPの `http_headers_helper` はローカルcommandの経路を持つため、HTTPなら通信制限だけで十分とは扱わない。対象0.155.1での対応は未確認。[公式Reference](https://learn.chatgpt.com/docs/config-file/config-reference)。managed hooksのみ許可する方式はuser/project/pluginの標準運用に影響するため、無断で採用しない。[公式Hooks](https://learn.chatgpt.com/docs/hooks)。

計画確定に必要な確認と実装後の受入を分ける。認証・モデル応答・worktree移動の追加反復は不要。通常起動/再開、refresh、vault、skill/memory、Claude回帰、日常利用は第1段階の実装後受入とする。G1共通設定とG4全面分離は既定の後続段階に残す。

次は無認証fixtureで承認記録とMCP再読込の最小確認を行い、標準機能の限界を具体的にして計画へ戻す。追加モデル呼出しは不要。即時反映が両立しない場合だけ「登録変更は承認後の次回起動で有効」という操作差を利用者判断へ戻す。15時JST以降は利用者申告によりClaude枠回復予定で、計画確定時の独立Claudeレビューを再開できる。
