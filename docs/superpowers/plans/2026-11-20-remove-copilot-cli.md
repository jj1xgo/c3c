# Copilot CLI の opt-in を外す 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1・2 の検査と試験の付け替えに使う。Task 3・4 は文言と文書）

**Goal:** c3c から Copilot CLI の opt-in（`.c3c/copilot-version.txt`、起動口〈並走のための `--c3c-fusion-tier` と `fusionTier` を含む〉・中継・雛形、ビルドの区間、試験と canary、文書）を外し、残った `copilot-version.txt` を起動・`-b`・`--check` で止める。SemVer の MAJOR（v21.0.0 の見込み）。

**Architecture:** 新しい検査（残った設定の検査）を先に TDD で入れ、続けてビルドの経路（`c3c` の資産の一覧・`COPILOT_CACHEBUST`・ビルドの文脈に残る古いファイル・`compose.yml`・`Dockerfile.claude` の区間・専用ファイル）と試験を一緒に外す。Copilot だけを根拠にしていた 2 つの境界の検査（`HOME_MOUNT` の秘密の重なり、`~/.config` の sticky と既知の限界）は残して理由を書き直し、最後に README・不変条件・`.gitignore` を整える。

**Tech Stack:** bash（`c3c` は `set -euo pipefail`、`test-build.sh`）、Python unittest（`tests/`）、Dockerfile、Compose。

**Spec:** `docs/superpowers/specs/2026-11-20-remove-copilot-cli-design.md`（c243e30）

**計画の保存先:** 承認の後に、この計画を `docs/superpowers/plans/2026-11-20-remove-copilot-cli.md` へ写して commit する（計画者が行う。記録節を正本とし、レビューの生の出力は公開のリポジトリに置かない）。

## Global Constraints

- 作業ブランチは `remove-copilot-cli`（c243e30 の上）。`main` に直接 commit しない。行番号は c243e30 の作業ツリーのもので、編集は関数名と対象の語を基準にする（前の Task の編集で行がずれる）。
- 変更する前に `docs/development-invariants.md` の該当節を読む（root `AGENTS.md`。`c3c`・`compose.yml`・`Dockerfile.claude` を変える）。
- ファイルを編集したターンの中で `./lint.sh` を走らせ、rc 0・警告ゼロを確かめる（版の WARNING の例外は README「変更後の確認」のとおり）。
- 日本語で書く。挙動を変えた README の節は、その挙動の commit に入れる（Task 1 の停止は Task 1 の commit で README に書く）。
- 残すもの: `.mcp.json.example` と `.c3c/allowed-domains.txt` の `api.githubcopilot.com`（GitHub MCP）、README 418・426（GitHub MCP）、`docs/superpowers/plans/` と `specs/` の過去の Copilot の文書、Codex の同梱 bubblewrap（#145）、`HOME_MOUNT`・`HOME_MOUNT_RO` の検査、`~/.config` の sticky の RUN（理由の文だけ直す）。
- 古いイメージは止めない（資産のハッシュのずれの WARNING に任せる）。
- commit は、この計画の承認の範囲で、各 Task の commit の Step で行ってよい。push・PR の作成・Issue や外部への投稿は、その都度持ち主に確かめる。
- 公開のリポジトリなので、計画・commit・PR にホストのパスや非公開のリポジトリの名前を書かない。`git add` はファイルを名指しし、`git add -A` を使わない。commit の前に `git status --short` で、意図しないファイル（特に `.c3c/copilot-version.txt`）が入っていないことを見る。
- 停止の文言（Task 1 で固定。README も同じ文）:
  `ERROR: <PROJECT_CONF_DIR>/copilot-version.txt があります。c3c v21 で Copilot CLI の opt-in を廃止したので、Copilot は入りません。このファイルを消してから起動してください（SECRETS_DIR の COPILOT_PAT も不要になりました。失効は GitHub で行います）。`
  出し方は既存の `guard_fail` のまま（起動は stderr、`--check` は stdout にまとまり、最後に `→ 結果: FAIL`）。設計書の「`--check` では `[ERROR]` で出す」とは違う（既存の止まる検査〈`test_copilot_version_bad_format_fails` など〉と同じ形にそろえる計画者の判断）。設計からの逸脱として、2026-11-20 の計画の承認で持ち主が確定した。
- 止めない条件は「symlink でない通常のファイルで、読めて、`LC_ALL=C tr -d '[:space:]'` の出力が 0 バイト」だけ。判定はバイト数（`wc -c`）と `tr` の rc の両方で行い、コマンド置換の文字列で判定しない（NUL を捨てるため）。ほか（版が書いてある、NUL を含む、ディレクトリ、symlink〈壊れたものを含む〉、読めない）は同じ文言で止める。

## Review Focus

1. 残った `copilot-version.txt` が symlink・ディレクトリ・壊れた symlink・NUL だけ・読めないとき、黙って通らずに止まる（Task 1 の `test_leftover_copilot_version_non_regular_fails`）。
2. `--check` で残った設定に当たっても、そのプロジェクトの後段の診断（`packages.txt:` の行）が停止の文言より後に出て、`→ 結果: FAIL`・rc 1 になる（Task 1 の `test_leftover_copilot_version_fails`）。
3. v20 で一度ビルドしたプロジェクトの `.build-context/<project>/` に、Copilot の 4 つのファイルが残る（Task 2 の `test_stale_copilot_files_removed_from_build_context`）。
4. 資産の一覧から消したファイルを `Dockerfile.claude` の COPY や `test-build.sh` の写しが参照し続けてビルドや試験が壊れる（Task 2 Step 6 の `git grep`、Step 7 の `--validator-only`・`--launcher-only`、Task 5 の全体実行）。
5. README の目次（20 行）の `#copilot-cli-を使う` を消し忘れて、lint のアンカー検査が落ちる（Task 4 Step 5）。

---

### Task 1: 残った `copilot-version.txt` を止める検査（TDD）

**Files:**
- Modify: `c3c`（`guard_build_input_defaults()`、1036-1108）
- Test: `tests/test_c3c_config.py`（`BuildInputDefaultTests`〈548〉の Copilot の区画 749-830 と、587-603 の試験）
- Modify: `README.md`（295 の `copilot-version.txt` の段落を、廃止の段落に置き換える）

**Interfaces:**
- Produces: `guard_build_input_defaults()` が Copilot の版を解決・表示しなくなり、代わりに残った設定の検査をする。ほかの関数の名前と引数は変えない。

- [ ] **Step 1: 試験を書く。** `tests/test_c3c_config.py` の 587-603（`test_rebuild_cachebust_follows_resolved_copilot_version`。版を書くと Task 1 の検査で止まるので、ここで消す）と 749-830（`# --- Copilot CLI` の区画、`COPILOT_PIN` と 6 つの試験）を消し、749 の位置に次の 4 つを置く。流儀は消す `test_copilot_version_bad_format_fails`（814-830）のまま（subTest ごとに `self.state = {'image_exists': False, 'label': '2', 'preflight': {}}`、`self.run_c3c('claude', str(self.proj))`、`self.assert_no_containers()`、`self.compose_calls('build')`、`self.run_check('c3c', self.proj)`）。`message` は Global Constraints の文言の `<PROJECT_CONF_DIR>` を `self.new` にしたもの。
  - `test_leftover_copilot_version_fails`: `('1.0.103', 'latest', 'x')` を subTest で書き、(a) 起動は rc 1・`message in result.stderr.splitlines()`・コンテナとビルドなし、(b) `self.run_c3c('claude', '-b', str(self.proj))` も rc 1・`self.compose_calls('build') == []`、(c) `--check` は rc 1・`message in check.stdout.splitlines()`・`'→ 結果: FAIL' in check.stdout`・停止の文言の行の位置より後に `packages.txt:` を含む行がある（後段の診断が続く）。
  - `test_leftover_copilot_version_non_regular_fails`: ディレクトリ、空の通常のファイルを指す symlink、壊れた symlink、中身が `b'\0'` のファイル、中身が `b' \0\n'` のファイル、読めないファイル（`chmod 0`。`os.geteuid() == 0` なら この場合だけ `self.skipTest`）で、起動と `--check` が上と同じ rc と `message` になる。
  - `test_leftover_copilot_version_blank_is_allowed`: 中身が `''` と `' \n\t\n'` の通常のファイルで、`result, run, staged = self.launch_claude()`（563 の既存の部品）が rc 0 で進み、stderr に `copilot-version.txt` を含む `ERROR:` の行が無い。`--check` は rc 0。
  - `test_no_copilot_version_is_allowed`: ファイルが無ければ、起動の stderr と `--check` の stdout のどこにも `Copilot` が出ない。
- [ ] **Step 2: 落ちることを確かめる。** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_config.py' -k leftover_copilot -k no_copilot -v`。Expected: `test_leftover_copilot_version_fails`・`test_leftover_copilot_version_non_regular_fails`・`test_no_copilot_version_is_allowed` の 3 つが FAIL、`test_leftover_copilot_version_blank_is_allowed` は OK（今の挙動を固定する回帰の試験）。
- [ ] **Step 3: 実装する。** `guard_build_input_defaults()` から、ループの `copilot-version.txt`（1050）、copilot の分岐（1055-1074）、`copilot_value`（1049）、Node が空で Copilot が有効なときの `guard_warn`（1102-1106）、説明コメントの Copilot の部分（1041-1044）を消す。検査は、Codex の npm の `guard_warn`（1097-1101）の後、関数の最後の `return 0` の直前に置く: `path="$PROJECT_CONF_DIR/copilot-version.txt"`。`[[ -e "$path" || -L "$path" ]]` なら、`[[ -f "$path" && ! -L "$path" && -r "$path" ]]` で、かつ `LC_ALL=C tr -d '[:space:]' < "$path" | wc -c` が成功して出力が `0` のときだけ通す。それ以外は `guard_fail "<Global Constraints の文言>" || return 1`。`resolve_asset_source()` は通さない（project の置き場だけを見る）。関数の説明コメントにこの検査を 2 行で書く。
- [ ] **Step 4: README。** 295 の `copilot-version.txt` の段落を、次の内容の段落に置き換える: c3c v21 で Copilot CLI の opt-in を廃止した。`.c3c/copilot-version.txt` に版が書いてある（または通常のファイルでない）と、起動・`-b`・`--check` が Global Constraints の文言で止まる。消せば起動する（中身が空白だけなら止まらないが、消してよい）。`SECRETS_DIR` の `COPILOT_PAT` は不要で、失効は GitHub で行う。作り直していないイメージには Copilot が残り、`-b` で作り直すまで資産のずれの WARNING が出る。
- [ ] **Step 5: 通ることを確かめる。** Step 2 のコマンド。Expected: 4 つとも OK。続けて `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_config.py' -v`。Expected: 全部 OK。`./lint.sh`。Expected: rc 0、警告ゼロ。
- [ ] **Step 6: commit。** `git status --short` を見てから `git add c3c tests/test_c3c_config.py README.md`、`git commit -m "feat!: 残った copilot-version.txt を起動と --check で止める（Copilot CLI の廃止の第 1 段）"`。

### Task 2: ビルドの経路と専用ファイル・試験を外す

**Files:**
- Delete: `copilot-launcher.sh`、`copilot-bwrap-shim.sh`、`copilot-settings.json`、`copilot-version.txt`、`tests/copilot-canary.sh`、`tests/copilot_canary_helper.py`、`tests/fixtures/copilot-canary/`、`tests/test_copilot_bwrap_shim.py`、`tests/test_copilot_canary.py`、`tests/test_copilot_canary_helper.py`、`tests/test_copilot_config_check.py`、`tests/test_copilot_launcher.py`
- Modify: `c3c`（`resolve_asset_source()` の説明 2727-2741〈Copilot は 2730-2731・2735〉と case 2748・2752、`ASSET_HASH_TARGETS` 2787-2789・2809、`stage_build_context()` の説明 2838-2840 とループ 2852・2877、`run_explicit_build()` 1672-1678・1686）
- Modify: `compose.yml:12`、`Dockerfile.claude`（377-492 の区間、505-516 の RUN とコメント）
- Modify: `test-build.sh`（409-422、1242-1246、2174、2910、3002-3004・3012、3216-3228、3512-3647）
- Modify: `tests/test_c3c_config.py`（451 の名前の一覧、`BuildInputDefaultTests` に試験を 2 つ足す）、`tests/test_container_paths.py:14`、`tests/test_network_timeouts.py:137`。`tests/test_c3c_launch.py:53` の記録するキーの一覧は変えない（`COPILOT_CACHEBUST` が渡らないことを観測するため）

**Interfaces:**
- Consumes: Task 1 の検査（project の `copilot-version.txt` は `resolve_asset_source()` を通さずに見る）。
- Produces: 資産の一覧とビルドの文脈に Copilot のファイルが無い。`c3c`・`compose.yml`・`Dockerfile.claude` に `COPILOT_CACHEBUST` が無い。

- [ ] **Step 1: 試験を先に書く。** `tests/test_c3c_config.py` の `BuildInputDefaultTests` に 2 つ足す。
  - `test_no_copilot_build_inputs`: `result, run, staged = self.launch_claude('-b')` の後、build の呼び出し（`[c for c in self.calls if c['args'][:1] == ['compose'] and 'build' in c['args']]`、ちょうど 1 つ）の `env['COPILOT_CACHEBUST'] is None` と、`'copilot-version.txt' not in staged`。
  - `test_stale_copilot_files_removed_from_build_context`: 起動の前にビルドの文脈のディレクトリ（`staged_files()` が読むのと同じ場所）を作り、`copilot-bwrap-shim.sh`・`copilot-launcher.sh`・`copilot-settings.json`・`copilot-version.txt` を置く。`self.launch_claude('-b')` の後、その 4 つがどれも無い。
  - 451 の名前の一覧から copilot の 3 つを外す。`tests/test_container_paths.py:14` と `tests/test_network_timeouts.py:137` から copilot の 3 つを外す。
- [ ] **Step 2: 落ちることを確かめる。** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_config.py' -k no_copilot_build -k stale_copilot -v`。Expected: 2 つとも FAIL。
- [ ] **Step 3: 本体から外す。** `c3c` の上の Files の箇所から Copilot の名前と `COPILOT_CACHEBUST` を消す。`stage_build_context()` の `mkdir -p` の直後に、古い版が置いた `copilot-bwrap-shim.sh copilot-launcher.sh copilot-settings.json copilot-version.txt` をビルドの文脈から消す 1 行（`rm -f -- "$BUILD_CONTEXT_DIR"/...`）とその理由のコメント（v20 以前のビルドの残り）を足す。`compose.yml:12` を消す。`Dockerfile.claude` の 377-492（`# >>> c3c copilot` から `# <<< c3c copilot`）と 505-516（Copilot の宛先を許可リストに足す RUN とそのコメント）を消す。Files の Delete を `git rm -r` する。
- [ ] **Step 4: 通ることを確かめる。** Step 2 のコマンド。Expected: 2 つとも OK。`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_*.py'`。Expected: 全部 OK。
- [ ] **Step 5: `test-build.sh` を直す。** 1242-1246 の 5 つの `check`、2174 と 2910 の `cp` の中かっこの一覧の copilot の 4 つ、3002-3004 と 3012 の写し、3512-3647 の実ビルドの opt-in の節（`log ""` の 3647 まで。3571 が使う `CODEX_LAUNCHER_PROBE` の定義〈3177〉は残す）を消す。3216-3228 の `--build-only` の probe は残し、名前と説明を「Copilot が入っていない（copilot・中継・雛形・Debian の bubblewrap・許可リストの宛先・一時ファイル）」にする（作り直したイメージに残りが無いことの回帰の検査。設計書の「外すもの」5 からの逸脱で、2026-11-20 の計画の承認で持ち主が確定した）。409-422 の apt-sources の検査は、413 の期待の数を 4 → 3、422 を 2 → 1 にし、418 の awk の `--no-install-recommends bubblewrap` の条件と、414-416 のコメント・失敗の文の Copilot の層を消す。
- [ ] **Step 6: 参照の残りを確かめる。** `git grep -nE 'copilot-(launcher|bwrap-shim|settings|version)|COPILOT_CACHEBUST|test_copilot_|copilot_canary|copilot-canary|c3c-fusion-tier|fusionTier' -- c3c compose.yml Dockerfile.claude test-build.sh tests`。Expected: `c3c` の Task 1 の検査と Step 3 の `rm -f` の行、`tests/test_c3c_config.py` の Task 1・Task 2 の試験、`tests/test_c3c_launch.py:53` の記録するキー、`tests/test_install_apt_sources.py:5`（Task 3 で直す）、`test-build.sh` の `--build-only` の probe だけ。
- [ ] **Step 7: 試験を流す。** `./lint.sh`、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only`。Expected: どれも rc 0（lint は警告ゼロ）。
- [ ] **Step 8: commit。** `git status --short` を見てから、上の Files を名指しで `git add` し、`git commit -m "feat!: Copilot CLI の起動口・中継・雛形・ビルドの区間・試験を外す"`。

### Task 3: Copilot だけを根拠にしていた境界の検査の理由を書き直す

**Files:**
- Modify: `c3c`（2423-2424 のコメント、2457 の ERROR の文）
- Modify: `Dockerfile.claude`（125-126・133 のコメント、599-605 のコメント）
- Modify: `install-apt-sources.sh:7-8`、`tests/test_install_apt_sources.py:5`、`test-build.sh:2763-2764`
- Modify: `docs/development-invariants.md`（41、63、76、156）、`README.md`（249、313、395、693-694、830）

- [ ] **Step 1: 文を入れる（逐語）。**
  - `HOME_MOUNT` の秘密の重なりの理由（`c3c` 2423 のコメント、`test-build.sh` 2763-2764 のコメント、不変条件 41、README 249）: 「秘密と認証の置き場を `~` の別の位置に見せると、パスで隠す仕組み（作り直していない古いイメージに残る Copilot の起動口の sandbox など）から読めるようになり、パスで隠す仕組みを今後足しても効かなくなるため。秘密は決まったマウント先だけに置く」。
  - `c3c` 2457 の ERROR の文の「Copilot の sandbox などパスで隠している経路から読めるようになるため」を「パスで隠す経路から読めるようになるため」にする。
  - `~/.config` の sticky の理由（`Dockerfile.claude` 602、不変条件 63 の前半）: 「sticky により node は自分で作ったものしか改名・削除できず、秘密の親 `c3c`（root 所有・755）を動かせない（秘密が別のパスに見えると、パスで隠す仕組みが効かなくなる。作り直していない古いイメージの Copilot の sandbox はパスだけで隠している）」。不変条件 63 の「`copilot-settings.json` の `deniedPaths`」の言及は外す。
  - `~/.config` の改名を塞がない既知の限界の理由（`Dockerfile.claude` 603-605、不変条件 63 の後半、README 395）: 「改名できるのは、秘密をもともと読める node だけで、別のパスに見えても読める者は増えない（作り直していない古いイメージの Copilot の sandbox の中からは `/home/node` が見えない）」。
  - apt-sources の「Copilot の層」「4 か所」（`Dockerfile.claude` 125-126・133、`install-apt-sources.sh` 7-8、不変条件 76・156、README 313・693-694・830）は、「3 か所: packages.txt の層の直前〈初回の導入〉と、そのあと apt-get update を走らせる層〈packages.txt の層、-b のたびに作り直す upgrade の層〉の update の前」の形にする。不変条件 76・156 の、鍵の取り直しと upgrade の前後の照合の範囲は変えない（Copilot の層の言及だけ外す）。
  - `tests/test_install_apt_sources.py:5` の「`tests/test_copilot_bwrap_shim.py` と同じ流儀」は、流儀の説明だけを残して消したファイルの名前を外す。
- [ ] **Step 2: 確かめる。** `./lint.sh`、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only`（`HOME_MOUNT`・`HOME_MOUNT_RO` の拒否の試験を含む。ERROR の文を照合する試験は無いことを c243e30 で確かめた）。Expected: rc 0。`git grep -n 'Copilot' -- c3c Dockerfile.claude install-apt-sources.sh docs/development-invariants.md tests test-build.sh`。Expected: Task 1 の検査と試験、Task 2 の `rm -f` と probe、Step 1 で書いた「古いイメージに残る Copilot」の言及、Task 4 Step 2 で消す不変条件の 120-141（中継・起動口と雛形・Dockerfile の区間の項）だけ。
- [ ] **Step 3: 不変条件に新しい検査を足す。** `docs/development-invariants.md` の `c3c` の節に 1 項: 残った `copilot-version.txt` は `resolve_asset_source()` を通さずに project の置き場だけを見て、空白だけの通常のファイル（symlink でない、読める、`tr` の出力が 0 バイト）以外は起動・`-b`・`--check` で止める（`-f` で見て黙って既定に落とさない）。ビルドの文脈から v20 以前の Copilot の 4 つのファイルを消す。
- [ ] **Step 4: commit。** `git status --short` を見てから名指しで `git add`、`git commit -m "docs: Copilot を外した後も残す境界の検査（HOME_MOUNT の秘密、~/.config の sticky）の理由を書き直す"`。

### Task 4: README・不変条件・.gitignore の残り

**Files:**
- Modify: `README.md`、`docs/development-invariants.md`（120-141）、`.gitignore:10-12`

- [ ] **Step 1: README から Copilot の機能の説明を外す。** 20（目次）、255（「ほかの CLI から見えるか」の Copilot の文。Codex の文は残す）、275（設定のコードブロックの行）、374（「Copilot 用 PAT」の行）、610-656（`## Copilot CLI を使う` の節）、695、738、757、773、869、875、907（`--launcher-only` の説明の Copilot の部分と `COPILOT_CACHEBUST`）、933、935、939（HOME_MOUNT の確認の Copilot の部分）。418・426（GitHub MCP）と Task 1 の廃止の段落、Task 3 の文は残す。
- [ ] **Step 2: 不変条件。** 120-141（中継・起動口と雛形・Dockerfile の区間）を消す。
- [ ] **Step 3: 保守者の手元の設定（持ち主に確かめてから）。** 作業ツリーに gitignore 済みの `.c3c/copilot-version.txt` があれば、持ち主に消してよいか確かめて消す（消さないと Task 1 の検査でこのリポジトリ自身の起動が止まり、次の Step で `.gitignore` の行を外すと未追跡として現れる）。ops の「ローカル専用ファイルの台帳」の該当の行も外す（ops に commit する）。
- [ ] **Step 4: .gitignore。** 10-12 を消す。`git status --short` に `.c3c/copilot-version.txt` が出ないことを確かめる。
- [ ] **Step 5: 確かめる。** `./lint.sh`（アンカー検査を含む）。Expected: rc 0、警告ゼロ。`git grep -niE 'copilot|fusion' -- ':!docs/superpowers'`。Expected: 出るのは、`.mcp.json.example` と `.c3c/allowed-domains.txt` の `api.githubcopilot.com`、README 418・426 の GitHub MCP、README の廃止の段落、Task 1 の検査と試験、Task 2 の `rm -f` と probe と記録するキー、Task 3 の「古いイメージに残る Copilot」の言及だけ。
- [ ] **Step 6: commit。** `git status --short` を見てから名指しで `git add`、`git commit -m "docs!: README と不変条件から Copilot CLI を外す"`。

### Task 5: 検証、PR 前の二重レビュー、PR

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

- [ ] **Step 1: 試験の全体。** `./lint.sh`、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only`、`./test-build.sh`（引数なしの全体。実イメージのビルドと `--build-only` と `--config-ro-only` を含む。podman が要るのでホストで）、`bash tests/test-runtime.sh`（README「変更後の確認」の #275 の項にある runtime の検証）、`bash examples/hooks/tests/test-block-pr-approve.sh`。Expected: どれも rc 0。コンテナの中で回せないものは `not run` と理由を書き、ホストで回す。
- [ ] **Step 2: 実機の確かめ（ホスト、この順で）。** 使い捨てのプロジェクトのディレクトリ（`.c3c/` に最小の設定）を作る。
  1. `main`（v20.6.1）の c3c を `git worktree add` した別の場所から、そのプロジェクトを `-b` で作り、古いイメージにする（`.c3c/copilot-version.txt` は空のまま）。
  2. そのプロジェクトに `.c3c/copilot-version.txt`（`1.0.103`）を置き、ブランチの c3c で `--check` が rc 1 で停止の文言と `→ 結果: FAIL` を出すこと、起動と `-b` も同じ文言で止まることを確かめる。
  3. ファイルを消し、ブランチの c3c で `--check` が rc 0、`-b` なしの起動が資産のずれの WARNING を出して進むことを確かめる（古いイメージは止めない）。
  4. ブランチの c3c で `-b` して、`podman run --rm --entrypoint sh <イメージ> -c 'command -v copilot; ls -A /usr/local/libexec/c3c /etc/c3c'` に Copilot のものが無い。ビルドの文脈の `.build-context/<project>/` に Copilot の 4 つのファイルが無い。
  5. 使い捨てのプロジェクトと worktree を片付ける。
- [ ] **Step 3: PR 前の二重レビュー（区分が境界のため）。** 範囲は `c243e30..HEAD`。

  **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review（結果を受け取るとき）

  - 初回は Claude → Codex の順で、間をはさまずに続けて background で起動する。Claude は `~/.agents/skills/claude-review/SKILL.md` の手順 1〜3、Codex は `~/.agents/skills/codex-review/SKILL.md` の手順 1（`-C` はこのリポジトリ。差分はリポジトリの外〈`/tmp` など〉に書いて `-r` で渡す。計画と設計はリポジトリの中なので `-r` しない）。観点に Review Focus の 5 つを足す。
  - Critical・Important を直して commit し、確認限定巡（Codex → Claude）を終える。初回の結果を review-data の表に入れる。
- [ ] **Step 4: PR を作る。**

  **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch（「push して PR を作る」を選ぶ）

  - push は持ち主に確かめてから（計画の承認は push の承認を兼ねない）。PR 本文に、変更の要旨、MAJOR であること、利用側の移行（`copilot-version.txt` を消す、`COPILOT_PAT` は不要、作り直すまでずれの WARNING）、検証の結果と `not run`、二重レビューの判定と未対応の Minor、設計からの逸脱（`--check` の出し方、`--build-only` の probe を残したこと）を書き、末尾に `— <実効モデル名> (c3c)` で署名する（実効モデルは transcript の `.message.model` で確かめる）。Claude と Codex のレビューの全文を PR コメントに投稿する。
  - PR 後の二重レビューとマージは、作成に関わっていない対話セッションが担う（handover で渡す）。
- [ ] **Step 5: タグ（マージの後、別のセッションでも可）。** Step 2 の `--check` の実機の確かめを済ませたうえで、v21.0.0 を提案する（root `AGENTS.md`、`release-tag` skill）。提案だけで、作成は持ち主の承認の後。

### Task 6: 保守者の手元の片付け（製品の変更の外、マージの後）

この Task は公開のリポジトリを変えない。場所や名前は公開の文書に書かず、c3c の handover（非公開）に書いた一覧で行う。どれも戻せないか対外的な操作なので、1 つずつ持ち主に確かめてから行う。

- [ ] **Step 1:** ホストの Copilot CLI をアンインストールする（入れ方〈npm か別の経路か〉と、ほかの使い道が無いことを先に確かめる）。
- [ ] **Step 2:** ホストの Copilot CLI の設定と記録の置き場、一時の作業場所を、中身を見てから片付ける（残す記録があれば handover の一覧に従う）。
- [ ] **Step 3:** `COPILOT_PAT` を `SECRETS_DIR` から外し、持ち主が GitHub でトークンを失効させる（AI は失効の操作をしない）。
- [ ] **Step 4:** 保守者の手元の `.c3c/env` の `HOME_MOUNT` の値が Copilot のためのものなら、持ち主に確かめて外す。

---

## 計画レビューの記録

- Self-Review: `Node.js 版` の文言、試験の置き場の確定、apt-sources の文の逐語化、推奨実装を Sonnet → Opus（セキュリティ境界）に修正
- 版: `plan-initial.md` （一時ファイル。公開のリポジトリには置かない）
- Claude（claude-opus-5-5、session `3894dec9-6e0b-460a-ad63-c96a5af1b8b9`、所要 288 秒）: 修正後に渡せる。生の出力 （一時ファイル。公開のリポジトリには置かない）
  - I1 587-603 の試験が Task 1 で落ちる → 採用（Task 1 Step 1 で消す）
  - I2 `COPILOT_CACHEBUST` の試験が何も確かめない → 採用（記録するキーを残し、build の呼び出しを見る）
  - I3 Task 2 の grep の Expected が合わない → 採用（対象を絞り、全体は Task 4）
  - I4 `c3c` の行番号が 2000 ずれ → 採用
  - I5 README 395 と既知の限界の理由 → 採用（Task 3 に逐語文）
  - I6 手元の `copilot-version.txt` と ops の台帳 → 採用（Task 4 Step 3）
  - I7 `--build-only` の probe を残すのは設計からの逸脱 → 採用（逸脱として明記し、持ち主に示す）
  - M1〜M7 → 採用（M2 は Codex C1 と同じ、M7 は Codex I3 と同じ）
- Codex（gpt-6.2-sol、所要 209 秒）: 修正後に渡せる。生の出力 （一時ファイル。公開のリポジトリには置かない）
  - C1 NUL だけのファイルを通す → 採用（バイト数と rc で判定、NUL と読めないファイルを試験に）
  - C2 ビルドの文脈に古い Copilot のファイルが残る → 採用（`stage_build_context()` で消し、回帰の試験）。イメージには入らない（COPY しない）ので害は散らかりだけだが、最も重い深刻度を暫定で採る
  - I1 行番号 → 採用（Claude I4 と同じ）
  - I2 試験の段階の食い違い → 採用（Claude I1・I2 と同じ。README の停止の段落は Task 1 の commit に入れた）
  - I3 後段の診断の証拠、`[ERROR]` との食い違い、`-b` → 採用
  - I4 grep の範囲、apt の失敗の文と 418 の条件、不変条件 76・156 の範囲 → 採用
  - I5 古いイメージの確かめの順、`tests/test-runtime.sh` → 採用
  - I6 計画の公開の手順、手元の設定、署名、push の承認 → 採用
  - M1・M2 → 採用
- 確認限定巡 1: Codex（C1・C2・I1〜I6、所要 111 秒）→ C1・C2・I1・I2・I5 は直った、I3（`[ERROR]` との食い違いは持ち主の判断が残る）・I4（Task 3 の grep が不変条件 120-141 に当たる）・I6（保守者の片付けと commit の承認の範囲）が残る、修正後に渡せる。生の出力 （一時ファイル。公開のリポジトリには置かない） → I3 は承認のときに持ち主が確定する逸脱として明記、I4・I6 を反映（Task 6 を追加）
- 確認限定巡 1: Claude（I1〜I7、所要 22 秒）→ 全部直った、実装に渡せる。生の出力 （一時ファイル。公開のリポジトリには置かない）
- 確認限定巡 2: Codex（I3・I4・I6、所要 28 秒）→ 全部直った、実装に渡せる（承認のときに I3 の出し方を確定する条件付き）。生の出力 （一時ファイル。公開のリポジトリには置かない）

---

区分: 境界（境界機構〈起動口・中継・sandbox の設定・ビルドの区間〉を外し、新しい停止の検査を入れ、境界の検査の理由を書き直す。利用者に移行作業が要る MAJOR）
推奨実装: Opus（c3c の既定は Sonnet だが、グローバル指示の Opus を推す条件のセキュリティ境界に当たる: sandbox の起動口・中継・設定の雛形とビルドの区間を外し、新しい停止の検査を入れ、境界の検査の理由を書き直す。あわせて push と PR の対外操作を含む。Sonnet を推さないのは、境界の検査の残し方を誤ると気づきにくいため。判定順 1〜5 には当たらない）
