# c3c 第0B-3段階: 作業先と設定層の無認証観測

日付: 2026-09-20。source commit `93211ed80ad3e4b4231f40ba5096df6924e76f34`、codex-cli 0.155.1。
計画: [0B-3計画](2026-09-20-c3c-phase0b3-session-validation.md)。実行と独立レビューはCodex。

## 結果

**同じApp Server・同じthread IDで、cwdのmetadataをA→B→Aへ変更できた。** 標準RPC `thread/settings/update` の応答と `thread/read` の値を確認した。モデルターン、CLI/TUIの操作、AI自身による選択・移動は実行していない。

| 観測 | 結果 |
|---|---|
| 対象版schema | `thread/settings/update(threadId,cwd)` を含む437 schemaを対象binaryから採取 |
| 無認証 | `account/read(refreshToken=false)` はaccount=null、requiresOpenaiAuth=true。終了時auth.json不在 |
| 未信頼Aのconfig/read | userのlowが有効。AのmediumはdisabledReason付きで無視され、repoをtrustedにするよう示された |
| fixtureのrepo/A/Bをtrustedへ変更後 | Aはmedium、Bはhigh。user設定ホームは同一 |
| thread/start(A) | reasoningEffort=medium、cwd=A、runtimeWorkspaceRoots=[A]、profile=:read-only |
| settings/update→thread/read | 同一thread IDを保ち、cwd=A→B→A |
| 存在しないcwd | settings/updateは成功応答し、thread/readもその存在しないパスを返した |
| 終了 | 完了マーカーあり、server rc0、コンテナprobe rc0、runner rc0、清掃rc0 |

無効パスの受理は、実作業が成功することを意味しない。実在確認やGit worktreeとして利用できるかの判定を、RPC成功応答で代替できないという観測である。

## 条件と根拠

既存image `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c`。network none・host mountゼロ・User=node・cap追加なし・privileged=false・security_opt追加なし。製品ENTRYPOINTを維持したがCMDを検査Pythonへ差し替え、通常entrypointは通していない。

Git repository、相対リンクのworktree A/B、user/project configはすべてコンテナ内の新規領域。system Git設定とuser Git設定を無効にした専用環境で作成した。実設定・認証・vault・既存worktreeを使っていない。

証跡: `$CC/.claude/test-results/c3c-0b3-ed145cfdcd1d/`。

- 実行別ディレクトリ `c3c-0b3-ed145cfdcd1d/` の `inspect.log`、`probe.log`、`result.json`、清掃ログと実行時添付。
- `schema-bundle.json`、helpログ、`methods.json` が対象版の一次情報。
- `probe.log`の応答id 2が認証状態、3/4/5が設定取得、6がthread作成、8/10/12がA/B/A、14が存在しないcwdのmetadata。
- stderrは実行中からホストログへ流し、失敗でも終了診断を残す。RPC失敗・作成失敗・清掃失敗の模擬回帰確認3件は成功。
- `remove`、`remaining`、`image-retained`はrc0、所有コンテナ一覧は空。コンテナ内fixtureも削除済み。help/schema採取用と本実行のownerラベルによる最終照会も空、image existsはrc0。

## 設計への引渡し

1. **操作の候補はあるが、CLI側の接続方法は未確認。** 標準App Serverの機能確認を、素のCLIでAIが使える機能の証明へ拡張しない。独自クライアントの製品採用は決めていない。
2. **設定ホームの共有だけでは設定共通化にならない。** 今回の異なるproject設定は同一user homeでもA/Bで実効値が変わった。G1が要求する共有対象とproject上書きの契約は未確定。
3. **取得値とthreadへの再読込は別。** config/readは明示cwdでの独立照会であり、移動後に指示・skill・MCP・sandbox許可範囲が更新された証拠ではない。
4. **trust記録はfixtureのuser configから変更できた。** この観測だけでMCP/hookのすべての承認経路や偽造可否を確定しない。プロジェクトtrustと、実行定義の人間による承認は分けて検証する。

実認証方式は利用者が**ChatGPT契約枠での新規ログイン**を選択済み。専用CODEX_HOMEへのdevice loginを次に準備し、ホストの認証はコピーしない。認証後のモデル実行は、別の具体的な観測手順と必要な境界検証を確定してから行う。

## 検証状態

構文確認、失敗時証跡の模擬3ケース、実測は成功。計画レビューは初回C0/I1/M0（失敗時の記録）、修正確認巡C0/I0/M0。ホストでの `./lint.sh` は警告ゼロで成功（sandbox内Compose検証は権限制約のためホストで実行）。新規コンテキストの結果レビューはC0/I0/M1。Minorは「B移動後のthreadがmediumを保持し、独立config/read(B)のhighと異なる観測を追記するとよい」で、改善提案として保留。初回退避33ファイルはSHA-256一致、終了記録は追加退避する。

実認証・モデル応答、標準CLI/TUI内の作業先変更、同一会話のツール/指示/MCP/sandbox追従と再開、通常entrypoint経由の本RPC操作は **not run**。G1/G3/G4/§7の受入完了ではない。

## 公式資料

[App Server](https://learn.chatgpt.com/docs/app-server)はcwdを伴う操作の背景資料。実際の名前・引数は採取した0.155.1 schemaで確認した。[CLI slash commands](https://learn.chatgpt.com/docs/cli/slash-commands)の一覧だけから、CLI側で不可能と断定しない。[Authentication](https://learn.chatgpt.com/docs/auth)は専用保存先とdevice loginの準備に参照した。今回の実認証成功の根拠ではない。
