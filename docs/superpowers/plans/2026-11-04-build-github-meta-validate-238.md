# ビルド時の GitHub meta のスナップショットを init と同じ規則で検査する 実装計画（#238）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** イメージを作るとき、GitHub meta のスナップショットを `init-firewall.sh` の `load_github_ranges()`（PR #236）と同じ規則で検査し、崩れたものを焼き込まない。取ったばかりの応答が検査に通らなければ、前回分 → 別プロジェクトの分（新しい順）を、それぞれ検査して最初に通ったものを使い、どれも通らなければビルドを止める（#238）。

**Architecture:** 検査は `validate-build-input.sh` の新しい kind `github-meta` に 1 本だけ書く（#34 の「このスクリプト単独が正本」の形）。`c3c` の `stage_build_context()`、`test-build.sh` の `stage_common_context()`、`Dockerfile.claude` の RUN は、今の `jq -e '.web and .api and .git'` をこの呼び出しに置き換える。起動時の `init-firewall.sh` は変えない。2 つの実装（検証器と `load_github_ranges()`）の結果が同じ入力でそろうことを、新しいテスト `tests/test-github-meta-agreement.sh` が確かめる。

**Tech Stack:** POSIX sh（`validate-build-input.sh`）、jq（1.6 以降）、bash（`c3c`・`test-build.sh`・テスト）、Python unittest（`tests/test_network_timeouts.py`）。

**Spec:** Issue #238 の本文（2026-11-04）と、持ち主が会話で承認した要約（2026-11-04）。別の設計文書は作らない。要約の要点: 規則は PR #236 の起動時の検査と同じ（単一の JSON オブジェクト、`web`・`api`・`git` が文字列の配列、IPv4 の値はどれも範囲内〈0〜255、/0〜/32、2 桁以上で先頭 0 は不可〉、IPv4 の値が 1 件以上）。切り替え先も検査し、崩れていれば次の候補へ。置き場所は `validate-build-input.sh`。`init-firewall.sh` は変えない。範囲外は #237 と `--check` の診断の追加。

## Global Constraints

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に 1 回）

- 作業ブランチは `fix/238-build-meta-validate`（`main` の e5264be から作る。Task 0）。
- `docs/development-invariants.md` の「`validate-build-input.sh`」の項を守る: `#!/bin/sh`・POSIX sh の範囲（ビルド時はコンテナ内の dash、ホストの sh でも走る）、終了コード契約 0（適合）/ 1（不適合）/ 2（診断不能）、`resolve_asset_source()` では `fixed` のまま。既存の kind（`packages`・`requirements`）の挙動と `--validator-only` の層 1 の件数（PASS=82）は変えない。
- `init-firewall.sh` は 1 バイトも変えない（`git diff --exit-code e5264be -- init-firewall.sh`）。
- 検証器が受け入れる入力は、`load_github_ranges()` が受け入れる入力の部分集合にする（検証器を init より緩くしない。厳しい側への差は、テストに理由付きで固定したものだけ）。init はコマンド置換で文字列の中の NUL を落として読むので、検証器は NUL を含む文字列を 1 つでも見つけたら拒否する（NUL を落とすと別の値になる値を、検証器が「IPv4 でない」として読み飛ばして通すと、init より緩くなるため。計画レビューで両者が反例を示した）。
- `stage_build_context()` と `stage_common_context()` に新しい関数を足さず、本体の中で完結させる（`tests/test_network_timeouts.py` が関数の本体だけを抜き出して走らせるため。PR #236 で関数を足してテストが落ちた前例）。
- 取得の回数と上限（`curl` の引数、`timeout` の 90 秒、再試行 2 回）は変えない。ライブ取得の場所を増やさない（`docs/development-invariants.md` の「GitHub meta スナップショット」）。
- 検証器は `jq -s` で全体を 1 回読む。jq の終了コードは 0 → 0、1・2・5 → 1（入力の誤り。jq 1.6 は解析の失敗が 2、1.7 以降は 5）、それ以外（3 = 式の誤りなど、127 = jq が無い）→ 2 にする。
- 新しい文言は下の Task に逐語で書いたものにする。既存の文言は、Task 3 で書き換えると書いたもの以外は変えない。
- 文書とコメントは日本語（README「表記」節）。挙動を変えたら README の該当節を同じ commit で直す（root `AGENTS.md`）。
- ファイルを編集したら、そのターン内で `./lint.sh` を実行し、rc 0・警告ゼロを確かめる（コンテナ内では Compose 検証が警告付きでスキップされる。その場合は Compose 検証を `not run` と報告する）。
- テストのコマンドは、どれもリポジトリのルート（`/workspace` か worktree のルート）で実行する。

## Review Focus

- 今の弱い検査を通るが規則に反する取得結果（`{"web":[1],"api":[],"git":[]}`）→ 焼き込まずに切り替える。Task 3 の `test_weak_response_falls_back_to_sibling_in_both_callers`。
- このプロジェクトの前回分が崩れている → 飛ばして別プロジェクトの分を使い、前回分を上書きする。Task 3 の `test_broken_own_snapshot_is_skipped_for_sibling`。
- いちばん新しい別プロジェクトの分が崩れている → その次に新しいものを使う。Task 3 の `test_broken_newest_sibling_is_skipped_for_older`。
- 中身の正しい 2 つのオブジェクトを連結したファイル → 検証器も init も止める（`length == 1` の検査だけで落ちる入力。PR #236 の未対応の Minor「meta-concatenated が `length == 1` を固定していない」も、検証器側でここで固定する）。Task 1・Task 2 の `concat-both-valid`。
- ホストに jq が無い → 検証器は rc 2。ビルドは切り替え先もすべて同じ理由で通らず止まり、検証器の標準エラー（`error: jq がありません`）がそのまま見える（黙って焼き込まない。原因が読める）。検証器の rc は Task 1 の `no-jq` で固定する。ビルド側は標準エラーを捨てないこと（Task 3 Step 4・5）で原因を残す。

---

### Task 0: ブランチを作り、承認された計画を公開の置き場へ置く

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees（並行するセッションが無ければ作業ツリーで `git switch -c` してよい）

- [ ] **Step 1: ブランチを作る**

  Run: `git status --short; git switch -c fix/238-build-meta-validate e5264be`
  Expected: `git status --short` の出力が空、ブランチが作られる。

- [ ] **Step 2: `--launcher-only` の PASS の基準値を控える**

  Run: `bash -o pipefail -c './test-build.sh --launcher-only 2>&1 | tail -2'; echo "rc=$?"`
  Expected: `FAIL=0`、`rc=0`。表示された PASS の値を控える（Task 3 Step 10 で使う）。

- [ ] **Step 3: 計画を置く**

  計画ファイルを `docs/superpowers/plans/2026-11-04-build-github-meta-validate-238.md` へ写す。記録節の一時パスは `<scratchpad>/` に置き換える（前例: `docs/superpowers/plans/2026-11-04-github-meta-early-stop-228.md` の記録節）。記録節に、ホストのパス・private のリポジトリや Issue の名前・保守者個人の PAT の設定が残っていないことを、#228 の計画の Task 0 Step 2 と同じ grep で確かめる。ただし対象は記録節だけにする（`sed -n '/^## 計画レビューの記録/,$p' <写し> | grep …`。説明文の行に一致しないため）。
  Expected: grep の出力なし（rc 1）。

  ```bash
  git add docs/superpowers/plans/2026-11-04-build-github-meta-validate-238.md
  git commit -m "docs: ビルド時の GitHub meta を init と同じ規則で検査する計画（#238）"
  ```

### Task 1: 検証器に kind `github-meta` を足す

**Files:**
- Modify: `validate-build-input.sh`（冒頭の使い方のコメント、kind の `case`、`github-meta` の分岐）
- Create: `tests/test-github-meta-agreement.sh`（この Task では検証器の部分だけ。init との照合は Task 2）
- Modify: `test-build.sh`（`run_launcher_tests` の中、`tests/test-firewall-init-trace.sh` の `check` の次の行に 1 行）

**Interfaces:**
- Produces: `sh validate-build-input.sh github-meta <infile>` — 引数はちょうど 2 つ（3 つ目を渡すと rc 2）。rc 0 = 規則に合う、rc 1 = 合わない（標準エラーに `error: <infile> は GitHub meta のスナップショットとして不正です` の 1 行。ただしファイルに生の NUL バイトがあるときは、先に走る既存の検査の文言 `error: <infile> に NUL バイトが含まれています（拒否）` で rc 1）、rc 2 = 診断不能（既存の契約と同じ: 引数の誤り、infile を読めない、一時ディレクトリを作れない、jq が無い・式の誤り）。標準出力には何も書かない。

- [ ] **Step 1: 失敗するテストを書く**

  `tests/test-github-meta-agreement.sh`（`#!/bin/bash`、`set -euo pipefail`、`LC_ALL=C`）。入力の表を 1 か所に置き、検証器の rc を照合する。表の 1 行は `名前|検証器の期待 rc|init の期待 rc|ファイルの中身`。中身は書いてある文字のまま `printf '%s\n'` で 1 つのファイルに書く（エスケープを展開しない。下の `\n`・`\u0000` は JSON の文字列のエスケープとしてファイルに入る）。Task 2 で init の列を使う。この Task では検証器の列だけを照合する。

  表:

  | 名前 | 検証器 | init | JSON |
  | --- | --- | --- | --- |
  | `good` | 0 | 0 | `{"web":["192.30.252.0/22","2a0a:a440::/29"],"api":["140.82.112.0/20"],"git":[]}` |
  | `bounds` | 0 | 0 | `{"web":["255.255.255.255/32","0.0.0.0/0"],"api":[],"git":[]}` |
  | `no-prefix` | 0 | 0 | `{"web":["0.0.0.0"],"api":[],"git":[]}` |
  | `extra-key` | 0 | 0 | `{"web":["1.2.3.4/8"],"api":[],"git":[],"hooks":5}` |
  | `duplicates` | 0 | 0 | `{"web":["1.2.3.4/8"],"api":["1.2.3.4/8"],"git":[]}` |
  | `empty` | 1 | 1 | （空。`printf '%s\n'` で書くので改行 1 つだけのファイルになる） |
  | `not-json` | 1 | 1 | `not json` |
  | `trailing-garbage` | 1 | 1 | `{"web":["1.2.3.4/8"],"api":[],"git":[]} x` |
  | `array-wrapped` | 1 | 1 | `[{"web":["1.2.3.4/8"],"api":[],"git":[]}]` |
  | `concat-both-valid` | 1 | 1 | `{"web":["1.2.3.4/8"],"api":[],"git":[]} {"web":["5.6.7.8/32"],"api":[],"git":[]}` |
  | `missing-key` | 1 | 1 | `{"web":["1.2.3.4/8"],"api":[]}` |
  | `null-key` | 1 | 1 | `{"web":["1.2.3.4/8"],"api":null,"git":[]}` |
  | `not-array` | 1 | 1 | `{"web":"1.2.3.4/8","api":[],"git":[]}` |
  | `non-string` | 1 | 1 | `{"web":[1],"api":["1.2.3.4/8"],"git":[]}` |
  | `octet-256` | 1 | 1 | `{"web":["256.0.0.0/8","1.2.3.4/8"],"api":[],"git":[]}` |
  | `prefix-33` | 1 | 1 | `{"web":["1.1.1.1/33","1.2.3.4/8"],"api":[],"git":[]}` |
  | `leading-zero-octet` | 1 | 1 | `{"web":["010.1.1.1/8"],"api":[],"git":[]}` |
  | `double-zero-octet` | 1 | 1 | `{"web":["00.1.1.1/8"],"api":[],"git":[]}` |
  | `leading-zero-prefix` | 1 | 1 | `{"web":["1.2.3.4/08"],"api":[],"git":[]}` |
  | `no-ipv4` | 1 | 1 | `{"web":[],"api":[],"git":[]}` |
  | `ipv6-only` | 1 | 1 | `{"web":["2a0a:a440::/29"],"api":[],"git":[]}` |
  | `spaced-only` | 1 | 1 | `{"web":[" 1.2.3.4/8"],"api":[],"git":[]}` |
  | `newline-hides-bad` | 1 | 1 | `{"web":["1.2.3.4/8\n300.0.0.0/8"],"api":[],"git":[]}`（JSON の文字列の中の改行。init は行に分けて 2 行目で止まる） |
  | `nul-in-string` | 1 | 0 | `{"web":["1.2.\u00003.4/8"],"api":[],"git":[]}`（JSON の NUL。init はコマンド置換が NUL を落として `1.2.3.4/8` と読むので通る〈承認の後に計画者と argon が実測で rc 0 を確かめた〉。検証器は厳しい側にずれる。表のこの行のコメントにそう書く） |
  | `nul-hides-bad-prefix` | 1 | 1 | `{"web":["1.2.3.4\u0000/40","5.6.7.8/32"],"api":[],"git":[]}`（init は NUL を落として `1.2.3.4/40` と読み止まる。NUL を含む文字列を拒否しない検証器は、ここで init より緩くなる） |
  | `nul-hides-bad-octet` | 1 | 1 | `{"web":["1.2.3.4/8","256.0.\u00000.0/8"],"api":[],"git":[]}`（init は `256.0.0.0/8` と読み止まる） |

  表のほかに、検証器の契約を 3 つ照合する（init の列は使わない）:
  - `outfile-given`: `sh validate-build-input.sh github-meta <good のファイル> <別のパス>` → rc 2、別のパスが作られない。
  - `missing-file`: 無いパス → rc 2。
  - `no-jq`: `PATH` を、`sh`・`mktemp`・`rm`・`wc`・`tr`・`cat`・`sed`・`grep`・`dirname` への symlink だけを置いた一時ディレクトリにして、`good` のファイルで起動する → rc 2。

  失敗は `FAIL: <名前>: 検証器 rc=<実際> (期待 <期待>)` を標準エラーに出して数え、最後に失敗があれば rc 1、無ければ `OK: <件数> 件` を出して rc 0。

- [ ] **Step 2: 失敗することを確かめる**

  Run: `bash tests/test-github-meta-agreement.sh`
  Expected: rc 1。kind `github-meta` が無いので、どの行も `検証器 rc=2` で FAIL（期待が 2 の契約の 3 つを除く）。

- [ ] **Step 3: `validate-build-input.sh` に kind `github-meta` を足す**

  - 冒頭のコメントの使い方を `validate-build-input.sh <kind> <infile> [outfile]` のまま、kind の行に `github-meta`（outfile を取らない。GitHub meta のスナップショットの検査、#238）を足す。終了コードの説明は共通のまま。2 行目の説明（`packages.txt / requirements.txt のビルド時インジェクション対策検証`）に GitHub meta のスナップショットの検査を足し、「責務は正規化と照合のみ」「3者が同じスクリプトを呼ぶ」の段落に、`github-meta` は照合だけで正規化しないこと、`c3c` の `stage_build_context()`・`test-build.sh` の `stage_common_context()`・`Dockerfile.claude` の RUN が呼ぶことを足す。
  - kind の `case` に `github-meta)` を足す。未知の kind の文言を `error: 未知の kind です: $VBI_KIND（packages・requirements・github-meta を想定）` に替える。
  - `github-meta` のとき、引数が 3 つなら `error: github-meta は outfile を取りません` で rc 2。
  - infile の読める検査と NUL バイトの検査（既存）の後で、`github-meta` なら正規化の `sed` に入らず、次の式で `jq -se "$式" "$VBI_INFILE" >/dev/null` を 1 回走らせ（`-e` が無いと結果の `false` が rc 0 になる。jq 自身の標準エラーは捨ててよい）、上の Global Constraints の対応で rc を返す（jq が無いときは `command -v jq` で先に見て `error: jq がありません` で rc 2）。式は init の規則を jq に写したもの（`split("\n")` は init がコマンド置換の出力を行に分けるのと合わせるため）:

    ```jq
    def ipv4: test("^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}(/[0-9]{1,2})?$");
    def part($max): (length == 1 or (startswith("0") | not)) and (tonumber <= $max);
    length == 1 and (.[0] | type == "object")
    and ([.[0].web, .[0].api, .[0].git] | all(type == "array" and all(.[]; type == "string" and (explode | all(. != 0)))))
    and ([.[0].web[], .[0].api[], .[0].git[] | split("\n")[] | select(ipv4)]
         | length >= 1
           and all(split("/") as $p
                   | ($p[0] | split(".") | all(part(255)))
                     and ($p[1] == null or ($p[1] | part(32)))))
    ```

  - rc 1 のときの文言は Interfaces の 1 行。

- [ ] **Step 4: 通ることを確かめる**

  Run: `bash -o pipefail -c 'bash tests/test-github-meta-agreement.sh && ./test-build.sh --validator-only 2>&1 | tail -3'; echo "rc=$?"`
  Expected: `OK: 29 件`（表 26 と契約 3）、`--validator-only` は `PASS=82  FAIL=0`（既存の件数のまま）、最後に `rc=0`。

- [ ] **Step 5: `test-build.sh` から呼ぶ**

  `run_launcher_tests`（`check "ファイアウォール初期化のルールの組み立て（固定入力）" ...` の次の行）に 1 行足す:
  `check "GitHub meta の検査（validate-build-input.sh と init-firewall.sh の判定の一致）" bash "${SCRIPT_DIR}/tests/test-github-meta-agreement.sh"`

- [ ] **Step 6: lint と commit**

  Run: `./lint.sh`
  Expected: rc 0。

  ```bash
  git add validate-build-input.sh tests/test-github-meta-agreement.sh test-build.sh
  git commit -m "feat: validate-build-input.sh に GitHub meta のスナップショットの検査を足す（#238）"
  ```

### Task 2: 同じ入力で init-firewall.sh の判定と照合する

**Files:**
- Modify: `tests/test-github-meta-agreement.sh`

**Interfaces:**
- Consumes: Task 1 の表と `validate-build-input.sh github-meta`。`init-firewall.sh` の `readonly IPV4_CIDR_RE=...` の行と `load_github_ranges()` の本体（変えない）。

- [ ] **Step 1: init の列を照合するテストを足す**

  `init-firewall.sh` から `readonly IPV4_CIDR_RE=` の行と `load_github_ranges() {` から最初の `^}` までを抜き出し、`GITHUB_META_SNAPSHOT` をその行のファイルに設定した `bash -c`（`set -euo pipefail`）の中で読み込んで `load_github_ranges` を呼ぶ。rc を表の init の列と照合し、外れたら `FAIL: <名前>: init rc=<実際> (期待 <期待>)`。抜き出しが空なら（関数名が変わった）`FAIL: init-firewall.sh から load_github_ranges を抜き出せません` で rc 1。

- [ ] **Step 2: 通ることを確かめる（init は変えていないので、最初から通るはず）**

  Run: `bash tests/test-github-meta-agreement.sh`
  Expected: `OK: 55 件`（検証器 26・init 26・契約 3）。

  **REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（init の rc が表と食い違ったら、止まらずにその場で原因を調べる。`nul-in-string` の init の期待だけは計画者の推測なので、実際の rc に合わせてよい。ほかの行が食い違ったら、表か init の読み方の誤りなので、原因が分かるまで直さずに調べ、分からなければ持ち主に報告する）

- [ ] **Step 3: 照合が効くことを確かめる**

  表の `bounds` の検証器の期待を一時的に 1 に替えて走らせ、`FAIL: bounds: 検証器 rc=0 (期待 1)` が出て rc 1 になることを見てから戻す（commit しない）。次に、作業ツリーで `validate-build-input.sh` の `part(32)` を `part(31)` に替えて走らせ、`bounds` が FAIL になることを見てから戻す。

- [ ] **Step 4: lint と commit**

  Run: `./lint.sh && git diff --exit-code e5264be -- init-firewall.sh`
  Expected: どちらも rc 0。

  ```bash
  git add tests/test-github-meta-agreement.sh
  git commit -m "test: GitHub meta の検査が validate-build-input.sh と init-firewall.sh で一致することを確かめる（#238）"
  ```

### Task 3: ビルドの 3 か所を検証器に置き換え、切り替え先も検査する

**Files:**
- Modify: `c3c`（`stage_build_context()` の GitHub meta の部分とその前のコメント）
- Modify: `test-build.sh`（`stage_common_context()` の GitHub meta の部分。層 2 の静的検査に 2 項目）
- Modify: `Dockerfile.claude`（`COPY github-meta.json` の次の RUN）
- Modify: `tests/test_network_timeouts.py`（応答の種類 `weak` と、テスト 4 つ）
- Modify: 偽の curl が IPv4 の無い meta を返す 4 か所 — `test-build.sh`（`-b` の meta 取得を通信なしで通す偽の curl、#213）、`tests/test_codex_launch.py`、`tests/test_c3c_launch.py`、`tests/test_project_images.py`
- Modify: `README.md`（「GitHub meta スナップショット」節）、`docs/development-invariants.md`（「`validate-build-input.sh`」の項）

**Interfaces:**
- Consumes: Task 1 の `sh <dir>/validate-build-input.sh github-meta <file>`。`c3c` は `"$BUILD_CONTEXT_DIR/validate-build-input.sh"`（同じ関数の前半でステージ済み）、`test-build.sh` は `"$dest/validate-build-input.sh"` を呼ぶ。

- [ ] **Step 1: 失敗するテストを書く（`tests/test_network_timeouts.py`）**

  - `Handler` の応答に `weak` を足す: 200 で `{"web":[1],"api":[],"git":[]}` を返す（今の `.web and .api and .git` を通る）。
  - `run_meta` の `cache` に加えて、崩れたファイルや mtime を置けるよう、テストの中で `self.run_dir / '.build-context' / <名前> / 'github-meta.json'` を直接書く（`os.utime` で mtime を決める）。
  - `test_weak_response_falls_back_to_sibling_in_both_callers`: `kind` が `launcher` と `build` の両方で、`weak` の応答と正しい別プロジェクトの分 → rc 0、`WARNING:` が出る、ステージのファイルが `META + b'\n'`。
  - `test_broken_own_snapshot_is_skipped_for_sibling`（`launcher`）: `invalid` の応答、このプロジェクトの前回分が `{"web":[1],"api":[],"git":[]}`、別プロジェクトの分が正しい → rc 0、標準エラーに `は検証に通らないため使いません` があり、ステージのファイルが `META + b'\n'`（前回分が上書きされる）。
  - `test_broken_newest_sibling_is_skipped_for_older`（`launcher` と `build`）: `invalid` の応答、別プロジェクト `newer`（mtime は `time.time() + 100`、ほかのどの候補より新しい）が崩れていて `older`（mtime は `time.time() - 100`）が正しい → rc 0、ステージのファイルが `older` の中身。subTest の各回の頭で `self.run_dir / '.build-context' / 'current' / 'github-meta.json'` を消す（前の回の `cp` が置いた正しいファイルが候補に入り、崩れた候補を飛ばす処理を通らずに当たってしまうため）。
  - `test_all_snapshots_broken_fails`（`launcher` は rc 1、`build` は rc 77）: `invalid` の応答、前回分と別プロジェクトの分がどれも崩れている → 標準エラーに `ERROR:`。`launcher` ではステージの前回分のバイトが変わらない。

- [ ] **Step 2: 失敗することを確かめる**

  Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_network_timeouts.py -v`
  Expected: 新しい 4 つが FAIL（今は弱い応答をそのまま焼き込み、切り替え先を検査しない）。既存のテストは通る。

- [ ] **Step 3: 偽の curl の固定値を替える**

  Files に挙げた 4 か所の `'{"web":[],"api":[],"git":[]}'` を `'{"web":["192.0.2.0/24"],"api":[],"git":[]}'` に替える（IPv4 が 0 件のままだと、新しい検査で取得が失敗扱いになり、切り替え先の無い checkout〈CI〉で `stage_build_context()` が止まる。手元では `.build-context/*` の本物のスナップショットが拾われて通ってしまう）。

  Run: `grep -rnF '{"web":[],"api":[],"git":[]}' tests test-build.sh`
  Expected: 出力なし（rc 1）。

- [ ] **Step 4: `c3c` の `stage_build_context()` を直す**

  - 取得の subshell の `jq -e '.web and .api and .git' "$gh_meta" >/dev/null 2>&1` を `sh "$BUILD_CONTEXT_DIR/validate-build-input.sh" github-meta "$gh_meta"` に替える（標準エラーは捨てない。検証器の `error:` の 1 行が、取得の失敗の WARNING の前に出て原因になる）。
  - 失敗の後の切り替えを、候補の列を順に検査する形にする。候補は (1) `"$BUILD_CONTEXT_DIR/github-meta.json"`（あれば）、(2) `ls -t "$RUN_DIR"/.build-context/*/github-meta.json` の出力の順で、(1) と同じファイル（`[[ "$candidate" -ef "$BUILD_CONTEXT_DIR/github-meta.json" ]]`）を除いたもの。候補ごとに同じ検証器を呼び（標準エラーは捨てない）、通らなければ `WARNING: GitHub meta スナップショット $candidate は検証に通らないため使いません` を出して次へ。最初に通った候補が (1) なら今の文言 `WARNING: 前回ステージングした GitHub meta スナップショットを再利用します`、(2) なら新しい文言 `WARNING: 別プロジェクトの GitHub meta スナップショットを再利用します（$candidate）` を出して `cp` する（今の (2) の文言「このプロジェクトのスナップショットもありません」は、(1) があって崩れていたときに事実と違うので替える。照合しているテストは無い〈計画者が grep で確かめた〉）。どれも通らなければ `ERROR: GitHub meta を取得できず、検証に通る過去のスナップショットもありません。上記の原因を確認して再試行してください` で `exit 1`。
  - 新しい関数を作らない（Global Constraints）。(2) の候補は `mapfile -t candidates < <(ls -t "$RUN_DIR"/.build-context/*/github-meta.json 2>/dev/null)` で配列に読み、`for` で回す（`ls … | while` にしない。パイプの右側はサブシェルなので、中の `exit 1` と「見つかった」の印が関数に伝わらない）。パスは `PROJECT_NAME` と固定のファイル名で改行を含まないので、今の `shellcheck disable=SC2012` の理由のコメントを残す。
  - 関数の前のコメントの (1)(2) の説明に「どれも validate-build-input.sh の github-meta の検査に通るものだけを使う」を足す。

- [ ] **Step 5: `test-build.sh` の `stage_common_context()` を直す**

  `c3c` と同じく、取得の検査を `sh "$dest/validate-build-input.sh" github-meta "$gh_meta"`（標準エラーは捨てない）にし、切り替え先は `mapfile -t candidates < <(ls -t "${SCRIPT_DIR}"/.build-context/*/github-meta.json 2>/dev/null)` の順に検査して最初に通ったものを使う（`$dest` は一時ディレクトリなので (1) は無い）。飛ばしたときの文言は `c3c` と同じ。使うときの文言は今の `WARNING: GitHub meta の取得に失敗しました。$sibling を再利用します` のまま（変数名は合わせてよい）。どれも通らなければ `ERROR: GitHub meta の取得に失敗し、検証に通る既存スナップショットもありません（通信・未認証 API のレート制限・応答形式を確認してください）` で `return 77`。

- [ ] **Step 6: `Dockerfile.claude` を直す**

  `COPY github-meta.json /etc/c3c/github-meta.json` の次の RUN を次にする（`/tmp/validate-build-input.sh` は 95 行目の COPY で同じステージに置いてある）:

  ```dockerfile
  RUN set -e; \
      chmod 644 /etc/c3c/github-meta.json; \
      sh /tmp/validate-build-input.sh github-meta /etc/c3c/github-meta.json || exit 1
  ```

  その前のコメントに「c3c と同じ validate-build-input.sh の github-meta の検査をここでも行う（#238）」を足す。

- [ ] **Step 7: 層 2 の静的検査に 2 項目を足す（`test-build.sh` の `run_validator_layer2()`）**

  `packages validator呼び出しのヒット数` の検査の近くに、同じ形で 2 つ:
  - `sh /tmp/validate-build-input.sh github-meta /etc/c3c/github-meta.json` を含み `|| exit 1` を含む論理行が 1 つ（`grep -F 'sh /tmp/validate-build-input.sh github-meta /etc/c3c/github-meta.json' "$logical" | grep -cF '|| exit 1'`。packages の検査は `'|| exit 1;'` とセミコロンまで見るが、新しい RUN は `|| exit 1` で論理行が終わるので、セミコロンを付けない。`[FAIL] layer2: github-meta validator呼び出しのヒット数=$hits (期待1)`）。
  - `jq -e '.web and .api and .git'` の論理行が 0（`[FAIL] layer2: github-meta の弱い検査が残っている(ヒット数=$hits)`）。

- [ ] **Step 8: 通ることを確かめる**

  Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_network_timeouts.py -v && grep -rnF "jq -e '.web and .api and .git'" c3c test-build.sh Dockerfile.claude`
  Expected: unittest は全部 OK（既存と新しい 4 つ）。grep の出力は `test-build.sh` の層 2 の検査の 1 行（Step 7 で足した、弱い検査が残っていないかを数える行）だけで、`c3c`・`Dockerfile.claude`・`stage_common_context()` の行は出ない。

  層 2 は通常実行の流れでしか走らない（`--validator-only`・`--launcher-only`・`--build-only` では走らない）ので、関数だけを抜き出して走らせる:

  Run: `bash -c 'SCRIPT_DIR=$PWD; PASS=0; FAIL=0; log() { echo "$*"; }; eval "$(sed -n "/^run_validator_layer2() {/,/^}/p" test-build.sh)"; run_validator_layer2; echo "PASS=$PASS FAIL=$FAIL"'`
  Expected: `FAIL=0`。続けて、作業ツリーの `Dockerfile.claude` の新しい RUN から `|| exit 1` を一時的に消して同じコマンドを走らせ、`[FAIL] layer2: github-meta validator呼び出しのヒット数=0 (期待1)` が出て `FAIL=1` になることを見てから、`|| exit 1` を戻す（commit しない。戻した後に `git diff -- Dockerfile.claude` を見て、差分が Step 6 の変更だけであることを確かめる）。

- [ ] **Step 9: README と不変条件の文書を直す**

  - README「GitHub meta スナップショット」節: 「取得に失敗した場合は (1) …、(2) …を警告付きで再利用し」を「取得か検証に失敗した場合は (1) …、(2) …のうち、検証に通るものを警告付きで再利用し」にする。検証の規則は、#236 で足した文の規則と同じであること、取得したものと再利用するものの両方を `validate-build-input.sh` が確かめること、`Dockerfile.claude` もビルドの中で同じ検査を行うことを 1 文で足す。
  - README で `validate-build-input.sh` の役割を説明している箇所（`grep -n 'validate-build-input' README.md` で探す。e5264be の時点では「利用側プロジェクトの設定」の近く）に、GitHub meta のスナップショットも検査することを 1 句足す。
  - `docs/development-invariants.md` の「`validate-build-input.sh`」の項の、POSIX sh を保つ理由の行（「`--check`・`test-build.sh` はホストの sh で走る」）に、`c3c` の staging もホストの sh で呼ぶことを足す。
  - `docs/development-invariants.md` の「`validate-build-input.sh`」の項の最初の行を「`packages.txt`/`requirements.txt` と GitHub meta のスナップショット（kind `github-meta`、#238）の検証はこのスクリプト単独が正本」にし、次の 1 行を足す: 「`init-firewall.sh` の `load_github_ranges()` は起動時の関門として同じ規則を自分で持つ（イメージの中で検証器を呼ばない）。2 つの判定の一致は `tests/test-github-meta-agreement.sh` が確かめ、検証器は init より緩くしない」。

- [ ] **Step 10: 全体の検証と commit**

  Run: `bash -o pipefail -c './lint.sh && ./test-build.sh --validator-only 2>&1 | tail -2 && ./test-build.sh --launcher-only 2>&1 | tail -2'; echo "rc=$?"`
  Expected: lint rc 0、`--validator-only` は `PASS=82  FAIL=0`、`--launcher-only` は `FAIL=0` で PASS は Task 0 Step 2 で控えた値より 1 多い（Task 1 Step 5 の check が 1 つ増えるため）、最後に `rc=0`。

  ```bash
  git add c3c test-build.sh Dockerfile.claude tests/test_network_timeouts.py tests/test_codex_launch.py tests/test_c3c_launch.py tests/test_project_images.py README.md docs/development-invariants.md
  git commit -m "fix: ビルド時の GitHub meta を init と同じ規則で検査し、切り替え先も検査する（#238）"
  ```

### Task 4: 実ビルドで確かめ、PR 前のレビューを経て PR を作る

- [ ] **Step 1: 実ビルド（ホスト）**

  Run（ホスト。コンテナの中では podman が無いので not run とし、Step 3 の runtime.yml で代える）: `bash -o pipefail -c './test-build.sh --build-only 2>&1 | tail -3'; echo "rc=$?"`
  Expected: `FAIL=0`、`rc=0`。ホストで `./test-build.sh` の全体も走らせられれば行う（Expected: `FAIL=0`）。走らせなければ not run と理由を書く（層 2 は Task 3 Step 8 で抜き出して走らせてある）。

- [ ] **Step 2: PR 前の二重レビュー（区分が境界のため。push の前に行う）**

  **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review（結果を受け取ったとき）

  Claude（`claude-review` skill、headless）→ Codex（`codex-review` skill、`gpt-6.1-sol`）の順に起動する（グローバル `AGENTS.md` の既定の順）。ホストの Claude のセッションのときだけ、Sol の直後に argon の並走（公開の経路。まだ push していないので `--unpushed <base の SHA>`。base は `git fetch` の後の `git merge-base HEAD origin/main`）。Critical・Important を直し、確認限定巡を終える。

- [ ] **Step 3: push と実コンテナの確認**

  持ち主の確認を取ってからブランチを push し、`gh workflow run runtime.yml --ref fix/238-build-meta-validate` を走らせ、結果が success であることを確かめる。

- [ ] **Step 4: PR を作る**

  **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch（PR を作る選択肢を名前で選ぶ）

  PR 本文に、変えた挙動、範囲外（#237、`--check` の診断、`init-firewall.sh` は変えていない）、テストの結果（not run を含む）、PR 前のレビューの判定と未対応の Minor を書く。両レビュアーの全文を PR コメントに載せる。`Closes #238`。署名 `— <実際のモデル名> (c3c)`。SemVer: README「バージョニング」節で判定し、タグを提案するなら番号と根拠を PR 本文と持ち主への報告に書く（崩れた GitHub meta でビルドが止まるか切り替わるのは既定の挙動の変化に当たりうる。タグは自動で作らない）。

## 計画レビューの記録

- Self-Review: 表のエスケープの書き方（`printf '%b'` と二重のバックスラッシュ）を「書いたままの文字を `printf '%s\n'` で書く」に改め、`trailing-newline` の行を除いて件数を直した。advisor の指摘で、並走の検査に当たる字面（非公開のリポジトリ名、ホストのパス）を計画から外し、候補のループの形（`mapfile` と `-ef`）、jq の `-se`、検証器の標準エラーを捨てないこと、(2) の文言を中立にすることを足した
- 版: `plan-initial.md` `<scratchpad>/tasks/b3wbez4mg.output`
- Claude（claude-opus-5-5、session `f28a41c5-b48b-45e1-bd7c-c760b9078c9d`、所要 348 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/btwcnl8u9.output`
  - C1 偽の curl 4 か所（`test-build.sh`・`tests/test_codex_launch.py`・`tests/test_c3c_launch.py`・`tests/test_project_images.py`）が IPv4 の無い meta を返し、新しい検査で CI が落ちる → 採用（Task 3 Step 3 と Files に追加。計画者が grep で 4 か所を確かめた）
  - I1 文字列の中の NUL で検証器が init より緩くなる（Codex C1 と同じ） → 採用（深刻度は Codex の Critical を採る。NUL を含む文字列を拒否する式に替え、表に 2 行足した）
  - I2 `test_broken_newest_sibling_is_skipped_for_older` の build の回が、前の回の `cp` で崩れた候補に届かない → 採用（各回の頭で消す、mtime を前後に固定）
  - I3 層 2 の新しい検査を走らせる手順が無い、`|| exit 1;` のセミコロン（Codex I2 と同じ） → 採用（Task 3 Step 7 にセミコロン無しを逐語で、Step 8 に層 2 だけを抜き出して走らせる手順と、壊して FAIL を見る手順）
  - M1 検証器の冒頭の説明・README の説明・不変条件の POSIX sh の理由 → 採用
  - M2 生の NUL バイトのときの rc 1 の文言 → 採用（Interfaces に例外を書いた）
  - M3 `--launcher-only` の PASS の基準値を控える Step が無い → 採用（Task 0 Step 2）
  - M4 Task 2 Step 2 に systematic-debugging → 採用
  - M5 push と PR 前のレビューの順 → 採用（Task 4 を、レビュー → push と runtime.yml → PR の順にした）
  - M6 SemVer の判断 → 採用（Task 4 Step 4 に 1 行）
- Codex（gpt-6.1-sol、所要 179 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bo8mhi64e.output`
  - C1 NUL を含む値と正常値の混在で、検証器が init より緩くなる（反例を jq 1.8.2 と bash で確かめた） → 採用（Claude I1 と同じ）
  - I1 `| tail` の検証コマンドが失敗の終了コードを隠す → 採用（`bash -o pipefail -c '…'; echo "rc=$?"` に替えた）
  - I2 層 2 の新しい検査を必ず走らせる経路が無い（Claude I3 と同じ） → 採用
  - M1 argon の並走は「ホストの Claude のセッション」に限る → 採用
- 確認限定巡 1: Codex（C1・I1・I2、所要 35 秒）→ どれも直った、実装に渡せる。生の出力 `<scratchpad>/tasks/bom1tr9id.output`
- 確認限定巡 1: Claude（C1・I1・I2・I3、所要 25 秒）→ どれも直った、実装に渡せる。生の出力 `<scratchpad>/tasks/bn9tm20vq.output`
- argon（並走、正式外）: 承認の後に `plan-initial.md` の版で起動した（公開の経路、`-c e5264be`）。修正後に渡せる、34.1 クレジット、所要 345 秒。生の出力はホストの並走の出力ディレクトリ（`20261104-c3c-plan-238-argon`）。Important 2・Minor 1 は、どれも Sol と Claude が挙げて承認前に反映したものと同じ（I1 NUL の穴〈Sol C1・Claude I1〉、I2 層 2 が走らない〈Sol I2・Claude I3〉、M1 Task 4 の REQUIRED SUB-SKILL の位置〈承認前に Step 4 へ移した〉）。argon だけが出した Critical・Important は無いので、Sol の確認限定巡は行わない。`nul-in-string` の init の rc が 0 になることを argon も実測した（計画者も承認後に実測して一致）

区分: 境界（ビルドの関門〈崩れた GitHub meta を焼き込まない検査〉と、不変条件のある `c3c`・`Dockerfile.claude`・`validate-build-input.sh` を変える。エグレスの許可リストの入力の検査に当たる）
推奨実装: Opus（セキュリティ境界〈ファイアウォールの許可リストの入力の検査〉を含むので、グローバル指示の Opus を推す条件に当たる。Sonnet にしない理由は、検証器と init の規則のずれを防ぐ判断と、POSIX sh と jq の版の差の扱いが実装中に残るため。判定順の 1〜5 には当たらない）
実装: Opus（持ち主指定、推奨どおり。新しいセッションで実装する。2026-11-04）
実行方法: executing-plans（Task 1〜3 が同じ検証器とテストを順に積み上げる直列の作業で、1 セッションに収まるため。2026-11-04、実装のセッションで承認）
