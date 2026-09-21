# c3c 第0B-8段階: 標準UIによるhook trustの持続・変更観測

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 検証専用SessionStart hookを標準 `/hooks` UIで信頼登録し、CLI再起動後の実行と、定義変更後の未実行・再登録を観測する。

**Architecture:** 0B-7の通常初期化runner内で標準CLIをPTY起動する。実行担当はprivateの端末記録を読み、許可済みのキーだけをreadonly mount内の制御ファイルで渡す。モデルへの指示は送信しない。UI操作と独立したhooks/list・markerを照合する。

**Tech Stack:** Linux/rootless Podman、codex-cli0.155.1、Python stdlib PTY/JSON/RPC。

**Spec:** [段階移行仕様](../specs/2026-09-20-c3c-incremental-design.md) G3・第1段階。正式な信頼登録・持続・変更時の状態を調べる。承認記録の偽造耐性は別途検証が必要。

## Global Constraints

- Codex限定、製品コード・既存worktree・ホスト設定・commit/pushは変更しない。固定image/main entrypoint readonly指定・通常firewall・capabilityは0B-7を継承。
- 認証は0B-4専用homeを継続使用。auth本文を読み出さずコピーしない。ログとTUI表示はprivate dir0700/files0600、公開文書へaccount表示等を転記しない。
- 定義は新規 `/workspace/c3c-hook-probe/.codex/hooks.json` のSessionStart1件だけ。実体はreadonly `/runtime-probe/hook-marker.py` で、version/cwd/timeだけを新規fixtureへ追記する。stdin/env/認証情報を読まない。
- 承認操作はこの既知の無害な定義に限定。bypass flag、信頼ファイルの偽造、managed/system偽装は使わない。UI表示でevent/source/commandを照合できなければ登録せず停止して記録する。
- 送信キーは `/hooks`（Enterを含まない）、Enter、上下矢印、Escape、Ctrl-C、個別hook画面での `t` だけ。slash候補を確認してからEnterを送る。通常のモデル指示は送らない。未知画面でEnterを連打しない。
- 制御はfixture内のJSONファイルのみ。Podman socket・daemon・公開portなし。hook trustの製品実装にこの制御経路を採用するものではない。
- 制御期間600秒、外側probe720秒/host wait780秒。App Server RPC30秒。期限切れ・想定外終了時もfinallyでPTYプロセス群停止、owner限定コンテナ/network清掃、認証home保持。
- dedicated homeには標準UIが作る検証用hook信頼記録が残りうる。logout/認証削除/承認記録の手書き削除は行わず、後続検証でこの専用sourceとhashを区別する。

## Review Focus

1. 表示と対象の混同: SessionStart1件、source=project、既知command、untrustedのhooks/listを開始条件にする。UIの信頼操作前にも同じ定義を照合する。
2. 入力からモデル実行への逸脱: slash入力とEnterを分離し、観測したメニューだけ操作。画面不明ならfinishで停止。MCPやモデルへのpromptはない。
3. 未起動を保護と誤認: 実体直接対照→untrusted→標準登録→再起動でmarker増加→v2変更時marker不増→再登録後の再起動で増加を比較する。
4. 永続化の誤判定: UI表示だけでなく、CLI終了後の独立hooks/listと次CLI起動のmarkerで確認。承認ストアを読んだり内容を推定して書かない。
5. 残留: PTY終了は正常・異常ともprocess groupを止める。最終コンテナ清掃は既存runnerのfinally。ログ保存に失敗してもowner照合後の削除を試みる。

## Files / Interfaces

`$ART=/tmp/c3c-phase0b8`（初回）・`/tmp/c3c-phase0b8-r2`（個別画面で確認した `t` キーを追加）・`/tmp/c3c-phase0b8-r3`（既知UI設定を含む完全一致検査へ修正した最終実行）:
- run.py/manage.py/process_runner.py: 0B-7由来の資源管理。
- probe.py: fixtureとPTY、制御JSONの限定キー処理、hooks/list snapshot、群停止。
- inspect_hooks.py: 標準App Serverを一時起動してhooks/listだけを取得し停止。
- hook-marker.py: 実行の無害な証拠。
- watch.py: 所有名のcontainerログをprivate保存し、pyte 0.8.2で現在セッションの120×40画面を復元する。既知fixtureのmarkerをその時点で読み、初回およびv2変更後の起動後・承認前に不実行を観測する。control.py: 指定済みキーまたはrestart/modify/finishをatomic JSON置換で送る。run stateから新規fixture位置だけを取得する。

### Task 1: 準備

- [ ] 全Python構文、hook JSON、control入力allowlistを確認。Expected 合法な1定義と限定キーのみ。
- [ ] セルフレビューと独立Codexレビュー、Critical/Important全解消・確認限定巡。最大5巡、同型2巡で収束診断。
- [ ] `./lint.sh` host実行。Expected rc0、Composeを含む。

### Task 2: 標準UI観測

- [ ] `python3 /tmp/c3c-phase0b8/run.py` をbackgroundのPTY監督として起動。通常初期化後、直接control markerとinitial hooks/list（1件untrusted）を確認。
- [ ] `/tmp/c3c-phase0b8-tools/bin/python /tmp/c3c-phase0b8/watch.py` で画面を確認。`control.py hooks`、候補確認後 `control.py enter` で `/hooks` を開く。
- [ ] watchで確認できたevent/source/commandのメニューだけを上下キー/Enterで操作し、v1を標準UIから信頼登録する。ここでのUI操作担当はCodexであり、人間が実際にクリックした記録とは言わない。
- [ ] `control.py restart`。Expected 独立snapshot trusted、再起動後v1 marker増加。
- [ ] `control.py modify`。Expected v2のhashが変わり、snapshot modified（実装がuntrustedと表示すればその値を記録）。再起動してもv2 markerは増えない。
- [ ] 同じ限定UI手順でv2の定義を照合し信頼登録、`control.py restart`。Expected trusted、v2 marker増加。
- [ ] `control.py finish`。Expected 最終snapshot・完了マーカー・runner rc0、owner資源清掃。期限/画面制約で到達しない操作はnot runとし、成功を仮定しない。

### Task 3: 設計判断への引渡し

- [ ] 正式UI登録・持続・変更後の状態を結果へ記録し、AIによる承認記録偽造耐性の未検証と区別する。
- [ ] 並行のG3独立設計レビューを照合。managed MCPの照合範囲とhooks運用への制約を、一次資料で確認できる事実だけとして記録し、第1段階に必要な判断を絞る。
- [ ] 新規結果レビュー、編集後lint、private証跡退避。Critical/Important未対応0で報告。

## 適用と引渡し

Superpowers writing-plans/executing-plans/requesting-code-reviewを継続。既存承認されたinline調査で、追加の実運用設定変更ではない。プローブは製品TDDの代わりではなく、標準機能の操作観測である。

[公式Hooks](https://learn.chatgpt.com/docs/hooks)の `/hooks` とhash単位の信頼を背景資料とし、実際のUIを見て操作する。対象helpで `--no-alt-screen` を確認済み。

`/goal`文面: 「0B-8計画で検証専用hookだけを標準UIから信頼登録し、再起動/定義変更/再登録を観測して清掃する。モデルpromptやauth本文の読取をしない。」host Podman sandbox権限、既存firewallの通信のみ。

実装: Codex — 利用者のCodex限定・継続指示に従い、検証専用の標準UI操作を担当する。

初回は個別レビュー画面の `Press t to trust` を確認したがallowlist外なのでfinishで終了、清掃rc0。再実行では同じ定義の個別画面を照合後に `control.py trust` を送る。最終実行では各操作コマンドのARTを `/tmp/c3c-phase0b8-r3` へ読み替える。watch用venvは `/tmp/c3c-phase0b8-tools` のまま。

r2は標準UIが保存した既知tui設定の完全一致検査で起動前停止。r3はその既知辞書だけを許容する検査へ修正し限定レビューを通過。実測結果は [結果記録](2026-09-20-c3c-phase0b8-results.md) を参照。信頼状態の持続・modified・再登録は観測したが、信頼済みhook実行marker増加は未達。Task 2/3の全Expected達成やG3解消とは扱わない。
