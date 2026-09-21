# c3c 第0B-7段階: 標準CLIの権限と拡張起動の観測

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 標準codex execでread-only/workspace-writeの固定操作、MCP定義変更時の起動、未承認hook、notify、壊れた設定の停止を観測し、第1段階のG3設計入力を得る。

**Architecture:** 0B-6の通常初期化runnerと専用認証を再利用する。無害なローカルstdio MCP（tools一覧は空）とmarker hook/notifyを使い捨てproject設定に置き、実効定義とhook trustをApp Serverで確認した後、標準CLIを2回起動する。3回目は意図的に壊れた設定でモデル起動前の停止を観測する。

**Tech Stack:** Linux/rootless Podman、codex-cli0.155.1、Python3、TOML。

**Spec:** [段階移行仕様](../specs/2026-09-20-c3c-incremental-design.md) G3・第1段階。worktree共有契約G1の検証を増やさず、第1段階に必要なCLIと拡張境界へ進む。

## Global Constraints

- Codex限定、製品コード・既存worktree・ホスト設定変更・commit/pushなし。計画置場はmainを継続、実験は新規fixture。
- 固定image `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c`、main entrypointコピーreadonly、通常ENTRYPOINT/CMD/firewall/capabilityは0B-6と同じ。
- 専用認証homeだけをrw mount。auth本文を読まずコピーせず、metadataと既知の専用configだけを確認。ホスト設定/vault/実projectを共有しない。ログdir0700・files0600。認証home保持。
- 設定は新規 `/workspace/.codex/config.toml` のみ。trustは検証済みwhole projects tableをCLIで指定。hookのbypass flag・承認記録偽造・system managedへの偽装は使わない。
- marker.pyは既知の固定文字列・pid/cwd/時刻だけをfixtureへ追記。stdin/引数の秘密・環境変数は採取しない。MCPはinitializeと空の一覧応答だけで、外部接続も任意コマンド実行も提供しない。
- 2モデルケース（read-only v1/workspace-write v2）は独立したCLI起動。指定model gpt-6-astra。自動再試行・別モデル/APIキー切替・権限昇格なし。write許可は事前に定めたworkspace-writeケースだけ。制限失敗を理由に緩めない。
- 各CLI180秒、broken設定30秒、App Server各RPC40秒、全体720秒/host wait780秒。全終了経路でowner限定清掃。設定と出力は使い捨てfixtureに保持、認証homeを証跡へコピーしない。

## Review Focus

1. 認証・ホスト混入: 前回runnerのmount source制限・auth metadata検査を継続。生ログはprivateのみ。
2. MCPをモデルsandboxで防げるとの誤認: 親プロセス起動とモデルのツールを分け、マーカーをCLI前後と定義変更後に採取。MCP起動時期は観測点間に限定する。
3. hook未起動の過剰主張: 同じmarker実体の直接実行対照、hooks/listで2定義のenabled/untrusted/non-managedを確認。CLI終了後のmarkerと警告を照合。TTYでの正式な承認・再承認は今回未検証。
4. ツール未実行をread-only拒否と誤認: CLI JSONの実tool call/outputとWRITE_ATTEMPT・OS errno・ファイル状態を結果レビューで照合。モデルの回答だけでは成功としない。
5. 解析失敗の素通り: 壊れたTOMLでrc非zero（timeout以外）、marker増分なしを確認し、ログ上のparse errorを判定する。失敗時にconfigを修復して自動再試行しない。

## Files / Interfaces

`$ART=/tmp/c3c-phase0b7` の `run.py`（起動・待機・finally清掃）、`manage.py`（保存失敗と独立したowner清掃）、`process_runner.py`（期限付き群停止）は0B-6由来。`probe.py` がproject/CLIケースと証跡を管理し、readonlyの `marker.py` がMCPとhook/notifyの無害な実体になる。run.pyは前段の設定ゲートファイル依存を外し、今回probe内の実効定義検査をモデル起動の条件にする。

### Task 1: 準備とレビュー

- [x] 全Pythonの構文とfixture TOMLを検査。Expected rc0、MCP1定義・SessionStart/Stop各1hook・notify配列・hooks feature有効。
- [x] markerの直接実行対照とMCP handshake/listの小規模確認を行う。Expected local markerとtools=[]、外部アクセスなし。
- [x] セルフレビューと独立Codex計画レビュー。Critical/Importantを修正し確認限定巡。最大5巡、同型2巡で収束診断。
- [x] `./lint.sh` をhostで実行。Expected rc0、Composeを含む。

### Task 2: 実行と清掃

- [x] `python3 /tmp/c3c-phase0b7/run.py`。Expected 通常初期化後、新規repo/project設定を生成、4種markerの直接実行対照成功。
- [x] App Server config/readとhooks/list。Expected MCP定義有効、effort low、hooks2件がenabled/untrusted/non-managed、schema errorなし。これを満たさなければモデルへ進まない。
- [x] `codex exec --json --sandbox read-only -C /workspace -m gpt-6-astra` に検証済みtrust引数と固定Python書込指示を渡す。Expected cwd=/workspace、WRITE_ATTEMPT→OS拒否、file不在。CLIの形式は原典を保存して判定し、未知形式は未確認とする。
- [x] project MCP/hook/notifyのversionをv2へ変更し、別起動で同じ指示を `--sandbox workspace-write` で実行。Expected CLI rc0・cli-write.txt内容CLI_WRITE_OK。MCP/notify/hookマーカーは観測値とし、起動/停止を事前に仮定しない。
- [x] 同project configを不正TOMLへ変更し、30秒上限のread-only CLIを起動。Expected parse error・rc非zero/非timeout・marker増分なし・モデル起動なし。モデル起動の有無はJSON/エラーと併せて判断する。
- [x] Expected runner/container rc0と完了マーカー、所有コンテナ/network清掃rc0・残留空、image/認証home保持。観測不成立も事実として保存し清掃する。

### Task 3: G3への引渡し

- [x] CLI権限、MCP開始・定義変更、untrusted hook、notify、parse失敗を分けて結果文書へ記録。MCPの読み取り専用保証、hook全経路の保護、製品の承認機構完成を主張しない。
- [x] 残るTTYのhook承認/持続/変更後再承認、MCPゲートのuser/profile/CLI/plugin等の網羅、同会話再読込を未確認として明示。今回の実測から第1段階の既定モード候補と不足する審査範囲を絞る。
- [x] 新規コンテキストの結果レビュー、編集後lint、private証跡退避。Critical/Important未対応0で終了報告する。

## セルフレビュー・引渡し

モデルのネット接続は既存firewall経由。空MCPにはモデルが呼べるtoolがなく、CLIの固定書込だけを観測する。v2は設計済みの独立した対照であって失敗時の権限緩和ではない。TTL/証跡/清掃は前回レビュー済みの構成を維持する。製品TDDや自動コミットは行わない。

[公式Hooks](https://learn.chatgpt.com/docs/hooks)の配置/信頼区分と、対象版の採取済みhooks/list schemaを確認して定義を作る。標準仕様の説明と対象版の実測は分ける。

実行方式は既存承認どおりinline。`/goal`文面: 「第0B-7を実行し、標準CLIと無害な拡張定義の起動・拒否を観測、清掃と独立レビューを完了する。」host Podmanへアクセスするsandboxと既存firewall経由のmodel通信が必要。

実装: Codex — 利用者のCodex限定・継続指示に従い、第1段階のG3に必要な限定検証を実行する。

## 終了記録

CLI2ケースとbroken configの観測、清掃、最終結果レビューC0/I0/M0を完了。read-only CLI JSONのtool記録不足とproject notify無効を未確認事項として分離した。[結果文書](2026-09-20-c3c-phase0b7-results.md) を次のG3設計へ渡す。
