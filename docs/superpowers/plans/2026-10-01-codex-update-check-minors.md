# #192 #190 の未対応 Minor 3 件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** #190（PR #191）の PR 前・PR 後レビューで Minor のまま残した 3 件を直す。検査の取りこぼしを無くし、FAIL のときの手掛かりを残し、古い固定版の限界を README に書く。

**Architecture:** 動作の変更は無い。`test-build.sh` の 2 か所（opt-out の検査式と、要件ファイルの probe の doctor 部分）と、README「イメージの変更」節の末尾の 1 文だけを変える。

**Tech Stack:** bash（`test-build.sh`）、POSIX sh（コンテナ内で評価する probe）、Podman、README。

**Spec:** [#192](https://github.com/jj1xgo/c3c/issues/192)（本文を 2026-10-01 に gh で確認。対応案 1〜3 をそのまま採る）。由来は `docs/superpowers/plans/2026-10-01-codex-update-check-requirements.md` の「PR 前レビュー結果」の未対応 Minor 1〜3。

**計画者:** Opus 5.5（claude-opus-5-5、コンテナ内セッション）。

## 背景

- このコンテナには `podman` が無い（`command -v podman` が空）。`test-build.sh` の実ビルドは host でしか回せない。
- `check()`（`test-build.sh:28`）はコマンドの stdout と stderr をまとめて `.claude/test-results/` のログに書く。probe が echo した内容は、FAIL のときにログで読める。
- probe は `sh -c` に渡す単一引用符の文字列（`CODEX_REQUIREMENTS_PROBE`、`test-build.sh:2418` 付近）。中に単一引用符を入れない。

## Global Constraints

- 編集したら `./lint.sh` を rc 0・警告ゼロで通す（Compose 検証を含む host で）。
- `test-build.sh` を変えるので、`./test-build.sh --build-only` と引数なしの全体実行 `./test-build.sh` をやり直す（handover の指示、#192 の本文）。
- 他セッションの変更と、未追跡の `.c3c/codex-version.txt`・`tests/__pycache__/` に触れない。
- 日本語で書く（README「表記」節）。README の新しい文は上流のソースを読んだ判断であり、実測していないことを明記する。
- commit は 1 つ。push と PR は持ち主の確認を得てから。

## Review Focus

1. opt-out のイメージに `/etc/codex` が dangling symlink で残る場合、検査は FAIL すべき（現状は PASS で見逃す）。
2. probe の doctor が失敗したとき、ログに doctor の stderr が出るべき（現状は `2>/dev/null` で消える）。
3. doctor が正常で実効値が false のときは、stderr の出力が増えずに PASS のままであるべき（stderr の表示を失敗時だけにする）。
4. probe の文字列に単一引用符を入れると `sh -c` の引数が壊れる。新しい関数とメッセージは二重引用符だけで書く。
5. README の新しい文は「効かない」と断定せず、上流のソースからの判断で未実測であることを示すべき。

---

### Task 1: `test-build.sh` の 2 か所を直す

**Files:**
- Modify: `test-build.sh`（opt-out の検査式、2574 行付近。probe の doctor 部分と直前のコメント、2415〜2437 行付近）

**Interfaces:**
- Consumes: 既存の `check()`、`CODEX_REQUIREMENTS_PROBE`、ビルド済みのテストイメージ `localhost/claude-test`（`--build-only` が作る）。
- Produces: 無し（テストの内部だけ）。

- [x] **Step 1: テスト用イメージを用意する（host）**

Run: `./test-build.sh --build-only`
Expected: `結果: PASS=22  FAIL=0`。終わった後も `localhost/claude-test` が残っていること（`podman image exists localhost/claude-test && echo ok` が `ok`）。残らない場合は、Step 2・3 の RED を `not run` にして理由を記録し、Step 4 へ進む。

- [x] **Step 2: RED（opt-out の検査式が dangling symlink を見逃すこと）**

`/etc/codex` を dangling symlink に置き換えて、今の式と新しい式を同じ条件で評価する。

```bash
podman run --rm --network=none --user root localhost/claude-test sh -c '
  rm -rf /etc/codex && ln -s /nonexistent /etc/codex || exit 9
  if [ ! -e /etc/codex ]; then echo "old: PASS（見逃し）"; else echo "old: FAIL"; fi
  if [ ! -e /etc/codex ] && [ ! -L /etc/codex ]; then echo "new: PASS（見逃し）"; else echo "new: FAIL（検出）"; fi'
```

Expected: `old: PASS（見逃し）` と `new: FAIL（検出）`。rc 9 で止まった場合は root でも消せなかったので、その出力を記録して `not run` 扱いにする。

- [x] **Step 3: RED（probe が doctor の stderr を捨てること）**

stderr に目印を書いて失敗する偽の `codex` を PATH の先頭に置き、今の probe を流す。

```bash
SCRATCH="$(mktemp -d)"
mkdir "$SCRATCH/stub"
printf '#!/bin/sh\necho "stub: doctor failed on purpose" >&2\nexit 1\n' > "$SCRATCH/stub/codex"
chmod 755 "$SCRATCH/stub/codex"
python3 - "$SCRATCH/probe.sh" <<'PY'
import pathlib, re, sys
s = pathlib.Path("test-build.sh").read_text()
m = re.search(r"^CODEX_REQUIREMENTS_PROBE='(.*?)'\ncheck ", s, re.S | re.M)
pathlib.Path(sys.argv[1]).write_text(m.group(1))
PY
podman run --rm --network=none -v "$SCRATCH/stub:/stub:ro" \
  -e PATH=/stub:/usr/local/bin:/usr/bin:/bin \
  localhost/claude-test sh -c "$(cat "$SCRATCH/probe.sh")"; echo "rc=$?"
```

Expected: rc が 0 以外、`codex doctor --json（rc=1）から更新確認の実効値を読めない` が出て、`stub: doctor failed on purpose` は出ない。SELinux でマウントが読めない場合は `:ro` を `:ro,z` にする。

- [x] **Step 4: opt-out の検査式を直す**

`test-build.sh` の opt-out の check（2574 行付近）の末尾を次のように変える。説明の文字列は変えない。

変更前:
```
[ ! -e /usr/local/libexec/c3c/codex-bwrap ] && [ ! -e /etc/codex ]'
```
変更後:
```
[ ! -e /usr/local/libexec/c3c/codex-bwrap ] && [ ! -e /etc/codex ] && [ ! -L /etc/codex ]'
```

- [x] **Step 5: probe の doctor 部分を直す**

probe の直前のコメント（2415〜2417 行）の 3 行目の末尾に次を足す。

変更前:
```
# 終了コードでは判定しない。timeout（124）だけは失敗にし、JSON にキーが無ければ（上流の出力形式の変更）失敗させる。
```
変更後:
```
# 終了コードでは判定しない。timeout（124）だけは失敗にし、JSON にキーが無ければ（上流の出力形式の変更）失敗させる。
# doctor の stderr はファイルに残し、失敗したときだけ出す（原因を追う手掛かり）。
```

probe の doctor 部分（`rc=0` の次の行から `[ "$v" = false ] ...` の行まで）を次に置き換える。

変更前:
```
CODEX_HOME="$home" timeout 60 codex -c check_for_update_on_startup=true doctor --json > "$home/doctor.json" 2>/dev/null || rc=$?
[ "$rc" != 124 ] || { echo "codex doctor が 60 秒で終わらない"; exit 1; }
v="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"checks\"][\"updates.status\"][\"details\"][\"check for update on startup\"])" "$home/doctor.json")" \
  || { echo "codex doctor --json（rc=$rc）から更新確認の実効値を読めない（上流の出力形式の変更を疑う）"; exit 1; }
[ "$v" = false ] || { echo "要件ファイルがあるのに更新確認の実効値が $v"; exit 1; }
```
変更後:
```
CODEX_HOME="$home" timeout 60 codex -c check_for_update_on_startup=true doctor --json > "$home/doctor.json" 2>"$home/doctor.err" || rc=$?
doctor_fail() { echo "$1"; echo "--- codex doctor の stderr ---"; cat "$home/doctor.err"; exit 1; }
[ "$rc" != 124 ] || doctor_fail "codex doctor が 60 秒で終わらない"
v="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"checks\"][\"updates.status\"][\"details\"][\"check for update on startup\"])" "$home/doctor.json")" \
  || doctor_fail "codex doctor --json（rc=$rc）から更新確認の実効値を読めない（上流の出力形式の変更を疑う）"
[ "$v" = false ] || doctor_fail "要件ファイルがあるのに更新確認の実効値が $v"
```

単一引用符を足していないことを確かめる: `python3 - <<'PY'` で Step 3 と同じ抽出をして、`"'" in m.group(1)` が `False` であること。

- [x] **Step 6: GREEN（Step 2・3 をやり直す）**

Step 2 の `new:` の行は、Step 4 の式そのものなので、Step 2 の Expected のままでよい（`new: FAIL（検出）`）。
Step 3 は、probe を抽出し直して（Step 3 の python ブロックを再実行）同じ `podman run` を流す。
Expected: rc が 0 以外。`codex doctor --json（rc=1）から更新確認の実効値を読めない（上流の出力形式の変更を疑う）`、`--- codex doctor の stderr ---`、`stub: doctor failed on purpose` の 3 行が出る。

- [x] **Step 7: lint と回帰（host）**

Run: `./lint.sh`
Expected: rc 0、警告ゼロ。

Run: `./test-build.sh --build-only`
Expected: `PASS=22  FAIL=0`。要件ファイルの check が PASS で、ログのその check の出力に `--- codex doctor の stderr ---` が出ていないこと（Review Focus 3）。

Run: `./test-build.sh`
Expected: `FAIL=0`（前回は PASS=589）。`Codex opt-out: codex が入っていない（起動口・同梱 bubblewrap・要件ファイルなし）` が PASS。PASS の件数が 589 から変わったら理由を記録する。

`TMPDIR` が `/var/tmp` か `/run/user/<uid>` 配下なら、README「変更後の確認」節のとおり `TMPDIR=/tmp` を付ける。

後片付け: `rm -rf "$SCRATCH"`。

### Task 2: README に 0.146.0 より前の版の限界を書き、commit する

**Files:**
- Modify: `README.md:622`（「イメージの変更」節の Codex の段落の最後の文）
- Modify: `docs/superpowers/plans/2026-10-01-codex-update-check-minors.md`（この計画。計画者が承認後に main へ commit して渡す。実装者は末尾に実装結果を足す）。#190 の計画ファイルは変えない。

- [x] **Step 1: README の最後の文を置き換える**

変更前:
```
要件ファイルでこの設定を扱えるのは、上流のソースでは rust-v0.146.0 以降（それより前の版はこのキーを無視すると読んでいるが、未確認）。
```
変更後:
```
要件ファイルでこの設定を扱えるのは、上流のソースでは rust-v0.146.0 以降。それより前の版を `.c3c/codex-version.txt` で固定した場合は要件ファイルが効かず、ログインシェルや `podman exec` から名前で呼ぶ対話 `codex` では起動時の更新確認が止まらない（上流のソースを読んだ判断で、実測はしていない）。
```

- [x] **Step 2: lint**

Run: `./lint.sh`
Expected: rc 0、警告ゼロ。

- [x] **Step 3: 計画ファイルに実装結果を書き、commit する**

計画ファイルの末尾に「## 実装結果」を足し、Task 1 の各 Step の実際の出力（RED・GREEN の行、PASS/FAIL の件数、lint の rc）と、実行しなかった項目を `not run` と理由付きで書く。

```bash
git switch -c fix/codex-update-check-minors
git add test-build.sh README.md docs/superpowers/plans/2026-10-01-codex-update-check-minors.md
git commit -m "fix: #190 の未対応 Minor を直す（opt-out の symlink 検査、doctor の stderr、0.146.0 より前の版）

Closes #192"
```

commit の末尾には、実装者のセッションの attribution の行を付ける。push と PR は持ち主に確認してから行う。PR 本文には、区分が軽量のため計画レビューと PR 前レビューを省いたこと、PR 後の二重レビューを行うことを書く。

---

## レビューと実行条件

- PR 後に、作成に関わっていない Codex（`codex exec --model gpt-6-astra --sandbox read-only`、先に background、stdin は `< /dev/null`）と Claude（Opus、対話セッション）の二重レビューを行う。マージは PR 後を担う Claude のセッションが 3 条件を確かめてから行う。
- タグ: 利用者から見えるインターフェースは変わらない（テストと README だけ）ので、タグは提案しない。
- Codex の実行条件: host の checkout（`~/…/c3c`）。sandbox は `workspace-write` で、Podman の実行と `podman run` のための host の許可が要る。ネットワークは `--build-only` と全体実行のイメージ取得とパッケージ導入に要る。sandbox 内で Podman が制限された場合は、許可を得て host で再実行し、スキップを検証の成功として扱わない。`/goal` は持ち主が明示した場合だけ開始する。

`/goal` に渡す文面: 「#192 の計画 `docs/superpowers/plans/2026-10-01-codex-update-check-minors.md` を executing-plans で実装する。test-build.sh の opt-out の検査式と probe の doctor 部分、README の 1 文を、計画の逐語どおりに変えて 1 つの commit にする。Task 1 の RED と GREEN、lint、test-build の --build-only と引数なしの全体実行を host で行い、実際の出力を計画末尾の実装結果に書く。他セッションの変更と未追跡ファイルに触れず、未実施の項目は not run と理由を書く。push と PR は持ち主の確認を得てから行う。」

区分: 軽量 — テストの検査式 2 か所と README の 1 文で、製品の動作・境界アセット・権限に効かず、変更は逐語で確定しているため。レビューは PR 後の二重レビューだけ。

推奨実装: Codex — 判定基準を上から当てると、1（コンテナ内でしか成立しない）は当たらない。むしろ実ビルドの検証に Podman が要り、このコンテナには無いので host が必要になる。2・3 も当たらず、host の checkout で完結し逐語手順と Expected まで確定しているので 4 に当たる。

実装: Codex（持ち主指定、2026-10-01。host の checkout で、計画末尾の `/goal` の文面を渡す）


## 実装結果

2026-10-01、host の Codex（GPT-6.1 Sol、セッションの `turn_context.model` は `gpt-6.1-sol`）が、`2fec672` から `fix/codex-update-check-minors` を切って実装した。テストの 2 か所と README の 1 文は計画の逐語どおり。既存の未追跡ファイルは対象外とした。

- Task 1 Step 1: host の `TMPDIR=/tmp ./test-build.sh --build-only` は rc 0、`PASS=22  FAIL=0`。`podman image exists localhost/claude-test` は rc 0、`ok`。ログ: `.claude/test-results/2026-10-01_194132.log`。
- Step 2 RED: `old: PASS（見逃し）` と `new: FAIL（検出）`、rc 0。使い捨てコンテナ内で `/etc/codex` を dangling symlink に置き換えられた。
- Step 3 RED: probe は rc 1。`codex doctor --json（rc=1）から更新確認の実効値を読めない（上流の出力形式の変更を疑う）` が出て、`stub: doctor failed on purpose` は出なかった。不正な JSON を読む Python の traceback も出た。
- Step 4・5: opt-out に `[ ! -L /etc/codex ]` を追加し、doctor の stderr をファイルへ保存して失敗時だけ表示する関数を追加。probe を抽出した単一引用符の検査は `False`。
- Step 6 GREEN: symlink は RED と同じ `old: PASS（見逃し）` / `new: FAIL（検出）`。probe は rc 1 で、上記の JSON 読取失敗メッセージに加え、`--- codex doctor の stderr ---` と `stub: doctor failed on purpose` が出た。Python の traceback は RED と同じ。
- Step 7: host の `./lint.sh` は rc 0、警告ゼロ、Compose 検証を含め `lint OK`。修正後の `TMPDIR=/tmp ./test-build.sh --build-only` は rc 0、`PASS=22  FAIL=0`。成功ログに stderr の見出しが無いことも確認した（`.claude/test-results/2026-10-01_194645.log`）。
- Step 7 全体: host の `TMPDIR=/tmp ./test-build.sh` は rc 0、`PASS=589  FAIL=0`（前回と同数）。opt-out のビルド、Codex と起動口・同梱 bubblewrap・要件ファイルの不在、Node default の 3 検査はすべて PASS。契約・ランチャー検査も全体実行に含まれる。ログ: `.claude/test-results/2026-10-01_195055.log`。
- Task 2: README の 1 文を逐語どおり置換。変更後の host lint も rc 0、警告ゼロ、Compose 検証を含め `lint OK`。

環境制約と未実施範囲:

- sandbox 内の初回 build-only は rc 1（`PASS=1  FAIL=2`、Podman と DNS の制約）。sandbox 内 lint も Podman の `/run` 書込制約で rc 1。いずれも host 権限で再実行し、上記の成功を確認した。
- host の各実ビルドでは GitHub meta の取得が既知の 403 で失敗し、既存スナップショットを再利用した。meta の新規取得は未確認であり、テスト成功と分けて扱う。
- 0.146.0 より前の Codex の実測は not run（今回の計画対象外。README に未実測であることを明記）。
- 計画レビュー・PR 前レビューは、承認済みの軽量区分に従って省略。PR 後の独立した二重レビューは未実施（PR 作成前）。push・PR は持ち主の確認後に行う。

手順の判断: 全体テスト待ちに、独立な README の置換を先行した。実行中の `test-build.sh` は変更していない。追加 worktree は作らず、承認済み計画が指定する checkout と専用ブランチを使用した。検証済みのテストは、記録・commit のためだけには繰り返さない。
