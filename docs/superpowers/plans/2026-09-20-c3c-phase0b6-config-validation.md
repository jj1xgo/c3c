# c3c 第0B-6段階: trust指定の修正と設定追従の観測

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 0B-5で未成立だったproject設定の有効化を確認し、同じ会話でのworktree移動後の設定metadataを観測する。

**Architecture:** 最初に無認証・network none・host mountなしのコンテナで同じtrust指定を検査する。その成功後だけ0B-5と同じ通常初期化・専用ChatGPT認証で3ターンを行う。trustはCLIの `projects` 全体へTOML inline tableを渡し、専用homeの設定ファイルを変更しない。

**Tech Stack:** Linux/rootless Podman、codex-cli 0.155.1、Python3、Git2.53。

**Spec:** [段階移行仕様](../specs/2026-09-20-c3c-incremental-design.md) G1/G3。G1の設定共通化と第1段階の日常利用前提を混同しない。0B-5結果の設定比較not runを引き継ぐ。

## Global Constraints

- Codex限定・既存mainの計画置場を継続、実験は新規fixture。製品コード/既存worktree/ホスト設定変更、commit/pushなし。
- image固定 `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c`。無認証検査はhost mountなし/network none/CMDのみ検査へ変更。実認証検査は0B-5と同じ通常ENTRYPOINT/CMD・readonly main entrypointコピー・firewall・既定capabilityを維持する。
- 認証は0B-4専用homeを継続使用。auth本文を読まずコピーせず、metadataと既知の専用configだけを確認する。ホストの実home/vaultを共有しない。ログdir0700・files0600、認証home保持。
- 無認証の設定ゲートに成功しなければ実認証を起動しない。さらに実認証プロセス自身もconfig/readの正確なtrustキー・実効medium/high・project layer有効をassertしてからthread/startする。
- モデルはgpt-6-astra、fallbackなし、never/:read-only、最大3ターン。応答待ち60秒＋応答後180秒、プローブ720秒/host wait780秒。モデル/認証エラーの自動リトライ、昇格、firewall無効化なし。
- 実モデルの固定コマンド・AGENTS/tag・会話token・rawイベントの静的判定器は0B-5修正版と同じ。未知ツール/補正/成功書込/OS拒否未確認なら停止。MCP/hook定義追加なし。
- owner確認後のfinally清掃。ログ保存失敗は清掃を妨げず、認証homeは保持する。無認証と実認証の資源・結果を分ける。

## Review Focus

1. quoted-path不備の再発: `projects={"/workspace"={trust_level="trusted"},...}` の実効キー完全一致、A medium/B high、disabledReasonなしを両段階で検証。
2. 認証の混入: 無認証はhost mountゼロ・新規CODEX_HOMEでauth不在を確認。実認証だけ既存専用homeを使用。
3. config/readとthread設定の混同: 独立照会・移動前後thread/readを記録し、モデルが使う内部effortを回答文や速度から推測しない。
4. 失敗時の過大主張: 実モデルは既存のraw判定器でcwd/OS拒否を検証。違いがなくても、任意設定/MCP/hookの追従成功と拡張しない。
5. 清掃と範囲: 無認証runnerも保存と独立したcleanupを実行。モデル実測のrunner/manage/判定器は前回レビュー済み版を、artパスと観測箇所だけ変更して使う。

## Files / Interfaces

- `$PREFLIGHT=/tmp/c3c-phase0b6-preflight`: run.py/probe.py/manage.py/process_runner.py。run.pyはnetwork none・mountなしの専用コンテナを作り、設定ゲートを実行して清掃する。result.jsonのprobe_rc=0/cleanup_rc=0/trust_gate=trueが実認証runnerの入力。
- `$ART=/tmp/c3c-phase0b6`: run.py/probe.py/manage.py/process_runner.py/event_check.py。0B-5修正版から派生、trustの全体table指定とconfig/readゲート、各ターン完了後thread/readを追加。前回の添付・証跡は変更しない。

### Task 1: 計画・無認証ゲート

- [x] `python3 -m py_compile /tmp/c3c-phase0b6/*.py /tmp/c3c-phase0b6-preflight/*.py`。Expected rc0。
- [x] 添付と仕様をセルフレビュー、独立Codexレビュー。Critical/Importantを解消して確認限定巡。最大5巡、同型2巡で収束診断。
- [x] `./lint.sh` をhostで実行。Expected rc0、Composeを含む。
- [x] `python3 /tmp/c3c-phase0b6-preflight/run.py`。Expected 無認証で正確なtrustキー、A medium/B high、layer有効、auth不在。rc0と完了マーカー。ownerコンテナ清掃、network noneのため専用networkなし、image保持。

### Task 2: 認証済みモデルによる観測

- [x] Task1成功後 `python3 /tmp/c3c-phase0b6/run.py`。Expected 同じconfigゲートが成功してから、同threadで3ターンA→B→A。
- [x] settings/update直後と各turn完了後のthread/readを照合。Expected 値を採取できること。A/Bのeffortが切り替わるか保持されるかは観測対象とし、事前に成功条件へ置かない。
- [x] 既存判定器によりツールcwd A/B/A・OS拒否・file不在を確認。Expected rc0、完了マーカー、ownerコンテナ/network残留ゼロ。失敗時も清掃確認、追加実行なし。

### Task 3: 結果と次の実装範囲

- [x] 設定取得・thread metadata・ツール観測を分けた結果文書を作る。実際のmodel requestのeffortは未採取なら未確認と明記する。CLI/TUIや自律移動の完成とはしない。
- [x] 第1段階へ残るG3のMCP/hook/既定権限検証と、後続G1の設定共通化の課題を分けて引き渡す。必要検証の全てを第1段階前へ拡大しない。
- [x] 新規コンテキストの結果レビュー、編集後lint、清掃と証跡退避を確認。Critical/Important未対応0を報告条件とする。

## セルフレビューと引渡し

0B-5の失敗したキー生成をTOML table全体で置き換えた。両段階で実効値を検査し、実認証実行の可否を機械的に接続する。前回の成功済み12判定器ケースは判定器の変更がないため反復しない。製品実装ではなく調査のため製品TDD/自動コミットは行わない。

実行方式は既存承認どおりinline。`/goal`文面: 「0B-6の無認証trustゲートと成功後3モデルターンを観測し、設定比較結果・清掃・独立レビューを完了する。」host Podmanへのsandbox権限が必要、無認証network none、実認証は既存firewall経由のみ。

実装: Codex — 利用者のCodex限定・継続指示に従い、前回のプローブ不備と未確認項目を限定検証する。

## 終了記録

無認証ゲートと実認証3ターン・清掃を完了。計画/結果レビューともC0/I0/M0。取得設定Amedium/Bhighに対し、全thread metadataはmediumを保持した。[結果文書](2026-09-20-c3c-phase0b6-results.md) に範囲と未確認事項を記録した。
