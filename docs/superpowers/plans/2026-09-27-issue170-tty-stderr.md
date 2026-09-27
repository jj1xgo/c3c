# TTY なしの確認で `/dev/tty` のリダイレクト失敗の行を出さない（#170）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** TTY が無い状態で `[y/N]` の確認に来たとき、`ERROR`／`INFO` の案内の前に bash のリダイレクト失敗の行（`<script>: line N: /dev/tty: No such device or address`）が stderr に混じらないようにする。停止・委譲の判定（終了コードと分岐）は変えない。

**Architecture:** bash はリダイレクトを左から処理するため、`read -r x </dev/tty 2>/dev/null` では `</dev/tty` の失敗時にまだ stderr が元のままになる。対象の `read` を `{ read -r x </dev/tty; } 2>/dev/null` で囲み、外側で stderr を先に捨てる。リポジトリ内の前例は `c3c:604` の `if ! { exec {tty_fd}<>/dev/tty; } 2>/dev/null; then`。

**Tech Stack:** bash（`c3c`・`entrypoint.sh`）、python3 標準ライブラリの unittest（既存のテストハーネス）、`lint.sh`・`test-build.sh`。

**Issue:** #170（再現手順と直し方の案は Issue 本文）

---

## 前提（計画時に確かめた事実、main 69fd3b9）

- `git grep -n '/dev/tty'` で、`read` を `/dev/tty` から行う箇所は次の 5 か所だけ（`c3c:604` は既に正しい形で、対象外）。

  | # | 場所 | 現在の行 | TTY なしの帰結 |
  |---|---|---|---|
  | 1 | `c3c:1300`（`check_codex_approval`） | `if ! read -r codex_confirm </dev/tty 2>/dev/null; then` | `exit 1` |
  | 2 | `c3c:1492`（`check_claude_project_approval`） | `if ! read -r project_confirm </dev/tty 2>/dev/null; then` | `exit 1` |
  | 3 | `c3c:2199`（`check_mcp_approval`） | `if ! read -r mcp_confirm </dev/tty 2>/dev/null; then` | INFO を出して `return 0`（コンテナ内ゲートへ委譲） |
  | 4 | `entrypoint.sh:160`（`.mcp.json` の stdio ゲート） | `if ! read -r mcp_confirm </dev/tty; then` | `exit 1` |
  | 5 | `entrypoint.sh:185`（project 設定ゲートの再照合） | `if ! read -r project_confirm </dev/tty; then` | `exit 1` |

- 各箇所の TTY なしの経路を通る既存テスト（ハーネスはいずれも `start_new_session=True` で制御端末を持たない）:

  | # | テスト |
  |---|---|
  | 1 | `tests/test_codex_launch.py` `test_no_tty_or_eof_never_launches_codex`（subTest `no tty`） |
  | 2 | `tests/test_claude_project_launch.py` `ApprovalTests.test_no_tty_blocks_unapproved` |
  | 3 | 無し（新規に足す） |
  | 4 | `tests/test_codex_entrypoint.py` `test_claude_gate_still_blocks_without_tty` |
  | 5 | `tests/test_claude_project_entrypoint.py` `test_run_prompts_when_changed_after_approval_and_blocks_without_tty` |

- main のまま、#2 と #3 の TTY なし起動の stderr に `.../c3c: line 1492: /dev/tty: No such device or address` と `.../c3c: line 2199: /dev/tty: No such device or address` が出ることを計画者が実測した（#3 は rc 0・本起動 1 回で、INFO「対話可能な TTY がないため、確認はコンテナ内の MCP 監査ゲートに委ねます。」も出る）。
- 判定の文字列は `'/dev/tty:'`（コロン付き）にする。bash のエラー行は必ず `/dev/tty: <strerror>` の形でパスを含み、ロケールに依らない。`c3c`・`entrypoint.sh` の正規のメッセージにこの文字列は無い（`git grep -n '/dev/tty:' c3c entrypoint.sh` が 0 件）。
- `docs/development-invariants.md` 80・81 行（MCP 監査ゲートと project 設定ゲートを外さない・fail-closed）に触れる変更だが、判定点の終了コードと分岐は変えない。

## ファイル構成

- 変更: `c3c`（3 行）、`entrypoint.sh`（2 行）
- 変更: `tests/test_codex_launch.py`、`tests/test_claude_project_launch.py`、`tests/test_codex_entrypoint.py`、`tests/test_claude_project_entrypoint.py`（アサーション追加と #3 の新規テスト）
- README.md: 変更しない（利用者から見える挙動は stderr の余分な 1 行が消えるだけで、README に該当の記述は無い。実装時に `grep -n 'No such device\|/dev/tty' README.md` で確かめる）

---

### Task 1: 回帰テストを先に足して red を確かめる

**Files:**
- Modify: `tests/test_codex_launch.py`（`test_no_tty_or_eof_never_launches_codex`）
- Modify: `tests/test_claude_project_launch.py`（`ApprovalTests`）
- Modify: `tests/test_codex_entrypoint.py`（`test_claude_gate_still_blocks_without_tty`）
- Modify: `tests/test_claude_project_entrypoint.py`（`test_run_prompts_when_changed_after_approval_and_blocks_without_tty`）

- [ ] **Step 1: 既存 4 テストにアサーションを 1 行ずつ足す**

  既存のアサーション（終了コード・`'TTY'`・本起動なし等）は残し、各テストの末尾に次を足す。

  ```python
  self.assertNotIn('/dev/tty:', result.stderr)
  ```

  `test_no_tty_or_eof_never_launches_codex` は subTest のループ内（`no tty` と `eof` の両方）に足す。`eof` は PTY があるので元から通るが、両方に掛けてよい。

- [ ] **Step 2: #3（`c3c:2199`）の新規テストを `ApprovalTests` に足す**

  `tests/test_claude_project_launch.py` の `ApprovalTests.test_no_tty_blocks_unapproved` の直後に追加する（`json` は既に import 済み）。project 設定は承認済みにして、`.mcp.json` のゲートだけが TTY を求める状態にする。launcher 内の順序は `check_mcp_approval`（2933 行）→ `check_claude_project_approval`（3001 行）。

  ```python
      def test_no_tty_mcp_gate_defers_without_redirect_error(self):
          # #170: TTY なしで .mcp.json の確認に来ても、bash のリダイレクト失敗の行を出さずにコンテナ内ゲートへ委ねる。
          if shutil.which('jq') is None:
              self.skipTest('jq がないため .mcp.json ゲートに到達しない')
          self.approve_claude()
          (self.proj / '.mcp.json').write_text(json.dumps({'mcpServers': {'s': {'command': 'evil'}}}))
          result = self.launch()
          self.assertEqual(result.returncode, 0, result.stderr)
          self.assertIn('確認はコンテナ内の MCP 監査ゲートに委ねます', result.stderr)
          self.assertNotIn('/dev/tty:', result.stderr)
          (run,) = self.main_runs()
          self.assertIn(run['env'].get('MCP_APPROVAL_FILE'), (None, ''))
  ```

  jq が無いと `compute_mcp_state` が `MCP_STATE=nojq` で黙って戻り（`c3c:2116-2118`）、ゲートに届かない。同じハーネスの既存テストと同じく skip する（`tests/test_codex_launch.py:694-696`）。`shutil` は import 済み。委譲時は `MCP_APPROVAL_FILE=""`（`c3c:2171`）のまま本起動へ渡り、コンテナ内ゲートが確認を担う（書き方は `tests/test_codex_launch.py:292` に合わせる）。

- [ ] **Step 3: red を確かめる**

  ```bash
  (cd tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_codex_launch test_claude_project_launch \
    test_codex_entrypoint test_claude_project_entrypoint) >/tmp/issue170-red.log 2>&1; echo "rc=$?"
  grep -nE '^(FAIL|ERROR):|unexpectedly found|^Ran |^FAILED|^OK' /tmp/issue170-red.log
  ```

  Expected（jq がある環境）: `rc=1`。FAIL は 5 件で、#1〜#5 の各テストが 1 件ずつ（#1 は subTest `no tty`）。失敗メッセージはすべて `'/dev/tty:' unexpectedly found`。ERROR は 0 件、それ以外は PASS。5 件のどれかが PASS したら、そのテストが該当の行を通っていない。ERROR が出たら環境の問題（下の「実行条件」）なので、実装へ進まずに原因を調べる。ログは全文を残し、`tail` で切らない。

### Task 2: 5 か所を直す

**Files:**
- Modify: `c3c:1300,1492,2199`
- Modify: `entrypoint.sh:160,185`

- [ ] **Step 1: 5 行を次のとおり置き換える（`printf` のプロンプトは `{ }` の外のまま）**

  | # | 変更前 | 変更後 |
  |---|---|---|
  | 1 | `    if ! read -r codex_confirm </dev/tty 2>/dev/null; then` | `    if ! { read -r codex_confirm </dev/tty; } 2>/dev/null; then` |
  | 2 | `    if ! read -r project_confirm </dev/tty 2>/dev/null; then` | `    if ! { read -r project_confirm </dev/tty; } 2>/dev/null; then` |
  | 3 | `      if ! read -r mcp_confirm </dev/tty 2>/dev/null; then` | `      if ! { read -r mcp_confirm </dev/tty; } 2>/dev/null; then` |
  | 4 | `      if ! read -r mcp_confirm </dev/tty; then` | `      if ! { read -r mcp_confirm </dev/tty; } 2>/dev/null; then` |
  | 5 | `      if ! read -r project_confirm </dev/tty; then` | `      if ! { read -r project_confirm </dev/tty; } 2>/dev/null; then` |

  `{ ...; }` は subshell を作らないので、`read` が設定した変数は後続の `case` からそのまま見える。終了コードは `read`（またはリダイレクト失敗の 1）がそのまま `if !` に渡る。

- [ ] **Step 2: 残りが無いことを確かめる**

  ```bash
  git grep -nE 'read [^|;]*</dev/tty' -- c3c entrypoint.sh
  ```

  Expected: 5 行すべてが `{ read -r ... </dev/tty; } 2>/dev/null` の形。

- [ ] **Step 3: green を確かめる**

  ```bash
  (cd tests && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_codex_launch test_claude_project_launch \
    test_codex_entrypoint test_claude_project_entrypoint) >/tmp/issue170-green.log 2>&1; echo "rc=$?"
  grep -nE '^(FAIL|ERROR):|^Ran |^FAILED|^OK' /tmp/issue170-green.log
  ```

  Expected: `rc=0`、`OK`（FAIL・ERROR 0。jq が無い環境では skip が 1 件）。

### Task 3: 全体の検証と commit

- [ ] **Step 1: lint**

  ```bash
  ./lint.sh >/tmp/issue170-lint.log 2>&1; echo "rc=$?"; tail -3 /tmp/issue170-lint.log
  grep -n 'WARNING\|スキップ' /tmp/issue170-lint.log
  ```

  Expected: `lint OK`、`rc=0`、警告ゼロ。lint は実 Podman の `podman compose config` も行う。Podman が無い・使えずに Compose 検証がスキップされた場合は、`lint OK` でも全項目の完了とは扱わず、Compose 検証を `not run` と理由付きで報告する（AGENTS.md「開発の進め方」）。

- [ ] **Step 2: launcher のテスト一式**

  ```bash
  ./test-build.sh --launcher-only >/tmp/issue170-launcher.log 2>&1; echo "rc=$?"
  grep -nE 'PASS=|FAIL=|^\[FAIL\]|^FAIL' /tmp/issue170-launcher.log | tail -20
  ```

  Expected: `rc=0`、`FAIL=0`。PASS の件数を記録する（main との差は 0 か、この計画で足したテストの分だけ増える）。この一式は fake podman で完結するが、`tests/test_network_timeouts.py` が loopback に HTTP サーバーを bind し、各ハーネスが PTY・`setsid` を使う。

- [ ] **Step 3: 実イメージでの確認（ホスト、実 Podman）**

  README「変更後の確認」節は、project 設定ゲート（`entrypoint.sh` のゲートを含む）の変更では、実イメージの helper と label を `test-build.sh` の通常モードで確かめると定めている。

  ```bash
  ./test-build.sh >/tmp/issue170-full.log 2>&1; echo "rc=$?"
  grep -nE 'PASS=|FAIL=|^\[FAIL\]' /tmp/issue170-full.log | tail -20
  ```

  Expected: `rc=0`、`FAIL=0`。実ビルドのため数分かかり、外部ネットワーク（パッケージ取得）を使う。

  あわせて、TTY の無い状態で未承認の `.claude/settings.json` を持つ一時プロジェクトを起動する。stderr に `/dev/tty:` の行が無く、`ERROR: 対話可能な TTY がないため project 設定を確認できません。起動を中止します` で止まることを見る（初回はこの一時プロジェクトのイメージを一からビルドするので数分かかる）。

  ```bash
  d=$(mktemp -d) && mkdir -p "$d/.claude" && echo '{"hooks":{}}' > "$d/.claude/settings.json" \
    && setsid -w ./c3c claude "$d" </dev/null 2>&1 | grep -n '/dev/tty:\|TTY'; ./c3c --clean "$d"; rm -rf "$d"
  ```

  Expected: `/dev/tty:` を含む行が無く、`TTY` を含む ERROR 行が 1 行。

  コンテナ内の `entrypoint.sh:160/185` は、この実機手順ではホスト側（`c3c:1492`）で先に止まるため通らない。entrypoint 側は、実物の `entrypoint.sh` を bash で動かす Task 1 のテスト（#4・#5）で確かめる。実イメージの entrypoint での TTY なしの確認は `not run` と PR 本文に書く。

  実 Podman・外部ネットワークが無い環境（Codex の sandbox 等）では、この Step は実施しない。`not run` と理由を書き、進行役がホストで行う。

- [ ] **Step 4: commit（1 コミット）**

  ```bash
  git add c3c entrypoint.sh tests/test_codex_launch.py tests/test_claude_project_launch.py \
    tests/test_codex_entrypoint.py tests/test_claude_project_entrypoint.py
  git commit -m "fix: TTY なしの確認で /dev/tty のリダイレクト失敗の行を出さない（#170）"
  ```

  push と PR は持ち主の確認の後。PR 本文には次を書く。
  - `closes #170` と区分。
  - 検証結果: red と green の件数、lint（Compose 検証の実施または `not run`）、`--launcher-only` の PASS/FAIL、通常モードと実機の実施または `not run`。
  - 利用者への影響: `entrypoint.sh` が変わるので、既存イメージでは `-b` で再ビルドするまで境界アセットのドリフトの WARNING が出る。表示だけの修正のため、SemVer のタグ提案はしない。

---

区分: 境界（変更する 5 行は、`docs/development-invariants.md` 80・81 行が「外さない・fail-closed」と定める人手確認ゲートの判定点そのものであり、変えるのは表示だけでも書き損じると停止が素通りになりうる。Issue の起票時は「通常」としたが、迷ったら重い方に従う。計画・実装完了時（PR 前）・PR 後の 3 段の二重レビュー）
推奨実装: Codex（実装者の判定 1〜3 に当たらない。コンテナ内でしか成立しない作業ではなく、`~/.claude` 配下・hook・秘密の経路にも触れず、設計判断は残らない。4 の「host の checkout で完結し、逐語手順と Expected まで確定」に当たる。PTY と `setsid` を使うテストが Codex の sandbox で動かない場合に備え、下の実行条件で失敗の扱いを決めてある）

実装: Codex（持ち主指定、2026-09-27。区分は境界で確定）

## Codex で実装する場合の実行条件

- sandbox: `workspace-write`。外部ネットワークは Task 1・2 と Task 3 Step 1・2 には不要。ただし loopback の bind（`tests/test_network_timeouts.py`）、PTY（`pty.openpty`・`TIOCSCTTY`）、`setsid`、lint の `podman compose config` は要る。Task 3 Step 3（実 Podman・実ビルド・外部ネットワーク）は Codex では行わず、`not run` として進行役がホストで行う。
- sandbox の制約（PTY・`setsid`・socket・Podman・`/tmp` の書き込み・`.git` への書き込み）でテストが ERROR になる、lint の Compose 検証がスキップされる、commit が拒否される場合は、該当の名前とエラー文を記録する。そのうえで昇格を求めて sandbox 外で再実行するか、差分を残して報告して止まる。sandbox 由来の失敗やスキップを FAIL=0 や完了と報告しない。
- `/goal` に渡す文面:

  > `docs/superpowers/plans/2026-09-27-issue170-tty-stderr.md` の計画を、superpowers:executing-plans に従ってブランチ `fix/issue170-tty-stderr` で Task 1 から順に実装する。Task 1 の red（5 件 FAIL、ERROR 0）を確かめてから Task 2 に進む。Task 3 は Step 1・2 を行い、Step 3 は `not run` として進行役に残す。1 コミットにする。push と PR 作成はしない。実装完了時（PR 前）の二重レビューは進行役が行う。完了時は次を報告して止まる: 変更内容、red と green の件数と各ログの該当行、lint と `--launcher-only` の rc と実出力の該当行、`not run` にした項目（Compose 検証のスキップ、sandbox 由来の ERROR を含む）とその理由。

## 計画レビューの記録

- 1 巡目（2026-09-27）: Codex（gpt-6-astra、`codex exec --sandbox read-only`）は「修正後に渡せる」で、Critical 0・Important 2・Minor 1。Claude（claude-opus-5-5、headless、Read/Grep/Glob）は「修正後に渡せる」で、Critical 0・Important 1・Minor 6。
  - 反映した: Claude の I1（jq が無いと新規テストが誤って FAIL になる → skip を追加）、Codex の I1（README が要求する通常モードの検証 → Task 3 Step 3 に追加）、Codex の I2（実行条件と実際の検証範囲のずれ → loopback・PTY・Podman を区別し、`not run` の扱いを `/goal` に追加）、Codex の Minor（`| tail` で rc と詳細が消える → ログを全文保存）。Claude の Minor 1（委譲時の `MCP_APPROVAL_FILE`）、2（`PYTHONDONTWRITEBYTECODE`）、3（entrypoint 側の実機は `not run` と明記）、4（ドリフトの WARNING を PR 本文へ）、5（`.git` の書き込み）、6（実機のビルド時間）。
- 確認限定 1 巡目（2026-09-27）: Codex（新しい `codex exec`、read-only）は Important 2 件と Minor が直ったことを確かめ、「実装に渡せる」とした。Claude（`--resume`、claude-opus-5-5）は Important 1 件が直ったことを確かめ、「実装に渡せる」とした。計画は 2 巡で収束した。
