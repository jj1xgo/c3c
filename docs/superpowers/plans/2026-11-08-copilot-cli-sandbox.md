# コンテナ内の Copilot CLI sandbox 対応 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.c3c/copilot-version.txt` で opt-in したプロジェクトの Claude のコンテナで、`copilot` を名前で呼ぶと、Copilot CLI の command sandboxing（通信なし）が起動するようにする。

**Architecture:** Codex の版の固定（`codex-version.txt`）・起動口（`codex-launcher.sh`）・固定の bwrap の置き場（#145）と同じ形で、Copilot の起動口と bwrap の中継を足す。起動口は、sandbox の設定の検査・作業ディレクトリの検査・環境の絞り込み・トークンの読み込みを行ってから、中継を PATH の先頭にして `npm-loader.js` を exec する。中継は、MXC が渡す引数のうち最初の `--` より前にある `--proc /proc` だけを `--ro-bind /proc /proc` に替えて `/usr/bin/bwrap` を exec する。opt-in しないイメージには何も入れない。

**Tech Stack:** bash（起動口・中継）、python3（起動口の中の JSON の検査、`python3 -I`）、Dockerfile（Podman/buildah）、unittest、`test-build.sh`。

**Spec:** `docs/superpowers/specs/2026-11-08-copilot-cli-sandbox-design.md`（commit `1e6d8fc`、ブランチ `feat/copilot-cli-sandbox`）

## Context

保守者は Codex と並べて Copilot CLI をレビューに使っているが、Copilot の sandbox は c3c のコンテナの中で動かない。2026-11-08 の試作（使い捨てのコンテナ、canary 3 回）で、原因が Podman の `/proc` のマスクで MXC の `--proc /proc` が失敗することだと分かった。中継で `/proc` を引き継げば、`/dev/net/tun`・slirp4netns なしで sandbox が起動し、外へ出られず、隠したパスも外側のプロセスの環境も読めないことを確かめた（詳細は spec の「試作で分かったこと」）。この計画は spec の c3c（製品）の部分だけを実装する。並走の仕組みの側は対象外。

## Global Constraints

- **REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に 1 回読み込む。コードを変える計画のため）
- 不変条件は `docs/development-invariants.md` に従う。`c3c`・`compose.yml`・`Dockerfile.claude`・`entrypoint.sh`・`codex-launcher.sh` を変える前に該当節を読む。新しい起動口と中継も同じ扱いにする（固定値は `readonly`、上書き口を作らない、fail-closed、`source` しない）。
- 版の書式は `^[0-9]+\.[0-9]+\.[0-9]+$` だけにする（`latest` は受けない。CACHEBUST を足さない）。同梱 default の `copilot-version.txt` は空（0 バイト）＝ 無効。
- 固定パス（逐語で使う）:
  - 起動口: `/usr/local/bin/copilot`（npm の symlink を置き換える）
  - 実体: `/usr/local/lib/node_modules/@github/copilot/npm-loader.js`（`#!/usr/bin/env node`）
  - ネイティブのバイナリ: `/usr/local/lib/node_modules/@github/copilot/node_modules/@github/copilot-linux-<arch>/copilot`（`uname -m` が `x86_64` なら `x64`、`aarch64` なら `arm64`）
  - 中継の置き場: `/usr/local/libexec/c3c/copilot-bwrap/bwrap`（ディレクトリの中身はこの 1 ファイルだけ）
  - 中継が exec する本物: `/usr/bin/bwrap`（Debian の `bubblewrap`、0.5.0 以上）
  - sandbox の設定の雛形: `/etc/c3c/copilot-settings.json`（root:root 0644）
  - トークン: `/home/node/.config/c3c/secrets/COPILOT_PAT`（`SECRETS_DIR` の直下。export しない）
  - `COPILOT_HOME`: `/home/node/.copilot`（固定。環境変数で変えられない。マウントしないので、コンテナを作り直すと消える）
  - 宛先: `api.individual.githubcopilot.com`、`telemetry.individual.githubcopilot.com`（opt-in のとき、イメージの `/etc/c3c/allowed-domains.txt` に足す）
- 中継・起動口・それらのディレクトリは root 所有で、group/other から書けないことをビルドで検査する（Codex の固定リンクと同じ形）。
- `/dev/net/tun` を通さない。slirp4netns を入れない。Podman の `unmask` を使わない。compose の上書きファイルを足さない。
- 挙動を変えた commit では、README.md の該当節も同じ commit で直す。編集したらそのターンで `./lint.sh` を走らせ、rc 0・警告 0 を確かめる。
- 新しい unittest は `test-build.sh` の `run_launcher_tests()` に `check` 行で登録し、`--launcher-only`（CI）で走らせる。
- モデルを呼ぶ試験は CI に入れない（Task 3 Step 1 と Task 5 の手動の確認だけ）。canary は 1 回あたり約 2 クレジット。消費は保守者が自分の記録に足すので、実装者は回数と `usage.json` の値を報告する。

## Review Focus

1. 作業ディレクトリが `/`、`/home`、`/home/node`、`~/.claude` の下などで起動される → sandbox から認証や `SECRETS_DIR` が読めてしまう。起動口が止めるべき（Task 3 の `test_refuses_sensitive_cwd`）。
2. `settings.json` に未知の許可（`readwritePaths`、`maskedEnv` など）や、真偽値でない値（`0`、`null`、`"false"`）が入る → 起動口が止めるべき（Task 3 の `test_refuses_unknown_sandbox_keys`、`test_refuses_non_bool_values`）。
3. `export/` に `GH_TOKEN` などの秘密を置いたプロジェクトや、並行して走る別の sandbox → トークンもほかの秘密も、Copilot の環境にも、どのプロセスの argv にも載らないべき（Task 3 の `test_env_is_allowlisted`、`test_token_not_in_any_argv`）。
4. MXC の引数の形が変わる、または sandbox の中のコマンドの引数に `--proc /proc` がある → 中継は `--` より後ろを変えず、組が無ければ何も替えずに渡すべき（Task 2 の `test_passes_through_without_pair`、`test_stops_at_double_dash`）。
5. Copilot の新しい版で、`/dev/net/tun` が要るようになる、またはトークンを sandbox に渡すようになる → 受け入れの canary で落ちて気づくべき（Task 5 の Expected）。

---

### Task 1: 版の pin とビルド入力の配線

**Files:**
- Create: `copilot-version.txt`（空、0 バイト）
- Modify: `c3c`（`resolve_asset_source()` の overridable の case、`ASSET_HASH_TARGETS`、`stage_build_context()` の `node-version.txt codex-version.txt allowed-ports.txt` のループ、`guard_build_input_defaults()` とその上のコメント）
- Modify: `test-build.sh`（`stage_common_context()` と `run_config_ro_launcher_tests()` のコピーの一覧）、`tests/test_network_timeouts.py` と `tests/test_container_paths.py` のファイルの一覧
- Modify: `README.md`（利用側プロジェクトの設定の一覧と説明、アーキテクチャの同梱 default の一覧）
- Test: `tests/test_c3c_config.py`（`BuildInputDefaultTests`）

**Interfaces:**
- Produces: ビルドコンテキストの `copilot-version.txt`。`ASSET_HASH_TARGETS` に `copilot-version.txt` を足す。

表示の文言（逐語。`--check` では接頭辞が `[INFO] `、通常起動では stderr に `INFO: `）:
- 採用元が同梱 default（空）: `Copilot 版: なし（既定で無効。導入するには <PROJECT_CONF_DIR>/copilot-version.txt に版を書きます）`
- project で空: `Copilot 版: なし（<ASSET_PATH> が空、Copilot を導入しません）`
- project で版あり: `Copilot 版: <版>（採用元: project <ASSET_PATH>）`
- 書式違反（`guard_fail`）: `ERROR: <ASSET_PATH> には 1.0.103 のような素のバージョンを書いてください（実際の値: <値>）`
- Node が空で Copilot が有効（`guard_warn`、Codex の文の「Codex」を「Copilot」に替えた形）

- [ ] **Step 1: 失敗する試験を書く**（`BuildInputDefaultTests` に追加）
  - `test_copilot_version_default_disabled`: project に無い → 上の「同梱 default（空）」の行が出る。
  - `test_copilot_version_project_pin`: project に `1.0.103` → 「採用元: project」の行。
  - `test_copilot_version_project_empty`: project で空 → 「が空、Copilot を導入しません」の行。
  - `test_copilot_enabled_without_node_warns`
  - `test_copilot_version_bad_format_fails`: `latest`、`1.0`、`1.0.103-beta` のそれぞれで `--check` が `[FAIL]`、通常起動が止まる。
  - 既存の `assertNotIn('opt-out', ...)`（`tests/test_c3c_config.py:549`）と `assertNotIn('同梱 default', ...)`（同 `:581`・`:614`）が、新しい行の後でも通ることを確かめる（上の文言はどちらの語も含まない）。
- [ ] **Step 2: 失敗を確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_c3c_config.py" -k BuildInputDefaultTests -v` / Expected: 追加した 5 つが FAIL、既存は PASS
- [ ] **Step 3: 実装する**。`guard_build_input_defaults()` のループに `copilot-version.txt` を足し、書式の検査（版ありのときだけ）と npm の WARNING を足す。上のコメントの「値の妥当性は Dockerfile と guard_codex_agent() が担う」を、Copilot はここでも検査すると直す。登録先の漏れを防ぐため、`grep -rn 'codex-version.txt'` の参照の数を数え、ビルド入力の一覧に当たる箇所すべてに足したことを確かめる（`docs/development-invariants.md:23`）。README の 2 箇所も直す。
- [ ] **Step 4: 通るのを確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_c3c_config.py" -v && ./test-build.sh --launcher-only && ./lint.sh` / Expected: すべて OK、lint rc 0
- [ ] **Step 5: commit** — `feat: Copilot CLI の版の pin をビルド入力に足す`

### Task 2: bwrap の中継

**Files:**
- Create: `copilot-bwrap-shim.sh`
- Modify: `c3c`（`resolve_asset_source()` の fixed の case、`ASSET_HASH_TARGETS`、`stage_build_context()` の fixed のループ）、`test-build.sh`（`stage_common_context()`・`run_config_ro_launcher_tests()` の一覧、`run_launcher_tests()` に `check` 行）、`tests/test_network_timeouts.py`・`tests/test_container_paths.py` の一覧、`tests/test_c3c_config.py:447` の `test_fixed_boundary_assets_cannot_be_overridden_from_the_new_layout` の一覧
- Test: `tests/test_copilot_bwrap_shim.py`

**Interfaces:**
- Produces: `copilot-bwrap-shim.sh`（イメージでは `/usr/local/libexec/c3c/copilot-bwrap/bwrap`）。固定値 `readonly REAL_BWRAP=/usr/bin/bwrap`。引数を前から見て、最初の `--` より前で、連続する 2 つがちょうど `--proc` と `/proc` の組をすべて `--ro-bind /proc /proc` の 3 つに替える。最初の `--` とそれより後ろは一字も変えない。`$REAL_BWRAP` が `-f`・`-x` でなければ `ERROR: /usr/bin/bwrap がありません。-b で再ビルドしてください。` で rc 1。そうでなければ `exec "$REAL_BWRAP" "${args[@]}"`。

- [ ] **Step 1: 失敗する試験を書く**（`tests/test_codex_launcher.py` と同じ流儀で、固定パスを試験用の dummy に置換したコピーを走らせ、dummy が NUL 区切りで argv を記録する）
  - `test_rewrites_proc_pair`: `--unshare-pid --proc /proc --dev /dev -- sh -c x` → `--unshare-pid --ro-bind /proc /proc --dev /dev -- sh -c x`
  - `test_passes_through_without_pair`: `--proc /other`、末尾の `--proc`、`--ro-bind /proc /proc` → どれも一字も変えない
  - `test_stops_at_double_dash`: `--proc /proc -- sh -c 'x' --proc /proc` → 前の組だけ替え、`--` より後ろの `--proc /proc` は残す
  - `test_preserves_args_with_spaces_and_empty`: `--setenv A 'x y' --setenv B ''` → そのまま
  - `test_fails_closed_without_real_bwrap`: 本物が無い → 上の ERROR 文言で rc 1
  - `test_exit_code_passthrough`: dummy の rc 7 → 中継も rc 7
- [ ] **Step 2: 失敗を確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_copilot_bwrap_shim.py" -v` / Expected: FAIL（ファイルが無い）
- [ ] **Step 3: 実装する**（bash、`set -u`、shebang `#!/bin/bash`）。fixed のアセットへの登録（Files の各箇所）も同じ commit で行う。
- [ ] **Step 4: 通るのを確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_copilot_bwrap_shim.py" -v && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_c3c_config.py" -v && ./test-build.sh --launcher-only && ./lint.sh` / Expected: OK、rc 0
- [ ] **Step 5: commit** — `feat: Copilot の sandbox 用の bwrap の中継を足す`

### Task 3: 起動口と sandbox の設定の雛形

**Files:**
- Create: `copilot-launcher.sh`、`copilot-settings.json`
- Modify: Task 2 と同じ登録先（2 つのファイルを fixed のアセットに足す。`run_launcher_tests()` に `check` 行を足す）
- Test: `tests/test_copilot_launcher.py`

**Interfaces:**
- Consumes: Task 2 の中継の置き場 `/usr/local/libexec/c3c/copilot-bwrap`。
- Produces: `copilot-launcher.sh`（イメージでは `/usr/local/bin/copilot`）。固定値（readonly）: `CONTAINER_HOME=/home/node`（作業ディレクトリの検査はこの定数から組む。試験はこの 1 か所を置換する）、`COPILOT_BWRAP_DIR=/usr/local/libexec/c3c/copilot-bwrap`、`COPILOT_JS=/usr/local/lib/node_modules/@github/copilot/npm-loader.js`、`COPILOT_HOME=/home/node/.copilot`、`SETTINGS_TEMPLATE=/etc/c3c/copilot-settings.json`、`TOKEN_FILE=/home/node/.config/c3c/secrets/COPILOT_PAT`。

- [ ] **Step 1: 実装の前の確認（約 2〜5 クレジット。想定外なら止まって持ち主に報告する）**
  - (a) Copilot CLI 1.0.103 の `copilot help`・`copilot help sandbox`・`copilot help config`・`copilot help environment` と公式文書（GitHub Docs の Copilot CLI の command reference、configuration directory、local sandboxing の各ページ）で、次を確かめて実装の台帳に書く。
    - 作業ディレクトリ（リポジトリ）から読む設定（`.github/` や `.copilot/` の下の settings・hooks・MCP・agents・instructions）があるか。あれば、そのうち sandbox の設定を重ねるもの、または sandbox の外でコマンドを動かすもの（hook、stdio の MCP）はどれか。
    - sandbox を弱める引数（`--no-sandbox` の類）や環境変数があるか。
    - 自動更新を引数でなく設定か環境変数で止められるか。
  - (b) 使い捨てのイメージ（既存の c3c のイメージの上で `apt-get update && apt-get install -y --no-install-recommends bubblewrap` と `npm install -g @github/copilot@1.0.103` を root で行い、Task 2 の中継を `/usr/local/libexec/c3c/copilot-bwrap/bwrap` に置いたもの）で、c3c と同じ実行時の条件（`--userns=keep-id`、`--cap-add NET_ADMIN,NET_RAW`、IPv6 無効の sysctl、専用のブリッジ網、製品の ENTRYPOINT、コンテナの中で `sudo /usr/local/bin/init-firewall.sh`）にし、PAT（Copilot Requests だけ）を `COPILOT_GITHUB_TOKEN` で渡して canary を 1 回走らせる。sandbox の中で `echo "tok_len=${#COPILOT_GITHUB_TOKEN}"` を見る。同じ canary で、使い捨ての作業ディレクトリ（コンテナの中に作った空のディレクトリ）に `touch "$PWD/.c3c-copilot-w"; echo "w_rc=$?"` を走らせ、書けるかも測る。
  - 判定:
    - (a) で、作業ディレクトリから sandbox の外で動くものを読む経路があり、起動口が引数か設定で止められないとき → 止まって持ち主に報告する。
    - (b) で `tok_len=0` → 下の手順 5 のとおり環境変数で渡す。
    - (b) で 0 でない → 止まって持ち主に報告する（トークンの渡し方を変える判断が要るため）。
    - (b) で `w_rc=0` → 止まって持ち主に報告する（作業ディレクトリを読み取りだけにするか、別の写しで走らせるかの判断が要るため。Task 5 Step 3 と同じ理由）。
- [ ] **Step 2: 失敗する試験を書く**（固定パスを置換したコピーと、env と argv と cwd を記録する dummy の `npm-loader.js` で走らせる）
  - `test_creates_settings_from_template`、`test_keeps_existing_settings`
  - `test_refuses_weakened_settings`: `allowOutbound: true`、`allowLocalNetwork: true`、`allowBypass: true`、`enabled: false`、`auth.gh: true`、`allowDevToolAccess: true`、`sandboxMcpServers: false` のそれぞれで rc 1
  - `test_refuses_missing_denied_paths`: `deniedPaths: []`、`/tmp` だけ、secrets だけ → rc 1。雛形に 1 つ足したもの → 通る
  - `test_refuses_non_bool_values`: `allowBypass: 0`、`auth.git: null`、`enabled: "true"` のそれぞれで rc 1
  - `test_refuses_unknown_sandbox_keys`: `filesystem.readwritePaths`、`sandbox.maskedEnv`、`userPolicy.proxy` のそれぞれで rc 1
  - `test_refuses_broken_json`、`test_refuses_settings_symlink`
  - `test_refuses_sensitive_cwd`: cwd が `/`、試験用の HOME とその親、HOME の下の `.config/c3c/secrets`・`.claude`・`.codex`・`.copilot`・任意のディレクトリ（例: `HOME/work`）→ rc 1。`/workspace` 相当、名前が前方一致するだけの `HOME` の兄弟（例: `/home/node2`）→ 通る
  - `test_refuses_missing_cwd`: cwd を消した後に起動 → rc 1
  - `test_requires_token_file`: 無い・空・LF だけ・2 行・CR を含む・途中に空白を含む・タブを含む → rc 1。末尾に LF が 1 つある 1 行 → 通る
  - `test_env_is_allowlisted`: 元の環境に `GH_TOKEN`・`GITHUB_TOKEN`・`COPILOT_GITHUB_TOKEN=old`・`GITHUB_MCP_PAT`・`AWS_ACCESS_KEY_ID`・`COPILOT_HOME=/elsewhere` → dummy の環境に無い（`COPILOT_GITHUB_TOKEN` はファイルの値、`COPILOT_HOME` は固定値、`PATH` は下の固定値）
  - `test_token_not_in_any_argv`: 起動口が exec するまでに起動した外部コマンド（PATH の先頭に、argv を記録する dummy の `env`・`python3`・`cat`・`realpath` などを置く）のどの argv にも、トークンの値が無い
  - `test_token_file_matches_entrypoint`: `TOKEN_FILE` の親が entrypoint.sh の `SECRETS_MOUNT` と一致する
  - `test_args_passthrough`: `-p 'a b' --model x` がそのまま
- [ ] **Step 3: 失敗を確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_copilot_launcher.py" -v` / Expected: FAIL
- [ ] **Step 4: 実装する**

  `copilot-settings.json`（逐語）:

  ```json
  {"sandbox":{"enabled":true,"allowBypass":false,"addCurrentWorkingDirectory":true,"allowDevToolAccess":false,"auth":{"git":false,"gh":false},"sandboxMcpServers":true,"sandboxLspServers":true,"userPolicy":{"network":{"allowOutbound":false,"allowLocalNetwork":false},"filesystem":{"deniedPaths":["/tmp","/home/node/.config/c3c/secrets"]}}}}
  ```

  起動口の処理（この順で行う。どれかを満たせなければ `ERROR: ...` を stderr に出して rc 1 とし、Copilot は起動しない）:
  1. 中継が `-f`・`-x` を満たし、`COPILOT_JS` も `-f`・`-x` を満たす。
  2. `cwd=$(pwd -P)` が成功する（失敗したら止める）。パスの比較はすべて `/` で区切った要素の単位で行う（文字列の前方一致にしない）。cwd が `$CONTAINER_HOME` かその祖先（`/` を含む）か、`$CONTAINER_HOME` の下のどこか（`.config`・`.claude`・`.codex`・`.copilot` を含むすべて）なら止める。
  3. `$COPILOT_HOME/settings.json` が無ければ、`install -d -m 0700 "$COPILOT_HOME"` のあと雛形をコピーする。有れば触らない。symlink なら止める。
  4. `python3 -I` で `$COPILOT_HOME/settings.json` を検査する（パスは引数で渡す）。合格の条件:
     - `sandbox.enabled`・`sandboxMcpServers`・`sandboxLspServers` が `True`
     - `allowBypass`・`allowDevToolAccess`、`auth.git`・`auth.gh`、`userPolicy.network.allowOutbound`・`allowLocalNetwork` が `False`
     - どれも `is True` / `is False` で比べる（数値・null・文字列は不合格）。`addCurrentWorkingDirectory` は bool。
     - キーの範囲: `sandbox` ⊆ {`enabled`,`allowBypass`,`addCurrentWorkingDirectory`,`allowDevToolAccess`,`auth`,`sandboxMcpServers`,`sandboxLspServers`,`userPolicy`}、`auth` = {`git`,`gh`}、`userPolicy` ⊆ {`network`,`filesystem`}、`network` = {`allowOutbound`,`allowLocalNetwork`}、`filesystem` ⊆ {`deniedPaths`}。`deniedPaths` は文字列の list で、雛形の `/tmp` と `/home/node/.config/c3c/secrets` を両方含む（足すのは自由、外すのは不合格）。
     - `sandbox` の外のキーは見ない。JSON が壊れていれば不合格。
  5. `TOKEN_FILE` を bash の組み込みで読む（`IFS= read -r -d '' v < file` のようにファイル全体を読む）。末尾の LF を 1 つだけ落とした値が、`LC_ALL=C` で `^[!-~]+$`（印字できる ASCII だけ、1 文字以上）に合わなければ止める（空、LF だけ、2 行以上、CR・空白・制御文字を含むものはすべて止まる）。
  6. 環境を bash の組み込みだけで絞る: `compgen -e` で export されている名前を列挙し、次の allowlist にないものをすべて `unset` する。allowlist は `HOME`・`LANG`・`LC_ALL`・`LC_CTYPE`・`TERM`・`TZ`・`NO_COLOR`・`COLORTERM`。そのあと `export PATH=/usr/local/libexec/c3c/copilot-bwrap:/usr/local/bin:/usr/bin:/bin COPILOT_HOME COPILOT_GITHUB_TOKEN=<5 の値>` とし、`exec "$COPILOT_JS" "$@"`。トークンを外部コマンドの引数にしない（`env -i` を使わない）。`set -x` や stderr にトークンを出さない。
  7. Step 1 (a) で、自動更新を止める設定か環境変数が分かったら、雛形か手順 6 に足す（引数は足さない）。分からなければ README に `--no-auto-update` を勧める 1 文を書く（Task 4）。
- [ ] **Step 5: 通るのを確かめる** — Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_copilot_launcher.py" -v && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p "test_c3c_config.py" -v && ./test-build.sh --launcher-only && ./lint.sh` / Expected: OK、rc 0
- [ ] **Step 6: commit** — `feat: Copilot CLI の起動口と sandbox の設定の雛形を足す`

### Task 4: イメージへの組み込みと文書

**Files:**
- Modify: `Dockerfile.claude`（`# <<< c3c codex-requirements` の直後、`COPY init-firewall.sh` より前に `# >>> c3c copilot` 〜 `# <<< c3c copilot` の区間を足す。許可リストへの追記は、`COPY allowed-domains.txt` の RUN の直後に別の RUN で行う）
- Modify: `test-build.sh`（`--build-only` の最終イメージの probe と、全体実行の opt-in ビルド）
- Modify: `README.md`、`docs/development-invariants.md`

**Interfaces:**
- Consumes: Task 1〜3 の 4 つのファイル（ビルドコンテキストの直下）。

`# >>> c3c copilot` の区間の中身（一時パスへ COPY し、`set -e`、opt-out の判定は Codex と同じ正規化 `tr -d '[:space:]'`）:
- 空なら: 一時ファイルを消して `INFO: Copilot は無効のため入れません` だけ。
- 版の書式を検査する（Global Constraints の正規表現）。`command -v npm` が無ければ、Codex と同じ文型の ERROR で止める。
- `apt-get update && apt-get install -y --no-install-recommends bubblewrap && apt-get clean && rm -rf /var/lib/apt/lists/*`。`dpkg --compare-versions "$(dpkg-query -W -f='${Version}' bubblewrap)" ge 0.5.0` が偽なら止める。
- `npm install -g "@github/copilot@${COPILOT_VERSION}"`。`package.json` の `version` が指定と一致すること、Global Constraints のネイティブのバイナリが実行可能な通常ファイルであることを確かめる。
- `/usr/local/bin/copilot` が symlink で、`readlink -e` が `COPILOT_JS` と一致し、`COPILOT_JS` が `-f`・`-x` を満たすことを確かめる。そのあと `rm -f` して、`install -o root -g root -m 0755` で起動口を置く。起動口の中に `readonly COPILOT_JS=<固定値>` があることを `grep -qxF` で確かめる。
- `install -d -o root -g root -m 0755 /usr/local/libexec/c3c /usr/local/libexec/c3c/copilot-bwrap`。中継を `install -o root -g root -m 0755` で置き、中継の中に `readonly REAL_BWRAP=/usr/bin/bwrap` があることを `grep -qxF` で確かめる。
- `install -d -o root -g root -m 0755 /etc/c3c`。雛形を `install -o root -g root -m 0644` で `/etc/c3c/copilot-settings.json` に置く。
- opt-in のときも opt-out のときも、区間の最後で `/tmp/copilot-version.txt`・`/tmp/copilot-launcher.sh`・`/tmp/copilot-bwrap-shim.sh`・`/tmp/copilot-settings.json` を `rm -f` する。
- 中継・起動口・雛形と、それぞれの親から `/` までが `( ! -user 0 -o -perm /022 )` に当たらないことを `find` で検査する（Codex の区間と同じ形）。中継のディレクトリの中身が 1 ファイルだけであることも確かめる。

許可リストへの追記（`COPY allowed-domains.txt` の RUN の直後の RUN）: `/etc/c3c/copilot-settings.json` があるときだけ、Global Constraints の 2 つの名前を、行の完全一致（`grep -qxF`）で無いときに限り `/etc/c3c/allowed-domains.txt` の末尾に足す。ファイルが空でなく、末尾が改行で終わっていなければ、先に改行を 1 つ足す（最後の行とつながらないように）。試験: 全体実行の opt-in のビルドで、project の `allowed-domains.txt` を末尾の改行なしにしたものでも、2 つの名前が独立した行になる。

- [ ] **Step 1: 失敗する probe を書く**（`test-build.sh`）
  - `--build-only`（同梱 default ＝ 無効）: `! command -v copilot && [ ! -e /usr/local/libexec/c3c/copilot-bwrap ] && [ ! -e /etc/c3c/copilot-settings.json ] && ! dpkg -s bubblewrap >/dev/null 2>&1 && ! grep -q githubcopilot /etc/c3c/allowed-domains.txt`。既存の `CODEX_LAUNCHER_PROBE` も通ること。
  - 全体実行に opt-in のビルドを足す（`copilot-version.txt` に `1.0.103`）。`COPILOT_PROBE` で次を確かめる。
    - 起動口・中継・雛形の所有者と mode、node から書けないこと
    - 中継のディレクトリの中身が 1 ファイルだけ
    - `node /usr/local/lib/node_modules/@github/copilot/npm-loader.js --version` の出力に `1.0.103` を含む
    - `/usr/bin/bwrap --version`
    - `bash -lc "command -v copilot"` が `/usr/local/bin/copilot`
    - `COPILOT_PAT` の無いイメージで `/usr/local/bin/copilot --version` が rc 1 で止まり、トークンの ERROR を出す
    - `/tmp/copilot-*` が残っていない
    - `/etc/c3c/allowed-domains.txt` に 2 つの名前がちょうど 1 行ずつある
    - opt-in でも Codex の `CODEX_LAUNCHER_PROBE` が通る
  - 全体実行に、Codex を無効（空の `codex-version.txt`）にして Copilot を有効にしたビルドを足す（`/usr/local/libexec/c3c` を Copilot の区間が自分で作る経路）。
  - 全体実行に、不正な版（`latest`）のビルドが失敗することを足す。
- [ ] **Step 2: 失敗を確かめる** — Run: `./test-build.sh` / Expected: 無効のときの probe は通り、opt-in の `COPILOT_PROBE` は区間が無いので FAIL
- [ ] **Step 3: 区間と追記の RUN を実装する**
- [ ] **Step 4: 文書を直す**（同じ commit）
  - README の「Copilot CLI を使う」節（Codex の対話の節の後、「c3c 入口」の前）:
    - opt-in の手順: 版を書く。PAT は `COPILOT_PAT` で、権限は Copilot Requests だけ。メイン PAT を使わない。
    - 宛先 2 つを自動で足すこと。個人のプラン以外の宛先は対象外。
    - 起動口が止める条件: 設定の検査、作業ディレクトリ、トークン。
    - sandbox から作業ディレクトリが見えること（書けるかは Task 5 の結果で書く）。
    - Copilot 自身のツール（ファイルの表示・編集など）は sandbox の外の Copilot のプロセスで動くこと。
    - 外への通信を許す設定は対応外。
    - `/dev/net/tun` と slirp4netns を入れない理由と、Copilot のヘルプとの食い違い。
    - 中継は、MXC に予備の道が入るまでの暫定。
    - `COPILOT_HOME` は永続化しないこと（コンテナを作り直すと雛形から作り直す）。
    - 自動更新（Task 3 Step 4 の 7）。
  - README の残りの節:
    - GitHub トークンの配線: `COPILOT_PAT` の行
    - 何ができて何ができないか: Copilot の行
    - セキュリティモデル: Copilot の sandbox と中継の段落
    - Podman 固有の注意の `/proc` の項
    - コンテナ間の永続化: `~/.copilot` は残らない
    - 変更後の確認: 起動口・中継・Dockerfile の copilot の区間・`copilot-version.txt` を変えたときの検証（`tests/test_copilot_*.py`、`--launcher-only`、`--build-only`、opt-in を含む全体実行、Task 5 の受け入れ）
  - `docs/development-invariants.md` のコアスクリプトの不変条件に、`copilot-launcher.sh`・`copilot-bwrap-shim.sh`・Dockerfile の copilot の区間・`copilot-version.txt` を足す。
- [ ] **Step 5: 通るのを確かめる** — Run: `./test-build.sh --build-only && ./test-build.sh && ./lint.sh` / Expected: すべて PASS。ネットワークの制約で全体実行が走らない場合は、`not run` と理由を書く。
- [ ] **Step 6: commit** — `feat: opt-in で Copilot CLI と bwrap の中継をイメージに入れる`

### Task 5: 実機の受け入れ（持ち主の操作、クレジットを使う）

この Task は、想定外の結果が出たら止まって持ち主に報告する（その場で直さない）。どの Step も、操作するのは持ち主。実装者は、打つコマンドを `!` で貼れる形で示し、結果を受け取って判定する。

- [ ] **Step 1（持ち主）:** c3c 自身の `.c3c/` に `copilot-version.txt`（`1.0.103`）を置く。`SECRETS_DIR` の直下に、Copilot Requests だけの PAT を `COPILOT_PAT`（600）で置く。`c3c -b` でビルドして起動する。Expected: 起動の INFO に `Copilot 版: 1.0.103（採用元: project …）` が出る。
- [ ] **Step 2（持ち主）:** コンテナの中で、外側の基準値と目印を用意する。
  - `readlink /proc/self/ns/user /proc/self/ns/net` を控える。
  - `echo MARK > /home/node/.copilot/mark`（Step 3 の前に一度 `copilot` を起動して、`COPILOT_HOME` を作っておく）。
  - 外側から `/home/node/.config/c3c/secrets/COPILOT_PAT` が読めること（`test -r`）を確かめる。
  - `mkdir -p /home/node/.config/gh && echo MARK > /home/node/.config/gh/c3c-copilot-mark` で gh の設定の場所に無害な目印を置き、外側から `cat` で読めることを確かめる（Step 5 で消す）。
- [ ] **Step 3（持ち主）:** `/workspace` を作業ディレクトリにして、canary を起動口経由で 2 回走らせる。
  - 依頼文 `P` は heredoc（`read -r -d '' P <<'EOF'`）で逐語に作る。1 行目は `Run exactly this one bash command with the shell tool, then report its full output verbatim inside a code block and nothing else:`、2 行目は次のコマンド:
    `readlink /proc/self/ns/user /proc/self/ns/net; ip -brief link; curl -sS -m 5 -o /dev/null -w "%{http_code}" https://api.github.com/; echo " curl_rc=$?"; cat /home/node/.config/c3c/secrets/COPILOT_PAT >/dev/null; echo "secret_rc=$?"; cat /home/node/.copilot/mark >/dev/null; echo "home_rc=$?"; cat /home/node/.config/gh/c3c-copilot-mark >/dev/null 2>&1; echo "gh_rc=$?"; echo "tok_len=${#COPILOT_GITHUB_TOKEN} gh_len=${#GH_TOKEN}"; echo "outer_environ=$(grep -l COPILOT_GITHUB_TOKEN /proc/[0-9]*/environ 2>/dev/null | wc -l)"; touch "$PWD/.c3c-copilot-w" 2>/dev/null; echo "w_rc=$?"`
  - 起動: `copilot -p "$P" -s --model gemini-4-argon --available-tools=bash --allow-tool=shell --no-ask-user --no-auto-update --max-ai-credits 30`
  - Expected:
    - user と net の名前空間が Step 2 の値と違う
    - ネットワークは `lo` だけで、`curl_rc=6`
    - `secret_rc`・`home_rc`・`gh_rc` が 0 以外
    - `tok_len=0`、`gh_len=0`、`outer_environ=0`
    - 2 回目も起動口が止まらない（Copilot が 1 回目で `settings.json` を書き換えても、検査を通る）
  - `w_rc=0`（sandbox から作業ディレクトリに書ける）のときは、作ったファイル `.c3c-copilot-w` を消し、そこで止めて持ち主に報告する。`/workspace` はホストのプロジェクトのフォルダなので、書けるとモデルが `.git/hooks` などに置いたものが、後でホストで sandbox の外で動きうる。作業ディレクトリを読み取りだけにする（雛形の `addCurrentWorkingDirectory` や MXC の読み取り専用の許可で足りるかを調べる）か、別の写しで走らせるかを、持ち主が決める。`w_rc` が 0 以外なら、README に「sandbox から作業ディレクトリは読めるが書けない」と書く。
  - `tok_len` が 0 でないときは、ここで止めて持ち主に報告する。
- [ ] **Step 4（持ち主）:** 作業ディレクトリを `/home/node` にして `copilot --version` → 起動口が rc 1 で止まる。`/home/node/.copilot/settings.json` の `allowOutbound` を true にして起動 → rc 1 で止まる。そのあと、`settings.json` を消して雛形から作り直させる。
- [ ] **Step 5（持ち主）:** 後片付け。`/home/node/.config/gh/c3c-copilot-mark` を消す。c3c 自身の `.c3c/copilot-version.txt` を消す（`.c3c/` は gitignore されているが、残すと c3c のイメージが Copilot 入りのままになる）。必要なら `c3c -b` で作り直す。
- [ ] **Step 6:** 結果（rc、出力、canary の回数と `usage.json` の値）を PR の本文に書く材料として残す。

### Task 6: 上流の MXC への要望の下書き

- [ ] **Step 1:** `microsoft/mxc` に出す Issue の本文の下書き（英語）を、PR の本文の末尾に置く。中身は、コンテナ（Podman の `/proc` のマスク）で `--proc /proc` が失敗する再現、Codex の `run_bwrap_with_proc_fallback()` の例、提案（マウントに失敗したら外側の `/proc` を `--ro-bind` で引き継ぐ道と、そのときの保護の違い）。投稿は持ち主の確認を得てから行う（対外操作）。

### Task 7: 仕上げ、PR、PR 後のレビューへの引き継ぎ

- [ ] **Step 1:** **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion — `./lint.sh`、`./test-build.sh --validator-only`、`--launcher-only`、`--build-only`、全体実行、Task 3 Step 1 と Task 5 の結果を、実行したもの・`not run`（理由）に分けて揃える。
- [ ] **Step 2:** **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review — 区分が境界なので、PR の前に Claude と Codex の二重レビュー（グローバル指示「モデルと実装者の使い分け」の順と並走の規則）を行う。Critical・Important を直して、確認限定巡を終える。
- [ ] **Step 3:** **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch — push して PR を作る選択肢を選ぶ。push の前に持ち主に確認する。PR の本文に書くもの:
  - レビューの判定と、未対応の Minor
  - Task 3 Step 1 と Task 5 の結果
  - `ASSET_HASH_TARGETS` が増えるので、無効のプロジェクトも含めて全利用側でドリフトの WARNING が出ること（不変条件どおりの意図した挙動）
  - Task 6 の下書き

  両レビューの全文は PR コメントに投稿する。
- [ ] **Step 4:** PR 後の二重レビューを、作成に関わっていない対話セッションに渡す。handover に、PR の番号、対象の commit、検証の結果、未確認の事項を書く。PR 後のセッションは、受け取ったレビューに superpowers:receiving-code-review を使う。マージは、そのセッションがグローバル指示の 3 条件で行う。
- [ ] **Step 5:** マージ後に、SemVer のタグ（opt-in の設定が増えるので minor）を `release-tag` skill で提案する（作成は持ち主の承認の後）。

## 計画レビューの記録

- Self-Review: 作業ディレクトリの拒否の範囲を広げた（`.claude`・`.codex`・secrets の下）、Task 5 の依頼文の仮置きを逐語にした、Task 4 Step 2 の Run を全体実行に直した、宛先の判定の対象を「採用した許可リスト」にした
- 版: `plan-initial.md` `<scratchpad>/tasks/b0cygjsl4.output`
- Claude（claude-opus-5-5、claude-fable-5-1 も使用、session `190aa310-bb7f-45a4-a6d4-597ac744ab4c`、所要 633 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bbjccbqa4.output`
  - I1 Task 1 が未作成の 3 ファイルを登録して通らない → 採用（各ファイルを作る Task 2・3 で登録する）
  - I2 新しい INFO 行で既存の試験が落ちる、文言が未定 → 採用（文言を逐語で決め、「opt-out」「同梱 default」を含まない形にした）
  - I3 新しい unittest が CI で走らない → 採用（`run_launcher_tests()` に登録）
  - I4 README を同じ commit で直していない → 採用（Task 1・4 に移し、旧 Task 6 を Task 4 に統合）
  - I5 README の節が足りない、`COPILOT_HOME` の永続化が未定 → 採用（節を足し、永続化しないと決めた）
  - I6 Dockerfile の区間の位置、apt の update、`/etc/c3c`、版の比較 → 採用（位置を逐語にし、apt の一連と `install -d` と `dpkg --compare-versions` を書いた）
  - I7 `COPILOT_HOME` を環境から受けると上書き口になる → 採用（固定値にした）
  - I8 トークンを環境変数で渡す方式の検証が遅い → 採用（Task 3 Step 1 (b) で先に確かめ、だめなら止まる）
  - I9 Copilot が作業ディレクトリから読む設定・hook と、作業ディレクトリへの書き込み → 採用（Task 3 Step 1 (a) で確かめ、止められなければ止まる。Task 5 で `w_rc` を測る）
  - I10 許可リストの判定の読み方 → 自動で足す形に変えたため不要（I11）。追記は行の完全一致で重複を避ける
  - I11 spec の「宛先を足す」を計画が「足さない」に変えていた → 採用（opt-in のときイメージの許可リストに足す。計画者の判断の誤り）
  - M1〜M13 → すべて採用（`--` で走査をやめる、`-x` と `grep -qxF`、値の検査、`pwd -P` の失敗・symlink・要素単位の比較、`TOKEN_FILE` と entrypoint の照合、opt-out の bubblewrap と組み合わせのビルド、fixed の試験の一覧、Task 5 の基準値・後片付け・2 回の実行・操作者、自動更新、ネイティブのバイナリのパス、PR 後のレビューとドリフトの WARNING、Copilot 自身のツール、推奨の理由）
- Codex（gpt-6.1-sol、所要 114 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bgu0fgyjl.output`
  - C1 `env -i` の引数にトークンが載り、並行する別の sandbox から `/proc/*/cmdline` で読める → 採用（bash の組み込みで環境を絞る形にし、`test_token_not_in_any_argv` を足した）
  - I1 apt の索引を取らずに install している → 採用（Claude の I6 と同じ）
  - I2 Task 1 が Task 2・3 の成果物に依存する → 採用（Claude の I1 と同じ）
  - I3 新しい unittest が CI に接続されない → 採用（Claude の I3 と同じ）
  - I4 README の commit の境界 → 採用（Claude の I4 と同じ）
  - I5 受け入れ試験で目標を判定しきれない → 採用（外側の基準値、目印、gh の設定、heredoc の依頼文を足した。`COPILOT_HOME` は固定にした）
  - M1 真偽値の検査に数値が通る → 採用（`is True` / `is False` と `test_refuses_non_bool_values`）
  - M2 PR 後のレビューへの引き継ぎが無い → 採用（Task 7 Step 4）
- 確認限定巡 1: Codex（C1・I1〜I5、所要 32 秒）→ C1・I1〜I4 は直った、I5 は一部未修正（gh の設定に目印と外側の正常対照が無い）。修正後に渡せる。生の出力 `<scratchpad>/tasks/bf09khvj3.output` → Task 5 Step 2・3・5 に gh の目印を足した
- 確認限定巡 1: Claude（I1〜I11、所要 31 秒）→ すべて直った。実装に渡せる。補足（Minor）: 許可リストの末尾に改行が無いと追記の行がつながる → 採用（改行を補う手順と試験を Task 4 に足した）。生の出力 `<scratchpad>/tasks/bktuxhkna.output`
- 確認限定巡 2: Codex（I5、所要 21 秒）→ 直った。実装に渡せる。生の出力 `<scratchpad>/tasks/b88awli40.output`
- 承認の後の変更（2026-11-08、持ち主の側から届いた注意を受けて）: Task 5 Step 3 で `w_rc=0` のときは、記録だけでなく止めて持ち主に報告し、読み取りだけにするか別の写しで走らせるかを決めてもらう形にした。同じ測定を Task 3 Step 1 (b) にも足し、実装の前に分かるようにした（Claude の I9 の扱いを強めた）。
- argon（並走、正式外）: 修正後に渡せる。消費 59.0 クレジット、所要 893 秒。生の出力 `<pairing-runs>/20261108-c3c-plan-copilot-sandbox-argon/out.txt`。送ったのは `plan-initial.md`（公開の経路、未 push、base `4508e96`）。Sol と材料が違った点: グローバル指示と `.claude/AGENTS.md` は渡さず名前だけ、スキルの表の `~/` のパスを外した
  - C1 Task 1 が未作成のファイルを登録 → 既に反映済み（Claude I1・Codex I2 と同じ）
  - C2 起動口が `deniedPaths` の中身を見ていない → 採用（雛形の 2 つを必須にし、`test_refuses_missing_denied_paths` を足した）
  - C3 `COPILOT_HOME` の上書き口と、作業ディレクトリの検査の抜け → `COPILOT_HOME` は既に固定。作業ディレクトリは採用（`/home/node` の下をすべて拒否、`CONTAINER_HOME` の定数）
  - I1 文言・既存の試験・許可リストの読み方 → 既に反映済み
  - I2 新しい試験が CI で走らない → 既に反映済み
  - I3 Dockerfile の位置・apt・arch・一時ファイル → 位置・apt・arch は既に反映済み。一時ファイルを opt-in でも消す点を採用
  - I4 トークンのファイルの境界（LF だけ、2 行、空白） → 採用（`^[!-~]+$` にし、試験を足した）。`env -i` の `--` の点は、`env -i` を使わない形にしたので不要
  - I5 Task 7 Step 3 のスキルの並びが誤り → 不採用（グローバル指示の表が例に挙げる並びそのもの。レビューの反映の後に検証をもう一度挟む）
  - M1 unittest のコマンドが `ModuleNotFoundError` になる（argon の実測） → 採用（既存と同じ `discover -s tests -p` の形）
  - M2 `/home/node` の定数 → 採用。M3 起動口の probe → 採用
- 確認限定巡 3: Codex（argon の C2・C3 の作業ディレクトリ・I3 の一時ファイル・I4、所要 26 秒）→ すべて直った。実装に渡せる。生の出力 `<scratchpad>/tasks/b60z8j8i5.output`

区分: 境界（セキュリティ境界〈コンテナの中の sandbox の構成〉と、秘密やトークンを読む経路〈`COPILOT_PAT` の読み込み〉に触れるため）
推奨実装: Opus（判定順 2「秘密やトークンを読む経路に触れる変更 → Claude（Opus）」に当たるため。Codex を推さないのは、判定順 2 が 4〜6 より先に当たるから。単価は Sonnet より高いが、作業は 7 Task で 1 セッションに収まる見込み）
