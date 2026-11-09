# Copilot CLI をビルド時の最新版で入れる Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `copilot-version.txt` に `latest` を書けるようにし、ビルドの中で sandbox の設定が読めているかを確かめて止め、確かめた版と違う版の起動では WARNING を出す。

**Architecture:** Codex の `latest`（`CODEX_CACHEBUST`）と同じ形で `COPILOT_CACHEBUST` を足す。Dockerfile の `# >>> c3c copilot` の区間で、入った Copilot に `config --list --json` を打たせ、起動口が書くのと同じ設定の葉が全部、型も含めて同じ値で出ていなければ止める。確認は区間の中の `node -e '...'` で書く（RUN の行継続で改行が消えるので Python は書けない。`# >>> c3c codex-bwrap` の区間と同じ形で、テストが抜き出して試す）。起動口 `copilot-launcher.sh` は `readonly VERIFIED_COPILOT_VERSION` と Copilot の `package.json` の版を比べる。

**Tech Stack:** bash、Dockerfile（Podman）、Node.js（`node -e`）、Python 3（`unittest`）。

**Spec:** `docs/superpowers/specs/2026-11-09-copilot-latest-design.md`（commit 28a6ec1）

## Context

保守者は、Copilot の版を上げるたびに番号を調べるのが手間で、最新を使うのがポリシーなので、`-b` でその時点の最新を入れたい（2026-11-09 の会話）。前回の設計は sandbox を 1.0.103 でだけ確かめたので番号に限っていた。新しい版で sandbox の設定の項目が黙って捨てられる危険を、ビルドの中の確認（止める）と起動時の WARNING（止めない）で拾う。設計は保守者が承認済み。

## Global Constraints

- **REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に 1 回読み込む。コードを変える計画のため）
- 版の書式: `^([0-9]+\.[0-9]+\.[0-9]+|latest)$`（`c3c` の `guard_build_input_defaults()` と `Dockerfile.claude` の両方）。ERROR の文言は `ERROR: <path> には 1.0.103 のような素のバージョンか、文字どおり "latest" を書いてください（実際の値: <value>）`（Dockerfile 側は `<path>` が `.c3c/copilot-version.txt`）。同梱の `copilot-version.txt` は 0 バイトのまま。
- `COPILOT_CACHEBUST` は `copilot-version.txt` の値が `latest` のときだけ `date +%s`、ほかは `pinned`（Codex と同じ）。
- 確かめた版: `readonly VERIFIED_COPILOT_VERSION=1.0.103`（`copilot-launcher.sh`）。
- ビルドの確認の入力: 雛形に `sandbox.userPolicy.filesystem.readonlyPaths = ["/workspace"]` を足したもの（起動口が `cwd=/workspace` で書くものと同じ）。比べ方: 入力の葉（object を辿った末端。array は 1 つの値）が全部出力にあり、型も含めて同じ（真偽値は真偽値、array は要素の型と並びまで同じ）。出力の余分な項目は許す。
- ビルドの確認の環境: `HOME`・`COPILOT_HOME`（どちらも一時のディレクトリ）・`PATH=/usr/local/bin:/usr/bin:/bin`・`COPILOT_AUTO_UPDATE=false` だけ。stdin は閉じる。打ち切りは 60 秒。
- 確認を飛ばす口（環境変数・ARG）を作らない。`--check` には知らせを足さない（設計で任された点。起動口の WARNING とビルドの確認で足りるため）。
- `docs/development-invariants.md` の Copilot の項と `copilot-launcher.sh` の項を、変更の前に読む（root `AGENTS.md`）。
- 挙動を変えた Task は、その Task の commit に README と不変条件の該当箇所の直しを含める（root `AGENTS.md`「挙動を変えたら README.md の該当節も同じコミットで更新する」）。
- 各 Task の編集の後に `./lint.sh`（rc 0、警告ゼロ。Compose の検証はコンテナ内では skip → `not run` と報告）。
- 文書は日本語（README「表記」節）。
- ブランチ `feat/copilot-latest`（設計の commit 28a6ec1 の上）。push と PR は持ち主に確かめてから。
- 実ビルド（`./test-build.sh` の全体実行と `--build-only`）はホストの podman が要るので、Task 4 で持ち主に 1 回まとめて頼む。それまでは待たずに先へ進む。

## Review Focus

1. `latest` が prerelease（`1.1.0-beta.1`）に解決された → 版の検査で ERROR、ビルドが止まる（Task 1 の `test_installed_version_check`）。
2. `config --list --json` が非 0、JSON でない、空、形が違う（`[]`・`null`・`{"sandbox": []}`）、打ち切り → どれも `ERROR:` の行と rc 1（traceback で落ちない）（Task 2 の `test_config_command_failures_fail_closed`）。
3. 新しい版が葉を 1 つ捨てる（`readonlyPaths` を含む）、値を変える、型だけ変える（`false`→`0`、`true`→`"true"`）、array を並べ替える → 止まる（Task 2 の `test_dropped_or_changed_leaf_fails`）。実物の Copilot が知らない項目を捨てて確認が止まることを、実ビルドの陰性でも確かめる（Task 2 の `test-build.sh`）。
4. 番号で固定した古い版でも WARNING が出て起動は続き、確かめた版では出ない。`package.json` が無い・壊れている・版が文字列でないときは ERROR（Task 3）。
5. 空・番号のプロジェクトで `COPILOT_CACHEBUST` が `pinned` のまま（Task 1 の `test_rebuild_cachebust_follows_resolved_copilot_version`）。

---

### Task 1: `latest` を受け、`COPILOT_CACHEBUST` で入れ直す

**Files:**
- Modify: `c3c`（`guard_build_input_defaults()` の Copilot の分岐と上のコメント、`run_explicit_build()`）
- Modify: `compose.yml`（build args に `COPILOT_CACHEBUST: ${COPILOT_CACHEBUST:-pinned}`）
- Modify: `Dockerfile.claude`（`# >>> c3c copilot` の区間: `ARG COPILOT_CACHEBUST=pinned`、RUN の先頭の `echo "copilot-cachebust=${COPILOT_CACHEBUST}"`、書式、入った版の検査、最後の INFO の行を `$installed` に、所有者・mode の検査の一覧に `$pkg/package.json`、区間の上のコメント）
- Modify: `README.md`（「利用側プロジェクトの設定」の `copilot-version.txt` の行と段落、「Copilot CLI を使う」の入れ方の 1・3 と「永続化と更新」）、`docs/development-invariants.md`（Copilot の区間の項の書式と CACHEBUST）
- Test: `tests/test_c3c_config.py`、`tests/test_c3c_launch.py`（記録する env の名前に `COPILOT_CACHEBUST`）、`tests/test_copilot_config_check.py`（新規。この Task では版の検査の部分だけ）、`test-build.sh`

**Interfaces:**
- Produces: ビルドの環境変数 `COPILOT_CACHEBUST`。区間の shell 変数 `installed`（入った版）と `pkg`（`/usr/local/lib/node_modules/@github/copilot`）。Task 2 はこの後ろ（ネイティブのバイナリの検査の後、起動口を置く前）に確認を置く。
- Produces: `tests/test_copilot_config_check.py` の `extract_block()`（`tests/test_codex_bwrap.py` と同じく、区間の開始・終了のコメントが一組であることを確かめ、行継続だけを除く）。

- [ ] **Step 1: 失敗するテストを書く**
  - `tests/test_c3c_config.py`:
    - `test_copilot_version_latest`: `latest` → 通常起動の stderr に `INFO: Copilot 版: latest（採用元: project <path>）`、`--check` の stdout に `[INFO] Copilot 版: latest（採用元: project <path>）`、rc 0。
    - `test_copilot_version_bad_format_fails` を直す: 値は `('1.0', '1.0.103-beta', 'LATEST', 'latest-1')`、文言は Global Constraints のもの。
    - `test_rebuild_cachebust_follows_resolved_copilot_version`: 値 `(None, '1.0.103', '', 'latest')` で `-b` → `latest` のときだけ `COPILOT_CACHEBUST` が `^\d+$`、ほかは `pinned`。
  - `tests/test_copilot_config_check.py`:
    - `test_installed_version_check`: 区間から、版の検査の shell 部分（`installed=` の行から、その検査の `}` まで）を抜き出し、`node` を偽のスクリプト（`-p` に決めた版を返す）に替えて `sh -c` で動かす。指定 `latest` × 入った版 `1.0.110` → rc 0、`1.1.0-beta.1`・空 → rc 非 0 と ERROR。指定 `1.0.103` × `1.0.103` → rc 0、`1.0.110` → rc 非 0。
- [ ] **Step 2:** `python3 -m unittest tests.test_c3c_config tests.test_copilot_config_check` → 新しいテストが FAIL。
- [ ] **Step 3: 実装する。** Global Constraints の書式・文言にし、`run_explicit_build()` に `codex_cachebust` と同じ形の `copilot_cachebust` を足して build の環境に渡す。Dockerfile の版の検査は、`latest` なら `installed` が `^[0-9]+\.[0-9]+\.[0-9]+$`、番号なら今の一致。README と不変条件の書式・CACHEBUST・`latest` の意味（`-b` のたびに最新）を同じ commit で直す（「`latest` は受けない」の記述を消す）。
- [ ] **Step 4:** `test-build.sh` の全体実行を直す: 陰性の `latest` を `1.0`（文言「素のバージョン」）に替える。`latest` の陽性のビルドを足し、`COPILOT_PROBE` は `$1=latest` のとき版の比較を「`package.json` の版が `X.Y.Z`」にする。新しいテストのファイルを `run_launcher_tests()` の Copilot の `check` の並びに足す（`--launcher-only` でも走る）。
- [ ] **Step 5:** `python3 -m unittest tests.test_c3c_config tests.test_c3c_launch tests.test_copilot_config_check` → PASS。`./lint.sh` → rc 0。
- [ ] **Step 6: Commit** `feat: copilot-version.txt で latest を受け、-b のたびに最新を入れる`

### Task 2: ビルドの中で sandbox の設定の読みを確かめる

**Files:**
- Modify: `Dockerfile.claude`（区間に `node -e` の確認を 1 つ）
- Modify: `README.md`（「Copilot CLI を使う」: ビルドの中の確認、拾えないもの 3 つ〈意味だけの変化、新しい項目のゆるい既定値、MXC の backend の変更〉、飛ばす口は無く通らなければ番号で固定して逃げる）、`docs/development-invariants.md`（区間の項: 入力・環境・比べ方・fail-closed・飛ばす口なし・一時の home を消す）
- Test: `tests/test_copilot_config_check.py`、`test-build.sh`

**Interfaces:**
- Consumes: `installed`・`pkg`・`expected`（`$pkg/npm-loader.js`）と `/tmp/copilot-settings.json`（Task 1 の区間）。
- Produces: 区間の中の `node -e '<script>' <loader> <template> <readonlyPath> <timeoutSeconds>` がちょうど 1 つ（`node -e '` は区間に 1 回だけ）。RUN からは `node -e '...' "$expected" /tmp/copilot-settings.json /workspace 60 || { echo "ERROR: ..." >&2; exit 1; }` で呼ぶ。スクリプトは単一引用符と `//` の行コメントを含まない（行継続で 1 行になるため）。成功で rc 0 と `INFO: Copilot <installed> が sandbox の設定を全部読めることを確かめました` の 1 行、失敗で `ERROR: ` で始まる行（違った葉のドット区切りの名前を含む）と rc 1。

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_copilot_config_check.py`。`extract_script()` は `tests/test_codex_bwrap.py` と同じく `node -e '([^']*)'` を 1 つだけ抜き出す。`<loader>` には一時の偽のスクリプト〈argv・環境・`COPILOT_HOME/settings.json` を記録し、決めた stdout と rc を返す。打ち切りの試験は `exec sleep 5`〉を渡し、`<timeoutSeconds>` は 1）
  - `test_passes_when_all_leaves_match`: 偽の出力 = 入力（並びを変えた JSON）→ rc 0。argv が `['config', '--list', '--json']`、環境のキーがちょうど `HOME`・`COPILOT_HOME`・`PATH`・`COPILOT_AUTO_UPDATE`（値 `false`）、書かれた `settings.json` が雛形＋`readonlyPaths: ["/workspace"]`。
  - `test_matches_launcher_settings`: 起動口（`tests/test_copilot_launcher.py` の setUp と同じ置換）を実際に走らせて書かれた `settings.json` の `readonlyPaths` を `["/workspace"]` に替えたものと、確認が書いた `settings.json` が等しい（組み立てのずれを拾う。設計の「判断」）。
  - `test_extra_output_is_allowed`: 出力に `sandbox.newKey`・`footer` が増えても rc 0。
  - `test_dropped_or_changed_leaf_fails`: subTest で `readonlyPaths` を消す、`allowOutbound` を `true`、`allowOutbound` を `0`、`enabled` を `"true"`、`deniedPaths` を並べ替える、`auth` を消す → rc 1、ERROR にその葉の名前（例 `sandbox.userPolicy.network.allowOutbound`）。
  - `test_config_command_failures_fail_closed`: 偽が rc 1／JSON でない／空／`[]`／`null`／`{"sandbox": []}`／打ち切り → rc 1 で `ERROR:` の行があり、`at ` で始まる traceback の行が無い。
  - `test_temp_home_removed`: 成功でも失敗でも、一時の home が残らない（偽が記録した `COPILOT_HOME` のパスが、終了後に無い）。
  - `test_run_wiring_fails_build`: 区間から確認の呼び出しの shell 部分を抜き出し、`node` を rc 1 を返す偽に替えて `sh -c` で動かす → rc 非 0（`set -e` と `|| exit 1` の配線）。
  - `test_no_bypass`: 区間の `ARG` が `COPILOT_CACHEBUST` だけ、区間に `SKIP` を含む名前が無い。
- [ ] **Step 2:** `python3 -m unittest tests.test_copilot_config_check` → 新しいテストが FAIL。
- [ ] **Step 3: 実装する。** スクリプトは `fs.mkdtempSync` で一時の home を作り、`try { … } finally { fs.rmSync(home, {recursive: true, force: true}) }`。`child_process.spawnSync(loader, ["config", "--list", "--json"], {env, stdio: ["ignore", "pipe", "pipe"], timeout: seconds * 1000})`。比較は葉ごとに `typeof` と値（array は `JSON.stringify` の一致）。例外はすべて捕まえて `ERROR:` の 1 行にする。README と不変条件を同じ commit で直す。
- [ ] **Step 4:** `test-build.sh` の全体実行に陰性を足す: 雛形に `"bogusKey": 1` を `sandbox` の下に足した `copilot-settings.json` をビルドの文脈に置いて番号（1.0.103）でビルド → 失敗し、出力に `sandbox.bogusKey` を含む（実物の Copilot が知らない項目を捨てることを使う。設計の「項目を 1 つ捨てる版を模す」をこれで代える）。既存の陽性のビルドのログに上の INFO の行があることも見る。
- [ ] **Step 5:** `python3 -m unittest tests.test_copilot_config_check tests.test_copilot_launcher` → PASS。`./lint.sh` → rc 0。
- [ ] **Step 6: Commit** `feat: ビルドで Copilot が sandbox の設定を全部読めることを確かめる`

### Task 3: 起動口で確かめた版と比べ、違えば WARNING を出す

**Files:**
- Modify: `copilot-launcher.sh`（手順 1 の後に版の比較、先頭のコメントの手順の一覧）
- Modify: `README.md`（「Copilot CLI を使う」: 起動時の WARNING、確かめた版を上げる手順〈「変更後の確認」の受け入れの canary に合格した後に定数を上げる PR〉）、`docs/development-invariants.md`（`copilot-launcher.sh` の項: 定数、手順の順序に「版の比較〈違えば WARNING〉」を中継の確認の次に入れる、`package.json` が読めなければ ERROR）
- Test: `tests/test_copilot_launcher.py`、`test-build.sh`（`COPILOT_PROBE`）

**Interfaces:**
- Consumes: `COPILOT_JS`（既存の `readonly`）。`package.json` は `"${COPILOT_JS%/*}/package.json"` で作る（新しい固定パスの定数を足さない。Dockerfile の `COPILOT_JS` の照合がそのまま効く）。
- Produces: `readonly VERIFIED_COPILOT_VERSION=1.0.103`。WARNING の行は `WARNING: Copilot CLI <入った版> は、c3c が sandbox を canary で確かめた版（1.0.103）と違います。` で始め、ビルドで設定の読みは確かめたが通信が塞がれるかは確かめていないこと、README「変更後の確認」の Copilot の受け入れを続ける。

- [ ] **Step 1: 失敗するテストを書く。** `setUp` で偽の `npm-loader.js` の隣に `package.json`（`{"version": "1.0.103"}`）を置く。
  - `test_no_warning_for_verified_version`: 1.0.103 → stderr に `WARNING` が無く、起動する。
  - `test_warns_for_other_version`: `1.0.110` と `1.0.90` → stderr に上の WARNING がちょうど 1 行、rc 0 で起動する。トークンが出力に無い。
  - `test_refuses_unreadable_package_json`: 無い／JSON でない／`version` が無い・数値・空・改行入り → `assert_refused`。
  - `test_verified_version_constant`: 起動口に `readonly VERIFIED_COPILOT_VERSION=` がちょうど 1 行あり、値が `X.Y.Z`。
- [ ] **Step 2:** `python3 -m unittest tests.test_copilot_launcher` → 新しいテストが FAIL。
- [ ] **Step 3: 実装する。** 版は `"$PYTHON3" -I -c` で `package.json` を読み、空でない印字できる 1 行の文字列だけを受ける（それ以外は `fail`）。違えば WARNING を `>&2` に 1 回。手順 1 の直後に置く。README と不変条件を同じ commit で直す。
- [ ] **Step 4:** `test-build.sh` の `COPILOT_PROBE` に足す: トークンが無くて止まる出力（`out`）に、入った版が 1.0.103 なら `WARNING: Copilot CLI` が無く、ほか（`latest` の陽性）ならある。
- [ ] **Step 5:** `python3 -m unittest tests.test_copilot_launcher` → PASS。`rg -n 'latest.?.?(は|を)(受けない|使えない)' README.md docs/development-invariants.md c3c Dockerfile.claude test-build.sh` → 0 件（rc 1 で正常。前回の設計と計画の文書は当時の記録なので対象外）。`./lint.sh` → rc 0。
- [ ] **Step 6: Commit** `feat: Copilot の起動口で、確かめた版と違えば WARNING を出す`

### Task 4: 検証と取り込み

- [ ] **Step 1:** `./lint.sh` と `./test-build.sh --launcher-only` を走らせ、結果を記録する。
- [ ] **Step 2（ホスト、持ち主）:** 持ち主にホストで `./test-build.sh --build-only` と全体実行を頼む（`latest` の陽性、`1.0` の陰性、`bogusKey` の陰性、番号の既存の陽性、WARNING の probe）。結果を受け取るまで、Step 3 のレビューは進めてよい。返らなければ `not run` と理由を PR 本文に書く。
- [ ] **Step 3:** 実装完了時（PR 前）の二重レビュー（区分: 境界）。Claude 側は グローバルの skill `claude-review`（`.agents/skills/claude-review/SKILL.md`）、Codex 側は `codex-review`（`.agents/skills/codex-review/SKILL.md`、gpt-6.1-sol）。**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review で受け取り、Critical・Important を直して確認限定巡。
- [ ] **Step 4:** **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch。レビューの反映の後に Step 1 を走らせ直し、push して PR を作る選択肢を選ぶ（push は持ち主に確かめる）。PR 本文に判定・未対応の Minor・`not run` を書き、レビューの全文をコメントに投稿する。台帳と `review-data`（`.agents/skills/review-data/SKILL.md`）に記録する。
- [ ] **Step 5:** PR 後の二重レビューを、作成に関わっていない対話セッションへ handover で渡す（対象 commit、生のログ、`not run` の項目）。マージはそのセッションが 3 条件で行う。
- [ ] **Step 6（持ち主、マージ後）:** 保守者のローカルの `.c3c/copilot-version.txt` を `latest` にし、ops の `.claude/AGENTS.md` の台帳の行（「2026-11-09 から 1.0.103」）を直す（ops に commit）。`-b` で再ビルドし、`copilot --version` と WARNING の有無を見る。新しい版なら README「変更後の確認」の受け入れの canary を回し、合格したら `VERIFIED_COPILOT_VERSION` を上げる別の PR を作る。
- [ ] **Step 7:** SemVer: `.c3c/` の設定形式（`latest` を受ける）とデフォルト挙動（起動時の WARNING）が変わるので、マージ後に MINOR のタグを提案する（root `AGENTS.md`、`.claude/skills/release-tag/SKILL.md`）。

---

## 計画レビューの記録

- Self-Review: Task 2 の node の場所（`/usr/bin/node` 固定 → `command -v node`）を直した（初回の前）。
- 版: `plan-initial.md` `<scratchpad>/tasks/bldqngx3g.output`
- Claude（claude-opus-5-5 ＋ claude-fable-5-1、session `f27780a8-7cbe-4d3c-af2c-941ba84489b5`、所要 420 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bh3c5z6sh.output`
  - C1 RUN の行継続で `python3 -I -c` は構文が壊れる → 採用（`node -e` に替えた）
  - I1 起動口とビルドの確認の組み立てのずれがテストで分からない → 採用（`test_matches_launcher_settings`）
  - I2 型の厳密さ → 採用（Codex I1 と同じ）
  - I3 grep が直し残しを拾わない → 採用（`rg`、`test-build.sh` も対象）
  - I4 実ビルドの時点が早い → 採用（Task 4 Step 2 にまとめ、WARNING の probe を足した）
  - I5 `latest` の陽性で probe が落ちる → 採用（Task 1 Step 4）
  - I6 `COPILOT_AUTO_UPDATE=false` が無い → 採用
  - I7 `package.json` の場所が二通り → 採用（`COPILOT_JS` から作る）
  - I8 不変条件の順序 → 採用（Task 3 の Files）
  - I9 verification の位置 → 採用（Codex I4 と同じ）
  - M1 打ち切りの秒数を引数に、`exec sleep` → 採用。M2 形の違う JSON → 採用。M3 版の検査を動かして確かめる → 採用（`test_installed_version_check`）。M4 INFO を `$installed` に → 採用。M5 `package.json` を所有者の検査に → 採用。M6 `--check` → 採用（足さないと明記）。M7 → 採用（`bogusKey` の実ビルドの陰性で代える）。M8 → 採用（`run_launcher_tests()`）。M9 → 採用（Task 4 Step 4・5）
- Codex（gpt-6.1-sol、所要 168 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bbg5m3lvl.output`
  - I1 型の違い → 採用
  - I2 実ビルドで確認が止まる検証が無い、版の検査が文字列だけ → 採用（`bogusKey` の陰性、`test_run_wiring_fails_build`、`test_installed_version_check`）
  - I3 README を同じ commit で → 採用（各 Task に文書を含め、旧 Task 4 を分けた）
  - I4 PR 直前の verification → 採用
  - I5 PR 後の引き渡し → 採用（Task 4 Step 5）
  - M1 grep → 採用。M2 ローカルの skill のパス → 採用（ホームを書かない相対の表記）
- 確認限定巡 1: Codex（I1〜I5・M1・M2、所要 25 秒）→ 全部直った、実装に渡せる。生の出力 `<scratchpad>/tasks/b76wgbl1w.output`
- 確認限定巡 1: Claude（C1・I1〜I9、`--resume`、所要 21 秒）→ 全部直った、実装に渡せる。生の出力 `<scratchpad>/tasks/b4o64g6q3.output`
- argon の並走: 走らせない（コンテナの中のセッションの回は対象外）。

区分: 境界（Copilot の sandbox の境界と不変条件〈`latest` を受けない〉を変え、トークンを読む起動口に手を入れるため）
推奨実装: Opus（判定順の 2「秘密やトークンを読む経路に触れる変更」に当たる。起動口はトークンを読むファイルで、セキュリティ境界も含むので Sonnet ではなく Opus。実ビルドはホストの podman が要るので、その確認だけ持ち主に頼む）
実装: Opus（持ち主指定、2026-11-09。このセッションで executing-plans）
