# c3c 第0B-3段階: Codex の作業先変更と設定層の事前検証

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 対象版の標準 App Server 操作で同じ thread の cwd を変更できるか、worktree ごとの設定層と trust の扱いを無認証で観測し、実認証テストに必要な条件を明確にする。

**Architecture:** 既存 image の1コンテナだけを使い、ホストmountなし・network noneで使い捨てrepoと2 worktreeを作る。JSON-RPC stdioから対象版のschemaに存在する操作だけを呼ぶ。CLI/TUIでAIが自律的に移動したことや、会話・指示・MCPが移動へ追従したこととは区別する。

**Tech Stack:** codex-cli 0.155.1、rootless Podman、Python3、Git 2.53.0。

**Spec:** `docs/superpowers/specs/2026-09-20-c3c-incremental-design.md` G1/G3/G4・§7。0A・0B-1・0B-2に続く限定調査。G3全体を完了扱いにしない。

## Global Constraints

- 製品コード変更、commit、push、PR、新規build/pullを行わない。既存 worktree と設定に触らない。
- 既存 image ID `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c`、製品ENTRYPOINT(setpriv+tini)維持、CMDのみ検査Pythonへ差替え。通常entrypoint・firewallの検証は0B-2から拡張しない。
- コンテナはnetwork none、ホストmountゼロ、User=node、cap追加なし、privilegedなし、security_opt追加なし。daemon/proxy/socket共有なし。stdin/stdoutのみでapp-serverを操作。
- 実認証を読み込まず、ログイン操作、turn/start、モデルリクエスト、MCP定義、hook定義、外部コマンド実行RPCを使わない。子プロセスのCODEX_HOME/HOMEはコンテナ内専用領域。
- trust変更は使い捨てuser configの機能観測であり、製品の承認や実コードの承認にはしない。trustファイルが書けることだけでMCP審査全体の性質を確定しない。
- cwd変更の結果を「素のCLIで同一会話の作業先を切替できた」と読み替えない。仕様§7のモデル・指示・MCP・履歴の実測は残す。
- ユーザーの指示に従いClaudeは起動せず、Codexで実行・レビューする。

## Review Focus

1. 標準機能と独自クライアントの混同: schema由来のRPCと、CLI/TUIのユーザー操作・AIの標準toolを区別する。
2. 設定取得とthread実効値の混同: config/read(cwd)は独立した設定照会。同じthreadへ再読込された証拠とは扱わない。
3. 未認証・モデル未実行: thread IDとmetadataだけを観測し、会話継続の成功を主張しない。
4. 不正cwdの扱い: nonexistent pathはerrorも受理も記録し、schema受理だけで利用可能と判断しない。
5. timeout/割込み/後始末: 0B-2の修正済みprocess group停止処理を無変更で再利用し、owner照合後に自分のコンテナのみ削除。未到達は成功と扱わない。

## 添付と根拠

ローカル添付は `/tmp/c3c-phase0b3/`。再開時は添付と計画を一緒に渡す。公開計画だけでは実行できない。

- `probe.py`: コンテナ内専用repo/worktree作成、stdio RPC、応答ログ。
- `run.py`: mount/権限検査後に上記を実行、owner付きコンテナ清掃。上流実行物はコンテナ内だけ。
- `process_runner.py`: 0B-2と同一。SIGTERM/INTを停止中延期し、TERM→KILL後の停止を確認する。
- `schema-bundle.json`: 対象版が `codex app-server generate-json-schema --experimental --out <DIR>` で生成した437 schema。採取はnetwork none・mountなし。helpも同条件で採取済み。
- 設定の識別子はuser=low、worktree A=medium、B=highという `model_reasoning_effort`。モデルは実行しない。

## Task 1: レビューと観測手順の確定

**Consumes:** 実測したhelp/schema、添付、仕様。
**Produces:** 独立レビューのCritical/Important未対応ゼロ。

- [ ] `python3 -m py_compile /tmp/c3c-phase0b3/run.py /tmp/c3c-phase0b3/probe.py /tmp/c3c-phase0b3/process_runner.py`。Expected: rc0。
- [ ] セルフレビューで仕様対応、添付実在、RPC名と引数、Review Focusを確認。
- [ ] Codexの独立レビュアーで計画と添付を確認。修正後は確認限定巡。最大5巡、同型2巡なら収束診断。

## Task 2: 無認証の観測

**Consumes:** 確定した添付。
**Produces:** `<RUN_ID>/probe.log`、`inspect.log`、段階別rc `result.json`、cleanup証跡。run-dirファイルがその実行専用の保存先を示す。

- [ ] `python3 /tmp/c3c-phase0b3/run.py > /tmp/c3c-phase0b3/run.log 2>&1`。ホストPodmanへアクセスできるsandboxで実行。コンテナ通信はnone。
- [ ] initialize→account/read(refreshToken=false)→config/read(A, includeLayers=true)。Expected: 実認証なし、設定層と値の記録。返却値は推測せず記録する。
- [ ] 専用user configだけでrepo/A/Bをtrustedに変更しconfig/read(A/B)。Expected: 有効値と無視された層・その理由を記録。設定の再読込が起きない場合も成立と偽らない。
- [ ] thread/start(A, read-only, never)→同じthreadIdでsettings/update(A→B→A)→各thread/read。Expected: RPC応答とmetadata.cwdを記録。error/未到達と変更成功を区別。モデルターンは開始しない。
- [ ] 存在しないcwdへsettings/update→thread/read。Expected: errorまたは受理後のmetadataを記録。どちらも実作業の成功にはしない。
- [ ] stderrは専用readerで実行中からホストログへ流し、例外時にもauth.json不存在とserver状態を記録して子プロセス終了。result.jsonはrun ID・未到達の初期値・原失敗・cleanup失敗を分け、清掃失敗時もfinallyで保存。コンテナ削除後、owner一覧空、既存image保持。Expected: すべての段階rcと完了マーカー、後始末rcが記録される。

## Task 3: 判定・認証テストへの引渡し

**Consumes:** Task2の観測と実inspect、公式認証資料。
**Produces:** `docs/superpowers/plans/2026-09-20-c3c-phase0b3-results.md`、非公開証跡の退避。

- [ ] app-serverの定義、RPC受理、metadataの変更、CLI/TUIでの操作、実会話の5段階を分けて結果に書く。
- [ ] 実認証テストは専用保存先で新規ログインする形を第一候補とする。利用者はChatGPT契約枠での新規ログインを選択済み。既存host authを勝手にコピーせず、初回認証は利用者のブラウザ操作が必要。
- [ ] `./lint.sh`。Expected: rc0・警告ゼロ・Compose含む。sandbox制約時はホスト実行で補完する。
- [ ] 新規コンテキストのCodexが結果と証跡をレビュー。C/I未対応ゼロ、Minorとnot runを記録。
- [ ] `.claude/test-results/<RUN_ID>/` に全添付・ログを退避しbyte照合。コンテナ内fixtureはそのコンテナと共に消え、既存imageは残る。

## 実行方法

writing-plans / executing-plans / requesting-code-review / verification-before-completionを使用。承認済み調査の継続として逐次実行し、製品実装・別branch・commitは行わない。進捗台帳はこの計画専用のSuperpowers workspaceへ保存する。認証を開始できない場合も、この無認証観測とレビューを完了してから必要な利用者操作を提示する。

`/goal` 引渡し文面: 「この0B-3計画と添付を使い、無認証のsession/config観測・清掃・結果レビューを完了する。CLIでの会話移動へ過剰に一般化せず、実認証の前提を明確にする。製品変更・commit・pushなし。」現セッションで新規goalは作らない。

実装: Codex — ユーザーの一時的なCodex限定指示に従い、ホストから限定コンテナを操作する。

## 公式資料と対象版の区別

- [Authentication](https://learn.chatgpt.com/docs/auth): 専用CODEX_HOMEでのfile保存とdevice認証の手順を確認。実ログインとrefreshは本調査では未実施。
- [App Server](https://learn.chatgpt.com/docs/app-server): cwdを伴う標準操作の背景資料。今回使うthread/settings/updateは、さらに対象0.155.1が生成したschemaで名前と引数を確認した。
- [CLI slash commands](https://learn.chatgpt.com/docs/cli/slash-commands): この一覧に作業先移動の操作を確認できなかったことは、不可能性の証明として扱わない。
