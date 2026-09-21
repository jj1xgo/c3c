# c3c Phase 0B-2 通常 entrypoint 検証計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 無認証の Codex sandbox が、通常のファイアウォール初期化後にも動くか実測する。

**Architecture:** 既存 `tests/test-runtime.sh` の fixture / PATH shim 方式を使う。製品 ENTRYPOINT・CMD を維持し、最後の `claude` だけを読み取り専用の検査プログラムに置き換える。これは正式な CLI 切替の実装でも、実 Claude/Codex 会話の検証でもない。初回の事前検査で baked entrypoint が別 worktree の試験版と判明したため、再実測では main の entrypoint を fixture へコピーし、製品と同じ絶対パスへ `:ro` で重ねる。ENTRYPOINT/CMD の配列は変更しないが、イメージに焼き込まれたスクリプトをそのまま使う検証とは区別する。

**Tech Stack:** Linux、rootless Podman、podman-compose、Python 3 / PyYAML、codex-cli 0.155.1。

**Spec:** `docs/superpowers/specs/2026-09-20-c3c-incremental-design.md`。上位の `2026-09-20-c3c-phase0-validation.md` の 0B のうち、通常 entrypoint の無認証部分だけを扱う。

## Global Constraints

- 製品ファイルを編集しない。公開成果物はこの計画と結果文書。コミット・push・PR は行わない。
- Claude の枠が回復するまで Codex のみで進める、という今回のユーザー指示を適用する。実 Claude、Fable、Opus は起動しない。
- 既存 image `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c` を使い、build/pull は行わない。
- ホストの認証・設定・vault・実プロジェクトをマウントしない。全 fixture は新規 `mkdtemp` 配下、例外は `/dev/null` と読み取り専用の `/etc/localtime`。
- 製品既定の NET_ADMIN / NET_RAW と IPv4 構成を維持する。privileged、SYS_ADMIN、seccomp 無効化、firewall 無効化を追加しない。
- 0B-1 の `--network none` と違い、通常 entrypoint が必要とする標準ネットワークを使う。製品自身の初期化通信と、GitHub:443 / GitHub:80 / example.com:443 の対照・保護検査に限定する。モデルへのリクエストは行わない。
- `.mcp.json` は置かず、Codex `config.toml` は空。MCP 承認の十分性、認証、同一会話の worktree 移動、実 launcher の選択機能は引き続き not run。
- 成否は終了コード・到達マーカー・ファイル状態・接続対照から判定する。環境エラー、未到達、成功を区別する。

## Review Focus

1. ホスト設定の混入: 子プロセスの環境を限定し、空 env-file を明示。起動前に解決済み volume の実パスを検査する。
2. 通常経路の取り違え: image の ENTRYPOINT/CMD と 4 本の製品スクリプトのハッシュを照合。protected の inspect と shim 到達・完了マーカーを記録する。
3. 偽の遮断成功: 固定した IP への全接続が control-before / control-after とも成功することを要求する。
4. inner 未起動の誤判定: `INNER_BEGIN` に到達してからの EACCES/EROFS と rc42、ファイル不存在を要求する。対照・workspace は rc0 とファイル生成を要求する。
5. 後始末の対象逸脱: 一意な owner label、network の project label を確認して自身の資源だけを削除。image は保持し、ログをバイト照合して退避する。

## ファイルとインターフェース

実行用のローカル添付は `/tmp/c3c-phase0b2/` に置く。実行後、同じファイルを非公開の `.claude/test-results/<RUN_ID>/` に退避する。公開計画のみをコピーして添付がない場合は実行できないので、添付を同時に引き継ぐ。

- `run.py`: fixture 作成、Compose 解決と検査、4 コンテナの観測（初回の停止済み実行と読出し対照は別記録）、後始末とログ退避。
- `process_runner.py`: 専用 process group で起動し、timeout / 割込み時は TERM→KILL で子孫の停止を確認。停止中の SIGTERM/INT は確認完了まで延期する。コマンド待機が例外終了した場合は例外型を問わず清掃成功としない。
- `test_process_runner.py`: 元の処理で子孫残留を再現し、修正後の timeout / 待機中割込み / 停止中 SIGTERM で残留しないことを確認。
- `probe.py`: 通常 entrypoint 後の runtime 検証、:ro 保護と Codex permission profile 検証。
- `image-entrypoint.sh`: 初回に既存 image から network none・ホストmountなしで採取した baked script。SHA256を固定し、mainとの差が最終argvだけであることを照合する。
- `tests/runtime-probe.py`: 無変更でコピーする既存の接続・capability・refresh 検証。
- `write-check.py`: 0B-1 の退避済み観測プログラムを無変更でコピー。INNER_BEGIN、WRITE_OK / WRITE_DENIED、終了コード 0 / 42 / 43 を返す。
- `logs/result.json`: 各段階の rc、verdict、cleanup。例外は INCOMPLETE として残し、成功と扱わない。

### Task 1: 計画・添付のレビュー

**Consumes:** 上位仕様、0B-1 の成立結果、製品 compose / entrypoint / 既存 runtime probe。
**Produces:** 実行可能な添付、Critical / Important 未解決ゼロのレビュー記録。

- [x] `python3 /tmp/c3c-phase0b2/test_process_runner.py`。Expected: 元の処理の子孫残留を再現後、修正後の timeout / 割込みの停止確認が成功。
- [x] `python3 -m py_compile /tmp/c3c-phase0b2/run.py /tmp/c3c-phase0b2/probe.py`。Expected: rc0。
- [x] 仕様対応、未実測範囲、手順間のパス・結果名・rc の一致をセルフレビューする。
- [x] 独立 Codex レビュアーが本計画と添付を読み取り専用でレビュー。Critical / Important を修正し、反映後に確認限定巡を 1 回行う。同型指摘が 2 巡続いたら別 Codex が収束診断、最大 5 巡。

### Task 2: 実測と退避

**Consumes:** Task 1 の確定した添付。
**Produces:** RUN_ID、専用 ROOT、ログと結果 JSON、同一内容の退避先。

- [x] `python3 /tmp/c3c-phase0b2/run.py > /tmp/c3c-phase0b2/run.log 2>&1` を checkout のルートから実行。必要な sandbox はホスト Podman に到達できるモード、ネットワークは前述の通常コンテナ通信。sandbox 制約時のみツールの権限昇格で実行する。
- [x] image / rootless / 解決済み設定 / source hash が一致することを確認。再実測の entrypoint は main の readonly fixture、それ以外3本は baked source を照合する。不一致なら通常経路の検査には進まない。
- [x] control-before → protected → control-after の rc とログを照合。Expected: 全 rc0、protected 内 RUNTIME_PROBE_OK と C3C_NORMAL_ENTRYPOINT_OK。UID 非 root、CapInh/Prm/Eff/Amb=0、iptables 直接操作不可、refresh 成功。
- [x] Expected: settings.json、hooks 内ファイル、MCP 承認記録への書込みは EROFS。control と :workspace はファイル生成、:read-only は inner 到達後 rc42 とファイル不存在。
- [x] Expected: protected fixture の内容不変、所有コンテナ残留ゼロ、専用 network 削除、既存 image 保持、退避した全ファイルのハッシュ一致。途中失敗時もログを残し、対象資源の清掃に失敗したら ROOT を保持する。

### Task 3: 結果レビューと報告

**Consumes:** Task 2 の rc / inspect / stdout / file-state / cleanup 証跡。
**Produces:** `docs/superpowers/plans/2026-09-20-c3c-phase0b2-results.md`。

- [x] 結果文書に、通常 entrypoint の観測と正式な CLI 起動・会話の未検証を分けて記載する。
- [x] `./lint.sh`。Expected: rc0、警告ゼロ。sandbox による Podman エラーは環境制約として記録し、権限昇格でホストの必須検査を実行する。
- [x] 新規コンテキストの Codex が結果と証跡をレビュー。Critical / Important を解消し、未対応 Minor と not run を明記する。
- [x] 清掃と退避が成功したときだけ、この実行が作った ROOT を削除し不存在を確認。添付・レビュー・進捗記録は保持する。

## 実測前提の修正（初回停止後）

初回 RUN_ID `c3c-0b2-46e30b998c0b` は entrypoint の SHA256 不一致で protected 前に停止した。採取した script は `trial/auto-permission-mode` のものと一致し、main との差は最終行の `--permission-mode auto` / `--dangerously-skip-permissions` だけ。残る3本は main と一致する。既存テスト用 image は main の script を含むが Codex がないため採用しない。

再実測は既存imageを変更せず、main entrypoint の読み取り専用 fixture で対象を固定する。`run.py` は採取した baked script の SHA256 `82276b590f9cd83430a2e4e89a3ff359a3578a14a8ad810131585335ff12a44c` と一行だけの差分を検証し、readonly mount と実測前後の内容不変も確認する。正式な current-main image の build・そのままの起動は not run。この条件変更をレビューしてから新規 ROOT/RUN_ID で実行する。

## 実行記録

2026-09-20 実測・結果レビュー・清掃を終了。結果は [0B-2 結果](2026-09-20-c3c-phase0b2-results.md) を参照。チェックは手順の実施を表す。初回のsource不一致と再実測後の退避失敗を成功扱いにせず、後者はsymlinkを辿らない別手順で復旧した。実測本体は再実行していない。正式build・認証・会話の未検証は結果側に残す。

## 実行方法と Superpowers の適用

`writing-plans` のセルフレビュー後、`executing-plans` でこのセッションから逐次実行する。ユーザーの継続指示により、承認済みの限定検証の確認を繰り返さない。製品実装ではないため、RED→GREEN を作る目的のコード変更や別開発ブランチは行わない。観測に失敗しても期待値へ合わせる修正はせず、環境制約と製品問題を分類する。全作業後は `requesting-code-review` と `verification-before-completion` を適用する。

Codex `/goal` 引き継ぎ文面: 「この 0B-2 計画とローカル添付を読み、通常 entrypoint の無認証検証、限定清掃、結果文書、Codex 独立レビューを完了する。実認証や Claude を起動せず、製品コード変更・commit・push・PR は行わない。」現在のセッションでは `/goal` を新設しない。

実装: Codex — ユーザーの一時的な Codex 限定指示による。確定した無認証の検証手順をホストから実行する。
