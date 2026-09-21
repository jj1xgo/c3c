# c3c 第0B-5段階: モデル経由の作業先・read-only観測

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 専用ChatGPT認証でモデルターンを実行し、同じthreadのA→B→A移動後のツールcwd・会話継続・指示と設定・書込拒否を区別して観測する。

**Architecture:** 0B-4の通常初期化fixtureを再利用し、専用認証homeだけを新しい検証コンテナへ渡す。使い捨てrepoの相対worktreeで標準App Serverをstdio起動し、標準RPCを使う。製品へ独自クライアントを採用する判断ではない。

**Tech Stack:** Linux/rootless Podman、codex-cli 0.155.1、Python3、Git 2.53。

**Spec:** [段階移行仕様](../specs/2026-09-20-c3c-incremental-design.md) G1/G3/G4、§7。0B-3/4の結果を前提とする。

## Global Constraints

- Codex限定。製品コード変更、実Claude、commit/push/PRなし。既存worktreeは触らない。既存mainの計画置場を継続し、実験は新規fixtureへ隔離する。
- 認証は0B-4の専用homeを継続使用し、ホスト認証・設定・vaultを共有しない。auth本文を読まずコピーしない。所有者/通常ファイル/0600、home/root0700を事前確認。設定ファイルが既知のfile store指定だけであることを確認する。
- 認証homeはrw（標準CLIの更新・履歴保存用）、その他mountは新規fixtureと既存の/dev/null・readonly localtimeのみ。image/main entrypoint固定・通常firewall・capability/ENTRYPOINT/CMD維持は0B-4と同じ。広い権限への再試行・APIキーへの切替は禁止。
- `gpt-6-astra`、provider model fallback=false、approvalPolicy=never、permissions=:read-only。同一threadで最大3ターン、各turn/start応答待ち60秒、応答後の完了待ち180秒、containerプローブ720秒、host wait780秒。失敗時は停止して証跡を残し、モデル/認証の自動再試行をしない。
- プロンプトは使い捨てのmarker読取とattempt.txt書込試行だけを指示。秘密・home・環境変数を読まずネットワークツールを使わない。モデル本文とコマンド結果にはfixtureだけを載せる。ログは0700private領域、ファイル0600。
- MCP/hook定義を追加しない。予期しないserver requestには承認せずエラー応答して中止する。新規MCPをこの検査で安全と判定しない。
- 全終了経路でowner確認後の清掃を試みる。観測ログ/認証modeの異常は記録しても清掃を妨げない。認証homeとfixture証跡は保持する。清掃失敗は結果に残し、成功と報告しない。

## Review Focus

1. 認証本文の露出・既存home混入: 0B-4 stateから専用homeだけを取り出し、mount sourceを限定する。ログを認証homeから分離する。
2. metadataだけの移動を実作業成功と誤認: experimentalRawEvents=trueでfunction_callの生引数を採取し、commandExecutionのcwd/outputとmarker、同一thread IDを照合する。生引数が得られなければ補正有無不明とする。モデルがcwd指定で補正した場合は標準cwd追従と扱わない。
3. 書込未実行を拒否成功と誤認: 各worktreeでプローブ親による非sandbox書込対照を実施し削除。モデルの単一commandExecution・期待cwd・非zero exit・WRITE_ATTEMPT＋Errno30＋ファイル不在を必要とする。不一致/書込成功/逸脱なら次ターンへ進まない。ツール未到達はnot run。
4. 設定・指示の追従の過剰主張: A/Bのproject設定はmedium/high、AGENTSはTAG_A/TAG_B。独立config/read、thread metadata、最終応答のtagを別々に記録。tagだけで自動再読込の内部実装を断定しない。
5. 期限切れ・失敗時の残留: host run finallyで清掃、readonly shimのtimeout、server group停止。承認要求/モデルエラー/想定外writeで次ターンへ進まない。

## 添付と手順

実行添付はprivate `$ART=/tmp/c3c-phase0b5` の `run.py`（起動・待機・finally清掃）、`manage.py`（owner限定の状態採取と清掃）、`probe.py`（fixture・RPC・3ターン）、`process_runner.py`（0B-2の期限付きプロセス群停止）。具体的な実装はこの添付に含む。公開文書に実認証保存先や一時コードを転記しない。

### Task 1: 準備とレビュー

- [x] `python3 -m py_compile /tmp/c3c-phase0b5/*.py`。Expected rc0。
- [x] 対象版の採取schemaでthread/start、settings/update、turn/start、turn/completedの名前/引数を照合。既存0B-3の437 schemaを使い、新規downloadなし。
- [x] セルフレビューと独立Codexレビュー。Critical/Importantを全修正し確認限定巡。最大5巡、同型2巡なら別Codexが収束診断。模擬異常確認は指摘された実際の分岐を対象にする。
- [x] `./lint.sh`。Expected rc0、ホストでCompose検証を含む。

### Task 2: 実測と清掃

- [x] `python3 /tmp/c3c-phase0b5/run.py`。host Podmanへのsandbox権限が必要。Expected: 通常初期化後、同一App Server/threadでA→B→Aの3ターン。
- [x] 各ターンはdefault cwdで `python3 -c` を1回実行するよう依頼。コードはcwd/marker/WRITE_ATTEMPTを出力して相対attempt.txtを書こうとする。workdir指定・cd・昇格は禁止。会話の最初にSESSION_TOKEN=ORCHIDを与え、後続ターンで値を問う。
- [x] Expected: コマンドのcwd/markerがA/B/A、書込はOSに拒否されファイルなし。達しなければ観測事実を不成立/not runに分類。TAG/effortは事前に成功を仮定しない。欠落・差異も結果とする。
- [x] Expected: container終了rcとプローブ完了を採取、finallyでownerコンテナ/network除去、残留ゼロ。認証homeを保持。失敗時も同じ清掃を確認する。

### Task 3: 結果の分類

- [x] 結果文書へ実model、thread/turn、tool cwd、OS拒否、marker、会話token、AGENTS tag、config/thread metadataを分離して記録する。モデルテキストとツール/ファイル証拠が矛盾する場合は成功扱いにしない。
- [x] 新規コンテキストの結果レビューと編集後lint。Critical/Importantを解消。実CLI/TUI内操作、AI自律選択、MCP/hook変更と再承認、再起動後の再開、G4の共有解消はnot runとして残す。

## 適用・引渡し

本セッションでの継続指示によりinline実行を継続する。調査fixtureのため製品RED→GREEN・自動コミットを行わず、構文・失敗分岐・実測ログで検証する。結果が不成立でも、その理由を確定せず広い権限へ変更しない。

`/goal`文面: 「第0B-5計画を実行し、専用認証による3モデルターンと同会話worktree移動を観測、清掃と独立レビューを完了する。既存設定/認証を読まず、製品実装と混同しない。」必要なsandboxはhost Podmanへアクセス可能な実行、networkは既存firewall経由のみ。

実装: Codex — 利用者のCodex限定・継続指示に従い、既存fixtureの具体的な手順を実行する。

## 計画レビュー記録

初回C0/I3/M1。raw引数採取、保存失敗からの清掃独立化（stateはatomic置換、cleanupはstdoutへ直接出力、観測ログの保存はbest effort）、想定外cwd/書込成功/未到達の停止を修正。模擬6ケースPASS。Minorの期限は応答待ち60秒＋応答後180秒と明記。確認限定巡へ渡す。

## 実測で判明したプローブ不備と限定修正

初回runはモデルAターンが完了し、raw custom_tool_call/exec → call_id一致のcustom_tool_call_outputに、既定cwd=A、WORKTREE_A、WRITE_ATTEMPT、Errno30、exit_code1が記録された。しかしcommandExecutionイベントは発行されず、プローブのイベント形式の仮定で停止した（container/runner rc1）。清掃成功、認証home保持。モデル/通信の失敗ではない。

systematic-debuggingで生ログの同一callを追跡し原因を特定した。修正版添付は `/tmp/c3c-phase0b5-r2`。初回の添付・ログ・stateを上書きしない。`event_check.py` を追加し、単一の既知custom execラッパーを静的に解析する。JavaScriptを実行せず、引数はcmd/max_output_tokens/yield_time_msだけ、cmdは要求した文字列と完全一致、workdir指定は拒否。call_idで出力を対応付け、cwd/marker/WRITE_ATTEMPT/Errno30/非zero exitを照合する。未知形式は停止し未確認に分類する。

初回の実ログ再生で成功、書込成功・cwd逸脱・出力欠落・call_id不一致・workdir追加の5改変はすべて拒否した。修正前は新parser未実装で失敗を確認した。検証器の修正をレビューした後、一度だけ新規fixture/threadで3ターンを実行する（モデル/認証失敗の自動リトライではない）。権限・model・認証homeは変更しない。初回Aと修正版A/B/Aのthreadを同一会話と合算しない。

## 終了記録

修正版3ターンと清掃を完了、最終結果レビューC0/I0/M0。設定比較はtrust指定不備によりnot run。受入未達の項目を残した観測結果は [結果文書](2026-09-20-c3c-phase0b5-results.md) を参照。
