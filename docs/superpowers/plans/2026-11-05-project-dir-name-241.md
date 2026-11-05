# #241 コンテナの中の Claude の transcript と auto memory をプロジェクトごとに分ける Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** コンテナの中の Claude Code が、利用側プロジェクトごとに別の `~/.claude/projects/<名前>/` へ transcript と auto memory を書くようにする。ログインと設定（`.claude.json`）は今と同じホストのファイルを使い続ける。この変更の前にビルドしたイメージでは起動を止め、`-b` を案内する。

**Architecture:** コンテナの環境に `CLAUDE_CONFIG_DIR=/home/node/.claude`（固定値）と `CLAUDE_CODE_PROJECT_DIR_NAME=<PROJECT_NAME>` を渡す（Claude Code v2.1.234 以降の機能）。`CLAUDE_CONFIG_DIR` を設定すると Claude Code は `.claude.json` を `$CLAUDE_CONFIG_DIR/.claude.json` から読むので、ホストの `<基点>/.claude.json` を `/home/node/.claude/.claude.json` にも bind する。マウント先の空ファイル `<基点>/.claude/.claude.json` は、launcher が `prepare_claude_config_ro()` の事前検査の中で型を確かめ、13 項目を作った後に作る（13 項目と同じ考え方。ただし rw）。entrypoint は 2 つの値を検証し、不正なら止める。`IMAGE_LAYOUT_VERSION` を 2 から 3 に上げ、古いイメージを `-b` へ案内する。

**Tech Stack:** bash（`c3c`・`entrypoint.sh`・`test-build.sh`・`tests/test-runtime.sh`）、Compose（`compose.yml`）、Dockerfile（label）、Python unittest（`tests/`）。

**Spec:** c3c#241 の本文（再現と影響）。持ち主の決定（2026-11-05）: 案 A（`CLAUDE_CONFIG_DIR` + `CLAUDE_CODE_PROJECT_DIR_NAME`）。`.claude.json` は今のファイルを重ねて使う。今の共有の memory は、切り替えのときに Claude が振り分けの案を出し、持ち主が確かめてから写す。古いイメージは `IMAGE_LAYOUT_VERSION` を上げて止める。

## Context

コンテナの中の Claude Code は、どのプロジェクトでも作業ディレクトリが `/workspace` なので、transcript と auto memory がホストの `~/.claude/projects/-workspace/` に集まる。あるプロジェクトのセッションが書いた memory を、別のプロジェクトのセッションが指示として読み込む（#241 の再現。使い捨ての repo で、別のプロジェクトの方針を答えた）。

公式文書と実測で確かめたこと:
- https://code.claude.com/docs/en/sessions の「Name the project directory yourself」: `CLAUDE_CODE_PROJECT_DIR_NAME` は `CLAUDE_CONFIG_DIR` と一緒に設定したときだけ効き、transcript を `<config dir>/projects/<名前>/`、auto memory を `<config dir>/projects/<名前>/memory/` に置く。1〜64 字の英数字・`-`・`_`（ほかの値は黙って無視される）。起動する環境から読み、settings の `env` では設定できない。v2.1.234 以降。
- https://code.claude.com/docs/en/env-vars の `CLAUDE_CONFIG_DIR`: 設定・セッション履歴・plugin をその下に置く。
- 実測（2026-11-05、Claude Code 2.1.318、使い捨ての `HOME` と設定ディレクトリ、未ログイン）: 2 つを渡すと `<cfg>/projects/<名前>/` に transcript、`<cfg>/projects/<名前>/memory/` ができた。`.claude.json` は `<cfg>/.claude.json` に作られ、`$HOME/.claude.json` は使われなかった。`CLAUDE_CONFIG_DIR` が無いときは `$HOME/.claude.json` だけを使い、`$HOME/.claude/.claude.json` は読まなかった（目印のファイルで確認）。
- Linux の資格情報 `.credentials.json` はもともとホストの `~/.claude/` にあり、`CLAUDE_CONFIG_DIR=/home/node/.claude` でも同じ場所になる（推定。Task 6 の実機で確かめる）。
- `compose.yml` は `DISABLE_AUTOUPDATER: "1"` なので、イメージの Claude Code はビルドした時の版のまま。古いイメージで v2.1.234 より前の版だと、名前が黙って無視されて共有が続く。そのため配置の版を上げて `-b` を求める（持ち主決定）。

名前には `compute_project_name()`（`c3c`）の `PROJECT_NAME`（`<小文字に整えた basename 40 字以内>-<絶対パスの sha256 先頭 8 字>`、文字は `[a-z0-9_-]`、先頭は `-` にならない、最長 49 字）をそのまま使う。イメージ名・承認記録と同じキーなので、同じ checkout なら同じ置き場になる。

範囲の外（README に限界として書く）:
1. `.claude.json` の `projects["/workspace"]` に入るもの（#163 の trust、local scope の MCP サーバー、allowedTools など）は分かれない。`~/.claude/history.jsonl` のように、ほかにも `/workspace` をキーにして混ざるものがありうる（未確認）。
2. 同じプロジェクトの worktree（`/workspace/.claude/worktrees/...`）の transcript は、今は worktree ごとに別の置き場だが、変更後は 1 つの置き場にまとまる（auto memory はもともと repo 単位で共有）。
3. 古い `-workspace/`（と `-workspace--claude-worktrees-*`）の記録は移さず残す。変更後の `/resume` の一覧には初めは出ない（`Ctrl+A` で全プロジェクトを出せば見える）。
4. シェル環境の `CLAUDE_CODE_VERSION` で v2.1.234 より古い版を固定して `-b` したイメージでは、`CLAUDE_CODE_PROJECT_DIR_NAME` が無視され、`-workspace/` に戻る（共有も戻る）。c3c は Claude Code の版を検査しない。
5. ホストの `<基点>/.claude/.claude.json` は c3c が作る空のマウント先。ホストで Claude Code 自身の `CLAUDE_CONFIG_DIR` を `<基点>/.claude` に向けて使う構成では、このファイルが設定として読まれる（c3c の `CLAUDE_CONFIG_DIR` は `.claude.json` と `.claude/` を含む基点を指し、Claude Code の同名の変数とは意味が違う）。

## Global Constraints

- **REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に読み込む）
- 変更前に `docs/development-invariants.md` の該当節（`c3c`・`compose.yml`・`entrypoint.sh`・`Dockerfile.claude`）を読む（root `AGENTS.md`）。
- コンテナに渡す値は次の 2 つだけ。`CLAUDE_CONFIG_DIR` は `compose.yml` に固定値 `/home/node/.claude` で書く（ホストの値を補間しない）。`CLAUDE_CODE_PROJECT_DIR_NAME` は launcher が export する `C3C_CLAUDE_PROJECT_DIR_NAME` から `${C3C_CLAUDE_PROJECT_DIR_NAME-}` で補間する（`:-` にしない。未設定でも既定値を作らず、entrypoint の検証に届かせる）。
- `C3C_CLAUDE_PROJECT_DIR_NAME` は `freeze_project_paths()` の中で `PROJECT_NAME` から無条件に代入して export し、`load_env_file()` より前に readonly にする（起動するシェルの環境の同名の値も `.c3c/env` の値も使わない。#39・#44 と同じ）。`ENV_FILE_ALLOWED_KEYS` には足さない。
- 既存の `/home/node/.claude.json` の bind は残す（新しい bind は追加で、置き換えない）。
- マウント先 `<基点>/.claude/.claude.json`:
  - 型の検査は副作用の無い関数 `validate_claude_json_mountpoint()` にし、`prepare_claude_config_ro()` の通常起動の事前検査ループ（13 項目の `validate_claude_config_ro_path` の並び）の最後で呼ぶ。13 項目を 1 つも作らないうちに止めるため（#131 と同じ）。
  - 通常ファイル（中身は問わない）ならそのまま使う。symlink（dangling を含む）・ディレクトリ・通常ファイル以外なら `ERROR` で止める（symlink を拒否する理由は 13 項目と同じ。README「ホストの Claude Code 設定の読み取り専用保護」）。
  - 作成は `prepare_claude_config_ro()` の 13 項目の作成の後に、作成の直前にもう一度 `validate_claude_json_mountpoint()` を呼んでから、noclobber（`set -C`）で空のファイルを作る。作成の直後にも `validate_claude_json_mountpoint()` を呼び、通常ファイルでなくなっていれば（作成と検査の間に置き換えられた）`ERROR` で止める。Task 1 のテストに、作成の直後の検査が呼ばれること（置き換えを模した fixture か、関数の呼び出し順の検査）を足す。
  - 文言（13 項目の文言と混ぜない。「読み取り専用保護」と「が無い（通常起動時に空で作成）」を含めない。既存のテストが 13 項目の件数をこれらの文字列で数えているため）:
    - 作成: `INFO: <path> を .claude.json の重ねマウント先として作成しました（中身は空。コンテナの中の Claude Code はここからホストの .claude.json を読みます）`
    - `--check` で無い: `[WARN] <path> がありません（通常起動時に .claude.json の重ねマウント先として作られます）`
    - 不正な型: `ERROR: <path> は .claude.json の重ねマウント先ですが、<symlink です|ディレクトリです|通常ファイルではありません>。中身を確かめてから取り除いてください。起動を中止します。`
  - `--check` は作らない。基点が解決できないとき（`resolve_claude_config_base` が 0 以外。診断は `prepare_claude_config_ro()` に任せる）と、基点の `.claude` 自体が無いとき（`prepare_claude_config_ro()` が WARN を出して返る経路）は、`prepare_claude_json_mountpoint()` は何も出さずに 0 で返す（記録の置き場の INFO も出さない）。`.claude` があって新しいマウント先が無ければ `[WARN]`、不正な型なら失敗として報告する。
- entrypoint は、Claude・Codex のどちらの経路でも、`CC_AGENT` の検証の直後（秘密の export より前）に次を検証し、合わなければ `ERROR` で `exit 1` する: `CLAUDE_CONFIG_DIR` がちょうど `/home/node/.claude`、`CLAUDE_CODE_PROJECT_DIR_NAME` が `^[a-z0-9_-]{1,64}$`。検証の後に 2 つを `readonly` にして export する（secrets/export の同名の値は、既存の「既に設定済みの名前はスキップ」で入らない）。
- `IMAGE_LAYOUT_VERSION` を 2 から 3 に上げる（`c3c` の定数と `Dockerfile.claude` の `LABEL io.c3c.image-layout` を揃える）。`guard_image_layout()` の文言は v15 以前の理由だけを書いているので、配置が変わった一般の理由に直す（例: `ERROR: イメージ $IMAGE_NAME は今の c3c のコンテナ内の配置に対応していません（label …=…、必要な値 …）。-b で再ビルドしてください。起動を中止します。`）。
- 古い記録の移動・複写を製品に入れない。
- 挙動を変えた README の節は、その挙動を変える commit と同じ commit で直す（root `AGENTS.md`）。各 Task の commit の前に `./lint.sh` を rc 0・警告なしで通す。

## Files

- Modify: `c3c`（`IMAGE_LAYOUT_VERSION`、`guard_image_layout()` の文言、`freeze_project_paths()`、新しい `validate_claude_json_mountpoint()` と `prepare_claude_json_mountpoint()`、`prepare_claude_config_ro()` の事前検査ループ、通常起動と `--check` の呼び出し列、`--check` の INFO）
- Modify: `Dockerfile.claude`（`LABEL io.c3c.image-layout`）
- Modify: `compose.yml`（`environment` に 2 行、`volumes` に 1 行）
- Modify: `entrypoint.sh`（先頭の検証）
- Modify: `test-build.sh`（新しい関数 `run_project_dir_launcher_tests` を `run_launcher_tests()` の中から 1 回呼ぶ。`run_config_ro_tests` の fixture と probe。配置の版の fixture）
- Modify: `tests/test_codex_entrypoint.py`（新しいクラス `ProjectDirEnvTests` と既存の環境）、ほかの entrypoint を起動するテストの環境、`tests/test-runtime.sh`（`clean_env` と基点の fixture）、`--check` の結果や配置の版を前提にした既存テストの fixture
- Modify: `README.md`、`docs/development-invariants.md`（各 Task で、その Task の挙動の節を直す）

## Task 0: 作業ブランチ

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

- [ ] `main`（`git pull --ff-only` 済み）から `fix/241-project-dir-name` を作る。ほかのセッションの worktree と変更が無いことを `git worktree list` と `git status` で確かめる。
- [ ] 計画を `docs/superpowers/plans/2026-11-05-project-dir-name-241.md` に写して commit する（計画者が承認の直後に済ませていれば飛ばす）。

## Task 1: launcher が名前を渡し、マウント先を用意する

- [ ] 失敗するテストを `run_project_dir_launcher_tests` に書き、`run_launcher_tests()` の中から 1 回呼ぶ（`test-build.sh` の決まり。個別の入口から直接呼ばない）。#159 の `J:` と #131 の config-ro の形に倣う:
  - 通常起動で compose に渡る環境の `C3C_CLAUDE_PROJECT_DIR_NAME` が、そのプロジェクトの `PROJECT_NAME`（`<basename>-<8 字>`）と一致する。
  - `.c3c/env` に `C3C_CLAUDE_PROJECT_DIR_NAME=evil` を書いても、起動するシェルの環境に `C3C_CLAUDE_PROJECT_DIR_NAME=evil` があっても、渡る値は変わらない（後者は `tests/test_c3c_launch.py` の `test_host_environment_value_is_ignored` と同じ形）。
  - `<基点>/.claude/.claude.json` が無ければ空の通常ファイルが作られ、作成の INFO（Global Constraints の文言）が出る。既にある通常ファイルの中身は変わらない。
  - symlink・dangling symlink・ディレクトリ・FIFO なら compose を呼ばずに止まり、`ERROR` に `.claude/.claude.json` が出る。13 項目が欠けた基点で試し、そのとき基点の `.claude` 以下が起動前と同じ（`snapshot_config_ro_targets` で比べる。13 項目も作られていない）。
  - `--check` は作らずに `[WARN]` を出し、不正な型なら失敗する（無書き込みを snapshot で確かめる）。基点の `.claude` 自体が無いときは、新しい WARN を出さない。
  - `CLAUDE_CONFIG_DIR` を設定した基点でも同じ場所を見る。
  - Codex 経路でも同じマウント先が用意される（同じ compose サービスを使うため）。
  - 既存の「A: 作成を 13 行ログする」などの件数の検査が、新しい INFO で数え違えない。
- [ ] 既存のテストのうち、13 項目を用意した fixture で `--check` の結果（`OK`・rc 0 など）を確かめているもの（`test-build.sh` の C0・C・P7 などと、`tests/test_c3c_launch.py`・`tests/test_codex_launch.py`・`tests/test_c3c_config.py`・`tests/test_project_images.py`）の fixture に、空の `.claude/.claude.json` を足す。13 項目を用意する共通の関数（`test-build.sh` の `launcher_sandbox_init()` の後に 13 項目を作る箇所や、Python 側の fixture の関数）があれば、そこで一緒に作る。`grep -n 'CONFIG_RO\|claude.json\|rc=0\|OK' test-build.sh tests/*.py` で探し、`./test-build.sh --launcher-only` が全部通るまで直す。
- [ ] テストが期待どおりに失敗することを確かめる。
- [ ] 実装: Global Constraints のとおり、`freeze_project_paths()` の代入、`validate_claude_json_mountpoint()`、`prepare_claude_config_ro()` の事前検査ループへの呼び出し、`prepare_claude_json_mountpoint()`（通常起動では `prepare_claude_config_ro` の直後、`--check` では `prepare_claude_config_ro || true` の直後に呼ぶ）。`--check` に `[INFO] コンテナの Claude の記録の置き場: <基点>/.claude/projects/<PROJECT_NAME>/` を出す。
- [ ] 同じ commit で文書を直す: README「ホストの Claude Code 設定の読み取り専用保護」の限界 (3) に、新しいマウント先が rw で 13 項目に入らないこと、型の検査と `--check` の扱いを書く。`docs/development-invariants.md` の `c3c` 節の `.claude.json` の項（#159）に、マウント先の型検査・作成の順序・`--check` の無書き込み、`C3C_CLAUDE_PROJECT_DIR_NAME` を env より前に readonly にし `ENV_FILE_ALLOWED_KEYS` に入れないこと（`CC_*` の書き方と同じ）を書く。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./test-build.sh --launcher-only` と `./lint.sh` が通ることを確かめて commit する。

## Task 2: compose が値とマウントを渡す

- [ ] 失敗するテストを書く: `compose.yml` の environment を読む既存のテスト（`tests/test_codex_entrypoint.py` の `KEYS` を読む検査）に倣い、`environment` に `CLAUDE_CONFIG_DIR: /home/node/.claude` と `CLAUDE_CODE_PROJECT_DIR_NAME: ${C3C_CLAUDE_PROJECT_DIR_NAME-}` があり、`volumes` に `${CLAUDE_CONFIG_DIR:-~}/.claude.json:/home/node/.claude/.claude.json` があることを確かめる。
- [ ] `lint.sh` の Compose 検証（`CC_CODEX_START_MODE`・`CC_CLAUDE_START_MODE` が `environment` にあるかを `grep -qE '^\s*<名前>:'` で確かめている箇所）に、`CLAUDE_CONFIG_DIR` と `CLAUDE_CODE_PROJECT_DIR_NAME` を同じ形で足す。
- [ ] 実装: `compose.yml` に足す。volume は `${CLAUDE_CONFIG_DIR:-~}/.claude:/home/node/.claude` の直後に置き、なぜ要るかのコメントを書く（`CLAUDE_CONFIG_DIR` を設定すると `.claude.json` の読み先が変わること、マウント先は launcher が作ること）。
- [ ] `test-build.sh` の `run_config_ro_tests`（実物の `compose.yml` を `--entrypoint bash` で起動する検査）の fixture の基点に、空の `.claude/.claude.json` を作る（作らないと podman がサブ uid 所有の実体を作る）。同じ検査に probe を 1 つ足す: コンテナの中で `/home/node/.claude/.claude.json` に書くと、ホストの基点の `.claude.json` が変わり、基点の `.claude/.claude.json` は空のまま。既存の 13 項目の書き込み拒否の probe は変えずに通る。
- [ ] 同じ commit で文書を直す: README「コンテナ間の永続化」の表に `/home/node/.claude/.claude.json` の行を足し、`/home/node/.claude/` の行に「transcript と auto memory は `projects/<PROJECT_NAME>/` に置く」と書く。README の `compose.yml` の説明（「アーキテクチャ」節の `**`compose.yml`**` の項）にマウントと 2 つの環境変数を足す。`docs/development-invariants.md` の `compose.yml` 節に、`CLAUDE_CONFIG_DIR` を補間しない固定値で書くこと、`${C3C_CLAUDE_PROJECT_DIR_NAME-}`（`:-` にしない）、新しい bind の理由を書く。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./lint.sh`（Compose 検証を含む）と `./test-build.sh --launcher-only` が通ることを確かめて commit する。`--config-ro-only` は Task 5 で必ず回す。

## Task 3: entrypoint が値を検証し、配置の版を上げる

- [ ] 失敗するテストを `tests/test_codex_entrypoint.py` の新しいクラス `ProjectDirEnvTests` に書く（同じファイルの entrypoint の起動の仕組みを使う。環境を足す引数が無ければ足す）: (a) 正しい 2 つの値なら先へ進む、(b) `CLAUDE_CODE_PROJECT_DIR_NAME` が未設定・空・65 字・`../x`・大文字を含む値なら `ERROR` で rc 1、(c) `CLAUDE_CONFIG_DIR` が未設定・`/home/node/.claude/`・別のパスなら `ERROR` で rc 1。Claude と Codex の両方の経路で確かめる。
- [ ] 配置の版のテスト: label が `2` の既存イメージ（fake podman の fixture）で、通常起動と `--check` が新しい文言の `ERROR` で止まり `-b` を案内する。`-b` のときは止まらない。既存の配置の版の fixture（`grep -n 'image-layout\|IMAGE_LAYOUT' test-build.sh tests/*.py` で探す）の値を 3 に直す。
- [ ] `ProjectDirEnvTests` に、`secrets/export/CLAUDE_CONFIG_DIR` と `secrets/export/CLAUDE_CODE_PROJECT_DIR_NAME` を置いても値が差し替わらず（既存の「既に設定済み」の WARNING でスキップされ）、`claude` の起動の環境に正しい 2 つの値が届くことを確かめるテストを足す（`SecretIsolationTests` の仕組みを使う）。
- [ ] 既存の entrypoint を起動するテスト（`grep -ln 'entrypoint.sh' tests/*.py tests/*.sh` で探す。少なくとも `tests/test_codex_entrypoint.py`・`tests/test_claude_project_entrypoint.py`・`tests/test_ipv6_entrypoint.py`）の環境に 2 つの正しい値を足す。`tests/test_ipv6_entrypoint.py` は環境の辞書をテストごとに作っているので、全部の箇所に足す。
- [ ] `tests/test-runtime.sh`: `clean_env` 配列に `C3C_CLAUDE_PROJECT_DIR_NAME=<固定の正しい値。例 c3c-runtime-test>` を足し、テスト用の基点（`$root` の下の設定ディレクトリ）に空の `.claude/.claude.json` を作る。
- [ ] 実装: `entrypoint.sh` の検証（Global Constraints のとおり）。`c3c` の `IMAGE_LAYOUT_VERSION=3`、`Dockerfile.claude` の label、`guard_image_layout()` の文言。
- [ ] 同じ commit で文書を直す: README「セキュリティモデル」の #163 の段落の後に #241 の段落を足す（何が分かれるか、名前の決まり方、Context の「範囲の外」の 5 項、古いイメージは `-b` まで起動が止まること、古い記録の移し方: `c3c --check <dir>` の INFO で置き場を知り、残したい memory のファイルを `memory/` へ写して `MEMORY.md` の行を足す）。README の配置の版（`io.c3c.image-layout`）を説明している箇所（`grep -n 'image-layout' README.md`。「--check」の検査項目の「v15 以前のイメージは `ERROR` 行で `-b` を案内し」など）を、配置が変わったイメージ一般の書き方に直す。`docs/development-invariants.md` の `entrypoint.sh` 節に検証を、`Dockerfile.claude` 節の `guard_image_layout()` の項に、3 に上げた理由（コンテナ内の env と mount の配置が変わり、古い Claude Code では分離が黙って効かないため）を書く。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./test-build.sh --launcher-only` と `./lint.sh` が通ることを確かめて commit する。

## Task 4: 確認の手順の文書

- [ ] README「変更後の確認」に、この配線（`C3C_CLAUDE_PROJECT_DIR_NAME`・`.claude/.claude.json` のマウント先・entrypoint の検証）を変えたときの確認を足す: `--launcher-only`、`--config-ro-only`、`bash tests/test-runtime.sh`、`-b` の後の実機の確認（Task 6 の項目）。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./lint.sh` が通ることを確かめて commit する。

## Task 5: 全体の検証（ホスト、実 podman）

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./lint.sh`、`./test-build.sh --launcher-only`、`./test-build.sh --validator-only` を回す。
- [ ] `./test-build.sh`（引数なし。テストイメージ `localhost/claude-test` を作り、`--config-ro-only` の検査も含む）を回す。時間がかかるので `run_in_background: true` で起動する。新しい rw bind の書き込み先と、既存の 13 項目の書き込み拒否の両方が通ることを確かめる。
- [ ] `bash tests/test-runtime.sh` を回し、`protected` の段まで通ることを確かめる。
- [ ] どれかを実行できなければ `not run` と理由と、代わりに確かめる場所（例: push の後に `.github/workflows/runtime.yml` を workflow_dispatch で起動する）を PR 本文に書く。
- [ ] 区分が境界なので、PR の前に二重レビューを受ける: Claude 側は `claude-review` skill（`~/.agents/skills/claude-review/SKILL.md`）、Codex 側は `codex-review` skill（`~/.agents/skills/codex-review/SKILL.md`）、起動の順と argon の並走はグローバル指示のとおり。

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review

- [ ] レビューの結果を受け取り、Critical・Important を直し、確認限定巡で確かめる。

## Task 6: 実機の確認（ホスト、実 podman、持ち主と一緒に）

- [ ] 古いイメージ（この変更の前にビルドしたもの）があるプロジェクトで `c3c claude <dir>` と `c3c --check <dir>` が配置の版の `ERROR` で止まり、`-b` を案内することを確かめる（AGENTS.md「バージョン管理」の、移行が必要な変更は `--check` が検出できることを実機で確かめる要件）。
- [ ] 使い捨ての repo A と B を作り、それぞれ `c3c claude -b <dir>` で起動する。
  - A と B のどちらでも: ログインし直しを求められない。`/status` のアカウントが今と同じ。
  - A で「次の文を memory に保存して: c3c-241-marker-A は A だけの目印」と頼み、`~/.claude/projects/<A の PROJECT_NAME>/memory/` にその文を含むファイルができることを `grep -r c3c-241-marker-A ~/.claude/projects/` で確かめる（A の置き場だけに出る）。
  - A を終えてから B の新しいセッションを始め、`/memory` の表示と、`~/.claude/projects/<B の PROJECT_NAME>/memory/` に目印が無いことを確かめる。B で「c3c-241-marker-A を知っているか」と尋ね、知らないと答えることも記録する（答えは補助。判定はファイルの有無で行う）。
  - transcript が `~/.claude/projects/<その PROJECT_NAME>/` に入り、`~/.claude/projects/-workspace/` に新しいファイルが増えていない。
  - ホストの `~/.claude.json` の更新時刻がセッションの後に新しくなっている（コンテナの書き込みが届く）。`~/.claude/.claude.json` が空のまま。`~/.claude/` の直下に `.claude.json.*` などの一時ファイルが残っていない（`ls -la ~/.claude/ | grep claude.json`）。
- [ ] `c3c --check <dir>` の INFO に置き場が出る。
- [ ] 結果を PR 本文に書く。確認できなかった項目は `not run` と理由を書く。

## Task 7: PR

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

- [ ] push の前に持ち主に確かめ、push して PR を作る（本文に Closes #241、検証結果、PR 前のレビューの判定と未対応の Minor、Claude と Codex のレビューの全文は PR コメントに）。
- [ ] PR 後の二重レビューは、作成に関わっていないセッションへ handover で渡す。
- [ ] マージの後、README「バージョニング」の基準で番号を判定し（古いイメージは `-b` しないと起動しなくなるので、利用者の対応が要る変更として MAJOR の見込み）、根拠を添えてタグ付与を持ち主に提案する（release-tag skill）。

## Task 8: この環境の古い memory の振り分け（マージの後。製品の変更ではない）

- [ ] 今の共有の memory の各ファイルを読み、どのプロジェクトのものか（複数・どれでもないを含む）の案を表にして持ち主に示す。
- [ ] 持ち主が確かめた後、各プロジェクトの新しい置き場（`c3c --check <dir>` の INFO）の `memory/` へ写し、`MEMORY.md` に行を足す。元の `-workspace/memory/` は消さない。
- [ ] 振り分けの結果を handover に書く。

## 計画レビューの記録

- Self-Review: 判断を委ねる記述 1 件（entrypoint のテストの置き場 → `tests/test_codex_entrypoint.py` の `ProjectDirEnvTests` に確定）、名前の欠け 1 件（ランチャーの検査の関数名 `run_project_dir_launcher_tests` を明記）、検証の漏れ 2 件（`run_config_ro_tests` の fixture にマウント先が要る、`tests/test-runtime.sh` は通常の entrypoint を通る）、スキルの指定の漏れ 1 件（Task 5 の receiving-code-review）を修正
- 版: `plan-initial.md` `<scratchpad>/tasks/b0i10bbzo.output`
- Claude（claude-opus-5-5、session `b6302a7e-c5e9-45af-9924-d027c903bfec`、所要 424 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bg2gvrh6n.output`
  - I1 マウント先の検査が 13 項目の作成の後 → 採用（事前検査ループで検査し、作成は後。Global Constraints）
  - I2 古いイメージでは分離が黙って効かない → 採用（持ち主決定で `IMAGE_LAYOUT_VERSION` を 3 に。Task 3・6・7）
  - I3 `tests/test-runtime.sh` を確かめる手順が無い → 採用（Task 3 で `clean_env` と fixture を具体化、Task 5 で実行）
  - M1 `run_launcher_tests()` から呼ぶ → 採用
  - M2 文言が未定 → 採用（Global Constraints に文言）
  - M3 シェル環境の上書きのテスト → 採用
  - M4 `--check` で `.claude` が無いとき → 採用
  - M5 不変条件の置き場を節ごとに → 採用
  - M6 範囲の外の追加（local scope の MCP など） → 採用（範囲の外 1）
  - M7 一時ファイルの残り → 採用（Task 6）
  - M8 `--check` の結果を前提にした既存テスト → 採用（Task 1）
  - M9 レビューの skill を名前で → 採用（Task 5）
- Codex（gpt-6.1-sol、所要 292 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/b9gtkprza.output`
  - I1 マウント先の検査の前に 13 項目が作られる → 採用（Claude I1 と同じ）
  - I2 `IMAGE_LAYOUT_VERSION` の更新が無い → 採用（持ち主決定、Claude I2 と同じ）
  - I3 `--config-ro-only` を省略可にしている → 採用（Task 5 で `./test-build.sh` の全体を必須に）
  - I4 README を同じ commit で直す制約と commit の切り方が矛盾 → 採用（文書の更新を各 Task の commit に移した）
  - M1 SemVer を minor と決めつけ → 採用（README の基準で判定。MAJOR の見込み）
  - M2 各 commit の前の verification-before-completion → 採用（Task 1〜4）
  - M3 実機の分離の確認が再現しにくい → 採用（目印の文とファイルの有無で判定）
- 確認限定巡 1: Codex（I1〜I4、所要 33 秒）→ I2・I3・I4 は直った。I1 は作成の直後の検査が無いとして一部未解消 → 採用（Global Constraints に作成直後の検査を追記）。生の出力 `<scratchpad>/tasks/b517mfxwy.output`
- 確認限定巡 2: Codex（I1、所要 23 秒）→ 直った。実装に渡せる。生の出力 `<scratchpad>/tasks/bgw1dmrnd.output`
- argon（並走、正式外）: 修正後に渡せる（Critical 2・Important 4・Minor 2、初版に対して）。62.3032 クレジット、所要 282 秒。生の出力 `<pairing-runs>/20261105-c3c-plan-241-argon/out.txt`。Sol と材料が違った点: グローバル `AGENTS.md` と `.claude/AGENTS.md` は送らず、スキルの表の 2 列だけを依頼文に貼った。計画のパスを `PAIRING-PLAN.md` にし、依頼文からホストのパスを外した
  - C1 `--check` の fixture と、基点が解決できないときの扱い → 採用（Global Constraints と Task 1 に明記。承認の後の変更）
  - C2 Task 2 の compose の変更で `ComposeContractTests` が壊れる → 不採用（正規表現は `CC_*` の 4 つだけを拾い、新しい bind の source は既存の `~/.claude.json` なので壊れない。コードで確認）
  - I1 検査の順序 → 正式なレビューの I1 で反映済み
  - I2 secrets/export の上書きのテストと、`tests/test_ipv6_entrypoint.py` の全箇所 → 採用（Task 3。承認の後の変更）
  - I3 `IMAGE_LAYOUT_VERSION` を上げない理由を書く → 不採用（持ち主の決定で上げる）
  - I4 `lint.sh` の Compose 検証 → 採用（Task 2。承認の後の変更）
  - M1 `tests/test-runtime.sh` の具体化、M2 probe の詳細 → 正式なレビューの反映で済み
- 確認限定巡 3: Codex（argon の C1・I2・I4 を出所付きで渡した、所要 30 秒）→ すべて直った。実装に渡せる。生の出力 `<scratchpad>/tasks/bvig6s09n.output`
- 確認限定巡 1: Claude（I1〜I3、所要 35 秒）→ すべて直った。実装に渡せる。生の出力 `<scratchpad>/tasks/b59ky9ty1.output`

区分: 境界（ホストと共有するマウントを足し、コンテナの中の Claude Code の設定の読み先を変える。`~/.claude` の挙動に効く）
推奨実装: Opus（グローバル指示の判定順 2「`~/.claude` 配下の挙動に効く変更」に当たり、セキュリティ境界も含むため。c3c の既定の Sonnet は、Opus を推す条件に当たるので使わない。Codex は判定順 2 により選ばない。Task 5・6 は実 podman と対話の TTY が要るのでホストで行う）
実装: Opus（持ち主指定、2026-11-05。推奨どおり）。計画→実装は handover で新しいセッションへ渡す
