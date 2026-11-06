# `-b` でベースイメージと Debian パッケージのセキュリティ更新を入れる 実装計画（#248）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `c3c -b` とイメージが無いときの初回のビルドで、ベースイメージをレジストリから取り直し、Debian パッケージの更新を当てる。取り直しに失敗したら止める。作成から 30 日を過ぎたイメージでは、起動のときと `--check` で WARNING を出す。

**Architecture:**
- `run_explicit_build()` は、compose の build の前に `podman pull <完全名>` を打ち、失敗したら止める。`FROM` にも同じ完全名を渡す。
- イメージが無いときのビルドは、経路によらず `run_explicit_build()` に通す（compose の暗黙のビルドに頼らない）。
- `Dockerfile.claude` の `USER node` の直前に root の upgrade の層を置き、`ARG CACHEBUST` をその前へ移す。境界のアサーションは upgrade の後へ移す。
- ビルドの時刻（`CACHEBUST` のエポック秒）を `LABEL io.c3c.build-epoch` に焼き、`guard_asset_drift()` が古さを判定する。

**Tech Stack:** bash（`c3c`・`test-build.sh`）、Dockerfile、Python unittest（`tests/`）、Podman 5.8.6 / podman-compose 1.6.0。

**Spec:** `docs/superpowers/specs/2026-11-06-base-image-security-updates-design.md`（dec416a）。spec の「テスト」の項にある「`compose-args.<n>` で取り直しの指定を確かめる」は、`--pull=newer` を前提にした古い記述である。同じ spec の「取り直しの方法」で `--pull=newer` をやめたので、この計画では、別に打つ `podman pull` の呼び出しを確かめる。

subagent-driven-development で実装するときは、push・PR・持ち主への確認の Step（Task 4 の取り直しの失敗の確認の前の問い合わせ、Task 4 の PR 前のレビューの起動、Task 5）は、コントローラが最終レビューの後に行う。実装担当のサブエージェントには渡さない。

## Context

`c3c -b` で再ビルドしても、Debian のセキュリティ修正が入らない（#248）。ベースを取り直さず、apt の層がビルドキャッシュに残り、`apt-get upgrade` も無いためである。2026-11-06 の実測では、既定の `debian:stable` に `stable-security` の 6 件（libssl3t64 など）が未適用だった。ビルドしたイメージにも 29〜42 件が残っていた。持ち主の決定（spec の 1〜6）は、次のとおり。

1. `-b` のたびに最新にする。
2. 取り直しに失敗したら止める。
3. 固定（日付タグ、digest pin）の有無によらず、upgrade を掛ける。
4. 古さの WARNING を出す。
5. 初回のビルドも `-b` と同じにする。
6. ベースが新しくなった直後の丸ごとのビルドは受け入れる。

## Global Constraints

- **REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に読み込む）
- 変更前に `docs/development-invariants.md` の `c3c`・`Dockerfile.claude`・`compose.yml` の節を読む（root `AGENTS.md`）。
- ベースの既定値の 3 か所（`Dockerfile.claude` の `ARG`・`compose.yml`・`guard_base_image()`）と、`guard_base_image()` の検証は変えない。
- 完全名: `base_image_pull_ref()` が、`BASE_IMAGE` から先頭の `docker.io/library/` か `docker.io/` を外し、`docker.io/library/` を付けたものを返す。例: `debian:stable` → `docker.io/library/debian:stable`、`docker.io/debian:trixie-20260701` → `docker.io/library/debian:trixie-20260701`。digest pin は `@sha256:…` を保つ。
- pull と `FROM` に同じ完全名を使う。`run_explicit_build()` と `run_main_compose()` が compose に渡す build arg の `BASE_IMAGE` も、この完全名にする。short name の解決（registries.conf の alias、`localhost/debian:*` などのローカルのイメージ）で、pull したものと別のイメージを `FROM` が使わないためである。その結果、`io.c3c.base-image` の label にも完全名が記録される。`guard_asset_drift()` の base-image の比較は、記録の値と今の値の両方を `base_image_pull_ref()` と同じ規則で正規化してから比べる（#248 より前のイメージは短い名前を記録しているので、正規化しないと全員に誤った WARNING が出る）。`--check` の `[INFO] ベースイメージ:` は、今と同じく書いた値を出す。
- 取り直しは、compose の build とは別の `podman pull "<完全名>"` で行い、その rc で止める。`--pull=newer` は使わない（`man podman-build`: newer は「Pull errors are suppressed if a local image was found.」）。`--pull=always` は失敗をエラーにするが、compose の build の中に入ると、取り直しの失敗と apt の失敗を終了コードでも文言でも分けられない。そのため使わない。
- `ref` はコマンドの置換で受けるときに失敗を捨てない（`local ref; ref=$(base_image_pull_ref) || exit 1` の形。不変条件の「コマンド置換の終了ステータスは捨てられる」と同じ型）。
- 文言（テストはこの部分文字列で確かめる）:
  - 取り直しの失敗: `ERROR: ベースイメージ <完全名> をレジストリから取り直せませんでした（podman pull の終了コード <rc>）。ネットワークとレジストリ（docker.io）を確かめてください。Docker Hub の取得の回数の上限（ログインしていないと IP ごとに 100 回）に当たったときも、この失敗になります。イメージは作り直していません。起動を中止します。`（上限の値は Docker の公式の文書〈docs.docker.com/docker-hub/usage/pulls/〉による。手元に最新があるときの `podman pull` も 1 回に数えられることを、2026-11-06 にホストで `ratelimit-remaining` が 100 → 99 になったことで確かめた）
  - build の失敗: `ERROR: イメージのビルドに失敗しました（podman compose build の終了コード <rc>。apt などのビルドの段の失敗です。上のログを確かめてください）。起動を中止します。`
  - 古さ: `WARNING: イメージ <IMAGE_NAME> は <N> 日前にビルドされました。Debian のセキュリティ更新を入れるには -b で再ビルドしてください。`
- 古さの目安は readonly の定数 `IMAGE_MAX_AGE_DAYS=30`。判定は `now - epoch > IMAGE_MAX_AGE_DAYS*86400` のときに WARNING を出す。`<N>` は `(now - epoch) / 86400` の切り捨て。
- 古さの判定:
  - 新しい `podman image exists` を足さない（`tests/test_c3c_launch.py` の `IMAGE_EXISTS_CALLS_CLAUDE_LAUNCH = 3` を保つ）。`guard_asset_drift()` の中で、既存の exists の後に `image_label build-epoch` で読む。
  - `BUILD=1 && CHECK_MODE=0` のときは判定しない（`guard_ipv6()` と同じ形）。
  - label が `^[1-9][0-9]{0,11}$` に一致しないとき（空・`unknown`・`abc`・`09` のような先頭の 0・13 桁以上）と、未来の時刻のときは、何も出さない。正規表現で絞ってから算術に渡す（`09` は bash の算術で 8 進数のエラーになり、20 桁の値は 64 ビットであふれるため）。#248 より前のイメージは、`Dockerfile.claude` が `ASSET_HASH_TARGETS` に入っているので、境界アセットのドリフトの WARNING がすでに `-b` を案内する。WARNING を二重に出さないためである。
  - `date -d` を使わない（macOS の podman machine を考え、整数の比較だけにする）。
- upgrade の層: `apt-get update --error-on=any && apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade --with-new-pkgs --no-install-recommends && apt-get clean && rm -rf /var/lib/apt/lists/*`。`full-upgrade` は使わない（パッケージを消すことがあるため）。`--error-on=any` は、security など一部のソースの取得だけが一時的に失敗したときも止めるために付ける（無いと `apt-get update` は rc 0 で終わりうるので、更新が欠けたまま upgrade が成功する。`man apt-get`: 「Fail the update command if any error occured, even a transient one.」）。`echo "cachebust=${CACHEBUST}"` で ARG を参照する（不変条件「宣言のみでは無効」）。
- 挙動を変えた README の節と不変条件は、その挙動を変える commit と同じ commit で直す。各 Task の commit の前に `./lint.sh` を rc 0・警告なしで通す。

## Review Focus

1. `base-image.txt` が digest pin（`debian:stable@sha256:…`）のとき、`podman pull` が通り、build がその digest を使うこと。また、どの指定でも、build が pull したものと同じベースを使うこと → Task 1 のテストで pull と build arg の完全名を確かめ、Task 4 で実 podman のベースの層を照合する。
2. Codex の経路と、project 設定ゲートの経路で、イメージが無いとき。pull が 1 回だけで、build が 1 回だけであること → Task 1 のテスト。
3. 取り直しの失敗で、compose が 1 回も呼ばれず、`run` にも進まないこと（古いイメージで起動しない） → Task 1 のテスト。
4. 作ったばかりのイメージと、`-b` の直前で、古さの WARNING が出ないこと → Task 2 のテスト。
5. upgrade で apt sources が `http://` に戻る、または `setpriv` が変わったら、ビルドが止まること → Task 3 で、アサーションが upgrade の後にあることを `test-build.sh --build-only` で確かめる。

## Files

- Modify: `c3c`（新しい `base_image_pull_ref()`、`run_explicit_build()`、起動の流れの build の条件、`run_main_compose()` と `compute_asset_hash` の周りのコメント、`IMAGE_MAX_AGE_DAYS`、`guard_asset_drift()`）
- Modify: `Dockerfile.claude`（upgrade の層、`ARG CACHEBUST` の位置、アサーションの位置、`LABEL io.c3c.build-epoch`）
- Modify: `tests/test_c3c_launch.py`・`tests/test_codex_launch.py`（偽 podman の `pull` と `build-epoch`、新しいテスト）、`tests/test_claude_project_launch.py`（ゲートの経路のテスト。`test_codex_launch` の偽 podman を使う）、`test-build.sh`（bash の偽 podman の `pull` の記録）
- Modify: `README.md`、`docs/development-invariants.md`

## Task 0: 作業ブランチ

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

- [ ] ブランチ `docs/248-base-image-security-updates`（spec の commit dec416a がある）を `fix/248-base-image-security-updates` に改名するか、そこから作る。ほかのセッションの worktree と変更が無いことを `git worktree list` と `git status` で確かめる。
- [ ] 計画を `docs/superpowers/plans/2026-11-06-base-image-security-updates-248.md` に写して commit する（計画者が承認の直後に済ませていれば飛ばす）。

## Task 1: 取り直しと、初回のビルドの経路

- [ ] 偽 podman を先に直す（直さないと、`pull` は `想定外の podman 呼び出し` で rc 125 になり、既存の `-b` のテストが全部落ちる）。
  - `tests/test_c3c_launch.py` の `PODMAN`: `args[:1] == ['pull']` で記録し、`state.get('pull_rc', 0)` で終わる。
  - `tests/test_codex_launch.py` の偽 podman も同じにする。`tests/test_project_images.py` の偽 podman は、build を呼ばないことを確かめ、呼ぶなら同じにする。
  - `test-build.sh` の `launcher_sandbox_init()` の bash の偽 podman: `pull` で引数を `$root/pull-calls` に書き、`${TEST_PULL_RC-0}` で終わる。`launcher_sandbox_reset_records()` で消す。
- [ ] 失敗するテストを `tests/test_c3c_launch.py` の新しいクラス `BaseImageRefreshTests(LaunchCase)` に書く。
  - `test_rebuild_pulls_base_before_build`: `-b` で、`pull docker.io/library/debian:stable` の呼び出しが compose の `build` より前に 1 回ある。
  - `test_pull_ref_is_fully_qualified`: `.c3c/base-image.txt` が `debian:testing`・`docker.io/debian:trixie-20260701`・`docker.io/library/debian:stable@sha256:<64 桁>` のとき、pull の引数がそれぞれ `docker.io/library/debian:testing`・`docker.io/library/debian:trixie-20260701`・`docker.io/library/debian:stable@sha256:<64 桁>` になる。compose の build と run に渡る `BASE_IMAGE`（記録の `env`）も、同じ完全名になる。
  - `test_base_image_drift_compares_normalized`: 記録の label が `debian:stable`（#248 より前の短い名前）で、今の設定が既定のとき、ベースイメージの設定が違うという WARNING が出ない。記録が `docker.io/library/debian:testing` で今が既定（stable）なら出る。偽 podman の `image inspect` に `io.c3c.base-image` を `state['base_image_label']` で返す分岐を足す。
  - `test_pull_failure_stops_before_compose`: `pull_rc=125` で rc が 0 以外になる。stderr に取り直しの失敗の文言（`をレジストリから取り直せませんでした` と `終了コード 125`）が出る。`compose_calls()` が空。
  - `test_build_failure_message`: `build_rc=3` で rc が 0 以外になる。stderr に build の失敗の文言（`podman compose build の終了コード 3`）が出る。`main_runs()` が空。
  - `test_absent_image_builds_explicitly_claude`: `image_exists=False` で `.claude` も `.mcp.json` も無いとき、pull が 1 回、`compose_calls('build')` が 1 回で、その後に本 run が 1 回ある。
  - `test_absent_image_pull_failure_does_not_run`: 上の状態で `pull_rc=125` なら、本 run が無い。
  - Codex の経路とゲートの経路（`.claude` があるプロジェクト）でも、イメージが無いとき pull が 1 回・build が 1 回であること。Codex の経路は `tests/test_codex_launch.py` に 1 件。ゲートの経路は `tests/test_claude_project_launch.py` に 1 件（`tests/test_c3c_launch.py` の偽 podman には、ゲートに要る `io.c3c.claude-project-audit-protocol` の label と `claude_preflight` の応答が無いため。`tests/test_codex_launch.py` の偽 podman にはある）。
  - 既存のイメージで `-b` が無いときは、pull しない。
- [ ] テストが期待どおりに失敗することを確かめる。`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_c3c_launch.BaseImageRefreshTests -v`。ゲートと Codex の分は `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_claude_project_launch.py' -v` と `-p 'test_codex_launch.py'`（`test_claude_project_launch.py` は `from test_codex_launch import` するので、`discover -s tests` で回す）。
- [ ] 実装する。
  - `base_image_pull_ref()`: 引数の値（省略時は `BASE_IMAGE`）から Global Constraints の完全名を標準出力へ出す。`guard_asset_drift()` の正規化にも同じ関数を使う。
  - `run_explicit_build()`: `local ref; ref=$(base_image_pull_ref) || exit 1` で受け、compose の前に `podman pull "$ref"` を打つ。rc を取り、Global Constraints の文言で `exit 1` する。compose の build には `BASE_IMAGE="$ref"` を渡す。compose の build も rc を取り、build の失敗の文言で `exit 1` する。
  - `run_main_compose()` に渡す `BASE_IMAGE` も完全名にする（build と run で値をそろえる）。
  - `guard_asset_drift()` の base-image の比較を、両方を正規化してから比べる形にする。
  - 起動の流れの build の条件（`if [[ $BUILD -eq 1 || ( "$AGENT" == codex && … ) || ( $CLAUDE_PROJECT_GATE … ) ]]`）を `[[ $BUILD -eq 1 || $IMAGE_PRESENT -eq 0 ]]` にする。
  - 今の挙動と合わなくなるコメントを直す: `run_main_compose()` の上の「-b なしの初回起動は compose の暗黙ビルドで焼かれる」、`compute_asset_hash` の周りの「-b 無しの初回起動（compose の暗黙ビルド）」、build の条件の上のコメント、`guard_image_layout()` の上の「未ビルドなら何もしない（compose の暗黙ビルドが label 付きで作る）」、`run_explicit_build()` の上の「-b のビルド、および Codex 経路の image 不在時の明示ビルド」。`grep -n '暗黙' c3c` で残りが無いことを確かめる。`run_main_compose()` に `BASE_IMAGE`・`ASSET_HASH` を渡すのは残す（害が無く、run 側の補間の既定値に効くため）。
- [ ] 既存のテストのうち、イメージが無いときに build が 0 回であることを前提にしたもの、build arg の `BASE_IMAGE` の値を短い名前で確かめているものを探す。
  - Python: `image_exists': False`・`image_exists'] = False` の箇所と、`BASE_IMAGE` の値を見ている箇所。`tests/test_c3c_launch.py`・`tests/test_c3c_config.py`・`tests/test_codex_launch.py`・`tests/test_claude_project_launch.py`。
  - `test-build.sh`: `TEST_IMAGE_EXISTS_RC=1` の回と、`compose-calls` の値や `compose-args.<n>` の番号で「どの呼び出しか」を決め打ちしている検査（イメージが無い回は、明示のビルドで 1 回ふえる）、`BASE_IMAGE=` を grep している検査、`TEST_BASE_IMAGE` で記録の label を差し替える検査（「L2-3: base-image の新 label が違えば WARNING」など。正規化した比較でも、違う値なら WARNING が出ることを保つ）。見つけたら、期待を新しい挙動に直し、直した理由をテストのコメントに書く。黙って消さない。`ImageLayoutGateTests.test_absent_image_is_not_checked` のコメント（「compose の暗黙ビルドが label 付きで作る」）も直す。
- [ ] 同じ commit で文書を直す。
  - README「イメージの変更」: `-b` と初回のビルドがベースを取り直すこと。レジストリ（docker.io）と `deb.debian.org` が要ること。取り直しに失敗したら止まり、古いイメージは残ること。ベースが新しくなった直後は丸ごとのビルドになること。
  - README「起動・ビルド準備の通信待ち時間」: pull は podman の既定の再試行に任せ、c3c は時間の上限を足さないこと。
  - README の「暗黙ビルド」を前提にした記述を直す: `--check --clean-missing` の節の「次回 `-b` または暗黙ビルドから付く」（由来の label の段落）、「変更後の確認」の「明示 build と run の暗黙ビルドへの受け渡し」。`grep -n '暗黙' README.md docs/development-invariants.md` で残りが無いことを確かめる。
  - README の `base-image.txt` の項と「アーキテクチャ」の `Dockerfile.claude` の項: `FROM` と label には完全名（`docker.io/library/debian:…`）が入ること。
  - `docs/development-invariants.md` の `c3c` 節: 取り直しは compose とは別の `podman pull` で行い、その rc で止めること（`--pull=newer` は失敗を握りつぶし、`--pull=always` は apt の失敗と分けられないので使わない）。pull と `FROM` に同じ完全名を渡すこと。イメージが無いときのビルドも、どの経路でも `run_explicit_build()` に通すこと（暗黙のビルドの fail-open を戻さない）。`CC_CLAUDE_START_MODE` の項にある「`.claude` か `.mcp.json` を持つ repo」だけ明示ビルドするという書き方を、すべての経路が明示ビルドになったことに合わせて直す。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./test-build.sh --launcher-only` と `./lint.sh` が通ることを確かめて commit する。

## Task 2: 古さの WARNING

- [ ] 偽 podman の `image inspect` に `io.c3c.build-epoch` を足す。既定は呼ばれた時点の `int(time.time())` で、`state['build_epoch']` があればそれを出す（既定を「新しい」にして、既存のテストの出力を変えない）。build のときは `build_epoch` を今の時刻にする。`test-build.sh` の偽 podman は `${TEST_BUILD_EPOCH-}` を出す（空なら判定しないので、既存のテストに影響しない）。
- [ ] 失敗するテストを `tests/test_c3c_launch.py` の新しいクラス `ImageAgeWarningTests(LaunchCase)` に書く。時刻は `now = int(time.time())` から作る。
  - `test_old_image_warns`: `build_epoch = now - 31*86400` で、stderr に `は 31 日前にビルドされました` と `-b で再ビルド` が出て、起動は rc 0 のまま。
  - `test_boundary`: `now - 30*86400 + 60` では出ない。`now - 30*86400 - 60` では出る。
  - `test_fresh_image_does_not_warn`: 既定の新しい epoch では出ない。
  - `test_missing_or_unknown_label_is_silent`: `''`・`unknown`・`abc`・`09`・`99999999999999999999`（20 桁）・`now + 86400`（未来）で、古さの WARNING が出ず、起動は rc 0 のまま（算術のエラーで落ちない）。
  - `test_rebuild_does_not_warn`: 古い epoch でも `-b` なら出ない。
  - `test_check_reports_old_image`: `--check` で同じ文言が出て、結果が WARN になる（`guard_warn` の集計）。無書き込みを `snapshot` で確かめる。
- [ ] テストが期待どおりに失敗することを確かめる。新しい `podman image exists` を足していないことは、新しいテストを作らず、既存の `IMAGE_EXISTS_CALLS_CLAUDE_LAUNCH` を使う検査（`tests/test_c3c_launch.py`）が通ったままであることで確かめる。
- [ ] 実装する: `readonly IMAGE_MAX_AGE_DAYS=30` を `c3c` の定数の並びに置く。`guard_asset_drift()` の、既存の label の読み込みの後に、Global Constraints の判定を足す。`Dockerfile.claude` の label の並び（`LABEL io.c3c.base-image` の近く。CACHEBUST を消費する RUN より後）に、`LABEL io.c3c.build-epoch="${CACHEBUST}"` を足す。label を足す RUN の位置は Task 3 で移すので、この Task では label だけを足す。
- [ ] 同じ commit で文書を直す。
  - README の `--check` の節と「イメージの変更」: 30 日の WARNING、label の名前、label が無い古いイメージはドリフトの WARNING が案内すること。
  - `docs/development-invariants.md` の `Dockerfile.claude` 節: label を、CACHEBUST の消費の後に置く既存の項（`ASSET_HASH` と同じ位置）に足す。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./test-build.sh --launcher-only` と `./lint.sh` が通ることを確かめて commit する。

## Task 3: upgrade の層とアサーションの位置

- [ ] `Dockerfile.claude` を直す。
  - `ARG CACHEBUST=unknown` を、`USER node` の後から、`WORKDIR /workspace` の直前（`COPY claude-project-audit.py` と chmod の後）へ移す。その直後に、Global Constraints の upgrade の RUN を置く（root）。
  - 今の固定 apt の層の直後にあるアサーションの RUN（setpriv・tini・`--ambient-caps`/`--inh-caps`・apt sources の `http://`）を、upgrade の RUN の直後へ移す。これで最終のイメージに対して検査される。HTTPS への書き換えの RUN の中に `http://` が残っていないことの検査（今のアサーションの最後の 2 行と同じもの）を置き、書き換えの直後の失敗も止める。
  - Claude Code の install の RUN は、そのまま `${CACHEBUST}` を参照する。
  - 移したことで、コメント（「固定 apt レイヤーの直後」「`-b` 実行のたびに値が変わるので、このレイヤー（およびそれ以降）は…」）を、今の位置に合うように直す。
- [ ] `./test-build.sh --build-only` で、テストイメージのビルドが通ること、アサーションの RUN が upgrade の後に走ることをビルドのログで確かめる。時間がかかるので `run_in_background: true` で起動する。
- [ ] 一部のソースの取得だけが失敗したときに止まることを、実 podman で確かめる（ホスト）。ベースは `debian:stable` と `debian:testing` の両方。ソースを 1 つ足すだけで、イメージや podman の設定は変えない。
  - 確かめるコマンド: `podman run --rm --user root docker.io/library/debian:<タグ> sh -c 'echo "deb http://deb.invalid/debian stable main" > /etc/apt/sources.list.d/broken.list; apt-get update --error-on=any; echo "rc=$?"; apt-get update; echo "rc_plain=$?"'`
  - Expected: `--error-on=any` の方が `rc=` で 0 以外になる。付けない方は `rc_plain=0` になる（取得失敗が警告だけで通ることの対照）。
  - `rc=0` になったら、upgrade の層の `apt-get update --error-on=any` だけでは部分的な失敗を止められないということになる。その場合は先へ進まず、結果を持ち主に報告する（別の止め方を決めるため）。
  - 結果は PR 本文に書く。
- [ ] 同じ commit で文書を直す。
  - README「アーキテクチャ」の `Dockerfile.claude` の項（「固定 apt レイヤーの直後に、…ビルド時アサーション」）を、upgrade の後に置いたことに合わせて直す。
  - README「利用側プロジェクトの設定」の `base-image.txt` の項（「rolling suite を指定すると…再現性が必要な場合は日付タグか digest pin」）を、固定で守れるのはベースの版だけで、apt のパッケージは `-b` の時点の最新になる、と書き直す。
  - README「イメージの変更」の「apt パッケージ等の上位レイヤーはキャッシュを流用するため高速」を、upgrade の層が毎回走ることに合わせて直す。
  - README「変更後の確認」に 1 項を足す: ベースの取り直し・upgrade の層・古さの判定（`run_explicit_build()`・`base_image_pull_ref()`・`guard_asset_drift()`・`Dockerfile.claude` の upgrade の層とアサーションの位置）を変えたら、`./test-build.sh --launcher-only` と `./test-build.sh --build-only` を回し、ホストの実ビルドで更新の件数とベースの層の一致（Task 4 の 2 つのコマンド）を確かめる。
  - `docs/development-invariants.md` の `Dockerfile.claude` 節の、アサーションの項（「固定 apt レイヤー直後の独立 `RUN`」）と `ARG CACHEBUST` の項を、新しい位置と、upgrade の後に検査する理由に直す。

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./lint.sh` が通ることを確かめて commit する。

## Task 4: 全体の検証（ホスト、実 podman）

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] `./lint.sh`、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only` を回す。
- [ ] `./test-build.sh`（引数なし）を `run_in_background: true` で回す。
- [ ] 実 podman で確かめる（ホスト）。結果は PR 本文に書く。
  - 既定の `debian:stable` の使い捨てのプロジェクトと、`debian:testing` のプロジェクトを `c3c -b` で作り直す。その後、`podman run --rm --user root --entrypoint sh <イメージ> -c 'apt-get update -qq --error-on=any && apt-get -s upgrade --with-new-pkgs | grep -E "^[0-9]+ upgraded"'` の出力が `0 upgraded, 0 newly installed` で始まる（kept back は spec の例外）。
  - 作ったイメージが、pull したベースを使っている。`podman image inspect --format '{{index .RootFS.Layers 0}}' <作ったイメージ>` と `podman image inspect --format '{{index .RootFS.Layers 0}}' docker.io/library/debian:<タグ>` が一致する（debian の公式イメージは 1 層）。一致しなければ止まって原因を調べる（short name の解決や、ローカルの別のイメージを疑う）。
  - `podman image inspect --format '{{index .Labels "io.c3c.build-epoch"}}' <イメージ>` がエポック秒で、`io.c3c.base-image` が完全名である。#248 より前に作ったイメージ（短い名前を記録）で起動して、ベースイメージの設定が違うという WARNING が出ない。
  - digest pin: `d=$(podman image inspect --format '{{.Digest}}' docker.io/library/debian:stable)` で digest を取り、使い捨てのプロジェクトの `.c3c/base-image.txt` に `debian:stable@$d` と書く（digest だけを書くと `guard_base_image()` に拒否される）。`c3c -b` が通り、上と同じ層の照合が一致する。
  - 取り直しの失敗: ホストのネットワークを切る前に、持ち主に確かめる（ほかのセッションも動いているため）。持ち主が良いと言ったら、一時的に切った状態で `c3c -b` が取り直しの失敗の文言で止まり、前のイメージの ID が変わらない（`podman images`）ことを確かめる。podman の設定（`registries.conf` など）は変えない。切れないか、持ち主が断ったら `not run` と理由を書く。
- [ ] どれかを実行できなければ `not run` と理由を PR 本文に書く。
- [ ] 区分が境界なので、PR の前に二重レビューを受ける: Claude 側は `claude-review` skill、Codex 側は `codex-review` skill、起動の順と argon の並走はグローバル指示のとおり。

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review

- [ ] レビューの結果を受け取り、Critical・Important を直し、確認限定巡で確かめる。

## Task 5: PR

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

- [ ] push の前に持ち主に確かめ、push して PR を作る（本文に Closes #248、検証結果、PR 前のレビューの判定と未対応の Minor。Claude と Codex のレビューの全文は PR コメントに）。
- [ ] PR 後の二重レビューは、作成に関わっていないセッションへ handover で渡す。
- [ ] マージの後、README「バージョニング」の基準で番号を判定し（既定の挙動が変わる。利用者の移行作業は要らないので minor の見込み）、根拠を添えてタグ付与を持ち主に提案する（release-tag skill）。

## 計画レビューの記録

- Self-Review: 言い回し 1 件（Task 4 のネットワークを切る手順の、registries.conf の書き方）を直した。spec の古い記述（`compose-args.<n>` で `--pull` を確かめる）は、この計画の Spec の行で置き換えを明記した。
- 版: `plan-initial.md` `<scratchpad>/tasks/b1emcp4vi.output`
- Claude（claude-opus-5-5、session `df74d62c-8dfc-44f2-8006-0e9f0876746f`、所要 267 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/btlu99is1.output`
  - I1 新しいベースを使ったことを確かめる手段が無い → 採用（Task 4 にベースの層の照合。Codex I2 と合わせて pull と `FROM` を同じ完全名に）
  - I2 ゲートの経路のテストを `test_c3c_launch.py` の偽 podman では書けない → 採用（`tests/test_claude_project_launch.py` に置き、`discover -s tests` で回す）
  - I3 暗黙ビルドを前提にした文書の漏れ（README 2 か所、不変条件の `CC_CLAUDE_START_MODE` の項、「変更後の確認」）→ 採用（Task 1・Task 3）
  - I4 既存テストの探し方が狭い → 採用（`test_claude_project_launch.py` と、回数・番号の決め打ちの検査を足した。例に挙がった `test-build.sh` の 2 件はどちらも `-b` の回で、もとから 2 回を数えているので影響しないことは確かめた）
  - M1 epoch の先頭の 0 と桁あふれ → 採用（Codex M2 と同じ。`^[1-9][0-9]{0,11}$`）
  - M2 回数のテストが振る舞いを確かめていない → 採用（テストを消し、既存の検査で確かめる）
  - M3 ネットワークを切る前の持ち主への確認 → 採用
  - M4 判定順の 4 に当たらない理由 → 採用
  - M5 subagent-driven-development のときの扱い → 採用（計画の先頭）
  - M6 コマンド置換の失敗の取りこぼし → 採用（Global Constraints と Task 1）
- Codex（gpt-6.1-sol、所要 136 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/b24fybgk4.output`
  - I1 `apt-get update` の部分的な失敗で更新が欠ける → 採用（`--error-on=any`。`man apt-get` で確かめた）
  - I2 pull した参照と `FROM` の参照が一致する保証が無い → 採用（build arg にも完全名を渡し、drift の比較は正規化してから。このホストの `shortnames.conf` は今は `docker.io/library/debian` を指すことを確かめた）
  - I3 digest pin の実機の手順が入力の検証を通らない → 採用（`debian:stable@<digest>` を書く形と、層の照合）
  - M1 `--pull=always` を除く根拠が誤り → 採用（man の文は newer の説明だった。別の pull を残す理由を「取り直しの失敗と apt の失敗を分けるため」に直した）
  - M2 epoch の数値の範囲 → 採用（Claude M1 と同じ）
- 確認限定巡 1: Claude（I1〜I4、所要 20 秒）→ すべて直った。実装に渡せる。生の出力 `<scratchpad>/tasks/b232j2rf4.output`
- 確認限定巡 1: Codex（I1〜I3、所要 27 秒）→ I2・I3 は直った。I1 は、一部の取得だけが失敗したときに止まる検証が無いとして一部未解消 → 採用（Task 3 に、壊れたソースを 1 つ足した実 podman の確認と対照を追加）。生の出力 `<scratchpad>/tasks/bc9jl6vm2.output`
- 確認限定巡 2: Codex（I1、所要 22 秒）→ 直った。実装に渡せる。生の出力 `<scratchpad>/tasks/bk8wv2v7n.output`
- argon（並走、正式外。gemini-4-argon、公開の経路・未 push で base c2d2739、送ったのは `plan-initial.md` の写し、87.0 クレジット、所要 900 秒）: 実装に渡せる（途中で出した I2「`Dockerfile.claude` が `ASSET_HASH_TARGETS` に無い」は自分で取り消した。実際に入っている）。生の出力 並走の出力ディレクトリ `20261106-c3c-plan-248-argon`
  - M1 `c3c` の「暗黙ビルド」を前提にしたコメントの漏れ（`guard_image_layout()` と `run_explicit_build()` の上）→ 採用（Task 1）
  - M2 Task 2 と Task 3 の順序 → 不採用（label の値はどちらの順でもビルドの時刻で、Task 2 の commit だけでも意味は変わらないため）
  - Sol と材料が違った点: 計画の写しから、Task 4 の skill の SKILL.md のホストのパス 2 つを消した。グローバル指示と `.claude/AGENTS.md` は渡さず、表を依頼文に貼った。計画のパスは `PAIRING-PLAN.md`
  - Critical・Important が無いので、Sol の確認限定巡は起動しない。argon の確認限定巡も無し（Sol の確認限定巡は argon の結果の前に済んでおり、argon 自身の Critical・Important も無い）
- 承認の後の変更（2026-11-06）: 取り直しの失敗の文言に、Docker Hub の回数の上限に当たった可能性を 1 文足した（横の注意から。上限の値と、最新があるときの pull も数えられることを確かめた）。挙動は変えていない。

区分: 境界（`Dockerfile.claude` のビルド時アサーション〈`docs/development-invariants.md` の不変条件〉の位置を変え、全利用者の既定のビルドの挙動を変えるため。spec と同じ）
推奨実装: Opus（グローバル指示の判定順 1〜5 には当たらない。c3c の既定は Claude Code 面の Sonnet だが、セキュリティ境界〈ビルド時アサーション、fail-closed の停止〉を含むので、Opus を推す条件に当たる。Codex は c3c の既定の面ではなく、判定順でも選ばれない。Task 3・4 は実 podman が要るのでホストで行う。判定順の 4〈host でしか成立しない → Codex〉に当たらないのは、このプロジェクトでは Claude Code もホストで動き、ホストの podman と端末を使えるため）
実装: Opus（持ち主指定、2026-11-06。推奨どおり）。計画→実装は handover で新しいセッションへ渡す
