# 外部の APT 取得元（`.c3c/apt-sources.txt`）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 利用側のプロジェクトが `.c3c/apt-sources.txt` に宣言した外部の APT 取得元を、鍵束の主鍵の指紋の集合で照合したうえでイメージに足せるようにし、findsummits がコンテナの中で Chrome・Brave・Firefox の安定版をヘッドレスで動かせるようにする（#273）。

**Architecture:** 書式の検査は既存の `validate-build-input.sh` に kind `apt-sources` を足す（ネットワークなし、ビルド時・`--check`・`test-build.sh` の 3 者共有のまま）。鍵の取得・照合・取得元の書き込みは新しい固定アセット `install-apt-sources.sh` が行い、`packages.txt` の層の直前と、`-b` のたびに走る upgrade の層の中（鍵の取り直し）の 2 か所から呼ぶ。upgrade の層の前後で境界のファイルの状態を記録して比べる新しい固定アセット `check-boundary-files.sh` を足す。

**Tech Stack:** bash（`c3c`・`test-build.sh`）、POSIX sh（`validate-build-input.sh` と新しい 2 本）、Dockerfile（Podman）、gnupg、Python unittest（`tests/`）。

**Spec:** `docs/superpowers/specs/2026-11-15-external-apt-sources-design.md`（commit d440cc6、ブランチ `feat/external-apt-sources-273`）

## Global Constraints

- **REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（コードを変える計画なので Task 1 の前に 1 回読み込む）。
- 作業はブランチ `feat/external-apt-sources-273`（作成済み、spec の commit だけを持つ）で行う。worktree は作らない。開始時に `git worktree list`・`git status` で他のセッションの変更が無いことを確かめる。
- 編集する前に `docs/development-invariants.md` の「コアスクリプトの不変条件」節を読む（root `AGENTS.md`）。
- 新しいアセット名を足すときは、既存のアセット名を `grep -rn` で数え直す。不変条件（`docs/development-invariants.md` の境界アセットの項）のとおり、固定スクリプトは `entrypoint.sh` と `git-askpass.sh` の両方で、optional は `allowed-ports.txt` で較正し、見つかった箇所ごとに依存先（一覧・コピー・ハッシュの対象）かどうかを見て、依存先にだけ足す。2026-11-15 時点で見つかるもの: `c3c`（`resolve_asset_source()`・`ASSET_HASH_TARGETS`・`stage_build_context()` と各説明のコメント）、`test-build.sh`（`stage_common_context()`・`run_config_ro_launcher_tests()` の runner のコピーの一覧）、`tests/test_network_timeouts.py`（fixed アセットを `run_dir` へ写す一覧）、`tests/test_container_paths.py`（`CONTAINER_SIDE`）。
- ファイルを編集したら、そのターンの中で `./lint.sh` を実行し、rc 0・警告ゼロを確かめる。shellcheck を引用符なしの展開などで黙らせるときは、`# shellcheck disable=SCxxxx` と理由のコメントを付ける。
- 挙動を変えた commit には、README の該当節の更新を同じ commit に入れる（root `AGENTS.md`）。
- 文書・メッセージ・コメントは日本語。`ERROR:`・`WARNING:`・`INFO:` は英語のまま。公開リポジトリなので、ホストのパス・private リポジトリの名前を commit に入れない。
- spec の「失敗とみなすこと」をすべて守る（照合を通らない鍵・照合できない鍵でビルドが成功しない、宣言していない主鍵が混じっても成功しない、`trusted=yes` を書く欄が無い、`http://` の取得元が通らない、`apt-sources.txt` を置かないプロジェクトの起動・`--check` に**この機能に由来する**警告を増やさない）。なお、`Dockerfile.claude` と `ASSET_HASH_TARGETS` が変わるので、更新の直後はどのプロジェクトにも既存のドリフトの WARNING が 1 回出る。これは既存の仕組みどおりで、想定内とする。
- spec との差: spec は境界のファイルの照合を「ビルドコンテキストの原本と同じか」と書き、比べ方を作る人に残している。この計画は「upgrade の層の直前と直後の状態を比べる」にする（`allowed-domains.txt` のように COPY の後に Dockerfile が書き足すファイルがあり、原本との比較では誤検知になるため）。

## Review Focus

1. 宣言した URI が既存の取得元（Dockerfile 固定の `cli.github.com`）と同じ → apt が `Signed-By` の食い違いで止まる。黙って片方を使わず、ビルドが止まること（Task 5 の陰性 3）。
2. 鍵のファイルが ASCII armor かバイナリか、gpg が読み飛ばす鍵を含むか → 形式によらず import → 宣言した指紋だけを export → 書き出した鍵の主鍵の集合を照合し直してから置く（Task 2 の `test_armored_and_binary_keys`・`test_installed_key_has_only_declared_primaries`）。
3. 鍵の URL が `http://` へリダイレクトする → curl が拒む（`--proto =https --proto-redir =https`。Task 2 の `test_curl_restricted_to_https`）。
4. 末尾に改行の無い `apt-sources.txt` → 最後の取得元を黙って落とさない（Task 1 のベクタと Task 2 の `test_last_line_without_newline`）。
5. upgrade の層での鍵の取り直しが失敗する（配信元の障害、鍵が HTML）→ `-b` が `ERROR:` と rc 1 で止まり、それまでの鍵と取得元のファイルを途中まで書き換えない（Task 2 の `test_fetch_failure_writes_nothing`・`test_garbage_key_rejected`）。

---

### Task 1: `validate-build-input.sh` に kind `apt-sources` を足す

**Files:**
- Modify: `validate-build-input.sh`
- Test: `test-build.sh`（`VBI_VECTORS` の表と、`run_validator_layer1()` の件数の assert〈200〜203 行付近〉）

**Interfaces:**
- Produces: `sh validate-build-input.sh apt-sources <infile> [outfile]` — rc 0 適合（outfile に正規化結果）、1 仕様外の行または名前の重複（outfile は変えない）、2 診断不能（既存の契約どおり）。正規化結果は 1 行 1 取得元で、欄を半角空白 1 つで区切った `<名前> <鍵の URL> <指紋>[,<指紋>...] <URI> <suite> <component>[ <component>...]`。**最後の行も改行で終える**（`packages` の既存の契約〈改行なしの入力は改行なしで出す〉は変えない）。

各欄の規則（ERE）: 名前 `[a-z0-9][a-z0-9-]{0,62}`、URL（鍵・URI 共通）`https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~%+/-]*)?`、指紋 `[0-9A-F]{40}(,[0-9A-F]{40})*`、suite `[A-Za-z0-9][A-Za-z0-9._/-]*`、component `[A-Za-z0-9][A-Za-z0-9._-]*`。コメントは `packages` と同じく行頭 `#` だけ（行内の `#` は拒否される）。

- [ ] **Step 1: 失敗する試験（ベクタ）を書く**

`VBI_VECTORS` に `apt-sources` の行を足す。注記は表の行に書かず、直前の `# …` のコメント行に書く。`F`＝`EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796`、`G`＝`35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3`、`L`＝`eb4c1bfd4f042f6dddccec917721f63bd38b4796` を実際の文字列で書く。少なくとも次を入れる:

- accept: `mozilla https://packages.mozilla.org/apt/repo-signing-key.gpg G https://packages.mozilla.org/apt mozilla main\n` → 同じ文字列
- accept（空白の正規化と CR）: `a\thttps://k.example/key.asc  F,G   https://r.example/deb/ stable main contrib\r\n` → `a https://k.example/key.asc F,G https://r.example/deb/ stable main contrib\n`
- accept（末尾に改行なし）: `a https://k.example/key F https://r.example stable main` → `a https://k.example/key F https://r.example stable main\n`
- exclude: `# comment\n`、`\n`
- reject: 鍵の URL が `http://`、URI が `http://`、指紋が `L`（小文字）、指紋が `F,`、component が無い、`[trusted=yes]` を含む、名前が `X`、名前が `../x`、URL に `?a=b`、suite が `-stable`、行末に `# note`、同じ名前の 2 行、`st\000able`

件数の assert は、既存の packages・requirements の数を変えず、総数と reject の数を足した分だけ直し、`apt-sources` の件数の assert を 1 本足す（数は表から数える）。

- [ ] **Step 2: 走らせて失敗を確かめる**

Run: `./test-build.sh --validator-only`
Expected: FAIL（`apt-sources` の全行〈未知の kind で rc 2〉と、件数の assert）

- [ ] **Step 3: 実装する**

kind の case に `apt-sources` を足す。正規化は `packages` と同じ sed に「連続する `[[:blank:]]` を 1 つの空白にする」を足し、出力の最後に改行が無ければ足す。照合は上の欄の規則を 1 行の ERE に組む。照合が通った後、**outfile を確定する前に**、第 1 欄の重複を中間ファイルで調べる（`cut -d' ' -f1 "$norm" > "$t/names"` → `sort "$t/names" > "$t/sorted"` → `uniq -d "$t/sorted" > "$t/dups"` と段ごとに rc を見る。パイプにしない〈既存の実装制約 9〜12〉）。重複があれば `error: <infile> で名前が重複しています: <名前>` と rc 1。冒頭の使い方のコメント・usage・未知の kind のメッセージに `apt-sources` を足す。

- [ ] **Step 4: 走らせて通ることを確かめる**

Run: `./test-build.sh --validator-only && ./lint.sh`
Expected: rc 0

- [ ] **Step 5: Commit**

```bash
git add validate-build-input.sh test-build.sh
git commit -m "feat: validate-build-input.sh に apt-sources の書式検査を足す（#273）"
```

### Task 2: 鍵の取得・照合・取得元の書き込み `install-apt-sources.sh`

**Files:**
- Create: `install-apt-sources.sh`（`#!/bin/sh`）
- Create: `tests/test_install_apt_sources.py`（unittest。`tests/test_copilot_bwrap_shim.py` と同じく、実物のスクリプトの固定パスを試験用の一時ディレクトリへ置換して実行する）
- Modify: `test-build.sh`（`run_launcher_tests()` の Python 試験の `check` の列〈1088 行付近〉に 1 行足す）
- Modify: `.c3c/packages.txt`（c3c 自身の開発用のコンテナに `gnupg` を足す。試験が実物の gpg を使うため）

**Interfaces:**
- Consumes: Task 1 の正規化結果のファイル。
- Produces: `sh install-apt-sources.sh <正規化済みのファイル>`
  - 空なら何もせず rc 0（gnupg も入れず、apt も gpg も呼ばない）。
  - 空でなければ、全行の鍵を取って照合し、**すべて通ってから** `KEYRING_DIR/c3c-<名前>.gpg`（root:root 0644、バイナリ）と `SOURCES_DIR/c3c-<名前>.list`（root:root 0644、中身 `deb [signed-by=KEYRING_DIR/c3c-<名前>.gpg] <URI> <suite> <component...>` の 1 行）を書く。
  - 失敗は rc 1 と `ERROR:` の行。固定の値はファイル冒頭の `readonly KEYRING_DIR=/etc/apt/keyrings`・`readonly SOURCES_DIR=/etc/apt/sources.list.d`・`readonly INSTALL_OWNER='root:root'`（環境変数で上書きできない。試験は文字列を置換する）。

- [ ] **Step 1: 失敗する試験を書く**

試験用の鍵は、試験ごとの一時の GNUPGHOME で `gpg --batch --passphrase '' --quick-gen-key <uid> ed25519 sign never` で作る。gpg が無ければ試験は **skip せずに失敗する**（CI の ubuntu-24.04 と c3c の開発用のコンテナ〈`.c3c/packages.txt` の gnupg〉で走る前提。skip にすると CI で黙って抜けるため）。`curl` と `gpg` と `apt-get` は PATH の先頭に置いた dummy で包む（呼ばれた引数を記録し、curl は URL ごとの fixture と rc の対応表に従う。gpg は記録してから実物の gpg を呼ぶ。apt-get は記録だけ）。試験:

- `test_empty_input_does_nothing`: 空 → rc 0、2 つのディレクトリが空、curl・gpg・apt-get の記録が無い。
- `test_single_key_match_writes_files`: 主鍵 1 本・指紋一致 → rc 0、`c3c-a.gpg` に `gpg --show-keys` で同じ 1 本の指紋、`c3c-a.list` の中身が期待どおり、mode 0644。
- `test_multi_primary_exact_set`: 主鍵 2 本の鍵束、指紋 2 つを逆順で宣言 → rc 0。
- `test_declared_subset_rejected`: 主鍵 2 本に 1 つだけ宣言 → rc 1、stderr に `指紋が一致しません`、何も書かない。
- `test_declared_superset_rejected`: 主鍵 1 本に 2 つ宣言 → rc 1、同上。
- `test_armored_and_binary_keys`: armor とバイナリの両方で rc 0、置いた鍵はどちらもバイナリで同じ主鍵の集合。
- `test_installed_key_has_only_declared_primaries`: 置いた `c3c-<名前>.gpg` の主鍵の集合が宣言と一致する（export し直した鍵を照合し直していること）。
- `test_garbage_key_rejected`: fixture が HTML → rc 1、stderr に `ERROR:`、何も書かない。
- `test_fetch_failure_writes_nothing`: 2 行のうち 2 行目の URL だけ curl が rc 22 → rc 1、stderr に `鍵を取得できません`、前もって置いた `c3c-a.*`（前回の内容）が 1 バイトも変わらない。
- `test_curl_restricted_to_https`: curl の記録に `--proto =https` と `--proto-redir =https` がある。
- `test_last_line_without_newline`: 改行で終わらない 1 行のファイル → rc 0、その取得元が書かれる。
- `test_refresh_overwrites_own_files`: 同じ入力で 2 回 → 2 回とも rc 0、内容が同じ、stderr に `INFO: a の鍵を照合して置きました` が 2 回とも出る。
- `test_installs_gnupg_only_when_missing`: PATH に gpg が無い設定で、apt-get の記録に `install -y --no-install-recommends gnupg` がある。gpg があるときは apt-get を呼ばない。

- [ ] **Step 2: 走らせて失敗を確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_install_apt_sources.py -v`
Expected: FAIL（スクリプトが無い）

- [ ] **Step 3: 実装する**

`set -eu`。流れ:
1. 空なら exit 0。
2. `gpg` が無ければ `apt-get update` と `apt-get install -y --no-install-recommends gnupg`（入れた gnupg は消さない）。
3. 一時ディレクトリ（`mktemp -d`）と、その下の一時の `GNUPGHOME` を作る。`trap` で `gpgconf --kill all`（GNUPGHOME を付けて）と一時ディレクトリの削除。
4. 各行を `while IFS=' ' read -r name keyurl fprs uri suite comps || [ -n "$name" ]` で読む。
   - `curl -fsSL --proto =https --proto-redir =https --tlsv1.2 --max-time 60 --max-filesize 1048576 -o <tmp>/<名前>.key <keyurl>`。失敗したら `ERROR: <名前> の鍵を取得できません（<keyurl>）` で exit 1。
   - 取得元ごとの空の GNUPGHOME に `gpg --batch --import <tmp>/<名前>.key`（armor もバイナリも同じ処理）。
   - 宣言した指紋ごとに `gpg --batch --export <指紋>…` で `<tmp>/<名前>.gpg` に書き出す。
   - 書き出したファイルと取得した元のファイルの両方に `gpg --show-keys --with-colons` をかける。`pub` の直後の `fpr` の第 10 欄だけを主鍵の指紋として集め、`sort -u` した集合を、宣言の `tr , '\n' | sort -u` と比べる。2 つとも一致しなければ `ERROR: <名前> の鍵の指紋が一致しません（宣言: … / 取得: …）` で exit 1。
   - gpg が失敗したら `|| { echo "ERROR: <名前> の鍵を読めません" >&2; exit 1; }` で握る。
5. **全行が通ってから**、`install -o root -g root -m 0644`（`INSTALL_OWNER` から作る）で 2 つのディレクトリへ置き、取得元ごとに `INFO: <名前> の鍵を照合して置きました` を標準エラー出力に出す（Task 5 の再ビルドの試験がこの行を見る）。
6. 最後に、置いた `.list` の数と入力の行数を比べ、違えば exit 1。

- [ ] **Step 4: 走らせて通ることを確かめる**

`test-build.sh` の `run_launcher_tests()` に `check "外部の APT 取得元の鍵の照合（指紋の集合・形式・失敗時に書かない・https だけ）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_install_apt_sources.py"` を足す。

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_install_apt_sources.py -v && ./lint.sh`
Expected: 全試験 OK、lint rc 0

- [ ] **Step 5: Commit**

```bash
git add install-apt-sources.sh tests/test_install_apt_sources.py test-build.sh .c3c/packages.txt
git commit -m "feat: 外部の APT 取得元の鍵を主鍵の指紋の集合で照合して置く install-apt-sources.sh（#273）"
```

### Task 3: 境界のファイルの照合 `check-boundary-files.sh`

**Files:**
- Create: `check-boundary-files.sh`（`#!/bin/sh`）
- Create: `tests/test_check_boundary_files.py`
- Modify: `test-build.sh`（`run_launcher_tests()` に `check` を 1 行）

**Interfaces:**
- Produces: `sh check-boundary-files.sh snapshot <記録のファイル> <パス>...` と `sh check-boundary-files.sh verify <記録のファイル> <パス>...`（パスはディレクトリかファイル）。記録は、各パス（ディレクトリならその下を `find -xdev` で）のディレクトリ・通常のファイル・symlink ごとに「パス、種類、uid:gid、mode、symlink の先、通常のファイルの sha256」を 1 行にして `LC_ALL=C sort` したもの。存在しないパスは「無い」と 1 行書く。verify は記録を作り直して比べ、違えば rc 1、`ERROR: upgrade の層で境界のファイルが変わりました` と差分の行。rc 2 は引数の誤り。改行を含むパス名は rc 1 で拒否する。

- [ ] **Step 1: 失敗する試験を書く**

`test_unchanged_passes`、`test_content_change_detected`、`test_mode_change_detected`、`test_added_file_detected`、`test_removed_file_detected`、`test_symlink_target_change_detected`、`test_missing_dir_recorded`（無いディレクトリが後で作られたら検出）、`test_single_file_path`、`test_bad_args_rc2`。どれも一時ディレクトリで、所有者は試験を走らせるユーザーのまま比べる。

- [ ] **Step 2: 走らせて失敗を確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_check_boundary_files.py -v`
Expected: FAIL

- [ ] **Step 3: 実装する**（`find <path> -xdev -printf` と `sha256sum`。中間ファイルで段ごとに rc を見る）。`run_launcher_tests()` に `check "upgrade の層の前後の境界のファイルの照合" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_check_boundary_files.py"` を足す。

- [ ] **Step 4: 走らせて通ることを確かめる**

Run: 上と同じ ＋ `./lint.sh`
Expected: OK、rc 0

- [ ] **Step 5: Commit**

```bash
git add check-boundary-files.sh tests/test_check_boundary_files.py test-build.sh
git commit -m "feat: upgrade の層の前後で境界のファイルを比べる check-boundary-files.sh（#273）"
```

### Task 4: ランチャーの配線（アセット・ステージング・ハッシュ・`--check`）

**Files:**
- Modify: `c3c`、`test-build.sh`、`tests/test_network_timeouts.py`、`tests/test_container_paths.py`（Global Constraints の一覧）
- Test: `tests/test_c3c_config.py`

**Interfaces:**
- Consumes: Task 1〜3 のファイル名。
- Produces: ビルドコンテキストに、`apt-sources.txt`（optional。プロジェクトに無ければ空のファイルを静かに作る。`allowed-ports.txt` と同じ扱い）と、`install-apt-sources.sh`・`check-boundary-files.sh`（fixed）が置かれる。3 つとも `ASSET_HASH` に入る。

この Task の commit では、まだイメージの挙動は変わらない（Dockerfile が新しいファイルを使うのは Task 5）。そのため README は Task 5 で更新する。

- [ ] **Step 1: 失敗する試験を書く**（`tests/test_c3c_config.py`）
- `apt-sources.txt` が無いプロジェクト: ステージ先に空の `apt-sources.txt` があり、起動・`--check` の出力に `apt-sources` を含む行が無い。
- ある: 中身がそのままステージされ、中身を変えると `ASSET_HASH` が変わる。
- `--check`: 仕様外の行があると `[WARN] apt-sources.txt に仕様外の行があります`、適合なら `[OK]   apt-sources.txt: 内容診断 OK`。
- fixed の 2 本がステージされ、片方を変えると `ASSET_HASH` が変わる。

- [ ] **Step 2: 走らせて失敗を確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_c3c_config.py -v`
Expected: 新しい試験が FAIL

- [ ] **Step 3: 実装する**
- `resolve_asset_source()`: fixed の列に `install-apt-sources.sh`・`check-boundary-files.sh`、optional の列に `apt-sources.txt`。
- `ASSET_HASH_TARGETS` に 3 つ。
- `stage_build_context()`: fixed のコピーのループに 2 本、optional のループ（`allowed-ports.txt` のもの）に `apt-sources.txt`。
- `--check` の内容診断: `packages.txt` 等のループ（無いと WARNING を出す）には入れない。ループの後に、「プロジェクトに `apt-sources.txt` があるときだけ `validate-build-input.sh apt-sources` を outfile なしで呼び、rc の解釈は既存の case と同じ」を足す。
- `test-build.sh` の `stage_common_context()` に 2 本の `cp` と `: > "$dest/apt-sources.txt"` を足す。`run_config_ro_launcher_tests()` の runner のコピーの一覧に 2 本を足す。
- `tests/test_network_timeouts.py` の fixed の一覧に 2 本、`tests/test_container_paths.py` の `CONTAINER_SIDE` に 2 本（コンテナの中で動くので、旧名の参照の検査の対象にする）。

- [ ] **Step 4: 走らせて通ることを確かめる**

Run: `./test-build.sh --launcher-only && ./lint.sh`
Expected: rc 0、FAIL 0

- [ ] **Step 5: Commit**

```bash
git add c3c test-build.sh tests/test_c3c_config.py tests/test_network_timeouts.py tests/test_container_paths.py
git commit -m "feat: apt-sources.txt と 2 本のスクリプトをビルドの入力に配線する（#273）"
```

### Task 5: `Dockerfile.claude` の層、実ビルドの試験、README

**Files:**
- Modify: `Dockerfile.claude`、`README.md`
- Test: `test-build.sh`（層 2 の静的検査 `run_validator_layer2()`、`--build-only` の範囲の検査、全体実行の陰性・陽性のビルド）

**Interfaces:**
- Consumes: Task 1〜4。

- [ ] **Step 1: 失敗する試験を書く**
- 層 2（`run_validator_layer2()`。CI で Dockerfile の配線を見ている唯一の層）に足す:
  - `sh /tmp/validate-build-input.sh apt-sources /tmp/apt-sources.txt /tmp/apt-sources.norm || exit 1;` がちょうど 1 回あり、`install-apt-sources.sh` の最初の呼び出しより前の同じ RUN にある。
  - `install-apt-sources.sh` の呼び出しが 2 回あり、どちらも引数が `/tmp/apt-sources.norm`（`.txt` でない）。
  - upgrade の RUN（`apt-get update --error-on=any` を含む論理行）に、`check-boundary-files.sh snapshot` が `apt-get update` より前、`check-boundary-files.sh verify` が upgrade より後にある。
  - 外部の取得元の RUN と upgrade の RUN で、`install-apt-sources.sh`・`check-boundary-files.sh` の失敗がビルドを止めること（RUN が `set -e;` で始まるか、各段が `&&` でつながり、`;` だけで後ろへ続いていない）。鍵の取り直しの失敗や照合の失敗が、後ろの段に握りつぶされないため。
- `--build-only` の範囲（3087 行の `finish_by_result` より前。既存のビルド `$IMAGE` を使う）に足す:
  - 陽性 2: `apt-sources.txt` が空のイメージに `/etc/apt/sources.list.d/c3c-*` と `/etc/apt/keyrings/c3c-*` が無く、`/tmp` に `apt-sources.*`・`install-apt-sources.sh`・`check-boundary-files.sh`・`c3c-boundary.state` が残っていない。
- 全体実行の範囲（3087 行より後。既存の「陰性1」「陽性1」の後に「apt-sources ビルド時検証テスト（#273）」の節）に足す:
  - 陰性 1: 指紋の 1 桁を変えた mozilla の行 → `check_fails ... "指紋が一致しません"`。
  - 陰性 2: URI が `http://` → `check_fails ... "仕様外の行があります"`。
  - 陰性 3（Review Focus 1）: `https://cli.github.com/packages` を GitHub の鍵の正しい指紋で宣言 → ビルドが止まる。`check_fails` の文字列は、実装時にこのビルドを 1 回走らせて apt が出す文言から取る（`Signed-By` を含む見込み。未確認）。指紋は実装時に `curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | gpg --show-keys --with-colons` で取った主鍵の値。
  - 陽性 1: mozilla の正しい行（spec の例）、`packages.txt` は空 → ビルドが成功する。`/etc/apt/keyrings/c3c-mozilla.gpg` と `/etc/apt/sources.list.d/c3c-mozilla.list` が root:root 0644。`podman run --rm --user 0 <image> sh -c 'apt-get update --error-on=any && apt-cache policy'` の出力に `packages.mozilla.org` がある（最終のイメージは `/var/lib/apt/lists` を消しているので、試験のコンテナの中で update してから見る）。
  - 陽性 1 の続き（キャッシュした再ビルドでの鍵の取り直し）: 同じ文脈を `--build-arg CACHEBUST=<別の値>` だけ変えて作り直す。出力に、外部の取得元の RUN がキャッシュを使ったこと（podman の `Using cache` の行がその RUN の STEP にある）と、upgrade の RUN の中で `INFO: mozilla の鍵を照合して置きました` が出たことを確かめる。取り直しの失敗でビルドが止まることは、単体の試験（`test_fetch_failure_writes_nothing` の rc 1）と層 2 の `set -e`・`&&` の検査で押さえる。

- [ ] **Step 2: 走らせて失敗を確かめる**

Run: `./test-build.sh --validator-only`（層 2）と `./test-build.sh`（全体。陽性 2 と全体の節）
Expected: 新しい項目が FAIL

- [ ] **Step 3: 実装する**
- `COPY validate-build-input.sh /tmp/` の直後に、`COPY apt-sources.txt /tmp/apt-sources.txt` と `COPY install-apt-sources.sh check-boundary-files.sh /tmp/` を置く。続けて `RUN set -e; sh /tmp/validate-build-input.sh apt-sources /tmp/apt-sources.txt /tmp/apt-sources.norm || exit 1; sh /tmp/install-apt-sources.sh /tmp/apt-sources.norm` を置く。その下の `packages.txt` の RUN は変えない。コメントに、照合するのは宣言した取得元の鍵までで、パッケージが自分で足す取得元（Google Chrome の例）は照合の外であることを書く。
- upgrade の RUN を次の順にする（照合は外の取得元が無いときも常に行う）:
  1. `echo cachebust`
  2. `sh /tmp/install-apt-sources.sh /tmp/apt-sources.norm`（鍵の取り直し）
  3. `sh /tmp/check-boundary-files.sh snapshot /tmp/c3c-boundary.state /usr/local/bin /usr/local/libexec/c3c /etc/c3c /etc/sudoers.d/node-firewall /etc/codex /etc/claude-code`
     - `/etc/sudoers.d` は丸ごと渡さない。sudo のパッケージの conffile（`README`）は、手を加えていなければ `--force-confold` でも upgrade で置き換わり、誤検知になるため。
     - Debian のパッケージは `/usr/local` に置かないので、`/usr/local/bin` は丸ごと渡してよい。
  4. 既存の `apt-get update --error-on=any` と upgrade
  5. `sh /tmp/check-boundary-files.sh verify`（3 と同じ引数）
  6. `rm -f /tmp/apt-sources.txt /tmp/apt-sources.norm /tmp/install-apt-sources.sh /tmp/check-boundary-files.sh /tmp/c3c-boundary.state`
  7. 既存の `apt-get clean`

  コメントに、照合は正直な壊れ方だけを捕まえ、悪意のある差し替えは防げないこと（spec の「境界のファイルの照合」）を書く。
- 既存の `http://` の 2 か所の検査は変えない（`c3c-*.list` も `find /etc/apt` の対象に入る）。
- README（同じ commit）:
  - 「利用側プロジェクトの設定」: ファイルの一覧に `apt-sources.txt`、その説明（書式、spec の例 3 行、指紋の取り方〈`curl -fsSL <鍵の URL> | gpg --show-keys --with-colons` の `pub` の直後の `fpr`〉、照合するのは宣言した取得元の鍵までで、パッケージが自分で足す取得元と鍵〈Google Chrome の `google-chrome.sources`〉は照合の外で消さないこと、`debian:sid` などで Debian 側にも同名のパッケージがあるときの優先度は扱わないこと、Google Chrome は amd64 だけであること。arm64 での挙動は、実装者が arm64 の環境を使えれば確かめて書き、使えなければ Task 8 の報告に `not run` と理由を書いて README には「確かめていない」と書く）。
  - 「アーキテクチャ」: ファイルの一覧に 2 本と、`Dockerfile.claude` の説明に外部の取得元の層。
  - 「イメージの変更」: upgrade の層で鍵を取り直すこと、境界のファイルを前後で比べること、鍵の配信元が止まっているときは `-b` が止まること。
  - 「セキュリティモデル」の残余: 「apt 側は設定済みリポジトリ内のパッケージに限られるため同じ経路は無い」を、外部の取得元を足すとその提供元にビルド時の root を（初回と `-b` のたびの upgrade で）渡すこと、境界のファイルの照合は正直な壊れ方だけを捕まえることに書き直す。

- [ ] **Step 4: 走らせて通ることを確かめる**

Run: `./test-build.sh --validator-only && ./test-build.sh && ./lint.sh`
Expected: FAIL 0、rc 0（既存の項目を含む）

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.claude README.md test-build.sh
git commit -m "feat: 外部の APT 取得元の層と、upgrade の層の境界のファイルの照合（#273）"
```

### Task 6: 開発者向けの文書

**Files:**
- Modify: `docs/development-invariants.md`
  - `validate-build-input.sh` の kind の追加。
  - `install-apt-sources.sh` の不変条件: 全行の照合の後に書く、空なら何もしない、固定パスを環境で上書きできない、import → export → 照合し直してから置く。
  - `check-boundary-files.sh` の照合を upgrade の RUN の中で前後に置くこと。
  - 外部の取得元の層を `packages.txt` の層より前に置く順序。
- Modify: `README.md` の「変更後の確認」節: 新しい 2 本の試験、層 2 の検査、`--build-only` の陽性 2、全体実行の陰性・陽性。
- `SECURITY-CLAIMS.md` は変えない（ビルド時の root の残余を述べた箇所が無いため。2026-11-15 に確認）。

- [ ] **Step 1: 書く**
- [ ] **Step 2: 確かめる** — Run: `./lint.sh`（Markdown のアンカーの検査を含む）。Expected: rc 0、警告ゼロ。
- [ ] **Step 3: Commit** — `git add docs/development-invariants.md README.md && git commit -m "docs: apt-sources の不変条件と変更後の確認（#273）"`

### Task 7: 実機の確かめ（findsummits の probe）

**Files:** なし（一時のプロジェクトのディレクトリだけ。findsummits のリポジトリは変えない）

- [ ] **Step 1:** 一時ディレクトリ `P` を作り、次をそろえる。
  - findsummits の checkout（c3c と同じ親ディレクトリの `findsummits`）から、`git -C <findsummits> archive ef22a04 docs/decisions/research/browser-automation-probe | tar -x -C P` で probe を取り出す。
  - `P/.c3c/` に、findsummits の `.c3c/` の `base-image.txt`・`node-version.txt`・`packages.txt`・`allowed-domains.txt` を写す。
  - `P/.c3c/apt-sources.txt` に spec の例 3 行を書く。
  - `P/.c3c/packages.txt` の末尾に `google-chrome-stable`・`brave-browser`・`firefox` を足す。
- [ ] **Step 2:** 持ち主に、端末で `./c3c claude -b P` を実行し、ビルドが終わって Claude が起動したらすぐ終えるよう頼む（`-b` だけのモードが無く、対話の起動になるため。`!` の行は対話の入力を受けない）。
- [ ] **Step 3:** そのイメージ（`podman images` で `<P の名前>-<8 桁>_claude-auth-workspace`）に対して、compose と同じ権限の設定で probe の 3 コマンドを走らせる。

  ```bash
  podman run --rm --userns=keep-id --user 1000:1000 --cap-add NET_ADMIN,NET_RAW \
    --sysctl net.ipv6.conf.all.disable_ipv6=1 --sysctl net.ipv6.conf.default.disable_ipv6=1 \
    --network none -v "P:/probe:ro,Z" -w /probe --entrypoint /usr/bin/setpriv <image> \
    --ambient-caps=-all --inh-caps=-all /usr/bin/tini -- sh -c '
      node docs/decisions/research/browser-automation-probe/cdp_probe.js google-chrome "$(mktemp -d)"; echo rc=$?
      node docs/decisions/research/browser-automation-probe/cdp_probe.js brave-browser "$(mktemp -d)"; echo rc=$?
      node docs/decisions/research/browser-automation-probe/bidi_probe.js /usr/lib/firefox/firefox "$(mktemp -d)"; echo rc=$?
      ps -eo pid,pgid,cmd'
  ```

  Expected: 3 つとも `rc=0`、出力の `checks` の 9 つがすべて `true`、最後の `ps` にブラウザが無い。
- [ ] **Step 4:** `./c3c --check P` が `[OK]   apt-sources.txt: 内容診断 OK` を出す。
- [ ] **Step 5:** 対象を確かめてから `./c3c --clean P` でイメージを消し、`P` を消す。
- ファイアウォールを通した本物の起動での確かめは、findsummits の側に頼む（Task 8 の PR の後に #273 へコメント）。

### Task 8: 完了と PR

- [ ] **Step 1:** **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion。`./lint.sh`・`./test-build.sh`（全体）・Task 7 の結果を、実行したものと `not run`（理由付き）に分けて書き出す。
- [ ] **Step 2:** 実装完了時（PR 前）の二重レビュー（区分が境界のため）。Claude は `claude-review` skill、Codex は `codex-review` skill（`gpt-6.1-sol`）、Claude → Codex の順。並走はグローバル `AGENTS.md` の「Copilot の並走」の公開の経路（`--diff <base の SHA>`、未 push なら `--unpushed <base の SHA>`）。
- [ ] **Step 3:** **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review。Critical・Important を直し、確認限定巡を終える。台帳（vault `knowledge/モデル別の実績.md`）と `review-data` の表に初回の結果を書く。
- [ ] **Step 4:** **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → **REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch（push して PR を作る選択肢。push は持ち主に確かめてから）。
  - PR 本文: #273 への参照、判定、未対応の Minor、`not run` の理由、SemVer の minor の候補（タグは持ち主の承認の後、`release-tag` skill）、末尾の署名 `— <実効モデル名> (c3c)`。
  - レビューの全文は PR コメントに投稿する。
- [ ] **Step 5:** PR 後の二重レビューのために handover を書く（`handover` skill）。対象の SHA、検証のログ、未対応の事項を入れ、作成に関わっていない Claude の対話セッションへ渡す。#273 に、findsummits 側で `-b` と probe を頼むコメントを書く。

---

## 計画レビューの記録

- Self-Review: `/etc/sudoers.d` を丸ごと照合すると sudo の conffile で誤検知になる点（`node-firewall` だけに絞った）、陰性 3 の apt の文言が未確認な点、README の「パッケージが自分で足す取得元」の記載漏れ、Task 7 の走らせ方を修正
- 版: `plan-initial.md` （非公開の記録に保存）
- Claude（claude-opus-5-5。modelUsage には claude-fable-5-2 も載った、session `c86ed147-4dd8-4e6d-b17a-cefb13948f14`、所要 476 秒）: 修正後に渡せる。生の出力 （非公開の記録に保存）
  - I1 新しいビルドの試験は `--build-only` では走らない → 採用（陽性 2 を 3087 行より前に、陰性と陽性 1 は全体実行に。Run を合わせた）
  - I2 層 2 の静的検査が無い → 採用（Task 5 Step 1）
  - I3 新しい unittest が走る入口に無い → 採用（Task 2・3 で `run_launcher_tests()` に登録）
  - I4 gpg が無い環境 → 採用（skip せず失敗にし、`.c3c/packages.txt` に gnupg）
  - I5 照合した鍵と置く鍵が違う → 採用（import → 宣言した指紋だけ export → 照合し直し）
  - I6 改行なしの最後の行が抜ける → 採用（正規化で改行を足す、`|| [ -n "$name" ]`、`.list` の数の照合、試験 2 つ）
  - I7 アセットの一覧を持つ試験 2 本の漏れ → 採用（Global Constraints と Task 4 の Files・`git add`）
  - I8 Task 7 が実行できない → 採用（3 コマンドを逐語、マウント、ビルドは持ち主の端末）
  - I9 README を同じ commit で → 採用（README を Task 5 の commit に移した）
  - M1 件数の assert と Expected → 採用
  - M2 ベクタ表の注記と占位 → 採用
  - M3 重複の検査の位置とパイプ → 採用
  - M4 gpg の失敗の握り → 採用
  - M5 dummy の作り → 採用（URL ごとの rc、gpg と apt-get も記録）
  - M6 shellcheck → 採用（Global Constraints。`INSTALL_OWNER` は引数の文字列でなく `root:root` の値にした）
  - M7 gpg-agent・keyboxd の残り → 採用（`gpgconf --kill all`）
  - M8 spec との差・ドリフトの WARNING → 採用（Global Constraints に明記）
  - M9 SECURITY-CLAIMS.md → 採用（変えないと確定）
  - M10 署名・台帳・review-data → 採用（Task 8）
- Codex（gpt-6.1-sol、所要 144 秒）: 修正後に渡せる。生の出力 （非公開の記録に保存）
  - I1 `--build-only` で届かない → 採用（Claude の I1 と同じ）
  - I2 `apt-cache policy` が lists の削除と食い違う → 採用（試験のコンテナで update してから見る）
  - I3 unittest の登録 → 採用（Claude の I3 と同じ）
  - I4 バイナリの鍵に import が無い → 採用（Claude の I5 と同じ直し）
  - I5 probe の手順が確定しない → 採用（Claude の I8 と同じ直し）
  - M1 README を同じ commit で → 採用（Claude の I9 と同じ）
  - M2 PR 後の引き継ぎ → 採用（Task 8 Step 5）
- 確認限定巡 1: Codex（I1〜I5、所要 37 秒）→ すべて直った、実装に渡せる。生の出力 （非公開の記録に保存）
- 確認限定巡 1: Claude（I1〜I9、所要 19 秒）→ すべて直った、実装に渡せる。生の出力 （非公開の記録に保存）
- fusion（並走、正式外）: 修正後に渡せる。依頼した段階 max・実際の段階 max（pattern single、ruleId `solo_astra_xhigh_rule_24`、gpt-6-astra だけ）、起動し直しなし、189.7 クレジット、所要 431 秒。承認の後に、初回の版（plan-initial）を公開の経路（`--unpushed c0f2680`、commit d440cc6）で送った。生の出力 `pairing-runs/20261115-c3c-plan-273-fusion/final.md`。Sol と材料が違った点: 計画の写しの記録節の一時パスを「非公開の記録に保存」に置き換えた（初回の版には記録節が無く、実際の置き換えは 0 件）、グローバル `AGENTS.md` と `.claude/AGENTS.md` は名前だけ（スキルの表の 2 列は貼った）
  - C1 バイナリの鍵の正規化で鍵が空になる → 採用（承認前に Sol I4・Claude I5 で直し済み。深刻度は Critical を暫定で採る）
  - I1 改行なしの最後の行 → 採用（Claude I6 で直し済み）
  - I2 `--build-only` → 採用（直し済み）、I3 `apt-cache policy` → 採用（直し済み）、I4 件数の assert → 採用（Claude M1 で直し済み）、I5 unittest の登録 → 採用（直し済み）、I7 重複の検査のパイプ → 採用（Claude M3 で直し済み）、I8 probe の手順 → 採用（直し済み）、I9 README の commit → 採用（直し済み）
  - I6 upgrade の層への配線を確かめる陰性の試験が無い → 一部採用（層 2 に、2 本の失敗がビルドを止める形〈`set -e` か `&&`〉の静的な検査を足した。確認限定巡 2 の Sol の指摘を受け、キャッシュした再ビルドで upgrade の層が鍵を取り直す陽性の試験も足した〈Task 5 陽性 1 の続き〉。採らないのは、upgrade の中で境界のファイルを変えると止まるビルドの試験だけ〈境界のファイルを upgrade の中で変える試験用のパッケージと取得元が要り、費用に見合わない。照合そのものは `check-boundary-files.sh` の単体の試験、配線は層 2 で押さえる〉。ビルドの中での取り直しの失敗は、ネットワークを途中で止める仕掛けが要るので、単体の試験〈rc 1〉と層 2 の検査で押さえる）
  - M1 較正は `entrypoint.sh` と `git-askpass.sh` で → 採用（Global Constraints）
  - M2 arm64 を最初から not run と決めている → 採用（使えれば確かめ、使えなければ理由付きで not run）
- 確認限定巡 2: Codex（fusion の C1・I6、所要 26 秒）→ C1 は直った。I6 は採った範囲は入ったが、キャッシュした再ビルドでの取り直しを省く理由が足りない → 陽性の試験を足した。生の出力 （非公開の記録に保存）
- 確認限定巡 3: Codex（fusion の I6 のキャッシュした再ビルドの点、所要 44 秒）→ 直った、実装に渡せる。生の出力 （非公開の記録に保存）

区分: 境界（ビルドの入力の検証〈`validate-build-input.sh`〉、外部の鍵の照合、境界のファイルの照合というセキュリティ境界に触れるため）
推奨実装: Opus（c3c の Claude Code 面の既定は Sonnet だが、グローバル指示の「セキュリティ境界を含むときは Opus」に当たる。判定順の 1〜5 には当たらない。実行方法は executing-plans を推す。Task 1〜5 が前のタスクのファイル名と出力に順に依存し、8 タスクで 1 セッションに収まるため）
