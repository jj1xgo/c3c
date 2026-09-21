# c3c 第0B-6段階: trust修正・設定追従の結果

日付: 2026-09-20。source commit `93211ed80ad3e4b4231f40ba5096df6924e76f34`、codex-cli 0.155.1。
計画: [0B-6計画](2026-09-20-c3c-phase0b6-config-validation.md)。実行・レビューはCodex。

## 結果

**trust指定を修正し、worktreeごとのproject設定を有効にできた。一方、同じ会話を移動してもthreadのreasoningEffortは開始時のmediumを保持した。**

| 観測 | 結果 |
|---|---|
| trustキー | projects全体をTOML inline tableで渡し、引用符がキーに混入しないことを確認 |
| 無認証ゲート | host mountゼロ・network none。A medium、B high、両project layer有効、auth不在。probe/cleanup rc0 |
| 実認証側のconfig/read | モデル起動前に同じキーと有効layerを検査、A medium・B high |
| thread/start(A) | model=gpt-6-astra、reasoningEffort=medium、never/:read-only、provider fallbackなし |
| thread/read | A開始後・B移動直後/ターン後・A帰還直後/ターン後の全てでreasoningEffort=medium |
| モデルのツールcwd | 単一threadの3ターンでA→B→A。raw引数にworkdir指定・cd・昇格なし |
| 指示・会話 | TAG_A→TAG_B→TAG_A。後続2ターンで最初に与えたORCHIDを回答 |
| read-only | 3回ともWRITE_ATTEMPT後のErrno30・exit1、attempt.txt不在。非sandbox書込対照は成功 |
| 終了 | server/container/runner rc0、完了マーカー。所有コンテナ/network清掃rc0、残留一覧空、image保持 |

モデルAPIへ送った内部のreasoning effortそのものは **not run（未採取）**。返答速度やモデルの自己申告から推測しない。今回確定したのは、独立config/readと、実ターンを挟んだthread metadataの差である。設定全般が保持される／再読込されないと一般化しない。

## cwd metadataの確認

Bへsettings/update直後はenvironments.cwd=B、thread.cwd=A。Bターン完了後は両方Bになった。Aへ戻した直後もenvironments.cwd=A、thread.cwd=Bで、Aターン完了後は両方Aになった。0B-5の観測を、ターン後のthread/readで補った。現在の作業先をトップレベルthread.cwdだけで即時判定しない。

## 条件と範囲

無認証側は検査CMDで実行し、製品entrypointは通していない。実認証側は0B-5同様、固定imageへmain entrypointコピーをreadonly指定して通常firewall初期化を通した。実Claudeを起動せず、末尾の呼出しを検査shimへ渡した。製品imageを新規buildした試験ではない。

0B-4で作った専用ChatGPT認証homeだけを継続使用した。auth本文を読まずコピーせず、認証metadataに異常なし。ホスト設定・vault・実プロジェクトはmountしていない。専用認証homeを保持した。

検証器のraw形式・OS拒否判定は0B-5修正版から変更せず、前回の12ケースを反復していない。今回の静的構文確認、TOMLキー検査、実効設定ゲートと実モデル3ターンを実施した。プローブ修正後のモデル再試行は行っていない。

## 次の実装範囲への引渡し

- **第1段階前のG3:** Codexの既定権限モード、MCPの実効設定源と承認、hook trustの不足を優先する。通常初期化下の認証・応答・read-only固定コマンド拒否は今回までで確認済み。ただしMCP/hookの安全性まで合格にしない。
- **第1段階の実装と受入:** CLI選択入口、通常起動・停止/再開、認証refresh、指示/skill/memory/履歴、vault、Claude既存経路、実プロジェクト利用はその段階の計画で扱う。全てを製品コード編集前の必須調査へ膨らませない。
- **第3段階のG1:** repo共通設定とproject上書きの契約を定める際、本結果を使う。設定homeの共有やcwd移動だけでは、設定共通化や全設定追従の保証にならない。今回の一例だけで標準CLIとの両立不能とも断定しない。

標準CLI/TUI内の移動、自律worktree選択・作成、MCP/hook変更時の再承認、書込可能モードの移動、再起動後の会話再開、G4の設定共有解消は **not run**。製品コードは未変更。

## 証跡・検証状態

privateの無認証/実認証実行領域に、添付・config/RPC生ログ・inspect・rc・清掃結果を分離して保存。summary.jsonは補助で、生ログを正本とする。認証homeは証跡から分離したまま。

計画レビューC0/I0/M0、構文・TOML確認・実行前host lint成功。最終結果レビューC0/I0/M0。編集後のhost `./lint.sh` はComposeを含めrc0、警告ゼロ。regular証跡87件を `$CC/.claude/test-results/c3c-0b6-config-validation/{preflight,authenticated}/` へ退避してSHA-256一致を実行側で確認し、完了したlintログを追加保存した。認証homeは走査・コピーしていない。
