# #243 コンテナの中の Claude Code で /cd を止める Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** c3c のイメージに Claude Code の managed settings を焼き込み、`permissions.deny: ["Cd"]` でコンテナの中の `/cd` を使えなくする。managed settings を持たない既存イメージでは、Claude 経路の起動を止めて `-b` を案内する。

**Architecture:** #190 の Codex 要件ファイルと同じく、`Dockerfile.claude` の RUN の中で `/etc/claude-code/managed-settings.json` を root:root 0644 で生成する（別アセットにしない。`Dockerfile.claude` が `ASSET_HASH_TARGETS` に入っているのでドリフトも検知される）。対応を示す label `io.c3c.claude-managed-settings=1` を付け、launcher は `guard_image_layout()` が取得済みの `podman image exists` の rc を使って、Claude 経路でだけこの label を照合する（`podman image exists` を呼び直さない）。

**Tech Stack:** bash（`c3c`・`test-build.sh`）、Dockerfile、Python unittest（`tests/test_c3c_launch.py` ほか）。

**Spec:** c3c#243（本文の再現・対応案）と #232 のコメント（実測 2026-11-05）。持ち主の決定（2026-11-05）: 案 A（managed settings で `/cd` を止める）、旧イメージは label で止める。

## Context

#232 の実測（使い捨ての repo、Claude Code 2.1.318）で、コンテナの中で `/cd .claude/worktrees/wt2` を打つと、移った先の `.claude/settings.json` の PreToolUse hook が確認なしに実行された。c3c の起動時の Claude project 設定ゲートは起動した checkout しか見ないので、別の branch の worktree の hook がゲートを迂回する。worktree は main の trust を使うので、`/cd` の trust の確認も出ない。公式文書（https://code.claude.com/docs/en/permissions の「Cd」節）では、規則に `Cd` とだけ書いた deny で `/cd` 全体を止められ、`/cd` は人だけが打てる（モデルからは呼べない）。managed settings は Linux では `/etc/claude-code/managed-settings.json` で、user・project・local・`--settings` のどれも上書きできない（https://code.claude.com/docs/en/managed-settings 、https://code.claude.com/docs/en/settings の「Settings precedence」）。

範囲の外（文書の限界に書くだけ。下の「限界の 5 項」）:
1. `/workspace` で branch を切り替えたときの project 設定の変化（設定ファイルの監視で hook が読み直される。https://code.claude.com/docs/en/settings の「When edits take effect」）。`SECURITY-CLAIMS.md` の C-5「限界・非対象」の 1 つ目（本起動の再照合の後の変更は検出しない）に当たる。実測は not run。
2. `EnterWorktree`（2.1.318 では移った先の設定を読み直さなかった。版で変わりうる）。
3. `/add-dir` でサブディレクトリの skills・commands・subagents が確認なしに読まれる（文書の記述、2.1.257 以降）。
4. Team・Enterprise の server-managed settings（claude.ai から配るもの）がある利用者では、既定の `"first-wins"` で server-managed が選ばれ、イメージのファイルは読まれない。
5. `Cd` 規則に対応していない古い Claude Code の版（`CLAUDE_CODE_VERSION` で固定したとき）では、managed settings の不正な項目は読み飛ばされるので `/cd` が止まらない恐れがある。label は焼き込みを示すだけで、効いていることは示さない。

## Global Constraints

- **REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に読み込む）
- managed settings の中身は次の 1 つだけにする（ほかの key を足さない）: `{"permissions": {"deny": ["Cd"]}}`
- 置き場: ファイル `/etc/claude-code/managed-settings.json` を root:root 0644、ディレクトリ `/etc/claude-code` を root:root 0755
- **Codex の版指定（opt-out を含む）やほかのビルド入力に関わらず、常に作る**。RUN ブロックは、ベースのパッケージを入れる最初の RUN 群の直後（`COPY validate-build-input.sh /tmp/` より前）に置く（停止の検査を早く終わらせるため。#190 の codex-requirements の分岐を写さない）
- base image が次のどれかなら、ビルドを止める（上書き・追記・chmod で直さない。#190 と同じ方針）: `/etc/claude-code/managed-settings.json` がある（symlink・dangling symlink を含む。`[ -e ] || [ -L ]` で判定）、`/etc/claude-code/managed-settings.d` がある（同じ判定）、既存の `/etc/claude-code` が symlink か、ディレクトリでないか、root:root 0755 でない（所有者・グループ・mode のどれが違っても止める）
- RUN ブロックは、上の検査をすべて終えてから初めて書き込む（`install -d`・ファイルの作成・`chown`・`chmod`）。検査の途中で何かを作ったり変えたりしない（止めたときに base image の既存の中身を変えないため）
- label: `io.c3c.claude-managed-settings`、値 `1`。launcher の定数 `CLAUDE_MANAGED_SETTINGS_LABEL`・`CLAUDE_MANAGED_SETTINGS_VERSION=1`（readonly）。`Dockerfile.claude` の label は `LABEL io.c3c.image-layout` と同じ位置（`CACHEBUST` 消費 RUN より後）に置く
- `IMAGE_LAYOUT_VERSION` は上げない（配置のパスは変えないため）。`guard_asset_drift()` は fail-open のまま
- Codex 経路（`AGENT=codex`）はこの label で止めない（Codex 経路では Claude Code の `/cd` を使わない。止めると Codex 利用者に不要な `-b` を強いる）
- 挙動を変える commit には、その挙動を説明する README・`SECURITY-CLAIMS.md`・`docs/development-invariants.md` の更新を同じ commit に入れる（root `AGENTS.md`）
- 各 Task の commit の前に `./lint.sh` が rc 0・警告ゼロ（Compose 検証を環境の制約でスキップしたら、その旨と `not run` を報告に書く）
- 公開リポジトリに入る文面に、ホストのパス・vault・非公開のリポジトリの名前を書かない。移行の案内に版の番号は書かない（タグの提案の後に決まるため）
- 日本語で書く（README「表記」節）

## Review Focus

1. Codex 経路（`c3c codex`）は label が無くても止めない → Task 2 のテスト `test_managed_settings_codex_path_not_checked`
2. イメージ未ビルドで `-b` なしの初回起動（compose の暗黙ビルド）は止めない → `test_managed_settings_image_absent_skips`
3. `-b` のときは見ない（この後に作り直すため） → `test_managed_settings_build_flag_skips`
4. Codex の opt-out ビルドでも managed settings が入る → Task 1 の opt-out イメージの検査
5. `--check`（agent 無指定は Claude の診断）: label の無いイメージを `[FAIL]` で報告し、起動しない → `test_check_reports_managed_settings`

---

### Task 0: 作業ブランチを作る

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

- [ ] **Step 1:** `git status -sb` と `git worktree list` で、ほかのセッションの変更や worktree が無いことを確かめる。あれば止めて持ち主に報告する
- [ ] **Step 2:** `main` を `origin/main` に揃え（`git fetch && git status -sb` で `## main...origin/main` に ahead/behind が無いこと）、`git switch -c fix/243-managed-cd-deny`

### Task 1: イメージに managed settings を焼き込み、label を付ける

**Files:**
- Modify: `Dockerfile.claude`（`# >>> c3c claude-managed-settings` ブロックを Global Constraints の位置に、label は `LABEL io.c3c.image-layout` の近く）
- Test: `test-build.sh`（`--build-only` の実イメージ検査。既存の `check "コンテナ内の配置 label"` と `/etc/codex/requirements.toml` の probe に並べる。Codex opt-out のイメージの検査〈`OPTOUT_IMAGE`〉にも足す）
- Modify: `README.md`（「セキュリティモデル」節に `/cd` の項）、`SECURITY-CLAIMS.md`（C-5 の保証と「限界・非対象」）、`docs/development-invariants.md`（`Dockerfile.claude` の項に、#190 の codex-requirements の項と並べて 1 項）

**Interfaces:**
- Produces: イメージの `/etc/claude-code/managed-settings.json`（内容は Global Constraints の JSON）、label `io.c3c.claude-managed-settings=1`

- [ ] **Step 1:** `docs/development-invariants.md` の `Dockerfile.claude` の項（#190 の codex-requirements の項を含む）を読む（root `AGENTS.md` の求め）
- [ ] **Step 2: `test-build.sh` の `--build-only` に検査を足す（先に失敗させる）**
  - `check "Claude managed settings label"`: `podman image inspect` の `io.c3c.claude-managed-settings` が `1`
  - `check "Claude managed settings の配置"`: コンテナの中で `stat -c %u:%g:%a /etc/claude-code` が `0:0:755`、`/etc/claude-code/managed-settings.json` が `0:0:644`、`python3 -I -c` で読んだ JSON が `{"permissions": {"deny": ["Cd"]}}` と等しい、node ユーザーでそのファイルに書けない（`test -w` が偽）
  - opt-out のイメージ（`OPTOUT_IMAGE`）にも `check "Codex opt-out: Claude managed settings がある"`（同じ配置と内容）
- [ ] **Step 3:** `./test-build.sh --build-only` を実行して、上の検査が FAIL することを確かめる
- [ ] **Step 4:** `Dockerfile.claude` に RUN ブロックと label を足す（Global Constraints の値・位置・停止条件。コメントに #243、`Cd` deny の意味、server-managed が優先される限界を 2〜3 行）
- [ ] **Step 5:** `./test-build.sh --build-only` を実行して PASS を確かめる
- [ ] **Step 6: 停止条件を手動ビルドで確かめる**（#190 の計画 `docs/superpowers/plans/2026-10-01-codex-update-check-requirements.md` の停止の確認と同じ型）。scratchpad に `FROM debian:testing` と 1 つの RUN で仕込む base を作り、`podman build -t localhost/c3c-243-base-<case> -f <base の Dockerfile> <空ディレクトリ>` で base を作ってから、c3c のビルドコンテキスト（`test-build.sh` の `stage_common_context` と同じ中身）で `podman build --build-arg BASE_IMAGE=localhost/c3c-243-base-<case> -f Dockerfile.claude ...` を実行する。ケースと Expected:
  - (a) `managed-settings.json` が通常ファイル → rc ≠ 0、`ERROR:` と `managed-settings.json` を含む
  - (b) `managed-settings.json` が dangling symlink → (a) と同じ
  - (c) `managed-settings.d` がディレクトリ → rc ≠ 0、`managed-settings.d` を含む
  - (d) `managed-settings.d` が dangling symlink → (c) と同じ
  - (e) `/etc/claude-code` が別のディレクトリへの symlink → rc ≠ 0、`/etc/claude-code` を含む
  - (f) `/etc/claude-code` が root:root 0775 → rc ≠ 0、`0755` を含む
  - (h) `/etc/claude-code` が 1000:1000 の 0755（所有者の不正）→ rc ≠ 0、`root:root` か `0:0` を含む
  - (g) 対照: `/etc/claude-code` が root:root 0755 の空ディレクトリ → ビルド成功、ファイルが Step 2 の配置と内容になる
  - 既存の中身を変えないことは、ビルドが失敗するとイメージが残らないので実物では確かめられない。代わりに、RUN ブロックで検査がすべて書き込みより前にあることを、PR 前のレビューの確認項目にする（PR 本文にもその旨を書く）
  - 結果（ケースごとの rc と ERROR の行）を PR 本文に書く。終わったら作った base とイメージを `podman rmi` で消す
- [ ] **Step 7: 文書を書く**
  - README「セキュリティモデル」節に `/cd` の項: イメージの managed settings が `/cd` を止める理由（#243 の再現の要点）、Context の「限界の 5 項」、Codex 経路は対象外であること
  - `SECURITY-CLAIMS.md` の C-5: 保証する動作に「イメージの managed settings で `/cd` を止める」を足し、「限界・非対象」に限界の 5 項（1 つ目は既存の 1 つ目を指す形）を足す
  - `docs/development-invariants.md`: 停止条件、置く位置と理由（opt-out に関わらず作る）、label の位置、`IMAGE_LAYOUT_VERSION` を上げない理由
  - README の #201 の項の「組織の managed settings か Team・Enterprise のサインインが無い環境では…」: c3c のコンテナには managed settings のファイルがある、と事実だけ足す。mod の承認の扱いが変わるかは実測していない（not run）と書き、変わったとは書かない
  - 実際に効いているかを確かめる手段: 認証なしで managed settings の読み込みを確かめるコマンドは分かっていないので、`--build-only` は配置と内容だけを見て、効き目は Task 3 の実機の確認で見る、と invariants に 1 文
- [ ] **Step 8:** `./lint.sh` が rc 0・警告ゼロ
- [ ] **Step 9: Commit** `feat: イメージに managed settings を置き、コンテナの中の /cd を止める（#243）`

### Task 2: 既存イメージの label を照合するガード

**Files:**
- Modify: `c3c`（定数は `IMAGE_LAYOUT_LABEL` の近く。判定関数 `check_claude_managed_settings()` は `check_image_layout()` の後。呼び出しは 2 か所: `guard_image_layout()` の中と、`--check` のイメージ節）
- Test: `tests/test_c3c_launch.py`（`io.c3c.image-layout` の既存テストに並べる）、`test-build.sh` の `--launcher-only` の LY 系に並べた MS 系
- Modify（fake の更新）: fake podman が label を返す箇所と、`compose build` のときに label の状態を更新する箇所の両方。少なくとも次を変える（ほかに `grep -rn 'io.c3c.image-layout\|build_layout' tests test-build.sh` で当たる所があればそれも）:
  - `tests/test_c3c_launch.py` の Python の `PODMAN`: `image inspect` の分岐に `io.c3c.claude-managed-settings` → `state.get('managed', '1')`、`compose build` の分岐に `state['managed'] = state.get('build_managed', '1')`
  - `tests/test_c3c_launch.py` の `BASH_PODMAN`（python3 が無い環境のテスト用）: `image inspect` の case に `*io.c3c.claude-managed-settings*) echo 1`
  - `tests/test_codex_launch.py` の `PODMAN`（`test_claude_project_launch.py` もこれを使う）: `image inspect` と `compose build` の両方に、上と同じ形
  - `test-build.sh` の fake（`io.c3c.image-layout` を返す行の近く）: `TEST_CLAUDE_MANAGED_SETTINGS` で上書きできる形、既定 `1`
- Modify: `README.md`（`/cd` の項に「managed settings を持たない既存イメージは、Claude 経路では `-b` まで起動しない。`c3c --check` は agent 無指定だと Claude の診断なので、Codex だけを使う利用者でも `[FAIL]` が出る」）、`docs/development-invariants.md`（`c3c` の項に 1 項: 判定は取得済みの rc で行い呼び直さない、Codex 経路を対象外にする理由）、README「変更後の確認」節（managed settings の RUN・label・ガードを変えたら `--build-only` と `--launcher-only` を実行し、実起動で `/cd` が拒否されることを確かめる）

**Interfaces:**
- Consumes: Task 1 の label `io.c3c.claude-managed-settings=1`
- Produces: `check_claude_managed_settings()`（引数なし。`check_image_layout()` が rc 0 で label を照合した後に呼ばれる前提で、`AGENT` が `claude` でなければ何もしない。`podman image inspect` で label を読み（inspect 自体が失敗したら、`guard_claude_project_image_support()` と同じく「イメージ $IMAGE_NAME を inspect できないため、managed settings への対応を確認できません。起動を中止します。」で `guard_fail`）、`1` でなければ `guard_fail`、`CHECK_MODE=1` なら `[OK]   Claude managed settings: $CLAUDE_MANAGED_SETTINGS_LABEL=1` を出す）
- 呼び出し: (1) `check_image_layout()` の rc 0 の分岐で配置の照合が通った後に `check_claude_managed_settings || return 1`（通常起動は `guard_image_layout()` 経由。`-b` のときは `guard_image_layout()` が先に return するので見ない）。(2) `--check` の `check_one_project()` は `check_image_layout 0` を呼ぶ既存の分岐を通るので、(1) で足りる。新しく `podman image exists` を呼ばない

- [ ] **Step 1:** `docs/development-invariants.md` の `guard_image_layout()` の項（LY-7 の再検査の禁止を含む）を読む
- [ ] **Step 2: 失敗するテストを書く**（`tests/test_c3c_launch.py`）
  - `test_managed_settings_label_missing_stops_before_compose`: label が空のイメージで `c3c claude <dir>` → rc ≠ 0、compose が 1 回も呼ばれない、stderr に `io.c3c.claude-managed-settings` と `-b` を含む
  - `test_managed_settings_label_present_proceeds`: label `1` → compose の run まで進む
  - `test_managed_settings_build_flag_skips`: `-b` → このガードで止まらない
  - `test_managed_settings_image_absent_skips`: `podman image exists` rc 1 → 止まらない
  - `test_managed_settings_codex_path_not_checked`: `c3c codex <dir>` で label が空でも、このガードの文言で止まらない
  - `test_check_reports_managed_settings`: `--check` で label 空 → 出力に `[FAIL]` か `ERROR` と label 名、label `1` → `[OK]   Claude managed settings`
  - `test_managed_settings_no_extra_image_exists`: 通常起動で `podman image exists` を呼ぶ回数が、変更前と同じ（fake の呼び出し記録で数える）
- [ ] **Step 3:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_c3c_launch.py -v` で新しいテストが FAIL することを確かめる
- [ ] **Step 4:** `c3c` に定数・関数・呼び出しを足し、fake podman を更新する。止めるときの文言: `ERROR: イメージ $IMAGE_NAME はコンテナの中の /cd を止める managed settings を持っていません（label $CLAUDE_MANAGED_SETTINGS_LABEL=${v:-なし}、必要な値 $CLAUDE_MANAGED_SETTINGS_VERSION）。-b で再ビルドしてください（#243）。起動を中止します。`（`${AGENT_RESELECT_HINT:+"$AGENT_RESELECT_HINT"}` も `check_image_layout` と同じく渡す）
- [ ] **Step 5:** `./test-build.sh --launcher-only` を実行して全 PASS を確かめる（`test-build.sh` の MS 系 3 本: label 空で止まる、`1` で進む、`--check` で FAIL。既存のテストが fake の更新漏れで落ちないこと）
- [ ] **Step 6:** 文書（Files の README・invariants・「変更後の確認」）を書く
- [ ] **Step 7:** `./lint.sh` が rc 0・警告ゼロ
- [ ] **Step 8: Commit** `feat: managed settings を持たない既存イメージでは Claude の起動を止める（#243）`

### Task 3: 実機の確認、レビュー、取り込み

- [ ] **Step 1: 実機の確認（持ち主に操作を頼む）**。手順は持ち主がそのまま貼れる形で 1 つずつ示す。使い捨ての repo（`git init`、`worktree.useRelativePaths true`、`.c3c/base-image.txt` は `debian:testing`）を作り、main には `.claude/` を置かず、`.claude/worktrees/wt2`（別 branch）にだけ、Bash の前に `.marker` へ 1 行書く PreToolUse hook を置いて commit する（#232 の実測と同じ形）
  1. 実装前の版（`main`）の `c3c` でビルドした既存イメージに対して、ブランチの `c3c --check <dir>` → label 名と `-b` の案内が出る。`c3c claude <dir>` → 起動しない
  2. `c3c claude -b <dir>` で起動し、行頭に空白を入れずに `/cd .claude/worktrees/wt2` を打つ → Expected: 移動が拒否され（作業ディレクトリが変わらない）、続けて Claude に Bash で `pwd` を実行させても `/workspace` のまま、ホストに `.marker` ができない
  3. 同じセッションで `/status` → `Setting sources` に managed settings のファイルが出る
  4. `/exit`。終わったら使い捨ての repo のイメージを `c3c --clean <dir>` で消す
- [ ] **Step 2: REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion — `./lint.sh`、`./test-build.sh --launcher-only`、`./test-build.sh --build-only` の結果、Task 1 Step 6 のケースの結果、Step 1 の表示を照合する。未実行は `not run` と理由
- [ ] **Step 3: 実装完了時（PR 前）の二重レビュー**（区分が境界のため。Claude は `claude-review` skill、Codex は `codex-review` skill の `codex-review.sh --provider openai -m gpt-6.1-sol`、argon の並走はグローバル `AGENTS.md` の規則のとおり）
- [ ] **Step 4: REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review — Critical・Important を直し、確認限定巡を終える
- [ ] **Step 5:** 計画の写しを `docs/superpowers/plans/2026-11-05-managed-cd-deny-243.md` に置く（ホストのパス・vault・非公開の名前を消す）。検査は、ホストのパス・一時ディレクトリ・非公開のリポジトリの名前・トークンの設定名を探す grep の出力が空であること（検査式は公開の写しには載せない）。写しを commit する（`docs: #243 の計画を置く`）
- [ ] **Step 6: REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → **REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch — Step 4 で変えたものに関係する検証（lint、該当するテストのモード）をやり直してから、push して PR を作る（push は持ち主に確認）。PR 本文に `Fixes #243`、レビューの判定と未対応の Minor、Task 1 Step 6 の結果。Claude と Codex のレビューの全文を PR コメントに
- [ ] **Step 7: PR 後の二重レビューを手配する**。PR 後は作成に関わっていないセッションが担う（グローバル指示）。handover（`handover` skill）に、PR 番号、対象の SHA、計画の場所、PR 前のレビューの結果（PR コメント）、実機の確認の記録、未確認の事項を書き、持ち主に PR 後の Claude の対話セッションを開いてもらう。Codex の PR 後のレビューは、そのセッションが `codex-review` skill で起動する
- [ ] **Step 8:** SemVer のタグを提案する（既定の挙動が変わり、旧イメージは `-b` が要る。`--check` が検出することは Step 1 で確認済み。番号案と根拠を README「バージョニング」節に照らして示し、作成は承認の後。マージの後に行う）

---

## 計画レビューの記録

- Self-Review: テスト駆動の指定（計画の先頭）の漏れを修正
- 版: `plan-initial.md` `<scratchpad>/tasks/b4dx4f0og.output`
- Claude（claude-opus-5-5、session `51b5291e-d13f-424d-89aa-e50301d8fe97`、所要 324 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bhkrduc9d.output`
  - I1 作業ブランチの Step が無い → 採用（Task 0）
  - I2 README を別の commit で直す → 採用（文書を Task 1・2 の commit に含め、旧 Task 3 を解体）
  - I3 lint が各 Task に無い → 採用（Global Constraints と各 Task の Step）
  - I4 SECURITY-CLAIMS の C-5 が対象外 → 採用（Task 1 Step 7）
  - I5 opt-out でもファイルを置く要件とテストが無い → 採用（置く位置を早い RUN に変え、常に作る。opt-out の検査を追加）
  - I6 停止条件の検証が無い → 採用（Task 1 Step 6 の手動ビルド 7 ケース）
  - I7 PR 前に verification-before-completion が無い → 採用（Task 3 Step 6）
  - M1 `--check` での呼び方 → 採用（判定を `check_image_layout()` の rc 0 の分岐から呼ぶ設計に変更）
  - M2 限界 (2) の参照先の誤り → 採用（C-5 の限界の 1 つ目に）
  - M3 移行の版の番号と置き場所 → 採用（番号は書かない、置き場所は `/cd` の項）
  - M4 実機の確認の Expected と #232 の再現 → 採用（Task 3 Step 1）
  - M5 古い版の限界 → 採用（限界の 5 項目）
  - M6 効き目の確かめ方 → 採用（手段が無いことを invariants に書き、実機で見る）
  - M7 写しの commit → 採用
  - M8 invariants を先に読む → 採用（Task 1・2 の Step 1）
  - M9 Codex だけの利用者の `--check` → 採用（README に 1 文）
- Codex（gpt-6.1-sol、所要 115 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/b8bryqj0r.output`
  - I1 停止条件のテストが無い → 採用（Claude I6 と同じ。dangling symlink と対照のケースを含める）
  - I2 rc 125 のテストが既存ガードだけで通る → 採用（設計で解消: 新しい判定は取得済みの rc を使い `podman image exists` を呼び直さないので、rc 125 は既存の判定が止める。代わりに呼び出し回数のテストを追加）
  - I3 挙動の変更と README が別の commit → 採用（Claude I2 と同じ）
  - I4 修正後の検証と PR 後のレビューへの引き継ぎが無い → 採用（Task 3 Step 6・7）
  - M1 写しの検査式が自身に一致する → 採用（検査式の行を除く）
  - M2 作業ブランチの扱い → 採用（Claude I1 と同じ）
- 確認限定巡 1: Codex（I1〜I4、所要 21 秒）→ I2・I3・I4 は解消、I1 は一部未解消（所有者の不正のケースと既存の中身の保持の確認が無い）→ ケース (h) と「検査を書き込みより前に終える」制約を追加。生の出力 `<scratchpad>/tasks/bj32qzry5.output`
- 確認限定巡 2: Codex（I1 の残り、所要 25 秒）→ 解消、実装に渡せる。生の出力 `<scratchpad>/tasks/b6hyyln9f.output`
- argon（並走、正式外）: 承認の後に起動（初回に Sol が読んだ版 `plan-initial.md`、c3c の HEAD 8cd1b5e）。非公開に置いた計画の経路の dry-run は rc 2 `ambiguous issue reference`（名前の無い `#N` を、公開の c3c では自分のリポジトリとして照会できない）。#237 の前例に合わせて公開の経路（`-D docs/superpowers/plans/2026-11-05-managed-cd-deny-243.md`）で送った（持ち主に確かめずに切り替えた。持ち主の判断は「今回はよいが、次からは聞く」、2026-11-05）。Sol と材料が違った点: 写しの Task 3 Step 5 の検査式（非公開の名前とホストのパスを含む）を説明の文に置き換えた。依頼文はグローバル指示のファイルを渡していない（名前だけ）。結果: 修正後に渡せる（31.9961 クレジット、所要 231 秒）。生の出力 `<pairing-runs>/20261105-c3c-plan-243-argon/out.txt`
  - I1 `--check` での呼び方と `[FAIL]` の行が出ない → 採用済み（Claude M1 の反映で、判定は `check_image_layout()` の rc 0 の分岐から呼び、期待は「`[FAIL]` か `ERROR`」になっていた。計画の変更なし）
  - I2 fake podman の更新対象の漏れ（`BASH_PODMAN`、`test_codex_launch.py`、`compose build` の状態の更新は grep の文字列に当たらない）→ 採用（Task 2 の Files に対象を明示）。Sol の確認限定巡で確かめる
  - M1 managed-settings.d の検査と opt-out の分岐 → 採用済み（Global Constraints にある）
  - M2 inspect 自体の失敗の扱い → 採用（別の文言で止める）
- 確認限定巡 3: Codex（argon の I2、所要 25 秒）→ 解消、実装に渡せる。生の出力 `<scratchpad>/tasks/b4es7ewc0.output`
- 承認の後に計画を変えた点（argon の反映）: Task 2 の fake の更新対象の明示、inspect の失敗の文言。持ち主に示した（2026-11-05）
- 生の出力と版の保存先: 非公開の場所（公開の写しには置かない）
- 確認限定巡 1: Claude（I1〜I7、所要 21 秒）→ すべて解消、実装に渡せる。生の出力 `<scratchpad>/tasks/byrvv5ixr.output`

---

区分: 境界（セキュリティ境界〈起動時のゲートの迂回を塞ぐ〉と、利用者に `-b` を強いる既定の挙動の変更を含むため）
推奨実装: Opus（グローバル指示の「Opus を推す条件」のセキュリティ境界に当たる。c3c の既定の Sonnet より優先。Task 3 の実機の確認は持ち主の操作が要り、Claude Code の面のセッションで進めるのが自然なので Codex を推さない）
実装: Opus（持ち主指定、2026-11-05）。計画したセッション（7af7a57d）は実装せず、handover で新しいセッションに渡す
