# Copilot の受け入れ（canary）のスクリプト 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目的:** 保守者が opt-in のコンテナの入力欄で `! bash tests/copilot-canary.sh` を 1 回打つと、README「変更後の確認」の Copilot の受け入れが全部走り、Copilot のセッション記録（`events.jsonl`）から項目ごとの合否を出す。

**構成:** 段取り（前提の確認・目印・起動口の呼び出し・後片付け）は bash の `tests/copilot-canary.sh`、判定と JSON の扱いは標準ライブラリだけの `tests/copilot_canary_helper.py`（`python3 -I` で呼ぶ）に分ける。Copilot は起動口 `/usr/local/bin/copilot` を通して呼び、各回に `--session-id <uuid>` を渡して、その回の `~/.copilot/session-state/<uuid>/events.jsonl` を読む。試験は、固定パスを一時ディレクトリへ置換した写しと偽の起動口で行う（`tests/test_copilot_launcher.py` と同じ流儀）。

**使う技術:** bash、Python 3（標準ライブラリ、`unittest`）、`flock`、shellcheck（`./lint.sh`）。

**仕様:** `docs/superpowers/specs/2026-11-12-copilot-canary-design.md`（commit 4f8cefb）

**経緯:** 今は canary を毎回、コンテナの中の AI のセッションが README の文から組み立て、合否をモデルの要約で読み、`settings.json` を弱める段は分類器に止められて保守者が手で打ち、消費の記録が漏れていた。これを 1 行で走り、記録から判定するスクリプトにする（spec「目的と理由」）。

作業ブランチは `feat/copilot-canary`（作成済み、`main` の `86b4af4` から。spec の commit 4f8cefb を含む）。計画の承認の直後に、計画者がこの計画を `docs/superpowers/plans/2026-11-12-copilot-canary.md` に写して commit する（公開の置き場。「計画レビューの記録」の一時パスと session ID は「（非公開の場所に保存）」に置き換え、commit の前に `grep -nE "$(id -un)|/tmp/|session" docs/superpowers/plans/2026-11-12-copilot-canary.md` の出力を目で見て、ホストのパス・ユーザー名・session ID が残っていないことを確かめる。`/home/node` は c3c の公開の配置なので残ってよい）。生の出力は保守者の非公開の場所に置く。実装者はその commit の上から始める。

**実行の場所:** タスク 0 の手順 1・2 とタスク 4 の手順 1 は opt-in のコンテナで保守者が `!` で打つ（タスク 0 の手順 2 とタスク 4 がクレジットを使う）。ほかはホストでもコンテナでもよい（実 podman も実 Copilot も使わない）。

## 全体の制約

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（コードを変える計画。タスク 1 の前に 1 回読み込む）

- 起動口 `copilot-launcher.sh`・雛形 `copilot-settings.json`・`VERIFIED_COPILOT_VERSION` は変えない（spec「やらないこと」「制約」）。
- スクリプトはトークンを読まない・引数に出さない。sandbox の中のコマンドが `COPILOT_PAT` を `cat … >/dev/null` するのは読めないことを確かめるためで、中身は出さない。
- 保守者個人のもの（並走の台帳のパス、非公開のリポジトリの名前、ホストのパス）をスクリプト・試験・README・fixture に書かない。
- モデルを呼ぶのは実機の確かめ（タスク 0 の手順 2 とタスク 4）だけで、これは CI に入れない。偽の起動口の試験（タスク 1・2）は `--launcher-only` に入るので CI でも走る（`bash`・`flock`・`python3` を要る）。
- Copilot の起動の引数は README の勧める組に、`-p <プロンプト> -s --model <M> --session-id <uuid> --max-ai-credits <N>` を足したもの: `--available-tools=bash --allow-tool=shell --allow-all-paths --allow-all-urls --no-ask-user --no-auto-update`。
- 既定値: 回数 `2`、モデル `gemini-4-argon`、1 回の上限 `--max-ai-credits 10`、作業ディレクトリ `/workspace`。
- 終了コード: 全部合格で 0、不合格か「確かめていない」があるか中断されたら 1、前提を満たさないか使い方の誤りは 2。
- 編集したら、そのターン内で `./lint.sh` を rc 0・警告ゼロで通す（コンテナでは compose の検証の WARNING が出るので、その旨と compose の検証の `not run` を書く）。シェルスクリプトは shebang `#!/bin/bash`。日本語で書く。

## レビューで見てほしい点

1. モデルがコマンドを打たずに（または別のコマンドを打って）「合格」と書いた回が、合格と出ること → 不合格（タスク 1 の試験）。
2. 外側と sandbox の名前空間の値の形が食い違い、同じ名前空間でも「違う」と出ること → 数字だけで渡し、同じなら不合格（タスク 1・2 の試験）。
3. 目印が置けていない、作業ディレクトリがもともと書けない、`curl` が無い（rc 127）など、塞いでいなくても期待の値が出る状態で合格と出ること → 前提で止めるか不合格（タスク 1・2 の試験）。
4. 途中で失敗・中断した後に、目印・試しのファイル・弱めた `settings.json` が残る、または後片付けに失敗したのに `全体: 合格` と出ること → 後片付けを確かめてから表と rc を決める（タスク 2 の試験）。
5. 中断や `session.shutdown` の欠落で、使ったクレジットが少なめに記録されること → 始めた回は上限の値で数え、中断でも 1 回だけ記録する（タスク 1・2 の試験）。

---

### タスク 0: 実物の形を確かめる（モデルを呼ばない）

**ファイル:**
- 作る: `tests/fixtures/copilot-canary/events-pass.jsonl`

- [ ] **手順 1: コンテナの Copilot の引数を確かめる** — 保守者に opt-in のコンテナの入力欄で `! copilot --help 2>&1 | grep -n -E -- '--session-id|--max-ai-credits|--available-tools|-s, --silent'` を打ってもらう。Expected: `--session-id <id>`（説明に「set the UUID for a new session」）、`--max-ai-credits <credits>`、`--available-tools`、`-s` の 4 つの行が出る（ホストの 1.0.109 では出ることを計画者が確かめた）。どれかが無ければ、先へ進まずに持ち主に報告する（spec の別案〈起動の前後で `session-state` のディレクトリを比べる〉に替えるかは計画に戻して決める）。
- [ ] **手順 2: `--session-id` と保存先の対応を実機で確かめる（モデルを 1 回呼ぶ。約 2 クレジット）** — 保守者に、opt-in のコンテナの入力欄で次を打ってもらう: `! cd /workspace && id=$(python3 -I -c 'import uuid; print(uuid.uuid4())') && copilot -p 'Reply with the single word OK.' -s --model gemini-4-argon --session-id "$id" --max-ai-credits 3 --available-tools=bash --allow-tool=shell --allow-all-paths --allow-all-urls --no-ask-user --no-auto-update; echo "rc=$? id=$id"; ls -l ~/.copilot/session-state/"$id"/events.jsonl && head -c 300 ~/.copilot/session-state/"$id"/events.jsonl`。Expected: `rc=0`、`~/.copilot/session-state/<その id>/events.jsonl` があり、先頭の `session.start` の `sessionId` がその id。使ったクレジットは、その `events.jsonl` の `session.shutdown` から読み、保守者の記録先に足してもらう。ならなければ、先へ進まずに持ち主に報告する（spec の別案〈起動の前後で `session-state` のディレクトリを比べる〉に替えるかは計画に戻して決める）。
- [ ] **手順 3: 実物の `events.jsonl` の形を写した fixture を作る** — 手順 2 の記録と、コンテナに残っている過去の canary の記録（`~/.copilot/session-state/*/events.jsonl` のうち bash の実行を含むもの。無ければ保守者の手元の Copilot の記録）で、次の欄があり、型が括弧の中のとおりであることを確かめる: `session.start` の `data.sessionId`（文字列で、`session-state/` の下のディレクトリの名前と同じ）、`tool.execution_start` の `data.toolCallId`（文字列）・`data.toolName`（文字列）・`data.arguments.command`（文字列）、`tool.execution_complete` の `data.toolCallId`（文字列）・`data.success`（真偽値）・`data.result.content`（文字列）、`session.shutdown` の `data.accountingSnapshot.totalNanoAiu`（数）・`data.accountingSnapshot.aiCreditsStatus`（文字列）。計画者はホストの Copilot の記録で、`sessionId` がディレクトリの名前と同じこと、ほかの欄があることを確かめた。`--session-id` で渡した ID がそのディレクトリの名前になることは、手順 2 で確かめる。確かめた欄だけを持つ最小の 4 行（`session.start`・`tool.execution_start`・`tool.execution_complete`・`session.shutdown`）を、ID と出力を作り物にして fixture に書く（実物の ID・パス・プロンプトを写さない）。欄が無いか型が違えば、先へ進まずに持ち主に報告する。
- [ ] **手順 4: commit** — `git add tests/fixtures/copilot-canary/events-pass.jsonl && git commit -m "test: Copilot の canary の events.jsonl の形の fixture を足す"`

### タスク 1: 判定のヘルパー `tests/copilot_canary_helper.py`

**ファイル:**
- 作る: `tests/copilot_canary_helper.py`
- 試験: `tests/test_copilot_canary_helper.py`

**受け渡し:**
- 使うもの: タスク 0 の fixture（試験の土台）。
- 渡すもの（タスク 2 が呼ぶ CLI。どれも `python3 -I tests/copilot_canary_helper.py <サブコマンド> …`）:
  - `judge EVENTS EXPECTED_COMMAND OUTER_USER OUTER_NET SESSION_ID` → `SESSION_ID` はその回に `--session-id` で渡した UUID。`EXPECTED_COMMAND` はコマンドの文字列そのもの（argv）。`OUTER_USER`・`OUTER_NET` は数字だけ（`^\d+$`。違えば rc 2）。標準出力の 1 行目が `PASS` か `FAIL: <理由>; <理由>…`、2 行目が `credits=<小数>` か `credits=unknown`。rc は PASS で 0、FAIL で 1、引数の誤りで 2。`EVENTS` が無い・読めないときは FAIL（rc 1、理由 `events.jsonl が無い`）で、2 行目は `credits=unknown`。
  - `weaken SETTINGS` → `sandbox.userPolicy.network.allowOutbound` を `true` にして一時ファイル＋`os.replace` で書き戻し、読み直して `true` であることを確かめる。rc 0／1。
  - `settings-match SETTINGS TEMPLATE WORKDIR` → `SETTINGS` の JSON が、`TEMPLATE` の JSON の `sandbox.userPolicy.filesystem.readonlyPaths` に `[WORKDIR]` を入れたものと、**葉の型も含めて**等しければ rc 0（`True` と `1`、`False` と `0` は不一致）、違えば理由を出して rc 1。
  - `spent-log FILE ID MONTH CREDITS WHAT` → `FILE` に `{"id": ID, "month": MONTH, "credits": CREDITS, "what": WHAT}` の 1 行を `ensure_ascii=False` で追記する。`MONTH` は `^\d{4}-\d{2}$`、`CREDITS` は有限で 0 以上の数。`FILE` が symlink か通常のファイルでない（無ければ作る）ときは rc 2 で何も書かない。
- 内部の関数（試験が import して呼ぶ）: `judge(events_path: str, expected_command: str, outer_user: str, outer_net: str, session_id: str) -> tuple[list[str], float | None]`（不合格の理由の一覧〈空なら合格〉と、クレジット〈分からなければ `None`〉）。

判定の規則（spec「項目」2 の期待値。rc の値を見る項目は、0 のほか 126・127〈コマンドが無い・実行できない〉も不合格にする）:
- `events.jsonl` の各行を JSON として読む（読めない行があれば理由 `events.jsonl の <行> 行目が JSON でない`）。
- `session.start` がちょうど 1 つで、`data.sessionId == session_id`（違えば理由 `別のセッションの記録`）。
- `tool.execution_start` のうち `data.toolName == "bash"` がちょうど 1 つで、その `data.arguments.command == expected_command`（1 字も違わない）。bash 以外の `tool.execution_start` があれば、理由 `bash 以外の道具 <名前> が走った` で不合格（`read_bash` も含む）。
- 同じ `data.toolCallId` の `tool.execution_complete` があり、`data.success is True`。出力は `data.result.content`（文字列）から読む。`assistant.message` は見ない。
- 出力の行から: `^user:\[(\d+)\]$` と `^net:\[(\d+)\]$` がそれぞれちょうど 1 つで、数字が `outer_user`・`outer_net` と違う。インターフェースの行 `^(\S+)\s+(UNKNOWN|UP|DOWN|DORMANT|LOWERLAYERDOWN|NOTPRESENT)\b` がちょうど 1 つで、名前が `lo`。`(curl_rc|secret_rc|home_rc|tok_len|gh_len|outer_environ|w_rc)=(\d+)` の各キーがちょうど 1 回現れ、`curl_rc`・`secret_rc`・`home_rc`・`w_rc` は 0・126・127 のどれでもなく、`tok_len`・`gh_len`・`outer_environ` は 0。
- クレジット: `type == "session.shutdown"` の `data.accountingSnapshot` で、`aiCreditsStatus == "complete"` なら `totalNanoAiu / 1e9`、それ以外か無ければ `None`。
- 回どうしの名前空間の比較はしない（spec）。
- 型の扱い: 各行と `data`・`arguments`・`result`・`accountingSnapshot` が dict でなければ、その欄は無いものとする。`totalNanoAiu` は `bool` でない有限で 0 以上の数のときだけ使う。`key=value` は前後が空白か行の端のときだけ拾う（`xcurl_rc=0` を拾わない）。

- [ ] **手順 1: 失敗する試験を書く** — `tests/test_copilot_canary_helper.py`（先頭で `Path(__file__).resolve().parent` を `sys.path` に足し、`copilot_canary_helper` を import する。`tests/` に `__init__.py` は無い）。タスク 0 の fixture を読んで形を変える関数 `make_events(output, *, command=…, tools=("bash",), success=True, shutdown=True, status="complete", nano=2_500_000_000, assistant_text=None)` を置き、次を試す。
  - `test_pass`: 期待の出力（`user:[4026532001]`・`net:[4026532002]`〈外側は `4026531837`・`4026531840`〉、`lo UNKNOWN 00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>` の 1 行、`000 curl_rc=6`、`secret_rc=1`、`home_rc=1`、`tok_len=0 gh_len=0`、`outer_environ=0`、`w_rc=1`）で `judge` が `([], 2.5)`。
  - `test_no_tool_call`・`test_two_bash_calls`・`test_command_differs`（1 字違い）・`test_not_complete`・`test_success_false` → 理由が 1 つ以上。
  - `test_extra_tool_read_bash`（`tools=("bash", "read_bash")`）→ 理由に `bash 以外の道具 read_bash` を含む。
  - `test_assistant_message_ignored`: 実行の出力は不合格の値で、`assistant_text` に合格の出力を入れても不合格。
  - `test_ns_same_as_outer`（user か net が外側と同じ数字）・`test_extra_interface`（`eth0 UP …` が増える）・`test_no_interface` → 不合格。
  - `test_rc_zero`・`test_rc_127`: `curl_rc`・`secret_rc`・`home_rc`・`w_rc` のそれぞれを 0、127 にして不合格（subTest）。
  - `test_tok_len_nonzero`・`test_outer_environ_nonzero`・`test_key_missing`・`test_key_twice` → 不合格。
  - `test_stderr_noise`: 出力に `curl: (6) Could not resolve host: api.github.com` の行が混じっても合格。
  - `test_credits_unknown`（`shutdown=False`、`status="partial"` のそれぞれ）→ クレジット `None`、判定は合格のまま。
  - `test_cli_judge`: 合格で rc 0・1 行目 `PASS`・2 行目 `credits=2.5`。不合格で rc 1・1 行目が `FAIL: ` で始まる。`OUTER_USER` に `user:[1]` を渡すと rc 2。`SESSION_ID` が記録の `sessionId` と違うと rc 1。無い `EVENTS` は rc 1・`credits=unknown`。
  - `test_weaken_and_match`: リポジトリの `copilot-settings.json` に `readonlyPaths: ["/w"]` を足したファイルで `settings-match … /w` が rc 0、`weaken` の後は rc 1、`allowOutbound` を `0` にしたもの（`False` でない）も rc 1。
  - `test_spent_log`: 新しいファイルに 1 行、既存のファイルに追記で 2 行目。`CREDITS=-1`・`nan`・`inf`・`MONTH=2026-1`・symlink の `FILE` は rc 2 で何も書かない。行は `json.loads` で 4 キーちょうど。
- [ ] **手順 2: 試験が落ちることを確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_copilot_canary_helper.py'` / Expected: ヘルパーが無いので ERROR。
- [ ] **手順 3: `tests/copilot_canary_helper.py` を実装する** — shebang `#!/usr/bin/env python3`、標準ライブラリだけ、上の 4 サブコマンドと `judge()`。
- [ ] **手順 4: 試験と lint を通す** — 手順 2 のコマンドで OK（失敗 0）。`./lint.sh` が rc 0。
- [ ] **手順 5: commit** — `git add tests/copilot_canary_helper.py tests/test_copilot_canary_helper.py && git commit -m "test: Copilot の canary の判定のヘルパーを足す"`

### タスク 2: 段取りのスクリプト `tests/copilot-canary.sh`

**ファイル:**
- 作る: `tests/copilot-canary.sh`
- 試験: `tests/test_copilot_canary.py`

**受け渡し:**
- 使うもの: タスク 1 の CLI（`judge`・`weaken`・`settings-match`・`spent-log`）。ヘルパーの場所はスクリプトの隣（`"${BASH_SOURCE[0]%/*}/copilot_canary_helper.py"`）。
- 渡すもの: `bash tests/copilot-canary.sh [--runs N] [--model M] [--max-ai-credits N] [--spent-log FILE] [<作業ディレクトリ>]`。

固定パスは `readonly` の定数（環境変数で差し替えない）: `COPILOT_BIN=/usr/local/bin/copilot`、`CONTAINER_HOME=/home/node`、`COPILOT_HOME=/home/node/.copilot`、`SETTINGS_TEMPLATE=/etc/c3c/copilot-settings.json`、`TOKEN_FILE=/home/node/.config/c3c/secrets/COPILOT_PAT`、`SECRETS_DIR=/home/node/.config/c3c/secrets`、`HOME_MARK=/home/node/.copilot/.c3c-canary-mark`、`PYTHON3=/usr/bin/python3`、`FLOCK=/usr/bin/flock`。sandbox で打たせるコマンドは spec「項目」2 のコマンドの `/home/node/.copilot/mark` を `/home/node/.copilot/.c3c-canary-mark` に替えたものを、`readonly CANARY_COMMAND` に逐語で置く（ヘルパーへは argv で渡す）。プロンプトは spec の 1 行目（`Run exactly this one bash command …`）＋改行＋`CANARY_COMMAND`。

項目と表の行（この順。各行は `[合格]`・`[不合格]`・`[確かめていない]` と理由）: `canary 1`…`canary N`、`/home/node で止まる`、`弱めた設定が戻る`、`後片付け`。ある段を行う前に前の段が失敗してその段を行えなかったときは `[確かめていない]`（理由に、行えなかったわけ）。

動き（この順）:
1. 引数の検査（`--runs` は `^[1-5]$`、`--max-ai-credits` は `^[1-9][0-9]*$`〈`08` などの先頭 0 を断る〉、`--model` は空でない、作業ディレクトリは存在するディレクトリ、未知のオプション・値の欠けたオプション・2 つ目の位置引数は誤り。`--spent-log` は空でなく、既にあれば symlink でない通常のファイル、無ければ親のディレクトリがあって書ける）。誤りは使い方を出して rc 2（クレジットを使う前に止める）。作業ディレクトリは `cd "$dir" && pwd -P` で解決した値 `WORKDIR` を以後の全段で使う。
2. 前提（どれも欠ければ `ERROR:` と rc 2、何も変えない）:
   - `WORKDIR` が起動口の拒む場所でない: `/`、`/home/node` とその祖先、`/home/node/.` で始まるエントリとその下、`/tmp` とその下、`SECRETS_DIR` とその下（`copilot-launcher.sh` の作業ディレクトリの検査と同じ規則）。`WORKDIR` に書ける（`[ -w ]`。書けない場所では `w_rc` の合格に意味が無いため）。
   - `COPILOT_BIN` が通常のファイルで `readonly VERIFIED_COPILOT_VERSION=` の行を含む。`SETTINGS_TEMPLATE` がある。`TOKEN_FILE` が読める通常のファイル（中身は読まない）。`COPILOT_BIN` は symlink でない。`COPILOT_HOME` は、あれば symlink でないディレクトリ。無ければ（作り直した直後のコンテナ）、起動口と同じく `mkdir -m 700` で作る（これだけは前提の確認の中で変えてよい）。
   - `HOME_MARK` と `WORKDIR/.c3c-copilot-w` が無い（`[ -e ] || [ -L ]` で見て、壊れた symlink もあるものとする。あれば触らない）。
   - 別の `copilot` が動いていない: `COPILOT_HOME/.c3c-launch.lock` を、無ければ作り（起動口と同じく `: >>`）、読み取りで開いた fd で `FLOCK -n` を取れることを確かめ、すぐ fd を閉じる（Copilot を呼ぶ前に閉じる）。
   - 外側の名前空間 `readlink /proc/self/ns/user`・`/proc/self/ns/net` から `^user:\[(\d+)\]$`・`^net:\[(\d+)\]$` で数字を取り出せる。
3. `trap` を登録する（INT・TERM・EXIT）。中断（INT・TERM）では、後片付け（下の 8）と、始めた回の消費の記録（下の 9。終わっていない回は上限で数える）を 1 回だけ行い、残りの段を行わずに rc 1 で終わる（`what` に「中断」）。二重に走らないよう、済んだ印の変数を見る。
4. `HOME_MARK` に目印を `set -C`（上書きしない）で書き、書いた後に通常のファイルで読めることを確かめる。満たさなければ canary を打たずに `ERROR:` と rc 2（目印は消す）。
5. canary を N 回: `uuid` を `PYTHON3 -I -c 'import uuid; print(uuid.uuid4())'` で作り、`WORKDIR` で `COPILOT_BIN -p "$prompt" -s --model "$model" --session-id "$uuid" --max-ai-credits "$cap" --available-tools=bash --allow-tool=shell --allow-all-paths --allow-all-urls --no-ask-user --no-auto-update` を呼ぶ。始めた回を数える。rc が 0 でなければ不合格（理由に rc）。続けて `judge "$COPILOT_HOME/session-state/$uuid/events.jsonl" "$CANARY_COMMAND" <外側 user の数字> <外側 net の数字> "$uuid"` を呼ぶ。`WORKDIR/.c3c-copilot-w` が出来ていれば、その回を不合格にしてその場で消す。クレジットが `unknown` なら `cap` で数え、その回の行に「クレジット不明（上限で数えた）」と出す。
6. `/home/node で止まる`: `(cd /home/node && COPILOT_BIN --version)` の rc が 1 で、stderr に `ERROR: 作業ディレクトリ /home/node では起動しません` を含めば合格。
7. `弱めた設定が戻る`: `weaken "$COPILOT_HOME/settings.json"` が rc 0（弱めが効いた）、`WORKDIR` で `COPILOT_BIN --version` が rc 0、`settings-match "$COPILOT_HOME/settings.json" "$SETTINGS_TEMPLATE" "$WORKDIR"` が rc 0、の 3 つが全部満たされたら合格。`weaken` が失敗したら `[確かめていない]`（理由: 弱められなかった）。`settings.json` が無ければ、先に `WORKDIR` で `COPILOT_BIN --version` を 1 回呼んで作る。
8. `後片付け`（表と rc を決める前に行う）: `HOME_MARK` と `WORKDIR/.c3c-copilot-w` を消し、`WORKDIR` で `COPILOT_BIN --version` を 1 回呼び、`settings-match` で雛形に戻ったことを確かめる。どれかが失敗したら不合格（理由に、残ったもの）。
9. 表を出す。続けて Copilot の版（`COPILOT_BIN --version 2>/dev/null` の 1 行目。起動口の WARNING を混ぜない。取れなければ `不明`）、起動口の `VERIFIED_COPILOT_VERSION`、モデル、各回の session ID と `events.jsonl` のパス、クレジットの合計。最後に `全体: 合格` か `全体: 不合格`（全部の行が `[合格]` のときだけ合格）。クレジットの合計は `PYTHON3 -I -c` で足す（bash で小数を扱わない）。`--spent-log` があれば、UTC の時刻を 1 回だけ取り、`spent-log FILE "copilot-canary-<その時刻 %Y%m%dT%H%M%SZ>-$$" "<その時刻 %Y-%m>" <合計> "<版>・<モデル>・<始めた回数> 回・<全体の合否>[・クレジット不明の回は上限で数えた][・中断]"`。記録に失敗したら `ERROR:` を出し、rc は 1（全体が合格でも）。
10. rc は 0／1（全体の制約）。

- [ ] **手順 1: 失敗する試験を書く** — `tests/test_copilot_canary.py`。`setUp` で一時ディレクトリに `home/node/.copilot`・`home/node/.config/c3c/secrets/COPILOT_PAT`（ダミーの 1 行）・雛形の写し・作業ディレクトリを作り、`tests/copilot-canary.sh` の写しの固定パス（`/usr/local/bin/copilot`・`/home/node`・`/etc/c3c/copilot-settings.json`・`/usr/bin/python3`・`/usr/bin/flock`・`/tmp` の拒否の規則）を一時ディレクトリや実物の `python3`・`flock` へ置換する（`CANARY_COMMAND` の中の `/home/node` も同じく置換されるので、偽の起動口はその置換後のコマンドを記録に書く）。ヘルパーも写しの隣に置く。偽の起動口（bash）は `readonly VERIFIED_COPILOT_VERSION=1.0.109` の行を含み、呼ばれた argv を記録し、次をする: 作業ディレクトリが置換後の `/home/node` なら `ERROR: 作業ディレクトリ … では起動しません` を出して rc 1。`--version` なら `settings.json` を雛形＋`readonlyPaths: [cwd]` で書いて `GitHub Copilot CLI 1.0.109.` を出す。`-p` なら `--session-id` の値の `session-state/<id>/events.jsonl` に、タスク 0 の fixture の形で、環境変数 `FAKE_MODE` で選ぶ記録を書く（既定は合格の出力で、名前空間は外と違う数字）。試験:
  - `test_all_pass`: rc 0、出力に `全体: 合格`、`[合格]` が 2 回分＋3 項目、目印と試しのファイルが残らない、`settings.json` が雛形＋`readonlyPaths` と等しい、argv に 全体の制約の組と `--model gemini-4-argon`・`--max-ai-credits 10`・`--session-id <uuid>` がある。
  - `test_model_claims_without_running`（`FAKE_MODE=no_tool`、`assistant.message` だけ）: rc 1、`全体: 不合格`。
  - `test_ns_same_as_outer`（`FAKE_MODE=same_ns`: 偽の起動口が自分で `readlink /proc/self/ns/user /proc/self/ns/net` を打ち、その出力をそのまま記録に書く）: rc 1。
  - `test_write_file_created`（偽の起動口が `.c3c-copilot-w` を作る）: 2 回とも不合格（各回でその場で消える）、rc 1、最後にファイルが無い。
  - `test_settings_not_restored`（偽の `--version` が `settings.json` を書き直さない）: `弱めた設定が戻る` と `後片付け` が不合格、rc 1。
  - `test_weaken_fails`（`settings.json` を読み取り専用のディレクトリに置くなどで `weaken` が失敗する）: `弱めた設定が戻る` が `[確かめていない]`、rc 1。
  - `test_version_fails_but_settings_match`（偽の `--version` が `settings.json` を雛形に書き戻してから rc 1 で終わる）: `弱めた設定が戻る` が不合格、rc 1。
  - `test_mark_not_removable`（偽の起動口の最後の `-p` の回が、`HOME_MARK` のファイルを消して、同じ名前の中身のあるディレクトリに替える）: `rm -f` が失敗し、`後片付け` が不合格（理由に `HOME_MARK`）、`全体: 不合格`、rc 1。スクリプトは `rm -rf` を使わない。
  - `test_home_not_refused`（偽の起動口が `/home/node` でも rc 0）: rc 1。
  - `test_existing_mark`（`HOME_MARK` を先に置く）: rc 2、目印の中身が変わっていない、偽の起動口が呼ばれていない。
  - `test_lock_held`（試験が lock を持ったまま）: rc 2。`test_lock_missing`（lock のファイルが無い）: rc 0。`test_copilot_home_missing`（`home/node/.copilot` が無い）: rc 0、後で `.copilot` が mode 700 のディレクトリ。
  - `test_dangling_mark`（`HOME_MARK` が壊れた symlink）: rc 2、symlink が残っている。
  - `test_bad_args`（`--runs 0`、`--runs x`、`--runs 08`、`--max-ai-credits 0`、`--model ''`、未知のオプション、位置引数 2 つ、親の無い `--spent-log`、symlink の `--spent-log`、無い作業ディレクトリ、置換後の `/home/node/.x`、置換後の （非公開の場所に保存）、書けない作業ディレクトリ、`/home/node` の祖先への symlink）: rc 2、偽の起動口が呼ばれていない、`settings.json` が変わっていない。
  - `test_spent_log`: `--spent-log` を渡すと 1 行増え、`credits` が 2 回分の合計（5.0）。`FAKE_MODE=no_shutdown` では上限×2＝20.0 で、`what` に「上限で数えた」を含む。渡さなければファイルを作らない。記録先が symlink なら rc 1 で `ERROR:`。
  - `test_interrupted`（`FAKE_MODE=hang` の 2 回目で、試験がスクリプトへ SIGTERM を送る）: rc 1、目印が残らず、`settings.json` が雛形に戻り、`--spent-log` に 1 行だけで `credits` が 1 回目の値＋上限（12.5）、`what` に「中断」。
  - `test_cleanup_on_failure`（偽の起動口の `-p` が rc 1）: rc 1、目印が残らない。
- [ ] **手順 2: 試験が落ちることを確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_copilot_canary.py'` / Expected: スクリプトが無いので FAIL か ERROR。
- [ ] **手順 3: `tests/copilot-canary.sh` を実装する** — 上の「動き」。`set -u`、`set -o pipefail`（`-e` は使わず、各段の rc を見る）。shebang `#!/bin/bash`。
- [ ] **手順 4: 試験と lint を通す** — タスク 1 と タスク 2 の両方の試験のコマンドで OK。`./lint.sh` が rc 0・警告ゼロ。
- [ ] **手順 5: commit** — `git add tests/copilot-canary.sh tests/test_copilot_canary.py && git commit -m "test: Copilot の受け入れ（canary）のスクリプトを足す"`

### タスク 3: test-build.sh と README

**ファイル:**
- 直す: `test-build.sh`（`run_launcher_tests()` の中、`test_copilot_launcher.py` の `check` の行の直後）
- 直す: `README.md`（「変更後の確認」の、Copilot CLI を変えた場合の段落。「さらに、モデルを呼ぶ実機の受け入れ（CI には入れない）を行う: …」の文を含む段落）

- [ ] **手順 1: test-build.sh に 2 行足す** — `check "Copilot の canary の判定（bash の実行がちょうど 1 回・ほかの道具で不合格・コマンドの一致・出力の期待値・モデルの文を見ない・クレジット・設定の弱めと型まで含む一致・消費の 1 行）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_copilot_canary_helper.py"` と、同じ形で `"Copilot の canary の段取り（前提と拒む作業ディレクトリ・目印・名前空間・/home/node での停止・弱めた設定の戻り・後片付けの確認・中断・引数の組・消費の記録）"` の `test_copilot_canary.py`。
- [ ] **手順 2: README を直す** — 実機の受け入れの文の後に、次の趣旨を足す: 「この受け入れは、opt-in のコンテナの入力欄で `! bash tests/copilot-canary.sh` と打つと全部走る（既定は gemini-4-argon で 2 回、1 回の上限 10 クレジット。`--runs`・`--model`・`--max-ai-credits`・`--spent-log FILE`・作業ディレクトリを渡せる）。合否は Copilot のセッション記録に残った実際のコマンドと出力から判定し、項目ごとの表と使ったクレジットを出す。合格しても `VERIFIED_COPILOT_VERSION` は変えない。」 その段落とは別の 1 文で、「`tests/copilot-canary.sh`・`tests/copilot_canary_helper.py` を変えたときは、`./lint.sh`、その試験 2 つを含む `--launcher-only`、実機の canary を行う（イメージのビルドの確認と全体実行は要らない）」と書く（Copilot CLI を変えた場合の一覧には入れない）。
- [ ] **手順 3: 確かめる** — Run: `TMPDIR=/tmp ./test-build.sh --launcher-only` / Expected: 新しい 2 つの `check` が PASS、FAIL=0。`./lint.sh` が rc 0。
- [ ] **手順 4: commit** — `git add test-build.sh README.md && git commit -m "docs: Copilot の受け入れをスクリプトで行えることを書く"`

### タスク 4: 実機の受け入れと仕上げ

- [ ] **手順 1: 実機の受け入れを頼む** — 保守者に、opt-in のコンテナ（このブランチの checkout。`-b` は不要。スクリプトは `/workspace` から読む）の入力欄で `! bash tests/copilot-canary.sh --spent-log <保守者の記録先>` を打ってもらい、出力を受け取る（記録先は保守者が決め、公開の文書に書かない）。Expected: rc 0、`全体: 合格`、各回のクレジットが上限 10 以下で「クレジット不明」の行が無い。不合格の項目が出たら、止まって保守者に報告する（スクリプトの誤りか sandbox の問題かを先に切り分けない）。
- [ ] **手順 2: 全体の検証** — `./lint.sh` rc 0、`TMPDIR=/tmp ./test-build.sh --launcher-only` FAIL=0。全体実行（`./test-build.sh`）は要らない（イメージに入るファイルも起動口も変えないため。タスク 3 の README の文のとおり、このスクリプトの変更で要るのは `./lint.sh`・`--launcher-only`・実機の canary）。コンテナで `./lint.sh` を走らせたときは、compose の検証の `not run` を書く。
- [ ] **手順 3: 実装完了時（PR 前）の二重レビュー**（区分が境界のため）— **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review（結果を受け取って反映するとき）。グローバル `AGENTS.md` のとおり Claude（claude-review skill）と Codex（codex-review skill、Sol）。Sol を Claude のセッションから起動する回は、グローバル `AGENTS.md`「Copilot の並走」も行う。Critical・Important を直し、確認限定巡を終えてから PR を作る。
- [ ] **手順 4: PR を作る** — **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch（push は保守者に確かめてから）。PR 本文に、受け入れの表、PR 前のレビューの判定、未対応の Minor、`not run` の検証と理由を書き、Claude と Codex のレビューの全文を PR コメントに投稿する。タグは提案しない（`tests/` の道具と README の追記で、利用者から見えるインターフェースは変わらない）。
- [ ] **手順 5: PR 後のレビューへ渡す** — PR 後の二重レビュー（区分にかかわらず必須）は作成に関わっていない対話セッションが担うので、handover に PR 番号・対象 commit・実機の受け入れの出力・`not run` の検証を書いて止まる。

---

## 計画レビューの記録

- Self-Review: タスク 4 の手順の受け取りの場面に receiving-code-review の指定が無かったのを足した
- 版: `plan-initial.md` （非公開の場所に保存）
- Claude（claude-opus-5-5、所要 300 秒）: 修正後に渡せる。生の出力 （非公開の場所に保存）
  - C1 外側の名前空間の値の形が未定で常に「違う」になりうる → 採用（数字だけで渡す、rc 2、タスク 2 に同じ名前空間の試験）
  - I1 目印が書けたかを確かめていない → 採用（`set -C` で書いて確かめる、前提に `COPILOT_HOME`・`TOKEN_FILE`）
  - I2 `--session-id` を先に確かめる段が無い → 採用（タスク 0。ホストの 1.0.109 の `--help` には有ることを計画者が確かめた）
  - I3 起動口が拒む作業ディレクトリを前提で止めていない、`pwd -P` → 採用
  - I4 `read_bash` で必ず不合格 → 採用（bash の実行がちょうど 1 つ、ほかの道具は名前付きの理由で不合格）
  - M1 `[確かめていない]` の条件 → 採用 / M2 試しのファイルをその場で消す → 採用 / M3 コマンドを argv で → 採用 / M4 lock のファイルが無いとき・`flock` の固定パス・fd を閉じる → 採用 / M5 rc 127 と書けない作業ディレクトリ → 採用（0・126・127 を不合格、前提に `-w`） / M6 verification-before-completion の位置 → 採用 / M7 PR 後のレビューと並走 → 採用 / M8 CI で走る試験の明記 → 採用 / M9 README の文の分け方 → 採用 / M10 Expected のクレジット → 採用 / M11 `--spent-log` を実機で使う → 採用 / M12 タスク 1 の lint → 採用
- Codex（gpt-6.1-sol、所要 138 秒）: 修正後に渡せる。生の出力 （非公開の場所に保存）
  - I1 拒む作業ディレクトリと symlink の別名、弱めた設定が残る → 採用（Claude の I3 と同じ。試験に symlink を足した）
  - I2 弱められなくても合格 → 採用（`weaken`・起動口・一致の 3 つを要る、`weaken` の失敗は `[確かめていない]`）
  - I3 後片付けの成功を確かめる前に合格 → 採用（後片付けを表と rc の前に行い、項目にした）
  - I4 中断した回の消費の記録 → 採用（trap で 1 回だけ記録、終わっていない回は上限、rc 1）
  - I5 実物の形との照合が無い → 採用（タスク 0 の fixture）
  - M1 型まで含む一致 → 採用 / M2 PR コメントへの全文の投稿と PR 後の引き渡し → 採用（タスク 4 手順 4・5）
- 確認限定巡 1: Codex（I1〜I5、所要 33 秒）→ I1・I4 は直った。I2（起動口が失敗して設定だけ一致する試験）・I3（削除の失敗の試験）・I5（`--session-id` と保存先の対応、欄の型）が部分修正。→ 反映（`test_version_fails_but_settings_match`・`test_mark_not_removable` を足し、タスク 0 で型と `sessionId`＝ディレクトリ名を確かめ、`judge` に `SESSION_ID` を足した）。生の出力 （非公開の場所に保存）
- 確認限定巡 2: Codex（I2・I3・I5、所要 32 秒）→ I2・I3 は直った。I5 は `--session-id` と保存先の対応をタスク 4 へ延ばしていた → 反映（タスク 0 の手順 2 で、モデルを 1 回呼んで実機で確かめる）。生の出力 （非公開の場所に保存）
- 確認限定巡 3: Codex（I5、所要 20 秒）→ 直った。実装に渡せる。生の出力 （非公開の場所に保存）
- carbon（並走、正式外）: 修正後に渡せる。68.2221 クレジット、所要 661 秒、`plan-initial.md` に対して（公開の経路、未 push、base 86b4af4）。生の出力 （非公開の場所に保存）
  - C1（名前空間の形）・C2（拒む作業ディレクトリと `pwd -P`）・I1（弱めの rc）・I4（grep の自己一致）→ Claude・Sol の指摘で反映済み
  - C3 作り直した直後に `~/.copilot` が無い → 採用（前提で `mkdir -m 700`、`test_copilot_home_missing`）
  - I2 trap の分け方 → 反映済み（中断は後片付けと記録を 1 回だけして rc 1）。壊れた symlink と `COPILOT_BIN` の symlink → 採用（`[ -e ] || [ -L ]`、`test_dangling_mark`）
  - I3 引数の誤りをクレジットの前に止める → 採用（`--spent-log`・未知のオプション・`08` など）。`events.jsonl` が無いときの `credits=unknown` → 反映済み。小数の合計 → 採用（python3）
  - I5 verification-before-completion の位置・タスク 1 の lint → 反映済み。全体実行の判断を委ねている・README の文 → 採用（要らないと明記）
  - M1 型の検査 → 採用 / M2 `--version` の WARNING を混ぜない・時刻を 1 回・id に PID → 採用 / M3 `sys.path` → 採用
- 承認の後に行うこと: 生の出力と版を保守者の非公開の場所に写す → carbon の並走（`plan-initial.md` を送る、`-c <spec の commit>`）→ carbon の完了の後に計画を公開の置き場へ写して commit
- 確認限定巡 1: Claude（C1・I1〜I4、所要 27 秒）→ 全部直った。実装に渡せる（任意の残り: 目印が書けない場合の試験）。生の出力 （非公開の場所に保存）

区分: 境界（sandbox の設定をわざと弱める段を持ち、判定を誤ると sandbox が塞いでいないのに「確かめた」と出て、セキュリティ境界の保証を誤らせるため。迷ったら重い方）
推奨実装: Opus（区分が境界でセキュリティ境界の確認を担うため、グローバル指示の Opus を推す条件に当たる。判定順の 1〜5 には当たらない〈実機の確認は保守者が打つので、実装はホストでもコンテナでも進められる〉。Sonnet にしない理由は、判定の規則の取りこぼしがそのまま偽の合格になるため）
実装: Opus（持ち主指定、2026-11-12。新しいセッションへ handover で渡し、executing-plans で実装する）
